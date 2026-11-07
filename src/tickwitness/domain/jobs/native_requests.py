"""Path-free, bounded native Job input; only the coordinator can publish."""

from typing import cast

from tickwitness.domain.evidence.reduction_records import (
    ReductionExecutionIntent,
    load_reduction_intent,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.jobs.contracts import MAX_JOB_INTEGER, execution_dispatch_nonce
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import load_replay_spec

MAX_NATIVE_JOB_REQUEST_BYTES = 16 * 1024 * 1024
_FIELDS = {
    "kind",
    "schema_version",
    "job_id",
    "coordinator_id",
    "job_attempt_id",
    "lease_token",
    "payload",
}
_PAYLOAD = {
    "research_attempt",
    "intent",
    "dataset_id",
    "normalized",
    "replay_spec",
    "native_deadline_ns",
}
type Row = dict[str, object]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def native_input_document(replay_input: ReplayInput) -> Row:
    """Freeze only engine input, never owner locators or a ledger capability."""
    preflight_replay(replay_input)
    return {
        "dataset_id": replay_input.dataset_id,
        "normalized": replay_input.normalized_bytes.decode("utf-8"),
        "replay_spec": replay_input.spec.document,
    }


def check_native_input_size(replay_input: ReplayInput) -> None:
    # Intent/reservation and all IPC metadata are bounded below this headroom.
    # Reject a predictably oversized encoding before consuming an original slot.
    _require(
        len(canonical(native_input_document(replay_input))) + 64 * 1024
        <= MAX_NATIVE_JOB_REQUEST_BYTES,
        "Frozen native input leaves insufficient bounded IPC headroom",
    )


def load_native_worker_request(
    raw: bytes,
) -> tuple[Row, ReplayInput, AttemptReservation, ReductionExecutionIntent]:
    try:
        request = parse(raw, limit=MAX_NATIVE_JOB_REQUEST_BYTES)
        _require(
            request.keys() == _FIELDS
            and request["kind"] == "job_native_worker_request_v1"
            and type(request["schema_version"]) is int
            and request["schema_version"] == 1,
            "Native Job request fields or version differ",
        )
        for key in ("job_id", "coordinator_id", "job_attempt_id", "lease_token"):
            identity(request[key])
        payload = request["payload"]
        _require(
            isinstance(payload, dict) and payload.keys() == _PAYLOAD,
            "Native Job payload fields differ",
        )
        payload = cast("Row", payload)
        deadline = payload["native_deadline_ns"]
        _require(
            type(deadline) is int and 0 < deadline <= MAX_JOB_INTEGER,
            "Native deadline must be a positive bounded monotonic integer",
        )
        _require(
            isinstance(payload["research_attempt"], dict),
            "Native Job requires its original reservation",
        )
        reservation_raw = canonical(cast("Row", payload["research_attempt"]))
        reservation = AttemptReservation(digest(reservation_raw), reservation_raw)
        _require(
            reservation.document["nonce"]
            == execution_dispatch_nonce(cast("str", request["job_id"])),
            "Native reservation nonce differs from the frozen Job dispatch",
        )
        _require(isinstance(payload["intent"], dict), "Native Job requires its original intent")
        intent = load_reduction_intent(canonical(cast("Row", payload["intent"])))
        _require(
            intent.document["protocol_id"] == reservation.protocol_id,
            "Native intent and original reservation protocol differ",
        )
        _require(
            isinstance(payload["normalized"], str) and isinstance(payload["replay_spec"], dict),
            "Native artifacts must be a normalized string and spec document",
        )
        replay_input = ReplayInput(
            identity(payload["dataset_id"]),
            cast("str", payload["normalized"]).encode("utf-8"),
            load_replay_spec(canonical(cast("Row", payload["replay_spec"]))),
        )
        bindings = cast("Row", intent.document["bindings"])
        _require(
            bindings["prefix_context_id"] == replay_input.dataset_id
            and bindings["normalized_sha256"] == digest(replay_input.normalized_bytes)
            and bindings["replay_spec_id"] == replay_input.spec.spec_id,
            "Native input differs from the exact durable execution intent",
        )
        preflight_replay(replay_input)
        return request, replay_input, reservation, intent
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
        raise EvidenceValidationError("Invalid native Job request: " + str(error)) from error


def build_native_worker_request(
    *,
    job_id: str,
    coordinator_id: str,
    job_attempt_id: str,
    lease_token: str,
    research_attempt: AttemptReservation,
    intent: ReductionExecutionIntent,
    replay_input: ReplayInput,
    native_deadline_ns: int,
) -> bytes:
    raw = canonical(
        {
            "kind": "job_native_worker_request_v1",
            "schema_version": 1,
            "job_id": job_id,
            "coordinator_id": coordinator_id,
            "job_attempt_id": job_attempt_id,
            "lease_token": lease_token,
            "payload": {
                "research_attempt": research_attempt.document,
                "intent": intent.document,
                **native_input_document(replay_input),
                "native_deadline_ns": native_deadline_ns,
            },
        }
    )
    load_native_worker_request(raw)
    return raw
