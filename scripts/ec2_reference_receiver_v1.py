#!/usr/bin/env python3
"""Receive existing EC2 evidence; never launch or repeat a qualification.

Deploy this client on an independent, already authorized remote SSH execution
surface. It is not a desktop fallback, key installer or EC2 launcher. The
historical entry point cannot invoke ACK. Private reviewed packets replace the
single PIN_SET_B64 data literal before execution, just as for the sibling reader.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

PIN_SET_B64 = "__TICKWITNESS_PIN_SET_B64__"
ROOT = Path("/var/lib/tickwitness-reference-ec2")
RUN = "ec201aab11254e8bb7cd1573a96a0004"
OPERATION = Path("/var/lib/tickwitness-lifecycle/reference-batches") / RUN
STAGE = Path("/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3")
UNIT = "tickwitness-test-session.service"
ARCHIVE_BASE = Path("/var/lib")
MAX_STREAM = 16 * 1024 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
MAX_TAR = MAX_PAYLOAD + 16 * 1024 * 1024
JSON_LIMIT = 65536
READ_NS = 25_000_000_000
STOP_NS = 2_000_000_000
ACK_MARGIN_NS = 15_000_000_000
HOST_FINGERPRINT = "SHA256:zB2adSrLIJ6RbqgQRlthIgrqPsx/AdeljZWUmOBL2qk"
FIXED_CASES = (
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
BASE = {"kind", "schema_version", "source_revision", "run_id", "boot_id"}
READY_KEYS = BASE | {
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
REPORT_KEYS = {
    "kind",
    "schema_version",
    "controls_status",
    "production_m1",
    "independent_human_security_review",
    "external_human_reproduction",
    "research_reservations",
    "replay_engine_invocations",
    "source_revision",
    "run_id",
    "acceptance_gate",
    "original_qualification_budget",
    "cases",
    "scope",
    "stop_scope",
    "recovery_context",
    "boot_id",
    "durable_budget_status",
    "durable_budget",
    "admissions_charged",
    "confirmed_backend_admissions",
    "backend_unconfirmed_admissions",
    "pending_probe_outcomes",
    "recovery_accounting",
    "admission_accounting_scope",
    "provider_context",
    "manifest_sha256",
    "completed_at_monotonic_ns",
    "observed_payload_starts",
}
MANIFEST_KEYS = {
    "kind",
    "schema_version",
    "provider_context",
    "qualification_started_ns",
    "qualification_deadline_ns",
    "recovery_context",
    "recovery_accounting",
    "recovery_accounting_phase",
    "production_m1_enabled",
    "available_for_probe",
    "unavailable_reasons",
    "os_release",
    "kernel",
    "architecture",
    "python_version",
    "libc_version",
    "runner_image_os",
    "runner_image_version",
    "source_revision",
    "controller_uid",
    "controller_gid",
    "reserved_uid_gid",
    "binaries",
    "host_mountinfo",
    "host_namespaces",
    "controllers",
    "apparmor",
    "explicit_userns_authorization",
    "bwrap_actual_version",
    "bwrap_package_version",
    "parent_subtree_control",
    "controller_limits",
    "syscall_mapping",
    "bpf_sha256",
    "bpf_hex",
    "guest_environment",
    "mount_plan",
    "bwrap_argv_template",
    "limits",
    "fixed_cases",
    "runtime_closure_scope",
}
STATE_KEYS = BASE | {
    "owner",
    "started_ns",
    "deadline_ns",
    "setup_deadline_ns",
    "phase",
    "host_preparation_started",
    "provider_context",
    "policy_receipts",
    "charged",
    "backend_confirmed",
    "admissions",
    "poisoned",
    "outcome",
    "reason",
    "final_report_sha256",
    "recovery_context",
}
TICKET_KEYS = {
    "run_id",
    "boot_id",
    "source_revision",
    "admission_number",
    "name",
    "nonce",
    "admitted_ns",
    "deadline_ns",
}
CASE_KEYS = {
    "name",
    "nonce",
    "admission_submitted",
    "admission",
    "status",
    "reason",
    "execution_evidence",
    "payload_started",
}
CONTEXT_KEYS = {
    "kind",
    "schema_version",
    "plan_id",
    "plan",
    "consumption",
    "history",
    "allowance",
    "invocation",
}
RECEIPT_KEYS = BASE | {
    "final_report_sha256",
    "controls_status",
    "production_m1",
    "recovery_context",
    "recovery_accounting",
}
SUMMARY_KEYS = {
    "admissions_charged",
    "boot_id",
    "controls_status",
    "manifest_sha256",
    "production_m1",
    "recovery_accounting",
    "recovery_context",
    "run_id",
    "terminal_receipt",
}
RESULT_KEYS = BASE | {
    "preparation_invoked",
    "preparation_returncode",
    "qualifier_invoked",
    "qualifier_returncode",
    "export_invoked",
    "export_returncode",
    "handoff_status",
    "returncode",
}
RAW_KEYS = {
    "actual_exit_code",
    "artifact_dir",
    "cleanup_confirmed",
    "failure",
    "host_facts",
    "name",
    "nonce",
    "payload_started",
    "started",
    "stderr",
    "stderr_truncated",
    "stdout",
    "stdout_truncated",
    "stop_confirmed",
    "stop_reason",
}
PLAN_KEYS = {
    "kind",
    "schema_version",
    "plan_id",
    "freeze_revision",
    "source_revision",
    "run_id",
    "expected_identity",
    "history",
    "allowance",
    "stop_observation",
    "source_lock",
    "provisioner_source",
}
CONSUMPTION_KEYS = BASE | {
    "plan_id",
    "freeze_revision",
    "plan_sha256",
    "history_state_sha256",
    "owner",
    "started_ns",
    "deadline_ns",
    "setup_deadline_ns",
    "max_admissions",
    "max_cumulative_admissions",
    "prior_charged",
}
PROVIDER_KEYS = BASE | {
    "provider",
    "host",
    "expected_identity",
    "observed_identity",
    "source_lock",
    "provider_source",
    "identity_document",
    "gha_metadata",
    "gha_metadata_reason",
    "recovery_context",
}


def _load_reader():
    path = Path(__file__).with_name("ec2_reference_reader_v1.py")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or before.st_uid not in {0, os.getuid()}
            or before.st_size > 1048576
        ):
            raise RuntimeError("Unsafe reviewed sibling reader")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(1048577)
        after = os.fstat(fd)
        fields = (
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
            len(raw) != before.st_size
            or any(getattr(before, k) != getattr(after, k) for k in fields)
            or any(getattr(after, k) != getattr(path.lstat(), k) for k in fields)
        ):
            raise RuntimeError("Reviewed sibling reader changed")
    finally:
        os.close(fd)
    spec = importlib.util.spec_from_file_location("tickwitness_transport_reader_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Reviewed sibling reader is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module, raw


reader, READER_SOURCE = _load_reader()
Row = dict[str, Any]


class Refused(RuntimeError):
    """An observation cannot authorize a transfer acknowledgment."""


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def exact(value: object, keys: set[str], label: str) -> Row:
    if type(value) is not dict or set(value) != keys:
        raise Refused(label + " exact fields")
    return value


def equal(value: object, expected: object, label: str) -> None:
    if canonical(value) != canonical(expected):
        raise Refused(label + " differs")


def number(value: object, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise Refused("Expected bounded integer")
    return value


def decimal(value: object) -> int:
    if type(value) is not str or re.fullmatch(r"0|[1-9][0-9]{0,24}", value) is None:
        raise Refused("Expected exact unsigned decimal string")
    return int(value)


def document(raw: bytes, *, canonical_required: bool = True, limit: int = MAX_PAYLOAD) -> Row:
    value = reader.strict_json(raw, limit=limit)
    if canonical_required and canonical(value) != raw:
        raise Refused("Original authority encoding differs")
    return value


def base(value: Row, pins, kind: str, version: int = 3) -> None:
    for name, expected in {
        "kind": kind,
        "schema_version": version,
        "source_revision": pins.data["source_revision"],
        "run_id": pins.data["run_id"],
        "boot_id": pins.data["original_boot_id"],
    }.items():
        equal(value.get(name), expected, name)


def raw_file(record: Row) -> bytes:
    reader.validate_file_record(record)
    if record["status"] not in {"PRESENT", "PRESENT_EMPTY"}:
        raise Refused("Required original file is not present")
    try:
        raw = base64.b64decode(record["raw_b64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise Refused("Invalid original raw bytes") from exc
    if len(raw) != record["bytes"] or sha(raw) != record["sha256"]:
        raise Refused("Original raw byte binding differs")
    return raw


def ready_document(record: Row, pins) -> Row:
    raw = raw_file(record)
    if sha(raw) != pins.data["original_ready_sha256"]:
        raise Refused("Original ready SHA differs")
    ready = exact(document(raw, limit=JSON_LIMIT), READY_KEYS, "Ready")
    base(ready, pins, "restricted_reference_ec2_handoff_ready_v3")
    for key in (
        "main_pid",
        "main_start_ticks",
        "controller_pid",
        "controller_start_ticks",
        "bytes",
        "started_ns",
        "deadline_ns",
        "outer_deadline_ns",
    ):
        number(ready[key], 1)
    if (
        ready["unit"] != UNIT
        or ready["invocation_id"] != pins.data["original_invocation_id"]
        or re.fullmatch(r"[0-9a-f]{32}", str(ready["nonce"])) is None
        or ready["controller_pid"] == ready["main_pid"]
        or ready["deadline_ns"]
        != min(ready["started_ns"] + 120_000_000_000, ready["outer_deadline_ns"])
        or ready["sha256"] != pins.data["original_archive_sha256"]
        or ready["bytes"] != pins.data["original_archive_bytes"]
        or ready["bytes"] > MAX_STREAM
    ):
        raise Refused("Original ready authority differs")
    expected_main = [
        "/usr/bin/sudo",
        "/bin/bash",
        str(STAGE / "run_ec2_reference_recovery_v3.sh"),
        pins.data["source_revision"],
        RUN,
    ]
    expected_controller = [
        "/usr/bin/python3",
        "-I",
        str(STAGE / "ec2_reference_handoff_v3.py"),
        "run",
        "--source-revision",
        pins.data["source_revision"],
        "--run-id",
        RUN,
    ]
    allowed_main = [
        expected_main,
        ["/usr/bin/timeout", "--signal=TERM", "--kill-after=2s", "1500s", *expected_controller],
    ]
    if ready["main_argv"] not in allowed_main or ready["controller_argv"] != expected_controller:
        raise Refused("Original complete command identity differs")
    if type(ready["guard_exec_start"]) is not str or not ready["guard_exec_start"]:
        raise Refused("Missing original guard command")
    if ready["guard_control_group"] != "/system.slice/" + UNIT:
        raise Refused("Original guard cgroup differs")
    exact(ready["archive_stat"], set(reader.STAT_KEYS), "Ready archive stat")
    for value in ready["archive_stat"].values():
        number(value)
    return ready


def validate_snapshot(snapshot: Row, pins, boot: str, *, live: bool) -> Row:
    # decode_frame establishes the shared wire's exact fields and integer types.
    snapshot = reader.decode_frame(canonical(snapshot))
    for name in ("observation_id", "source_revision", "run_id", "original_boot_id"):
        equal(snapshot[name], pins.data[name], "Snapshot " + name)
    equal(snapshot["server_boot_id"], boot, "Observed current boot")
    ready = ready_document(snapshot["ready"], pins)
    archive = snapshot["archive"]
    reader.validate_file_record(archive, allow_metadata=True)
    for name in ("bytes", "sha256"):
        equal(archive[name], ready[name], "Snapshot archive " + name)
    equal(
        archive["stat"],
        {k: str(v) for k, v in ready["archive_stat"].items()},
        "Snapshot archive seal",
    )
    if live:
        if snapshot["live"] is not True or boot != pins.data["original_boot_id"]:
            raise Refused("Historical or replacement boot cannot acknowledge")
        guard, master = snapshot["guard"], snapshot["master"]
        if guard is None or master is None:
            raise Refused("Original live processes unavailable")
        expected = {
            "active_state": "active",
            "sub_state": "running",
            "invocation_id": ready["invocation_id"],
            "main_pid": ready["main_pid"],
            "main_start_ticks": ready["main_start_ticks"],
            "main_argv": ready["main_argv"],
            "exec_start": ready["guard_exec_start"],
            "control_group": ready["guard_control_group"],
            "user": "ubuntu",
        }
        equal(guard, expected, "Current original guard")
        for key, value in {
            "pid": ready["controller_pid"],
            "start_ticks": ready["controller_start_ticks"],
            "argv": ready["controller_argv"],
            "cgroup": ready["guard_control_group"],
            "effective_uid": 0,
        }.items():
            equal(master[key], value, "Current original master " + key)
        number(master["ppid"], 1)
        if decimal(snapshot["server_now_ns"]) >= ready["deadline_ns"]:
            raise Refused("Original ready window expired")
    return ready


class Clock:
    def now(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class LocalStore:
    """Exclusive private output; a partial ACK intent is permanently USED."""

    def __init__(self, directory: Path, *, owner: int | None = None) -> None:
        self.directory = directory.absolute()
        self.owner = os.getuid() if owner is None else owner
        self._ancestry(self.directory.parent)
        self.directory.mkdir(mode=0o700)
        self._fsync(self.directory.parent)

    def _ancestry(self, path: Path) -> None:
        for item in (path, *path.parents):
            info = item.lstat()
            # System ancestors may be owned by root, but never writable by other users.
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, self.owner}:
                raise Refused("Unsafe local output ancestry")
            if info.st_mode & 0o022 and not (info.st_mode & stat.S_ISVTX and info.st_uid == 0):
                raise Refused("Writable local output ancestry")

    def _fsync(self, path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def write(self, name: str, raw: bytes) -> None:
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}", name) is None:
            raise Refused("Fixed local evidence name")
        self._ancestry(self.directory)
        fd = os.open(
            self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync(self.directory)

    def record(self, name: str, value: object) -> None:
        self.write(name, canonical(value))


class IntentStore(LocalStore):
    """One fixed per-user fence survives new audit destinations and crashes."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (
            Path.home() / ".local/state/tickwitness/ec2-transport-v1/ack-intents"
            if directory is None
            else directory.absolute()
        )
        self.owner = os.getuid()
        missing = []
        current = self.directory
        while not current.exists() and not current.is_symlink():
            missing.append(current)
            current = current.parent
        self._ancestry(current)
        for path in reversed(missing):
            with suppress(FileExistsError):
                path.mkdir(mode=0o700)
            self._ancestry(path)
            self._fsync(path.parent)
        self._ancestry(self.directory)
        if self.directory.stat().st_uid != self.owner or self.directory.stat().st_mode & 0o077:
            raise Refused("ACK intent directory must be private to the executing user")

    def claim(self, ready: Row, pins, value: Row) -> str:
        identity = {
            key: ready[key]
            for key in (
                "source_revision",
                "run_id",
                "boot_id",
                "invocation_id",
                "main_pid",
                "main_start_ticks",
                "controller_pid",
                "controller_start_ticks",
                "nonce",
                "bytes",
                "sha256",
            )
        }
        identity["ready_sha256"] = pins.data["original_ready_sha256"]
        name = sha(canonical(identity)) + ".json"
        self.record(name, value)
        return name


