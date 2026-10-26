"""Pinned public native hooks for an external, no-impact FIFO shadow queue.

The source mapper is shared with the earlier replay profile. Matching permission,
queue budgets, strategy, and result identity are separate. ``Any`` stays at this
Cython boundary; every returned value passes the native-free queue DTO loader.
"""

from __future__ import annotations

import importlib
import platform
from decimal import Decimal
from importlib import metadata
from types import SimpleNamespace
from typing import Any, cast

from tickwitness.domain.replay.contracts import ReplayEvent
from tickwitness.domain.replay.queue_contracts import ENGINE, TRACE_CHANNELS, QueueReplayInput
from tickwitness.infrastructure._nautilus_native import (
    _decimal,
    _make_data,
    _native_api,
    _precision,
    _Settings,
    _units,
)


class _ShadowQueue:
    """Capture-scoped grant ledger; native callbacks consume each grant at most once."""

    def __init__(self, replay_input: QueueReplayInput, settings: _Settings) -> None:
        self.policy = replay_input.policy_id
        self.settings = settings
        request = replay_input.family.constraint.document
        updates = cast("list[dict[str, Any]]", request["updates"])
        self.updates = {update["capture_seq"]: update for update in updates}
        self.pending_trade_refs: list[int] = []
        self.current: ReplayEvent | None = None
        self.index = 0
        self.active = False
        self.ahead = self.behind = self.external = self.observed = 0
        self.filled = 0
        self.offer = self.granted = self.consumed = 0
        self.grant_taken = False
        self.trace: list[dict[str, object]] = []
        self.hooks: list[dict[str, object]] = []
        self.current_row: dict[str, object] = {}

    def queue(self) -> dict[str, int] | None:
        if not self.active:
            return None
        return {"ahead_lots": self.ahead, "behind_lots": self.behind,
                "external_lots": self.external}

    def begin(self, event: ReplayEvent) -> None:
        self.current = event
        before = self.queue()
        self.offer = self.granted = self.consumed = 0
        self.grant_taken = False
        flow = {"additions_lots": 0, "cancellations_lots": 0, "trade_lots": 0,
                "cancel_ahead_lots": 0, "cancel_behind_lots": 0}
        if event.event_type == "trade":
            quantity = event.quantity_lots
            if (event.price_ticks != self.settings.limit_price_ticks
                    or event.aggressor_side != "sell" or quantity is None
                    or quantity > self.external):
                raise ValueError("Source trade violates the frozen target or external depth")
            flow["trade_lots"] = quantity
            self.pending_trade_refs.append(event.capture_seq)
            if self.active:
                old_ahead = self.ahead
                self.ahead = max(0, self.ahead - quantity)
                self.behind -= max(0, quantity - old_ahead)
                self.offer = min(self.settings.quantity_lots - self.filled,
                                 max(0, quantity - old_ahead))
            self.external -= quantity
        else:
            target = dict(event.bids).get(self.settings.limit_price_ticks)
            if target is not None:
                self.observed = target
                if event.event_type == "snapshot":
                    if self.index != 1 or self.active:
                        raise ValueError("Only capture 1 may initialize shadow depth")
                else:
                    update = self.updates.get(event.capture_seq)
                    if update is None:
                        raise ValueError("Target checkpoint has no frozen gross flow")
                    addition, cancellation = update["additions_lots"], update["cancellations_lots"]
                    if (type(addition) is not int or addition < 0
                            or type(cancellation) is not int or cancellation < 0
                            or self.external + addition - cancellation != target
                            or update["trade_capture_seqs"] != self.pending_trade_refs):
                        raise ValueError("Gross flow or source trade reconciliation differs")
                    self.pending_trade_refs.clear()
                    flow["additions_lots"] = addition
                    flow["cancellations_lots"] = cancellation
                    if self.active:
                        self.behind += addition
                        front = (min(cancellation, self.ahead)
                                 if self.policy == "cancel_front_first_v1"
                                 else max(0, cancellation - self.behind))
                        back = cancellation - front
                        self.ahead -= front
                        self.behind -= back
                        flow["cancel_ahead_lots"] = front
                        flow["cancel_behind_lots"] = back
                self.external = target
        if self.active and (self.ahead < 0 or self.behind < 0
                            or self.ahead + self.behind != self.external):
            raise ValueError("External shadow queue conservation failed")
        self.current_row = {
            "source_ref": event.source_ref, "receive_time_ns": event.receive_time_ns,
            "market_observed_lots": self.observed, "before": before, "after": self.queue(),
            "flow": flow, "grant_limit_lots": self.offer, "granted_lots": 0,
            "native_filled_lots": 0, "own_remaining_lots": self.settings.quantity_lots - self.filled,
            "accepted_here": False,
        }
        self.trace.append(self.current_row)

    def accepted(self) -> None:
        if self.active or self.current is None or self.current.capture_seq != 1:
            raise ValueError("Queue execution requires one actual acceptance at capture 1")
        self.active = True
        self.ahead, self.behind = self.external, 0
        self.offer = 0
        self.current_row["after"] = self.queue()
        self.current_row["accepted_here"] = True

    def take(self) -> int:
        if self.current is None:
            raise ValueError("Native fill hook has no source capture")
        allowed = self.offer if self.active and not self.grant_taken else 0
        if self.current.event_type != "trade":
            allowed = 0
        self.grant_taken = True
        self.granted += allowed
        self.current_row["granted_lots"] = self.granted
        self.hooks.append({"source_ref": self.current.source_ref,
                           "origin": "native_public_fill_simulation_hook",
                           "offered_lots": allowed,
                           "cumulative_granted_lots": self.granted})
        return allowed

    def fill(self, quantity: int) -> None:
        if self.current is None or self.current.event_type != "trade" or quantity <= 0:
            raise ValueError("Native queue fill requires a positive source trade")
        self.consumed += quantity
        if (self.consumed > self.granted
                or self.filled + quantity > self.settings.quantity_lots):
            raise ValueError("Native fill exceeds the granted capture or remaining order budget")
        self.filled += quantity
        self.current_row["native_filled_lots"] = self.consumed
        self.current_row["own_remaining_lots"] = self.settings.quantity_lots - self.filled


