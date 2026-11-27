#!/usr/bin/env python3
"""Read fixed existing EC2 evidence; never import or invoke its old authority.

The private deployment packet replaces only PIN_SET_B64 with reviewed data.
CLI callers must use the native 25s+2s watchdog (120s+2s for the original-window
post waiter). The existing independent sleep300 lifecycle guard owns Stop.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import errno
import hashlib
import json
import os
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

PIN_SET_B64 = "__TICKWITNESS_PIN_SET_B64__"

Row = dict[str, Any]
OBSERVATION_ID = "ec2-readback-20261127-run0004-01"
SOURCE = "908d56db32439f38686346687a5b43239b1b7264"
RUN_ID = "ec201aab11254e8bb7cd1573a96a0004"
ORIGINAL_BOOT = "352c3c3d-d057-4ce8-838d-2f46738624bf"
ORIGINAL_INVOCATION = "4c261176550240faba960a772ebc1048"
ARCHIVE_SHA = "2b4421e622e0d3a17f0ad3b71495b2285389b6bfaa9fc0879e54e6ebe47230a9"
ARCHIVE_BYTES = 428942
READY_SHA = "9543a4fbe9d8a6da74a90bda73b8c4e91733623ad818f7a989d8cba173c9430f"
AUDIT_SHA = "db1f359f6b9d2a83307388630cdb4b4e9014ef83f4f6b741d344f66074c34a73"
ROOT = "/var/lib/tickwitness-reference-ec2"
OPERATION = "/var/lib/tickwitness-lifecycle/reference-batches/" + RUN_ID
STAGE = "/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3"
UNIT = "tickwitness-test-session.service"
MISSING_GUARD = {
    "ActiveState": "inactive",
    "SubState": "dead",
    "InvocationID": "",
    "MainPID": "0",
    "ExecStart": "",
    "ControlGroup": "",
    "User": "",
    "DropInPaths": "",
    "LoadState": "not-found",
}
LAST_ENV = "/var/lib/tickwitness-lifecycle/last-test-result.env"
ARCHIVE = OPERATION + "/evidence.tar.gz"
READY = OPERATION + "/handoff-ready.json"
JSON_LIMIT = 65536
PIN_LIMIT = 1048576
FRAME_LIMIT = 131072
STREAM_LIMIT = 16777216
PAYLOAD_LIMIT = 67108864
MODES = (
    "snapshot",
    "archive",
    "post-records",
    "capture-env",
    "inventory",
    "journal-boot",
    "journal-unit",
    "journal-invocation",
)
OLD_BOOTS = {
    "122c5232-f007-4fe1-b555-6797ee475eba",
    "503b0e3e-0efe-4d7c-99b3-e282176c4c29",
    "5fc1dec3-13e7-4d43-b584-314aedc95e6b",
    "5e83ad22-d623-4ddd-87f8-41a27a599f2d",
    ORIGINAL_BOOT,
}
OLD_SOURCES = {
    "ae3d8e7981a79d6fc692f2cb656534a2f9a6683b",
    "d5f5fab9978d0cb2d1fed92f32552632705d52ee",
    "fae7fad81fe6107f0227fe70a9e9a3feeda52346",
    SOURCE,
}
SOURCE_NAMES = (
    "src/tickwitness/infrastructure/restricted_reference_ec2.py",
    "scripts/qualify_restricted_reference_ec2.py",
    "scripts/prepare_reference_policy_ec2.py",
    "scripts/prepare_reference_policy.py",
    "scripts/qualify_restricted_reference.py",
    "src/tickwitness/infrastructure/restricted_reference.py",
    "src/tickwitness/infrastructure/restricted_reference_bootstrap.py",
    "scripts/restricted_reference_payload.py",
    "research/security/reference-ec2.apparmor",
    "scripts/prepare_ec2_reference_recovery_v3.py",
)
SOURCE_PATHS = {"/opt/tickwitness-reference/" + SOURCE + "/" + name for name in SOURCE_NAMES}
POST_NAMES = (
    "controller-result.json",
    "handoff-ack.json",
    "export.stdout",
    "export.stderr",
    "handoff-ready.json",
    "controller-start.json",
    "qualifier-exit.json",
    "export-call.json",
    "export-consumption.json",
    "controller-cancel.json",
    "qualification.stdout",
    "qualification.stderr",
)
OPERATION_NAMES = set(POST_NAMES) | {
    "batch-source.sh",
    "preparer-source.sh",
    "handoff-source.py",
    "preparation.stdout",
    "preparation.stderr",
    "source-check.log",
    "history-before.log",
    "history-prepared.log",
    "history-after.log",
    "evidence.tar.gz",
}
LIFECYCLE_SHA = {
    "/usr/local/sbin/tickwitness-run-tests": (
        "3ffa94999948a32c2efdd5f5999f8a410d91c4b56ff32390489e7acaf9c37b32"
    ),
    "/usr/local/libexec/tickwitness-stop-after-test": (
        "8814afcb2172781e4f8b53b772205fa0a9498712dc235f87e63dfb1e3f86176c"
    ),
    "/etc/systemd/system/tickwitness-boot-deadline.timer": (
        "16320eba4e809a6bcf2fd47a1670d39b95f500b3275fd2fc7bdcc67ec6b820d6"
    ),
    "/etc/systemd/system/tickwitness-boot-deadline.service": (
        "5ac5d11c5f09e748636913fe76ab3202a681077ce6f221f298750f05ebb49fa4"
    ),
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
PIN_KEYS = {
    "kind",
    "schema_version",
    "observation_id",
    "source_revision",
    "run_id",
    "original_boot_id",
    "original_invocation_id",
    "original_archive_sha256",
    "original_archive_bytes",
    "original_ready_sha256",
    "origin_audit_index_sha256",
    "files",
    "source_files",
}
FILE_KEYS = {"path", "status", "bytes", "sha256", "stat", "raw_b64"}
BASE_KEYS = {
    "kind",
    "schema_version",
    "observation_id",
    "source_revision",
    "run_id",
    "original_boot_id",
    "server_boot_id",
}
SNAPSHOT_KEYS = BASE_KEYS | {"server_now_ns", "ready", "archive", "guard", "master", "live"}
ARCHIVE_KEYS = BASE_KEYS | {"phase", "path", "bytes", "sha256", "stat"}
POST_BEGIN_KEYS = BASE_KEYS | {
    "mode",
    "wait_existing_terminal",
    "ready_sha256",
    "invocation_id",
    "server_now_ns",
    "deadline_ns",
    "record_names",
}
POST_RECORD_KEYS = BASE_KEYS | {"sequence", "record"}
POST_END_KEYS = BASE_KEYS | {"mode", "records", "sha256", "complete", "reason", "deadline_ns"}
INVENTORY_KEYS = BASE_KEYS | {
    "files_verified",
    "source_files_verified",
    "source_original_inode",
    "source_current_stats",
}
CAPTURE_ENV_KEYS = BASE_KEYS | {"record"}
JOURNAL_KEYS = BASE_KEYS | {
    "mode",
    "bytes",
    "sha256",
    "producer_exit_code",
    "complete",
    "query",
    "producer_stderr_b64",
}
GUARD_KEYS = {
    "active_state",
    "sub_state",
    "invocation_id",
    "main_pid",
    "main_start_ticks",
    "main_argv",
    "exec_start",
    "control_group",
    "user",
}
MASTER_KEYS = {"pid", "start_ticks", "argv", "cgroup", "ppid", "effective_uid"}
PRESENT = {"PRESENT", "PRESENT_EMPTY"}
FILE_STATUSES = PRESENT | {"ABSENT", "UNREADABLE", "UNSAFE", "CHANGED", "TOO_LARGE"}
STAGE_PATHS = {
    STAGE + "/" + name
    for name in (
        "run_ec2_reference_recovery_v3.sh",
        "provision_ec2_reference_source.sh",
        "ec2_reference_handoff_v3.py",
    )
}


class Refused(RuntimeError):
    """No observation failure grants a write, acknowledgement or renewed clock."""


class ReaderAlarm(Refused):
    """The original command/watchdog deadline requests bounded cleanup."""


class ReadError(Refused):
    def __init__(self, status: str, raw: bytes | None = None, seal: Row | None = None) -> None:
        super().__init__(status)
        self.status, self.raw, self.seal = status, raw, seal


class ProcessGone(Refused):
    def __init__(self, start_ticks: int) -> None:
        super().__init__("Observed process is no longer live")
        self.start_ticks = start_ticks


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def exact(value: object, keys: set[str], label: str) -> Row:
    if type(value) is not dict or set(value) != keys:
        raise Refused("Unknown or missing " + label + " fields")
    return value


def integer(value: object, low: int = 0, high: int = 2**63 - 1) -> bool:
    return type(value) is int and low <= value <= high


def decimal(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,23}", value) is not None


def hex_string(value: object, size: int) -> bool:
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{size}}}", value) is not None


def uuid_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is not None
    )


def strict_json(raw: bytes, limit: int = FRAME_LIMIT) -> Row:
    if not 0 < len(raw) <= limit:
        raise Refused("Bounded JSON required")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refused("Duplicate JSON field")
            result[key] = value
        return result

    def bad_constant(_value):
        raise Refused("Non-JSON numeric constant")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
    except (ValueError, UnicodeError) as error:
        raise Refused("Malformed JSON") from error
    if type(value) is not dict:
        raise Refused("JSON object required")
    return value


def validate_stat(value: object, *, owner: int | None = None) -> Row:
    row = exact(value, STAT_KEYS, "stat")
    if not all(decimal(item) for item in row.values()):
        raise Refused("Stat fields require lossless unsigned decimal strings")
    if (
        int(row["inode"]) < 1
        or int(row["nlink"]) != 1
        or (owner is not None and int(row["uid"]) != owner)
        or not stat.S_ISREG(int(row["mode"]))
        or int(row["mode"]) & 0o022
    ):
        raise Refused("Unsafe original regular-file stat")
    return row


def allowed_path(value: object) -> bool:
    if (
        not isinstance(value, str)
        or len(value) > 768
        or not value.startswith("/")
        or str(Path(value)) != value
        or ".." in Path(value).parts
        or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
    ):
        return False
    if value in SOURCE_PATHS or value in STAGE_PATHS or value in LIFECYCLE_SHA or value == LAST_ENV:
        return True
    if value.startswith(OPERATION + "/"):
        return value[len(OPERATION) + 1 :] in OPERATION_NAMES
    if value in {
        ROOT + "/host-admission.json",
        ROOT + "/recovery-plan.json",
        ROOT + "/recovery-consumption.json",
        ROOT + "/recovery-evidence/operator-stop.md",
    }:
        return True
    for version in (2, 3):
        if value in {
            ROOT + f"/recovery-v{version}/" + name
            for name in ("plan.json", "consumption.json", "operator-stop.md")
        }:
            return True
    for source in OLD_SOURCES:
        if value == ROOT + "/sources/" + source + "/source-lock.json":
            return True
    for index in (1, 2, 3, 4):
        prefix = ROOT + f"/runs/ec201aab11254e8bb7cd1573a96a000{index}/"
        if value.startswith(prefix):
            relative = value[len(prefix) :]
            return bool(relative) and len(Path(relative).parts) <= 12
    return False


def protected_limit(path: str) -> int:
    if path == ARCHIVE:
        return STREAM_LIMIT
    if path in SOURCE_PATHS or path.endswith(
        ("history-before.log", "history-after.log", "history-prepared.log")
    ):
        return PIN_LIMIT
    return 2 * PIN_LIMIT


class PinSet:
    def __init__(self, raw: bytes, *, owner: int = 0) -> None:
        self.data = exact(strict_json(raw, PIN_LIMIT), PIN_KEYS, "pin set")
        expected = {
            "kind": "ec2_transport_pin_set_v1",
            "schema_version": 1,
            "observation_id": OBSERVATION_ID,
            "source_revision": SOURCE,
            "run_id": RUN_ID,
            "original_boot_id": ORIGINAL_BOOT,
            "original_invocation_id": ORIGINAL_INVOCATION,
            "original_archive_sha256": ARCHIVE_SHA,
            "original_archive_bytes": ARCHIVE_BYTES,
            "original_ready_sha256": READY_SHA,
            "origin_audit_index_sha256": AUDIT_SHA,
        }
        for key, value in expected.items():
            if type(self.data[key]) is not type(value) or self.data[key] != value:
                raise Refused("Pin set does not bind the original observation: " + key)
        self.files: dict[str, Row] = {}
        self.source_files: dict[str, Row] = {}
        for name, destination, keys in (
            ("files", self.files, {"path", "bytes", "sha256", "stat"}),
            ("source_files", self.source_files, {"path", "bytes", "sha256"}),
        ):
            rows = self.data[name]
            if type(rows) is not list or not 0 < len(rows) <= 10000:
                raise Refused("Bounded pin rows required")
            for item in rows:
                row = exact(item, keys, "pin row")
                path = row["path"]
                if (
                    not allowed_path(path)
                    or path == LAST_ENV
                    or path in self.files
                    or path in self.source_files
                    or not integer(row["bytes"], 0, protected_limit(path))
                    or not hex_string(row["sha256"], 64)
                ):
                    raise Refused("Unsafe, duplicate or oversized protected pin")
                if name == "source_files":
                    if path not in SOURCE_PATHS:
                        raise Refused("Source pins cannot expand the ten-file closure")
                else:
                    seal = validate_stat(row["stat"], owner=owner)
                    if int(seal["size"]) != row["bytes"]:
                        raise Refused("Original size pin differs")
                destination[path] = row
        if set(self.source_files) != SOURCE_PATHS or not {READY, ARCHIVE}.issubset(self.files):
            raise Refused("Exact source closure and original ready/archive pins required")
        if (
            self.files[READY]["sha256"] != READY_SHA
            or self.files[ARCHIVE]["sha256"] != ARCHIVE_SHA
            or self.files[ARCHIVE]["bytes"] != ARCHIVE_BYTES
        ):
            raise Refused("Original ready/archive pin differs from the frozen transfer")
        total = sum(row["bytes"] for path, row in self.files.items() if path != ARCHIVE)
        total += sum(row["bytes"] for row in self.source_files.values())
        if total > PAYLOAD_LIMIT:
            raise Refused("Protected source payload exceeds aggregate bound")


def stat_record(info: os.stat_result) -> Row:
    return dict(
        zip(
            ("device", "inode", "mode", "uid", "gid", "nlink", "size", "mtime_ns", "ctime_ns"),
            map(
                str,
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
            ),
            strict=True,
        )
    )


class SafeFiles:
    """Readonly real descriptors; a constructor-only trust root supports remote fixtures."""

    def __init__(self, root: Path = Path("/"), *, owner: int = 0) -> None:
        self.root, self.owner = root, owner

    def path(self, logical: str) -> Path:
        if not allowed_path(logical):
            raise Refused("Path is outside the fixed evidence allowlist")
        return self.root / logical.lstrip("/")

    def ancestry(self, directory: Path) -> tuple[tuple[str, int, int], ...]:
        if not directory.is_relative_to(self.root):
            raise Refused("Path escaped trusted root")
        current = self.root
        identities = []
        for part in ("", *directory.relative_to(self.root).parts):
            if part:
                current /= part
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner or info.st_mode & 0o022:
                raise Refused("Unsafe readonly ancestry")
            identities.append((str(current), info.st_dev, info.st_ino))
        return tuple(identities)

    def read(self, logical: str, limit: int) -> tuple[bytes | None, Row | None]:
        path = self.path(logical)
        parents = self.ancestry(path.parent)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except FileNotFoundError:
            if self.ancestry(path.parent) != parents:
                raise Refused("Parent identity changed while observing absence") from None
            try:
                path.lstat()
            except FileNotFoundError:
                return None, None
            raise Refused("Leaf changed while observing absence") from None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise Refused("Unsafe evidence symlink") from error
            raise
        try:
            info = os.fstat(fd)
            before = stat_record(info)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.owner
                or info.st_nlink != 1
                or info.st_mode & 0o022
                or before != stat_record(path.lstat())
            ):
                raise Refused("Unsafe or oversized regular evidence file")
            if info.st_size > limit:
                prefix = os.read(fd, limit)
                raise ReadError("TOO_LARGE", prefix, before)
            pieces, remaining = [], limit + 1
            while remaining:
                piece = os.read(fd, min(65536, remaining))
                if not piece:
                    break
                pieces.append(piece)
                remaining -= len(piece)
            raw = b"".join(pieces)
            try:
                unchanged = (
                    before == stat_record(os.fstat(fd))
                    and before == stat_record(path.lstat())
                    and self.ancestry(path.parent) == parents
                )
            except (OSError, Refused):
                unchanged = False
            if len(raw) != info.st_size or len(raw) > limit or not unchanged:
                raise ReadError("CHANGED", raw, before)
            return raw, before
        finally:
            os.close(fd)


def file_record(path: str, raw: bytes | None, seal: Row | None, *, metadata: bool = False) -> Row:
    return {
        "path": path,
        "status": "ABSENT" if raw is None else "PRESENT" if raw else "PRESENT_EMPTY",
        "bytes": None if raw is None else len(raw),
        "sha256": None if raw is None else sha(raw),
        "stat": seal,
        "raw_b64": None if raw is None or metadata else base64.b64encode(raw).decode(),
    }


def validate_file_record(value: object, *, allow_metadata: bool = False) -> None:
    row = exact(value, FILE_KEYS, "file record")
    if (
        not allowed_path(row["path"])
        or not isinstance(row["status"], str)
        or row["status"] not in FILE_STATUSES
    ):
        raise Refused("Invalid file record path/status")
    if row["status"] not in PRESENT | {"CHANGED", "TOO_LARGE"}:
        if any(row[key] is not None for key in ("bytes", "sha256", "stat", "raw_b64")):
            raise Refused("Unavailable file cannot invent bytes or a stat")
        return
    if not integer(row["bytes"], 0, STREAM_LIMIT) or not hex_string(row["sha256"], 64):
        raise Refused("Invalid retained file byte binding")
    seal = validate_stat(row["stat"])
    if row["status"] in PRESENT and (
        int(seal["size"]) != row["bytes"]
        or (row["status"] == "PRESENT_EMPTY") != (row["bytes"] == 0)
    ):
        raise Refused("File status/size differs")
    if row["raw_b64"] is None:
        if not allow_metadata:
            raise Refused("Required original bytes are missing")
    else:
        if not isinstance(row["raw_b64"], str):
            raise Refused("Base64 must be a string")
        try:
            raw = base64.b64decode(row["raw_b64"], validate=True)
        except (ValueError, binascii.Error) as error:
            raise Refused("Invalid original base64 bytes") from error
        if len(raw) != row["bytes"] or sha(raw) != row["sha256"]:
            raise Refused("Original bytes do not match hash/length")


def _argv(value: object) -> bool:
    return (
        type(value) is list
        and 0 < len(value) <= 64
        and all(isinstance(item, str) and 0 < len(item) <= 4096 for item in value)
        and sum(len(item) for item in value) <= 16384
    )


def validate_guard(value: object) -> Row:
    row = exact(value, GUARD_KEYS, "guard")
    if (
        not all(
            isinstance(row[key], str)
            for key in (
                "active_state",
                "sub_state",
                "invocation_id",
                "exec_start",
                "control_group",
                "user",
            )
        )
        or not integer(row["main_pid"])
        or not integer(row["main_start_ticks"])
        or not (
            (row["main_pid"] == 0 and row["main_start_ticks"] == 0 and row["main_argv"] == [])
            or (row["main_pid"] > 0 and row["main_start_ticks"] > 0 and _argv(row["main_argv"]))
        )
    ):
        raise Refused("Invalid guard observation")
    return row


def validate_master(value: object) -> Row:
    row = exact(value, MASTER_KEYS, "master")
    if (
        not all(integer(row[key], 1) for key in ("pid", "start_ticks", "ppid"))
        or not integer(row["effective_uid"])
        or not _argv(row["argv"])
        or not isinstance(row["cgroup"], str)
    ):
        raise Refused("Invalid master observation")
    return row


def decode_frame(raw: bytes) -> Row:
    row = strict_json(raw)
    shapes = {
        "ec2_reader_snapshot_v1": SNAPSHOT_KEYS,
        "ec2_reader_archive_v1": ARCHIVE_KEYS,
        "ec2_reader_post_begin_v1": POST_BEGIN_KEYS,
        "ec2_reader_post_record_v1": POST_RECORD_KEYS,
        "ec2_reader_post_end_v1": POST_END_KEYS,
        "ec2_reader_inventory_v1": INVENTORY_KEYS,
        "ec2_reader_capture_env_v1": CAPTURE_ENV_KEYS,
        "ec2_reader_journal_v1": JOURNAL_KEYS,
    }
    if not isinstance(row.get("kind"), str) or row["kind"] not in shapes:
        raise Refused("Unknown reader frame")
    exact(row, shapes[row["kind"]], "reader frame")
    if (
        type(row["schema_version"]) is not int
        or row["schema_version"] != 1
        or row["observation_id"] != OBSERVATION_ID
        or row["source_revision"] != SOURCE
        or row["run_id"] != RUN_ID
        or row["original_boot_id"] != ORIGINAL_BOOT
        or not uuid_string(row["server_boot_id"])
    ):
        raise Refused("Reader frame identity")
    if "server_now_ns" in row and not decimal(row["server_now_ns"]):
        raise Refused("Wire server clock requires an unsigned decimal string")
    if "deadline_ns" in row and row["deadline_ns"] is not None and not decimal(row["deadline_ns"]):
        raise Refused("Wire deadline requires an unsigned decimal string")
    kind = row["kind"]
    if kind == "ec2_reader_snapshot_v1":
        validate_file_record(row["ready"])
        validate_file_record(row["archive"], allow_metadata=True)
        validate_guard(row["guard"])
        if row["master"] is not None:
            validate_master(row["master"])
        if type(row["live"]) is not bool:
            raise Refused("Snapshot live flag")
        if row["live"] != (row["server_boot_id"] == ORIGINAL_BOOT):
            raise Refused("Snapshot cannot conflate current and original boots")
        if row["live"] != (row["master"] is not None):
            raise Refused("Live snapshot must bind its actual original master")
    elif kind == "ec2_reader_archive_v1":
        if (
            row["phase"] not in {"before", "after"}
            or row["path"] != ARCHIVE
            or not integer(row["bytes"], 1, STREAM_LIMIT)
            or not hex_string(row["sha256"], 64)
        ):
            raise Refused("Archive frame fields")
        if int(validate_stat(row["stat"])["size"]) != row["bytes"]:
            raise Refused("Archive frame size")
    elif kind == "ec2_reader_post_begin_v1":
        if (
            row["mode"] != "post-records"
            or type(row["wait_existing_terminal"]) is not bool
            or row["ready_sha256"] != READY_SHA
            or row["invocation_id"] != ORIGINAL_INVOCATION
            or row["record_names"] != list(POST_NAMES)
        ):
            raise Refused("Post header fields")
        if not row["wait_existing_terminal"] and row["deadline_ns"] is not None:
            raise Refused("Historical collection cannot gain a deadline")
        if row["wait_existing_terminal"] and (
            row["server_boot_id"] != ORIGINAL_BOOT
            or row["deadline_ns"] is None
            or int(row["server_now_ns"]) >= int(row["deadline_ns"])
        ):
            raise Refused("Waiter is outside the original live window")
    elif kind == "ec2_reader_post_record_v1":
        if not integer(row["sequence"], 1):
            raise Refused("Record sequence")
        validate_file_record(row["record"])
        if row["record"]["path"] not in {OPERATION + "/" + name for name in POST_NAMES}:
            raise Refused("Post record outside the closed set")
    elif kind == "ec2_reader_inventory_v1":
        if (
            not integer(row["files_verified"], 1, 10000)
            or row["source_files_verified"] != 10
            or type(row["source_files_verified"]) is not int
            or row["source_original_inode"] != "NOT_RECORDED"
        ):
            raise Refused("Inventory summary fields")
        stats = exact(row["source_current_stats"], SOURCE_PATHS, "current source stats")
        for value in stats.values():
            validate_stat(value)
    elif kind == "ec2_reader_capture_env_v1":
        validate_file_record(row["record"])
        if row["record"]["path"] != LAST_ENV:
            raise Refused("Unexpected shared environment path")
    elif kind == "ec2_reader_journal_v1":
        if (
            row["mode"] not in {"journal-boot", "journal-unit", "journal-invocation"}
            or not integer(row["bytes"], 0, STREAM_LIMIT - 1)
            or not hex_string(row["sha256"], 64)
            or type(row["complete"]) is not bool
            or (
                row["producer_exit_code"] is not None and type(row["producer_exit_code"]) is not int
            )
            or not _argv(row["query"])
        ):
            raise Refused("Journal completion fields")
        try:
            diagnostic = base64.b64decode(row["producer_stderr_b64"], validate=True)
        except (ValueError, binascii.Error, TypeError) as error:
            raise Refused("Journal stderr original bytes required") from error
        if len(diagnostic) > JSON_LIMIT:
            raise Refused("Journal stderr exceeds bound")
    elif (
        row["mode"] != "post-records"
        or not integer(row["records"])
        or not hex_string(row["sha256"], 64)
        or type(row["complete"]) is not bool
        or row["reason"] not in {"observed", "terminal", "deadline", "error"}
    ):
        raise Refused("Post footer fields")
    if kind == "ec2_reader_post_end_v1" and (
        row["complete"] != (row["reason"] in {"observed", "terminal"})
        or (row["complete"] and row["records"] < len(POST_NAMES))
    ):
        raise Refused("Post footer cannot promote incomplete evidence")
    return row


class Clock:
    def now(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class Host:
    def boot(self) -> str:
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not uuid_string(value):
            raise Refused("Invalid actual current boot")
        return value

    def process(self, pid: int) -> Row:
        root = Path("/proc") / str(pid)
        before = (root / "stat").read_bytes()
        fields = before[before.rfind(b")") + 2 :].split()
        if len(fields) >= 20 and fields[0] in (b"Z", b"X", b"x"):
            raise ProcessGone(int(fields[19]))
        command = (root / "cmdline").read_bytes()
        if (
            len(fields) < 20
            or fields[0] in (b"Z", b"X", b"x")
            or not command.endswith(b"\0")
            or not 0 < len(command) <= 16384
        ):
            raise Refused("Actual process is missing or not live")
        argv = [part.decode("utf-8", "strict") for part in command[:-1].split(b"\0")]
        groups = (root / "cgroup").read_text().splitlines()
        uid = [
            line.split()[1:]
            for line in (root / "status").read_text().splitlines()
            if line.startswith("Uid:")
        ]
        after = (root / "stat").read_bytes()
        tail = after[after.rfind(b")") + 2 :].split()
        if (
            len(groups) != 1
            or not groups[0].startswith("0::/")
            or len(uid) != 1
            or len(uid[0]) != 4
            or len(tail) < 20
            or fields[19] != tail[19]
            or tail[0] in (b"Z", b"X", b"x")
        ):
            raise Refused("Actual process identity changed")
        return {
            "pid": pid,
            "start_ticks": int(fields[19]),
            "argv": argv,
            "cgroup": groups[0][3:],
            "ppid": int(fields[1]),
            "effective_uid": int(uid[0][1]),
        }

    def show(self, unit: str, names: tuple[str, ...]) -> Row:
        result = subprocess.run(
            [
                "/usr/bin/systemctl",
                "show",
                unit,
                "--all",
                "--no-pager",
                "--property=" + ",".join(names),
            ],
            capture_output=True,
            timeout=3,
            check=False,
        )
        if len(result.stdout) > JSON_LIMIT or len(result.stderr) > JSON_LIMIT:
            raise Refused("Oversized manager observation")
        values = {}
        for line in result.stdout.decode("utf-8", "strict").splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values:
                raise Refused("Invalid manager observation")
            values[key] = value
        if set(values) != set(names):
            raise Refused("Missing manager identity field")
        if result.returncode != 0 and not (
            unit == UNIT and result.returncode in {1, 4} and values == MISSING_GUARD
        ):
            raise Refused("Manager observation failed")
        return values

    def guard(self) -> Row:
        names = (
            "ActiveState",
            "SubState",
            "InvocationID",
            "MainPID",
            "ExecStart",
            "ControlGroup",
            "User",
            "DropInPaths",
            "LoadState",
        )
        first = self.show(UNIT, names)
        if first["LoadState"] == "not-found" and first != MISSING_GUARD:
            raise Refused("Absent transient guard identity was not positively observed")
        if (
            first["DropInPaths"]
            or not first["MainPID"].isascii()
            or not first["MainPID"].isdecimal()
        ):
            raise Refused("Guard configuration changed")
        pid = int(first["MainPID"])
        if pid == 0:
            if first["ActiveState"] not in {"inactive", "failed", "deactivating"} or first[
                "LoadState"
            ] not in {"loaded", "not-found"}:
                raise Refused("Inactive/absent guard was not positively observed")
            return {
                "active_state": first["ActiveState"],
                "sub_state": first["SubState"],
                "invocation_id": first["InvocationID"],
                "main_pid": 0,
                "main_start_ticks": 0,
                "main_argv": [],
                "exec_start": first["ExecStart"],
                "control_group": first["ControlGroup"],
                "user": first["User"],
            }
        try:
            process = self.process(pid)
        except ProcessGone as error:
            if first["ActiveState"] not in {"inactive", "failed", "deactivating"}:
                raise
            if first != self.show(UNIT, names):
                raise Refused("Manager changed while observing exited guard") from None
            return {
                "active_state": first["ActiveState"],
                "sub_state": first["SubState"],
                "invocation_id": first["InvocationID"],
                "main_pid": pid,
                "main_start_ticks": error.start_ticks,
                "main_argv": [],
                "exec_start": first["ExecStart"],
                "control_group": first["ControlGroup"],
                "user": first["User"],
            }
        if process["cgroup"] != first["ControlGroup"] or first != self.show(UNIT, names):
            raise Refused("Guard changed during observation")
        return {
            "active_state": first["ActiveState"],
            "sub_state": first["SubState"],
            "invocation_id": first["InvocationID"],
            "main_pid": pid,
            "main_start_ticks": process["start_ticks"],
            "main_argv": process["argv"],
            "exec_start": first["ExecStart"],
            "control_group": first["ControlGroup"],
            "user": first["User"],
        }

    def lifecycle(self, files: SafeFiles) -> None:
        for path, digest in LIFECYCLE_SHA.items():
            raw, _ = files.read(path, PIN_LIMIT)
            if raw is None or sha(raw) != digest:
                raise Refused("Original lifecycle bytes changed")
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
            or timer["TimersMonotonic"] != "{ OnBootUSec=4h ; next_elapse=4h }"
        ):
            raise Refused("Original four-hour safeguard changed")
        stop = self.show("tickwitness-boot-deadline.service", ("DropInPaths", "FragmentPath"))
        if (
            stop["DropInPaths"]
            or stop["FragmentPath"] != "/etc/systemd/system/tickwitness-boot-deadline.service"
        ):
            raise Refused("Original boot Stop service changed")

    def no_project_process(self) -> None:
        result = subprocess.run(
            [
                "/usr/bin/pgrep",
                "-af",
                "qualify_restricted_reference_ec2[.]py|"
                "ec2_reference_handoff_v3[.]py|run_ec2_reference_recovery_v3[.]sh",
            ],
            capture_output=True,
            timeout=3,
            check=False,
        )
        if result.returncode != 1:
            raise Refused("Project process active or process observation failed")


class Reader:
    def __init__(
        self,
        pins: PinSet,
        files: SafeFiles | None = None,
        host: Host | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.pins = pins
        self.files = SafeFiles() if files is None else files
        self.host = Host() if host is None else host
        self.clock = Clock() if clock is None else clock
        self.source_seals: dict[str, Row] = {}
        self.current_guard: Row | None = None
        self.command_deadline_ns: int | None = None

    def base(self, kind: str, boot: str) -> Row:
        return {
            "kind": kind,
            "schema_version": 1,
            "observation_id": OBSERVATION_ID,
            "source_revision": SOURCE,
            "run_id": RUN_ID,
            "original_boot_id": ORIGINAL_BOOT,
            "server_boot_id": boot,
        }

    def current(self, expected_boot: str, *, capture: bool = False) -> tuple[str, Row]:
        boot = self.host.boot()
        if not uuid_string(expected_boot) or boot != expected_boot:
            raise Refused("Actual current boot differs")
        self.host.lifecycle(self.files)
        guard = self.host.guard()
        if capture:
            if boot in OLD_BOOTS or guard["active_state"] != "inactive" or guard["main_pid"] != 0:
                raise Refused("Capture must precede a new retrieval guard")
            self.host.no_project_process()
        elif boot != ORIGINAL_BOOT:
            process = self.host.process(guard["main_pid"])
            if (
                boot in OLD_BOOTS
                or guard["active_state"] != "active"
                or guard["sub_state"] != "running"
                or guard["main_argv"] != ["/usr/bin/sleep", "300"]
                or guard["user"] != "ubuntu"
                or not hex_string(guard["invocation_id"], 32)
                or guard["control_group"] != "/system.slice/" + UNIT
                or process["effective_uid"] != 1000
                or process["start_ticks"] != guard["main_start_ticks"]
                or "path=/usr/bin/sleep ;" not in guard["exec_start"]
                or "argv[]=/usr/bin/sleep 300 ;" not in guard["exec_start"]
            ):
                raise Refused("Expected the one exact sleep300 retrieval guard")
            if self.current_guard is None:
                self.current_guard = guard
            elif self.current_guard != guard:
                raise Refused("Retrieval guard identity cannot be renewed")
        return boot, guard

    def observed(self, path: str, *, metadata: bool = False) -> Row:
        try:
            raw, seal = self.files.read(path, STREAM_LIMIT if path == ARCHIVE else JSON_LIMIT)
            return file_record(path, raw, seal, metadata=metadata)
        except ReadError as error:
            row = file_record(path, error.raw, error.seal)
            row["status"] = error.status
            return row
        except Refused:
            return {
                "path": path,
                "status": "UNSAFE",
                "bytes": None,
                "sha256": None,
                "stat": None,
                "raw_b64": None,
            }
        except OSError:
            return {
                "path": path,
                "status": "UNREADABLE",
                "bytes": None,
                "sha256": None,
                "stat": None,
                "raw_b64": None,
            }

    def verified(self, path: str) -> tuple[bytes, Row]:
        pin = self.pins.files[path]
        raw, seal = self.files.read(path, protected_limit(path))
        if (
            raw is None
            or sha(raw) != pin["sha256"]
            or len(raw) != pin["bytes"]
            or seal != pin["stat"]
        ):
            raise Refused("Original protected bytes/inode changed: " + path)
        return raw, seal

    def inventory(self, expected_boot: str) -> Row:
        boot, _ = self.current(expected_boot)
        for path in self.pins.files:
            self.verified(path)
        for path, pin in self.pins.source_files.items():
            raw, seal = self.files.read(path, PIN_LIMIT)
            if raw is None or sha(raw) != pin["sha256"] or len(raw) != pin["bytes"]:
                raise Refused("Original source bytes differ")
            if path in self.source_seals and self.source_seals[path] != seal:
                raise Refused("Source inode changed during this readback")
            self.source_seals[path] = seal
        self.current(expected_boot)
        return self.base("ec2_reader_inventory_v1", boot) | {
            "files_verified": len(self.pins.files),
            "source_files_verified": len(self.source_seals),
            "source_original_inode": "NOT_RECORDED",
            "source_current_stats": self.source_seals,
        }

    def ready(self) -> tuple[Row, Row]:
        raw, seal = self.verified(READY)
        row = strict_json(raw, JSON_LIMIT)
        required = {
            "kind",
            "schema_version",
            "source_revision",
            "run_id",
            "boot_id",
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
        }
        exact(row, required, "original ready")
        if (
            row["kind"] != "restricted_reference_ec2_handoff_ready_v3"
            or type(row["schema_version"]) is not int
            or row["schema_version"] != 3
            or row["source_revision"] != SOURCE
            or row["run_id"] != RUN_ID
            or row["boot_id"] != ORIGINAL_BOOT
            or row["invocation_id"] != ORIGINAL_INVOCATION
            or row["unit"] != UNIT
            or row["sha256"] != ARCHIVE_SHA
            or row["bytes"] != ARCHIVE_BYTES
        ):
            raise Refused("Original ready identity differs")
        for key in (
            "main_pid",
            "main_start_ticks",
            "controller_pid",
            "controller_start_ticks",
            "started_ns",
            "deadline_ns",
            "outer_deadline_ns",
            "bytes",
        ):
            if not integer(row[key], 1):
                raise Refused("Original ready requires integer fields")
        if row["deadline_ns"] != min(
            row["started_ns"] + 120_000_000_000, row["outer_deadline_ns"]
        ) or not hex_string(row["nonce"], 32):
            raise Refused("Original ready clock/nonce differs")
        return row, file_record(READY, raw, seal)

    def live(self, ready: Row, guard: Row) -> Row:
        raw, _ = self.verified(OPERATION + "/controller-start.json")
        start = exact(
            strict_json(raw, JSON_LIMIT),
            {
                "kind",
                "schema_version",
                "source_revision",
                "run_id",
                "boot_id",
                "controller_pid",
                "controller_start_ticks",
                "controller_argv",
                "started_ns",
                "outer_deadline_ns",
            },
            "original controller start",
        )
        if (
            start["kind"] != "restricted_reference_ec2_controller_start_v3"
            or type(start["schema_version"]) is not int
            or start["schema_version"] != 3
            or start["source_revision"] != SOURCE
            or start["run_id"] != RUN_ID
            or start["boot_id"] != ORIGINAL_BOOT
            or any(
                start[key] != ready[key]
                for key in (
                    "controller_pid",
                    "controller_start_ticks",
                    "controller_argv",
                    "outer_deadline_ns",
                )
            )
        ):
            raise Refused("Master does not bind the original controller start")
        master = self.host.process(ready["controller_pid"])
        main = self.host.process(guard["main_pid"])
        validate_master(master)
        allowed_uid = {0, 1000} if ready["main_argv"][0] == "/usr/bin/sudo" else {0}
        if (
            self.host.boot() != ORIGINAL_BOOT
            or guard["active_state"] != "active"
            or guard["sub_state"] != "running"
            or guard["invocation_id"] != ready["invocation_id"]
            or guard["main_pid"] != ready["main_pid"]
            or guard["main_start_ticks"] != ready["main_start_ticks"]
            or guard["main_argv"] != ready["main_argv"]
            or guard["exec_start"] != ready["guard_exec_start"]
            or guard["control_group"] != ready["guard_control_group"]
            or master["start_ticks"] != ready["controller_start_ticks"]
            or master["argv"] != ready["controller_argv"]
            or master["effective_uid"] != 0
            or guard["user"] != "ubuntu"
            or main["effective_uid"] not in allowed_uid
            or main["start_ticks"] != ready["main_start_ticks"]
            or main["argv"] != ready["main_argv"]
            or main["cgroup"] != guard["control_group"]
            or master["cgroup"] != guard["control_group"]
            or self.clock.now() >= min(ready["deadline_ns"], ready["outer_deadline_ns"])
        ):
            raise Refused("Original live guard/master/window differs")
        return master

    def snapshot(self, expected_boot: str) -> Row:
        self.inventory(expected_boot)
        boot, guard = self.current(expected_boot)
        ready, retained = self.ready()
        raw, seal = self.verified(ARCHIVE)
        master = self.live(ready, guard) if boot == ORIGINAL_BOOT else None
        self.current(expected_boot)
        value = self.base("ec2_reader_snapshot_v1", boot) | {
            "server_now_ns": str(self.clock.now()),
            "ready": retained,
            "archive": file_record(ARCHIVE, raw, seal, metadata=True),
            "guard": guard,
            "master": master,
            "live": boot == ORIGINAL_BOOT,
        }
        decode_frame(canonical(value))
        return value

    def archive(self, expected_boot: str, output: BinaryIO, metadata: BinaryIO) -> None:
        boot, _ = self.current(expected_boot)
        raw, seal = self.verified(ARCHIVE)
        before = self.base("ec2_reader_archive_v1", boot) | {
            "phase": "before",
            "path": ARCHIVE,
            "bytes": len(raw),
            "sha256": sha(raw),
            "stat": seal,
        }
        metadata.write(canonical(before))
        metadata.flush()
        output.write(raw)
        output.flush()
        after_raw, after_seal = self.verified(ARCHIVE)
        if after_raw != raw or after_seal != seal:
            raise Refused("Archive changed during transfer")
        self.current(expected_boot)
        metadata.write(canonical(before | {"phase": "after"}))
        metadata.flush()

    def post_records(
        self, expected_boot: str, *, wait_existing_terminal: bool = False
    ) -> Iterator[Row]:
        boot, guard = self.current(expected_boot)
        ready, _ = self.ready()
        deadline = None
        if wait_existing_terminal:
            self.live(ready, guard)
            deadline = min(ready["deadline_ns"], ready["outer_deadline_ns"])
            if self.command_deadline_ns is not None:
                self.command_deadline_ns = min(self.command_deadline_ns, deadline)
                remaining = (self.command_deadline_ns - self.clock.now()) / 1e9
                if remaining <= 0:
                    raise ReaderAlarm("Original waiter command deadline expired before output")
                signal.setitimer(signal.ITIMER_REAL, remaining)
        yield self.base("ec2_reader_post_begin_v1", boot) | {
            "mode": "post-records",
            "wait_existing_terminal": wait_existing_terminal,
            "ready_sha256": READY_SHA,
            "invocation_id": ORIGINAL_INVOCATION,
            "server_now_ns": str(self.clock.now()),
            "deadline_ns": None if deadline is None else str(deadline),
            "record_names": list(POST_NAMES),
        }
        digest, count, total, previous = hashlib.sha256(), 0, 0, {}
        complete, reason = False, "error"
        while True:
            rows = {}
            for name in POST_NAMES:
                row = self.observed(OPERATION + "/" + name)
                rows[name] = row
                encoded = canonical(row)
                if previous.get(name) != encoded:
                    count += 1
                    frame = self.base("ec2_reader_post_record_v1", boot) | {
                        "sequence": count,
                        "record": row,
                    }
                    raw = canonical(frame)
                    total += len(raw)
                    if total >= STREAM_LIMIT:
                        raise Refused("Post-record stream reached its bound")
                    digest.update(raw)
                    yield frame
                    previous[name] = encoded
            if any(row["status"] not in PRESENT | {"ABSENT"} for row in rows.values()):
                break
            if not wait_existing_terminal:
                self.current(expected_boot)
                complete, reason = True, "observed"
                break
            if self.host.boot() != boot:
                raise Refused("Waiter cannot follow another boot")
            if self.clock.now() >= deadline:
                reason = "deadline"
                break
            current = self.host.guard()
            if (
                current["invocation_id"] and current["invocation_id"] != guard["invocation_id"]
            ) or (
                current["main_pid"]
                and (
                    current["main_pid"] != guard["main_pid"]
                    or current["main_start_ticks"] != guard["main_start_ticks"]
                    or (current["main_argv"] and current["main_argv"] != guard["main_argv"])
                )
            ):
                raise Refused("Waiter cannot follow a replacement invocation or PID")
            try:
                master = self.host.process(ready["controller_pid"])
            except FileNotFoundError:
                master = None
            except ProcessGone as error:
                if error.start_ticks != ready["controller_start_ticks"]:
                    raise Refused("A stopped PID belongs to another master") from error
                master = None
            if master is not None and (
                master["start_ticks"] != ready["controller_start_ticks"]
                or master["argv"] != ready["controller_argv"]
                or master["cgroup"] != guard["control_group"]
            ):
                raise Refused("Waiter cannot follow a reused master PID")
            if current["active_state"] in {"inactive", "failed", "deactivating"}:
                if rows["controller-result.json"]["status"] in PRESENT:
                    complete, reason = True, "terminal"
                    break
            elif current != guard:
                raise Refused("Waiter cannot follow a replacement guard")
            self.clock.sleep(min(0.1, (deadline - self.clock.now()) / 1e9))
        yield self.base("ec2_reader_post_end_v1", boot) | {
            "mode": "post-records",
            "records": count,
            "sha256": digest.hexdigest(),
            "complete": complete,
            "reason": reason,
            "deadline_ns": None if deadline is None else str(deadline),
        }

    def capture_env(self, expected_boot: str) -> Row:
        boot, _ = self.current(expected_boot, capture=True)
        result = self.observed(LAST_ENV)
        self.current(expected_boot, capture=True)
        return self.base("ec2_reader_capture_env_v1", boot) | {"record": result}

    def journal(self, mode: str, expected_boot: str, output: BinaryIO) -> Row:
        boot, _ = self.current(expected_boot)
        command = [
            "/usr/bin/journalctl",
            "--no-pager",
            "--output=json",
            "--all",
            "_BOOT_ID=" + ORIGINAL_BOOT.replace("-", ""),
        ]
        if mode == "journal-unit":
            command += ["-u", UNIT]
        elif mode == "journal-invocation":
            command += ["_SYSTEMD_INVOCATION_ID=" + ORIGINAL_INVOCATION]
        elif mode != "journal-boot":
            raise Refused("Unknown fixed journal query")
        deadline = self.clock.now() + 25_000_000_000
        if self.command_deadline_ns is not None:
            deadline = min(deadline, self.command_deadline_ns)
        if self.clock.now() >= deadline:
            raise Refused("Original journal deadline exhausted before spawn")
        original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        cleanup: Row = {}
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
        count, errors, digest, complete = 0, bytearray(), hashlib.sha256(), False
        code = None
        try:
            with selectors.DefaultSelector() as selected:
                for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                    if stream is None:
                        raise Refused("Journal pipes missing")
                    os.set_blocking(stream.fileno(), False)
                    selected.register(stream, selectors.EVENT_READ, label)
                while selected.get_map():
                    if self.clock.now() >= deadline:
                        raise Refused("Original journal deadline exhausted")
                    for key, _events in selected.select(0.02):
                        raw = os.read(key.fileobj.fileno(), 65536)
                        if not raw:
                            selected.unregister(key.fileobj)
                            continue
                        if key.data == "stdout":
                            if count + len(raw) >= STREAM_LIMIT:
                                prefix = raw[: STREAM_LIMIT - count]
                                output.write(prefix)
                                output.flush()
                                raise Refused("Journal stdout bound reached")
                            output.write(raw)
                            output.flush()
                            count += len(raw)
                            digest.update(raw)
                        else:
                            if len(errors) + len(raw) > JSON_LIMIT:
                                raise Refused("Journal stderr bound reached")
                            errors.extend(raw)
                # WNOWAIT retains the leader PID, even after exit, until all
                # signals to its owned group are finished. Never signal a
                # potentially reused PGID after first reaping that leader.
                while self.clock.now() < deadline:
                    observed = os.waitid(
                        os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                    )
                    if observed is not None:
                        code = (
                            observed.si_status
                            if observed.si_code == os.CLD_EXITED
                            else -observed.si_status
                        )
                        break
                    self.clock.sleep(0.02)
                if code is None:
                    raise Refused("Journal leader exit unconfirmed inside original deadline")
                complete = code == 0 and count > 0 and not errors
        finally:
            interrupted: ReaderAlarm | None = None
            while True:
                try:
                    stop_journal(process, cleanup, self.command_deadline_ns, original_mask)
                    break
                except ReaderAlarm as error:
                    # Either deadline signal may arrive before the mask is
                    # established. Resume the same grace, without signalling
                    # a group again after its reserved leader was reaped.
                    interrupted = error
            if interrupted is not None:
                raise interrupted
        self.current(expected_boot)
        return self.base("ec2_reader_journal_v1", boot) | {
            "mode": mode,
            "bytes": count,
            "sha256": digest.hexdigest(),
            "producer_exit_code": code,
            "complete": complete,
            "query": command,
            "producer_stderr_b64": base64.b64encode(errors).decode(),
        }


def stop_journal(
    process: subprocess.Popen[bytes],
    state: Row,
    command_deadline_ns: int | None,
    original_mask: set[signal.Signals],
) -> None:
    if state.get("done"):
        return
    if "grace" not in state:
        now = time.monotonic()
        cap = now + 2 if command_deadline_ns is None else command_deadline_ns / 1e9 + 2
        state["grace"] = min(now + 2, cap)
        state["kill_at"] = min(now + 1, state["grace"])
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM, signal.SIGTERM})
    signal.setitimer(signal.ITIMER_REAL, 0)
    stopped = False
    try:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        time.sleep(max(0, state["kill_at"] - time.monotonic()))
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        while time.monotonic() < state["grace"]:
            if owned_group_stopped(process.pid, state["grace"]):
                stopped = True
                break
            time.sleep(min(0.02, max(0, state["grace"] - time.monotonic())))
        # No subsequent attempt may signal this PGID after leader reaping.
        state["done"] = True
        try:
            process.wait(timeout=max(0, state["grace"] - time.monotonic()))
        except subprocess.TimeoutExpired:
            stopped = False
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        for signum in (signal.SIGALRM, signal.SIGTERM):
            if signum in signal.sigpending():
                signal.sigtimedwait({signum}, 0)
        if command_deadline_ns is not None:
            remaining = (command_deadline_ns - time.monotonic_ns()) / 1e9
            if remaining > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining)
        signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)
    if not stopped:
        raise Refused("Journal owned group stop unconfirmed within deadline grace")


def owned_group_stopped(pgid: int, deadline: float) -> bool:
    """Observe termination before reaping the leader that reserves this PGID."""
    with os.scandir("/proc") as entries:
        for entry in entries:
            if time.monotonic() >= deadline:
                return False
            if not entry.name.isascii() or not entry.name.isdecimal():
                continue
            try:
                raw = Path(entry.path, "stat").read_bytes()
            except (FileNotFoundError, ProcessLookupError):
                continue
            tail = raw.rsplit(b")", 1)[-1].split()
            if len(tail) < 4:
                raise Refused("Owned group observation contains malformed procfs state")
            if tail[2] == str(pgid).encode() and tail[0] not in {b"Z", b"X"}:
                return False
    return time.monotonic() < deadline


def _alarm(_signum, _frame) -> None:
    raise ReaderAlarm("Original reader command deadline expired")


def main(arguments: list[str] | None = None) -> int:
    started_ns = time.monotonic_ns()
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=MODES)
    parser.add_argument("expected_current_boot")
    parser.add_argument("--wait-existing-terminal", action="store_true")
    args = parser.parse_args(arguments)
    if args.wait_existing_terminal and args.mode != "post-records":
        parser.error("The original-window waiter is available only for post-records")
    if (
        os.geteuid() != 0
        or sys.platform != "linux"
        or platform.machine() != "x86_64"
        or not uuid_string(args.expected_current_boot)
    ):
        raise Refused("Only the fixed root Linux x86_64 reader is supported")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise Refused("Only the fixed Ubuntu24.04 reader is supported")
    try:
        pins = PinSet(base64.b64decode(PIN_SET_B64, validate=True))
    except (ValueError, binascii.Error) as error:
        raise Refused("The reviewed private packet must embed its pin data") from error
    reader = Reader(pins)
    reader.command_deadline_ns = started_ns + (
        120_000_000_000 if args.wait_existing_terminal else 25_000_000_000
    )
    signal.signal(signal.SIGALRM, _alarm)
    signal.signal(signal.SIGTERM, _alarm)
    remaining = (reader.command_deadline_ns - time.monotonic_ns()) / 1e9
    if remaining <= 0:
        raise ReaderAlarm("Original reader command deadline expired during prelude")
    signal.setitimer(signal.ITIMER_REAL, remaining)
    output, metadata = sys.stdout.buffer, sys.stderr.buffer
    if args.mode == "snapshot":
        output.write(canonical(reader.snapshot(args.expected_current_boot)))
    elif args.mode == "archive":
        reader.archive(args.expected_current_boot, output, metadata)
    elif args.mode == "post-records":
        for frame in reader.post_records(
            args.expected_current_boot, wait_existing_terminal=args.wait_existing_terminal
        ):
            output.write(canonical(frame))
            output.flush()
            if frame["kind"] == "ec2_reader_post_end_v1" and not frame["complete"]:
                return 74
    elif args.mode == "capture-env":
        frame = reader.capture_env(args.expected_current_boot)
        output.write(canonical(frame))
        if frame["record"]["status"] not in PRESENT | {"ABSENT"}:
            return 74
    elif args.mode == "inventory":
        output.write(canonical(reader.inventory(args.expected_current_boot)))
    else:
        frame = reader.journal(args.mode, args.expected_current_boot, output)
        metadata.write(canonical(frame))
        metadata.flush()
        if not frame["complete"]:
            return 74
    output.flush()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            "EC2_READ_ONLY_RETRIEVAL_REFUSED " + type(error).__name__ + ": " + str(error),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(74) from error
