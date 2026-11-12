#!/usr/bin/env python3
"""Qualify opt-in Job controls using installed code and real owned processes.

The eight-slot native lifecycle is frozen before its baseline. Historical
five/eight/eleven-slot evidence is neither enlarged nor imported. Core-only
transport probes are labelled fixtures, never native research execution.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from smoke_job_followups import _GUARD_PREFIX, _GUARD_SUFFIX
from smoke_native_jobs import _RUNTIME, _bootstrap
from smoke_reduction_execution import _GUARD, _LEDGER_VIEW, _canonical, _request, _sha, _tree

_CONTROL_VIEW = """
from tickwitness.application.jobs import JobConflictError
from tickwitness.infrastructure.job_controls import JobControlStore
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
def observe():
    store=SqliteJobStore(catalog,create=False)
    rows=[]
    for job_id in json.loads(sys.argv[1]):
        control=JobControlStore(catalog,job_id)
        policy=control.policy()
        result=store.result(job_id)
        rows.append({'snapshot':store.get(job_id),'events':store.events(job_id,limit=1000),
            'result':None if result is None else json.loads(result),
            'control':{'policy':None if policy is None else policy.document,
                'policy_id':None if policy is None else policy.policy_id,
                'cancel':control.cancel_request(),
                'publication':control.publication_admission(),'result':control.result()}})
    return {'jobs':rows,'coordinator_active':store.coordinator_active()}
try:print(json.dumps(observe(),sort_keys=True,separators=(',',':')))
except JobConflictError as error:
    print(json.dumps({'error':{'code':error.code,'message':str(error)}}),file=sys.stderr)
    raise SystemExit(9)
"""
_CATALOG_ONLY = """
from tickwitness.application.jobs import JobConflictError
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
try:
    store=SqliteJobStore(catalog,create=False)
    job_id=sys.argv[1]
    raw=store.result(job_id)
    value={'snapshot':store.get(job_id),'events':store.events(job_id,limit=1000),
           'result':None if raw is None else json.loads(raw)}
    print(json.dumps(value,sort_keys=True,separators=(',',':')))
except JobConflictError as error:
    print(json.dumps({'error':{'code':error.code,'message':str(error)}}),file=sys.stderr)
    raise SystemExit(9)
"""
_NATIVE_WORKER = """
import hashlib,io,json,os,resource,signal,sys
from pathlib import Path
from threading import Event
from tickwitness.infrastructure import native_job_worker
from tickwitness.infrastructure.nautilus_replay import NautilusReplayAdapter
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
mode,root=sys.argv[1],Path(sys.argv[2])
root.mkdir(parents=True,exist_ok=True)
raw=sys.stdin.buffer.readline(16*1024*1024+2)
assert raw.endswith(b'\\n') and len(raw)<=16*1024*1024+1
request=json.loads(raw)
(root/'request.jsonl').write_bytes(raw)
process_identity={'kind':'actual_controlled_compute_identity_v1','pid':os.getpid(),
                  'parent_pid':os.getppid(),'process_group':os.getpgrp(),
                  'session_id':os.getsid(0),'job_id':request['job_id'],
                  'request_sha256':hashlib.sha256(raw).hexdigest()}
(root/'process-identity.json').write_text(
    json.dumps(process_identity,sort_keys=True,separators=(',',':')))
