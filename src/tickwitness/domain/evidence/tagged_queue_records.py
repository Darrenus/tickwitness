"""Immutable evidence for a new tagged queue claim and shared frozen budget."""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TaggedQueueProtocol,
    load_tagged_queue_protocol,
)

MAX_TAGGED_QUEUE_RECORD_BYTES = 1024 * 1024


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    _require(isinstance(value, dict) and value.keys() == keys, label + " fields differ")
    return cast("dict[str, object]", value)


def _markers(document: dict[str, object], kind: str) -> None:
    _require(document["kind"] == kind, "Unsupported tagged queue record kind")
    _require(
        type(document["schema_version"]) is int and document["schema_version"] == 1,
        "Unsupported tagged queue record version",
    )


@dataclass(frozen=True, slots=True)
class TaggedQueueAttemptReservation(AttemptReservation):
    """A tagged slot cannot be reinterpreted as an old shadow or replay slot."""

    def __post_init__(self) -> None:
        document = parse(self.canonical_bytes)
        _require(
            document.get("kind") == "tagged_queue_attempt_reservation_v1",
            "Unsupported tagged queue attempt reservation",
        )
        legacy = dict(document, kind="replay_attempt_reservation_v1")
        raw = canonical(legacy)
        AttemptReservation(digest(raw), raw)
        _require(
            identity(self.attempt_id) == digest(self.canonical_bytes),
            "Tagged queue reservation identity mismatch",
        )


def _protocol(value: object) -> TaggedQueueProtocol:
    _require(isinstance(value, dict), "Tagged intent requires a complete frozen protocol")
    try:
        return load_tagged_queue_protocol(canonical(cast("dict[str, object]", value)))
    except ProtocolValidationError as error:
        raise EvidenceValidationError(f"Invalid tagged intent protocol: {error}") from error


def _validate_intent(raw: bytes) -> dict[str, object]:
    document = _exact(
        parse(raw, limit=MAX_TAGGED_QUEUE_RECORD_BYTES),
        {"kind", "schema_version", "protocol_id", "claim_revision_id", "protocol", "policy_id"},
        "Tagged queue intent",
    )
    _markers(document, "tagged_queue_run_intent_v1")
    protocol = _protocol(document["protocol"])
    _require(
        identity(document["protocol_id"]) == protocol.protocol_id,
        "Tagged intent protocol ID mismatch",
    )
    _require(
        identity(document["claim_revision_id"]) == protocol.claim_revision_id,
        "Tagged intent claim revision mismatch",
    )
    policy = document["policy_id"]
    _require(
        isinstance(policy, str) and policy in cast("list[str]", protocol.document["policies"]),
        "Tagged intent policy is not frozen in its protocol",
    )
    return document


@dataclass(frozen=True, slots=True)
class TaggedQueueRunIntent:
    intent_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_intent(self.canonical_bytes)
        _require(
            identity(self.intent_id) == digest(self.canonical_bytes), "Tagged intent ID mismatch"
        )

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=MAX_TAGGED_QUEUE_RECORD_BYTES)

    @property
    def protocol(self) -> TaggedQueueProtocol:
        return _protocol(self.document["protocol"])

    @property
    def policy_id(self) -> str:
        return cast("str", self.document["policy_id"])


def build_tagged_queue_intent(
    protocol: TaggedQueueProtocol, policy_id: str
) -> TaggedQueueRunIntent:
    _require(type(protocol) is TaggedQueueProtocol, "Intent requires an actual TaggedQueueProtocol")
    rebuilt = _protocol(protocol.document)
    _require(
        rebuilt.protocol_id == protocol.protocol_id
        and rebuilt.canonical_bytes == protocol.canonical_bytes,
        "Tagged protocol identity does not reproduce",
    )
    raw = canonical(
        {
            "kind": "tagged_queue_run_intent_v1",
            "schema_version": 1,
            "protocol_id": rebuilt.protocol_id,
            "claim_revision_id": rebuilt.claim_revision_id,
            "protocol": rebuilt.document,
            "policy_id": policy_id,
        }
    )
    return TaggedQueueRunIntent(digest(raw), raw)


def load_tagged_queue_intent(raw: bytes) -> TaggedQueueRunIntent:
    return TaggedQueueRunIntent(digest(raw), raw)


