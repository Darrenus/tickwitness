"""Inspect disposable copies of the installed smoke's already consumed evidence."""

import hashlib
import json
import shutil
import sqlite3
import stat
import subprocess
import time
from pathlib import Path

_INSPECTION_GUARD = """
import importlib.abc
import socket
import sqlite3
import subprocess
import sys

allowed_catalog = sys.argv.pop(1)
expect_sqlite = sys.argv.pop(1) == 'yes'
actual_connect = sqlite3.connect
attempted = []
connections = []

def forbidden(*args, **kwargs):
    attempted.append('publication/reservation/engine/network/worker/sqlite-write')
    raise AssertionError('Read-only inspection crossed its installed-check boundary')

class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('nautilus_trader',
                'tickwitness.infrastructure._nautilus_native',
                'tickwitness.infrastructure._queue_native',
                'tickwitness.infrastructure._tagged_queue_native')):
            attempted.append('native:' + fullname)
            raise AssertionError('Read-only inspection cannot import a native engine')

class NoWorker(subprocess.Popen):
    def __new__(cls, *args, **kwargs):
        return forbidden(*args, **kwargs)

class NoSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        return forbidden(*args, **kwargs)

def readonly_connect(database, *args, **kwargs):
    if database != allowed_catalog or kwargs.get('uri') is not True:
        return forbidden()
    connections.append(database)
    return actual_connect(database, *args, **kwargs)

sys.meta_path.insert(0, NoNative())
socket.socket = NoSocket
socket.create_connection = forbidden
socket.socketpair = forbidden
subprocess.Popen = NoWorker
sqlite3.connect = readonly_connect
sqlite3.dbapi2.connect = readonly_connect
try:
    from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
    from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
    from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
    from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
    from tickwitness.infrastructure.nautilus_replay import NautilusReplayAdapter
    from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
    for owner, names in (
        (LocalAttemptLedger, ('reserve', 'reserve_with_nonce', 'publish', 'bind_intent')),
        (LocalExecutableProtocolRegistry, ('seal',)),
        (LocalDatasetStore, ('publish',)),
        (BoundedReplayAdapter, ('run',)),
        (NautilusReplayAdapter, ('run',)),
        (SubprocessReplayAdapter, ('run',)),
    ):
        for name in names:
            setattr(owner, name, forbidden)
    from tickwitness.cli import main
    status = main(sys.argv[1:])
finally:
    assert not attempted, attempted
    assert bool(connections) == expect_sqlite, connections
raise SystemExit(status)
"""


