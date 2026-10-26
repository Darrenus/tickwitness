"""Persistent queue slots share a family budget and cannot change execution kind."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from tickwitness.domain.assumptions.derivation import CLOCK_PROFILE_ID
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.queue_records import (
    QueueAttemptReservation,
    build_queue_failure,
    build_queue_intent,
    build_queue_run_receipt,
)
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.evidence.scenario_records import SCENARIO_SCOPE, load_scenario_intent
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.queue_family import (
    build_queue_family_protocol,
    load_queue_family_protocol,
)
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
    LocalAttemptLedger,
)

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


def legacy_failure(attempt):
    return canonical(
        {
            "kind": "replay_attempt_failure_v1",
            "schema_version": 1,
            "attempt": attempt.document,
            "protocol_id": attempt.protocol_id,
            "error": {"code": "native_failure", "message": "Legacy baseline failure"},
        }
    )


def scenario_intent(owner_id):
    return load_scenario_intent(
        canonical(
            {
                "kind": "scenario_execution_intent_v1",
                "schema_version": 1,
                "protocol_id": owner_id,
                "claim_revision_id": "c" * 64,
                "scope": dict(SCENARIO_SCOPE),
                "bindings": {
                    name: "d" * 64
                    for name in (
                        "development_dataset_id", "source_normalized_sha256", "replay_spec_id",
                        "assumption_id", "scenario_id", "derived_view_id", "derived_normalized_sha256",
                    )
                },
                "clock_profile_id": CLOCK_PROFILE_ID,
            }
        )
    )


def test_two_policies_consume_one_shared_persistent_family_budget(tmp_path) -> None:
    owner = family()
    root = tmp_path / "runs"
    ledger = LocalAttemptLedger(root)
    front = ledger.reserve(owner)
    assert isinstance(front, QueueAttemptReservation)
    front_intent = build_queue_intent(owner, "cancel_front_first_v1")
    ledger.bind_intent(front, front_intent.canonical_bytes)
    failed = build_queue_failure(front, front_intent, "native_timeout", "Worker failed")
    ledger.publish(front, failed)
    back = ledger.reserve(load_queue_family_protocol(owner.canonical_bytes))
    back_intent = build_queue_intent(owner, "cancel_back_first_v1")
    ledger.bind_intent(back, back_intent.canonical_bytes)
    # A missing terminal survives restart as consumed, reserved and unfinalized.
    reopened = LocalAttemptLedger(root, create=False)
    assert reopened.list_reservations(owner) == (front, back)
    assert reopened.get_intent(front.attempt_id) == front_intent.canonical_bytes
    assert reopened.get_outcome(front.attempt_id) == failed
    assert reopened.get_intent(back.attempt_id) == back_intent.canonical_bytes
    assert reopened.get_outcome(back.attempt_id) is None
    with pytest.raises(AttemptBudgetExceededError):
        reopened.reserve(owner)
    # The source v2 budget is a different explicit owner, never a second policy budget.
    assert reopened.list_reservations(owner.source_protocol) == ()
    source = reopened.reserve(owner.source_protocol)
    assert source.protocol_id == owner.source_protocol.protocol_id
    assert not isinstance(source, QueueAttemptReservation)


def test_racing_policies_compete_for_the_same_last_slot(tmp_path) -> None:
    owner = family()
    ledger = LocalAttemptLedger(tmp_path / "runs")
    ledger.reserve(owner)
    barrier = Barrier(2)

    def reserve(policy):
        barrier.wait(timeout=5)
        try:
            attempt = ledger.reserve(owner)
        except AttemptBudgetExceededError:
            return None
        ledger.bind_intent(attempt, build_queue_intent(owner, policy).canonical_bytes)
        return attempt

    with ThreadPoolExecutor(max_workers=2) as executor:
        front = executor.submit(reserve, "cancel_front_first_v1")
        back = executor.submit(reserve, "cancel_back_first_v1")
        results = [front.result(timeout=10), back.result(timeout=10)]
    assert sum(result is not None for result in results) == 1
    assert len(ledger.list_reservations(owner)) == 2
    winner = next(result for result in results if result is not None)
    assert winner.attempt_index == 2
    assert ledger.get_intent(winner.attempt_id) is not None


def test_queue_outcome_requires_its_exact_durable_policy_intent(tmp_path) -> None:
    owner = family()
    ledger = LocalAttemptLedger(tmp_path / "runs")
    attempt = ledger.reserve(owner)
    front = build_queue_intent(owner, "cancel_front_first_v1")
    back = build_queue_intent(owner, "cancel_back_first_v1")
    failed = build_queue_failure(attempt, front, "native_failure", "Worker failed")
    with pytest.raises(AttemptLedgerError, match="durable intent"):
        ledger.publish(attempt, failed)
    ledger.bind_intent(attempt, front.canonical_bytes)
    with pytest.raises(AttemptLedgerError, match="different immutable intent"):
        ledger.bind_intent(attempt, back.canonical_bytes)
    with pytest.raises(AttemptLedgerError, match="durable intent"):
        ledger.publish(attempt, build_queue_failure(attempt, back, "failed", "Failure"))
    assert ledger.publish(attempt, failed) == digest(failed)
    assert ledger.publish(attempt, failed) == digest(failed)
    assert ledger.bind_intent(attempt, front.canonical_bytes) == front.intent_id


def test_success_receipt_retains_result_evaluation_and_full_intent_closure(tmp_path) -> None:
    owner = family()
    ledger = LocalAttemptLedger(tmp_path / "runs")
    attempt = ledger.reserve(owner)
    intent = build_queue_intent(owner, "cancel_back_first_v1")
    ledger.bind_intent(attempt, intent.canonical_bytes, artifacts=(owner.canonical_bytes,))
    result, evaluation = b"queue result artifact", b"independent queue audit artifact"
    receipt = build_queue_run_receipt(
        {
            "kind": "queue_run_receipt_v1",
            "schema_version": 1,
            "attempt": attempt.document,
            "protocol_id": owner.family_id,
            "intent": intent.document,
            "execution_status": "incomplete",
            "bindings": {
                "replay_result_sha256": digest(result),
                "evaluation_sha256": digest(evaluation),
            },
        }
    )
    assert ledger.publish(attempt, receipt.canonical_bytes, artifacts=(result, evaluation)) == receipt.run_id
    assert ledger.get_outcome(attempt.attempt_id) == receipt.canonical_bytes
    assert ledger.read_artifact(intent.intent_id) == intent.canonical_bytes
    assert ledger.read_artifact(owner.family_id) == owner.canonical_bytes
    assert ledger.read_artifact(digest(result)) == result
    assert ledger.read_artifact(digest(evaluation)) == evaluation


def test_queue_and_legacy_reservations_intents_and_outcomes_cannot_be_mixed(tmp_path) -> None:
    owner = family()
    ledger = LocalAttemptLedger(tmp_path / "runs")
    queue = ledger.reserve(owner)
    old = ledger.reserve(owner.source_protocol)
    intent = build_queue_intent(owner, "cancel_front_first_v1")
    forged_scenario = scenario_intent(owner.family_id)
    with pytest.raises(AttemptLedgerError):
        ledger.bind_intent(queue, forged_scenario.canonical_bytes)
    with pytest.raises(AttemptLedgerError):
        ledger.bind_intent(old, intent.canonical_bytes)
    with pytest.raises(AttemptLedgerError, match="reserved execution owner"):
        ledger.publish(queue, legacy_failure(queue))
    queue_failure = build_queue_failure(queue, intent, "failure", "Queue failure")
    with pytest.raises(AttemptLedgerError, match="reserved execution owner"):
        ledger.publish(old, queue_failure)
    assert ledger.get_intent(queue.attempt_id) is None
    assert ledger.get_outcome(queue.attempt_id) is None
    assert ledger.publish(old, legacy_failure(old)) == digest(legacy_failure(old))


def test_racing_intent_binds_commit_only_one_policy(tmp_path) -> None:
    owner = family()
    ledger = LocalAttemptLedger(tmp_path / "runs")
    attempt = ledger.reserve(owner)
    barrier = Barrier(2)

    def bind(policy):
        intent = build_queue_intent(owner, policy)
        barrier.wait(timeout=5)
        try:
            ledger.bind_intent(attempt, intent.canonical_bytes)
            return intent
        except AttemptLedgerError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        front = executor.submit(bind, "cancel_front_first_v1")
        back = executor.submit(bind, "cancel_back_first_v1")
        results = [front.result(timeout=10), back.result(timeout=10)]
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    assert ledger.get_intent(attempt.attempt_id) == winner.canonical_bytes


def test_failed_intent_publication_never_refunds_family_slot(tmp_path, monkeypatch) -> None:
    owner = family()
    ledger = LocalAttemptLedger(tmp_path / "runs")
    attempt = ledger.reserve(owner)
    intent = build_queue_intent(owner, "cancel_front_first_v1")
    original = os.link

    def fail(source, destination, **kwargs):
        if destination == f"{attempt.attempt_id}.json":
            raise OSError("Injected queue intent commit failure")
        return original(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(AttemptLedgerError, match="intent commit failure"):
        ledger.bind_intent(attempt, intent.canonical_bytes)
    assert ledger.get_intent(attempt.attempt_id) is None
    assert ledger.get_outcome(attempt.attempt_id) is None
    assert ledger.read_artifact(intent.intent_id) == intent.canonical_bytes
    assert ledger.reserve(owner).attempt_index == 2
    with pytest.raises(AttemptBudgetExceededError):
        ledger.reserve(owner)


@pytest.mark.parametrize("owner_kind", ["family", "source"])
@pytest.mark.parametrize("mutation", ["identity", "budget_bool", "duck"])
def test_forged_budget_owner_is_rejected_before_namespace_creation(tmp_path, owner_kind, mutation) -> None:
    owner = family()
    owner = owner if owner_kind == "family" else owner.source_protocol
    original_id = owner.protocol_id
    ledger = LocalAttemptLedger(tmp_path / "runs")
    if mutation == "identity":
        object.__setattr__(owner, "protocol_id", "0" * 64)
    elif mutation == "budget_bool":
        document = owner.document
        document["budget"]["max_attempts"] = True
        object.__setattr__(owner, "canonical_bytes", canonical(document))
        object.__setattr__(owner, "protocol_id", digest(owner.canonical_bytes))
    else:
        owner = SimpleNamespace(
            protocol_id=owner.protocol_id, canonical_bytes=owner.canonical_bytes, document=owner.document
        )
    with pytest.raises(AttemptLedgerError):
        ledger.reserve(owner)
    with pytest.raises(AttemptLedgerError):
        ledger.list_reservations(owner)
    assert not (tmp_path / "runs" / "slots" / original_id).exists()


def test_listing_is_read_only_and_checks_committed_cas_closure(tmp_path) -> None:
    owner = family()
    root = tmp_path / "runs"
    ledger = LocalAttemptLedger(root)
    assert ledger.list_reservations(owner) == ()
    assert not (root / "slots" / owner.family_id).exists()
    attempt = ledger.reserve(owner)
    read_only = LocalAttemptLedger(root, create=False)
    assert read_only.list_reservations(owner) == (attempt,)
    assert not (root / "intents").exists()
    (root / "objects" / "sha256" / attempt.attempt_id).unlink()
    with pytest.raises(AttemptLedgerError, match="CAS closure"):
        read_only.list_reservations(owner)
