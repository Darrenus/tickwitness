"""Named candidate reservations consume the existing protocol's immutable slots."""

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
    LocalAttemptLedger,
)


def subject(case):
    return load_executable_protocol(case.registry.get(case.frozen.protocol_id).canonical_bytes)


def test_named_reservation_uses_original_budget_after_baseline(experiment_case):
    case = experiment_case
    protocol = subject(case)
    ledger = LocalAttemptLedger(case.root / "runs")
    first = ledger.reserve(protocol)
    second = ledger.reserve_with_nonce(protocol, "a" * 32)
    assert first.protocol_id == second.protocol_id == protocol.protocol_id
    assert first.attempt_index == 1 and second.attempt_index == 2
    assert second.document["nonce"] == "a" * 32
    assert second.document["kind"] == "replay_attempt_reservation_v1"
    assert second.document["max_wall_seconds"] == protocol.document["budget"]["max_wall_seconds"]
    with pytest.raises(AttemptBudgetExceededError):
        ledger.reserve_with_nonce(protocol, "b" * 32)
    assert ledger.list_reservations(protocol) == (first, second)


def test_committed_named_nonce_never_returns_an_old_slot_for_replay(experiment_case):
    case = experiment_case
    protocol = subject(case)
    ledger = LocalAttemptLedger(case.root / "runs")
    first = ledger.reserve_with_nonce(protocol, "a" * 32)
    with pytest.raises(AttemptLedgerError, match="already committed"):
        ledger.reserve_with_nonce(protocol, "a" * 32)
    assert ledger.list_reservations(protocol) == (first,)
    assert ledger.reserve(protocol).attempt_index == 2


def test_same_named_nonce_concurrency_consumes_only_one_slot(experiment_case):
    case = experiment_case
    protocol = subject(case)
    root = case.root / "runs"
    LocalAttemptLedger(root)
    barrier = Barrier(4)

    def allocate(_index):
        ledger = LocalAttemptLedger(root, create=False)
        barrier.wait()
        try:
            return ledger.reserve_with_nonce(protocol, "c" * 32)
        except AttemptLedgerError as error:
            return error

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(allocate, range(4)))
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert len(LocalAttemptLedger(root, create=False).list_reservations(protocol)) == 1
    assert all(
        "already committed" in str(item) for item in results if isinstance(item, Exception)
    )


def test_ordinary_and_named_reservations_compete_for_the_same_last_slot(experiment_case):
    case = experiment_case
    protocol = subject(case)
    root = case.root / "runs"
    ledger = LocalAttemptLedger(root)
    ledger.reserve(protocol)
    barrier = Barrier(2)

    def allocate(named):
        participant = LocalAttemptLedger(root, create=False)
        barrier.wait()
        try:
            return (
                participant.reserve_with_nonce(protocol, "d" * 32)
                if named else participant.reserve(protocol)
            )
        except AttemptBudgetExceededError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(allocate, (False, True)))
    assert sum(isinstance(item, AttemptBudgetExceededError) for item in results) == 1
    reservations = ledger.list_reservations(protocol)
    assert len(reservations) == 2
    assert {item.attempt_index for item in reservations} == {1, 2}


def test_slot_commit_followed_by_fsync_failure_is_recoverable_by_nonce(
    experiment_case, monkeypatch
):
    case = experiment_case
    protocol = subject(case)
    ledger = LocalAttemptLedger(case.root / "runs")
    original_link, original_sync = os.link, os.fsync
    committed = False

    def link(source, destination, **kwargs):
        nonlocal committed
        original_link(source, destination, **kwargs)
        if destination == "0001.json":
            committed = True

    def fsync(descriptor):
        nonlocal committed
        if committed and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            committed = False
            raise OSError("injected post-slot fsync failure")
        original_sync(descriptor)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(AttemptLedgerError, match="post-slot"):
        ledger.reserve_with_nonce(protocol, "e" * 32)
    observed = ledger.list_reservations(protocol)
    assert len(observed) == 1
    assert observed[0].document["nonce"] == "e" * 32
    assert ledger.get_outcome(observed[0].attempt_id) is None
    with pytest.raises(AttemptLedgerError, match="already committed"):
        ledger.reserve_with_nonce(protocol, "e" * 32)
    assert ledger.reserve(protocol).attempt_index == 2


@pytest.mark.parametrize("nonce", ["", "A" * 32, "f" * 31, "f" * 33, True, 1, None])
def test_invalid_named_nonce_does_not_create_lock_or_consume_budget(experiment_case, nonce):
    case = experiment_case
    ledger = LocalAttemptLedger(case.root / "runs")
    before = tuple((case.root / "runs").iterdir())
    with pytest.raises(AttemptLedgerError, match="nonce"):
        ledger.reserve_with_nonce(subject(case), nonce)
    assert tuple((case.root / "runs").iterdir()) == before
    assert ledger.list_reservations(subject(case)) == ()


def test_named_reservation_rejects_a_protocol_duck_type(experiment_case):
    case = experiment_case
    ledger = LocalAttemptLedger(case.root / "runs")
    with pytest.raises(AttemptLedgerError, match="ExecutableProtocol"):
        ledger.reserve_with_nonce(subject(case).document, "f" * 32)
    assert ledger.list_reservations(subject(case)) == ()


@pytest.mark.parametrize("attack", ["symlink", "fifo", "directory"])
def test_named_lock_rejects_non_regular_paths_without_blocking(experiment_case, attack):
    case = experiment_case
    ledger = LocalAttemptLedger(case.root / "runs")
    path = case.root / "runs" / ".search-reservation.lock"
    if attack == "symlink":
        target = case.root / "outside"
        target.write_bytes(b"unchanged")
        path.symlink_to(target)
    elif attack == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    with pytest.raises(AttemptLedgerError):
        ledger.reserve_with_nonce(subject(case), "a" * 32)
    assert ledger.list_reservations(subject(case)) == ()
