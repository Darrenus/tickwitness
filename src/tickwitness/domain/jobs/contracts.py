"""One-attempt managed jobs, independent of research attempt budgets.

Times are supplied by the trusted coordinator. Query liveness labels never
mutate a stored snapshot or certify progress, clock authenticity or recovery.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.reduction_comparison import load_reduction_comparison_export
from tickwitness.domain.evidence.reduction_records import (
    MAX_REDUCTION_RECORD_BYTES,
    load_reduction_failure,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse

MAX_JOB_SPEC_BYTES = 64 * 1024
MAX_JOB_SNAPSHOT_BYTES = 128 * 1024
MIN_JOB_LEASE_NS = 1_000_000_000
MAX_JOB_LEASE_NS = 60_000_000_000
MAX_JOB_INTEGER = (1 << 63) - 1
MAX_FOLLOWUP_ANCESTRY = 32
MAX_FOLLOWUP_RESULT_BYTES = MAX_REDUCTION_RECORD_BYTES + 64 * 1024
_REQUEST_FIELDS = {
    "run_id",
    "expected_bundle_id",
    "expected_report_id",
    "input_root",
    "runs",
    "source_evidence",
    "split",
}
_EXECUTION_REQUEST_FIELDS = {
    "preparation",
    "expected_preparation_id",
    "expected_bundle_id",
    "expected_report_id",
    "input_root",
    "source_evidence",
    "runs",
    "split",
    "engine_runtime",
    "restart_mode",
}
_FOLLOWUP_REQUEST_FIELDS = {"origin_spec", "parent_job_id", "mode", "idempotency_key"}
_FOLLOWUP_RESULT_FIELDS = {
    "kind",
    "schema_version",
    "job_id",
    "origin_job_id",
    "parent_job_id",
    "action",
    "dispatch_job_id",
    "outcome",
}
_SPEC_FIELDS = {"kind", "schema_version", "operation", "request", "lease_duration_ns"}
_SNAPSHOT_FIELDS = {
    "kind",
    "schema_version",
    "job_id",
    "spec",
    "state",
    "version",
    "created_at_ns",
    "updated_at_ns",
    "attempt",
    "result_sha256",
    "failure",
}
_ATTEMPT_FIELDS = {
    "job_attempt_id",
    "attempt_number",
    "nonce",
    "coordinator_id",
    "lease_token",
    "heartbeat_sequence",
    "heartbeat_at_ns",
    "lease_expires_at_ns",
}
_STATES = {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "LOST"}
_LOST_REASONS = {"coordinator_lost", "lease_expired"}
type Row = dict[str, object]


class JobValidationError(ValueError):
    """A job declaration, snapshot or transition contradicts its frozen contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobValidationError(message)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _integer(value: object, label: str, low: int = 0, high: int = MAX_JOB_INTEGER) -> int:
    _require(type(value) is int and low <= value <= high, label + " is outside its integer range")
    return cast("int", value)


def _markers(row: Row, kind: str) -> None:
    _require(row["kind"] == kind, "Unsupported job document kind")
    _integer(row["schema_version"], "schema_version", 1, 1)


def _path(value: object, *, relative: bool) -> str:
    _require(
        isinstance(value, str) and 0 < len(value) <= 4096 and "\x00" not in value,
        "Job locator must be a bounded nonempty POSIX path",
    )
    path = cast("str", value)
    if relative:
        _require(
            not path.startswith("/")
            and "\\" not in path
            and not any(part in (".", "..") for part in path.split("/")),
            "Job source evidence must be relative without dot or dotdot segments",
        )
    else:
        _require(path.startswith("/"), "Job root locators must be absolute POSIX paths")
    return path


def _request(value: object) -> Row:
    request = _exact(value, _REQUEST_FIELDS, "Job request")
    _require(request["split"] == "development", "Jobs permit development evidence only")
    for name in ("run_id", "expected_bundle_id", "expected_report_id"):
        identity(request[name])
    for name in ("input_root", "runs"):
        _path(request[name], relative=False)
    _path(request["source_evidence"], relative=True)
    return request


