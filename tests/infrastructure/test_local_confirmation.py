"""Managed one-shot history: immutable declarations, bounded IO and no refunds."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.research_contracts.confirmation import (
    ConfirmationAlreadyExposed,
    ConfirmationExposure,
    ConfirmationProtocol,
    build_confirmation_exposure,
    build_confirmation_protocol,
    load_confirmation_exposure,
    origin_footprint,
)
from tickwitness.domain.research_contracts.protocols import build_frozen_protocol
from tickwitness.infrastructure import local_confirmation as local
from tickwitness.infrastructure.local_confirmation import (
    MAX_EXPOSURE_LEDGER_BYTES,
    ConfirmationNotFoundError,
    ConfirmationProtocolRecord,
    ConfirmationStoreError,
    LocalConfirmationExposureLedger,
    LocalConfirmationRegistry,
)


def _trade(trade_id: str = "original", **changes: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "trade",
        "source": "synthetic",
        "instrument": "EURUSD",
        "session": "session-one",
        "capture_seq": 1,
        "event_time_ns": 100,
        "receive_time_ns": 101,
        "trade_id": trade_id,
        "price_ticks": 100,
        "quantity_lots": 1,
        "aggressor_side": "sell",
        **changes,
    }


def _book(last: int, **changes: object) -> dict[str, object]:
    row = _trade()
    for field in ("trade_id", "price_ticks", "quantity_lots", "aggressor_side"):
        del row[field]
    return {
        **row,
        "type": "snapshot",
        "last_sequence": last,
        "bids": [[100, 2]],
        "asks": [[101, 2]],
        **changes,
    }


def _protocol(
    title: str = "Original confirmation",
    records: tuple[dict[str, object], ...] | None = None,
    *,
    source_title: str = "Original source",
) -> ConfirmationProtocol:
    source = build_frozen_protocol(
        canonical(
            {
                "schema_version": 1,
                "claim": {
                    "title": source_title,
                    "hypothesis": "Synthetic net marked PnL exceeds zero.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "0",
                    "unit": "USD",
                },
                "strategy_name": "synthetic_v1",
                "parameters": {},
                "configuration": {
                    "fee_model_id": "fee_v1",
                    "execution_model_id": "execution_v1",
                    "clock_policy_id": "capture_order_v1",
                },
                "budget": {"max_scenarios": 3, "max_wall_seconds": 30, "max_events": 1000},
                "seed": 1,
            }
        ),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
        strategy_sha256="c" * 64,
    )
    return build_confirmation_protocol(
        canonical(
            {
                "kind": "confirmation_request_v1",
                "schema_version": 1,
                "title": title,
                "max_events": 1000,
            }
        ),
        source_protocol=source.canonical_bytes,
        confirmation_normalized=b"".join(
            canonical(row) + b"\n" for row in ((_trade(),) if records is None else records)
        ),
    )


def _state(dataset: Path) -> Path:
    return dataset / "confirmation-state"


def _log(dataset: Path) -> Path:
    return _state(dataset) / "exposures.json"


def _exposures(raw: bytes) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", json.loads(raw)["exposures"])


def _write_log(dataset: Path, entries: tuple[ConfirmationExposure, ...]) -> bytes:
    data = canonical(
        {
            "kind": "confirmation_exposure_ledger_v1",
            "schema_version": 1,
            "exposures": [
                entry.document for entry in sorted(entries, key=lambda entry: entry.exposure_id)
            ],
        }
    )
    _log(dataset).write_bytes(data)
    return data


def test_registry_roundtrip_records_and_readonly_audit(tmp_path: Path) -> None:
    registry = LocalConfirmationRegistry(tmp_path, create=True)
    value = _protocol()
    first = registry.seal(value.canonical_bytes)
    again = registry.seal(value.canonical_bytes)
    assert first == ConfirmationProtocolRecord(value.protocol_id, value.canonical_bytes, True)
    assert again.created is False
    assert registry.get(value.protocol_id) == again
    assert LocalConfirmationExposureLedger(tmp_path).entries() == ()
    assert {child.name for child in tmp_path.iterdir()} == {
        ".confirmation-state-initialized",
        "confirmation-state",
    }
    assert {child.name for child in _state(tmp_path).iterdir()} == {
        "protocols",
        "exposures.json",
        ".lock",
    }
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    assert LocalConfirmationRegistry(tmp_path).get(value.protocol_id) == again
    assert LocalConfirmationExposureLedger(tmp_path).entries() == ()
    assert {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")} == before
    with pytest.raises(FrozenInstanceError):
        first.created = False  # type: ignore[misc]
    with pytest.raises(ConfirmationStoreError):
        ConfirmationProtocolRecord(
            value.protocol_id,
            bytearray(value.canonical_bytes),  # type: ignore[arg-type]
            False,
        )


@pytest.mark.parametrize("factory", [LocalConfirmationRegistry, LocalConfirmationExposureLedger])
def test_missing_readonly_state_creates_nothing(tmp_path: Path, factory: type) -> None:
    with pytest.raises(ConfirmationNotFoundError):
        factory(tmp_path)
    assert list(tmp_path.iterdir()) == []
    missing = tmp_path / "missing"
    with pytest.raises(ConfirmationStoreError):
        factory(missing, create=True)
    assert not missing.exists()


def test_missing_id_does_not_create_or_reset_history(tmp_path: Path) -> None:
    registry = LocalConfirmationRegistry(tmp_path, create=True)
    before = _log(tmp_path).read_bytes()
    with pytest.raises(ConfirmationNotFoundError):
        registry.get("0" * 64)
    assert _log(tmp_path).read_bytes() == before


@pytest.mark.parametrize("target", ["state", "anchor", "log", "lock", "protocols"])
def test_missing_initialized_state_never_becomes_fresh(tmp_path: Path, target: str) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    ledger.expose(_protocol())
    paths = {
        "state": _state(tmp_path),
        "anchor": tmp_path / ".confirmation-state-initialized",
        "log": _log(tmp_path),
        "lock": _state(tmp_path) / ".lock",
        "protocols": _state(tmp_path) / "protocols",
    }
    path = paths[target]
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    for factory in (LocalConfirmationRegistry, LocalConfirmationExposureLedger):
        for create in (False, True):
            with pytest.raises(ConfirmationStoreError) as caught:
                factory(tmp_path, create=create)
            assert not isinstance(caught.value, ConfirmationNotFoundError)
    with pytest.raises(ConfirmationStoreError):
        ledger.entries()
    assert not path.exists()


def test_same_origin_across_names_protocols_and_registry_instances(tmp_path: Path) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    original = _protocol()
    exposed = ledger.expose(original)
    assert exposed == build_confirmation_exposure(original)
    assert ledger.entries() == (exposed,)
    assert ledger.find_conflicts(origin_footprint((_trade(),))) == (exposed,)
    renamed = _protocol("Renamed", source_title="Unrelated source claim")
    assert renamed.protocol_id != original.protocol_id
    registry = LocalConfirmationRegistry(tmp_path)
    registry.seal(renamed.canonical_bytes)
    for value in (original, renamed):
        with pytest.raises(ConfirmationAlreadyExposed) as caught:
            LocalConfirmationExposureLedger(tmp_path).expose(value)
        assert caught.value.exposures == (exposed,)
    assert ledger.entries() == (exposed,)


def test_changed_payload_capture_time_and_partial_superset_inherit_origin(tmp_path: Path) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    original = _protocol(records=(_trade("one"), _trade("two", capture_seq=2)))
    exposed = ledger.expose(original)
    changed = _trade("two", capture_seq=97, event_time_ns=999, receive_time_ns=1000, price_ticks=9)
    for records in ((changed,), (changed, _trade("three", capture_seq=98))):
        with pytest.raises(ConfirmationAlreadyExposed) as caught:
            ledger.expose(_protocol("Repacked", records))
        assert caught.value.exposures == (exposed,)
    disjoint = ledger.expose(_protocol("Disjoint", (_trade("independent"),)))
    assert len(ledger.entries()) == 2
    assert ledger.find_conflicts(origin_footprint((_trade("independent"),))) == (disjoint,)


def test_closed_book_ranges_detect_resegmentation_and_allow_adjacent_window(tmp_path: Path) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    original = _protocol(
        records=(
            _book(100),
            _book(110, type="delta", first_sequence=101, capture_seq=2),
        )
    )
    exposed = ledger.expose(original)
    for last in (100, 105, 110):
        with pytest.raises(ConfirmationAlreadyExposed) as caught:
            ledger.expose(_protocol(str(last), (_book(last),)))
        assert caught.value.exposures == (exposed,)
    assert ledger.expose(_protocol("Adjacent", (_book(111),))) != exposed


def test_trusted_stream_names_define_scope_without_claiming_global_history(tmp_path: Path) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    ledger.expose(_protocol())
    # Different owner-declared source/session is explicitly outside equivalence inference.
    assert ledger.find_conflicts(origin_footprint((_trade(session="another-session"),))) == ()
    assert ledger.find_conflicts(origin_footprint((_trade(source="another-source"),))) == ()


def test_concurrent_overlapping_windows_have_one_winner(tmp_path: Path) -> None:
    LocalConfirmationExposureLedger(tmp_path, create=True)
    barrier = Barrier(8)

    def together(index: int) -> str:
        ledger = LocalConfirmationExposureLedger(tmp_path)
        value = _protocol(str(index))
        barrier.wait(timeout=10)
        try:
            ledger.expose(value)
            return "committed"
        except ConfirmationAlreadyExposed:
            return "refused"

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(together, range(8)))
    assert statuses.count("committed") == 1
    assert statuses.count("refused") == 7
    assert len(LocalConfirmationExposureLedger(tmp_path).entries()) == 1


def test_processes_share_the_same_whole_ledger_lock(tmp_path: Path) -> None:
    LocalConfirmationExposureLedger(tmp_path, create=True)
    script = """