assert request['kind']=='job_native_worker_request_v1'
assert request['payload']['research_attempt']['attempt_index'] in (4,5,6,7,8)
def document(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def record(value):
    with (root/'native-calls.jsonl').open('ab') as stream:stream.write(document(value)+b'\\n')
def forbidden(*args,**kwargs):
    raise AssertionError('Controlled native worker cannot open research or Catalog')
LocalAttemptLedger.__init__=forbidden
SqliteJobStore.__init__=forbidden
actual=NautilusReplayAdapter.run
def counted(self,replay_input):
    record({'kind':'actual_native_adapter_invoked_v1','pid':os.getpid(),
            'parent_pid':os.getppid(),'process_group':os.getpgrp(),'session_id':os.getsid(0),
            'dataset_id':replay_input.dataset_id,'job_id':request['job_id']})
    result=actual(self,replay_input)
    (root/'actual-native-result.json').write_bytes(document(result.document))
    limits={'cpu':list(resource.getrlimit(resource.RLIMIT_CPU)),
            'file':list(resource.getrlimit(resource.RLIMIT_FSIZE)),
            'files':list(resource.getrlimit(resource.RLIMIT_NOFILE))}
    workspace_info=os.stat('.')
    ready={'kind':'actual_native_completed_while_heartbeat_emitter_live_v1',
           'pid':os.getpid(),'parent_pid':os.getppid(),'process_group':os.getpgrp(),
           'session_id':os.getsid(0),'job_id':request['job_id'],
           'workspace':str(Path.cwd()),'limits':limits,'mode':mode,
           'workspace_at_ready':{'exists':Path.cwd().exists(),
               'is_symlink':Path.cwd().is_symlink(),
               'device':workspace_info.st_dev,'inode':workspace_info.st_ino}}
    (root/'ready.pending').write_bytes(document(ready))
    os.replace(root/'ready.pending',root/'ready.json')
    if mode in ('cancel','deadline'):
        Event().wait(55)
        raise AssertionError('Controlled stop failed to stop the real worker')
    if mode=='resource':
        signal.signal(signal.SIGXFSZ,signal.SIG_DFL)
        cap=resource.getrlimit(resource.RLIMIT_FSIZE)[0]
        assert cap==65536
        descriptor=os.open('actual-fsize-limit.bin',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.write(descriptor,b'x'*cap)
        os.fsync(descriptor)
        (root/'resource-probe.json').write_bytes(document({
            'kind':'actual_single_file_limit_probe_v1','limit':cap,
            'bytes_before_violation':os.fstat(descriptor).st_size,
            'native_completed':True,'pid':os.getpid(),'parent_pid':os.getppid(),
            'process_group':os.getpgrp(),'session_id':os.getsid(0)}))
        os.write(descriptor,b'x')
        raise AssertionError('OS single-file limit did not stop the worker')
    return result
NautilusReplayAdapter.run=counted
actual_stdout=sys.stdout
class Buffer:
    def __getattr__(self,name):return getattr(actual_stdout.buffer,name)
    def write(self,data):
        with (root/'delivered-ipc.jsonl').open('ab') as stream:stream.write(data)
        return actual_stdout.buffer.write(data)
    def flush(self):return actual_stdout.buffer.flush()
class Output:
    buffer=Buffer()
    def __getattr__(self,name):return getattr(actual_stdout,name)
    def write(self,value):return self.buffer.write(value.encode())
    def flush(self):return self.buffer.flush()
sys.stdin=io.TextIOWrapper(io.BytesIO(raw),encoding='utf-8')
sys.stdout=Output()
raise SystemExit(native_job_worker.main())
"""
_CORE_WORKER = """
import hashlib,json,os,resource,signal,sys
from pathlib import Path
from threading import Event,Thread
from tickwitness.infrastructure.job_worker import _Emitter
mode,root=sys.argv[1],Path(sys.argv[2])
root.mkdir(parents=True,exist_ok=True)
raw=sys.stdin.buffer.readline(65538)
request=json.loads(raw)
(root/'request.jsonl').write_bytes(raw)
process_identity={'kind':'actual_controlled_compute_identity_v1','pid':os.getpid(),
                  'parent_pid':os.getppid(),'process_group':os.getpgrp(),
                  'session_id':os.getsid(0),'job_id':request['job_id'],
                  'request_sha256':hashlib.sha256(raw).hexdigest()}
(root/'process-identity.json').write_text(
    json.dumps(process_identity,sort_keys=True,separators=(',',':')))
bindings={key:request[key] for key in
          ('job_id','coordinator_id','job_attempt_id','lease_token')}
emitter=_Emitter(bindings)
emitter.emit('job_heartbeat_v1')
thread=Thread(target=emitter.pulse,args=(0.2,),daemon=True)
thread.start()
(Path.cwd()/'owned-scratch.txt').write_text('Owned transport fixture, not research evidence')
ready={'kind':'core_transport_fixture_ready_v1','pid':os.getpid(),
       'parent_pid':os.getppid(),'process_group':os.getpgrp(),'session_id':os.getsid(0),
       'workspace':str(Path.cwd()),'job_id':request['job_id'],'mode':mode,
       'limits':{'cpu':list(resource.getrlimit(resource.RLIMIT_CPU)),
                 'file':list(resource.getrlimit(resource.RLIMIT_FSIZE)),
                 'files':list(resource.getrlimit(resource.RLIMIT_NOFILE))}}
(root/'ready.pending').write_text(json.dumps(ready,sort_keys=True,separators=(',',':')))
os.replace(root/'ready.pending',root/'ready.json')
if mode=='resource':
    signal.signal(signal.SIGXFSZ,signal.SIG_DFL)
    cap=resource.getrlimit(resource.RLIMIT_FSIZE)[0]
    assert cap==65536
    descriptor=os.open('actual-fsize-limit.bin',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    os.write(descriptor,b'x'*cap)
    os.fsync(descriptor)
    (root/'resource-probe.json').write_text(json.dumps({'limit':cap,
        'bytes_before_violation':os.fstat(descriptor).st_size,'fixture':True}))
    os.write(descriptor,b'x')
    raise AssertionError('OS single-file limit did not stop transport fixture')
if mode=='orphan':
    if not emitter.broken.wait(15):raise AssertionError('Owner death did not close heartbeat pipe')
    (root/'broken-channel.json').write_text(json.dumps({'observed':True,'pid':os.getpid(),
        'parent_pid':os.getppid(),'process_group':os.getpgrp(),'session_id':os.getsid(0)}))
    Event().wait(1)
    os._exit(3)
Event().wait(55)
raise AssertionError('Transport control did not stop its fixture')
"""
_COORDINATOR = """
import json,os,sys,time
from pathlib import Path
from threading import Event
from tickwitness import cli_jobs
from tickwitness.cli import main
from tickwitness.infrastructure import job_reduction,job_supervisor
from tickwitness.infrastructure.job_control_runtime import current_control
mode,root,worker=sys.argv.pop(1),Path(sys.argv.pop(1)),sys.argv.pop(1)
root.mkdir(parents=True,exist_ok=True)
job_id=sys.argv[2]
def record(value):
    with (root/'coordinator-controls.jsonl').open('a') as stream:
        stream.write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n')
def gate(kind,extra):
    ready={'kind':kind,'pid':os.getpid(),'parent_pid':os.getppid(),
           'process_group':os.getpgrp(),'session_id':os.getsid(0),'job_id':job_id,**extra}
    record(ready)
    (root/'publication.pending').write_text(json.dumps(ready,sort_keys=True,separators=(',',':')))
    os.replace(root/'publication.pending',root/'publication.json')
    deadline=time.monotonic()+25
    while not (root/'release-publication').exists() and time.monotonic()<deadline:
        Event().wait(0.02)
    if not (root/'release-publication').exists():raise AssertionError('Publication gate timed out')
original_before=job_supervisor._before_control_publication
def before(row):
    original_before(row)
    if mode=='cancel_publication':
        gate('real_native_audited_before_control_publication_v1',{'snapshot':row})
job_supervisor._before_control_publication=before
original_publication=job_reduction.publish_reduction_execution
def publication(execution,reservation,audited,*,ledger,fence):
    if mode=='publication_wins':
        owned=current_control()
        assert owned is not None
        marker=owned.control.publication_admission()
        assert marker is not None
        gate('control_admission_won_before_real_research_publish_v1',{
             'research_attempt_id':reservation.attempt_id,'publication_admission':marker})
    return original_publication(execution,reservation,audited,ledger=ledger,fence=fence)
job_reduction.publish_reduction_execution=publication
original_run=cli_jobs.run_job
def managed(store,selected):
    worker_mode=mode if mode in ('cancel','deadline','resource','orphan') else 'normal'
    return original_run(store,selected,_worker_command=(sys.executable,'-I','-B',worker,
                                                      worker_mode,str(root)))
cli_jobs.run_job=managed
raise SystemExit(main(sys.argv[1:]))
"""
_WORKSPACE_PROBE = """
import fcntl,os
root=Path(sys.argv[1])
assert root.name=='scratch' and root.parent.parent.parent.parent.name=='.job-controls'
lock=root.parent/'lifetime.lock'
descriptor=os.open(lock,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
busy=False
try:
    try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:busy=True
finally:os.close(descriptor)
print(json.dumps({'lifetime_busy':busy,'scratch_exists':root.is_dir(),
                  'scratch_files':sorted(item.name for item in root.iterdir())}))
"""


@contextmanager
def _workspace(records, report, resource_report=None):
    with TemporaryDirectory(prefix="tickwitness-job-controls-") as temporary:
        root = Path(temporary)
        try:
            yield root
        except BaseException as error:
            with suppress(OSError):
                report.unlink(missing_ok=True)
            if resource_report is not None:
                with suppress(OSError):
                    resource_report.unlink(missing_ok=True)
            if not records.exists():
                shutil.copytree(root, records)
                (records / "diagnostic-capture.json").write_bytes(
                    _canonical(
                        {
                            "kind": "job_control_diagnostics_v1",
                            "accepted": False,
                            "exception_type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                )
            raise


def _capture(calls, transcripts, executable, entry, command, completed, expected):
    record = {
        "executable": executable,
        "entry": list(entry),
        "command": list(command),
        "expected_exit_code": expected,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    calls.append(record)
    (transcripts / f"{len(calls):04d}.json").write_bytes(_canonical(record))
    if completed.returncode != expected:
        raise RuntimeError("Unexpected control command exit: " + repr(record))
    if expected < 0:
        assert not completed.stdout and not completed.stderr
        return {"signal_exit_code": completed.returncode}
    output = completed.stdout if expected == 0 else completed.stderr
    assert not (completed.stderr if expected == 0 else completed.stdout)
    return json.loads(output)


def _wait_gate(process, path, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_bytes())
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError("Coordinator exited before gate: " + repr((stdout, stderr)))
        Event().wait(0.02)
    raise AssertionError("Controlled Job gate timed out: " + str(path))


def _cleanup(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _workspace_observation(directory, catalog):
    ready = json.loads((directory / "ready.json").read_bytes())
    request = json.loads((directory / "request.jsonl").read_bytes())
    scratch = Path(ready["workspace"])
    expected = (
        catalog
        / ".job-controls"
        / request["job_id"]
        / "workspaces"
        / request["job_attempt_id"]
        / "scratch"
    )
    bound = scratch.resolve() == expected.resolve()
    seal = None
    seal_sha256 = None
    if bound:
        raw = (scratch.parent / "workspace.json").read_bytes()
        assert len(raw) <= 4096
        seal = json.loads(raw)
        seal_sha256 = _sha(raw)
    observation = {
        "kind": "actual_owned_workspace_observation_v1",
        "job_id": request["job_id"],
        "path": str(scratch),
        "namespace_bound": bound,
        "exists": scratch.exists(),
        "is_symlink": scratch.is_symlink(),
        "seal": seal,
        "seal_sha256": seal_sha256,
    }
    (directory / "workspace-after.json").write_bytes(_canonical(observation))
    return observation


_RESOURCE_METRICS = {
    "coordinator_cpu_ns": ("ns", "coordinator_process", "process_time_ns_delta"),
    "compute_user_cpu_ns": ("ns", "terminated_compute_child_os_accounting", "anchor_wait4"),
    "compute_system_cpu_ns": ("ns", "terminated_compute_child_os_accounting", "anchor_wait4"),
    "compute_peak_rss_bytes": (
        "bytes",
        "terminated_compute_child_os_accounting",
        "anchor_wait4",
    ),
    "scratch_cleanup_logical_bytes": (
        "bytes",
        "owned_scratch_cleanup_regular_entries",
        "nofollow_cleanup_stat",
    ),
    "job_elapsed_ns": ("ns", "live_control_window", "monotonic_ns_delta"),
    "research_slots_reserved_count": (
        "count",
        "this_job_confirmed_new_reservations",
        "coordinator_reservation_confirmation",
    ),
    "audited_native_results_count": (
        "count",
        "this_job_new_native_results_audited",
        "coordinator_native_result_audit",
    ),
    "processed_input_record_count": (
        "count",
        "this_job_audited_native_result",
        "coordinator_native_result_audit",
    ),
    "predicate_evaluation_count": ("count", "frozen_research_predicate", "not_instrumented"),
}


def _resource_document(report, observed, *, worker_identity=None, positive=False, resource=False):
    """Bind operational observations to the actual existing execution, not guesses."""
    assert set(report) == {
        "kind",
        "schema_version",
        "job_id",
        "job_attempt_id",
        "policy_id",
        "catalog_state",
        "catalog_snapshot_sha256",
        "worker_started",
        "worker_usage",
        "collection_status",
        "metrics",
        "stages",
    }
    snapshot, control = observed["snapshot"], observed["control"]
    assert report["kind"] == "job_resource_report_v1" and report["schema_version"] == 1
    assert report["job_id"] == snapshot["job_id"]
    assert report["job_attempt_id"] == snapshot["attempt"]["job_attempt_id"]
    assert report["policy_id"] == control["policy_id"]
    assert report["catalog_state"] == snapshot["state"]
    assert report["catalog_snapshot_sha256"] == _sha(_canonical(snapshot))
    assert report["worker_started"] == control["result"]["worker_started"]
    assert report["collection_status"] in {"complete", "partial"}
    assert set(report["metrics"]) == set(_RESOURCE_METRICS)
    for name, metric in report["metrics"].items():
        assert set(metric) == {"availability", "value", "unit", "scope", "source", "reason"}
        assert (metric["unit"], metric["scope"], metric["source"]) == _RESOURCE_METRICS[name]
        if metric["availability"] == "measured":
            assert type(metric["value"]) is int and 0 <= metric["value"] < 2**63
            assert metric["reason"] is None
        else:
            assert metric["availability"] == "unavailable" and metric["value"] is None
            assert metric["reason"] in {
                "not_recorded",
                "worker_not_started",
                "usage_unavailable",
                "unsupported_platform",
                "cleanup_incomplete",
                "reservation_unconfirmed",
                "result_not_audited",
                "not_instrumented",
                "phase_not_observed",
                "clock_unavailable",
            }
    metrics = report["metrics"]
    assert metrics["predicate_evaluation_count"]["availability"] == "unavailable"
    assert metrics["predicate_evaluation_count"]["reason"] == "not_instrumented"
    assert metrics["job_elapsed_ns"]["availability"] == "measured"
    assert metrics["coordinator_cpu_ns"]["availability"] == "measured"
    assert [stage["name"] for stage in report["stages"]] == [
        "pre_worker_admission",
        "owned_worker_lifetime",
        "cleanup",
        "post_cleanup",
    ]
    for stage in report["stages"]:
        assert set(stage) == {
            "name",
            "availability",
            "start_offset_ns",
            "end_offset_ns",
            "duration_ns",
            "reason",
        }
        if stage["availability"] == "measured":
            start, end, duration = (
                stage["start_offset_ns"],
                stage["end_offset_ns"],
                stage["duration_ns"],
            )
            assert all(type(value) is int for value in (start, end, duration))
            assert 0 <= start <= end <= metrics["job_elapsed_ns"]["value"]
            assert duration == end - start and stage["reason"] is None
        else:
            assert stage["availability"] == "unavailable"
            assert stage["reason"] == "phase_not_observed"
            assert all(
                stage[name] is None for name in ("start_offset_ns", "end_offset_ns", "duration_ns")
            )
    usage = report["worker_usage"]
    worker_metrics = ("compute_user_cpu_ns", "compute_system_cpu_ns", "compute_peak_rss_bytes")
    if not report["worker_started"]:
        assert usage is None
        for name in worker_metrics:
            assert metrics[name]["availability"] == "unavailable"
            assert metrics[name]["reason"] == "worker_not_started"
        assert metrics["scratch_cleanup_logical_bytes"]["value"] == 0
    elif usage is not None:
        assert worker_identity is not None
        assert set(usage) == {
            "kind",
            "schema_version",
            "anchor_pid",
            "compute_pid",
            "platform",
            "user_cpu_us",
            "system_cpu_us",
            "maxrss_raw",
            "maxrss_unit",
            "compute_wait_status",
        }
        assert usage["kind"] == "job_compute_usage_v1" and usage["schema_version"] == 1
        assert usage["anchor_pid"] == worker_identity["parent_pid"]
        assert usage["compute_pid"] == worker_identity["pid"]
        assert usage["anchor_pid"] != usage["compute_pid"]
        platform = "darwin" if sys.platform == "darwin" else "linux"
        assert usage["platform"] == platform
        assert usage["maxrss_unit"] == ("bytes" if platform == "darwin" else "KiB")
        assert type(usage["compute_wait_status"]) is int
        assert -255 <= usage["compute_wait_status"] <= 255
        for name in ("user_cpu_us", "system_cpu_us", "maxrss_raw"):
            assert type(usage[name]) is int and 0 <= usage[name] < 2**63
        assert metrics["compute_user_cpu_ns"]["value"] == usage["user_cpu_us"] * 1000
        assert metrics["compute_system_cpu_ns"]["value"] == usage["system_cpu_us"] * 1000
        multiplier = 1 if platform == "darwin" else 1024
        assert metrics["compute_peak_rss_bytes"]["value"] == usage["maxrss_raw"] * multiplier
        assert all(metrics[name]["availability"] == "measured" for name in worker_metrics)
        # The anchor's deadline and the compute child's wait status may differ.
    else:
        assert report["collection_status"] == "partial"
        assert all(metrics[name]["availability"] == "unavailable" for name in worker_metrics)
    if positive:
        assert usage is not None
        assert usage["user_cpu_us"] + usage["system_cpu_us"] > 0
        assert metrics["compute_peak_rss_bytes"]["value"] > 0
    if resource and control["result"]["cleanup_confirmed"]:
        assert metrics["scratch_cleanup_logical_bytes"]["availability"] == "measured"
        assert metrics["scratch_cleanup_logical_bytes"]["value"] >= 65536


def _resource_preview(preview, observed):
    assert set(preview) == {
        "kind",
        "schema_version",
        "job_id",
        "operation",
        "policy_id",
        "configured_limits",
        "estimates",
        "research_slot_requirement",
        "execution_authorized",
    }
    snapshot, control = observed["snapshot"], observed["control"]
    assert preview["kind"] == "job_resource_preview_v1" and preview["schema_version"] == 1
    assert preview["job_id"] == snapshot["job_id"]
    assert preview["operation"] == snapshot["spec"]["operation"]
    assert preview["policy_id"] == control["policy_id"]
    expected_limits = None if control["policy"] is None else control["policy"]["limits"]
    assert preview["configured_limits"] == expected_limits
    assert preview["execution_authorized"] is False
    assert set(preview["estimates"]) == {"cpu_ns", "peak_rss_bytes", "elapsed_ns", "disk_bytes"}
    assert all(
        estimate == {"availability": "unavailable", "value": None, "reason": "not_calibrated"}
        for estimate in preview["estimates"].values()
    )
    read_only = snapshot["spec"]["operation"] == "compare_reduction_run_v1" or (
        snapshot["spec"]["operation"] == "resolve_reduction_job_v1"
        and snapshot["spec"]["request"]["mode"] == "acknowledge_committed_v1"
    )
    assert preview["research_slot_requirement"] == (
        {"availability": "measured", "value": 0, "reason": "structurally_read_only"}
        if read_only
        else {"availability": "unavailable", "value": None, "reason": "conditional_execution"}
    )
    assert "lease_token" not in _canonical(preview).decode()


def main():
    parser = argparse.ArgumentParser()
    for name in ("python", "verifier-python", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--resource-report", type=Path)
    args = parser.parse_args()
    if (
        args.report.exists()
        or args.records_dir.exists()
        or (args.resource_report is not None and args.resource_report.exists())
    ):
        raise FileExistsError("Control qualification destinations must be new")
    if args.resource_report is not None and (
        args.resource_report.absolute() == args.report.absolute()
        or args.resource_report.absolute().is_relative_to(args.records_dir.absolute())
    ):
        raise ValueError("Resource qualification report needs a separate destination")
    producer_python = str(args.python.absolute())
    verifier = str(args.verifier_python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    golden_before = _tree(examples / "alpha")
    with _workspace(args.records_dir, args.report, args.resource_report) as root:
        inputs, preparations, catalog, controls, transcripts, cwd = (
            root / name
            for name in ("input-root", "preparations", "jobs", "controls", "transcripts", "cwd")
        )
        for directory in (inputs, preparations, controls, transcripts, cwd):
            directory.mkdir()
        native_worker = controls / "native-worker.py"
        core_worker = controls / "core-worker.py"
        native_worker.write_text(_NATIVE_WORKER)
        core_worker.write_text(_CORE_WORKER)
        calls = []
        ids = []
        resource_observations = []
        resource_confirmation_refusals = []

        def invoke(executable, entry, command=(), expected=0, *, retry_read_conflict=False):
            deadline = time.monotonic() + 10
            while True:
                remaining = deadline - time.monotonic()
                if retry_read_conflict and remaining <= 0:
                    raise AssertionError("Readonly control observation remained busy")
                completed = subprocess.run(
                    [executable, "-I", *entry, *command],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=remaining if retry_read_conflict else 240,
                )
                read_busy = retry_read_conflict and completed.returncode == 9
                payload = _capture(
                    calls,
                    transcripts,
                    executable,
                    entry,
                    command,
                    completed,
                    9 if read_busy else expected,
                )
                if not read_busy:
                    return payload
                assert payload["error"]["code"] == "job_conflict"
                if time.monotonic() >= deadline:
                    raise AssertionError("Readonly control observation remained busy")
                Event().wait(0.02)

        def guarded(code, jobs):
            suffix = _GUARD_SUFFIX.replace(
                "writers={",
                "writers={'submit-comparison-job','configure-job-control',"
                "'cancel-job','reclaim-job-workspaces',",
            )
            return ["-c", _GUARD_PREFIX + _GUARD + suffix + code], ("readonly", str(jobs))

        def run(*command, producer=False, guard=False, jobs=catalog, expected=0):
            if guard:
                entry, prefix = guarded("\nraise SystemExit(main(sys.argv[1:]))\n", jobs)
            else:
                entry, prefix = ["-m", "tickwitness"], ()
            executable = producer_python if producer else verifier
            return invoke(executable, entry, (*prefix, *command), expected)

        def helper(code, *command):
            return invoke(verifier, ["-c", _GUARD + code], ("readonly", *command))

        def view(selected, jobs=catalog):
            entry, prefix = guarded(_CONTROL_VIEW, jobs)
            return invoke(
                verifier, entry, (*prefix, json.dumps(selected)), retry_read_conflict=True
            )

        def actual(job_id, jobs=catalog):
            return view([job_id], jobs)["jobs"][0]

        def catalog_only(job_id, jobs=catalog):
            entry, prefix = guarded(_CATALOG_ONLY, jobs)
            return invoke(verifier, entry, (*prefix, job_id), retry_read_conflict=True)

        def resource_observation(
            job_id,
            phase,
            *,
            jobs=catalog,
            recorded=False,
            worker_identity=None,
            positive=False,
            resource=False,
            reserved=0,
            audited=0,
        ):
            if args.resource_report is None:
                return None
            observed = actual(job_id, jobs)

            def trees():
                return {
                    "catalog": _tree(jobs),
                    "input_root": _tree(inputs),
                    "preparations": _tree(preparations),
                    "controls": _tree(controls),
                    "original_ledger": _tree(root / "live-runs"),
                }

            before = trees()
            inspection = run(
                "inspect-job-resources",
                job_id,
                "--jobs",
                str(jobs),
                "--split",
                "development",
                guard=True,
                jobs=jobs,
            )
            preview = run(
                "preview-job-resources",
                job_id,
                "--jobs",
                str(jobs),
                "--split",
                "development",
                guard=True,
                jobs=jobs,
            )
            repeated = run(
                "inspect-job-resources",
                job_id,
                "--jobs",
                str(jobs),
                "--split",
                "development",
                guard=True,
                jobs=jobs,
            )
            after = trees()
            assert before == after and inspection == repeated
            assert set(inspection) == {
                "kind",
                "schema_version",
                "job_id",
                "policy_id",
                "current_snapshot_sha256",
                "report_id",
                "report",
                "report_matches_current_snapshot",
                "status",
                "execution_authorized",
            }
            assert inspection["kind"] == "job_resource_inspection_v1"
            assert inspection["schema_version"] == 1 and inspection["job_id"] == job_id
            assert inspection["policy_id"] == observed["control"]["policy_id"]
            assert inspection["current_snapshot_sha256"] == _sha(_canonical(observed["snapshot"]))
            assert inspection["execution_authorized"] is False
            _resource_preview(preview, observed)
            report_file = jobs / ".job-resources" / job_id / "report.json"
            if recorded:
                report = inspection["report"]
                assert isinstance(report, dict)
                raw = report_file.read_bytes()
                assert raw == _canonical(report) and len(raw) <= 16384
                assert inspection["report_id"] == _sha(raw)
                assert inspection["report_matches_current_snapshot"] is True
                assert inspection["status"] == (
                    "RECORDED" if report["collection_status"] == "complete" else "PARTIAL"
                )
                _resource_document(
                    report,
                    observed,
                    worker_identity=worker_identity,
                    positive=positive,
                    resource=resource,
                )
                if phase in {"post-exhaustion-ack", "queued-cancelled"}:
                    assert report["worker_started"] is False
                metrics = report["metrics"]
                assert metrics["research_slots_reserved_count"]["value"] == reserved
                assert metrics["audited_native_results_count"]["value"] == audited
                processed = metrics["processed_input_record_count"]
                if audited:
                    assert processed["availability"] == "measured" and processed["value"] == 6
                else:
                    assert processed["availability"] == "unavailable"
                    assert processed["reason"] == "result_not_audited"
            else:
                assert inspection["status"] == "NOT_RECORDED"
                assert inspection["report_id"] is None and inspection["report"] is None
                assert inspection["report_matches_current_snapshot"] is None
                assert not report_file.exists()
            observation = {
                "phase": phase,
                "job_id": job_id,
                "catalog": jobs.name,
                "inspection": inspection,
                "preview": preview,
                "before_roots": before,
                "after_roots": after,
                "worker_identity": worker_identity,
                "new_research_reservations": reserved,
                "new_native_results_audited": audited,
            }
            resource_observations.append(observation)
            return observation

        def configure(job_id, *, wall=120, file_bytes=8388608, jobs=catalog):
            command = (
                "configure-job-control",
                job_id,
                "--jobs",
                str(jobs),
                "--wall-seconds",
                str(wall),
                "--worker-cpu-seconds",
                "60",
                "--max-file-bytes",
                str(file_bytes),
                "--max-open-files",
                "128",
            )
            configured = run(*command, guard=True, jobs=jobs)
            before = _tree(jobs)
            repeated = run(*command, guard=True, jobs=jobs)
            assert _tree(jobs) == before
            observed = actual(job_id, jobs)["control"]
            assert observed["policy"]["limits"] == {
                "max_wall_ns": wall * 1_000_000_000,
                "worker_cpu_seconds": 60,
                "max_file_bytes": file_bytes,
                "max_open_files": 128,
                "cleanup_grace_ns": 5_000_000_000,
            }
            assert observed["policy"]["job_id"] == job_id
            assert _sha(_canonical(observed["policy"])) == observed["policy_id"]
            run(
                "configure-job-control",
                job_id,
                "--jobs",
                str(jobs),
                "--wall-seconds",
                str(wall),
                "--max-file-bytes",
                str(file_bytes + 1),
                guard=True,
                jobs=jobs,
                expected=9,
            )
            assert _tree(jobs) == before
            resource_observation(job_id, "queued-configured", jobs=jobs)
            return {"configured": configured, "repeated": repeated, "stored": observed}

        def submit_comparison(tag, *, jobs=catalog, run_id=None, source=None):
            selected = run_id or _sha(tag.encode())
            source = source or {"bundle_id": "1" * 64, "report_id": "2" * 64}
            queued = run(
                "submit-comparison-job",
                selected,
                "--expected-bundle-id",
                source["bundle_id"],
                "--expected-report-id",
                source["report_id"],
                "--input-root",
                str(inputs),
                "--source-evidence",
                "live-source",
                "--runs",
                str(root / "live-runs"),
                "--jobs",
                str(jobs),
                guard=True,
                jobs=jobs,
            )
            assert queued["stored_state"] == "QUEUED"
            if jobs == catalog:
                ids.append(queued["job_id"])
            return queued

        def cancellation(job_id, key, *, jobs=catalog):
            started = time.monotonic_ns()
            response = run(
                "cancel-job",
                job_id,
                "--cancel-key",
                key,
                "--jobs",
                str(jobs),
                guard=True,
                jobs=jobs,
            )
            returned = time.monotonic_ns()
            assert response["status"] in {"accepted", "already_requested"}
            assert actual(job_id, jobs)["control"]["cancel"] is not None
            return {
                "response": response,
                "request_started_ns": started,
                "request_returned_ns": returned,
            }

        def collected(process, executable, entry, command, expected=0):
            stdout, stderr = process.communicate(timeout=35)
            completed = subprocess.CompletedProcess(
                process.args, process.returncode, stdout, stderr
            )
            return _capture(calls, transcripts, executable, entry, command, completed, expected)

        def compute_identity(directory, job_id, ready):
            identity = json.loads((directory / "process-identity.json").read_bytes())
            assert identity["job_id"] == job_id
            assert identity["request_sha256"] == _sha((directory / "request.jsonl").read_bytes())
            assert identity["pid"] != identity["process_group"]
            assert identity["parent_pid"] == identity["process_group"] == identity["session_id"]
            for name in ("pid", "parent_pid", "process_group", "session_id"):
                assert identity[name] == ready[name]
            return identity

        def launch(executable, mode, directory, worker, job_id, jobs=catalog):
            entry = ["-c", _COORDINATOR]
            command = (mode, str(directory), str(worker), "run-job", job_id, "--jobs", str(jobs))
            process = subprocess.Popen(
                [executable, "-I", *entry, *command],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            return process, entry, command

        def finished_stop(job_id, failure_code, jobs=catalog):
            observed = actual(job_id, jobs)
            snapshot, control = observed["snapshot"], observed["control"]
            assert snapshot["state"] == "FAILED" and snapshot["failure"]["code"] == failure_code
            assert snapshot["result_sha256"] is None and observed["result"] is None
            result = control["result"]
            assert result["cause"] == failure_code
            assert result["job_id"] == job_id and result["policy_id"] == control["policy_id"]
            assert result["catalog_state"] == snapshot["state"]
            assert result["catalog_snapshot_sha256"] == _sha(_canonical(snapshot))
            assert all(
                result[key] is True
                for key in (
                    "worker_group_absent",
                    "workspace_removed",
                    "cleanup_confirmed",
                    "stop_confirmed",
                )
            )
            assert result["publication_admitted"] is False
            return observed

        identities = {
            "producer": invoke(producer_python, ["-c", _RUNTIME]),
            "verifier": invoke(verifier, ["-c", _RUNTIME]),
        }
        assert identities["producer"]["native_distribution"] == (
            None if args.core_only else "1.231.0"
        )
        assert identities["verifier"]["native_distribution"] is None
        (root / "interpreter-identities.json").write_bytes(_canonical(identities))
        confirmation_refusals = []
        for command, extra in (
            ("configure-job-control", ()),
            ("cancel-job", ("--cancel-key", "confirmation-denied")),
            ("inspect-job-control", ()),
            ("reclaim-job-workspaces", ()),
        ):
            refusal = run(
                command,
                "invalid",
                *extra,
                "--jobs",
                str(root / "never-jobs"),
                "--split",
                "confirmation",
                expected=5,
            )
            assert refusal["error"]["code"] == "confirmation_access_denied"
            confirmation_refusals.append({"command": command, "refusal": refusal})
        assert not (root / "never-jobs").exists()
        if args.resource_report is not None:
            for command in ("inspect-job-resources", "preview-job-resources"):
                refusal = run(
                    command,
                    "invalid",
                    "--jobs",
                    str(root / "never-resource-jobs"),
                    "--split",
                    "confirmation",
                    expected=5,
                )
                assert refusal["error"]["code"] == "confirmation_access_denied"
                resource_confirmation_refusals.append({"command": command, "refusal": refusal})
            assert not (root / "never-resource-jobs").exists()
        lifecycle = None
        native_cases = []
        source = None
        if not args.core_only:
            lifecycle = _bootstrap(
                run,
                helper,
                examples,
                root,
                inputs,
                original_attempts=8,
                qualification_title="Synthetic eight-slot strong Job control qualification",
            )
            source = lifecycle["source"]
            (inputs / "origin-request.json").write_bytes(_canonical(_request(5, 6)))
            prepared = run(
                "prepare-reduction-input",
                "live-source",
                "origin-request.json",
                "--input-root",
                str(inputs),
                "--expected-bundle-id",
                source["bundle_id"],
                "--expected-report-id",
                source["report_id"],
                "--output",
                str(preparations / "origin"),
            )
            origin = run(
                "submit-reduction-job",
                str(preparations / "origin"),
                "--expected-preparation-id",
                prepared["preparation_id"],
                "--expected-bundle-id",
                source["bundle_id"],
                "--expected-report-id",
                source["report_id"],
                "--source-evidence",
                "live-source",
                "--input-root",
                str(inputs),
                "--runs",
                str(root / "live-runs"),
                "--jobs",
                str(catalog),
                guard=True,
            )
            parent_id = origin["job_id"]
            ids.append(parent_id)
            source_before = _tree(inputs / "live-source")

            def ledger():
                return helper(
                    _LEDGER_VIEW,
                    str(inputs / "live-source"),
                    str(root / "live-runs"),
                    source["bundle_id"],
                )

            for slot, mode in enumerate(
                ("cancel", "deadline", "resource", "cancel_publication", "publication_wins"), 4
            ):
                if slot == 4:
                    submission = origin
                else:
                    submission = run(
                        "retry-reduction-job",
                        parent_id,
                        "--retry-key",
                        f"control-slot-{slot}",
                        "--jobs",
                        str(catalog),
                        guard=True,
                    )
                    ids.append(submission["job_id"])
                job_id = submission["job_id"]
                policy = configure(
                    job_id,
                    wall=15 if mode == "deadline" else 120,
                    file_bytes=65536 if mode == "resource" else 8388608,
                )
                directory = controls / f"native-slot-{slot}-{mode}"
                process, entry, command = launch(
                    producer_python, mode, directory, native_worker, job_id
                )
                cancellation_record = None
                admitted_cancel = None
                late_cancel = None
                try:
                    gate_path = directory / (
                        "publication.json" if "publication" in mode else "ready.json"
                    )
                    gate = _wait_gate(process, gate_path)
                    before = catalog_only(job_id) if mode == "publication_wins" else actual(job_id)
                    assert before["snapshot"]["state"] in (
                        {"RUNNING", "FAILED"} if mode == "resource" else {"RUNNING"}
                    )
                    if mode in {"cancel", "cancel_publication"}:
                        cancellation_record = cancellation(job_id, f"cancel-slot-{slot}")
                        if mode == "cancel_publication":
                            (directory / "release-publication").write_text("release")
                    elif mode == "publication_wins":
                        assert gate["publication_admission"] is not None
                        admitted_cancel = run(
                            "cancel-job",
                            job_id,
                            "--cancel-key",
                            "too-late-gate",
                            "--jobs",
                            str(catalog),
                            guard=True,
                        )
                        assert admitted_cancel["status"] == "too_late"
                        assert admitted_cancel["request"] is None
                        assert (
                            admitted_cancel["publication_admission"]
                            == (gate["publication_admission"])
                        )
                        (directory / "release-publication").write_text("release")
                    finished = collected(process, producer_python, entry, command)
                finally:
                    _cleanup(process)
                    if (directory / "ready.json").exists():
                        with suppress(OSError, ValueError, KeyError, TypeError):
                            _workspace_observation(directory, catalog)
                request = json.loads((directory / "request.jsonl").read_bytes())
                worker_ready = json.loads((directory / "ready.json").read_bytes())
                worker_identity = compute_identity(directory, job_id, worker_ready)
                workspace_after = json.loads((directory / "workspace-after.json").read_bytes())
                assert workspace_after["namespace_bound"] is True
                seal = workspace_after["seal"]
                assert seal["job_id"] == job_id
                assert seal["job_attempt_id"] == request["job_attempt_id"]
                assert seal["coordinator_id"] == request["coordinator_id"]
                assert seal["policy_id"] == policy["stored"]["policy_id"]
                assert worker_ready["workspace_at_ready"]["exists"] is True
                assert worker_ready["workspace_at_ready"]["is_symlink"] is False
                assert worker_ready["workspace_at_ready"]["device"] == seal["scratch_device"]
                assert worker_ready["workspace_at_ready"]["inode"] == seal["scratch_inode"]
                calls_for_worker = [
                    json.loads(line)
                    for line in (directory / "native-calls.jsonl").read_bytes().splitlines()
                ]
                assert len(calls_for_worker) == 1
                assert worker_ready["pid"] == calls_for_worker[0]["pid"]
                for name in ("parent_pid", "process_group", "session_id"):
                    assert calls_for_worker[0][name] == worker_identity[name]
                assert worker_ready["limits"]["cpu"][0] == 60
                assert worker_ready["limits"]["files"][0] == 128
                assert worker_ready["limits"]["file"][0] == (
                    65536 if mode == "resource" else 8388608
                )
                assert request["job_id"] == job_id
                assert request["payload"]["research_attempt"]["attempt_index"] == slot
                assert (directory / "actual-native-result.json").exists()
                frames = [
                    json.loads(line)
                    for line in (directory / "delivered-ipc.jsonl").read_bytes().splitlines()
                ]
                assert len(frames) >= 1
                assert [frame["sequence"] for frame in frames] == list(range(1, len(frames) + 1))
                for frame in frames:
                    assert all(
                        frame[key] == request[key]
                        for key in ("job_id", "coordinator_id", "job_attempt_id", "lease_token")
                    )
                observed = actual(job_id)
                if observed["control"]["result"]["cleanup_confirmed"]:
                    assert workspace_after["exists"] is False
                    assert workspace_after["is_symlink"] is False
                if mode == "publication_wins":
                    assert finished["stored_state"] == "SUCCEEDED"
                    assert observed["result"]["action"] == "replayed_from_origin"
                    assert observed["result"]["dispatch_job_id"] == job_id
                    native_result = (directory / "actual-native-result.json").read_bytes()
                    assert observed["result"]["outcome"]["bindings"]["replay_result_sha256"] == (
                        _sha(native_result)
                    )
                    assert observed["control"]["result"]["cause"] == "finished"
                    frozen_catalog = _tree(catalog)
                    late_cancel = run(
                        "cancel-job",
                        job_id,
                        "--cancel-key",
                        "after-actual-commit",
                        "--jobs",
                        str(catalog),
                        guard=True,
                    )
                    assert late_cancel["status"] in {"too_late", "already_terminal"}
                    assert actual(job_id)["control"]["cancel"] is None
                    assert _tree(catalog) == frozen_catalog
                else:
                    expected = {
                        "cancel": "job_cancelled",
                        "deadline": "job_deadline_exceeded",
                        "resource": "job_resource_limit",
                        "cancel_publication": "job_cancelled",
                    }[mode]
                    observed = finished_stop(job_id, expected)
                    if mode == "deadline":
                        assert len(frames) >= 3
                        assert observed["control"]["result"]["timing_ns"]["elapsed"] >= (
                            15_000_000_000
                        )
                    if mode == "resource":
                        assert observed["snapshot"]["failure"]["worker_exit_code"] == (
                            -signal.SIGXFSZ
                        )
                        quota = json.loads((directory / "resource-probe.json").read_bytes())
                        assert quota["native_completed"]
                        assert quota["bytes_before_violation"] == 65536
                if cancellation_record is not None:
                    observed_at = time.monotonic_ns()
                    cancellation_record["terminal_observed_ns"] = observed_at
                    cancellation_record["observed_upper_bound_ns"] = (
                        observed_at - cancellation_record["request_started_ns"]
                    )
                    assert cancellation_record["observed_upper_bound_ns"] > 0
                terminal_before = actual(job_id)
                terminal_tree = _tree(catalog)
                repeated_terminal = run("run-job", job_id, "--jobs", str(catalog), guard=True)
                assert repeated_terminal["stored_state"] == finished["stored_state"]
                assert actual(job_id) == terminal_before and _tree(catalog) == terminal_tree
                slots = ledger()
                assert len(slots["slots"]) == slot
                assert slots["slots"][-1]["outcome_id"] is None or mode == "publication_wins"
                assert _tree(inputs / "live-source") == source_before
                resource_observation(
                    job_id,
                    "native-" + mode,
                    recorded=True,
                    worker_identity=worker_identity,
                    positive=mode == "publication_wins",
                    resource=mode == "resource",
                    reserved=1,
                    audited=1 if mode in {"cancel_publication", "publication_wins"} else 0,
                )
                native_cases.append(
                    {
                        "slot": slot,
                        "mode": mode,
                        "submission": submission,
                        "policy": policy,
                        "gate": gate,
                        "before": before,
                        "finished": finished,
                        "observed": observed,
                        "cancel": cancellation_record,
                        "admitted_cancel": admitted_cancel,
                        "late_cancel": late_cancel,
                        "terminal_rerun": repeated_terminal,
                        "worker_request": request,
                        "native_calls": calls_for_worker,
                        "actual_worker_ready": worker_ready,
                        "worker_process_identity": worker_identity,
                        "workspace_observation": workspace_after,
                        "actual_coordinator_pid": process.pid,
                        "delivered_ipc": frames,
                        "original_ledger": slots,
                    }
                )
                parent_id = job_id
            final_before_ack = ledger()
            assert [item["attempt_index"] for item in final_before_ack["slots"]] == list(
                range(1, 9)
            )
            assert [
                item["attempt_index"]
                for item in final_before_ack["slots"]
                if item["outcome_id"] is not None
            ] == [1, 2, 3, 8]
            native_before = _tree(controls)
            research_before = _tree(root / "live-runs")
            ack = run(
                "recover-reduction-job",
                parent_id,
                "--recovery-key",
                "after-eight-slots",
                "--jobs",
                str(catalog),
                guard=True,
            )
            ids.append(ack["job_id"])
            ack_policy = configure(ack["job_id"])
            ack_finished = run("run-job", ack["job_id"], "--jobs", str(catalog), guard=True)
            assert ack_finished["stored_state"] == "SUCCEEDED"
            ack_observed = actual(ack["job_id"])
            assert ack_observed["result"]["action"] == "acknowledged_committed"
            assert _tree(root / "live-runs") == research_before
            assert _tree(controls) == native_before and ledger() == final_before_ack
            resource_observation(ack["job_id"], "post-exhaustion-ack", recorded=True)
            lifecycle.update(
                {
                    "cases": native_cases,
                    "after": final_before_ack,
                    "acknowledgment": {
                        "submission": ack,
                        "policy": ack_policy,
                        "finished": ack_finished,
                        "observed": ack_observed,
                    },
                    "research_after_ack_unchanged": True,
                }
            )

        completed_run = (
            None
            if args.core_only
            else _sha(_canonical(native_cases[-1]["observed"]["result"]["outcome"]))
        )
        queued = submit_comparison(
            "queued-cancellation",
            run_id=completed_run,
            source=source,
        )
        resource_observation(queued["job_id"], "queued-unconfigured")
        queued_policy = configure(queued["job_id"])
        queued_cancel = cancellation(queued["job_id"], "queued-cancel")
        queued_observed = actual(queued["job_id"])
        if queued_observed["snapshot"]["state"] == "QUEUED":
            run("run-job", queued["job_id"], "--jobs", str(catalog), guard=True)
        queued_observed = finished_stop(queued["job_id"], "job_cancelled")
        queued_cancel["terminal_observed_ns"] = time.monotonic_ns()
        queued_cancel["observed_upper_bound_ns"] = (
            queued_cancel["terminal_observed_ns"] - queued_cancel["request_started_ns"]
        )
        assert queued_observed["control"]["result"]["worker_started"] is False
        queued_tree = _tree(catalog)
        repeated_cancel = run(
            "cancel-job",
            queued["job_id"],
            "--cancel-key",
            "queued-cancel",
            "--jobs",
            str(catalog),
            guard=True,
        )
        assert repeated_cancel["status"] == "already_requested" and _tree(catalog) == queued_tree
        conflicting_cancel = run(
            "cancel-job",
            queued["job_id"],
            "--cancel-key",
            "other-queued-key",
            "--jobs",
            str(catalog),
            guard=True,
            expected=9,
        )
        assert _tree(catalog) == queued_tree
        resource_observation(queued["job_id"], "queued-cancelled", recorded=True)
        transport_cases = []
        for mode in ("cancel", "deadline", "resource", "orphan"):
            jobs = root / f"transport-{mode}-jobs"
            queued_transport = submit_comparison("transport-" + mode, jobs=jobs)
            job_id = queued_transport["job_id"]
            policy = configure(
                job_id,
                jobs=jobs,
                wall=3 if mode in {"deadline", "orphan"} else 120,
                file_bytes=65536 if mode == "resource" else 8388608,
            )
            directory = controls / ("transport-" + mode)
            process, entry, command = launch(verifier, mode, directory, core_worker, job_id, jobs)
            cancel = None
            try:
                gate = _wait_gate(process, directory / "ready.json")
                worker_identity = compute_identity(directory, job_id, gate)
                scratch = Path(gate["workspace"])
                assert scratch.resolve().is_relative_to(jobs.resolve())
                assert scratch.name == "scratch"
                if mode == "cancel":
                    cancel = cancellation(job_id, "transport-cancel", jobs=jobs)
                if mode == "orphan":
                    live_workspace = helper(_WORKSPACE_PROBE, str(scratch))
                    assert live_workspace["lifetime_busy"] is True
                    before_kill = actual(job_id, jobs)
                    os.kill(process.pid, signal.SIGKILL)
                    finished = collected(process, verifier, entry, command, -signal.SIGKILL)
                    deadline = time.monotonic() + 10
                    unlocked = None
                    while time.monotonic() < deadline:
                        unlocked = helper(_WORKSPACE_PROBE, str(scratch))
                        if not unlocked["lifetime_busy"]:
                            break
                        Event().wait(0.05)
                    assert unlocked is not None and not unlocked["lifetime_busy"]
                    reclaimed = run(
                        "reclaim-job-workspaces", job_id, "--jobs", str(jobs), jobs=jobs
                    )
                    assert not scratch.exists()
                    observed = actual(job_id, jobs)
                    assert observed["snapshot"]["state"] == "LOST"
                    resource_observation(job_id, "transport-orphan", jobs=jobs)
                    transport_cases.append(
                        {
                            "mode": mode,
                            "fixture_only": True,
                            "submission": queued_transport,
                            "policy": policy,
                            "gate": gate,
                            "before_kill": before_kill,
                            "actual_coordinator_pid": process.pid,
                            "actual_worker_pid": gate["pid"],
                            "worker_process_identity": worker_identity,
                            "live_workspace": live_workspace,
                            "unlocked_workspace": unlocked,
                            "finished": finished,
                            "reclaimed": reclaimed,
                            "observed": observed,
                        }
                    )
                    continue
                finished = collected(process, verifier, entry, command)
            finally:
                _cleanup(process)
            cause = {
                "cancel": "job_cancelled",
                "deadline": "job_deadline_exceeded",
                "resource": "job_resource_limit",
            }[mode]
            observed = finished_stop(job_id, cause, jobs)
            if mode == "deadline":
                assert observed["control"]["result"]["timing_ns"]["elapsed"] >= 3_000_000_000
            assert not scratch.exists()
            if cancel is not None:
                observed_at = time.monotonic_ns()
                cancel["terminal_observed_ns"] = observed_at
                cancel["observed_upper_bound_ns"] = observed_at - cancel["request_started_ns"]
            resource_observation(
                job_id,
                "transport-" + mode,
                jobs=jobs,
                recorded=True,
                worker_identity=worker_identity,
                resource=mode == "resource",
            )
            transport_cases.append(
                {
                    "mode": mode,
                    "fixture_only": True,
                    "submission": queued_transport,
                    "policy": policy,
                    "gate": gate,
                    "finished": finished,
                    "cancel": cancel,
                    "observed": observed,
                    "worker_process_identity": worker_identity,
                }
            )
        assert _tree(examples / "alpha") == golden_before
        resource_report = None
        if args.resource_report is not None:
            recorded_resources = [
                observation
                for observation in resource_observations
                if observation["inspection"]["report"] is not None
            ]
            native_resources = [
                observation
                for observation in resource_observations
                if observation["phase"].startswith("native-")
            ]
            assert len(native_resources) == (0 if args.core_only else 5)
            native_calls = sum(len(case["native_calls"]) for case in native_cases)
            assert native_calls == len(native_resources)
            assert len(recorded_resources) == (4 if args.core_only else 10)
            orphan_resources = [
                observation
                for observation in resource_observations
                if observation["phase"] == "transport-orphan"
            ]
            assert len(orphan_resources) == 1
            assert orphan_resources[0]["inspection"]["status"] == "NOT_RECORDED"
            assert all(
                observation["before_roots"] == observation["after_roots"]
                for observation in resource_observations
            )
            resource_report = {
                "kind": "installed_job_resources_acceptance_v1",
                "schema_version": 1,
                "accepted": True,
                "core_only_profile": args.core_only,
                "interpreter_identities": identities,
                "confirmation_refusals": resource_confirmation_refusals,
                "observations": resource_observations,
                "accounting": {
                    "original_protocol": None if lifecycle is None else lifecycle["after"],
                    "managed_native_calls": native_calls,
                    "recorded_reports": len(recorded_resources),
                    "worker_usage_reports": sum(
                        observation["inspection"]["report"]["worker_usage"] is not None
                        for observation in recorded_resources
                    ),
                    "new_research_slots_from_inspection_or_preview": 0,
                    "post_exhaustion_ack_new_slots": 0,
                    "post_exhaustion_ack_new_workers": 0,
                },
                "scope": {
                    "actual_managed_native_resources": not args.core_only,
                    "core_transport_fixtures": True,
                    "cpu_source": "owned_compute_child_wait4",
                    "memory_scope": "terminated_compute_child_os_accounting",
                    "disk_scope": "owned_scratch_cleanup_regular_entries",
                    "measurements_are_estimates": False,
                    "preview_calibrated": False,
                    "predicate_evaluations_instrumented": False,
                    "unsupported_and_tampered_live_probes": False,
                    "hard_rss_or_aggregate_scratch_limits": False,
                    "global_resource_accounting": False,
                    "research_budget_reset": False,
                    "external_human_attempts": 0,
                    "external_human_gate": "PENDING",
                },
            }
            inner_resources = root / "job-resources-smoke" / "report.json"
            inner_resources.parent.mkdir()
            inner_resources.write_bytes(_canonical(resource_report))
        report = {
            "kind": "installed_job_controls_acceptance_v1",
            "accepted": True,
            "core_only_profile": args.core_only,
            "interpreter_identities": identities,
            "confirmation_refusals": confirmation_refusals,
            "native_lifecycle": lifecycle,
            "queued_cancellation": {
                "submission": queued,
                "policy": queued_policy,
                "cancel": queued_cancel,
                "observed": queued_observed,
                "repeated": repeated_cancel,
                "conflicting_key": conflicting_cancel,
            },
            "transport_fixtures": transport_cases,
            "catalog": view(ids),
            "scope": {
                "actual_native_controls": not args.core_only,
                "queued_cancellation": True,
                "real_transport_fixture_controls": True,
                "explicit_orphan_scratch_reclamation": True,
                "research_budget_reset": False,
                "global_lineage_cancellation": False,
                "hostile_code_containment": False,
                "checkpoint_resume": False,
                "external_human_attempts": 0,
                "external_human_gate": "PENDING",
            },
        }
        inner = root / "job-controls-smoke" / "report.json"
        inner.parent.mkdir()
        inner.write_bytes(_canonical(report))
        shutil.copytree(root, args.records_dir)
        (args.records_dir / "artifact-files.json").write_bytes(_canonical(_tree(args.records_dir)))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(_canonical(report))
        if args.resource_report is not None:
            args.resource_report.parent.mkdir(parents=True, exist_ok=True)
            with args.resource_report.open("xb") as resource_stream:
                resource_stream.write(_canonical(resource_report))


if __name__ == "__main__":
    main()
