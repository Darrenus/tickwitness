"""Use actual sealed datasets and registries to verify protocol binding and denial."""

import json
from pathlib import Path

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.research import (
    ConfirmationAccessDenied,
    freeze_protocol,
    inspect_protocol,
    read_protocol_data,
)
from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry


def request(*, fee_model: str = "zero_fees_v1", hypothesis: str = "Positive marked PnL") -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "claim": {
                "title": "Synthetic claim",
                "hypothesis": hypothesis,
                "metric": "net_marked_pnl_v1",
                "comparator": "gt",
                "threshold": "0.00",
                "unit": "synthetic_quote_units",
            },
            "strategy_name": "static_source",
            "parameters": {"quantity_lots": 1},
            "configuration": {
                "fee_model_id": fee_model,
                "execution_model_id": "unbound",
                "clock_policy_id": "capture_order_unbound_v1",
            },
            "budget": {"max_scenarios": 10, "max_wall_seconds": 60, "max_events": 100},
            "seed": 7,
        }
    ).encode()


def snapshot(capture_seq: int, *, event_time: int | None = None, price: int = 99) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "type": "snapshot",
                "source": "synthetic",
                "instrument": "TEST-USD",
                "session": "research-test",
                "capture_seq": capture_seq,
                "event_time_ns": event_time if event_time is not None else capture_seq * 100,
                "receive_time_ns": None,
                "last_sequence": capture_seq * 10,
                "bids": [[price, 5]],
                "asks": [[price + 2, 5]],
            }
        )
        + "\n"
    ).encode()


def setup_data(tmp_path: Path) -> tuple[LocalDatasetStore, str, str]:
    store = LocalDatasetStore(tmp_path / "data")
    development = import_events(snapshot(1), lambda: store)
    confirmation = import_events(snapshot(3, price=199), lambda: store)
    return store, development.dataset_id, confirmation.dataset_id


def trade(
    capture_seq: int, *, event_time: int, quantity: int = 1, trade_id: str = "trade-1"
) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "type": "trade",
                "source": "synthetic",
                "instrument": "TEST-USD",
                "session": "research-test",
                "capture_seq": capture_seq,
                "event_time_ns": event_time,
                "receive_time_ns": None,
                "trade_id": trade_id,
                "price_ticks": 99,
                "quantity_lots": quantity,
                "aggressor_side": "sell",
            }
        )
        + "\n"
    ).encode()


def delta(capture_seq: int, first: int, last: int, *, price: int = 99) -> bytes:
    observation = json.loads(snapshot(capture_seq, price=price))
    observation.update({"type": "delta", "first_sequence": first, "last_sequence": last})
    return (json.dumps(observation) + "\n").encode()


def freeze(
    tmp_path: Path, data: LocalDatasetStore, development: str, confirmation: str, draft: bytes
):
    return freeze_protocol(
        draft,
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        strategy_source=b"raise AssertionError('source must never execute during freezing')\n",
        datasets=data,
        registry_factory=lambda: LocalProtocolRegistry(tmp_path / "registry"),
    )


def test_real_freeze_repeat_inspect_and_model_change(tmp_path: Path) -> None:
    data, development, confirmation = setup_data(tmp_path)
    first = freeze(tmp_path, data, development, confirmation, request())
    repeated = freeze(tmp_path, data, development, confirmation, request())
    changed_model = freeze(tmp_path, data, development, confirmation, request(fee_model="fee_v2"))
    changed_claim = freeze(
        tmp_path, data, development, confirmation, request(hypothesis="Different hypothesis")
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.protocol_id == first.protocol_id
    assert changed_model.protocol_id != first.protocol_id
    assert changed_model.claim_revision_id == first.claim_revision_id
    assert changed_claim.claim_revision_id != first.claim_revision_id
    inspected = inspect_protocol(
        first.protocol_id, LocalProtocolRegistry(tmp_path / "registry"), data
    )
    assert inspected.document == first.document
    assert inspected.document["execution_ready"] is False


def test_development_read_uses_immutable_binding(tmp_path: Path) -> None:
    data, development, confirmation = setup_data(tmp_path)
    frozen = freeze(tmp_path, data, development, confirmation, request())

    result = read_protocol_data(
        frozen.protocol_id,
        split="development",
        registry_factory=lambda: LocalProtocolRegistry(tmp_path / "registry", create=False),
        datasets_factory=lambda: data,
        limit=1,
    )

    assert result.dataset_id == development
    assert result.dataset_id != confirmation
    assert result.observations[0]["bids"] == [[99, 5]]
    assert result.total_records == 1


@pytest.mark.parametrize("split", ["confirmation", "unknown", "DEVELOPMENT"])
def test_non_development_access_denied_before_any_repository_is_constructed(split: str) -> None:
    def must_not_open():
        raise AssertionError("An unauthorized read must not initialize or inspect storage")

    with pytest.raises(ConfirmationAccessDenied):
        read_protocol_data(
            "0" * 64,
            split=split,
            registry_factory=must_not_open,
            datasets_factory=must_not_open,
        )


@pytest.mark.parametrize("repackaged", [False, True])
def test_capture_or_semantic_overlap_rejected_before_registry_creation(
    tmp_path: Path, repackaged: bool
) -> None:
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(snapshot(1), lambda: data).dataset_id
    if repackaged:
        observation = json.loads(snapshot(1))
        observation["capture_seq"] = 3
        raw = (json.dumps(observation) + "\n").encode()
    else:
        # Different raw bytes, identical normalized market observation.
        raw = snapshot(1).replace(b'"source":', b'"source" :')
    confirmation = import_events(raw, lambda: data).dataset_id

    with pytest.raises(ProtocolValidationError):
        freeze(tmp_path, data, development, confirmation, request())

    assert not (tmp_path / "registry").exists()


def test_reversed_capture_order_is_not_a_forward_confirmation_partition(tmp_path: Path) -> None:
    data, development, confirmation = setup_data(tmp_path)

    with pytest.raises(ProtocolValidationError):
        freeze(tmp_path, data, confirmation, development, request())

    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize(("event_time", "quantity"), [(100, 1), (300, 1), (100, 2), (300, 2)])
def test_trade_origin_identity_cannot_cross_partitions_by_changing_payload(
    tmp_path: Path, event_time: int, quantity: int
) -> None:
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(trade(1, event_time=100), lambda: data).dataset_id
    confirmation = import_events(
        trade(3, event_time=event_time, quantity=quantity), lambda: data
    ).dataset_id

    with pytest.raises(ProtocolValidationError, match="overlapping market observations"):
        freeze(tmp_path, data, development, confirmation, request())

    assert not (tmp_path / "registry").exists()


def test_distinct_trade_ids_with_identical_market_values_are_not_false_overlap(
    tmp_path: Path,
) -> None:
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(
        trade(1, event_time=100, trade_id="trade-1"), lambda: data
    ).dataset_id
    confirmation = import_events(
        trade(3, event_time=100, trade_id="trade-2"), lambda: data
    ).dataset_id

    receipt = freeze(tmp_path, data, development, confirmation, request())

    assert receipt.document["execution_ready"] is False


@pytest.mark.parametrize("confirmation_sequence", [9, 10])
def test_book_sequence_cannot_be_reused_or_reversed_with_a_different_payload(
    tmp_path: Path, confirmation_sequence: int
) -> None:
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(snapshot(1), lambda: data).dataset_id
    observation = json.loads(snapshot(3, price=199))
    observation["last_sequence"] = confirmation_sequence
    confirmation = import_events((json.dumps(observation) + "\n").encode(), lambda: data).dataset_id

    with pytest.raises(ProtocolValidationError, match="book sequence ranges"):
        freeze(tmp_path, data, development, confirmation, request())

    assert not (tmp_path / "registry").exists()


def test_partially_overlapping_aggregated_depth_ranges_are_rejected(tmp_path: Path) -> None:
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(snapshot(1) + delta(2, 11, 12), lambda: data).dataset_id
    initial = json.loads(snapshot(3, price=199))
    initial["last_sequence"] = 11
    confirmation = import_events(
        (json.dumps(initial) + "\n").encode() + delta(4, 12, 13, price=199), lambda: data
    ).dataset_id

    with pytest.raises(ProtocolValidationError, match="book sequence ranges"):
        freeze(tmp_path, data, development, confirmation, request())

    assert not (tmp_path / "registry").exists()


def test_strictly_forward_nonoverlapping_depth_ranges_can_freeze(tmp_path: Path) -> None:
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(snapshot(1) + delta(2, 11, 12), lambda: data).dataset_id
    initial = json.loads(snapshot(3, price=199))
    initial["last_sequence"] = 13
    confirmation = import_events(
        (json.dumps(initial) + "\n").encode() + delta(4, 14, 15, price=199), lambda: data
    ).dataset_id

    receipt = freeze(tmp_path, data, development, confirmation, request())

    assert receipt.document["execution_ready"] is False


def test_new_capture_session_does_not_bypass_the_same_stream_contract(tmp_path: Path) -> None:
    data, development, _ = setup_data(tmp_path)
    observation = json.loads(snapshot(3, price=199))
    observation["session"] = "different-session"
    confirmation = import_events((json.dumps(observation) + "\n").encode(), lambda: data).dataset_id

    with pytest.raises(ProtocolValidationError, match="same streams"):
        freeze(tmp_path, data, development, confirmation, request())

    assert not (tmp_path / "registry").exists()


def test_self_consistent_storage_report_cannot_claim_false_validation(tmp_path: Path) -> None:
    data, _, confirmation = setup_data(tmp_path)
    raw = snapshot(1)
    normalized = normalize_events(raw)
    forged_report = dict(normalized.report, replay_certified=True)
    forged = data.publish(raw, normalized.normalized_bytes, forged_report)

    with pytest.raises(ProtocolValidationError, match="report"):
        freeze(tmp_path, data, forged.dataset_id, confirmation, request())

    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize("forged_count", [True, 1.0])
def test_report_boolean_or_float_cannot_impersonate_the_integer_record_count(
    tmp_path: Path, forged_count: object
) -> None:
    data, _, confirmation = setup_data(tmp_path)
    raw = snapshot(1)
    normalized = normalize_events(raw)
    assert normalized.report["record_count"] == 1
    forged_report = dict(normalized.report, record_count=forged_count)
    # These values compare equal under Python dict equality but have different
    # JSON types. Exercise the real CAS/catalog roundtrip before freezing.
    assert forged_report == normalized.report
    forged = data.publish(raw, normalized.normalized_bytes, forged_report)

    with pytest.raises(ProtocolValidationError, match="report"):
        freeze(tmp_path, data, forged.dataset_id, confirmation, request())

    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize("source", [b"", b"\xff", b"def broken(", b"x" * (256 * 1024 + 1)])
def test_invalid_strategy_is_rejected_before_registry_creation(
    tmp_path: Path, source: bytes
) -> None:
    data, development, confirmation = setup_data(tmp_path)

    with pytest.raises(ProtocolValidationError):
        freeze_protocol(
            request(),
            development_dataset_id=development,
            confirmation_dataset_id=confirmation,
            strategy_source=source,
            datasets=data,
            registry_factory=lambda: LocalProtocolRegistry(tmp_path / "registry"),
        )

    assert not (tmp_path / "registry").exists()
