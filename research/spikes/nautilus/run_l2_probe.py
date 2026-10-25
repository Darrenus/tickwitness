"""Bounded offline NautilusTrader 1.231.0 L2/partial/EOF selection probes.

Original synthetic data, trusted local strategy, no live adapter or network.
This does not implement exact cancellation-world witnesses or a product adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from decimal import Decimal
from pathlib import Path

import nautilus_trader
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, LatencyModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import EUR, USD
from nautilus_trader.model.data import BookOrder, OrderBookDelta, OrderBookDeltas, TradeTick
from nautilus_trader.model.enums import (
    AccountType,
    AggressorSide,
    BookAction,
    BookType,
    OmsType,
    OrderSide,
    RecordFlag,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TradeId, TraderId, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy

VERSION = "1.231.0"
IID = InstrumentId.from_str("EURUSD.SIM")
VENUE = Venue("SIM")
BASE = 1_700_000_000_000_000_000
SECOND = 1_000_000_000
START_CASH = Decimal("10000.00")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def make_instrument() -> CurrencyPair:
    return CurrencyPair(
        instrument_id=IID,
        raw_symbol=Symbol("EURUSD"),
        base_currency=EUR,
        quote_currency=USD,
        price_precision=2,
        size_precision=0,
        price_increment=Price.from_str("1.00"),
        size_increment=Quantity.from_int(1),
        lot_size=Quantity.from_int(1),
        min_quantity=Quantity.from_int(1),
        margin_init=Decimal("1"),
        margin_maint=Decimal("1"),
        maker_fee=Decimal("0.01"),
        taker_fee=Decimal("0.02"),
        ts_event=BASE,
        ts_init=BASE,
    )


def delta(
    offset: int,
    sequence: int,
    side: OrderSide,
    price: str,
    size: int,
    action: BookAction = BookAction.UPDATE,
    snapshot: bool = False,
) -> OrderBookDelta:
    flags = int(RecordFlag.F_LAST)
    if snapshot:
        flags |= int(RecordFlag.F_SNAPSHOT)
    return OrderBookDelta(
        instrument_id=IID,
        action=action,
        order=BookOrder(side, Price.from_str(price), Quantity.from_int(size), sequence),
        flags=flags,
        sequence=sequence,
        ts_event=BASE + offset,
        ts_init=BASE + offset,
    )


def book(offset: int, sequence: int, bid_size: int = 1) -> OrderBookDeltas:
    values = [OrderBookDelta.clear(IID, sequence, BASE + offset, BASE + offset)]
    for index, (side, price, size) in enumerate(
        [
            (OrderSide.BUY, "100.00", bid_size),
            (OrderSide.BUY, "99.00", 10),
            (OrderSide.SELL, "103.00", 10),
            (OrderSide.SELL, "104.00", 10),
        ]
    ):
        item = delta(offset, sequence + index + 1, side, price, size, BookAction.ADD, True)
        # A single snapshot batch ends only at the final level.
        if index != 3:
            item = OrderBookDelta(
                IID,
                BookAction.ADD,
                item.order,
                int(RecordFlag.F_SNAPSHOT),
                item.sequence,
                item.ts_event,
                item.ts_init,
            )
        values.append(item)
    return OrderBookDeltas(IID, values)


def update(offset: int, sequence: int, size: int) -> OrderBookDeltas:
    return OrderBookDeltas(IID, [delta(offset, sequence, OrderSide.BUY, "100.00", size)])


def trade(offset: int, ordinal: int, size: int) -> TradeTick:
    return TradeTick(
        IID,
        Price.from_str("100.00"),
        Quantity.from_int(size),
        AggressorSide.SELLER,
        TradeId(f"SOURCE-TRADE-{ordinal}"),
        BASE + offset,
        BASE + offset,
    )


def make_data(case_id: str) -> list:
    if case_id.startswith("eof-"):
        data = [book(0, 1), update(3 * SECOND, 6, 1)]
        if case_id == "eof-with-later-data":
            data.append(update(6 * SECOND, 7, 1))
        return data
    same = case_id in ("partial-same-time", "cancel-zero-same-time", "cancel-delayed-same-time")
    second_time = SECOND if same else 2 * SECOND
    return [
        book(0, 1),
        update(SECOND // 2, 6, 4),
        trade(SECOND, 1, 2),
        update(SECOND + (0 if same else 1), 7, 2),
        trade(second_time, 2, 1),
        update(second_time + (0 if same else 1), 8, 1),
        update(3 * SECOND, 9, 1),
    ]


def data_row(value: object) -> dict:
    common = {
        "type": type(value).__name__,
        "ts_event": str(value.ts_event),
        "ts_init": str(value.ts_init),
    }
    if isinstance(value, TradeTick):
        return dict(
            common,
            price=str(value.price),
            size=str(value.size),
            aggressor_side=value.aggressor_side.name,
            trade_id=str(value.trade_id),
        )
    return dict(
        common,
        deltas=[
            {
                "action": item.action.name,
                "side": item.order.side.name,
                "price": str(item.order.price),
                "size": str(item.order.size),
                "flags": item.flags,
                "sequence": item.sequence,
            }
            for item in value.deltas
        ],
    )


class L2Probe(Strategy):
    def __init__(self, case_id: str) -> None:
        super().__init__(
            StrategyConfig(
                strategy_id="L2Probe-001",
                order_id_tag="001",
                use_uuid_client_order_ids=False,
                log_events=False,
                log_commands=False,
            )
        )
        self.case_id = case_id
        self.timeline: list[dict] = []
        self.fills: list[dict] = []
        self.decisions: list[dict] = []
        self.submitted = False
        self.cancel_sent = False

    def state(self) -> dict:
        account = self.cache.account_for_venue(VENUE)
        cached_book = self.cache.order_book(IID)
        positions = [p for p in self.cache.positions() if p.instrument_id == IID]
        net = sum(
            (
                Decimal(str(p.quantity)) * (1 if p.side.name == "LONG" else -1)
                for p in positions
                if not p.is_closed
            ),
            Decimal("0"),
        )
        order_rows = [
            {
                "client_order_id": str(o.client_order_id),
                "status": o.status.name,
                "quantity": str(o.quantity),
                "filled_qty": str(o.filled_qty),
                "leaves_qty": str(o.leaves_qty),
            }
            for o in self.cache.orders()
        ]
        commission = sum((Decimal(f["commission_amount"]) for f in self.fills), Decimal("0"))
        return {
            "clock_ns": str(self.clock.timestamp_ns()),
            "net_position_from_cache": str(net),
            "cached_book_type": None if cached_book is None else cached_book.book_type.name,
            "cached_bid_levels": 0 if cached_book is None else len(cached_book.bids()),
            "cached_ask_levels": 0 if cached_book is None else len(cached_book.asks()),
            "cash_total_usd": None
            if account is None
            else str(account.balance_total(USD).as_decimal()),
            "cash_free_usd": None
            if account is None
            else str(account.balance_free(USD).as_decimal()),
            "cash_locked_usd": None
            if account is None
            else str(account.balance_locked(USD).as_decimal()),
            "observed_fill_qty": str(
                sum((Decimal(f["quantity"]) for f in self.fills), Decimal("0"))
            ),
            "observed_commission_usd": str(commission),
            "orders": order_rows,
        }

    def record(self, stage: str, event: object | None = None) -> None:
        value = {"stage": stage, "state": self.state()}
        if event is not None:
            value["event_type"] = type(event).__name__
            value["event_ts_ns"] = str(event.ts_event)
        self.timeline.append(value)

    def on_start(self) -> None:
        self.subscribe_order_book_deltas(IID, book_type=BookType.L2_MBP)
        self.subscribe_trade_ticks(IID)

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        self.record("on_order_book_deltas", deltas)
        if self.submitted:
            return
        if self.case_id.startswith("eof-"):
            if deltas.ts_init != BASE + 3 * SECOND:
                return
            order = self.order_factory.market(IID, OrderSide.BUY, Quantity.from_int(1))
        else:
            order = self.order_factory.limit(
                IID, OrderSide.BUY, Quantity.from_int(2), Price.from_str("100.00"), post_only=True
            )
        self.submitted = True
        self.decisions.append(
            {
                "action": "submit",
                "clock_ns": str(self.clock.timestamp_ns()),
                "order_type": order.order_type.name,
                "client_order_id": str(order.client_order_id),
            }
        )
        self.submit_order(order)

    def on_trade_tick(self, tick: TradeTick) -> None:
        self.record("on_trade_tick", tick)

    def on_order_event(self, event: object) -> None:
        self.record("on_order_event", event)

    def on_order_filled(self, event: object) -> None:
        self.fills.append(
            {
                "client_order_id": str(event.client_order_id),
                "fill_ordinal": len(self.fills) + 1,
                "trade_id": str(event.trade_id),
                "quantity": str(event.last_qty),
                "price": str(event.last_px),
                "commission": str(event.commission),
                "commission_amount": str(event.commission.as_decimal()),
                "liquidity_side": event.liquidity_side.name,
                "ts_event": str(event.ts_event),
                "ts_init": str(event.ts_init),
            }
        )
        self.record("on_order_filled", event)
        if self.case_id.startswith("cancel-") and not self.cancel_sent:
            order = self.cache.order(event.client_order_id)
            if not order.is_closed:
                self.cancel_sent = True
                self.decisions.append(
                    {
                        "action": "cancel_after_first_fill",
                        "clock_ns": str(self.clock.timestamp_ns()),
                        "client_order_id": str(event.client_order_id),
                    }
                )
                self.cancel_order(order)

    def on_position_opened(self, event: object) -> None:
        self.record("on_position_opened", event)

    def on_position_changed(self, event: object) -> None:
        self.record("on_position_changed", event)

    def on_stop(self) -> None:
        self.record("on_stop")


def run_case(case_id: str) -> dict:
    delayed_cancel = SECOND if case_id == "cancel-delayed-same-time" else 0
    insert_delay = 2 * SECOND if case_id.startswith("eof-") else 0
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("L2PROBE-001"),
            logging=LoggingConfig(bypass_logging=True),
            run_analysis=False,
        )
    )
    strategy = L2Probe(case_id)
    inputs = make_data(case_id)
    config = {
        "book_type": "L2_MBP",
        "queue_position": True,
        "trade_execution": True,
        "liquidity_consumption": True,
        "use_message_queue": True,
        "insert_latency_ns": str(insert_delay),
        "cancel_latency_ns": str(delayed_cancel),
        "account_type": "MARGIN",
        "maker_fee_rate": "0.01",
        "taker_fee_rate": "0.02",
    }
    try:
        engine.add_venue(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USD,
            starting_balances=[Money(START_CASH, USD)],
            default_leverage=Decimal("1"),
            book_type=BookType.L2_MBP,
            fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=7),
            latency_model=LatencyModel(
                base_latency_nanos=0,
                insert_latency_nanos=insert_delay,
                cancel_latency_nanos=delayed_cancel,
            ),
            use_message_queue=True,
            use_random_ids=False,
            trade_execution=True,
            bar_execution=False,
            queue_position=True,
            liquidity_consumption=True,
        )
        engine.add_instrument(make_instrument())
        engine.add_data(inputs)
        engine.add_strategy(strategy)
        engine.run()
        final = strategy.state()
        fill_callbacks = [r for r in strategy.timeline if r["stage"] == "on_order_filled"]
        expected_fills = {
            "partial-separated": 2,
            "partial-same-time": 2,
            "cancel-zero-same-time": 1,
            "cancel-delayed-same-time": 2,
            "eof-no-future-data": 0,
            "eof-with-later-data": 1,
        }[case_id]
        has_unresolved_commands = any(
            o["status"] in ("SUBMITTED", "INITIALIZED", "PENDING_UPDATE", "PENDING_CANCEL")
            for o in final["orders"]
        )
        return {
            "case_id": case_id,
            "execution_status": "EXECUTED",
            "config": config,
            "expectations": {
                "fill_callback_count_for_fixed_fixture": expected_fills,
                "eof_autonomous_drain_not_assumed": case_id.startswith("eof-"),
            },
            "input_trace": [data_row(item) for item in inputs],
            "decisions": strategy.decisions,
            "fills": strategy.fills,
            "timeline": strategy.timeline,
            "final_state": final,
            "checks": {
                "fill_callbacks_evaluated": len(fill_callbacks),
                "fill_count_matches_fixture_expectation": len(strategy.fills) == expected_fills,
                "per_fill_commission_matches_declared_rate": all(
                    Decimal(f["commission_amount"])
                    == Decimal(f["quantity"])
                    * Decimal(f["price"])
                    * (Decimal("0.01") if f["liquidity_side"] == "MAKER" else Decimal("0.02"))
                    for f in strategy.fills
                ),
                "callback_position_matches_observed_fills": all(
                    Decimal(r["state"]["net_position_from_cache"])
                    == Decimal(r["state"]["observed_fill_qty"])
                    for r in fill_callbacks
                )
                if fill_callbacks
                else None,
                "callback_cash_matches_margin_fees": all(
                    Decimal(r["state"]["cash_total_usd"])
                    == START_CASH - Decimal(r["state"]["observed_commission_usd"])
                    for r in fill_callbacks
                )
                if fill_callbacks
                else None,
                "final_position_matches_observed_fills": Decimal(final["net_position_from_cache"])
                == Decimal(final["observed_fill_qty"]),
                "final_cash_matches_margin_fees": Decimal(final["cash_total_usd"])
                == START_CASH - Decimal(final["observed_commission_usd"]),
                "exact_front_back_witnesses_verified": False,
            },
            "completeness": {
                "last_input_time_ns": str(max(item.ts_init for item in inputs)),
                "has_unresolved_order_commands_at_end": has_unresolved_commands,
                "label": "INCOMPLETE_AT_DATA_END"
                if has_unresolved_commands
                else "FIXTURE_ORDER_TERMINAL",
                "note": "Engine run returned; this does not certify universal inflight drain.",
            },
        }
    except Exception as exc:
        return {
            "case_id": case_id,
            "execution_status": "ERROR",
            "exception": repr(exc),
            "config": config,
            "input_trace": [data_row(item) for item in inputs],
            "timeline": strategy.timeline,
            "fills": strategy.fills,
        }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if nautilus_trader.__version__ != VERSION:
        raise RuntimeError("This probe requires stable v1 nautilus-trader==1.231.0")
    cases = [
        run_case(name)
        for name in (
            "partial-separated",
            "partial-same-time",
            "cancel-zero-same-time",
            "cancel-delayed-same-time",
            "eof-no-future-data",
            "eof-with-later-data",
        )
    ]
    package = Path(nautilus_trader.__file__).parent
    payload = {
        "schema": "nautilus-v1-l2-selection-v1",
        "engine_version": VERSION,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "package_license_expression": importlib.metadata.metadata("nautilus_trader").get(
                "License-Expression"
            ),
            "source_hashes": {
                name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                for name in ("backtest/engine.pyx", "model/data.pyx")
            },
        },
        "normalization": [
            "Random event UUIDs, engine run/instance IDs, wall-clock time omitted.",
            "Synthetic event times, event ordering, prices, quantities and cash preserved.",
        ],
        "scope": "Synthetic L2 deltas + TradeTick; no QuoteTick, v2 API or live execution.",
        "cases": cases,
        "limits": [
            "No exact front/back cancellation-world certificate.",
            "Margin cash is not debited by opening notional; fees are separate from margin lock.",
            "No third-party source or binary modified; no upstream reports sent.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        json.dumps(
            [
                {
                    "case_id": c["case_id"],
                    "status": c["execution_status"],
                    "fills": c.get("fills"),
                    "final": c.get("final_state"),
                    "checks": c.get("checks"),
                    "error": c.get("exception"),
                }
                for c in cases
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
