"""Validate the version-one captured L2 JSONL contract using bounded bytes.

No timestamps or missing book paths are invented. The output preserves every
record in capture order; its report explains which records must not be applied.
Accepted input is neither proof of clock accuracy nor replay certification.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Never, cast

_INT64_MAX = (1 << 63) - 1
_COMMON_FIELDS = frozenset(
    {
        "schema_version",
        "type",
        "source",
        "instrument",
        "session",
        "capture_seq",
        "event_time_ns",
        "receive_time_ns",
    }
)
_TYPE_FIELDS = {
    "snapshot": frozenset({"last_sequence", "bids", "asks"}),
    "delta": frozenset({"first_sequence", "last_sequence", "bids", "asks"}),
    "trade": frozenset({"trade_id", "price_ticks", "quantity_lots", "aggressor_side"}),
}


class DataValidationError(ValueError):
    """The input cannot be represented by the supported observation contract."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ValidationLimits:
    """Positive byte, record and depth limits checked before expensive work."""

    max_bytes: int = 8 * 1024 * 1024
    max_records: int = 100_000
    max_line_bytes: int = 65_536
    max_levels_per_side: int = 1_000

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_records", "max_line_bytes", "max_levels_per_side"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise DataValidationError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class NormalizedDataset:
    """Canonical JSONL plus JSON-safe, observation-scoped quality findings."""

    normalized_bytes: bytes
    report: dict[str, object]


_DEFAULT_LIMITS = ValidationLimits()


type _Record = dict[str, object]
type _Stream = tuple[str, str, str]


@dataclass(slots=True)
class _Epoch:
    stream: _Stream
    number: int
    start_line: int
    end_line: int
    snapshot_sequence: int
    last_sequence: int
    closed_by: str | None = None

    def report(self) -> dict[str, object]:
        return {
            "stream": _stream_report(self.stream),
            "epoch": self.number,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "snapshot_sequence": self.snapshot_sequence,
            "last_sequence": self.last_sequence,
            "closed_by": self.closed_by,
        }


@dataclass(slots=True)
class _StreamState:
    capture_high_water: int | None = None
    captures: dict[int, bytes] = field(default_factory=dict)
    delta_ranges: dict[tuple[int, int], bytes] = field(default_factory=dict)
    trades: dict[str, bytes] = field(default_factory=dict)
    observed_book_high_water: int | None = None
    epoch: _Epoch | None = None
    epoch_count: int = 0


