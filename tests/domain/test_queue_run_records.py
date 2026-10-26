"""Queue records freeze the whole model family without widening legacy evidence."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.queue_records import (
    QueueAttemptReservation,
    QueueRunIntent,
    QueueRunReceipt,
    build_queue_failure,
    build_queue_intent,
    build_queue_run_receipt,
    load_queue_failure,
    load_queue_intent,
    load_queue_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    load_run_receipt,
)
from tickwitness.domain.evidence.scenario_records import load_scenario_intent
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.queue_family import build_queue_family_protocol

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def family():
    experiment = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    spec = build_replay_spec(canonical(experiment["replay_spec"]))
    source = build_executable_protocol(
        canonical(experiment), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    normalized = normalize_events((EXAMPLES / "queue-observations.jsonl").read_bytes())
    return build_queue_family_protocol(
        canonical(
            {
                "kind": "queue_family_request_v1",
                "schema_version": 1,
                "cancel_at_capture_seq": 6,
                "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 1000},
            }
        ),
        source_protocol=source,
        replay_input=ReplayInput("a" * 64, normalized.normalized_bytes, spec),
        queue_request=(EXAMPLES / "queue-constraint-request.json").read_bytes(),
    )


def reservation(owner):
    raw = canonical(
        {
            "kind": "queue_attempt_reservation_v1",
            "schema_version": 1,
            "protocol_id": owner.family_id,
            "attempt_index": 1,
            "nonce": "a" * 32,
            "max_wall_seconds": 30,
            "created_at_utc": "2026-10-26T00:00:00.000000+00:00",
        }
    )
    return QueueAttemptReservation(digest(raw), raw)


def receipt_document(attempt, intent):
    return {
        "kind": "queue_run_receipt_v1",
        "schema_version": 1,
        "attempt": attempt.document,
        "protocol_id": attempt.protocol_id,
        "intent": intent.document,
        "execution_status": "completed",
        "bindings": {"replay_result_sha256": "d" * 64, "evaluation_sha256": "e" * 64},
    }


def test_intent_freezes_full_family_source_constraint_and_chosen_policy() -> None:
    owner = family()
    front = build_queue_intent(owner, "cancel_front_first_v1")
    back = build_queue_intent(owner, "cancel_back_first_v1")
    assert front == load_queue_intent(front.canonical_bytes)
    assert front.intent_id == digest(front.canonical_bytes)
    assert front.intent_id != back.intent_id
    assert front.document["protocol_id"] == back.document["protocol_id"] == owner.family_id
    assert front.family == owner
    assert front.policy_id == "cancel_front_first_v1"
    assert front.document["family"] == owner.document
    detached = front.document
    detached["family"]["bindings"]["normalized_sha256"] = "0" * 64
    assert front.family == owner
    with pytest.raises(FrozenInstanceError):
        front.canonical_bytes = b"{}"
    with pytest.raises(EvidenceValidationError):
        build_queue_intent(owner, "undeclared_policy_v1")
    with pytest.raises(EvidenceValidationError):
        QueueRunIntent("0" * 64, front.canonical_bytes)


@pytest.mark.parametrize(
    "mutation",
    ["kind", "version", "owner", "policy", "extra", "family_engine", "family_scope", "family_hash"],
)
def test_intent_rejects_cross_model_and_forged_frozen_context(mutation) -> None:
    document = build_queue_intent(family(), "cancel_front_first_v1").document
    if mutation == "kind":
        document["kind"] = "scenario_execution_intent_v1"
    elif mutation == "version":
        document["schema_version"] = True
    elif mutation == "owner":
        document["protocol_id"] = "0" * 64
    elif mutation == "policy":
        document["policy_id"] = "undeclared_v1"
    elif mutation == "extra":
        document["claim_verdict"] = True
    elif mutation == "family_engine":
        document["family"]["engine"]["semantic_id"] = "nautilus_v1_receive_order_single_limit_buy_v1"
    elif mutation == "family_scope":
        document["family"]["scope"]["impact_compatibility_verified"] = True
    else:
        document["family"]["bindings"]["normalized_sha256"] = "0" * 64
    with pytest.raises(EvidenceValidationError):
        load_queue_intent(canonical(document))


def test_queue_reservation_is_a_distinct_strict_kind_and_bounds_are_unchanged() -> None:
    attempt = reservation(family())
    assert isinstance(attempt, AttemptReservation)
    with pytest.raises(EvidenceValidationError):
        AttemptReservation(attempt.attempt_id, attempt.canonical_bytes)
    for key, value in (
        ("attempt_index", True),
        ("max_wall_seconds", 61),
        ("nonce", "z" * 32),
        ("created_at_utc", "2026-02-30T00:00:00.000000+00:00"),
        ("schema_version", True),
        ("unexpected", "extra"),
    ):
        changed = dict(attempt.document, **{key: value})
        raw = canonical(changed)
        with pytest.raises(EvidenceValidationError):
            QueueAttemptReservation(digest(raw), raw)


def test_receipt_and_failure_roundtrip_bind_complete_original_attempt_and_intent() -> None:
    owner = family()
    attempt = reservation(owner)
    intent = build_queue_intent(owner, "cancel_front_first_v1")
    receipt = build_queue_run_receipt(receipt_document(attempt, intent))
    assert receipt == load_queue_run_receipt(receipt.canonical_bytes)
    assert receipt.intent_id == intent.intent_id
    assert receipt.run_id == digest(receipt.canonical_bytes)
    failure = build_queue_failure(attempt, intent, "native_timeout", "Worker reached frozen limit")
    assert load_queue_failure(failure)["intent"] == intent.document
    assert load_queue_failure(failure)["attempt"] == attempt.document
    with pytest.raises(EvidenceValidationError):
        load_run_receipt(receipt.canonical_bytes)
    with pytest.raises(EvidenceValidationError):
        load_scenario_intent(intent.canonical_bytes)
    with pytest.raises(EvidenceValidationError):
        QueueRunReceipt("0" * 64, receipt.canonical_bytes)


@pytest.mark.parametrize(
    "mutation", ["reservation_kind", "wall", "index", "family", "status", "hash", "extra"]
)
def test_receipt_rejects_reservation_retyping_and_inconsistent_family_budget(mutation) -> None:
    owner = family()
    document = receipt_document(reservation(owner), build_queue_intent(owner, "cancel_front_first_v1"))
    if mutation == "reservation_kind":
        document["attempt"]["kind"] = "replay_attempt_reservation_v1"
    elif mutation == "wall":
        document["attempt"]["max_wall_seconds"] = 31
    elif mutation == "index":
        document["attempt"]["attempt_index"] = 3
    elif mutation == "family":
        document["attempt"]["protocol_id"] = "0" * 64
    elif mutation == "status":
        document["execution_status"] = "failed"
    elif mutation == "hash":
        document["bindings"]["evaluation_sha256"] = "invalid"
    else:
        document["claim_verdict_issued"] = True
    with pytest.raises(EvidenceValidationError):
        build_queue_run_receipt(document)


@pytest.mark.parametrize("code,message", [("", "failure"), ("x" * 129, "failure"), ("x", ""), ("x", "m" * 4097)])
def test_failure_enforces_error_bounds(code, message) -> None:
    owner = family()
    with pytest.raises(EvidenceValidationError):
        build_queue_failure(reservation(owner), build_queue_intent(owner, "cancel_front_first_v1"), code, message)