import sys
from pathlib import Path
from tickwitness.domain.research_contracts.confirmation import (
    ConfirmationAlreadyExposed, load_confirmation_protocol,
)
from tickwitness.infrastructure.local_confirmation import LocalConfirmationExposureLedger
ledger = LocalConfirmationExposureLedger(Path(sys.argv[1]))
protocol = load_confirmation_protocol(bytes.fromhex(sys.argv[2]))
print('ready', flush=True)
input()
try:
    ledger.expose(protocol)
    print('committed', flush=True)
except ConfirmationAlreadyExposed:
    print('refused', flush=True)
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path),
                _protocol(str(index)).canonical_bytes.hex(),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(2)
    ]
    try:
        for process in processes:
            assert process.stdout is not None
            assert process.stdout.readline().strip() == "ready"
        for process in processes:
            assert process.stdin is not None
            process.stdin.write("\n")
            process.stdin.flush()
        outputs = [process.communicate(timeout=15) for process in processes]
        assert all(process.returncode == 0 for process in processes), outputs
        assert sorted(stdout.strip() for stdout, _stderr in outputs) == ["committed", "refused"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    assert len(LocalConfirmationExposureLedger(tmp_path).entries()) == 1


@pytest.mark.parametrize("after_replace", [False, True])
def test_replace_failure_never_returns_permission_or_rolls_back_published_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_replace: bool
) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    first = ledger.expose(_protocol())
    value = _protocol("Second", (_trade("second"),))
    original = _log(tmp_path).read_bytes()
    replace = os.replace

    def fail(*args: object, **kwargs: object) -> None:
        if after_replace:
            replace(*args, **kwargs)  # type: ignore[arg-type]
        raise OSError("Injected replacement uncertainty")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(ConfirmationStoreError, match="uncertainty"):
        ledger.expose(value)
    published = _log(tmp_path).read_bytes()
    if after_replace:
        assert len(_exposures(published)) == 2
        assert first.document in _exposures(published)
        assert build_confirmation_exposure(value).document in _exposures(published)
    else:
        assert published == original
    assert (_state(tmp_path) / ".pending-exposure").exists()
    with pytest.raises(ConfirmationStoreError, match="incomplete or uncertain"):
        ledger.entries()
    for create in (False, True):
        with pytest.raises(ConfirmationStoreError):
            LocalConfirmationExposureLedger(tmp_path, create=create)


