"""Family-bound queue execution evidence, separate from baseline claim evidence."""

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
from tickwitness.domain.research_contracts.queue_family import (
    QueueFamilyProtocol,
    load_queue_family_protocol,
)

MAX_QUEUE_RECORD_BYTES = 512 * 1024


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    _require(isinstance(value, dict) and value.keys() == keys, label + " fields differ")
    return cast("dict[str, object]", value)


def _markers(document: dict[str, object], kind: str) -> None:
    _require(document["kind"] == kind, "Unsupported queue record kind")
    _require(
        type(document["schema_version"]) is int and document["schema_version"] == 1,
        "Unsupported queue record version",
    )


@dataclass(frozen=True, slots=True)
class QueueAttemptReservation(AttemptReservation):
    """A queue family slot cannot be reinterpreted as an old replay slot."""

    def __post_init__(self) -> None:
        document = parse(self.canonical_bytes)
        _require(
            document.get("kind") == "queue_attempt_reservation_v1",
            "Unsupported queue attempt reservation",
        )
        # Reuse every existing field/type/time bound without widening its schema.
        legacy = dict(document, kind="replay_attempt_reservation_v1")
        raw = canonical(legacy)
        AttemptReservation(digest(raw), raw)
        _require(
            identity(self.attempt_id) == digest(self.canonical_bytes),
            "Queue reservation identity mismatch",
        )


def _family(value: object) -> QueueFamilyProtocol:
    _require(isinstance(value, dict), "Queue intent requires a complete frozen family")
    try:
        return load_queue_family_protocol(canonical(cast("dict[str, object]", value)))
    except ProtocolValidationError as error:
        raise EvidenceValidationError(f"Invalid queue intent family: {error}") from error


def _validate_intent(raw: bytes) -> dict[str, object]:
    document = _exact(
        parse(raw, limit=MAX_QUEUE_RECORD_BYTES),
        {"kind", "schema_version", "protocol_id", "family", "policy_id"},
        "Queue intent",
    )
    _markers(document, "queue_run_intent_v1")
    family = _family(document["family"])
    _require(identity(document["protocol_id"]) == family.family_id, "Queue family ID mismatch")
    policy = document["policy_id"]
    _require(
        isinstance(policy, str) and policy in cast("list[str]", family.document["policies"]),
        "Queue intent policy is not frozen in its family",
    )
    return document


@dataclass(frozen=True, slots=True)
class QueueRunIntent:
    intent_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_intent(self.canonical_bytes)
        _require(
            identity(self.intent_id) == digest(self.canonical_bytes), "Queue intent ID mismatch"
        )

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=MAX_QUEUE_RECORD_BYTES)

    @property
    def family(self) -> QueueFamilyProtocol:
        return _family(self.document["family"])

    @property
    def policy_id(self) -> str:
        return cast("str", self.document["policy_id"])


def build_queue_intent(family: QueueFamilyProtocol, policy_id: str) -> QueueRunIntent:
    _require(type(family) is QueueFamilyProtocol, "Intent requires a QueueFamilyProtocol")
    rebuilt = _family(family.document)
    _require(
        rebuilt.family_id == family.family_id and rebuilt.canonical_bytes == family.canonical_bytes,
        "Queue family identity does not reproduce",
    )
    raw = canonical(
        {
            "kind": "queue_run_intent_v1",
            "schema_version": 1,
            "protocol_id": rebuilt.family_id,
            "family": rebuilt.document,
            "policy_id": policy_id,
        }
    )
    return QueueRunIntent(digest(raw), raw)


def load_queue_intent(raw: bytes) -> QueueRunIntent:
    return QueueRunIntent(digest(raw), raw)


def _attempt_and_intent(
    document: dict[str, object],
) -> tuple[QueueAttemptReservation, QueueRunIntent]:
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
        "Queue attempt",
    )
    raw = canonical(attempt)
    reservation = QueueAttemptReservation(digest(raw), raw)
    _require(isinstance(document["intent"], dict), "Queue record requires a complete intent")
    intent = load_queue_intent(canonical(cast("dict[str, object]", document["intent"])))
    _require(
        identity(document["protocol_id"]) == reservation.protocol_id
        and document["protocol_id"] == intent.family.family_id,
        "Queue attempt and intent family mismatch",
    )
    budget = cast("dict[str, int]", intent.family.document["budget"])
    _require(
        reservation.attempt_index <= budget["max_attempts"]
        and reservation.document["max_wall_seconds"] == budget["max_wall_seconds"],
        "Queue reservation exceeds its frozen family budget",
    )
    return reservation, intent


def _validate_receipt(raw: bytes) -> dict[str, object]:
    document = _exact(
        parse(raw, limit=MAX_QUEUE_RECORD_BYTES),
        {
            "kind",
            "schema_version",
            "attempt",
            "protocol_id",
            "intent",
            "execution_status",
            "bindings",
        },
        "Queue run receipt",
    )
    _markers(document, "queue_run_receipt_v1")
    _attempt_and_intent(document)
    _require(
        document["execution_status"] in ("completed", "incomplete"),
        "Queue receipts require audited completed or incomplete execution",
    )
    bindings = _exact(
        document["bindings"],
        {"replay_result_sha256", "evaluation_sha256"},
        "Queue receipt bindings",
    )
    for value in bindings.values():
        identity(value)
    return document


@dataclass(frozen=True, slots=True)
class QueueRunReceipt:
    run_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_receipt(self.canonical_bytes)
        _require(identity(self.run_id) == digest(self.canonical_bytes), "Queue receipt ID mismatch")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=MAX_QUEUE_RECORD_BYTES)

    @property
    def intent_id(self) -> str:
        return digest(canonical(cast("dict[str, object]", self.document["intent"])))


def build_queue_run_receipt(document: dict[str, object]) -> QueueRunReceipt:
    raw = canonical(document)
    return QueueRunReceipt(digest(raw), raw)


def load_queue_run_receipt(raw: bytes) -> QueueRunReceipt:
    return QueueRunReceipt(digest(raw), raw)


def load_queue_failure(raw: bytes) -> dict[str, object]:
    document = _exact(
        parse(raw, limit=MAX_QUEUE_RECORD_BYTES),
        {"kind", "schema_version", "attempt", "protocol_id", "intent", "error"},
        "Queue failure",
    )
    _markers(document, "queue_attempt_failure_v1")
    _attempt_and_intent(document)
    details = _exact(document["error"], {"code", "message"}, "Queue failure error")
    for key, maximum in (("code", 128), ("message", 4096)):
        value = details[key]
        _require(
            isinstance(value, str) and 0 < len(value) <= maximum,
            f"Queue failure {key} is empty or oversized",
        )
    return document


def build_queue_failure(
    reservation: AttemptReservation, intent: QueueRunIntent, code: str, message: str
) -> bytes:
    _require(
        type(reservation) is QueueAttemptReservation and type(intent) is QueueRunIntent,
        "Queue failure requires immutable queue reservation and intent",
    )
    raw = canonical(
        {
            "kind": "queue_attempt_failure_v1",
            "schema_version": 1,
            "attempt": reservation.document,
            "protocol_id": reservation.protocol_id,
            "intent": intent.document,
            "error": {"code": code, "message": message},
        }
    )
    load_queue_failure(raw)
    return raw
