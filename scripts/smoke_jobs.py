#!/usr/bin/env python3
"""Qualify managed read-only Jobs using installed core code and real processes.

Research runs are reused from an already qualified comparison artifact. Fault
workers are declared trusted transport fixtures; they never invent native results.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

_GUARD = """
import importlib.abc
from importlib import metadata
import json, os, socket, sqlite3, sys
from pathlib import Path
from urllib.parse import unquote
try:
    metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Managed comparison qualification requires core-only runtime')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Coordinator cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_confirmation import (
    LocalConfirmationRegistry, LocalConfirmationExposureLedger,
)
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry
from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args, **kwargs):
    raise AssertionError('Managed comparison cannot write research, execute native or use network')
socket.socket = forbidden
socket.create_connection = forbidden
BoundedReplayAdapter.__init__ = forbidden
SubprocessReplayAdapter.__init__ = forbidden
for repository in (LocalCampaignBudgetStore, LocalExecutableProtocolRegistry,
                   LocalDatasetStore, LocalProtocolRegistry,
                   LocalConfirmationRegistry, LocalConfirmationExposureLedger,
                   LocalSearchCampaignStore, LocalReductionCampaignStore,
                   LocalSearchFindingRegistry, LocalSearchPlanRegistry):
    repository.__init__ = forbidden
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
original_ledger_init = LocalAttemptLedger.__init__
def readonly_ledger_init(self, *args, **kwargs):
    if kwargs.get('create', True) is not False:
        forbidden()
    return original_ledger_init(self, *args, **kwargs)
LocalAttemptLedger.__init__ = readonly_ledger_init
original_sqlite_connect = sqlite3.connect
def guard_catalog(catalog):
    allowed = os.path.abspath(str(Path(catalog) / 'catalog.sqlite3'))
    def connect(database, *args, **kwargs):
        value = str(database)
        if value.startswith('file:'):
            value = unquote(value[5:].split('?', 1)[0])
        if os.path.abspath(value) != allowed:
            forbidden()
        return original_sqlite_connect(database, *args, **kwargs)
    sqlite3.connect = connect
"""
_RUNTIME = """
import json, sys
from importlib import metadata
try:
    native = metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    native = None
print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,
                  'base_prefix':sys.base_prefix,'native_distribution':native,
                  'project_version':metadata.version('tickwitness')},sort_keys=True))
"""
_PRE_IO = """
from types import SimpleNamespace
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.cli_jobs import execute
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
class Unreadable:
    def __getattribute__(self, name):
        raise AssertionError('Confirmation accessed locator/spec: ' + name)
SqliteJobStore.__init__ = forbidden
try:
    execute(SimpleNamespace(command='submit-comparison-job',split='confirmation',
                            run_id=Unreadable(),input_root=Unreadable(),runs=Unreadable(),
                            source_evidence=Unreadable(),expected_bundle_id=Unreadable(),
                            expected_report_id=Unreadable(),lease_seconds=Unreadable(),
                            jobs=Unreadable()))
except ConfirmationAccessDenied:
    print(json.dumps({'confirmation_rejected_before_spec_locator_catalog_io':True}))
else:
    raise AssertionError('Confirmation submission was accepted')
"""
_CATALOG = """
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
store = SqliteJobStore(Path(sys.argv[1]),create=False)
ids = json.loads(sys.argv[2])
records = []
for job_id in ids:
    result = store.result(job_id)
    records.append({'snapshot':store.get(job_id),'events':store.events(job_id,limit=1000),
                    'result':None if result is None else json.loads(result)})
print(json.dumps({'jobs':records,'coordinator_active':store.coordinator_active()},
                 sort_keys=True,separators=(',',':')))
