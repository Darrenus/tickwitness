"""Real SQLite/lock persistence; comparison data is a declared offline domain fixture.

Store tests establish atomic job/binding behavior, not a new native execution or
independent scientific verdict. Installed qualification separately delegates the
real comparison operation and reaudits its source evidence.
"""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from threading import Event
from types import SimpleNamespace

import pytest
from test_reduction_comparison_contract import compare as comparison_fixture

from tickwitness.application.jobs import (
    JobConflictError,
    JobNotFoundError,
    JobStoreError,
    job_view,
)
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import JobValidationError, build_job_spec
from tickwitness.infrastructure import sqlite_job_store
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore, _event

NOW = 1_700_000_000_000_000_000
_HOT_JOURNAL_CHILD = """
import os, signal, sys
from pathlib import Path
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
root, gate = Path(sys.argv[1]), Path(sys.argv[2])
store = SqliteJobStore(root)
original_size = (root / 'catalog.sqlite3').stat().st_size
with store.coordinator():
    with store._connection(write=True) as connection:
        connection.execute('PRAGMA cache_size=1')
        connection.execute('PRAGMA cache_spill=ON')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('UPDATE jobs SET snapshot=?', (b'x' * (4 * 1024 * 1024),))
        journal = root / 'catalog.sqlite3-journal'
        assert journal.stat().st_size > 512
        with journal.open('rb') as stream:
            assert stream.read(8) != b'\\x00' * 8
        assert (root / 'catalog.sqlite3').stat().st_size > original_size
        gate.write_text(str(os.getpid()))
        signal.pause()
"""


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


@pytest.fixture
def job_case(tmp_path):
    comparison = comparison_fixture()
    bindings = comparison.document["bindings"]
    request = {
        "run_id": bindings["reduced"]["run_id"],
        "expected_bundle_id": bindings["source"]["bundle_id"],
        "expected_report_id": bindings["source"]["report_id"],
        "input_root": "/declared-job-inputs",
        "source_evidence": "source",
        "runs": "/declared-existing-runs",
        "split": "development",
    }
    spec = build_job_spec(request, lease_duration_ns=1_000_000_000)
    root = tmp_path / "jobs"
    return SimpleNamespace(
        root=root,
        store=SqliteJobStore(root, create=True),
        spec=spec,
        request=request,
        comparison=comparison,
    )


def claim(value, owner, *, version=1, now=NOW + 1):
    return value.store.claim(
        value.spec.spec_id,
        expected_version=version,
        coordinator_id=owner,
        attempt_nonce="a" * 64,
        lease_token="b" * 64,
        now_ns=now,
    )


def heartbeat(value, row, *, now=NOW + 2, **changes):
    attempt = row["attempt"]
    options = {
        "expected_version": row["version"],
        "coordinator_id": attempt["coordinator_id"],
        "job_attempt_id": attempt["job_attempt_id"],
        "lease_token": attempt["lease_token"],
        "sequence": attempt["heartbeat_sequence"] + 1,
        "now_ns": now,
    }
    options.update(changes)
    return value.store.heartbeat(value.spec.spec_id, **options)


def complete(value, row, *, now=NOW + 3, raw=None, **changes):
    attempt = row["attempt"]
    options = {
        "expected_version": row["version"],
        "coordinator_id": attempt["coordinator_id"],
        "job_attempt_id": attempt["job_attempt_id"],
        "lease_token": attempt["lease_token"],
        "now_ns": now,
    }
    options.update(changes)
    return value.store.complete(
        value.spec.spec_id, value.comparison.export_bytes if raw is None else raw, **options
    )


def failure():
    return {"code": "operation_failed", "message": "Declared worker failure", "worker_exit_code": 2}


def test_readonly_missing_constructor_creates_no_root_or_database(tmp_path):
    missing = tmp_path / "missing" / "jobs"
    with pytest.raises(JobNotFoundError):
        SqliteJobStore(missing, create=False)
    assert not (tmp_path / "missing").exists()


