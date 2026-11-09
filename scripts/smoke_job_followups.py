#!/usr/bin/env python3
"""Qualify explicit native retry and core-only ACK recovery on one five-slot protocol.

The protocol is newly frozen before its baseline. Existing five/eight/eleven-slot
qualifications and their golden evidence are not enlarged, reset or imported.
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

from smoke_native_jobs import _RUNTIME, _WORKER, _bootstrap
from smoke_reduction_execution import (
    _GOLDEN,
    _GUARD,
    _LEDGER_VIEW,
    _READ_ARTIFACT,
    _canonical,
    _request,
    _sha,
    _tree,
)

_GUARD_PREFIX = """
import sqlite3
actual_sqlite_connect=sqlite3.connect
"""
_GUARD_SUFFIX = """
import os
from urllib.parse import unquote
catalog=Path(sys.argv.pop(1))
allowed=os.path.abspath(str(catalog/'catalog.sqlite3'))
def catalog_connect(database,*args,**kwargs):
    locator=str(database)
    value=unquote(locator[5:].split('?',1)[0]) if locator.startswith('file:') else locator
    if os.path.abspath(value)!=allowed:forbidden()
    command=sys.argv[1] if len(sys.argv)>1 else ''
    writers={'submit-reduction-job','retry-reduction-job','recover-reduction-job','run-job',
             'reconcile-jobs'}
    if command not in writers and 'mode=ro' not in locator:forbidden()
    return actual_sqlite_connect(database,*args,**kwargs)
sqlite3.connect=catalog_connect
"""
_NATIVE_CONTROL = """
import hashlib,json,os,sys,time
from pathlib import Path
from threading import Event
from tickwitness import cli_jobs
from tickwitness.cli import main
from tickwitness.infrastructure import job_reduction
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
mode,root,worker=sys.argv.pop(1),Path(sys.argv.pop(1)),sys.argv.pop(1)
root.mkdir(parents=True,exist_ok=True)
job_id=sys.argv[2]
def record(value):
    with (root/'coordinator-controls.jsonl').open('a') as stream:
        stream.write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n')
publication=job_reduction.publish_reduction_execution
if mode=='retry_ack_loss':
    def gated(execution,reservation,audited,*,ledger,fence):
        ready={'kind':'actual_retry_native_verified_before_research_publication_v1',
               'pid':os.getpid(),'job_id':job_id,'research_attempt_id':reservation.attempt_id,
               'outcome_id':audited.receipt.run_id}
        pending=root/'publication-gate.pending'
        pending.write_text(json.dumps(ready,sort_keys=True,separators=(',',':')))
        record(ready)
        os.replace(pending,root/'publication-gate.json')
        deadline=time.monotonic()+20
        while not (root/'release-publication').exists() and time.monotonic()<deadline:
            Event().wait(0.02)
        if not (root/'release-publication').exists():raise RuntimeError('Release gate timed out')
        return publication(execution,reservation,audited,ledger=ledger,fence=fence)
    job_reduction.publish_reduction_execution=gated
original_publish=LocalAttemptLedger.publish
def publish(self,reservation,raw,*,artifacts=()):
    record({'kind':'research_publish_invoked_v1','attempt_id':reservation.attempt_id})
    committed=original_publish(self,reservation,raw,artifacts=artifacts)
    record({'kind':'actual_research_outcome_committed_v1','attempt_id':reservation.attempt_id,
            'outcome_id':committed,'outcome_sha256':hashlib.sha256(raw).hexdigest()})
    if mode=='retry_ack_loss':raise OSError('Injected ACK loss after actual retry research commit')
    return committed
LocalAttemptLedger.publish=publish
original_run=cli_jobs.run_job
def managed(store,selected):
    worker_mode='worker_kill' if mode=='worker_kill' else 'normal'
    return original_run(store,selected,_worker_command=(sys.executable,'-I','-B',worker,
                                                      worker_mode,str(root)))
cli_jobs.run_job=managed
raise SystemExit(main(sys.argv[1:]))
"""
_ACK_CONTROL = """
import hashlib,json,os,time
from threading import Event
from tickwitness.application.jobs import JobStoreError
from tickwitness.infrastructure import job_supervisor
mode,root=sys.argv.pop(1),Path(sys.argv.pop(1))
root.mkdir(parents=True,exist_ok=True)
original_complete=job_supervisor._complete_followup
def record(value):
    with (root/'ack-controls.jsonl').open('a') as stream:
        stream.write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n')
