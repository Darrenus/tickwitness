#!/usr/bin/env python3
"""Fixed, one-use root operations for the fourth internal EC2 qualification.

This module deliberately imports no project code. Its Controller is also the
production state machine exercised by the remote controller/handoff regressions.
The lifecycle service, not this module, owns the final instance Stop.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import pwd
import re
import secrets
import signal
import stat
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol

RUN_ID = "ec201aab11254e8bb7cd1573a96a0004"
PLAN_ID = "ec2-recovery-20261127-v3"
UNIT = "tickwitness-test-session.service"
ROOT = Path("/var/lib/tickwitness-reference-ec2")
STAGE = Path("/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3")
OPERATION = Path("/var/lib/tickwitness-lifecycle/reference-batches") / RUN_ID
JSON_LIMIT = 65536
ARCHIVE_LIMIT = 16777216
RAW_LIMIT = 67108864
OUTER_NS = 1500_000_000_000
GRACE_NS = 2_000_000_000
HANDOFF_NS = 120_000_000_000
STOP_SHA = "85cf2e0aea083bae7cfacbe6f52c3c2b49c5bcc057b73fed3c7f3491b9be8f07"
OLD_RUNS = tuple(f"ec201aab11254e8bb7cd1573a96a000{n}" for n in (1, 2, 3))
OLD_SOURCES = (
    "ae3d8e7981a79d6fc692f2cb656534a2f9a6683b",
    "d5f5fab9978d0cb2d1fed92f32552632705d52ee",
    "fae7fad81fe6107f0227fe70a9e9a3feeda52346",
)
OLD_BOOTS = (
    "122c5232-f007-4fe1-b555-6797ee475eba",
    "503b0e3e-0efe-4d7c-99b3-e282176c4c29",
    "5fc1dec3-13e7-4d43-b584-314aedc95e6b",
    "5e83ad22-d623-4ddd-87f8-41a27a599f2d",
)
_LAUNCHER_SHA256 = "3ffa94999948a32c2efdd5f5999f8a410d91c4b56ff32390489e7acaf9c37b32"
_STOP_HOOK_SHA256 = "8814afcb2172781e4f8b53b772205fa0a9498712dc235f87e63dfb1e3f86176c"
_BOOT_TIMER_SHA256 = "16320eba4e809a6bcf2fd47a1670d39b95f500b3275fd2fc7bdcc67ec6b820d6"
_BOOT_SERVICE_SHA256 = "5ac5d11c5f09e748636913fe76ab3202a681077ce6f221f298750f05ebb49fa4"
LIFECYCLE_SHA = {
    "/usr/local/sbin/tickwitness-run-tests": _LAUNCHER_SHA256,
    "/usr/local/libexec/tickwitness-stop-after-test": _STOP_HOOK_SHA256,
    "/etc/systemd/system/tickwitness-boot-deadline.timer": _BOOT_TIMER_SHA256,
    "/etc/systemd/system/tickwitness-boot-deadline.service": _BOOT_SERVICE_SHA256,
}
BASE = {"kind", "schema_version", "source_revision", "run_id", "boot_id"}
KEYS = {
    "controller-start": BASE
    | {
        "controller_pid",
        "controller_start_ticks",
        "controller_argv",
        "started_ns",
        "outer_deadline_ns",
    },
    "qualifier-exit": BASE | {"invoked", "returncode", "report"},
    "export-call": BASE | {"controller_pid", "controller_start_ticks", "started_ns"},
    "export-consumption": BASE | {"controller_pid", "controller_start_ticks", "started_ns"},
    "handoff-ready": BASE
    | {
        "unit",
        "invocation_id",
        "main_pid",
        "main_start_ticks",
        "main_argv",
        "guard_exec_start",
        "guard_control_group",
        "controller_pid",
        "controller_start_ticks",
        "controller_argv",
        "nonce",
        "bytes",
        "sha256",
        "archive_stat",
        "started_ns",
        "deadline_ns",
        "outer_deadline_ns",
    },
    "handoff-ack": BASE
    | {
        "invocation_id",
        "main_pid",
        "controller_pid",
        "nonce",
        "bytes",
        "sha256",
    },
    "controller-cancel": BASE
    | {
        "invocation_id",
        "main_pid",
        "controller_pid",
        "controller_start_ticks",
        "requested_ns",
    },
    "controller-result": BASE
    | {
        "preparation_invoked",
        "preparation_returncode",
        "qualifier_invoked",
        "qualifier_returncode",
        "export_invoked",
        "export_returncode",
        "handoff_status",
        "returncode",
    },
}
STAT_KEYS = {
    "device",
    "inode",
    "mode",
    "uid",
    "gid",
    "nlink",
    "size",
    "mtime_ns",
    "ctime_ns",
}
Row = dict[str, Any]


class Refused(RuntimeError):
    """An uncertain or invalid operation must not gain another invocation."""


def integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def hex_string(value: object, size: int) -> bool:
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{size}}}", value) is not None


def uuid_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is not None
    )


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _pairs(pairs: list[tuple[str, Any]]) -> Row:
    result: Row = {}
    for key, value in pairs:
        if key in result:
            raise Refused("Duplicate JSON field")
        result[key] = value
    return result


def decode(raw: bytes) -> Row:
    if not 0 < len(raw) <= JSON_LIMIT:
        raise Refused("Operational record size")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (ValueError, UnicodeError) as exc:
        raise Refused("Invalid operational JSON") from exc
    if type(value) is not dict or canonical(value) != raw:
        raise Refused("Noncanonical operational JSON")
    return value


def _bad_constant(value: str) -> Any:
    raise Refused(f"Non-JSON numeric constant: {value}")


def controller_argv(source: str) -> list[str]:
    return [
        "/usr/bin/python3",
        "-I",
        str(STAGE / "ec2_reference_handoff_v3.py"),
        "run",
        "--source-revision",
        source,
        "--run-id",
        RUN_ID,
    ]


def main_argv(source: str) -> list[str]:
    return [
        "/usr/bin/sudo",
        "/bin/bash",
        str(STAGE / "run_ec2_reference_recovery_v3.sh"),
        source,
        RUN_ID,
    ]


def guard_commands(source: str) -> tuple[list[str], ...]:
    # sudo may remain as systemd's monitor or exec the exact thin-shell timeout.
    # These are complete commands, never substring/source-only qualification.
    return (
        main_argv(source),
        [
            "/usr/bin/timeout",
            "--signal=TERM",
            "--kill-after=2s",
            "1500s",
            *controller_argv(source),
        ],
    )


def validate_record(value: Row, name: str, source: str, boot: str) -> None:
    if name not in KEYS or set(value) != KEYS[name]:
        raise Refused("Operational record exact fields")
    if (
        value["kind"] != "restricted_reference_ec2_" + name.replace("-", "_") + "_v3"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 3
        or value["source_revision"] != source
        or value["run_id"] != RUN_ID
        or value["boot_id"] != boot
        or not hex_string(source, 40)
        or not uuid_string(boot)
    ):
        raise Refused("Operational record identity")
    for key in (
        "controller_pid",
        "controller_start_ticks",
        "main_pid",
        "main_start_ticks",
        "started_ns",
        "deadline_ns",
        "outer_deadline_ns",
        "requested_ns",
        "bytes",
    ):
        if key in value and not integer(value[key], 1):
            raise Refused("Operational integer field")
    for key, size in (("invocation_id", 32), ("nonce", 32), ("sha256", 64)):
        if key in value and not hex_string(value[key], size):
            raise Refused("Operational hexadecimal field")
    if "controller_argv" in value and value["controller_argv"] != controller_argv(source):
        raise Refused("Controller exact command")
    if "main_argv" in value and value["main_argv"] not in guard_commands(source):
        raise Refused("Guard exact command")
    if name == "controller-start" and value["outer_deadline_ns"] != value["started_ns"] + OUTER_NS:
        raise Refused("Original outer anchor")
    if name == "handoff-ready":
        seal = value["archive_stat"]
        if (
            value["unit"] != UNIT
            or type(seal) is not dict
            or set(seal) != STAT_KEYS
            or any(not integer(item) for item in seal.values())
            or seal["nlink"] != 1
            or not stat.S_ISREG(seal["mode"])
            or seal["size"] != value["bytes"]
            or not 0 < value["bytes"] <= ARCHIVE_LIMIT
            or value["deadline_ns"]
            != min(value["started_ns"] + HANDOFF_NS, value["outer_deadline_ns"])
            or value["deadline_ns"] <= value["started_ns"]
            or not isinstance(value["guard_exec_start"], str)
            or not 0 < len(value["guard_exec_start"]) < 16384
            or not isinstance(value["guard_control_group"], str)
            or not value["guard_control_group"].startswith("/")
        ):
            raise Refused("Ready archive/guard/deadline fields")
    if name == "handoff-ack" and value["bytes"] > ARCHIVE_LIMIT:
        raise Refused("ACK archive bound")
    if name == "qualifier-exit":
        _phase_fields(value, "invoked", "returncode")
        report = value["report"]
        if report is not None and (
            type(report) is not dict
            or set(report) != {"path", "bytes", "sha256"}
            or report["path"] != str(ROOT / "runs" / RUN_ID / "qualification-report.json")
            or not integer(report["bytes"], 1)
            or report["bytes"] > ARCHIVE_LIMIT
            or not hex_string(report["sha256"], 64)
        ):
            raise Refused("Retained qualifier report fields")
    if name == "controller-result":
        for phase in ("preparation", "qualifier", "export"):
            _phase_fields(value, phase + "_invoked", phase + "_returncode")
        if (
            value["handoff_status"]
            not in {
                "not_started",
                "acknowledged",
                "expired",
                "cancelled",
                "failed",
                "unknown",
            }
            or not integer(value["returncode"])
            or value["returncode"] > 255
        ):
            raise Refused("Final controller outcome fields")


def _phase_fields(value: Row, invoked: str, code: str) -> None:
    if (
        type(value[invoked]) is not bool
        or (value[code] is not None and type(value[code]) is not int)
        or (not value[invoked] and value[code] is not None)
    ):
        raise Refused("Original phase invocation/returncode")


def stat_record(info: os.stat_result) -> Row:
    return dict(
        zip(
            ("device", "inode", "mode", "uid", "gid", "nlink", "size", "mtime_ns", "ctime_ns"),
            (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_uid,
                info.st_gid,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            ),
            strict=True,
        )
    )


class Store:
    """No-follow filesystem port. Test constructors may use a private temp trust root."""

    def __init__(
        self,
        operation: Path = OPERATION,
        *,
        owner: int = 0,
        trust_root: Path = Path("/"),
        archive_base: Path = Path("/var/lib"),
    ) -> None:
        self.operation = operation
        self.owner = owner
        self.trust_root = trust_root
        self.archive_base = archive_base

    def ancestry(self, directory: Path) -> None:
        if not directory.is_absolute() or not directory.is_relative_to(self.trust_root):
            raise Refused("Path outside trusted ancestry")
        current = self.trust_root
        for part in ("", *directory.relative_to(current).parts):
            if part:
                current /= part
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner or info.st_mode & 0o022:
                raise Refused("Unsafe root directory ancestry")

    def fsync_directory(self, directory: Path) -> None:
        self.ancestry(directory)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def create_operation(self) -> None:
        self.ancestry(self.operation.parent)
        self.operation.mkdir(mode=0o700)
        self.fsync_directory(self.operation.parent)

    def open_file(self, path: Path, limit: int = RAW_LIMIT) -> tuple[BinaryIO, Row]:
        self.ancestry(path.parent)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.owner
                or info.st_nlink != 1
                or info.st_mode & 0o022
                or info.st_size > limit
            ):
                raise Refused("Unsafe bounded single-link regular file")
            before = stat_record(info)
            if before != stat_record(path.lstat()):
                raise Refused("File path/descriptor changed")
            return os.fdopen(fd, "rb"), before
        except BaseException:
            os.close(fd)
            raise

    def read(self, path: Path, limit: int = JSON_LIMIT) -> tuple[bytes, Row]:
        stream, before = self.open_file(path, limit)
        with stream:
            raw = stream.read(limit + 1)
            if (
                len(raw) > limit
                or len(raw) != before["size"]
                or before != stat_record(os.fstat(stream.fileno()))
                or before != stat_record(path.lstat())
            ):
                raise Refused("File changed during bounded read")
        return raw, before

    def write(
        self,
        name: str,
        raw: bytes,
        mode: int = 0o400,
        *,
        before_create: Callable[[], None] | None = None,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,80}", name):
            raise Refused("Fixed operation filename")
        self.ancestry(self.operation)
        if before_create is not None:
            before_create()
        fd = os.open(
            self.operation / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        self.fsync_directory(self.operation)

    def record(
        self,
        name: str,
        value: Row,
        source: str,
        boot: str,
        *,
        before_create: Callable[[], None] | None = None,
    ) -> None:
        validate_record(value, name, source, boot)
        raw = canonical(value)
        if len(raw) > JSON_LIMIT:
            raise Refused("Operational record exceeds bound")
        self.write(name + ".json", raw, before_create=before_create)

    def record_read(self, name: str, source: str, boot: str) -> Row:
        raw, _ = self.read(self.operation / (name + ".json"))
        value = decode(raw)
        validate_record(value, name, source, boot)
        return value

    def exists(self, name: str) -> bool:
        try:
            (self.operation / name).lstat()
            return True
        except FileNotFoundError:
            return False

    def archive(self) -> tuple[Row, str]:
        raw, seal = self.read(self.operation / "evidence.tar.gz", ARCHIVE_LIMIT)
        if not raw:
            raise Refused("Empty archive")
        return seal, hashlib.sha256(raw).hexdigest()


def copy_stop_observation(
    source: Path = STAGE / "operator-stop.md",
    target: Path = ROOT / "recovery-v3/operator-stop.md",
    *,
    store: Store | None = None,
) -> None:
    """The preparation child calls this same no-follow producer, not a copy of it."""
    store = Store() if store is None else store
    raw, seal = store.read(source, 1222)
    if (
        len(raw) != 1222
        or hashlib.sha256(raw).hexdigest() != STOP_SHA
        or stat_record(source.lstat()) != seal
    ):
        raise Refused("Wrong or unstable original Stop observation")
    store.ancestry(target.parent.parent)
    target.parent.mkdir(mode=0o700)
    store.fsync_directory(target.parent.parent)
    target_store = Store(
        target.parent,
        owner=store.owner,
        trust_root=store.trust_root,
        archive_base=store.archive_base,
    )
    target_store.write("operator-stop.md", raw)
    if stat_record(source.lstat()) != seal:
        raise Refused("Stop source changed during exclusive copy; retained uncertain target")


class ClockPort(Protocol):
    def now(self) -> int: ...
    def sleep(self, seconds: float) -> None: ...


class Clock:
    def now(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int
    argv: list[str]
    cgroup: str
    ppid: int
    effective_uid: int = 0


@dataclass(frozen=True)
class GuardIdentity:
    invocation_id: str
    main: ProcessIdentity
    exec_start: str
    cgroup: str


class HostPort(Protocol):
    def boot(self) -> str: ...
    def master(self, source: str) -> ProcessIdentity: ...
    def live(self, source: str, start: Row) -> GuardIdentity: ...
    def before_preparation(self, source: str, store: Store) -> None: ...
    def after_preparation(self, source: str, store: Store) -> None: ...
    def stop(self, guard: GuardIdentity) -> None: ...


class Host:
    def __init__(self, store: Store) -> None:
        self.store = store

    def boot(self) -> str:
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not uuid_string(value) or value in OLD_BOOTS:
            raise Refused("Expected a new actual qualification boot")
        return value

    def process(self, pid: int) -> ProcessIdentity:
        if not integer(pid, 1):
            raise Refused("Invalid process identity")
        root = Path("/proc") / str(pid)
        raw = (root / "stat").read_bytes()
        fields = raw[raw.rfind(b")") + 2 :].split()
        if len(fields) < 20 or fields[0] in (b"Z", b"X", b"x"):
            raise Refused("Process is not live")
        ticks, ppid = int(fields[19]), int(fields[1])
        command = (root / "cmdline").read_bytes()
        if not command.endswith(b"\0") or not 0 < len(command) <= JSON_LIMIT:
            raise Refused("Bounded actual process command")
        argv = [item.decode("utf-8", "strict") for item in command[:-1].split(b"\0")]
        cgroups = (root / "cgroup").read_text().splitlines()
        if len(cgroups) != 1 or not cgroups[0].startswith("0::/"):
            raise Refused("Unified actual process cgroup")
        uid_lines = [
            line.split()[1:]
            for line in (root / "status").read_text().splitlines()
            if line.startswith("Uid:")
        ]
        if len(uid_lines) != 1 or len(uid_lines[0]) != 4:
            raise Refused("Actual process effective identity")
        effective_uid = int(uid_lines[0][1])
        again = (root / "stat").read_bytes()
        tail = again[again.rfind(b")") + 2 :].split()
        if len(tail) < 20 or int(tail[19]) != ticks or tail[0] in (b"Z", b"X", b"x"):
            raise Refused("Process identity changed")
        return ProcessIdentity(pid, ticks, argv, cgroups[0][3:], ppid, effective_uid)

    def master(self, source: str) -> ProcessIdentity:
        value = self.process(os.getpid())
        if value.argv != controller_argv(source) or value.effective_uid != 0:
            raise Refused("Unexpected Python master command")
        return value

    def show(self, unit: str, fields: tuple[str, ...]) -> Row:
        result = subprocess.run(
            ["/usr/bin/systemctl", "show", unit, "--no-pager", "--property=" + ",".join(fields)],
            capture_output=True,
            timeout=3,
            check=True,
        )
        if len(result.stdout) > JSON_LIMIT or len(result.stderr) > JSON_LIMIT:
            raise Refused("Bounded systemctl observation")
        values: Row = {}
        for line in result.stdout.decode("utf-8", "strict").splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values:
                raise Refused("Malformed systemctl fields")
            values[key] = value
        if set(values) != set(fields):
            raise Refused("Missing systemctl identity")
        return values

    def live(self, source: str, start: Row) -> GuardIdentity:
        validate_record(start, "controller-start", source, self.boot())
        master = self.process(start["controller_pid"])
        if (
            master.effective_uid != 0
            or master.start_ticks != start["controller_start_ticks"]
            or master.argv != start["controller_argv"]
        ):
            raise Refused("Master PID/start/command changed")
        fields = (
            "ActiveState",
            "SubState",
            "InvocationID",
            "MainPID",
            "ExecStart",
            "ControlGroup",
            "DropInPaths",
            "User",
        )
        first = self.show(UNIT, fields)
        if (
            first["ActiveState"] != "active"
            or first["SubState"] != "running"
            or not hex_string(first["InvocationID"], 32)
            or first["DropInPaths"]
            or not first["MainPID"].isdigit()
            or first["User"] != "ubuntu"
        ):
            raise Refused("Original lifecycle guard is not active/running")
        main = self.process(int(first["MainPID"]))
        owner_uid = pwd.getpwnam("ubuntu").pw_uid
        if owner_uid != 1000:
            raise Refused("Fixed lifecycle owner identity changed")
        allowed_uid = {0, owner_uid} if main.argv == main_argv(source) else {0}
        if (
            main.effective_uid not in allowed_uid
            or main.argv not in guard_commands(source)
            or main.cgroup != first["ControlGroup"]
            or master.cgroup != first["ControlGroup"]
            or first["ControlGroup"] != "/system.slice/" + UNIT
            or "path=/usr/bin/sudo ;" not in first["ExecStart"]
            or "argv[]=" + " ".join(main_argv(source)) + " ;" not in first["ExecStart"]
            or first != self.show(UNIT, fields)
        ):
            raise Refused("Complete live guard/master identity mismatch")
        return GuardIdentity(first["InvocationID"], main, first["ExecStart"], main.cgroup)

    def _controls(self) -> None:
        if (
            Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_text().strip()
            != "1"
        ):
            raise Refused("Original AppArmor restriction changed")
        clone = Path("/proc/sys/kernel/unprivileged_userns_clone")
        if clone.exists() and clone.read_text().strip() != "1":
            raise Refused("Original user namespace setting changed")

    def before_preparation(self, source: str, store: Store) -> None:
        self._controls()
        for path, expected in LIFECYCLE_SHA.items():
            raw, _ = store.read(Path(path), 1048576)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise Refused("Original lifecycle file changed")
        timer = self.show(
            "tickwitness-boot-deadline.timer",
            (
                "ActiveState",
                "UnitFileState",
                "DropInPaths",
                "FragmentPath",
                "TimersMonotonic",
            ),
        )
        if (
            timer["ActiveState"] != "active"
            or timer["UnitFileState"] != "enabled"
            or timer["DropInPaths"]
            or timer["FragmentPath"] != "/etc/systemd/system/tickwitness-boot-deadline.timer"
            or "OnBootUSec=4h" not in timer["TimersMonotonic"]
        ):
            raise Refused("Original independent boot timer changed")
        for filename, copy in (
            ("run_ec2_reference_recovery_v3.sh", "batch-source.sh"),
            ("provision_ec2_reference_source.sh", "preparer-source.sh"),
            ("ec2_reference_handoff_v3.py", "handoff-source.py"),
        ):
            raw, _ = store.read(STAGE / filename, 1048576)
            store.write(copy, raw)
        history = history_snapshot(store)
        store.write("history-before.log", canonical(history))

    def after_preparation(self, source: str, store: Store) -> None:
        self._controls()
        checkout = Path("/opt/tickwitness-reference") / source
        records = []
        for filename, copy in (
            ("run_ec2_reference_recovery_v3.sh", "batch-source.sh"),
            ("provision_ec2_reference_source.sh", "preparer-source.sh"),
            ("ec2_reference_handoff_v3.py", "handoff-source.py"),
        ):
            staged, seal = store.read(STAGE / filename, 1048576)
            selected, _ = store.read(checkout / "scripts" / filename, 1048576)
            retained, _ = store.read(store.operation / copy, 1048576)
            if staged != selected or retained != selected:
                raise Refused("Stage/operation script does not match selected Git source")
            records.append(
                {"path": filename, "sha256": hashlib.sha256(staged).hexdigest(), "stat": seal}
            )
        store.write("source-check.log", canonical(records))
        before, _ = store.read(store.operation / "history-before.log", RAW_LIMIT)
        after = canonical(history_snapshot(store))
        store.write("history-prepared.log", after)
        if before != after:
            raise Refused("Historical bytes/inodes changed during preparation")

    def stop(self, guard: GuardIdentity) -> None:
        # Caller must revalidate this exact guard immediately before this method.
        subprocess.run(["/usr/bin/systemctl", "stop", UNIT], timeout=10, check=True)


@dataclass(frozen=True)
class PhaseResult:
    returncode: int | None
    timed_out: bool = False


class RunnerPort(Protocol):
    def run(
        self, argv: list[str], deadline: int, grace_deadline: int, stdout: Path, stderr: Path
    ) -> PhaseResult: ...


class ProcessRunner:
    """The live master directly owns each child; TERM/KILL never renews the clock."""

    def __init__(self, clock: ClockPort, store: Store) -> None:
        self.clock = clock
        self.store = store

    def run(
        self, argv: list[str], deadline: int, grace_deadline: int, stdout: Path, stderr: Path
    ) -> PhaseResult:
        self.store.ancestry(stdout.parent)
        self.store.ancestry(stderr.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        out_fd = os.open(stdout, flags, 0o400)
        try:
            err_fd = os.open(stderr, flags, 0o400)
        except BaseException:
            os.close(out_fd)
            raise
        try:
            with os.fdopen(out_fd, "wb") as out, os.fdopen(err_fd, "wb") as err:
                if self.clock.now() >= deadline:
                    return PhaseResult(None, True)
                process = subprocess.Popen(argv, stdout=out, stderr=err, start_new_session=True)
                timed_out = False
                try:
                    code = process.wait(timeout=max(0, deadline - self.clock.now()) / 1e9)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        grace_started = self.clock.now()
                        remaining = max(0, grace_deadline - grace_started)
                        term_deadline = grace_started + remaining // 2
                        code = process.wait(timeout=max(0, term_deadline - self.clock.now()) / 1e9)
                    except subprocess.TimeoutExpired:
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                        try:
                            code = process.wait(
                                timeout=max(0, grace_deadline - self.clock.now()) / 1e9
                            )
                        except subprocess.TimeoutExpired:
                            code = None
                out.flush()
                err.flush()
                os.fsync(out.fileno())
                os.fsync(err.fileno())
                return PhaseResult(code, timed_out)
        finally:
            self.store.fsync_directory(stdout.parent)


PREPARATION = r"""set -euo pipefail
source_revision=$1
stage=/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3
/bin/bash "$stage/provision_ec2_reference_source.sh" --recovery-v3 "$source_revision"
/usr/bin/python3 -I - <<'PY'
import runpy
runpy.run_path(
    '/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3/ec2_reference_handoff_v3.py',
    run_name='tickwitness_stop_copy_v3',
)['copy_stop_observation']()
PY
selected_source=/opt/tickwitness-reference/$source_revision
/usr/bin/python3 -I "$selected_source/scripts/prepare_ec2_reference_recovery_v3.py" \
    --source-revision "$source_revision" --plan-id ec2-recovery-20261127-v3
