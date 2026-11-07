#!/usr/bin/env python3
"""Qualify installed managed native Jobs on one original synthetic eight-slot budget.

The legacy five-slot reduction and eleven-slot read-only comparison profiles
remain independent. Fault workers delegate the installed native worker and gate
an actual native result; they never manufacture a successful engine response.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from smoke_reduction_execution import (
    _GOLDEN,
    _GUARD,
    _LEDGER_VIEW,
    _READ_ARTIFACT,
    _canonical,
    _check_attempt_recovery,
    _request,
    _sha,
    _tree,
)

_RUNTIME = """
import json,sys
from importlib import metadata
try:native=metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:native=None
print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,
                  'base_prefix':sys.base_prefix,'native_distribution':native,
                  'project_version':metadata.version('tickwitness')},sort_keys=True))
"""
_CATALOG_GUARD_PREFIX = """
import sqlite3
real_sqlite_connect=sqlite3.connect
"""
_CATALOG_GUARD_SUFFIX = """
import os
from urllib.parse import unquote
catalog=Path(sys.argv.pop(1))
allowed=os.path.abspath(str(catalog/'catalog.sqlite3'))
def catalog_connect(database,*args,**kwargs):
    locator=str(database)
    value=unquote(locator[5:].split('?',1)[0]) if locator.startswith('file:') else locator
    if os.path.abspath(value)!=allowed:forbidden()
    command=sys.argv[1] if len(sys.argv)>1 else ''
    if command not in ('submit-reduction-job','run-job') and 'mode=ro' not in locator:forbidden()
    return real_sqlite_connect(database,*args,**kwargs)
sqlite3.connect=catalog_connect
"""
_WORKER = """
import io,json,os,sys
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
assert set(request)=={'kind','schema_version','job_id','coordinator_id',
                      'job_attempt_id','lease_token','payload'}
assert set(request['payload'])=={'research_attempt','intent','dataset_id',
                                'normalized','replay_spec','native_deadline_ns'}
assert request['kind']=='job_native_worker_request_v1'
assert request['payload']['research_attempt']['attempt_index'] in (4,5,6,7,8)
def forbidden(*args,**kwargs):
    raise AssertionError('Native worker cannot open or mutate research ledger or Job Catalog')
LocalAttemptLedger.__init__=forbidden
SqliteJobStore.__init__=forbidden
for name in ('reserve','reserve_with_nonce','bind_intent','publish'):
    setattr(LocalAttemptLedger,name,forbidden)
actual_native_run=NautilusReplayAdapter.run
def counted_native(self,replay_input):
    with (root/'native-calls.jsonl').open('ab') as stream:
        stream.write(json.dumps({'kind':'actual_native_adapter_run_started_v1',
                    'dataset_id':replay_input.dataset_id},sort_keys=True,
                    separators=(',',':')).encode()+b'\\n')
    return actual_native_run(self,replay_input)
NautilusReplayAdapter.run=counted_native
actual_stdout=sys.stdout
class Buffer:
    def write(self,data):
        if b'\\n' in data:
            frame=json.loads(data)
            if frame['kind']=='job_native_result_v1':
                (root/'produced-native-result.jsonl').write_bytes(data)
                if mode in ('worker_kill','coordinator_kill'):
                    ready={'pid':os.getpid(),'job_id':request['job_id'],
                           'job_attempt_id':request['job_attempt_id'],
                           'terminal_sequence':frame['sequence'],
                           'last_heartbeat_sequence':frame['sequence']-1,
                           'research_attempt_id':__import__('hashlib').sha256(
                               json.dumps(request['payload']['research_attempt'],sort_keys=True,
                                   separators=(',',':')).encode()).hexdigest(),
                           'phase':'after_actual_native_result_before_terminal_ipc'}
                    pending=root/'gate.pending'
                    pending.write_text(json.dumps(ready,sort_keys=True,separators=(',',':')))
                    os.replace(pending,root/'gate.json')
                    Event().wait(55)
        with (root/'delivered-ipc.jsonl').open('ab') as stream:stream.write(data)
        return actual_stdout.buffer.write(data)
    def flush(self):return actual_stdout.buffer.flush()
class Output:
    buffer=Buffer()
    def write(self,value):return self.buffer.write(value.encode())
    def flush(self):return self.buffer.flush()
