"""Real optional native qualification, using only original bounded synthetic inputs."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay.capabilities import ReplayCapability, UnsupportedCapabilityError
from tickwitness.domain.replay.contracts import ReplayInput, load_replay_result
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec
from tickwitness.infrastructure import nautilus_replay
from tickwitness.infrastructure.nautilus_replay import (
    ENGINE_ID,
    ENGINE_VERSION,
    SEMANTIC_ID,
    NautilusReplayAdapter,
    ReplayDependencyError,
    ReplayEngineError,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _native_installed() -> bool:
    try:
        return metadata.version("nautilus_trader") == ENGINE_VERSION
    except metadata.PackageNotFoundError:
        return False


native = pytest.mark.skipif(not _native_installed(), reason="optional pinned Nautilus extra absent")


def test_capabilities_are_explicit_and_never_claim_checkpoint_support() -> None:
    capabilities = NautilusReplayAdapter().capabilities
    capabilities.require(frozenset({ReplayCapability.FILL_TRACE, ReplayCapability.ACCOUNT_LEDGER}))
    with pytest.raises(UnsupportedCapabilityError) as caught:
        capabilities.require(frozenset({ReplayCapability.CHECKPOINT}))
    assert caught.value.missing == frozenset({ReplayCapability.CHECKPOINT})


def _input(
    fixture: str = "replay-partials.jsonl",
    *,
    changes: dict[str, dict[str, object]] | None = None,
    limit: int | None = None,
    spec_fixture: str = "replay-spec.json",
    raw: bytes | None = None,
) -> ReplayInput:
    document = json.loads((EXAMPLES / spec_fixture).read_bytes())
    for group, values in (changes or {}).items():
        document[group].update(values)
    source = (EXAMPLES / fixture).read_bytes() if raw is None else raw
    if limit is not None:
        source = b"\n".join(source.splitlines()[:limit]) + b"\n"
    normalized = normalize_events(source).normalized_bytes
    return ReplayInput(
        dataset_id=hashlib.sha256(normalized).hexdigest(),
        normalized_bytes=normalized,
        spec=build_replay_spec(json.dumps(document).encode()),
    )


def _run(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return NautilusReplayAdapter().run(_input(*args, **kwargs)).document


@native
@pytest.mark.parametrize("fixture", ["replay-partials.jsonl", "replay-same-time.jsonl"])
def test_real_l2_two_partials_account_cache_and_capture_trigger(fixture: str) -> None:
    document = _run(fixture)
    assert document["engine"] == {
        "id": ENGINE_ID,
        "version": ENGINE_VERSION,
        "semantic_id": SEMANTIC_ID,
    }
    assert document["environment"]["package_versions"]["nautilus_trader"] == ENGINE_VERSION
    assert document["execution_status"] == "completed"
    assert document["completeness"] == {
        "input_records": 7,
        "processed_records": 7,
        "open_orders": [],
        "pending_commands": [],
        "stop_reason": "input_exhausted",
    }
    inputs = document["input_trace"]
    assert [row["source_ref"]["capture_seq"] for row in inputs] == list(range(1, 8))
    assert inputs[0]["fields"]["bids"] == [[100, 1], [99, 10]]
    assert inputs[0]["fields"]["asks"] == [[103, 10], [104, 10]]
    assert inputs[0]["fields"]["source_sequence_last"] == 10
    assert inputs[0]["fields"]["native_internal_id"] == "1"
    for row in inputs:
        fields = row["fields"]
        assert fields["event_time_ns"] == fields["receive_time_ns"] - 100
        assert fields["native_ts_event_ns"] == fields["native_ts_init_ns"]
        assert fields["native_ts_init_ns"] == fields["receive_time_ns"]
        assert fields["source_clock_certified"] is False
    assert inputs[2]["fields"]["source_trade_id"] == "source-trade-1"
    assert inputs[2]["fields"]["native_internal_id"] == "CAPTURE-3"
    fills = document["fill_trace"]
    assert [row["source_ref"]["capture_seq"] for row in fills] == [3, 5]
    assert [row["fields"]["quantity_lots"] for row in fills] == [1, 1]
    assert [row["fields"]["price_ticks"] for row in fills] == [100, 100]
    assert [row["fields"]["commission"] for row in fills] == ["1", "1"]
    accounts = [
        row for row in document["account_trace"] if row["kind"] == "fill_callback_account_snapshot"
    ]
    assert [
        (
            row["fields"]["net_position_lots"],
            row["fields"]["cash_total"],
            row["fields"]["observed_commission"],
        )
        for row in accounts
    ] == [(1, "9999", "1"), (2, "9998", "2")]
    assert [row["source_ref"]["capture_seq"] for row in accounts] == [3, 5]
    assert accounts[0]["fields"]["orders"][0]["status"] == "PARTIALLY_FILLED"
    assert accounts[1]["fields"]["orders"][0]["status"] == "FILLED"
    for row in accounts:
        state = row["fields"]
        assert state["book_type"] == "L2_MBP"
        assert (state["bid_levels"], state["ask_levels"]) == (2, 2)
        assert Decimal(state["cash_free"]) + Decimal(state["cash_locked"]) == Decimal(
            state["cash_total"]
        )
    if fixture == "replay-same-time.jsonl":
        assert fills[0]["native_time_ns"] == fills[1]["native_time_ns"]


@native
@pytest.mark.parametrize("cancel_delay,expected_fills", [(0, 1), (1_000_000_000, 2)])
def test_same_time_cancel_race_has_receipts_and_input_step_sources(
    cancel_delay: int, expected_fills: int
) -> None:
    document = _run(
        "replay-same-time.jsonl",
        changes={
            "strategy": {"cancel_after_first_fill": True},
            "execution": {"cancel_latency_ns": cancel_delay},
        },
    )
    assert document["execution_status"] == "completed"
    assert len(document["fill_trace"]) == expected_fills
    assert [row["fields"]["action"] for row in document["decision_trace"]] == ["submit", "cancel"]
    cancel_decision = document["decision_trace"][1]
    assert cancel_decision["source_ref"]["capture_seq"] == 3
    receipt_kind = "OrderCanceled" if cancel_delay == 0 else "OrderCancelRejected"
    receipt = next(row for row in document["order_trace"] if row["kind"] == receipt_kind)
    assert receipt["source_ref"]["capture_seq"] == (3 if cancel_delay == 0 else 7)
    assert receipt["fields"]["pending_command_ids"] == []
    # A later input step settles a delayed command; it does not become its issuing input.
    assert document["completeness"]["pending_commands"] == []


@native
def test_eof_retains_cancel_command_even_when_order_is_filled() -> None:
    document = _run(
        "replay-same-time.jsonl",
        limit=5,
        changes={
            "strategy": {"cancel_after_first_fill": True},
            "execution": {"cancel_latency_ns": 1_000_000_000},
        },
    )
    assert len(document["fill_trace"]) == 2
    assert document["account_trace"][-1]["fields"]["orders"][0]["status"] == "FILLED"
    assert document["execution_status"] == "incomplete"
    completeness = document["completeness"]
    assert completeness["stop_reason"] == "pending_commands_at_data_end"
    assert completeness["open_orders"] == []
    assert len(completeness["pending_commands"]) == 1
    pending = completeness["pending_commands"][0]
    assert pending["command_type"] == "cancel"
    assert pending["command_id"] == "command-1"
    assert pending["decision_ref"] == "decision-1"
    assert pending["source_ref"] == {"line": 3, "capture_seq": 3, "event_type": "trade"}
    assert document["account_trace"][-1]["native_time_ns"] == 1_700_000_001_000_000_000
    assert not any(row["kind"] == "OrderCancelRejected" for row in document["order_trace"])


@native
def test_eof_pending_submission_does_not_invent_future_market_data() -> None:
    document = _run("replay-eof-pending.jsonl", spec_fixture="replay-eof-spec.json")
    assert document["execution_status"] == "incomplete"
    completeness = document["completeness"]
    assert completeness["processed_records"] == completeness["input_records"] == 2
    assert completeness["stop_reason"] == "pending_commands_at_data_end"
    assert completeness["pending_commands"][0]["command_type"] == "submit"
    assert completeness["pending_commands"][0]["source_ref"]["capture_seq"] == 2
    assert completeness["open_orders"][0]["status"] == "SUBMITTED"
    assert document["fill_trace"] == []
    assert document["account_trace"][-1]["native_time_ns"] == 1_700_000_003_000_000_000


@native
def test_accepted_resting_open_order_has_a_distinct_incomplete_reason() -> None:
    document = _run("replay-unfilled.jsonl")
    assert document["execution_status"] == "incomplete"
    completeness = document["completeness"]
    assert completeness["pending_commands"] == []
    assert completeness["open_orders"][0]["status"] == "ACCEPTED"
    assert completeness["stop_reason"] == "input_exhausted_with_open_orders"


@native
def test_post_only_rejection_acknowledges_submission_and_is_terminal() -> None:
    document = _run(changes={"strategy": {"limit_price_ticks": 104}})
    assert document["execution_status"] == "completed"
    assert document["fill_trace"] == []
    assert any(row["kind"] == "OrderRejected" for row in document["order_trace"])
    assert document["completeness"]["pending_commands"] == []


@native
def test_fractional_units_preserve_ticks_lots_and_expose_native_fee_quantization() -> None:
    document = _run(
        changes={
            "instrument": {"price_increment": "0.01", "size_increment": "0.1"},
        }
    )
    assert document["execution_status"] == "completed"
    for row in document["fill_trace"]:
        fields = row["fields"]
        assert fields["price_ticks"] == 100
        assert fields["quantity_lots"] == 1
        assert fields["price"] == "1.00"
        assert fields["quantity"] == "0.1"
        assert fields["exact_decimal_fee_before_native_quantization"] == "0.00100"
        assert fields["commission"] == "0"
        assert Decimal(fields["native_commission_minus_exact_decimal_fee"]) == Decimal("-0.001")
        assert "f64_notional_USD_Money_precision_2" in fields["native_fee_policy"]
    assert document["account_trace"][-1]["fields"]["net_position_lots"] == 2


@native
def test_repeat_and_low_caller_decimal_precision_have_identical_complete_semantic_bytes() -> None:
    replay_input = _input()
    adapter = NautilusReplayAdapter()
    first = adapter.run(replay_input)
    assert adapter.run(replay_input).canonical_bytes == first.canonical_bytes
    with localcontext() as context:
        context.prec = 2
        assert adapter.run(replay_input).canonical_bytes == first.canonical_bytes
    assert load_replay_result(first.canonical_bytes).canonical_bytes == first.canonical_bytes


@native
@pytest.mark.parametrize("callback_operation", ["account", "command"])
def test_callback_failure_cannot_be_misreported_as_completed(
    monkeypatch: pytest.MonkeyPatch, callback_operation: str
) -> None:
    from tickwitness.infrastructure import _nautilus_native

    def failed(*args: object, **kwargs: object) -> None:
        raise ValueError("Injected trusted callback failure")

    monkeypatch.setattr(_nautilus_native._Evidence, callback_operation, failed)
    with pytest.raises(ReplayEngineError, match="Injected trusted callback failure"):
        NautilusReplayAdapter().run(_input())


def test_missing_dependency_is_structured_after_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(nautilus_replay.metadata, "version", missing)
    with pytest.raises(ReplayDependencyError, match="optional nautilus") as caught:
        NautilusReplayAdapter().run(_input())
    assert caught.value.code == "missing_dependency"


def test_wrong_native_version_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nautilus_replay.metadata, "version", lambda _: "2.0.0")
    with pytest.raises(ReplayDependencyError, match=r"1\.231\.0") as caught:
        NautilusReplayAdapter().run(_input())
    assert caught.value.code == "version_mismatch"


@pytest.mark.parametrize("problem", ["crossed", "duplicate", "resnapshot", "empty_delta"])
def test_unsupported_data_is_rejected_before_dependency_lookup(
    monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    records = [
        json.loads(line) for line in (EXAMPLES / "replay-partials.jsonl").read_bytes().splitlines()
    ]
    if problem == "crossed":
        records[0]["bids"][0][0] = 103
    elif problem == "duplicate":
        records.insert(1, records[0].copy())
    elif problem == "resnapshot":
        records = [*records[:1], {**records[0], "capture_seq": 2, "last_sequence": 11}]
    else:
        records[1]["bids"] = []

    def forbidden_lookup(name: str) -> str:
        raise AssertionError("Native dependency lookup ran before failed preflight")

    monkeypatch.setattr(nautilus_replay.metadata, "version", forbidden_lookup)
    source = b"\n".join(json.dumps(record).encode() for record in records) + b"\n"
    with pytest.raises(ReplayValidationError):
        NautilusReplayAdapter().run(_input(raw=source))


@pytest.mark.parametrize(
    "failure,expected",
    [
        (RuntimeError("probe failure"), ReplayEngineError),
        (ImportError("native unavailable"), ReplayDependencyError),
    ],
)
def test_native_failure_never_returns_an_executed_success_artifact(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, expected: type[Exception]
) -> None:
    from tickwitness.infrastructure import _nautilus_native

    monkeypatch.setattr(nautilus_replay.metadata, "version", lambda _: ENGINE_VERSION)

    def failed(_: object) -> dict[str, object]:
        raise failure

    monkeypatch.setattr(_nautilus_native, "run_native", failed)
    with pytest.raises(expected):
        NautilusReplayAdapter().run(_input())
