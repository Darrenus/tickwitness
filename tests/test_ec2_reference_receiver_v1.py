"""Production receiver, real durable qualification and existing Controller.

Trusted host/process/launch ports use private inert files. No test is an AWS
qualification, independent cloud download or owner-key deployment. The original
Ec2Run/driver/controller/exporter/ACK producers are used, not a second ledger.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
decisions = importlib.import_module("test_ec2_reference_qualification_v3")

base_host = decisions.base_host
host = decisions.host
recovery = decisions.recovery
v2 = decisions.v2
v2_history = decisions.v2_history
v3 = decisions.v3
v3_history = decisions.v3_history
driver = decisions.driver


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename
    )
    assert spec is not None and spec.loader is not None
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


client = load("ec2_receiver_v1_under_test", "ec2_reference_receiver_v1.py")
ops = load("ec2_receiver_real_ops_v3", "ec2_reference_handoff_v3.py")
reader = client.reader


class LocalClock:
    def __init__(self):
        self.value = 10**15

    def now(self):
        return self.value


@pytest.fixture
def produced(driver, monkeypatch, tmp_path):
    """A real Controller waits while the real receiver receives its genuine archive."""
    original_raw = decisions.raw_result
    root = driver.case.host.root
    operation = tmp_path / "operations" / ops.RUN_ID
    operation.parent.mkdir(mode=0o700)
    stage = tmp_path / "stage"
    stage.mkdir(mode=0o700)
    for name in (
        "run_ec2_reference_recovery_v3.sh",
        "provision_ec2_reference_source.sh",
        "ec2_reference_handoff_v3.py",
    ):
        (stage / name).write_bytes(("inert operational fixture: " + name + "\n").encode())
    for module in (client, ops):
        monkeypatch.setattr(module, "ROOT", root)
        monkeypatch.setattr(module, "OPERATION", operation)
        monkeypatch.setattr(module, "STAGE", stage)
    monkeypatch.setattr(client, "ARCHIVE_BASE", tmp_path)
    monkeypatch.setattr(
        ops, "OLD_SOURCES", tuple(row["source_revision"] for row in driver.case.history.values())
    )
    store = ops.Store(operation, owner=os.getuid(), trust_root=tmp_path, archive_base=tmp_path)
    release, waiting = threading.Event(), threading.Event()
    qualifier_requested, qualifier_finished = threading.Event(), threading.Event()
    qualifier_results = []

    class ServerClock:
        value = 1_000_000_000_000

        def now(self):
            return self.value

        def sleep(self, seconds):
            waiting.set()
            if not release.wait(10):
                raise RuntimeError("Test did not release the original waiter")
            self.value += max(1, int(seconds * 1e9))

    clock = ServerClock()
    source, boot = decisions.CURRENT, driver.case.host.boot[0]

    class Host:
        guard = ops.GuardIdentity(
            "b" * 32,
            ops.ProcessIdentity(10, 100, ops.main_argv(source), "/system.slice/" + ops.UNIT, 1),
            "fixture original complete ExecStart",
            "/system.slice/" + ops.UNIT,
        )

        def boot(self):
            return boot

        def master(self, selected):
            assert selected == source
            return ops.ProcessIdentity(20, 200, ops.controller_argv(source), self.guard.cgroup, 10)

        def process(self, _pid):
            return ops.ProcessIdentity(
                30,
                300,
                [
                    "/usr/bin/python3",
                    "-I",
                    str(stage / "ec2_reference_handoff_v3.py"),
                    "internal-export",
                    "--source-revision",
                    source,
                    "--run-id",
                    ops.RUN_ID,
                ],
                self.guard.cgroup,
                20,
            )

        def live(self, selected, start):
            assert selected == source and start["controller_pid"] == 20
            return self.guard

        def before_preparation(self, selected, active):
            assert selected == source
            for retained, name in (
                ("batch-source.sh", "run_ec2_reference_recovery_v3.sh"),
                ("preparer-source.sh", "provision_ec2_reference_source.sh"),
                ("handoff-source.py", "ec2_reference_handoff_v3.py"),
            ):
                active.write(retained, (stage / name).read_bytes())
            active.write("history-before.log", ops.canonical(ops.history_snapshot(active)))

        def after_preparation(self, selected, active):
            assert selected == source
            active.write("history-prepared.log", ops.canonical(ops.history_snapshot(active)))
            active.write("source-check.log", b"inert source observation\n")

    host_port = Host()

    def raw_result(run, ticket, manifest_sha256):
        result = original_raw(run, ticket, manifest_sha256)
        out, err = f"retained {ticket.name} {ticket.nonce}\n", ""
        result.update(
            actual_exit_code=0,
            artifact_dir=str(run.artifact_dir),
            started=True,
            stdout=out,
            stderr=err,
            stdout_truncated=False,
            stderr_truncated=False,
            stop_reason="natural_exit",
        )
        result["host_facts"].update(
            canaries_before={"protected": "fixture-canary"},
            canaries_after={"protected": "fixture-canary"},
            confirmed_task_absent=True,
            stop_intent_ns=ticket.admitted_ns + 1,
            stop_confirmation_deadline_ns=ticket.admitted_ns + 1 + ops.GRACE_NS,
            stop_elapsed_ns=1,
            deadline_elapsed_ns=2,
            bootstrap_admission={
                "receipt": {"policy_setup_sha256": run._state["policy_receipts"]["report_sha256"]}
            },
            stdout_sha256=client.sha(out.encode()),
            stderr_sha256=client.sha(err.encode()),
            stdout_retained_bytes=len(out.encode()),
            stderr_retained_bytes=len(err.encode()),
        )
        stem = run.artifact_dir / f"{ticket.name}-{ticket.nonce}"
        stem.with_suffix(".json").write_bytes(client.canonical(result))
        stem.with_suffix(".stdout").write_bytes(out.encode())
        stem.with_suffix(".stderr").write_bytes(err.encode())
        return result

    monkeypatch.setattr(decisions, "raw_result", raw_result)

    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, argv, deadline, grace, stdout, stderr):
            name = "qualifier" if stdout.stem == "qualification" else stdout.stem
            self.calls.append(name)
            assert deadline < grace <= controller.deadline + ops.GRACE_NS
            stream = io.StringIO()
            if name == "qualifier":
                # The actual driver owns signal handlers and must execute in
                # pytest's main thread, while this original phase waits for it.
                qualifier_requested.set()
                if not qualifier_finished.wait(10):
                    raise RuntimeError("Main thread did not complete the one qualifier call")
                code, raw = qualifier_results[0]
                assert code == 0
                stream.write(raw)
            elif name == "export":
                with contextlib.redirect_stdout(stream):
                    ops.internal_export(source, store, host_port, clock)
            store.write(stdout.name, stream.getvalue().encode())
            store.write(stderr.name, b"")
            clock.value += 1_000_000_000
            return ops.PhaseResult(0)

    runner = Runner()
    controller = ops.Controller(source, store, host_port, runner, clock)
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(controller.run()), daemon=True)
    thread.start()
    assert qualifier_requested.wait(10), "Original Controller did not request its qualifier phase"
    qualification_output = io.StringIO()
    driver.case.host.clock[0] = clock.now()
    try:
        with contextlib.redirect_stdout(qualification_output):
            code = decisions.invoke()
        qualifier_results.append((code, qualification_output.getvalue()))
    finally:
        qualifier_finished.set()
    assert code == 0
    assert driver.path == driver.runs[0].run_dir
    assert (driver.path / "state.json").is_file()
    assert waiting.wait(10), "Original Controller did not publish ready"
    ready = store.record_read("handoff-ready", source, boot)
    archive = (operation / "evidence.tar.gz").read_bytes()
    # Pin rows come from the actual exporter, not fabricated filesystem stats.
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        data = json.load(tar.extractfile("export-inventory.json"))
    files = [
        {
            "path": row["path"],
            "bytes": row["stat"]["size"],
            "sha256": row["sha256"],
            "stat": {key: str(value) for key, value in row["stat"].items()},
        }
        for row in data["archived"]
    ]
    for path in (operation / "handoff-ready.json", operation / "evidence.tar.gz", *stage.iterdir()):
        files.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": client.sha(path.read_bytes()),
                "stat": reader.stat_record(path.stat()),
            }
        )
    source_rows = [
        {"path": str(path), "bytes": path.stat().st_size, "sha256": client.sha(path.read_bytes())}
        for relative in decisions.ec2.RECOVERY_V3_SOURCE_FILES
        for path in [driver.case.host.source / relative]
    ]
    updates = {
        "ROOT": str(root),
        "OPERATION": str(operation),
        "STAGE": str(stage),
        "SOURCE": source,
        "ORIGINAL_BOOT": boot,
        "ORIGINAL_INVOCATION": host_port.guard.invocation_id,
        "ARCHIVE": str(operation / "evidence.tar.gz"),
        "READY": str(operation / "handoff-ready.json"),
        "ARCHIVE_SHA": client.sha(archive),
        "ARCHIVE_BYTES": len(archive),
        "READY_SHA": client.sha((operation / "handoff-ready.json").read_bytes()),
        "SOURCE_PATHS": {row["path"] for row in source_rows},
        "STAGE_PATHS": {str(path) for path in stage.iterdir()},
        "OLD_SOURCES": {row["source_revision"] for row in driver.case.history.values()} | {source},
    }
    for key, value in updates.items():
        monkeypatch.setattr(reader, key, value)
    pins_data = {
        "kind": "ec2_transport_pin_set_v1",
        "schema_version": 1,
        "observation_id": reader.OBSERVATION_ID,
        "source_revision": source,
        "run_id": ops.RUN_ID,
        "original_boot_id": boot,
        "original_invocation_id": host_port.guard.invocation_id,
        "original_archive_sha256": client.sha(archive),
        "original_archive_bytes": len(archive),
        "original_ready_sha256": updates["READY_SHA"],
        "origin_audit_index_sha256": reader.AUDIT_SHA,
        "files": files,
        "source_files": source_rows,
    }
    pins = reader.PinSet(client.canonical(pins_data), owner=os.getuid())
    result = SimpleNamespace(
        driver=driver,
        pins=pins,
        ready=ready,
        archive=archive,
        store=store,
        host=host_port,
        clock=clock,
        release=release,
        thread=thread,
        outcome=outcome,
        runner=runner,
        root=tmp_path,
    )
    yield result
    if thread.is_alive():
        clock.value = ready["deadline_ns"]
        release.set()
        thread.join(3)
    assert not thread.is_alive()


class Immediate:
    def __init__(self, result, callback=None, error=None):
        self.result, self.callback, self.error = result, callback, error

    def finish(self, _deadline):
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return self.result

    def observed(self):
        return self.result

    def first_line(self, _deadline):
        return self.result.stdout.split(b"\n", 1)[0] + b"\n"


class DirectReadChannels:
    """Transport port uses actual Reader + ACK, not another receive implementation."""

    def __init__(self, env, clock):
        self.env, self.clock, self.calls = env, clock, []
        self.prepared_ns = clock.now() - 10_000_000_000
        self.ack_calls = 0
        self.ack_error = None
        self.header_error = None
        self.cost = 0

        class Files(reader.SafeFiles):
            def path(self, logical):
                assert reader.allowed_path(logical)
                return Path(logical)

        class Host:
            def boot(self):
                return env.host.boot()

            def guard(self):
                guard = env.host.guard
                return {
                    "active_state": "active" if env.thread.is_alive() else "inactive",
                    "sub_state": "running" if env.thread.is_alive() else "dead",
                    "invocation_id": guard.invocation_id,
                    "main_pid": guard.main.pid,
                    "main_start_ticks": guard.main.start_ticks,
                    "main_argv": guard.main.argv,
                    "exec_start": guard.exec_start,
                    "control_group": guard.cgroup,
                    "user": "ubuntu",
                }

            def process(self, pid):
                if pid == env.host.guard.main.pid:
                    main = env.host.guard.main
                    return {
                        "pid": main.pid,
                        "start_ticks": main.start_ticks,
                        "argv": main.argv,
                        "cgroup": main.cgroup,
                        "ppid": main.ppid,
                        "effective_uid": 1000,
                    }
                master = env.host.master(env.pins.data["source_revision"])
                assert pid == master.pid
                return {
                    "pid": master.pid,
                    "start_ticks": master.start_ticks,
                    "argv": master.argv,
                    "cgroup": master.cgroup,
                    "ppid": master.ppid,
                    "effective_uid": 0,
                }

            def validate(self):
                pass

            def lifecycle(self, _files):
                pass

        self.reader = reader.Reader(
            env.pins, files=Files(env.root, owner=os.getuid()), host=Host(), clock=env.clock
        )

    def start(self, mode, boot, _deadline, *, wait=False):
        self.calls.append((mode, wait))
        self.clock.value += self.cost
        out, err = io.BytesIO(), io.BytesIO()
        if mode == "snapshot":
            out.write(client.canonical(self.reader.snapshot(boot)))
        elif mode == "inventory":
            out.write(client.canonical(self.reader.inventory(boot)))
        elif mode == "archive":
            self.reader.archive(boot, out, err)
        elif mode == "post-records":
            generator = self.reader.post_records(boot, wait_existing_terminal=wait)
            header = next(generator)
            first = client.canonical(header)
            if self.header_error:
                header.update(self.header_error)
                first = client.canonical(header)

            def finish():
                if wait:
                    self.env.thread.join(3)
                    assert not self.env.thread.is_alive()
                for row in generator:
                    out.write(client.canonical(row))

            out.write(first)

            class Post(Immediate):
                def finish(inner, deadline):
                    finish()
                    return client.Completed(out.getvalue(), b"", 0)

            return Post(client.Completed(first, b"", 0))
        else:
            raise AssertionError("Unexpected mode " + mode)
        return Immediate(client.Completed(out.getvalue(), err.getvalue(), 0))

    def ack(self, ready, source, _deadline):
        self.ack_calls += 1
        assert any(mode == "post-records" and wait for mode, wait in self.calls)
        ops.acknowledge(
            source,
            self.env.store,
            self.env.host,
            self.env.clock,
            {
                key: ready[key]
                for key in (
                    "boot_id",
                    "invocation_id",
                    "main_pid",
                    "controller_pid",
                    "nonce",
                    "bytes",
                    "sha256",
                )
            },
        )
        self.env.release.set()
        return Immediate(client.Completed(b"", b"", 0), error=self.ack_error)


def receiver(env, tmp_path, name="audit", *, intents=None):
    clock = LocalClock()
    channels = DirectReadChannels(env, clock)
    local = client.LocalStore(tmp_path / name)
    permanent = client.IntentStore(tmp_path / "permanent") if intents is None else intents
    actual = client.Receiver(env.pins, channels, local, clock, intents=permanent)
    return actual, channels, local, permanent


def test_actual_durable_graph_and_controller_ack_are_received_once(produced, tmp_path):
    actual, channels, local, permanent = receiver(produced, tmp_path)
    before = (produced.driver.path / "state.json").read_bytes()
    result = actual.live_receive(produced.pins.data["original_boot_id"])
    assert channels.ack_calls == 1
    assert result["post_status"] == "ACKNOWLEDGED_RECORDS_OBSERVED"
    assert result["transport_status"] == "UNKNOWN_PENDING_MANAGER_EXIT_AND_CLOUD_STOP"
    assert produced.outcome == [0]
    assert produced.runner.calls == ["preparation", "qualifier", "export"]
    assert before == (produced.driver.path / "state.json").read_bytes()
    assert result["qualification"]["raw_cases"] == 24
    assert result["qualification"]["retained_streams"] == 48
    assert result["qualification"]["prior_charged"] == 21
    assert result["qualification"]["cumulative_charged"] == 45
    assert (local.directory / "ack-intent.json").is_file()
    assert len(list(permanent.directory.iterdir())) == 1


@pytest.mark.parametrize("mode", ["late", "late_preparation", "download_cost", "bad_post_header"])
def test_original_clock_and_authenticated_post_gate_allow_zero_ack(produced, tmp_path, mode):
    actual, channels, _, _ = receiver(produced, tmp_path)
    if mode == "late":
        produced.clock.value = produced.ready["deadline_ns"]
    elif mode == "late_preparation":
        channels.prepared_ns = actual.clock.now()
    elif mode == "download_cost":
        channels.cost = 40_000_000_000
    else:
        channels.header_error = {"invocation_id": "c" * 32}
    with pytest.raises((client.Refused, reader.Refused)):
        actual.live_receive(produced.pins.data["original_boot_id"])
    assert channels.ack_calls == 0


def test_new_audit_destination_cannot_retransmit_after_lost_ack_reply(produced, tmp_path):
    actual, channels, _, permanent = receiver(produced, tmp_path)
    channels.ack_error = OSError("Reply lost after original durable ACK")
    result = actual.live_receive(produced.pins.data["original_boot_id"])
    assert result["ack_reply"].startswith("UNKNOWN_AFTER_SINGLE_ACK_SUBMISSION")
    assert channels.ack_calls == 1
    assert produced.outcome == [0]
    # Reaching the permanent fence does not depend on a fresh audit directory.
    another = client.LocalStore(tmp_path / "another-audit")
    with pytest.raises(FileExistsError):
        permanent.claim(produced.ready, produced.pins, {"attempt": "forbidden second submission"})
    assert not (another.directory / "ack-intent.json").exists()
    assert channels.ack_calls == 1


def test_partial_shared_intent_fsync_failure_is_permanently_used(produced, tmp_path, monkeypatch):
    _, _, _, permanent = receiver(produced, tmp_path)
    original = client.os.fsync
    with monkeypatch.context() as patch:
        patch.setattr(
            client.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync unknown"))
        )
        with pytest.raises(OSError):
            permanent.claim(produced.ready, produced.pins, {"intent": "first"})
    assert client.os.fsync is original
    with pytest.raises(FileExistsError):
        permanent.claim(produced.ready, produced.pins, {"intent": "second"})


@pytest.mark.parametrize(
    "which",
    [
        "report_unknown",
        "prior_three",
        "raw_nonce",
        "raw_unknown",
        "stream_hash",
        "stream_bytes",
        "backend_bytes",
        "stop",
        "canary",
        "manifest_unknown",
        "receipt",
        "plan_unknown",
        "consumption_unknown",
    ],
)
def test_full_semantics_refuse_rebound_source_bytes(produced, which):
    verifier = client.ArchiveVerifier(produced.pins)
    verifier.parse(produced.archive)
    run = client.ROOT / "runs" / client.RUN
    mapping = {
        "report_unknown": run / "qualification-report.json",
        "prior_three": run / "qualification-report.json",
        "raw_nonce": run / "case-01.json",
        "raw_unknown": run / "case-01.json",
        "stream_hash": run / "case-01.json",
        "stop": run / "case-01.json",
        "canary": run / "case-01.json",
        "manifest_unknown": run / "qualification/manifest.json",
        "receipt": client.OPERATION / "qualification.stdout",
        "plan_unknown": client.ROOT / "recovery-v3/plan.json",
        "consumption_unknown": client.ROOT / "recovery-v3/consumption.json",
    }
    first = verifier.json(run / "case-01.json")
    stem = run / "qualification" / f"positive-{first['nonce']}"
    if which in {"stream_bytes", "backend_bytes"}:
        path = stem.with_suffix(".stdout" if which == "stream_bytes" else ".json")
        verifier.files[verifier.member(path)] = b"changed actual retained bytes\n"
    else:
        path = mapping[which]
        value = verifier.json(path, canonical_required=which != "receipt")
        if which.endswith("unknown"):
            value["unknown_authority"] = True
        elif which == "prior_three":
            value["recovery_accounting"]["prior_charged"] = 3
        elif which == "raw_nonce":
            value["nonce"] = "0" * 32
        elif which == "stream_hash":
            value["host_facts"]["stdout_sha256"] = "0" * 64
        elif which == "stop":
            value["host_facts"]["confirmed_task_absent"] = False
        elif which == "canary":
            value["host_facts"]["canaries_after"] = {"changed": True}
        else:
            value["terminal_receipt"]["recovery_accounting"]["cumulative_charged"] = 24
        verifier.files[verifier.member(path)] = client.canonical(value)
    # Exercise inner semantics after the genuine outer verification, avoiding a
    # known-SHA mismatch being the sole rejection of an authority mutation.
    verifier.parse = lambda _raw: None
    with pytest.raises((client.Refused, reader.Refused)):
        verifier.verify(produced.archive)


@pytest.mark.parametrize("missing", ["INVOCATION_ID", "_PID", "UNIT", "CODE_FUNC", "MESSAGE_ID"])
def test_positive_manager_exit_requires_actual_pid1_original_identity(produced, missing):
    row = {
        "_PID": "1",
        "UNIT": client.UNIT,
        "_BOOT_ID": produced.pins.data["original_boot_id"].replace("-", ""),
        "INVOCATION_ID": produced.pins.data["original_invocation_id"],
        "MESSAGE_ID": "98e322203f7a4ed290d09fe03c09fe15",
        "CODE_FUNC": "unit_log_process_exit",
        "EXIT_CODE": "exited",
        "EXIT_STATUS": "0",
    }
    assert client.manager_exit(client.canonical(row), produced.pins, 0)
    del row[missing]
    assert not client.manager_exit(client.canonical(row), produced.pins, 0)
    assert not client.manager_exit(
        client.canonical({"boot_id": produced.pins.data["original_boot_id"], "exit_status": "0"}),
        produced.pins,
        0,
    )


def test_isolated_actual_cli_loads_only_its_fixed_sibling_reader():
    path = Path(__file__).parents[1] / "scripts/ec2_reference_receiver_v1.py"
    result = subprocess.run(
        [sys.executable, "-I", str(path), "--help"], capture_output=True, timeout=10
    )
    assert result.returncode == 0 and b"historical-retrieve" in result.stdout
    bad = subprocess.run(
        [sys.executable, "-I", str(path), "arbitrary-command"], capture_output=True, timeout=10
    )
    assert bad.returncode == 2


@pytest.mark.skipif(sys.platform != "linux", reason="Real /proc owned-process-group observation")
@pytest.mark.parametrize("hold_pipe", [True, False])
def test_actual_bounded_transport_reaps_exited_leader_and_sigterm_ignoring_child(
    tmp_path, hold_pipe
):
    pid_path = tmp_path / "child.pid"
    code = (
        "import os,signal,time,pathlib; p=os.fork(); "
        "\nif p==0:\n signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        + ("" if hold_pipe else "os.close(1); os.close(2); ")
        + "pathlib.Path("
        + repr(str(pid_path))
        + ").write_text(str(os.getpid())); time.sleep(5)"
        "\nelse:\n time.sleep(.05); os._exit(0)"
    )
    started = time.monotonic_ns()
    job = client.RemoteJob([sys.executable, "-I", "-c", code], deadline_ns=started + 300_000_000)
    try:
        if hold_pipe:
            with pytest.raises(TimeoutError):
                job.finish(started + 300_000_000)
        else:
            assert job.finish(started + 300_000_000).returncode == 0
        assert time.monotonic_ns() - started < 2_300_000_000
        pid = int(pid_path.read_text())
        status = Path(f"/proc/{pid}/status")
        assert not status.exists() or "\nState:\tZ" in status.read_text()
    finally:
        if pid_path.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