"""
_LEDGER = """
from tickwitness.application.search_evidence import verify_search_package
from tickwitness.domain.evidence.run_records import canonical,digest
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import (
    load_search_finding_protocol,
)
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle
source=read_search_evidence_bundle(Path(sys.argv[2]))
verify_search_package(source,expected_bundle_id=sys.argv[4])
authority=load_search_finding_protocol(source.artifacts['finding_protocol'])
protocol=load_executable_protocol(canonical(authority.plan.document['protocol']))
ledger=LocalAttemptLedger(Path(sys.argv[3]),create=False)
slots=[]
for reservation in ledger.list_reservations(protocol):
    intent=ledger.get_intent(reservation.attempt_id)
    outcome=ledger.get_outcome(reservation.attempt_id)
    slots.append({'attempt_id':reservation.attempt_id,'attempt_index':reservation.attempt_index,
                  'reservation':reservation.document,
                  'intent_id':None if intent is None else digest(intent),
                  'outcome_id':None if outcome is None else digest(outcome),
                  'outcome_kind':None if outcome is None else json.loads(outcome)['kind']})
print(json.dumps({'protocol_id':protocol.protocol_id,'budget':protocol.document['budget'],
                  'slots':slots},sort_keys=True,separators=(',',':')))
"""
_WORKER = """
import json,os,sys
from pathlib import Path
from threading import Event
request=json.loads(sys.stdin.buffer.readline())
def emit(kind,sequence,**payload):
    frame={key:request[key] for key in
           ('job_id','coordinator_id','job_attempt_id','lease_token')}
    frame.update(kind=kind,schema_version=1,sequence=sequence,**payload)
    raw=json.dumps(frame,sort_keys=True,separators=(',',':'))+'\\n'
    with Path(sys.argv[2]).open('a') as stream:
        stream.write(raw)
    sys.stdout.write(raw);sys.stdout.flush()
"""
_COORDINATOR = """
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
row=run_job(SqliteJobStore(Path(sys.argv[1]),create=False),sys.argv[2],
            _worker_command=(sys.executable,'-I','-B',sys.argv[3],sys.argv[4],sys.argv[5]))
print(json.dumps(row,sort_keys=True,separators=(',',':')))
"""
_CONTROL = """
import signal,subprocess,time
from contextlib import suppress
from threading import Event
from tickwitness.application.jobs import JobConflictError,job_view
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
store=SqliteJobStore(Path(sys.argv[1]),create=False)
job_id,mode=sys.argv[2],sys.argv[3]
controls=Path(sys.argv[4]);controls.mkdir(parents=True,exist_ok=True)
definition=json.loads(Path(sys.argv[5]).read_text())
worker=controls/'worker.py';worker.write_text(definition['worker'])
gate,frames=controls/'gate.json',controls/'worker-ipc.jsonl'
command=(sys.executable,'-I','-B',str(worker),str(gate),str(frames))
if mode not in ('worker_kill','coordinator_kill'):
    started=time.monotonic_ns()
    row=run_job(store,job_id,_worker_command=command)
    result={'mode':mode,'snapshot':row,'elapsed_monotonic_ns':time.monotonic_ns()-started,
            'events':store.events(job_id,limit=1000)}
    if gate.exists():
        pid=json.loads(gate.read_text())['pid']
        try:os.kill(pid,0)
        except ProcessLookupError:result['worker_reaped']=True
        else:raise AssertionError('Live coordinator did not reap its worker')
    print(json.dumps(result,sort_keys=True,separators=(',',':')))
    raise SystemExit(0)
