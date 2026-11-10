"""Actual process/OS-limit transport and owned scratch; not native research positives."""

import errno
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from contextlib import suppress
from threading import Event, Thread, Timer

import pytest
from test_job_supervisor import _queued

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.jobs.control import build_job_control_policy
from tickwitness.infrastructure import job_control_bootstrap, job_control_runtime
from tickwitness.infrastructure.job_control_runtime import (
    JobControlStop,
    JobExecutionControl,
    check_control,
    control_admission,
    control_publication,
    current_control,
    reclaim_workspaces,
    validate_worker_limits,
)
from tickwitness.infrastructure.job_control_workspace import OwnedJobWorkspace
from tickwitness.infrastructure.job_controls import JobControlStore


def configured(tmp_path, **limits):
    store, queued = _queued(tmp_path)
    control = JobControlStore(tmp_path / "jobs", queued["job_id"])
    policy = build_job_control_policy(queued["job_id"], **limits)
    with store.coordinator() as owner:
        control.configure(policy)
        row = store.claim(
            queued["job_id"],
            expected_version=1,
            coordinator_id=owner,
            attempt_nonce="a" * 64,
            lease_token="b" * 64,
            now_ns=time.time_ns(),
        )
    return store, control, row


def ready(child):
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "Controlled child did not reach its ready gate"
    assert child.stdout.readline() == b"ready\n"


def close_pipes(child):
    for stream in (child.stdin, child.stdout, child.stderr):
        if stream is not None:
            stream.close()


def test_unconfigured_context_guards_are_noops():
    assert current_control() is None
    check_control()
    with control_admission(), control_publication():
        assert current_control() is None


def test_fixed_deadline_is_not_renewed_and_stop_bypasses_exception_catchers(tmp_path, monkeypatch):
    _, control, row = configured(tmp_path, max_wall_ns=1_000_000_000)
    clock = [100]
    monkeypatch.setattr(job_control_runtime.time, "monotonic_ns", lambda: clock[0])
    guard = JobExecutionControl(control)
    guard.bind(row)
    original = guard.deadline_ns
    with guard.activate():
        assert current_control() is guard
        clock[0] += 500_000_000
        check_control()
        assert guard.deadline_ns == original
        clock[0] = original
        with pytest.raises(JobControlStop) as stopped:
            try:
                check_control()
            except Exception:
                pytest.fail("Legacy Exception handling must not consume a control stop")
        assert stopped.value.code == "job_deadline_exceeded"
    assert current_control() is None
    result = guard.finish(row, cause="job_deadline_exceeded")
    assert result["stop_confirmed"] is True and result["worker_started"] is False
    assert result["timing_ns"]["elapsed"] == 1_000_000_000


def test_accepted_request_prevents_publication_without_creating_scratch(tmp_path):
    _, control, row = configured(tmp_path)
    accepted = control.request_cancel("cancel-a", now_ns=time.time_ns(), snapshot=row)
    guard = JobExecutionControl(control)
    guard.bind(row)
    with pytest.raises(JobControlStop) as stopped, guard.activate(), control_publication():
        pytest.fail("Cancellation must fence publication admission")
    assert stopped.value.code == "job_cancelled"
    assert control.publication_admission() is None
    assert not (control.directory / "workspaces").exists()
    assert (
        control.request_cancel("cancel-a", now_ns=time.time_ns(), snapshot=row)["request"]
        == (accepted["request"])
    )
    result = guard.finish(row, cause="job_cancelled")
    assert result["stop_confirmed"] is True and result["publication_admitted"] is False


def test_publication_admission_is_reentrant_and_late_cancel_is_not_accepted(tmp_path, monkeypatch):
    _, control, row = configured(tmp_path, max_wall_ns=1_000_000_000)
    guard = JobExecutionControl(control)
    guard.bind(row)
    with guard.activate(), control_publication():
        admission = control.publication_admission()
        assert admission["job_attempt_id"] == row["attempt"]["job_attempt_id"]
        monkeypatch.setattr(job_control_runtime.time, "monotonic_ns", lambda: guard.deadline_ns)
        check_control()  # An admitted commit is not retroactively undone.
        with control_publication(), control_admission():
            check_control()
        assert control.request_cancel("too-late", now_ns=time.time_ns(), snapshot=row)[
            "status"
        ] == ("too_late")
    assert control.cancel_request() is None
    result = guard.finish(row)
    assert result["publication_admitted"] is True and result["stop_confirmed"] is False


