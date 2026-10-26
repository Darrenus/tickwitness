"""Audited controlled-intervention responses, without counterexample verdicts.

Each channel is ordered by its own recorded ordinal. The presentation order
below does not establish the earliest event across different callback channels.
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import cast

from tickwitness.domain.assumptions.derivation import DerivedReplayView, derive_replay_view
from tickwitness.domain.evidence.protocol_evaluation import ProtocolEvaluation
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    RunReceipt,
    canonical,
    digest,
    load_run_receipt,
    parse,
)
from tickwitness.domain.evidence.scenario_records import (
    ScenarioEvaluation,
    ScenarioRunReceipt,
    build_scenario_intent,
    load_scenario_run_receipt,
)
from tickwitness.domain.replay.comparison import ReplayComparison
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult, load_replay_result
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    load_executable_protocol,
)

_CHANNELS = ("input_trace", "decision_trace", "order_trace", "fill_trace", "account_trace")
_SECTIONS = (*_CHANNELS, "execution_status", "completeness")
_REPORT_LIMIT = 512 * 1024
_PROJECTION_ID = "coupled_stress_business_projection_v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _equal(left: object, right: object, message: str) -> None:
    _require(canonical({"value": left}) == canonical({"value": right}), message)


def _decimal(value: Fraction) -> str:
    """Format a terminating exact decimal without Decimal context rounding."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    _require(denominator == 1, "Comparison amount must have a terminating decimal")
    places = max(twos, fives)
    scaled = value.numerator * 2 ** (places - twos) * 5 ** (places - fives)
    if places == 0:
        return str(scaled)
    digits = str(abs(scaled)).zfill(places + 1)
    rendered = digits[:-places] + "." + digits[-places:]
    rendered = rendered.rstrip("0").rstrip(".")
    return ("-" if scaled < 0 else "") + rendered


def _pointer_key(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _difference(
    pointer: str,
    left: object,
    right: object,
    *,
    left_present: bool = True,
    right_present: bool = True,
) -> dict[str, object]:
    return {
        "json_pointer": pointer,
        "left_present": left_present,
        "right_present": right_present,
        "left_value": left,
        "right_value": right,
    }


def _first(left: object, right: object, pointer: str) -> dict[str, object] | None:
    if type(left) is not type(right):
        return _difference(pointer, left, right)
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(left.keys() | right.keys()):
            path = pointer + "/" + _pointer_key(key)
            if key not in left:
                return _difference(path, None, right[key], left_present=False)
            if key not in right:
                return _difference(path, left[key], None, right_present=False)
            found = _first(left[key], right[key], path)
            if found is not None:
                return found
        return None
    if isinstance(left, list) and isinstance(right, list):
        for index, (a, b) in enumerate(zip(left, right, strict=False)):
            found = _first(a, b, f"{pointer}/{index}")
            if found is not None:
                return found
        common = min(len(left), len(right))
        if len(left) < len(right):
            return _difference(f"{pointer}/{common}", None, right[common], left_present=False)
        if len(right) < len(left):
            return _difference(f"{pointer}/{common}", left[common], None, right_present=False)
        return None
    return None if left == right else _difference(pointer, left, right)


def _raw_value(document: dict[str, object], pointer: str, present: bool) -> object:
    if not present:
        return None
    value: object = document
    for token in pointer.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(key)]
        else:
            value = cast("dict[str, object]", value)[key]
    return value


def _trace_ref(document: dict[str, object], channel: str, index: int) -> dict[str, object] | None:
    rows = cast("list[dict[str, object]]", document[channel])
    if index >= len(rows):
        return None
    row = rows[index]
    return {
        "channel": channel,
        "ordinal": row["ordinal"],
        "kind": row["kind"],
        "native_time_ns": row["native_time_ns"],
        "source_ref": row["source_ref"],
    }


def _section_differences(
    left: dict[str, object],
    right: dict[str, object],
    raw_left: dict[str, object],
    raw_right: dict[str, object],
) -> dict[str, object]:
    differences: dict[str, object] = {}
    for section in _SECTIONS:
        found = _first(left[section], right[section], "/" + section)
        if found is not None:
            pointer = cast("str", found["json_pointer"])
            found["section"] = section
            found["left_raw_value"] = _raw_value(
                raw_left, pointer, cast("bool", found["left_present"])
            )
            found["right_raw_value"] = _raw_value(
                raw_right, pointer, cast("bool", found["right_present"])
            )
            found["left_trace_ref"] = None
            found["right_trace_ref"] = None
            if section in _CHANNELS:
                index = int(pointer.split("/")[2])
                found["left_trace_ref"] = _trace_ref(raw_left, section, index)
                found["right_trace_ref"] = _trace_ref(raw_right, section, index)
        differences[section] = found
    return {
        "first_divergence": next((item for item in differences.values() if item is not None), None),
        "per_channel_first": differences,
    }


