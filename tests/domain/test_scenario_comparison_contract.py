"""Controlled comparisons audit real saved zero-shift evidence and explicit projections."""

import json
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.assumptions import (
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.protocol_evaluation import SCOPE, ProtocolEvaluation
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    build_run_receipt,
    canonical,
    digest,
)
from tickwitness.domain.evidence.scenario_comparison import (
    ScenarioComparison,
    _decimal,
    _numeric,
    compare_scenario_traces,
)
from tickwitness.domain.evidence.scenario_records import (
    SCENARIO_SCOPE,
    ScenarioEvaluation,
    build_scenario_intent,
    build_scenario_run_receipt,
)
from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def case() -> SimpleNamespace:
    data = normalize_events((FIXTURES / "evidence-events.jsonl").read_bytes()).normalized_bytes
    spec = build_replay_spec((FIXTURES / "evidence-replay-spec.json").read_bytes())
    protocol = build_executable_protocol(
        canonical(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Saved-native controlled comparison",
                    "hypothesis": "The baseline marked value exceeds zero.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "0",
                    "unit": "USD",
                },
                "replay_spec": spec.document,
                "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 100},
            }
        ),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
    )
    source = ReplayInput("a" * 64, data, spec)
    assumptions = build_assumption_spec(
        (EXAMPLES / "assumption-request.json").read_bytes(), protocol=protocol, replay_input=source
    )
    request = json.loads((EXAMPLES / "scenario-request.json").read_bytes())
    request["additional_delay"]["value"] = 0
    scenario = build_scenario_spec(canonical(request), assumptions=assumptions)
    view = derive_replay_view(
        validate_scenario_spec(scenario, assumptions, protocol=protocol, replay_input=source)
    )
    golden = json.loads((FIXTURES / "evidence-result.json").read_bytes())
    baseline_result = build_replay_result({**golden, "dataset_id": source.dataset_id})
    scenario_result = build_replay_result({**golden, "dataset_id": view.view_id})
    fixture = SimpleNamespace(
        protocol=protocol,
        source_input=source,
        view=view,
        baseline_result=baseline_result,
        scenario_result=scenario_result,
    )
    refresh_receipts(fixture)
    return fixture


def reservation(protocol, index=1):
    return {
        "kind": "replay_attempt_reservation_v1",
        "schema_version": 1,
        "protocol_id": protocol.protocol_id,
        "attempt_index": index,
        "nonce": ("a" if index == 1 else "b") * 32,
        "max_wall_seconds": 60,
        "created_at_utc": "2026-10-26T00:00:00.000000+00:00",
    }


def refresh_receipts(fixture):
    left = ProtocolEvaluation(fixture.protocol, fixture.source_input, fixture.baseline_result)
    right = ScenarioEvaluation(fixture.view, fixture.scenario_result)
    fixture.baseline_receipt = build_run_receipt(
        {
            "kind": "research_run_receipt_v1",
            "schema_version": 1,
            "attempt": reservation(fixture.protocol, 1),
            "protocol_id": fixture.protocol.protocol_id,
            "claim_revision_id": fixture.protocol.claim_revision_id,
            "execution_status": fixture.baseline_result.document["execution_status"],
            "scope": dict(SCOPE),
            "bindings": {
                "dataset_id": fixture.source_input.dataset_id,
                "data_sha256": digest(fixture.source_input.normalized_bytes),
                "replay_spec_id": fixture.source_input.spec.spec_id,
                "replay_result_sha256": digest(fixture.baseline_result.canonical_bytes),
                "evaluation_sha256": left.evaluation_id,
            },
        }
    )
    fixture.scenario_receipt = build_scenario_run_receipt(
        {
            "kind": "scenario_run_receipt_v1",
            "schema_version": 1,
            "attempt": reservation(fixture.protocol, 2),
            "protocol_id": fixture.protocol.protocol_id,
            "claim_revision_id": fixture.protocol.claim_revision_id,
            "execution_status": fixture.scenario_result.document["execution_status"],
            "scope": dict(SCENARIO_SCOPE),
            "intent": build_scenario_intent(fixture.view).document,
            "bindings": {
                "replay_result_sha256": digest(fixture.scenario_result.canonical_bytes),
                "evaluation_sha256": right.evaluation_id,
            },
        }
    )


def compare(fixture=None, **changes):
    values = vars(case() if fixture is None else fixture).copy()
    values.update(changes)
    return ScenarioComparison(**values)