def _execution_request(value: object) -> Row:
    request = _exact(value, _EXECUTION_REQUEST_FIELDS, "Execution job request")
    _require(request["split"] == "development", "Jobs permit development evidence only")
    _require(
        request["engine_runtime"] == "coordinator_interpreter_v1",
        "Execution jobs require the frozen coordinator interpreter policy",
    )
    _require(
        request["restart_mode"] == "frozen_origin_new_attempt_only_v1",
        "Execution jobs cannot authorize checkpoint resume or same-attempt replay",
    )
    for name in ("expected_preparation_id", "expected_bundle_id", "expected_report_id"):
        identity(request[name])
    for name in ("preparation", "input_root", "runs"):
        _path(request[name], relative=False)
    _path(request["source_evidence"], relative=True)
    return request


def _followup_request(value: object) -> tuple[Row, JobSpec]:
    request = _exact(value, _FOLLOWUP_REQUEST_FIELDS, "Followup job request")
    origin = request["origin_spec"]
    _require(
        isinstance(origin, dict) and origin.get("kind") == "reduction_execution_job_spec_v1",
        "Followup origin must be an original native spec, never a recursive followup",
    )
    checked_origin = load_job_spec(canonical(cast("Row", origin)))
    identity(request["parent_job_id"])
    mode = request["mode"]
    _require(
        isinstance(mode, str) and mode in {"retry_from_origin_v1", "acknowledge_committed_v1"},
        "Unsupported explicit followup mode",
    )
    key = request["idempotency_key"]
    _require(
        isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key) is not None,
        "Followup key requires 1..128 ASCII identifier characters, starting alphanumeric",
    )
    return request, checked_origin


def _spec_document(raw: bytes) -> Row:
    row = _exact(parse(raw, limit=MAX_JOB_SPEC_BYTES), _SPEC_FIELDS, "Job spec")
    if row["kind"] == "comparison_job_spec_v1":
        _markers(row, "comparison_job_spec_v1")
        _require(
            row["operation"] == "compare_reduction_run_v1", "Unsupported managed job operation"
        )
        _request(row["request"])
    elif row["kind"] == "reduction_execution_job_spec_v1":
        _markers(row, "reduction_execution_job_spec_v1")
        _require(
            row["operation"] == "execute_reduction_input_v1", "Unsupported managed job operation"
        )
        _execution_request(row["request"])
    else:
        _markers(row, "reduction_followup_job_spec_v1")
        _require(
            row["operation"] == "resolve_reduction_job_v1", "Unsupported managed job operation"
        )
        _request_row, origin = _followup_request(row["request"])
        _require(
            row["lease_duration_ns"] == origin.document["lease_duration_ns"],
            "Followup lease must equal the frozen original lease",
        )
    _integer(row["lease_duration_ns"], "lease_duration_ns", MIN_JOB_LEASE_NS, MAX_JOB_LEASE_NS)
    return row


@dataclass(frozen=True, slots=True)
class JobSpec:
    spec_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _spec_document(self.canonical_bytes)
            _require(
                identity(self.spec_id) == digest(self.canonical_bytes), "Job spec identity differs"
            )
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise JobValidationError("Cannot load job spec: " + str(error)) from error

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_JOB_SPEC_BYTES)


