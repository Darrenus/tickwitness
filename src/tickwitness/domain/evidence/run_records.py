"""Immutable reservation and execution receipts; these are not statistical trial families."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Never, cast


class EvidenceValidationError(ValueError):
    """Evidence identities, encoding or execution bindings do not agree."""


def canonical(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise EvidenceValidationError("Receipt must contain finite valid JSON") from error


def digest(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise EvidenceValidationError("Content identity requires immutable bytes")
    return hashlib.sha256(raw).hexdigest()


def identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EvidenceValidationError("Identity must be a lowercase SHA-256 digest")
    return value


def _reject(_value: str) -> Never:
    raise EvidenceValidationError("Receipt JSON cannot contain floats or non-finite values")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceValidationError("Duplicate receipt field")
        result[key] = value
    return result


def parse(raw: bytes, *, limit: int = 16_384) -> dict[str, object]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
        raise EvidenceValidationError("Receipt exceeds its immutable byte limit")
    try:
        value: object = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_float=_reject,
            parse_constant=_reject,
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise EvidenceValidationError("Invalid receipt JSON") from error
    if not isinstance(value, dict) or canonical(value) != raw:
        raise EvidenceValidationError("Receipt must be a canonical JSON object")
    return cast("dict[str, object]", value)


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise EvidenceValidationError("Receipt integer is outside its supported range")
    return value


@dataclass(frozen=True, slots=True)
class AttemptReservation:
    attempt_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        value = parse(self.canonical_bytes)
        if set(value) != {
            "kind",
            "schema_version",
            "protocol_id",
            "attempt_index",
            "nonce",
            "max_wall_seconds",
            "created_at_utc",
        }:
            raise EvidenceValidationError("Reservation fields do not match schema")
        if (
            value["kind"] != "replay_attempt_reservation_v1"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise EvidenceValidationError("Unsupported attempt reservation")
        identity(value["protocol_id"])
        _integer(value["attempt_index"], 1, 100)
        _integer(value["max_wall_seconds"], 1, 60)
        if (
            not isinstance(value["nonce"], str)
            or re.fullmatch(r"[0-9a-f]{32}", value["nonce"]) is None
        ):
            raise EvidenceValidationError("Reservation nonce must contain 16 random bytes")
        if (
            not isinstance(value["created_at_utc"], str)
            or re.fullmatch(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00", value["created_at_utc"]
            )
            is None
        ):
            raise EvidenceValidationError("Reservation requires an explicit UTC timestamp")
        try:
            datetime.fromisoformat(value["created_at_utc"])
        except ValueError as error:
            raise EvidenceValidationError("Reservation UTC timestamp is invalid") from error
        if digest(self.canonical_bytes) != identity(self.attempt_id):
            raise EvidenceValidationError("Reservation identity mismatch")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes)

    @property
    def protocol_id(self) -> str:
        return cast("str", self.document["protocol_id"])

    @property
    def attempt_index(self) -> int:
        return cast("int", self.document["attempt_index"])


@dataclass(frozen=True, slots=True)
class RunReceipt:
    run_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        value = parse(self.canonical_bytes)
        if set(value) != {
            "kind",
            "schema_version",
            "attempt",
            "protocol_id",
            "claim_revision_id",
            "execution_status",
            "scope",
            "bindings",
        }:
            raise EvidenceValidationError("Run receipt fields do not match schema")
        if (
            value["kind"] != "research_run_receipt_v1"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise EvidenceValidationError("Unsupported run receipt")
        attempt = value["attempt"]
        if not isinstance(attempt, dict):
            raise EvidenceValidationError("Run requires a reservation")
        reservation_bytes = canonical(attempt)
        reservation = AttemptReservation(digest(reservation_bytes), reservation_bytes)
        if reservation.protocol_id != identity(value["protocol_id"]):
            raise EvidenceValidationError("Attempt belongs to a different protocol")
        identity(value["claim_revision_id"])
        if value["execution_status"] not in ("completed", "incomplete"):
            raise EvidenceValidationError("Only audited run results can have a run receipt")
        if canonical(cast("dict[str, object]", value["scope"])) != canonical(
            {"phase": "development", "scenario_id": "baseline_v1", "search_performed": False}
        ):
            raise EvidenceValidationError("Unsupported research scope")
        bindings = value["bindings"]
        if not isinstance(bindings, dict) or set(bindings) != {
            "dataset_id",
            "data_sha256",
            "replay_spec_id",
            "replay_result_sha256",
            "evaluation_sha256",
        }:
            raise EvidenceValidationError("Run bindings do not match schema")
        for item in bindings.values():
            identity(item)
        if identity(self.run_id) != digest(self.canonical_bytes):
            raise EvidenceValidationError("Run receipt identity mismatch")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes)


def build_run_receipt(document: dict[str, object]) -> RunReceipt:
    data = canonical(document)
    return RunReceipt(digest(data), data)


def load_run_receipt(data: bytes) -> RunReceipt:
    return RunReceipt(digest(data), data)