def _attempt_and_intent(
    document: dict[str, object],
) -> tuple[TaggedQueueAttemptReservation, TaggedQueueRunIntent]:
    attempt = _exact(
        document["attempt"],
        {
            "kind",
            "schema_version",
            "protocol_id",
            "attempt_index",
            "nonce",
            "max_wall_seconds",
            "created_at_utc",
        },
        "Tagged attempt",
    )
    raw = canonical(attempt)
    reservation = TaggedQueueAttemptReservation(digest(raw), raw)
    _require(isinstance(document["intent"], dict), "Tagged outcome requires a complete intent")
    intent = load_tagged_queue_intent(canonical(cast("dict[str, object]", document["intent"])))
    protocol = intent.protocol
    _require(
        identity(document["protocol_id"]) == reservation.protocol_id == protocol.protocol_id,
        "Tagged attempt and intent protocol mismatch",
    )
    _require(
        identity(document["claim_revision_id"]) == protocol.claim_revision_id,
        "Tagged outcome claim revision mismatch",
    )
    budget = cast("dict[str, int]", protocol.document["budget"])
    _require(
        reservation.attempt_index <= budget["max_attempts"]
        and reservation.document["max_wall_seconds"] == budget["max_wall_seconds"],
        "Tagged reservation exceeds its frozen shared budget",
    )
    return reservation, intent


def _validate_receipt(raw: bytes) -> dict[str, object]:
    document = _exact(
        parse(raw, limit=MAX_TAGGED_QUEUE_RECORD_BYTES),
        {
            "kind",
            "schema_version",
            "attempt",
            "protocol_id",
            "claim_revision_id",
            "intent",
            "execution_status",
            "bindings",
        },
        "Tagged run receipt",
    )
    _markers(document, "tagged_queue_run_receipt_v1")
    _attempt_and_intent(document)
    _require(
        document["execution_status"] == "completed",
        "Tagged receipts require audited completed execution",
    )
    bindings = _exact(
        document["bindings"],
        {"replay_result_sha256", "evaluation_sha256"},
        "Tagged receipt bindings",
    )
    for value in bindings.values():
        identity(value)
    return document


@dataclass(frozen=True, slots=True)
class TaggedQueueRunReceipt:
    run_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_receipt(self.canonical_bytes)
        _require(
            identity(self.run_id) == digest(self.canonical_bytes), "Tagged receipt ID mismatch"
        )

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=MAX_TAGGED_QUEUE_RECORD_BYTES)

    @property
    def intent_id(self) -> str:
        return digest(canonical(cast("dict[str, object]", self.document["intent"])))


def build_tagged_queue_run_receipt(document: dict[str, object]) -> TaggedQueueRunReceipt:
    raw = canonical(document)
    return TaggedQueueRunReceipt(digest(raw), raw)


def load_tagged_queue_run_receipt(raw: bytes) -> TaggedQueueRunReceipt:
    return TaggedQueueRunReceipt(digest(raw), raw)


def load_tagged_queue_failure(raw: bytes) -> dict[str, object]:
    document = _exact(
        parse(raw, limit=MAX_TAGGED_QUEUE_RECORD_BYTES),
        {
            "kind",
            "schema_version",
            "attempt",
            "protocol_id",
            "claim_revision_id",
            "intent",
            "error",
        },
        "Tagged failure",
    )
    _markers(document, "tagged_queue_attempt_failure_v1")
    _attempt_and_intent(document)
    details = _exact(document["error"], {"code", "message"}, "Tagged failure error")
    for key, maximum in (("code", 128), ("message", 4096)):
        value = details[key]
        _require(
            isinstance(value, str) and 0 < len(value) <= maximum,
            f"Tagged failure {key} is empty or oversized",
        )
    return document


def build_tagged_queue_failure(
    reservation: AttemptReservation, intent: TaggedQueueRunIntent, code: str, message: str
) -> bytes:
    _require(
        type(reservation) is TaggedQueueAttemptReservation and type(intent) is TaggedQueueRunIntent,
        "Tagged failure requires immutable tagged reservation and intent",
    )
    raw = canonical(
        {
            "kind": "tagged_queue_attempt_failure_v1",
            "schema_version": 1,
            "attempt": reservation.document,
            "protocol_id": reservation.protocol_id,
            "claim_revision_id": intent.protocol.claim_revision_id,
            "intent": intent.document,
            "error": {"code": code, "message": message},
        }
    )
    load_tagged_queue_failure(raw)
    return raw
