"""Standalone, stdlib-only bootstrap for the fixed Linux qualification profile.

This is not a Job worker, shell runner or product execution mode. The trusted
root controller attaches this live child before releasing the first gate.
"""

from __future__ import annotations

import ctypes
import json
import os
import resource
import signal
import stat
import sys
import time
from pathlib import Path

_LIMITS = {
    "cpu.max": "25000 100000",
    "memory.max": "268435456",
    "memory.swap.max": "0",
    "memory.oom.group": "1",
    "pids.max": "32",
}


def _prctl(option: int, value: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if int(libc.prctl(option, value, 0, 0, 0)) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _gate(descriptor: int, expected: bytes, deadline: int) -> None:
    remaining = (deadline - time.monotonic_ns()) / 1_000_000_000
    if remaining <= 0:
        raise ValueError("Original reference admission expired")
    signal.setitimer(signal.ITIMER_REAL, remaining)
    if os.read(descriptor, 1) != expected:
        raise ValueError("Reference admission gate was not released")


def main() -> int:
    try:
        if len(sys.argv) != 7 or os.geteuid() != 0 or sys.platform != "linux":
            raise ValueError("Reference bootstrap requires its fixed root invocation")
        config_path = Path(sys.argv[1])
        gate, report, bpf = (int(value) for value in sys.argv[2:5])
        parent, deadline = (int(value) for value in sys.argv[5:7])
        if min(gate, report, bpf) < 3 or len({gate, report, bpf}) != 3:
            raise ValueError("Reference bootstrap descriptors differ")
        info = config_path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != 0
            or info.st_mode & 0o022
            or info.st_size > 16384
        ):
            raise ValueError("Reference bootstrap configuration is not root owned")
        config = json.loads(config_path.read_bytes())
        if not isinstance(config, dict) or set(config) != {"cgroup", "argv"}:
            raise ValueError("Reference bootstrap configuration fields differ")
        cgroup = Path(config["cgroup"])
        argv = config["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(value, str) and "\x00" not in value for value in argv)
            or argv[0] != "/usr/bin/bwrap"
            or not cgroup.is_relative_to("/sys/fs/cgroup")
            or not cgroup.name.startswith("tickwitness-reference-")
        ):
            raise ValueError("Reference bootstrap locator differs")
        _prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG, checked again after UID drop.
        if os.getppid() != parent:
            raise ValueError("Reference controller identity changed")
        _gate(gate, b"A", deadline)
        membership = Path("/proc/self/cgroup").read_text()
        expected = str(cgroup.relative_to("/sys/fs/cgroup"))
        if membership.strip() != "0::/" + expected:
            raise ValueError("Reference child was not attached to its owned cgroup")
        for name, value in _LIMITS.items():
            if (cgroup / name).read_text().strip() != value:
                raise ValueError("Reference controller readback differs: " + name)
        os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))
        for number, ceiling in (
            (resource.RLIMIT_FSIZE, 8388608),
            (resource.RLIMIT_NOFILE, 64),
            (resource.RLIMIT_CORE, 0),
            (resource.RLIMIT_RTPRIO, 0),
        ):
            resource.setrlimit(number, (ceiling, ceiling))
        os.setgroups([])
        os.setresgid(61184, 61184, 61184)
        os.setresuid(61184, 61184, 61184)
        _prctl(38, 1)  # PR_SET_NO_NEW_PRIVS.
        _prctl(1, signal.SIGKILL)  # Credential changes clear PDEATHSIG.
        if (
            os.getresuid() != (61184, 61184, 61184)
            or os.getresgid() != (61184, 61184, 61184)
            or os.getgroups()
            or os.getppid() != parent
        ):
            raise ValueError("Reference identity drop was not irreversible")
        receipt = {
            "kind": "restricted_reference_bootstrap_v1",
            "pid": os.getpid(),
            "parent_pid": parent,
            "uid": list(os.getresuid()),
            "gid": list(os.getresgid()),
            "groups": os.getgroups(),
        }
        raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        if os.write(report, raw) != len(raw):
            raise ValueError("Reference bootstrap receipt was not delivered")
        _gate(gate, b"B", deadline)
        # The root controller owns the same absolute deadline from here. Do not
        # let an inherited alarm make a stopped launcher look like probe success.
        signal.setitimer(signal.ITIMER_REAL, 0)
        os.close(gate)
        os.close(report)
        os.set_inheritable(bpf, True)
        # bwrap consumes the BPF FD; its final exec filter applies after setup.
        os.execv(argv[0], argv)
    except (OSError, ValueError, TypeError, KeyError) as error:
        sys.stderr.write(("restricted_reference_bootstrap_refused: " + str(error))[:2048] + "\n")
        return 78
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