def test_queries_are_byte_unchanged_and_never_create_wal_or_sidecars(job_case):
    value = job_case
    with value.store.coordinator():
        queued = value.store.submit(value.spec, now_ns=NOW)
    before = tree(value.root)
    reader = SqliteJobStore(value.root, create=False)
    assert reader.get(value.spec.spec_id) == queued
    assert reader.result(value.spec.spec_id) is None
    assert reader.events(value.spec.spec_id)[0]["event_type"] == "JobSubmitted"
    assert reader.coordinator_active() is False
    assert tree(value.root) == before
    assert set(before) == {"catalog.sqlite3", "coordinator.lock"}


@pytest.mark.parametrize("method", ["get", "events", "result"])
def test_exclusive_sql_lock_yields_bounded_retryable_read_conflict_without_mutation(
    job_case, monkeypatch, method
):
    value = job_case
    with value.store.coordinator():
        queued = value.store.submit(value.spec, now_ns=NOW)
    before = tree(value.root)
    reader = SqliteJobStore(value.root, create=False)
    monkeypatch.setattr(sqlite_job_store, "_BUSY_TIMEOUT_SECONDS", 0.02)
    with sqlite3.connect(value.root / "catalog.sqlite3") as blocker:
        blocker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with pytest.raises(JobConflictError, match="read is busy; retry read") as caught:
            getattr(reader, method)(value.spec.spec_id)
        assert time.monotonic() - started < 5
        assert caught.value.exit_code == 9
        assert tree(value.root) == before
    assert reader.get(value.spec.spec_id) == queued
    assert tree(value.root) == before


def test_exclusive_sql_lock_keeps_writer_failure_unconfirmed_without_automatic_retry(
    job_case, monkeypatch
):
    value = job_case
    with value.store.coordinator():
        queued = value.store.submit(value.spec, now_ns=NOW)
        before = tree(value.root)
        monkeypatch.setattr(sqlite_job_store, "_BUSY_TIMEOUT_SECONDS", 0.02)
        with sqlite3.connect(value.root / "catalog.sqlite3") as blocker:
            blocker.execute("BEGIN EXCLUSIVE")
            with pytest.raises(JobStoreError, match="publication is unconfirmed") as caught:
                value.store.submit(value.spec, now_ns=NOW + 1)
            assert not isinstance(caught.value, JobConflictError)
            assert tree(value.root) == before
        assert value.store.get(value.spec.spec_id) == queued
        assert tree(value.root) == before


def test_submission_is_idempotent_without_new_events_or_timestamp_reset(job_case):
    value = job_case
    with value.store.coordinator():
        original = value.store.submit(value.spec, now_ns=NOW)
        assert value.store.submit(value.spec, now_ns=NOW - 1) == original
        assert value.store.submit(value.spec, now_ns=NOW + 500) == original
        assert len(value.store.events(value.spec.spec_id)) == 1
        with pytest.raises(JobValidationError):
            value.store.submit(value.spec, now_ns=True)
    assert value.store.get(value.spec.spec_id) == original


def test_all_mutations_need_exclusive_ownership_and_lock_descriptor_is_not_inherited(job_case):
    value = job_case
    with pytest.raises(JobConflictError):
        value.store.submit(value.spec, now_ns=NOW)
    other = SqliteJobStore(value.root, create=False)
    with value.store.coordinator() as owner:
        assert value.store.coordinator_active() is other.coordinator_active() is True
        assert value.store._owner_fd is not None
        assert not os.get_inheritable(value.store._owner_fd)
        with pytest.raises(JobConflictError), other.coordinator():
            pass
        with pytest.raises(JobConflictError), value.store.coordinator():
            pass
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
    assert other.coordinator_active() is False
    with pytest.raises(JobConflictError):
        heartbeat(value, row)
    assert value.store.get(value.spec.spec_id) == row