def test_busy_cancel_publication_is_waited_before_any_execution_admission(tmp_path, monkeypatch):
    _, control, row = configured(tmp_path)
    guard = JobExecutionControl(control)
    guard.bind(row)
    peer = JobControlStore(tmp_path / "jobs", row["job_id"])
    entered, release = Event(), Event()
    original_publish = peer._publish
    outcomes = []

    def slow_publish(directory, name, raw):
        if name == "cancel.json":
            entered.set()
            assert release.wait(timeout=5)
        return original_publish(directory, name, raw)

    def cancel():
        try:
            outcomes.append(
                peer.request_cancel("racing-cancel", now_ns=time.time_ns(), snapshot=row)
            )
        except BaseException as error:
            outcomes.append(error)

    monkeypatch.setattr(peer, "_publish", slow_publish)
    writer = Thread(target=cancel)
    writer.start()
    timer = Timer(0.05, release.set)
    try:
        assert entered.wait(timeout=5)
        timer.start()
        with pytest.raises(JobControlStop) as stopped, guard.admission():
            pytest.fail("Cancel publication must be observed before irreversible admission")
        assert stopped.value.code == "job_cancelled"
    finally:
        release.set()
        writer.join(timeout=5)
        timer.cancel()
    assert not writer.is_alive() and outcomes[0]["status"] == "accepted"
    assert control.publication_admission() is None


def test_requested_unsupported_hard_ceiling_refuses_without_changing_parent(tmp_path, monkeypatch):
    _, control, _ = configured(tmp_path)
    actual = job_control_bootstrap.resource.getrlimit
    limits_before = actual(job_control_bootstrap.resource.RLIMIT_NOFILE)

    def inherited(number):
        if number == job_control_bootstrap.resource.RLIMIT_NOFILE:
            return 32, 32
        return actual(number)

    monkeypatch.setattr(job_control_bootstrap.resource, "getrlimit", inherited)
    with pytest.raises(JobConflictError, match="inherited hard limit"):
        validate_worker_limits(control.policy())
    assert actual(job_control_bootstrap.resource.RLIMIT_NOFILE) == limits_before
    assert not (control.directory / "workspaces").exists()


def test_actual_bootstrap_caps_file_and_preserves_owned_lifetime_until_exit(tmp_path):
    _, control, row = configured(
        tmp_path,
        max_wall_ns=5_000_000_000,
        worker_cpu_seconds=2,
        max_file_bytes=1024,
        max_open_files=32,
    )
    guard = JobExecutionControl(control)
    guard.bind(row)
    command = (
        sys.executable,
        "-I",
        "-B",
        "-c",
        "import json,resource\nfrom pathlib import Path\n"
        "print(json.dumps({'cpu':resource.getrlimit(resource.RLIMIT_CPU),"
        "'file':resource.getrlimit(resource.RLIMIT_FSIZE),"
        "'fd':resource.getrlimit(resource.RLIMIT_NOFILE)}),flush=True)\n"
        "try:\n    Path('oversized').write_bytes(b'x'*4096)\n"
        "except OSError as error:\n    print(json.dumps({'errno':error.errno}),flush=True)\n"
        "    raise SystemExit(8)\n",
    )
    child = None
    with guard.activate(), guard.workspace(row) as scratch:
        try:
            child = guard.spawn(command, cwd=scratch)
            observed = json.loads(child.stdout.readline())
            assert observed == {"cpu": [2, 2], "file": [1024, 1024], "fd": [32, 32]}
            assert json.loads(child.stdout.readline()) == {"errno": errno.EFBIG}
            assert child.stdout.read() == b""
            guard.stop_process(child)
            assert guard.worker_exit_code == 8
            assert (scratch / "oversized").stat().st_size <= 1024
        finally:
            if child is not None:
                close_pipes(child)
    assert not scratch.exists()
    assert (scratch.parent / "workspace.json").is_file()
    result = guard.finish(row, cause="job_resource_limit")
    assert result["worker_started"] and result["cleanup_confirmed"] and result["stop_confirmed"]
    assert result["worker_exit_code"] == 8


@pytest.mark.parametrize("exit_code", [0, 8])
def test_session_anchor_holds_pipes_until_compute_exit_without_reaping_leader(tmp_path, exit_code):
    _, control, row = configured(tmp_path, max_wall_ns=5_000_000_000)
    guard = JobExecutionControl(control)
    guard.bind(row)
    child = None
    command = (
        sys.executable,
        "-I",
        "-B",
        "-c",
        "import json,os,sys,time; "
        "print(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp()}),flush=True); "
        "sys.stdin.buffer.readline(); "
        "os.close(1); os.close(2); time.sleep(0.15); "
        f"os._exit({exit_code})",
    )
    with guard.activate(), guard.workspace(row) as scratch:
        try:
            child = guard.spawn(command)
            observed = json.loads(child.stdout.readline())
            assert observed["pgid"] == child.pid and observed["pid"] != child.pid
            started = time.monotonic_ns()
            child.stdin.write(b"release\n")
            child.stdin.flush()
            assert child.stdout.read() == b""
            assert time.monotonic_ns() - started >= 100_000_000
            assert child.returncode is None  # No Popen.poll/wait before the one group signal.
            guard.stop_process(child)
            assert guard.worker_exit_code == exit_code
        finally:
            if child is not None:
                close_pipes(child)
    assert not scratch.exists()