class ArchiveVerifier:
    """Inspect original gzip/tar bytes without extraction, execution or old APIs."""

    def __init__(self, pins) -> None:
        self.pins = pins
        self.files: dict[str, bytes] = {}

    def parse(self, raw: bytes) -> None:
        if not 0 < len(raw) <= MAX_STREAM:
            raise Refused("Compressed archive bound")
        if len(raw) != self.pins.data["original_archive_bytes"]:
            raise Refused("Original archive length differs")
        if sha(raw) != self.pins.data["original_archive_sha256"]:
            raise Refused("Original archive SHA differs")
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            expanded = stream.read(MAX_TAR + 1)
        if len(expanded) > MAX_TAR:
            raise Refused("Bounded archive decompression exceeded")
        total = 0
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
            for item in archive:
                path = PurePosixPath(item.name)
                if (
                    not item.isreg()
                    or item.issparse()
                    or path.is_absolute()
                    or str(path) != item.name
                    or ".." in path.parts
                    or "\\" in item.name
                    or re.fullmatch(r"[a-zA-Z0-9/._-]+", item.name) is None
                    or item.name in self.files
                    or len(self.files) >= 10001
                ):
                    raise Refused("Unsafe, duplicate or excessive archive member")
                if item.size < 0 or item.size > (
                    4 * 1024 * 1024 if item.name == "export-inventory.json" else 2 * 1024 * 1024
                ):
                    raise Refused("Archive regular-member bound")
                total += item.size
                if total > MAX_PAYLOAD + 4 * 1024 * 1024:
                    raise Refused("Archive source-payload bound")
                extracted = archive.extractfile(item)
                if extracted is None:
                    raise Refused("Missing regular member bytes")
                content = extracted.read(item.size + 1)
                if len(content) != item.size:
                    raise Refused("Truncated regular member")
                self.files[item.name] = content
        inventory = document(self.files.get("export-inventory.json", b""), limit=4 * 1024 * 1024)
        exact(inventory, {"absent", "inventory_only", "archived"}, "Export inventory")
        if type(inventory["absent"]) is not list or type(inventory["inventory_only"]) is not list:
            raise Refused("Inventory observational lists")
        rows = inventory["archived"]
        if type(rows) is not list or len(rows) > 10000:
            raise Refused("Inventory source count")
        covered: set[str] = set()
        pins = {item["path"]: item for item in self.pins.data["files"]}
        for value in rows:
            row = exact(value, {"path", "stat", "sha256"}, "Inventory row")
            name = self.member(row["path"])
            if name in covered or name not in self.files:
                raise Refused("Inventory coverage differs")
            covered.add(name)
            raw = self.files[name]
            seal = exact(row["stat"], set(reader.STAT_KEYS), "Inventory stat")
            for value in seal.values():
                number(value)
            if seal["size"] != len(raw) or row["sha256"] != sha(raw):
                raise Refused("Inventory bytes/hash differ")
            if row["path"] not in pins:
                raise Refused("Inventory file lacks original remote pin")
            pinned = pins[row["path"]]
            equal({k: str(v) for k, v in seal.items()}, pinned["stat"], "Inventory original seal")
            equal(sha(raw), pinned["sha256"], "Inventory original SHA")
            equal(len(raw), pinned["bytes"], "Inventory original length")
        if covered != set(self.files) - {"export-inventory.json"}:
            raise Refused("Inventory does not cover every source member")

    def member(self, path: str | Path) -> str:
        path = Path(path)
        if not path.is_absolute() or not path.is_relative_to(ARCHIVE_BASE):
            raise Refused("Original fixed archive path")
        return str(path.relative_to(ARCHIVE_BASE))

    def read(self, path: str | Path) -> bytes:
        try:
            return self.files[self.member(path)]
        except KeyError as exc:
            raise Refused("Missing required original archive member") from exc

    def json(self, path: str | Path, *, canonical_required: bool = True) -> Row:
        return document(self.read(path), canonical_required=canonical_required)

    def binding(self, value: object) -> Row:
        row = exact(value, {"path", "bytes", "sha256"}, "Original file binding")
        raw = self.read(row["path"])
        equal(row["bytes"], len(raw), "Original bound length")
        equal(row["sha256"], sha(raw), "Original bound SHA")
        return row

    def verify(self, raw: bytes) -> Row:
        self.parse(raw)
        run = ROOT / "runs" / RUN
        report_raw = self.read(run / "qualification-report.json")
        report = exact(document(report_raw), REPORT_KEYS, "Qualification report")
        state_raw = self.read(run / "state.json")
        state = exact(document(state_raw), STATE_KEYS, "Durable state")
        manifest = exact(self.json(run / "qualification/manifest.json"), MANIFEST_KEYS, "Manifest")
        base(report, self.pins, "restricted_reference_ec2_recovery_qualification_v3")
        base(state, self.pins, "restricted_reference_ec2_recovery_run_v3")
        equal(state["final_report_sha256"], sha(report_raw), "Durable final report SHA")
        for field, value in {
            "phase": "TERMINAL",
            "outcome": "QUALIFIED_REFERENCE_ONLY",
            "poisoned": False,
            "charged": 24,
            "backend_confirmed": 24,
        }.items():
            equal(state[field], value, "Durable " + field)
        for field, value in {
            "controls_status": "QUALIFIED_REFERENCE_ONLY",
            "production_m1": "DISABLED",
            "independent_human_security_review": "NOT_PERFORMED",
            "external_human_reproduction": "0/0/PENDING",
            "research_reservations": 0,
            "replay_engine_invocations": 0,
            "admissions_charged": 24,
            "confirmed_backend_admissions": 24,
            "backend_unconfirmed_admissions": 0,
            "pending_probe_outcomes": 0,
            "observed_payload_starts": 24,
            "durable_budget_status": "CONFIRMED",
            "acceptance_gate": "matching_durable_terminal_and_final_report_sha256",
        }.items():
            equal(report[field], value, "Report " + field)
        started = number(state["started_ns"])
        deadline = number(state["deadline_ns"], 1)
        equal(deadline, started + 600_000_000_000, "Original admission clock")
        equal(state["setup_deadline_ns"], started + 30_000_000_000, "Original setup clock")
        durable = {
            "started_ns": started,
            "deadline_ns": deadline,
            "max_admissions": 24,
            "charged": 24,
            "backend_confirmed": 24,
            "unconfirmed": 0,
            "poisoned": False,
            "pending_outcomes": 0,
        }
        equal(report["durable_budget"], durable, "Original durable budget")
        equal(
            report["original_qualification_budget"],
            {"max_admissions": 24, "window_ns": 600_000_000_000},
            "Original qualification allowance",
        )
        budget = {
            "kind": "restricted_reference_ec2_recovery_budget_v3",
            "schema_version": 3,
            "plan_id": "ec2-recovery-20261127-v3",
            "historical_run_ids": [RUN[:-1] + str(i) for i in (1, 2, 3)],
            "prior_charged": 21,
            "prior_backend_confirmed": 21,
            "current_charged": 24,
            "current_backend_confirmed": 24,
            "current_unconfirmed": 0,
            "current_pending_outcomes": 0,
            "cumulative_charged": 45,
            "cumulative_backend_confirmed": 45,
            "max_current_admissions": 24,
            "max_cumulative_admissions": 45,
        }
        equal(report["recovery_accounting"], budget, "Final 24/45 accounting")
        context = exact(report["recovery_context"], CONTEXT_KEYS, "Recovery context")
        equal(context, state["recovery_context"], "Durable immutable context")
        equal(context["kind"], "restricted_reference_ec2_recovery_context_v3", "Context kind")
        equal(context["schema_version"], 3, "Context schema")
        equal(context["plan_id"], budget["plan_id"], "Context plan")
        equal(
            context["invocation"],
            {
                "run_id": RUN,
                "source_revision": self.pins.data["source_revision"],
                "boot_id": self.pins.data["original_boot_id"],
                "started_ns": started,
                "deadline_ns": deadline,
                "setup_deadline_ns": state["setup_deadline_ns"],
            },
            "Context clocks",
        )
        equal(
            context["allowance"],
            {
                "additional_invocations": 1,
                "max_admissions": 24,
                "max_cumulative_admissions": 45,
                "setup_ns": 30_000_000_000,
                "window_ns": 600_000_000_000,
            },
            "Context allowance",
        )
        plan = exact(self.json(self.binding(context["plan"])["path"]), PLAN_KEYS, "Original plan")
        consumption = exact(
            self.json(self.binding(context["consumption"])["path"]),
            CONSUMPTION_KEYS,
            "Original consumption",
        )
        for field, value in {
            "kind": "restricted_reference_ec2_recovery_plan_v3",
            "schema_version": 3,
            "plan_id": context["plan_id"],
            "run_id": RUN,
            "source_revision": self.pins.data["source_revision"],
            "freeze_revision": "72c83a02d47a403d5f9d33aad2f84ccaba7ec6a4",
            "allowance": context["allowance"],
        }.items():
            equal(plan[field], value, "Original plan " + field)
        base(consumption, self.pins, "restricted_reference_ec2_recovery_consumption_v3")
        for field, value in {
            "plan_id": context["plan_id"],
            "freeze_revision": plan["freeze_revision"],
            "plan_sha256": context["plan"]["sha256"],
            "owner": state["owner"],
            "started_ns": started,
            "deadline_ns": deadline,
            "setup_deadline_ns": state["setup_deadline_ns"],
            "max_admissions": 24,
            "max_cumulative_admissions": 45,
            "prior_charged": 21,
            "history_state_sha256": {
                key: value["state_sha256"] for key, value in context["history"].items()
            },
        }.items():
            equal(consumption[field], value, "Original consumption " + field)
        equal(plan.get("history"), context["history"], "Frozen history graph")
        equal(plan.get("source_revision"), self.pins.data["source_revision"], "Plan source")
        equal(consumption.get("run_id"), RUN, "Consumption run")
        equal(
            consumption.get("source_revision"),
            self.pins.data["source_revision"],
            "Consumption source",
        )
        equal(consumption.get("boot_id"), self.pins.data["original_boot_id"], "Consumption boot")
        self.history(context["history"])
        provider = exact(state["provider_context"], PROVIDER_KEYS, "Original provider")
        base(provider, self.pins, "restricted_reference_ec2_recovery_host_v3")
        equal(provider["recovery_context"], context, "Provider context")
        equal(provider["source_lock"], plan["source_lock"], "Provider/plan source lock")
        equal(provider["expected_identity"], plan["expected_identity"], "Expected EC2 identity")
        equal(provider["observed_identity"], plan["expected_identity"], "Actual EC2 identity")
        self.source_closure(provider, plan)
        equal(manifest["kind"], "restricted_reference_ec2_recovery_manifest_v3", "Manifest kind")
        equal(manifest["schema_version"], 3, "Manifest version")
        for key, value in {
            "source_revision": self.pins.data["source_revision"],
            "recovery_context": context,
            "provider_context": state["provider_context"],
            "production_m1_enabled": False,
            "available_for_probe": True,
            "fixed_cases": list(FIXED_CASES),
            "qualification_started_ns": started,
            "qualification_deadline_ns": deadline,
            "recovery_accounting_phase": "pre_probe_manifest",
        }.items():
            equal(manifest[key], value, "Manifest " + key)
        initial = budget | {
            "current_charged": 0,
            "current_backend_confirmed": 0,
            "cumulative_charged": 21,
            "cumulative_backend_confirmed": 21,
        }
        equal(manifest["recovery_accounting"], initial, "Pre-probe 0/21 accounting")
        equal(report["provider_context"], state["provider_context"], "Original provider")
        manifest_sha = sha(self.read(run / "qualification/manifest.json"))
        equal(report["manifest_sha256"], manifest_sha, "Report manifest bytes")
        admissions, cases = state["admissions"], report["cases"]
        if (
            type(admissions) is not list
            or len(admissions) != 24
            or type(cases) is not list
            or len(cases) != 24
        ):
            raise Refused("Complete 24 admissions and cases required")
        nonces: set[str] = set()
        for index, (admission, case, name) in enumerate(
            zip(admissions, cases, FIXED_CASES, strict=True), 1
        ):
            exact(admission, TICKET_KEYS | {"accepted", "outcome"}, "Durable admission")
            exact(case, CASE_KEYS, "Report case")
            ticket = {k: admission[k] for k in TICKET_KEYS}
            equal(ticket, case["admission"], "Case/durable ticket")
            for key, value in {
                "run_id": RUN,
                "boot_id": self.pins.data["original_boot_id"],
                "source_revision": self.pins.data["source_revision"],
                "admission_number": index,
                "name": name,
            }.items():
                equal(ticket[key], value, "Ticket " + key)
            admitted = number(ticket["admitted_ns"])
            if not started <= admitted < deadline or ticket["deadline_ns"] != min(
                admitted + 10_000_000_000, deadline
            ):
                raise Refused("Original ticket admission/deadline differs")
            nonce = ticket["nonce"]
            if (
                type(nonce) is not str
                or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
                or nonce in nonces
            ):
                raise Refused("Unique actual nonce required")
            nonces.add(nonce)
            for key, value in {
                "name": name,
                "nonce": nonce,
                "status": "PASS",
                "admission_submitted": True,
                "payload_started": True,
                "reason": "actual_scoped_control_evidence",
            }.items():
                equal(case[key], value, "Current case " + key)
            equal(admission["accepted"], True, "Accepted durable admission")
            case_path = run / f"case-{index:02d}.json"
            equal(
                case["execution_evidence"],
                {
                    "path": str(case_path),
                    "bytes": len(self.read(case_path)),
                    "sha256": sha(self.read(case_path)),
                },
                "Original raw case binding",
            )
            raw_case = exact(self.json(case_path), RAW_KEYS, "Original raw case")
            backend = run / "qualification" / f"{name}-{nonce}.json"
            equal(
                self.read(backend).hex(),
                self.read(case_path).hex(),
                "Backend/driver exact raw bytes",
            )
            outcome = exact(
                admission["outcome"],
                {"stop_confirmed", "cleanup_confirmed", "failure", "result_sha256"},
                "Durable outcome",
            )
            equal(outcome["result_sha256"], sha(self.read(case_path)), "Durable outcome raw SHA")
            for key, value in {
                "name": name,
                "nonce": nonce,
                "payload_started": True,
                "started": True,
                "stop_confirmed": True,
                "cleanup_confirmed": True,
                "failure": outcome["failure"],
            }.items():
                equal(raw_case.get(key), value, "Raw case " + key)
            equal(outcome["stop_confirmed"], True, "Outcome stop")
            equal(outcome["cleanup_confirmed"], True, "Outcome cleanup")
            facts = raw_case.get("host_facts")
            if type(facts) is not dict:
                raise Refused("Missing original raw host facts")
            for key, value in {
                "manifest_sha256": manifest_sha,
                "admission_number": index,
                "original_admission_ns": admitted,
                "original_deadline_ns": ticket["deadline_ns"],
            }.items():
                equal(facts.get(key), value, "Raw host binding " + key)
            equal(facts.get("confirmed_task_absent"), True, "Original task absence")
            canaries = facts.get("canaries_before")
            if type(canaries) is not dict or not canaries:
                raise Refused("Missing original canary observations")
            equal(facts.get("canaries_after"), canaries, "Unchanged original canaries")
            stop = number(facts.get("stop_intent_ns"), admitted)
            equal(facts.get("stop_confirmation_deadline_ns"), stop + STOP_NS, "Original stop clock")
            if number(facts.get("stop_elapsed_ns")) > STOP_NS:
                raise Refused("Original stop exceeded its confirmation bound")
            if number(facts.get("deadline_elapsed_ns")) < stop - admitted:
                raise Refused("Original elapsed/stop clock contradiction")
            bootstrap = facts.get("bootstrap_admission")
            if type(bootstrap) is not dict or type(bootstrap.get("receipt")) is not dict:
                raise Refused("Missing original bootstrap observation")
            equal(
                bootstrap["receipt"].get("policy_setup_sha256"),
                state["policy_receipts"]["report_sha256"],
                "Original bootstrap policy setup",
            )
            for stream in ("stdout", "stderr"):
                content = raw_case.get(stream)
                if type(content) is not str:
                    raise Refused("Missing original output stream")
                retained = content.encode()
                if self.read(run / "qualification" / f"{name}-{nonce}.{stream}") != retained:
                    raise Refused("Actual retained stream and raw result differ")
                equal(facts.get(stream + "_sha256"), sha(retained), "Retained stream SHA")
                equal(
                    facts.get(stream + "_retained_bytes"), len(retained), "Retained stream length"
                )
        summary = exact(
            self.json(OPERATION / "qualification.stdout", canonical_required=False),
            SUMMARY_KEYS,
            "Original qualifier stdout summary",
        )
        receipt = exact(summary["terminal_receipt"], RECEIPT_KEYS, "Original live receipt")
        base(receipt, self.pins, "restricted_reference_ec2_recovery_terminal_receipt_v3")
        for key, value in {
            "final_report_sha256": sha(report_raw),
            "controls_status": "QUALIFIED_REFERENCE_ONLY",
            "production_m1": "DISABLED",
            "recovery_context": context,
            "recovery_accounting": budget,
        }.items():
            equal(receipt[key], value, "Original live receipt " + key)
        for key in SUMMARY_KEYS - {"terminal_receipt"}:
            equal(summary[key], report[key], "Original stdout/report " + key)
        exit_record = exact(
            self.json(OPERATION / "qualifier-exit.json"),
            BASE | {"invoked", "returncode", "report"},
            "Original qualifier exit",
        )
        base(exit_record, self.pins, "restricted_reference_ec2_qualifier_exit_v3")
        equal(exit_record["invoked"], True, "Original qualifier invoked")
        equal(exit_record["returncode"], 0, "Original qualifier returncode")
        self.binding(exit_record["report"])
        return {
            "kind": "ec2_received_qualification_v1",
            "schema_version": 1,
            "source_revision": self.pins.data["source_revision"],
            "run_id": RUN,
            "boot_id": self.pins.data["original_boot_id"],
            "report_sha256": sha(report_raw),
            "terminal_state_sha256": sha(state_raw),
            "manifest_sha256": manifest_sha,
            "terminal_receipt": receipt,
            "current_charged": 24,
            "prior_charged": 21,
            "cumulative_charged": 45,
            "raw_cases": 24,
            "retained_streams": 48,
            "qualification_scope": "QUALIFIED_REFERENCE_ONLY",
            "production_m1": "DISABLED",
        }

    def source_closure(self, provider: Row, plan: Row) -> None:
        lock = exact(
            self.json(self.binding(plan["source_lock"])["path"]),
            {"kind", "schema_version", "source_revision", "source_root", "files"},
            "Source lock",
        )
        equal(lock["kind"], "restricted_reference_ec2_recovery_source_lock_v3", "Source lock kind")
        equal(lock["schema_version"], 3, "Source lock schema")
        equal(lock["source_revision"], self.pins.data["source_revision"], "Source lock revision")
        source_root = Path(lock["source_root"])
        files = lock["files"]
        expected = {
            str(Path(row["path"]).relative_to(source_root)): {
                k: row[k] for k in ("bytes", "sha256")
            }
            for row in self.pins.data["source_files"]
        }
        if len(expected) != 10:
            raise Refused("Original ten-file source closure required")
        equal(files, expected, "Ten protected source hashes")
        for field in ("provider_source",):
            row = exact(provider[field], {"path", "sha256", "bytes"}, "Source receipt")
            equal(
                row,
                next(
                    (
                        item
                        for item in self.pins.data["source_files"]
                        if item["path"] == row["path"]
                    ),
                    None,
                ),
                "Protected provider receipt",
            )
        preparer = exact(
            plan["provisioner_source"], {"path", "sha256", "bytes"}, "Preparer receipt"
        )
        equal(
            preparer,
            next(
                (
                    item
                    for item in self.pins.data["source_files"]
                    if item["path"] == preparer["path"]
                ),
                None,
            ),
            "Protected preparer receipt",
        )
        identity = self.json(
            self.binding(provider["identity_document"])["path"], canonical_required=False
        )
        for key, value in provider["observed_identity"].items():
            equal(identity.get(key), value, "Original IID " + key)
        pins = {row["path"]: row for row in self.pins.data["files"]}
        for retained, original in (
            ("batch-source.sh", "run_ec2_reference_recovery_v3.sh"),
            ("preparer-source.sh", "provision_ec2_reference_source.sh"),
            ("handoff-source.py", "ec2_reference_handoff_v3.py"),
        ):
            row = pins.get(str(STAGE / original))
            if row is None or sha(self.read(OPERATION / retained)) != row["sha256"]:
                raise Refused("Retained operational source binding differs")

    def history(self, history: object) -> None:
        rows = exact(history, {"original", "recovery", "recovery_v2"}, "Three historical runs")
        total = 0
        for label, expected_count in (("original", 1), ("recovery", 1), ("recovery_v2", 19)):
            common = {
                "archive_sha256",
                "backend_confirmed",
                "boot_id",
                "case_sha256",
                "charged",
                "claim_sha256",
                "report_sha256",
                "run_id",
                "source_lock_sha256",
                "source_revision",
                "state_sha256",
            }
            extra = (
                {"host_claim_sha256"}
                if label == "original"
                else {
                    "consumption_sha256",
                    "identity_document_sha256",
                    "manifest_sha256",
                    "plan_sha256",
                    "policy_preload_sha256",
                    "policy_setup_sha256",
                    "sealed_index_sha256",
                }
            )
            row = exact(rows[label], common | extra, "Historical authority")
            equal(row["charged"], expected_count, "Historical charge")
            equal(row["backend_confirmed"], expected_count, "Historical confirmation")
            total += expected_count
            directory = ROOT / "runs" / row["run_id"]
            mapping = {
                "claim_sha256": directory / "claim.json",
                "state_sha256": directory / "state.json",
                "report_sha256": directory / "qualification-report.json",
                "source_lock_sha256": ROOT
                / "sources"
                / row["source_revision"]
                / "source-lock.json",
            }
            if label == "original":
                mapping["host_claim_sha256"] = ROOT / "host-admission.json"
            if label != "original":
                recovery_root = ROOT if label == "recovery" else ROOT / "recovery-v2"
                mapping.update(
                    {
                        "plan_sha256": recovery_root
                        / ("recovery-plan.json" if label == "recovery" else "plan.json"),
                        "consumption_sha256": recovery_root
                        / (
                            "recovery-consumption.json"
                            if label == "recovery"
                            else "consumption.json"
                        ),
                        "manifest_sha256": directory / "qualification/manifest.json",
                        "identity_document_sha256": directory / "instance-identity-document.json",
                        "policy_preload_sha256": directory
                        / "policy-evidence/preload-manifest.json",
                        "policy_setup_sha256": directory / "policy-evidence/policy-setup.json",
                    }
                )
            for field, path in mapping.items():
                equal(sha(self.read(path)), row[field], "Retained historical " + field)
            cases = row["case_sha256"]
            cases = {"case-01.json": cases} if type(cases) is str else cases
            if type(cases) is not dict or len(cases) != expected_count:
                raise Refused("Retained historical raw-case count")
            for name, digest in cases.items():
                equal(sha(self.read(directory / name)), digest, "Retained historical case")
        equal(total, 21, "Prior charged distinct from schema3")


