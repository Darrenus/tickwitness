"""One-attempt managed audit jobs, independent of research attempt budgets.

Times are supplied by the trusted coordinator. Query liveness labels never
mutate a stored snapshot or certify progress, clock authenticity or recovery.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse

MAX_JOB_SPEC_BYTES = 64 * 1024
MAX_JOB_SNAPSHOT_BYTES = 128 * 1024
MIN_JOB_LEASE_NS = 1_000_000_000
MAX_JOB_LEASE_NS = 60_000_000_000
MAX_JOB_INTEGER = (1 << 63) - 1
_REQUEST_FIELDS = {
    "run_id", "expected_bundle_id", "expected_report_id", "input_root", "runs",
    "source_evidence", "split",
}
_SPEC_FIELDS = {"kind", "schema_version", "operation", "request", "lease_duration_ns"}
_SNAPSHOT_FIELDS = {
    "kind", "schema_version", "job_id", "spec", "state", "version", "created_at_ns",
    "updated_at_ns", "attempt", "result_sha256", "failure",
}
_ATTEMPT_FIELDS = {
    "job_attempt_id", "attempt_number", "nonce", "coordinator_id", "lease_token",
    "heartbeat_sequence", "heartbeat_at_ns", "lease_expires_at_ns",
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
            not path.startswith("/") and "\\" not in path
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


def _spec_document(raw: bytes) -> Row:
    row = _exact(parse(raw, limit=MAX_JOB_SPEC_BYTES), _SPEC_FIELDS, "Job spec")
    _markers(row, "comparison_job_spec_v1")
    _require(row["operation"] == "compare_reduction_run_v1", "Unsupported managed job operation")
    _request(row["request"])
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
        lease = _integer(
            lease_duration_ns, "lease_duration_ns", MIN_JOB_LEASE_NS, MAX_JOB_LEASE_NS
        )
        raw = canonical(
            {
                "kind": "comparison_job_spec_v1", "schema_version": 1,
                "operation": "compare_reduction_run_v1", "request": checked,
                "lease_duration_ns": lease,
            }
        )
        return load_job_spec(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot build job spec: " + str(error)) from error


def load_job_spec(raw: bytes) -> JobSpec:
    try:
        _spec_document(raw)
        return JobSpec(digest(raw), raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise JobValidationError("Cannot load job spec: " + str(error)) from error


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
            version == 1 and updated == created and row["attempt"] is None
            and row["result_sha256"] is None and row["failure"] is None,
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
        return load_job_snapshot(canonical(
            {
                "kind": "job_snapshot_v1", "schema_version": 1, "job_id": checked.spec_id,
                "spec": checked.document, "state": "QUEUED", "version": 1,
                "created_at_ns": now, "updated_at_ns": now, "attempt": None,
                "result_sha256": None, "failure": None,
            }
        ))
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
            "attempt_number": 1, "nonce": attempt_nonce, "coordinator_id": coordinator_id,
            "lease_token": lease_token, "heartbeat_sequence": 0, "heartbeat_at_ns": now,
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
        ("coordinator_id", coordinator_id), ("job_attempt_id", job_attempt_id),
        ("lease_token", lease_token),
    ):
        identity(value)
        _require(attempt[name] == value, "Worker message credentials differ: " + name)
    _require(now < cast("int", attempt["lease_expires_at_ns"]), "Job heartbeat lease has expired")
    return output, attempt, now


def heartbeat_job(
    row: Row, *, coordinator_id: str, job_attempt_id: str, lease_token: str,
    sequence: int, now_ns: int,
) -> Row:
    try:
        output, attempt, now = _active(
            row, coordinator_id=coordinator_id, job_attempt_id=job_attempt_id,
            lease_token=lease_token, now_ns=now_ns,
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
    row: Row, *, coordinator_id: str, job_attempt_id: str, lease_token: str,
    result_sha256: str | None, failure: Row | None, now_ns: int,
) -> Row:
    try:
        output, _attempt, now = _active(
            row, coordinator_id=coordinator_id, job_attempt_id=job_attempt_id,
            lease_token=lease_token, now_ns=now_ns,
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
                if reason == "coordinator_lost" else "Heartbeat lease expired"
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
