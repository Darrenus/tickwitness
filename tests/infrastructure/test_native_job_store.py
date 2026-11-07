"""Actual Catalog admission fences with offline original-receipt binding fixtures.

Native execution/publication is qualified separately by installed remote Jobs.
These tests do not run an engine or consume a real research attempt.
"""

import os
import sqlite3
from types import SimpleNamespace

import pytest
from test_native_job_contracts import execution_case
from test_sqlite_job_store import claim, heartbeat, tree

from tickwitness.application.jobs import JobConflictError, JobStoreError, job_view
from tickwitness.domain.evidence.reduction_records import build_reduction_run_receipt
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import build_execution_job_spec, job_dispatch_nonce
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore

NOW = 1_700_000_000_000_000_000


@pytest.fixture
def native_store(tmp_path):
    case = execution_case()
    root = tmp_path / "native-jobs"
    return SimpleNamespace(
        root=root,
        store=SqliteJobStore(root, create=True),
        spec=case.spec,
        request=case.request,
        receipt=case.receipt,
    )


def options(row, **changes):
    attempt = row["attempt"]
    return {
        "expected_version": row["version"],
        "coordinator_id": attempt["coordinator_id"],
        "job_attempt_id": attempt["job_attempt_id"],
        "lease_token": attempt["lease_token"],
        "now_ns": NOW + 2,
        **changes,
    }


def test_current_owner_admission_does_not_write_or_extend_any_catalog_fact(native_store):
    value = native_store
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        before = tree(value.root)
        events = value.store.events(value.spec.spec_id)
        for timestamp in (NOW + 2, NOW + 500, NOW + 999):
            assert (
                value.store.assert_active(value.spec.spec_id, **options(row, now_ns=timestamp))
                == row
            )
        assert tree(value.root) == before
        assert value.store.events(value.spec.spec_id) == events
        assert value.store.get(value.spec.spec_id) == row
        assert value.store.result(value.spec.spec_id) is None
    reader = SqliteJobStore(value.root, create=False)
    assert reader.get(value.spec.spec_id) == row
    assert tree(value.root) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_version": 1},
        {"expected_version": True},
        {"expected_version": 0},
        {"expected_version": "2"},
        {"coordinator_id": "0" * 64},
        {"job_attempt_id": "0" * 64},
        {"lease_token": "0" * 64},
        {"now_ns": NOW},
        {"now_ns": NOW + 1 + 1_000_000_000},
        {"now_ns": True},
    ],
)
def test_expired_wrong_epoch_attempt_token_or_version_cannot_admit_publication(
    native_store, changes
):
    value = native_store
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        before = tree(value.root)
        with pytest.raises(JobConflictError) as caught:
            value.store.assert_active(value.spec.spec_id, **options(row, **changes))
        assert caught.value.exit_code == 9
        assert tree(value.root) == before
        assert value.store.get(value.spec.spec_id) == row


def test_admission_reads_latest_heartbeat_version_instead_of_trusting_cached_snapshot(native_store):
    value = native_store
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        stale = claim(value, owner)
        current = heartbeat(value, stale)
        before = tree(value.root)
        with pytest.raises(JobConflictError, match="version changed"):
            value.store.assert_active(value.spec.spec_id, **options(stale))
        assert value.store.assert_active(value.spec.spec_id, **options(current)) == current
        assert tree(value.root) == before


def test_admission_requires_the_live_posix_owner_not_a_reader_or_inherited_pid(
    native_store, monkeypatch
):
    value = native_store
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        before = tree(value.root)
        reader = SqliteJobStore(value.root, create=False)
        with pytest.raises(JobConflictError, match="exclusive coordinator ownership"):
            reader.assert_active(value.spec.spec_id, **options(row))
        with monkeypatch.context() as changed:
            changed.setattr(value.store, "_owner_pid", os.getpid() + 1)
            with pytest.raises(JobConflictError, match="exclusive coordinator ownership"):
                value.store.assert_active(value.spec.spec_id, **options(row))
        with monkeypatch.context() as changed:
            changed.setattr(value.store, "_owner_fd", None)
            with pytest.raises(JobConflictError, match="exclusive coordinator ownership"):
                value.store.assert_active(value.spec.spec_id, **options(row))
        assert tree(value.root) == before
    with pytest.raises(JobConflictError, match="exclusive coordinator ownership"):
        value.store.assert_active(value.spec.spec_id, **options(row))
    assert tree(value.root) == before


@pytest.mark.parametrize("lost", ["pid", "descriptor", "epoch"])
def test_admission_rechecks_owner_after_a_potentially_blocking_snapshot_read(
    native_store, monkeypatch, lost
):
    value = native_store
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        before = tree(value.root)
        actual_get = value.store.get
        with monkeypatch.context() as changed:

            def lose_owner_after_read(job_id):
                observed = actual_get(job_id)
                if lost == "pid":
                    changed.setattr(value.store, "_owner_pid", os.getpid() + 1)
                elif lost == "descriptor":
                    changed.setattr(value.store, "_owner_fd", None)
                else:
                    changed.setattr(value.store, "_owner", "0" * 64)
                return observed

            changed.setattr(value.store, "get", lose_owner_after_read)
            with pytest.raises(JobConflictError):
                value.store.assert_active(value.spec.spec_id, **options(row))
        assert value.store.get(value.spec.spec_id) == row
        assert tree(value.root) == before