@pytest.mark.parametrize("point", ["published", "marker_removed"])
def test_fsync_uncertainty_preserves_exposure_and_refuses_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    replace, unlink, fsync = os.replace, os.unlink, os.fsync
    reached = False
    failed = False

    def observe_replace(*args: object, **kwargs: object) -> None:
        nonlocal reached
        replace(*args, **kwargs)  # type: ignore[arg-type]
        if point == "published":
            reached = True

    def observe_unlink(path: str, **kwargs: object) -> None:
        nonlocal reached
        unlink(path, **kwargs)  # type: ignore[arg-type]
        if path == ".pending-exposure" and point == "marker_removed":
            reached = True

    def fail_once(descriptor: int) -> None:
        nonlocal failed
        if reached and not failed:
            failed = True
            raise OSError("Injected fsync uncertainty")
        fsync(descriptor)

    monkeypatch.setattr(os, "replace", observe_replace)
    monkeypatch.setattr(os, "unlink", observe_unlink)
    monkeypatch.setattr(os, "fsync", fail_once)
    with pytest.raises(ConfirmationStoreError, match="fsync uncertainty"):
        ledger.expose(_protocol())
    assert len(_exposures(_log(tmp_path).read_bytes())) == 1
    assert (_state(tmp_path) / ".pending-exposure").exists()
    with pytest.raises(ConfirmationStoreError):
        ledger.expose(_protocol())