def test_zero_shift_is_a_bound_controlled_intervention_with_zero_response() -> None:
    fixture = case()
    report = compare(fixture)
    document = report.document
    assert document["kind"] == "scenario_comparison_v1"
    assert document["controlled_intervention"] is True
    assert document["strictly_paired"] is False
    assert document["numeric_comparison"] == {
        "status": "comparable",
        "reason": None,
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "baseline_value": "-2",
        "scenario_value": "-2",
        "delta": "0",
        "delta_direction": "scenario_minus_baseline",
        "baseline_ineligibility_reason": None,
        "scenario_ineligibility_reason": None,
    }
    assert document["trace_comparison"]["raw_trace_changed"] is False
    assert document["trace_comparison"]["business_trace_changed"] is False
    assert document["trace_comparison"]["business"]["first_divergence"] is None
    assert document["condition_differences"][0]["json_pointer"] == "/dataset_id"
    bindings = document["bindings"]
    assert bindings["protocol_id"] == fixture.protocol.protocol_id
    assert bindings["baseline"]["run_id"] == fixture.baseline_receipt.run_id
    assert bindings["scenario"]["run_id"] == fixture.scenario_receipt.run_id
    assert bindings["assumption_id"] == fixture.view.validated.assumptions.assumption_id
    assert bindings["scenario_id"] == fixture.view.validated.scenario.scenario_id
    assert bindings["derived_view_id"] == fixture.view.view_id
    assert bindings["baseline"]["attempt_id"] != bindings["scenario"]["attempt_id"]
    assert b'"satisfied"' not in report.canonical_bytes
    assert b'"claim_observation"' not in report.canonical_bytes
    assert report.comparison_id == digest(report.canonical_bytes)


def test_comparison_is_frozen_deterministic_and_documents_are_detached() -> None:
    fixture = case()
    report = compare(fixture)
    assert compare(fixture).canonical_bytes == report.canonical_bytes
    document = report.document
    document["numeric_comparison"]["delta"] = "999"
    assert report.document["numeric_comparison"]["delta"] == "0"
    with pytest.raises(FrozenInstanceError):
        report.canonical_bytes = b"{}"
    with pytest.raises((TypeError, ValueError), match="canonical_bytes"):
        replace(report, canonical_bytes=b"{}")


@pytest.mark.parametrize("role", ["baseline", "scenario"])
@pytest.mark.parametrize("field", ["evaluation_sha256", "replay_result_sha256"])
def test_self_consistent_receipt_hash_changes_do_not_bypass_recomputed_bindings(
    role, field
) -> None:
    fixture = case()
    record = getattr(fixture, role + "_receipt").document
    record["bindings"][field] = "0" * 64
    builder = build_run_receipt if role == "baseline" else build_scenario_run_receipt
    setattr(fixture, role + "_receipt", builder(record))
    with pytest.raises(EvidenceValidationError, match="bindings"):
        compare(fixture)


def test_distinct_protocol_attempts_are_required() -> None:
    fixture = case()
    record = fixture.scenario_receipt.document
    record["attempt"] = fixture.baseline_receipt.document["attempt"]
    fixture.scenario_receipt = build_scenario_run_receipt(record)
    with pytest.raises(EvidenceValidationError, match="distinct consumed attempts"):
        compare(fixture)


@pytest.mark.parametrize("mutation", ["wall", "index"])
def test_attempts_must_respect_original_protocol_budget(mutation) -> None:
    fixture = case()
    record = fixture.scenario_receipt.document
    record["attempt"]["max_wall_seconds" if mutation == "wall" else "attempt_index"] = (
        59 if mutation == "wall" else 3
    )
    fixture.scenario_receipt = build_scenario_run_receipt(record)
    with pytest.raises(EvidenceValidationError, match="frozen protocol budget"):
        compare(fixture)


def test_environment_change_is_rejected_even_when_trace_and_receipt_are_self_consistent() -> None:
    fixture = case()
    result = fixture.scenario_result.document
    result["environment"]["python_version"] = "different-runtime"
    fixture.scenario_result = build_replay_result(result)
    refresh_receipts(fixture)
    with pytest.raises(EvidenceValidationError, match="environment mismatch"):
        compare(fixture)


def test_source_view_mismatch_is_rejected_before_comparing_unchanged_results() -> None:
    fixture = case()
    wrong_source = ReplayInput(
        "c" * 64, fixture.source_input.normalized_bytes, fixture.source_input.spec
    )
    with pytest.raises(EvidenceValidationError, match="Source input mismatch"):
        compare(fixture, source_input=wrong_source)


def test_receipt_status_is_rechecked_against_audited_native_result() -> None:
    fixture = case()
    record = fixture.scenario_receipt.document
    record["execution_status"] = "incomplete"
    fixture.scenario_receipt = build_scenario_run_receipt(record)
    with pytest.raises(EvidenceValidationError, match="Status mismatch"):
        compare(fixture)


def renamed_trace_result(result, *, order_id="shifted-native-order", reason=None):
    """Structural projection fixture only; never submitted as audited native evidence."""
    document = result.document
    old_id = document["decision_trace"][0]["fields"]["order_id"]
    for channel in ("input_trace", "decision_trace", "order_trace", "fill_trace", "account_trace"):
        for row in document[channel]:
            row["native_time_ns"] += 2_000_000_000
            fields = row["fields"]
            for key in (
                "native_event_ts_ns",
                "native_init_ts_ns",
                "native_ts_event_ns",
                "native_ts_init_ns",
                "receive_time_ns",
            ):
                if key in fields:
                    fields[key] += 2_000_000_000
            if fields.get("order_id") == old_id:
                fields["order_id"] = order_id
            if channel == "fill_trace":
                fields["native_trade_id"] = "new-native-trade"
            for order in fields.get("orders", []):
                if order["order_id"] == old_id:
                    order["order_id"] = order_id
    if reason is not None:
        document["order_trace"][-1]["kind"] = "OrderCancelRejected"
        document["order_trace"][-1]["fields"]["reason"] = reason
    return build_replay_result(document)


