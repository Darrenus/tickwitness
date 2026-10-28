"""Frozen one-time observation release and stable, owner-declared origin coverage.

These values grant no engine execution or finding authority. Origin identities
are scoped to trusted source labels, not authenticated acquisition history.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.protocols import (
    ProtocolValidationError,
    _canonical,
    _digest,
    _hash,
    _integer,
    _object,
    _parse,
    _text,
    load_frozen_protocol,
)

MAX_CONFIRMATION_PROTOCOL_BYTES = 3 * 1024 * 1024
MAX_ORIGIN_FOOTPRINT_BYTES = 2 * 1024 * 1024
MAX_CONFIRMATION_EXPOSURE_BYTES = 3 * 1024 * 1024
EXPOSURE_POLICY = "irreversible_origin_overlap_before_release_v1"
IDENTITY_POLICY = "source_instrument_session_trade_id_or_closed_book_interval_v1"
SCOPE: dict[str, object] = {
    "observation_release_only": True,
    "engine_execution_authorized": False,
    "source_claim_evaluated": False,
    "confirmation_finding_issued": False,
    "historical_unseen_certified": False,
    "author_signature_verified": False,
}
_REQUEST_FIELDS = frozenset({"kind", "schema_version", "title", "max_events"})
_PROTOCOL_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "title",
        "source_protocol",
        "bindings",
        "origin_footprint",
        "read_policy",
        "scope",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "source_protocol_id",
        "source_claim_revision_id",
        "development_dataset_id",
        "confirmation_dataset_id",
        "confirmation_normalized_sha256",
        "confirmation_event_count",
        "origin_footprint_id",
    }
)
_EXPOSURE_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "state",
        "confirmation_protocol_id",
        "source_protocol_id",
        "confirmation_dataset_id",
        "confirmation_normalized_sha256",
        "origin_footprint_id",
        "origin_footprint",
        "policy",
    }
)
type Row = dict[str, object]
type Stream = tuple[str, str, str]


class ConfirmationValidationError(ProtocolValidationError):
    """A confirmation declaration or exposure violates its bounded contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfirmationValidationError(message)


def _bounded(document: Row, maximum: int, label: str) -> bytes:
    raw = _canonical(document)
    _require(len(raw) <= maximum, label + " exceeds its byte limit")
    return raw


def _strict(raw: bytes, fields: frozenset[str], maximum: int, label: str) -> Row:
    document = _object(_parse(raw, max_bytes=maximum), fields, label)
    _require(_canonical(document) == raw, label + " must use exact canonical JSON")
    return document


def _source(raw: bytes) -> tuple[str, str, Row]:
    document = _parse(raw, max_bytes=128 * 1024)
    if document.get("kind") == "frozen_research_protocol_v1":
        value = load_frozen_protocol(raw)
        return value.protocol_id, value.claim_revision_id, value.document
    value2 = load_executable_protocol(raw)
    return value2.protocol_id, value2.claim_revision_id, value2.document


