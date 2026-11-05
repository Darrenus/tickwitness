"""Reaudited original/reduced scenario observations and their unequal horizons.

Trace channel order is a deterministic presentation rule. It does not establish
global time order, a shared terminal state, or the cause of a business difference.
Live-ledger authentication belongs to the application, not this pure value.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import cast

from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.evidence.reduction_preservation import ReductionPreservationAssessment
from tickwitness.domain.evidence.reduction_records import ReductionRunReceipt, ReductionStateAudit
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.scenario_comparison import compare_scenario_traces
from tickwitness.domain.evidence.scenario_records import (
    ScenarioEvaluation,
    ScenarioRunReceipt,
    build_scenario_intent,
    load_scenario_run_receipt,
)
from tickwitness.domain.reduction.contracts import MaterializedReduction
from tickwitness.domain.replay.comparison import ReplayComparison
from tickwitness.domain.replay.contracts import ReplayResult, load_replay_result
from tickwitness.domain.research_contracts.search_finding_protocol import SearchFindingProtocol

MAX_REDUCTION_COMPARISON_BYTES = 16 * 1024 * 1024
MAX_REDUCTION_COMPARISON_EXPORT_BYTES = MAX_REDUCTION_COMPARISON_BYTES + 64 * 1024
COMPARISON_SCOPE: Mapping[str, object] = MappingProxyType(
    {
        "phase": "development",
        "authority": "original_reduced_witness_review_v1",
        "source_claim_evaluated": False,
        "baseline_truth_evaluated": False,
        "original_finding_rewritten": False,
        "original_predicate_domain_extended": False,
        "budget_owner_changed": False,
        "numeric_effect_comparable": False,
        "global_earliest_claimed": False,
        "causal_attribution_issued": False,
        "shared_terminal_state_captured": False,
        "local_minimum_verified": False,
        "global_minimum_verified": False,
        "checkpoint_resume_verified": False,
        "full_attempt_history_verified": False,
        "global_ledger_authenticity_verified": False,
        "author_signature_verified": False,
        "human_domain_approval_verified": False,
        "confirmation_accessed": False,
    }
)
COMPARISON_VERIFICATION: Mapping[str, object] = MappingProxyType(
    {
        "original_scenario_reaudited": True,
        "reduced_state_reaudited": True,
        "preservation_recomputed": True,
        "input_partition_recomputed": True,
        "trace_comparison_recomputed": True,
        "native_replayed": False,
        "attempt_reserved": False,
        "live_ledger_reaudited": False,
        "source_claim_evaluated": False,
        "baseline_truth_evaluated": False,
        "shared_terminal_state_captured": False,
        "global_earliest_claimed": False,
        "causal_attribution_issued": False,
    }
)
_REPORT_FIELDS = {
    "kind",
    "schema_version",
    "scope",
    "bindings",
    "input_difference",
    "original_observation",
    "reduced_assessment",
    "trace_comparison",
    "condition_differences",
    "horizon",
    "both_false_witnesses",
    "verification",
}
type Row = dict[str, object]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _same(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _attempt(document: Row, materialized: MaterializedReduction) -> AttemptReservation:
    raw = canonical(cast("Row", document["attempt"]))
    attempt = AttemptReservation(digest(raw), raw)
    protocol = materialized.source.validation.protocol
    budget = cast("Row", protocol.document["budget"])
    _require(
        attempt.protocol_id == protocol.protocol_id
        and attempt.attempt_index <= cast("int", budget["max_attempts"])
        and attempt.document["max_wall_seconds"] == budget["max_wall_seconds"],
        "Comparison attempt differs from the original protocol budget",
    )
    return attempt


def _original_observation(authority: SearchFindingProtocol, evaluation: Row) -> Row:
    criterion = cast("Row", cast("Row", authority.document["predicate"])["criterion"])
    _same(
        [criterion["metric"], criterion["unit"], evaluation["unit"]],
        ["net_marked_pnl_v1", "USD", "USD"],
        "Original witness valuation profile differs",
    )
    _require(
        evaluation["execution_status"] == "completed"
        and evaluation["valuation_status"] == "valued",
        "Original witness must be completed and numerically eligible",
    )
    value = cast("Row", evaluation["valuation"])["net_marked_pnl"]
    _require(isinstance(value, str), "Original witness requires an exact decimal observation")
    actual, threshold = Fraction(cast("str", value)), Fraction(cast("str", criterion["threshold"]))
    truth = {
        "gt": actual > threshold,
        "ge": actual >= threshold,
        "lt": actual < threshold,
        "le": actual <= threshold,
    }[cast("str", criterion["comparator"])]
    _require(truth is False, "Selected original witness does not make its frozen criterion false")
    return {
        **criterion,
        "eligible": True,
        "value": value,
        "truth": False,
        "reason": None,
        "mark": evaluation["mark"],
        "evaluation_policy": evaluation["evaluation_policy"],
    }


def _reference(event: Row, index: int) -> Row:
    return {"line": index + 1, "capture_seq": event["capture_seq"], "event_type": event["type"]}


def _input_difference(materialized: MaterializedReduction) -> Row:
    original = derive_replay_view(materialized.source.validation)
    original_lines = original.replay_input.normalized_bytes.splitlines()
    reduced_lines = materialized.replay_input.normalized_bytes.splitlines()
    original_events = [parse(line, limit=8 * 1024 * 1024) for line in original_lines]
    reduced_events = [parse(line, limit=8 * 1024 * 1024) for line in reduced_lines]
    refs = [_reference(event, index) for index, event in enumerate(original_events)]
    operators = cast("Row", materialized.recipe.document["operators"])
    count = len(reduced_events)
    captures = [ref["capture_seq"] for ref in refs]
    focus = captures.index(operators["focus_from_capture_seq"])
    _require(
        count > focus
        and count <= len(refs)
        and refs[count - 1]["capture_seq"] == operators["through_capture_seq"],
        "Comparison prefix does not contain its actual frozen review window",
    )
    changed = []
    for index, (left, right) in enumerate(zip(original_events, reduced_events, strict=False)):
        left_payload, right_payload = dict(left), dict(right)
        old_clock, new_clock = (
            left_payload.pop("receive_time_ns"),
            right_payload.pop("receive_time_ns"),
        )
        _same(left_payload, right_payload, "Reduction changed non-clock retained event payload")
        if old_clock != new_clock:
            changed.append(
                {
                    "source_ref": refs[index],
                    "original_line_sha256": digest(original_lines[index]),
                    "reduced_line_sha256": digest(reduced_lines[index]),
                    "field_differences": [
                        {
                            "json_pointer": "/receive_time_ns",
                            "original_value": old_clock,
                            "reduced_value": new_clock,
                        }
                    ],
                }
            )
    protocol = original.validated.protocol.document
    strategy = cast("Row", cast("Row", protocol["replay_spec"])["strategy"])
    submit = cast("int", strategy["submit_capture_seq"])
    transform = cast("Row", original.validated.assumptions.document["transform"])
    anchor = cast("int", transform["from_capture_seq"])
    return {
        "reference_policy": "original_source_line_capture_seq_event_type_v1",
        "source_event_count": len(refs),
        "retained_event_count": count,
        "removed_event_count": len(refs) - count,
        "original_additional_delay_ns": cast(
            "Row", original.validated.scenario.document["additional_delay"]
        )["value"],
        "reduced_additional_delay_ns": operators["additional_delay_ns"],
        "origin_ref": refs[0],
        "focus_ref": refs[focus],
        "through_ref": refs[count - 1],
        "minimum_through_capture_seq": max(
            submit, anchor, cast("int", operators["focus_from_capture_seq"])
        ),
        "retained_refs": refs[:count],
        "warmup_refs": refs[:focus],
        "review_refs": refs[focus:count],
        "removed_events": [
            {
                "source_ref": refs[index],
                "original_event": original_events[index],
                "original_line_sha256": digest(original_lines[index]),
            }
            for index in range(count, len(refs))
        ],
        "changed_retained_events": changed,
    }


def _horizon_side(result: ReplayResult, evaluation: Row, through: object) -> Row:
    return {
        "through_ref": through,
        "execution_status": result.document["execution_status"],
        "completeness": result.document["completeness"],
        "valuation_status": evaluation["valuation_status"],
        "mark": evaluation["mark"],
    }


@dataclass(frozen=True, slots=True)
class ReductionComparison:
    authority: SearchFindingProtocol
    materialized: MaterializedReduction
    original_receipt: ScenarioRunReceipt
    original_result: ReplayResult
    reduced_receipt: ReductionRunReceipt
    reduced_result: ReplayResult
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require(
                type(self.authority) is SearchFindingProtocol
                and type(self.materialized) is MaterializedReduction
                and type(self.original_receipt) is ScenarioRunReceipt
                and type(self.original_result) is ReplayResult
                and type(self.reduced_receipt) is ReductionRunReceipt
                and type(self.reduced_result) is ReplayResult,
                "Reduction comparison requires typed original and reduced execution evidence",
            )
            preservation = ReductionPreservationAssessment(
                self.authority, self.materialized, self.reduced_receipt, self.reduced_result
            )
            authority, materialized = preservation.authority, preservation.materialized
            reduced_receipt, reduced_result = preservation.receipt, preservation.result
            original_receipt = load_scenario_run_receipt(self.original_receipt.canonical_bytes)
            _require(
                original_receipt.run_id == self.original_receipt.run_id
                and original_receipt.run_id == materialized.source.source_run_id,
                "Original comparison receipt is not the selected source witness",
            )
            original_result = load_replay_result(self.original_result.canonical_bytes)
            view = derive_replay_view(materialized.source.validation)
            evaluation = ScenarioEvaluation(view, original_result)
            original = original_receipt.document
            protocol = view.validated.protocol
            _same(
                [original["protocol_id"], original["claim_revision_id"]],
                [protocol.protocol_id, protocol.claim_revision_id],
                "Original witness belongs to a different owner or claim",
            )
            _same(
                original["intent"], build_scenario_intent(view).document, "Original intent differs"
            )
            _same(
                original["bindings"],
                {
                    "replay_result_sha256": digest(original_result.canonical_bytes),
                    "evaluation_sha256": evaluation.evaluation_id,
                },
                "Original witness result or evaluation binding differs",
            )
            _same(
                original["execution_status"],
                original_result.document["execution_status"],
                "Original witness status differs from its actual result",
            )
            original_attempt, reduced_attempt = (
                _attempt(original, materialized),
                _attempt(reduced_receipt.document, materialized),
            )
            _require(
                original_attempt.attempt_id != reduced_attempt.attempt_id
                and original_attempt.attempt_index != reduced_attempt.attempt_index,
                "Original and reduced results require distinct consumed attempts",
            )
            for key in ("engine", "environment"):
                _same(
                    original_result.document[key],
                    reduced_result.document[key],
                    "Original and reduced running condition differs: " + key,
                )
            original_evaluation = cast("Row", evaluation.document["replay_evaluation"])
            original_observation = _original_observation(authority, original_evaluation)
            reduced_audit = ReductionStateAudit(materialized, reduced_result)
            reduced_evaluation = cast("Row", reduced_audit.document["replay_evaluation"])
            partition = _input_difference(materialized)
            original_events = view.replay_input.normalized_bytes.splitlines()
            last_original = parse(original_events[-1], limit=8 * 1024 * 1024)
            outcome = preservation.document["outcome"]
            both_false: bool | None = None if outcome == "NOT_EVALUABLE" else outcome == "PRESERVED"
            bindings = {
                "source": materialized.recipe.document["source"],
                "original": {
                    "run_id": original_receipt.run_id,
                    "attempt_id": original_attempt.attempt_id,
                    "intent_id": original_receipt.intent_id,
                    "result_sha256": digest(original_result.canonical_bytes),
                    "evaluation_sha256": evaluation.evaluation_id,
                    "view_id": view.view_id,
                    "normalized_sha256": digest(view.replay_input.normalized_bytes),
                },
                "reduced": {
                    **cast("Row", preservation.document["candidate"]),
                    "assessment_id": preservation.assessment_id,
                },
            }
            document: Row = {
                "kind": "reduction_comparison_v1",
                "schema_version": 1,
                "scope": dict(COMPARISON_SCOPE),
                "bindings": bindings,
                "input_difference": partition,
                "original_observation": original_observation,
                "reduced_assessment": preservation.document,
                "trace_comparison": compare_scenario_traces(original_result, reduced_result),
                "condition_differences": ReplayComparison(original_result, reduced_result).document[
                    "condition_differences"
                ],
                "horizon": {
                    "policy": "whole_recorded_runs_including_unequal_eof_v1",
                    "original_event_count": len(original_events),
                    "reduced_event_count": partition["retained_event_count"],
                    "shared_input_event_count": partition["retained_event_count"],
                    "same_input_horizon": partition["removed_event_count"] == 0,
                    "shared_terminal_state_captured": False,
                    "original": _horizon_side(
                        original_result,
                        original_evaluation,
                        _reference(last_original, len(original_events) - 1),
                    ),
                    "reduced": _horizon_side(
                        reduced_result, reduced_evaluation, partition["through_ref"]
                    ),
                },
                "both_false_witnesses": both_false,
                "verification": dict(COMPARISON_VERIFICATION),
            }
            raw = canonical(document)
            parse(raw, limit=MAX_REDUCTION_COMPARISON_BYTES)
            for name, value in (
                ("authority", authority),
                ("materialized", materialized),
                ("original_receipt", original_receipt),
                ("original_result", original_result),
                ("reduced_receipt", reduced_receipt),
                ("reduced_result", reduced_result),
                ("canonical_bytes", raw),
            ):
                object.__setattr__(self, name, value)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
            raise EvidenceValidationError(
                "Cannot compare reduced witness: " + str(error)
            ) from error

    @property
    def comparison_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_REDUCTION_COMPARISON_BYTES)

    @property
    def export_bytes(self) -> bytes:
        raw = canonical(
            {
                "kind": "reduction_comparison_export_v1",
                "schema_version": 1,
                "comparison_id": self.comparison_id,
                "report": self.document,
            }
        )
        parse(raw, limit=MAX_REDUCTION_COMPARISON_EXPORT_BYTES)
        return raw


def load_reduction_comparison_export(raw: bytes) -> tuple[str, Row]:
    """Check bounded encoding and identity, not independent observation semantics."""
    try:
        envelope = parse(raw, limit=MAX_REDUCTION_COMPARISON_EXPORT_BYTES)
        _require(
            envelope.keys() == {"kind", "schema_version", "comparison_id", "report"},
            "Reduction comparison export fields differ",
        )
        _same(
            [envelope["kind"], envelope["schema_version"]],
            ["reduction_comparison_export_v1", 1],
            "Unsupported reduction comparison export",
        )
        report = envelope["report"]
        _require(
            isinstance(report, dict) and report.keys() == _REPORT_FIELDS,
            "Comparison report fields differ",
        )
        report = cast("Row", report)
        report_raw = canonical(report)
        parse(report_raw, limit=MAX_REDUCTION_COMPARISON_BYTES)
        _same(
            [report["kind"], report["schema_version"]],
            ["reduction_comparison_v1", 1],
            "Unsupported comparison report",
        )
        _same(report["scope"], dict(COMPARISON_SCOPE), "Comparison report scope differs")
        _same(
            report["verification"],
            dict(COMPARISON_VERIFICATION),
            "Comparison verification scope differs",
        )
        comparison_id = identity(envelope["comparison_id"])
        _require(digest(report_raw) == comparison_id, "Comparison export identity differs")
        return comparison_id, report
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise EvidenceValidationError(
            "Cannot load reduction comparison export: " + str(error)
        ) from error