@dataclass(frozen=True)
class Completed:
    stdout: bytes
    stderr: bytes
    returncode: int | None


class RemoteJob:
    """Continuously drain a bounded original stream while other channels run."""

    def __init__(
        self,
        argv: list[str],
        *,
        deadline_ns: int,
        input_bytes: bytes | None = None,
        clock: Clock | None = None,
    ) -> None:
        if not hasattr(os, "waitid") or not hasattr(os, "WNOWAIT"):
            raise Refused(
                "Bounded transport requires an independent Linux waitid execution surface"
            )
        self.clock = Clock() if clock is None else clock
        self.deadline_ns = deadline_ns
        self.stdout, self.stderr = bytearray(), bytearray()
        self.error: BaseException | None = None
        self.returncode: int | None = None
        self.changed = threading.Condition()
        self.stop_lock = threading.Lock()
        self.stopped = False
        with tempfile.TemporaryFile() as source:
            if input_bytes is not None:
                source.write(input_bytes)
                source.flush()
                source.seek(0)
            self.process = subprocess.Popen(
                argv,
                stdin=source if input_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _stop(self) -> None:
        with self.stop_lock:
            if self.stopped:
                return
            self.stopped = True
            stop_deadline = min(self.clock.now() + STOP_NS, self.deadline_ns + STOP_NS)
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            # A reaped leader does not prove its process group has disappeared.
            # Keep the leader unreaped until both group signals have been sent;
            # its reserved PID prevents a reused unrelated PGID being targeted.
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
            remaining = max(0, stop_deadline - self.clock.now()) / 1e9
            stopped = reader.owned_group_stopped(self.process.pid, time.monotonic() + remaining)
            with suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=max(0, (stop_deadline - self.clock.now()) / 1e9))
            if not stopped:
                raise Refused("Owned transport group stop was not confirmed inside original grace")

    def _drain(self) -> None:
        try:
            assert self.process.stdout is not None and self.process.stderr is not None
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ, self.stdout)
                selector.register(self.process.stderr, selectors.EVENT_READ, self.stderr)
                while selector.get_map():
                    remaining = self.deadline_ns - self.clock.now()
                    if remaining <= 0:
                        raise TimeoutError("Original bounded SSH stream deadline")
                    for key, _ in selector.select(min(0.1, remaining / 1e9)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        with self.changed:
                            key.data.extend(chunk)
                            if len(self.stdout) >= MAX_STREAM or len(self.stderr) >= MAX_STREAM:
                                raise Refused("Original SSH stream reached its bound")
                            self.changed.notify_all()
                while self.clock.now() < self.deadline_ns:
                    exited = os.waitid(
                        os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                    )
                    if exited is not None:
                        break
                    time.sleep(min(0.01, max(0, self.deadline_ns - self.clock.now()) / 1e9))
                else:
                    raise TimeoutError("SSH leader exit unavailable before original deadline")
                self._stop()
                self.returncode = self.process.returncode
                if self.returncode is None:
                    raise TimeoutError("SSH exit unavailable before original deadline")
        except BaseException as exc:
            self.error = exc
            self._stop()
        finally:
            for stream in (self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()
            with self.changed:
                self.changed.notify_all()

    def first_line(self, deadline_ns: int) -> bytes:
        with self.changed:
            while b"\n" not in self.stdout:
                if self.error is not None:
                    raise self.error
                if self.returncode is not None:
                    raise Refused("Positive post-reader header was not observed")
                remaining = min(deadline_ns, self.deadline_ns) - self.clock.now()
                if remaining <= 0 or len(self.stdout) > reader.FRAME_LIMIT:
                    raise Refused("Post-reader header bound")
                self.changed.wait(min(0.1, remaining / 1e9))
            return bytes(self.stdout).split(b"\n", 1)[0] + b"\n"

    def finish(self, deadline_ns: int) -> Completed:
        self.deadline_ns = min(self.deadline_ns, deadline_ns)
        remaining = max(0, min(deadline_ns, self.deadline_ns) - self.clock.now()) / 1e9
        self.thread.join(
            remaining
            + max(0, (self.deadline_ns + STOP_NS - max(self.deadline_ns, self.clock.now())) / 1e9)
        )
        if self.thread.is_alive():
            self._stop()
            raise TimeoutError("SSH stream did not stop within its bound")
        if self.error is not None:
            raise self.error
        assert self.returncode is not None
        return Completed(bytes(self.stdout), bytes(self.stderr), self.returncode)

    def observed(self) -> Completed:
        with self.changed:
            return Completed(bytes(self.stdout), bytes(self.stderr), self.process.returncode)


class SSH:
    """Only the fixed stdin reader and one exact original ACK are callable."""

    def __init__(self, alias: str, pins, *, clock: Clock | None = None) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", alias) is None:
            raise Refused("Use an existing SSH config alias, without options or credentials")
        self.alias, self.clock = alias, Clock() if clock is None else clock
        self.host_options: list[str] = []
        self.prepared_ns: int | None = None
        self.controls: list[Path] = []
        self.masters: list[RemoteJob] = []
        marker = b'PIN_SET_B64 = "__TICKWITNESS_PIN_SET_B64__"'
        if READER_SOURCE.count(marker) != 1:
            raise Refused("Reviewed reader must have one data marker")
        self.source = READER_SOURCE.replace(
            marker, b'PIN_SET_B64 = "' + base64.b64encode(canonical(pins.data)) + b'"'
        )

    def prepare(self, store: LocalStore) -> None:
        """Authenticate fixed ephemeral channels before the publisher's ready phase.

        This method launches no remote command and never launches the publisher.
        The later snapshot proves this preparation precedes original ready.start.
        """
        cap = self.clock.now() + READ_NS
        self.verify_configuration(store, cap)
        for index in range(3):
            socket = store.directory / f"ssh-control-{index}"
            if len(str(socket).encode()) > 100:
                raise Refused("Private SSH control socket path is too long")
            argv = [
                "/usr/bin/ssh",
                *self.host_options,
                "-T",
                "-M",
                "-N",
                "-S",
                str(socket),
                "-o",
                "ControlPersist=no",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectionAttempts=1",
                "-o",
                "ConnectTimeout=5",
                "--",
                self.alias,
            ]
            master = RemoteJob(argv, deadline_ns=cap + 120_000_000_000, clock=self.clock)
            self.masters.append(master)
            self.controls.append(socket)
            check = None
            while self.clock.now() < cap:
                check = RemoteJob(
                    ["/usr/bin/ssh", "-S", str(socket), "-O", "check", "--", self.alias],
                    deadline_ns=cap,
                    clock=self.clock,
                ).finish(cap)
                if check.returncode == 0:
                    break
                if master.returncode is not None:
                    raise Refused("SSH preauthentication failed")
                self.clock.sleep(0.02)
            if check is None or check.returncode != 0:
                raise Refused("SSH preauthentication exceeded its fixed bound")
            store.write(f"ssh-prepared-{index}.stderr", check.stderr)
        self.prepared_ns = self.clock.now()
        store.record(
            "ssh-prepared.json",
            {
                "kind": "ec2_receiver_prepared_v1",
                "schema_version": 1,
                "prepared_local_ns": self.prepared_ns,
            },
        )

    def verify_configuration(self, store: LocalStore, cap: int) -> None:
        observed = RemoteJob(
            ["/usr/bin/ssh", "-G", "--", self.alias], deadline_ns=cap, clock=self.clock
        ).finish(cap)
        store.write("ssh-effective.stdout", observed.stdout)
        store.write("ssh-effective.stderr", observed.stderr)
        if observed.returncode != 0 or len(observed.stdout) > JSON_LIMIT:
            raise Refused("Existing SSH configuration could not be verified")
        values: dict[str, list[str]] = {}
        for line in observed.stdout.decode().splitlines():
            key, separator, value = line.partition(" ")
            if not separator:
                raise Refused("Malformed effective SSH configuration")
            values.setdefault(key, []).append(value)
        if values.get("user") != ["ubuntu"] or values.get("port") != ["22"]:
            raise Refused("Original SSH user/port differs")
        host = values.get("hostkeyalias", values.get("hostname", []))
        if host == ["none"]:
            host = values.get("hostname", [])
        if len(host) != 1 or re.fullmatch(r"[A-Za-z0-9_.:-]+", host[0]) is None:
            raise Refused("Existing SSH host identity is unavailable")
        paths = values.get("userknownhostsfile", [])
        matching = None
        for entry in paths:
            for value in shlex.split(entry):
                path = Path(value).expanduser()
                if not path.is_absolute() or "%" in str(path):
                    raise Refused("Unsupported existing known-hosts path")
                result = RemoteJob(
                    ["/usr/bin/ssh-keygen", "-F", host[0], "-f", str(path)],
                    deadline_ns=cap,
                    clock=self.clock,
                ).finish(cap)
                for line in result.stdout.splitlines():
                    fields = line.split()
                    if len(fields) != 3 or fields[1] != b"ssh-ed25519":
                        continue
                    try:
                        key = base64.b64decode(fields[2], validate=True)
                    except ValueError:
                        continue
                    fingerprint = "SHA256:" + base64.b64encode(
                        hashlib.sha256(key).digest()
                    ).decode().rstrip("=")
                    if fingerprint == HOST_FINGERPRINT:
                        matching = fields[2]
        if matching is None:
            raise Refused("Frozen original ED25519 host fingerprint was not verified")
        store.write(
            "ssh-original-known-host",
            b"tickwitness-reference-original ssh-ed25519 " + matching + b"\n",
        )
        self.host_options = [
            "-o",
            "UserKnownHostsFile=" + str(store.directory / "ssh-original-known-host"),
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "HostKeyAlias=tickwitness-reference-original",
            "-o",
            "HostKeyAlgorithms=ssh-ed25519",
            "-o",
            "UpdateHostKeys=no",
            "-o",
            "VerifyHostKeyDNS=no",
        ]

    def close(self) -> None:
        for master in self.masters:
            master._stop()

    def _start(
        self, command: list[str], deadline_ns: int, *, source: bytes | None = None, channel: int = 0
    ) -> RemoteJob:
        if self.prepared_ns is None or len(self.controls) != 3:
            raise Refused("Preauthenticated independent SSH channels are required")
        argv = [
            "/usr/bin/ssh",
            *self.host_options,
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ControlMaster=no",
            "-S",
            str(self.controls[channel]),
            "-o",
            "ProxyCommand=/usr/bin/false",
            "-o",
            "ConnectionAttempts=1",
            "--",
            self.alias,
            shlex.join(command),
        ]
        return RemoteJob(argv, deadline_ns=deadline_ns, input_bytes=source, clock=self.clock)

    def start(self, mode: str, boot: str, deadline_ns: int, *, wait: bool = False):
        if (
            mode not in reader.MODES
            or not reader.uuid_string(boot)
            or (wait and mode != "post-records")
        ):
            raise Refused("Fixed reader command only")
        command = ["/usr/bin/sudo", "-n", "/usr/bin/python3", "-I", "-", mode, boot]
        if wait:
            command.append("--wait-existing-terminal")
        return self._start(command, deadline_ns, source=self.source, channel=1 if wait else 0)

    def ack(self, ready: Row, source: str, deadline_ns: int):
        command = [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/python3",
            "-I",
            str(STAGE / "ec2_reference_handoff_v3.py"),
            "ack",
            "--source-revision",
            source,
            "--run-id",
            RUN,
        ]
        for key in (
            "boot_id",
            "invocation_id",
            "main_pid",
            "controller_pid",
            "nonce",
            "bytes",
            "sha256",
        ):
            command.extend(["--" + key.replace("_", "-"), str(ready[key])])
        return self._start(command, deadline_ns, channel=2)


class PostRecords:
    def __init__(self, pins, boot: str, ready: Row, header: bytes, *, live: bool) -> None:
        self.pins, self.boot, self.ready = pins, boot, ready
        self.header = reader.decode_frame(header)
        if self.header["kind"] != "ec2_reader_post_begin_v1":
            raise Refused("Missing positive post-reader begin")
        for key in ("observation_id", "source_revision", "run_id", "original_boot_id"):
            equal(self.header[key], pins.data[key], "Post header " + key)
        equal(self.header["server_boot_id"], boot, "Post observed boot")
        equal(self.header["ready_sha256"], pins.data["original_ready_sha256"], "Post ready SHA")
        equal(self.header["invocation_id"], ready["invocation_id"], "Post original invocation")
        equal(self.header["wait_existing_terminal"], live, "Post explicit mode")
        if live:
            equal(
                self.header["deadline_ns"],
                str(min(ready["deadline_ns"], ready["outer_deadline_ns"])),
                "Post original deadline",
            )
            if decimal(self.header["server_now_ns"]) >= decimal(self.header["deadline_ns"]):
                raise Refused("Late positive post header")
        self.rows: dict[str, Row] = {}

    def finish(self, result: Completed) -> Row:
        if result.returncode != 0:
            raise Refused("Post-reader producer was incomplete")
        lines = result.stdout.splitlines(keepends=True)
        if len(lines) < 3 or any(not line.endswith(b"\n") for line in lines):
            raise Refused("Truncated post-record framing")
        equal(reader.decode_frame(lines[0]), self.header, "Retained post header")
        digest, count = hashlib.sha256(), 0
        for raw in lines[1:-1]:
            row = reader.decode_frame(raw)
            if row["kind"] != "ec2_reader_post_record_v1" or row["server_boot_id"] != self.boot:
                raise Refused("Post data frame identity")
            count += 1
            equal(row["sequence"], count, "Continuous post-record sequence")
            digest.update(raw)
            self.rows[row["record"]["path"]] = row["record"]
        end = reader.decode_frame(lines[-1])
        if end["kind"] != "ec2_reader_post_end_v1" or end["server_boot_id"] != self.boot:
            raise Refused("Missing bound post footer")
        equal(end["records"], count, "Post original frame count")
        equal(end["sha256"], digest.hexdigest(), "Post original frame digest")
        equal(end["deadline_ns"], self.header["deadline_ns"], "Post unchanged deadline")
        if end["complete"] is not True:
            raise Refused("Post evidence incomplete; absence is only as of original deadline")
        expected = {str(OPERATION / name) for name in reader.POST_NAMES}
        if set(self.rows) != expected:
            raise Refused("Post fixed record set incomplete")
        if any(
            row["status"] not in {"PRESENT", "PRESENT_EMPTY", "ABSENT"}
            for row in self.rows.values()
        ):
            raise Refused("Post record error is not an absence or a complete readback")
        return end

    def original(self, name: str) -> Row:
        return document(raw_file(self.rows[str(OPERATION / name)]), limit=JSON_LIMIT)

    def acknowledgment(self) -> Row:
        ack = exact(
            self.original("handoff-ack.json"),
            BASE | {"invocation_id", "main_pid", "controller_pid", "nonce", "bytes", "sha256"},
            "Original ACK",
        )
        base(ack, self.pins, "restricted_reference_ec2_handoff_ack_v3")
        for key in ("invocation_id", "main_pid", "controller_pid", "nonce", "bytes", "sha256"):
            equal(ack[key], self.ready[key], "Original ACK " + key)
        result = exact(
            self.original("controller-result.json"), RESULT_KEYS, "Original controller result"
        )
        base(result, self.pins, "restricted_reference_ec2_controller_result_v3")
        for key, value in {
            "preparation_invoked": True,
            "preparation_returncode": 0,
            "qualifier_invoked": True,
            "qualifier_returncode": 0,
            "export_invoked": True,
            "export_returncode": 0,
            "handoff_status": "acknowledged",
            "returncode": 0,
        }.items():
            equal(result[key], value, "Actual controller " + key)
        raw_file(self.rows[str(OPERATION / "export.stdout")])
        raw_file(self.rows[str(OPERATION / "export.stderr")])
        return result


def manager_exit(raw: bytes, pins, expected_code: int) -> bool:
    """PID1's INVOCATION_ID (without underscore) binds positive original exit."""
    if len(raw) > MAX_STREAM:
        raise Refused("Original journal stream bound")
    found = False
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            raise Refused("Truncated original journal entry")
        row = reader.strict_json(line, limit=MAX_STREAM)
        if (
            row.get("_PID") == "1"
            and row.get("UNIT") == UNIT
            and row.get("_BOOT_ID") == pins.data["original_boot_id"].replace("-", "")
            and row.get("INVOCATION_ID") == pins.data["original_invocation_id"]
            and row.get("MESSAGE_ID") == "98e322203f7a4ed290d09fe03c09fe15"
            and row.get("CODE_FUNC") == "unit_log_process_exit"
        ):
            if row.get("EXIT_CODE") != "exited" or row.get("EXIT_STATUS") != str(expected_code):
                raise Refused("Original manager exit contradicts controller result")
            found = True
    return found


class Receiver:
    """Production receive order; injected ports never add a CLI authority."""

    def __init__(
        self,
        pins,
        ssh,
        store: LocalStore,
        clock: Clock | None = None,
        *,
        intents: IntentStore | None = None,
    ) -> None:
        self.pins, self.ssh, self.store = pins, ssh, store
        self.clock = Clock() if clock is None else clock
        self.deadline: int | None = None
        self.ack_submitted = False
        self.intents = IntentStore() if intents is None else intents

    def save_job(self, name: str, job, deadline: int) -> Completed:
        try:
            result = job.finish(deadline)
        except BaseException as exc:
            partial = job.observed()
            self.store.write(name + ".stdout", partial.stdout)
            self.store.write(name + ".stderr", partial.stderr)
            self.store.record(
                name + ".exit.json",
                {"returncode": partial.returncode, "complete": False, "error": type(exc).__name__},
            )
            raise
        self.store.write(name + ".stdout", result.stdout)
        self.store.write(name + ".stderr", result.stderr)
        self.store.record(name + ".exit.json", {"returncode": result.returncode, "complete": True})
        return result

    def remaining(self, margin: int = 0) -> int:
        if self.deadline is None or self.clock.now() + margin >= self.deadline:
            raise Refused("Conservative original window has insufficient remaining time")
        return self.deadline

    def _request(self, mode: str, boot: str) -> Completed:
        cap = self.clock.now() + READ_NS
        if self.deadline is not None:
            cap = min(cap, self.remaining())
        result = self.save_job(mode, self.ssh.start(mode, boot, cap), cap)
        if result.returncode != 0:
            raise Refused("Read-only producer did not complete")
        return result

    def snapshot(self, boot: str, *, live: bool, name: str) -> Row:
        started = self.clock.now()
        cap = (
            started + READ_NS if self.deadline is None else min(started + READ_NS, self.remaining())
        )
        result = self.save_job(name, self.ssh.start("snapshot", boot, cap), cap)
        if result.returncode != 0:
            raise Refused("Authenticated snapshot unavailable")
        snapshot = reader.decode_frame(result.stdout)
        ready = validate_snapshot(snapshot, self.pins, boot, live=live)
        if live:
            remote_remaining = min(ready["deadline_ns"], ready["outer_deadline_ns"]) - decimal(
                snapshot["server_now_ns"]
            )
            bound = started + remote_remaining
            self.deadline = bound if self.deadline is None else min(self.deadline, bound)
            self.remaining()
            prepared = getattr(self.ssh, "prepared_ns", None)
            # Request-start gives an earlier, conservative mapped ready.start.
            earliest_ready = started + ready["started_ns"] - decimal(snapshot["server_now_ns"])
            if type(prepared) is not int or prepared > earliest_ready:
                raise Refused("SSH and validators were not proved prepared before original ready")
        return ready

    def inventory(self, boot: str, name: str) -> Row:
        cap = (
            self.clock.now() + READ_NS
            if self.deadline is None
            else min(self.clock.now() + READ_NS, self.remaining())
        )
        result = self.save_job(name, self.ssh.start("inventory", boot, cap), cap)
        if result.returncode != 0:
            raise Refused("Protected source inventory incomplete")
        row = reader.decode_frame(result.stdout)
        if row["kind"] != "ec2_reader_inventory_v1" or row["server_boot_id"] != boot:
            raise Refused("Protected source inventory identity")
        equal(row["files_verified"], len(self.pins.data["files"]), "All original file pins")
        equal(
            row["source_files_verified"],
            len(self.pins.data["source_files"]),
            "All ten source hashes",
        )
        equal(row["source_original_inode"], "NOT_RECORDED", "Original source inode provenance")
        if set(row["source_current_stats"]) != {
            item["path"] for item in self.pins.data["source_files"]
        }:
            raise Refused("Protected source inode observation set")
        return row

    def archive(self, boot: str, ready: Row) -> Row:
        result = self._request("archive", boot)
        lines = result.stderr.splitlines(keepends=True)
        if len(lines) != 2:
            raise Refused("Archive before/after metadata incomplete")
        before, after = (reader.decode_frame(raw) for raw in lines)
        for phase, frame in (("before", before), ("after", after)):
            equal(frame["phase"], phase, "Archive metadata phase")
            equal(frame["server_boot_id"], boot, "Archive observed boot")
            for key in ("bytes", "sha256"):
                equal(frame[key], ready[key], "Archive metadata " + key)
            equal(
                frame["stat"],
                {key: str(value) for key, value in ready["archive_stat"].items()},
                "Archive metadata original seal",
            )
        equal(before | {"phase": "after"}, after, "Stable archive metadata")
        verified = ArchiveVerifier(self.pins).verify(result.stdout)
        self.store.record("qualification-verified.json", verified)
        return verified

    def historical_retrieve(self, boot: str) -> Row:
        # Deliberately contains no ACK call or local intent creation.
        ready = self.snapshot(boot, live=False, name="historical-snapshot")
        before = self.inventory(boot, "inventory-before")
        verified = self.archive(boot, ready)
        result = self._request("post-records", boot)
        header = result.stdout.split(b"\n", 1)[0] + b"\n"
        post = PostRecords(self.pins, boot, ready, header, live=False)
        footer = post.finish(result)
        reconciliation = "UNKNOWN_ORIGINAL_POST_RECORDS"
        manager = False
        controller_record = post.rows[str(OPERATION / "controller-result.json")]
        if controller_record["status"] in {"PRESENT", "PRESENT_EMPTY"}:
            try:
                existing = exact(
                    post.original("controller-result.json"),
                    RESULT_KEYS,
                    "Historical controller result",
                )
                base(existing, self.pins, "restricted_reference_ec2_controller_result_v3")
                equal(existing["qualifier_invoked"], True, "Historical qualifier invoked")
                equal(existing["qualifier_returncode"], 0, "Historical qualifier code")
                if existing["handoff_status"] == "acknowledged":
                    post.acknowledgment()
                elif (
                    existing["handoff_status"] == "expired"
                    and existing["returncode"] == 74
                    and post.rows[str(OPERATION / "handoff-ack.json")]["status"] == "ABSENT"
                ):
                    reconciliation = "ORIGINAL_EXPIRED_WITH_ABSENT_ACK"
                else:
                    reconciliation = "ORIGINAL_FAILURE_OR_UNKNOWN"
                for mode in ("journal-boot", "journal-unit", "journal-invocation"):
                    stream = self._request(mode, boot)
                    metadata = reader.decode_frame(stream.stderr)
                    equal(metadata["mode"], mode, "Original journal query mode")
                    equal(metadata["server_boot_id"], boot, "Journal retrieval boot")
                    equal(metadata["complete"], True, "Original journal completion")
                    equal(metadata["producer_exit_code"], 0, "Journal producer exit")
                    equal(metadata["bytes"], len(stream.stdout), "Journal actual length")
                    equal(metadata["sha256"], sha(stream.stdout), "Journal actual SHA")
                    if mode != "journal-invocation":
                        manager = (
                            manager_exit(stream.stdout, self.pins, existing["returncode"])
                            or manager
                        )
            except (Refused, reader.Refused, OSError, ValueError):
                reconciliation = "UNKNOWN_ORIGINAL_POST_RECORDS_OR_JOURNALS"
        after = self.inventory(boot, "inventory-after")
        equal(before, after, "Protected readback source and historical pins")
        return {
            "kind": "ec2_historical_receive_v1",
            "schema_version": 1,
            "qualification": verified,
            "post_footer": footer,
            "ack_submitted": False,
            "post_reconciliation": reconciliation,
            "manager_exit": "OBSERVED" if manager else "NOT_OBSERVED",
            "transport_status": "READBACK_ONLY_PENDING_INDEPENDENT_STOP",
            "cloud_stop": "NOT_OBSERVED",
        }

    def live_receive(self, boot: str) -> Row:
        ready = self.snapshot(boot, live=True, name="initial-snapshot")
        before = self.inventory(boot, "inventory-before")
        verified = self.archive(boot, ready)
        after = self.inventory(boot, "inventory-after")
        equal(before, after, "Protected original source and history remain stable")
        self.remaining(ACK_MARGIN_NS)
        post_start = self.clock.now()
        post_job = self.ssh.start("post-records", boot, self.remaining(), wait=True)
        post = PostRecords(self.pins, boot, ready, post_job.first_line(self.remaining()), live=True)
        # This independent authenticated channel has proved its original identity.
        remote_remaining = decimal(post.header["deadline_ns"]) - decimal(
            post.header["server_now_ns"]
        )
        self.deadline = min(self.remaining(), post_start + remote_remaining)
        final_ready = self.snapshot(boot, live=True, name="final-snapshot")
        equal(final_ready, ready, "Unchanged original ready authority")
        self.remaining(ACK_MARGIN_NS)
        intent = {
            "kind": "ec2_receiver_ack_intent_v1",
            "schema_version": 1,
            "source_revision": self.pins.data["source_revision"],
            "run_id": RUN,
            "boot_id": boot,
            "ready_sha256": self.pins.data["original_ready_sha256"],
            "archive_sha256": ready["sha256"],
            "invocation_id": ready["invocation_id"],
            "main_pid": ready["main_pid"],
            "controller_pid": ready["controller_pid"],
            "nonce": ready["nonce"],
            "started_local_ns": self.clock.now(),
            "deadline_local_ns": self.remaining(),
        }
        name = self.intents.claim(ready, self.pins, intent)
        self.store.record("ack-intent.json", intent | {"permanent_intent": name})
        # fsync and its parent are part of the original clock, not free time.
        self.remaining(ACK_MARGIN_NS)
        self.ack_submitted = True
        ack_error = None
        try:
            job = self.ssh.ack(ready, self.pins.data["source_revision"], self.remaining())
            reply = self.save_job("ack", job, self.remaining())
            if reply.returncode != 0:
                ack_error = "UNKNOWN_AFTER_SINGLE_ACK_SUBMISSION"
        except (OSError, TimeoutError, Refused) as exc:
            ack_error = "UNKNOWN_AFTER_SINGLE_ACK_SUBMISSION:" + type(exc).__name__
        # The already open reader is the only post-ACK action, never another ACK.
        post_status = "UNKNOWN"
        try:
            result = self.save_job("post-records", post_job, self.deadline)
            post.finish(result)
            post.acknowledgment()
            post_status = "ACKNOWLEDGED_RECORDS_OBSERVED"
        except (OSError, TimeoutError, Refused, reader.Refused) as exc:
            post_status = "UNKNOWN:" + type(exc).__name__
        return {
            "kind": "ec2_live_receive_v1",
            "schema_version": 1,
            "qualification": verified,
            "ack_submitted": True,
            "ack_reply": "COMMAND_ZERO" if ack_error is None else ack_error,
            "post_status": post_status,
            "transport_status": "UNKNOWN_PENDING_MANAGER_EXIT_AND_CLOUD_STOP",
            "cloud_stop": "NOT_OBSERVED",
            "manager_exit": "NOT_OBSERVED",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("live-receive", "historical-retrieve"))
    parser.add_argument(
        "ssh_alias", help="Existing authorized alias on an independent remote execution surface"
    )
    parser.add_argument("expected_current_boot")
    parser.add_argument("destination", type=Path, help="New exclusive private audit directory")
    arguments = parser.parse_args(argv)
    try:
        if not reader.uuid_string(arguments.expected_current_boot):
            raise Refused("Expected current boot must be exact UUID")
        pins = reader.PinSet(base64.b64decode(PIN_SET_B64, validate=True))
        store = LocalStore(arguments.destination)
        clock = Clock()
        ssh = SSH(arguments.ssh_alias, pins, clock=clock)
        receiver = Receiver(pins, ssh, store, clock)
        try:
            ssh.prepare(store)
            result = (
                receiver.live_receive(arguments.expected_current_boot)
                if arguments.mode == "live-receive"
                else receiver.historical_retrieve(arguments.expected_current_boot)
            )
        finally:
            ssh.close()
        store.record("receive-result.json", result)
        print(canonical(result).decode(), end="")
        return 0 if arguments.mode == "historical-retrieve" else 74
    except (OSError, ValueError, Refused, reader.Refused) as exc:
        print("receive_refused_or_uncertain:" + type(exc).__name__, file=sys.stderr)
        return 74


if __name__ == "__main__":
    raise SystemExit(main())
