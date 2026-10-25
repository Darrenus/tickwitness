"""Private v1 native bridge. Imported only by the preflighted optional adapter.

``Any`` is confined to this file's Cython API boundary: no native object enters a
domain DTO or the returned JSON. Native classes are loaded dynamically so core
validation, CLI help, and domain imports do not require a native installation.
"""

from __future__ import annotations

import importlib
import platform
from dataclasses import dataclass
from decimal import Decimal
from importlib import metadata
from types import SimpleNamespace
from typing import Any, cast

from tickwitness.domain.replay.contracts import PreparedReplay, ReplayEvent
from tickwitness.infrastructure.nautilus_replay import ENGINE_ID, ENGINE_VERSION, SEMANTIC_ID


def _native_api() -> SimpleNamespace:
    names = {
        "backtest.engine": ["BacktestEngine"],
        "backtest.models": ["FillModel", "LatencyModel"],
        "backtest.modules": ["SimulationModule"],
        "backtest.config": ["SimulationModuleConfig"],
        "config": ["BacktestEngineConfig", "LoggingConfig", "StrategyConfig"],
        "model.currencies": ["EUR", "USD"],
        "model.data": ["BookOrder", "OrderBookDelta", "OrderBookDeltas", "TradeTick"],
        "model.enums": [
            "AccountType",
            "AggressorSide",
            "BookAction",
            "BookType",
            "OmsType",
            "OrderSide",
            "RecordFlag",
        ],
        "model.identifiers": ["InstrumentId", "Symbol", "TradeId", "TraderId", "Venue"],
        "model.instruments": ["CurrencyPair"],
        "model.objects": ["Money", "Price", "Quantity"],
        "trading.strategy": ["Strategy"],
    }
    api = SimpleNamespace()
    for suffix, symbols in names.items():
        module = importlib.import_module("nautilus_trader." + suffix)
        for name in symbols:
            setattr(api, name, getattr(module, name))
    return api


def _decimal(value: Decimal) -> str:
    """Non-exponent exact text, preserving declared or native decimal precision."""
    return format(value, "f")


def _units(value: Any, increment: Decimal) -> int:
    mapped = Decimal(str(value)) / increment
    if mapped != mapped.to_integral_value():
        raise ValueError("Native value is not an exact multiple of the declared increment")
    return int(mapped)


def _precision(increment: Decimal) -> int:
    exponent = increment.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("Non-finite native increment")
    return -exponent


@dataclass(frozen=True, slots=True)
class _Settings:
    price_increment: Decimal
    size_increment: Decimal
    starting_cash: Decimal
    maker_rate: Decimal
    taker_rate: Decimal
    insert_latency: int
    cancel_latency: int
    submit_capture_seq: int
    limit_price_ticks: int
    quantity_lots: int
    cancel_after_first_fill: bool
    seed: int

    @classmethod
    def from_prepared(cls, prepared: PreparedReplay) -> _Settings:
        document = prepared.spec.document
        instrument = cast("dict[str, str]", document["instrument"])
        account = cast("dict[str, str]", document["account"])
        fees = cast("dict[str, str]", document["fees"])
        execution = cast("dict[str, int]", document["execution"])
        strategy = cast("dict[str, object]", document["strategy"])
        return cls(
            Decimal(instrument["price_increment"]),
            Decimal(instrument["size_increment"]),
            Decimal(account["starting_cash"]),
            Decimal(fees["maker_rate"]),
            Decimal(fees["taker_rate"]),
            execution["insert_latency_ns"],
            execution["cancel_latency_ns"],
            cast("int", strategy["submit_capture_seq"]),
            cast("int", strategy["limit_price_ticks"]),
            cast("int", strategy["quantity_lots"]),
            cast("bool", strategy["cancel_after_first_fill"]),
            cast("int", document["seed"]),
        )


