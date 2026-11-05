"""Signal uncertainty cannot mask a live child or replace an observed exit."""

import errno
import os
import selectors
import signal
import subprocess
import sys
from contextlib import suppress
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import job_supervisor


def _ready(child):
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "Controlled child did not reach its ready gate"
    assert child.stdout.readline() == b"ready\n"


@pytest.mark.parametrize("exit_code", [0, 7])
def test_eperm_after_real_child_exit_preserves_observed_status(monkeypatch, exit_code):
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", f"raise SystemExit({exit_code})"],
        start_new_session=True,
    )
    assert child.wait(timeout=10) == exit_code

    def denied(*args):
        raise PermissionError(errno.EPERM, "Controlled group-signal error after actual exit")

    monkeypatch.setattr(job_supervisor.os, "killpg", denied)
    job_supervisor._terminate(child)
    assert child.returncode == exit_code


def test_eperm_after_real_signal_exit_preserves_negative_status(monkeypatch):
    child = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; from threading import Event; print('ready',flush=True); Event().wait(30)",
        ],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    original_kill = os.killpg
    try:
        _ready(child)
        original_kill(child.pid, signal.SIGKILL)
        assert child.wait(timeout=10) == -signal.SIGKILL

        def denied(*args):
            raise PermissionError(errno.EPERM, "Controlled group-signal error after SIGKILL")

        monkeypatch.setattr(job_supervisor.os, "killpg", denied)
        job_supervisor._terminate(child)
        assert child.returncode == -signal.SIGKILL
    finally:
        with suppress(ProcessLookupError):
            original_kill(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
        child.stdout.close()


def test_live_eperm_remains_visible_and_child_is_not_reported_reaped(monkeypatch):
    child = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "from threading import Event; print('ready',flush=True); Event().wait(30)",
        ],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    original_kill = os.killpg
    try:
        _ready(child)

        def denied(*args):
            raise PermissionError(errno.EPERM, "Controlled live-child permission uncertainty")

        monkeypatch.setattr(job_supervisor.os, "killpg", denied)
        with pytest.raises(PermissionError, match="live-child"):
            job_supervisor._terminate(child)
        assert child.poll() is None
    finally:
        with suppress(ProcessLookupError):
            original_kill(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
        child.stdout.close()


def test_unrelated_signal_io_error_is_not_excused_by_an_exited_child(monkeypatch):
    child = SimpleNamespace(pid=os.getpgrp() + 100_000, poll=lambda: 0)

    def broken(*args):
        raise OSError(errno.EIO, "Controlled signal IO failure")

    monkeypatch.setattr(job_supervisor.os, "killpg", broken)
    with pytest.raises(OSError, match="signal IO"):
        job_supervisor._signal_group(child)


def test_own_process_group_never_reaches_signal_syscall(monkeypatch):
    def forbidden(*args):
        raise AssertionError("Own process group must never be signalled")

    monkeypatch.setattr(job_supervisor.os, "killpg", forbidden)
    with pytest.raises(RuntimeError, match="own process group"):
        job_supervisor._signal_group(SimpleNamespace(pid=os.getpgrp()))