process=subprocess.Popen([sys.executable,'-I','-B','-c',definition['coordinator'],
                          sys.argv[1],job_id,str(worker),str(gate),str(frames)],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
pid=None
try:
    deadline=time.monotonic()+15
    before=None
    while time.monotonic()<deadline:
        if gate.exists():
            row=store.get(job_id)
            if row['state']=='RUNNING' and row['attempt']['heartbeat_sequence']>=1:
                before=row;break
        if process.poll() is not None:
            out,err=process.communicate()
            raise AssertionError('Coordinator exited before gate: '+repr((out,err)))
        Event().wait(0.02)
    if before is None:raise AssertionError('Persisted heartbeat gate timed out')
    ready=json.loads(gate.read_text());pid=ready['pid']
    assert ready['job_id']==job_id
    if mode=='worker_kill':
        os.kill(pid,signal.SIGKILL)
        out,err=process.communicate(timeout=15)
        assert process.returncode==0 and not err
        row=json.loads(out)
        assert row['state']=='FAILED' and row['failure']['worker_exit_code']==-signal.SIGKILL
        try:os.kill(pid,0)
        except ProcessLookupError:reaped=True
        else:raise AssertionError('SIGKILL worker was not reaped')
        result={'mode':mode,'before':before,'snapshot':row,'worker_pid':pid,
                'coordinator_pid':process.pid,'coordinator_exit_code':process.returncode,
                'worker_reaped':reaped,'signal_sent':'SIGKILL','stderr':err.decode()}
    else:
        os.kill(process.pid,signal.SIGKILL)
        out,err=process.communicate(timeout=15)
        assert process.returncode==-signal.SIGKILL
        row=store.get(job_id)
        assert row==before and row['state']=='RUNNING' and not store.coordinator_active()
        view=job_view(row,now_ns=time.time_ns(),coordinator_active=False)
        assert view['state']=='COORDINATOR_LOST' and view['stored_state']=='RUNNING'
        assert store.get(job_id)==before
        result={'mode':mode,'before':before,'snapshot':row,'effective_view':view,
                'worker_pid':pid,'coordinator_pid':process.pid,
                'coordinator_exit_code':process.returncode,'signal_sent':'SIGKILL',
                'readonly_query_preserved_snapshot':True,
                'orphan_cleanup_signal_sent':True,'stderr':err.decode()}
    result['events']=store.events(job_id,limit=1000)
    print(json.dumps(result,sort_keys=True,separators=(',',':')))
finally:
    if pid is not None:
        with suppress(ProcessLookupError):os.killpg(pid,signal.SIGKILL)
    if process.poll() is None:process.kill()
    process.communicate(timeout=15)
"""
_STALE = """
import time
from tickwitness.application.jobs import JobConflictError
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
store=SqliteJobStore(Path(sys.argv[1]),create=False)
old=json.loads(Path(sys.argv[2]).read_text())['before']
before=store.get(old['job_id']);attempt=old['attempt']
with store.coordinator():
    try:
        store.heartbeat(old['job_id'],expected_version=before['version'],
                        coordinator_id=attempt['coordinator_id'],
                        job_attempt_id=attempt['job_attempt_id'],lease_token=attempt['lease_token'],
                        sequence=attempt['heartbeat_sequence']+1,now_ns=time.time_ns())
    except JobConflictError as error:
        code=error.code
    else:raise AssertionError('Stale credentials mutated an orphan terminal')
after=store.get(old['job_id'])
assert before==after and after['state']=='LOST' and store.result(old['job_id']) is None
print(json.dumps({'code':code,'before':before,'after':after,'new_attempts':0},
                 sort_keys=True,separators=(',',':')))
"""
_ACK_LOSS = """
from tickwitness.application.jobs import JobStoreError
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
store=SqliteJobStore(Path(sys.argv[1]),create=False)
actual=store.complete
def lost_ack(*args,**kwargs):
    actual(*args,**kwargs)
    raise JobStoreError('Controlled acknowledgement loss after actual commit')
store.complete=lost_ack
try:run_job(store,sys.argv[2])
except JobStoreError as error:code=error.code
else:raise AssertionError('Post-commit acknowledgement uncertainty was hidden')
row=store.get(sys.argv[2])
assert (row['state']=='SUCCEEDED' and row['failure'] is None
        and store.result(sys.argv[2]) is not None)
print(json.dumps({'acknowledgement_unconfirmed':True,'code':code,'snapshot':row,
                  'events':store.events(sys.argv[2],limit=1000)},
                 sort_keys=True,separators=(',',':')))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AssertionError("Job qualification workspace cannot contain symlinks")
        if path.is_file():
            result[str(path.relative_to(root))] = _sha(path.read_bytes())
    return result


@contextmanager
def _workspace(records: Path, report: Path) -> Iterator[Path]:
    with TemporaryDirectory(prefix="tickwitness-jobs-") as temporary:
        root = Path(temporary)
        try:
            yield root
        except BaseException as error:
            for accepted in (
                report,
                root / "jobs-smoke" / "report.json",
                records / "jobs-smoke" / "report.json",
            ):
                with suppress(OSError):
                    accepted.unlink(missing_ok=True)
            try:
                shutil.copytree(root, records, dirs_exist_ok=True)
                (records / "diagnostic-capture.json").write_bytes(
                    _canonical(
                        {
                            "kind": "jobs_workspace_diagnostics_v1",
                            "accepted": False,
                            "exception_type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                )
            except Exception as diagnostic_error:
                print("Failed to preserve diagnostics: " + str(diagnostic_error), file=sys.stderr)
            raise


def _view(row: dict, *, state: str) -> None:
    assert row["kind"] == "job_view_v1" and row["schema_version"] == 1
    assert row["stored_state"] == row["state"] == state
    scope = row["scope"]
    assert scope["operation"] == "compare_reduction_run_v1"
    assert all(value is False for key, value in scope.items() if key != "operation")
    if row["attempt"] is not None:
        assert "lease_token" not in row["attempt"] and "nonce" not in row["attempt"]
        assert row["attempt"]["attempt_number"] == 1


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "source-report", "source-records", "report", "records-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--core-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.records_dir.exists() or arguments.report.exists():
        raise FileExistsError("Job qualification destinations must be new")
    verifier = str(arguments.python.absolute())
    original_tree = _tree(arguments.source_records)
    original_report = arguments.source_report.read_bytes()
    source = json.loads(original_report)
    assert source["kind"] == "installed_reduction_comparison_acceptance_v1"
    assert source["accepted"] is True and source["core_only_profile"] is arguments.core_only
    assert source["native_execution"] is False
    assert source["upstream_native_evidence_reused"] is (not arguments.core_only)
    assert (
        original_report
        == (arguments.source_records / "reduction-comparison-smoke" / "report.json").read_bytes()
    )
    assert {name: sha for name, sha in original_tree.items() if name != "artifact-files.json"} == (
        json.loads((arguments.source_records / "artifact-files.json").read_bytes())
    )
    with _workspace(arguments.records_dir, arguments.report) as root:
        inputs, cwd, transcripts, controls = (
            root / name for name in ("input-root", "unrelated-cwd", "transcripts", "controls")
        )
        for directory in (inputs, cwd, transcripts, controls):
            directory.mkdir()
        upstream = inputs / "upstream"
        shutil.copytree(arguments.source_records, upstream)
        (root / "source-comparison-report.json").write_bytes(original_report)
        protected = _tree(upstream)
        assert protected == original_tree
        catalog = root / "job-catalog"
        calls = []

        def invoke(entry, command, *, expected=0):
            completed = subprocess.run(
                [verifier, "-I", "-B", *entry, *command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            record = {
                "executable": verifier,
                "entry": entry,
                "command": list(command),
                "exit_code": completed.returncode,
                "expected_exit_code": expected,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            calls.append(record)
            (transcripts / f"{len(calls):04d}.json").write_bytes(_canonical(record))
            assert len(completed.stdout.encode()) <= 32 * 1024 * 1024
            assert len(completed.stderr.encode()) <= 64 * 1024
            if completed.returncode != expected or (
                completed.stderr if expected == 0 else completed.stdout
            ):
                raise RuntimeError(
                    f"Installed Job command exited {completed.returncode}, expected {expected}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            assert _tree(upstream) == protected
            return json.loads(completed.stdout if expected == 0 else completed.stderr)

        def run(*command, expected=0):
            entry = _GUARD + (
                "\nguard_catalog(Path(sys.argv[sys.argv.index('--jobs')+1])); "
                "raise SystemExit(main(sys.argv[1:]))\n"
            )
            return invoke(["-c", entry], command, expected=expected)

        def helper(code, *command):
            return invoke(["-c", _GUARD + "\nguard_catalog(Path(sys.argv[1]))\n" + code], command)

        runtime = invoke(["-c", _RUNTIME], ())
        prefix = str(arguments.python.absolute().parent.parent.resolve())
        assert str(Path(runtime["prefix"]).resolve()) == prefix
        assert Path(runtime["prefix"]).resolve() != Path(runtime["base_prefix"]).resolve()
        assert runtime["native_distribution"] is None and runtime["project_version"] == "0.2.0.dev0"
        identity = {
            "requested_executable": verifier,
            "requested_venv_prefix_resolved": prefix,
            "runtime": runtime,
        }
        (root / "interpreter-identity.json").write_bytes(_canonical(identity))
        pre_io = helper(_PRE_IO, str(root / "never-catalog"))
        assert pre_io == {"confirmation_rejected_before_spec_locator_catalog_io": True}
        refused = run(
            "submit-comparison-job",
            "invalid",
            "--input-root",
            str(root / "never-input"),
            "--source-evidence",
            "missing-source",
            "--runs",
            str(root / "never-runs"),
            "--expected-bundle-id",
            "invalid",
            "--expected-report-id",
            "invalid",
            "--split",
            "confirmation",
            "--jobs",
            str(root / "never-catalog"),
            expected=5,
        )
        assert refused["error"]["code"] == "confirmation_access_denied"
        missing = run("inspect-job", "0" * 64, "--jobs", str(root / "never-catalog"), expected=4)
        assert missing["error"]["code"] == "job_not_found"
        assert not (root / "never-catalog").exists() and not (root / "never-input").exists()

        research = upstream / source["upstream_records_path"]
        assert research.resolve().is_relative_to(upstream.resolve())
        research_input, research_runs = research / "input-root", research / "live-runs"
        if arguments.core_only:
            pins = source["scope"]
            assert pins["authority"] == "original_reduced_witness_review_v1"
            run_id, source_name = "0" * 64, "old-exhausted-source"
            bundle = "2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369"
            report_pin = "398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb"
            research_runs = root / "never-research-runs"
            before = None
        else:
            bundle = source["lifecycle"]["source_bundle_id"]
            report_pin = source["lifecycle"]["source_report_id"]
            run_id = source["lifecycle"]["repeated_best"]["report"]["bindings"]["reduced"]["run_id"]
            source_name = "live-source"
            before = helper(
                _LEDGER,
                str(catalog),
                str(research_input / source_name),
                str(research_runs),
                bundle,
            )
            assert before == source["lifecycle"]["after"]
            assert [row["attempt_index"] for row in before["slots"]] == list(range(1, 12))

        jobs = {}

        def submit(name, lease, *, selected=run_id):
            queued = run(
                "submit-comparison-job",
                selected,
                "--input-root",
                str(research_input),
                "--source-evidence",
                source_name,
                "--runs",
                str(research_runs),
                "--expected-bundle-id",
                bundle,
                "--expected-report-id",
                report_pin,
                "--lease-seconds",
                str(lease),
                "--jobs",
                str(catalog),
            )
            _view(queued, state="QUEUED")
            assert queued["version"] == 1 and queued["attempt"] is None
            jobs[name] = {"submission": queued, "job_id": queued["job_id"], "lease_seconds": lease}
            return queued["job_id"]

        main_job = submit("main", 30)
        no_result = run("read-job-result", main_job, "--jobs", str(catalog), expected=9)
        assert no_result["error"]["code"] == "job_conflict"
        finished = run("run-job", main_job, "--jobs", str(catalog))
        _view(finished, state="FAILED" if arguments.core_only else "SUCCEEDED")
        assert finished["attempt"]["heartbeat_sequence"] >= 2
        jobs["main"]["finished"] = finished
        repeated = run("run-job", main_job, "--jobs", str(catalog))
        assert repeated == finished
        resubmitted = run(
            "submit-comparison-job",
            run_id,
            "--input-root",
            str(research_input),
            "--source-evidence",
            source_name,
            "--runs",
            str(research_runs),
            "--expected-bundle-id",
            bundle,
            "--expected-report-id",
            report_pin,
            "--lease-seconds",
            "30",
            "--jobs",
            str(catalog),
        )
        assert resubmitted == finished
        jobs["main"]["idempotent_resubmission"] = resubmitted
        observed = run("inspect-job", main_job, "--jobs", str(catalog), "--events")
        assert observed["event_limit"] == 100 and observed["complete_history_claimed"] is False
        assert observed["events"] and all("snapshot" not in item for item in observed["events"])
        jobs["main"]["inspection"] = observed
        positives = None
        if arguments.core_only:
            assert finished["result_sha256"] is None and finished["failure"] is not None
            absent = run("read-job-result", main_job, "--jobs", str(catalog), expected=9)
            assert absent["error"]["code"] == "job_conflict"
        else:
            result = run("read-job-result", main_job, "--jobs", str(catalog))
            assert result == source["lifecycle"]["repeated_best"]
            assert calls[-1]["stdout"] == _canonical(result).decode()
            assert finished["result_sha256"] == _sha(_canonical(result))
            (root / "main-result.json").write_bytes(_canonical(result))
            unknown_export = source["lifecycle"]["main"][6]["export"]
            unknown_run = unknown_export["report"]["bindings"]["reduced"]["run_id"]
            unknown_job = submit("unknown", 30, selected=unknown_run)
            unknown = run("run-job", unknown_job, "--jobs", str(catalog))
            _view(unknown, state="SUCCEEDED")
            unknown_result = run("read-job-result", unknown_job, "--jobs", str(catalog))
            assert unknown_result == unknown_export
            assert unknown_result["report"]["both_false_witnesses"] is None
            assert unknown_result["report"]["reduced_assessment"]["outcome"] == "NOT_EVALUABLE"
            unknown_assessment = unknown_result["report"]["reduced_assessment"]
            unknown_observation = unknown_assessment["criterion_observation"]
            assert unknown_observation["truth"] is None and unknown_observation["value"] is None
            jobs["unknown"]["finished"] = unknown
            (root / "unknown-result.json").write_bytes(_canonical(unknown_result))
            positives = {"best": result, "unknown": unknown_result}

        coordinator_code = _GUARD + "\nguard_catalog(Path(sys.argv[1]))\n" + _COORDINATOR

        def control(name, lease, body):
            job_id = submit(name, lease)
            directory = controls / name
            definition = controls / (name + "-definition.json")
            definition.write_bytes(
                _canonical({"worker": _WORKER + body, "coordinator": coordinator_code})
            )
            outcome = helper(
                _CONTROL,
                str(catalog),
                job_id,
                name,
                str(directory),
                str(definition),
            )
            path = controls / (name + "-outcome.json")
            path.write_bytes(_canonical(outcome))
            jobs[name]["control"] = outcome
            return job_id, outcome, path

        gated = (
            "emit('job_heartbeat_v1',1)\n"
            "Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),"
            "'job_id':request['job_id']}))\n"
            "Event().wait(30)\n"
        )
        _, killed, _ = control("worker_kill", 10, gated)
        assert killed["worker_reaped"] is True
        assert killed["snapshot"]["state"] == "FAILED"
        assert killed["snapshot"]["failure"]["worker_exit_code"] == -9
        owner_job, orphan, orphan_path = control("coordinator_kill", 20, gated)
        assert orphan["coordinator_exit_code"] == -9
        assert orphan["effective_view"]["state"] == "COORDINATOR_LOST"
        catalog_before_query = _tree(catalog)
        orphan_view = run("inspect-job", owner_job, "--jobs", str(catalog), "--events")
        assert orphan_view["stored_state"] == "RUNNING"
        assert orphan_view["state"] == "COORDINATOR_LOST"
        assert _tree(catalog) == catalog_before_query
        reconciliation = run("reconcile-jobs", "--jobs", str(catalog))
        assert len(reconciliation["jobs"]) == 1
        _view(reconciliation["jobs"][0], state="LOST")
        assert reconciliation["jobs"][0]["failure"]["code"] == "coordinator_lost"
        assert all(
            reconciliation[key] is False
            for key in (
                "worker_started",
                "research_attempt_reserved",
                "automatic_retry_performed",
                "checkpoint_restored",
            )
        )
        stale = helper(_STALE, str(catalog), str(orphan_path))
        assert stale["code"] == "job_conflict" and stale["before"] == stale["after"]
        jobs["coordinator_kill"]["reconciliation"] = reconciliation
        jobs["coordinator_kill"]["stale_credentials"] = stale
        stopped = run("run-job", owner_job, "--jobs", str(catalog))
        assert stopped == reconciliation["jobs"][0]
        jobs["coordinator_kill"]["terminal_run_did_not_resume"] = stopped
        _, pulsed, _ = control(
            "heartbeat",
            2,
            "for sequence in range(1,9):\n"
            "    emit('job_heartbeat_v1',sequence)\n    Event().wait(0.35)\n"
            "emit('job_failure_v1',9,failure={'code':'controlled_failure','message':'pulse train',"
            "'worker_exit_code':7})\nraise SystemExit(7)\n",
        )
        assert pulsed["elapsed_monotonic_ns"] >= 2_000_000_000
        assert pulsed["snapshot"]["state"] == "FAILED"
        assert pulsed["snapshot"]["failure"]["code"] == "controlled_failure"
        assert pulsed["snapshot"]["attempt"]["heartbeat_sequence"] == 9
        _, expired, _ = control(
            "silent_expiry",
            3,
            "Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid()}))\nEvent().wait(30)\n",
        )
        assert expired["snapshot"]["state"] == "LOST"
        assert expired["snapshot"]["failure"]["code"] == "lease_expired"
        assert expired["worker_reaped"] is True

        if not arguments.core_only:
            forged = deepcopy(positives["best"])
            assessment = forged["report"]["reduced_assessment"]
            assessment["outcome"] = "NOT_PRESERVED"
            assessment["criterion_observation"].update(value="-2", truth=True)
            forged["report"]["both_false_witnesses"] = False
            forged["report"]["bindings"]["reduced"]["assessment_id"] = _sha(_canonical(assessment))
            forged["comparison_id"] = _sha(_canonical(forged["report"]))
            (root / "forged-worker-export.json").write_bytes(_canonical(forged))
            _, rejected, _ = control(
                "forged_result",
                15,
                f"emit('job_result_v1',1,export=json.loads({_canonical(forged).decode()!r}))\n",
            )
            assert rejected["snapshot"]["state"] == "FAILED"
            assert rejected["snapshot"]["result_sha256"] is None
            assert rejected["snapshot"]["failure"]["worker_exit_code"] == 0
            diagnostic = rejected["snapshot"]["failure"]
            assert "Coordinator re-audit rejected result" in diagnostic["message"]
            ack_job = submit("postcommit_acknowledgement_loss", 16)
            uncertain = helper(_ACK_LOSS, str(catalog), ack_job)
            assert uncertain["acknowledgement_unconfirmed"] is True
            assert uncertain["snapshot"]["state"] == "SUCCEEDED"
            resolved = run("inspect-job", ack_job, "--jobs", str(catalog))
            _view(resolved, state="SUCCEEDED")
            ack_result = run("read-job-result", ack_job, "--jobs", str(catalog))
            assert ack_result == positives["best"]
            assert run("run-job", ack_job, "--jobs", str(catalog)) == resolved
            jobs["postcommit_acknowledgement_loss"]["uncertainty"] = uncertain
            jobs["postcommit_acknowledgement_loss"]["resolved"] = resolved

        catalog_state = helper(
            _CATALOG,
            str(catalog),
            json.dumps([item["job_id"] for item in jobs.values()]),
        )
        assert catalog_state["coordinator_active"] is False
        assert len(catalog_state["jobs"]) == len(jobs)
        for record in catalog_state["jobs"]:
            snapshot = record["snapshot"]
            assert snapshot["state"] in ("SUCCEEDED", "FAILED", "LOST")
            assert snapshot["attempt"]["attempt_number"] == 1
            assert [event["aggregate_version"] for event in record["events"]] == list(
                range(1, snapshot["version"] + 1)
            )
            assert (record["result"] is not None) is (snapshot["state"] == "SUCCEEDED")
        (root / "catalog-records.json").write_bytes(_canonical(catalog_state))
        assert not (catalog / "catalog.sqlite3-wal").exists()
        assert not (catalog / "catalog.sqlite3-shm").exists()
        after = None
        if not arguments.core_only:
            after = helper(
                _LEDGER,
                str(catalog),
                str(research_input / source_name),
                str(research_runs),
                bundle,
            )
            assert after == before and len(after["slots"]) == 11
        assert _tree(upstream) == protected and _tree(arguments.source_records) == original_tree
        assert arguments.source_report.read_bytes() == original_report
        report = {
            "kind": "installed_jobs_acceptance_v1",
            "accepted": True,
            "core_only_profile": arguments.core_only,
            "interpreter_identity": identity,
            "pre_io": pre_io,
            "confirmation_refusal": refused,
            "missing_catalog_refusal": missing,
            "source_comparison_report_sha256": _sha(original_report),
            "source_comparison_records_manifest_sha256": original_tree["artifact-files.json"],
            "source_records_path": "input-root/upstream",
            "source_report_path": "source-comparison-report.json",
            "source_bytes_unchanged": True,
            "jobs": jobs,
            "catalog": catalog_state,
            "managed_job_count": len(jobs),
            "research_before": before,
            "research_after": after,
            "comparison_positive_results": positives,
            "native_execution": False,
            "native_replayed": False,
            "research_attempts_added": 0,
            "new_native_runs": 0,
            "actual_native_source_records": not arguments.core_only,
            "signals": {
                "worker_sigkill_after_persisted_heartbeat": True,
                "coordinator_sigkill_after_persisted_heartbeat": True,
                "coordinator_process_reaped": True,
                "worker_reaped_by_live_coordinator": True,
                "orphan_cleanup_signal_only_no_strong_cleanup_certification": True,
                "readonly_orphan_diagnosis_and_explicit_lost_reconciliation": True,
            },
            "guard": {
                "scope": "coordinator_and_qualification_helpers_v1",
                "core_only": True,
                "research_writer_ports_forbidden_in_coordinator": True,
                "old_research_store_construction_forbidden": True,
                "network_forbidden": True,
                "sqlite_allowed_only_for_job_catalog": True,
                "trusted_job_worker_spawn_allowed": True,
            },
            "scope": {
                "operation": "compare_reduction_run_v1",
                "job_attempt_is_research_attempt": False,
                "native_research_execution_supported": False,
                "automatic_retry_supported": False,
                "checkpoint_resume_verified": False,
                "strong_cancellation_verified": False,
                "hard_job_deadline_verified": False,
                "physical_crash_durability_verified": False,
                "global_history_authenticated": False,
                "human_domain_approval_verified": False,
            },
            "external_attempts": 0,
            "external_attempt_gate": "PENDING",
        }
        inner = root / "jobs-smoke" / "report.json"
        inner.parent.mkdir()
        inner.write_bytes(_canonical(report))
        shutil.copytree(root, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(_tree(arguments.records_dir))
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
