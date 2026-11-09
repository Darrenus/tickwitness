"""Persisted followup semantics with declared offline native-result fixtures.

Installed remote qualification separately exercises actual native retry and
core-only acknowledgment; saved-result ports here do not qualify native work.
"""

import time

import pytest
from test_job_supervisor import _command
from test_native_job_supervisor import native_job_root as native_job_root
from test_native_job_supervisor import queued, saved_worker
from test_reduction_execution import forbidden
from test_reduction_execution import reduction_case as reduction_case
from test_search_findings import tree

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.evidence.run_records import parse
from tickwitness.domain.jobs.contracts import build_followup_job_spec, job_dispatch_nonce
from tickwitness.infrastructure import job_reduction, job_supervisor
from tickwitness.infrastructure.job_supervisor import run_job


def submit(store, origin, parent, mode, key):
    spec = build_followup_job_spec(origin, parent, mode, key)
    with store.coordinator():
        store.reconcile_orphans(now_ns=time.time_ns())
        row = store.submit(spec, now_ns=time.time_ns())
    return spec, row


def failed_parent(value, root, tmp_path, monkeypatch):
    origin, store, _ = queued(value, root)
    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    row = run_job(
        store,
        origin.spec_id,
        _worker_command=_command(tmp_path, "emit('job_heartbeat_v1',1)\nsys.exit(7)\n"),
    )
    assert row["state"] == "FAILED"
    return origin, store, row


def test_known_exhaustion_refuses_before_creating_original_family_metadata(
    reduction_case, native_job_root, monkeypatch
):
    value = reduction_case
    protocol = value.prepared.materialization.source.validation.protocol
    limit = protocol.document["budget"]["max_attempts"]
    while len(value.ledger.list_reservations(protocol)) < limit:
        value.ledger.reserve(protocol)
    origin, store, _ = queued(value, native_job_root)
    before = tree(value.case.root / "runs")
    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    completed = run_job(store, origin.spec_id)
    assert completed["state"] == "FAILED"
    assert completed["failure"]["code"] == "attempt_budget_exhausted"
    assert completed["failure"]["worker_exit_code"] is None
    assert tree(value.case.root / "runs") == before


def test_explicit_retry_uses_new_original_slot_and_preserves_failed_parent(
    reduction_case, native_job_root, tmp_path, monkeypatch
):
    value = reduction_case
    origin, store, parent = failed_parent(value, native_job_root, tmp_path, monkeypatch)
    before = value.ledger.list_reservations(
        value.prepared.materialization.source.validation.protocol
    )
    child, _ = submit(store, origin, origin.spec_id, "retry_from_origin_v1", "retry-a")
    completed = run_job(store, child.spec_id, _worker_command=saved_worker(value, tmp_path))
    assert completed["state"] == "SUCCEEDED"
    result = parse(store.result(child.spec_id))
    assert result["action"] == "replayed_from_origin"
    assert result["dispatch_job_id"] == child.spec_id
    assert result["outcome"]["attempt"]["nonce"] == job_dispatch_nonce(child)
    after = value.ledger.list_reservations(
        value.prepared.materialization.source.validation.protocol
    )
    assert len(after) == len(before) + 1 and after[:-1] == before
    assert after[-1].document["nonce"] != before[-1].document["nonce"]
    assert store.get(origin.spec_id) == parent
    original = tree(value.case.root / "runs")
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    _, repeated = submit(store, origin, origin.spec_id, "retry_from_origin_v1", "retry-a")
    assert repeated == completed and run_job(store, child.spec_id) == completed
    assert tree(value.case.root / "runs") == original
    with pytest.raises(JobConflictError):
        submit(store, origin, origin.spec_id, "retry_from_origin_v1", "retry-b")


@pytest.mark.parametrize("mode", ["retry_from_origin_v1", "acknowledge_committed_v1"])
def test_committed_result_is_only_acknowledged_without_runtime_or_new_slot(
    reduction_case, native_job_root, tmp_path, monkeypatch, mode
):
    value = reduction_case
    origin, store, _ = queued(value, native_job_root)
    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    parent = run_job(store, origin.spec_id, _worker_command=saved_worker(value, tmp_path))
    receipt = store.result(origin.spec_id)
    followup, _ = submit(store, origin, origin.spec_id, mode, "resolve-a")
    original = tree(value.case.root / "runs")
    monkeypatch.setattr(job_reduction, "require_native_runtime", forbidden)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    completed = run_job(store, followup.spec_id)
    assert completed["state"] == "SUCCEEDED"
    result = parse(store.result(followup.spec_id))
    assert result["action"] == "acknowledged_committed"
    assert result["dispatch_job_id"] == origin.spec_id
    assert result["outcome"] == parse(receipt)
    assert tree(value.case.root / "runs") == original
    assert store.get(origin.spec_id) == parent


def test_ack_commit_error_keeps_atomic_success_and_same_key_does_not_execute_again(
    reduction_case, native_job_root, tmp_path, monkeypatch
):
    value = reduction_case
    origin, store, _ = queued(value, native_job_root)
    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    run_job(store, origin.spec_id, _worker_command=saved_worker(value, tmp_path))
    ack, _ = submit(store, origin, origin.spec_id, "acknowledge_committed_v1", "ack-a")
    complete = store.complete
    calls = []

    def lost_ack(*args, **kwargs):
        completed = complete(*args, **kwargs)
        calls.append(completed)
        raise JobStoreError("Controlled response loss after actual Catalog commit")

    original = tree(value.case.root / "runs")
    monkeypatch.setattr(store, "complete", lost_ack)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    with pytest.raises(JobStoreError, match="response loss"):
        run_job(store, ack.spec_id)
    assert len(calls) == 1 and store.get(ack.spec_id)["state"] == "SUCCEEDED"
    events = store.events(ack.spec_id)
    assert run_job(store, ack.spec_id) == calls[0]
    assert store.events(ack.spec_id) == events
    assert tree(value.case.root / "runs") == original


def test_ack_without_committed_outcome_never_consumes_a_slot(
    reduction_case, native_job_root, tmp_path, monkeypatch
):
    value = reduction_case
    origin, store, _ = failed_parent(value, native_job_root, tmp_path, monkeypatch)
    ack, _ = submit(store, origin, origin.spec_id, "acknowledge_committed_v1", "ack-a")
    original = tree(value.case.root / "runs")
    monkeypatch.setattr(job_reduction, "require_native_runtime", forbidden)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    row = run_job(store, ack.spec_id)
    assert row["state"] == "FAILED" and row["failure"]["code"] == "research_outcome_not_committed"
    assert row["failure"]["worker_exit_code"] is None
    assert tree(value.case.root / "runs") == original
