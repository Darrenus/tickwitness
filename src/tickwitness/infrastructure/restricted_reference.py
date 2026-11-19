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
from typing import cast

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


def _write(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as output:
        os.fchmod(output.fileno(), 0o644)
        output.write(raw)


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

    def __init__(self, artifact_dir: Path, fixed_payload_path: Path) -> None:
        self.artifact_dir = artifact_dir.absolute()
        self.payload = fixed_payload_path.absolute()
        self._started_ns = time.monotonic_ns()
        self._admissions = 0
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
        _write(self.artifact_dir / "manifest.json", manifest_raw)
        _write(self.artifact_dir / "manifest.sha256", self.manifest_sha256.encode() + b"\n")

    def _capture_manifest(self) -> Row:
        reasons: list[str] = []
        binaries: Row = {}
        for name, path in {
            "python": _PYTHON,
            "bwrap": _BWRAP,
            "libc": Path("/usr/lib/x86_64-linux-gnu/libc.so.6"),
            "launcher": Path(__file__),
            "bootstrap": Path(__file__).with_name("restricted_reference_bootstrap.py"),
            "payload": self.payload,
        }.items():
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
        return {
            "kind": "restricted_reference_manifest_v1",
            "production_m1_enabled": False,
            "available_for_probe": not reasons,
            "unavailable_reasons": reasons,
            "os_release": release,
            "kernel": platform.uname()._asdict(),
            "architecture": platform.machine(),
            "python_version": sys.version,
            "libc_version": list(platform.libc_ver()),
            "runner_image_os": os.environ.get("ImageOS"),  # noqa: SIM112 - provider-defined spelling
            "runner_image_version": os.environ.get("ImageVersion"),  # noqa: SIM112 - provider-defined spelling
            "source_revision": os.environ.get("GITHUB_SHA"),
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

    def _unchanged_tuple(self) -> None:
        binaries = cast("Row", self.manifest["binaries"])
        for value in binaries.values():
            record = cast("Row", value)
            if (
                record.get("sha256") is None
                or _sha(Path(cast("str", record["path"])).read_bytes()) != record["sha256"]
            ):
                raise ValueError("Frozen reference binary/payload tuple changed")

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
        (setup / "input").mkdir(mode=0o755)
        _write(setup / "input" / "payload.py", self._frozen_bytes("payload"))
        _write(setup / "input" / "immutable.txt", b"restricted-reference-immutable\n")
        outside = setup / "outside-readable.txt"
        _write(outside, (nonce + "\n").encode())
        facts["canaries_before"] = {
            "outside_sha256": _sha(outside.read_bytes()),
            "immutable_input_sha256": _sha((setup / "input" / "immutable.txt").read_bytes()),
            "payload_sha256": _sha((setup / "input" / "payload.py").read_bytes()),
            "outside_mode": stat.S_IMODE(outside.stat().st_mode),
            "outside_parent_mode": stat.S_IMODE(setup.stat().st_mode),
        }
        context = {
            "name": name,
            "nonce": nonce,
            "outside_path": str(outside),
            "immutable_path": "/input/immutable.txt",
            "secret_env_keys": ["TICKWITNESS_REFERENCE_SECRET"],
            "fd_socket": 200,
            "fd_file": 201,
            "fd_canary_nonce": nonce,
        }
        _write(setup / "input" / "probe-context.json", _canonical(context))
        return setup, cgroup

    def _observe_guest(self, cgroup: Path, name: str, nonce: str) -> Row:
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
        for expression in (
            r"^Max file size\s+8388608\s+8388608\s+bytes$",
            r"^Max core file size\s+0\s+0\s+bytes$",
            r"^Max open files\s+64\s+64\s+files$",
            r"^Max realtime priority\s+0\s+0\s*$",
        ):
            if re.search(expression, limits, re.M) is None:
                raise ValueError("Independent hard/soft process ceiling readback differs")
        scheduler = os.sched_getscheduler(pid)
        if scheduler != os.SCHED_OTHER:
            raise ValueError("Actual task did not inherit the selected fair scheduler")
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
            "apparmor_label": (root / "attr/current").read_text().strip(),
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

    def run_probe(self, name: str, arguments: tuple[str, ...] = ()) -> Row:
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
        self._nonces.add(arguments[0])
        self._admissions += 1
        nonce = arguments[0]
        admitted = time.monotonic_ns()
        deadline = min(admitted + WALL_NS, self._started_ns + WINDOW_NS)
        facts: Row = {
            "manifest_sha256": self.manifest_sha256,
            "admission_number": self._admissions,
            "original_admission_ns": admitted,
            "original_deadline_ns": deadline,
            "cgroup_before": None,
            "cgroup_after": None,
            "bootstrap_admission": None,
            "guest_process_observation": None,
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
            self._unchanged_tuple()
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
            _write(setup / "launch.json", _canonical({"cgroup": str(cgroup), "argv": argv}))
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
            facts["bootstrap_admission"] = {
                "receipt": json.loads(receipt),
                "host_status": observed,
                "host_cgroup": Path(f"/proc/{process.pid}/cgroup").read_text(),
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
                _write(self.artifact_dir / (name + "-" + nonce + "." + label), bytes(retained))
            _write(self.artifact_dir / (name + "-" + nonce + ".json"), _canonical(result) + b"\n")
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
                        observation = self._observe_guest(cgroup, name, nonce)
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