def test_heartbeat_then_atomic_success_binds_real_export_and_event_chain(job_case):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = heartbeat(value, claim(value, owner))
        finished = complete(value, row)
        assert finished["state"] == "SUCCEEDED"
        assert finished["result_sha256"] == digest(value.comparison.export_bytes)
        assert value.store.result(value.spec.spec_id) == value.comparison.export_bytes
        events = value.store.events(value.spec.spec_id)
        assert [event["event_type"] for event in events] == [
            "JobSubmitted",
            "JobClaimed",
            "JobHeartbeatRecorded",
            "JobSucceeded",
        ]
        assert [event["aggregate_version"] for event in events] == [1, 2, 3, 4]
        previous = value.spec.spec_id
        for event in events:
            assert event["causation_id"] == previous
            assert event["aggregate_id"] == event["correlation_id"] == value.spec.spec_id
            assert event["snapshot_sha256"] == digest(canonical(event["snapshot"]))
            payload = dict(event)
            assert payload.pop("event_id") == digest(canonical(payload))
            previous = event["event_id"]
        assert value.store.events(value.spec.spec_id, limit=2) == events[-2:]
    reopened = SqliteJobStore(value.root, create=False)
    assert reopened.get(value.spec.spec_id) == finished
    assert reopened.result(value.spec.spec_id) == value.comparison.export_bytes


@pytest.mark.parametrize(
    "changed",
    [
        {"expected_version": 1},
        {"coordinator_id": "0" * 64},
        {"job_attempt_id": "0" * 64},
        {"lease_token": "0" * 64},
        {"sequence": 2},
    ],
)
def test_wrong_version_epoch_attempt_token_or_sequence_never_mutates(job_case, changed):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        before = value.store.events(value.spec.spec_id)
        with pytest.raises(JobConflictError):
            heartbeat(value, row, **changed)
        assert value.store.get(value.spec.spec_id) == row
        assert value.store.events(value.spec.spec_id) == before


def test_only_one_running_job_can_be_claimed_even_by_same_owner(job_case):
    value = job_case
    other = build_job_spec({**value.request, "input_root": "/another-declared-root"})
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        value.store.submit(other, now_ns=NOW)
        claim(value, owner)
        with pytest.raises(JobConflictError, match="Single-worker"):
            value.store.claim(
                other.spec_id,
                expected_version=1,
                coordinator_id=owner,
                attempt_nonce="c" * 64,
                lease_token="d" * 64,
                now_ns=NOW + 2,
            )
        assert value.store.get(other.spec_id)["state"] == "QUEUED"


def test_new_owner_reconciles_old_epoch_without_retry_and_rejects_old_credentials(job_case):
    value = job_case
    with value.store.coordinator() as old_owner:
        value.store.submit(value.spec, now_ns=NOW)
        running = claim(value, old_owner)
    view = job_view(running, now_ns=NOW + 2, coordinator_active=False)
    assert view["state"] == "COORDINATOR_LOST"
    with value.store.coordinator() as new_owner:
        assert new_owner != old_owner
        with pytest.raises(JobConflictError, match="epoch"):
            heartbeat(value, running)
        changed = value.store.reconcile_orphans(now_ns=NOW + 3)
        assert len(changed) == 1 and changed[0]["state"] == "LOST"
        assert changed[0]["failure"]["code"] == "coordinator_lost"
        assert changed[0]["attempt"]["job_attempt_id"] == running["attempt"]["job_attempt_id"]
        assert value.store.reconcile_orphans(now_ns=NOW + 4) == []
        assert value.store.submit(value.spec, now_ns=NOW + 5) == changed[0]
        with pytest.raises(JobConflictError):
            claim(value, new_owner, version=changed[0]["version"], now=NOW + 6)