def _intervals(values: list[tuple[int, int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for first, last in sorted(values):
        if merged and first <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    return merged


def _footprint_document(raw: bytes) -> Row:
    document = _strict(
        raw,
        frozenset({"kind", "schema_version", "identity_policy", "streams"}),
        MAX_ORIGIN_FOOTPRINT_BYTES,
        "Origin footprint",
    )
    _require(document["kind"] == "confirmation_origin_footprint_v1", "Unsupported origin footprint")
    _integer(document["schema_version"], "schema_version", 1, 1)
    _require(document["identity_policy"] == IDENTITY_POLICY, "Unsupported origin identity policy")
    streams = document["streams"]
    _require(type(streams) is list and 1 <= len(streams) <= 1000, "Invalid origin stream inventory")
    rebuilt: list[Row] = []
    keys: list[Stream] = []
    atoms = 0
    for item in cast("list[object]", streams):
        row = _object(
            item,
            frozenset({"source", "instrument", "session", "trade_ids", "book_intervals"}),
            "Origin stream",
        )
        key = tuple(_text(row[name], name, 256) for name in ("source", "instrument", "session"))
        keys.append(cast("Stream", key))
        trades = row["trade_ids"]
        _require(type(trades) is list and len(trades) <= 1000, "Invalid origin trade inventory")
        trade_ids = [_text(value, "trade_id", 256) for value in cast("list[object]", trades)]
        _require(trade_ids == sorted(set(trade_ids)), "Origin trade IDs must be sorted and unique")
        books = row["book_intervals"]
        _require(type(books) is list and len(books) <= 1000, "Invalid origin book inventory")
        intervals: list[tuple[int, int]] = []
        for value in cast("list[object]", books):
            _require(
                type(value) is list and len(value) == 2, "Book origin must be a closed interval"
            )
            pair = cast("list[object]", value)
            first = _integer(pair[0], "first_sequence", 0, (1 << 63) - 1)
            last = _integer(pair[1], "last_sequence", first, (1 << 63) - 1)
            intervals.append((first, last))
        _require(bool(trade_ids or intervals), "Origin stream cannot be empty")
        atoms += len(trade_ids) + len(intervals)
        rebuilt.append(
            {
                "source": key[0],
                "instrument": key[1],
                "session": key[2],
                "trade_ids": trade_ids,
                "book_intervals": _intervals(intervals),
            }
        )
    _require(atoms <= 1000, "Origin footprint exceeds its event profile")
    _require(keys == sorted(set(keys)), "Origin streams must be sorted and unique")
    expected: Row = {
        "kind": "confirmation_origin_footprint_v1",
        "schema_version": 1,
        "identity_policy": IDENTITY_POLICY,
        "streams": rebuilt,
    }
    _require(_canonical(expected) == raw, "Origin footprint intervals are not canonical coverage")
    return expected


@dataclass(frozen=True, slots=True)
class OriginFootprint:
    footprint_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _footprint_document(self.canonical_bytes)
            _require(
                _hash(self.footprint_id, "footprint_id") == _digest(self.canonical_bytes),
                "Origin footprint identity differs",
            )
        except ValueError as error:
            raise ConfirmationValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return _parse(self.canonical_bytes, max_bytes=MAX_ORIGIN_FOOTPRINT_BYTES)


def load_origin_footprint(raw: bytes) -> OriginFootprint:
    try:
        _footprint_document(raw)
        return OriginFootprint(_digest(raw), raw)
    except ValueError as error:
        raise ConfirmationValidationError(str(error)) from error


def origin_footprint(records: tuple[Row, ...]) -> OriginFootprint:
    try:
        _require(
            type(records) is tuple and 1 <= len(records) <= 1000,
            "Origin records must contain 1 to 1000 events",
        )
        raw = b"".join(_canonical(row) + b"\n" for row in records)
        validated = normalize_events(raw)
        _require(
            validated.report["quality_status"] == "accepted",
            "Origin records must be accepted observations",
        )
        streams: dict[Stream, tuple[set[str], list[tuple[int, int]]]] = {}
        for row in records:
            key = cast(
                "Stream",
                tuple(cast("str", row[name]) for name in ("source", "instrument", "session")),
            )
            trades, books = streams.setdefault(key, (set(), []))
            if row["type"] == "trade":
                trades.add(cast("str", row["trade_id"]))
            else:
                last = cast("int", row["last_sequence"])
                books.append(
                    (cast("int", row["first_sequence"]) if row["type"] == "delta" else last, last)
                )
        document: Row = {
            "kind": "confirmation_origin_footprint_v1",
            "schema_version": 1,
            "identity_policy": IDENTITY_POLICY,
            "streams": [
                {
                    "source": key[0],
                    "instrument": key[1],
                    "session": key[2],
                    "trade_ids": sorted(trades),
                    "book_intervals": _intervals(books),
                }
                for key, (trades, books) in sorted(streams.items())
            ],
        }
        return load_origin_footprint(
            _bounded(document, MAX_ORIGIN_FOOTPRINT_BYTES, "Origin footprint")
        )
    except (ValueError, TypeError, KeyError) as error:
        raise ConfirmationValidationError(str(error)) from error


def footprints_overlap(left: OriginFootprint, right: OriginFootprint) -> bool:
    first = load_origin_footprint(left.canonical_bytes)
    second = load_origin_footprint(right.canonical_bytes)
    _require(
        first.footprint_id == left.footprint_id and second.footprint_id == right.footprint_id,
        "Origin footprint identity differs",
    )
    streams = {
        tuple(row[name] for name in ("source", "instrument", "session")): row
        for row in cast("list[Row]", first.document["streams"])
    }
    for row in cast("list[Row]", second.document["streams"]):
        other = streams.get(tuple(row[name] for name in ("source", "instrument", "session")))
        if other is None:
            continue
        if set(cast("list[str]", row["trade_ids"])) & set(cast("list[str]", other["trade_ids"])):
            return True
        left_books = cast("list[list[int]]", row["book_intervals"])
        right_books = cast("list[list[int]]", other["book_intervals"])
        left_index = right_index = 0
        while left_index < len(left_books) and right_index < len(right_books):
            low, high = left_books[left_index]
            other_low, other_high = right_books[right_index]
            if low <= other_high and other_low <= high:
                return True
            if high < other_high:
                left_index += 1
            else:
                right_index += 1
    return False


def _request(raw: bytes) -> Row:
    request = _object(_parse(raw, max_bytes=64 * 1024), _REQUEST_FIELDS, "Confirmation request")
    _require(request["kind"] == "confirmation_request_v1", "Unsupported confirmation request")
    _integer(request["schema_version"], "schema_version", 1, 1)
    return {
        "kind": "confirmation_request_v1",
        "schema_version": 1,
        "title": _text(request["title"], "title", 200),
        "max_events": _integer(request["max_events"], "max_events", 1, 1000),
    }


def _protocol_document(
    request: Row, source: bytes, normalized_hash: str, count: int, footprint: OriginFootprint
) -> Row:
    source_id, claim_id, document = _source(source)
    datasets = cast("dict[str, str]", document["datasets"])
    maximum = cast("int", request["max_events"])
    _integer(
        count,
        "confirmation_event_count",
        1,
        min(maximum, cast("int", cast("Row", document["budget"])["max_events"])),
    )
    return {
        "kind": "confirmation_protocol_v1",
        "schema_version": 1,
        "title": request["title"],
        "source_protocol": document,
        "bindings": {
            "source_protocol_id": source_id,
            "source_claim_revision_id": claim_id,
            "development_dataset_id": datasets["development"],
            "confirmation_dataset_id": datasets["confirmation"],
            "confirmation_normalized_sha256": _hash(
                normalized_hash, "confirmation_normalized_sha256"
            ),
            "confirmation_event_count": count,
            "origin_footprint_id": footprint.footprint_id,
        },
        "origin_footprint": footprint.document,
        "read_policy": {
            "id": "single_full_window_open_v1",
            "max_events": maximum,
            "exposure_policy": EXPOSURE_POLICY,
        },
        "scope": dict(SCOPE),
    }


def _validated_protocol(raw: bytes) -> Row:
    document = _strict(
        raw, _PROTOCOL_FIELDS, MAX_CONFIRMATION_PROTOCOL_BYTES, "Confirmation protocol"
    )
    bindings = _object(document["bindings"], _BINDING_FIELDS, "Confirmation bindings")
    policy = _object(
        document["read_policy"],
        frozenset({"id", "max_events", "exposure_policy"}),
        "Confirmation read policy",
    )
    request = _request(
        _canonical(
            {
                "kind": "confirmation_request_v1",
                "schema_version": 1,
                "title": document["title"],
                "max_events": policy["max_events"],
            }
        )
    )
    footprint = load_origin_footprint(_canonical(cast("Row", document["origin_footprint"])))
    expected = _protocol_document(
        request,
        _canonical(cast("Row", document["source_protocol"])),
        cast("str", bindings["confirmation_normalized_sha256"]),
        cast("int", bindings["confirmation_event_count"]),
        footprint,
    )
    _require(_canonical(expected) == raw, "Confirmation policies, bindings or encoding differ")
    return expected


@dataclass(frozen=True, slots=True)
class ConfirmationProtocol:
    protocol_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated_protocol(self.canonical_bytes)
            _require(
                _hash(self.protocol_id, "protocol_id") == _digest(self.canonical_bytes),
                "Confirmation protocol identity differs",
            )
        except (ValueError, TypeError, KeyError) as error:
            raise ConfirmationValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return _parse(self.canonical_bytes, max_bytes=MAX_CONFIRMATION_PROTOCOL_BYTES)


def load_confirmation_protocol(raw: bytes) -> ConfirmationProtocol:
    try:
        _validated_protocol(raw)
        return ConfirmationProtocol(_digest(raw), raw)
    except (ValueError, TypeError, KeyError) as error:
        raise ConfirmationValidationError(str(error)) from error


def build_confirmation_protocol(
    request: bytes, *, source_protocol: bytes, confirmation_normalized: bytes
) -> ConfirmationProtocol:
    try:
        declaration = _request(request)
        validated = normalize_events(confirmation_normalized)
        _require(
            validated.normalized_bytes == confirmation_normalized
            and validated.report["quality_status"] == "accepted",
            "Confirmation data must be accepted canonical normalized events",
        )
        records = tuple(_parse(line) for line in confirmation_normalized.splitlines())
        footprint = origin_footprint(records)
        document = _protocol_document(
            declaration, source_protocol, _digest(confirmation_normalized), len(records), footprint
        )
        return load_confirmation_protocol(
            _bounded(document, MAX_CONFIRMATION_PROTOCOL_BYTES, "Confirmation protocol")
        )
    except (ValueError, TypeError, KeyError) as error:
        raise ConfirmationValidationError(str(error)) from error


def _validated_exposure(raw: bytes) -> Row:
    document = _strict(
        raw, _EXPOSURE_FIELDS, MAX_CONFIRMATION_EXPOSURE_BYTES, "Confirmation exposure"
    )
    _require(
        document["kind"] == "confirmation_exposure_v1" and document["state"] == "EXPOSED",
        "Unsupported confirmation exposure",
    )
    _integer(document["schema_version"], "schema_version", 1, 1)
    _require(document["policy"] == EXPOSURE_POLICY, "Exposure consumption policy differs")
    for name in (
        "confirmation_protocol_id",
        "source_protocol_id",
        "confirmation_dataset_id",
        "confirmation_normalized_sha256",
        "origin_footprint_id",
    ):
        _hash(document[name], name)
    footprint = load_origin_footprint(_canonical(cast("Row", document["origin_footprint"])))
    _require(
        footprint.footprint_id == document["origin_footprint_id"],
        "Exposure origin footprint binding differs",
    )
    return document


@dataclass(frozen=True, slots=True)
class ConfirmationExposure:
    exposure_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated_exposure(self.canonical_bytes)
            _require(
                _hash(self.exposure_id, "exposure_id") == _digest(self.canonical_bytes),
                "Exposure identity differs",
            )
        except (ValueError, TypeError, KeyError) as error:
            raise ConfirmationValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return _parse(self.canonical_bytes, max_bytes=MAX_CONFIRMATION_EXPOSURE_BYTES)


def load_confirmation_exposure(raw: bytes) -> ConfirmationExposure:
    try:
        _validated_exposure(raw)
        return ConfirmationExposure(_digest(raw), raw)
    except (ValueError, TypeError, KeyError) as error:
        raise ConfirmationValidationError(str(error)) from error


def build_confirmation_exposure(protocol: ConfirmationProtocol) -> ConfirmationExposure:
    checked = load_confirmation_protocol(protocol.canonical_bytes)
    _require(checked.protocol_id == protocol.protocol_id, "Exposure protocol identity differs")
    document = checked.document
    bindings = cast("Row", document["bindings"])
    exposure: Row = {
        "kind": "confirmation_exposure_v1",
        "schema_version": 1,
        "state": "EXPOSED",
        "confirmation_protocol_id": protocol.protocol_id,
        "origin_footprint": document["origin_footprint"],
        "policy": EXPOSURE_POLICY,
    }
    for name in (
        "source_protocol_id",
        "confirmation_dataset_id",
        "confirmation_normalized_sha256",
        "origin_footprint_id",
    ):
        exposure[name] = bindings[name]
    return load_confirmation_exposure(
        _bounded(exposure, MAX_CONFIRMATION_EXPOSURE_BYTES, "Confirmation exposure")
    )


class ConfirmationAlreadyExposed(PermissionError):
    """A managed origin overlap is consumed, irrespective of output delivery."""

    code = "confirmation_already_exposed"

    def __init__(self, exposures: tuple[ConfirmationExposure, ...]) -> None:
        _require(
            type(exposures) is tuple and 1 <= len(exposures) <= 256,
            "Exposure conflict must preserve bounded actual records",
        )
        checked = tuple(load_confirmation_exposure(value.canonical_bytes) for value in exposures)
        _require(
            all(
                left.exposure_id == right.exposure_id
                for left, right in zip(exposures, checked, strict=True)
            ),
            "Exposure conflict identity differs",
        )
        _require(
            len({value.exposure_id for value in checked}) == len(checked),
            "Duplicate exposure conflict",
        )
        self.exposures = tuple(sorted(checked, key=lambda value: value.exposure_id))
        super().__init__("Confirmation origins are already exposed in the managed dataset ledger")