def complete(store,row,spec,dispatch,outcome,action,window):
    if action!='acknowledged_committed':raise AssertionError('ACK control cannot execute native')
    ready={'kind':'core_verified_committed_outcome_before_catalog_completion_v1',
           'pid':os.getpid(),'job_id':spec.spec_id,'dispatch_job_id':dispatch.spec_id,
           'outcome_id':hashlib.sha256(outcome).hexdigest(),'action':action,
           'snapshot':row}
    record(ready)
    if mode=='kill_before_complete':
        pending=root/'ack-gate.pending'
        pending.write_text(json.dumps(ready,sort_keys=True,separators=(',',':')))
        os.replace(pending,root/'ack-gate.json')
        Event().wait(55)
        raise AssertionError('Kill gate did not kill the coordinator')
    returned=original_complete(store,row,spec,dispatch,outcome,action,window)
    record({'kind':'actual_ack_catalog_completion_committed_v1','job_id':spec.spec_id,
            'snapshot':returned})
    if mode=='ack_loss':raise JobStoreError('Injected ACK loss after actual ACK Catalog commit')
    return returned
job_supervisor._complete_followup=complete
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
_STALE_ACK = """
from tickwitness.application.jobs import JobConflictError
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
store=SqliteJobStore(catalog,create=False)
old=json.loads(Path(sys.argv[1]).read_bytes())
raw=Path(sys.argv[2]).read_bytes()
job_id=old['job_id'];before=store.get(job_id);attempt=old['attempt']
try:
    with store.coordinator():
        store.complete(job_id,raw,expected_version=before['version'],
            coordinator_id=attempt['coordinator_id'],job_attempt_id=attempt['job_attempt_id'],
            lease_token=attempt['lease_token'],now_ns=__import__('time').time_ns())
except JobConflictError:
    print(json.dumps({'stale_ack_publication_refused':True,
                      'snapshot_unchanged':store.get(job_id)==before}))
else:raise AssertionError('Retired ACK coordinator published through new ownership')
"""


@contextmanager
def _workspace(records: Path, report: Path):
    with TemporaryDirectory(prefix="tickwitness-job-followups-") as temporary:
        root = Path(temporary)
        failure = None
        try:
            yield root
        except BaseException as caught:
            failure = caught
            with suppress(OSError):
                report.unlink(missing_ok=True)
            raise
        finally:
            if not records.exists():
                shutil.copytree(root, records)
                (records / "diagnostic-capture.json").write_bytes(
                    _canonical(
                        {
                            "kind": "job_followup_workspace_diagnostics_v1",
                            "accepted": False,
                            "exception_type": None if failure is None else type(failure).__name__,
                            "message": None if failure is None else str(failure),
                        }
                    )
                )


def _resolution(document, *, job_id, origin_id, parent_id, dispatch_id, action, outcome):
    assert document == {
        "kind": "reduction_job_resolution_v1",
        "schema_version": 1,
        "job_id": job_id,
        "origin_job_id": origin_id,
        "parent_job_id": parent_id,
        "action": action,
        "dispatch_job_id": dispatch_id,
        "outcome": outcome,
    }


