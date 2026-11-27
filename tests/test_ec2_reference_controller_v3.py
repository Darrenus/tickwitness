"""Remote regressions of the actual detached Controller, never AWS qualification."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/ec2_reference_handoff_v3.py"
SPEC = importlib.util.spec_from_file_location("ec2_controller_v3_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ops = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ops
SPEC.loader.exec_module(ops)
SOURCE = "a" * 40
BOOT = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(ops, "ROOT", tmp_path / "reference")
    parent = tmp_path / "operations"
    parent.mkdir(mode=0o700)
    store = ops.Store(
        parent / ops.RUN_ID, owner=os.getuid(), trust_root=tmp_path, archive_base=tmp_path
    )
    report = ops.ROOT / "runs" / ops.RUN_ID / "qualification-report.json"
    report.parent.mkdir(parents=True, mode=0o700)

    class Clock:
        value = 1_000_000_000
        acknowledge = True
        callback = None

        def now(self):
            return self.value

        def sleep(self, seconds):
            self.value += max(1, int(seconds * 1e9))
            if self.callback:
                self.callback()
            elif self.acknowledge and store.exists("handoff-ready.json"):
                ready = store.record_read("handoff-ready", SOURCE, BOOT)
                supplied = {
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
                }
                ops.acknowledge(SOURCE, store, host, self, supplied)
                self.acknowledge = False

    clock = Clock()

    class Host:
        after_failure = False
        before_failure = False
        stop_calls = 0
        guard = ops.GuardIdentity(
            "b" * 32,
            ops.ProcessIdentity(10, 100, ops.main_argv(SOURCE), "/system.slice/" + ops.UNIT, 1),
            "actual trusted ExecStart",
            "/system.slice/" + ops.UNIT,
        )

        def boot(self):
            return BOOT

        def master(self, source):
            return ops.ProcessIdentity(20, 200, ops.controller_argv(source), self.guard.cgroup, 10)

        def live(self, source, start):
            assert source == SOURCE and start["controller_pid"] == 20
            return self.guard

        def before_preparation(self, source, active_store):
            assert active_store.exists("controller-start.json")
            if self.before_failure:
                raise ops.Refused("preparation observer refusal")

        def after_preparation(self, source, active_store):
            if self.after_failure:
                raise ops.Refused("source/history observer refusal")

        def stop(self, guard):
            assert guard == self.guard
            self.stop_calls += 1

    host = Host()

    class Runner:
        def __init__(self):
            self.calls = []
            self.results = {
                name: ops.PhaseResult(0)
                for name in (
                    "preparation",
                    "qualifier",
                    "export",
                )
            }
            self.costs = {name: 1_000_000_000 for name in self.results}
            self.spawn_failure = None
            self.before = None

        def run(self, argv, deadline, grace_deadline, stdout, stderr):
            name = "qualifier" if stdout.stem == "qualification" else stdout.stem
            self.calls.append((name, list(argv), deadline, grace_deadline, clock.now()))
            # This is the same Controller's launch port, not another state machine.
            assert controller.invoked[name] is True
            assert store.exists("controller-start.json")
            if name == "export":
                assert store.exists("qualifier-exit.json") and store.exists("export-call.json")
            if self.before:
                self.before(name)
            if name == self.spawn_failure:
                raise OSError("uncertain launch")
            store.write(stdout.name, (name + " original stdout\n").encode())
            store.write(stderr.name, b"")
            clock.value += self.costs[name]
            if name == "qualifier":
                report.write_bytes(b'{"actual":"retained original report"}\n')
            if name == "export" and self.results[name].returncode == 0:
                start = store.record_read("controller-start", SOURCE, BOOT)
                store.record(
                    "export-consumption",
                    controller.base("export-consumption")
                    | {
                        "controller_pid": start["controller_pid"],
                        "controller_start_ticks": start["controller_start_ticks"],
                        "started_ns": clock.now(),
                    },
                    SOURCE,
                    BOOT,
                )
                store.write("evidence.tar.gz", b"the actual child archive bytes")
            return self.results[name]

    runner = Runner()
    controller = ops.Controller(SOURCE, store, host, runner, clock)
    return SimpleNamespace(
        store=store, host=host, clock=clock, runner=runner, controller=controller, report=report
    )


@pytest.mark.parametrize("original", [0, 1, 74, 255])
def test_acknowledged_archive_preserves_original_normal_qualifier_exit(environment, original):
    env = environment
    env.runner.results["qualifier"] = ops.PhaseResult(original)
    assert env.controller.run() == original
    result = env.store.record_read("controller-result", SOURCE, BOOT)
    qualifier = env.store.record_read("qualifier-exit", SOURCE, BOOT)
    assert result["handoff_status"] == "acknowledged"
    assert result["qualifier_invoked"] is qualifier["invoked"] is True
    assert result["qualifier_returncode"] == qualifier["returncode"] == original
    assert result["preparation_returncode"] == result["export_returncode"] == 0
    assert set(result) == ops.KEYS["controller-result"]
    assert qualifier["report"]["path"] == str(env.report)
    assert [call[0] for call in env.runner.calls] == ["preparation", "qualifier", "export"]
    assert env.host.stop_calls == 0  # Exit lets the independent original hook own Stop.


@pytest.mark.parametrize("original", [None, -9, -15, 256])
def test_unknown_signal_or_non_normal_code_never_becomes_a_success(environment, original):
    env = environment
    env.runner.results["qualifier"] = ops.PhaseResult(original)
    assert env.controller.run() == 74
    assert env.store.record_read("qualifier-exit", SOURCE, BOOT)["returncode"] == original
    assert (
        env.store.record_read("controller-result", SOURCE, BOOT)["qualifier_returncode"] == original
    )
    assert len(env.runner.calls) == 3


@pytest.mark.parametrize("phase", ["preparation", "qualifier", "export"])
def test_spawn_failure_is_invoked_and_unknown_without_second_launch(environment, phase):
    env = environment
    env.runner.spawn_failure = phase
    assert env.controller.run() == 74
    result = env.store.record_read("controller-result", SOURCE, BOOT)
    assert result[phase + "_invoked"] is True
    assert result[phase + "_returncode"] is None
    assert [call[0] for call in env.runner.calls].count(phase) == 1
    assert [call[0] for call in env.runner.calls].count("export") == 1
    if phase == "preparation":
        assert result["qualifier_invoked"] is False
        assert env.store.record_read("qualifier-exit", SOURCE, BOOT)["returncode"] is None


@pytest.mark.parametrize("phase", ["preparation", "qualifier", "export"])
def test_phase_timeout_retains_signed_code_and_original_ceiling(environment, phase):
    env = environment
    env.runner.results[phase] = ops.PhaseResult(-9, True)
    assert env.controller.run() == 74
    assert env.controller.results[phase].returncode == -9
    expected = {"preparation": 480, "qualifier": 612, "export": 25}
    for name, _, deadline, grace, started in env.runner.calls:
        assert deadline == min(started + expected[name] * 1_000_000_000, env.controller.deadline)
        assert grace == min(deadline + ops.GRACE_NS, env.controller.deadline + ops.GRACE_NS)
    assert env.controller.deadline == env.controller.started + ops.OUTER_NS


def test_shortened_outer_remaining_time_is_not_renewed(environment, monkeypatch):
    env = environment
    env.clock.acknowledge = False
    monkeypatch.setattr(
        env.host,
        "before_preparation",
        lambda *args: setattr(env.clock, "value", env.clock.now() + 1490_000_000_000),
    )
    assert env.controller.run() == 74
    assert [call[0] for call in env.runner.calls] == ["export"]
    assert env.runner.calls[0][2] == env.controller.deadline
    ready = env.store.record_read("handoff-ready", SOURCE, BOOT)
    assert ready["deadline_ns"] == env.controller.deadline
    assert not env.store.exists("controller-result.json")


def test_preparation_observation_consumes_the_same_480_second_phase(environment, monkeypatch):
    env = environment
    monkeypatch.setattr(
        env.host,
        "before_preparation",
        lambda *args: setattr(env.clock, "value", env.clock.now() + 479_000_000_000),
    )
    assert env.controller.run() == 74
    preparation = env.runner.calls[0]
    assert preparation[0] == "preparation"
    assert preparation[2] == env.controller.started + 480_000_000_000
    assert preparation[2] - preparation[4] == 1_000_000_000
    assert env.controller.invoked["qualifier"] is False
    assert env.controller.results["preparation"].returncode == 0
    assert env.controller.results["preparation"].timed_out is True


@pytest.mark.parametrize("fault", ["before_failure", "after_failure"])
def test_observer_refusal_exports_once_without_qualification(environment, fault):
    env = environment
    setattr(env.host, fault, True)
    assert env.controller.run() == 74
    result = env.store.record_read("controller-result", SOURCE, BOOT)
    assert result["qualifier_invoked"] is False
    assert result["qualifier_returncode"] is None
    assert [call[0] for call in env.runner.calls].count("export") == 1


def test_existing_operation_permanently_prevents_even_preparation(environment):
    env = environment
    env.store.operation.mkdir(mode=0o700)
    with pytest.raises(FileExistsError):
        env.controller.run()
    assert env.runner.calls == []


def test_failed_operation_directory_fsync_remains_consumed(environment, monkeypatch):
    env = environment
    monkeypatch.setattr(
        env.store,
        "fsync_directory",
        lambda _: (_ for _ in ()).throw(OSError("uncertain directory fsync")),
    )
    with pytest.raises(OSError, match="uncertain"):
        env.controller.run()
    with pytest.raises(FileExistsError):
        env.controller.run()
    assert env.runner.calls == []


def test_lost_execution_connection_does_not_enter_the_controller_ports(environment):
    env = environment
    env.clock.acknowledge = False
    assert env.controller.run() == 74
    assert env.store.record_read("controller-result", SOURCE, BOOT)["handoff_status"] == "expired"
    assert env.clock.now() >= env.store.record_read("handoff-ready", SOURCE, BOOT)["deadline_ns"]
    assert [call[0] for call in env.runner.calls] == ["preparation", "qualifier", "export"]


def test_export_failure_keeps_original_qualifier_exit_and_never_reexports(environment):
    env = environment
    env.runner.results["qualifier"] = ops.PhaseResult(1)
    env.runner.results["export"] = ops.PhaseResult(74)
    assert env.controller.run() == 74
    assert env.store.record_read("qualifier-exit", SOURCE, BOOT)["returncode"] == 1
    assert not env.store.exists("handoff-ready.json")
    with pytest.raises(ops.Refused, match="already invoked"):
        env.controller.phase("export", ["unused"], 25)
    assert [call[0] for call in env.runner.calls].count("export") == 1


@pytest.mark.parametrize("name", ["qualifier-exit", "export-call", "controller-result"])
def test_partial_record_is_never_overwritten_or_retried(environment, monkeypatch, name):
    env = environment
    original = env.store.record
    attempts = []

    def fail(selected, value, source, boot, **kwargs):
        attempts.append(selected)
        if selected == name:
            env.store.write(selected + ".json", b"{")
            raise OSError("partial authority remains")
        original(selected, value, source, boot, **kwargs)

    monkeypatch.setattr(env.store, "record", fail)
    assert env.controller.run() == 74
    assert (env.store.operation / (name + ".json")).read_bytes() == b"{"
    assert attempts.count(name) == 1
    assert [call[0] for call in env.runner.calls].count("export") <= 1


@pytest.mark.skipif(sys.platform != "linux", reason="Real Linux process-group producer")
@pytest.mark.parametrize("ignore_term", [False, True])
def test_real_child_term_or_kill_has_one_parent_owned_original_deadline(tmp_path, ignore_term):
    store = ops.Store(tmp_path, owner=os.getuid(), trust_root=tmp_path, archive_base=tmp_path)
    clock = ops.Clock()
    runner = ops.ProcessRunner(clock, store)
    child = (
        "import os,signal,time; "
        + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if ignore_term else "")
        + "print(os.getpid(),os.getppid(),flush=True); time.sleep(30)"
    )
    started = clock.now()
    result = runner.run(
        [sys.executable, "-I", "-u", "-c", child],
        started + 1_000_000_000,
        started + 2_000_000_000,
        tmp_path / "child.stdout",
        tmp_path / "child.stderr",
    )
    assert result.timed_out is True
    assert result.returncode == (-signal.SIGKILL if ignore_term else -signal.SIGTERM)
    pid, parent = map(int, (tmp_path / "child.stdout").read_text().split())
    assert parent == os.getpid()
    assert clock.now() - started < 5_000_000_000
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


@pytest.mark.skipif(sys.platform != "linux", reason="Independent Linux lifecycle surrogate")
@pytest.mark.parametrize("death", ["normal", "TERM", "KILL"])
def test_independent_parent_records_stop_after_controller_normal_or_signal(tmp_path, death):
    # This harmless parent substitutes for systemd/the existing Stop hook. It is
    # explicitly not a claim that a controller's finally block survives SIGKILL.
    record = tmp_path / "independent-stop.json"
    parent = r"""
