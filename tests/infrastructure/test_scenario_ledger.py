"""Scenario intent publication precedes execution and cannot change attempt type."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, get_ident

import pytest

from tickwitness.application.scenarios import validate_scenario_contracts
from tickwitness.domain.assumptions.derivation import DerivedReplayView
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.evidence.scenario_records import (
    build_scenario_failure,
    build_scenario_intent,
    load_scenario_intent,
)
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    load_executable_protocol,
)
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
    LocalAttemptLedger,
)


def bound_protocol(case) -> ExecutableProtocol:
    stored = case.registry.get(case.frozen.protocol_id)
    return load_executable_protocol(stored.canonical_bytes)


def fixture(case):
    examples = Path(__file__).resolve().parents[2] / "examples"
    checked = validate_scenario_contracts(
        case.frozen.protocol_id,
        (examples / "assumption-request.json").read_bytes(),
        (examples / "scenario-request.json").read_bytes(),
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
    )
    view = DerivedReplayView(checked.validation)
    return view, build_scenario_intent(view)


def legacy_failure(reservation) -> bytes:
    return canonical(
        {
            "kind": "replay_attempt_failure_v1",
            "schema_version": 1,
            "attempt": reservation.document,
            "protocol_id": reservation.protocol_id,
            "error": {"code": "native_failure", "message": "Original baseline failure"},
        }
    )


def test_intent_is_optional_for_legacy_roots_and_reading_never_creates_it(experiment_case) -> None:
    case = experiment_case
    ledger = LocalAttemptLedger(case.root / "runs")
    reservation = ledger.reserve(bound_protocol(case))
    assert ledger.get_intent(reservation.attempt_id) is None
    assert not (case.root / "runs" / "intents").exists()
    ledger.publish(reservation, legacy_failure(reservation))
    assert ledger.get_outcome(reservation.attempt_id) == legacy_failure(reservation)
    assert not (case.root / "runs" / "intents").exists()


def test_intent_roundtrip_idempotency_failure_closure_and_same_budget(experiment_case) -> None:
    case = experiment_case
    view, intent = fixture(case)
    ledger = LocalAttemptLedger(case.root / "runs")
    protocol = bound_protocol(case)
    reservation = ledger.reserve(protocol)
    artifacts = (view.canonical_bytes, view.replay_input.normalized_bytes)
    assert (
        ledger.bind_intent(reservation, intent.canonical_bytes, artifacts=artifacts)
        == intent.intent_id
    )
    assert ledger.get_intent(reservation.attempt_id) == intent.canonical_bytes
    assert ledger.get_outcome(reservation.attempt_id) is None
    assert ledger.read_artifact(intent.intent_id) == intent.canonical_bytes
    for artifact in artifacts:
        assert ledger.read_artifact(digest(artifact)) == artifact
    failure = build_scenario_failure(reservation, intent, "engine_timeout", "Worker timeout")
    assert ledger.publish(reservation, failure) == digest(failure)
    assert ledger.get_outcome(reservation.attempt_id) == failure
    assert ledger.bind_intent(reservation, intent.canonical_bytes) == intent.intent_id
    assert ledger.publish(reservation, failure) == digest(failure)
    ledger.reserve(protocol)
    with pytest.raises(AttemptBudgetExceededError):
        ledger.reserve(protocol)


def test_scenario_outcome_requires_preexisting_exact_intent(experiment_case) -> None:
    case = experiment_case
    _, intent = fixture(case)
    ledger = LocalAttemptLedger(case.root / "runs")
    reservation = ledger.reserve(bound_protocol(case))
    failure = build_scenario_failure(reservation, intent, "native_failure", "Original failure")
    with pytest.raises(AttemptLedgerError, match="durable intent"):
        ledger.publish(reservation, failure)
    assert ledger.get_outcome(reservation.attempt_id) is None
    ledger.bind_intent(reservation, intent.canonical_bytes)
    changed = intent.document
    changed["bindings"]["scenario_id"] = "0" * 64
    other = load_scenario_intent(canonical(changed))
    with pytest.raises(AttemptLedgerError, match="different immutable intent"):
        ledger.bind_intent(reservation, other.canonical_bytes)
    with pytest.raises(AttemptLedgerError, match="durable intent"):
        ledger.publish(reservation, build_scenario_failure(reservation, other, "failed", "Failure"))
    with pytest.raises(AttemptLedgerError, match="baseline outcomes"):
        ledger.publish(reservation, legacy_failure(reservation))


def test_finalized_baseline_attempt_cannot_gain_a_scenario_intent(experiment_case) -> None:
    case = experiment_case
    _, intent = fixture(case)
    ledger = LocalAttemptLedger(case.root / "runs")
    reservation = ledger.reserve(bound_protocol(case))
    ledger.publish(reservation, legacy_failure(reservation))
    with pytest.raises(AttemptLedgerError, match="after an outcome"):
        ledger.bind_intent(reservation, intent.canonical_bytes)
    assert ledger.get_intent(reservation.attempt_id) is None


def test_baseline_publication_racing_intent_bind_cannot_commit_both(experiment_case) -> None:
    case = experiment_case
    _, intent = fixture(case)
    ledger = LocalAttemptLedger(case.root / "runs")
    reservation = ledger.reserve(bound_protocol(case))
    barrier = Barrier(2)

    def publish_baseline() -> bool:
        barrier.wait(timeout=5)
        try:
            ledger.publish(reservation, legacy_failure(reservation))
            return True
        except AttemptLedgerError:
            return False

    def bind_scenario() -> bool:
        barrier.wait(timeout=5)
        try:
            ledger.bind_intent(reservation, intent.canonical_bytes)
            return True
        except AttemptLedgerError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(publish_baseline)
        second = executor.submit(bind_scenario)
        assert int(first.result(timeout=10)) + int(second.result(timeout=10)) == 1
    if ledger.get_intent(reservation.attempt_id) is None:
        assert ledger.get_outcome(reservation.attempt_id) == legacy_failure(reservation)
    else:
        assert ledger.get_outcome(reservation.attempt_id) is None


def test_reader_does_not_keep_stale_missing_intent_across_outcome_commit(
    experiment_case, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    _, intent = fixture(case)
    root = case.root / "runs"
    ledger = LocalAttemptLedger(root)
    reservation = ledger.reserve(bound_protocol(case))
    failure = build_scenario_failure(reservation, intent, "native_failure", "Original failure")
    paused, release = Event(), Event()
    outcome_inode = (root / "outcomes").stat().st_ino
    original = ledger._read
    reader_thread = []

    def read(directory, name, limit, **kwargs):
        if (
            reader_thread
            and get_ident() == reader_thread[0]
            and name == f"{reservation.attempt_id}.json"
            and os.fstat(directory).st_ino == outcome_inode
        ):
            paused.set()
            assert release.wait(timeout=5)
        return original(directory, name, limit, **kwargs)

    def reader():
        reader_thread.append(get_ident())
        return ledger.get_outcome(reservation.attempt_id)

    monkeypatch.setattr(ledger, "_read", read)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(reader)
        try:
            assert paused.wait(timeout=5)
            ledger.bind_intent(reservation, intent.canonical_bytes)
            ledger.publish(reservation, failure)
        finally:
            release.set()
        assert result.result(timeout=5) == failure


def test_intent_commit_failure_consumes_slot_and_preserves_only_cas_orphan(
    experiment_case, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    _, intent = fixture(case)
    root = case.root / "runs"
    ledger = LocalAttemptLedger(root)
    protocol = bound_protocol(case)
    reservation = ledger.reserve(protocol)
    original = os.link

    def fail(source, destination, **kwargs):
        if destination == f"{reservation.attempt_id}.json":
            raise OSError("Injected intent commit failure")
        return original(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(AttemptLedgerError, match="intent commit failure"):
        ledger.bind_intent(reservation, intent.canonical_bytes)
    assert ledger.get_intent(reservation.attempt_id) is None
    assert ledger.read_artifact(intent.intent_id) == intent.canonical_bytes
    assert ledger.get_outcome(reservation.attempt_id) is None
    ledger.reserve(protocol)
    with pytest.raises(AttemptBudgetExceededError):
        ledger.reserve(protocol)


@pytest.mark.parametrize("target", ["mapping", "cas"])
@pytest.mark.parametrize("mutation", ["corrupt", "symlink", "fifo", "missing"])
def test_unsafe_intent_or_missing_closure_is_rejected(experiment_case, target, mutation) -> None:
    case = experiment_case
    _, intent = fixture(case)
    root = case.root / "runs"
    ledger = LocalAttemptLedger(root)
    reservation = ledger.reserve(bound_protocol(case))
    ledger.bind_intent(reservation, intent.canonical_bytes)
    failure = build_scenario_failure(reservation, intent, "native_failure", "Original failure")
    ledger.publish(reservation, failure)
    path = (
        root / "intents" / f"{reservation.attempt_id}.json"
        if target == "mapping"
        else root / "objects" / "sha256" / intent.intent_id
    )
    path.unlink()
    if mutation == "corrupt":
        path.write_bytes(b"corrupt")
    elif mutation == "symlink":
        outside = case.root / "outside"
        outside.write_bytes(intent.canonical_bytes)
        path.symlink_to(outside)
    elif mutation == "fifo":
        os.mkfifo(path)
    with pytest.raises(AttemptLedgerError):
        ledger.get_outcome(reservation.attempt_id)


def test_intent_directory_symlink_is_not_followed(experiment_case) -> None:
    case = experiment_case
    _, intent = fixture(case)
    root = case.root / "runs"
    ledger = LocalAttemptLedger(root)
    reservation = ledger.reserve(bound_protocol(case))
    outside = case.root / "outside"
    outside.mkdir()
    (root / "intents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(AttemptLedgerError):
        ledger.bind_intent(reservation, intent.canonical_bytes)
    assert list(outside.iterdir()) == []
