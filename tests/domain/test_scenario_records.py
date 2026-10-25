"""Strict intent and scenario records keep baseline claim truth out of stress runs."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.assumptions import (
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.assumptions.derivation import DerivedReplayView
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    load_run_receipt,
)
from tickwitness.domain.evidence.scenario_records import (
    SCENARIO_SCOPE,
    ScenarioEvaluation,
    build_scenario_failure,
    build_scenario_intent,
    build_scenario_run_receipt,
    load_scenario_failure,
    load_scenario_intent,
    load_scenario_run_receipt,
)
from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol


def case() -> SimpleNamespace:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    examples = Path(__file__).resolve().parents[2] / "examples"
    data = normalize_events((fixtures / "evidence-events.jsonl").read_bytes()).normalized_bytes
    spec = build_replay_spec((fixtures / "evidence-replay-spec.json").read_bytes())
    protocol = build_executable_protocol(
        canonical(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Original scenario record fixture",
                    "hypothesis": "Baseline marked value exceeds minus three USD.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "-3",
                    "unit": "USD",
                },
                "replay_spec": spec.document,
                "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 100},
            }
        ),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
    )
    replay_input = ReplayInput("a" * 64, data, spec)
    assumptions = build_assumption_spec(
        (examples / "assumption-request.json").read_bytes(),
        protocol=protocol,
        replay_input=replay_input,
    )
    request = json.loads((examples / "scenario-request.json").read_bytes())
    request["additional_delay"]["value"] = 0
    scenario = build_scenario_spec(canonical(request), assumptions=assumptions)
    validated = validate_scenario_spec(
        scenario,
        assumptions,
        protocol=protocol,
        replay_input=replay_input,
    )
    view = DerivedReplayView(validated)
    result = json.loads((fixtures / "evidence-result.json").read_bytes())
    result["dataset_id"] = view.view_id
    result = build_replay_result(result)
    raw = canonical(
        {
            "kind": "replay_attempt_reservation_v1",
            "schema_version": 1,
            "protocol_id": protocol.protocol_id,
            "attempt_index": 1,
            "nonce": "a" * 32,
            "max_wall_seconds": 60,
            "created_at_utc": "2026-10-26T00:00:00.000000+00:00",
        }
    )
    return SimpleNamespace(
        protocol=protocol,
        view=view,
        result=result,
        reservation=AttemptReservation(digest(raw), raw),
    )


def receipt_document(fixture: SimpleNamespace) -> dict[str, object]:
    intent = build_scenario_intent(fixture.view)
    evaluation = ScenarioEvaluation(fixture.view, fixture.result)
    return {
        "kind": "scenario_run_receipt_v1",
        "schema_version": 1,
        "attempt": fixture.reservation.document,
        "protocol_id": fixture.protocol.protocol_id,
        "claim_revision_id": fixture.protocol.claim_revision_id,
        "execution_status": "completed",
        "scope": dict(SCENARIO_SCOPE),
        "intent": intent.document,
        "bindings": {
            "replay_result_sha256": digest(fixture.result.canonical_bytes),
            "evaluation_sha256": evaluation.evaluation_id,
        },
    }


def test_intent_binds_source_and_derived_view_without_mutable_references() -> None:
    fixture = case()
    intent = build_scenario_intent(fixture.view)
    document = intent.document
    assert document["protocol_id"] == fixture.protocol.protocol_id
    assert document["claim_revision_id"] == fixture.protocol.claim_revision_id
    assert document["clock_profile_id"] == "coupled_receive_suffix_clock_v1"
    assert document["scope"] == dict(SCENARIO_SCOPE)
    assert document["bindings"] == {
        "development_dataset_id": "a" * 64,
        "source_normalized_sha256": digest(fixture.view.validated.replay_input.normalized_bytes),
        "replay_spec_id": fixture.view.replay_input.spec.spec_id,
        "assumption_id": fixture.view.validated.assumptions.assumption_id,
        "scenario_id": fixture.view.validated.scenario.scenario_id,
        "derived_view_id": fixture.view.view_id,
        "derived_normalized_sha256": digest(fixture.view.replay_input.normalized_bytes),
    }
    assert load_scenario_intent(intent.canonical_bytes) == intent
    assert build_scenario_intent(fixture.view) == intent
    document["bindings"]["derived_view_id"] = "0" * 64
    assert intent == build_scenario_intent(fixture.view)
    with pytest.raises(FrozenInstanceError):
        intent.intent_id = "0" * 64  # type: ignore[misc]
    with pytest.raises(EvidenceValidationError):
        replace(intent, intent_id="0" * 64)


def test_scenario_evaluation_has_a_metric_and_never_evaluates_baseline_claim() -> None:
    fixture = case()
    evaluation = ScenarioEvaluation(fixture.view, fixture.result)
    assert evaluation.document["metric_observation"] == {
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "eligible": True,
        "value": "-2",
    }
    assert evaluation.document["scope"]["baseline_claim_evaluated"] is False
    assert b'"satisfied"' not in evaluation.canonical_bytes
    assert b'"claim_observation"' not in evaluation.canonical_bytes
    assert evaluation.evaluation_id == digest(evaluation.canonical_bytes)
    assert (
        ScenarioEvaluation(fixture.view, fixture.result).canonical_bytes
        == evaluation.canonical_bytes
    )
    document = fixture.result.document
    document["dataset_id"] = fixture.view.validated.replay_input.dataset_id
    with pytest.raises(ValueError):
        ScenarioEvaluation(fixture.view, build_replay_result(document))


def test_scenario_receipt_is_a_separate_strict_schema() -> None:
    fixture = case()
    receipt = build_scenario_run_receipt(receipt_document(fixture))
    assert receipt.run_id == digest(receipt.canonical_bytes)
    assert receipt.intent_id == build_scenario_intent(fixture.view).intent_id
    assert load_scenario_run_receipt(receipt.canonical_bytes) == receipt
    with pytest.raises(EvidenceValidationError):
        load_run_receipt(receipt.canonical_bytes)
    document = receipt.document
    document["intent"]["bindings"]["scenario_id"] = "0" * 64
    assert receipt.document != document
    with pytest.raises(EvidenceValidationError):
        replace(receipt, run_id="0" * 64)


def test_view_is_rederived_before_public_intent_or_evaluation_building() -> None:
    fixture = case()
    forged = replace(fixture.view)
    object.__setattr__(forged, "canonical_bytes", b"{}")
    with pytest.raises(EvidenceValidationError, match="reproduce"):
        build_scenario_intent(forged)
    with pytest.raises(EvidenceValidationError, match="reproduce"):
        ScenarioEvaluation(forged, fixture.result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "research_run_receipt_v1"),
        ("schema_version", True),
        ("protocol_id", "0" * 64),
        ("claim_revision_id", "0" * 64),
        ("execution_status", []),
        ("execution_status", "failed"),
        ("scope", {"phase": "development", "baseline_claim_evaluated": True}),
        ("bindings", {"replay_result_sha256": "0" * 64, "evaluation_sha256": True}),
        ("extra", "field"),
    ],
)
def test_forged_receipt_fields_are_rejected(field: str, value: object) -> None:
    document = receipt_document(case())
    document[field] = value
    with pytest.raises(EvidenceValidationError):
        build_scenario_run_receipt(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("clock_profile_id", "dual_clock_feed_v1"),
        ("scope", {"phase": "confirmation"}),
        ("protocol_id", "../bad"),
        ("bindings", {"derived_view_id": "0" * 64}),
        ("execution_approved", True),
    ],
)
def test_forged_intent_fields_are_rejected(field: str, value: object) -> None:
    document = build_scenario_intent(case().view).document
    document[field] = value
    with pytest.raises(EvidenceValidationError):
        load_scenario_intent(canonical(document))


def test_scenario_failure_preserves_intent_and_attempt_without_a_false_run() -> None:
    fixture = case()
    intent = build_scenario_intent(fixture.view)
    raw = build_scenario_failure(
        fixture.reservation, intent, "engine_timeout", "Native worker timed out"
    )
    document = load_scenario_failure(raw)
    assert document["intent"] == intent.document
    assert document["attempt"] == fixture.reservation.document
    assert "bindings" not in document and "claim_observation" not in document
    with pytest.raises(EvidenceValidationError):
        load_scenario_run_receipt(raw)
    document["error"]["message"] = ""
    with pytest.raises(EvidenceValidationError):
        load_scenario_failure(canonical(document))


@pytest.mark.parametrize(
    "raw",
    [b"", b"\xff", b"[]", b'{"x":1,"x":2}', b'{"x":1.0}', b'{"x":NaN}', b" " * (16 * 1024 + 1)],
)
def test_malformed_or_oversized_record_bytes_are_rejected(raw: bytes) -> None:
    for loader in (load_scenario_intent, load_scenario_run_receipt, load_scenario_failure):
        with pytest.raises(EvidenceValidationError):
            loader(raw)
