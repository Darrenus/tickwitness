"""Persisted native-Job semantics using explicitly offline saved-result ports.

The subprocess result fixtures here are not native execution qualification.
Installed eight-slot qualification separately uses actual Nautilus workers.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress

import pytest
from test_campaign_supervisor import _alive
from test_job_supervisor import _command
from test_reduction_execution import forbidden
from test_reduction_execution import reduction_case as reduction_case

from tickwitness.application.experiments import ProtocolRunError
from tickwitness.application.jobs import JobConflictError
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.domain.jobs.contracts import build_execution_job_spec, job_dispatch_nonce
from tickwitness.infrastructure import job_reduction, job_supervisor, native_job_worker
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.job_reduction import inspect_native_job_dispatch, prepare_native_job
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.nautilus_replay import ReplayDependencyError
from tickwitness.infrastructure.reduction_bundles import LocalReductionBundles
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore


@pytest.fixture
def native_job_root(tmp_path_factory):
    # The original research fixture keeps its ledger beside portable evidence.
    # Give managed input, publication and Catalog their own sibling workspace.
    return tmp_path_factory.mktemp("native-job-supervisor")


def queued(value, native_job_root, *, lease_ns=30_000_000_000):
    inputs = native_job_root / "inputs"
    inputs.mkdir()
    shutil.copytree(value.case.root / "portable-source", inputs / "portable-source")
    preparation = native_job_root / "prepared"
    LocalReductionBundles(inputs).publish(value.prepared, preparation)
    spec = build_execution_job_spec(
        {
            "preparation": str(preparation.absolute()),
            "expected_preparation_id": value.prepared.preparation_id,
            "expected_bundle_id": value.source.bundle_id,
            "expected_report_id": digest(value.source.artifacts["finding_report"]),
            "input_root": str(inputs.absolute()),
            "source_evidence": "portable-source",
            "runs": str((value.case.root / "runs").absolute()),
            "split": "development",
            "engine_runtime": "coordinator_interpreter_v1",
            "restart_mode": "frozen_origin_new_attempt_only_v1",
        },
        lease_duration_ns=lease_ns,
    )
    store = SqliteJobStore(native_job_root / "catalog", create=True)
    with store.coordinator():
        row = store.submit(spec, now_ns=time.time_ns())
    return spec, store, row


def saved_worker(value, tmp_path, *, wrong_context=False):
    # Existing declared saved-native fixture port, not a fresh native engine.
    result = value.case.engine_factory(60).run(value.prepared.materialization.replay_input)
    document = result.document
    if wrong_context:
        document["dataset_id"] = "0" * 64
    fixture = tmp_path / "saved-result.json"
    fixture.write_bytes(canonical(document))
    return _command(
        tmp_path,
        "emit('job_heartbeat_v1',1)\n"
        f"result=json.loads(open({str(fixture)!r}).read())\n"
        "emit('job_native_result_v1',2,replay_result=result)\n",
    )


def test_coordinator_reserves_and_binds_before_worker_and_terminal_repeat_is_idempotent(
    reduction_case,
    tmp_path,
    native_job_root,
    monkeypatch,
):
    value = reduction_case
    spec, store, row = queued(value, native_job_root)
    command = saved_worker(value, tmp_path)
    prepared = prepare_native_job(spec)
    actual_popen = subprocess.Popen
    calls = []

    def launch(*args, **kwargs):
        slots = value.ledger.list_reservations(prepared.execution.protocol)
        reservation = slots[-1]
        assert reservation.attempt_index == 3
        assert reservation.document["nonce"] == job_dispatch_nonce(spec)
        assert (
            value.ledger.get_intent(reservation.attempt_id)
            == prepared.execution.intent.canonical_bytes
        )
        assert value.ledger.get_outcome(reservation.attempt_id) is None
        for artifact in prepared.execution.artifacts:
            assert value.ledger.read_artifact(digest(artifact)) == artifact
        calls.append(reservation.attempt_id)
        return actual_popen(*args, **kwargs)

    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", launch)
    result = run_job(store, row["job_id"], _worker_command=command)
    assert result["state"] == "SUCCEEDED" and len(calls) == 1
    assert store.result(spec.spec_id) == value.ledger.get_outcome(calls[0])
    observation = inspect_native_job_dispatch(spec)
    assert observation["status"] == "committed_result"
    assert observation["research_attempt_id"] == calls[0]
    before_slots = value.ledger.list_reservations(prepared.execution.protocol)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    assert run_job(store, spec.spec_id) == result
    with store.coordinator():
        assert store.submit(spec, now_ns=time.time_ns()) == result
    assert value.ledger.list_reservations(prepared.execution.protocol) == before_slots


def test_known_unavailable_runtime_fails_before_consuming_an_original_slot(
    reduction_case,
    native_job_root,
    monkeypatch,
):
    value = reduction_case
    spec, store, _ = queued(value, native_job_root)
    before = value.ledger.list_reservations(
        value.prepared.materialization.source.validation.protocol
    )

    def unavailable():
        raise ReplayDependencyError("engine_unavailable", "Controlled missing optional runtime")

    monkeypatch.setattr(job_reduction, "require_native_runtime", unavailable)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    result = run_job(store, spec.spec_id)
    assert result["state"] == "FAILED" and result["failure"]["worker_exit_code"] is None
    assert result["failure"]["code"] == "engine_unavailable"
    assert inspect_native_job_dispatch(spec)["status"] == "no_reservation_observed"
    assert (
        value.ledger.list_reservations(value.prepared.materialization.source.validation.protocol)
        == before
    )


def test_wrong_result_context_cannot_publish_a_research_manifest(
    reduction_case,
    tmp_path,
    native_job_root,
    monkeypatch,
):
    value = reduction_case
    spec, store, _ = queued(value, native_job_root)
    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    result = run_job(
        store, spec.spec_id, _worker_command=saved_worker(value, tmp_path, wrong_context=True)
    )
    assert result["state"] == "FAILED" and store.result(spec.spec_id) is None
    assert result["failure"]["worker_exit_code"] == 0
    observation = inspect_native_job_dispatch(spec)
    assert observation["status"] == "reserved_unfinalized"
    assert value.ledger.get_outcome(observation["research_attempt_id"]) is None


def test_publication_rejects_a_stale_catalog_version_without_writing_research(
    reduction_case,
    tmp_path,
    native_job_root,
    monkeypatch,
):
    value = reduction_case
    spec, store, _ = queued(value, native_job_root)
    original = job_reduction.publish_reduction_execution

    def race(execution, reservation, audited, *, ledger, fence):
        latest = store.get(spec.spec_id)
        attempt = latest["attempt"]
        store.heartbeat(
            spec.spec_id,
            expected_version=latest["version"],
            coordinator_id=attempt["coordinator_id"],
            job_attempt_id=attempt["job_attempt_id"],
            lease_token=attempt["lease_token"],
            sequence=attempt["heartbeat_sequence"] + 1,
            now_ns=time.time_ns(),
        )
        return original(execution, reservation, audited, ledger=ledger, fence=fence)

    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    monkeypatch.setattr(job_reduction, "publish_reduction_execution", race)
    with pytest.raises(JobConflictError, match="version"):
        run_job(store, spec.spec_id, _worker_command=saved_worker(value, tmp_path))
    assert store.get(spec.spec_id)["state"] == "RUNNING"
    assert inspect_native_job_dispatch(spec)["status"] == "reserved_unfinalized"


def test_monotonic_publication_expiry_is_not_rebased_from_utc(
    reduction_case,
    tmp_path,
    native_job_root,
    monkeypatch,
):
    value = reduction_case
    spec, store, _ = queued(value, native_job_root)
    original = job_reduction.publish_reduction_execution
    mono = time.monotonic_ns

    def late(execution, reservation, audited, *, ledger, fence):
        monkeypatch.setattr(job_supervisor.time, "monotonic_ns", lambda: mono() + 31_000_000_000)
        return original(execution, reservation, audited, ledger=ledger, fence=fence)

    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    monkeypatch.setattr(job_reduction, "publish_reduction_execution", late)
    with pytest.raises(JobConflictError, match="UTC cannot confirm"):
        run_job(store, spec.spec_id, _worker_command=saved_worker(value, tmp_path))
    assert store.get(spec.spec_id)["state"] == "RUNNING"
    assert inspect_native_job_dispatch(spec)["status"] == "reserved_unfinalized"


def test_committed_research_ack_loss_is_not_overwritten_or_automatically_replayed(
    reduction_case,
    tmp_path,
    native_job_root,
    monkeypatch,
):
    value = reduction_case
    spec, store, _ = queued(value, native_job_root)
    publish = LocalAttemptLedger.publish
    commits = []

    def lost_ack(self, reservation, raw, *, artifacts=()):
        publish(self, reservation, raw, artifacts=artifacts)
        commits.append((reservation.attempt_id, raw))
        raise OSError("Controlled ACK loss after actual research publication")

    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    monkeypatch.setattr(LocalAttemptLedger, "publish", lost_ack)
    with pytest.raises(ProtocolRunError, match="could not be confirmed"):
        run_job(store, spec.spec_id, _worker_command=saved_worker(value, tmp_path))
    assert len(commits) == 1 and store.get(spec.spec_id)["state"] == "RUNNING"
    observed = inspect_native_job_dispatch(spec)
    assert observed["status"] == "committed_result"
    assert canonical(observed["recovery"]["final_manifest"]) == commits[0][1]
    assert store.result(spec.spec_id) is None
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    reconciled = run_job(store, spec.spec_id)
    assert reconciled["state"] == "LOST"
    assert len(commits) == 1 and value.ledger.get_outcome(commits[0][0]) == commits[0][1]


def test_native_deadline_is_not_extended_by_renewing_heartbeats(tmp_path):
    request = {
        "preparation": "/owner/prepared",
        "expected_preparation_id": "0" * 64,
        "expected_bundle_id": "1" * 64,
        "expected_report_id": "2" * 64,
        "input_root": "/owner/inputs",
        "source_evidence": "source",
        "runs": "/owner/runs",
        "split": "development",
        "engine_runtime": "coordinator_interpreter_v1",
        "restart_mode": "frozen_origin_new_attempt_only_v1",
    }
    spec = build_execution_job_spec(request, lease_duration_ns=3_000_000_000)
    store = SqliteJobStore(tmp_path / "catalog", create=True)
    process = None
    with store.coordinator() as owner:
        row = store.submit(spec, now_ns=time.time_ns())
        row = store.claim(
            spec.spec_id,
            expected_version=1,
            coordinator_id=owner,
            attempt_nonce="3" * 64,
            lease_token="4" * 64,
            now_ns=time.time_ns(),
        )
        attempt = row["attempt"]
        raw = canonical(
            {
                "job_id": spec.spec_id,
                **{
                    key: attempt[key] for key in ("coordinator_id", "job_attempt_id", "lease_token")
                },
            }
        )
        command = _command(
            tmp_path,
            "for seq in range(1,100):\n    emit('job_heartbeat_v1',seq)\n    time.sleep(0.1)\n",
        )
        deadline = time.monotonic_ns() + 2_000_000_000
        window = job_supervisor._LeaseWindow(time.monotonic_ns() + 3_000_000_000, deadline)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            with pytest.raises(job_supervisor._NativeDeadlineExpired):
                job_supervisor._exchange(process, raw, store, row, window)
            assert window.native_deadline_ns == deadline
            assert store.get(spec.spec_id)["attempt"]["heartbeat_sequence"] >= 2
        finally:
            if process is not None:
                job_supervisor._terminate(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()


def test_catalog_read_cannot_spend_the_remaining_research_write_authorization(
    reduction_case,
    native_job_root,
    monkeypatch,
):
    value = reduction_case
    spec, store, _ = queued(value, native_job_root)
    owner = value.prepared.materialization.source.validation.protocol
    before = value.ledger.list_reservations(owner)
    actual_assert = store.assert_active
    monotonic = time.monotonic_ns
    calls = []

    def delayed(*args, **kwargs):
        snapshot = actual_assert(*args, **kwargs)
        monkeypatch.setattr(
            job_supervisor.time, "monotonic_ns", lambda: monotonic() + 31_000_000_000
        )
        return snapshot

    def reserve(*args, **kwargs):
        calls.append("reserve")
        raise AssertionError("A stale post-read fence cannot enter original reservation")

    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    monkeypatch.setattr(store, "assert_active", delayed)
    monkeypatch.setattr(LocalAttemptLedger, "reserve_with_nonce", reserve)
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    with pytest.raises(JobConflictError, match="UTC cannot confirm"):
        run_job(store, spec.spec_id)
    assert calls == [] and value.ledger.list_reservations(owner) == before


def test_alarm_setup_rechecks_remaining_absolute_time_before_arming(monkeypatch):
    clock = [10]
    armed = []
    monkeypatch.setattr(native_job_worker.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(native_job_worker.signal, "signal", lambda *args: None)

    def late_mask(*args):
        clock[0] = 101

    monkeypatch.setattr(native_job_worker.signal, "pthread_sigmask", late_mask)
    monkeypatch.setattr(native_job_worker.signal, "setitimer", lambda *args: armed.append(args))
    with pytest.raises(EvidenceValidationError, match="during alarm setup"):
        native_job_worker.arm_native_deadline(100)
    assert armed == []


def test_default_os_alarm_terminates_gil_held_c_work_after_coordinator_sigkill(tmp_path):
    # No native research/budget fixture: an actual libc sleep holds the GIL via
    # PyDLL, proving this deadline does not depend on a Python handler/thread.
    child_code = (
        "import ctypes,time; "
        "from tickwitness.infrastructure.native_job_worker import arm_native_deadline; "
        "arm_native_deadline(time.monotonic_ns()+3_000_000_000); print('armed',flush=True); "
        "ctypes.PyDLL(None).sleep(30)"
    )
    coordinator_code = (
        "import json,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-I','-B','-c',{child_code!r}],"
        "stdout=subprocess.PIPE); "
        "assert child.stdout.readline()==b'armed\\n'; "
        "print(json.dumps({'child':child.pid}),flush=True); time.sleep(30)"
    )
    coordinator = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", coordinator_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    child = None
    try:
        import selectors

        with selectors.DefaultSelector() as selector:
            selector.register(coordinator.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=10), "Alarm fixture did not arm"
        child = json.loads(coordinator.stdout.readline())["child"]
        assert _alive(child), "Alarm fixture expired before coordinator fault injection"
        coordinator.kill()
        assert coordinator.wait(timeout=5) == -signal.SIGKILL
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and _alive(child):
            time.sleep(0.1)
        assert not _alive(child)
    finally:
        with suppress(ProcessLookupError):
            os.killpg(coordinator.pid, signal.SIGKILL)
        coordinator.wait(timeout=5)
        coordinator.stdout.close()
        coordinator.stderr.close()
