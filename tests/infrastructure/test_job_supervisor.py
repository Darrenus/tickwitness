"""Real trusted processes exercise IPC, ownership loss and bounded supervision.

Fault programs are explicit transport fixtures. They do not simulate native
research success. The result-forgery/late-publication cases re-audit persisted
offline comparison fixtures; installed native-source qualification is separate.
"""

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pytest
from test_reduction_execution import reduction_case as reduction_case
from test_reduction_execution import run as execute_prefix

from tickwitness.application.jobs import JobConflictError, JobStoreError, job_view
from tickwitness.application.reduction_comparison import compare_reduction_run
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.domain.jobs.contracts import build_job_spec
from tickwitness.infrastructure import job_supervisor
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.job_worker import MAX_JOB_FRAME_BYTES
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore

_WORKER = """
import json, os, signal, sys, time
from pathlib import Path
from threading import Event
request = json.loads(sys.stdin.buffer.readline())
def emit(kind, sequence, **payload):
    frame = {key: request[key] for key in
             ('job_id', 'coordinator_id', 'job_attempt_id', 'lease_token')}
    frame.update(kind=kind, schema_version=1, sequence=sequence, **payload)
    sys.stdout.write(json.dumps(frame, sort_keys=True, separators=(',', ':')) + '\\n')
    sys.stdout.flush()
"""
_COORDINATOR = """
import json, sys
from pathlib import Path
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
row = run_job(SqliteJobStore(Path(sys.argv[1]), create=False), sys.argv[2],
              _worker_command=(sys.executable, '-I', '-B', sys.argv[3], sys.argv[4]))
print(json.dumps(row, sort_keys=True))
"""


def _command(tmp_path, body):
    worker = tmp_path / "trusted-job-worker.py"
    worker.write_text(_WORKER + body, encoding="utf-8")
    return (sys.executable, "-I", "-B", str(worker))