def _inventory(root: Path, *, runtime_store: Path | None = None) -> dict[str, tuple[object, ...]]:
    """Exclude atime; copies also permit only known SQLite sidecars/directory clocks."""
    sidecars = (
        set()
        if runtime_store is None
        else {runtime_store / "catalog.sqlite3-wal", runtime_store / "catalog.sqlite3-shm"}
    )
    result: dict[str, tuple[object, ...]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        if path in sidecars:
            assert stat.S_ISREG(info.st_mode), "SQLite runtime sidecars must remain regular files"
            continue
        metadata: tuple[object, ...] = (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_uid,
            info.st_gid,
            info.st_nlink,
        )
        if stat.S_ISREG(info.st_mode):
            metadata += (
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        else:
            assert stat.S_ISDIR(info.st_mode), "Inspection fixtures require files/directories"
            if runtime_store is None:
                metadata += (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        result[str(path.relative_to(root))] = metadata
    return result


def _stdout(document: dict[str, object]) -> str:
    return (
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    )


def inspection_diagnostics(
    interpreter: str,
    store: Path,
    registry: Path,
    runs: Path,
    protocol_id: str,
    attempt_id: str,
    directory: Path,
) -> None:
    """Run sixteen reads, reusing existing smoke bytes without new research actions."""
    deadline = time.monotonic() + 90
    sources = (store, registry, runs)
    original = tuple(_inventory(path) for path in sources)
    protocol_bytes = (registry / "protocols" / f"{protocol_id}.json").read_bytes()
    reservation_bytes = (runs / "objects" / "sha256" / attempt_id).read_bytes()
    outcome_bytes = (runs / "outcomes" / f"{attempt_id}.json").read_bytes()
    assert hashlib.sha256(protocol_bytes).hexdigest() == protocol_id
    assert hashlib.sha256(reservation_bytes).hexdigest() == attempt_id
    outcome_id = hashlib.sha256(outcome_bytes).hexdigest()
    assert (runs / "objects" / "sha256" / outcome_id).read_bytes() == outcome_bytes
    protocol, reservation = json.loads(protocol_bytes), json.loads(reservation_bytes)
    assert reservation["protocol_id"] == protocol_id
    slot = Path("slots") / protocol_id / f"{reservation['attempt_index']:04}.json"
    assert (runs / slot).read_bytes() == reservation_bytes
    experiment = {
        "protocol_id": protocol_id,
        "claim_revision_id": protocol["claim_revision_id"],
        "created": False,
        "document": protocol,
    }
    finalized = {
        "attempt_id": attempt_id,
        "reservation": reservation,
        "budget_consumed": True,
        "state": "finalized",
        "outcome": json.loads(outcome_bytes),
    }
    directory.mkdir()
    calls = 0

    def unchanged_source() -> None:
        assert tuple(_inventory(path) for path in sources) == original, "Source smoke state changed"

    def copied(name: str) -> Path:
        unchanged_source()
        case = directory / name
        case.mkdir()
        for source, target in zip(sources, ("data", "registry", "runs"), strict=True):
            shutil.copytree(source, case / target)
        unchanged_source()
        return case

    def inspect(
        case: Path, command: str, requested_id: str, *, expected: int = 0, sqlite: bool = False
    ) -> tuple[dict[str, object], str]:
        nonlocal calls
        calls += 1
        assert calls <= 16
        options = (
            ("--registry", str(case / "registry"), "--store", str(case / "data"))
            if command == "inspect-experiment"
            else ("--runs", str(case / "runs"))
        )
        before = _inventory(case, runtime_store=case / "data")
        unchanged_source()
        remaining = deadline - time.monotonic()
        assert remaining > 0, "Installed inspection diagnostic deadline exhausted"
        try:
            result = subprocess.run(
                [
                    interpreter,
                    "-I",
                    "-c",
                    _INSPECTION_GUARD,
                    (case / "data" / "catalog.sqlite3").as_uri() + "?mode=ro",
                    "yes" if sqlite else "no",
                    command,
                    requested_id,
                    *options,
                ],
                cwd=case,
                text=True,
                capture_output=True,
                check=False,
                timeout=min(15, remaining),
            )
        finally:
            assert _inventory(case, runtime_store=case / "data") == before, (
                "Inspection changed persistent copied evidence"
            )
            unchanged_source()
        if result.returncode != expected or (result.stdout if expected else result.stderr):
            raise RuntimeError(
                f"Guarded installed {command} exited {result.returncode}: "
                f"{result.stdout}\n{result.stderr}"
            )
        return json.loads(result.stderr if expected else result.stdout), result.stdout

    def absent(
        case: Path,
        command: str,
        requested_id: str,
        lookup: str,
        message: str,
        *,
        resource_id: str | None = None,
        sqlite: bool = False,
    ) -> None:
        receipt, _ = inspect(case, command, requested_id, expected=4, sqlite=sqlite)
        error = {
            "code": "dataset_not_found"
            if lookup in {"dataset_store", "referenced_dataset"}
            else "research_evidence_not_found",
            "message": message,
            "reason": "inspection_evidence_not_found",
            "command": command,
            "requested_id": requested_id,
            "lookup": lookup,
        }
        if resource_id is not None:
            error["resource_id"] = resource_id
        assert receipt == {"error": error}

    def generic(case: Path, command: str, *, sqlite: bool = False) -> None:
        requested_id = protocol_id if command == "inspect-experiment" else attempt_id
        receipt, _ = inspect(case, command, requested_id, expected=3, sqlite=sqlite)
        assert set(receipt) == {"error"}
        error = receipt["error"]
        assert isinstance(error, dict) and set(error) == {"code", "message"}
        assert error["code"] == (
            "store_integrity_or_publication_failure"
            if case.name == "missing-data-objects"
            else "research_store_integrity_or_io_failure"
        )
        assert isinstance(error["message"], str) and error["message"]

    valid = copied("valid-experiment")
    assert inspect(valid, "inspect-experiment", protocol_id, sqlite=True)[1] == _stdout(experiment)
    valid_attempt = copied("finalized-attempt")
    assert inspect(valid_attempt, "inspect-attempt", attempt_id)[1] == _stdout(finalized)

    unfinalized = copied("unfinalized-attempt")
    (unfinalized / "runs" / "outcomes" / f"{attempt_id}.json").unlink()
    expected_unfinalized = dict(finalized, state="reserved_unfinalized", outcome=None)
    assert inspect(unfinalized, "inspect-attempt", attempt_id)[1] == _stdout(expected_unfinalized)

    missing_registry = copied("missing-registry")
    shutil.rmtree(missing_registry / "registry")
    absent(
        missing_registry,
        "inspect-experiment",
        protocol_id,
        "executable_registry",
        "Executable registry does not exist",
    )
    missing_store = copied("missing-store")
    shutil.rmtree(missing_store / "data")
    absent(
        missing_store,
        "inspect-experiment",
        protocol_id,
        "dataset_store",
        "Dataset store does not exist",
    )
    missing_protocol = copied("missing-protocol")
    (missing_protocol / "registry" / "protocols" / f"{protocol_id}.json").unlink()
    absent(
        missing_protocol,
        "inspect-experiment",
        protocol_id,
        "executable_protocol",
        f"Executable protocol is not published: {protocol_id}",
        resource_id=protocol_id,
        sqlite=True,
    )

    missing_dataset = copied("missing-referenced-dataset")
    dataset_id = next(iter(protocol["datasets"].values()))
    # Fixture preparation writes only this disposable catalog; child reads stay mode=ro.
    connection = sqlite3.connect(missing_dataset / "data" / "catalog.sqlite3")
    try:
        cursor = connection.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))
        assert cursor.rowcount == 1
        connection.commit()
    finally:
        connection.close()
    absent(
        missing_dataset,
        "inspect-experiment",
        protocol_id,
        "referenced_dataset",
        f"Dataset is not published: {dataset_id}",
        resource_id=dataset_id,
        sqlite=True,
    )

    missing_ledger = copied("missing-ledger")
    shutil.rmtree(missing_ledger / "runs")
    absent(
        missing_ledger,
        "inspect-attempt",
        attempt_id,
        "attempt_ledger",
        "Attempt ledger does not exist",
    )
    unknown = "0" * 64 if attempt_id != "0" * 64 else "f" * 64
    unknown_attempt = copied("unknown-attempt")
    assert not (unknown_attempt / "runs" / "objects" / "sha256" / unknown).exists()
    absent(
        unknown_attempt,
        "inspect-attempt",
        unknown,
        "committed_attempt",
        "Attempt has no committed reservation closure",
        resource_id=unknown,
    )
    orphan = copied("reservation-cas-orphan")
    (orphan / "runs" / slot).unlink()
    assert (orphan / "runs" / "objects" / "sha256" / attempt_id).read_bytes() == reservation_bytes
    absent(
        orphan,
        "inspect-attempt",
        attempt_id,
        "committed_attempt",
        "Attempt has no committed reservation closure",
        resource_id=attempt_id,
    )

    corrupt_protocol = copied("corrupt-protocol")
    (corrupt_protocol / "registry" / "protocols" / f"{protocol_id}.json").write_bytes(b"corrupt")
    generic(corrupt_protocol, "inspect-experiment", sqlite=True)
    missing_data_objects = copied("missing-data-objects")
    shutil.rmtree(missing_data_objects / "data" / "objects")
    generic(missing_data_objects, "inspect-experiment", sqlite=True)
    missing_outcome_cas = copied("missing-outcome-cas")
    (missing_outcome_cas / "runs" / "objects" / "sha256" / outcome_id).unlink()
    generic(missing_outcome_cas, "inspect-attempt")
    missing_protocols = copied("missing-registry-protocols")
    shutil.rmtree(missing_protocols / "registry" / "protocols")
    generic(missing_protocols, "inspect-experiment")
    missing_ledger_objects = copied("missing-ledger-objects")
    shutil.rmtree(missing_ledger_objects / "runs" / "objects")
    generic(missing_ledger_objects, "inspect-attempt")
    corrupt_reservation = copied("corrupt-reservation-cas")
    (corrupt_reservation / "runs" / "objects" / "sha256" / attempt_id).write_bytes(b"corrupt")
    generic(corrupt_reservation, "inspect-attempt")
    assert calls == 16 and time.monotonic() <= deadline
    unchanged_source()
    print("Installed inspection diagnostics: 16 guarded read-only calls passed.")
