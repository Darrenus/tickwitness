"""Schema1 followup admission and atomic ACK wrappers, using declared offline outcomes."""

import sqlite3
from types import SimpleNamespace

import pytest
from test_followup_job_contracts import ACK, RETRY, failure_for_dispatch, receipt_for_dispatch
from test_native_job_contracts import execution_case
from test_native_job_store import options
from test_sqlite_job_store import tree

from tickwitness.application.jobs import JobConflictError, JobNotFoundError, JobStoreError, job_view
from tickwitness.domain.evidence.run_records import digest
from tickwitness.domain.jobs import (
    build_execution_job_spec,
    build_followup_job_spec,
    build_followup_result,
)
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore

NOW = 1_700_000_000_000_000_000


def claim_spec(store, spec, owner, *, now=NOW):
    store.submit(spec, now_ns=now)
    return store.claim(
        spec.spec_id, expected_version=1, coordinator_id=owner,
        attempt_nonce="a" * 64, lease_token="b" * 64, now_ns=now + 1,
    )


def fail_spec(store, spec, owner, *, now=NOW):
    row = claim_spec(store, spec, owner, now=now)
    return store.fail(
        spec.spec_id,
        {
            "code": "worker_died",
            "message": "Declared interrupted native operation",
            "worker_exit_code": -9,
        },
        **options(row, now_ns=now + 2),
    )


@pytest.fixture
def followup_store(tmp_path):
    case = execution_case()
    root = tmp_path / "jobs"
    store = SqliteJobStore(root, create=True)
    with store.coordinator() as owner:
        original = fail_spec(store, case.spec, owner)
    return SimpleNamespace(root=root, store=store, case=case, original=original)


def test_same_key_submission_is_stable_and_only_one_retry_successor_is_admitted(followup_store):
    value = followup_store
    origin = value.case.spec
    first = build_followup_job_spec(origin, origin.spec_id, RETRY, "retry-A")
    sibling = build_followup_job_spec(origin, origin.spec_id, RETRY, "retry-B")
    with value.store.coordinator():
        queued = value.store.submit(first, now_ns=NOW + 3)
        before = tree(value.root)
        assert value.store.submit(first, now_ns=NOW + 500) == queued
        assert tree(value.root) == before
        with pytest.raises(JobConflictError, match="different retry successor"):
            value.store.submit(sibling, now_ns=NOW + 4)
        assert tree(value.root) == before
        assert value.store.get(origin.spec_id) == value.original
        assert len(value.store.events(first.spec_id)) == 1
    reader = SqliteJobStore(value.root, create=False)
    assert reader.validate_followup_context(first.spec_id) == (value.original,)
    assert tree(value.root) == before


def test_ack_records_do_not_occupy_retry_successor_and_can_use_distinct_recovery_keys(
    followup_store
):
    value = followup_store
    origin = value.case.spec
    specs = [
        build_followup_job_spec(origin, origin.spec_id, ACK, "A"),
        build_followup_job_spec(origin, origin.spec_id, RETRY, "A"),
        build_followup_job_spec(origin, origin.spec_id, ACK, "B"),
    ]
    with value.store.coordinator():
        rows = [value.store.submit(spec, now_ns=NOW + 3) for spec in specs]
        assert len({row["job_id"] for row in rows}) == 3
        before = tree(value.root)
        for spec, row in zip(specs, rows, strict=True):
            assert value.store.submit(spec, now_ns=NOW + 500) == row
        assert tree(value.root) == before
    for spec in specs:
        assert value.store.validate_followup_context(spec.spec_id) == (value.original,)
    assert tree(value.root) == before


def test_child_can_only_follow_a_present_durably_terminal_local_root(followup_store, tmp_path):
    value = followup_store
    origin = value.case.spec
    other = SqliteJobStore(tmp_path / "other", create=True)
    child = build_followup_job_spec(origin, origin.spec_id, ACK, "ack")
    with other.coordinator() as owner:
        before = tree(tmp_path / "other")
        with pytest.raises(JobNotFoundError):
            other.submit(child, now_ns=NOW + 3)
        assert tree(tmp_path / "other") == before
        queued = other.submit(origin, now_ns=NOW)
        before = tree(tmp_path / "other")
        with pytest.raises(JobConflictError, match="durably terminal"):
            other.submit(child, now_ns=NOW + 3)
        assert tree(tmp_path / "other") == before
        running = other.claim(
            origin.spec_id, expected_version=queued["version"], coordinator_id=owner,
            attempt_nonce="a" * 64, lease_token="b" * 64, now_ns=NOW + 1,
        )
        with pytest.raises(JobConflictError, match="durably terminal"):
            other.submit(child, now_ns=NOW + 3)
        assert other.get(origin.spec_id) == running


def test_ack_mode_parent_is_rejected_without_mutating_existing_jobs(followup_store):
    value = followup_store
    origin = value.case.spec
    ack = build_followup_job_spec(origin, origin.spec_id, ACK, "failed-ack")
    child = build_followup_job_spec(origin, ack.spec_id, RETRY, "retry")
    with value.store.coordinator() as owner:
        fail_spec(value.store, ack, owner, now=NOW + 3)
        before = tree(value.root)
        with pytest.raises(JobConflictError, match="acknowledgment-only"):
            value.store.submit(child, now_ns=NOW + 6)
        assert tree(value.root) == before


