"""Read accepted immutable events through a narrow storage port."""

import json
from typing import Protocol

from tickwitness.application.datasets import DatasetRecord
from tickwitness.domain.data_evidence.events import DataValidationError, normalize_events

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