class _Evidence:
    def __init__(self, replay_input: QueueReplayInput, api: SimpleNamespace) -> None:
        self.replay_input = replay_input
        self.prepared = replay_input.prepared
        self.settings = _Settings.from_prepared(self.prepared)
        self.api = api
        self.iid = api.InstrumentId.from_str("EURUSD.SIM")
        self.venue = api.Venue("SIM")
        self.queue = _ShadowQueue(replay_input, self.settings)
        strategy = cast("dict[str, int]", replay_input.family.document["strategy"])
        self.cancel_capture = strategy["cancel_at_capture_seq"]
        self.traces: dict[str, list[dict[str, object]]] = {key: [] for key in TRACE_CHANNELS}
        self.pending: dict[str, dict[str, object]] = {}
        self.commission = Decimal(0)
        self.failure: Exception | None = None

    def record(self, channel: str, kind: str, now: int, fields: dict[str, object],
               *, final: bool = False) -> None:
        current = self.queue.current
        self.traces[channel].append({
            "kind": kind, "ordinal": len(self.traces[channel]), "native_time_ns": now,
            "source_ref": None if final or current is None else current.source_ref,
            "fields": fields,
        })

    def begin(self, native: Any) -> None:
        if self.queue.index >= len(self.prepared.events):
            raise ValueError("Native engine processed unexpected additional input")
        event = self.prepared.events[self.queue.index]
        internal_id = str(native.trade_id) if event.event_type == "trade" else str(native.sequence)
        expected = (f"CAPTURE-{event.capture_seq}" if event.event_type == "trade"
                    else str(event.capture_seq))
        if (internal_id != expected or native.ts_init != event.receive_time_ns
                or native.ts_event != event.receive_time_ns):
            raise ValueError("Native source identity or receive clock differs from frozen input")
        self.queue.index += 1
        self.queue.begin(event)
        self.record("input_trace", "input_processed", event.receive_time_ns, {
            "event_time_ns": event.event_time_ns, "receive_time_ns": event.receive_time_ns,
            "native_ts_event_ns": native.ts_event, "native_ts_init_ns": native.ts_init,
            "clock_policy_id": "receive_order_v1", "source_clock_certified": False,
            "source_sequence_first": event.first_sequence,
            "source_sequence_last": event.last_sequence, "source_trade_id": event.trade_id,
            "native_internal_id": internal_id,
            "native_id_policy": "capture_seq_batch_sequence_or_CAPTURE_trade_id",
            "bids": [list(level) for level in event.bids],
            "asks": [list(level) for level in event.asks], "price_ticks": event.price_ticks,
            "quantity_lots": event.quantity_lots, "aggressor_side": event.aggressor_side,
            "source_ref_semantics": "input_step_before_native_matching_and_settlement",
        })

    def command(self, action: str, order: Any, now: int) -> None:
        if self.queue.current is None:
            raise ValueError("Queue strategy command requires a source capture")
        ordinal = len(self.traces["decision_trace"])
        decision_ref, command_id = f"decision-{ordinal}", f"command-{ordinal}"
        order_id = str(order.client_order_id)
        self.pending[command_id] = {
            "command_id": command_id, "order_id": order_id, "command_type": action,
            "decision_ref": decision_ref, "source_ref": self.queue.current.source_ref,
        }
        self.record("decision_trace", "command_issued", now, {
            "decision_ref": decision_ref, "command_id": command_id, "action": action,
            "order_id": order_id, "strategy_kind": "single_limit_buy_cancel_at_capture_v1",
            "limit_price_ticks": self.settings.limit_price_ticks,
            "quantity_lots": self.settings.quantity_lots, "post_only": True,
            "cause": "selected_capture" if action == "submit" else "family_cancel_capture",
        })

    def acknowledge(self, event: Any) -> None:
        name, order_id = type(event).__name__, str(event.client_order_id)
        action = ("submit" if name in ("OrderAccepted", "OrderRejected", "OrderDenied", "OrderFilled")
                  else "cancel" if name in ("OrderCanceled", "OrderCancelRejected") else None)
        if action is not None:
            for key, command in list(self.pending.items()):
                if command["order_id"] == order_id and command["command_type"] == action:
                    del self.pending[key]

    def order(self, native: Any) -> dict[str, object]:
        return {
            "order_id": str(native.client_order_id), "status": native.status.name,
            "quantity_lots": _units(native.quantity, self.settings.size_increment),
            "filled_quantity_lots": _units(native.filled_qty, self.settings.size_increment),
            "remaining_quantity_lots": _units(native.leaves_qty, self.settings.size_increment),
        }

    def order_event(self, strategy: Any, event: Any,
                    acceptance: dict[str, object] | None = None) -> None:
        self.acknowledge(event)
        native = strategy.cache.order(event.client_order_id)
        state = (self.order(native) if native is not None else {
            "order_id": str(event.client_order_id), "status": None, "quantity_lots": None,
            "filled_quantity_lots": None, "remaining_quantity_lots": None,
        })
        self.record("order_trace", type(event).__name__, strategy.clock.timestamp_ns(), {
            **state, "event_type": type(event).__name__, "pending_commands": list(self.pending),
            "actual_acceptance": acceptance,
        })

    def account(self, strategy: Any, kind: str, *, final: bool = False) -> None:
        account = strategy.cache.account_for_venue(self.venue)
        if account is None:
            raise ValueError("Native margin account is unavailable")
        net = sum((Decimal(str(position.quantity)) * (1 if position.side.name == "LONG" else -1)
                   for position in strategy.cache.positions()
                   if position.instrument_id == self.iid and not position.is_closed), Decimal(0))
        total = account.balance_total(self.api.USD).as_decimal()
        free = account.balance_free(self.api.USD).as_decimal()
        locked = account.balance_locked(self.api.USD).as_decimal()
        if net < 0 or total != free + locked:
            raise ValueError("Native long-only margin account conservation failed")
        book = strategy.cache.order_book(self.iid)
        self.record("account_trace", kind, strategy.clock.timestamp_ns(), {
            "account_type": "MARGIN", "oms_type": "NETTING", "currency": "USD",
            "cash_total": _decimal(total), "cash_free": _decimal(free),
            "cash_locked": _decimal(locked), "net_position_lots": _units(net, self.settings.size_increment),
            "observed_fill_lots": self.queue.filled, "observed_commission": _decimal(self.commission),
            "native_money_precision": 2,
            "money_rounding_policy": "native_v1_f64_notional_then_USD_Money_precision_2",
            "cash_semantics": "native_margin_balance_not_spot_notional_debit",
            "book_type": None if book is None else book.book_type.name,
            "bid_levels": 0 if book is None else len(book.bids()),
            "ask_levels": 0 if book is None else len(book.asks()),
            "orders": [self.order(order) for order in strategy.cache.orders()],
        }, final=final)


