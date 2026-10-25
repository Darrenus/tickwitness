"""Real attempt budget races, interrupted publication and immutable outcome checks."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import cast

import pytest

from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    build_run_receipt,
    canonical,
    digest,
)
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    build_executable_protocol,
)
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
    AttemptNotFoundError,
    LocalAttemptLedger,
)


def protocol(attempts: int = 3, wall: int = 17) -> ExecutableProtocol:
    spec = json.loads(
        (Path(__file__).resolve().parents[2] / "examples" / "replay-spec.json").read_bytes()
    )
    return build_executable_protocol(
        canonical(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Original attempt ledger fixture",
                    "hypothesis": "Synthetic marked PnL is positive under the bound model.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "0",
                    "unit": "USD",
                },
                "replay_spec": spec,
                "budget": {"max_attempts": attempts, "max_wall_seconds": wall, "max_events": 100},
            }
        ),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
    )


def failure(
    reservation: AttemptReservation, *, message: str = "Original injected failure"
) -> bytes:
    return canonical(
        {
            "kind": "replay_attempt_failure_v1",
            "schema_version": 1,
            "attempt": reservation.document,
            "protocol_id": reservation.protocol_id,
            "error": {"code": "native_timeout", "message": message},
        }
    )


def receipt(reservation: AttemptReservation) -> bytes:
    return build_run_receipt(
        {
            "kind": "research_run_receipt_v1",
            "schema_version": 1,
            "attempt": reservation.document,
            "protocol_id": reservation.protocol_id,
            "claim_revision_id": protocol().claim_revision_id,
            "execution_status": "completed",
            "scope": {
                "phase": "development",
                "scenario_id": "baseline_v1",
                "search_performed": False,
            },
            "bindings": {
                "dataset_id": "a" * 64,
                "data_sha256": "b" * 64,
                "replay_spec_id": "c" * 64,
                "replay_result_sha256": "d" * 64,
                "evaluation_sha256": "e" * 64,
            },
        }
    ).canonical_bytes


def slot(root: Path, reservation: AttemptReservation) -> Path:
    return root / "slots" / reservation.protocol_id / f"{reservation.attempt_index:04}.json"


def test_reserve_roundtrip_bound_budget_and_no_refund_when_unfinalized(tmp_path: Path) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    bound = protocol(2, 13)
    first, second = ledger.reserve(bound), ledger.reserve(bound)
    assert (first.attempt_index, second.attempt_index) == (1, 2)
    assert first.attempt_id != second.attempt_id
    assert first.protocol_id == bound.protocol_id
    assert first.document["max_wall_seconds"] == 13
    assert ledger.get_reservation(first.attempt_id) == first
    assert ledger.get_outcome(first.attempt_id) is None
    assert ledger.read_artifact(first.attempt_id) == first.canonical_bytes
    assert slot(tmp_path, first).read_bytes() == first.canonical_bytes
    assert (
        slot(tmp_path, first).stat().st_ino
        == (tmp_path / "objects" / "sha256" / first.attempt_id).stat().st_ino
    )
    with pytest.raises(AttemptBudgetExceededError):
        LocalAttemptLedger(tmp_path, create=False).reserve(bound)
    # Budget is per immutable protocol ID, not a statistical strategy family.
    assert ledger.reserve(protocol(3, 13)).attempt_index == 1


@pytest.mark.parametrize("round_id", range(3))
def test_concurrent_fresh_reservations_cannot_exceed_protocol_budget(
    tmp_path: Path, round_id: int
) -> None:
    root = tmp_path / str(round_id) / "nested" / "ledger"
    bound, barrier = protocol(3), Barrier(10)

    def together() -> AttemptReservation | None:
        barrier.wait(timeout=5)
        try:
            return LocalAttemptLedger(root).reserve(bound)
        except AttemptBudgetExceededError:
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: together(), range(10)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 3
    assert {result.attempt_index for result in winners} == {1, 2, 3}
    assert len({result.attempt_id for result in winners}) == 3
    ledger = LocalAttemptLedger(root, create=False)
    for result in winners:
        assert ledger.get_reservation(result.attempt_id) == result
    assert len(list((root / "slots" / bound.protocol_id).iterdir())) == 3


@pytest.mark.parametrize("kind", ["success", "failure"])
def test_publish_roundtrip_artifacts_and_identical_repeat_is_idempotent(
    tmp_path: Path, kind: str
) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol(1))
    outcome = receipt(reservation) if kind == "success" else failure(reservation)
    artifact = b"Original opaque replay artifact; schema audited by application"
    identity = ledger.publish(reservation, outcome, artifacts=(artifact,))
    assert identity == digest(outcome)
    assert ledger.read_artifact(identity) == outcome
    assert ledger.read_artifact(digest(artifact)) == artifact
    assert ledger.get_outcome(reservation.attempt_id) == outcome
    assert ledger.publish(reservation, outcome, artifacts=(artifact,)) == identity
    assert ledger.get_outcome(reservation.attempt_id) == outcome
    with pytest.raises(AttemptBudgetExceededError):
        ledger.reserve(protocol(1))


def test_different_terminal_outcome_can_never_overwrite_first(tmp_path: Path) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol())
    first, second = failure(reservation), failure(reservation, message="Conflicting outcome")
    ledger.publish(reservation, first)
    with pytest.raises(AttemptLedgerError, match="different content"):
        ledger.publish(reservation, second)
    assert ledger.get_outcome(reservation.attempt_id) == first


def test_competing_terminal_outcomes_have_one_commit_winner(tmp_path: Path) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol())
    barrier = Barrier(8)

    def together(index: int) -> bytes | None:
        outcome = failure(reservation, message=f"Original competing outcome {index}")
        barrier.wait(timeout=5)
        try:
            ledger.publish(reservation, outcome)
            return outcome
        except AttemptLedgerError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(together, range(8)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert ledger.get_outcome(reservation.attempt_id) == winners[0]


def test_reservation_cas_orphan_is_not_a_committed_attempt(tmp_path: Path) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    old = ledger.reserve(protocol(1))
    slot(tmp_path, old).unlink()  # Simulate durable CAS preceding a failed slot commit.
    with pytest.raises(AttemptNotFoundError, match="closure"):
        ledger.get_reservation(old.attempt_id)
    with pytest.raises(AttemptNotFoundError):
        ledger.publish(old, failure(old))
    replacement = ledger.reserve(protocol(1))
    assert replacement.attempt_index == 1 and replacement.attempt_id != old.attempt_id
    with pytest.raises(AttemptLedgerError):
        ledger.get_reservation(old.attempt_id)


def test_slot_commit_then_error_still_consumes_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    original_link = os.link

    def link_then_fail(source: str, destination: str, **kwargs: object) -> None:
        original_link(source, destination, **kwargs)  # type: ignore[arg-type]
        if destination == "0001.json":
            raise OSError("Injected post-slot-commit failure")

    monkeypatch.setattr(os, "link", link_then_fail)
    with pytest.raises(AttemptLedgerError, match="post-slot-commit"):
        ledger.reserve(protocol(1))
    monkeypatch.setattr(os, "link", original_link)
    with pytest.raises(AttemptBudgetExceededError):
        ledger.reserve(protocol(1))
    raw = next((tmp_path / "slots" / protocol(1).protocol_id).iterdir()).read_bytes()
    assert ledger.get_outcome(digest(raw)) is None


def test_failed_outcome_commit_keeps_reserved_state_and_durable_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol(1))
    original_link = os.link

    def fail_outcome(source: str, destination: str, **kwargs: object) -> None:
        if destination == f"{reservation.attempt_id}.json":
            raise OSError("Injected final outcome link failure")
        original_link(source, destination, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "link", fail_outcome)
    artifact = b"Original durable artifact before failed final commit"
    with pytest.raises(AttemptLedgerError, match="final outcome"):
        ledger.publish(reservation, failure(reservation), artifacts=(artifact,))
    assert ledger.read_artifact(digest(artifact)) == artifact
    assert ledger.get_outcome(reservation.attempt_id) is None
    assert list((tmp_path / "outcomes").iterdir()) == []
    with pytest.raises(AttemptBudgetExceededError):
        ledger.reserve(protocol(1))


def test_unpublished_outcome_is_never_partially_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol())
    ready, release = Event(), Event()
    original_link = os.link

    def paused_link(source: str, destination: str, **kwargs: object) -> None:
        if destination == f"{reservation.attempt_id}.json":
            ready.set()
            assert release.wait(timeout=5)
        original_link(source, destination, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "link", paused_link)
    outcome = failure(reservation)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(ledger.publish, reservation, outcome)
        try:
            assert ready.wait(timeout=5)
            assert ledger.get_outcome(reservation.attempt_id) is None
            assert ledger.read_artifact(digest(outcome)) == outcome
        finally:
            release.set()
        assert future.result(timeout=5) == digest(outcome)
    assert ledger.get_outcome(reservation.attempt_id) == outcome


@pytest.mark.parametrize("target", ["slot", "reservation", "outcome", "outcome_cas", "artifact"])
def test_corruption_is_detected_and_never_repaired(tmp_path: Path, target: str) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol(2))
    artifact, outcome = b"Original opaque artifact", failure(reservation)
    ledger.publish(reservation, outcome, artifacts=(artifact,))
    path = {
        "slot": slot(tmp_path, reservation),
        "reservation": tmp_path / "objects" / "sha256" / reservation.attempt_id,
        "outcome": tmp_path / "outcomes" / f"{reservation.attempt_id}.json",
        "outcome_cas": tmp_path / "objects" / "sha256" / digest(outcome),
        "artifact": tmp_path / "objects" / "sha256" / digest(artifact),
    }[target]
    path.write_bytes(b"corrupted")
    with pytest.raises(AttemptLedgerError):
        if target in {"slot", "reservation"}:
            ledger.get_reservation(reservation.attempt_id)
        elif target == "artifact":
            ledger.read_artifact(digest(artifact))
        else:
            ledger.get_outcome(reservation.attempt_id)
    with pytest.raises(AttemptLedgerError):
        ledger.publish(reservation, outcome, artifacts=(artifact,))
    assert path.read_bytes() == b"corrupted"


def test_missing_occupied_cas_is_corruption_and_does_not_enable_another_attempt(
    tmp_path: Path,
) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol(2))
    (tmp_path / "objects" / "sha256" / reservation.attempt_id).unlink()
    with pytest.raises(AttemptLedgerError, match="CAS closure"):
        ledger.reserve(protocol(2))
    assert len(list((tmp_path / "slots" / reservation.protocol_id).iterdir())) == 1


def test_outcome_missing_cas_is_corruption_not_reserved_unfinalized(tmp_path: Path) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol())
    outcome = failure(reservation)
    ledger.publish(reservation, outcome)
    (tmp_path / "objects" / "sha256" / digest(outcome)).unlink()
    with pytest.raises(AttemptLedgerError, match="CAS closure"):
        ledger.get_outcome(reservation.attempt_id)


@pytest.mark.parametrize("target", ["slot", "cas", "outcome"])
@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversize"])
def test_unsafe_evidence_is_rejected_without_following_or_blocking(
    tmp_path: Path, target: str, kind: str
) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol())
    ledger.publish(reservation, failure(reservation))
    path = {
        "slot": slot(tmp_path, reservation),
        "cas": tmp_path / "objects" / "sha256" / reservation.attempt_id,
        "outcome": tmp_path / "outcomes" / f"{reservation.attempt_id}.json",
    }[target]
    outside = tmp_path / "outside"
    original = path.read_bytes()
    path.unlink()
    if kind == "symlink":
        outside.write_bytes(original)
        path.symlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.write_bytes(b"x" * (16 * 1024 + 1))
    with pytest.raises(AttemptLedgerError):
        ledger.get_outcome(reservation.attempt_id)
    if kind == "symlink":
        assert outside.read_bytes() == original


@pytest.mark.parametrize(
    "component", ["objects", "objects/sha256", "slots", "outcomes", "protocol_slots"]
)
def test_directory_symlinks_are_rejected(tmp_path: Path, component: str) -> None:
    root = tmp_path / "ledger"
    ledger = LocalAttemptLedger(root)
    reservation = ledger.reserve(protocol())
    path = (
        root / component
        if component != "protocol_slots"
        else root / "slots" / reservation.protocol_id
    )
    outside = tmp_path / "outside"
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AttemptLedgerError):
        ledger.get_reservation(reservation.attempt_id)


def test_missing_read_only_ledger_and_unknown_reads_create_nothing(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    with pytest.raises(AttemptNotFoundError):
        LocalAttemptLedger(root, create=False)
    assert not root.exists()
    ledger = LocalAttemptLedger(tmp_path / "existing")
    before = {path: path.stat().st_mtime_ns for path in (tmp_path / "existing").rglob("*")}
    with pytest.raises(AttemptNotFoundError):
        ledger.get_reservation("0" * 64)
    with pytest.raises(AttemptNotFoundError):
        ledger.read_artifact("0" * 64)
    assert {path: path.stat().st_mtime_ns for path in (tmp_path / "existing").rglob("*")} == before


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63])
def test_ids_cannot_be_paths(tmp_path: Path, identity: str) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    with pytest.raises(AttemptLedgerError):
        ledger.get_reservation(identity)
    with pytest.raises(AttemptLedgerError):
        ledger.read_artifact(identity)


@pytest.mark.parametrize("mutation", ["attempt", "protocol_id", "extra", "error", "schema", "kind"])
def test_outcome_must_bind_complete_reservation_and_strict_envelope(
    tmp_path: Path, mutation: str
) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol())
    document = json.loads(failure(reservation))
    if mutation == "attempt":
        document["attempt"]["nonce"] = "0" * 32
    elif mutation == "protocol_id":
        document["protocol_id"] = "c" * 64
    elif mutation == "error":
        document["error"] = {"code": "timeout", "message": "", "stack": "extra"}
    elif mutation == "schema":
        document["schema_version"] = True
    elif mutation == "kind":
        document["kind"] = "unknown"
    else:
        document["execution_ready"] = True
    with pytest.raises(AttemptLedgerError):
        ledger.publish(reservation, canonical(document))
    assert ledger.get_outcome(reservation.attempt_id) is None
    assert list((tmp_path / "outcomes").iterdir()) == []


@pytest.mark.parametrize(
    "artifacts",
    [[b"list"], (b"",), (bytearray(b"mutable"),), (b"x",) * 17, (b"x" * (16 * 1024 * 1024 + 1),)],
)
def test_artifact_bounds_apply_before_any_publication(tmp_path: Path, artifacts: object) -> None:
    ledger = LocalAttemptLedger(tmp_path)
    reservation = ledger.reserve(protocol())
    before = set((tmp_path / "objects" / "sha256").iterdir())
    with pytest.raises(AttemptLedgerError):
        ledger.publish(
            reservation, failure(reservation), artifacts=cast("tuple[bytes, ...]", artifacts)
        )
    assert set((tmp_path / "objects" / "sha256").iterdir()) == before


@pytest.mark.parametrize("limit", [0, True, 16 * 1024 * 1024 + 1])
def test_artifact_read_limit_is_bounded(tmp_path: Path, limit: int) -> None:
    with pytest.raises(AttemptLedgerError):
        LocalAttemptLedger(tmp_path).read_artifact("0" * 64, max_bytes=limit)