class _Evidence:
    def __init__(self, prepared: PreparedReplay, settings: _Settings, api: SimpleNamespace) -> None:
        self.prepared = prepared
        self.settings = settings
        self.api = api
        self.current: ReplayEvent | None = None
        self.processed = 0
        self.failure: Exception | None = None
        self.pending: dict[str, dict[str, object]] = {}
        self.traces: dict[str, list[dict[str, object]]] = {
            channel: []
            for channel in (
                "input_trace",
                "decision_trace",
                "order_trace",
                "fill_trace",
                "account_trace",
            )
        }
        self.commission = Decimal("0")
        self.filled_lots = 0
        self.iid = api.InstrumentId.from_str("EURUSD.SIM")
        self.venue = api.Venue("SIM")

    def record(
        self, channel: str, kind: str, now: int, fields: dict[str, object], *, final: bool = False
    ) -> None:
        self.traces[channel].append(
            {
                "kind": kind,
                "ordinal": len(self.traces[channel]),
                "native_time_ns": now,
                "source_ref": None if final or self.current is None else self.current.source_ref,
                "fields": fields,
            }
        )

    def begin_input(self, native: Any) -> None:
        """Public pre_process hook runs before matching and strategy market callbacks."""
        if self.processed >= len(self.prepared.events):
            raise ValueError("Native engine processed unexpected additional input")
        event = self.prepared.events[self.processed]
        internal_id = str(native.trade_id) if event.event_type == "trade" else str(native.sequence)
        expected_id = (
            f"CAPTURE-{event.capture_seq}"
            if event.event_type == "trade"
            else str(event.capture_seq)
        )
        if internal_id != expected_id or native.ts_init != event.receive_time_ns:
            raise ValueError("Native input order/identity differs from the prepared capture order")
        self.current = event
        self.processed += 1
        self.record(
            "input_trace",
            "input_processed",
            event.receive_time_ns,
            {
                "event_time_ns": event.event_time_ns,
                "receive_time_ns": event.receive_time_ns,
                "native_ts_event_ns": native.ts_event,
                "native_ts_init_ns": native.ts_init,
                "clock_policy_id": "receive_order_v1",
                "source_clock_certified": False,
                "source_sequence_first": event.first_sequence,
                "source_sequence_last": event.last_sequence,
                "source_trade_id": event.trade_id,
                "native_internal_id": internal_id,
                "native_id_policy": "capture_seq_batch_sequence_or_CAPTURE_trade_id",
                "bids": [list(level) for level in event.bids],
                "asks": [list(level) for level in event.asks],
                "price_ticks": event.price_ticks,
                "quantity_lots": event.quantity_lots,
                "aggressor_side": event.aggressor_side,
                "source_ref_semantics": "input_step_before_native_matching_and_settlement",
            },
        )

    def command(self, action: str, order: Any, now: int) -> None:
        if self.current is None:
            raise ValueError("Built-in strategy command requires an input context")
        ordinal = len(self.traces["decision_trace"])
        decision_ref, command_id = f"decision-{ordinal}", f"command-{ordinal}"
        order_id = str(order.client_order_id)
        row: dict[str, object] = {
            "command_id": command_id,
            "order_id": order_id,
            "command_type": action,
            "decision_ref": decision_ref,
            "source_ref": self.current.source_ref,
        }
        self.pending[command_id] = row
        self.record(
            "decision_trace",
            "command_issued",
            now,
            {
                "decision_ref": decision_ref,
                "command_id": command_id,
                "action": action,
                "order_id": order_id,
                "strategy_kind": "single_limit_buy_v1",
                "limit_price_ticks": self.settings.limit_price_ticks,
                "quantity_lots": self.settings.quantity_lots,
                "post_only": True,
                "cause": "selected_capture" if action == "submit" else "first_partial_fill",
            },
        )

    def acknowledge(self, event: Any) -> None:
        name, order_id = type(event).__name__, str(event.client_order_id)
        # FILLED acknowledges submission, never an outstanding cancellation receipt.
        action = (
            "submit"
            if name in ("OrderAccepted", "OrderRejected", "OrderDenied", "OrderFilled")
            else "cancel"
            if name in ("OrderCanceled", "OrderCancelRejected")
            else None
        )
        if action is not None:
            for key, command in list(self.pending.items()):
                if command["order_id"] == order_id and command["command_type"] == action:
                    del self.pending[key]

    def state(self, strategy: Any) -> dict[str, object]:
        account = strategy.cache.account_for_venue(self.venue)
        if account is None:
            raise ValueError("Native margin account is unavailable")
        net = sum(
            (
                Decimal(str(position.quantity)) * (1 if position.side.name == "LONG" else -1)
                for position in strategy.cache.positions()
                if position.instrument_id == self.iid and not position.is_closed
            ),
            Decimal("0"),
        )
        book = strategy.cache.order_book(self.iid)
        orders = [
            {
                "order_id": str(order.client_order_id),
                "status": order.status.name,
                "quantity_lots": _units(order.quantity, self.settings.size_increment),
                "filled_quantity_lots": _units(order.filled_qty, self.settings.size_increment),
                "remaining_quantity_lots": _units(order.leaves_qty, self.settings.size_increment),
            }
            for order in strategy.cache.orders()
        ]
        return {
            "account_type": "MARGIN",
            "oms_type": "NETTING",
            "currency": "USD",
            "cash_total": _decimal(account.balance_total(self.api.USD).as_decimal()),
            "cash_free": _decimal(account.balance_free(self.api.USD).as_decimal()),
            "cash_locked": _decimal(account.balance_locked(self.api.USD).as_decimal()),
            "net_position_lots": _units(net, self.settings.size_increment),
            "observed_fill_lots": self.filled_lots,
            "observed_commission": _decimal(self.commission),
            "native_money_precision": 2,
            "money_rounding_policy": "native_v1_f64_notional_then_USD_Money_precision_2",
            "cash_semantics": "native_margin_balance_not_spot_notional_debit",
            "book_type": None if book is None else book.book_type.name,
            "bid_levels": 0 if book is None else len(book.bids()),
            "ask_levels": 0 if book is None else len(book.asks()),
            "orders": orders,
        }

    def account(self, strategy: Any, kind: str, *, final: bool = False) -> None:
        self.record(
            "account_trace", kind, strategy.clock.timestamp_ns(), self.state(strategy), final=final
        )

    def result(self, strategy: Any) -> dict[str, object]:
        if self.failure is not None:
            raise self.failure
        if self.processed != len(self.prepared.events):
            raise ValueError("Native engine did not process every prepared input")
        submissions = [
            row
            for row in self.traces["decision_trace"]
            if cast("dict[str, object]", row["fields"])["action"] == "submit"
        ]
        if len(submissions) != 1 or len(strategy.cache.orders()) != 1:
            raise ValueError("Built-in single-order execution did not produce exactly one order")
        self.account(strategy, "final_account_snapshot", final=True)
        open_orders = [
            {"order_id": str(order.client_order_id), "status": order.status.name}
            for order in strategy.cache.orders()
            if not order.is_closed
        ]
        pending = list(self.pending.values())
        reason = (
            "pending_commands_at_data_end"
            if pending
            else "input_exhausted_with_open_orders"
            if open_orders
            else "input_exhausted"
        )
        packages: dict[str, str] = {}
        for name in ("nautilus_trader", "numpy", "pandas", "msgspec", "pyarrow", "pytz"):
            packages[name] = metadata.version(name)
        return {
            "kind": "replay_qualification_result_v1",
            "schema_version": 1,
            "engine": {"id": ENGINE_ID, "version": ENGINE_VERSION, "semantic_id": SEMANTIC_ID},
            "environment": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "package_versions": packages,
            },
            "dataset_id": self.prepared.dataset_id,
            "data_sha256": self.prepared.data_sha256,
            "spec_id": self.prepared.spec.spec_id,
            "execution_status": "incomplete" if pending or open_orders else "completed",
            "completeness": {
                "input_records": len(self.prepared.events),
                "processed_records": self.processed,
                "open_orders": open_orders,
                "pending_commands": pending,
                "stop_reason": reason,
            },
            **self.traces,
        }


