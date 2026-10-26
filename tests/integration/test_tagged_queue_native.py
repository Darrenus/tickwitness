"""Conserved tagged worlds execute original user inputs through pinned native hooks."""

import json
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay._validation import ReplayValidationError, canonical
from tickwitness.domain.replay.contracts import ReplayInput, load_replay_result
from tickwitness.domain.replay.queue_contracts import load_queue_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.replay.tagged_queue_contracts import (
    TaggedQueueReplayInput,
    load_tagged_queue_replay_result,
)
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TAGGED_POLICY_IDS,
    build_tagged_queue_protocol,
)
from tickwitness.infrastructure._tagged_queue_native import _TaggedQueue
from tickwitness.infrastructure._tagged_queue_worker import _request
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError
from tickwitness.infrastructure.tagged_queue_replay import (
    NautilusTaggedQueueReplayAdapter,
    TaggedQueueSubprocessReplayAdapter,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _native_installed() -> bool:
    try:
        return metadata.version("nautilus_trader") == "1.231.0"
    except metadata.PackageNotFoundError:
        return False


native = pytest.mark.skipif(not _native_installed(), reason="optional pinned Nautilus extra absent")


def context(case="standard", policy=TAGGED_POLICY_IDS[0], comparator="gt"):
    rows = [
        json.loads(line)
        for line in (EXAMPLES / "queue-observations.jsonl").read_bytes().splitlines()
    ]
    declaration = json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())
    experiment = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    if case == "same_time":
        for row in rows:
            row["receive_time_ns"] = rows[0]["receive_time_ns"]
            row["event_time_ns"] = rows[0]["event_time_ns"]
    if case == "no_cancel":
        rows[2]["bids"] = [[100, 8]]
        rows[4]["bids"] = rows[5]["bids"] = [[100, 5]]
        declaration["updates"][1]["cancellations_lots"] = 0
    if case == "gross_churn":
        declaration["updates"][1].update(additions_lots=3, cancellations_lots=6)
    if case == "high_mark":
        rows[-1]["bids"].append([102, 10])
    if case == "variable":
        for row in rows:
            for side in ("bids", "asks"):
                if side in row:
                    row[side] = [[price + 300, size] for price, size in row[side]]
            if "price_ticks" in row:
                row["price_ticks"] += 300
        experiment["replay_spec"]["instrument"].update(
            price_increment="0.25", size_increment="0.01"
        )
        experiment["replay_spec"]["strategy"].update(limit_price_ticks=400, quantity_lots=3)
        experiment["replay_spec"]["account"]["starting_cash"] = "12345.67"
    normalized = normalize_events(
        b"\n".join(canonical(row) for row in rows) + b"\n"
    ).normalized_bytes
    source = build_executable_protocol(
        canonical(experiment), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    replay_input = ReplayInput(
        "a" * 64, normalized, build_replay_spec(canonical(experiment["replay_spec"]))
    )
    protocol = build_tagged_queue_protocol(
        canonical(
            {
                "kind": "tagged_queue_request_v1",
                "schema_version": 1,
                "claim": {
                    "title": "Tagged finite-path inventory",
                    "hypothesis": (
                        "Tagged inventory has positive marked net value at the frozen horizon"
                    ),
                    "metric": "tagged_inventory_net_marked_pnl_v1",
                    "unit": "USD",
                    "comparator": comparator,
                    "threshold": "0",
                },
                "budget": {"max_attempts": 4, "max_wall_seconds": 60, "max_events": 1000},
            }
        ),
        source_protocol=source,
        replay_input=replay_input,
        queue_request=canonical(declaration),
    )
    return TaggedQueueReplayInput(protocol, normalized, policy)


@native
@pytest.mark.parametrize(
    "case,expected_lots",
    [
        ("standard", [2, 0]),
        ("same_time", [2, 0]),
        ("no_cancel", [0, 0]),
        ("gross_churn", [2, 0]),
        ("variable", [3, 1]),
        ("high_mark", [2, 0]),
    ],
)
def test_actual_tagged_native_fills_are_single_counted_and_cleanup_is_after_mark(
    case, expected_lots
):
    front_input = context(case)
    requests = [
        front_input,
        TaggedQueueReplayInput(
            front_input.protocol, front_input.normalized_bytes, TAGGED_POLICY_IDS[1]
        ),
    ]
    results = [NautilusTaggedQueueReplayAdapter().run(request) for request in requests]
    assert [
        sum(fill["fields"]["quantity_lots"] for fill in result.document["fill_trace"])
        for result in results
    ] == expected_lots
    for request, result, filled in zip(requests, results, expected_lots, strict=True):
        doc = result.document
        assert doc["bindings"] == request.bindings
        assert load_tagged_queue_replay_result(result.canonical_bytes) == result
        for old_loader in (load_replay_result, load_queue_replay_result):
            with pytest.raises(ReplayValidationError):
                old_loader(result.canonical_bytes)
        assert doc["execution_status"] == "completed"
        assert doc["completeness"]["input_records"] == len(request.prepared.events)
        assert doc["completeness"]["pending_commands"] == doc["completeness"]["open_orders"] == []
        accepted = [row for row in doc["order_trace"] if row["kind"] == "OrderAccepted"]
        assert len(accepted) == 1
        acceptance = accepted[0]["fields"]["actual_acceptance"]
        assert accepted[0]["source_ref"]["capture_seq"] == 1
        assert acceptance["native_bid_lots"] == 5
        assert acceptance["acceptance_role"] == "tagged_reconstruction_proxy"
        assert (
            acceptance["queue"]["ahead_lots"]
            == 5 - request.prepared.spec.document["strategy"]["quantity_lots"]
        )
        for row in doc["queue_trace"]:
            state, flow = row["after"], row["flow"]
            assert (
                state["total_lots"]
                == state["ahead_lots"] + state["own_live_lots"] + state["behind_lots"]
            )
            assert state["external_lots"] == state["ahead_lots"] + state["behind_lots"]
            if row["observed_total_lots"] is not None:
                assert state["total_lots"] == row["observed_total_lots"]
            assert (
                flow["external_trade_ahead_lots"]
                + flow["own_trade_lots"]
                + flow["external_trade_behind_lots"]
                == flow["trade_lots"]
            )
            assert row["own_fill_grant_lots"] == row["granted_lots"] == row["native_filled_lots"]
        horizon = doc["horizon_snapshot"]
        state = horizon["queue_state"]
        assert horizon["source_ref"] == request.prepared.events[-1].source_ref
        assert horizon["native_time_ns"] == request.prepared.events[-1].receive_time_ns
        assert state["own_filled_lots"] == horizon["account"]["net_position_lots"] == filled
        assert horizon["native_target_lots"] == state["total_lots"]
        snapshots = [
            row for row in doc["account_trace"] if row["kind"] == "horizon_account_snapshot"
        ]
        assert len(snapshots) == 1 and snapshots[0]["phase"] == "claim_horizon"
        assert snapshots[0]["fields"] == horizon["account"]
        cleanup = doc["cleanup"]
        assert cleanup["canceled_own_lots"] == state["own_live_lots"]
        assert cleanup["projected_total_after_cleanup"] == state["external_lots"]
        assert cleanup["own_live_after_cleanup"] == 0
        assert cleanup["native_unfilled_lots"] == state["own_live_lots"]
        assert (
            cleanup["book_role"] == horizon["account"]["book_role"] == "recorded_observation_cache"
        )
        cancel = [row for row in doc["decision_trace"] if row["fields"]["action"] == "cancel"]
        if state["own_live_lots"]:
            assert len(cancel) == 1
            assert cancel[0]["phase"] == "post_horizon_cleanup"
            assert cancel[0]["native_time_ns"] == horizon["native_time_ns"]
            assert cleanup["native_status"] == "CANCELED"
            assert any(
                row["kind"] == "OrderCanceled" and row["phase"] == "post_horizon_cleanup"
                for row in doc["order_trace"]
            )
        else:
            assert cancel == [] and cleanup["native_status"] == "FILLED"
        assert doc["account_trace"][-1]["kind"] == "final_account_snapshot"
        assert doc["account_trace"][-1]["phase"] == "post_horizon_cleanup"
        assert doc["account_trace"][-1]["fields"]["net_position_lots"] == filled
        assert all(fill["phase"] == "observed_window" for fill in doc["fill_trace"])
        assert all(fill["fields"]["liquidity_side"] == "MAKER" for fill in doc["fill_trace"])
        commission = sum(
            (Decimal(fill["fields"]["commission"]) for fill in doc["fill_trace"]), Decimal(0)
        )
        assert (
            Decimal(horizon["account"]["cash_total"])
            == Decimal(request.prepared.spec.document["account"]["starting_cash"]) - commission
        )
        if case == "standard":
            assert commission == Decimal(filled)
        if case == "high_mark":
            assert horizon["mark"]["price_ticks"] == 102
    assert requests[0].normalized_bytes == requests[1].normalized_bytes


@native
def test_installed_tagged_worker_preserves_new_protocol_and_semantic():
    request = context("variable")
    result = TaggedQueueSubprocessReplayAdapter().run(request)
    assert result.document["bindings"] == request.bindings
    assert result.document["engine"]["semantic_id"] == "nautilus_tagged_fifo_reconstruction_v1"
    assert result.document["horizon_snapshot"]["queue_state"]["own_filled_lots"] == 3


def test_repeated_hook_does_not_regrant_and_nontrade_has_no_capacity():
    request = context()
    queue = _TaggedQueue(request, SimpleNamespace(quantity_lots=2))
    events = request.prepared.events
    for event in events:
        queue.index += 1
        queue.begin(event)
        if event.capture_seq == 1:
            queue.accepted(5)
        first, second = queue.take(), queue.take()
        assert second == 0
        if event.event_type == "trade":
            assert first == 2
            queue.fill(first)
        else:
            assert first == 0
    assert queue.filled == 2
    assert sum(row["offered_lots"] for row in queue.hooks) == 2
    queue.phase = "post_horizon_cleanup"
    assert queue.take() == 0
    with pytest.raises(ValueError):
        queue.fill(1)


def test_worker_request_is_strict_and_requires_the_new_protocol():
    request = context()
    payload = {
        "kind": "tagged_queue_replay_worker_request_v1",
        "schema_version": 1,
        "protocol": request.protocol.canonical_bytes.decode(),
        "normalized": request.normalized_bytes.decode(),
        "policy_id": request.policy_id,
    }
    assert _request(canonical(payload)) == request
    payload["kind"] = "queue_replay_worker_request_v1"
    with pytest.raises(ReplayValidationError):
        _request(canonical(payload))


@pytest.mark.parametrize("timeout", [True, 0, 61, 1.5])
def test_tagged_transport_timeout_is_bounded(timeout):
    with pytest.raises(ReplayValidationError):
        TaggedQueueSubprocessReplayAdapter(timeout_seconds=timeout)


def test_unavailable_worker_does_not_fallback_to_local_or_other_engine(tmp_path):
    with pytest.raises(ReplayProcessError, match="could not start"):
        TaggedQueueSubprocessReplayAdapter(python_executable=tmp_path / "absent").run(context())
