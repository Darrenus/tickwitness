"""Standalone, stdlib-only bootstrap for the fixed Linux qualification profile.

This is not a Job worker, shell runner or product execution mode. The trusted
root controller attaches this live child before releasing the first gate.
"""

from __future__ import annotations

import ctypes
import hashlib
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
_POLICY_SHA256 = "a71430ec3060e80404e01d2ece292ef9569837eb5e679deccd7fd8d9d8be9427"
_PROFILE = b"tickwitness-reference-bwrap"
_LABEL = "tickwitness-reference-bwrap (unconfined)"
_EC2_FAMILY = "aws_ec2_dedicated_v1"
_EC2_POLICY_SHA256 = "62c319e3655d13e4c4f856e3591efb48dda36ce3ba175681688ff49b05592314"
_LIBRARY = Path("/usr/lib/x86_64-linux-gnu/libapparmor.so.1")


def _policy_selection(family: object = None) -> tuple[bytes, str, str]:
    """A closed source-pinned family, never a caller-selected profile or hash."""
    if family is None:
        return _PROFILE, _LABEL, _POLICY_SHA256
    if family == _EC2_FAMILY:
        return (
            b"tickwitness-reference-ec2",
            "tickwitness-reference-ec2 (unconfined)",
            _EC2_POLICY_SHA256,
        )
    raise ValueError("Unknown fixed reference policy family")


def _enter_profile(
    library_sha256: str, deadline: int, *, family: object = None
) -> dict[str, object]:
    profile, _, _ = _policy_selection(family)
    before = Path("/proc/self/attr/current").read_text().strip()
    if (
        before != "unconfined"
        or "NoNewPrivs:\t0" not in Path("/proc/self/status").read_text().splitlines()
    ):
        raise ValueError("Explicit profile transition requires the original pre-NNP state")
    real = _LIBRARY.resolve(strict=True)
    descriptor = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o022
            or info.st_nlink != 1
        ):
            raise ValueError("Bound transition library is not root-owned immutable state")
        digest, count = hashlib.sha256(), 0
        while True:
            if time.monotonic_ns() >= deadline:
                raise ValueError("Original bootstrap deadline expired before profile transition")
            raw = os.read(descriptor, 65536)
            if not raw:
                break
            digest.update(raw)
            count += len(raw)
        after = os.fstat(descriptor)
        if (
            digest.hexdigest() != library_sha256
            or count != info.st_size
            or any(
                getattr(info, key) != getattr(after, key)
                for key in (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_uid",
                    "st_gid",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            )
        ):
            raise ValueError("Actual transition library differs from frozen tuple")
    finally:
        os.close(descriptor)
    library = ctypes.CDLL(str(_LIBRARY), use_errno=True)
    change = library.aa_change_profile
    change.argtypes = [ctypes.c_char_p]
    change.restype = ctypes.c_int
    ctypes.set_errno(0)
    returned = int(change(profile))
    error = ctypes.get_errno()
    return {
        "before_label": before,
        "after_label": Path("/proc/self/attr/current").read_text().strip(),
        "returncode": returned,
        "errno": error,
        "library_path": str(_LIBRARY),
        "library_sha256": library_sha256,
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
        fields = {
            "cgroup",
            "argv",
            "policy_setup_sha256",
            "policy_sha256",
            "libapparmor_sha256",
        }
        if not isinstance(config, dict) or set(config) not in (
            fields,
            fields | {"reference_family"},
        ):
            raise ValueError("Reference bootstrap configuration fields differ")
        family = config.get("reference_family")
        if "reference_family" in config and family != _EC2_FAMILY:
            raise ValueError("Explicit reference family must select the fixed EC2 profile")
        _, expected_label, policy_sha256 = _policy_selection(family)
        if config["policy_sha256"] != policy_sha256 or any(
            not isinstance(config[key], str)
            or len(config[key]) != 64
            or any(value not in "0123456789abcdef" for value in config[key])
            for key in ("policy_setup_sha256", "libapparmor_sha256")
        ):
            raise ValueError("Explicit profile binding is absent or unknown")
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
        transition = _enter_profile(config["libapparmor_sha256"], deadline, family=family)
        if transition["returncode"] != 0 or transition["after_label"] != expected_label:
            failure = {
                "kind": "restricted_reference_bootstrap_transition_failed_v1",
                "apparmor_transition": transition,
                "policy_sha256": policy_sha256,
            }
            os.write(report, json.dumps(failure, sort_keys=True).encode() + b"\n")
            return 78
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
        if Path("/proc/self/attr/current").read_text().strip() != expected_label:
            raise ValueError("Named-unconfined label was lost during identity/NNP setup")
        receipt = {
            "kind": "restricted_reference_bootstrap_v1",
            "pid": os.getpid(),
            "parent_pid": parent,
            "uid": list(os.getresuid()),
            "gid": list(os.getresgid()),
            "groups": os.getgroups(),
            "apparmor_transition": transition,
            "apparmor_label": Path("/proc/self/attr/current").read_text().strip(),
            "policy_setup_sha256": config["policy_setup_sha256"],
            "policy_sha256": policy_sha256,
        }
        if family is not None:
            receipt["reference_family"] = family
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
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        sys.stderr.write(("restricted_reference_bootstrap_refused: " + str(error))[:2048] + "\n")
        return 78
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