def _order_id(document: dict[str, object]) -> str:
    decisions = cast("list[dict[str, object]]", document["decision_trace"])
    submissions = [
        cast("dict[str, object]", row["fields"])["order_id"]
        for row in decisions
        if cast("dict[str, object]", row["fields"]).get("action") == "submit"
    ]
    _require(len(submissions) == 1 and isinstance(submissions[0], str), "One submit ID required")
    return cast("str", submissions[0])


def _map_order(fields: dict[str, object], order_id: str) -> None:
    if fields.get("order_id") == order_id:
        fields["order_id"] = "order-0"


def _business_projection(document: dict[str, object]) -> dict[str, object]:
    # Canonical round-trip makes this a detached tree; source evidence is retained.
    output = parse(canonical(document), limit=16 * 1024 * 1024)
    order_id = _order_id(output)
    for channel in _CHANNELS:
        for row in cast("list[dict[str, object]]", output[channel]):
            row.pop("native_time_ns", None)
            fields = cast("dict[str, object]", row["fields"])
            if channel == "input_trace":
                for key in ("receive_time_ns", "native_ts_event_ns", "native_ts_init_ns"):
                    fields.pop(key, None)
            if channel in ("decision_trace", "order_trace", "fill_trace"):
                _map_order(fields, order_id)
            if channel in ("order_trace", "fill_trace"):
                fields.pop("native_event_ts_ns", None)
                fields.pop("native_init_ts_ns", None)
            if channel == "fill_trace":
                fields.pop("native_trade_id", None)
            if (
                channel == "order_trace"
                and row["kind"] == "OrderCancelRejected"
                and fields.get("reason") == f"ClientOrderId('{order_id}') not found"
            ):
                fields["reason"] = "ClientOrderId('order-0') not found"
            if channel == "account_trace":
                for order in cast("list[dict[str, object]]", fields.get("orders", [])):
                    _map_order(order, order_id)
    completeness = cast("dict[str, object]", output["completeness"])
    for key in ("open_orders", "pending_commands"):
        for order in cast("list[dict[str, object]]", completeness[key]):
            _map_order(order, order_id)
    return {section: output[section] for section in _SECTIONS}


def compare_scenario_traces(baseline: ReplayResult, scenario: ReplayResult) -> dict[str, object]:
    """Compare structural traces only; this function does not audit financial evidence."""
    _require(
        isinstance(baseline, ReplayResult) and isinstance(scenario, ReplayResult),
        "Trace comparison requires validated results",
    )
    left, right = baseline.document, scenario.document
    raw = _section_differences(left, right, left, right)
    business = _section_differences(
        _business_projection(left), _business_projection(right), left, right
    )
    return {
        "raw": raw,
        "business": business,
        "raw_trace_changed": raw["first_divergence"] is not None,
        "business_trace_changed": business["first_divergence"] is not None,
        "comparison_order": list(_SECTIONS),
        "within_channel_order": "recorded_ordinal_then_sorted_json_keys_v1",
        "global_earliest_claimed": False,
        "projection_policy": {
            "id": _PROJECTION_ID,
            "excluded_paths": [
                "/<trace>/*/native_time_ns",
                "/input_trace/*/fields/receive_time_ns",
                "/input_trace/*/fields/native_ts_event_ns",
                "/input_trace/*/fields/native_ts_init_ns",
                "/order_trace/*/fields/native_event_ts_ns",
                "/order_trace/*/fields/native_init_ts_ns",
                "/fill_trace/*/fields/native_event_ts_ns",
                "/fill_trace/*/fields/native_init_ts_ns",
                "/fill_trace/*/fields/native_trade_id",
            ],
            "order_id_mapping": "exact_submit_order_id_at_known_order_fields_to_order-0",
            "cancel_reason_mapping": "exact_OrderCancelRejected_ClientOrderId_not_found_template",
            "source_event_time_and_payload_preserved": True,
            "raw_values_and_trace_references_retained": True,
            "unknown_fields_preserved": True,
        },
    }