def test_failed_initialization_keeps_anchor_and_does_not_retry_as_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("Injected initial publication failure")

    monkeypatch.setattr(local, "_rename_exclusive", fail)
    with pytest.raises(ConfirmationStoreError, match="publication failure"):
        LocalConfirmationRegistry(tmp_path, create=True)
    assert (tmp_path / ".confirmation-state-initialized").exists()
    assert not _state(tmp_path).exists()
    with pytest.raises(ConfirmationStoreError, match="anchor or state"):
        LocalConfirmationExposureLedger(tmp_path, create=True)


def test_failed_initial_directory_fsync_leaves_published_state_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rename, fsync = local._rename_exclusive, os.fsync
    published = False
    failed = False

    def observe(*args: object, **kwargs: object) -> None:
        nonlocal published
        rename(*args, **kwargs)  # type: ignore[arg-type]
        published = True

    def fail_once(descriptor: int) -> None:
        nonlocal failed
        if published and not failed:
            failed = True
            raise OSError("Injected initialization durability failure")
        fsync(descriptor)

    monkeypatch.setattr(local, "_rename_exclusive", observe)
    monkeypatch.setattr(os, "fsync", fail_once)
    with pytest.raises(ConfirmationStoreError, match="durability failure"):
        LocalConfirmationRegistry(tmp_path, create=True)
    assert _state(tmp_path).is_dir()
    assert (_state(tmp_path) / ".initializing").exists()
    with pytest.raises(ConfirmationStoreError, match="uncertain"):
        LocalConfirmationRegistry(tmp_path, create=True)


def test_protocol_corruption_is_not_repaired_even_if_resealed(tmp_path: Path) -> None:
    registry = LocalConfirmationRegistry(tmp_path, create=True)
    value = _protocol()
    registry.seal(value.canonical_bytes)
    path = _state(tmp_path) / "protocols" / f"{value.protocol_id}.json"
    path.write_bytes(b"{}")
    operations = (
        lambda: registry.get(value.protocol_id),
        lambda: registry.seal(value.canonical_bytes),
    )
    for operation in operations:
        with pytest.raises(ConfirmationStoreError):
            operation()
    assert path.read_bytes() == b"{}"
    forged = value.document
    cast("dict[str, object]", forged["read_policy"])["exposure_policy"] = "refundable"
    data = canonical(forged)
    identity = hashlib.sha256(data).hexdigest()
    (_state(tmp_path) / "protocols" / f"{identity}.json").write_bytes(data)
    with pytest.raises(ConfirmationStoreError):
        registry.get(identity)