def _core_profile(run, catalog_view, root, inputs, preparations, catalog, controls):
    examples = Path(__file__).resolve().parents[1] / "examples"
    shutil.copytree(examples / "alpha" / "counterexample", inputs / "old-source")
    (inputs / "request.json").write_bytes(_canonical(_request(5, 6)))
    prepared = run(
        "prepare-reduction-input",
        "old-source",
        "request.json",
        "--input-root",
        str(inputs),
        "--expected-bundle-id",
        _GOLDEN["bundle_id"],
        "--expected-report-id",
        _GOLDEN["report_id"],
        "--output",
        str(preparations / "old-prefix"),
    )
    queued = run(
        "submit-reduction-job",
        str(preparations / "old-prefix"),
        "--expected-preparation-id",
        prepared["preparation_id"],
        "--expected-bundle-id",
        _GOLDEN["bundle_id"],
        "--expected-report-id",
        _GOLDEN["report_id"],
        "--source-evidence",
        "old-source",
        "--input-root",
        str(inputs),
        "--runs",
        str(root / "never-runs"),
        "--jobs",
        str(catalog),
        guarded=True,
    )
    before = _tree(inputs), _tree(preparations), _tree(controls)
    failed = run("run-job", queued["job_id"], "--jobs", str(catalog), guarded=True)
    assert failed["stored_state"] == "FAILED"
    ids = [queued["job_id"]]
    refusals = []
    for command, key_flag, key in (
        ("retry-reduction-job", "--retry-key", "core-retry"),
        ("recover-reduction-job", "--recovery-key", "core-ack"),
    ):
        followup = run(
            command, queued["job_id"], key_flag, key, "--jobs", str(catalog), guarded=True
        )
        assert followup["stored_state"] == "QUEUED"
        stopped = run("run-job", followup["job_id"], "--jobs", str(catalog), guarded=True)
        assert stopped["stored_state"] == "FAILED"
        assert stopped["failure"]["code"] == "research_evidence_not_found"
        ids.append(followup["job_id"])
        refusals.append({"submission": followup, "finished": stopped})
    assert (_tree(inputs), _tree(preparations), _tree(controls)) == before
    assert not (root / "never-runs").exists()
    return {
        "origin_submission": queued,
        "origin_refusal": failed,
        "followup_refusals": refusals,
        "catalog": catalog_view(ids),
        "authority": "missing_original_ledger_refusals_only_v1",
        "native_positive_qualified": False,
        "committed_ack_positive_qualified": False,
        "research_attempts_created": 0,
        "native_calls": 0,
    }