def _queued(tmp_path, *, lease_ns=30_000_000_000, request=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    if request is None:
        request = {
            "run_id": "0" * 64,
            "expected_bundle_id": "1" * 64,
            "expected_report_id": "2" * 64,
            "input_root": str((tmp_path / "input").absolute()),
            "source_evidence": "source",
            "runs": str((tmp_path / "research-runs").absolute()),
            "split": "development",
        }
    spec = build_job_spec(request, lease_duration_ns=lease_ns)
    store = SqliteJobStore(tmp_path / "jobs", create=True)
    with store.coordinator():
        row = store.submit(spec, now_ns=time.time_ns())
    return store, row


def _wait_for(predicate, *, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        Event().wait(0.02)
    raise AssertionError("Controlled worker/coordinator gate did not become ready")


def _kill(pid):
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def _comparison_case(value):
    submitted = execute_prefix(value)
    report_id = digest(value.source.artifacts["finding_report"])
    comparison = compare_reduction_run(
        submitted.run_id,
        source=value.source,
        expected_bundle_id=value.source.bundle_id,
        expected_report_id=report_id,
        split="development",
        ledger_factory=lambda: value.ledger,
    )
    return comparison, {
        "run_id": submitted.run_id,
        "expected_bundle_id": value.source.bundle_id,
        "expected_report_id": report_id,
        "input_root": str(value.case.root.absolute()),
        "source_evidence": "portable-source",
        "runs": str((value.case.root / "runs").absolute()),
        "split": "development",
    }


def test_real_default_worker_reports_missing_evidence_as_failed_job(tmp_path):
    store, queued = _queued(tmp_path)
    row = run_job(store, queued["job_id"])
    assert row["state"] == "FAILED" and row["result_sha256"] is None
    assert row["failure"]["worker_exit_code"] != 0
    assert row["attempt"]["attempt_number"] == 1
    assert row["attempt"]["heartbeat_sequence"] >= 2
    assert store.result(queued["job_id"]) is None


def test_authenticated_failure_frame_requires_matching_actual_exit_and_never_retries(tmp_path):
    store, queued = _queued(tmp_path)
    command = _command(
        tmp_path,
        "emit('job_heartbeat_v1', 1)\n"
        "emit('job_failure_v1', 2, failure={'code':'controlled_failure', "
        "'message':'declared transport fixture', 'worker_exit_code':7})\n"
        "raise SystemExit(7)\n",
    )
    row = run_job(store, queued["job_id"], _worker_command=command)
    assert row["state"] == "FAILED"
    assert row["failure"] == {
        "code": "controlled_failure",
        "message": "declared transport fixture",
        "worker_exit_code": 7,
    }
    assert row["attempt"]["heartbeat_sequence"] == 2
    before = canonical(row)
    assert canonical(run_job(store, queued["job_id"], _worker_command=("/missing",))) == before
    assert store.result(queued["job_id"]) is None


@pytest.mark.parametrize(
    "body",
    [
        "sys.stdout.write('not-json\\n'); sys.stdout.flush()\n",
        "sys.stdout.write('{}\\n'); sys.stdout.flush()\n",
        "emit('job_heartbeat_v1', 2)\n",
        "emit([], 1)\n",
        "emit({}, 1)\n",
        "emit('job_heartbeat_v1', 1); emit('job_heartbeat_v1', 1)\n",
        "request['job_id']='f'*64; emit('job_heartbeat_v1', 1)\n",
        "request['job_attempt_id']='f'*64; emit('job_heartbeat_v1', 1)\n",
        "request['coordinator_id']='f'*64; emit('job_heartbeat_v1', 1)\n",
        "request['lease_token']='f'*64; emit('job_heartbeat_v1', 1)\n",
        "emit('job_failure_v1', 1, failure={'code':'x','message':'x','worker_exit_code':7})\n",
        "emit('job_result_v1', 1, export={})\n",
        "emit('job_failure_v1',1,failure={'code':'x','message':'x','worker_exit_code':7}); "
        "emit('job_failure_v1',2,failure={'code':'x','message':'x','worker_exit_code':7})\n",
    ],
)
def test_real_malformed_or_unauthenticated_transport_never_publishes_success(tmp_path, body):
    store, queued = _queued(tmp_path)
    row = run_job(store, queued["job_id"], _worker_command=_command(tmp_path, body))
    assert row["state"] == "FAILED"
    assert row["result_sha256"] is None and store.result(queued["job_id"]) is None
    assert len(row["failure"]["message"]) <= 2048
    assert row["attempt"]["attempt_number"] == 1


@pytest.mark.parametrize(
    "body",
    ["os.write(2, b'x' * 65537)\n", f"os.write(1, b'x' * {MAX_JOB_FRAME_BYTES + 1})\n"],
)
def test_real_worker_output_is_bounded_without_fake_success(tmp_path, body):
    store, queued = _queued(tmp_path)
    row = run_job(store, queued["job_id"], _worker_command=_command(tmp_path, body))
    assert row["state"] == "FAILED" and row["result_sha256"] is None
    assert len(row["failure"]["message"]) <= 2048


def test_silent_worker_lease_expires_and_child_is_reaped(tmp_path):
    store, queued = _queued(tmp_path, lease_ns=2_000_000_000)
    gate = tmp_path / "silent-pid.json"
    command = _command(
        tmp_path,
        f"Path({str(gate)!r}).write_text(json.dumps({{'pid':os.getpid()}}))\nEvent().wait(30)\n",
    )
    row = run_job(store, queued["job_id"], _worker_command=command)
    assert row["state"] == "LOST" and row["failure"]["code"] == "lease_expired"
    assert row["result_sha256"] is None and row["attempt"]["heartbeat_sequence"] == 0
    pid = json.loads(gate.read_text())["pid"]
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_real_heartbeats_extend_lease_and_have_strict_persisted_sequence(tmp_path):
    store, queued = _queued(tmp_path, lease_ns=2_000_000_000)
    command = _command(
        tmp_path,
        "for sequence in range(1,9):\n"
        "    emit('job_heartbeat_v1', sequence)\n"
        "    Event().wait(0.35)\n"
        "emit('job_failure_v1',9,failure={'code':'controlled_failure', "
        "'message':'pulse train completed','worker_exit_code':7})\n"
        "raise SystemExit(7)\n",
    )
    started = time.monotonic()
    row = run_job(store, queued["job_id"], _worker_command=command)
    assert time.monotonic() - started >= 2
    assert row["state"] == "FAILED" and row["failure"]["code"] == "controlled_failure"
    assert row["attempt"]["heartbeat_sequence"] == 9
    assert row["version"] == 12  # queued, claim, nine accepted frames, failure
    assert store.result(queued["job_id"]) is None


@pytest.mark.parametrize("target", ["worker", "coordinator"])
def test_actual_sigkill_after_persisted_heartbeat_has_honest_liveness_and_reconcile(
    tmp_path, target
):
    store, queued = _queued(tmp_path)
    gate = tmp_path / "worker-gate.json"
    command = _command(
        tmp_path,
        "emit('job_heartbeat_v1',1)\n"
        "Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'job_id':request['job_id']}))\n"
        "Event().wait(30)\n",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _COORDINATOR,
            str(tmp_path / "jobs"),
            queued["job_id"],
            command[-1],
            str(gate),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    worker_pid = None
    try:

        def ready():
            if not gate.is_file():
                return None
            try:
                current = store.get(queued["job_id"])
            except JobConflictError:
                return None  # A busy read has not observed the heartbeat yet.
            if current["state"] != "RUNNING" or current["attempt"]["heartbeat_sequence"] < 1:
                return None
            return current

        before = _wait_for(ready)
        gate_data = json.loads(gate.read_text())
        assert gate_data["job_id"] == queued["job_id"]
        worker_pid = gate_data["pid"]
        if target == "worker":
            os.kill(worker_pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0 and not stderr
            row = json.loads(stdout)
            assert row["state"] == "FAILED"
            assert row["failure"]["code"] == "job_worker_failed"
            assert row["failure"]["worker_exit_code"] == -signal.SIGKILL
            with pytest.raises(ProcessLookupError):
                os.kill(worker_pid, 0)
        else:
            os.kill(process.pid, signal.SIGKILL)
            process.communicate(timeout=15)
            assert process.returncode == -signal.SIGKILL
            row = store.get(queued["job_id"])
            assert row["state"] == "RUNNING" and canonical(row) == canonical(before)
            assert store.coordinator_active() is False
            view = job_view(row, now_ns=time.time_ns(), coordinator_active=False)
            assert view["stored_state"] == "RUNNING" and view["state"] == "COORDINATOR_LOST"
            assert canonical(store.get(queued["job_id"])) == canonical(before)
            with store.coordinator():
                changed = store.reconcile_orphans(now_ns=time.time_ns())
                assert len(changed) == 1 and changed[0]["state"] == "LOST"
                lost = changed[0]
                assert lost["failure"]["code"] == "coordinator_lost"
                credentials = before["attempt"]
                with pytest.raises(JobConflictError):
                    store.heartbeat(
                        queued["job_id"],
                        expected_version=lost["version"],
                        coordinator_id=credentials["coordinator_id"],
                        job_attempt_id=credentials["job_attempt_id"],
                        lease_token=credentials["lease_token"],
                        sequence=credentials["heartbeat_sequence"] + 1,
                        now_ns=time.time_ns(),
                    )
            assert store.result(queued["job_id"]) is None
    finally:
        if worker_pid is not None:
            _kill(worker_pid)
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=15)


def test_worker_has_no_catalog_locator_or_inherited_coordinator_lock(tmp_path):
    store, queued = _queued(tmp_path)
    captured = tmp_path / "captured-request.json"
    lock_stat = (tmp_path / "jobs" / "coordinator.lock").stat()
    body = (
        "descriptors=[]\n"
        "for name in os.listdir('/dev/fd'):\n"
        "    try:\n"
        "        stat=os.fstat(int(name)); descriptors.append([stat.st_dev,stat.st_ino])\n"
        "    except OSError:\n"
        "        pass\n"
        f"Path({str(captured)!r}).write_text(json.dumps({{'request':request,'fds':descriptors}}))\n"
        "emit('job_failure_v1',1,failure={'code':'controlled_failure','message':'captured',"
        "'worker_exit_code':7})\nraise SystemExit(7)\n"
    )
    row = run_job(store, queued["job_id"], _worker_command=_command(tmp_path, body))
    assert row["state"] == "FAILED"
    evidence = json.loads(captured.read_text())
    assert evidence["request"].keys() == {
        "kind",
        "schema_version",
        "spec",
        "job_id",
        "coordinator_id",
        "job_attempt_id",
        "lease_token",
    }
    assert str(tmp_path / "jobs") not in json.dumps(evidence["request"])
    assert [lock_stat.st_dev, lock_stat.st_ino] not in evidence["fds"]


def test_pinned_self_rehashed_worker_export_is_independently_rejected(tmp_path, reduction_case):
    comparison, request = _comparison_case(reduction_case)
    forged = deepcopy(json.loads(comparison.export_bytes))
    assessment = forged["report"]["reduced_assessment"]
    assessment["outcome"] = "NOT_PRESERVED"
    assessment["criterion_observation"].update(value="1", truth=True)
    forged["report"]["both_false_witnesses"] = False
    forged["report"]["bindings"]["reduced"]["assessment_id"] = digest(canonical(assessment))
    forged["comparison_id"] = digest(canonical(forged["report"]))
    catalog_root = tmp_path.parent / (tmp_path.name + "-forged-job")
    store, queued = _queued(catalog_root, request=request)
    command = _command(
        tmp_path, f"emit('job_result_v1',1,export=json.loads({json.dumps(forged)!r}))\n"
    )
    row = run_job(store, queued["job_id"], _worker_command=command)
    assert row["state"] == "FAILED" and row["result_sha256"] is None
    assert "Coordinator re-audit rejected result" in row["failure"]["message"]
    assert row["failure"]["worker_exit_code"] == 0
    assert store.result(queued["job_id"]) is None


def test_post_commit_acknowledgement_failure_preserves_success_instead_of_overwrite(
    tmp_path, reduction_case, monkeypatch
):
    comparison, request = _comparison_case(reduction_case)
    catalog_root = tmp_path.parent / (tmp_path.name + "-late-job")
    store, queued = _queued(catalog_root, request=request)
    actual_complete = store.complete

    def late(*args, **kwargs):
        actual_complete(*args, **kwargs)
        raise JobStoreError("Controlled lost acknowledgement after actual commit")

    monkeypatch.setattr(store, "complete", late)
    command = _command(
        tmp_path,
        f"emit('job_result_v1',1,export=json.loads({comparison.export_bytes.decode()!r}))\n",
    )
    with pytest.raises(JobStoreError, match="lost acknowledgement"):
        run_job(store, queued["job_id"], _worker_command=command)
    committed = store.get(queued["job_id"])
    assert committed["state"] == "SUCCEEDED" and committed["failure"] is None
    assert store.result(queued["job_id"]) == comparison.export_bytes
    assert canonical(run_job(store, queued["job_id"], _worker_command=("/missing",))) == (
        canonical(committed)
    )


@pytest.mark.parametrize("verification_fails", [False, True])
def test_original_monotonic_lease_fences_both_reaudit_outcomes_despite_utc_window(
    tmp_path, reduction_case, monkeypatch, verification_fails
):
    comparison, request = _comparison_case(reduction_case)
    catalog_root = tmp_path.parent / (tmp_path.name + "-clock-job")
    store, queued = _queued(catalog_root, request=request)
    command = _command(
        tmp_path,
        f"emit('job_result_v1',1,export=json.loads({comparison.export_bytes.decode()!r}))\n",
    )
    original_verify = job_supervisor.execute_comparison
    monotonic_ns = time.monotonic_ns
    utc_ns = time.time_ns
    offset = [0]
    clock = SimpleNamespace(monotonic_ns=lambda: monotonic_ns() + offset[0], time_ns=utc_ns)

    def verify(spec, *, saved=None):
        result = original_verify(spec, saved=saved)
        current = store.get(queued["job_id"])
        assert current["updated_at_ns"] <= utc_ns() < current["attempt"]["lease_expires_at_ns"]
        # A controlled clock discrepancy, without a racy real-time sleep. It
        # represents elapsed monotonic time not reflected in the UTC window.
        offset[0] = 61_000_000_000
        if verification_fails:
            raise EvidenceValidationError("Controlled verification failure after lease elapsed")
        return result

    monkeypatch.setattr(job_supervisor, "time", clock)
    monkeypatch.setattr(job_supervisor, "execute_comparison", verify)
    with pytest.raises(JobConflictError, match="UTC cannot confirm"):
        run_job(store, queued["job_id"], _worker_command=command)
    current = store.get(queued["job_id"])
    assert current["state"] == "RUNNING" and current["result_sha256"] is None
    assert (
        job_view(current, now_ns=utc_ns(), coordinator_active=False)["state"] == "COORDINATOR_LOST"
    )
    with store.coordinator():
        changed = store.reconcile_orphans(now_ns=utc_ns())
    assert len(changed) == 1 and changed[0]["state"] == "LOST"