@pytest.mark.parametrize(
    "target", ["dataset", "state", "protocols", "anchor", "lock", "log", "file"]
)
def test_nofollow_paths_reject_symlinks(tmp_path: Path, target: str) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    registry = LocalConfirmationRegistry(dataset, create=True)
    value = _protocol()
    registry.seal(value.canonical_bytes)
    paths = {
        "dataset": dataset,
        "state": _state(dataset),
        "protocols": _state(dataset) / "protocols",
        "anchor": dataset / ".confirmation-state-initialized",
        "lock": _state(dataset) / ".lock",
        "log": _log(dataset),
        "file": _state(dataset) / "protocols" / f"{value.protocol_id}.json",
    }
    path = paths[target]
    outside = tmp_path / "outside"
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=outside.is_dir())
    with pytest.raises(ConfirmationStoreError):
        registry.get(value.protocol_id)
    with pytest.raises(ConfirmationStoreError):
        registry.seal(value.canonical_bytes)
    if target != "file":
        with pytest.raises(ConfirmationStoreError):
            LocalConfirmationExposureLedger(dataset, create=True)


@pytest.mark.parametrize("target", ["anchor", "lock", "log", "protocol"])
@pytest.mark.parametrize("kind", ["fifo", "directory", "oversize"])
def test_nonregular_and_oversize_files_are_bounded_and_never_block(
    tmp_path: Path, target: str, kind: str
) -> None:
    registry = LocalConfirmationRegistry(tmp_path, create=True)
    value = _protocol()
    registry.seal(value.canonical_bytes)
    paths = {
        "anchor": tmp_path / ".confirmation-state-initialized",
        "lock": _state(tmp_path) / ".lock",
        "log": _log(tmp_path),
        "protocol": _state(tmp_path) / "protocols" / f"{value.protocol_id}.json",
    }
    path = paths[target]
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        with path.open("wb") as stream:
            stream.truncate(MAX_EXPOSURE_LEDGER_BYTES + 1)
    with pytest.raises(ConfirmationStoreError):
        registry.get(value.protocol_id)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"\xff", b'{"x":1,"x":2}', b" "])
def test_corrupt_or_other_format_log_never_means_empty(tmp_path: Path, raw: bytes) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    _log(tmp_path).write_bytes(raw)
    with pytest.raises(ConfirmationStoreError):
        ledger.entries()
    with pytest.raises(ConfirmationStoreError):
        ledger.expose(_protocol())
    with pytest.raises(ConfirmationStoreError):
        LocalConfirmationExposureLedger(tmp_path, create=True)
    assert _log(tmp_path).read_bytes() == raw


def test_unknown_state_entries_and_abandoned_markers_are_rejected(tmp_path: Path) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    extra = _state(tmp_path) / "unknown"
    extra.write_bytes(b"x")
    with pytest.raises(ConfirmationStoreError, match="Unknown"):
        ledger.entries()
    extra.unlink()
    for name in (".pending-exposure", ".exposure-next", ".initializing"):
        path = _state(tmp_path) / name
        path.write_bytes(b"uncertain")
        with pytest.raises(ConfirmationStoreError, match="uncertain"):
            ledger.find_conflicts(origin_footprint((_trade(),)))
        path.unlink()


def test_exact_byte_budget_is_allowed_but_overflow_never_truncates_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    value = _protocol()
    exposure = build_confirmation_exposure(value)
    exact = local._log_bytes((exposure,))
    monkeypatch.setattr(local, "MAX_EXPOSURE_LEDGER_BYTES", len(exact))
    assert ledger.expose(value) == exposure
    assert _log(tmp_path).read_bytes() == exact
    with pytest.raises(ConfirmationStoreError, match="byte limit"):
        ledger.expose(_protocol("Overflow", (_trade("other"),)))
    assert _log(tmp_path).read_bytes() == exact
    assert not (_state(tmp_path) / ".pending-exposure").exists()
    monkeypatch.setattr(local, "MAX_EXPOSURE_LEDGER_BYTES", len(exact) - 1)
    with pytest.raises(ConfirmationStoreError):
        ledger.entries()