sys.stdin=io.TextIOWrapper(io.BytesIO(raw),encoding='utf-8')
sys.stdout=Output()
raise SystemExit(native_job_worker.main())
"""
_COORDINATOR = """
import json,sys,time
from pathlib import Path
from tickwitness import cli_jobs
from tickwitness.cli import main
from tickwitness.infrastructure import job_reduction
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
mode,root,worker=sys.argv.pop(1),Path(sys.argv.pop(1)),sys.argv.pop(1)
root.mkdir(parents=True,exist_ok=True)
def record(value):
    with (root/'coordinator-controls.jsonl').open('a') as stream:
        stream.write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n')
original_publish=LocalAttemptLedger.publish
def publish(self,reservation,raw,*,artifacts=()):
    record({'kind':'research_publish_invoked_v1','attempt_id':reservation.attempt_id})
    committed=original_publish(self,reservation,raw,artifacts=artifacts)
    record({'kind':'actual_research_outcome_committed_v1',
            'attempt_id':reservation.attempt_id,'outcome_id':committed})
    if mode=='ack_loss':
        raise OSError('Qualification injected acknowledgement loss after actual research commit')
    return committed
LocalAttemptLedger.publish=publish
if mode=='expired_publication':
    original_admission=job_reduction.publish_reduction_execution
    def delayed(execution,reservation,audited,*,ledger,fence):
        record({'kind':'actual_native_result_audited_before_publication_delay_v1',
                'attempt_id':reservation.attempt_id,'delay_seconds':11})
        time.sleep(11)
        return original_admission(execution,reservation,audited,ledger=ledger,fence=fence)
    job_reduction.publish_reduction_execution=delayed
original_run=cli_jobs.run_job
def managed(store,job_id):
    return original_run(store,job_id,_worker_command=(sys.executable,'-I','-B',worker,
                                                    mode,str(root)))
cli_jobs.run_job=managed
raise SystemExit(main(sys.argv[1:]))
"""
_CATALOG = """
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
store=SqliteJobStore(catalog,create=False)
rows=[]
for job_id in json.loads(sys.argv[1]):
    raw=store.result(job_id)
    rows.append({'snapshot':store.get(job_id),'events':store.events(job_id,limit=1000),
                 'result':None if raw is None else json.loads(raw)})
print(json.dumps({'jobs':rows,'coordinator_active':store.coordinator_active()},
                 sort_keys=True,separators=(',',':')))
"""
_STALE = """
from tickwitness.application.jobs import JobConflictError
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
store=SqliteJobStore(Path(sys.argv[1]),create=False)
old=json.loads(Path(sys.argv[3]).read_bytes())
job_id=sys.argv[2]
before=store.get(job_id)
credentials=old['attempt']
try:
    with store.coordinator():
        store.assert_active(job_id,expected_version=before['version'],
            coordinator_id=credentials['coordinator_id'],
            job_attempt_id=credentials['job_attempt_id'],
            lease_token=credentials['lease_token'],now_ns=__import__('time').time_ns())
except JobConflictError:
    print(json.dumps({'stale_publication_admission_refused':True,
                      'snapshot_unchanged':store.get(job_id)==before}))