def test_signal_permission_requires_actual_exit_and_group_absence(tmp_path, monkeypatch):
    _, control, row = configured(tmp_path)
    guard = JobExecutionControl(control)
    guard.bind(row)
    child = None
    actual_kill = os.killpg
    with guard.activate(), guard.workspace(row) as scratch:
        try:
            child = guard.spawn((sys.executable, "-I", "-B", "-c", "print('ready',flush=True)"))
            ready(child)
            assert child.stdout.read() == b""  # EOF without poll/wait: leader remains unreaped.
            signals = []

            def exited_permission(pid, number):
                signals.append(number)
                if number == signal.SIGKILL:
                    raise PermissionError(errno.EPERM, "Controlled exited-leader Darwin race")
                return actual_kill(pid, number)

            monkeypatch.setattr(job_control_runtime.os, "killpg", exited_permission)
            guard.stop_process(child)
            assert guard.worker_exit_code == 0
            assert signals.count(signal.SIGKILL) == 1 and 0 in signals
        finally:
            if child is not None:
                close_pipes(child)
    assert not scratch.exists()
    assert guard.finish(row)["stop_confirmed"] is False


def test_live_signal_uncertainty_retains_workspace_and_cannot_confirm_stop(tmp_path, monkeypatch):
    _, control, row = configured(tmp_path)
    guard = JobExecutionControl(control)
    guard.bind(row)
    actual_kill = os.killpg
    child = None
    scratch = None

    def denied(_pid, _signal):
        raise PermissionError(errno.EPERM, "Controlled live-child signal uncertainty")

    try:
        with pytest.raises(JobStoreError), guard.activate(), guard.workspace(row) as scratch:
            child = guard.spawn(
                (
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    "from threading import Event; print('ready',flush=True); Event().wait(30)",
                )
            )
            ready(child)
            monkeypatch.setattr(job_control_runtime.os, "killpg", denied)
            guard.stop_process(child)
        assert scratch.is_dir()
        result = guard.finish(row, cause="job_control_error", diagnostic="uncertain group")
        assert result["worker_started"] and result["worker_exit_code"] is None
        assert not result["workspace_removed"] and not result["stop_confirmed"]
    finally:
        if child is not None:
            with suppress(ProcessLookupError):
                actual_kill(child.pid, signal.SIGKILL)
            child.wait(timeout=10)
            close_pipes(child)


def test_replaced_scratch_is_not_followed_or_reported_cleaned(tmp_path):
    _, control, row = configured(tmp_path)
    guard = JobExecutionControl(control)
    guard.bind(row)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"foreign evidence")
    with pytest.raises(JobStoreError), guard.activate(), guard.workspace(row) as scratch:
        scratch.rmdir()
        scratch.symlink_to(outside, target_is_directory=True)
    assert (outside / "keep").read_bytes() == b"foreign evidence"
    result = guard.finish(row, cause="job_control_error")
    assert result["workspace_removed"] is False and result["cleanup_confirmed"] is False


def test_reclamation_refuses_live_lifetime_then_removes_only_reconciled_scratch(
    tmp_path, monkeypatch
):
    store, control, row = configured(tmp_path)
    workspace = OwnedJobWorkspace(control.directory, control.policy().policy_id, row)
    child = None
    actual_kill = os.killpg
    try:
        workspace.create()
        fd = workspace.lifetime_fd
        child = subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import os,sys; os.fstat(int(sys.argv[1])); "
                "print('ready',flush=True); sys.stdin.buffer.read()",
                str(fd),
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            pass_fds=(fd,),
        )
        workspace.close_parent_lifetime()
        ready(child)
        with store.coordinator():
            lost = store.reconcile_orphans(now_ns=time.time_ns())[0]
        assert lost["state"] == "LOST"

        def forbidden(*_args):
            raise AssertionError("Reclamation must never signal a persisted PID")

        monkeypatch.setattr(job_control_runtime.os, "killpg", forbidden)
        with pytest.raises(JobConflictError, match="lifetime"):
            reclaim_workspaces(control, lost)
        assert workspace.scratch.is_dir()
        child.stdin.close()
        child.wait(timeout=10)
        outcome = reclaim_workspaces(control, lost)
        assert outcome["workspace_removed"] is True and outcome["pid_signalled"] is False
        assert not workspace.scratch.exists()
        assert (workspace.path / "workspace.json").is_file()
        assert reclaim_workspaces(control, lost)["workspace_removed"] is True
    finally:
        workspace.close()
        if child is not None:
            if child.returncode is None:
                with suppress(ProcessLookupError):
                    actual_kill(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            close_pipes(child)


def test_control_result_after_real_commit_response_loss_is_not_auto_retried(tmp_path, monkeypatch):
    _, control, row = configured(tmp_path)
    guard = JobExecutionControl(control)
    guard.bind(row)
    actual_write = control.write_result
    calls = []

    def committed_then_lost(document):
        calls.append(document)
        actual_write(document)
        raise JobStoreError("Controlled post-control-result commit response loss")

    monkeypatch.setattr(control, "write_result", committed_then_lost)
    with pytest.raises(JobStoreError, match="response loss"):
        guard.finish(row, cause="job_control_error")
    assert control.result()["cause"] == "job_control_error"
    with pytest.raises(JobStoreError, match="never auto-retry"):
        guard.finish(row, cause="job_control_error")
    assert len(calls) == 1