def _numeric(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    reason = (
        "baseline_not_eligible"
        if left["valuation_status"] != "valued"
        else "scenario_not_eligible"
        if right["valuation_status"] != "valued"
        else None
    )
    if reason is None:
        left_mark = dict(cast("dict[str, object]", left["mark"]))
        right_mark = dict(cast("dict[str, object]", right["mark"]))
        left_mark.pop("native_time_ns")
        right_mark.pop("native_time_ns")
        if canonical(left_mark) != canonical(right_mark):
            reason = "mark_definition_changed"
        elif canonical(cast("dict[str, object]", left["fee_model_verification"])) != canonical(
            cast("dict[str, object]", right["fee_model_verification"])
        ):
            reason = "fee_definition_changed"
    left_value = (
        cast("dict[str, str]", left["valuation"])["net_marked_pnl"]
        if left["valuation_status"] == "valued"
        else None
    )
    right_value = (
        cast("dict[str, str]", right["valuation"])["net_marked_pnl"]
        if right["valuation_status"] == "valued"
        else None
    )
    return {
        "status": "comparable" if reason is None else "not_comparable",
        "reason": reason,
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "baseline_value": left_value,
        "scenario_value": right_value,
        "delta": _decimal(Fraction(right_value) - Fraction(left_value))
        if reason is None and right_value is not None and left_value is not None
        else None,
        "delta_direction": "scenario_minus_baseline",
        "baseline_ineligibility_reason": left["ineligibility_reason"],
        "scenario_ineligibility_reason": right["ineligibility_reason"],
    }


def _reservation(document: dict[str, object], protocol: ExecutableProtocol) -> AttemptReservation:
    raw = canonical(cast("dict[str, object]", document["attempt"]))
    reservation = AttemptReservation(digest(raw), raw)
    budget = cast("dict[str, int]", protocol.document["budget"])
    _require(
        reservation.protocol_id == protocol.protocol_id
        and reservation.attempt_index <= budget["max_attempts"]
        and reservation.document["max_wall_seconds"] == budget["max_wall_seconds"],
        "Comparison attempt differs from the frozen protocol budget",
    )
    return reservation


@dataclass(frozen=True, slots=True)
class ScenarioComparison:
    protocol: ExecutableProtocol
    source_input: ReplayInput
    view: DerivedReplayView
    baseline_receipt: RunReceipt
    scenario_receipt: ScenarioRunReceipt
    baseline_result: ReplayResult
    scenario_result: ReplayResult
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        _require(
            isinstance(self.protocol, ExecutableProtocol)
            and isinstance(self.source_input, ReplayInput)
            and isinstance(self.view, DerivedReplayView)
            and isinstance(self.baseline_receipt, RunReceipt)
            and isinstance(self.scenario_receipt, ScenarioRunReceipt)
            and isinstance(self.baseline_result, ReplayResult)
            and isinstance(self.scenario_result, ReplayResult),
            "Scenario comparison requires immutable protocol, view, receipts and results",
        )
        protocol = load_executable_protocol(self.protocol.canonical_bytes)
        view = derive_replay_view(self.view.validated)
        _require(self.protocol == protocol, "Protocol identity mismatch")
        _equal(self.view.canonical_bytes.hex(), view.canonical_bytes.hex(), "View mismatch")
        _require(self.view.replay_input == view.replay_input, "Derived input mismatch")
        _require(view.validated.replay_input == self.source_input, "Source input mismatch")
        _require(view.validated.protocol == protocol, "View belongs to a different protocol")
        baseline = load_run_receipt(self.baseline_receipt.canonical_bytes)
        scenario = load_scenario_run_receipt(self.scenario_receipt.canonical_bytes)
        left = load_replay_result(self.baseline_result.canonical_bytes)
        right = load_replay_result(self.scenario_result.canonical_bytes)
        _require(baseline.run_id == self.baseline_receipt.run_id, "Baseline run identity mismatch")
        _require(scenario.run_id == self.scenario_receipt.run_id, "Scenario run identity mismatch")
        left_evaluation = ProtocolEvaluation(protocol, self.source_input, left)
        right_evaluation = ScenarioEvaluation(view, right)
        base_doc, scenario_doc = baseline.document, scenario.document
        for run_document in (base_doc, scenario_doc):
            _equal(run_document["protocol_id"], protocol.protocol_id, "Run protocol mismatch")
            _equal(run_document["claim_revision_id"], protocol.claim_revision_id, "Claim mismatch")
        _equal(
            scenario_doc["intent"],
            build_scenario_intent(view).document,
            "Scenario intent differs from the derived intervention",
        )
        _equal(
            base_doc["bindings"],
            {
                "dataset_id": self.source_input.dataset_id,
                "data_sha256": digest(self.source_input.normalized_bytes),
                "replay_spec_id": self.source_input.spec.spec_id,
                "replay_result_sha256": digest(left.canonical_bytes),
                "evaluation_sha256": left_evaluation.evaluation_id,
            },
            "Baseline bindings do not match recomputed evidence",
        )
        _equal(
            scenario_doc["bindings"],
            {
                "replay_result_sha256": digest(right.canonical_bytes),
                "evaluation_sha256": right_evaluation.evaluation_id,
            },
            "Scenario bindings do not match recomputed evidence",
        )
        for run_document, result in ((base_doc, left), (scenario_doc, right)):
            _equal(
                run_document["execution_status"], result.document["execution_status"], "Status mismatch"
            )
        _equal(left.document["engine"], right.document["engine"], "Comparison engine mismatch")
        _equal(
            left.document["environment"],
            right.document["environment"],
            "Comparison environment mismatch",
        )
        left_attempt, right_attempt = (
            _reservation(base_doc, protocol),
            _reservation(scenario_doc, protocol),
        )
        _require(
            left_attempt.attempt_id != right_attempt.attempt_id
            and left_attempt.attempt_index != right_attempt.attempt_index,
            "Baseline and scenario require distinct consumed attempts",
        )
        base_audit = cast("dict[str, object]", left_evaluation.document["replay_evaluation"])
        scenario_audit = cast("dict[str, object]", right_evaluation.document["replay_evaluation"])
        _equal(
            base_audit["evaluation_policy"], scenario_audit["evaluation_policy"], "Policy mismatch"
        )
        _equal(base_audit["unit"], scenario_audit["unit"], "Comparison unit mismatch")
        raw_comparison = ReplayComparison(left, right).document
        document: dict[str, object] = {
            "kind": "scenario_comparison_v1",
            "schema_version": 1,
            "scope": {
                "phase": "development",
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "calibration_status": "uncalibrated",
                "search_performed": False,
                "baseline_claim_recomputed_for_integrity": True,
                "scenario_claim_evaluated": False,
                "claim_verdict_issued": False,
            },
            "controlled_intervention": True,
            "strictly_paired": False,
            "bindings": {
                **cast("dict[str, object]", build_scenario_intent(view).document["bindings"]),
                "protocol_id": protocol.protocol_id,
                "claim_revision_id": protocol.claim_revision_id,
                "intent_id": build_scenario_intent(view).intent_id,
                "baseline": {
                    "run_id": baseline.run_id,
                    "attempt_id": left_attempt.attempt_id,
                    "result_sha256": digest(left.canonical_bytes),
                    "evaluation_sha256": left_evaluation.evaluation_id,
                },
                "scenario": {
                    "run_id": scenario.run_id,
                    "attempt_id": right_attempt.attempt_id,
                    "result_sha256": digest(right.canonical_bytes),
                    "evaluation_sha256": right_evaluation.evaluation_id,
                },
            },
            "common_conditions": {
                "engine": left.document["engine"],
                "environment": left.document["environment"],
                "replay_spec_id": self.source_input.spec.spec_id,
                "seed": self.source_input.spec.document["seed"],
                "evaluation_policy": base_audit["evaluation_policy"],
                "metric": "net_marked_pnl_v1",
                "unit": "USD",
            },
            "intervention": {
                "clock_profile_id": view.document["clock_profile_id"],
                "transform": view.document["transform"],
                "additional_delay": view.document["additional_delay"],
            },
            "condition_differences": raw_comparison["condition_differences"],
            "numeric_comparison": _numeric(base_audit, scenario_audit),
            "trace_comparison": compare_scenario_traces(left, right),
        }
        raw = canonical(document)
        parse(raw, limit=_REPORT_LIMIT)
        object.__setattr__(self, "canonical_bytes", raw)

    @property
    def comparison_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=_REPORT_LIMIT)