def test_explicit_timestamps_and_internal_ids_change_raw_but_not_business_projection() -> None:
    baseline = case().baseline_result
    scenario = renamed_trace_result(baseline)
    report = compare_scenario_traces(baseline, scenario)
    assert report["raw_trace_changed"] is True
    assert report["business_trace_changed"] is False
    assert report["business"]["first_divergence"] is None
    assert report["global_earliest_claimed"] is False


def test_projection_never_rewrites_source_payload_substrings_containing_native_order_id() -> None:
    baseline = case().baseline_result
    old_id = baseline.document["decision_trace"][0]["fields"]["order_id"]
    left = baseline.document
    left["input_trace"][2]["fields"]["source_trade_id"] = "payload-" + old_id
    right = renamed_trace_result(build_replay_result(left)).document
    right["input_trace"][2]["fields"]["source_trade_id"] = "payload-shifted-native-order"
    report = compare_scenario_traces(build_replay_result(left), build_replay_result(right))
    first = report["business"]["first_divergence"]
    assert first["json_pointer"] == "/input_trace/2/fields/source_trade_id"
    assert first["left_value"] == "payload-" + old_id
    assert first["left_raw_value"] == "payload-" + old_id
    assert first["right_trace_ref"]["source_ref"]["capture_seq"] == 3


def test_only_exact_known_cancel_rejection_template_normalizes_its_order_token() -> None:
    fixture = case()
    left = fixture.baseline_result.document
    old_id = left["decision_trace"][0]["fields"]["order_id"]
    left["order_trace"][-1]["kind"] = "OrderCancelRejected"
    left["order_trace"][-1]["fields"]["reason"] = f"ClientOrderId('{old_id}') not found"
    baseline = build_replay_result(left)
    right = renamed_trace_result(baseline, reason="ClientOrderId('shifted-native-order') not found")
    assert compare_scenario_traces(baseline, right)["business_trace_changed"] is False
    unknown = renamed_trace_result(baseline, reason="Unknown reason shifted-native-order")
    assert compare_scenario_traces(baseline, unknown)["business_trace_changed"] is True


def test_missing_fill_retains_present_flags_raw_values_and_both_source_references() -> None:
    baseline = case().baseline_result
    right = baseline.document
    right["fill_trace"].pop()
    report = compare_scenario_traces(baseline, build_replay_result(right))
    first = report["business"]["per_channel_first"]["fill_trace"]
    assert first["json_pointer"] == "/fill_trace/1"
    assert first["left_present"] is True
    assert first["right_present"] is False
    assert first["left_trace_ref"]["source_ref"]["capture_seq"] == 5
    assert first["right_trace_ref"] is None
    assert first["left_raw_value"]["fields"]["native_trade_id"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(0), "0"),
        (Fraction(-1, 8), "-0.125"),
        (Fraction(1, 5), "0.2"),
        (Fraction(12345678901234567890123456789, 1000000000), "12345678901234567890.123456789"),
    ],
)
def test_exact_delta_format_does_not_depend_on_decimal_precision(value, expected) -> None:
    assert _decimal(value) == expected


def test_nonterminating_fraction_cannot_silently_round() -> None:
    with pytest.raises(EvidenceValidationError, match="terminating decimal"):
        _decimal(Fraction(1, 3))


@pytest.mark.parametrize("side", ["baseline", "scenario"])
@pytest.mark.parametrize(
    "reason", ["execution_incomplete", "no_fills", "ambiguous_native_fee_model"]
)
def test_unvalued_side_never_produces_a_numeric_zero_or_difference(side, reason) -> None:
    """Direct numeric-policy unit inputs; these are not forged replay receipts."""
    fixture = case()
    audited = ProtocolEvaluation(
        fixture.protocol, fixture.source_input, fixture.baseline_result
    ).document["replay_evaluation"]
    unavailable = {
        **audited,
        "valuation_status": "not_eligible",
        "ineligibility_reason": reason,
        "valuation": None,
        "mark": None,
    }
    report = (
        _numeric(unavailable, audited) if side == "baseline" else _numeric(audited, unavailable)
    )
    assert report["status"] == "not_comparable"
    assert report["reason"] == side + "_not_eligible"
    assert report["delta"] is None
    assert report[side + "_value"] is None


def test_mark_definition_mismatch_does_not_create_a_pnl_comparison() -> None:
    fixture = case()
    audited = ProtocolEvaluation(
        fixture.protocol, fixture.source_input, fixture.baseline_result
    ).document["replay_evaluation"]
    changed = {**audited, "mark": {**audited["mark"], "price_ticks": 101}}
    result = _numeric(audited, changed)
    assert result["status"] == "not_comparable"
    assert result["reason"] == "mark_definition_changed"
    assert result["delta"] is None
