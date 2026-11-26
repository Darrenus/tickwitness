"""Fixed, owner-trusted EC2 qualification identity and one durable admission budget.

This is not a general remote provider or an execution backend. Trusted provisioning
must create the source lock before invocation. No import performs host operations.
"""

from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import http.client
import json
import os
import platform
import re
import secrets
import signal
import stat
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

type Row = dict[str, object]
ROOT = Path("/var/lib/tickwitness-reference-ec2")
SOURCE_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_IDENTITY = {
    "instanceId": "i-0d79530ca78320939",
    "region": "ap-southeast-1",
    "imageId": "ami-09289bc217ad5e9e7",
    "instanceType": "m7i.2xlarge",
    "architecture": "x86_64",
}
SOURCE_FILES = (
    "src/tickwitness/infrastructure/restricted_reference_ec2.py",
    "scripts/qualify_restricted_reference_ec2.py",
    "scripts/prepare_reference_policy_ec2.py",
    "scripts/prepare_reference_policy.py",
    "scripts/qualify_restricted_reference.py",
    "src/tickwitness/infrastructure/restricted_reference.py",
    "src/tickwitness/infrastructure/restricted_reference_bootstrap.py",
    "scripts/restricted_reference_payload.py",
    "research/security/reference-ec2.apparmor",
)
RECOVERY_SOURCE_FILES = (*SOURCE_FILES, "scripts/prepare_ec2_reference_recovery.py")
RECOVERY_PLAN_ID = "ec2-recovery-20261126-v1"
RECOVERY_RUN_ID = "ec201aab11254e8bb7cd1573a96a0002"
RECOVERY_FREEZE_REVISION = "a19cff330df5a04e405c83baebcfb0bddf3498fa"
RECOVERY_STOP_SHA256 = "a64c30e2fff9fad194184ee278636e19da6ebfecbcae1f19ffe715b2db266193"
RECOVERY_PREDECESSOR = {
    "source_revision": "ae3d8e7981a79d6fc692f2cb656534a2f9a6683b",
    "run_id": "ec201aab11254e8bb7cd1573a96a0001",
    "boot_id": "122c5232-f007-4fe1-b555-6797ee475eba",
    "host_claim_sha256": "7406dfdd9e66a47a2e19761d9501891258f839d4dbefc5b2089b8876780fafca",
    "claim_sha256": "7406dfdd9e66a47a2e19761d9501891258f839d4dbefc5b2089b8876780fafca",
    "state_sha256": "2b4b455b60f97d5052ae4bcb81c01f41566708a9c9486a94de71dee03eb13a5d",
    "report_sha256": "dcb7b4a585b9b02601f21697d2bb2c06bc5f480bc5a04e205e38d79c3abb1152",
    "case_sha256": "dd5fb4e40f9b88fb2926808fb7a3e82f6720a356ea196dc5cebbfa8eb0a1450b",
    "source_lock_sha256": "ed9f02ac04541945ceaab9021836984aa6e12c9fc9bad4be9308b5602e564d5c",
    "archive_sha256": "4203ef17dff24fe38cd2107e93a1b764e8bfacc96e87172251dfe5630f48aba5",
    "charged": 1,
    "backend_confirmed": 1,
}
RECOVERY_ALLOWANCE = {
    "additional_invocations": 1,
    "max_admissions": 24,
    "window_ns": 600_000_000_000,
    "setup_ns": 30_000_000_000,
    "max_cumulative_admissions": 25,
}
RECOVERY_V2_SOURCE_FILES = (*SOURCE_FILES, "scripts/prepare_ec2_reference_recovery_v2.py")
RECOVERY_V2_PLAN_ID = "ec2-recovery-20261127-v2"
RECOVERY_V2_RUN_ID = "ec201aab11254e8bb7cd1573a96a0003"
RECOVERY_V2_FREEZE_REVISION = "5ef1945c154cc944900a6d042f947bba0d620fd9"
RECOVERY_V2_STOP_SHA256 = "b6fbd33d2d0c8f9f0da20f31535a13d058785665ee9fc0d70baa4116517f7d6d"
RECOVERY_V2_HISTORY = {
    "original": dict(RECOVERY_PREDECESSOR),
    "recovery": {
        "source_revision": "d5f5fab9978d0cb2d1fed92f32552632705d52ee",
        "run_id": "ec201aab11254e8bb7cd1573a96a0002",
        "boot_id": "503b0e3e-0efe-4d7c-99b3-e282176c4c29",
        "claim_sha256": "e1f4a1e805ce62b3d5758ac4c372101b34c4e5945f5629864352c80aa5825b42",
        "state_sha256": "bb59f7c5027f3d61b5cefd0a8674ffb1e9fc7514cebc5bcc1aa6e14a62a3d1a5",
        "report_sha256": "ca3048f10484f0bd8c8f1aa7c30db5e672f922fff799ec6b83f7659569b8d5fc",
        "case_sha256": "572844853e49d00720682332d89a718ee5e424a63252c47998010a37a448cf4a",
        "source_lock_sha256": "a878a9eaf805559cce4358aa678f7e5b99dea8ea9d31bc9d5af8246155836bf2",
        "manifest_sha256": "261bd6890d6c064949fa7960916079f72e65316cbfe367472fab57a968a137be",
        "plan_sha256": "c10d872d2eb24fd7dc2ab6fc655222a6de44ecbe4742a26d1c113f4f9daf47f9",
        "consumption_sha256": "1df9fc47bb1b66ee0f67fa64edb3086a156b6faca749b3a4b3647abd59c4b5e1",
        "policy_setup_sha256": "2fe0bddd7b8d09998ecf7ae758ee7385603e0d063cf6d75e4ddf6a85bc0eb4f8",
        "policy_preload_sha256": "b0f57477e2a85abd090a8688a0ecd680e20a424ea46bc5d6d2462f473e6e7798",
        "identity_document_sha256": (
            "8a01b4cb7de9b5fe1c376abe3fd0479942219b3dd3eb485acbd82991adc1b831"
        ),
        "archive_sha256": "4ade0f15fd75a2ac6e457f798ec55e72880bbffad602d72ded3c9c3b427f692f",
        "sealed_index_sha256": "6516ceb56fbc302484cf391cc0c0434a3414c5e6ad6cb33ccbed06a9b1323571",
        "charged": 1,
        "backend_confirmed": 1,
    },
}
RECOVERY_V2_ALLOWANCE = {**RECOVERY_ALLOWANCE, "max_cumulative_admissions": 26}
RECOVERY_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
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
)
WINDOW_NS = 600_000_000_000
SETUP_NS = 30_000_000_000
PROBE_NS = 10_000_000_000
MAX_ADMISSIONS = 24
FIXED_PROBES = (
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
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_STATE_KEYS = {
    "kind",
    "schema_version",
    "source_revision",
    "run_id",
    "boot_id",
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
}
_PLAN_KEYS = {
    "kind",
    "schema_version",
    "plan_id",
    "freeze_revision",
    "source_revision",
    "run_id",
    "expected_identity",
    "predecessor",
    "allowance",
    "stop_observation",
    "source_lock",
    "provisioner_source",
}


def canonical(value: object) -> bytes:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return raw + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object, keys: set[str], label: str) -> Row:
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or any(not isinstance(key, str) for key in value)
    ):
        raise ValueError("Invalid or unknown " + label + " fields")
    return cast(Row, value)


def validate_recovery_manifest_shape(value: object, *, version: int = 1) -> Row:
    """Check the frozen complete top-level shape; nested raw observations stay raw."""
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("Unsupported exact recovery manifest version")
    manifest = _mapping(value, set(RECOVERY_MANIFEST_KEYS), "recovery manifest")
    _fixed(
        manifest["kind"], f"restricted_reference_ec2_recovery_manifest_v{version}", "manifest kind"
    )
    _fixed(manifest["schema_version"], version, "manifest schema")
    return manifest


def _fixed(value: object, expected: object, label: str) -> None:
    """Compare bounded JSON identities without bool/int equality or extra fields."""
    if type(value) is not type(expected):
        raise ValueError("Invalid exact " + label + " type")
    if isinstance(expected, dict):
        actual = cast(Row, value)
        if set(actual) != set(expected):
            raise ValueError("Invalid or unknown " + label + " fields")
        for key, item in expected.items():
            _fixed(actual[key], item, label + "." + key)
    elif isinstance(expected, list):
        actual_list = cast(list[object], value)
        if len(actual_list) != len(expected):
            raise ValueError("Invalid " + label + " length")
        for item, other in zip(actual_list, expected, strict=True):
            _fixed(item, other, label)
    elif value != expected:
        raise ValueError("Mismatched fixed " + label)


def _json(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> Row:
        result: Row = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    return cast(object, json.loads(raw, object_pairs_hook=pairs))


def _secure_directory(path: Path, *, create: bool = False) -> None:
    if not path.is_absolute():
        raise ValueError("Absolute trusted directory required")
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if not create:
                raise
            _secure_directory(part.parent, create=True)
            part.mkdir(mode=0o700)
            info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Untrusted directory ancestry: " + str(part))


def _secure_read(path: Path, limit: int) -> tuple[bytes, tuple[int, int, int, int, int]]:
    _secure_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not _regular_root(info) or info.st_size > limit:
            raise ValueError("Untrusted or oversized root file: " + str(path))
        raw = os.read(fd, limit + 1)
        after = os.fstat(fd)
        seal = (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_size)
        if len(raw) > limit or len(raw) != info.st_size or _stable(info) != _stable(after):
            raise ValueError("Trusted file changed during bounded read")
        return raw, seal
    finally:
        os.close(fd)


def _stable(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _regular_root(info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and info.st_nlink == 1
        and not info.st_mode & 0o022
    )


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_exclusive(path: Path, raw: bytes) -> None:
    """Create a bounded root-owned observation, never replace a prior observation."""
    if len(raw) > 262_144:
        raise ValueError("Root evidence exceeds bound")
    _secure_directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _file_record(path: Path, limit: int) -> tuple[Row, tuple[int, int, int, int, int]]:
    raw, seal = _secure_read(path, limit)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}, seal


def _source_records(
    source_revision: str,
    *,
    recovery: bool,
    seals: dict[str, tuple[Row, tuple[int, int, int, int, int]]],
    version: int = 1,
) -> tuple[Row, Row]:
    if type(version) is not int or version not in {1, 2} or (not recovery and version != 1):
        raise ValueError("Unsupported exact source closure version")
    path = ROOT / "sources" / source_revision / "source-lock.json"
    raw, seal = _secure_read(path, 65536)
    document = _mapping(
        _json(raw),
        {"kind", "schema_version", "source_revision", "source_root", "files"},
        "source-lock",
    )
    kind = (
        f"restricted_reference_ec2_recovery_source_lock_v{version}"
        if recovery
        else "restricted_reference_ec2_source_lock_v1"
    )
    if (
        document["kind"] != kind
        or type(document["schema_version"]) is not int
        or document["schema_version"] != version
        or document["source_revision"] != source_revision
        or document["source_root"] != str(SOURCE_ROOT)
    ):
        raise ValueError("Trusted actual source-lock identity differs")
    selected = (
        RECOVERY_V2_SOURCE_FILES
        if version == 2
        else RECOVERY_SOURCE_FILES if recovery else SOURCE_FILES
    )
    files = _mapping(document["files"], set(selected), "source closure")
    source_lock = {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}
    seals[str(path)] = (source_lock, seal)
    for relative in selected:
        expected = _mapping(files[relative], {"sha256", "bytes"}, "source entry")
        if (
            not isinstance(expected["sha256"], str)
            or not _HEX64.fullmatch(expected["sha256"])
            or type(expected["bytes"]) is not int
            or not 0 < expected["bytes"] <= 1_048_576
        ):
            raise ValueError("Invalid actual source digest or length")
        actual, source_seal = _file_record(SOURCE_ROOT / relative, 1_048_576)
        if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
            raise ValueError("Actual trusted source bytes differ")
        seals[str(SOURCE_ROOT / relative)] = (actual, source_seal)
    return source_lock, seals[str(SOURCE_ROOT / SOURCE_FILES[0])][0]


def _recovery_arguments(source_revision: str, run_id: str, plan_id: str) -> None:
    if type(source_revision) is not str or not _HEX40.fullmatch(source_revision):
        raise ValueError("Actual lowercase source commit required")
    if (
        type(run_id) is not str
        or run_id != RECOVERY_RUN_ID
        or type(plan_id) is not str
        or plan_id != RECOVERY_PLAN_ID
    ):
        raise ValueError("Only the one frozen recovery plan/run is supported")
    if source_revision == RECOVERY_PREDECESSOR["source_revision"]:
        raise ValueError("Recovery cannot reselect its failed predecessor source")


def _recovery_history(
    seals: dict[str, tuple[Row, tuple[int, int, int, int, int]]],
) -> Row:
    """Verify pinned predecessor bytes; no old record is written or reopened."""
    expected: object
    previous = RECOVERY_PREDECESSOR
    old_dir = ROOT / "runs" / str(previous["run_id"])

    def read(path: Path, key: str, limit: int) -> object:
        raw, seal = _secure_read(path, limit)
        if _sha(raw) != previous[key]:
            raise ValueError("Pinned recovery predecessor bytes differ: " + key)
        if canonical(_json(raw)) != raw:
            raise ValueError("Predecessor is not exact canonical JSON")
        seals[str(path)] = ({"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}, seal)
        return _json(raw)

    host_claim = read(ROOT / "host-admission.json", "host_claim_sha256", 65536)
    claim = read(old_dir / "claim.json", "claim_sha256", 65536)
    _fixed(claim, host_claim, "predecessor host/run claim")
    state = _mapping(
        read(old_dir / "state.json", "state_sha256", 262144), _STATE_KEYS, "predecessor state"
    )
    report_value = read(old_dir / "qualification-report.json", "report_sha256", 262144)
    result_value = read(old_dir / "case-01.json", "case_sha256", 2_097_152)
    lock_value = read(
        ROOT / "sources" / str(previous["source_revision"]) / "source-lock.json",
        "source_lock_sha256",
        65536,
    )
    if not all(
        isinstance(value, dict) for value in (claim, report_value, result_value, lock_value)
    ):
        raise ValueError("Predecessor observation must be a JSON object")
    report, result, old_lock = (
        cast(Row, report_value),
        cast(Row, result_value),
        cast(Row, lock_value),
    )
    old_claim = cast(Row, claim)
    for document in (old_claim, state, report):
        for field in ("source_revision", "run_id", "boot_id"):
            _fixed(document.get(field), previous[field], "predecessor " + field)
    for field, expected in (
        ("phase", "TERMINAL"),
        ("outcome", "NOT_QUALIFIED"),
        ("poisoned", True),
        ("charged", 1),
        ("backend_confirmed", 1),
        ("final_report_sha256", None),
    ):
        _fixed(state[field], expected, "predecessor " + field)
    for field in ("started_ns", "deadline_ns", "setup_deadline_ns"):
        if type(state[field]) is not int:
            raise ValueError("Invalid predecessor original clock type")
        _fixed(state[field], old_claim.get(field), "predecessor original clock")
    if (
        cast(int, state["deadline_ns"]) - cast(int, state["started_ns"]) != WINDOW_NS
        or cast(int, state["setup_deadline_ns"]) - cast(int, state["started_ns"]) != SETUP_NS
    ):
        raise ValueError("Predecessor original clock changed")
    admissions = state["admissions"]
    if not isinstance(admissions, list) or len(admissions) != 1:
        raise ValueError("Predecessor must retain its one charged admission")
    if not isinstance(admissions[0], dict):
        raise ValueError("Invalid predecessor admission")
    admission = cast(Row, admissions[0])
    outcome = admission.get("outcome")
    if not isinstance(outcome, dict):
        raise ValueError("Predecessor outcome remains pending/unknown")
    for field, expected in (
        ("accepted", True),
        ("name", "positive"),
        ("admission_number", 1),
        ("source_revision", previous["source_revision"]),
        ("run_id", previous["run_id"]),
        ("boot_id", previous["boot_id"]),
    ):
        _fixed(admission.get(field), expected, "predecessor admission " + field)
    _fixed(
        outcome,
        {
            "result_sha256": previous["case_sha256"],
            "stop_confirmed": True,
            "cleanup_confirmed": True,
            "failure": "setup_refused",
        },
        "predecessor outcome",
    )
    for field, expected in (
        ("controls_status", "NOT_QUALIFIED"),
        ("admissions_charged", 1),
        ("confirmed_backend_admissions", 1),
        ("backend_unconfirmed_admissions", 0),
        ("pending_probe_outcomes", 0),
        ("observed_payload_starts", 0),
        ("research_reservations", 0),
        ("replay_engine_invocations", 0),
    ):
        _fixed(report.get(field), expected, "predecessor report " + field)
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != MAX_ADMISSIONS:
        raise ValueError("Predecessor report lost its incomplete catalog")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError("Invalid predecessor case")
        _fixed(case.get("name"), FIXED_PROBES[index], "predecessor case name")
        _fixed(case.get("status"), "UNKNOWN", "predecessor case status")
        _fixed(case.get("admission_submitted"), index == 0, "predecessor submission")
    for field, expected in (
        ("name", "positive"),
        ("payload_started", False),
        ("failure", "setup_refused"),
        ("stop_confirmed", True),
        ("cleanup_confirmed", True),
    ):
        _fixed(result.get(field), expected, "predecessor case " + field)
    _fixed(
        old_lock.get("kind"), "restricted_reference_ec2_source_lock_v1", "predecessor source kind"
    )
    _fixed(old_lock.get("source_revision"), previous["source_revision"], "predecessor source")
    path = ROOT / "recovery-evidence" / "operator-stop.md"
    raw, seal = _secure_read(path, 65536)
    if _sha(raw) != RECOVERY_STOP_SHA256:
        raise ValueError("Pinned owner Stop observation bytes differ")
    stop_record = {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}
    seals[str(path)] = (stop_record, seal)
    return {
        "kind": "trusted_owner_aws_stop_observation_v1",
        "observed_state": "Stopped",
        "reason": "Client.InstanceInitiatedShutdown",
        "evidence": stop_record,
    }


def _recovery_v2_history(
    seals: dict[str, tuple[Row, tuple[int, int, int, int, int]]],
) -> Row:
    """Read both fixed failures and their old v1 lineage, without rewriting history."""
    _fixed(RECOVERY_V2_HISTORY["original"], RECOVERY_PREDECESSOR, "original history pins")
    _recovery_history(seals)
    previous = RECOVERY_V2_HISTORY["recovery"]
    old_dir = ROOT / "runs" / str(previous["run_id"])

    def read(
        path: Path,
        key: str,
        limit: int,
        *,
        canonical_required: bool = True,
        without_newline: bool = False,
    ) -> Row:
        raw, seal = _secure_read(path, limit)
        if _sha(raw) != previous[key]:
            raise ValueError("Pinned second recovery bytes differ: " + key)
        value = _json(raw)
        if not isinstance(value, dict):
            raise ValueError("Second recovery record is not canonical JSON")
        expected_raw = canonical(value)
        if without_newline:
            expected_raw = expected_raw[:-1]
        if canonical_required and expected_raw != raw:
            raise ValueError("Second recovery record is not producer-canonical JSON")
        seals[str(path)] = ({"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}, seal)
        return cast(Row, value)

    claim = read(old_dir / "claim.json", "claim_sha256", 65536)
    state = _mapping(
        read(old_dir / "state.json", "state_sha256", 262144),
        _STATE_KEYS | {"recovery_context"},
        "second recovery state",
    )
    report = read(old_dir / "qualification-report.json", "report_sha256", 262144)
    result = read(old_dir / "case-01.json", "case_sha256", 2_097_152)
    manifest = validate_recovery_manifest_shape(
        read(old_dir / "qualification" / "manifest.json", "manifest_sha256", 262144)
    )
    plan_path, consumption_path = ROOT / "recovery-plan.json", ROOT / "recovery-consumption.json"
    plan = _mapping(read(plan_path, "plan_sha256", 65536), _PLAN_KEYS, "old recovery plan")
    consumption = read(consumption_path, "consumption_sha256", 65536)
    lock_path = ROOT / "sources" / str(previous["source_revision"]) / "source-lock.json"
    old_lock = read(lock_path, "source_lock_sha256", 65536)
    preload = read(
        old_dir / "policy-evidence" / "preload-manifest.json",
        "policy_preload_sha256",
        262144,
        without_newline=True,
    )
    setup = read(old_dir / "policy-evidence" / "policy-setup.json", "policy_setup_sha256", 262144)
    identity = read(
        old_dir / "instance-identity-document.json",
        "identity_document_sha256",
        16384,
        canonical_required=False,
    )
    fields = (
        "source_revision",
        "run_id",
        "boot_id",
        "started_ns",
        "deadline_ns",
        "setup_deadline_ns",
    )
    _mapping(claim, {"kind", "schema_version", "owner", "recovery_context", *fields}, "old claim")
    invocation = {field: claim[field] for field in fields}
    for field in fields:
        if field.endswith("_ns") and type(invocation[field]) is not int:
            raise ValueError("Second recovery original clock is not an integer")
        _fixed(state[field], invocation[field], "second recovery original " + field)
    for field in ("source_revision", "run_id", "boot_id"):
        _fixed(invocation[field], previous[field], "second recovery " + field)
        _fixed(report.get(field), previous[field], "second report " + field)
    if (
        cast(int, invocation["deadline_ns"]) - cast(int, invocation["started_ns"]) != WINDOW_NS
        or cast(int, invocation["setup_deadline_ns"]) - cast(int, invocation["started_ns"])
        != SETUP_NS
    ):
        raise ValueError("Second recovery original deadlines changed")
    for field, expected in (
        ("kind", "restricted_reference_ec2_recovery_run_v1"),
        ("schema_version", 1),
        ("phase", "TERMINAL"),
        ("outcome", "NOT_QUALIFIED"),
        ("poisoned", True),
        ("charged", 1),
        ("backend_confirmed", 1),
        ("final_report_sha256", None),
    ):
        _fixed(state[field], expected, "second recovery " + field)
    _fixed(claim["kind"], "restricted_reference_ec2_recovery_claim_v1", "second claim kind")
    _fixed(claim["schema_version"], 1, "second claim schema")
    owner = _mapping(claim["owner"], {"pid", "start_ticks", "uid", "invocation"}, "old owner")
    for field in ("pid", "start_ticks", "uid"):
        if type(owner[field]) is not int or cast(int, owner[field]) < 0:
            raise ValueError("Second recovery owner integer is invalid")
    if type(owner["invocation"]) is not str or not _HEX64.fullmatch(owner["invocation"]):
        raise ValueError("Second recovery owner invocation is invalid")
    _fixed(state["owner"], owner, "second state owner")
    for field, expected in (
        ("kind", "restricted_reference_ec2_recovery_plan_v1"),
        ("schema_version", 1),
        ("plan_id", RECOVERY_PLAN_ID),
        ("freeze_revision", RECOVERY_FREEZE_REVISION),
        ("source_revision", previous["source_revision"]),
        ("run_id", previous["run_id"]),
        ("expected_identity", EXPECTED_IDENTITY),
        ("predecessor", RECOVERY_PREDECESSOR),
        ("allowance", RECOVERY_ALLOWANCE),
        ("source_lock", seals[str(lock_path)][0]),
    ):
        _fixed(plan[field], expected, "old recovery plan " + field)
    old_stop = ROOT / "recovery-evidence" / "operator-stop.md"
    _fixed(
        plan["stop_observation"],
        {
            "kind": "trusted_owner_aws_stop_observation_v1",
            "observed_state": "Stopped",
            "reason": "Client.InstanceInitiatedShutdown",
            "evidence": seals[str(old_stop)][0],
        },
        "old recovery Stop observation",
    )
    _fixed(
        consumption,
        {
            "kind": "restricted_reference_ec2_recovery_consumption_v1",
            "schema_version": 1,
            "plan_id": RECOVERY_PLAN_ID,
            "plan_sha256": previous["plan_sha256"],
            "freeze_revision": RECOVERY_FREEZE_REVISION,
            **invocation,
            "owner": owner,
            "predecessor_state_sha256": RECOVERY_PREDECESSOR["state_sha256"],
            "prior_charged": 1,
            "max_admissions": 24,
            "max_cumulative_admissions": 25,
        },
        "old recovery consumption",
    )
    context = {
        "kind": "restricted_reference_ec2_recovery_context_v1",
        "schema_version": 1,
        "plan_id": RECOVERY_PLAN_ID,
        "plan": seals[str(plan_path)][0],
        "predecessor": dict(RECOVERY_PREDECESSOR),
        "consumption": seals[str(consumption_path)][0],
        "invocation": invocation,
        "allowance": dict(RECOVERY_ALLOWANCE),
    }
    _fixed(claim["recovery_context"], context, "second claim context")
    provider = state["provider_context"]
    if not isinstance(provider, dict):
        raise ValueError("Second recovery provider is missing")
    for document in (state, report, manifest, cast(Row, provider)):
        _fixed(document.get("recovery_context"), context, "second immutable context")
    for document in (report, manifest, preload, setup):
        _fixed(document.get("provider_context"), provider, "second observed provider")
    for field, expected in (
        ("kind", "restricted_reference_ec2_recovery_host_v1"),
        ("schema_version", 1),
        ("source_revision", previous["source_revision"]),
        ("run_id", previous["run_id"]),
        ("boot_id", previous["boot_id"]),
        ("source_lock", seals[str(lock_path)][0]),
        ("identity_document", seals[str(old_dir / "instance-identity-document.json")][0]),
    ):
        _fixed(provider.get(field), expected, "second provider " + field)
    for field, expected in EXPECTED_IDENTITY.items():
        _fixed(identity.get(field), expected, "second identity " + field)
    _fixed(
        state["policy_receipts"],
        {
            "preload_sha256": previous["policy_preload_sha256"],
            "report_sha256": previous["policy_setup_sha256"],
        },
        "second policy receipts",
    )
    _fixed(setup.get("preload_manifest_sha256"), previous["policy_preload_sha256"], "old preload")
    _fixed(old_lock.get("kind"), "restricted_reference_ec2_recovery_source_lock_v1", "old lock")
    _fixed(old_lock.get("schema_version"), 1, "old lock schema")
    _fixed(old_lock.get("source_revision"), previous["source_revision"], "old lock source")
    _mapping(old_lock.get("files"), set(RECOVERY_SOURCE_FILES), "old recovery source closure")
    rows = state["admissions"]
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Second recovery lost its one charged admission")
    ticket_keys = {field.name for field in dataclasses.fields(ProbeAdmission)}
    admission = _mapping(rows[0], ticket_keys | {"accepted", "outcome"}, "old admission")
    for field, expected in (
        ("accepted", True),
        ("admission_number", 1),
        ("name", "positive"),
        ("source_revision", previous["source_revision"]),
        ("run_id", previous["run_id"]),
        ("boot_id", previous["boot_id"]),
    ):
        _fixed(admission[field], expected, "second admission " + field)
    if (
        type(admission["nonce"]) is not str
        or not _HEX32.fullmatch(admission["nonce"])
        or type(admission["admitted_ns"]) is not int
        or type(admission["deadline_ns"]) is not int
        or not cast(int, invocation["started_ns"]) <= admission["admitted_ns"]
        < cast(int, invocation["deadline_ns"])
        or admission["deadline_ns"]
        != min(cast(int, invocation["deadline_ns"]), admission["admitted_ns"] + PROBE_NS)
    ):
        raise ValueError("Second recovery ticket nonce or original deadline is invalid")
    _fixed(
        admission["outcome"],
        {
            "result_sha256": previous["case_sha256"],
            "stop_confirmed": True,
            "cleanup_confirmed": True,
            "failure": "setup_refused",
        },
        "second admission outcome",
    )
    for field, expected in (
        ("name", "positive"),
        ("nonce", admission["nonce"]),
        ("payload_started", False),
        ("failure", "setup_refused"),
        ("stop_confirmed", True),
        ("cleanup_confirmed", True),
    ):
        _fixed(result.get(field), expected, "second raw case " + field)
    facts = result.get("host_facts")
    if not isinstance(facts, dict):
        raise ValueError("Second raw case lacks original host bindings")
    for field, expected in (
        ("manifest_sha256", previous["manifest_sha256"]),
        ("admission_number", 1),
        ("original_admission_ns", admission["admitted_ns"]),
        ("original_deadline_ns", admission["deadline_ns"]),
    ):
        _fixed(facts.get(field), expected, "second raw case binding " + field)
    initial = {
        "kind": "restricted_reference_ec2_recovery_budget_v1",
        "schema_version": 1,
        "plan_id": RECOVERY_PLAN_ID,
        "predecessor_run_id": RECOVERY_PREDECESSOR["run_id"],
        "prior_charged": 1,
        "prior_backend_confirmed": 1,
        "current_charged": 0,
        "current_backend_confirmed": 0,
        "current_unconfirmed": 0,
        "current_pending_outcomes": 0,
        "cumulative_charged": 1,
        "cumulative_backend_confirmed": 1,
        "max_current_admissions": 24,
        "max_cumulative_admissions": 25,
    }
    _fixed(manifest["recovery_accounting"], initial, "second pre-probe accounting")
    _fixed(manifest["recovery_accounting_phase"], "pre_probe_manifest", "second manifest phase")
    final = {
        **initial,
        "current_charged": 1,
        "current_backend_confirmed": 1,
        "cumulative_charged": 2,
        "cumulative_backend_confirmed": 2,
    }
    _fixed(report.get("recovery_accounting"), final, "second final accounting")
    for field, expected in (
        ("kind", "restricted_reference_ec2_recovery_qualification_v1"),
        ("schema_version", 1),
        ("controls_status", "NOT_QUALIFIED"),
        ("admissions_charged", 1),
        ("confirmed_backend_admissions", 1),
        ("backend_unconfirmed_admissions", 0),
        ("pending_probe_outcomes", 0),
        ("observed_payload_starts", 0),
        ("research_reservations", 0),
        ("replay_engine_invocations", 0),
        ("manifest_sha256", previous["manifest_sha256"]),
    ):
        _fixed(report.get(field), expected, "second report " + field)
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != MAX_ADMISSIONS:
        raise ValueError("Second failed report lost its incomplete catalog")
    for index, value in enumerate(cases):
        if not isinstance(value, dict):
            raise ValueError("Second report case is not an object")
        _fixed(value.get("name"), FIXED_PROBES[index], "second report case name")
        _fixed(value.get("status"), "UNKNOWN", "second report case status")
        _fixed(value.get("admission_submitted"), index == 0, "second report submission")
        if index == 0:
            _fixed(
                value.get("admission"), {key: admission[key] for key in ticket_keys}, "old ticket"
            )
            _fixed(value.get("nonce"), admission["nonce"], "old report nonce")
            _fixed(
                value.get("execution_evidence"), seals[str(old_dir / "case-01.json")][0], "old case"
            )
    path = ROOT / "recovery-v2" / "operator-stop.md"
    raw, seal = _secure_read(path, 65536)
    if _sha(raw) != RECOVERY_V2_STOP_SHA256:
        raise ValueError("Pinned second owner Stop observation bytes differ")
    record = {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}
    seals[str(path)] = (record, seal)
    return {
        "kind": "trusted_owner_aws_stop_observation_v1",
        "observed_state": "Stopped",
        "reason": "Client.InstanceInitiatedShutdown",
        "evidence": record,
    }


def _boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if not _BOOT.fullmatch(value):
        raise ValueError("Missing actual kernel boot identity")
    return value


def _owner() -> Row:
    # Field22 starttime binds this PID, not a recycled numeric PID.
    raw = Path("/proc/self/stat").read_text()
    fields = raw[raw.rfind(")") + 2 :].split()
    if len(fields) < 20 or not fields[19].isdecimal():
        raise ValueError("Missing actual controller process identity")
    return {"pid": os.getpid(), "start_ticks": int(fields[19]), "uid": os.geteuid()}


def _host() -> Row:
    if platform.system() != "Linux" or platform.machine() != "x86_64" or os.geteuid() != 0:
        raise ValueError("Dedicated reference requires actual root Linux x86_64")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise ValueError("Dedicated reference requires actual Ubuntu24.04")
    label = Path("/proc/self/attr/current").read_text().strip()
    status = Path("/proc/self/status").read_text().splitlines()
    if label != "unconfined" or "NoNewPrivs:\t0" not in status:
        raise ValueError("Controller must retain original unconfined pre-NNP context")
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "architecture": platform.machine(),
        "os_release": release,
        "boot_id": _boot_id(),
        "controller_uid": os.geteuid(),
        "controller_gid": os.getegid(),
        "controller_label": label,
    }


def _recovery_plan(
    *,
    source_revision: str,
    run_id: str,
    plan_id: str,
    host: Row,
    seals: dict[str, tuple[Row, tuple[int, int, int, int, int]]],
) -> Row:
    _recovery_arguments(source_revision, run_id, plan_id)
    if host["boot_id"] == RECOVERY_PREDECESSOR["boot_id"]:
        raise ValueError("Recovery requires a different actual boot identity")
    source_lock, _provider = _source_records(source_revision, recovery=True, seals=seals)
    stop = _recovery_history(seals)
    return {
        "kind": "restricted_reference_ec2_recovery_plan_v1",
        "schema_version": 1,
        "plan_id": plan_id,
        "freeze_revision": RECOVERY_FREEZE_REVISION,
        "source_revision": source_revision,
        "run_id": run_id,
        "expected_identity": dict(EXPECTED_IDENTITY),
        "predecessor": dict(RECOVERY_PREDECESSOR),
        "allowance": dict(RECOVERY_ALLOWANCE),
        "stop_observation": stop,
        "source_lock": source_lock,
        "provisioner_source": seals[str(SOURCE_ROOT / RECOVERY_SOURCE_FILES[-1])][0],
    }


def recovery_plan_document(*, source_revision: str, run_id: str, plan_id: str) -> Row:
    """Read-only trusted preparation; caller holds the historical local host flock.

    No claim, monotonic window, metadata request, policy or probe is allocated.
    The fixed helper exclusively persists the returned plan while holding its lock.
    """
    return _recovery_plan(
        source_revision=source_revision,
        run_id=run_id,
        plan_id=plan_id,
        host=_host(),
        seals={},
    )


def _recovery_v2_arguments(source_revision: str, run_id: str, plan_id: str) -> None:
    if (
        type(source_revision) is not str
        or not _HEX40.fullmatch(source_revision)
        or type(run_id) is not str
        or run_id != RECOVERY_V2_RUN_ID
        or type(plan_id) is not str
        or plan_id != RECOVERY_V2_PLAN_ID
        or source_revision in {
            RECOVERY_V2_HISTORY["original"]["source_revision"],
            RECOVERY_V2_HISTORY["recovery"]["source_revision"],
        }
    ):
        raise ValueError("Only the fixed v2 plan/run and a new actual source are supported")


def _recovery_v2_plan(
    *,
    source_revision: str,
    run_id: str,
    plan_id: str,
    host: Row,
    seals: dict[str, tuple[Row, tuple[int, int, int, int, int]]],
) -> Row:
    _recovery_v2_arguments(source_revision, run_id, plan_id)
    if host["boot_id"] in {item["boot_id"] for item in RECOVERY_V2_HISTORY.values()}:
        raise ValueError("Recovery v2 requires a different actual boot from both failed boots")
    source_lock, _provider = _source_records(source_revision, recovery=True, version=2, seals=seals)
    stop = _recovery_v2_history(seals)
    return {
        "kind": "restricted_reference_ec2_recovery_plan_v2",
        "schema_version": 2,
        "plan_id": plan_id,
        "freeze_revision": RECOVERY_V2_FREEZE_REVISION,
        "source_revision": source_revision,
        "run_id": run_id,
        "expected_identity": dict(EXPECTED_IDENTITY),
        "history": _json(canonical(RECOVERY_V2_HISTORY)),
        "allowance": dict(RECOVERY_V2_ALLOWANCE),
        "stop_observation": stop,
        "source_lock": source_lock,
        "provisioner_source": seals[str(SOURCE_ROOT / RECOVERY_V2_SOURCE_FILES[-1])][0],
    }


def recovery_v2_plan_document(*, source_revision: str, run_id: str, plan_id: str) -> Row:
    """Read-only v2 preparation while its caller holds the original host flock."""
    return _recovery_v2_plan(
        source_revision=source_revision, run_id=run_id, plan_id=plan_id, host=_host(), seals={}
    )


def _metadata(*, deadline_ns: int) -> bytes:
    """One direct bounded IMDSv2 PUT/GET. No redirect, proxy, retry or token storage."""
    deadline = min(deadline_ns, time.monotonic_ns() + 5_000_000_000)

    def request(method: str, path: str, headers: dict[str, str], limit: int) -> bytes:
        remaining = deadline - time.monotonic_ns()
        if remaining <= 0:
            raise TimeoutError("Original IMDS/setup deadline exhausted")
        connection = http.client.HTTPConnection("169.254.169.254", timeout=remaining / 1e9)
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("IMDSv2 refused fixed request")
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining = deadline - time.monotonic_ns()
                if remaining <= 0:
                    raise TimeoutError("Original IMDS/setup deadline exhausted")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining / 1e9)
                chunk = response.read1(min(4096, limit + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError("IMDSv2 response exceeds bound")
                chunks.append(chunk)
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("Original IMDS/setup deadline exhausted")
            return b"".join(chunks)
        finally:
            connection.close()

    if threading.current_thread() is not threading.main_thread():
        raise ValueError("Bounded IMDS setup requires the trusted main controller thread")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise ValueError("Refusing to replace an existing controller alarm")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expired(_number: int, _frame: object) -> None:
        raise TimeoutError("Original combined IMDS/setup deadline exhausted")

    remaining = deadline - time.monotonic_ns()
    if remaining <= 0:
        raise TimeoutError("Original IMDS/setup deadline exhausted")
    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, remaining / 1e9)
        token_raw = request(
            "PUT", "/latest/api/token", {"X-aws-ec2-metadata-token-ttl-seconds": "60"}, 4096
        )
        token = token_raw.decode("ascii")
        if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ValueError("Invalid bounded IMDSv2 token")
        return request(
            "GET",
            "/latest/dynamic/instance-identity/document",
            {"X-aws-ec2-metadata-token": token},
            16384,
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


@dataclasses.dataclass(frozen=True)
class BudgetSnapshot:
    started_ns: int
    deadline_ns: int
    max_admissions: int
    charged: int
    backend_confirmed: int
    unconfirmed: int
    poisoned: bool
    pending_outcomes: int = 0


@dataclasses.dataclass(frozen=True)
class ProbeAdmission:
    run_id: str
    boot_id: str
    source_revision: str
    admission_number: int
    name: str
    nonce: str
    admitted_ns: int
    deadline_ns: int


class Ec2Run:
    """A non-reconstructible live claim; all durable charges precede backend calls."""

    source_revision: str
    run_id: str
    boot_id: str
    started_ns: int
    deadline_ns: int
    setup_deadline_ns: int
    run_dir: Path
    staged_policy: Path
    policy_evidence_dir: Path
    artifact_dir: Path
    _owner: Row
    _host: Row
    _lock_fd: int
    _fenced: bool
    _state: Row
    _claim_raw: bytes
    _host_claim_raw: bytes
    _recovery_mode: bool = False
    _recovery_raw: bytes | None
    _seals: dict[str, tuple[Row, tuple[int, int, int, int, int]]]
    _source_lock: Row
    _provider_source: Row

    def __init__(self) -> None:
        raise TypeError("Use the exclusive Ec2Run.claim factory")

    @classmethod
    def claim(cls, *, source_revision: str, run_id: str) -> Ec2Run:
        if cls is not Ec2Run:
            raise TypeError("Only the fixed Ec2Run authority can claim this reference")
        if not _HEX40.fullmatch(source_revision) or not _HEX32.fullmatch(run_id):
            raise ValueError("Actual lowercase source commit and explicit32-hex run required")
        started = time.monotonic_ns()
        host = _host()
        owner = _owner()
        _secure_directory(ROOT, create=True)
        _secure_directory(ROOT / "runs", create=True)
        lock_path = ROOT / "host-admission.json"
        lock_fd = os.open(
            lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        instance: Ec2Run | None = None
        # The persistent host claim is intentionally never removed or automatically reused.
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            instance = object.__new__(cls)
            instance.source_revision = source_revision
            instance.run_id = run_id
            instance.boot_id = str(host["boot_id"])
            instance.started_ns = started
            instance.deadline_ns = started + WINDOW_NS
            instance.setup_deadline_ns = started + SETUP_NS
            instance.run_dir = ROOT / "runs" / run_id
            instance.staged_policy = instance.run_dir / "policy.apparmor"
            instance.policy_evidence_dir = instance.run_dir / "policy-evidence"
            instance.artifact_dir = instance.run_dir / "qualification"
            instance.run_dir.mkdir(mode=0o700)
            _fsync_dir(instance.run_dir.parent)
            instance._owner = {**owner, "invocation": secrets.token_hex(32)}
            instance._host = host
            instance._lock_fd = lock_fd
            instance._fenced = False
            instance._recovery_mode = False
            instance._recovery_raw = None
            instance._seals = {}
            instance._state = {
                "kind": "restricted_reference_ec2_run_v1",
                "schema_version": 1,
                "source_revision": source_revision,
                "run_id": run_id,
                "boot_id": instance.boot_id,
                "owner": instance._owner,
                "started_ns": started,
                "deadline_ns": instance.deadline_ns,
                "setup_deadline_ns": instance.setup_deadline_ns,
                "phase": "CLAIMED",
                "host_preparation_started": False,
                "provider_context": None,
                "policy_receipts": None,
                "charged": 0,
                "backend_confirmed": 0,
                "admissions": [],
                "poisoned": False,
                "outcome": None,
                "reason": None,
                "final_report_sha256": None,
            }
            claim = canonical(
                {
                    "kind": "restricted_reference_ec2_claim_v1",
                    "schema_version": 1,
                    "source_revision": source_revision,
                    "run_id": run_id,
                    "boot_id": instance.boot_id,
                    "owner": instance._owner,
                    "started_ns": started,
                    "deadline_ns": instance.deadline_ns,
                    "setup_deadline_ns": instance.setup_deadline_ns,
                }
            )
            if os.write(lock_fd, claim) != len(claim):
                raise OSError("Partial durable host claim write")
            os.fsync(lock_fd)
            _fsync_dir(ROOT)
            write_exclusive(instance.run_dir / "claim.json", claim)
            write_exclusive(instance.run_dir / "state.json", canonical(instance._state))
            instance._claim_raw = claim
            instance._host_claim_raw = claim
            instance._bind_source()
            instance.require_phase("CLAIMED")
            return instance
        except BaseException:
            if instance is not None and hasattr(instance, "_state"):
                try:
                    instance._state["phase"] = "TERMINAL"
                    instance._state["poisoned"] = True
                    instance._state["outcome"] = "NOT_QUALIFIED"
                    instance._state["reason"] = "claim_failed_or_uncertain"
                    instance._persist()
                except Exception:
                    pass
            os.close(lock_fd)
            # Every partially-created claim survives. Never erase an uncertain admission.
            raise

    @classmethod
    def claim_recovery(cls, *, source_revision: str, run_id: str, plan_id: str) -> Ec2Run:
        """Consume the one reviewed successor without changing the old host claim."""
        return cls._claim_recovery(
            source_revision=source_revision, run_id=run_id, plan_id=plan_id, version=1
        )

    @classmethod
    def claim_recovery_v2(cls, *, source_revision: str, run_id: str, plan_id: str) -> Ec2Run:
        """Consume only the separately frozen third invocation, preserving both failures."""
        return cls._claim_recovery(
            source_revision=source_revision, run_id=run_id, plan_id=plan_id, version=2
        )

    @classmethod
    def _claim_recovery(
        cls, *, source_revision: str, run_id: str, plan_id: str, version: int
    ) -> Ec2Run:
        if cls is not Ec2Run:
            raise TypeError("Only the fixed Ec2Run authority can claim this recovery")
        started = time.monotonic_ns()
        if type(version) is not int or version not in {1, 2}:
            raise ValueError("Only the two separately frozen recovery selections exist")
        arguments = _recovery_v2_arguments if version == 2 else _recovery_arguments
        arguments(source_revision, run_id, plan_id)
        host, owner = _host(), _owner()
        _secure_directory(ROOT)
        _secure_directory(ROOT / "runs")
        lock_path = ROOT / "host-admission.json"
        lock_fd = os.open(
            lock_path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        )
        instance: Ec2Run | None = None
        try:
            info = os.fstat(lock_fd)
            if not _regular_root(info) or info.st_size > 65536:
                raise ValueError("Historical host claim is not a bounded root regular file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            host_claim = os.read(lock_fd, 65537)
            if (
                len(host_claim) != info.st_size
                or _stable(info) != _stable(os.fstat(lock_fd))
                or _stable(info) != _stable(lock_path.lstat())
                or _sha(host_claim) != RECOVERY_PREDECESSOR["host_claim_sha256"]
            ):
                raise ValueError("Original locked host claim bytes/identity differ")
            instance = object.__new__(cls)
            instance.source_revision, instance.run_id = source_revision, run_id
            instance.boot_id = str(host["boot_id"])
            instance.started_ns = started
            instance.deadline_ns, instance.setup_deadline_ns = (
                started + WINDOW_NS,
                started + SETUP_NS,
            )
            instance.run_dir = ROOT / "runs" / run_id
            instance.staged_policy = instance.run_dir / "policy.apparmor"
            instance.policy_evidence_dir = instance.run_dir / "policy-evidence"
            instance.artifact_dir = instance.run_dir / "qualification"
            instance._owner = {**owner, "invocation": secrets.token_hex(32)}
            instance._host, instance._lock_fd = host, lock_fd
            instance._host_claim_raw = host_claim
            instance._fenced, instance._recovery_mode = False, True
            instance._recovery_raw, instance._seals = None, {}
            builder = _recovery_v2_plan if version == 2 else _recovery_plan
            expected_plan = builder(
                source_revision=source_revision,
                run_id=run_id,
                plan_id=plan_id,
                host=host,
                seals=instance._seals,
            )
            plan_path = (
                ROOT / "recovery-v2" / "plan.json" if version == 2 else ROOT / "recovery-plan.json"
            )
            plan_raw, plan_seal = _secure_read(plan_path, 65536)
            plan_keys = _PLAN_KEYS - {"predecessor"} | {"history"} if version == 2 else _PLAN_KEYS
            plan = _mapping(_json(plan_raw), plan_keys, "recovery plan")
            _fixed(plan, expected_plan, "recovery plan")
            if canonical(plan) != plan_raw:
                raise ValueError("Recovery plan is not exact canonical bytes")
            plan_record = {"path": str(plan_path), "sha256": _sha(plan_raw), "bytes": len(plan_raw)}
            instance._seals[str(plan_path)] = (plan_record, plan_seal)
            instance._source_lock = cast(Row, plan["source_lock"])
            instance._provider_source = instance._seals[str(SOURCE_ROOT / SOURCE_FILES[0])][0]
            if time.monotonic_ns() >= instance.setup_deadline_ns:
                raise TimeoutError("Original recovery setup deadline exhausted during validation")
            invocation = {
                "source_revision": source_revision,
                "run_id": run_id,
                "boot_id": instance.boot_id,
                "started_ns": started,
                "deadline_ns": instance.deadline_ns,
                "setup_deadline_ns": instance.setup_deadline_ns,
            }
            consumption = {
                "kind": f"restricted_reference_ec2_recovery_consumption_v{version}",
                "schema_version": version,
                "plan_id": plan_id,
                "plan_sha256": plan_record["sha256"],
                "freeze_revision": (
                    RECOVERY_V2_FREEZE_REVISION if version == 2 else RECOVERY_FREEZE_REVISION
                ),
                **invocation,
                "owner": instance._owner,
                **(
                    {
                        "history_state_sha256": {
                            key: value["state_sha256"] for key, value in RECOVERY_V2_HISTORY.items()
                        }
                    }
                    if version == 2
                    else {"predecessor_state_sha256": RECOVERY_PREDECESSOR["state_sha256"]}
                ),
                "prior_charged": version,
                "max_admissions": 24,
                "max_cumulative_admissions": 24 + version,
            }
            consumption_path = (
                ROOT / "recovery-v2" / "consumption.json"
                if version == 2
                else ROOT / "recovery-consumption.json"
            )
            # O_EXCL plus both fsyncs precede any successor run, metadata or policy.
            # Partial/empty/uncertain consumption is never removed, even on failure.
            write_exclusive(consumption_path, canonical(consumption))
            if version == 2:
                observed, consumption_seal = _secure_read(consumption_path, 65536)
                if observed != canonical(consumption):
                    raise ValueError("Durable v2 consumption publication is uncertain")
                consumption_record = {
                    "path": str(consumption_path),
                    "sha256": _sha(observed),
                    "bytes": len(observed),
                }
            else:
                consumption_record, consumption_seal = _file_record(consumption_path, 65536)
            instance._seals[str(consumption_path)] = (consumption_record, consumption_seal)
            context = {
                "kind": f"restricted_reference_ec2_recovery_context_v{version}",
                "schema_version": version,
                "plan_id": plan_id,
                "plan": plan_record,
                **(
                    {"history": _json(canonical(RECOVERY_V2_HISTORY))}
                    if version == 2
                    else {"predecessor": dict(RECOVERY_PREDECESSOR)}
                ),
                "consumption": consumption_record,
                "invocation": invocation,
                "allowance": dict(RECOVERY_V2_ALLOWANCE if version == 2 else RECOVERY_ALLOWANCE),
            }
            instance._recovery_raw = canonical(context)
            instance.run_dir.mkdir(mode=0o700)
            _fsync_dir(instance.run_dir.parent)
            claim = canonical(
                {
                    "kind": f"restricted_reference_ec2_recovery_claim_v{version}",
                    "schema_version": version,
                    **invocation,
                    "owner": instance._owner,
                    "recovery_context": context,
                }
            )
            instance._claim_raw = claim
            instance._state = {
                "kind": f"restricted_reference_ec2_recovery_run_v{version}",
                "schema_version": version,
                **invocation,
                "owner": instance._owner,
                "phase": "CLAIMED",
                "host_preparation_started": False,
                "provider_context": None,
                "policy_receipts": None,
                "charged": 0,
                "backend_confirmed": 0,
                "admissions": [],
                "poisoned": False,
                "outcome": None,
                "reason": None,
                "final_report_sha256": None,
                "recovery_context": _json(instance._recovery_raw),
            }
            write_exclusive(instance.run_dir / "claim.json", claim)
            write_exclusive(instance.run_dir / "state.json", canonical(instance._state))
            instance.require_phase("CLAIMED")
            return instance
        except BaseException:
            if instance is not None and hasattr(instance, "_state"):
                with suppress(Exception):
                    instance._state["phase"] = "TERMINAL"
                    instance._state["poisoned"] = True
                    instance._state["outcome"] = "NOT_QUALIFIED"
                    instance._state["reason"] = "recovery_claim_failed_or_uncertain"
                    instance._persist()
            os.close(lock_fd)
            raise

    def _bind_source(self) -> None:
        self._source_lock, self._provider_source = _source_records(
            self.source_revision,
            recovery=self._recovery_mode,
            seals=self._seals,
            version=self._context_version() if self._recovery_mode else 1,
        )

    def _context_version(self) -> int:
        raw = self._recovery_raw
        if type(raw) is not bytes:
            raise ValueError("Missing immutable recovery authority")
        value = _json(raw)
        if not isinstance(value, dict):
            raise ValueError("Invalid immutable recovery context")
        version = value.get("schema_version")
        if type(version) is not int or version not in {1, 2}:
            raise ValueError("Unknown exact immutable recovery version")
        key = "history" if version == 2 else "predecessor"
        context = _mapping(
            value,
            {
                "kind", "schema_version", "plan_id", "plan", key, "consumption", "invocation",
                "allowance",
            },
            "immutable recovery context",
        )
        _fixed(context["kind"], f"restricted_reference_ec2_recovery_context_v{version}", "context")
        _fixed(
            context["plan_id"], RECOVERY_V2_PLAN_ID if version == 2 else RECOVERY_PLAN_ID, "plan ID"
        )
        return version

    def _live(self) -> None:
        if self._fenced:
            raise ValueError("Durable claim is fenced after uncertain persistence")
        version = self._context_version() if self._recovery_mode else 1
        for field in (
            "source_revision",
            "run_id",
            "boot_id",
            "started_ns",
            "deadline_ns",
            "setup_deadline_ns",
        ):
            if self._recovery_mode:
                _fixed(getattr(self, field), self._state[field], "live original recovery " + field)
            if getattr(self, field) != self._state[field]:
                raise ValueError("Original claim identity or clock cannot be reassigned")
        expected_dir = ROOT / "runs" / self.run_id
        if (
            self.run_dir != expected_dir
            or self.staged_policy != expected_dir / "policy.apparmor"
            or self.policy_evidence_dir != expected_dir / "policy-evidence"
            or self.artifact_dir != expected_dir / "qualification"
        ):
            raise ValueError("Fixed claim paths cannot be redirected")
        if _boot_id() != self.boot_id:
            self._state["phase"] = "TERMINAL"
            self._state["outcome"] = "NOT_QUALIFIED"
            self._poison("boot_identity_changed")
            raise ValueError("An earlier boot cannot resume its qualification")
        if _owner() != {key: self._owner[key] for key in ("pid", "start_ticks", "uid")}:
            raise ValueError("Claim owner invocation differs")
        info = os.fstat(self._lock_fd)
        current = (ROOT / "host-admission.json").lstat()
        if _stable(info) != _stable(current) or not _regular_root(info):
            raise ValueError("Live host claim identity differs")
        os.lseek(self._lock_fd, 0, os.SEEK_SET)
        if os.read(self._lock_fd, 65537) != self._host_claim_raw:
            raise ValueError("Live host claim contents differ")
        claim_raw, _ = _secure_read(self.run_dir / "claim.json", 65536)
        state_raw, _ = _secure_read(self.run_dir / "state.json", 262144)
        keys = _STATE_KEYS | {"recovery_context"} if self._recovery_mode else _STATE_KEYS
        state = _mapping(_json(state_raw), keys, "durable run")
        if claim_raw != self._claim_raw or canonical(state) != canonical(self._state):
            raise ValueError("Durable run identity or counters differ")
        if self._recovery_mode:
            if self._recovery_raw is None:
                raise ValueError("Missing immutable recovery authority")
            context = _json(self._recovery_raw)
            _fixed(state["recovery_context"], context, "live recovery context")
            _fixed(
                state["kind"],
                f"restricted_reference_ec2_recovery_run_v{version}",
                "recovery state kind",
            )
            _fixed(state["schema_version"], version, "recovery state schema")
            own_claim = cast(Row, _json(claim_raw))
            _fixed(own_claim.get("recovery_context"), context, "recovery claim context")
            context_row = cast(Row, context)
            _fixed(
                {
                    field: state[field]
                    for field in (
                        "source_revision",
                        "run_id",
                        "boot_id",
                        "started_ns",
                        "deadline_ns",
                        "setup_deadline_ns",
                    )
                },
                context_row["invocation"],
                "recovery original invocation",
            )
            _fixed(state["owner"], own_claim["owner"], "recovery state owner")
            _fixed(self._owner, own_claim["owner"], "recovery live owner")
            self._validate_recovery_accounting()
            for path, (expected, seal) in self._seals.items():
                actual, actual_seal = _file_record(Path(path), 1_048_576)
                if actual != expected or actual_seal != seal:
                    self._poison("trusted_recovery_record_changed")
                    raise ValueError("Frozen trusted recovery record changed")

    def _validate_recovery_accounting(self) -> None:
        rows = self._state["admissions"]
        charged, confirmed = self._state["charged"], self._state["backend_confirmed"]
        if (
            type(charged) is not int
            or type(confirmed) is not int
            or not isinstance(rows, list)
            or not 0 <= confirmed <= charged <= MAX_ADMISSIONS
            or charged != len(rows)
        ):
            raise ValueError("Invalid actual recovery admission counters")
        accepted = 0
        nonces: set[str] = set()
        ticket_keys = {field.name for field in dataclasses.fields(ProbeAdmission)}
        for index, value in enumerate(rows):
            row = _mapping(value, ticket_keys | {"accepted", "outcome"}, "recovery admission")
            for field, expected in (
                ("run_id", self.run_id),
                ("boot_id", self.boot_id),
                ("source_revision", self.source_revision),
                ("admission_number", index + 1),
                ("name", FIXED_PROBES[index]),
            ):
                _fixed(row[field], expected, "recovery ticket " + field)
            nonce = row["nonce"]
            if type(nonce) is not str or not _HEX32.fullmatch(nonce) or nonce in nonces:
                raise ValueError("Invalid/duplicate recovery nonce")
            nonces.add(nonce)
            if (
                type(row["admitted_ns"]) is not int
                or type(row["deadline_ns"]) is not int
                or not self.started_ns <= row["admitted_ns"] < self.deadline_ns
                or row["deadline_ns"] != min(self.deadline_ns, row["admitted_ns"] + PROBE_NS)
                or type(row["accepted"]) is not bool
            ):
                raise ValueError("Invalid recovery ticket clock/acceptance")
            accepted += row["accepted"] is True
            outcome = row["outcome"]
            if outcome is not None:
                outcome_row = _mapping(
                    outcome,
                    {"result_sha256", "stop_confirmed", "cleanup_confirmed", "failure"},
                    "recovery outcome",
                )
                digest, failure = outcome_row["result_sha256"], outcome_row["failure"]
                if (
                    row["accepted"] is not True
                    or type(digest) is not str
                    or not _HEX64.fullmatch(digest)
                    or type(outcome_row["stop_confirmed"]) is not bool
                    or type(outcome_row["cleanup_confirmed"]) is not bool
                    or (failure is not None and type(failure) is not str)
                ):
                    raise ValueError("Invalid recovery outcome fields")
        if accepted != confirmed:
            raise ValueError("Actual accepted recovery rows and counters differ")

    @property
    def recovery_context(self) -> Row | None:
        if not getattr(self, "_recovery_mode", False):
            return None
        self._live()
        return cast(Row, _json(cast(bytes, self._recovery_raw)))

    @property
    def recovery_schema_version(self) -> int | None:
        """Read version only from the live, independently immutable context."""
        context = self.recovery_context
        if context is None:
            return None
        version = context.get("schema_version")
        if type(version) is not int or version not in {1, 2}:
            raise ValueError("Unknown exact established recovery schema")
        _fixed(
            context.get("kind"), f"restricted_reference_ec2_recovery_context_v{version}", "schema"
        )
        return version

    def recovery_accounting(self, snapshot: BudgetSnapshot) -> Row | None:
        if not getattr(self, "_recovery_mode", False):
            return None
        if type(snapshot) is not BudgetSnapshot:
            raise ValueError("Actual live recovery budget snapshot required")
        _fixed(
            dataclasses.asdict(snapshot),
            dataclasses.asdict(self.snapshot()),
            "live recovery snapshot",
        )
        version = self._context_version()
        return {
            "kind": f"restricted_reference_ec2_recovery_budget_v{version}",
            "schema_version": version,
            "plan_id": RECOVERY_V2_PLAN_ID if version == 2 else RECOVERY_PLAN_ID,
            **(
                {"historical_run_ids": [item["run_id"] for item in RECOVERY_V2_HISTORY.values()]}
                if version == 2
                else {"predecessor_run_id": RECOVERY_PREDECESSOR["run_id"]}
            ),
            "prior_charged": version,
            "prior_backend_confirmed": version,
            "current_charged": snapshot.charged,
            "current_backend_confirmed": snapshot.backend_confirmed,
            "current_unconfirmed": snapshot.unconfirmed,
            "current_pending_outcomes": snapshot.pending_outcomes,
            "cumulative_charged": version + snapshot.charged,
            "cumulative_backend_confirmed": version + snapshot.backend_confirmed,
            "max_current_admissions": 24,
            "max_cumulative_admissions": 24 + version,
        }

    def _persist(self) -> None:
        temporary = self.run_dir / ("state-next-" + secrets.token_hex(16) + ".json")
        try:
            write_exclusive(temporary, canonical(self._state))
            os.replace(temporary, self.run_dir / "state.json")
            _fsync_dir(self.run_dir)
        except BaseException:
            self._fenced = True
            # An exclusive, persistent marker prevents an uncertain write being retried.
            with suppress(OSError):
                write_exclusive(self.run_dir / "persistence-uncertain", b"FENCED\n")
            raise

    def _poison(self, reason: str) -> None:
        self._state["poisoned"] = True
        self._state["reason"] = reason[:2048]
        self._persist()

    def require_phase(self, phase: str) -> None:
        self._live()
        if self._state["phase"] != phase or self._state["poisoned"] is not False:
            if self._state["phase"] != "TERMINAL" and self._state["poisoned"] is False:
                self._poison("duplicate_or_out_of_order_phase_entry")
            raise ValueError("Qualification phase/poison fence refuses this operation")

    @property
    def provider_record(self) -> Row:
        value = self._state["provider_context"]
        keys = {
            "kind",
            "schema_version",
            "provider",
            "expected_identity",
            "observed_identity",
            "source_revision",
            "run_id",
            "boot_id",
            "host",
            "gha_metadata",
            "gha_metadata_reason",
            "provider_source",
            "source_lock",
            "identity_document",
        }
        if self._recovery_mode:
            keys.add("recovery_context")
        record = _mapping(
            value,
            keys,
            "provider context",
        )
        kind = (
            f"restricted_reference_ec2_recovery_host_v{self._context_version()}"
            if self._recovery_mode
            else "restricted_reference_ec2_host_v1"
        )
        if (
            record["kind"] != kind
            or type(record["schema_version"]) is not int
            or record["schema_version"] != (self._context_version() if self._recovery_mode else 1)
            or record["provider"] != "aws_ec2_dedicated_v1"
            or record["source_revision"] != self.source_revision
            or record["run_id"] != self.run_id
            or record["boot_id"] != self.boot_id
            or record["gha_metadata"] is not None
            or record["gha_metadata_reason"] != "not_applicable_aws_ec2"
        ):
            raise ValueError("Unknown or mismatched fixed provider identity/schema")
        if self._recovery_mode:
            _fixed(record["recovery_context"], self.recovery_context, "provider recovery context")
        for field in ("expected_identity", "observed_identity"):
            identity = _mapping(record[field], set(EXPECTED_IDENTITY), field)
            if identity != EXPECTED_IDENTITY or any(
                type(value) is not str for value in identity.values()
            ):
                raise ValueError("Unknown/mismatched selected EC2 identity")
        host = _mapping(
            record["host"],
            {
                "system",
                "release",
                "version",
                "architecture",
                "os_release",
                "boot_id",
                "controller_uid",
                "controller_gid",
                "controller_label",
            },
            "provider host",
        )
        release = host["os_release"]
        if (
            host != self._host
            or host["system"] != "Linux"
            or host["architecture"] != "x86_64"
            or host["boot_id"] != self.boot_id
            or host["controller_label"] != "unconfined"
            or type(host["controller_uid"]) is not int
            or host["controller_uid"] != 0
            or type(host["controller_gid"]) is not int
            or not isinstance(host["release"], str)
            or not host["release"]
            or not isinstance(host["version"], str)
            or not host["version"]
            or not isinstance(release, dict)
            or release.get("ID") != "ubuntu"
            or release.get("VERSION_ID") != "24.04"
            or any(type(key) is not str or type(value) is not str for key, value in release.items())
        ):
            raise ValueError("Missing/mismatched actual provider host tuple")
        for field, path, limit in (
            ("provider_source", SOURCE_ROOT / SOURCE_FILES[0], 1_048_576),
            ("source_lock", ROOT / "sources" / self.source_revision / "source-lock.json", 65536),
            ("identity_document", self.run_dir / "instance-identity-document.json", 16384),
        ):
            item = _mapping(record[field], {"path", "sha256", "bytes"}, field)
            if (
                item["path"] != str(path)
                or not isinstance(item["sha256"], str)
                or not _HEX64.fullmatch(item["sha256"])
                or type(item["bytes"]) is not int
                or not 0 < item["bytes"] <= limit
                or self._seals.get(str(path), (None, None))[0] != item
            ):
                raise ValueError("Unbound provider source/cache receipt")
        return cast(Row, _json(canonical(record)))

    def prepare_host(self) -> Row:
        self.require_phase("CLAIMED")
        if self._state["host_preparation_started"] is not False:
            raise ValueError("Host setup is single-use and cannot be retried")
        self._state["host_preparation_started"] = True
        self._persist()
        try:
            if time.monotonic_ns() >= self.setup_deadline_ns:
                raise TimeoutError("Original setup deadline exhausted")
            raw = _metadata(deadline_ns=self.setup_deadline_ns)
            document = _json(raw)
            if not isinstance(document, dict):
                raise ValueError("Missing actual instance identity document")
            observed: Row = {}
            for key, expected in EXPECTED_IDENTITY.items():
                if type(document.get(key)) is not str or document[key] != expected:
                    raise ValueError("Actual selected EC2 identity differs: " + key)
                observed[key] = document[key]
            path = self.run_dir / "instance-identity-document.json"
            write_exclusive(path, raw)
            iid_record, iid_seal = _file_record(path, 16384)
            self._seals[str(path)] = (iid_record, iid_seal)
            self._state["provider_context"] = {
                "kind": (
                    f"restricted_reference_ec2_recovery_host_v{self._context_version()}"
                    if self._recovery_mode
                    else "restricted_reference_ec2_host_v1"
                ),
                "schema_version": self._context_version() if self._recovery_mode else 1,
                "provider": "aws_ec2_dedicated_v1",
                "expected_identity": dict(EXPECTED_IDENTITY),
                "observed_identity": observed,
                "source_revision": self.source_revision,
                "run_id": self.run_id,
                "boot_id": self.boot_id,
                "host": self._host,
                "gha_metadata": None,
                "gha_metadata_reason": "not_applicable_aws_ec2",
                "provider_source": self._provider_source,
                "source_lock": self._source_lock,
                "identity_document": iid_record,
                **({"recovery_context": self.recovery_context} if self._recovery_mode else {}),
            }
            self._persist()
            return self.revalidate(deadline_ns=self.setup_deadline_ns)
        except BaseException:
            self._poison("host_preparation_failed_or_uncertain")
            raise

    def revalidate(self, *, deadline_ns: int) -> Row:
        self._live()
        if (
            type(deadline_ns) is not int
            or deadline_ns > self.deadline_ns
            or time.monotonic_ns() >= deadline_ns
            or self._state["poisoned"] is not False
            or self._state["phase"] == "TERMINAL"
        ):
            raise ValueError("Original claim deadline/phase refuses admission")
        for path, (expected, seal) in self._seals.items():
            actual, actual_seal = _file_record(Path(path), 1_048_576)
            if actual != expected or actual_seal != seal:
                self._poison("trusted_source_or_cached_identity_changed")
                raise ValueError("Frozen trusted source or identity cache changed")
        return self.provider_record

    def policy_ready(self, *, preload_sha256: str, report_sha256: str) -> None:
        self.require_phase("CLAIMED")
        self.revalidate(deadline_ns=self.setup_deadline_ns)
        for name, digest in (
            ("preload-manifest.json", preload_sha256),
            ("policy-setup.json", report_sha256),
        ):
            if not _HEX64.fullmatch(digest):
                raise ValueError("Invalid policy receipt digest")
            record, _ = _file_record(self.policy_evidence_dir / name, 262144)
            if record["sha256"] != digest:
                raise ValueError("Actual policy receipt digest differs")
        self._state["policy_receipts"] = {
            "preload_sha256": preload_sha256,
            "report_sha256": report_sha256,
        }
        self._state["phase"] = "POLICY_READY"
        self._persist()

    def acquire_runner(self) -> BudgetSnapshot:
        self.require_phase("POLICY_READY")
        self.revalidate(deadline_ns=self.deadline_ns)
        self._state["phase"] = "QUALIFYING"
        self._persist()
        return self.snapshot()

    def snapshot(self) -> BudgetSnapshot:
        self._live()
        charged = cast(int, self._state["charged"])
        confirmed = cast(int, self._state["backend_confirmed"])
        return BudgetSnapshot(
            self.started_ns,
            self.deadline_ns,
            MAX_ADMISSIONS,
            charged,
            confirmed,
            charged - confirmed,
            self._state["poisoned"] is True,
            sum(row["outcome"] is None for row in self._admissions()),
        )

    def _admissions(self) -> list[Row]:
        return cast(list[Row], self._state["admissions"])

    def reserve_probe(self, *, name: str, nonce: str) -> ProbeAdmission:
        self.require_phase("QUALIFYING")
        self.revalidate(deadline_ns=self.deadline_ns)
        if not _HEX32.fullmatch(nonce):
            raise ValueError("Fixed probe identity/nonce missing")
        admissions = self._admissions()
        if (
            len(admissions) >= MAX_ADMISSIONS
            or name != FIXED_PROBES[len(admissions)]
            or any(row["name"] == name or row["nonce"] == nonce for row in admissions)
            or any(row["outcome"] is None for row in admissions)
        ):
            raise ValueError("Original shared admissions exhausted, duplicate or uncertain")
        admitted = time.monotonic_ns()
        if admitted >= self.deadline_ns:
            raise TimeoutError("Original qualification window exhausted before durable charge")
        ticket = ProbeAdmission(
            self.run_id,
            self.boot_id,
            self.source_revision,
            len(admissions) + 1,
            name,
            nonce,
            admitted,
            min(self.deadline_ns, admitted + PROBE_NS),
        )
        admissions.append({**dataclasses.asdict(ticket), "accepted": False, "outcome": None})
        self._state["charged"] = len(admissions)
        self._persist()  # durable charge occurs before any backend call
        return ticket

    def _ticket(self, admission: ProbeAdmission) -> Row:
        if type(admission) is not ProbeAdmission or not 1 <= admission.admission_number <= 24:
            raise ValueError("Actual durable admission ticket required")
        if self._recovery_mode and type(admission.admission_number) is not int:
            raise ValueError("Actual integer recovery admission number required")
        rows = self._admissions()
        if admission.admission_number > len(rows):
            raise ValueError("Admission was not durably submitted")
        row = rows[admission.admission_number - 1]
        ticket = dataclasses.asdict(admission)
        if self._recovery_mode:
            _fixed(ticket, {key: row[key] for key in ticket}, "actual recovery ticket")
        if {key: row[key] for key in ticket} != ticket:
            raise ValueError("Admission source/run/boot/deadline identity differs")
        return row

    def admit_probe(self, admission: ProbeAdmission) -> None:
        self.require_phase("QUALIFYING")
        row = self._ticket(admission)
        self.revalidate(deadline_ns=admission.deadline_ns)
        if row["accepted"] is not False or row["outcome"] is not None:
            raise ValueError("Durable admission cannot be accepted twice")
        row["accepted"] = True
        self._state["backend_confirmed"] = cast(int, self._state["backend_confirmed"]) + 1
        self._persist()

    def finish_probe(
        self,
        admission: ProbeAdmission,
        *,
        result_sha256: str,
        stop_confirmed: bool,
        cleanup_confirmed: bool,
        failure: str | None,
    ) -> None:
        self._live()
        row = self._ticket(admission)
        if (
            self._state["phase"] != "QUALIFYING"
            or row["accepted"] is not True
            or row["outcome"] is not None
            or not _HEX64.fullmatch(result_sha256)
            or type(stop_confirmed) is not bool
            or type(cleanup_confirmed) is not bool
            or (failure is not None and not isinstance(failure, str))
        ):
            raise ValueError("Probe outcome cannot replace or invent an admission")
        row["outcome"] = {
            "result_sha256": result_sha256,
            "stop_confirmed": stop_confirmed,
            "cleanup_confirmed": cleanup_confirmed,
            "failure": failure,
        }
        expected_termination = (
            admission.name in {"cpu", "detached"} and failure == "deadline_exceeded"
        ) or (admission.name == "output_flood" and failure in {"stdout_limit", "stderr_limit"})
        if (
            (failure is not None and not expected_termination)
            or not stop_confirmed
            or not cleanup_confirmed
        ):
            self._state["poisoned"] = True
            self._state["reason"] = "probe_failed_or_stop_cleanup_uncertain"
        self._persist()

    def finish(
        self,
        *,
        outcome: str,
        reason: str | None,
        final_report_sha256: str | None = None,
    ) -> None:
        self._live()
        if self._state["phase"] == "TERMINAL":
            raise ValueError("Terminal run cannot be replaced or restarted")
        if outcome not in {"NOT_QUALIFIED", "QUALIFIED_REFERENCE_ONLY"}:
            raise ValueError("Unknown fixed qualification outcome")
        pending = any(row["outcome"] is None for row in self._admissions())
        if outcome == "QUALIFIED_REFERENCE_ONLY" and (
            self._state["phase"] != "QUALIFYING"
            or self._state["poisoned"] is not False
            or pending
            or len(self._admissions()) != len(FIXED_PROBES)
        ):
            raise ValueError("Incomplete/uncertain run cannot qualify")
        if outcome == "QUALIFIED_REFERENCE_ONLY":
            self._check_final_report(final_report_sha256)
        elif final_report_sha256 is not None:
            raise ValueError("Unqualified outcomes do not authenticate a successful report")
        self._state["poisoned"] = self._state["poisoned"] is True or pending
        self._state["phase"] = "TERMINAL"
        self._state["outcome"] = outcome
        self._state["reason"] = reason[:2048] if reason is not None else None
        self._state["final_report_sha256"] = final_report_sha256
        self._persist()

    def _check_final_report(self, digest: str | None) -> Row:
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise ValueError("Successful qualification requires a bound final report")
        raw, _ = _secure_read(self.run_dir / "qualification-report.json", 262144)
        report = _json(raw)
        if not isinstance(report, dict) or _sha(raw) != digest:
            raise ValueError("Final report and durable terminal digest differ")
        cases = report.get("cases")
        report_kind = (
            f"restricted_reference_ec2_recovery_qualification_v{self._context_version()}"
            if self._recovery_mode
            else "restricted_reference_ec2_qualification_v1"
        )
        if (
            report.get("kind") != report_kind
            or type(report.get("schema_version")) is not int
            or report.get("schema_version")
            != (self._context_version() if self._recovery_mode else 1)
            or report.get("source_revision") != self.source_revision
            or report.get("run_id") != self.run_id
            or report.get("boot_id") != self.boot_id
            or report.get("controls_status") != "QUALIFIED_REFERENCE_ONLY"
            or report.get("production_m1") != "DISABLED"
            or report.get("acceptance_gate") != "matching_durable_terminal_and_final_report_sha256"
            or report.get("admissions_charged") != MAX_ADMISSIONS
            or report.get("confirmed_backend_admissions") != MAX_ADMISSIONS
            or report.get("pending_probe_outcomes") != 0
            or type(report.get("pending_probe_outcomes")) is not int
            or report.get("durable_budget_status") != "CONFIRMED"
            or report.get("durable_budget") != dataclasses.asdict(self.snapshot())
            or report.get("failure") is not None
            or not isinstance(cases, list)
            or len(cases) != len(FIXED_PROBES)
        ):
            raise ValueError("Final report lacks complete matching scoped evidence")
        for name, case in zip(FIXED_PROBES, cases, strict=True):
            if (
                not isinstance(case, dict)
                or case.get("name") != name
                or case.get("status") != "PASS"
            ):
                raise ValueError("Final report has incomplete fixed-case evidence")
        if self._recovery_mode:
            self._check_recovery_report(cast(Row, report))
        return cast(Row, report)

    def _check_recovery_report(self, report: Row) -> None:
        expected: object
        version = self._context_version()
        _mapping(
            report,
            {
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
            },
            "successful recovery report",
        )
        snapshot = self.snapshot()
        accounting = self.recovery_accounting(snapshot)
        _fixed(report["recovery_context"], self.recovery_context, "report recovery context")
        _fixed(report["recovery_accounting"], accounting, "report recovery accounting")
        _fixed(report["durable_budget"], dataclasses.asdict(snapshot), "report original budget")
        _fixed(report["provider_context"], self.provider_record, "report actual provider")
        for field, expected in (
            ("admissions_charged", 24),
            ("confirmed_backend_admissions", 24),
            ("backend_unconfirmed_admissions", 0),
            ("pending_probe_outcomes", 0),
            ("observed_payload_starts", 24),
            ("research_reservations", 0),
            ("replay_engine_invocations", 0),
            ("schema_version", version),
            ("independent_human_security_review", "NOT_PERFORMED"),
            ("external_human_reproduction", "0/0/PENDING"),
        ):
            _fixed(report[field], expected, "recovery report " + field)
        _fixed(
            report["original_qualification_budget"],
            {
                "max_admissions": 24,
                "window_ns": WINDOW_NS,
            },
            "recovery original allowance",
        )
        if (
            type(report["completed_at_monotonic_ns"]) is not int
            or report["completed_at_monotonic_ns"] < self.started_ns
        ):
            raise ValueError("Invalid recovery completion clock")
        manifest_raw, _ = _secure_read(self.artifact_dir / "manifest.json", 262144)
        manifest_value = _json(manifest_raw)
        if not isinstance(manifest_value, dict) or _sha(manifest_raw) != report["manifest_sha256"]:
            raise ValueError("Actual recovery manifest bytes differ")
        manifest = validate_recovery_manifest_shape(manifest_value, version=version)
        for field, expected in (
            ("kind", f"restricted_reference_ec2_recovery_manifest_v{version}"),
            ("schema_version", version),
            ("source_revision", self.source_revision),
            ("provider_context", self.provider_record),
            ("recovery_context", self.recovery_context),
            ("production_m1_enabled", False),
            ("available_for_probe", True),
            ("fixed_cases", list(FIXED_PROBES)),
            ("qualification_started_ns", self.started_ns),
            ("qualification_deadline_ns", self.deadline_ns),
            ("recovery_accounting_phase", "pre_probe_manifest"),
        ):
            _fixed(manifest.get(field), expected, "actual recovery manifest " + field)
        initial = cast(Row, accounting).copy()
        initial.update(
            {
                "current_charged": 0,
                "current_backend_confirmed": 0,
                "current_unconfirmed": 0,
                "current_pending_outcomes": 0,
                "cumulative_charged": version,
                "cumulative_backend_confirmed": version,
            }
        )
        _fixed(manifest.get("recovery_accounting"), initial, "pre-probe recovery accounting")
        ticket_fields = {field.name for field in dataclasses.fields(ProbeAdmission)}
        for index, case_value in enumerate(cast(list[object], report["cases"])):
            case = _mapping(
                case_value,
                {
                    "name",
                    "nonce",
                    "admission_submitted",
                    "admission",
                    "status",
                    "reason",
                    "execution_evidence",
                    "payload_started",
                },
                "successful recovery case",
            )
            admission = self._admissions()[index]
            _fixed(case["reason"], "actual_scoped_control_evidence", "current recovery assessment")
            _fixed(
                case.get("admission"),
                {key: admission[key] for key in ticket_fields},
                "current recovery case ticket",
            )
            _fixed(case.get("nonce"), admission["nonce"], "current recovery case nonce")
            _fixed(case.get("admission_submitted"), True, "current recovery case charge")
            _fixed(case.get("payload_started"), True, "current recovery payload gate")
            path = self.run_dir / f"case-{index + 1:02d}.json"
            raw, _ = _secure_read(path, 2_097_152)
            record = {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}
            _fixed(case.get("execution_evidence"), record, "actual current recovery case bytes")
            outcome = cast(Row, admission["outcome"])
            _fixed(outcome["result_sha256"], _sha(raw), "durable current recovery outcome")
            result_value = _json(raw)
            if not isinstance(result_value, dict):
                raise ValueError("Actual recovery result is not a JSON object")
            result = cast(Row, result_value)
            for field, expected in (
                ("name", FIXED_PROBES[index]),
                ("nonce", admission["nonce"]),
                ("payload_started", True),
                ("stop_confirmed", True),
                ("cleanup_confirmed", True),
                ("failure", outcome["failure"]),
            ):
                _fixed(result.get(field), expected, "actual recovery result " + field)
            facts = result.get("host_facts")
            if not isinstance(facts, dict):
                raise ValueError("Recovery result has no bound host observations")
            for field, expected in (
                ("manifest_sha256", report["manifest_sha256"]),
                ("admission_number", index + 1),
                ("original_admission_ns", admission["admitted_ns"]),
                ("original_deadline_ns", admission["deadline_ns"]),
            ):
                _fixed(facts.get(field), expected, "current recovery host binding " + field)
            _fixed(outcome["stop_confirmed"], True, "durable recovery stop")
            _fixed(outcome["cleanup_confirmed"], True, "durable recovery cleanup")

    def qualification_receipt(self) -> Row:
        """A terminal outcome alone is insufficient: re-read its bound complete report."""
        self._live()
        if (
            self._state["phase"] != "TERMINAL"
            or self._state["outcome"] != "QUALIFIED_REFERENCE_ONLY"
            or self._state["poisoned"] is not False
        ):
            raise ValueError("No complete successful terminal qualification")
        digest = self._state["final_report_sha256"]
        self._check_final_report(cast(str | None, digest))
        return {
            "kind": (
                f"restricted_reference_ec2_recovery_terminal_receipt_v{self._context_version()}"
                if self._recovery_mode
                else "restricted_reference_ec2_terminal_receipt_v1"
            ),
            "schema_version": self._context_version() if self._recovery_mode else 1,
            "run_id": self.run_id,
            "source_revision": self.source_revision,
            "boot_id": self.boot_id,
            "final_report_sha256": digest,
            "controls_status": "QUALIFIED_REFERENCE_ONLY",
            "production_m1": "DISABLED",
            **(
                {
                    "recovery_context": self.recovery_context,
                    "recovery_accounting": self.recovery_accounting(self.snapshot()),
                }
                if self._recovery_mode
                else {}
            ),
        }
