"""Immutable opt-in Job controls, independent of research and Catalog schemas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse
from tickwitness.domain.jobs.contracts import MAX_JOB_INTEGER, JobValidationError

type Row = dict[str, object]

MAX_JOB_CONTROL_BYTES = 16 * 1024
_POLICY_FIELDS = {"kind", "schema_version", "job_id", "limits"}
_LIMIT_BOUNDS = {
    "max_wall_ns": (1_000_000_000, 3_600_000_000_000),
    "worker_cpu_seconds": (1, 3600),
    "max_file_bytes": (1024, 1024 * 1024 * 1024),
    "max_open_files": (32, 4096),
    "cleanup_grace_ns": (100_000_000, 5_000_000_000),
}
_CANCEL_FIELDS = {
    "kind",
    "schema_version",
    "job_id",
    "policy_id",
    "idempotency_key",
    "requested_at_ns",
}
_ADMISSION_FIELDS = {
    "kind",
    "schema_version",
    "job_id",
    "policy_id",
    "job_attempt_id",
    "admitted_at_ns",
}
_RESULT_FIELDS = {
    "kind",
    "schema_version",
    "job_id",
    "policy_id",
    "job_attempt_id",
    "cause",
    "catalog_state",
    "catalog_snapshot_sha256",
    "publication_admitted",
    "worker_started",
    "worker_exit_code",
    "worker_group_absent",
    "workspace_removed",
    "cleanup_confirmed",
    "stop_confirmed",
    "timing_ns",
    "diagnostic",
}
_CAUSES = {
    "finished",
    "job_cancelled",
    "job_deadline_exceeded",
    "job_resource_limit",
    "job_control_error",
    "coordinator_interrupted",
}
_STATES = {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "LOST"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobValidationError(message)


def _integer(value: object, label: str, low: int = 0, high: int = MAX_JOB_INTEGER) -> int:
    _require(type(value) is int and low <= value <= high, label + " is outside its integer range")
    return cast("int", value)


def _identity(value: object) -> str:
    try:
        return identity(value)
    except ValueError as error:
        raise JobValidationError("Job control identity is invalid: " + str(error)) from error


def _document(raw: bytes, fields: set[str], kind: str) -> Row:
    try:
        row = parse(raw, limit=MAX_JOB_CONTROL_BYTES)
        _require(row.keys() == fields, "Job control document fields differ")
        _require(
            row["kind"] == kind
            and type(row["schema_version"]) is int
            and row["schema_version"] == 1,
            "Unsupported Job control document",
        )
        _identity(row["job_id"])
        return row
    except (ValueError, TypeError, KeyError) as error:
        if isinstance(error, JobValidationError):
            raise
        raise JobValidationError("Cannot load Job control document: " + str(error)) from error


def _policy_document(raw: bytes) -> Row:
    row = _document(raw, _POLICY_FIELDS, "job_control_policy_v1")
    limits = row["limits"]
    _require(
        isinstance(limits, dict) and limits.keys() == _LIMIT_BOUNDS.keys(), "Policy limits differ"
    )
    for name, (low, high) in _LIMIT_BOUNDS.items():
        _integer(cast("Row", limits)[name], name, low, high)
    return row


@dataclass(frozen=True, slots=True)
class JobControlPolicy:
    policy_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _policy_document(self.canonical_bytes)
        try:
            _require(
                identity(self.policy_id) == digest(self.canonical_bytes),
                "Control policy identity differs",
            )
        except ValueError as error:
            if isinstance(error, JobValidationError):
                raise
            raise JobValidationError("Cannot identify Job control policy: " + str(error)) from error

    @property
    def document(self) -> Row:
        return _policy_document(self.canonical_bytes)


def build_job_control_policy(
    job_id: str,
    *,
    max_wall_ns: int = 120_000_000_000,
    worker_cpu_seconds: int = 60,
    max_file_bytes: int = 8_388_608,
    max_open_files: int = 128,
    cleanup_grace_ns: int = 5_000_000_000,
) -> JobControlPolicy:
    raw = canonical(
        {
            "kind": "job_control_policy_v1",
            "schema_version": 1,
            "job_id": job_id,
            "limits": {
                "max_wall_ns": max_wall_ns,
                "worker_cpu_seconds": worker_cpu_seconds,
                "max_file_bytes": max_file_bytes,
                "max_open_files": max_open_files,
                "cleanup_grace_ns": cleanup_grace_ns,
            },
        }
    )
    return load_job_control_policy(raw)


def load_job_control_policy(raw: bytes) -> JobControlPolicy:
    _policy_document(raw)
    return JobControlPolicy(digest(raw), raw)


def control_key(value: object) -> str:
    _require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is not None,
        "Cancellation key requires 1..128 ASCII identifier characters, starting alphanumeric",
    )
    return cast("str", value)


def load_job_cancel_request(raw: bytes) -> Row:
    row = _document(raw, _CANCEL_FIELDS, "job_cancel_request_v1")
    _identity(row["policy_id"])
    control_key(row["idempotency_key"])
    _integer(row["requested_at_ns"], "Cancellation UTC time")
    return row


def build_job_cancel_request(policy: JobControlPolicy, *, key: str, now_ns: int) -> Row:
    checked = load_job_control_policy(policy.canonical_bytes)
    return load_job_cancel_request(
        canonical(
            {
                "kind": "job_cancel_request_v1",
                "schema_version": 1,
                "job_id": checked.document["job_id"],
                "policy_id": checked.policy_id,
                "idempotency_key": key,
                "requested_at_ns": now_ns,
            }
        )
    )


def load_job_publication_admission(raw: bytes) -> Row:
    row = _document(raw, _ADMISSION_FIELDS, "job_publication_admission_v1")
    _identity(row["policy_id"])
    _identity(row["job_attempt_id"])
    _integer(row["admitted_at_ns"], "Publication admission UTC time")
    return row


def build_job_publication_admission(
    policy: JobControlPolicy, job_attempt_id: str, *, now_ns: int
) -> Row:
    checked = load_job_control_policy(policy.canonical_bytes)
    return load_job_publication_admission(
        canonical(
            {
                "kind": "job_publication_admission_v1",
                "schema_version": 1,
                "job_id": checked.document["job_id"],
                "policy_id": checked.policy_id,
                "job_attempt_id": job_attempt_id,
                "admitted_at_ns": now_ns,
            }
        )
    )


def load_job_control_result(raw: bytes) -> Row:
    row = _document(raw, _RESULT_FIELDS, "job_control_result_v1")
    _identity(row["policy_id"])
    if row["job_attempt_id"] is not None:
        _identity(row["job_attempt_id"])
    state, snapshot_sha = row["catalog_state"], row["catalog_snapshot_sha256"]
    if state is None:
        _require(snapshot_sha is None, "An unknown Catalog state cannot certify snapshot bytes")
    else:
        _require(isinstance(state, str) and state in _STATES, "Unsupported actual Catalog state")
        _identity(snapshot_sha)
    _require(
        isinstance(row["cause"], str) and row["cause"] in _CAUSES,
        "Unsupported control result cause",
    )
    for name in (
        "publication_admitted",
        "worker_started",
        "worker_group_absent",
        "workspace_removed",
        "cleanup_confirmed",
        "stop_confirmed",
    ):
        _require(type(row[name]) is bool, "Control result flags must be booleans")
    exit_code = row["worker_exit_code"]
    if exit_code is not None:
        _integer(exit_code, "Actual worker exit", -255, 255)
    _require(
        row["worker_started"] is True or exit_code is None,
        "A never-started worker has no exit code",
    )
    if row["cleanup_confirmed"]:
        _require(
            row["worker_group_absent"] is True and row["workspace_removed"] is True,
            "Confirmed cleanup requires absent group and removed workspace",
        )
    if row["stop_confirmed"]:
        _require(
            row["cause"] in {"job_cancelled", "job_deadline_exceeded", "job_resource_limit"}
            and row["catalog_state"] != "SUCCEEDED"
            and row["cleanup_confirmed"] is True
            and row["worker_group_absent"] is True
            and row["workspace_removed"] is True
            and (row["worker_started"] is False or exit_code is not None),
            "Confirmed stop requires actual worker exit and confirmed cleanup",
        )
    _require(
        row["cause"] != "job_cancelled" or row["publication_admitted"] is False,
        "Accepted cancellation cannot follow publication admission",
    )
    timing = row["timing_ns"]
    _require(
        isinstance(timing, dict)
        and timing.keys() == {"elapsed", "request_observed", "worker_reaped", "cleanup_finished"},
        "Control timing fields differ",
    )
    timings = cast("Row", timing)
    elapsed = _integer(timings["elapsed"], "Control elapsed time")
    for name in ("request_observed", "worker_reaped", "cleanup_finished"):
        if timings[name] is not None:
            _integer(timings[name], "Control elapsed offset", 0, elapsed)
    if timings["worker_reaped"] is not None and timings["cleanup_finished"] is not None:
        _require(
            cast("int", timings["worker_reaped"]) <= cast("int", timings["cleanup_finished"]),
            "Cleanup cannot precede actual worker reap",
        )
    diagnostic = row["diagnostic"]
    _require(
        isinstance(diagnostic, str) and len(diagnostic) <= 2048,
        "Control diagnostic is oversized",
    )
    return row


def build_job_control_result(document: Row) -> Row:
    return load_job_control_result(canonical(document))