def test_full_256_record_ledger_refuses_new_consumption_and_rejects_257(tmp_path: Path) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    template = build_confirmation_exposure(_protocol()).document
    entries: list[ConfirmationExposure] = []
    for index in range(257):
        footprint = origin_footprint((_trade(f"id-{index}"),))
        document = {
            **template,
            "origin_footprint": footprint.document,
            "origin_footprint_id": footprint.footprint_id,
            "confirmation_protocol_id": hashlib.sha256(str(index).encode()).hexdigest(),
        }
        entries.append(load_confirmation_exposure(canonical(document)))
    original = _write_log(tmp_path, tuple(entries[:256]))
    assert len(ledger.entries()) == 256
    with pytest.raises(ConfirmationStoreError, match="256 record"):
        ledger.expose(_protocol("Full", (_trade("new-origin"),)))
    assert _log(tmp_path).read_bytes() == original
    _write_log(tmp_path, tuple(entries))
    with pytest.raises(ConfirmationStoreError, match="256 record"):
        ledger.entries()


def test_duplicate_and_noncanonical_ledger_records_are_rejected(tmp_path: Path) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    entry = build_confirmation_exposure(_protocol())
    _write_log(tmp_path, (entry, entry))
    with pytest.raises(ConfirmationStoreError, match="unique"):
        ledger.entries()
    _write_log(tmp_path, (entry,))
    pretty = json.dumps(json.loads(_log(tmp_path).read_bytes()), indent=2).encode()
    _log(tmp_path).write_bytes(pretty)
    with pytest.raises(ConfirmationStoreError, match="canonical"):
        ledger.entries()


@pytest.mark.parametrize("kind", ["trade", "book"])
def test_self_consistent_but_overlapping_history_is_invalid(tmp_path: Path, kind: str) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    records = (_trade(),) if kind == "trade" else (_book(100),)
    original = build_confirmation_exposure(_protocol("First", records))
    renamed = build_confirmation_exposure(_protocol("Second", records))
    assert original.exposure_id != renamed.exposure_id
    raw = _write_log(tmp_path, (original, renamed))
    with pytest.raises(ConfirmationStoreError, match="origins overlap"):
        ledger.entries()
    with pytest.raises(ConfirmationStoreError, match="origins overlap"):
        LocalConfirmationRegistry(tmp_path, create=True)
    assert _log(tmp_path).read_bytes() == raw


def test_replaced_lock_inode_is_not_used_for_a_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = LocalConfirmationExposureLedger(tmp_path, create=True)
    original = _log(tmp_path).read_bytes()
    open_file = os.open
    swapped = False

    def swap(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        descriptor = open_file(path, flags, *args, **kwargs)  # type: ignore[call-overload]
        if path == ".lock" and not swapped:
            swapped = True
            lock_path = _state(tmp_path) / ".lock"
            lock_path.unlink()
            lock_path.write_bytes(b"")
        return descriptor

    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(ConfirmationStoreError, match="changed while open"):
        ledger.expose(_protocol())
    assert _log(tmp_path).read_bytes() == original


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63, "a/" * 32])
def test_protocol_ids_are_hashes_not_paths(tmp_path: Path, identity: str) -> None:
    registry = LocalConfirmationRegistry(tmp_path, create=True)
    with pytest.raises(ConfirmationStoreError, match="64 lowercase"):
        registry.get(identity)


@pytest.mark.parametrize("create", [None, 1, "true"])
def test_create_flag_is_genuinely_boolean(tmp_path: Path, create: object) -> None:
    with pytest.raises(ConfirmationStoreError, match="boolean"):
        LocalConfirmationRegistry(tmp_path, create=create)  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []
