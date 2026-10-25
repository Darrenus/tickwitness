"""Qualification uses accepted sealed data, validates first, and pins returned identities."""

import hashlib
import json
from pathlib import Path

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.replay import replay_dataset
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore


def specification() -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "clock_policy_id": "receive_order_v1",
            "instrument": {
                "base_currency": "EUR",
                "quote_currency": "USD",
                "price_increment": "1",
                "size_increment": "1",
            },
            "account": {"starting_cash": "10000"},
            "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
            "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
            "strategy": {
                "kind": "single_limit_buy_v1",
                "submit_capture_seq": 1,
                "limit_price_ticks": 100,
                "quantity_lots": 2,
                "cancel_after_first_fill": False,
            },
            "seed": 7,
        }
    ).encode()


def snapshot(*, receive_time: int | None = 100) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "type": "snapshot",
                "source": "synthetic",
                "instrument": "EUR-USD",
                "session": "app-replay",
                "capture_seq": 1,
                "event_time_ns": 100,
                "receive_time_ns": receive_time,
                "last_sequence": 10,
                "bids": [[100, 1], [99, 10]],
                "asks": [[103, 10], [104, 10]],
            }
        )
        + "\n"
    ).encode()


def test_invalid_spec_does_not_open_store_or_construct_engine() -> None:
    def forbidden():
        raise AssertionError("Invalid input must fail before opening infrastructure")

    with pytest.raises(ReplayValidationError):
        replay_dataset(
            "0" * 64, b'{"schema_version":1}', datasets_factory=forbidden, engine_factory=forbidden
        )


def test_unsupported_clock_does_not_construct_engine(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path / "data")
    identity = import_events(snapshot(receive_time=None), lambda: store).dataset_id

    def forbidden():
        raise AssertionError("Unsupported clock must fail before native construction")

    with pytest.raises(ReplayValidationError):
        replay_dataset(
            identity, specification(), datasets_factory=lambda: store, engine_factory=forbidden
        )


@pytest.mark.parametrize("count", [True, 1.0])
def test_replay_reuses_strict_report_verification(tmp_path: Path, count: object) -> None:
    from tickwitness.domain.data_evidence.events import normalize_events

    store = LocalDatasetStore(tmp_path / "data")
    raw = snapshot()
    validated = normalize_events(raw)
    forged = store.publish(
        raw, validated.normalized_bytes, dict(validated.report, record_count=count)
    )

    def forbidden():
        raise AssertionError("Forged report must fail before native construction")

    with pytest.raises(ReplayValidationError, match="report"):
        replay_dataset(
            forged.dataset_id,
            specification(),
            datasets_factory=lambda: store,
            engine_factory=forbidden,
        )


def test_engine_receives_exact_sealed_bytes_after_complete_preflight(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path / "data")
    imported = import_events(snapshot(), lambda: store)
    reached: list[ReplayInput] = []

    class StopAfterReceipt:
        def run(self, request: ReplayInput):
            reached.append(request)
            raise RuntimeError("Verified port boundary reached")

    with pytest.raises(RuntimeError, match="Verified port"):
        replay_dataset(
            imported.dataset_id,
            specification(),
            datasets_factory=lambda: store,
            engine_factory=StopAfterReceipt,
        )

    assert len(reached) == 1
    assert reached[0].dataset_id == imported.dataset_id
    assert (
        hashlib.sha256(reached[0].normalized_bytes).hexdigest()
        == imported.manifest["objects"]["normalized"]["sha256"]
    )


@pytest.mark.parametrize("identity", ["dataset_id", "data_sha256", "spec_id"])
def test_result_cannot_silently_switch_immutable_input(
    tmp_path: Path, replay_result_factory, identity: str
) -> None:
    store = LocalDatasetStore(tmp_path / "data")
    imported = import_events(snapshot(), lambda: store)

    class WrongResult:
        def run(self, request: ReplayInput):
            return replay_result_factory(request, **{identity: "b" * 64})

    with pytest.raises(ReplayValidationError, match="immutable input"):
        replay_dataset(
            imported.dataset_id,
            specification(),
            datasets_factory=lambda: store,
            engine_factory=WrongResult,
        )
