"""Read accepted immutable events through a narrow storage port."""

import hashlib
import json
from typing import Protocol, cast

from tickwitness.application.datasets import DatasetRecord
from tickwitness.domain.data_evidence.events import DataValidationError, normalize_events
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError

MAX_DATA_BYTES = 8 * 1024 * 1024


class DataAccessError(ValueError):
    """Stored evidence does not satisfy the accepted normalized-event contract."""


class DatasetReader(Protocol):
    def get(self, dataset_id: str) -> DatasetRecord: ...

    def read_normalized(self, dataset_id: str, *, max_bytes: int = MAX_DATA_BYTES) -> bytes: ...


def read_accepted_events(dataset_id: str, datasets: DatasetReader) -> bytes:
    """Verify storage closure, canonical events and the complete typed quality report."""
    record = datasets.get(dataset_id)
    if (
        record.dataset_id != dataset_id
        or record.manifest.get("format_id") != "tickwitness.normalized-events.v1"
    ):
        raise DataAccessError("Dataset identity or event format does not match")
    data = datasets.read_normalized(dataset_id, max_bytes=MAX_DATA_BYTES)
    try:
        validated = normalize_events(data)
    except DataValidationError as error:
        raise DataAccessError("Dataset does not satisfy normalized-events-v1") from error
    try:
        stored_report = json.dumps(
            record.report, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        expected_report = json.dumps(
            validated.report, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise DataAccessError("Dataset quality report cannot be encoded as finite JSON") from error
    if data != validated.normalized_bytes or stored_report != expected_report:
        raise DataAccessError("Dataset normalization or quality report does not match")
    if validated.report["quality_status"] != "accepted":
        raise DataAccessError("Quarantined data cannot bind a research operation")
    return data


def _stream(record: dict[str, object]) -> tuple[str, str, str]:
    return (
        cast("str", record["source"]),
        cast("str", record["instrument"]),
        cast("str", record["session"]),
    )


def _semantic_identity(record: dict[str, object]) -> bytes:
    # Stable origin identities cannot become independent observations by changing
    # timestamps, capture metadata, or conflicting market payloads.
    content = {
        "source": record["source"],
        "instrument": record["instrument"],
        "session": record["session"],
    }
    if record["type"] == "trade":
        content.update({"kind": "trade", "trade_id": record["trade_id"]})
    else:
        last = record["last_sequence"]
        content.update(
            {
                "kind": "book_sequence_interval",
                "first_sequence": record["first_sequence"] if record["type"] == "delta" else last,
                "last_sequence": last,
            }
        )
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).digest()


def assert_forward_disjoint(
    development: tuple[dict[str, object], ...], confirmation: tuple[dict[str, object], ...]
) -> None:
    def ranges(
        records: tuple[dict[str, object], ...], *, book_sequences: bool = False
    ) -> dict[tuple[str, str, str], tuple[int, int]]:
        result: dict[tuple[str, str, str], tuple[int, int]] = {}
        for record in records:
            stream = _stream(record)
            if book_sequences:
                if record["type"] == "trade":
                    continue
                last = cast("int", record["last_sequence"])
                first = cast("int", record["first_sequence"]) if record["type"] == "delta" else last
            else:
                first = last = cast("int", record["capture_seq"])
            low, high = result.get(stream, (first, last))
            result[stream] = min(low, first), max(high, last)
        return result

    dev_ranges, confirmation_ranges = ranges(development), ranges(confirmation)
    if dev_ranges.keys() != confirmation_ranges.keys() or any(
        dev_ranges[stream][1] >= confirmation_ranges[stream][0] for stream in dev_ranges
    ):
        raise ProtocolValidationError(
            "Partitions must be disjoint forward captures of the same streams"
        )
    dev_book = ranges(development, book_sequences=True)
    confirmation_book = ranges(confirmation, book_sequences=True)
    if any(
        dev_book[stream][1] >= confirmation_book[stream][0]
        for stream in dev_book.keys() & confirmation_book.keys()
    ):
        raise ProtocolValidationError(
            "Partitions contain overlapping or reversed book sequence ranges"
        )
    dev_observations = {_semantic_identity(record) for record in development}
    if any(_semantic_identity(record) in dev_observations for record in confirmation):
        raise ProtocolValidationError("Partitions contain overlapping market observations")