def _make_data(evidence: _Evidence) -> list[Any]:
    api, settings = evidence.api, evidence.settings
    values: list[Any] = []
    for event in evidence.prepared.events:
        now, sequence = event.receive_time_ns, event.capture_seq
        if event.event_type == "trade":
            assert event.price_ticks is not None and event.quantity_lots is not None
            values.append(
                api.TradeTick(
                    evidence.iid,
                    api.Price.from_str(_decimal(event.price_ticks * settings.price_increment)),
                    api.Quantity.from_str(_decimal(event.quantity_lots * settings.size_increment)),
                    api.AggressorSide.BUYER
                    if event.aggressor_side == "buy"
                    else api.AggressorSide.SELLER,
                    api.TradeId(f"CAPTURE-{sequence}"),
                    now,
                    now,
                )
            )
            continue
        snapshot = event.event_type == "snapshot"
        deltas: list[Any] = []
        if snapshot:
            deltas.append(api.OrderBookDelta.clear(evidence.iid, sequence, now, now))
        levels = [(api.OrderSide.BUY, price, size) for price, size in event.bids]
        levels += [(api.OrderSide.SELL, price, size) for price, size in event.asks]
        for index, (side, price, size) in enumerate(levels):
            flags = int(api.RecordFlag.F_SNAPSHOT) if snapshot else 0
            if index == len(levels) - 1:
                flags |= int(api.RecordFlag.F_LAST)
            action = (
                api.BookAction.ADD
                if snapshot
                else api.BookAction.UPDATE
                if size
                else (api.BookAction.DELETE)
            )
            deltas.append(
                api.OrderBookDelta(
                    evidence.iid,
                    action,
                    api.BookOrder(
                        side,
                        api.Price.from_str(_decimal(price * settings.price_increment)),
                        api.Quantity.from_str(_decimal(size * settings.size_increment)),
                        0,
                    ),
                    flags,
                    sequence,
                    now,
                    now,
                )
            )
        values.append(api.OrderBookDeltas(evidence.iid, deltas))
    return values


