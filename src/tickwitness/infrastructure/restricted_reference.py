"""Fixed, privileged Linux reference qualification; no product M1 admission.

Only the trusted remote host harness may instantiate this adapter. Neither Job
workers nor the SDK import or select it. Guest reports never adjudicate isolation.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import selectors
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from tickwitness.infrastructure.restricted_reference_ec2 import Ec2Run, ProbeAdmission

type Row = dict[str, object]

PROBE_NAMES = (
    "positive",
    "filesystem",
    "readonly",
    "environment",
    "identity",
    "network_ipv4",
    "network_ipv6",
    "network_dns",
    "network_loopback",
    "inherited_fds",
    "memory",
    "pids",
    "disk_bytes",
    "inodes",
    "fds",
    "file_size",
    "cpu",
    "output_flood",
    "detached",
    "namespace_denial",
    "privileged_syscalls",
    "abi_denial",
    "malformed_output",
    "stdio_closed",
)
CONTROL_VALUES = {
    "cpu.max": "25000 100000",
    "memory.max": "268435456",
    "memory.swap.max": "0",
    "memory.oom.group": "1",
    "pids.max": "32",
}
GUEST_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "HOME": "/nonexistent",
    "TMPDIR": "/tmp",
    "PYTHONDONTWRITEBYTECODE": "1",
    "TICKWITNESS_REFERENCE": "restricted_reference_v1",
    "PWD": "/scratch",
}
STREAM_LIMIT = 65536
WALL_NS = 10_000_000_000
STOP_NS = 2_000_000_000
WINDOW_NS = 600_000_000_000
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_PYTHON = Path("/usr/bin/python3.12")
_BWRAP = Path("/usr/bin/bwrap")
POLICY_SHA256 = "a71430ec3060e80404e01d2ece292ef9569837eb5e679deccd7fd8d9d8be9427"
PROFILE_NAME = "tickwitness-reference-bwrap"
EXPECTED_LABEL = PROFILE_NAME + " (unconfined)"
EC2_POLICY_SHA256 = "62c319e3655d13e4c4f856e3591efb48dda36ce3ba175681688ff49b05592314"
EC2_PROFILE_NAME = "tickwitness-reference-ec2"
EC2_FAMILY = "aws_ec2_dedicated_v1"
_POLICY_EVIDENCE = Path("/tmp/tickwitness-reference-policy-evidence")
_STAGED_POLICY = Path("/etc/apparmor.d/tickwitness-reference-bwrap")
_LIBAPPARMOR = Path("/usr/lib/x86_64-linux-gnu/libapparmor.so.1")
_PROFILE_TABLE = Path("/sys/kernel/security/apparmor/profiles")
_PROFILE_ROOT = Path("/sys/kernel/security/apparmor/policy/profiles")
_FEATURE_ROOT = Path("/sys/kernel/security/apparmor/features")
_RESTRICT = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
_DOCUMENT_LIMIT = 262144
_POLICY_FIELDS = {
    "kind",
    "schema_version",
    "status",
    "profile_name",
    "attachment",
    "mode",
    "policy",
    "identities",
    "features",
    "loader",
    "loaded_profiles_before",
    "loaded_profiles_after",
    "restrict_before",
    "restrict_after",
    "source_revision",
    "preload_manifest_sha256",
}
_POLICY_IDENTITIES = {
    "bwrap": _BWRAP,
    "parser": Path("/usr/sbin/apparmor_parser"),
    "abi": Path("/etc/apparmor.d/abi/4.0"),
    "parser_config": Path("/etc/apparmor/parser.conf"),
    "libapparmor": _LIBAPPARMOR,
}
_STABLE = (
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
_CLONE_NS = 0x7E020080  # Includes CLONE_NEWTIME as well as the older namespace flags.
# Linux native x86_64 ABI. The selected host header is independently checked.
DENIED_SYSCALLS = {
    "shmget": 29,
    "shmat": 30,
    "shmctl": 31,
    "socket": 41,
    "connect": 42,
    "accept": 43,
    "sendto": 44,
    "recvfrom": 45,
    "sendmsg": 46,
    "recvmsg": 47,
    "shutdown": 48,
    "bind": 49,
    "listen": 50,
    "getsockname": 51,
    "getpeername": 52,
    "socketpair": 53,
    "setsockopt": 54,
    "getsockopt": 55,
    "semget": 64,
    "semop": 65,
    "semctl": 66,
    "shmdt": 67,
    "msgget": 68,
    "msgsnd": 69,
    "msgrcv": 70,
    "msgctl": 71,
    "ptrace": 101,
    "mknod": 133,
    "setpriority": 141,
    "sched_setparam": 142,
    "sched_setscheduler": 144,
    "pivot_root": 155,
    "chroot": 161,
    "mount": 165,
    "umount2": 166,
    "swapon": 167,
    "swapoff": 168,
    "reboot": 169,
    "init_module": 175,
    "delete_module": 176,
    "semtimedop": 220,
    "mq_open": 240,
    "mq_unlink": 241,
    "mq_timedsend": 242,
    "mq_timedreceive": 243,
    "mq_notify": 244,
    "mq_getsetattr": 245,
    "kexec_load": 246,
    "add_key": 248,
    "request_key": 249,
    "keyctl": 250,
    "ioprio_set": 251,
    "mknodat": 259,
    "unshare": 272,
    "accept4": 288,
    "perf_event_open": 298,
    "recvmmsg": 299,
    "sendmmsg": 307,
    "setns": 308,
    "process_vm_readv": 310,
    "process_vm_writev": 311,
    "finit_module": 313,
    "sched_setattr": 314,
    "memfd_create": 319,
    "kexec_file_load": 320,
    "bpf": 321,
    "userfaultfd": 323,
    "io_uring_setup": 425,
    "io_uring_enter": 426,
    "io_uring_register": 427,
    "open_tree": 428,
    "move_mount": 429,
    "fsopen": 430,
    "fsconfig": 431,
    "fsmount": 432,
    "fspick": 433,
    "clone3": 435,
    "pidfd_open": 434,
    "pidfd_getfd": 438,
    "pidfd_send_signal": 424,
    "process_madvise": 440,
    "mount_setattr": 442,
    "memfd_secret": 447,
    "process_mrelease": 448,
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _row(value: object, keys: set[str] | None = None) -> Row:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Policy evidence requires an object")
    result = cast("Row", value)
    if keys is not None and set(result) != keys:
        raise ValueError("Policy evidence fields differ")
    return result


def _kernel_policy_input(path: Path) -> bool:
    """Recognize only existing kernel inputs whose size metadata is not byte length."""
    if not path.is_absolute() or ".." in path.parts:
        return False
    if path in {
        Path("/sys/module/apparmor/parameters/enabled"),
        _RESTRICT,
        _PROFILE_TABLE,
        Path("/proc/self/attr/current"),
        Path("/proc/self/status"),
        Path("/proc/sys/kernel/random/boot_id"),
    }:
        return True
    if path.is_relative_to(_FEATURE_ROOT):
        return path != _FEATURE_ROOT
    if not path.is_relative_to(_PROFILE_ROOT):
        return False
    parts = path.relative_to(_PROFILE_ROOT).parts
    return (
        len(parts) >= 2
        and len(parts) % 2 == 0
        and parts[-1] in {"name", "mode", "attach"}
        and all(parts[index] == "profiles" for index in range(1, len(parts) - 1, 2))
    )


def _policy_read(path: Path, limit: int, deadline: int, *, root_owned: bool = True) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (root_owned and before.st_uid != 0)
            or (before.st_mode & 0o022 and path != Path("/proc/self/attr/current"))
            or before.st_nlink != 1
        ):
            raise ValueError("Policy control is not a root-owned regular input")
        raw = bytearray()
        while len(raw) <= limit:
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("Original reference policy observation window expired")
            chunk = os.read(descriptor, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(raw) > limit
            or (not _kernel_policy_input(path) and len(raw) != before.st_size)
            or any(getattr(before, key) != getattr(after, key) for key in _STABLE)
        ):
            raise ValueError("Policy input changed or exceeded its bound")
        return bytes(raw)
    finally:
        os.close(descriptor)


def _policy_document(
    name: str,
    deadline: int,
    limit: int = _DOCUMENT_LIMIT,
    *,
    evidence_dir: Path | None = None,
) -> bytes:
    allowed = {"policy-setup.json", "preload-manifest.json"} | {
        f"command-{index}.{stream}" for index in (1, 2, 3) for stream in ("stdout", "stderr")
    }
    if name not in allowed:
        raise ValueError("Policy evidence locator is not in the fixed closure")
    selected = _POLICY_EVIDENCE if evidence_dir is None else evidence_dir
    directory = os.open(selected, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Policy evidence directory is not root-owned private control")
        # /proc/self/fd keeps the proven directory open; the child is no-follow.
        return _policy_read(Path(f"/proc/self/fd/{directory}") / name, limit, deadline)
    finally:
        os.close(directory)


def _policy_identity(path: Path, deadline: int, *, optional: bool = False) -> Row:
    try:
        real = path.resolve(strict=True)
    except FileNotFoundError:
        if optional and not os.path.lexists(path):
            return {
                "path": str(path),
                "realpath": None,
                "exists": False,
                "sha256": None,
                "bytes": None,
                "reason": "not_present",
            }
        raise ValueError("Required policy identity is missing") from None
    descriptor = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_mode & 0o022
            or before.st_nlink != 1
        ):
            raise ValueError("Policy identity is not immutable root-owned state")
        digest, count = hashlib.sha256(), 0
        while True:
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("Original reference policy identity deadline expired")
            raw = os.read(descriptor, 65536)
            if not raw:
                break
            digest.update(raw)
            count += len(raw)
            if (
                path in (_POLICY_IDENTITIES["abi"], _POLICY_IDENTITIES["parser_config"])
                and count > 65536
            ):
                raise ValueError("ABI/configuration exceeds its frozen bound")
        after = os.fstat(descriptor)
        if count != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in _STABLE
        ):
            raise ValueError("Policy identity changed during independent hashing")
        return {
            "path": str(path),
            "realpath": str(real),
            "exists": True,
            "sha256": digest.hexdigest(),
            "bytes": count,
            "uid": before.st_uid,
            "gid": before.st_gid,
            "mode": stat.S_IMODE(before.st_mode),
            "device": before.st_dev,
            "inode": before.st_ino,
            "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns,
        }
    finally:
        os.close(descriptor)


def _profiles(raw: bytes) -> list[Row]:
    result: list[Row] = []
    for line in raw.decode().splitlines():
        if " (" not in line or not line.endswith(")"):
            raise ValueError("Loaded profile table is ambiguous")
        name, mode = line.rsplit(" (", 1)
        if not name or not mode[:-1] or len(result) >= 512:
            raise ValueError("Loaded profile table exceeds its declared scope")
        result.append({"name": name, "mode": mode[:-1]})
    if len({row["name"] for row in result}) != len(result):
        raise ValueError("Duplicate loaded profile name")
    return sorted(result, key=lambda row: cast("str", row["name"]))


def _attachments(profiles: list[Row], deadline: int) -> list[Row]:
    result: list[Row] = []

    def visit(directory: Path, parent: str, depth: int) -> None:
        if depth > 8:
            raise ValueError("Policy namespace depth exceeds its bound")
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_dir() or len(result) >= 512:
                raise ValueError("Unknown or excessive policy namespace")
            name = _policy_read(path / "name", 4096, deadline).decode().strip()
            mode = _policy_read(path / "mode", 4096, deadline).decode().strip()
            attachment = _policy_read(path / "attach", 4096, deadline).decode().strip()
            full = parent + "//" + name if parent and not name.startswith(parent + "//") else name
            result.append({"name": full, "mode": mode, "attachment": attachment})
            if (path / "profiles").exists():
                visit(path / "profiles", full, depth + 1)

    visit(_PROFILE_ROOT, "", 0)
    result.sort(key=lambda row: cast("str", row["name"]))
    if [{"name": row["name"], "mode": row["mode"]} for row in result] != profiles:
        raise ValueError("Current attachment/profile observations disagree")
    return result


def _features(deadline: int) -> Row:
    files: list[Row] = []
    total = 0

    def visit(directory: Path, depth: int) -> None:
        nonlocal total
        if depth > 8:
            raise ValueError("Policy feature depth exceeds its bound")
        for path in sorted(directory.iterdir()):
            mode = path.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                visit(path, depth + 1)
            elif stat.S_ISREG(mode) and len(files) < 256:
                raw = _policy_read(path, 4096, deadline)
                total += len(raw)
                if total > 1048576:
                    raise ValueError("Policy feature bytes exceed their bound")
                files.append(
                    {
                        "path": str(path),
                        "relative_path": str(path.relative_to(_FEATURE_ROOT)),
                        "sha256": _sha(raw),
                        "bytes": len(raw),
                    }
                )
            else:
                raise ValueError("Policy feature type/count exceeds its bound")

    visit(_FEATURE_ROOT, 0)
    if not files:
        raise ValueError("Policy feature closure is unavailable")
    return {"files": files, "canonical_sha256": _sha(_canonical(files))}


def parser_configuration_guard(raw: bytes | None) -> Row:
    options: list[str] = []
    if raw is not None:
        for line in raw.decode("utf-8").splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            if value != "write-cache" or options:
                raise ValueError("Parser configuration can redirect or enlarge fixed input closure")
            options.append(value)
    return {
        "kind": "fixed_parser_configuration_guard_v1",
        "exists": raw is not None,
        "source_sha256": _sha(raw) if raw is not None else None,
        "allowed_options": options,
        "cache_disabled_for_all_parser_commands": True,
        "input_redirection_options_permitted": False,
    }


def _require_ec2_run(ec2_run: Ec2Run) -> None:
    # The default GHA path does not import or acquire EC2 provider authority.
    from tickwitness.infrastructure.restricted_reference_ec2 import Ec2Run as ActualEc2Run

    if type(ec2_run) is not ActualEc2Run:
        raise ValueError("Actual closed EC2 run authority is required")


def validate_policy_setup(report: Row, preload: Row, *, ec2_run: Ec2Run | None = None) -> None:
    """Validate the fixed receipt without treating its assertions as OS readbacks."""
    is_ec2 = ec2_run is not None
    if ec2_run is not None:
        _require_ec2_run(ec2_run)
    profile_name = EC2_PROFILE_NAME if is_ec2 else PROFILE_NAME
    policy_sha256 = EC2_POLICY_SHA256 if is_ec2 else POLICY_SHA256
    staged_policy = ec2_run.staged_policy if ec2_run is not None else _STAGED_POLICY
    attachment = None if is_ec2 else str(_BWRAP)
    setup_kind = (
        "restricted_reference_ec2_policy_setup_v1"
        if is_ec2
        else "restricted_reference_policy_setup_v1"
    )
    preload_kind = (
        "restricted_reference_ec2_policy_preload_v1"
        if is_ec2
        else "restricted_reference_policy_preload_v1"
    )
    fields = _POLICY_FIELDS | {"provider_context"} if is_ec2 else _POLICY_FIELDS
    _row(report, fields)
    if (
        report["kind"] != setup_kind
        or type(report["schema_version"]) is not int
        or report["schema_version"] != 1
        or report["status"] != "LOADED_REFERENCE_ONLY"
        or report["profile_name"] != profile_name
        or report["attachment"] != attachment
        or report["mode"] != "unconfined"
        or report["restrict_before"] != "1"
        or report["restrict_after"] != "1"
    ):
        raise ValueError("Selected policy setup was not established")
    policy = _row(report["policy"], {"path", "sha256", "bytes"})
    if (
        policy["path"] != str(staged_policy)
        or policy["sha256"] != policy_sha256
        or type(policy["bytes"]) is not int
        or not 0 < policy["bytes"] <= 65536
    ):
        raise ValueError("Fixed selected policy identity differs")
    before, after = report["loaded_profiles_before"], report["loaded_profiles_after"]
    if not isinstance(before, list) or not isinstance(after, list) or len(before) > 512:
        raise ValueError("Loaded policy receipts are not bounded typed lists")
    old = [_row(row, {"name", "mode"}) for row in before]
    if (
        any(not isinstance(row[key], str) or not row[key] for row in old for key in row)
        or len({row["name"] for row in old}) != len(old)
        or old != sorted(old, key=lambda row: cast("str", row["name"]))
    ):
        raise ValueError("Loaded profile receipt is not a sorted typed unique list")
    policy_rows: list[Row] = [*old, {"name": profile_name, "mode": "unconfined"}]
    expected = sorted(policy_rows, key=lambda row: cast("str", row["name"]))
    if any(row["name"] == profile_name for row in old) or after != expected:
        raise ValueError("Policy receipt reused/replaced a pre-existing profile")
    identities = _row(report["identities"], set(_POLICY_IDENTITIES))
    for key, path in _POLICY_IDENTITIES.items():
        identity = _row(identities[key])
        if identity.get("path") != str(path):
            raise ValueError("Policy identity locator differs")
        if identity.get("exists") is False:
            if key != "parser_config" or identity != {
                "path": str(path),
                "realpath": None,
                "exists": False,
                "sha256": None,
                "bytes": None,
                "reason": "not_present",
            }:
                raise ValueError("Only parser configuration may be explicitly absent")
        else:
            if (
                set(identity)
                != {
                    "path",
                    "realpath",
                    "exists",
                    "sha256",
                    "bytes",
                    "uid",
                    "gid",
                    "mode",
                    "device",
                    "inode",
                    "mtime_ns",
                    "ctime_ns",
                }
                or identity.get("exists") is not True
                or not isinstance(identity.get("realpath"), str)
                or re.fullmatch("[0-9a-f]{64}", str(identity.get("sha256"))) is None
                or any(
                    type(identity.get(field)) is not int or cast("int", identity[field]) < 0
                    for field in (
                        "bytes",
                        "uid",
                        "gid",
                        "mode",
                        "device",
                        "inode",
                        "mtime_ns",
                        "ctime_ns",
                    )
                )
            ):
                raise ValueError("Policy identity receipt schema differs")
    feature = _row(report["features"], {"files", "canonical_sha256"})
    if (
        not isinstance(feature["files"], list)
        or not 0 < len(feature["files"]) <= 256
        or _sha(_canonical(feature["files"])) != feature["canonical_sha256"]
    ):
        raise ValueError("Policy feature closure digest differs")
    loader = _row(report["loader"])
    argv = [
        str(_POLICY_IDENTITIES["parser"]),
        "--add",
        "--skip-cache",
        "--base=/etc/apparmor.d",
        str(staged_policy),
    ]
    commands = loader.get("commands")
    started, deadline = loader.get("original_started_ns"), loader.get("original_deadline_ns")
    if (
        loader.get("argv") != argv
        or not isinstance(commands, list)
        or len(commands) != 3
        or type(started) is not int
        or type(deadline) is not int
        or deadline - started != 30000000000
        or loader.get("bounds")
        != {"window_ns": 30000000000, "max_commands": 3, "per_stream_bytes": 65536}
    ):
        raise ValueError("Policy setup command/window proof differs")
    if ec2_run is not None and (
        started != ec2_run.started_ns or deadline != ec2_run.setup_deadline_ns
    ):
        raise ValueError("EC2 setup did not retain the original claimed window")
    expected_commands = [
        [str(_POLICY_IDENTITIES["parser"]), "--skip-cache", "--version"],
        [
            "/usr/bin/dpkg-query",
            "--show",
            "--showformat=${binary:Package}\t${Version}\t${Status}\n",
            "apparmor",
            "libapparmor1",
            "bubblewrap",
        ],
        argv,
    ]
    for index, command in enumerate(commands):
        row = _row(command)
        if (
            row.get("argv") != expected_commands[index]
            or row.get("started") is not True
            or row.get("stop_confirmed") is not True
            or type(row.get("returncode")) is not int
            or row.get("returncode") != 0
            or row.get("timed_out") is not False
            or row.get("overflow") is not None
            or row.get("exception") is not None
            or row.get("original_deadline_ns") != deadline
            or type(row.get("started_monotonic_ns")) is not int
            or type(row.get("finished_monotonic_ns")) is not int
            or cast("int", row["started_monotonic_ns"]) < started
            or cast("int", row["finished_monotonic_ns"]) < cast("int", row["started_monotonic_ns"])
            or cast("int", row["finished_monotonic_ns"]) > deadline
        ):
            raise ValueError("Policy setup command is failed, unknown or late")
        for stream in ("stdout", "stderr"):
            count = row.get(stream + "_bytes")
            if type(count) is not int or not 0 <= count <= 65536:
                raise ValueError("Policy setup output proof exceeds its bound")
    attachments = loader.get("attachments_after")
    if not isinstance(attachments, list):
        raise ValueError("Policy attachment receipt is absent")
    selected = [row for row in attachments if _row(row).get("name") == profile_name]
    foreign = [row for row in attachments if _row(row).get("name") != profile_name]
    if selected != [
        {
            "name": profile_name,
            "mode": "unconfined",
            "attachment": profile_name if is_ec2 else str(_BWRAP),
        }
    ] or foreign != loader.get("attachments_before"):
        raise ValueError("Policy attachment receipt changed foreign state")
    for key in (
        "policy",
        "identities",
        "features",
        "source_revision",
        "loaded_profiles_before",
        "restrict_before",
    ):
        if report[key] != preload.get(key):
            raise ValueError("Pre-load and post-load policy bindings disagree")
    if (
        preload.get("kind") != preload_kind
        or type(preload.get("schema_version")) is not int
        or preload.get("schema_version") != 1
        or preload.get("parser_argv") != argv
    ):
        raise ValueError("Pre-load policy identity differs")
    if preload.get("attachments_before") != loader.get("attachments_before") or preload.get(
        "parser_configuration_guard"
    ) != loader.get("parser_configuration_guard"):
        raise ValueError("Pre-load parser/attachment observations differ")
    if ec2_run is not None:
        context = ec2_run.provider_record
        if any(
            document.get("provider_context") != context for document in (report, preload, loader)
        ):
            raise ValueError("EC2 policy provider bindings differ")
        manual = _row(loader.get("manual_attachment_observation"), {"raw", "interpretation"})
        if manual != {
            "raw": EC2_PROFILE_NAME,
            "interpretation": "kernel_profile_name_fallback_no_exec_attachment",
        }:
            raise ValueError("EC2 selected manual attachment readback differs")


def _write(path: Path, raw: bytes, *, durable: bool = False) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as output:
        os.fchmod(output.fileno(), 0o644)
        output.write(raw)
        if durable:
            output.flush()
            os.fsync(output.fileno())
    if durable:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def build_seccomp() -> bytes:
    """Concrete native-ABI cBPF; x32 is explicitly EPERM, not kernel ENOSYS."""
    deny, allow, kill = 0x00050001, 0x7FFF0000, 0x80000000
    instructions = [
        (0x20, 0, 0, 4),  # seccomp_data.arch
        (0x15, 1, 0, 0xC000003E),
        (0x06, 0, 0, kill),
        (0x20, 0, 0, 0),  # seccomp_data.nr
        (0x45, 0, 1, 0x40000000),
        (0x06, 0, 0, deny),
        (0x15, 0, 4, 56),  # clone flags, before normal syscall denials.
        (0x20, 0, 0, 16),
        (0x45, 0, 1, _CLONE_NS),
        (0x06, 0, 0, deny),
        (0x06, 0, 0, allow),
    ]
    for number in sorted(DENIED_SYSCALLS.values()):
        # ENOSYS permits libc's ordinary thread fallback to the flags-filtered
        # classic clone. No clone3 operation itself is admitted.
        action = 0x00050026 if number == DENIED_SYSCALLS["clone3"] else deny
        instructions.extend(((0x15, 0, 1, number), (0x06, 0, 0, action)))
    instructions.append((0x06, 0, 0, allow))
    return b"".join(struct.pack("HBBI", *instruction) for instruction in instructions)


def parse_counters(raw: str) -> dict[str, int]:
    result = {}
    for line in raw.splitlines():
        key, value = line.split()
        if key in result or not value.isdecimal():
            raise ValueError("Invalid controller counter")
        result[key] = int(value)
    return result


def _status(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key] = value
    return result


def _validate_process_limits(raw: str) -> None:
    """Require exact ceilings while allowing procfs horizontal column padding."""
    expected = {
        "Max file size": r"[ \t]+8388608[ \t]+8388608[ \t]+bytes[ \t]*",
        "Max core file size": r"[ \t]+0[ \t]+0[ \t]+bytes[ \t]*",
        "Max open files": r"[ \t]+64[ \t]+64[ \t]+files[ \t]*",
        "Max realtime priority": r"[ \t]+0[ \t]+0[ \t]*",
    }
    message = "Independent hard/soft process ceiling readback differs"
    seen: set[str] = set()
    for line in raw.split("\n"):
        candidate = line.lstrip(" \t")
        for label, columns in expected.items():
            if not candidate.startswith(label):
                continue
            remainder = candidate[len(label) :]
            if remainder and not remainder[0].isspace():
                continue  # A different OS row may share a label prefix.
            if label in seen or re.fullmatch(re.escape(label) + columns, line) is None:
                raise ValueError(message + ": " + label)
            seen.add(label)
    if missing := set(expected) - seen:
        raise ValueError(message + ": missing " + ", ".join(sorted(missing)))


def parse_mounts(raw: str) -> list[Row]:
    mounts: list[Row] = []
    for line in raw.splitlines():
        left, right = line.split(" - ", 1)
        fields, tail = left.split(), right.split()
        if len(fields) < 6 or len(tail) < 3:
            raise ValueError("Invalid observed mountinfo")
        mounts.append(
            {
                "id": fields[0],
                "parent": fields[1],
                "device": fields[2],
                "root": fields[3],
                "path": fields[4],
                "options": fields[5].split(","),
                "filesystem": tail[0],
                "source": tail[1],
                "super_options": tail[2].split(","),
                "raw": line,
            }
        )
    return mounts


def validate_mounts(mounts: list[Row]) -> bool:
    by_path = {mount["path"]: mount for mount in mounts}
    required = {"/", "/usr", "/proc", "/input", "/scratch"}
    if len(by_path) != len(mounts) or not required.issubset(by_path):
        return False
    for mount in mounts:
        path = cast("str", mount["path"])
        options = cast("list[str]", mount["options"])
        if path not in required and not path.startswith("/proc/"):
            return False
        if path == "/scratch":
            if "rw" not in options or mount["filesystem"] != "tmpfs":
                return False
        elif "ro" not in options:
            return False
    return True


def _snapshot(cgroup: Path) -> Row:
    result: Row = {name: (cgroup / name).read_text().strip() for name in CONTROL_VALUES}
    for name in ("cpu.stat", "memory.events", "pids.events", "cgroup.events"):
        result[name] = parse_counters((cgroup / name).read_text())
    for name in ("memory.current", "memory.peak", "pids.current", "pids.peak"):
        try:
            result[name] = int((cgroup / name).read_text())
        except FileNotFoundError:
            result[name] = None
    result["cgroup.procs"] = [int(item) for item in (cgroup / "cgroup.procs").read_text().split()]
    return result


def _scratch(path: Path) -> Row:
    info = os.statvfs(path)
    return {
        "bytes_total": info.f_frsize * info.f_blocks,
        "bytes_available": info.f_frsize * info.f_bavail,
        "inodes_total": info.f_files,
        "inodes_available": info.f_favail,
        "device": path.stat().st_dev,
        "inode": path.stat().st_ino,
    }


def _heartbeat(path: Path) -> Row:
    """Read only the frozen named file after task absence; never follow a link."""
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            "heartbeat", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != 61184
            or before.st_size > 1024
        ):
            return {
                "text": None,
                "is_regular": stat.S_ISREG(before.st_mode),
                "read_error": "unsafe_named_file",
            }
        raw = os.read(descriptor, 1025)
        after = os.fstat(descriptor)
        stable = (
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
        if (
            any(getattr(before, key) != getattr(after, key) for key in stable)
            or len(raw) > 1024
            or len(raw) != before.st_size
        ):
            raise ValueError("Stopped heartbeat changed or exceeded its bound")
        return {
            "text": raw.decode("utf-8"),
            "sha256": _sha(raw),
            "size": len(raw),
            "is_regular": True,
        }
    except (OSError, ValueError) as error:
        return {"text": None, "is_regular": None, "read_error": str(error)[:256]}
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def _namespace_links(pid: int) -> dict[str, str]:
    return {
        name: os.readlink(f"/proc/{pid}/ns/{name}")
        for name in ("mnt", "user", "pid", "ipc", "net", "uts", "cgroup")
    }


def _path_identity(path: Path) -> dict[str, int]:
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
        raise ValueError("Owned root directory identity differs")
    return {"device": info.st_dev, "inode": info.st_ino}


def _scratch_identity(path: Path) -> dict[str, int]:
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 61184:
        raise ValueError("Private scratch identity differs")
    return {"device": info.st_dev, "inode": info.st_ino}


def _host_mount(path: Path) -> Row:
    matches = [
        item
        for item in parse_mounts(Path("/proc/self/mountinfo").read_text())
        if item["path"] == str(path)
    ]
    if len(matches) != 1 or matches[0]["filesystem"] != "tmpfs":
        raise ValueError("Exact owned scratch mount is not uniquely observed")
    return matches[0]


def _mount(path: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    options = b"size=16777216,nr_inodes=512,mode=0700,uid=61184,gid=61184"
    if int(libc.mount(b"tmpfs", os.fsencode(path), b"tmpfs", 14, options)) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _unmount(path: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if int(libc.umount2(os.fsencode(path), 0)) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _identity(path: Path) -> Row:
    info = path.stat()
    return {"path": str(path), "sha256": _sha(path.read_bytes()), "bytes": info.st_size}


def _guest_argv(setup: Path, bpf_fd: int, name: str, nonce: str) -> tuple[str, ...]:
    argv = [
        str(_BWRAP),
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-net",
        "--unshare-uts",
        "--unshare-cgroup",
        "--disable-userns",
        "--new-session",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--uid",
        "61184",
        "--gid",
        "61184",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--remount-ro",
        "/proc",
        "--ro-bind",
        str(setup / "input"),
        "/input",
        "--bind",
        str(setup / "scratch"),
        "/scratch",
        "--symlink",
        "/scratch/tmp",
        "/tmp",
        "--dir",
        "/var",
        "--symlink",
        "/scratch/var-tmp",
        "/var/tmp",
        "--dir",
        "/dev",
        "--symlink",
        "/proc/self/fd",
        "/dev/fd",
        "--symlink",
        "/proc/self/fd/0",
        "/dev/stdin",
        "--symlink",
        "/proc/self/fd/1",
        "/dev/stdout",
        "--symlink",
        "/proc/self/fd/2",
        "/dev/stderr",
        "--symlink",
        "/scratch/shm",
        "/dev/shm",
        "--remount-ro",
        "/",
        "--chdir",
        "/scratch",
    ]
    for key, value in GUEST_ENV.items():
        argv.extend(("--setenv", key, value))
    argv.extend(
        (
            "--seccomp",
            str(bpf_fd),
            "--",
            str(_PYTHON),
            "-I",
            "-B",
            "/input/payload.py",
            name,
            nonce,
        )
    )
    return tuple(argv)


class ReferenceRunner:
    """Root-only, one immutable manifest and at most24 fixed probe admissions."""

    def __init__(
        self,
        artifact_dir: Path,
        fixed_payload_path: Path,
        *,
        ec2_run: Ec2Run | None = None,
    ) -> None:
        if ec2_run is not None:
            _require_ec2_run(ec2_run)
        self.artifact_dir = artifact_dir.absolute()
        self.payload = fixed_payload_path.absolute()
        self._ec2_run = ec2_run
        self._profile_name = PROFILE_NAME if ec2_run is None else EC2_PROFILE_NAME
        self._policy_sha256 = POLICY_SHA256 if ec2_run is None else EC2_POLICY_SHA256
        self._expected_label = self._profile_name + " (unconfined)"
        self._staged_policy = _STAGED_POLICY if ec2_run is None else ec2_run.staged_policy
        self._policy_evidence = _POLICY_EVIDENCE if ec2_run is None else ec2_run.policy_evidence_dir
        if ec2_run is None:
            self._started_ns = time.monotonic_ns()
            self._qualification_deadline_ns = self._started_ns + WINDOW_NS
            self._admissions = 0
        else:
            if self.artifact_dir != ec2_run.artifact_dir:
                raise ValueError("EC2 evidence must use the already owned run artifact directory")
            selected_payload = Path(__file__).resolve().parents[3] / "scripts"
            if self.payload != selected_payload / "restricted_reference_payload.py":
                raise ValueError("EC2 qualification requires the fixed source-locked payload")
            budget = ec2_run.acquire_runner()
            if budget.deadline_ns - budget.started_ns != WINDOW_NS or budget.max_admissions != 24:
                raise ValueError("EC2 run has a different original qualification budget")
            self._started_ns = budget.started_ns
            self._qualification_deadline_ns = budget.deadline_ns
            self._admissions = budget.backend_confirmed
        self._nonces: set[str] = set()
        self._poisoned = False
        self._owned: dict[str, tuple[Path, Path]] = {}
        self._owned_seals: dict[str, Row] = {}
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        if self.artifact_dir.is_symlink() or any(self.artifact_dir.iterdir()):
            raise ValueError("Reference evidence requires a fresh non-symlink directory")
        if self.artifact_dir.stat().st_uid != 0:
            raise ValueError("Reference evidence directory must already be root owned")
        self.artifact_dir.chmod(0o755)
        self.manifest = self._capture_manifest()
        manifest_raw = _canonical(self.manifest) + b"\n"
        self.manifest_sha256 = _sha(manifest_raw)
        self.host_tuple_digest = self.manifest_sha256
        durable = self._ec2_run is not None
        _write(self.artifact_dir / "manifest.json", manifest_raw, durable=durable)
        _write(
            self.artifact_dir / "manifest.sha256",
            self.manifest_sha256.encode() + b"\n",
            durable=durable,
        )

    def _capture_policy(self, *, deadline_ns: int | None = None) -> Row:
        deadline = self._qualification_deadline_ns
        if deadline_ns is not None:
            deadline = min(deadline, deadline_ns)
        if self._ec2_run is not None:
            self._ec2_run.revalidate(deadline_ns=deadline)
        raw = _policy_document("policy-setup.json", deadline, evidence_dir=self._policy_evidence)
        preload_raw = _policy_document(
            "preload-manifest.json", deadline, evidence_dir=self._policy_evidence
        )
        report = _row(json.loads(raw))
        preload = _row(json.loads(preload_raw))
        if raw != _canonical(report) + b"\n" or preload_raw != _canonical(preload):
            raise ValueError("Policy documents are not exact canonical frozen bytes")
        validate_policy_setup(report, preload, ec2_run=self._ec2_run)
        if _sha(preload_raw) != report["preload_manifest_sha256"]:
            raise ValueError("Actual pre-load manifest byte hash differs")
        revision = (
            os.environ.get("GITHUB_SHA") if self._ec2_run is None else self._ec2_run.source_revision
        )
        if (
            report["source_revision"] != revision
            or re.fullmatch("[0-9a-f]{40}", str(report["source_revision"])) is None
        ):
            raise ValueError("Policy setup belongs to another source revision")
        policy = _row(report["policy"])
        policy_raw = _policy_read(self._staged_policy, 65536, deadline)
        if _sha(policy_raw) != self._policy_sha256 or len(policy_raw) != policy["bytes"]:
            raise ValueError("Actual installed policy bytes differ from the source freeze")
        identities = {
            key: _policy_identity(path, deadline, optional=key == "parser_config")
            for key, path in _POLICY_IDENTITIES.items()
        }
        if identities != report["identities"]:
            raise ValueError("Actual parser/ABI/config/library/bwrap tuple differs")
        configuration = (
            _policy_read(_POLICY_IDENTITIES["parser_config"].resolve(), 65536, deadline)
            if identities["parser_config"]["exists"]
            else None
        )
        loader = _row(report["loader"])
        if parser_configuration_guard(configuration) != loader.get("parser_configuration_guard"):
            raise ValueError("Actual parser configuration closure is not the selected guard")
        for index, command in enumerate(cast("list[object]", loader["commands"]), 1):
            command_row = _row(command)
            for stream in ("stdout", "stderr"):
                captured = _policy_document(
                    f"command-{index}.{stream}",
                    deadline,
                    65536,
                    evidence_dir=self._policy_evidence,
                )
                if (
                    len(captured) != command_row[stream + "_bytes"]
                    or _sha(captured) != command_row[stream + "_sha256"]
                ):
                    raise ValueError("Actual bounded parser command bytes differ")
        if (
            cast("int", identities["bwrap"]["mode"]) & 0o6000
            or cast("int", identities["parser"]["mode"]) & 0o6000
        ):
            raise ValueError("Selected parser/bwrap mode carries privileges")
        if _policy_identity(self._staged_policy, deadline) != preload.get("staged_identity"):
            raise ValueError("Exclusive staged policy identity changed after loading")
        if _features(deadline) != report["features"]:
            raise ValueError("Actual kernel policy features changed")
        profiles = _profiles(_policy_read(_PROFILE_TABLE, _DOCUMENT_LIMIT, deadline))
        loader = _row(report["loader"])
        attachments = _attachments(profiles, deadline)
        if (
            profiles != report["loaded_profiles_after"]
            or attachments != loader["attachments_after"]
        ):
            raise ValueError("Actual loaded policy name/mode/attachment differs")
        restrict = _policy_read(_RESTRICT, 16, deadline).decode().strip()
        enabled = _policy_read(Path("/sys/module/apparmor/parameters/enabled"), 16, deadline)
        label = _policy_read(Path("/proc/self/attr/current"), 4096, deadline).decode().strip()
        if (
            restrict != "1"
            or enabled.strip() != b"Y"
            or label != "unconfined"
            or _status(Path("/proc/self/status")).get("NoNewPrivs", "").strip() != "0"
        ):
            raise ValueError("Controller AppArmor/NNP/global userns state differs")
        host = {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "os_release": _policy_read(Path("/etc/os-release").resolve(), 65536, deadline).decode(),
            "boot_id": _policy_read(Path("/proc/sys/kernel/random/boot_id"), 128, deadline)
            .decode()
            .strip(),
            "runner_image_os": (
                os.environ.get("ImageOS")  # noqa: SIM112 -- provider-defined spelling
                if self._ec2_run is None
                else None
            ),
            "runner_image_version": (
                os.environ.get("ImageVersion")  # noqa: SIM112 -- provider-defined spelling
                if self._ec2_run is None
                else None
            ),
            "run_id": (
                os.environ.get("GITHUB_RUN_ID") if self._ec2_run is None else self._ec2_run.run_id
            ),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT") if self._ec2_run is None else None,
            "controller_uid": os.geteuid(),
            "controller_gid": os.getegid(),
            "controller_label": label,
        }
        if host != loader.get("host") or host != preload.get("host"):
            raise ValueError("Policy setup is not bound to the actual current host/job")
        source_bindings = [
            (
                "loader_source",
                self.payload.parent
                / (
                    "prepare_reference_policy.py"
                    if self._ec2_run is None
                    else "prepare_reference_policy_ec2.py"
                ),
            ),
            (
                "policy_source",
                self.payload.parent.parent
                / "research/security"
                / (
                    "reference-bwrap.apparmor"
                    if self._ec2_run is None
                    else "reference-ec2.apparmor"
                ),
            ),
        ]
        if self._ec2_run is not None:
            source_bindings.append(
                ("shared_loader_source", self.payload.parent / "prepare_reference_policy.py")
            )
        for field, path in source_bindings:
            identity = _row(loader.get(field), {"path", "sha256", "bytes"})
            source = _policy_read(path, 65536, deadline, root_owned=False)
            if identity != {"path": str(path), "sha256": _sha(source), "bytes": len(source)}:
                raise ValueError("Actual trusted policy-loader source changed")
            if identity != preload.get(field):
                raise ValueError("Pre-load and final policy source bindings differ")
        return {
            "report": report,
            "report_sha256": _sha(raw),
            "preload_manifest_sha256": _sha(preload_raw),
            "actual_host": host,
            "current_loaded_profiles": profiles,
            "current_attachments": attachments,
            "controller_label": label,
            "expected_task_label": self._expected_label,
        }

    def _manifest_context(self) -> Row:
        if self._ec2_run is None:
            return {"kind": "restricted_reference_manifest_v1"}
        _require_ec2_run(self._ec2_run)
        fields: Row = {
            "kind": "restricted_reference_ec2_manifest_v1",
            "schema_version": 1,
            "provider_context": self._ec2_run.provider_record,
            "qualification_started_ns": self._started_ns,
            "qualification_deadline_ns": self._qualification_deadline_ns,
        }
        context = self._ec2_run.recovery_context
        if context is not None:
            snapshot = self._ec2_run.snapshot()
            if (
                snapshot.charged != 0
                or snapshot.backend_confirmed != 0
                or snapshot.unconfirmed != 0
                or snapshot.pending_outcomes != 0
                or snapshot.poisoned
            ):
                raise ValueError("Recovery manifest requires its actual pre-probe snapshot")
            accounting = self._ec2_run.recovery_accounting(snapshot)
            if accounting is None:
                raise ValueError("Recovery manifest lacks its cumulative accounting")
            fields.update(
                kind="restricted_reference_ec2_recovery_manifest_v1",
                recovery_context=context,
                recovery_accounting=accounting,
                recovery_accounting_phase="pre_probe_manifest",
            )
        return fields

    def _capture_manifest(self) -> Row:
        reasons: list[str] = []
        binaries: Row = {}
        selected_sources = {
            "python": _PYTHON,
            "bwrap": _BWRAP,
            "libc": Path("/usr/lib/x86_64-linux-gnu/libc.so.6"),
            "launcher": Path(__file__),
            "bootstrap": Path(__file__).with_name("restricted_reference_bootstrap.py"),
            "payload": self.payload,
        }
        if self._ec2_run is not None:
            selected_sources.update(
                {
                    "ec2_provider": Path(__file__).with_name("restricted_reference_ec2.py"),
                    "ec2_policy_loader": self.payload.parent / "prepare_reference_policy_ec2.py",
                    "shared_policy_loader": self.payload.parent / "prepare_reference_policy.py",
                }
            )
        for name, path in selected_sources.items():
            try:
                binaries[name] = _identity(path)
                if path.stat().st_mode & (stat.S_ISUID | stat.S_ISGID):
                    reasons.append("setuid_or_setgid_binary:" + name)
            except OSError as error:
                binaries[name] = {"path": str(path), "sha256": None, "reason": str(error)}
                reasons.append("missing_binary:" + name)
        release = Path("/etc/os-release").read_text() if sys.platform == "linux" else ""
        if sys.platform != "linux" or platform.machine() != "x86_64":
            reasons.append("unsupported_os_or_architecture")
        if "ID=ubuntu" not in release or 'VERSION_ID="24.04"' not in release:
            reasons.append("unsupported_ubuntu_release")
        if os.geteuid() != 0:
            reasons.append("root_controller_required")
        controllers = ""
        if sys.platform == "linux":
            try:
                controllers = (_CGROUP_ROOT / "cgroup.controllers").read_text().strip()
                if not {"cpu", "memory", "pids"}.issubset(controllers.split()):
                    reasons.append("missing_cgroup_v2_controllers")
                enabled = (_CGROUP_ROOT / "cgroup.subtree_control").read_text().split()
                if not {"cpu", "memory", "pids"}.issubset(enabled):
                    reasons.append("required_parent_controllers_not_enabled")
            except OSError:
                reasons.append("cgroup_v2_unavailable")
        header = Path("/usr/include/x86_64-linux-gnu/asm/unistd_64.h")
        mapping: Row = {}
        try:
            raw_header = header.read_text()
            for name, number in DENIED_SYSCALLS.items():
                found = re.search(r"^#define __NR_" + name + r"\s+(\d+)$", raw_header, re.M)
                observed = None if found is None else int(found[1])
                mapping[name] = {"selected": number, "observed_header": observed}
                if observed != number:
                    reasons.append("unknown_syscall_mapping:" + name)
        except OSError:
            reasons.append("syscall_header_unavailable")
        apparmor: Row = {}
        for label, path in {
            "enabled": Path("/sys/module/apparmor/parameters/enabled"),
            "userns_restriction": Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns"),
            "controller_label": Path("/proc/self/attr/current"),
            "loaded_profiles": Path("/sys/kernel/security/apparmor/profiles"),
        }.items():
            try:
                text = path.read_text()
                apparmor[label] = (
                    [line for line in text.splitlines() if "bwrap" in line]
                    if label == "loaded_profiles"
                    else text.strip()
                )
            except OSError as error:
                apparmor[label] = {"value": None, "reason": str(error)}
        profiles: Row = {}
        for path in Path("/etc/apparmor.d").glob("*bwrap*"):
            if path.is_file():
                profiles[str(path)] = _identity(path)
        apparmor["profile_files"] = profiles
        package_status = Path("/var/lib/dpkg/status")
        package_version: str | None = None
        if package_status.exists():
            for paragraph in package_status.read_text().split("\n\n"):
                if paragraph.startswith("Package: bubblewrap\n"):
                    match = re.search(r"^Version: (.+)$", paragraph, re.M)
                    package_version = None if match is None else match[1]
        bwrap_version: str | None = None
        if os.geteuid() == 0 and _BWRAP.exists() and sys.platform == "linux":
            try:
                # Fixed trusted TCB version query, never a caller command/probe.
                version = subprocess.run(
                    (str(_BWRAP), "--version"),
                    capture_output=True,
                    timeout=1,
                    check=False,
                    env={"PATH": "/usr/bin:/bin"},
                    close_fds=True,
                )
                if version.returncode == 0 and len(version.stdout) <= 1024:
                    bwrap_version = version.stdout.decode("utf-8").strip()
                else:
                    reasons.append("bwrap_version_unavailable")
            except (OSError, UnicodeError, subprocess.SubprocessError):
                reasons.append("bwrap_version_unavailable")
        policy_setup: Row
        try:
            policy_setup = self._capture_policy()
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            policy_setup = {"verified": False, "reason": str(error)[:2048]}
            reasons.append("explicit_policy_setup_unavailable")
        return {
            **self._manifest_context(),
            "production_m1_enabled": False,
            "available_for_probe": not reasons,
            "unavailable_reasons": reasons,
            "os_release": release,
            "kernel": platform.uname()._asdict(),
            "architecture": platform.machine(),
            "python_version": sys.version,
            "libc_version": list(platform.libc_ver()),
            "runner_image_os": (
                os.environ.get("ImageOS")  # noqa: SIM112 -- provider-defined spelling
                if self._ec2_run is None
                else None
            ),
            "runner_image_version": (
                os.environ.get("ImageVersion")  # noqa: SIM112 -- provider-defined spelling
                if self._ec2_run is None
                else None
            ),
            "source_revision": (
                os.environ.get("GITHUB_SHA")
                if self._ec2_run is None
                else self._ec2_run.source_revision
            ),
            "controller_uid": os.geteuid(),
            "controller_gid": os.getegid(),
            "reserved_uid_gid": 61184,
            "binaries": binaries,
            "host_mountinfo": Path("/proc/self/mountinfo").read_text()
            if sys.platform == "linux"
            else None,
            "host_namespaces": _namespace_links(os.getpid()) if sys.platform == "linux" else None,
            "controllers": controllers,
            "apparmor": apparmor,
            "explicit_userns_authorization": policy_setup,
            "bwrap_actual_version": bwrap_version,
            "bwrap_package_version": package_version,
            "parent_subtree_control": (_CGROUP_ROOT / "cgroup.subtree_control").read_text().strip()
            if (_CGROUP_ROOT / "cgroup.subtree_control").exists()
            else None,
            "controller_limits": CONTROL_VALUES,
            "syscall_mapping": mapping,
            "bpf_sha256": _sha(build_seccomp()),
            "bpf_hex": build_seccomp().hex(),
            "guest_environment": {**GUEST_ENV, "PWD": "/scratch"},
            "mount_plan": "readonly root/proc/usr/input; only scratch writable; no device nodes",
            "bwrap_argv_template": list(
                _guest_argv(Path("<owned-setup>"), 3, "<probe>", "<nonce>")
            ),
            "limits": {
                "wall_ns": WALL_NS,
                "stop_confirmation_ns": STOP_NS,
                "qualification_window_ns": WINDOW_NS,
                "admissions": 24,
                "stdout_bytes": STREAM_LIMIT,
                "stderr_bytes": STREAM_LIMIT,
                "scratch_bytes": 16777216,
                "scratch_inodes": 512,
                "file_bytes": 8388608,
                "open_files": 64,
            },
            "fixed_cases": list(PROBE_NAMES),
            "runtime_closure_scope": (
                "Host /usr is a trusted read-only runtime closure; selected binary hashes do not "
                "hash/authenticate its full tree or the supplier. Kernel/host/harness are trusted."
            ),
        }

    def _unchanged_tuple(self, *, deadline_ns: int | None = None) -> None:
        binaries = cast("Row", self.manifest["binaries"])
        for value in binaries.values():
            record = cast("Row", value)
            if (
                record.get("sha256") is None
                or _sha(Path(cast("str", record["path"])).read_bytes()) != record["sha256"]
            ):
                raise ValueError("Frozen reference binary/payload tuple changed")
        current = (
            self._capture_policy()
            if deadline_ns is None
            else self._capture_policy(deadline_ns=deadline_ns)
        )
        if current != self.manifest["explicit_userns_authorization"]:
            raise ValueError("Frozen explicit policy/control tuple changed")

    def _frozen_bytes(self, name: str) -> bytes:
        record = cast("Row", cast("Row", self.manifest["binaries"])[name])
        raw = Path(cast("str", record["path"])).read_bytes()
        if _sha(raw) != record["sha256"]:
            raise ValueError("Bytes copied from frozen reference TCB changed: " + name)
        return raw

    @staticmethod
    def _protected_hashes(setup: Path) -> dict[str, str]:
        protected = (
            "outside-readable.txt",
            "input/payload.py",
            "input/immutable.txt",
            "input/probe-context.json",
            "bootstrap.py",
            "launch.json",
            "filter.bpf",
        )
        result = {}
        for relative in protected:
            path = setup / relative
            info = path.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0
                or info.st_nlink != 1
                or info.st_mode & 0o022
            ):
                raise ValueError("Protected host input identity changed: " + relative)
            result[relative] = _sha(path.read_bytes())
        return result

    @staticmethod
    def _drain_stopped(
        process: subprocess.Popen[bytes], output: dict[str, bytearray], result: Row
    ) -> None:
        for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            if stream is None:
                continue
            os.set_blocking(stream.fileno(), False)
            while len(output[label]) <= STREAM_LIMIT:
                try:
                    bound = min(4096, STREAM_LIMIT - len(output[label]) + 1)
                    chunk = os.read(stream.fileno(), bound)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                remaining = STREAM_LIMIT - len(output[label])
                output[label].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    result[label + "_truncated"] = True
                    if result["failure"] is None:
                        result["failure"] = label + "_limit"
                    break

    @staticmethod
    def _record_members(cgroup: Path, facts: Row, phase: str) -> None:
        observations = cast("list[Row]", facts["active_member_observations"])
        if len(observations) >= 48:
            return
        pids = [int(item) for item in (cgroup / "cgroup.procs").read_text().split()]
        if len(pids) > 32:
            raise ValueError("Observed task membership exceeds frozen PID bound")
        members: list[Row] = []
        for pid in pids:
            try:
                root = Path(f"/proc/{pid}")
                status = {key: value.strip() for key, value in _status(root / "status").items()}
                members.append(
                    {
                        "pid": pid,
                        "sid_host": os.getsid(pid),
                        "parent_pid": int(status["PPid"]),
                        "namespace_pids": status.get("NSpid"),
                        "namespace_session_ids": status.get("NSsid"),
                        "signal_ignored": status["SigIgn"],
                        "ignores_sigterm": bool(int(status["SigIgn"], 16) & (1 << 14)),
                        "uid": status["Uid"],
                        "state": status["State"],
                    }
                )
            except (FileNotFoundError, ProcessLookupError, KeyError, ValueError):
                members.append({"pid": pid, "observation": None, "reason": "exited_or_incomplete"})
        observations.append(
            {
                "phase": phase,
                "observed_at_ns": time.monotonic_ns(),
                "members": members,
                "cgroup_procs": pids,
            }
        )

    def _prepare_input(self, setup: Path, name: str, nonce: str) -> None:
        inputs = setup / "input"
        # mkdir's mode is filtered by the trusted controller's private umask.
        # Change only our newly created directory; never reuse a foreign input.
        inputs.mkdir(mode=0o755)
        inputs.chmod(0o755)
        _write(inputs / "payload.py", self._frozen_bytes("payload"))
        _write(inputs / "immutable.txt", b"restricted-reference-immutable\n")
        context = {
            "name": name,
            "nonce": nonce,
            "outside_path": str(setup / "outside-readable.txt"),
            "immutable_path": "/input/immutable.txt",
            "secret_env_keys": ["TICKWITNESS_REFERENCE_SECRET"],
            "fd_socket": 200,
            "fd_file": 201,
            "fd_canary_nonce": nonce,
        }
        _write(inputs / "probe-context.json", _canonical(context))

    def _prepare_case(self, name: str, nonce: str, facts: Row) -> tuple[Path, Path]:
        if os.geteuid() != 0:
            raise ValueError("Reference controller is not root")
        for item in Path("/proc").iterdir():
            if item.name.isdecimal():
                with suppress(FileNotFoundError, ProcessLookupError):
                    if item.stat().st_uid == 61184:
                        raise ValueError("Reserved reference identity is already in use")
        cgroup = _CGROUP_ROOT / ("tickwitness-reference-" + nonce)
        setup = Path(tempfile.mkdtemp(prefix="tickwitness-reference-"))
        setup.chmod(0o711)
        self._owned[nonce] = (setup, cgroup)
        facts["owned_setup_path"] = str(setup)
        facts["owned_cgroup_path"] = str(cgroup)
        facts["preparation_stage"] = "owned_setup_created"
        self._owned_seals[nonce] = {"setup": _path_identity(setup)}
        facts["owned_setup_identity"] = self._owned_seals[nonce]["setup"]
        cgroup.mkdir(mode=0o700)
        self._owned_seals[nonce]["cgroup"] = _path_identity(cgroup)
        facts["owned_cgroup_identity"] = self._owned_seals[nonce]["cgroup"]
        facts["preparation_stage"] = "owned_cgroup_created"
        for key, value in CONTROL_VALUES.items():
            (cgroup / key).write_text(value)
        before = _snapshot(cgroup)
        if any(before[key] != value for key, value in CONTROL_VALUES.items()):
            raise ValueError("Required cgroup control readback differs")
        facts["cgroup_before"] = before
        facts["preparation_stage"] = "controller_readback_complete"
        (setup / "scratch").mkdir()
        _mount(setup / "scratch")
        facts["scratch_mounted"] = True
        self._owned_seals[nonce]["scratch"] = _scratch_identity(setup / "scratch")
        self._owned_seals[nonce]["scratch_mount"] = _host_mount(setup / "scratch")
        facts["owned_scratch_identity"] = self._owned_seals[nonce]["scratch"]
        facts["owned_scratch_mount"] = self._owned_seals[nonce]["scratch_mount"]
        facts["preparation_stage"] = "private_scratch_mounted"
        for child in ("tmp", "var-tmp", "shm"):
            (setup / "scratch" / child).mkdir(mode=0o700)
            os.chown(setup / "scratch" / child, 61184, 61184)
        facts["scratch_before"] = _scratch(setup / "scratch")
        self._prepare_input(setup, name, nonce)
        outside = setup / "outside-readable.txt"
        _write(outside, (nonce + "\n").encode())
        facts["canaries_before"] = {
            "outside_sha256": _sha(outside.read_bytes()),
            "immutable_input_sha256": _sha((setup / "input" / "immutable.txt").read_bytes()),
            "payload_sha256": _sha((setup / "input" / "payload.py").read_bytes()),
            "outside_mode": stat.S_IMODE(outside.stat().st_mode),
            "outside_parent_mode": stat.S_IMODE(setup.stat().st_mode),
        }
        return setup, cgroup

    def _observe_guest(self, cgroup: Path, name: str, nonce: str, *, facts: Row) -> Row:
        candidates = []
        for pid in cast("list[int]", _snapshot(cgroup)["cgroup.procs"]):
            root = Path(f"/proc/{pid}")
            with suppress(FileNotFoundError, ProcessLookupError):
                command = (root / "cmdline").read_bytes().split(b"\0")[:-1]
                if command == [
                    os.fsencode(_PYTHON),
                    b"-I",
                    b"-B",
                    b"/input/payload.py",
                    name.encode(),
                    nonce.encode(),
                ]:
                    candidates.append(pid)
        if len(candidates) != 1:
            raise ValueError("Actual fixed payload process was not uniquely observed")
        pid = candidates[0]
        root = Path(f"/proc/{pid}")
        status = {key: value.strip() for key, value in _status(root / "status").items()}
        if (
            status.get("Uid", "").split() != ["61184"] * 4
            or status.get("Gid", "").split() != ["61184"] * 4
            or status.get("Groups", "").split()
            or status.get("NoNewPrivs") != "1"
            or status.get("Seccomp") != "2"
            or any(int(status.get(key, "1"), 16) for key in ("CapEff", "CapPrm", "CapAmb"))
        ):
            raise ValueError("Independent task identity or security observation differs")
        namespaces = _namespace_links(pid)
        host = cast("dict[str, str]", self.manifest["host_namespaces"])
        if any(namespaces[key] == host[key] for key in host):
            raise ValueError("Required task namespace did not differ from controller")
        raw = (root / "mountinfo").read_text()
        mounts = parse_mounts(raw)
        if not validate_mounts(mounts):
            raise ValueError("Observed task has missing or unexpected writable mounts")
        descriptors = {item.name: os.readlink(item) for item in (root / "fd").iterdir()}
        if set(descriptors) != {"0", "1", "2"} or any(
            not value.startswith("pipe:[") for value in descriptors.values()
        ):
            raise ValueError("Final task inherited non-pipe or additional descriptors")
        limits = (root / "limits").read_text()
        # Partial observations diagnose a refusal; they do not open the guest gate.
        facts["guest_process_limits_raw"] = limits
        facts["guest_process_limits_pid"] = pid
        _validate_process_limits(limits)
        scheduler = os.sched_getscheduler(pid)
        if scheduler != os.SCHED_OTHER:
            raise ValueError("Actual task did not inherit the selected fair scheduler")
        actual_label = (root / "attr/current").read_text().strip()
        if actual_label != self._expected_label:
            raise ValueError("Actual task lost its selected named-unconfined authorization label")
        controller_label = Path("/proc/self/attr/current").read_text().strip()
        if controller_label != "unconfined":
            raise ValueError("Task transition unexpectedly changed the host controller label")
        return {
            "pid": pid,
            "status": status,
            "namespaces": namespaces,
            "uid_map": (root / "uid_map").read_text(),
            "gid_map": (root / "gid_map").read_text(),
            "descriptors": descriptors,
            "raw_mountinfo": raw,
            "mounts": mounts,
            "mounts_validated": True,
            "limits": limits,
            "scheduler_policy": scheduler,
            "cgroup": (root / "cgroup").read_text(),
            "apparmor_label": actual_label,
            "controller_apparmor_label": controller_label,
        }

    def _stop(
        self, cgroup: Path, process: subprocess.Popen[bytes] | None, stop_deadline: int
    ) -> bool:
        owners = [nonce for nonce, (_setup, owned) in self._owned.items() if owned == cgroup]
        if len(owners) != 1 or _path_identity(cgroup) != self._owned_seals[owners[0]]["cgroup"]:
            raise ValueError("Current owned cgroup identity changed; no kill was issued")
        (cgroup / "cgroup.kill").write_text("1")
        while time.monotonic_ns() < stop_deadline:
            events = parse_counters((cgroup / "cgroup.events").read_text())
            members = (cgroup / "cgroup.procs").read_text().split()
            if events.get("populated") == 0 and not members:
                if time.monotonic_ns() > stop_deadline:
                    return False
                if process is not None:
                    remaining = (stop_deadline - time.monotonic_ns()) / 1e9
                    if remaining < 0:
                        return False
                    process.wait(timeout=remaining)
                return time.monotonic_ns() <= stop_deadline
            time.sleep(0.01)
        return False

    def _attempt_owned_stop(
        self,
        cgroup: Path,
        process: subprocess.Popen[bytes] | None,
        facts: Row,
        result: Row,
        stop_deadline: int,
    ) -> bool:
        try:
            self._record_members(cgroup, facts, "before_kill")
        except (OSError, ValueError) as error:
            facts["member_observation_error"] = str(error)[:256]
            result["failure"] = "host_observation_failed"
        # Diagnostics are not on the containment critical path. _stop itself
        # verifies the current owned leaf before it can issue any kill.
        return self._stop(cgroup, process, stop_deadline)

    def _cleanup(self, nonce: str, facts: Row) -> bool:
        setup, cgroup = self._owned[nonce]
        seal = self._owned_seals[nonce]
        if (
            not facts.get("confirmed_task_absent")
            or _path_identity(setup) != seal["setup"]
            or _path_identity(cgroup) != seal["cgroup"]
        ):
            raise ValueError("Owned setup/cgroup or confirmed-stop identity changed; retained")
        if facts.get("scratch_mounted"):
            if (
                _scratch_identity(setup / "scratch") != seal["scratch"]
                or _host_mount(setup / "scratch") != seal["scratch_mount"]
            ):
                raise ValueError("Exact owned scratch mount identity changed; retained")
            facts["scratch_after"] = _scratch(setup / "scratch")
            cast("Row", facts["scratch_after"])["named_files"] = {
                "heartbeat": _heartbeat(setup / "scratch")
            }
            _unmount(setup / "scratch")
        # Only exact owned, empty mountpoints and explicitly created input files.
        for child in ("payload.py", "immutable.txt", "probe-context.json"):
            with suppress(FileNotFoundError):
                (setup / "input" / child).unlink()
        for child in ("input", "scratch"):
            with suppress(FileNotFoundError):
                (setup / child).rmdir()
        for child in ("outside-readable.txt", "bootstrap.py", "launch.json", "filter.bpf"):
            with suppress(FileNotFoundError):
                (setup / child).unlink()
        setup.rmdir()
        cgroup.rmdir()
        del self._owned[nonce]
        del self._owned_seals[nonce]
        return True

    def run_probe(
        self,
        name: str,
        arguments: tuple[str, ...] = (),
        *,
        ec2_admission: ProbeAdmission | None = None,
    ) -> Row:
        if (
            name not in PROBE_NAMES
            or len(arguments) != 1
            or not re.fullmatch("[0-9a-f]{32}", arguments[0])
        ):
            raise ValueError("Only a fixed probe and one32-hex nonce may be admitted")
        if self._admissions >= 24 or time.monotonic_ns() >= self._started_ns + WINDOW_NS:
            raise ValueError("Original qualification admission budget exhausted")
        if self._poisoned:
            raise ValueError("Unconfirmed task ownership prevents later admission")
        if arguments[0] in self._nonces:
            raise ValueError("Reference nonce cannot be reused")
        nonce = arguments[0]
        if self._ec2_run is None:
            if ec2_admission is not None:
                raise ValueError("EC2 tickets cannot authorize the GHA reference family")
            self._admissions += 1
            admitted = time.monotonic_ns()
            deadline = min(admitted + WALL_NS, self._started_ns + WINDOW_NS)
        else:
            if (
                ec2_admission is None
                or ec2_admission.name != name
                or ec2_admission.nonce != nonce
                or ec2_admission.run_id != self._ec2_run.run_id
                or ec2_admission.boot_id != self._ec2_run.boot_id
                or ec2_admission.source_revision != self._ec2_run.source_revision
                or ec2_admission.admission_number != self._admissions + 1
                or ec2_admission.admitted_ns < self._started_ns
                or ec2_admission.deadline_ns
                != min(ec2_admission.admitted_ns + WALL_NS, self._qualification_deadline_ns)
            ):
                raise ValueError("Original durable EC2 admission identity differs")
            self._ec2_run.admit_probe(ec2_admission)
            self._admissions = ec2_admission.admission_number
            admitted = ec2_admission.admitted_ns
            deadline = ec2_admission.deadline_ns
        self._nonces.add(nonce)
        facts: Row = {
            "manifest_sha256": self.manifest_sha256,
            "admission_number": self._admissions,
            "original_admission_ns": admitted,
            "original_deadline_ns": deadline,
            "cgroup_before": None,
            "cgroup_after": None,
            "bootstrap_admission": None,
            "guest_process_observation": None,
            "guest_process_limits_raw": None,
            "guest_process_limits_pid": None,
            "mounts": None,
            "scratch_before": None,
            "scratch_after": None,
            "canaries_before": None,
            "canaries_after": None,
            "fd_canary_observation": None,
            "launcher_secret_present": None,
            "active_member_observations": [],
        }
        result: Row = {
            "name": name,
            "nonce": nonce,
            "started": False,
            "payload_started": False,
            "actual_exit_code": None,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "stop_confirmed": False,
            "cleanup_confirmed": False,
            "failure": None,
            "stop_reason": None,
            "artifact_dir": str(self.artifact_dir),
            "host_facts": facts,
        }
        process: subprocess.Popen[bytes] | None = None
        setup: Path | None = None
        cgroup: Path | None = None
        output = {"stdout": bytearray(), "stderr": bytearray()}
        descriptors: list[int] = []
        sockets: tuple[socket.socket, socket.socket] | None = None
        try:
            if not self.manifest["available_for_probe"]:
                raise ValueError("Selected host tuple preflight is unavailable")
            if self._ec2_run is None:
                self._unchanged_tuple()
            else:
                self._unchanged_tuple(deadline_ns=deadline)
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("Original deadline expired during policy/TCB preflight")
            setup, cgroup = self._prepare_case(name, nonce, facts)
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("Reference setup exhausted original deadline")
            for fd in (200, 201):
                try:
                    os.fstat(fd)
                except OSError:
                    continue
                raise ValueError("Reserved host canary FD is already occupied")
            sockets = socket.socketpair()
            os.dup2(sockets[0].fileno(), 200, inheritable=True)
            file_fd = os.open(setup / "outside-readable.txt", os.O_RDONLY)
            os.dup2(file_fd, 201, inheritable=True)
            os.close(file_fd)
            descriptors.extend((200, 201))
            gate_read, gate_write = os.pipe()
            report_read, report_write = os.pipe()
            descriptors.extend((gate_read, gate_write, report_read, report_write))
            _write(setup / "filter.bpf", build_seccomp())
            bpf = os.open(setup / "filter.bpf", os.O_RDONLY)
            descriptors.append(bpf)
            argv = _guest_argv(setup, bpf, name, nonce)
            policy_setup = _row(self.manifest["explicit_userns_authorization"])
            policy_report = _row(policy_setup["report"])
            library_identity = _row(_row(policy_report["identities"])["libapparmor"])
            launch: Row = {
                "cgroup": str(cgroup),
                "argv": argv,
                "policy_setup_sha256": policy_setup["report_sha256"],
                "policy_sha256": self._policy_sha256,
                "libapparmor_sha256": library_identity["sha256"],
            }
            if self._ec2_run is not None:
                launch["reference_family"] = EC2_FAMILY
            _write(setup / "launch.json", _canonical(launch))
            _write(setup / "bootstrap.py", self._frozen_bytes("bootstrap"))
            cast("Row", facts["canaries_before"])["protected_tcb_sha256"] = self._protected_hashes(
                setup
            )
            env = {"PATH": "/usr/bin:/bin", "TICKWITNESS_REFERENCE_SECRET": nonce}
            facts["launcher_secret_present"] = "TICKWITNESS_REFERENCE_SECRET" in env
            facts["fd_canary_prelaunch"] = {
                "socket_fd": 200,
                "file_fd": 201,
                "socket_inheritable": os.get_inheritable(200),
                "file_inheritable": os.get_inheritable(201),
                "socket_preconnected": sockets[0].getpeername() == sockets[1].getsockname(),
                "socket_is_socket": stat.S_ISSOCK(os.fstat(200).st_mode),
                "file_is_regular": stat.S_ISREG(os.fstat(201).st_mode),
                "socket_target": os.readlink("/proc/self/fd/200"),
                "file_target": os.readlink("/proc/self/fd/201"),
                "file_sha256": _sha(os.pread(201, 4096, 0)),
            }
            facts["actual_bwrap_argv"] = list(argv)
            facts["cgroup_path"] = str(cgroup)
            process = subprocess.Popen(
                (
                    str(_PYTHON),
                    "-I",
                    "-B",
                    str(setup / "bootstrap.py"),
                    str(setup / "launch.json"),
                    str(gate_read),
                    str(report_write),
                    str(bpf),
                    str(os.getpid()),
                    str(deadline),
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                close_fds=True,
                pass_fds=(gate_read, report_write, bpf),
                start_new_session=True,
            )
            result["started"] = True
            (cgroup / "cgroup.procs").write_text(str(process.pid))
            if (Path(f"/proc/{process.pid}/cgroup").read_text().strip()) != (
                "0::/" + str(cgroup.relative_to(_CGROUP_ROOT))
            ):
                raise ValueError("Host attachment verification differs")
            facts["child_attached"] = True
            pretransition = {
                key: value.strip()
                for key, value in _status(Path(f"/proc/{process.pid}/status")).items()
            }
            prelabel = Path(f"/proc/{process.pid}/attr/current").read_text().strip()
            if (
                prelabel != "unconfined"
                or pretransition.get("NoNewPrivs") != "0"
                or pretransition.get("Uid", "").split() != ["0"] * 4
            ):
                raise ValueError("Actual attached bootstrap is not in the selected pre-NNP state")
            facts["bootstrap_pretransition"] = {
                "host_status": pretransition,
                "apparmor_label": prelabel,
                "host_cgroup": Path(f"/proc/{process.pid}/cgroup").read_text(),
            }
            os.write(gate_write, b"A")
            os.close(report_write)
            descriptors.remove(report_write)
            os.set_blocking(report_read, False)
            receipt = bytearray()
            while b"\n" not in receipt and time.monotonic_ns() < deadline:
                try:
                    chunk = os.read(report_read, 2049 - len(receipt))
                except BlockingIOError:
                    time.sleep(0.005)
                    continue
                if not chunk or len(receipt) + len(chunk) > 2048:
                    raise ValueError("Bootstrap admission receipt missing or excessive")
                receipt.extend(chunk)
            if not receipt.endswith(b"\n"):
                raise TimeoutError("Bootstrap admission did not finish within original deadline")
            receipt_document = _row(json.loads(receipt))
            facts["bootstrap_admission"] = {"receipt": receipt_document}
            if receipt_document.get("kind") != "restricted_reference_bootstrap_v1":
                raise ValueError("Explicit bootstrap profile transition failed")
            observed = {
                key: value.strip()
                for key, value in _status(Path(f"/proc/{process.pid}/status")).items()
            }
            if (
                observed.get("Uid", "").split() != ["61184"] * 4
                or observed.get("Gid", "").split() != ["61184"] * 4
                or observed.get("Groups", "").split()
                or observed.get("NoNewPrivs") != "1"
                or any(int(observed.get(key, "1"), 16) for key in ("CapEff", "CapPrm", "CapAmb"))
            ):
                raise ValueError("Host bootstrap identity observation differs")
            label = Path(f"/proc/{process.pid}/attr/current").read_text().strip()
            transition = _row(receipt_document.get("apparmor_transition"))
            if (
                label != self._expected_label
                or receipt_document.get("apparmor_label") != label
                or transition.get("returncode") != 0
                or transition.get("before_label") != "unconfined"
                or transition.get("after_label") != label
                or transition.get("library_path") != str(_LIBAPPARMOR)
                or transition.get("library_sha256") != library_identity["sha256"]
                or receipt_document.get("policy_setup_sha256") != policy_setup["report_sha256"]
                or receipt_document.get("policy_sha256") != self._policy_sha256
                or (
                    self._ec2_run is not None
                    and receipt_document.get("reference_family") != EC2_FAMILY
                )
            ):
                raise ValueError("Actual bootstrap named-unconfined policy binding differs")
            facts["bootstrap_admission"] = {
                "receipt": receipt_document,
                "host_status": observed,
                "host_cgroup": Path(f"/proc/{process.pid}/cgroup").read_text(),
                "apparmor_label": label,
            }
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("Original deadline expired before unprivileged exec")
            os.write(gate_write, b"B")
            for fd in (gate_read, gate_write, report_read, bpf):
                os.close(fd)
                descriptors.remove(fd)
            self._pump(process, cgroup, name, nonce, deadline, output, result, facts)
            if not result["payload_started"] and result["failure"] is None:
                result["failure"] = "setup_refused"
                facts["diagnostic"] = "Fixed payload never reached its independently checked gate"
        except TimeoutError as error:
            result["failure"] = "deadline_exceeded"
            facts["diagnostic"] = str(error)[:2048]
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            result["failure"] = (
                "setup_refused" if not result["payload_started"] else ("host_observation_failed")
            )
            facts["diagnostic"] = (type(error).__name__ + ": " + str(error))[:2048]
        finally:
            result["stop_reason"] = result["failure"] or "natural_exit"
            stop_started = time.monotonic_ns()
            stop_deadline = stop_started + STOP_NS
            facts["stop_intent_ns"] = stop_started
            facts["stop_confirmation_deadline_ns"] = stop_deadline
            if cgroup is not None:
                try:
                    # Only our still-unreleased trusted bootstrap may be
                    # outside the leaf. Never signal an escaped guest PID.
                    if (
                        process is not None
                        and not facts.get("child_attached")
                        and process.poll() is None
                    ):
                        process.kill()
                    result["stop_confirmed"] = self._attempt_owned_stop(
                        cgroup, process, facts, result, stop_deadline
                    )
                    facts["stop_elapsed_ns"] = time.monotonic_ns() - stop_started
                    facts["cgroup_after"] = _snapshot(cgroup)
                    if setup is not None:
                        outside = setup / "outside-readable.txt"
                        facts["canaries_after"] = {
                            "outside_sha256": _sha(outside.read_bytes()),
                            "immutable_input_sha256": _sha(
                                (setup / "input" / "immutable.txt").read_bytes()
                            ),
                            "payload_sha256": _sha((setup / "input" / "payload.py").read_bytes()),
                            "outside_mode": stat.S_IMODE(outside.stat().st_mode),
                            "outside_parent_mode": stat.S_IMODE(setup.stat().st_mode),
                            "protected_tcb_sha256": self._protected_hashes(setup),
                        }
                    if not result["stop_confirmed"]:
                        result["failure"] = "stop_unconfirmed"
                        self._poisoned = True
                    else:
                        facts["confirmed_task_absent"] = True
                        if facts.get("canaries_before") != facts.get("canaries_after"):
                            raise ValueError("Protected host canary/input bytes changed; retained")
                        result["cleanup_confirmed"] = self._cleanup(nonce, facts)
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    result["failure"] = (
                        "cleanup_unconfirmed" if result["stop_confirmed"] else "stop_unconfirmed"
                    )
                    facts["cleanup_diagnostic"] = str(error)[:2048]
                    self._poisoned = True
            elif nonce in self._owned:
                # Partial preparation is never assumed absent or reclaimed.
                self._poisoned = True
            if process is not None:
                result["actual_exit_code"] = process.poll()
                try:
                    self._drain_stopped(process, output, result)
                except OSError as error:
                    facts["stream_drain_error"] = str(error)[:256]
                    result["failure"] = "host_observation_failed"
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            if sockets is not None:
                sockets[1].setblocking(False)
                try:
                    received = sockets[1].recv(4096)
                except BlockingIOError:
                    received = b""
                before_fds = cast("Row", facts.get("fd_canary_prelaunch") or {})
                facts["fd_canary_observation"] = {
                    **before_fds,
                    "socket_fd": 200,
                    "file_fd": 201,
                    "preconnected_inheritable": bool(
                        before_fds.get("socket_preconnected")
                        and before_fds.get("socket_inheritable")
                        and before_fds.get("file_inheritable")
                    ),
                    "unexpected_socket_bytes": len(received),
                    "socket_received_bytes": len(received),
                    "file_unchanged": facts.get("canaries_before") == facts.get("canaries_after"),
                    "unexpected_socket_sha256": _sha(received),
                }
                for channel in sockets:
                    channel.close()
            for descriptor in descriptors:
                with suppress(OSError):
                    os.close(descriptor)
            facts["deadline_elapsed_ns"] = time.monotonic_ns() - admitted
            if "stop_elapsed_ns" not in facts:
                facts["stop_elapsed_ns"] = time.monotonic_ns() - stop_started
            for label, retained in output.items():
                result[label] = bytes(retained).decode("utf-8", errors="replace")
                facts[label + "_retained_bytes"] = len(retained)
                facts[label + "_sha256"] = _sha(bytes(retained))
                _write(
                    self.artifact_dir / (name + "-" + nonce + "." + label),
                    bytes(retained),
                    durable=self._ec2_run is not None,
                )
            result_raw = _canonical(result) + b"\n"
            _write(
                self.artifact_dir / (name + "-" + nonce + ".json"),
                result_raw,
                durable=self._ec2_run is not None,
            )
            if self._ec2_run is not None and ec2_admission is not None:
                # The durable provider applies the catalog-specific expected
                # termination rules. Local ownership uncertainty always fences.
                self._poisoned = (
                    self._poisoned
                    or result["stop_confirmed"] is not True
                    or result["cleanup_confirmed"] is not True
                )
                self._ec2_run.finish_probe(
                    ec2_admission,
                    result_sha256=_sha(result_raw),
                    stop_confirmed=result["stop_confirmed"] is True,
                    cleanup_confirmed=result["cleanup_confirmed"] is True,
                    failure=cast("str | None", result["failure"]),
                )
        return result

    def _pump(
        self,
        process: subprocess.Popen[bytes],
        cgroup: Path,
        name: str,
        nonce: str,
        deadline: int,
        output: dict[str, bytearray],
        result: Row,
        facts: Row,
    ) -> None:
        if process.stdout is None or process.stderr is None or process.stdin is None:
            raise ValueError("Reference process pipes were not created")
        expected = {"kind": "restricted_reference_started_v1", "name": name, "nonce": nonce}
        next_members = time.monotonic_ns()
        with selectors.DefaultSelector() as selector:
            for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            while True:
                if time.monotonic_ns() >= deadline:
                    result["failure"] = "deadline_exceeded"
                    return
                if time.monotonic_ns() >= next_members:
                    self._record_members(cgroup, facts, "active")
                    next_members = time.monotonic_ns() + 250_000_000
                wait = min(0.02, max(0, deadline - time.monotonic_ns()) / 1e9)
                for key, _events in selector.select(timeout=wait):
                    label = cast("str", key.data)
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = STREAM_LIMIT - len(output[label])
                    output[label].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        result[label + "_truncated"] = True
                        result["failure"] = label + "_limit"
                        return
                    if (
                        label == "stdout"
                        and not result["payload_started"]
                        and b"\n" in output[label]
                    ):
                        line = bytes(output[label]).split(b"\n", 1)[0]
                        if len(line) > 1024 or json.loads(line) != expected:
                            raise ValueError("Fixed payload readiness frame differs")
                        observation = self._observe_guest(cgroup, name, nonce, facts=facts)
                        facts["guest_process_observation"] = observation
                        facts["mounts"] = observation["mounts"]
                        facts["raw_mountinfo"] = observation["raw_mountinfo"]
                        if time.monotonic_ns() >= deadline:
                            raise TimeoutError("Original deadline expired before payload GO")
                        result["payload_started"] = True
                        process.stdin.write(("GO " + nonce + "\n").encode("ascii"))
                        process.stdin.flush()
                if process.poll() is not None and not selector.get_map():
                    if time.monotonic_ns() >= deadline:
                        result["failure"] = "deadline_exceeded"
                    return
