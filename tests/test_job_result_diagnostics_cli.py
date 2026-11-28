"""Attribute only validated stored-state refusals; preserve uncertain Job reads."""

import argparse
import builtins
import errno
import hashlib
import json
import os
import socket
import sqlite3
import stat
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from test_reduction_comparison_contract import compare, comparison_case
from test_sqlite_job_store import NOW, claim, complete, failure
from test_sqlite_job_store import job_case as job_case

from tickwitness import cli_jobs
from tickwitness.application.jobs import JobConflictError, JobNotFoundError, JobStoreError
from tickwitness.cli import main
from tickwitness.domain.jobs import build_job_spec
from tickwitness.infrastructure import sqlite_job_store
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore

MESSAGE = "Only a succeeded Job has a readable result"


def arguments(value, *, command="read-job-result", requested=None, root=None):
    return [command, requested or value.spec.spec_id, "--jobs", str(root or value.root)]


def inventory(root: Path) -> dict[str, tuple[int, str]]:
    """Keep every entry and regular byte; exclude no journal, WAL or SHM."""
    result = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            kind = stat.S_IFMT(entry.stat(follow_symlinks=False).st_mode)
            if kind == stat.S_IFREG:
                payload = hashlib.sha256(path.read_bytes()).hexdigest()
            elif kind == stat.S_IFLNK:
                payload = os.readlink(path)
            else:
                payload = ""
            if kind == stat.S_IFDIR:
                pending.append(path)
            result[str(path.relative_to(root))] = kind, payload
    return result


def prepare(value, state):
    """Persist real transitions with an offline result; never run a worker."""
    with value.store.coordinator() as owner:
        row = value.store.submit(value.spec, now_ns=NOW)
        if state != "QUEUED":
            row = claim(value, owner)
        if state == "SUCCEEDED":
            row = complete(value, row)
        elif state == "FAILED":
            attempt = row["attempt"]
            row = value.store.fail(
                value.spec.spec_id,
                failure(),
                expected_version=row["version"],
                coordinator_id=owner,
                job_attempt_id=attempt["job_attempt_id"],
                lease_token=attempt["lease_token"],
                now_ns=NOW + 2,
            )
        elif state == "LOST":
            row = value.store.mark_lost(
                value.spec.spec_id,
                expected_version=row["version"],
                reason="lease_expired",
                now_ns=row["attempt"]["lease_expires_at_ns"],
            )
    assert row["state"] == state
    assert value.store.get(value.spec.spec_id) == row
    return row


def guard_reads(monkeypatch, root):
    """Install after preparation; permit only this existing Catalog in mode=ro."""
    connections = []
    real_connect = sqlite3.connect
    real_import = builtins.__import__
    expected_uri = "file:" + quote(str(root / "catalog.sqlite3"), safe="/") + "?mode=ro"

    def forbidden(*args, **kwargs):
        raise AssertionError("A result read cannot mutate, reconcile or execute research")

    def readonly_connect(database, *args, **kwargs):
        assert database == expected_uri and kwargs.get("uri") is True
        connections.append(database)
        return real_connect(database, *args, **kwargs)

    def readonly_store(path, **kwargs):
        assert Path(path).absolute() == root and kwargs == {"create": False}
        return SqliteJobStore(path, **kwargs)

    def import_without_native(name, *args, **kwargs):
        if name == "nautilus_trader" or name.startswith("nautilus_trader."):
            raise AssertionError("A result read cannot import a native engine")
        return real_import(name, *args, **kwargs)

    class NoWorker(subprocess.Popen):
        def __new__(cls, *args, **kwargs):
            return forbidden(*args, **kwargs)

    class NoSocket(socket.socket):
        def __new__(cls, *args, **kwargs):
            return forbidden(*args, **kwargs)

    for method in (
        "coordinator",
        "submit",
        "claim",
        "heartbeat",
        "complete",
        "fail",
        "mark_lost",
        "reconcile_orphans",
    ):
        monkeypatch.setattr(SqliteJobStore, method, forbidden)
    for owner, method in (
        (LocalAttemptLedger, "reserve"),
        (LocalAttemptLedger, "reserve_with_nonce"),
        (LocalAttemptLedger, "publish"),
        (LocalAttemptLedger, "bind_intent"),
        (LocalExecutableProtocolRegistry, "seal"),
        (LocalDatasetStore, "publish"),
    ):
        monkeypatch.setattr(owner, method, forbidden)
    monkeypatch.setattr(cli_jobs, "run_job", forbidden)
    monkeypatch.setattr(cli_jobs, "SqliteJobStore", readonly_store)
    monkeypatch.setattr(subprocess, "Popen", NoWorker)
    monkeypatch.setattr(socket, "socket", NoSocket)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socketpair", forbidden)
    monkeypatch.setattr(sqlite3, "connect", readonly_connect)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", readonly_connect)
    monkeypatch.setattr(builtins, "__import__", import_without_native)
    return connections