else:raise AssertionError('Retired coordinator admission was accepted')
"""


@contextmanager
def _workspace(records: Path, report: Path):
    with TemporaryDirectory(prefix="tickwitness-native-jobs-") as temporary:
        root = Path(temporary)
        error = None
        try:
            yield root
        except BaseException as caught:
            error = caught
            with suppress(OSError):
                report.unlink(missing_ok=True)
            raise
        finally:
            if not records.exists():
                shutil.copytree(root, records)
                (records / "diagnostic-capture.json").write_bytes(
                    _canonical(
                        {
                            "kind": "native_job_workspace_diagnostics_v1",
                            "accepted": False,
                            "exception_type": None if error is None else type(error).__name__,
                            "message": None if error is None else str(error),
                        }
                    )
                )


def _bootstrap(run, helper, examples: Path, root: Path, inputs: Path) -> dict:
    for name in (
        "replay-partials.jsonl",
        "replay-confirmation.jsonl",
        "stress-assumption-request.json",
        "search-execution-grid-request.json",
        "search-finding-request.json",
    ):
        shutil.copyfile(examples / name, inputs / name)
    request = json.loads((examples / "stress-experiment-request.json").read_bytes())
    request["claim"]["title"] = "Synthetic eight-slot managed native Job qualification"
    request["budget"]["max_attempts"] = 8
    (inputs / "experiment.json").write_bytes(_canonical(request))
    (inputs / "campaign-budget.json").write_bytes(
        _canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": 2,
                "max_wall_time_ms": 120000,
                "max_storage_bytes": 512 * 1024 * 1024,
            }
        )
    )
    data, registry, plans, runs, findings = (
        root / name for name in ("data", "registry", "plans", "live-runs", "findings")
    )
    datasets = [
        run("import-events", name, "--input-root", str(inputs), "--store", str(data))["dataset_id"]
        for name in ("replay-partials.jsonl", "replay-confirmation.jsonl")
    ]
    frozen = run(
        "freeze-experiment", "experiment.json", "--input-root", str(inputs),
        "--development-dataset", datasets[0], "--confirmation-dataset", datasets[1],
        "--store", str(data), "--registry", str(registry),
    )
    assert frozen["document"]["budget"] == {
        "max_attempts": 8, "max_events": 1000, "max_wall_seconds": 60
    }
    plan = run(
        "freeze-search-plan", frozen["protocol_id"], "stress-assumption-request.json",
        "search-execution-grid-request.json", "--input-root", str(inputs),
        "--store", str(data), "--registry", str(registry), "--plans", str(plans),
    )
    authority = run(
        "freeze-search-finding-protocol", plan["plan_id"], "search-finding-request.json",
        "--input-root", str(inputs), "--plans", str(plans), "--finding-registry", str(findings),
    )
    baseline = run(
        "replay-protocol", frozen["protocol_id"], "--store", str(data),
        "--registry", str(registry), "--runs", str(runs), producer=True,
    )
    common = ("--plans", str(plans), "--store", str(data), "--registry", str(registry),
              "--runs", str(runs))
    campaign = run(
        "run-bounded-search-plan", plan["plan_id"], "campaign-budget.json",
        "--input-root", str(inputs), *common, producer=True,
    )
    finding = run(
        "evaluate-search-findings", authority["protocol_id"], *common,
        "--finding-registry", str(findings),
    )
    assert finding["report"]["outcome"] == "COUNTEREXAMPLE_FOUND"
    assert [row["ordinal"] for row in finding["report"]["witnesses"]] == [1, 3]
    source = run(
        "export-search-evidence", authority["protocol_id"], "--expected-report-id",
        finding["report_id"], *common, "--finding-registry", str(findings),
        "--output", str(inputs / "live-source"),
    )
    before = helper(_LEDGER_VIEW, str(inputs / "live-source"), str(runs), source["bundle_id"])
    assert before["protocol_id"] == frozen["protocol_id"]
    assert [row["attempt_index"] for row in before["slots"]] == [1, 2, 3]
    return {
        "frozen": frozen, "plan": plan, "baseline": baseline,
        "campaign": campaign, "finding": finding, "source": source, "before": before,
    }


def _managed_lifecycle(
    run, helper, catalog_helper, invoke, capture, catalog_view, lifecycle, native, root,
    inputs, preparations, catalog, controls, worker, cwd,
) -> dict:
    runs = root / "live-runs"
    source = lifecycle["source"]
    source_before = _tree(inputs / "live-source")
    original_records = _tree(runs)
    jobs = {}
    ids = []

    def ledger():
        return helper(_LEDGER_VIEW, str(inputs / "live-source"), str(runs), source["bundle_id"])

    def submit(name, focus, through, *, lease=30, jobs_root=catalog, existing=None):
        if existing is None:
            (inputs / (name + ".json")).write_bytes(_canonical(_request(focus, through)))
            prepared = run(
                "prepare-reduction-input", "live-source", name + ".json",
                "--input-root", str(inputs), "--expected-bundle-id", source["bundle_id"],
                "--expected-report-id", source["report_id"], "--output", str(preparations / name),
            )
            preparation = preparations / name
        else:
            prepared, preparation = existing
        command = (
            "submit-reduction-job", str(preparation), "--expected-preparation-id",
            prepared["preparation_id"], "--expected-bundle-id", source["bundle_id"],
            "--expected-report-id", source["report_id"], "--source-evidence", "live-source",
            "--input-root", str(inputs), "--runs", str(runs), "--jobs", str(jobs_root),
            "--lease-seconds", str(lease),
        )
        queued = run(*command, guarded=True, jobs=jobs_root)
        assert queued["stored_state"] == "QUEUED"
        before_repeat = _tree(runs), _tree(jobs_root)
        assert run(*command, guarded=True, jobs=jobs_root) == queued
        assert (_tree(runs), _tree(jobs_root)) == before_repeat
        value = {
            "name": name, "preparation": prepared,
            "preparation_path": str(preparation.relative_to(root)),
            "submission": queued, "job_id": queued["job_id"], "lease_seconds": lease,
        }
        if jobs_root == catalog:
            jobs[name] = value
            ids.append(queued["job_id"])
        return value

    def inspect_dispatch(value):
        before = _tree(runs), _tree(catalog), _tree(inputs / "live-source")
        observed = run(
            "inspect-reduction-job", value["job_id"], "--jobs", str(catalog), guarded=True
        )
        assert observed["kind"] == "native_job_inspection_v1"
        dispatch = observed["dispatch"]
        assert dispatch["kind"] == "native_job_dispatch_observation_v1"
        assert dispatch["job_id"] == value["job_id"]
        assert dispatch["dispatch_nonce"] == _sha(
            _canonical({"kind": "reduction_job_dispatch_nonce_v1", "job_id": value["job_id"]})
        )[:32]
        assert dispatch["observation_only"] is True
        for key in (
            "execution_authorized", "job_state_changed", "automatic_retry_performed",
            "budget_refunded", "global_absence_verified",
        ):
            assert dispatch[key] is False
        assert (_tree(runs), _tree(catalog), _tree(inputs / "live-source")) == before
        return observed

    def coordinator(value, mode, *, expected=0):
        directory = controls / value["name"]
        entry = ["-c", _COORDINATOR]
        command = (
            mode, str(directory), str(worker), "run-job", value["job_id"],
            "--jobs", str(catalog),
        )
        return invoke(native, entry, command, expected=expected)

    def worker_evidence(value, slot):
        directory = controls / value["name"]
        request = json.loads((directory / "request.jsonl").read_bytes())
        produced = json.loads((directory / "produced-native-result.jsonl").read_bytes())
        calls = [
            json.loads(line)
            for line in (directory / "native-calls.jsonl").read_bytes().splitlines()
        ]
        assert calls == [{
            "kind": "actual_native_adapter_run_started_v1",
            "dataset_id": value["preparation"]["prefix_context_id"],
        }]
        assert request["job_id"] == produced["job_id"] == value["job_id"]
        assert produced["kind"] == "job_native_result_v1"
        delivered = [
            json.loads(line)
            for line in (directory / "delivered-ipc.jsonl").read_bytes().splitlines()
        ]
        for sequence, frame in enumerate(delivered, start=1):
            assert frame["sequence"] == sequence
            assert all(
                frame[key] == request[key]
                for key in ("job_id", "coordinator_id", "job_attempt_id", "lease_token")
            )
        if value["name"] in ("worker_kill", "coordinator_kill"):
            assert len(delivered) == produced["sequence"] - 1
            assert all(frame["kind"] == "job_heartbeat_v1" for frame in delivered)
        else:
            assert delivered[-1] == produced
            assert len(delivered) == produced["sequence"]
        reservation = request["payload"]["research_attempt"]
        assert reservation["attempt_index"] == slot
        assert reservation["protocol_id"] == lifecycle["frozen"]["protocol_id"]
        assert reservation["max_wall_seconds"] == 60
        expected_nonce = _sha(_canonical({
            "kind": "reduction_job_dispatch_nonce_v1", "job_id": value["job_id"]
        }))[:32]
        assert reservation["nonce"] == expected_nonce
        snapshot = ledger()
        actual = snapshot["slots"][slot - 1]
        assert actual["reservation"] == reservation
        assert actual["attempt_id"] == _sha(_canonical(reservation))
        assert actual["intent_id"] == _sha(_canonical(request["payload"]["intent"]))
        for object_name in (
            "manifest.json", "recipe.json", "materialization.json", "normalized.jsonl"
        ):
            raw = (root / value["preparation_path"] / object_name).read_bytes()
            assert (runs / "objects" / "sha256" / _sha(raw)).read_bytes() == raw
        return {
            "request": request, "produced_terminal": produced, "delivered_ipc": delivered,
            "native_calls": calls,
            "ledger_slot": actual, "control_path": str(directory.relative_to(root)),
            "worker_research_and_catalog_constructor_tripwires": True,
        }

    def unchanged_terminal(value):
        before = _tree(runs), _tree(catalog), _tree(controls)
        repeated = run("run-job", value["job_id"], "--jobs", str(catalog), producer=True)
        assert repeated["stored_state"] in ("SUCCEEDED", "FAILED", "LOST")
        assert (_tree(runs), _tree(catalog), _tree(controls)) == before
        return repeated

    for name, focus, through, slot, mode in (
        ("pending-cancel", 4, 4, 4, "normal"),
        ("filled-cancel-rejected", 5, 6, 5, "ack_loss"),
    ):
        value = submit(name, focus, through)
        before = ledger()
        assert len(before["slots"]) == slot - 1
        outcome = coordinator(value, mode, expected=3 if mode == "ack_loss" else 0)
        if mode == "normal":
            assert outcome["stored_state"] == "SUCCEEDED"
        else:
            assert outcome["error"]["code"] == "attempt_outcome_unconfirmed"
            assert outcome["error"]["budget_consumed"] is True
        value["coordinator_response"] = outcome
        value["worker_evidence"] = worker_evidence(value, slot)
        observation = inspect_dispatch(value)
        recovery = observation["dispatch"]["recovery"]
        assert recovery["status"] == "committed_result"
        run_id = recovery["bindings"]["run_id"]
        inspected = run(
            "inspect-reduction-run", run_id, "--source-evidence", "live-source",
            "--input-root", str(inputs), "--runs", str(runs), guarded=True,
        )
        _check_attempt_recovery(recovery, source, value["preparation"], inspected)
        raw = helper(
            _READ_ARTIFACT, str(runs), inspected["receipt"]["bindings"]["replay_result_sha256"]
        )
        assert raw == value["worker_evidence"]["produced_terminal"]["replay_result"]
        assert raw["execution_status"] == ("incomplete" if slot == 4 else "completed")
        assert inspected["state_audit"]["coverage"]["processed_records"] == through
        assert inspected["state_audit"]["flags"]["checkpoint_used"] is False
        value["recovery"] = observation
        value["independent_inspection"] = inspected
        value["raw_result"] = raw
        if mode == "normal":
            assert outcome["result_sha256"] == run_id
            assert outcome["scope"]["research_attempt_reserved"] is True
            assert outcome["scope"]["native_replayed"] is True
            published = run(
                "read-job-result", value["job_id"], "--jobs", str(catalog), guarded=True
            )
            assert published == inspected["receipt"]
            value["catalog_result"] = published
            value["repeated_terminal"] = unchanged_terminal(value)
        else:
            assert observation["job"]["stored_state"] == "RUNNING"
            assert observation["job"]["state"] == "COORDINATOR_LOST"
            unavailable = run(
                "read-job-result", value["job_id"], "--jobs", str(catalog),
                guarded=True, expected=9,
            )
            assert unavailable["error"]["code"] == "job_conflict"
            value["job_result_unconfirmed"] = unavailable
        assert _tree(inputs / "live-source") == source_before

    duplicate_catalog = root / "duplicate-catalog"
    primary = jobs["pending-cancel"]
    before_duplicate = ledger()
    duplicate = submit(
        "duplicate", 4, 4, jobs_root=duplicate_catalog,
        existing=(primary["preparation"], root / primary["preparation_path"]),
    )
    assert duplicate["job_id"] == primary["job_id"]
    rejected = run(
        "run-job", duplicate["job_id"], "--jobs", str(duplicate_catalog), producer=True
    )
    assert rejected["stored_state"] == "FAILED"
    assert ledger() == before_duplicate
    duplicate["refusal"] = rejected
    duplicate["research_ledger_unchanged"] = True

    for name, slot in (("worker_kill", 6), ("coordinator_kill", 7)):
        value = submit(name, 5, 6)
        directory = controls / name
        entry = ["-c", _COORDINATOR]
        command = (name, str(directory), str(worker), "run-job", value["job_id"],
                   "--jobs", str(catalog))
        process = subprocess.Popen(
            [native, "-I", *entry, *command], cwd=cwd, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, text=True,
        )
        worker_pid = None
        try:
            deadline = time.monotonic() + 25
            gate = directory / "gate.json"
            while time.monotonic() < deadline and not gate.exists():
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    raise AssertionError(
                        "Coordinator exited before actual native gate: " + repr((stdout, stderr))
                    )
                Event().wait(0.02)
            assert gate.exists(), "Actual native result gate timed out"
            ready = json.loads(gate.read_bytes())
            worker_pid = ready["pid"]
            assert ready["job_id"] == value["job_id"]
            # The worker has stopped its heartbeat thread before this gated
            # terminal frame. Wait for every already-delivered heartbeat to
            # commit, so this test kills at a quiescent publication boundary
            # rather than accidentally qualifying SQLite hot-journal recovery.
            expected_sequence = ready["last_heartbeat_sequence"]
            assert expected_sequence >= 1
            before_kill = None
            while time.monotonic() < deadline:
                observed = catalog_view([value["job_id"]])["jobs"][0]["snapshot"]
                assert observed["state"] == "RUNNING"
                sequence = observed["attempt"]["heartbeat_sequence"]
                assert sequence <= expected_sequence
                if sequence == expected_sequence:
                    before_kill = observed
                    break
                if process.poll() is not None:
                    raise AssertionError("Coordinator exited before its final heartbeat commit")
                Event().wait(0.02)
            assert before_kill is not None, "Final native heartbeat commit gate timed out"
            assert before_kill["state"] == "RUNNING"
            assert before_kill["attempt"]["heartbeat_sequence"] == expected_sequence
            assert before_kill["attempt"]["job_attempt_id"] == ready["job_attempt_id"]
            evidence = worker_evidence(value, slot)
            assert evidence["ledger_slot"]["attempt_id"] == ready["research_attempt_id"]
            assert evidence["ledger_slot"]["outcome_id"] is None
            os.kill(worker_pid if name == "worker_kill" else process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=20)
            completed = subprocess.CompletedProcess(
                process.args, process.returncode, stdout, stderr
            )
            if name == "worker_kill":
                finished = capture(native, entry, command, completed, 0)
                assert finished["stored_state"] == "FAILED"
                assert finished["failure"]["worker_exit_code"] == -signal.SIGKILL
                with suppress(ProcessLookupError):
                    os.kill(worker_pid, 0)
                    raise AssertionError("Surviving killed worker was not reaped")
                value["finished"] = finished
            else:
                capture(native, entry, command, completed, -signal.SIGKILL)
                diagnosed = run(
                    "inspect-job", value["job_id"], "--jobs", str(catalog), guarded=True
                )
                assert diagnosed["stored_state"] == "RUNNING"
                assert diagnosed["state"] == "COORDINATOR_LOST"
                value["readonly_orphan"] = diagnosed
                value["explicit_reconciliation"] = run("reconcile-jobs", "--jobs", str(catalog))
                after = run("inspect-job", value["job_id"], "--jobs", str(catalog), guarded=True)
                assert after["stored_state"] == "LOST"
                value["finished"] = after
                old_path = directory / "retired-snapshot.json"
                old_path.write_bytes(_canonical(before_kill))
                stale_before = _tree(runs), _tree(catalog)
                stale = catalog_helper(_STALE, str(catalog), value["job_id"], str(old_path))
                assert stale == {
                    "stale_publication_admission_refused": True, "snapshot_unchanged": True
                }
                assert (_tree(runs), _tree(catalog)) == stale_before
                value["stale_coordinator_admission"] = stale
            value["worker_evidence"] = evidence
            value["actual_kill"] = {
                "target": name, "signal": signal.SIGKILL,
                "coordinator_pid": process.pid, "worker_pid": worker_pid,
                "gate": ready, "persisted_before_kill": before_kill,
                "all_preterminal_heartbeats_committed": True,
                "coordinator_exit_code": process.returncode,
            }
            value["recovery"] = inspect_dispatch(value)
            assert value["recovery"]["dispatch"]["status"] == "reserved_unfinalized"
            assert value["recovery"]["dispatch"]["recovery"]["final_manifest"] is None
            value["repeated_terminal"] = unchanged_terminal(value)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            # A live coordinator has already reaped the killed worker. Only
            # the orphan from coordinator death still needs a separate signal.
            if worker_pid is not None and name == "coordinator_kill":
                with suppress(ProcessLookupError):
                    os.killpg(worker_pid, signal.SIGKILL)

    value = submit("expired_publication", 5, 6, lease=10)
    expired = coordinator(value, "expired_publication")
    assert expired["stored_state"] == "LOST"
    value["finished"] = expired
    value["worker_evidence"] = worker_evidence(value, 8)
    assert value["worker_evidence"]["ledger_slot"]["outcome_id"] is None
    records = [json.loads(line) for line in (
        controls / "expired_publication" / "coordinator-controls.jsonl"
    ).read_bytes().splitlines()]
    assert [row["kind"] for row in records] == [
        "actual_native_result_audited_before_publication_delay_v1"
    ]
    value["expired_publication_control"] = records
    value["recovery"] = inspect_dispatch(value)
    assert value["recovery"]["dispatch"]["status"] == "reserved_unfinalized"
    value["repeated_terminal"] = unchanged_terminal(value)

    final = ledger()
    assert final["budget"] == {"max_attempts": 8, "max_events": 1000, "max_wall_seconds": 60}
    assert [row["attempt_index"] for row in final["slots"]] == list(range(1, 9))
    assert final["slots"][:3] == lifecycle["before"]["slots"]
    assert len({row["attempt_id"] for row in final["slots"]}) == 8
    assert len({row["reservation"]["nonce"] for row in final["slots"]}) == 8
    physical_slots = runs / "slots" / lifecycle["frozen"]["protocol_id"]
    assert sorted(path.name for path in physical_slots.iterdir()) == [
        f"{index:04d}.json" for index in range(1, 9)
    ]
    assert all(
        row["outcome_id"] is None and row["intent_id"] is not None
        for row in final["slots"][5:]
    )
    assert [row["outcome_kind"] for row in final["slots"][3:5]] == [
        "reduction_run_receipt_v1", "reduction_run_receipt_v1"
    ]
    before_exhaustion = _tree(runs)
    exhausted = submit(
        "exhaustion", 4, 4, lease=29,
        existing=(primary["preparation"], root / primary["preparation_path"]),
    )
    stopped = run("run-job", exhausted["job_id"], "--jobs", str(catalog), producer=True)
    assert stopped["stored_state"] == "FAILED"
    assert stopped["failure"]["code"] == "attempt_budget_exhausted"
    assert _tree(runs) == before_exhaustion and ledger() == final
    exhausted["refusal"] = stopped
    exhausted["no_ninth_slot_or_native_run"] = True
    acknowledgment = inspect_dispatch(jobs["filled-cancel-rejected"])
    assert acknowledgment["job"]["stored_state"] == "LOST"
    assert acknowledgment["dispatch"]["status"] == "committed_result"
    assert acknowledgment["dispatch"]["recovery"]["bindings"]["run_id"] == (
        jobs["filled-cancel-rejected"]["recovery"]["dispatch"]["recovery"]["bindings"]["run_id"]
    )
    assert all(_tree(runs).get(relative) == sha for relative, sha in original_records.items())
    assert _tree(inputs / "live-source") == source_before
    return {
        "jobs": jobs, "duplicate_catalog": duplicate, "after": final,
        "catalog": catalog_view(ids), "post_ack_reconciliation_observation": acknowledgment,
        "source_bundle_unchanged": True, "original_records_unchanged": True,
        "new_research_attempts": 5, "actual_managed_native_runs": 5,
        "native_result_returned_for_publication": 3, "actual_new_research_results": 2,
        "consumed_unfinalized_original_slots": [6, 7, 8],
        "scope": {
            "positive_managed_native_execution": True,
            "actual_worker_and_coordinator_sigkill_after_native_before_terminal_ipc": True,
            "expired_publication_refused": True, "retired_coordinator_admission_refused": True,
            "post_commit_research_ack_loss_observed": True,
            "job_ack_recovery_performed": False, "automatic_retry_performed": False,
            "checkpoint_restored": False, "budget_refunded": False,
            "strong_orphan_cleanup_certified": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "verifier-python", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--core-only", action="store_true")
    args = parser.parse_args()
    if args.report.exists() or args.records_dir.exists():
        raise FileExistsError("Native Job qualification destinations must be new")
    native, verifier = str(args.python.absolute()), str(args.verifier_python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    golden_before = _tree(examples / "alpha")
    with _workspace(args.records_dir, args.report) as root:
        inputs, preparations, catalog, cwd, transcripts, controls = (
            root / name for name in (
                "input-root", "preparations", "jobs", "unrelated-cwd", "transcripts", "controls"
            )
        )
        for directory in (inputs, preparations, cwd, transcripts, controls):
            directory.mkdir()
        worker = controls / "native-worker.py"
        worker.write_text(_WORKER)
        calls = []

        def invoke(executable, entry, command=(), *, expected=0):
            completed = subprocess.run(
                [executable, "-I", *entry, *command], cwd=cwd, capture_output=True,
                text=True, check=False, timeout=240,
            )
            return capture(executable, entry, command, completed, expected)

        def capture(executable, entry, command, completed, expected):
            record = {
                "executable": executable, "entry": list(entry), "command": list(command),
                "expected_exit_code": expected, "exit_code": completed.returncode,
                "stdout": completed.stdout, "stderr": completed.stderr,
            }
            calls.append(record)
            (transcripts / f"{len(calls):04d}.json").write_bytes(_canonical(record))
            payload = completed.stdout if expected == 0 else completed.stderr
            unexpected = completed.stderr if expected == 0 else completed.stdout
            if completed.returncode != expected or unexpected:
                raise RuntimeError(
                    f"Native Job command exited {completed.returncode}, expected {expected}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            if expected < 0 and not payload:
                return {"signal_exit_code": completed.returncode}
            return json.loads(payload)

        def run(*command, producer=False, guarded=False, expected=0, jobs=catalog):
            if guarded:
                entry = ["-c", _CATALOG_GUARD_PREFIX + _GUARD + _CATALOG_GUARD_SUFFIX
                         + "\nraise SystemExit(main(sys.argv[1:]))\n"]
                command = ("readonly", str(jobs), *command)
            else:
                entry = ["-m", "tickwitness"]
            return invoke(native if producer else verifier, entry, command, expected=expected)

        def helper(code, *command):
            return invoke(verifier, ["-c", _GUARD + code], ("readonly", *command))

        def catalog_view(ids):
            entry = ["-c", _CATALOG_GUARD_PREFIX + _GUARD + _CATALOG_GUARD_SUFFIX + _CATALOG]
            return invoke(verifier, entry, ("readonly", str(catalog), json.dumps(ids)))

        def catalog_helper(code, *command):
            entry = ["-c", _CATALOG_GUARD_PREFIX + _GUARD + _CATALOG_GUARD_SUFFIX + code]
            return invoke(verifier, entry, ("readonly", str(catalog), *command))

        identities = {
            "producer": invoke(native, ["-c", _RUNTIME]),
            "verifier": invoke(verifier, ["-c", _RUNTIME]),
        }
        for name, requested in (("producer", args.python), ("verifier", args.verifier_python)):
            expected_prefix = requested.absolute().parent.parent.resolve()
            assert Path(identities[name]["prefix"]).resolve() == expected_prefix
            assert expected_prefix != Path(identities[name]["base_prefix"]).resolve()
        assert identities["verifier"]["native_distribution"] is None
        assert identities["producer"]["native_distribution"] == (
            None if args.core_only else "1.231.0"
        )
        (root / "interpreter-identities.json").write_bytes(_canonical(identities))
        confirmation = run(
            "submit-reduction-job", str(root / "missing-preparation"),
            "--expected-preparation-id", "invalid", "--expected-bundle-id", "invalid",
            "--expected-report-id", "invalid", "--source-evidence", "missing-source",
            "--input-root", str(root / "missing-input"), "--runs", str(root / "missing-runs"),
            "--jobs", str(root / "missing-catalog"), "--split", "confirmation", expected=5,
        )
        assert confirmation["error"]["code"] == "confirmation_access_denied"
        assert all(not (root / name).exists() for name in (
            "missing-input", "missing-runs", "missing-catalog"
        ))
        lifecycle = None
        if args.core_only:
            shutil.copytree(examples / "alpha" / "counterexample", inputs / "old-source")
            (inputs / "request.json").write_bytes(_canonical(_request(4, 4)))
            prepared = run(
                "prepare-reduction-input", "old-source", "request.json", "--input-root",
                str(inputs), "--expected-bundle-id", _GOLDEN["bundle_id"],
                "--expected-report-id", _GOLDEN["report_id"], "--output",
                str(preparations / "old-prefix"),
            )
            queued = run(
                "submit-reduction-job", str(preparations / "old-prefix"),
                "--expected-preparation-id", prepared["preparation_id"],
                "--expected-bundle-id", _GOLDEN["bundle_id"], "--expected-report-id",
                _GOLDEN["report_id"], "--source-evidence", "old-source", "--input-root",
                str(inputs), "--runs", str(root / "never-runs"), "--jobs", str(catalog),
                guarded=True,
            )
            before = _tree(inputs), _tree(preparations)
            failed = run("run-job", queued["job_id"], "--jobs", str(catalog), guarded=True)
            assert failed["stored_state"] == "FAILED"
            assert failed["failure"]["code"] == "research_evidence_not_found"
            assert (_tree(inputs), _tree(preparations)) == before
            assert not (root / "never-runs").exists()
            core = {"submission": queued, "finished": failed,
                    "catalog": catalog_view([queued["job_id"]]),
                    "scope": "missing_live_ledger_refusal_only_no_native_source"}
        else:
            core = None
            lifecycle = _bootstrap(run, helper, examples, root, inputs)
            lifecycle.update(
                _managed_lifecycle(
                    run, helper, catalog_helper, invoke, capture, catalog_view, lifecycle,
                    native, root, inputs, preparations, catalog, controls, worker, cwd,
                )
            )
        assert _tree(examples / "alpha") == golden_before
        report = {
            "kind": "installed_managed_native_job_acceptance_v1", "accepted": True,
            "core_only_profile": args.core_only, "interpreter_identities": identities,
            "confirmation": confirmation, "core_refusal": core, "lifecycle": lifecycle,
            "scope": {
                "operation": "execute_reduction_input_v1",
                "restart_mode": "frozen_origin_new_attempt_only_v1",
                "checkpoint_supported": False, "automatic_retry": False,
                "job_ack_recovery": False, "strong_cancellation": False,
                "external_human_attempts": 0, "external_human_gate": "PENDING",
            },
        }
        inner = root / "native-jobs-smoke" / "report.json"
        inner.parent.mkdir()
        inner.write_bytes(_canonical(report))
        shutil.copytree(root, args.records_dir)
        (args.records_dir / "artifact-files.json").write_bytes(_canonical(_tree(args.records_dir)))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