import json, os, select, signal, subprocess, sys
from pathlib import Path
delay = '0.05' if sys.argv[2] == 'normal' else '30'
child = subprocess.Popen([sys.executable, '-I', '-u', '-c',
    'import time; print("live",flush=True); time.sleep(' + delay + ')'], stdout=subprocess.PIPE)
try:
    assert select.select([child.stdout], [], [], 2)[0]
    assert child.stdout.readline() == b'live\n'
    mode = sys.argv[2]
    if mode != 'normal':
        os.kill(child.pid, getattr(signal, 'SIG' + mode))
    code = child.wait(timeout=3)
finally:
    if child.poll() is None:
        child.kill()
        child.wait(timeout=3)
Path(sys.argv[1]).write_text(json.dumps({'stop_observed_by_parent': True, 'returncode': code}))
"""
    supervisor = subprocess.Popen(
        [sys.executable, "-I", "-c", parent, str(record), death],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, stderr = supervisor.communicate(timeout=10)
        assert supervisor.returncode == 0, stderr
    finally:
        if supervisor.poll() is None:
            os.killpg(supervisor.pid, signal.SIGKILL)
            supervisor.wait(timeout=3)
    evidence = json.loads(record.read_bytes())
    assert evidence["stop_observed_by_parent"] is True
    assert evidence["returncode"] == {"normal": 0, "TERM": -15, "KILL": -9}[death]


def test_no_public_wait_test_mode_or_alternate_run_is_accepted():
    for arguments in (
        ["wait"],
        ["run", "--test-mode"],
        ["run", "--source-revision", SOURCE, "--run-id", ops.OLD_RUNS[-1]],
        ["run", "--source-rev", SOURCE, "--run-id", ops.RUN_ID],
    ):
        with pytest.raises(SystemExit):
            ops._arguments(arguments)
