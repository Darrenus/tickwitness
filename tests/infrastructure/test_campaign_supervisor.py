"""Real process-group cleanup and bounded transport for the campaign deadline."""

import json
import os
import signal
import subprocess
import time

import pytest
from test_subprocess_replay import fake_interpreter

from tickwitness.infrastructure import campaign_supervisor
from tickwitness.infrastructure.campaign_supervisor import (
    MAX_CAMPAIGN_IPC_BYTES,
    supervise_campaign,
)


def _alive(pid):
    # An orphan may remain a zombie briefly before its OS parent reaps it. It
    # cannot run or retain campaign IO, so do not mistake it for a live worker.
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _assert_dead(pid):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and _alive(pid):
        time.sleep(0.01)
    try:
        assert not _alive(pid)
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize("limit", [True, 0, -1, 3_600_001, 1.5])
def test_timeout_is_exact_bounded_integer(limit):
    with pytest.raises(ValueError, match="timeout_ms"):
        supervise_campaign({}, timeout_ms=limit)


@pytest.mark.parametrize("payload", [{"deadline_ns": 1}, {"bad": float("nan")}, {"x": "a" * 70000}])
def test_bad_or_caller_deadline_frame_never_spawns(payload, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Bad frame cannot launch coordinator")

    monkeypatch.setattr(campaign_supervisor.subprocess, "Popen", forbidden)
    with pytest.raises(ValueError):
        supervise_campaign(payload, timeout_ms=100)


def test_request_contains_one_supervisor_absolute_deadline(tmp_path):
    executable = fake_interpreter(
        tmp_path,
        "import json,sys\nrequest=json.load(sys.stdin)\nprint(json.dumps(request))\n",
    )
    before = time.monotonic_ns()
    result = supervise_campaign(
        {"plan_id": "a" * 64}, timeout_ms=1000, python_executable=executable
    )
    payload = json.loads(result.stdout)
    assert result.reason == "finished" and result.exit_code == 0
    assert before < payload["deadline_ns"] <= time.monotonic_ns() + 1_000_000_000
    assert payload["plan_id"] == "a" * 64
    assert result.elapsed_ns >= 0
    assert result.stderr == b""


def test_application_budget_exit_is_a_finished_protocol_response(tmp_path):
    executable = fake_interpreter(
        tmp_path, 'import sys\nprint(\'{"reason":"storage_limit"}\')\nsys.exit(8)\n'
    )
    result = supervise_campaign({}, timeout_ms=1000, python_executable=executable)
    assert result.reason == "finished" and result.exit_code == 8
    assert json.loads(result.stdout) == {"reason": "storage_limit"}


def test_subsecond_deadline_terminates_coordinator_and_descendant(tmp_path):
    executable = fake_interpreter(
        tmp_path,
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])\n"
        "print(json.dumps({'coordinator':os.getpid(),'child':child.pid}),flush=True)\n"
        "time.sleep(20)\n",
    )
    started = time.monotonic()
    result = supervise_campaign({}, timeout_ms=600, python_executable=executable)
    assert result.reason == "time_limit" and result.exit_code == 8
    assert time.monotonic() - started < 3
    pids = json.loads(result.stdout)
    _assert_dead(pids["coordinator"])
    _assert_dead(pids["child"])


def test_successful_coordinator_exit_still_terminates_surviving_descendants(tmp_path):
    executable = fake_interpreter(
        tmp_path,
        "import json,os,subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])\n"
        "print(json.dumps({'coordinator':os.getpid(),'child':child.pid}),flush=True)\n",
    )
    started = time.monotonic()
    result = supervise_campaign({}, timeout_ms=5000, python_executable=executable)
    assert result.reason == "finished" and result.exit_code == 0
    assert time.monotonic() - started < 3
    pids = json.loads(result.stdout)
    _assert_dead(pids["coordinator"])
    _assert_dead(pids["child"])


@pytest.mark.parametrize("stream", [1, 2])
def test_coordinator_output_flood_stops_at_in_memory_cap(tmp_path, stream):
    executable = fake_interpreter(
        tmp_path,
        f"import os\nwhile True:\n    os.write({stream}, b'x' * 65536)\n",
    )
    result = supervise_campaign({}, timeout_ms=3000, python_executable=executable)
    assert result.reason == "worker_failed" and result.exit_code == 7
    assert len(result.stdout) <= MAX_CAMPAIGN_IPC_BYTES
    assert len(result.stderr) <= MAX_CAMPAIGN_IPC_BYTES
    assert sorted(path.name for path in tmp_path.iterdir()) == ["worker"]


def test_exact_output_allowance_does_not_reject_a_valid_transport(tmp_path):
    executable = fake_interpreter(
        tmp_path, f"import os\nos.write(1,b'x'*{MAX_CAMPAIGN_IPC_BYTES})\n"
    )
    result = supervise_campaign({}, timeout_ms=1000, python_executable=executable)
    assert result.reason == "finished" and result.exit_code == 0
    assert result.stdout == b"x" * MAX_CAMPAIGN_IPC_BYTES