def test_killed_owner_hot_journal_requires_explicit_rw_owner_recovery(job_case, tmp_path):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        original = claim(value, owner)
    gate = tmp_path / "hot-journal-ready"
    process = subprocess.Popen(
        [sys.executable, "-c", _HOT_JOURNAL_CHILD, str(value.root), str(gate)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    try:
        deadline = time.monotonic() + 20
        while not gate.exists() and process.poll() is None and time.monotonic() < deadline:
            Event().wait(0.01)
        if not gate.exists():
            if process.poll() is None:
                process.kill()
            _, diagnostic = process.communicate(timeout=5)
            pytest.fail("Hot journal gate was not reached: " + diagnostic.decode(errors="replace"))
        assert gate.read_text() == str(process.pid)
        process.kill()
        assert process.wait(timeout=5) == -signal.SIGKILL
        before = tree(value.root)
        assert "catalog.sqlite3-journal" in before
        reader = SqliteJobStore(value.root, create=False)
        with pytest.raises(JobStoreError):
            reader.get(value.spec.spec_id)
        assert tree(value.root) == before
        with reader.coordinator():
            changed = reader.reconcile_orphans(now_ns=NOW + 2)
        assert len(changed) == 1
        lost = changed[0]
        assert lost["state"] == "LOST" and lost["failure"]["code"] == "coordinator_lost"
        assert lost["attempt"] == original["attempt"]
        assert lost["created_at_ns"] == original["created_at_ns"]
        assert lost["version"] == original["version"] + 1
        assert reader.result(value.spec.spec_id) is None
        assert [event["event_type"] for event in reader.events(value.spec.spec_id)] == [
            "JobSubmitted",
            "JobClaimed",
            "JobLost",
        ]
        assert not (value.root / "catalog.sqlite3-journal").exists()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_clock_reversal_is_visible_and_cannot_reconcile_by_inventing_time(job_case):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        running = claim(value, owner)
        view = job_view(running, now_ns=NOW, coordinator_active=True)
        assert view["stored_state"] == "RUNNING" and view["state"] == "CLOCK_UNCERTAIN"
        assert "lease_token" not in view["attempt"] and "nonce" not in view["attempt"]
        with pytest.raises(JobConflictError):
            heartbeat(value, running, now=NOW)
    with value.store.coordinator():
        with pytest.raises(JobConflictError):
            value.store.reconcile_orphans(now_ns=NOW)
        assert value.store.get(value.spec.spec_id) == running


def test_expired_lease_refuses_late_heartbeat_completion_and_becomes_lost(job_case):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        running = claim(value, owner)
        expired = running["attempt"]["lease_expires_at_ns"]
        with pytest.raises(JobConflictError):
            heartbeat(value, running, now=expired)
        with pytest.raises(JobConflictError):
            complete(value, running, now=expired)
        with pytest.raises(JobConflictError):
            value.store.mark_lost(
                value.spec.spec_id,
                expected_version=running["version"],
                reason="coordinator_lost",
                now_ns=NOW + 2,
            )
        lost = value.store.mark_lost(
            value.spec.spec_id,
            expected_version=running["version"],
            reason="lease_expired",
            now_ns=expired,
        )
        assert lost["state"] == "LOST" and lost["result_sha256"] is None


@pytest.mark.parametrize("pin", ["bundle_id", "report_id", "run_id"])
def test_rehashed_output_still_requires_exact_job_source_and_run_pins(job_case, pin):
    value = job_case
    exported = json.loads(value.comparison.export_bytes)
    if pin == "run_id":
        exported["report"]["bindings"]["reduced"][pin] = "0" * 64
    else:
        exported["report"]["bindings"]["source"][pin] = "0" * 64
    exported["comparison_id"] = digest(canonical(exported["report"]))
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        with pytest.raises(JobStoreError, match="pins"):
            complete(value, row, raw=canonical(exported))
        assert value.store.get(value.spec.spec_id) == row
        assert value.store.result(value.spec.spec_id) is None
        assert len(value.store.events(value.spec.spec_id)) == 2


def test_failed_job_keeps_diagnostic_and_never_becomes_a_research_verdict(job_case):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        failed = value.store.fail(
            value.spec.spec_id,
            failure(),
            expected_version=row["version"],
            coordinator_id=owner,
            job_attempt_id=row["attempt"]["job_attempt_id"],
            lease_token=row["attempt"]["lease_token"],
            now_ns=NOW + 2,
        )
        assert failed["state"] == "FAILED" and failed["failure"] == failure()
        assert value.store.result(value.spec.spec_id) is None
        view = job_view(failed, now_ns=NOW + 3, coordinator_active=True)
        assert view["scope"]["research_attempt_reserved"] is False


@pytest.mark.parametrize("stage", ["submit", "complete"])
def test_event_insert_failure_rolls_back_snapshot_and_result_together(job_case, monkeypatch, stage):
    value = job_case

    def fail_event(_connection, _event):
        raise OSError("Declared event write failure")

    with value.store.coordinator() as owner:
        if stage == "complete":
            value.store.submit(value.spec, now_ns=NOW)
            row = claim(value, owner)
        monkeypatch.setattr(value.store, "_insert_event", fail_event)
        with pytest.raises(JobStoreError, match="unconfirmed"):
            if stage == "submit":
                value.store.submit(value.spec, now_ns=NOW)
            else:
                complete(value, row)
        if stage == "submit":
            with pytest.raises(JobNotFoundError):
                value.store.get(value.spec.spec_id)
        else:
            assert value.store.get(value.spec.spec_id) == row
            assert value.store.result(value.spec.spec_id) is None
            assert len(value.store.events(value.spec.spec_id)) == 2


def test_error_after_commit_keeps_actual_success_and_refuses_failure_overwrite(
    job_case,
    monkeypatch,
):
    value = job_case

    def late_error(connection):
        connection.commit()
        raise OSError("Commit acknowledgement was lost")

    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        running = claim(value, owner)
        monkeypatch.setattr(value.store, "_commit", late_error)
        with pytest.raises(JobStoreError, match="unconfirmed"):
            complete(value, running)
        finished = value.store.get(value.spec.spec_id)
        assert finished["state"] == "SUCCEEDED"
        assert value.store.result(value.spec.spec_id) == value.comparison.export_bytes
        with pytest.raises(JobConflictError):
            value.store.fail(
                value.spec.spec_id,
                failure(),
                expected_version=finished["version"],
                coordinator_id=owner,
                job_attempt_id=running["attempt"]["job_attempt_id"],
                lease_token=running["attempt"]["lease_token"],
                now_ns=NOW + 4,
            )
        assert value.store.get(value.spec.spec_id) == finished


@pytest.mark.parametrize("change", ["future", "foreign", "unversioned"])
def test_foreign_or_future_catalog_is_not_initialized_over(job_case, change):
    value = job_case
    with sqlite3.connect(value.root / "catalog.sqlite3") as connection:
        if change == "future":
            connection.execute("PRAGMA user_version=99")
        elif change == "foreign":
            connection.execute("PRAGMA application_id=1")
        else:
            connection.execute("PRAGMA user_version=0")
    before = tree(value.root)
    for create in (False, True):
        with pytest.raises(JobStoreError):
            SqliteJobStore(value.root, create=create)
    assert tree(value.root) == before


def test_corrupt_table_shape_is_rejected_readonly_without_schema_repair(job_case):
    value = job_case
    with sqlite3.connect(value.root / "catalog.sqlite3") as connection:
        connection.execute("DROP TABLE job_events")
    before = tree(value.root)
    reader = SqliteJobStore(value.root, create=False)
    with pytest.raises(JobStoreError, match="schema differs"):
        reader.get(value.spec.spec_id)
    assert tree(value.root) == before


def test_similarly_named_sqlite_object_is_not_hidden_from_schema_validation(job_case):
    value = job_case
    with sqlite3.connect(value.root / "catalog.sqlite3") as connection:
        connection.execute("CREATE VIEW sqlitex_unexpected AS SELECT 1 AS value")
    before = tree(value.root)
    reader = SqliteJobStore(value.root, create=False)
    with pytest.raises(JobStoreError, match="schema differs"):
        reader.get(value.spec.spec_id)
    assert tree(value.root) == before


def test_sparse_high_version_event_suffix_is_rejected_with_bounded_work(job_case):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        original = claim(value, owner)
    high = 2**62
    previous = {
        **original,
        "version": high - 1,
        "attempt": {**original["attempt"], "heartbeat_sequence": high - 3},
    }
    current = {
        **original,
        "version": high,
        "attempt": {**original["attempt"], "heartbeat_sequence": high - 2},
    }
    previous_event = _event(previous, "JobHeartbeatRecorded", "0" * 64)
    current_event = _event(current, "JobHeartbeatRecorded", previous_event["event_id"])
    raw = canonical(current)
    with sqlite3.connect(value.root / "catalog.sqlite3") as connection:
        connection.execute(
            "UPDATE jobs SET version=?,snapshot_sha256=?,snapshot=?",
            (high, digest(raw), raw),
        )
        for event in (previous_event, current_event):
            connection.execute(
                "INSERT INTO job_events(job_id,version,event_id,event) VALUES(?,?,?,?)",
                (
                    value.spec.spec_id,
                    event["aggregate_version"],
                    event["event_id"],
                    canonical(event),
                ),
            )
    before = tree(value.root)
    with pytest.raises(JobStoreError, match="suffix is not contiguous"):
        value.store.events(value.spec.spec_id, limit=100)
    assert tree(value.root) == before


@pytest.mark.parametrize("field", ["snapshot_sha256", "snapshot", "event", "result"])
def test_tampered_row_event_or_result_is_not_a_successful_query(job_case, field):
    value = job_case
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        complete(value, claim(value, owner))
    with sqlite3.connect(value.root / "catalog.sqlite3") as connection:
        if field == "event":
            connection.execute("UPDATE job_events SET event=? WHERE version=3", (b"{}",))
        elif field == "snapshot_sha256":
            connection.execute("UPDATE jobs SET snapshot_sha256=?", ("0" * 64,))
        elif field == "snapshot":
            connection.execute("UPDATE jobs SET snapshot=?", (b"{}",))
        else:
            connection.execute("UPDATE jobs SET result=?", (b"{}",))
    before = tree(value.root)
    with pytest.raises(JobStoreError):
        value.store.get(value.spec.spec_id)
    assert tree(value.root) == before


@pytest.mark.parametrize("name", ["catalog.sqlite3", "coordinator.lock", "catalog.sqlite3-journal"])
def test_catalog_lock_and_existing_journal_symlinks_are_not_followed(job_case, name):
    value = job_case
    outside = value.root.parent / "outside"
    outside.write_bytes(b"protected outside data")
    target = value.root / name
    target.unlink(missing_ok=True)
    target.symlink_to(outside)
    before = outside.read_bytes()
    with pytest.raises(JobStoreError):
        reader = SqliteJobStore(value.root, create=False)
        if name.endswith("-journal"):
            reader.get(value.spec.spec_id)
    assert outside.read_bytes() == before


@pytest.mark.parametrize("name", ["catalog.sqlite3", "coordinator.lock"])
def test_fifo_catalog_files_are_rejected_without_blocking(job_case, name):
    value = job_case
    target = value.root / name
    target.unlink()
    os.mkfifo(target)
    with pytest.raises(JobStoreError, match="regular"):
        SqliteJobStore(value.root, create=False)


def test_root_symlink_is_rejected_and_partial_initialization_is_not_reset(job_case):
    value = job_case
    alias = value.root.parent / "alias"
    alias.symlink_to(value.root, target_is_directory=True)
    with pytest.raises(JobStoreError):
        SqliteJobStore(alias, create=False)
    (value.root / "catalog.sqlite3").unlink()
    with pytest.raises(JobStoreError, match="Partial"):
        SqliteJobStore(value.root, create=True)


@pytest.mark.parametrize("limit", [0, 1001, True])
def test_event_reads_have_an_explicit_nonboolean_bound(job_case, limit):
    with pytest.raises(JobStoreError):
        job_case.store.events(job_case.spec.spec_id, limit=limit)