def build_job_spec(request: Row, *, lease_duration_ns: int = 30_000_000_000) -> JobSpec:
    try:
        checked = _request(request)
        lease = _integer(lease_duration_ns, "lease_duration_ns", MIN_JOB_LEASE_NS, MAX_JOB_LEASE_NS)
        raw = canonical(
            {
                "kind": "comparison_job_spec_v1",
                "schema_version": 1,
                "operation": "compare_reduction_run_v1",
                "request": checked,
                "lease_duration_ns": lease,
            }
        )
        return load_job_spec(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot build job spec: " + str(error)) from error


def build_execution_job_spec(request: Row, *, lease_duration_ns: int = 30_000_000_000) -> JobSpec:
    """Freeze a native operation; actual research authority remains coordinator-owned."""
    try:
        checked = _execution_request(request)
        lease = _integer(lease_duration_ns, "lease_duration_ns", MIN_JOB_LEASE_NS, MAX_JOB_LEASE_NS)
        return load_job_spec(
            canonical(
                {
                    "kind": "reduction_execution_job_spec_v1",
                    "schema_version": 1,
                    "operation": "execute_reduction_input_v1",
                    "request": checked,
                    "lease_duration_ns": lease,
                }
            )
        )
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot build execution job spec: " + str(error)) from error


def build_followup_job_spec(
    origin_spec: JobSpec, parent_job_id: str, mode: str, idempotency_key: str
) -> JobSpec:
    """Freeze an explicit resolution request, without changing the parent's terminal state."""
    try:
        _require(type(origin_spec) is JobSpec, "Followup requires an actual original JobSpec")
        origin = load_job_spec(origin_spec.canonical_bytes)
        request, checked_origin = _followup_request(
            {
                "origin_spec": origin.document,
                "parent_job_id": parent_job_id,
                "mode": mode,
                "idempotency_key": idempotency_key,
            }
        )
        return load_job_spec(
            canonical(
                {
                    "kind": "reduction_followup_job_spec_v1",
                    "schema_version": 1,
                    "operation": "resolve_reduction_job_v1",
                    "request": request,
                    "lease_duration_ns": checked_origin.document["lease_duration_ns"],
                }
            )
        )
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot build followup job spec: " + str(error)) from error


def load_job_spec(raw: bytes) -> JobSpec:
    try:
        _spec_document(raw)
        return JobSpec(digest(raw), raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot load job spec: " + str(error)) from error


def execution_origin_spec(spec: JobSpec) -> JobSpec:
    """Return the one original native descriptor; locators/pins cannot drift along a chain."""
    checked = load_job_spec(spec.canonical_bytes)
    operation = checked.document["operation"]
    if operation == "execute_reduction_input_v1":
        return checked
    _require(operation == "resolve_reduction_job_v1", "Operation has no native execution origin")
    request = cast("Row", checked.document["request"])
    return load_job_spec(canonical(cast("Row", request["origin_spec"])))


def validate_followup_context(spec: JobSpec, lookup: Callable[[str], Row]) -> tuple[Row, ...]:
    """Check a bounded same-Catalog ancestry, without changing state or trusting a receipt.

    Lookup IO failures retain their own classification. Sibling admission and
    the shared original-ledger journal/lock are separate transactional checks.
    """
    checked = load_job_spec(spec.canonical_bytes)
    _require(
        checked.document["operation"] == "resolve_reduction_job_v1",
        "Ancestry validation requires an explicit followup Job",
    )
    origin = execution_origin_spec(checked)
    request = cast("Row", checked.document["request"])
    current = identity(request["parent_job_id"])
    visited = {checked.spec_id}
    reverse: list[Row] = []
    while True:
        _require(current not in visited, "Followup ancestry is cyclic or aliases the child")
        _require(len(reverse) < MAX_FOLLOWUP_ANCESTRY, "Followup ancestry exceeds its bound")
        visited.add(current)
        row = load_job_snapshot(canonical(lookup(current)))
        _require(row["job_id"] == current, "Followup lookup returned another parent Job")
        _require(
            row["state"] in {"FAILED", "LOST", "SUCCEEDED"},
            "Followup parents must be durably terminal; reconcile orphan ownership explicitly",
        )
        parent = load_job_spec(canonical(cast("Row", row["spec"])))
        reverse.append(row)
        if current == origin.spec_id:
            _require(
                parent.canonical_bytes == origin.canonical_bytes,
                "Followup root differs from the exact original native descriptor",
            )
            break
        _require(
            parent.document["operation"] == "resolve_reduction_job_v1",
            "Followup chain does not reach its exact original root",
        )
        parent_request = cast("Row", parent.document["request"])
        _require(
            parent_request["mode"] == "retry_from_origin_v1",
            "An acknowledgment-only Job cannot become a native followup parent",
        )
        _require(
            execution_origin_spec(parent).canonical_bytes == origin.canonical_bytes,
            "Followup ancestor belongs to another frozen original descriptor",
        )
        current = identity(parent_request["parent_job_id"])
    if request["mode"] == "retry_from_origin_v1":
        _require(
            len(reverse) < MAX_FOLLOWUP_ANCESTRY,
            "Retry would exceed the bounded original dispatch chain",
        )
    return tuple(reversed(reverse))


def execution_dispatch_nonce(job_id: str) -> str:
    """Derive the original ledger's nonce before any reservation can be consumed."""
    return digest(
        canonical({"kind": "reduction_job_dispatch_nonce_v1", "job_id": identity(job_id)})
    )[:32]


def job_dispatch_nonce(spec: JobSpec) -> str:
    """Return a native Job's immutable association, never replay authorization."""
    checked = load_job_spec(spec.canonical_bytes)
    operation = checked.document["operation"]
    _require(
        operation == "execute_reduction_input_v1"
        or (
            operation == "resolve_reduction_job_v1"
            and cast("Row", checked.document["request"])["mode"] == "retry_from_origin_v1"
        ),
        "Only native execution Jobs have an original research dispatch nonce",
    )
    return execution_dispatch_nonce(checked.spec_id)


def _checked_dispatch_outcome(origin: JobSpec, dispatch_job_id: str, raw: bytes) -> Row:
    document = parse(raw, limit=MAX_REDUCTION_RECORD_BYTES)
    if document.get("kind") == "reduction_run_receipt_v1":
        document = load_reduction_run_receipt(raw).document
    else:
        document = load_reduction_failure(raw)
    request = cast("Row", origin.document["request"])
    intent = cast("Row", document["intent"])
    bindings = cast("Row", intent["bindings"])
    _require(
        bindings["source_bundle_id"] == request["expected_bundle_id"]
        and bindings["source_report_id"] == request["expected_report_id"]
        and bindings["preparation_id"] == request["expected_preparation_id"],
        "Followup outcome does not bind its exact frozen origin pins",
    )
    _require(
        cast("Row", document["attempt"])["nonce"] == execution_dispatch_nonce(dispatch_job_id),
        "Followup outcome belongs to another actual original dispatch nonce",
    )
    return document


def _check_followup_result(spec: JobSpec, raw: bytes) -> str:
    document = _exact(
        parse(raw, limit=MAX_FOLLOWUP_RESULT_BYTES), _FOLLOWUP_RESULT_FIELDS, "Followup result"
    )
    _markers(document, "reduction_job_resolution_v1")
    request = cast("Row", spec.document["request"])
    origin = execution_origin_spec(spec)
    _require(
        document["job_id"] == spec.spec_id
        and document["origin_job_id"] == origin.spec_id
        and document["parent_job_id"] == request["parent_job_id"],
        "Followup result does not bind its Job, original root and parent",
    )
    dispatch_job_id = identity(document["dispatch_job_id"])
    action = document["action"]
    _require(
        isinstance(action, str) and action in {"replayed_from_origin", "acknowledged_committed"},
        "Unsupported actual followup action",
    )
    _require(isinstance(document["outcome"], dict), "Followup requires the exact original outcome")
    outcome = _checked_dispatch_outcome(
        origin, dispatch_job_id, canonical(cast("Row", document["outcome"]))
    )
    if action == "replayed_from_origin":
        _require(
            request["mode"] == "retry_from_origin_v1"
            and dispatch_job_id == spec.spec_id
            and outcome["kind"] == "reduction_run_receipt_v1",
            "Replayed followup requires a current retry dispatch and audited result receipt",
        )
    return digest(raw)


def build_followup_result(
    spec: JobSpec, dispatch_spec: JobSpec, outcome_raw: bytes, action: str
) -> bytes:
    """Bind a checked original outcome to the actual resolution action, without executing."""
    checked = load_job_spec(spec.canonical_bytes)
    _require(
        checked.document["operation"] == "resolve_reduction_job_v1",
        "Resolution result requires a followup descriptor",
    )
    origin = execution_origin_spec(checked)
    dispatch = load_job_spec(dispatch_spec.canonical_bytes)
    _require(
        execution_origin_spec(dispatch).canonical_bytes == origin.canonical_bytes,
        "Resolution dispatch belongs to another frozen original descriptor",
    )
    job_dispatch_nonce(dispatch)
    outcome = _checked_dispatch_outcome(origin, dispatch.spec_id, outcome_raw)
    request = cast("Row", checked.document["request"])
    raw = canonical(
        {
            "kind": "reduction_job_resolution_v1",
            "schema_version": 1,
            "job_id": checked.spec_id,
            "origin_job_id": origin.spec_id,
            "parent_job_id": request["parent_job_id"],
            "action": action,
            "dispatch_job_id": dispatch.spec_id,
            "outcome": outcome,
        }
    )
    _check_followup_result(checked, raw)
    return raw


def check_job_result(spec: JobSpec, raw: bytes) -> str:
    """Check exact frozen pins; independent source/result reaudit occurs before publication."""
    checked = load_job_spec(spec.canonical_bytes)
    request = cast("Row", checked.document["request"])
    if checked.document["operation"] == "compare_reduction_run_v1":
        _, report = load_reduction_comparison_export(raw)
        bindings = cast("Row", report["bindings"])
        source, reduced = cast("Row", bindings["source"]), cast("Row", bindings["reduced"])
        _require(
            source["bundle_id"] == request["expected_bundle_id"]
            and source["report_id"] == request["expected_report_id"]
            and reduced["run_id"] == request["run_id"],
            "Job result does not bind its original request pins",
        )
    elif checked.document["operation"] == "resolve_reduction_job_v1":
        return _check_followup_result(checked, raw)
    else:
        receipt = load_reduction_run_receipt(raw)
        document = receipt.document
        intent = cast("Row", document["intent"])
        bindings = cast("Row", intent["bindings"])
        _require(
            bindings["source_bundle_id"] == request["expected_bundle_id"]
            and bindings["source_report_id"] == request["expected_report_id"]
            and bindings["preparation_id"] == request["expected_preparation_id"],
            "Native Job result does not bind its original request pins",
        )
        _require(
            cast("Row", document["attempt"])["nonce"] == job_dispatch_nonce(checked),
            "Native Job result belongs to another original research dispatch nonce",
        )
    return digest(raw)


def _attempt_id(job_id: str, nonce: str) -> str:
    return digest(canonical({"job_id": job_id, "attempt_number": 1, "nonce": nonce}))


def _addition(left: int, right: int, label: str) -> int:
    _require(left <= MAX_JOB_INTEGER - right, label + " overflows the supported integer range")
    return left + right


def _failure(value: object) -> Row:
    failure = _exact(value, {"code", "message", "worker_exit_code"}, "Job failure")
    code, message = failure["code"], failure["message"]
    _require(
        isinstance(code, str) and 0 < len(code) <= 128, "Job failure code is empty or oversized"
    )
    _require(isinstance(message, str) and len(message) <= 2048, "Job failure message is oversized")
    if failure["worker_exit_code"] is not None:
        _integer(failure["worker_exit_code"], "worker_exit_code", -255, 255)
    return failure


def _validated_snapshot(raw: bytes) -> Row:
    row = _exact(parse(raw, limit=MAX_JOB_SNAPSHOT_BYTES), _SNAPSHOT_FIELDS, "Job snapshot")
    _markers(row, "job_snapshot_v1")
    job_id = identity(row["job_id"])
    _require(isinstance(row["spec"], dict), "Job snapshot requires its full frozen spec")
    spec = load_job_spec(canonical(cast("Row", row["spec"])))
    _require(job_id == spec.spec_id, "Job snapshot belongs to another spec")
    state = row["state"]
    _require(isinstance(state, str) and state in _STATES, "Unsupported stored job state")
    version = _integer(row["version"], "version", 1)
    created = _integer(row["created_at_ns"], "created_at_ns")
    updated = _integer(row["updated_at_ns"], "updated_at_ns")
    _require(created <= updated, "Job time moved backwards before its creation")
    if state == "QUEUED":
        _require(
            version == 1
            and updated == created
            and row["attempt"] is None
            and row["result_sha256"] is None
            and row["failure"] is None,
            "Queued job cannot contain execution or terminal facts",
        )
        return row
    attempt = _exact(row["attempt"], _ATTEMPT_FIELDS, "Job attempt")
    for name in ("job_attempt_id", "nonce", "coordinator_id", "lease_token"):
        identity(attempt[name])
    _integer(attempt["attempt_number"], "attempt_number", 1, 1)
    _require(
        attempt["job_attempt_id"] == _attempt_id(job_id, cast("str", attempt["nonce"])),
        "Job attempt identity differs from its job and nonce",
    )
    sequence = _integer(attempt["heartbeat_sequence"], "heartbeat_sequence")
    heartbeat_at = _integer(attempt["heartbeat_at_ns"], "heartbeat_at_ns")
    expiry = _integer(attempt["lease_expires_at_ns"], "lease_expires_at_ns")
    lease = cast("int", spec.document["lease_duration_ns"])
    _require(
        created <= heartbeat_at <= updated
        and expiry == _addition(heartbeat_at, lease, "Heartbeat lease"),
        "Job heartbeat and lease timestamps contradict its frozen duration",
    )
    expected_version = _addition(sequence, 2 if state == "RUNNING" else 3, "Job version")
    _require(
        version == expected_version, "Job version contradicts its one-attempt heartbeat history"
    )
    if state == "RUNNING":
        _require(
            updated == heartbeat_at and row["result_sha256"] is None and row["failure"] is None,
            "Running job cannot contain terminal facts",
        )
    elif state == "SUCCEEDED":
        identity(row["result_sha256"])
        _require(row["failure"] is None, "Succeeded job cannot contain a failure")
        _require(updated < expiry, "Job completed after its heartbeat lease expired")
    else:
        _require(
            row["result_sha256"] is None, "Failed or lost job cannot contain a successful result"
        )
        failure = _failure(row["failure"])
        if state == "FAILED":
            _require(updated < expiry, "Job failed after its heartbeat lease expired")
        else:
            _require(
                failure["code"] in _LOST_REASONS and failure["worker_exit_code"] is None,
                "Lost job must identify lost ownership or an expired lease",
            )
            if failure["code"] == "lease_expired":
                _require(updated >= expiry, "Lease-expired loss predates the recorded expiry")
    return row


def load_job_snapshot(raw: bytes) -> Row:
    try:
        return _validated_snapshot(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot load job snapshot: " + str(error)) from error


def _copy(row: Row) -> Row:
    _require(isinstance(row, dict), "Job transition requires a complete snapshot")
    return load_job_snapshot(canonical(row))


def _now(row: Row, now_ns: int) -> int:
    now = _integer(now_ns, "now_ns")
    _require(now >= cast("int", row["updated_at_ns"]), "Job coordinator clock moved backwards")
    return now


def _changed(row: Row, now_ns: int) -> Row:
    row["version"] = _addition(cast("int", row["version"]), 1, "Job version")
    row["updated_at_ns"] = now_ns
    return load_job_snapshot(canonical(row))


def queued_job(spec: JobSpec, *, now_ns: int) -> Row:
    try:
        _require(type(spec) is JobSpec, "Queued job requires a frozen JobSpec")
        checked = load_job_spec(spec.canonical_bytes)
        _require(checked.spec_id == spec.spec_id, "Queued job spec identity differs")
        now = _integer(now_ns, "now_ns")
        return load_job_snapshot(
            canonical(
                {
                    "kind": "job_snapshot_v1",
                    "schema_version": 1,
                    "job_id": checked.spec_id,
                    "spec": checked.document,
                    "state": "QUEUED",
                    "version": 1,
                    "created_at_ns": now,
                    "updated_at_ns": now,
                    "attempt": None,
                    "result_sha256": None,
                    "failure": None,
                }
            )
        )
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot queue job: " + str(error)) from error


def claim_job(
    row: Row, *, coordinator_id: str, attempt_nonce: str, lease_token: str, now_ns: int
) -> Row:
    try:
        output = _copy(row)
        _require(output["state"] == "QUEUED", "Only a queued job can be claimed once")
        now = _now(output, now_ns)
        for value in (coordinator_id, attempt_nonce, lease_token):
            identity(value)
        lease = cast("int", cast("Row", output["spec"])["lease_duration_ns"])
        output["attempt"] = {
            "job_attempt_id": _attempt_id(cast("str", output["job_id"]), attempt_nonce),
            "attempt_number": 1,
            "nonce": attempt_nonce,
            "coordinator_id": coordinator_id,
            "lease_token": lease_token,
            "heartbeat_sequence": 0,
            "heartbeat_at_ns": now,
            "lease_expires_at_ns": _addition(now, lease, "Claim lease"),
        }
        output["state"] = "RUNNING"
        return _changed(output, now)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot claim job: " + str(error)) from error


def _active(
    row: Row, *, coordinator_id: str, job_attempt_id: str, lease_token: str, now_ns: int
) -> tuple[Row, Row, int]:
    output = _copy(row)
    _require(output["state"] == "RUNNING", "Only a running job accepts worker messages")
    now = _now(output, now_ns)
    attempt = cast("Row", output["attempt"])
    for name, value in (
        ("coordinator_id", coordinator_id),
        ("job_attempt_id", job_attempt_id),
        ("lease_token", lease_token),
    ):
        identity(value)
        _require(attempt[name] == value, "Worker message credentials differ: " + name)
    _require(now < cast("int", attempt["lease_expires_at_ns"]), "Job heartbeat lease has expired")
    return output, attempt, now


def assert_active_job(
    row: Row, *, coordinator_id: str, job_attempt_id: str, lease_token: str, now_ns: int
) -> Row:
    """Check current mutation authority without advancing a version or lease."""
    try:
        output, _attempt, _now_ns = _active(
            row,
            coordinator_id=coordinator_id,
            job_attempt_id=job_attempt_id,
            lease_token=lease_token,
            now_ns=now_ns,
        )
        return output
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot admit active job operation: " + str(error)) from error


def heartbeat_job(
    row: Row,
    *,
    coordinator_id: str,
    job_attempt_id: str,
    lease_token: str,
    sequence: int,
    now_ns: int,
) -> Row:
    try:
        output, attempt, now = _active(
            row,
            coordinator_id=coordinator_id,
            job_attempt_id=job_attempt_id,
            lease_token=lease_token,
            now_ns=now_ns,
        )
        actual = _integer(sequence, "heartbeat sequence", 1)
        expected = _addition(cast("int", attempt["heartbeat_sequence"]), 1, "Heartbeat sequence")
        _require(actual == expected, "Heartbeat sequence must be exactly the next sequence")
        lease = cast("int", cast("Row", output["spec"])["lease_duration_ns"])
        attempt["heartbeat_sequence"] = actual
        attempt["heartbeat_at_ns"] = now
        attempt["lease_expires_at_ns"] = _addition(now, lease, "Heartbeat lease")
        return _changed(output, now)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot accept job heartbeat: " + str(error)) from error


def finish_job(
    row: Row,
    *,
    coordinator_id: str,
    job_attempt_id: str,
    lease_token: str,
    result_sha256: str | None,
    failure: Row | None,
    now_ns: int,
) -> Row:
    try:
        output, _attempt, now = _active(
            row,
            coordinator_id=coordinator_id,
            job_attempt_id=job_attempt_id,
            lease_token=lease_token,
            now_ns=now_ns,
        )
        if result_sha256 is not None and failure is None:
            identity(result_sha256)
            output["state"] = "SUCCEEDED"
            output["result_sha256"] = result_sha256
        else:
            _require(
                result_sha256 is None and failure is not None,
                "Job needs exactly one terminal outcome",
            )
            output["failure"] = _failure(failure)
            output["state"] = "FAILED"
        return _changed(output, now)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot finish job: " + str(error)) from error


def lose_job(row: Row, *, reason: str, now_ns: int) -> Row:
    try:
        output = _copy(row)
        _require(output["state"] == "RUNNING", "Only a running job can become lost")
        _require(isinstance(reason, str) and reason in _LOST_REASONS, "Unsupported job loss reason")
        now = _now(output, now_ns)
        attempt = cast("Row", output["attempt"])
        if reason == "lease_expired":
            _require(
                now >= cast("int", attempt["lease_expires_at_ns"]), "Job lease has not expired"
            )
        output["state"] = "LOST"
        output["failure"] = {
            "code": reason,
            "message": (
                "Coordinator ownership was lost"
                if reason == "coordinator_lost"
                else "Heartbeat lease expired"
            ),
            "worker_exit_code": None,
        }
        return _changed(output, now)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot mark job lost: " + str(error)) from error


def effective_state(row: Row, *, now_ns: int, coordinator_active: bool) -> str:
    try:
        checked = _copy(row)
        now = _integer(now_ns, "now_ns")
        _require(
            type(coordinator_active) is bool, "Coordinator activity must be a boolean observation"
        )
        state = cast("str", checked["state"])
        if state != "RUNNING":
            return state
        if not coordinator_active:
            return "COORDINATOR_LOST"
        if now < cast("int", checked["updated_at_ns"]):
            return "CLOCK_UNCERTAIN"
        if now >= cast("int", cast("Row", checked["attempt"])["lease_expires_at_ns"]):
            return "LEASE_EXPIRED"
        return "RUNNING"
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot inspect job state: " + str(error)) from error