def run_native(replay_input: QueueReplayInput) -> dict[str, object]:
    """Run only after family/input preflight; no script, user code, or private queue patch."""
    api = _native_api()
    api.OrderBook = importlib.import_module("nautilus_trader.model.book").OrderBook
    evidence = _Evidence(replay_input, api)
    settings, queue = evidence.settings, evidence.queue

    def price(ticks: int) -> Any:
        return api.Price.from_str(_decimal(Decimal(ticks) * settings.price_increment))

    def quantity(lots: int) -> Any:
        return api.Quantity.from_str(_decimal(Decimal(lots) * settings.size_increment))

    class QueueModule(api.SimulationModule):
        def __init__(self) -> None:
            super().__init__(api.SimulationModuleConfig())

        def pre_process(self, data: Any) -> None:
            try:
                evidence.begin(data)
            except Exception as error:
                evidence.failure = error
                raise

        def process(self, ts_now: int) -> None:
            pass

        def log_diagnostics(self, logger: Any) -> None:
            pass

        def reset(self) -> None:
            pass

    class QueueFill(api.FillModel):
        def __init__(self) -> None:
            super().__init__(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=settings.seed)

        def get_orderbook_for_fill_simulation(self, instrument: Any, order: Any,
                                             best_bid: Any, best_ask: Any) -> Any:
            try:
                allowed = queue.take()
                book = api.OrderBook(instrument_id=instrument.id, book_type=api.BookType.L2_MBP)
                if allowed:
                    book.add(api.BookOrder(api.OrderSide.SELL, price(settings.limit_price_ticks),
                                           quantity(allowed), 1), 0, 0)
                # An empty public book is authoritative. None enables default matching.
                return book
            except Exception as error:
                evidence.failure = error
                raise

    class QueueBuy(api.Strategy):
        def __init__(self) -> None:
            super().__init__(api.StrategyConfig(
                strategy_id="QueueResearch-001", order_id_tag="001",
                use_uuid_client_order_ids=False, log_events=False, log_commands=False,
            ))
            self.order: Any = None
            self.cancel_sent = False

        def on_start(self) -> None:
            self.subscribe_order_book_deltas(evidence.iid, book_type=api.BookType.L2_MBP)
            self.subscribe_trade_ticks(evidence.iid)
            evidence.account(self, "initial_account_snapshot")

        def market(self) -> None:
            try:
                current = queue.current
                if current is None:
                    raise ValueError("Native strategy market callback has no source input")
                if self.order is None and current.capture_seq == settings.submit_capture_seq:
                    self.order = self.order_factory.limit(
                        evidence.iid, api.OrderSide.BUY, quantity(settings.quantity_lots),
                        price(settings.limit_price_ticks), post_only=True,
                    )
                    evidence.command("submit", self.order, self.clock.timestamp_ns())
                    self.submit_order(self.order)
                if (current.capture_seq == evidence.cancel_capture and self.order is not None
                        and not self.order.is_closed and not self.cancel_sent):
                    self.cancel_sent = True
                    evidence.command("cancel", self.order, self.clock.timestamp_ns())
                    self.cancel_order(self.order)
            except Exception as error:
                evidence.failure = error
                raise

        def on_order_book_deltas(self, deltas: Any) -> None:
            self.market()

        def on_trade_tick(self, tick: Any) -> None:
            self.market()

        def on_order_accepted(self, event: Any) -> None:
            try:
                queue.accepted()
                book = self.cache.order_book(evidence.iid)
                if book is None:
                    raise ValueError("Actual acceptance has no public native book")
                # Sum public BookOrder Quantities, avoiding BookLevel.size() float conversion.
                actual_depth = sum(
                    _units(order.size, settings.size_increment)
                    for level in book.bids() for order in level.orders()
                    if _units(order.price, settings.price_increment) == settings.limit_price_ticks
                )
                if actual_depth != queue.external:
                    raise ValueError("Actual acceptance depth differs from the declared target")
                evidence.order_event(self, event, {
                    "native_bid_lots": actual_depth, "queue": queue.queue(),
                    "target_price_ticks": settings.limit_price_ticks,
                })
            except Exception as error:
                evidence.failure = error
                raise

        def on_order_event(self, event: Any) -> None:
            try:
                # The specific callback records acceptance only after actual depth validation.
                if type(event).__name__ != "OrderAccepted":
                    evidence.order_event(self, event)
            except Exception as error:
                evidence.failure = error
                raise

        def on_order_filled(self, event: Any) -> None:
            try:
                lots = _units(event.last_qty, settings.size_increment)
                queue.fill(lots)
                evidence.acknowledge(event)
                evidence.commission += event.commission.as_decimal()
                evidence.record("fill_trace", "OrderFilled", self.clock.timestamp_ns(), {
                    "order_id": str(event.client_order_id), "native_trade_id": str(event.trade_id),
                    "price_ticks": _units(event.last_px, settings.price_increment),
                    "quantity_lots": lots, "price": str(event.last_px), "quantity": str(event.last_qty),
                    "commission": _decimal(event.commission.as_decimal()),
                    "commission_currency": str(event.commission.currency),
                    "liquidity_side": event.liquidity_side.name,
                })
                evidence.account(self, "fill_callback_account_snapshot")
            except Exception as error:
                evidence.failure = error
                raise

    engine = api.BacktestEngine(config=api.BacktestEngineConfig(
        trader_id=api.TraderId("QUEUERESEARCH-001"),
        logging=api.LoggingConfig(bypass_logging=True), run_analysis=False,
    ))
    try:
        engine.add_venue(
            venue=evidence.venue, oms_type=api.OmsType.NETTING, account_type=api.AccountType.MARGIN,
            base_currency=api.USD,
            starting_balances=[api.Money.from_str(_decimal(settings.starting_cash) + " USD")],
            default_leverage=Decimal(1), book_type=api.BookType.L2_MBP, modules=[QueueModule()],
            fill_model=QueueFill(),
            latency_model=api.LatencyModel(base_latency_nanos=0,
                                           insert_latency_nanos=settings.insert_latency,
                                           cancel_latency_nanos=settings.cancel_latency),
            use_message_queue=True, use_random_ids=False, trade_execution=True,
            bar_execution=False, queue_position=False, liquidity_consumption=True,
        )
        now = evidence.prepared.events[0].receive_time_ns
        engine.add_instrument(api.CurrencyPair(
            instrument_id=evidence.iid, raw_symbol=api.Symbol("EURUSD"),
            base_currency=api.EUR, quote_currency=api.USD,
            price_precision=_precision(settings.price_increment),
            size_precision=_precision(settings.size_increment),
            price_increment=api.Price.from_str(_decimal(settings.price_increment)),
            size_increment=api.Quantity.from_str(_decimal(settings.size_increment)),
            lot_size=api.Quantity.from_str(_decimal(settings.size_increment)),
            min_quantity=api.Quantity.from_str(_decimal(settings.size_increment)),
            margin_init=Decimal(1), margin_maint=Decimal(1), maker_fee=settings.maker_rate,
            taker_fee=settings.taker_rate, ts_event=now, ts_init=now,
        ))
        # Only the existing receive-order EURUSD source mapper is reused.
        engine.add_data(_make_data(cast("Any", evidence)))
        strategy = QueueBuy()
        engine.add_strategy(strategy)
        engine.run()
        if evidence.failure is not None:
            raise evidence.failure
        if queue.index != len(evidence.prepared.events) or queue.pending_trade_refs:
            raise ValueError("Native execution did not reconcile every original source input")
        if not queue.active or len(strategy.cache.orders()) != 1:
            raise ValueError("Queue execution requires exactly one actually accepted native order")
        evidence.account(strategy, "final_account_snapshot", final=True)
        open_orders = [{"order_id": str(order.client_order_id), "status": order.status.name}
                       for order in strategy.cache.orders() if not order.is_closed]
        pending = list(evidence.pending.values())
        reason = ("pending_commands_at_data_end" if pending else
                  "input_exhausted_with_open_orders" if open_orders else "input_exhausted")
        # EOF is the actual final capture. No synthetic clock tick or order drain is added.
        return {
            "kind": "queue_replay_result_v1", "schema_version": 1,
            "bindings": replay_input.bindings, "engine": ENGINE,
            "environment": {
                "python_version": platform.python_version(), "platform": platform.platform(),
                "package_versions": {name: metadata.version(name) for name in
                                     ("nautilus_trader", "numpy", "pandas", "pyarrow", "msgspec")},
            },
            "execution_status": "incomplete" if pending or open_orders else "completed",
            "completeness": {
                "input_records": len(evidence.prepared.events), "processed_records": queue.index,
                "open_orders": open_orders, "pending_commands": pending, "stop_reason": reason,
            },
            **evidence.traces, "queue_trace": queue.trace, "hook_trace": queue.hooks,
        }
    finally:
        engine.dispose()