def test_new_owner_cannot_admit_a_former_running_attempt_even_before_reconciliation(native_store):
    value = native_store
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        stale = claim(value, owner)
    reopened = SqliteJobStore(value.root, create=False)
    with reopened.coordinator() as new_owner:
        before = tree(value.root)
        with pytest.raises(JobConflictError):
            reopened.assert_active(value.spec.spec_id, **options(stale))
        with pytest.raises(JobConflictError):
            reopened.assert_active(value.spec.spec_id, **options(stale, coordinator_id=new_owner))
        assert tree(value.root) == before
        lost = reopened.reconcile_orphans(now_ns=NOW + 3)
        assert len(lost) == 1 and lost[0]["state"] == "LOST"
        after = tree(value.root)
        with pytest.raises(JobConflictError):
            reopened.assert_active(
                value.spec.spec_id, **options(lost[0], coordinator_id=new_owner, now_ns=NOW + 4)
            )
        assert tree(value.root) == after


@pytest.mark.parametrize("pending", [False, True])
def test_atomic_native_success_stores_exact_original_manifest_without_schema_upgrade(
    tmp_path, pending
):
    case = execution_case(pending=pending)
    root = tmp_path / "catalog"
    store = SqliteJobStore(root, create=True)
    value = SimpleNamespace(spec=case.spec, store=store)
    with store.coordinator() as owner:
        submitted = store.submit(case.spec, now_ns=NOW)
        assert store.submit(case.spec, now_ns=NOW + 1) == submitted
        row = claim(value, owner)
        assert store.assert_active(case.spec.spec_id, **options(row)) == row
        finished = store.complete(case.spec.spec_id, case.receipt.canonical_bytes, **options(row))
        assert finished["state"] == "SUCCEEDED"
        assert finished["result_sha256"] == case.receipt.run_id
        assert store.result(case.spec.spec_id) == case.receipt.canonical_bytes
        events = store.events(case.spec.spec_id)
        assert [event["event_type"] for event in events] == [
            "JobSubmitted",
            "JobClaimed",
            "JobSucceeded",
        ]
        assert [event["aggregate_version"] for event in events] == [1, 2, 3]
        before = tree(root)
        assert store.submit(case.spec, now_ns=NOW + 3) == finished
        with pytest.raises(JobConflictError):
            store.assert_active(case.spec.spec_id, **options(finished, now_ns=NOW + 3))
        assert tree(root) == before
    reopened = SqliteJobStore(root, create=False)
    assert reopened.get(case.spec.spec_id) == finished
    assert reopened.result(case.spec.spec_id) == case.receipt.canonical_bytes
    assert tree(root) == before
    with sqlite3.connect(root / "catalog.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } == {"jobs", "job_events"}
        actual_result = connection.execute(
            "SELECT result FROM jobs WHERE job_id=?", (case.spec.spec_id,)
        ).fetchone()[0]
    assert actual_result == case.receipt.canonical_bytes
    view = job_view(finished, now_ns=NOW + 3, coordinator_active=False)
    assert view["scope"]["research_attempt_reserved"] is True
    assert view["scope"]["native_replayed"] is True


@pytest.mark.parametrize(
    "attack", ["preparation_pin", "bundle_pin", "report_pin", "dispatch_nonce", "raw_result"]
)
def test_native_manifest_binding_failure_leaves_no_success_blob_or_event(native_store, attack):
    value = native_store
    document = value.receipt.document
    if attack == "raw_result":
        raw = canonical({"kind": "replay_qualification_result_v1", "execution_status": "completed"})
    elif attack == "dispatch_nonce":
        document["attempt"]["nonce"] = "0" * 32
        raw = build_reduction_run_receipt(document).canonical_bytes
    else:
        pin = {
            "preparation_pin": "expected_preparation_id",
            "bundle_pin": "expected_bundle_id",
            "report_pin": "expected_report_id",
        }[attack]
        value.spec = build_execution_job_spec(
            {**value.request, pin: "0" * 64}, lease_duration_ns=1_000_000_000
        )
        document["attempt"]["nonce"] = job_dispatch_nonce(value.spec)
        raw = build_reduction_run_receipt(document).canonical_bytes
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        before = tree(value.root)
        with pytest.raises(JobStoreError):
            value.store.complete(value.spec.spec_id, raw, **options(row))
        assert value.store.get(value.spec.spec_id) == row
        assert value.store.result(value.spec.spec_id) is None
        assert len(value.store.events(value.spec.spec_id)) == 2
        assert tree(value.root) == before


def test_native_result_blob_hash_and_exact_receipt_are_checked_again_on_read(native_store):
    value = native_store
    with value.store.coordinator() as owner:
        value.store.submit(value.spec, now_ns=NOW)
        row = claim(value, owner)
        value.store.complete(value.spec.spec_id, value.receipt.canonical_bytes, **options(row))
    document = value.receipt.document
    document["attempt"]["nonce"] = "0" * 32
    forged = build_reduction_run_receipt(document).canonical_bytes
    assert digest(forged) != value.receipt.run_id
    with sqlite3.connect(value.root / "catalog.sqlite3") as connection:
        connection.execute("UPDATE jobs SET result=?", (forged,))
    before = tree(value.root)
    reader = SqliteJobStore(value.root, create=False)
    with pytest.raises(JobStoreError, match="dispatch nonce"):
        reader.result(value.spec.spec_id)
    assert tree(value.root) == before
