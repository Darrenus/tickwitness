"""Standalone stdlib-only worker bootstrap; executed by file path before imports."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import signal
import stat
import sys
import time
from collections.abc import Sequence

JOB_DEADLINE_ENV = "TICKWITNESS_JOB_CONTROL_DEADLINE_NS"
_LIMIT_FIELDS = {
    "max_wall_ns",
    "worker_cpu_seconds",
    "max_file_bytes",
    "max_open_files",
    "cleanup_grace_ns",
}


def checked_limits(document: object) -> dict[str, int]:
    """Check the actual host ceilings without changing the coordinator's limits."""
    if os.name != "posix" or not isinstance(document, dict):
        raise ValueError("Job resource enforcement requires POSIX")
    if not callable(getattr(os, "fork", None)):
        raise ValueError("Job resource enforcement requires an owned fork/session anchor")
    if set(document) != {"kind", "schema_version", "job_id", "limits"}:
        raise ValueError("Unsupported Job control policy fields")
    if (
        document["kind"] != "job_control_policy_v1"
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
    ):
        raise ValueError("Unsupported Job control policy")
    job_id = document["job_id"]
    if (
        not isinstance(job_id, str)
        or len(job_id) != 64
        or any(item not in "0123456789abcdef" for item in job_id)
    ):
        raise ValueError("Job bootstrap identity differs")
    values = document["limits"]
    if not isinstance(values, dict) or set(values) != _LIMIT_FIELDS:
        raise ValueError("Job resource fields differ")
    bounds = {
        "max_wall_ns": (1_000_000_000, 3_600_000_000_000),
        "worker_cpu_seconds": (1, 3600),
        "max_file_bytes": (1024, 1_073_741_824),
        "max_open_files": (32, 4096),
        "cleanup_grace_ns": (100_000_000, 5_000_000_000),
    }
    for name, (low, high) in bounds.items():
        value = values[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Job resource value is outside its frozen bounds: " + name)
    limits: dict[str, int] = dict(values)
    for symbol, name in (
        ("RLIMIT_CPU", "worker_cpu_seconds"),
        ("RLIMIT_FSIZE", "max_file_bytes"),
        ("RLIMIT_NOFILE", "max_open_files"),
    ):
        number = getattr(resource, symbol, None)
        if number is None:
            raise ValueError("Requested worker ceiling is unsupported: " + symbol)
        _soft, hard = resource.getrlimit(number)
        if hard != resource.RLIM_INFINITY and limits[name] > hard:
            raise ValueError("Requested worker ceiling exceeds the inherited hard limit: " + symbol)
    return limits


def _arm(deadline: int) -> None:
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM})
    remaining = deadline - time.monotonic_ns()
    if remaining <= 0:
        raise ValueError("Job total deadline expired during worker setup")
    signal.setitimer(signal.ITIMER_REAL, remaining / 1_000_000_000)


def _diagnostic(error: BaseException) -> None:
    try:
        sys.stderr.write(("job_resource_bootstrap_error: " + str(error))[:2048] + "\n")
        sys.stderr.flush()
    except OSError:
        pass


def main(arguments: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    try:
        if len(args) < 6 or args[4] != "--":
            raise ValueError("Job bootstrap arguments differ")
        raw = args[0].encode("utf-8")
        if len(raw) > 4096 or hashlib.sha256(raw).hexdigest() != args[1]:
            raise ValueError("Job bootstrap policy digest differs")
        document = json.loads(raw)
        if json.dumps(document, sort_keys=True, separators=(",", ":")).encode() != raw:
            raise ValueError("Job bootstrap policy is not canonical")
        limits = checked_limits(document)
        deadline, lifetime = int(args[2]), int(args[3])
        lock = os.fstat(lifetime)
        if not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.geteuid() or lock.st_nlink != 1:
            raise ValueError("Job lifetime descriptor is not an owned regular file")
        if lock.st_size != 0:
            raise ValueError("Job lifetime lock is not empty")
        remaining = deadline - time.monotonic_ns()
        if remaining <= 0 or remaining > limits["max_wall_ns"]:
            raise ValueError("Job total deadline has expired or exceeds its policy")
        for number, name in (
            (resource.RLIMIT_CPU, "worker_cpu_seconds"),
            (resource.RLIMIT_FSIZE, "max_file_bytes"),
            (resource.RLIMIT_NOFILE, "max_open_files"),
        ):
            resource.setrlimit(number, (limits[name], limits[name]))
        if hasattr(resource, "RLIMIT_CORE"):
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.set_inheritable(lifetime, True)
        os.environ[JOB_DEADLINE_ENV] = str(deadline)
        _arm(deadline)
        command = args[5:]
        if not command or not os.path.isabs(command[0]):
            raise ValueError("Worker executable must be an absolute allowlisted locator")
        child = os.fork()
        if child == 0:
            # POSIX interval timers are not inherited across fork. Re-arm before
            # exec/imports, retaining the SAME absolute live total deadline.
            try:
                _arm(deadline)
                os.execv(command[0], command)
            except (OSError, ValueError) as error:
                _diagnostic(error)
                os._exit(78)
        # The anchor keeps its pipe ends and lifetime descriptor until kernel
        # exit. A compute child may close streams before Python teardown ends;
        # that must not expose premature EOF to the trusted coordinator.
        while True:
            try:
                _pid, status = os.waitpid(child, 0)
                break
            except InterruptedError:
                continue
        exit_code = os.waitstatus_to_exitcode(status)
        if exit_code < 0:
            number = -exit_code
            if number not in {signal.SIGKILL, signal.SIGSTOP}:
                signal.signal(number, signal.SIG_DFL)
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {number})
            os.kill(os.getpid(), number)
            os._exit(128 + number)
        os._exit(exit_code)
    except (OSError, ValueError, TypeError, KeyError) as error:
        _diagnostic(error)
        return 78
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
