"""Native-free valid replay receipts for boundary-failure tests."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result


@pytest.fixture
def replay_result_factory():
    def make(request: ReplayInput, **changes: object):
        records = [json.loads(line) for line in request.normalized_bytes.splitlines()]
        document = {
            "kind": "replay_qualification_result_v1",
            "schema_version": 1,
            "engine": {
                "id": "nautilus-trader",
                "version": "1.231.0",
                "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1",
            },
            "environment": {
                "python_version": "fixture",
                "platform": "fixture",
                "package_versions": {"nautilus-trader": "1.231.0"},
            },
            "dataset_id": request.dataset_id,
            "data_sha256": hashlib.sha256(request.normalized_bytes).hexdigest(),
            "spec_id": request.spec.spec_id,
            "execution_status": "completed",
            "completeness": {
                "input_records": len(records),
                "processed_records": len(records),
                "open_orders": [],
                "pending_commands": [],
                "stop_reason": "input_exhausted",
            },
            "input_trace": [
                {
                    "kind": "fixture_input",
                    "ordinal": index,
                    "native_time_ns": record["receive_time_ns"],
                    "source_ref": {
                        "line": index + 1,
                        "capture_seq": record["capture_seq"],
                        "event_type": record["type"],
                    },
                    "fields": {},
                }
                for index, record in enumerate(records)
            ],
            "decision_trace": [],
            "order_trace": [],
            "fill_trace": [],
            "account_trace": [],
        }
        document.update(changes)
        return build_replay_result(document)

    return make


@pytest.fixture
def experiment_case(tmp_path: Path):
    """A genuine saved native fixture, never a product fake-engine switch."""
    from tickwitness.application.datasets import import_events
    from tickwitness.application.experiments import freeze_experiment
    from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
    from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
    from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore

    fixture = Path(__file__).parent / "fixtures"
    raw = (fixture / "evidence-events.jsonl").read_bytes()
    spec = json.loads((fixture / "evidence-replay-spec.json").read_bytes())
    golden = json.loads((fixture / "evidence-result.json").read_bytes())
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(raw, lambda: data).dataset_id
    snapshot = json.loads(raw.splitlines()[0])
    snapshot.update(
        capture_seq=100,
        last_sequence=100,
        event_time_ns=1700000010000000000,
        receive_time_ns=1700000010000000100,
        bids=[[101, 5], [100, 10]],
        asks=[[104, 10], [105, 10]],
    )
    confirmation = import_events((json.dumps(snapshot) + "\n").encode(), lambda: data).dataset_id
    request = {
        "schema_version": 2,
        "claim": {
            "title": "Saved native fixture",
            "hypothesis": "Net marked value exceeds minus three USD under the declared model",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "-3",
            "unit": "USD",
        },
        "replay_spec": spec,
        "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 100},
    }
    registry = LocalExecutableProtocolRegistry(tmp_path / "registry")
    frozen = freeze_experiment(
        json.dumps(request).encode(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        datasets_factory=lambda: data,
        registry_factory=lambda: registry,
    )

    class FixtureEngine:
        def run(self, replay_input: ReplayInput):
            assert (
                hashlib.sha256(replay_input.normalized_bytes).hexdigest() == golden["data_sha256"]
            )
            assert replay_input.spec.spec_id == golden["spec_id"]
            result = dict(golden, dataset_id=replay_input.dataset_id)
            return build_replay_result(result)

    return SimpleNamespace(
        root=tmp_path,
        data=data,
        registry=registry,
        frozen=frozen,
        development=development,
        confirmation=confirmation,
        request=request,
        raw=raw,
        spec=spec,
        ledger_factory=lambda: LocalAttemptLedger(tmp_path / "runs"),
        engine_factory=lambda timeout: FixtureEngine(),
    )


def synthetic_queue_result(replay_input, *, commission_override=None):
    """Native-free callback evidence for audits, never a selectable product engine.

    Build from the public input and the separately validated conservation trace.
    Money uses Decimal's explicit two-stage USD rounding; test cases avoid native
    raw-mode ambiguity unless the test supplies its own observed commission.
    """
    from decimal import ROUND_HALF_UP, Decimal

    from tickwitness.domain.replay.queue_contracts import ENGINE, build_queue_replay_result

    events = replay_input.prepared.events
    spec = replay_input.replay_input.spec.document
    settings = spec["strategy"]
    requested, limit = settings["quantity_lots"], settings["limit_price_ticks"]
    price_increment = Decimal(spec["instrument"]["price_increment"])
    size_increment = Decimal(spec["instrument"]["size_increment"])
    starting_cash = Decimal(spec["account"]["starting_cash"])
    maker = Decimal(spec["fees"]["maker_rate"])
    selected = next(
        row
        for row in replay_input.feasibility.document["interpretations"]
        if row["policy_id"] == replay_input.policy_id
    )
    transitions = {row["source_ref"]["line"]: row for row in selected["trace"]}
    document = {
        "kind": "queue_replay_result_v1",
        "schema_version": 1,
        "bindings": replay_input.bindings,
        "engine": dict(ENGINE),
        "environment": {
            "python_version": "test-fixture",
            "platform": "native-free-test-fixture",
            "package_versions": {"nautilus_trader": "1.231.0"},
        },
        "execution_status": "completed",
        "completeness": {
            "input_records": len(events),
            "processed_records": len(events),
            "open_orders": [],
            "pending_commands": [],
            "stop_reason": "input_exhausted",
        },
        "input_trace": [],
        "decision_trace": [],
        "order_trace": [],
        "fill_trace": [],
        "account_trace": [],
        "queue_trace": [],
        "hook_trace": [],
    }
    order_id = "fixture-queue-order-1"

    def record(channel, kind, event, fields, *, boundary=False):
        document[channel].append(
            {
                "kind": kind,
                "ordinal": len(document[channel]),
                "native_time_ns": event.receive_time_ns,
                "source_ref": None if boundary else event.source_ref,
                "fields": fields,
            }
        )

    def order(status, filled):
        return {
            "order_id": order_id,
            "status": status,
            "quantity_lots": requested,
            "filled_quantity_lots": filled,
            "remaining_quantity_lots": requested - filled,
        }

    def lifecycle(kind, status, event, filled, pending, acceptance=None):
        record(
            "order_trace",
            kind,
            event,
            {
                **order(status, filled),
                "event_type": kind,
                "pending_commands": pending,
                "actual_acceptance": acceptance,
            },
        )

    def account(kind, event, filled, fees, status=None, *, boundary=False, initial=False):
        cash = format(starting_cash - fees, "f")
        record(
            "account_trace",
            kind,
            event,
            {
                "account_type": "MARGIN",
                "oms_type": "NETTING",
                "currency": "USD",
                "cash_total": cash,
                "cash_free": cash,
                "cash_locked": "0",
                "net_position_lots": filled,
                "observed_fill_lots": filled,
                "observed_commission": format(fees, "f"),
                "native_money_precision": 2,
                "money_rounding_policy": "native_v1_f64_notional_then_USD_Money_precision_2",
                "cash_semantics": "native_margin_balance_not_spot_notional_debit",
                "book_type": "L2_MBP",
                "bid_levels": 0 if initial else 2,
                "ask_levels": 0 if initial else 2,
                "orders": [] if initial else [order(status, filled)],
            },
            boundary=boundary,
        )

    def decision(action, event):
        index = len(document["decision_trace"])
        record(
            "decision_trace",
            "command_issued",
            event,
            {
                "decision_ref": f"decision-{index}",
                "command_id": f"command-{index}",
                "action": action,
                "order_id": order_id,
                "strategy_kind": "single_limit_buy_cancel_at_capture_v1",
                "limit_price_ticks": limit,
                "quantity_lots": requested,
                "post_only": True,
                "cause": "selected_capture" if action == "submit" else "family_cancel_capture",
            },
        )

    account("initial_account_snapshot", events[0], 0, Decimal(0), boundary=True, initial=True)
    remaining, filled, fees, observed, state = requested, 0, Decimal(0), 0, None
    for event in events:
        record(
            "input_trace",
            "input_processed",
            event,
            {
                "aggressor_side": event.aggressor_side,
                "asks": [list(level) for level in event.asks],
                "bids": [list(level) for level in event.bids],
                "clock_policy_id": "receive_order_v1",
                "event_time_ns": event.event_time_ns,
                "receive_time_ns": event.receive_time_ns,
                "native_id_policy": "capture_seq_batch_sequence_or_CAPTURE_trade_id",
                "native_internal_id": (
                    f"CAPTURE-{event.capture_seq}"
                    if event.event_type == "trade"
                    else str(event.capture_seq)
                ),
                "native_ts_event_ns": event.receive_time_ns,
                "native_ts_init_ns": event.receive_time_ns,
                "price_ticks": event.price_ticks,
                "quantity_lots": event.quantity_lots,
                "source_clock_certified": False,
                "source_ref_semantics": "input_step_before_native_matching_and_settlement",
                "source_sequence_first": event.first_sequence,
                "source_sequence_last": event.last_sequence,
                "source_trade_id": event.trade_id,
            },
        )
        before = state
        transition = transitions.get(event.line)
        flow = {
            "additions_lots": 0,
            "cancellations_lots": 0,
            "trade_lots": 0,
            "cancel_ahead_lots": 0,
            "cancel_behind_lots": 0,
        }
        if transition is not None:
            flow, state = transition["flow"], transition["after"]
        for price, quantity in event.bids:
            if price == limit:
                observed = quantity
        capacity = 0
        if event.event_type == "trade":
            capacity = min(remaining, max(0, event.quantity_lots - before["ahead_lots"]))
            document["hook_trace"].append(
                {
                    "source_ref": event.source_ref,
                    "origin": "native_public_fill_simulation_hook",
                    "offered_lots": capacity,
                    "cumulative_granted_lots": capacity,
                }
            )
        filled += capacity
        remaining -= capacity
        document["queue_trace"].append(
            {
                "source_ref": event.source_ref,
                "receive_time_ns": event.receive_time_ns,
                "market_observed_lots": observed,
                "before": before,
                "after": state,
                "flow": flow,
                "grant_limit_lots": capacity,
                "granted_lots": capacity,
                "native_filled_lots": capacity,
                "own_remaining_lots": remaining,
                "accepted_here": event.line == 1,
            }
        )
        if event.line == 1:
            decision("submit", event)
            lifecycle("OrderInitialized", "INITIALIZED", event, 0, ["command-0"])
            lifecycle("OrderSubmitted", "SUBMITTED", event, 0, ["command-0"])
            lifecycle(
                "OrderAccepted",
                "ACCEPTED",
                event,
                0,
                [],
                {"native_bid_lots": observed, "queue": state, "target_price_ticks": limit},
            )
        if capacity:
            price = Decimal(limit) * price_increment
            quantity = Decimal(capacity) * size_increment
            notional = (price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            commission = (notional * maker).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if commission_override is not None:
                commission = Decimal(commission_override)
            fees += commission
            status = "FILLED" if not remaining else "PARTIALLY_FILLED"
            lifecycle("OrderFilled", status, event, filled, [])
            record(
                "fill_trace",
                "OrderFilled",
                event,
                {
                    "order_id": order_id,
                    "native_trade_id": f"fixture-native-trade-{event.capture_seq}",
                    "price_ticks": limit,
                    "quantity_lots": capacity,
                    "price": format(price, "f"),
                    "quantity": format(quantity, "f"),
                    "commission": format(commission, "f"),
                    "commission_currency": "USD",
                    "liquidity_side": "MAKER",
                },
            )
            account("fill_callback_account_snapshot", event, filled, fees, status)
        if (
            event.capture_seq == replay_input.family.document["strategy"]["cancel_at_capture_seq"]
            and remaining
        ):
            decision("cancel", event)
            lifecycle("OrderPendingCancel", "PENDING_CANCEL", event, filled, ["command-1"])
            lifecycle("OrderCanceled", "CANCELED", event, filled, [])
    account(
        "final_account_snapshot",
        events[-1],
        filled,
        fees,
        "CANCELED" if remaining else "FILLED",
        boundary=True,
    )
    return build_queue_replay_result(document)


@pytest.fixture
def queue_result_factory():
    return synthetic_queue_result