def test_followup_context_rereads_retry_chain_and_does_not_write_or_require_ownership(
    followup_store
):
    value = followup_store
    origin = value.case.spec
    first = build_followup_job_spec(origin, origin.spec_id, RETRY, "A")
    second = build_followup_job_spec(origin, first.spec_id, ACK, "ack-A")
    with value.store.coordinator() as owner:
        failed_child = fail_spec(value.store, first, owner, now=NOW + 3)
        value.store.submit(second, now_ns=NOW + 6)
    before = tree(value.root)
    reader = SqliteJobStore(value.root, create=False)
    assert reader.validate_followup_context(second.spec_id) == (value.original, failed_child)
    assert reader.validate_followup_context(second.spec_id) == (value.original, failed_child)
    assert tree(value.root) == before


@pytest.mark.parametrize("outcome_kind", ["receipt", "failure"])
def test_ack_complete_atomically_stores_resolution_without_rewriting_original_terminal(
    followup_store, outcome_kind
):
    value = followup_store
    origin = value.case.spec
    ack = build_followup_job_spec(origin, origin.spec_id, ACK, "ack-v1")
    raw_outcome = (
        value.case.receipt.canonical_bytes
        if outcome_kind == "receipt"
        else failure_for_dispatch(value.case, origin)
    )
    raw = build_followup_result(ack, origin, raw_outcome, "acknowledged_committed")
    with value.store.coordinator() as owner:
        row = claim_spec(value.store, ack, owner, now=NOW + 3)
        assert value.store.validate_followup_context(ack.spec_id) == (value.original,)
        finished = value.store.complete(ack.spec_id, raw, **options(row, now_ns=NOW + 5))
        assert finished["state"] == "SUCCEEDED" and finished["result_sha256"] == digest(raw)
        assert value.store.result(ack.spec_id) == raw
        assert value.store.get(origin.spec_id) == value.original
        assert len(value.store.events(origin.spec_id)) == 3
        assert [event["event_type"] for event in value.store.events(ack.spec_id)] == [
            "JobSubmitted", "JobClaimed", "JobSucceeded"
        ]
        before = tree(value.root)
        assert value.store.submit(ack, now_ns=NOW + 500) == finished
        with pytest.raises(JobConflictError):
            value.store.complete(ack.spec_id, raw, **options(finished, now_ns=NOW + 6))
        assert tree(value.root) == before
    reopened = SqliteJobStore(value.root, create=False)
    assert reopened.result(ack.spec_id) == raw
    assert reopened.validate_followup_context(ack.spec_id) == (value.original,)
    assert tree(value.root) == before
    view = job_view(finished, now_ns=NOW + 6, coordinator_active=False)
    assert view["scope"]["research_attempt_reserved"] is None
    assert view["scope"]["native_replayed"] is None
    with sqlite3.connect(value.root / "catalog.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_retry_result_keeps_current_dispatch_separate_from_original_root(followup_store):
    value = followup_store
    origin = value.case.spec
    retry = build_followup_job_spec(origin, origin.spec_id, RETRY, "retry-A")
    receipt = receipt_for_dispatch(value.case, retry)
    raw = build_followup_result(retry, retry, receipt.canonical_bytes, "replayed_from_origin")
    with value.store.coordinator() as owner:
        row = claim_spec(value.store, retry, owner, now=NOW + 3)
        result = value.store.complete(retry.spec_id, raw, **options(row, now_ns=NOW + 5))
        assert result["state"] == "SUCCEEDED"
        assert value.store.result(retry.spec_id) == raw
        assert value.store.get(origin.spec_id) == value.original


def test_original_research_receipt_cannot_replace_required_resolution_wrapper(followup_store):
    value = followup_store
    origin = value.case.spec
    ack = build_followup_job_spec(origin, origin.spec_id, ACK, "ack")
    with value.store.coordinator() as owner:
        row = claim_spec(value.store, ack, owner, now=NOW + 3)
        before = tree(value.root)
        with pytest.raises(JobStoreError):
            value.store.complete(
                ack.spec_id, value.case.receipt.canonical_bytes,
                **options(row, now_ns=NOW + 5),
            )
        assert value.store.result(ack.spec_id) is None
        assert tree(value.root) == before


@pytest.mark.parametrize("mode", [RETRY, ACK])
def test_succeeded_original_parent_may_be_resolved_without_rewriting_its_result(tmp_path, mode):
    case = execution_case()
    store = SqliteJobStore(tmp_path / "jobs", create=True)
    child = build_followup_job_spec(case.spec, case.spec.spec_id, mode, "resolve")
    with store.coordinator() as owner:
        running = claim_spec(store, case.spec, owner)
        original = store.complete(
            case.spec.spec_id, case.receipt.canonical_bytes, **options(running, now_ns=NOW + 2)
        )
        queued = store.submit(child, now_ns=NOW + 3)
        assert queued["state"] == "QUEUED"
        assert store.validate_followup_context(child.spec_id) == (original,)
        assert store.result(case.spec.spec_id) == case.receipt.canonical_bytes
        assert store.get(case.spec.spec_id) == original


def test_changed_origin_cannot_be_rebound_to_existing_parent_or_duplicate_key(followup_store):
    value = followup_store
    changed = build_execution_job_spec({**value.case.request, "preparation": "/changed/prefix"})
    child = build_followup_job_spec(changed, value.case.spec.spec_id, RETRY, "retry-A")
    with value.store.coordinator():
        before = tree(value.root)
        with pytest.raises(JobConflictError, match="exact original root"):
            value.store.submit(child, now_ns=NOW + 3)
        assert tree(value.root) == before
