"""Exercise the real domain plus temporary SQLite/CAS through the application port."""

import json
from pathlib import Path

import pytest

from tickwitness.application.datasets import import_events, inspect_dataset
from tickwitness.domain.data_evidence.events import DataValidationError
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore


def _snapshot(*, receive_time: int | None = 110) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "type": "snapshot",
                "source": "synthetic",
                "instrument": "TEST-USD",
                "session": "test-session",
                "capture_seq": 1,
                "event_time_ns": 100,
                "receive_time_ns": receive_time,
                "last_sequence": 10,
                "bids": [[99, 5]],
                "asks": [[101, 5]],
            }
        )
        + "\n"
    ).encode()


def test_same_input_publishes_once_and_survives_a_new_repository_instance(tmp_path: Path) -> None:
    root = tmp_path / "store"
    raw = _snapshot()

    first = import_events(raw, lambda: LocalDatasetStore(root))
    repeated = import_events(raw, lambda: LocalDatasetStore(root))
    inspected = inspect_dataset(first.dataset_id, LocalDatasetStore(root))

    assert first.created is True
    assert repeated.created is False
    assert first.dataset_id == repeated.dataset_id == inspected.dataset_id
    assert first.manifest == inspected.manifest
    assert inspected.report["record_count"] == 1
    assert len(LocalDatasetStore(root).list_datasets()) == 1


def test_invalid_data_never_constructs_a_destination(tmp_path: Path) -> None:
    root = tmp_path / "not-created"

    with pytest.raises(DataValidationError):
        import_events(b"not JSON\n", lambda: LocalDatasetStore(root))

    assert not root.exists()


def test_unknown_receive_time_stays_unknown_in_the_published_evidence(tmp_path: Path) -> None:
    result = import_events(
        _snapshot(receive_time=None), lambda: LocalDatasetStore(tmp_path / "store")
    )

    assert result.report["unknown_receive_count"] == 1
    assert result.report["replay_certified"] is False


def test_sequence_gap_is_preserved_and_published_as_quarantined(tmp_path: Path) -> None:
    delta = {
        "schema_version": 1,
        "type": "delta",
        "source": "synthetic",
        "instrument": "TEST-USD",
        "session": "test-session",
        "capture_seq": 2,
        "event_time_ns": 102,
        "receive_time_ns": 112,
        "first_sequence": 12,
        "last_sequence": 12,
        "bids": [[99, 4]],
        "asks": [],
    }
    raw = _snapshot() + (json.dumps(delta) + "\n").encode()

    result = import_events(raw, lambda: LocalDatasetStore(tmp_path / "store"))

    assert result.report["record_count"] == 2
    assert result.report["quality_status"] == "quarantined"
    assert result.report["replay_certified"] is False
