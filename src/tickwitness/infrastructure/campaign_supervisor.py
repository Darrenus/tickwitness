"""Supervise one trusted campaign process with a single absolute execution deadline.

Pipes are bounded in memory. The session's process group is terminated on every
exit path, including successful coordinator exit with surviving descendants.
Finalization and independent evidence inspection are the caller's separate phase.
This is not a malicious-code sandbox, filesystem quota or memory quota.
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal, cast

MAX_CAMPAIGN_IPC_BYTES = 64 * 1024
_READ_CHUNK = 64 * 1024


class _PipeDeadlineExceeded(TimeoutError):
    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout, self.stderr = stdout, stderr
        super().__init__("Absolute execution deadline reached")


class _PipeOutputExceeded(ValueError):
    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout, self.stderr = stdout, stderr
        super().__init__("Worker output exceeded its bounded pipe allowance")


def _pipe_exchange(
    process: subprocess.Popen[bytes],
    payload: bytes,
    *,
    deadline_ns: int,
    stdout_limit: int,
    stderr_limit: int,
    clock_ns: Callable[[], int],
    on_process_exit: Callable[[], None] | None = None,
) -> tuple[bytes, bytes]:
    """Pump three nonblocking pipes; never collect more than either output cap.

    A single detection byte may be read beyond the allowance but is never
    appended. It detects flooding without a regular-file spool or unbounded
    communicate() accumulation. The parent still owns termination/reaping.
    """
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise ValueError("Pipe supervision requires stdin, stdout and stderr pipes")
    streams: tuple[IO[bytes], ...] = (process.stdin, process.stdout, process.stderr)
    output, errors = bytearray(), bytearray()
    offset = 0
    exit_observed = False
    with selectors.DefaultSelector() as selector:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
        if payload:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = deadline_ns - clock_ns()
            if remaining <= 0:
                raise _PipeDeadlineExceeded(bytes(output), bytes(errors))
            if not exit_observed and process.poll() is not None:
                exit_observed = True
                if on_process_exit is not None:
                    on_process_exit()
            events = selector.select(timeout=min(0.05, remaining / 1_000_000_000))
            for key, _mask in events:
                stream = cast("IO[bytes]", key.fileobj)
                if key.data == "stdin":
                    try:
                        count = os.write(stream.fileno(), payload[offset : offset + _READ_CHUNK])
                    except BrokenPipeError:
                        count = 0
                    except BlockingIOError:
                        continue
                    offset += count
                    if count == 0 or offset == len(payload):
                        selector.unregister(stream)
                        stream.close()
                    continue
                destination, limit = (
                    (output, stdout_limit) if key.data == "stdout" else (errors, stderr_limit)
                )
                try:
                    data = os.read(stream.fileno(), min(_READ_CHUNK, limit - len(destination) + 1))
                except BlockingIOError:
                    continue
                if not data:
                    selector.unregister(stream)
                    stream.close()
                elif len(data) > limit - len(destination):
                    raise _PipeOutputExceeded(bytes(output), bytes(errors))
                else:
                    destination.extend(data)
        # A process can close its pipes before it exits. Waiting remains under
        # the same absolute deadline rather than resetting a timeout here.
        while process.poll() is None:
            remaining = deadline_ns - clock_ns()
            if remaining <= 0:
                raise _PipeDeadlineExceeded(bytes(output), bytes(errors))
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=min(0.05, remaining / 1_000_000_000))
        if not exit_observed and on_process_exit is not None:
            on_process_exit()
        if clock_ns() >= deadline_ns:
            raise _PipeDeadlineExceeded(bytes(output), bytes(errors))
    return bytes(output), bytes(errors)


def _close_pipes(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


@contextmanager
def _defer_sigint() -> Iterator[None]:
    """Deliver interruption only after a child handle is owned or reaped.

    A newly exec'd coordinator inherits this temporary mask and restores SIGINT
    at its entry point. No Python preexec callback is installed.
    """
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    # Popen(start_new_session=True) establishes pgid == pid. Never target the
    # caller's group, even if an unexpected/mocked process violates that rule.
    with _defer_sigint():
        if process.pid == os.getpgrp():
            raise RuntimeError("Refusing to terminate the supervisor's own process group")
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


@dataclass(frozen=True, slots=True)
class CampaignSupervision:
    reason: Literal["finished", "time_limit", "worker_failed"]
    exit_code: int
    elapsed_ns: int
    stdout: bytes
    stderr: bytes


def supervise_campaign(
    payload: dict[str, object],
    *,
    timeout_ms: int,
    python_executable: Path | None = None,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> CampaignSupervision:
    """Run one coordinator session; normal application exit8 is still 'finished'.

    The caller interprets the worker's small protocol response and writes the
    separately reserved terminal record. Elapsed time includes cleanup, which
    can require OS scheduling after the execution deadline; it is not a promise
    of real-time process delivery or a bound on the caller's final inspection.
    """
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 3_600_000:
        raise ValueError("Campaign timeout_ms must be an integer in 1..3600000")
    if not isinstance(payload, dict) or "deadline_ns" in payload:
        raise ValueError("Campaign payload must be an object without a supplied deadline")
    if os.name != "posix":
        raise ValueError("Campaign process supervision requires POSIX")
    started = clock_ns()
    deadline = started + timeout_ms * 1_000_000
    frame = {**payload, "deadline_ns": deadline}
    try:
        raw = json.dumps(
            frame, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("Campaign IPC frame must be bounded finite UTF-8 JSON") from error
    if len(raw) > MAX_CAMPAIGN_IPC_BYTES:
        raise ValueError("Campaign IPC frame exceeds 64 KiB")
    if clock_ns() >= deadline:
        return CampaignSupervision("time_limit", 8, max(0, clock_ns() - started), b"", b"")
    executable = str((python_executable or Path(sys.executable)).absolute())
    process: subprocess.Popen[bytes] | None = None
    reason: Literal["finished", "time_limit", "worker_failed"] = "worker_failed"
    exit_code, output, errors = 7, b"", b""
    try:
        with _defer_sigint():
            process = subprocess.Popen(
                [executable, "-I", "-m", "tickwitness.infrastructure.budgeted_campaign_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        active_process = process
        output, errors = _pipe_exchange(
            process,
            raw,
            deadline_ns=deadline,
            stdout_limit=MAX_CAMPAIGN_IPC_BYTES,
            stderr_limit=MAX_CAMPAIGN_IPC_BYTES,
            clock_ns=clock_ns,
            on_process_exit=lambda: _terminate_group(active_process),
        )
        reason = "finished"
        exit_code = process.returncode if process.returncode is not None else 7
    except _PipeDeadlineExceeded as error:
        reason, exit_code, output, errors = "time_limit", 8, error.stdout, error.stderr
    except _PipeOutputExceeded as error:
        reason, exit_code, output, errors = "worker_failed", 7, error.stdout, error.stderr
        if not errors:
            errors = str(error).encode("utf-8")
    except OSError as error:
        reason, exit_code = "worker_failed", 7
        errors = f"Cannot supervise campaign worker (errno {error.errno})".encode("ascii")
    finally:
        if process is not None:
            with _defer_sigint():
                try:
                    _terminate_group(process)
                finally:
                    _close_pipes(process)
    # Reject a late completion even if the process exited just before polling.
    if reason == "finished" and clock_ns() >= deadline:
        reason, exit_code = "time_limit", 8
    return CampaignSupervision(reason, exit_code, max(0, clock_ns() - started), output, errors)