def _reject_float_or_constant(_value: str) -> Never:
    raise DataValidationError("floating-point numbers and non-finite constants are not allowed")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DataValidationError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_record(raw_line: bytes, line: int) -> _Record:
    try:
        text = raw_line.decode("utf-8", errors="strict")
        parsed: object = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float_or_constant,
            parse_constant=_reject_float_or_constant,
        )
    except DataValidationError as error:
        raise DataValidationError(f"line {line}: {error.message}") from error
    except UnicodeDecodeError as error:
        raise DataValidationError(f"line {line}: input must be UTF-8") from error
    except (ValueError, RecursionError) as error:
        raise DataValidationError(f"line {line}: invalid or excessively nested JSON") from error
    if not isinstance(parsed, dict):
        raise DataValidationError(f"line {line}: each record must be a JSON object")
    return cast("dict[str, object]", parsed)


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= _INT64_MAX:
        raise DataValidationError(f"{name} must be an integer in [{minimum}, {_INT64_MAX}]")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise DataValidationError(f"{name} must be a nonempty identifier of at most 256 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise DataValidationError(f"{name} cannot contain control characters")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise DataValidationError(f"{name} must contain valid Unicode scalar values") from error
    return value


def _levels(value: object, name: str, event_type: str, limits: ValidationLimits) -> None:
    if not isinstance(value, list) or len(value) > limits.max_levels_per_side:
        raise DataValidationError(f"{name} must be a list within max_levels_per_side")
    prices: set[int] = set()
    for entry in value:
        if not isinstance(entry, list) or len(entry) != 2:
            raise DataValidationError(f"{name} entries must be [price_ticks, quantity_lots]")
        price = _integer(entry[0], f"{name}.price_ticks", minimum=1)
        _integer(entry[1], f"{name}.quantity_lots", minimum=1 if event_type == "snapshot" else 0)
        if price in prices:
            raise DataValidationError(f"{name} contains duplicate price levels")
        prices.add(price)


def _validate_record(record: _Record, limits: ValidationLimits) -> _Stream:
    event_type = record.get("type")
    if not isinstance(event_type, str) or event_type not in _TYPE_FIELDS:
        raise DataValidationError("type must be snapshot, delta, or trade")
    expected = _COMMON_FIELDS | _TYPE_FIELDS[event_type]
    if record.keys() != expected:
        raise DataValidationError("record contains missing or unknown fields")
    if _integer(record["schema_version"], "schema_version") != 1:
        raise DataValidationError("unsupported schema_version")
    stream = (
        _identifier(record["source"], "source"),
        _identifier(record["instrument"], "instrument"),
        _identifier(record["session"], "session"),
    )
    _integer(record["capture_seq"], "capture_seq", minimum=1)
    _integer(record["event_time_ns"], "event_time_ns")
    if record["receive_time_ns"] is not None:
        _integer(record["receive_time_ns"], "receive_time_ns")
    if event_type == "trade":
        _identifier(record["trade_id"], "trade_id")
        _integer(record["price_ticks"], "price_ticks", minimum=1)
        _integer(record["quantity_lots"], "quantity_lots", minimum=1)
        if record["aggressor_side"] not in ("buy", "sell"):
            raise DataValidationError("aggressor_side must be buy or sell")
    else:
        last = _integer(record["last_sequence"], "last_sequence")
        if event_type == "delta":
            first = _integer(record["first_sequence"], "first_sequence")
            if first > last:
                raise DataValidationError("first_sequence cannot exceed last_sequence")
        _levels(record["bids"], "bids", event_type, limits)
        _levels(record["asks"], "asks", event_type, limits)
    return stream


def _canonical(record: _Record) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _signature(record: _Record, keys: tuple[str, ...]) -> bytes:
    return hashlib.sha256(_canonical({key: record[key] for key in keys})).digest()


def _delta_signature(record: _Record) -> bytes:
    """Compare unique price-level mappings without mutating capture evidence."""
    ordered: _Record = {
        side: sorted(cast("list[list[int]]", record[side]), key=lambda level: level[0])
        for side in ("bids", "asks")
    }
    return _signature(ordered, ("bids", "asks"))


def _stream_report(stream: _Stream) -> dict[str, object]:
    return {"source": stream[0], "instrument": stream[1], "session": stream[2]}


def _close_epoch(state: _StreamState, reason: str) -> None:
    if state.epoch is not None:
        state.epoch.closed_by = reason
        state.epoch = None


@dataclass(slots=True)
class _Quality:
    findings: list[dict[str, object]] = field(default_factory=list)
    quarantined: bool = False

    def add(self, code: str, line: int, stream: _Stream, *, quarantine: bool = False) -> None:
        self.findings.append(
            {
                "code": code,
                "line": line,
                "stream": _stream_report(stream),
                "severity": "quarantine" if quarantine else "notice",
            }
        )
        self.quarantined = self.quarantined or quarantine


def _capture_disposition(
    state: _StreamState,
    record: _Record,
    canonical: bytes,
    line: int,
    stream: _Stream,
    quality: _Quality,
) -> str | None:
    capture_seq = cast("int", record["capture_seq"])
    digest = hashlib.sha256(canonical).digest()
    previous = state.captures.get(capture_seq)
    if previous is not None:
        if previous == digest:
            quality.add("DUPLICATE_CAPTURE", line, stream)
            return "ignored_duplicate"
        quality.add("CAPTURE_SEQUENCE_CONFLICT", line, stream, quarantine=True)
        _close_epoch(state, "CAPTURE_SEQUENCE_CONFLICT")
        return "quarantined"
    state.captures[capture_seq] = digest
    if state.capture_high_water is not None:
        if capture_seq < state.capture_high_water:
            quality.add("OUT_OF_ORDER_CAPTURE", line, stream, quarantine=True)
            _close_epoch(state, "OUT_OF_ORDER_CAPTURE")
            return "ignored_out_of_order"
        if capture_seq != state.capture_high_water + 1:
            quality.add("CAPTURE_SEQUENCE_GAP", line, stream, quarantine=True)
            _close_epoch(state, "CAPTURE_SEQUENCE_GAP")
    state.capture_high_water = capture_seq
    return None


def _trade_disposition(
    state: _StreamState, record: _Record, line: int, stream: _Stream, quality: _Quality
) -> str:
    trade_id = cast("str", record["trade_id"])
    digest = _signature(record, ("event_time_ns", "price_ticks", "quantity_lots", "aggressor_side"))
    previous = state.trades.get(trade_id)
    if previous is not None:
        if previous == digest:
            quality.add("DUPLICATE_TRADE", line, stream)
            return "ignored_duplicate"
        quality.add("TRADE_ID_CONFLICT", line, stream, quarantine=True)
        _close_epoch(state, "TRADE_ID_CONFLICT")
        return "quarantined"
    state.trades[trade_id] = digest
    return "observed"


def _book_disposition(
    state: _StreamState,
    record: _Record,
    line: int,
    stream: _Stream,
    quality: _Quality,
    epochs: list[_Epoch],
) -> str:
    last = cast("int", record["last_sequence"])
    high_water = state.observed_book_high_water
    state.observed_book_high_water = max(last, high_water) if high_water is not None else last
    if record["type"] == "snapshot":
        if high_water is not None and last < high_water:
            quality.add("STALE_SNAPSHOT", line, stream)
            return "ignored_stale"
        _close_epoch(state, "RESNAPSHOT")
        state.epoch_count += 1
        state.epoch = _Epoch(stream, state.epoch_count, line, line, last, last)
        epochs.append(state.epoch)
        return "applied"

    first = cast("int", record["first_sequence"])
    sequence_range = (first, last)
    digest = _delta_signature(record)
    previous = state.delta_ranges.get(sequence_range)
    if previous is not None:
        if previous == digest:
            quality.add("DUPLICATE_DELTA", line, stream)
            return "ignored_duplicate"
        quality.add("DELTA_SEQUENCE_CONFLICT", line, stream, quarantine=True)
        _close_epoch(state, "DELTA_SEQUENCE_CONFLICT")
        return "quarantined"
    state.delta_ranges[sequence_range] = digest
    if state.epoch is None:
        quality.add("MISSING_VALID_SNAPSHOT", line, stream, quarantine=True)
        return "quarantined"
    if last <= state.epoch.last_sequence:
        quality.add("STALE_DELTA", line, stream)
        return "ignored_stale"
    if first != state.epoch.last_sequence + 1:
        code = "BOOK_SEQUENCE_GAP" if first > state.epoch.last_sequence + 1 else "OVERLAPPING_DELTA"
        quality.add(code, line, stream, quarantine=True)
        _close_epoch(state, code)
        return "quarantined"
    state.epoch.last_sequence = last
    return "applied"


def normalize_events(raw: bytes, limits: ValidationLimits = _DEFAULT_LIMITS) -> NormalizedDataset:
    """Validate canonical JSONL, preserving capture order and all observations.

    Malformed records fail atomically. Structurally legal but incomplete or
    conflicting histories remain importable with a quarantined quality report.
    Neither a later snapshot nor canonical encoding repairs missing history.
    """
    if not isinstance(raw, bytes):
        raise DataValidationError("raw must be bytes")
    if not isinstance(limits, ValidationLimits):
        raise DataValidationError("limits must be ValidationLimits")
    if len(raw) > limits.max_bytes:
        raise DataValidationError("input exceeds max_bytes")
    record_count = raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)
    if record_count > limits.max_records:
        raise DataValidationError("input exceeds max_records")
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if not lines:
        raise DataValidationError("input must contain at least one record")

    quality = _Quality()
    streams: dict[_Stream, _StreamState] = {}
    epochs: list[_Epoch] = []
    record_states: list[dict[str, object]] = []
    normalized: list[bytes] = []
    unknown_receive_count = 0
    for line, raw_line in enumerate(lines, start=1):
        if raw_line.endswith(b"\r"):
            raw_line = raw_line[:-1]
        if len(raw_line) > limits.max_line_bytes:
            raise DataValidationError(f"line {line}: record exceeds max_line_bytes")
        record = _parse_record(raw_line, line)
        try:
            stream = _validate_record(record, limits)
        except DataValidationError as error:
            raise DataValidationError(f"line {line}: {error.message}") from error
        canonical = _canonical(record)
        normalized.append(canonical + b"\n")
        state = streams.setdefault(stream, _StreamState())
        if record["receive_time_ns"] is None:
            unknown_receive_count += 1
            quality.add("UNKNOWN_RECEIVE_TIME", line, stream)
        disposition = _capture_disposition(state, record, canonical, line, stream, quality)
        if disposition is None:
            if record["type"] == "trade":
                disposition = _trade_disposition(state, record, line, stream, quality)
            else:
                disposition = _book_disposition(state, record, line, stream, quality, epochs)
        if state.epoch is not None:
            state.epoch.end_line = line
        record_states.append(
            {
                "line": line,
                "stream": _stream_report(stream),
                "disposition": disposition,
                "book_epoch": state.epoch.number if state.epoch is not None else None,
            }
        )
    report: dict[str, object] = {
        "schema_version": 1,
        "normalizer_version": "normalized-events-v1",
        "record_count": len(lines),
        "stream_count": len(streams),
        "quality_status": "quarantined" if quality.quarantined else "accepted",
        "findings": quality.findings,
        "unknown_receive_count": unknown_receive_count,
        "record_states": record_states,
        "book_epochs": [epoch.report() for epoch in epochs],
        "validation_scope": "schema_and_sequence_preflight",
        "checks": [
            "input_and_record_limits",
            "strict_utf8_and_json",
            "v1_fields_types_and_int64_ranges",
            "capture_order_and_duplicate_identity",
            "strict_nonoverlapping_book_sequence_epochs",
            "trade_identity_consistency",
        ],
        "not_checked": [
            "full_book_state_and_crossed_book",
            "snapshot_depth_completeness",
            "trade_to_book_quantity_consistency",
            "instrument_tick_and_lot_specification",
            "source_authenticity_and_source_protocol",
            "clock_accuracy_and_available_at_evidence",
            "engine_replay_and_real_execution",
        ],
        "book_state_reconstructed": False,
        "replay_certified": False,
        "clock_binding": "unbound",
    }
    return NormalizedDataset(b"".join(normalized), report)
