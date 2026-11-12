"""Operational observations and metadata-only previews, never execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse
from tickwitness.domain.jobs.contracts import MAX_JOB_INTEGER, JobValidationError, load_job_snapshot
from tickwitness.domain.jobs.control import JobControlPolicy, load_job_control_policy

type Row = dict[str, object]

MAX_JOB_RESOURCE_BYTES = 16 * 1024
MAX_COMPUTE_USAGE_BYTES = 511
RESOURCE_METRICS = {
    "coordinator_cpu_ns": ("ns", "coordinator_process", "process_time_ns_delta"),
    "compute_user_cpu_ns": (
        "ns", "terminated_compute_child_os_accounting", "anchor_wait4"
    ),
    "compute_system_cpu_ns": (
        "ns", "terminated_compute_child_os_accounting", "anchor_wait4"
    ),
    "compute_peak_rss_bytes": (
        "bytes", "terminated_compute_child_os_accounting", "anchor_wait4"
    ),
    "scratch_cleanup_logical_bytes": (
        "bytes", "owned_scratch_cleanup_regular_entries", "nofollow_cleanup_stat"
    ),
    "job_elapsed_ns": ("ns", "live_control_window", "monotonic_ns_delta"),
    "research_slots_reserved_count": (
        "count", "this_job_confirmed_new_reservations", "coordinator_reservation_confirmation"
    ),
    "audited_native_results_count": (
        "count", "this_job_new_native_results_audited", "coordinator_native_result_audit"
    ),
    "processed_input_record_count": (
        "count", "this_job_audited_native_result", "coordinator_native_result_audit"
    ),
    "predicate_evaluation_count": ("count", "frozen_research_predicate", "not_instrumented"),
}
RESOURCE_STAGES = (
    "pre_worker_admission", "owned_worker_lifetime", "cleanup", "post_cleanup"
)
_REASONS = {
    "not_recorded", "worker_not_started", "usage_unavailable", "unsupported_platform",
    "cleanup_incomplete", "reservation_unconfirmed", "result_not_audited", "not_instrumented",
    "phase_not_observed", "clock_unavailable",
}
_FIELDS = {
    "kind", "schema_version", "job_id", "job_attempt_id", "policy_id", "catalog_state",
    "catalog_snapshot_sha256", "worker_started", "worker_usage", "collection_status",
    "metrics", "stages",
}
_USAGE_FIELDS = {
    "kind", "schema_version", "anchor_pid", "compute_pid", "platform", "user_cpu_us",
    "system_cpu_us", "maxrss_raw", "maxrss_unit", "compute_wait_status",
}
_WORKER_METRICS = ("compute_user_cpu_ns", "compute_system_cpu_ns", "compute_peak_rss_bytes")
_STATES = {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "LOST"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobValidationError(message)


def _integer(value: object, label: str, low: int = 0, high: int = MAX_JOB_INTEGER) -> int:
    _require(type(value) is int and low <= value <= high, label + " is outside its integer range")
    return cast("int", value)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _identity(value: object) -> str:
    try:
        return identity(value)
    except ValueError as error:
        raise JobValidationError("Resource identity is invalid: " + str(error)) from error


def _parse(raw: bytes, *, limit: int) -> Row:
    try:
        return parse(raw, limit=limit)
    except (ValueError, TypeError) as error:
        raise JobValidationError("Invalid canonical resource record: " + str(error)) from error


def resource_metric(name: str, value: int | None, reason: str | None = None) -> Row:
    """Construct one fixed-unit observation; absence never becomes numeric zero."""
    _require(isinstance(name, str) and name in RESOURCE_METRICS, "Unsupported resource metric")
    unit, scope, source = RESOURCE_METRICS[name]
    if value is None:
        _require(
            isinstance(reason, str) and reason in _REASONS,
            "Unavailable resource metric requires a fixed reason",
        )
    else:
        _integer(value, "Resource metric")
        _require(reason is None, "Measured resource metric has no unavailable reason")
    if name == "predicate_evaluation_count":
        _require(
            value is None and reason == "not_instrumented",
            "Predicate evaluation count is not instrumented",
        )
    return {
        "availability": "unavailable" if value is None else "measured",
        "value": value, "unit": unit, "scope": scope, "source": source, "reason": reason,
    }


def resource_stage(
    name: str, start: int | None, end: int | None, reason: str = "phase_not_observed"
) -> Row:
    """One stage in a single live control clock, without restart reconstruction."""
    _require(name in RESOURCE_STAGES, "Unsupported resource stage")
    if start is not None:
        _integer(start, "Resource stage start")
    if end is not None:
        _integer(end, "Resource stage end")
    if start is None or end is None:
        _require(reason == "phase_not_observed", "Unobserved phase reason differs")
        return {
            "name": name, "availability": "unavailable", "start_offset_ns": None,
            "end_offset_ns": None, "duration_ns": None, "reason": reason,
        }
    _require(start <= end, "Resource stage clock regressed")
    return {
        "name": name, "availability": "measured", "start_offset_ns": start,
        "end_offset_ns": end, "duration_ns": end - start, "reason": None,
    }


def load_job_compute_usage(raw: bytes) -> Row:
    """Validate canonical frame content after the caller checks/strips its newline."""
    row = _exact(_parse(raw, limit=MAX_COMPUTE_USAGE_BYTES), _USAGE_FIELDS, "Compute usage")
    _require(
        row["kind"] == "job_compute_usage_v1"
        and type(row["schema_version"]) is int and row["schema_version"] == 1,
        "Unsupported compute usage document",
    )
    anchor = _integer(row["anchor_pid"], "Anchor PID", 1)
    compute = _integer(row["compute_pid"], "Compute PID", 1)
    _require(anchor != compute, "Anchor and compute identities must differ")
    platform, unit = row["platform"], row["maxrss_unit"]
    _require(
        (platform == "linux" and unit == "KiB") or (platform == "darwin" and unit == "bytes"),
        "Compute usage platform and RSS unit differ",
    )
    for field in ("user_cpu_us", "system_cpu_us"):
        _integer(row[field], field, high=MAX_JOB_INTEGER // 1000)
    _integer(row["maxrss_raw"], "Raw RSS", high=MAX_JOB_INTEGER // (1024 if unit == "KiB" else 1))
    _integer(row["compute_wait_status"], "Compute wait status", -255, 255)
    return row


def _checked_report(raw: bytes) -> Row:
    row = _exact(_parse(raw, limit=MAX_JOB_RESOURCE_BYTES), _FIELDS, "Resource report")
    _require(
        row["kind"] == "job_resource_report_v1"
        and type(row["schema_version"]) is int and row["schema_version"] == 1,
        "Unsupported resource report document",
    )
    _identity(row["job_id"])
    _identity(row["policy_id"])
    if row["job_attempt_id"] is not None:
        _identity(row["job_attempt_id"])
    state, snapshot = row["catalog_state"], row["catalog_snapshot_sha256"]
    if state is None:
        _require(snapshot is None, "Unknown Catalog state cannot certify snapshot bytes")
    else:
        _require(isinstance(state, str) and state in _STATES, "Unsupported resource Catalog state")
        _identity(snapshot)
    _require(type(row["worker_started"]) is bool, "Resource worker flag must be boolean")
    _require(
        row["worker_started"] is False or row["job_attempt_id"] is not None,
        "A started worker requires its observed Job attempt",
    )
    _require(
        isinstance(row["collection_status"], str)
        and row["collection_status"] in {"complete", "partial"},
        "Unsupported collection status",
    )
    metrics = _exact(row["metrics"], set(RESOURCE_METRICS), "Resource metrics")
    values: dict[str, int | None] = {}
    for name in RESOURCE_METRICS:
        metric = _exact(
            metrics[name], {"availability", "value", "unit", "scope", "source", "reason"}, name
        )
        value = metric["value"]
        if value is not None:
            _integer(value, name)
        values[name] = cast("int | None", value)
        rebuilt = resource_metric(name, values[name], cast("str | None", metric["reason"]))
        _require(metric == rebuilt, "Resource metric provenance or availability differs")
    for name in ("research_slots_reserved_count", "audited_native_results_count"):
        if values[name] is not None:
            _integer(values[name], name, high=1)
    audited = values["audited_native_results_count"]
    processed = cast("Row", metrics["processed_input_record_count"])
    if audited == 1:
        _require(values["processed_input_record_count"] is not None, "Audited result lacks records")
    else:
        _require(
            processed
            == resource_metric("processed_input_record_count", None, "result_not_audited"),
            "Processed records require an independently audited new native result",
        )
    usage_raw = row["worker_usage"]
    usage: Row | None = None
    if usage_raw is not None:
        _require(isinstance(usage_raw, dict), "Compute usage must be an object")
        usage = load_job_compute_usage(canonical(cast("Row", usage_raw)))
        _require(row["worker_started"] is True, "Unstarted worker cannot have OS usage")
        expected = (
            cast("int", usage["user_cpu_us"]) * 1000,
            cast("int", usage["system_cpu_us"]) * 1000,
            cast("int", usage["maxrss_raw"]) * (1024 if usage["platform"] == "linux" else 1),
        )
        for name, value in zip(_WORKER_METRICS, expected, strict=True):
            _require(metrics[name] == resource_metric(name, value), "Raw compute usage differs")
    else:
        for name in _WORKER_METRICS:
            metric = cast("Row", metrics[name])
            reasons = (
                {"usage_unavailable", "unsupported_platform", "not_recorded"}
                if row["worker_started"] else {"worker_not_started"}
            )
            _require(
                metric["availability"] == "unavailable"
                and isinstance(metric["reason"], str) and metric["reason"] in reasons,
                "Absent compute usage cannot certify worker measurements",
            )
    stages = row["stages"]
    _require(isinstance(stages, list) and len(stages) == 4, "Resource stages differ")
    for name, value in zip(RESOURCE_STAGES, cast("list[object]", stages), strict=True):
        stage = _exact(
            value,
            {"name", "availability", "start_offset_ns", "end_offset_ns", "duration_ns", "reason"},
            "Resource stage",
        )
        start, end = stage["start_offset_ns"], stage["end_offset_ns"]
        if stage["availability"] == "measured":
            _integer(start, "Stage start")
            _integer(end, "Stage end")
            elapsed = values["job_elapsed_ns"]
            _require(elapsed is not None and cast("int", end) <= elapsed, "Stage exceeds elapsed")
            rebuilt = resource_stage(name, cast("int", start), cast("int", end))
        else:
            rebuilt = resource_stage(name, None, None)
        _require(stage == rebuilt, "Resource stage duration, name or availability differs")
    if row["collection_status"] == "complete":
        _require(
            state in {"SUCCEEDED", "FAILED", "LOST"} and row["job_attempt_id"] is not None,
            "Complete collection requires a terminal observed attempt",
        )
        _require(
            all(values[name] is not None for name in (
                "coordinator_cpu_ns", "job_elapsed_ns", "scratch_cleanup_logical_bytes"
            )) and (row["worker_started"] is False or usage is not None),
            "Complete collection lacks applicable worker, clock or cleanup observations",
        )
    return row


@dataclass(frozen=True, slots=True)
class JobResourceReport:
    report_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _checked_report(self.canonical_bytes)
        _require(
            _identity(self.report_id) == digest(self.canonical_bytes), "Report identity differs"
        )

    @property
    def document(self) -> Row:
        return _checked_report(self.canonical_bytes)


def load_job_resource_report(raw: bytes) -> JobResourceReport:
    _checked_report(raw)
    return JobResourceReport(digest(raw), raw)


def build_job_resource_report(document: Row) -> JobResourceReport:
    try:
        raw = canonical(document)
    except (ValueError, TypeError) as error:
        raise JobValidationError("Cannot encode resource report: " + str(error)) from error
    return load_job_resource_report(raw)


def build_job_resource_preview(snapshot: Row, policy: JobControlPolicy | None) -> Row:
    """Only supplied Catalog/policy metadata; no input locator or budget authority."""
    checked = load_job_snapshot(canonical(snapshot))
    job_id = checked["job_id"]
    limits: object = None
    policy_id: str | None = None
    if policy is not None:
        sealed = load_job_control_policy(policy.canonical_bytes)
        _require(sealed.document["job_id"] == job_id, "Preview policy belongs to another Job")
        policy_id, limits = sealed.policy_id, sealed.document["limits"]
    spec = cast("Row", checked["spec"])
    operation = spec["operation"]
    request = cast("Row", spec["request"])
    readonly = operation == "compare_reduction_run_v1" or (
        operation == "resolve_reduction_job_v1" and request["mode"] == "acknowledge_committed_v1"
    )
    return {
        "kind": "job_resource_preview_v1", "schema_version": 1, "job_id": job_id,
        "operation": operation, "policy_id": policy_id, "configured_limits": limits,
        "estimates": {
            name: {"availability": "unavailable", "value": None, "reason": "not_calibrated"}
            for name in ("cpu_ns", "peak_rss_bytes", "elapsed_ns", "disk_bytes")
        },
        "research_slot_requirement": {
            "availability": "measured" if readonly else "unavailable",
            "value": 0 if readonly else None,
            "reason": "structurally_read_only" if readonly else "conditional_execution",
        },
        "execution_authorized": False,
    }
