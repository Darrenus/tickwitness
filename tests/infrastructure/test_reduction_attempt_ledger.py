"""New reduction envelopes reuse ordinary immutable slots without weakening routing."""

from pathlib import Path

import pytest

from tickwitness.application.reductions import prepare_reduction_input
from tickwitness.domain.evidence.reduction_records import (
    ReductionStateAudit,
    build_reduction_failure,
    build_reduction_intent,
    build_reduction_run_receipt,
    load_reduction_failure,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import canonical, digest, parse
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
    LocalAttemptLedger,
)
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

CORPUS = Path(__file__).resolve().parents[2] / "examples" / "alpha"


def context():
    source = read_search_evidence_bundle(CORPUS / "counterexample")
    prepared = prepare_reduction_input(
        source,
        canonical(
            {
                "kind": "reduction_request_v1", "schema_version": 1, "witness_ordinal": 3,
                "focus_from_capture_seq": 1, "through_capture_seq": 7,
                "additional_delay_ns": 2_000_000_000,
            }
        ),
        expected_bundle_id=source.bundle_id,
        expected_report_id=digest(source.artifacts["finding_report"]),
    )
    materialized = prepared.materialization
    selected = parse(source.artifacts["cas/" + materialized.source.source_run_id])
    document = parse(source.artifacts["cas/" + selected["bindings"]["replay_result_sha256"]])
    # The unchanged full tape uses a new reduction context identifier. This is
    # the real source golden's trace, not a claim of a new native execution.
    document["dataset_id"] = materialized.replay_input.dataset_id
    result = build_replay_result(document)
    return source, prepared, result


@pytest.mark.parametrize("kind", ["success", "failure"])
def test_reduction_intent_and_outcome_roundtrip_in_original_protocol_slots(tmp_path, kind):
    _source, prepared, result = context()
    owner = prepared.materialization.source.validation.protocol
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(owner)
    intent = build_reduction_intent(prepared.materialization)
    objects = (prepared.recipe.canonical_bytes, prepared.materialization.canonical_bytes,
               prepared.artifacts["normalized"])
    assert ledger.bind_intent(reservation, intent.canonical_bytes, artifacts=objects) == intent.intent_id
    assert ledger.get_intent(reservation.attempt_id) == intent.canonical_bytes
    if kind == "success":
        audit = ReductionStateAudit(prepared.materialization, result)
        receipt = build_reduction_run_receipt(
            {
                "kind": "reduction_run_receipt_v1", "schema_version": 1,
                "attempt": reservation.document, "protocol_id": owner.protocol_id,
                "claim_revision_id": owner.claim_revision_id, "scope": intent.document["scope"],
                "intent": intent.document, "execution_status": result.document["execution_status"],
                "bindings": {"replay_result_sha256": digest(result.canonical_bytes),
                             "state_audit_sha256": audit.audit_id},
            }
        )
        outcome, artifacts = receipt.canonical_bytes, (result.canonical_bytes, audit.canonical_bytes)
        assert load_reduction_run_receipt(outcome).intent_id == intent.intent_id
    else:
        outcome = build_reduction_failure(reservation, intent, "native_timeout", "Observed timeout")
        artifacts = ()
        assert load_reduction_failure(outcome)["protocol_id"] == owner.protocol_id
    outcome_id = ledger.publish(reservation, outcome, artifacts=artifacts)
    reopened = LocalAttemptLedger(tmp_path, create=False)
    assert reopened.get_reservation(reservation.attempt_id) == reservation
    assert reopened.get_intent(reservation.attempt_id) == intent.canonical_bytes
    assert reopened.get_outcome(reservation.attempt_id) == outcome
    assert reopened.read_artifact(outcome_id) == outcome
    assert reopened.publish(reservation, outcome, artifacts=artifacts) == outcome_id
    for _ in range(2):
        reopened.reserve(owner)
    with pytest.raises(AttemptBudgetExceededError):
        reopened.reserve(owner)


def test_reduction_outcome_requires_exact_durable_intent_and_cannot_replace_terminal(tmp_path):
    _source, prepared, _result = context()
    owner = prepared.materialization.source.validation.protocol
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(owner)
    intent = build_reduction_intent(prepared.materialization)
    failure = build_reduction_failure(reservation, intent, "native_timeout", "First failure")
    with pytest.raises(AttemptLedgerError, match="exact durable intent"):
        ledger.publish(reservation, failure)
    assert ledger.get_outcome(reservation.attempt_id) is None
    ledger.bind_intent(reservation, intent.canonical_bytes)
    ledger.publish(reservation, failure)
    changed = build_reduction_failure(reservation, intent, "native_timeout", "Different failure")
    with pytest.raises(AttemptLedgerError, match="different content"):
        ledger.publish(reservation, changed)
    assert ledger.get_outcome(reservation.attempt_id) == failure


@pytest.mark.parametrize("attack", ["owner", "execution_flag", "unknown_kind"])
def test_reduction_intent_routing_preserves_strict_owner_and_static_flags(tmp_path, attack):
    _source, prepared, _result = context()
    owner = prepared.materialization.source.validation.protocol
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(owner)
    intent = build_reduction_intent(prepared.materialization).document
    if attack == "owner":
        intent["protocol_id"] = "0" * 64
    elif attack == "execution_flag":
        intent["flags"]["from_origin_prefix_replayed"] = True
    else:
        intent["kind"] = "unrecognized_reduction_execution_intent_v1"
    with pytest.raises(AttemptLedgerError):
        ledger.bind_intent(reservation, canonical(intent))
    assert ledger.get_intent(reservation.attempt_id) is None
    assert ledger.get_outcome(reservation.attempt_id) is None


def test_baseline_outcome_cannot_finalize_reduction_intent(tmp_path):
    _source, prepared, _result = context()
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(prepared.materialization.source.validation.protocol)
    ledger.bind_intent(reservation, build_reduction_intent(prepared.materialization).canonical_bytes)
    baseline_failure = canonical(
        {"kind": "replay_attempt_failure_v1", "schema_version": 1,
         "attempt": reservation.document, "protocol_id": reservation.protocol_id,
         "error": {"code": "native_timeout", "message": "Baseline envelope is wrong"}}
    )
    with pytest.raises(AttemptLedgerError, match="cannot publish baseline"):
        ledger.publish(reservation, baseline_failure)
    assert ledger.get_outcome(reservation.attempt_id) is None