"""


class Controller:
    def __init__(
        self, source: str, store: Store, host: HostPort, runner: RunnerPort, clock: ClockPort
    ) -> None:
        if not hex_string(source, 40):
            raise Refused("Exact source revision required")
        self.source, self.store, self.host = source, store, host
        self.runner, self.clock = runner, clock
        self.started = clock.now()
        self.deadline = self.started + OUTER_NS
        self.boot = host.boot()
        self.start: Row = {}
        self.invoked = {name: False for name in ("preparation", "qualifier", "export")}
        self.results = {name: PhaseResult(None) for name in self.invoked}
        self.status = "not_started"

    def base(self, name: str) -> Row:
        return {
            "kind": "restricted_reference_ec2_" + name.replace("-", "_") + "_v3",
            "schema_version": 3,
            "source_revision": self.source,
            "run_id": RUN_ID,
            "boot_id": self.boot,
        }

    def phase(
        self, name: str, argv: list[str], seconds: int, *, anchor: int | None = None
    ) -> PhaseResult:
        if self.invoked[name]:
            raise Refused("Phase already invoked")
        started = self.clock.now() if anchor is None else anchor
        deadline = min(started + seconds * 1_000_000_000, self.deadline)
        if self.clock.now() >= deadline:
            self.results[name] = PhaseResult(None, True)
            return self.results[name]
        grace = min(deadline + GRACE_NS, self.deadline + GRACE_NS)
        self.invoked[name] = True  # Before Popen; uncertain submission remains invoked.
        filename = "qualification" if name == "qualifier" else name
        try:
            result = self.runner.run(
                argv,
                deadline,
                grace,
                self.store.operation / (filename + ".stdout"),
                self.store.operation / (filename + ".stderr"),
            )
        except Exception:
            result = PhaseResult(None)
        self.results[name] = result
        return result

    def run(self) -> int:
        # No cleanup/finally handler can create another operation or rerun a phase.
        self.store.create_operation()
        master = self.host.master(self.source)
        self.start = self.base("controller-start") | {
            "controller_pid": master.pid,
            "controller_start_ticks": master.start_ticks,
            "controller_argv": master.argv,
            "started_ns": self.started,
            "outer_deadline_ns": self.deadline,
        }
        self.store.record("controller-start", self.start, self.source, self.boot)
        try:
            preparation_started = self.clock.now()
            preparation_deadline = min(preparation_started + 480_000_000_000, self.deadline)
            self.host.live(self.source, self.start)
            self.host.before_preparation(self.source, self.store)
            preparation = self.phase(
                "preparation",
                ["/bin/bash", "-c", PREPARATION, "v3-preparation", self.source],
                480,
                anchor=preparation_started,
            )
            if preparation.returncode == 0 and not preparation.timed_out:
                self.host.after_preparation(self.source, self.store)
                self.host.live(self.source, self.start)
                if self.clock.now() >= preparation_deadline:
                    self.results["preparation"] = PhaseResult(preparation.returncode, True)
                    raise Refused("Preparation observation exhausted its original phase clock")
                self.phase(
                    "qualifier",
                    [
                        "/usr/bin/python3",
                        "-I",
                        str(
                            Path("/opt/tickwitness-reference")
                            / self.source
                            / "scripts/qualify_restricted_reference_ec2.py"
                        ),
                        "--source-revision",
                        self.source,
                        "--run-id",
                        RUN_ID,
                        "--recovery-plan",
                        PLAN_ID,
                    ],
                    612,
                )
        except Exception:
            self.status = "failed"
        try:
            report = self._report_record()
            self.store.record(
                "qualifier-exit",
                self.base("qualifier-exit")
                | {
                    "invoked": self.invoked["qualifier"],
                    "returncode": self.results["qualifier"].returncode,
                    "report": report,
                },
                self.source,
                self.boot,
            )
            if self.clock.now() < self.deadline:
                self.host.live(self.source, self.start)
                self.store.record(
                    "export-call",
                    self.base("export-call")
                    | {
                        "controller_pid": master.pid,
                        "controller_start_ticks": master.start_ticks,
                        "started_ns": self.clock.now(),
                    },
                    self.source,
                    self.boot,
                )
                exported = self.phase(
                    "export",
                    [
                        "/usr/bin/python3",
                        "-I",
                        str(STAGE / "ec2_reference_handoff_v3.py"),
                        "internal-export",
                        "--source-revision",
                        self.source,
                        "--run-id",
                        RUN_ID,
                    ],
                    25,
                )
                if exported.returncode == 0 and not exported.timed_out:
                    self.status = self.wait()
                else:
                    self.status = "failed"
            else:
                self.status = "expired"
        except Exception:
            self.status = "failed"
        qualifier = self.results["qualifier"]
        original = qualifier.returncode
        code = (
            original
            if (
                self.status == "acknowledged"
                and self.results["export"].returncode == 0
                and self.invoked["qualifier"]
                and type(original) is int
                and 0 <= original <= 255
                and not any(result.timed_out for result in self.results.values())
                and self.results["preparation"].returncode == 0
            )
            else 74
        )
        if self.clock.now() < self.deadline:
            result = self.base("controller-result") | {
                "handoff_status": self.status,
                "returncode": code,
            }
            for phase in self.invoked:
                result[phase + "_invoked"] = self.invoked[phase]
                result[phase + "_returncode"] = self.results[phase].returncode
            try:
                self.store.record("controller-result", result, self.source, self.boot)
            except Exception:
                return 74
        else:
            return 74
        return code

    def _report_record(self) -> Row | None:
        path = ROOT / "runs" / RUN_ID / "qualification-report.json"
        try:
            raw, _ = self.store.read(path, ARCHIVE_LIMIT)
            if not raw:
                return None
            return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        except (OSError, Refused):
            return None

    def wait(self) -> str:
        started = self.clock.now()
        deadline = min(started + HANDOFF_NS, self.deadline)
        if started >= deadline:
            return "expired"
        guard = self.host.live(self.source, self.start)
        seal, digest = self.store.archive()
        ready = self.base("handoff-ready") | {
            "unit": UNIT,
            "invocation_id": guard.invocation_id,
            "main_pid": guard.main.pid,
            "main_start_ticks": guard.main.start_ticks,
            "main_argv": guard.main.argv,
            "guard_exec_start": guard.exec_start,
            "guard_control_group": guard.cgroup,
            "controller_pid": self.start["controller_pid"],
            "controller_start_ticks": self.start["controller_start_ticks"],
            "controller_argv": self.start["controller_argv"],
            "nonce": secrets.token_hex(16),
            "bytes": seal["size"],
            "sha256": digest,
            "archive_stat": seal,
            "started_ns": started,
            "deadline_ns": deadline,
            "outer_deadline_ns": self.deadline,
        }
        if self.clock.now() >= deadline:
            return "expired"
        self.store.record("handoff-ready", ready, self.source, self.boot)
        print("TICKWITNESS_EC2_HANDOFF_READY " + canonical(ready).decode().strip(), flush=True)
        while self.clock.now() < deadline:
            if self.store.exists("controller-cancel.json"):
                cancelled = self.store.record_read("controller-cancel", self.source, self.boot)
                if (
                    cancelled["controller_pid"] != self.start["controller_pid"]
                    or cancelled["controller_start_ticks"] != self.start["controller_start_ticks"]
                    or cancelled["invocation_id"] != guard.invocation_id
                    or cancelled["main_pid"] != guard.main.pid
                    or not self.started <= cancelled["requested_ns"] <= self.clock.now()
                ):
                    raise Refused("Cancel is not bound to the original live controller")
                return "cancelled"
            if self.store.exists("handoff-ack.json"):
                ack = self.store.record_read("handoff-ack", self.source, self.boot)
                validate_handoff(self.source, self.store, self.host, self.clock, ready, ack)
                return "acknowledged"
            if self.host.live(self.source, self.start) != guard:
                return "failed"
            self.clock.sleep(min(0.1, max(0, deadline - self.clock.now()) / 1e9))
        return "expired"


def _history_roots() -> tuple[Path, ...]:
    return (
        ROOT / "host-admission.json",
        ROOT / "recovery-plan.json",
        ROOT / "recovery-consumption.json",
        ROOT / "recovery-evidence",
        ROOT / "recovery-v2",
        *(ROOT / "runs" / run for run in OLD_RUNS),
        *(ROOT / "sources" / source for source in OLD_SOURCES),
    )


def bounded_files(
    store: Store, roots: tuple[Path, ...], *, required: bool
) -> tuple[
    list[Path],
    list[str],
]:
    """Enumerate fixed trees, rejecting links, special files and mounted subtrees."""
    files: list[Path] = []
    absent: list[str] = []
    total = 0
    for root in roots:
        try:
            info = root.lstat()
        except FileNotFoundError:
            if required:
                raise Refused("Missing historical root: " + str(root)) from None
            absent.append(str(root))
            continue
        device = info.st_dev
        pending = [root]
        while pending:
            path = pending.pop()
            if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path.parts[1:]):
                raise Refused("Unsafe fixed-tree filename")
            info = path.lstat()
            if info.st_dev != device:
                raise Refused("Mounted subtree in fixed evidence tree")
            if stat.S_ISDIR(info.st_mode):
                store.ancestry(path)
                pending.extend(sorted(path.iterdir(), reverse=True))
            elif stat.S_ISREG(info.st_mode):
                stream, _ = store.open_file(path)
                stream.close()
                files.append(path)
                total += info.st_size
            else:
                raise Refused("Symlink or special file in fixed evidence tree")
            if len(files) + len(pending) > 10000 or total > RAW_LIMIT:
                raise Refused("Evidence tree exceeds fixed bound")
    return sorted(set(files)), absent


def history_snapshot(store: Store) -> list[Row]:
    files, _ = bounded_files(store, _history_roots(), required=True)
    result = []
    for path in files:
        raw, seal = store.read(path, RAW_LIMIT)
        result.append({"path": str(path), "stat": seal, "sha256": hashlib.sha256(raw).hexdigest()})
    return result


def _start(store: Store, host: HostPort, source: str) -> Row:
    return store.record_read("controller-start", source, host.boot())


def _same_guard(ready: Row, guard: GuardIdentity, start: Row) -> None:
    if (
        ready["invocation_id"] != guard.invocation_id
        or ready["main_pid"] != guard.main.pid
        or ready["main_start_ticks"] != guard.main.start_ticks
        or ready["main_argv"] != guard.main.argv
        or ready["guard_exec_start"] != guard.exec_start
        or ready["guard_control_group"] != guard.cgroup
        or ready["controller_pid"] != start["controller_pid"]
        or ready["controller_start_ticks"] != start["controller_start_ticks"]
        or ready["controller_argv"] != start["controller_argv"]
        or ready["outer_deadline_ns"] != start["outer_deadline_ns"]
        or ready["started_ns"] < start["started_ns"]
    ):
        raise Refused("Ready is not the same original guard/master/clock")


def validate_handoff(
    source: str, store: Store, host: HostPort, clock: ClockPort, ready: Row, ack: Row
) -> None:
    boot = host.boot()
    validate_record(ready, "handoff-ready", source, boot)
    validate_record(ack, "handoff-ack", source, boot)
    start = _start(store, host, source)
    guard = host.live(source, start)
    _same_guard(ready, guard, start)
    if any(ack[key] != ready[key] for key in KEYS["handoff-ack"] - {"kind"}):
        raise Refused("ACK does not bind the exact downloaded ready record")
    if clock.now() >= min(ready["deadline_ns"], start["outer_deadline_ns"]):
        raise Refused("Original handoff window expired")
    seal, digest = store.archive()
    if seal != ready["archive_stat"] or digest != ready["sha256"]:
        raise Refused("Archive changed after ready publication")
    # Expensive hashing and live process checks consume the original window.
    if host.live(source, start) != guard or clock.now() >= ready["deadline_ns"]:
        raise Refused("Handoff identity changed or expired during verification")


def acknowledge(source: str, store: Store, host: HostPort, clock: ClockPort, supplied: Row) -> None:
    boot = host.boot()
    ready = store.record_read("handoff-ready", source, boot)
    ack = {
        "kind": "restricted_reference_ec2_handoff_ack_v3",
        "schema_version": 3,
        "source_revision": source,
        "run_id": RUN_ID,
        **supplied,
    }
    validate_handoff(source, store, host, clock, ready, ack)
    # No writes have occurred before all the checks above, including the last clock.
    store.record(
        "handoff-ack",
        ack,
        source,
        boot,
        before_create=lambda: validate_handoff(source, store, host, clock, ready, ack),
    )


def cancel(source: str, store: Store, host: HostPort, clock: ClockPort, supplied: Row) -> None:
    expected = {"boot_id", "invocation_id", "main_pid", "controller_pid"}
    if (
        set(supplied) != expected
        or not uuid_string(supplied["boot_id"])
        or not hex_string(supplied["invocation_id"], 32)
        or not integer(supplied["main_pid"], 1)
        or not integer(supplied["controller_pid"], 1)
    ):
        raise Refused("Cancel exact caller identity fields")
    start = _start(store, host, source)
    guard = host.live(source, start)
    requested = clock.now()
    if (
        supplied["boot_id"] != start["boot_id"]
        or supplied["invocation_id"] != guard.invocation_id
        or supplied["main_pid"] != guard.main.pid
        or supplied["controller_pid"] != start["controller_pid"]
        or not start["started_ns"] <= requested < start["outer_deadline_ns"]
    ):
        raise Refused("Cancel stale/wrong original guard identity")
    value = {
        "kind": "restricted_reference_ec2_controller_cancel_v3",
        "schema_version": 3,
        "source_revision": source,
        "run_id": RUN_ID,
        **supplied,
        "controller_start_ticks": start["controller_start_ticks"],
        "requested_ns": requested,
    }

    def before_create() -> None:
        if host.live(source, start) != guard:
            raise Refused("Cancel target changed before exclusive publication")
        now = clock.now()
        if not requested <= now < start["outer_deadline_ns"]:
            raise Refused("Cancel expired during publication verification")

    store.record("controller-cancel", value, source, start["boot_id"], before_create=before_create)
    if host.live(source, start) != guard or clock.now() >= start["outer_deadline_ns"]:
        raise Refused("Guard changed after cancel record; no signal sent")
    host.stop(guard)


class LimitedWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.count = 0

    def write(self, data: bytes) -> int:
        if self.count + len(data) > ARCHIVE_LIMIT:
            raise Refused("Compressed archive exceeds 16MiB")
        written = self.stream.write(data)
        self.count += written
        return written

    def flush(self) -> None:
        self.stream.flush()


def export_archive(source: str, store: Store) -> None:
    """One child exports actual fixed files; late records are explicitly outside."""
    before, _ = store.read(store.operation / "history-before.log", RAW_LIMIT)
    after = canonical(history_snapshot(store))
    store.write("history-after.log", after)
    if before != after:
        raise Refused("Historical bytes/inodes changed before export")
    operation_names = (
        "controller-start.json",
        "qualifier-exit.json",
        "export-call.json",
        "export-consumption.json",
        "batch-source.sh",
        "preparer-source.sh",
        "handoff-source.py",
        "preparation.stdout",
        "preparation.stderr",
        "qualification.stdout",
        "qualification.stderr",
        "source-check.log",
        "history-before.log",
        "history-prepared.log",
        "history-after.log",
    )
    roots = (
        *_history_roots(),
        ROOT / "recovery-v3",
        ROOT / "runs" / RUN_ID,
        ROOT / "sources" / source,
        *(store.operation / name for name in operation_names),
    )
    files, absent = bounded_files(store, roots, required=False)
    inventory: Row = {
        "absent": absent,
        "inventory_only": [
            str(store.operation / name)
            for name in (
                "export.stdout",
                "export.stderr",
                "handoff-ready.json",
                "handoff-ack.json",
                "controller-cancel.json",
                "controller-result.json",
            )
        ],
        "archived": [],
    }
    fd = os.open(
        store.operation / "archive.pending",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
    )
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            limited = LimitedWriter(stream)
            with tarfile.open(fileobj=limited, mode="w|gz", format=tarfile.PAX_FORMAT) as archive:
                for path in files:
                    raw, seal = store.read(path, RAW_LIMIT)
                    name = str(path.relative_to(store.archive_base))
                    item = tarfile.TarInfo(name)
                    item.mode = stat.S_IMODE(seal["mode"])
                    item.uid, item.gid = seal["uid"], seal["gid"]
                    item.size = len(raw)
                    item.mtime = seal["mtime_ns"] // 1_000_000_000
                    archive.addfile(item, io.BytesIO(raw))
                    inventory["archived"].append(
                        {"path": str(path), "stat": seal, "sha256": hashlib.sha256(raw).hexdigest()}
                    )
                raw = canonical(inventory)
                item = tarfile.TarInfo("export-inventory.json")
                item.size, item.mode = len(raw), 0o400
                archive.addfile(item, io.BytesIO(raw))
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    # Hard-link is an exclusive publication, never replacement. Crash at nlink=2
    # remains uncertain/USED; only this successful publication unlinks pending.
    os.link(
        store.operation / "archive.pending",
        store.operation / "evidence.tar.gz",
        follow_symlinks=False,
    )
    store.fsync_directory(store.operation)
    os.unlink(store.operation / "archive.pending")
    store.fsync_directory(store.operation)
    seal, digest = store.archive()
    print(
        f"TICKWITNESS_EC2_ARCHIVE_PUBLISHED run={RUN_ID} bytes={seal['size']} sha256={digest}",
        flush=True,
    )


def internal_export(source: str, store: Store, host: Host, clock: ClockPort) -> None:
    start = _start(store, host, source)
    guard = host.live(source, start)
    call = store.record_read("export-call", source, host.boot())
    child = host.process(os.getpid())
    expected = [
        "/usr/bin/python3",
        "-I",
        str(STAGE / "ec2_reference_handoff_v3.py"),
        "internal-export",
        "--source-revision",
        source,
        "--run-id",
        RUN_ID,
    ]
    if (
        call["controller_pid"] != start["controller_pid"]
        or call["controller_start_ticks"] != start["controller_start_ticks"]
        or not start["started_ns"] <= call["started_ns"] <= clock.now()
        or child.ppid != start["controller_pid"]
        or child.cgroup != guard.cgroup
        or child.argv != expected
        or clock.now() >= start["outer_deadline_ns"]
    ):
        raise Refused("Exporter must be the original master's direct live child")
    value = {
        "kind": "restricted_reference_ec2_export_consumption_v3",
        "schema_version": 3,
        "source_revision": source,
        "run_id": RUN_ID,
        "boot_id": host.boot(),
        "controller_pid": start["controller_pid"],
        "controller_start_ticks": start["controller_start_ticks"],
        "started_ns": clock.now(),
    }
    store.record("export-consumption", value, source, start["boot_id"])
    export_archive(source, store)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "ack", "cancel", "internal-export"):
        child = commands.add_parser(command, allow_abbrev=False)
        child.add_argument("--source-revision", required=True)
        child.add_argument("--run-id", required=True, choices=(RUN_ID,))
        if command in ("ack", "cancel"):
            child.add_argument("--boot-id", required=True)
            child.add_argument("--invocation-id", required=True)
            child.add_argument("--main-pid", required=True, type=int)
            child.add_argument("--controller-pid", required=True, type=int)
        if command == "ack":
            child.add_argument("--nonce", required=True)
            child.add_argument("--bytes", required=True, type=int)
            child.add_argument("--sha256", required=True)
    result = parser.parse_args(argv)
    if not hex_string(result.source_revision, 40):
        parser.error("source revision must be an exact lowercase Git commit")
    return result


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if os.geteuid() != 0 or sys.platform != "linux" or platform.machine() != "x86_64":
        raise Refused("Only the fixed root Linux x86_64 reference is supported")
    release = Path("/etc/os-release").read_text()
    if not re.search(r"^ID=ubuntu$", release, re.MULTILINE) or not re.search(
        r'^VERSION_ID="24\.04"$', release, re.MULTILINE
    ):
        raise Refused("Only the fixed Ubuntu 24.04 reference is supported")
    os.umask(0o077)
    store, clock = Store(), Clock()
    host = Host(store)
    if args.command == "run":
        return Controller(
            args.source_revision, store, host, ProcessRunner(clock, store), clock
        ).run()
    if args.command == "internal-export":
        internal_export(args.source_revision, store, host, clock)
        return 0
    supplied = {
        key: getattr(args, key)
        for key in (
            "boot_id",
            "invocation_id",
            "main_pid",
            "controller_pid",
        )
    }
    if args.command == "ack":
        supplied.update({key: getattr(args, key) for key in ("nonce", "bytes", "sha256")})
        acknowledge(args.source_revision, store, host, clock, supplied)
    else:
        cancel(args.source_revision, store, host, clock, supplied)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"TICKWITNESS_EC2_OPERATION_REFUSED {error}", file=sys.stderr, flush=True)
        raise SystemExit(74) from error