def run_native(prepared: PreparedReplay) -> dict[str, object]:
    """Execute the trusted fixed strategy once; no streaming restart or EOF guard data."""
    api = _native_api()
    settings = _Settings.from_prepared(prepared)
    evidence = _Evidence(prepared, settings, api)
    module_base, strategy_base = api.SimulationModule, api.Strategy

    class SourceContext(module_base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(api.SimulationModuleConfig())

        def pre_process(self, data: Any) -> None:
            try:
                evidence.begin_input(data)
            except Exception as error:
                evidence.failure = error
                raise

        def process(self, ts_now: int) -> None:
            pass

        def log_diagnostics(self, logger: Any) -> None:
            pass

        def reset(self) -> None:
            pass

    class SingleLimitBuy(strategy_base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(
                api.StrategyConfig(
                    strategy_id="TickWitness-001",
                    order_id_tag="001",
                    use_uuid_client_order_ids=False,
                    log_events=False,
                    log_commands=False,
                )
            )
            self.submitted = False
            self.cancel_sent = False

        def on_start(self) -> None:
            try:
                self.subscribe_order_book_deltas(evidence.iid, book_type=api.BookType.L2_MBP)
                self.subscribe_trade_ticks(evidence.iid)
                evidence.account(self, "initial_account_snapshot", final=True)
            except Exception as error:
                evidence.failure = error
                raise

        def maybe_submit(self) -> None:
            current = evidence.current
            if (
                self.submitted
                or current is None
                or current.capture_seq != settings.submit_capture_seq
            ):
                return
            try:
                self.submitted = True
                order = self.order_factory.limit(
                    evidence.iid,
                    api.OrderSide.BUY,
                    api.Quantity.from_str(
                        _decimal(settings.quantity_lots * settings.size_increment)
                    ),
                    api.Price.from_str(
                        _decimal(settings.limit_price_ticks * settings.price_increment)
                    ),
                    post_only=True,
                )
                evidence.command("submit", order, self.clock.timestamp_ns())
                self.submit_order(order)
            except Exception as error:
                evidence.failure = error
                raise

        def on_order_book_deltas(self, deltas: Any) -> None:
            self.maybe_submit()

        def on_trade_tick(self, tick: Any) -> None:
            self.maybe_submit()

        def on_order_event(self, event: Any) -> None:
            try:
                evidence.acknowledge(event)
                order = self.cache.order(event.client_order_id)
                fields: dict[str, object] = {
                    "order_id": str(event.client_order_id),
                    "status": None if order is None else order.status.name,
                    "native_event_ts_ns": event.ts_event,
                    "native_init_ts_ns": event.ts_init,
                    "pending_command_ids": list(evidence.pending),
                }
                if hasattr(event, "reason"):
                    fields["reason"] = str(event.reason)
                evidence.record(
                    "order_trace", type(event).__name__, self.clock.timestamp_ns(), fields
                )
            except Exception as error:
                evidence.failure = error
                raise

        def on_order_filled(self, event: Any) -> None:
            try:
                evidence.acknowledge(event)
                lots = _units(event.last_qty, settings.size_increment)
                evidence.filled_lots += lots
                evidence.commission += event.commission.as_decimal()
                rate = (
                    settings.maker_rate
                    if event.liquidity_side.name == "MAKER"
                    else settings.taker_rate
                )
                unrounded_fee = Decimal(str(event.last_px)) * Decimal(str(event.last_qty)) * rate
                evidence.record(
                    "fill_trace",
                    "OrderFilled",
                    self.clock.timestamp_ns(),
                    {
                        "order_id": str(event.client_order_id),
                        "native_trade_id": str(event.trade_id),
                        "price_ticks": _units(event.last_px, settings.price_increment),
                        "quantity_lots": lots,
                        "price": str(event.last_px),
                        "quantity": str(event.last_qty),
                        "commission": _decimal(event.commission.as_decimal()),
                        "commission_currency": str(event.commission.currency),
                        "declared_fee_rate": _decimal(rate),
                        "exact_decimal_fee_before_native_quantization": _decimal(unrounded_fee),
                        "native_commission_minus_exact_decimal_fee": _decimal(
                            event.commission.as_decimal() - unrounded_fee
                        ),
                        "native_fee_policy": (
                            "v1_MakerTakerFeeModel_f64_notional_USD_Money_precision_2"
                        ),
                        "liquidity_side": event.liquidity_side.name,
                        "native_event_ts_ns": event.ts_event,
                        "native_init_ts_ns": event.ts_init,
                        "source_ref_semantics": "input_step_before_native_matching_and_settlement",
                    },
                )
                evidence.account(self, "fill_callback_account_snapshot")
                if settings.cancel_after_first_fill and not self.cancel_sent:
                    order = self.cache.order(event.client_order_id)
                    if order is not None and not order.is_closed:
                        self.cancel_sent = True
                        evidence.command("cancel", order, self.clock.timestamp_ns())
                        self.cancel_order(order)
            except Exception as error:
                evidence.failure = error
                raise

    engine = api.BacktestEngine(
        config=api.BacktestEngineConfig(
            trader_id=api.TraderId("TICKWITNESS-001"),
            logging=api.LoggingConfig(bypass_logging=True),
            run_analysis=False,
        )
    )
    try:
        engine.add_venue(
            venue=evidence.venue,
            oms_type=api.OmsType.NETTING,
            account_type=api.AccountType.MARGIN,
            base_currency=api.USD,
            starting_balances=[api.Money.from_str(_decimal(settings.starting_cash) + " USD")],
            default_leverage=Decimal("1"),
            book_type=api.BookType.L2_MBP,
            modules=[SourceContext()],
            fill_model=api.FillModel(
                prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=settings.seed
            ),
            latency_model=api.LatencyModel(
                base_latency_nanos=0,
                insert_latency_nanos=settings.insert_latency,
                cancel_latency_nanos=settings.cancel_latency,
            ),
            use_message_queue=True,
            use_random_ids=False,
            trade_execution=True,
            bar_execution=False,
            queue_position=True,
            liquidity_consumption=True,
        )
        now = prepared.events[0].receive_time_ns
        engine.add_instrument(
            api.CurrencyPair(
                instrument_id=evidence.iid,
                raw_symbol=api.Symbol("EURUSD"),
                base_currency=api.EUR,
                quote_currency=api.USD,
                price_precision=_precision(settings.price_increment),
                size_precision=_precision(settings.size_increment),
                price_increment=api.Price.from_str(_decimal(settings.price_increment)),
                size_increment=api.Quantity.from_str(_decimal(settings.size_increment)),
                lot_size=api.Quantity.from_str(_decimal(settings.size_increment)),
                min_quantity=api.Quantity.from_str(_decimal(settings.size_increment)),
                margin_init=Decimal("1"),
                margin_maint=Decimal("1"),
                maker_fee=settings.maker_rate,
                taker_fee=settings.taker_rate,
                ts_event=now,
                ts_init=now,
            )
        )
        engine.add_data(_make_data(evidence))
        strategy = SingleLimitBuy()
        engine.add_strategy(strategy)
        engine.run()
        return evidence.result(strategy)
    finally:
        engine.dispose()
