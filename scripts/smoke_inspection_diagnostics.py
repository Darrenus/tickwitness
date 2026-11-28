"""Inspect disposable copies of the installed smoke's already consumed evidence."""

import hashlib
import json
import os
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


def _inventory(root: Path, *, runtime_store: Path | None = None) -> dict[str, object]:
    """Retain full non-atime metadata; report unsafe/unreadable entries without hiding peers."""
    sidecars = (
        set()
        if runtime_store is None
        else {runtime_store / "catalog.sqlite3-wal", runtime_store / "catalog.sqlite3-shm"}
    )
    entries, errors = {}, []

    def visit(path, parent_fd=None):
        name = str(path.relative_to(root))
        target = path if parent_fd is None else path.name
        try:
            info = os.stat(target, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            errors.append({"path": name, "operation": "lstat", **_exception(error)})
            return
        regular, directory = stat.S_ISREG(info.st_mode), stat.S_ISDIR(info.st_mode)
        if path in sidecars and regular:
            return
        entry = {
            "type": stat.S_IFMT(info.st_mode),
            "dev": info.st_dev,
            "ino": info.st_ino,
            "mode": info.st_mode,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "nlink": info.st_nlink,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
            "sha256": None,
        }
        if path in sidecars or not (regular or directory):
            errors.append({"path": name, "operation": "type", "actual_type": entry["type"]})
        elif regular:
            try:
                entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                errors.append({"path": name, "operation": "read", **_exception(error)})
        entries[name] = entry
        if directory and path not in sidecars:
            descriptor = None
            try:
                descriptor = os.open(
                    target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                with os.scandir(descriptor) as children:
                    child_names = sorted(child.name for child in children)
                for child_name in child_names:
                    visit(path / child_name, descriptor)
            except OSError as error:
                errors.append({"path": name, "operation": "enumerate", **_exception(error)})
            finally:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError as error:
                        errors.append({"path": name, "operation": "close", **_exception(error)})

    visit(root)
    return {"entries": entries, "errors": errors}


def _exception(error: OSError) -> dict[str, object]:
    return {"type": type(error).__name__, "errno": error.errno, "message": str(error)[:1024]}


def _persistent(snapshot):
    """Copied evidence binds names/types and regular-file size/hash, not inode metadata."""
    return {
        name: {"type": entry["type"], "size": entry["size"], "sha256": entry["sha256"]}
        if entry["type"] == stat.S_IFREG
        else {"type": entry["type"]}
        for name, entry in snapshot["entries"].items()
    }


def _old_copy_metadata(snapshot):
    """Reproduce the 5a copy comparison, whose directories omitted size and clocks."""
    common = ("dev", "ino", "mode", "uid", "gid", "nlink")
    regular = (*common, "size", "mtime_ns", "ctime_ns", "sha256")
    return {
        name: {key: entry[key] for key in (regular if entry["type"] == stat.S_IFREG else common)}
        for name, entry in snapshot["entries"].items()
    }


def _difference(before, after):
    return {
        "unchanged": before == after,
        "before_keys": sorted(before),
        "after_keys": sorted(after),
        "added": [
            {"path": name, "value": after[name]} for name in sorted(after.keys() - before.keys())
        ],
        "removed": [
            {"path": name, "value": before[name]} for name in sorted(before.keys() - after.keys())
        ],
        "changed": [
            {
                "path": name,
                "fields": {
                    key: {"before": before[name].get(key), "after": after[name].get(key)}
                    for key in sorted(before[name].keys() | after[name].keys())
                    if before[name].get(key) != after[name].get(key)
                },
            }
            for name in sorted(before.keys() & after.keys())
            if before[name] != after[name]
        ],
    }


def _diff_summary(difference):
    """Bound log size while retaining actual field deltas, full counts and a full-diff hash."""
    limit = 32
    summary = {"unchanged": difference["unchanged"]}
    for key in ("before_keys", "after_keys", "added", "removed", "changed"):
        summary[key] = difference[key][:limit]
        summary[key + "_count"] = len(difference[key])
    summary["actual_changed_fields"] = sorted(
        {key for entry in difference["changed"] for key in entry["fields"]}
    )
    summary["details_complete"] = all(
        len(difference[key]) <= limit
        for key in ("before_keys", "after_keys", "added", "removed", "changed")
    )
    summary["full_diff_sha256"] = hashlib.sha256(
        json.dumps(difference, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return summary


def _stream(value: bytes) -> dict[str, object]:
    return {
        "bytes": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
        "preview": value[:4096].decode("utf-8", errors="replace"),
        "preview_truncated": len(value) > 4096,
    }


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

    def source_observation():
        observations = []
        for name, path, baseline in zip(
            ("data", "registry", "runs"), sources, original, strict=True
        ):
            current = _inventory(path)
            difference = _difference(baseline["entries"], current["entries"])
            observations.append(
                {
                    "tree": name,
                    "strict_unchanged": difference["unchanged"]
                    and not baseline["errors"]
                    and not current["errors"],
                    "baseline_errors": baseline["errors"][:32],
                    "current_errors": current["errors"][:32],
                    "baseline_error_count": len(baseline["errors"]),
                    "current_error_count": len(current["errors"]),
                    "difference": _diff_summary(difference),
                }
            )
        return observations

    def unchanged_source() -> None:
        observed = source_observation()
        if not all(item["strict_unchanged"] for item in observed):
            raise RuntimeError(
                "Source smoke state changed: " + json.dumps(observed, sort_keys=True)
            )

    def copied(name: str) -> Path:
        unchanged_source()
        case = directory / name
        case.mkdir()
        for source, target in zip(sources, ("data", "registry", "runs"), strict=True):
            shutil.copytree(source, case / target)
        unchanged_source()
        return case

    def inspect(
        case: Path,
        command: str,
        requested_id: str,
        *,
        expected: int = 0,
        sqlite: bool = False,
        expected_receipt=None,
        expected_stdout: str | None = None,
        generic_code: str | None = None,
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
        source_before = source_observation()
        remaining = deadline - time.monotonic()
        child = {"state": "not_started", "returncode": None, "expected_returncode": expected}
        stdout, stderr = b"", b""
        try:
            if (
                remaining > 0
                and not before["errors"]
                and all(item["strict_unchanged"] for item in source_before)
            ):
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
                    capture_output=True,
                    check=False,
                    timeout=min(15, remaining),
                )
                stdout, stderr = result.stdout, result.stderr
                child.update(state="completed", returncode=result.returncode)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            child.update(state="timeout", timeout_seconds=error.timeout)
        except OSError as error:
            child.update(state="os_error", error=_exception(error))
        finally:
            after = _inventory(case, runtime_store=case / "data")
            source_after = source_observation()
        persistent_diff = _difference(_persistent(before), _persistent(after))
        metadata_diff = _difference(before["entries"], after["entries"])
        old_metadata_diff = _difference(_old_copy_metadata(before), _old_copy_metadata(after))
        persistent_unchanged = (
            persistent_diff["unchanged"] and not before["errors"] and not after["errors"]
        )
        report = {
            "kind": "installed_inspection_observation_v1",
            "case": case.name,
            "command": command,
            "child": child,
            "copy": {
                "persistent_unchanged": persistent_unchanged,
                "persistent_difference": _diff_summary(persistent_diff),
                "old_metadata_equal": old_metadata_diff["unchanged"],
                "old_metadata_observation": _diff_summary(old_metadata_diff),
                "full_metadata_equal": metadata_diff["unchanged"],
                "metadata_observation": _diff_summary(metadata_diff),
                "before_errors": before["errors"][:32],
                "after_errors": after["errors"][:32],
                "before_error_count": len(before["errors"]),
                "after_error_count": len(after["errors"]),
            },
            "source_strict_unchanged": all(
                item["strict_unchanged"] for item in (*source_before, *source_after)
            ),
            "source_before": source_before,
            "source_after": source_after,
        }
        failures = []
        if not persistent_unchanged:
            failures.append("copied_persistent_evidence_changed_or_unreadable")
        if not report["source_strict_unchanged"]:
            failures.append("source_strict_inventory_changed_or_unreadable")
        if child["state"] != "completed" or child["returncode"] != expected:
            failures.append("child_did_not_complete_with_expected_exit")
        unexpected_stream = stdout if expected else stderr
        if unexpected_stream:
            failures.append(
                "unexpected_success_stdout" if expected else "unexpected_success_stderr"
            )
        receipt, decoded_stdout = None, ""
        if child["state"] == "completed":
            try:
                decoded_stdout = stdout.decode("utf-8")
                receipt = json.loads(stderr if expected else stdout)
                if expected_receipt is not None and receipt != expected_receipt:
                    failures.append("receipt_fields_differ")
                if expected_stdout is not None and decoded_stdout != expected_stdout:
                    failures.append("success_receipt_bytes_differ")
                if generic_code is not None:
                    error = receipt.get("error") if isinstance(receipt, dict) else None
                    if not (
                        isinstance(receipt, dict)
                        and set(receipt) == {"error"}
                        and isinstance(error, dict)
                        and set(error) == {"code", "message"}
                        and error["code"] == generic_code
                        and isinstance(error["message"], str)
                        and error["message"]
                    ):
                        failures.append("generic_refusal_fields_differ")
            except ValueError as error:
                failures.append(
                    {"receipt_error": type(error).__name__, "message": str(error)[:512]}
                )
        if failures:
            report.update(failures=failures, stdout=_stream(stdout), stderr=_stream(stderr))
            raise RuntimeError(
                "Installed inspection diagnostic failure: " + json.dumps(report, sort_keys=True)
            )
        metadata_observation = {
            key: value
            for key, value in report["copy"]["metadata_observation"].items()
            if key not in {"before_keys", "after_keys"}
        }
        old_metadata_observation = {
            key: value
            for key, value in report["copy"]["old_metadata_observation"].items()
            if key not in {"before_keys", "after_keys"}
        }
        print(
            json.dumps(
                {
                    "kind": report["kind"],
                    "case": case.name,
                    "command": command,
                    "child": child,
                    "persistent_unchanged": persistent_unchanged,
                    "source_strict_unchanged": report["source_strict_unchanged"],
                    "old_metadata_equal": report["copy"]["old_metadata_equal"],
                    "full_metadata_equal": report["copy"]["full_metadata_equal"],
                    "old_metadata_observation": old_metadata_observation,
                    "metadata_observation": metadata_observation,
                },
                sort_keys=True,
            )
        )
        return receipt, decoded_stdout

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
        receipt, _ = inspect(
            case,
            command,
            requested_id,
            expected=4,
            sqlite=sqlite,
            expected_receipt={"error": error},
        )
        assert receipt == {"error": error}

    def generic(case: Path, command: str, *, sqlite: bool = False) -> None:
        requested_id = protocol_id if command == "inspect-experiment" else attempt_id
        code = (
            "store_integrity_or_publication_failure"
            if case.name == "missing-data-objects"
            else "research_store_integrity_or_io_failure"
        )
        receipt, _ = inspect(
            case, command, requested_id, expected=3, sqlite=sqlite, generic_code=code
        )
        assert set(receipt) == {"error"}
        error = receipt["error"]
        assert isinstance(error, dict) and set(error) == {"code", "message"}
        assert error["code"] == code
        assert isinstance(error["message"], str) and error["message"]

    valid = copied("valid-experiment")
    assert inspect(
        valid, "inspect-experiment", protocol_id, sqlite=True, expected_stdout=_stdout(experiment)
    )[1] == _stdout(experiment)
    valid_attempt = copied("finalized-attempt")
    assert inspect(
        valid_attempt, "inspect-attempt", attempt_id, expected_stdout=_stdout(finalized)
    )[1] == _stdout(finalized)

    unfinalized = copied("unfinalized-attempt")
    (unfinalized / "runs" / "outcomes" / f"{attempt_id}.json").unlink()
    expected_unfinalized = dict(finalized, state="reserved_unfinalized", outcome=None)
    assert inspect(
        unfinalized, "inspect-attempt", attempt_id, expected_stdout=_stdout(expected_unfinalized)
    )[1] == _stdout(expected_unfinalized)

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