def _native_profile(
    run,
    helper,
    guard,
    invoke,
    capture,
    catalog_view,
    lifecycle,
    native,
    verifier,
    root,
    inputs,
    preparations,
    catalog,
    controls,
    worker,
    cwd,
):
    runs = root / "live-runs"
    source = lifecycle["source"]
    source_before = _tree(inputs / "live-source")
    original_records = _tree(runs)
    ids = []

    def ledger():
        return helper(_LEDGER_VIEW, str(inputs / "live-source"), str(runs), source["bundle_id"])

    def row(job_id, *, jobs=catalog):
        return catalog_view([job_id], jobs=jobs)["jobs"][0]["snapshot"]

    def native_command(mode, job_id, directory):
        return (mode, str(directory), str(worker), "run-job", job_id, "--jobs", str(catalog))

    def launch(executable, entry, command):
        return subprocess.Popen(
            [executable, "-I", *entry, *command],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def collected(process, executable, entry, command, expected):
        stdout, stderr = process.communicate(timeout=30)
        completed = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        return capture(executable, entry, command, completed, expected)

    def wait_gate(process, path, *, seconds=25):
        deadline = time.monotonic() + seconds
        while not path.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError("Coordinator exited before gate: " + repr((stdout, stderr)))
            Event().wait(0.02)
        assert path.exists(), "Controlled coordinator gate timed out"
        return json.loads(path.read_bytes()), deadline

    def cleanup(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    def submit(parent_id, mode, key, *, jobs=catalog):
        command, flag = (
            ("retry-reduction-job", "--retry-key")
            if mode == "retry"
            else ("recover-reduction-job", "--recovery-key")
        )
        argv = (command, parent_id, flag, key, "--jobs", str(jobs))
        before = _tree(runs)
        queued = run(*argv, guarded=True, jobs=jobs)
        assert queued["stored_state"] == "QUEUED"
        after_submit = _tree(jobs)
        assert run(*argv, guarded=True, jobs=jobs) == queued
        assert _tree(jobs) == after_submit and _tree(runs) == before
        if jobs == catalog:
            ids.append(queued["job_id"])
        return {
            "submission": queued,
            "job_id": queued["job_id"],
            "parent_job_id": parent_id,
            "mode": mode,
            "key": key,
        }

    def native_evidence(directory, job_id, slot):
        request = json.loads((directory / "request.jsonl").read_bytes())
        terminal = json.loads((directory / "produced-native-result.jsonl").read_bytes())
        delivered = [
            json.loads(line)
            for line in (directory / "delivered-ipc.jsonl").read_bytes().splitlines()
        ]
        native_calls = [
            json.loads(line)
            for line in (directory / "native-calls.jsonl").read_bytes().splitlines()
        ]
        assert request["job_id"] == terminal["job_id"] == job_id
        assert terminal["kind"] == "job_native_result_v1"
        assert len(native_calls) == 1
        assert native_calls[0]["dataset_id"] == request["payload"]["dataset_id"]
        for sequence, frame in enumerate(delivered, start=1):
            assert frame["sequence"] == sequence
            assert all(
                frame[key] == request[key]
                for key in ("job_id", "coordinator_id", "job_attempt_id", "lease_token")
            )
        reservation = request["payload"]["research_attempt"]
        assert reservation["attempt_index"] == slot
        assert (
            reservation["nonce"]
            == _sha(_canonical({"kind": "reduction_job_dispatch_nonce_v1", "job_id": job_id}))[:32]
        )
        actual = ledger()["slots"][slot - 1]
        assert actual["reservation"] == reservation
        assert actual["attempt_id"] == _sha(_canonical(reservation))
        assert actual["intent_id"] == _sha(_canonical(request["payload"]["intent"]))
        return {
            "request": request,
            "produced_terminal": terminal,
            "delivered_ipc": delivered,
            "native_calls": native_calls,
            "ledger_slot": actual,
            "control_path": str(directory.relative_to(root)),
        }

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
        str(runs),
        "--jobs",
        str(catalog),
        guarded=True,
    )
    origin_id = origin["job_id"]
    ids.append(origin_id)
    directory = controls / "origin-worker-kill"
    entry = ["-c", _NATIVE_CONTROL]
    argv = native_command("worker_kill", origin_id, directory)
    process = launch(native, entry, argv)
    worker_pid = None
    try:
        gate, deadline = wait_gate(process, directory / "gate.json")
        worker_pid = gate["pid"]
        assert gate["job_id"] == origin_id
        target_sequence = gate["last_heartbeat_sequence"]
        before_kill = None
        while time.monotonic() < deadline:
            observed = row(origin_id)
            assert observed["state"] == "RUNNING"
            sequence = observed["attempt"]["heartbeat_sequence"]
            assert sequence <= target_sequence
            if sequence == target_sequence:
                before_kill = observed
                break
            Event().wait(0.02)
        assert before_kill is not None and target_sequence >= 1
        evidence = native_evidence(directory, origin_id, 4)
        assert len(evidence["delivered_ipc"]) == gate["terminal_sequence"] - 1
        assert evidence["ledger_slot"]["outcome_id"] is None
        os.kill(worker_pid, signal.SIGKILL)
        finished = collected(process, native, entry, argv, 0)
        assert finished["stored_state"] == "FAILED"
        assert finished["failure"]["worker_exit_code"] == -signal.SIGKILL
        with suppress(ProcessLookupError):
            os.kill(worker_pid, 0)
            raise AssertionError("Origin killed worker was not reaped")
    finally:
        cleanup(process)
    origin_record = {
        "submission": origin,
        "finished": finished,
        "preparation": prepared,
        "worker_evidence": evidence,
        "actual_worker_pid": worker_pid,
        "coordinator_pid": process.pid,
        "gate": gate,
        "persisted_before_kill": before_kill,
    }
    premature = submit(origin_id, "ack", "no-outcome-yet")
    before = _tree(runs), _tree(controls)
    premature["finished"] = run(
        "run-job", premature["job_id"], "--jobs", str(catalog), guarded=True
    )
    assert premature["finished"]["stored_state"] == "FAILED"
    assert (_tree(runs), _tree(controls)) == before
    assert row(premature["job_id"])["result_sha256"] is None

    # Only the Catalog checkpoint is copied. Every copy keeps the SAME actual
    # original research ledger and shared family journal; no budget is cloned.
    checkpoint = _tree(catalog)
    assert catalog_view(ids)["coordinator_active"] is False
    busy_catalog, stale_catalog = root / "busy-catalog", root / "stale-catalog"
    shutil.copytree(catalog, busy_catalog)
    shutil.copytree(catalog, stale_catalog)
    retry = submit(origin_id, "retry", "retry-one")
    busy = submit(origin_id, "retry", "retry-one", jobs=busy_catalog)
    stale = submit(origin_id, "retry", "retry-one", jobs=stale_catalog)
    assert retry["job_id"] == busy["job_id"] == stale["job_id"]
    retry_id = retry["job_id"]
    directory = controls / "retry-native"
    argv = native_command("retry_ack_loss", retry_id, directory)
    process = launch(native, entry, argv)
    try:
        publication_gate, _ = wait_gate(process, directory / "publication-gate.json")
        assert publication_gate["job_id"] == retry_id
        assert publication_gate["pid"] == process.pid
        retry_evidence = native_evidence(directory, retry_id, 5)
        assert retry_evidence["ledger_slot"]["outcome_id"] is None
        blocked_before = _tree(runs), _tree(controls)
        busy["refusal"] = run(
            "run-job",
            busy["job_id"],
            "--jobs",
            str(busy_catalog),
            guarded=True,
            jobs=busy_catalog,
            expected=9,
        )
        assert busy["refusal"]["error"]["code"] == "job_conflict"
        assert (_tree(runs), _tree(controls)) == blocked_before
        (directory / "release-publication").write_bytes(b"release\n")
        retry["publication_ack_loss"] = collected(process, native, entry, argv, 3)
        assert retry["publication_ack_loss"]["error"]["code"] == "attempt_outcome_unconfirmed"
    finally:
        cleanup(process)
    retry["publication_gate"] = publication_gate
    retry["worker_evidence"] = retry_evidence
    exhausted = ledger()
    assert exhausted["budget"] == {"max_attempts": 5, "max_events": 1000, "max_wall_seconds": 60}
    assert [slot["attempt_index"] for slot in exhausted["slots"]] == [1, 2, 3, 4, 5]
    assert exhausted["slots"][:3] == lifecycle["before"]["slots"]
    assert exhausted["slots"][3]["outcome_id"] is None
    outcome_id = exhausted["slots"][4]["outcome_id"]
    assert exhausted["slots"][4]["outcome_kind"] == "reduction_run_receipt_v1"
    inspected = run(
        "inspect-reduction-run",
        outcome_id,
        "--source-evidence",
        "live-source",
        "--input-root",
        str(inputs),
        "--runs",
        str(runs),
        guarded=True,
    )
    outcome = inspected["receipt"]
    raw_result = helper(_READ_ARTIFACT, str(runs), outcome["bindings"]["replay_result_sha256"])
    assert raw_result == retry_evidence["produced_terminal"]["replay_result"]
    assert (
        retry_evidence["request"]["payload"]["normalized"]
        == (evidence["request"]["payload"]["normalized"])
    )
    assert (
        retry_evidence["request"]["payload"]["dataset_id"]
        == (evidence["request"]["payload"]["dataset_id"])
    )
    retry["independent_inspection"] = inspected
    retry["raw_result"] = raw_result
    retry["before_reconciliation"] = run(
        "inspect-job", retry_id, "--jobs", str(catalog), guarded=True
    )
    assert retry["before_reconciliation"]["stored_state"] == "RUNNING"
    assert retry["before_reconciliation"]["state"] == "COORDINATOR_LOST"
    retry["explicit_reconciliation"] = run("reconcile-jobs", "--jobs", str(catalog), guarded=True)
    busy["explicit_reconciliation"] = run(
        "reconcile-jobs", "--jobs", str(busy_catalog), guarded=True, jobs=busy_catalog
    )
    old_terminals = {origin_id: row(origin_id), retry_id: row(retry_id)}
    assert old_terminals[origin_id]["state"] == "FAILED"
    assert old_terminals[retry_id]["state"] == "LOST"
    retry["same_key_submission_after_loss"] = run(
        "retry-reduction-job",
        origin_id,
        "--retry-key",
        "retry-one",
        "--jobs",
        str(catalog),
        guarded=True,
    )
    before_repeat = _tree(runs), _tree(catalog), _tree(controls)
    retry["terminal_rerun"] = run("run-job", retry_id, "--jobs", str(catalog), guarded=True)
    assert retry["terminal_rerun"]["stored_state"] == "LOST"
    assert (_tree(runs), _tree(catalog), _tree(controls)) == before_repeat
    before = _tree(runs), _tree(catalog), _tree(controls)
    sibling = run(
        "retry-reduction-job",
        origin_id,
        "--retry-key",
        "different-sibling",
        "--jobs",
        str(catalog),
        guarded=True,
        expected=9,
    )
    assert sibling["error"]["code"] == "job_conflict"
    assert (_tree(runs), _tree(catalog), _tree(controls)) == before

    research_at_exhaustion = _tree(runs)
    before_core = _tree(runs), _tree(controls)
    stale["finished"] = run(
        "run-job", retry_id, "--jobs", str(stale_catalog), guarded=True, jobs=stale_catalog
    )
    assert stale["finished"]["stored_state"] == "SUCCEEDED"
    stale["resolution"] = run(
        "read-job-result", retry_id, "--jobs", str(stale_catalog), guarded=True, jobs=stale_catalog
    )
    _resolution(
        stale["resolution"],
        job_id=retry_id,
        origin_id=origin_id,
        parent_id=origin_id,
        dispatch_id=retry_id,
        action="acknowledged_committed",
        outcome=outcome,
    )
    assert (_tree(runs), _tree(controls)) == before_core
    later_retry = submit(retry_id, "retry", "after-committed-result")
    later_retry["finished"] = run(
        "run-job", later_retry["job_id"], "--jobs", str(catalog), guarded=True
    )
    assert later_retry["finished"]["stored_state"] == "SUCCEEDED"
    later_retry["resolution"] = run(
        "read-job-result", later_retry["job_id"], "--jobs", str(catalog), guarded=True
    )
    _resolution(
        later_retry["resolution"],
        job_id=later_retry["job_id"],
        origin_id=origin_id,
        parent_id=retry_id,
        dispatch_id=retry_id,
        action="acknowledged_committed",
        outcome=outcome,
    )
    assert _tree(runs) == research_at_exhaustion

    killed_ack = submit(origin_id, "ack", "kill-before-complete")
    ack_dir = controls / "ack-coordinator-kill"
    ack_entry = guard(_ACK_CONTROL)
    ack_argv = (
        "readonly",
        str(catalog),
        "kill_before_complete",
        str(ack_dir),
        "run-job",
        killed_ack["job_id"],
        "--jobs",
        str(catalog),
    )
    process = launch(verifier, ack_entry, ack_argv)
    try:
        ack_gate, _ = wait_gate(process, ack_dir / "ack-gate.json")
        assert ack_gate["pid"] == process.pid
        assert ack_gate["job_id"] == killed_ack["job_id"]
        assert ack_gate["dispatch_job_id"] == retry_id
        assert ack_gate["outcome_id"] == outcome_id
        assert row(killed_ack["job_id"]) == ack_gate["snapshot"]
        os.kill(process.pid, signal.SIGKILL)
        collected(process, verifier, ack_entry, ack_argv, -signal.SIGKILL)
    finally:
        cleanup(process)
    killed_ack["gate"] = ack_gate
    killed_ack["readonly_orphan"] = run(
        "inspect-job", killed_ack["job_id"], "--jobs", str(catalog), guarded=True
    )
    assert killed_ack["readonly_orphan"]["state"] == "COORDINATOR_LOST"
    killed_ack["reconciliation"] = run("reconcile-jobs", "--jobs", str(catalog), guarded=True)
    assert row(killed_ack["job_id"])["state"] == "LOST"
    old_snapshot = ack_dir / "retired-snapshot.json"
    old_snapshot.write_bytes(_canonical(ack_gate["snapshot"]))
    stale_wrapper = {
        "kind": "reduction_job_resolution_v1",
        "schema_version": 1,
        "job_id": killed_ack["job_id"],
        "origin_job_id": origin_id,
        "parent_job_id": origin_id,
        "action": "acknowledged_committed",
        "dispatch_job_id": retry_id,
        "outcome": outcome,
    }
    stale_result = ack_dir / "retired-valid-result.json"
    stale_result.write_bytes(_canonical(stale_wrapper))
    before_stale = _tree(runs), _tree(catalog)
    killed_ack["stale_publication"] = invoke(
        verifier,
        guard(_STALE_ACK),
        ("readonly", str(catalog), str(old_snapshot), str(stale_result)),
    )
    assert killed_ack["stale_publication"] == {
        "stale_ack_publication_refused": True,
        "snapshot_unchanged": True,
    }
    assert (_tree(runs), _tree(catalog)) == before_stale

    ack = submit(origin_id, "ack", "finish-ack")
    ack_dir = controls / "ack-publication-ack-loss"
    before_ack = _tree(runs)
    ack["completion_ack_loss"] = invoke(
        verifier,
        guard(_ACK_CONTROL),
        (
            "readonly",
            str(catalog),
            "ack_loss",
            str(ack_dir),
            "run-job",
            ack["job_id"],
            "--jobs",
            str(catalog),
        ),
        expected=3,
    )
    assert "error" in ack["completion_ack_loss"]
    ack["independent_inspection"] = run(
        "inspect-job", ack["job_id"], "--jobs", str(catalog), guarded=True
    )
    assert ack["independent_inspection"]["stored_state"] == "SUCCEEDED"
    ack["resolution"] = run("read-job-result", ack["job_id"], "--jobs", str(catalog), guarded=True)
    _resolution(
        ack["resolution"],
        job_id=ack["job_id"],
        origin_id=origin_id,
        parent_id=origin_id,
        dispatch_id=retry_id,
        action="acknowledged_committed",
        outcome=outcome,
    )
    assert _tree(runs) == before_ack == research_at_exhaustion
    before = _tree(runs), _tree(catalog), _tree(controls)
    ack["same_key_resubmission"] = run(
        "recover-reduction-job",
        origin_id,
        "--recovery-key",
        "finish-ack",
        "--jobs",
        str(catalog),
        guarded=True,
    )
    ack["terminal_rerun"] = run("run-job", ack["job_id"], "--jobs", str(catalog), guarded=True)
    assert ack["same_key_resubmission"] == ack["independent_inspection"]
    assert ack["terminal_rerun"] == ack["independent_inspection"]
    assert (_tree(runs), _tree(catalog), _tree(controls)) == before
    assert {key: row(key) for key in old_terminals} == old_terminals
    assert ledger() == exhausted
    physical = runs / "slots" / lifecycle["frozen"]["protocol_id"]
    assert sorted(path.name for path in physical.iterdir()) == [
        f"{index:04d}.json" for index in range(1, 6)
    ]
    assert len({slot["attempt_id"] for slot in exhausted["slots"]}) == 5
    assert all(_tree(runs).get(relative) == sha for relative, sha in original_records.items())
    assert _tree(inputs / "live-source") == source_before
    return {
        "origin_job": origin_record,
        "premature_ack": premature,
        "native_retry": retry,
        "catalog_checkpoint_before_retry": checkpoint,
        "same_key_busy_catalog": busy,
        "same_key_stale_catalog": stale,
        "other_key_sibling_refusal": sibling,
        "retry_after_committed_outcome": later_retry,
        "ack_coordinator_kill": killed_ack,
        "ack_own_completion_ack_loss": ack,
        "after": exhausted,
        "old_terminal_snapshots_unchanged": old_terminals,
        "catalog": catalog_view(ids),
        "busy_catalog": catalog_view([*ids[:2], retry_id], jobs=busy_catalog),
        "stale_catalog": catalog_view([*ids[:2], retry_id], jobs=stale_catalog),
        "new_original_research_slots": [4, 5],
        "actual_managed_native_calls": 2,
        "native_retry_started_from_frozen_origin": True,
        "core_ack_after_budget_exhaustion": True,
        "source_and_original_records_unchanged": True,
        "no_sixth_slot_refund_or_same_slot_replay": True,
        "failed_native_origin_and_lost_native_retry_not_rewritten": True,
        "committed_failure_qualification": "unit_fixtures_only_no_native_failure_receipt_claim",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "verifier-python", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--core-only", action="store_true")
    args = parser.parse_args()
    if args.report.exists() or args.records_dir.exists():
        raise FileExistsError("Followup qualification destinations must be new")
    native, verifier = str(args.python.absolute()), str(args.verifier_python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    golden_before = _tree(examples / "alpha")
    with _workspace(args.records_dir, args.report) as root:
        inputs, preparations, catalog, cwd, transcripts, controls = (
            root / name
            for name in (
                "input-root",
                "preparations",
                "jobs",
                "unrelated-cwd",
                "transcripts",
                "controls",
            )
        )
        for directory in (inputs, preparations, cwd, transcripts, controls):
            directory.mkdir()
        worker = controls / "native-worker.py"
        worker.write_text(_WORKER)
        calls = []

        def capture(executable, entry, command, completed, expected):
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
            payload = completed.stdout if expected == 0 else completed.stderr
            unwanted = completed.stderr if expected == 0 else completed.stdout
            if completed.returncode != expected or unwanted:
                raise RuntimeError(
                    f"Installed followup exited {completed.returncode}, expected {expected}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            if expected < 0 and not payload:
                return {"signal_exit_code": completed.returncode}
            return json.loads(payload)

        def invoke(executable, entry, command=(), *, expected=0):
            completed = subprocess.run(
                [executable, "-I", *entry, *command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=240,
            )
            return capture(executable, entry, command, completed, expected)

        def guard(code):
            return ["-c", _GUARD_PREFIX + _GUARD + _GUARD_SUFFIX + code]

        def run(*command, producer=False, guarded=False, jobs=catalog, expected=0):
            entry = (
                guard("\nraise SystemExit(main(sys.argv[1:]))\n")
                if guarded
                else ["-m", "tickwitness"]
            )
            actual = ("readonly", str(jobs), *command) if guarded else command
            return invoke(native if producer else verifier, entry, actual, expected=expected)

        def helper(code, *command):
            return invoke(verifier, ["-c", _GUARD + code], ("readonly", *command))

        def catalog_view(ids, *, jobs=catalog):
            return invoke(verifier, guard(_CATALOG), ("readonly", str(jobs), json.dumps(ids)))

        identities = {
            "producer": invoke(native, ["-c", _RUNTIME]),
            "verifier": invoke(verifier, ["-c", _RUNTIME]),
        }
        for name, requested in (("producer", args.python), ("verifier", args.verifier_python)):
            assert Path(identities[name]["prefix"]).resolve() == (
                requested.absolute().parent.parent.resolve()
            )
            assert Path(identities[name]["prefix"]).resolve() != (
                Path(identities[name]["base_prefix"]).resolve()
            )
        assert identities["verifier"]["native_distribution"] is None
        assert identities["producer"]["native_distribution"] == (
            None if args.core_only else "1.231.0"
        )
        (root / "interpreter-identities.json").write_bytes(_canonical(identities))
        confirmations = []
        for command, key_flag in (
            ("retry-reduction-job", "--retry-key"),
            ("recover-reduction-job", "--recovery-key"),
        ):
            refusal = run(
                command,
                "invalid",
                key_flag,
                "key",
                "--jobs",
                str(root / "never-jobs"),
                "--split",
                "confirmation",
                expected=5,
            )
            assert refusal["error"]["code"] == "confirmation_access_denied"
            confirmations.append({"command": command, "refusal": refusal})
        assert not (root / "never-jobs").exists()
        if args.core_only:
            scope = _core_profile(run, catalog_view, root, inputs, preparations, catalog, controls)
            lifecycle = None
        else:
            scope = None
            lifecycle = _bootstrap(
                run,
                helper,
                examples,
                root,
                inputs,
                original_attempts=5,
                qualification_title=(
                    "Synthetic five-slot explicit retry and ACK recovery qualification"
                ),
            )
            lifecycle.update(
                _native_profile(
                    run,
                    helper,
                    guard,
                    invoke,
                    capture,
                    catalog_view,
                    lifecycle,
                    native,
                    verifier,
                    root,
                    inputs,
                    preparations,
                    catalog,
                    controls,
                    worker,
                    cwd,
                )
            )
        assert _tree(examples / "alpha") == golden_before
        report = {
            "kind": "installed_job_followup_acceptance_v1",
            "accepted": True,
            "core_only_profile": args.core_only,
            "interpreter_identities": identities,
            "confirmation_refusals": confirmations,
            "core_refusal": scope,
            "lifecycle": lifecycle,
            "scope": {
                "explicit_idempotent_retry": not args.core_only,
                "committed_outcome_acknowledgment": not args.core_only,
                "checkpoint_resume": False,
                "automatic_retry": False,
                "research_budget_reset": False,
                "strong_cancellation": False,
                "external_human_attempts": 0,
                "external_human_gate": "PENDING",
            },
        }
        inner = root / "job-followups-smoke" / "report.json"
        inner.parent.mkdir()
        inner.write_bytes(_canonical(report))
        shutil.copytree(root, args.records_dir)
        (args.records_dir / "artifact-files.json").write_bytes(_canonical(_tree(args.records_dir)))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