def test_late_exit_is_not_accepted_even_when_poll_reports_exit(tmp_path, monkeypatch):
    executable = fake_interpreter(tmp_path, "import time\ntime.sleep(10)\n")
    clock = [100]

    def late_exchange(*_args, **_kwargs):
        clock[0] = 1_000_101
        return b'{"status":"completed"}', b""

    monkeypatch.setattr(campaign_supervisor, "_pipe_exchange", late_exchange)
    result = supervise_campaign(
        {},
        timeout_ms=1,
        python_executable=executable,
        clock_ns=lambda: clock[0],
    )
    assert result.reason == "time_limit" and result.exit_code == 8


def test_keyboard_interrupt_cleans_the_complete_worker_group(tmp_path, monkeypatch):
    marker = tmp_path / "pids.json"
    executable = fake_interpreter(
        tmp_path,
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])\n"
        f"with open({str(marker)!r},'w') as stream:\n"
        "    json.dump({'coordinator':os.getpid(),'child':child.pid},stream)\n"
        "time.sleep(20)\n",
    )

    def interrupted(*_args, **_kwargs):
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "Controlled worker did not start"
        raise KeyboardInterrupt("simulated user interruption")

    monkeypatch.setattr(campaign_supervisor, "_pipe_exchange", interrupted)
    with pytest.raises(KeyboardInterrupt):
        supervise_campaign({}, timeout_ms=5000, python_executable=executable)
    pids = json.loads(marker.read_bytes())
    _assert_dead(pids["coordinator"])
    _assert_dead(pids["child"])


def test_missing_coordinator_interpreter_is_explicit_failure(tmp_path):
    result = supervise_campaign({}, timeout_ms=1000, python_executable=tmp_path / "missing")
    assert result.reason == "worker_failed" and result.exit_code == 7
    assert result.stdout == b"" and len(result.stderr) <= MAX_CAMPAIGN_IPC_BYTES


def _signal_mask():
    return signal.pthread_sigmask(signal.SIG_BLOCK, set())


def test_launch_and_cleanup_defer_sigint_and_restore_the_original_mask(tmp_path, monkeypatch):
    executable = fake_interpreter(tmp_path, "print('{}')\n")
    previous = _signal_mask()
    actual_popen = campaign_supervisor.subprocess.Popen
    actual_killpg = campaign_supervisor.os.killpg
    observed = []

    def launch(*args, **kwargs):
        assert signal.SIGINT in _signal_mask()
        observed.append("launch")
        return actual_popen(*args, **kwargs)

    def terminate(group, requested_signal):
        assert signal.SIGINT in _signal_mask()
        observed.append("terminate")
        return actual_killpg(group, requested_signal)

    monkeypatch.setattr(campaign_supervisor.subprocess, "Popen", launch)
    monkeypatch.setattr(campaign_supervisor.os, "killpg", terminate)
    result = supervise_campaign({}, timeout_ms=1000, python_executable=executable)
    assert result.reason == "finished"
    assert "launch" in observed and "terminate" in observed
    assert _signal_mask() == previous


@pytest.mark.parametrize("failure", ["os_error", "interrupt"])
def test_launch_exception_restores_sigint_mask(monkeypatch, failure):
    previous = _signal_mask()

    def failed_launch(*_args, **_kwargs):
        assert signal.SIGINT in _signal_mask()
        if failure == "interrupt":
            raise KeyboardInterrupt("synthetic interrupted launch before a child exists")
        raise OSError(2, "synthetic missing interpreter")

    monkeypatch.setattr(campaign_supervisor.subprocess, "Popen", failed_launch)
    if failure == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            supervise_campaign({}, timeout_ms=1000)
    else:
        assert supervise_campaign({}, timeout_ms=1000).reason == "worker_failed"
    assert _signal_mask() == previous


def test_pending_sigint_at_launch_is_delivered_only_after_handle_assignment(tmp_path, monkeypatch):
    executable = fake_interpreter(tmp_path, "import time\ntime.sleep(20)\n")
    previous = _signal_mask()
    if signal.SIGINT in previous:
        pytest.skip("Pending-signal test requires the caller's SIGINT to be unblocked")
    actual_popen = campaign_supervisor.subprocess.Popen
    launched = []

    def interrupted_launch(*args, **kwargs):
        assert signal.SIGINT in _signal_mask()
        process = actual_popen(*args, **kwargs)
        launched.append(process)
        # This is a real pending signal, not a Python exception raised inside
        # Popen: restoration must happen after the caller owns the handle.
        signal.raise_signal(signal.SIGINT)
        return process

    monkeypatch.setattr(campaign_supervisor.subprocess, "Popen", interrupted_launch)
    with pytest.raises(KeyboardInterrupt):
        supervise_campaign({}, timeout_ms=1000, python_executable=executable)
    assert len(launched) == 1 and launched[0].poll() is not None
    assert _signal_mask() == previous
