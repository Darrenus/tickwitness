"""Persistence order and failure semantics of the actual tagged application boundary."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import ProtocolRunError, freeze_experiment
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_queue_execution import (
    freeze_tagged_queue, inspect_tagged_queue, inspect_tagged_queue_run,
    run_tagged_queue_model, run_tagged_queue_pair,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError, digest
from tickwitness.domain.evidence.tagged_queue_records import load_tagged_queue_intent
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS
from tickwitness.infrastructure.attempt_ledger import AttemptBudgetExceededError, LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def tagged_app(tmp_path):
    data = LocalDatasetStore(tmp_path / "data")
    development, confirmation = (import_events((EXAMPLES / name).read_bytes(), lambda: data).dataset_id
                                 for name in ("queue-observations.jsonl", "replay-confirmation.jsonl"))
    sources = LocalExecutableProtocolRegistry(tmp_path / "registry")
    source = freeze_experiment((EXAMPLES / "experiment-request.json").read_bytes(),
        development_dataset_id=development, confirmation_dataset_id=confirmation,
        datasets_factory=lambda: data, registry_factory=lambda: sources)
    registry = LocalTaggedQueueRegistry(tmp_path / "registry", create=True)
    frozen = freeze_tagged_queue(source.protocol_id, (EXAMPLES / "tagged-queue-request.json").read_bytes(),
        (EXAMPLES / "queue-constraint-request.json").read_bytes(), split="development",
        registry_factory=lambda: sources, datasets_factory=lambda: data, protocols_factory=lambda: registry)
    ledger = LocalAttemptLedger(tmp_path / "ledger")
    return SimpleNamespace(protocol=frozen.protocol, data=data, registry=registry, ledger=ledger,
        factories={"protocols_factory": lambda: registry, "datasets_factory": lambda: data, "ledger_factory": lambda: ledger})


def test_worker_construction_follows_immutable_intent_and_all_source_artifacts(tagged_app):
    case = tagged_app
    called = []

    def unavailable(timeout):
        called.append(timeout)
        reservations = case.ledger.list_reservations(case.protocol)
        assert len(reservations) == 1
        attempt = reservations[0]
        intent = load_tagged_queue_intent(case.ledger.get_intent(attempt.attempt_id))
        assert intent.protocol == case.protocol and intent.policy_id == TAGGED_POLICY_IDS[0]
        for raw in (case.protocol.canonical_bytes, case.protocol.source_protocol.canonical_bytes,
                    case.protocol.constraint.canonical_bytes):
            assert case.ledger.read_artifact(digest(raw)) == raw
        raise RuntimeError("Actual worker could not be constructed")

    with pytest.raises(ProtocolRunError, match="could not be constructed"):
        run_tagged_queue_model(case.protocol.protocol_id, TAGGED_POLICY_IDS[0], split="development",
                               replay_factory=unavailable, **case.factories)
    assert called == [30]
    report = inspect_tagged_queue(case.protocol.protocol_id, **case.factories)
    assert report["budget"]["consumed_attempts"] == 1
    assert report["attempts"][0]["outcome_kind"] == "tagged_queue_attempt_failure_v1"
    assert report["attempts"][0]["budget_consumed"] is True


def test_pair_stops_after_first_failure_and_shared_budget_does_not_refund(tagged_app):
    case = tagged_app
    calls = []

    def unavailable(timeout):
        calls.append(timeout)
        raise RuntimeError("No native runtime")

    for expected in (1, 2):
        result = run_tagged_queue_pair(case.protocol.protocol_id, split="development", replay_factory=unavailable, **case.factories)
        assert result["status"] == "failed" and result["runs"] == []
        assert len(result["failures"]) == 1
        assert result["failures"][0]["policy_id"] == TAGGED_POLICY_IDS[0]
        assert result["pending_policy_ids"] == [TAGGED_POLICY_IDS[1]]
        assert len(case.ledger.list_reservations(case.protocol)) == expected
    result = run_tagged_queue_pair(case.protocol.protocol_id, split="development", replay_factory=unavailable, **case.factories)
    assert result["failures"][0]["code"] == "attempt_budget_exhausted"
    assert result["failures"][0]["budget_consumed"] is False
    assert calls == [30, 30]
    with pytest.raises(AttemptBudgetExceededError):
        case.ledger.reserve(case.protocol)


def test_interruption_leaves_visible_consumed_slot_and_intent(tagged_app):
    case = tagged_app

    def interrupted(timeout):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_tagged_queue_model(case.protocol.protocol_id, TAGGED_POLICY_IDS[1], split="development",
                               replay_factory=interrupted, **case.factories)
    inspected = inspect_tagged_queue(case.protocol.protocol_id, **case.factories)
    assert inspected["budget"]["consumed_attempts"] == 1
    assert inspected["attempts"][0]["state"] == "reserved_unfinalized"
    assert inspected["attempts"][0]["policy_id"] == TAGGED_POLICY_IDS[1]


@pytest.mark.parametrize("function,args", [
    (freeze_tagged_queue, ("a" * 64, b"{}", b"{}")),
    (inspect_tagged_queue, ("a" * 64,)),
    (inspect_tagged_queue_run, ("a" * 64,)),
    (run_tagged_queue_model, ("a" * 64, TAGGED_POLICY_IDS[0])),
    (run_tagged_queue_pair, ("a" * 64,)),
])
def test_confirmation_refused_before_factories(function, args):
    def forbidden(*args):
        pytest.fail("Confirmation must be refused before any repository or worker")
    kwargs = {"split": "confirmation", "protocols_factory": forbidden, "datasets_factory": forbidden}
    if function is freeze_tagged_queue:
        kwargs["registry_factory"] = forbidden
    else:
        kwargs["ledger_factory"] = forbidden
    if function in (run_tagged_queue_model, run_tagged_queue_pair):
        kwargs["replay_factory"] = forbidden
    with pytest.raises(ConfirmationAccessDenied):
        function(*args, **kwargs)


def test_wrong_policy_is_rejected_before_consuming_attempt(tagged_app):
    with pytest.raises((EvidenceValidationError, ValueError)):
        run_tagged_queue_model(tagged_app.protocol.protocol_id, "cancel_front_first_v1", split="development",
                               replay_factory=lambda _: pytest.fail("No worker"), **tagged_app.factories)
    assert tagged_app.ledger.list_reservations(tagged_app.protocol) == ()