def error_output(argv, capsys, exit_code):
    assert main(argv) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    envelope = json.loads(captured.err)
    assert set(envelope) == {"error"}
    return envelope["error"]


def generic(error, code, message=None):
    assert set(error) == {"code", "message"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    if message is not None:
        assert error["message"] == message


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "FAILED", "LOST"])
def test_only_verified_non_succeeded_states_have_exact_context(
    job_case, tmp_path, capsys, monkeypatch, state
):
    value = job_case
    prepare(value, state)
    before = inventory(tmp_path)
    connections = guard_reads(monkeypatch, value.root)

    def forbidden(*args, **kwargs):
        raise AssertionError("A non-succeeded refusal must not read a result or effective state")

    monkeypatch.setattr(SqliteJobStore, "result", forbidden)
    monkeypatch.setattr(SqliteJobStore, "coordinator_active", forbidden)
    monkeypatch.setattr(cli_jobs, "job_view", forbidden)
    monkeypatch.setattr(cli_jobs, "time", SimpleNamespace(time_ns=forbidden))
    error = error_output(arguments(value), capsys, 9)
    assert error == {
        "code": "job_conflict",
        "message": MESSAGE,
        "reason": "job_result_not_succeeded",
        "command": "read-job-result",
        "requested_job_id": value.spec.spec_id,
        "stored_state": state,
    }
    assert connections
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("domain_unknown", [False, True])
def test_successful_saved_result_bytes_and_domain_unknown_are_unchanged(
    job_case, tmp_path, capsys, monkeypatch, domain_unknown
):
    value = job_case
    if domain_unknown:
        value.comparison = compare(comparison_case(count=4))
        bindings = value.comparison.document["bindings"]
        value.request.update(
            run_id=bindings["reduced"]["run_id"],
            expected_bundle_id=bindings["source"]["bundle_id"],
            expected_report_id=bindings["source"]["report_id"],
        )
        value.spec = build_job_spec(value.request, lease_duration_ns=1_000_000_000)
        assessment = value.comparison.document["reduced_assessment"]
        assert assessment["outcome"] == "NOT_EVALUABLE"
        assert assessment["criterion_observation"]["truth"] is None
        assert assessment["criterion_observation"]["value"] is None
    prepare(value, "SUCCEEDED")
    before = inventory(tmp_path)
    connections = guard_reads(monkeypatch, value.root)
    assert main(arguments(value)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == value.comparison.export_bytes.decode("utf-8")
    assert not captured.out.endswith("\n")
    assert connections
    assert inventory(tmp_path) == before


def test_invalid_requested_identity_precedes_catalog_io(tmp_path, capsys, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An invalid identity must precede Catalog construction")

    monkeypatch.setattr(cli_jobs, "SqliteJobStore", forbidden)
    error = error_output(
        ["read-job-result", "invalid", "--jobs", str(tmp_path / "absent")], capsys, 2
    )
    generic(error, "invalid_research_evidence")
    assert inventory(tmp_path) == {}


@pytest.mark.parametrize("missing", ["catalog", "job"])
def test_missing_catalog_or_job_is_generic_and_never_created(
    job_case, tmp_path, capsys, monkeypatch, missing
):
    value = job_case
    prepare(value, "QUEUED")
    root = tmp_path / "absent" if missing == "catalog" else value.root
    before = inventory(tmp_path)
    guard_reads(monkeypatch, root)
    error = error_output(arguments(value, requested="0" * 64, root=root), capsys, 4)
    generic(error, "job_not_found")
    assert not (tmp_path / "absent").exists()
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("command", ["read-job-result", "inspect-job"])
def test_same_message_generic_conflict_never_acquires_state(
    job_case, tmp_path, capsys, monkeypatch, command
):
    value = job_case
    prepare(value, "QUEUED")
    before = inventory(tmp_path)
    guard_reads(monkeypatch, value.root)

    def conflict(*args, **kwargs):
        raise JobConflictError(MESSAGE)

    monkeypatch.setattr(SqliteJobStore, "get", conflict)
    error = error_output(arguments(value, command=command), capsys, 9)
    generic(error, "job_conflict", MESSAGE)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("failure_kind", ["conflict", "store", "missing", "io", "none"])
def test_second_result_read_retains_its_own_exception_or_none_route(
    job_case, tmp_path, capsys, monkeypatch, failure_kind
):
    value = job_case
    prepare(value, "SUCCEEDED")
    real_get = SqliteJobStore.get
    observed = []

    def verified_get(store, requested):
        row = real_get(store, requested)
        assert row["state"] == "SUCCEEDED"
        observed.append("verified_get")
        return row

    def uncertain_result(store, requested):
        assert observed == ["verified_get"] and requested == value.spec.spec_id
        observed.append("result")
        if failure_kind == "none":
            return None
        error_type = {
            "conflict": JobConflictError,
            "store": JobStoreError,
            "missing": JobNotFoundError,
            "io": OSError,
        }[failure_kind]
        raise error_type(MESSAGE)

    monkeypatch.setattr(SqliteJobStore, "get", verified_get)
    monkeypatch.setattr(SqliteJobStore, "result", uncertain_result)
    before = inventory(tmp_path)
    guard_reads(monkeypatch, value.root)
    code, exit_code = {
        "conflict": ("job_conflict", 9),
        "store": ("job_store_integrity_or_io_failure", 3),
        "missing": ("job_not_found", 4),
        "io": ("io_failure", 3),
        "none": ("job_conflict", 9),
    }[failure_kind]
    error = error_output(arguments(value), capsys, exit_code)
    generic(error, code, "Job result is unavailable" if failure_kind == "none" else MESSAGE)
    assert observed == ["verified_get", "result"]
    assert inventory(tmp_path) == before


@pytest.mark.parametrize(
    "damage",
    [
        "missing_blob",
        "corrupt_blob",
        "snapshot",
        "snapshot_hash",
        "event",
        "event_index",
        "extra_blob",
    ],
)
def test_real_catalog_corruption_precedes_any_state_context(
    job_case, tmp_path, capsys, monkeypatch, damage
):
    value = job_case
    row = prepare(value, "QUEUED" if damage == "extra_blob" else "SUCCEEDED")
    connection = sqlite3.connect(value.root / "catalog.sqlite3")
    try:
        if damage in {"event", "event_index"}:
            column, payload = ("event", b"{}") if damage == "event" else ("event_id", "0" * 64)
            changed = connection.execute(
                f"UPDATE job_events SET {column}=? WHERE version=?", (payload, row["version"])
            )
        else:
            column, payload = {
                "missing_blob": ("result", None),
                "corrupt_blob": ("result", b"{}"),
                "extra_blob": ("result", b"{}"),
                "snapshot": ("snapshot", b"{}"),
                "snapshot_hash": ("snapshot_sha256", "0" * 64),
            }[damage]
            changed = connection.execute(f"UPDATE jobs SET {column}=?", (payload,))
        assert changed.rowcount == 1
        connection.commit()
    finally:
        connection.close()
    before = inventory(tmp_path)
    guard_reads(monkeypatch, value.root)
    error = error_output(arguments(value), capsys, 3)
    generic(error, "job_store_integrity_or_io_failure")
    assert inventory(tmp_path) == before


def test_real_bounded_busy_read_remains_generic_without_retry(
    job_case, tmp_path, capsys, monkeypatch
):
    value = job_case
    prepare(value, "QUEUED")
    monkeypatch.setattr(sqlite_job_store, "_BUSY_TIMEOUT_SECONDS", 0.02)
    blocker = sqlite3.connect(value.root / "catalog.sqlite3")
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        before = inventory(tmp_path)
        connections = guard_reads(monkeypatch, value.root)
        started = time.monotonic()
        error = error_output(arguments(value), capsys, 9)
        assert time.monotonic() - started < 5
        generic(error, "job_conflict", "Job catalog read is busy; retry read")
        assert len(connections) == 1
        assert inventory(tmp_path) == before
    finally:
        blocker.rollback()
        blocker.close()


@pytest.mark.parametrize("target", ["root", "catalog"])
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_permission_and_io_errors_do_not_imply_a_known_state(
    job_case, tmp_path, capsys, monkeypatch, target, error_number
):
    value = job_case
    prepare(value, "QUEUED")
    victim = value.root if target == "root" else "catalog.sqlite3"
    real_open = os.open
    observed = []

    def blocked(path, flags, *args, **kwargs):
        if path == victim:
            observed.append(path)
            raise OSError(error_number, MESSAGE)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", blocked)
    before = inventory(tmp_path)
    guard_reads(monkeypatch, value.root)
    error = error_output(arguments(value), capsys, 3)
    generic(error, "job_store_integrity_or_io_failure")
    assert observed
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("entry", ["catalog_symlink", "lock_fifo", "journal_symlink", "wal", "shm"])
def test_unsafe_catalog_entries_are_preserved_as_generic_refusals(
    job_case, tmp_path, capsys, monkeypatch, entry
):
    value = job_case
    prepare(value, "QUEUED")
    if entry == "lock_fifo":
        target = value.root / "coordinator.lock"
        target.unlink()
        os.mkfifo(target)
    elif entry in {"wal", "shm"}:
        (value.root / f"catalog.sqlite3-{entry}").write_bytes(b"retained unsupported sidecar")
    else:
        target = value.root / (
            "catalog.sqlite3" if entry == "catalog_symlink" else "catalog.sqlite3-journal"
        )
        outside = tmp_path / "outside"
        outside.write_bytes(target.read_bytes() if target.exists() else b"protected outside")
        target.unlink(missing_ok=True)
        target.symlink_to(outside)
    before = inventory(tmp_path)
    guard_reads(monkeypatch, value.root)
    error = error_output(arguments(value), capsys, 3)
    generic(error, "job_store_integrity_or_io_failure")
    assert inventory(tmp_path) == before


def test_cli_local_typed_refusal_does_not_change_direct_store_queries(job_case, monkeypatch):
    value = job_case
    row = prepare(value, "QUEUED")
    assert value.store.result(value.spec.spec_id) is None
    before = inventory(value.root)
    guard_reads(monkeypatch, value.root)
    assert value.store.get(value.spec.spec_id) == row
    namespace = argparse.Namespace(
        command="read-job-result", job_id=value.spec.spec_id, jobs=value.root
    )
    with pytest.raises(cli_jobs.JobResultNotSucceededError) as caught:
        cli_jobs.execute(namespace)
    assert isinstance(caught.value, JobConflictError)
    assert str(caught.value) == MESSAGE
    assert caught.value.code == "job_conflict" and caught.value.exit_code == 9
    assert inventory(value.root) == before
