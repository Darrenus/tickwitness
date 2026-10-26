"""Pinned public native hooks for a conserved inclusive tagged reconstruction.

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
from tickwitness.domain.replay.tagged_queue_contracts import ENGINE, TRACE_CHANNELS, TaggedQueueReplayInput
from tickwitness.infrastructure._nautilus_native import (
    _decimal,
    _make_data,
    _native_api,
    _precision,
    _Settings,
    _units,
)


class _TaggedQueue:
    """Capture-scoped capacity from the frozen, conserved tagged reconstruction.

    Pure completions allocate the public tape. These runtime counters independently
    require actual native acceptance, exactly-once capacity grants, and actual fills.
    """

    def __init__(self, replay_input: TaggedQueueReplayInput, settings: _Settings) -> None:
        self.settings = settings
        interpretations = cast("list[dict[str, Any]]", replay_input.witnesses.document["interpretations"])
        witness = next(row for row in interpretations if row["policy_id"] == replay_input.policy_id)
        self.expected = cast("list[dict[str, Any]]", witness["trace"])
        self.horizon = cast("dict[str, Any]", witness["horizon"])
        self.current: ReplayEvent | None = None
        self.index = 0
        self.active = False
        self.filled = 0
        self.offer = self.granted = self.consumed = 0
        self.grant_taken = False
        self.trace: list[dict[str, object]] = []
        self.hooks: list[dict[str, object]] = []
        self.current_row: dict[str, Any] = {}
        self.phase = "bootstrap"

    def queue(self) -> dict[str, int] | None:
        return None if not self.current_row else cast("dict[str, int]", self.current_row["after"])

    def begin(self, event: ReplayEvent) -> None:
        if self.current is not None and (self.granted != self.offer or self.consumed != self.offer):
            raise ValueError("Native matching did not consume exactly the conserved tagged grant")
        self.current = event
        expected = self.expected[self.index - 1]
        if expected["source_ref"] != event.source_ref:
            raise ValueError("Frozen tagged completion differs from the actual native source step")
        if self.index > 1 and not self.active:
            raise ValueError("Tagged representation was not actually accepted at capture 1")
        self.phase = "observed_window"
        self.offer = expected["own_fill_grant_lots"]
        self.granted = self.consumed = 0
        self.grant_taken = False
        self.current_row = {**expected, "granted_lots": 0, "native_filled_lots": 0, "accepted_here": False}
        self.trace.append(self.current_row)

    def accepted(self, native_depth: int) -> None:
        if self.active or self.current is None or self.current.capture_seq != 1:
            raise ValueError("Tagged reconstruction requires one actual acceptance at capture 1")
        if native_depth != self.current_row["observed_total_lots"]:
            raise ValueError("Actual acceptance depth differs from the recorded inclusive total")
        self.active = True
        self.current_row["accepted_here"] = True

    def take(self) -> int:
        if self.current is None:
            raise ValueError("Native fill hook has no source capture")
        allowed = self.offer if self.active and not self.grant_taken and self.phase == "observed_window" else 0
        if self.current.event_type != "trade":
            allowed = 0
        self.grant_taken = True
        self.granted += allowed
        self.current_row["granted_lots"] = self.granted
        self.hooks.append({"source_ref": self.current.source_ref,
                           "origin": "native_public_fill_simulation_hook", "offered_lots": allowed,
                           "cumulative_granted_lots": self.granted, "phase": self.phase})
        return allowed

    def fill(self, quantity: int) -> None:
        if self.current is None or self.current.event_type != "trade" or quantity <= 0 or self.phase != "observed_window":
            raise ValueError("Native tagged fill requires a positive observed-window source trade")
        self.consumed += quantity
        if self.consumed > self.granted or self.filled + quantity > self.settings.quantity_lots:
            raise ValueError("Native tagged fill exceeds its single-counted capacity")
        self.filled += quantity
        self.current_row["native_filled_lots"] = self.consumed


class _Evidence:
    def __init__(self, replay_input: TaggedQueueReplayInput, api: SimpleNamespace) -> None:
        self.replay_input = replay_input
        self.prepared = replay_input.prepared
        self.settings = _Settings.from_prepared(self.prepared)
        self.api = api
        self.iid = api.InstrumentId.from_str("EURUSD.SIM")
        self.venue = api.Venue("SIM")
        self.queue = _TaggedQueue(replay_input, self.settings)
        strategy = cast("dict[str, int]", replay_input.protocol.document["strategy"])
        self.cancel_capture = strategy["horizon_capture_seq"]
        self.traces: dict[str, list[dict[str, object]]] = {key: [] for key in TRACE_CHANNELS}
        self.pending: dict[str, dict[str, object]] = {}
        self.commission = Decimal(0)
        self.failure: Exception | None = None
        self.horizon_snapshot: dict[str, object] | None = None

    def record(
        self, channel: str, kind: str, now: int, fields: dict[str, object], *, final: bool = False
    ) -> None:
        current = self.queue.current
        self.traces[channel].append(
            {
                "kind": kind,
                "ordinal": len(self.traces[channel]),
                "native_time_ns": now,
                "source_ref": None if final or current is None else current.source_ref,
                "phase": self.queue.phase,
                "fields": fields,
            }
        )

    def begin(self, native: Any) -> None:
        if self.queue.index >= len(self.prepared.events):
            raise ValueError("Native engine processed unexpected additional input")
        event = self.prepared.events[self.queue.index]
        internal_id = str(native.trade_id) if event.event_type == "trade" else str(native.sequence)
        expected = (
            f"CAPTURE-{event.capture_seq}"
            if event.event_type == "trade"
            else str(event.capture_seq)
        )
        if (
            internal_id != expected
            or native.ts_init != event.receive_time_ns
            or native.ts_event != event.receive_time_ns
        ):
            raise ValueError("Native source identity or receive clock differs from frozen input")
        self.queue.index += 1
        self.queue.begin(event)
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
        if self.queue.current is None:
            raise ValueError("Queue strategy command requires a source capture")
        ordinal = len(self.traces["decision_trace"])
        decision_ref, command_id = f"decision-{ordinal}", f"command-{ordinal}"
        order_id = str(order.client_order_id)
        self.pending[command_id] = {
            "command_id": command_id,
            "order_id": order_id,
            "command_type": action,
            "decision_ref": decision_ref,
            "source_ref": self.queue.current.source_ref,
        }
        self.record(
            "decision_trace",
            "command_issued",
            now,
            {
                "decision_ref": decision_ref,
                "command_id": command_id,
                "action": action,
                "order_id": order_id,
                "strategy_kind": "tagged_passive_order_at_entry_v1",
                "limit_price_ticks": self.settings.limit_price_ticks,
                "quantity_lots": self.settings.quantity_lots,
                "post_only": True,
                "cause": "entry_tag_representation" if action == "submit" else "post_horizon_cleanup",
            },
        )

    def acknowledge(self, event: Any) -> None:
        name, order_id = type(event).__name__, str(event.client_order_id)
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

    def order(self, native: Any) -> dict[str, object]:
        return {
            "order_id": str(native.client_order_id),
            "status": native.status.name,
            "quantity_lots": _units(native.quantity, self.settings.size_increment),
            "filled_quantity_lots": _units(native.filled_qty, self.settings.size_increment),
            "remaining_quantity_lots": _units(native.leaves_qty, self.settings.size_increment),
        }

    def order_event(
        self, strategy: Any, event: Any, acceptance: dict[str, object] | None = None
    ) -> None:
        self.acknowledge(event)
        native = strategy.cache.order(event.client_order_id)
        state = (
            self.order(native)
            if native is not None
            else {
                "order_id": str(event.client_order_id),
                "status": None,
                "quantity_lots": None,
                "filled_quantity_lots": None,
                "remaining_quantity_lots": None,
            }
        )
        self.record(
            "order_trace",
            type(event).__name__,
            strategy.clock.timestamp_ns(),
            {
                **state,
                "event_type": type(event).__name__,
                "pending_commands": list(self.pending),
                "actual_acceptance": acceptance,
            },
        )

    def account(self, strategy: Any, kind: str, *, final: bool = False) -> None:
        account = strategy.cache.account_for_venue(self.venue)
        if account is None:
            raise ValueError("Native margin account is unavailable")
        net = sum(
            (
                Decimal(str(position.quantity)) * (1 if position.side.name == "LONG" else -1)
                for position in strategy.cache.positions()
                if position.instrument_id == self.iid and not position.is_closed
            ),
            Decimal(0),
        )
        total = account.balance_total(self.api.USD).as_decimal()
        free = account.balance_free(self.api.USD).as_decimal()
        locked = account.balance_locked(self.api.USD).as_decimal()
        if net < 0 or total != free + locked:
            raise ValueError("Native long-only margin account conservation failed")
        book = strategy.cache.order_book(self.iid)
        self.record(
            "account_trace",
            kind,
            strategy.clock.timestamp_ns(),
            {
                "account_type": "MARGIN",
                "oms_type": "NETTING",
                "currency": "USD",
                "cash_total": _decimal(total),
                "cash_free": _decimal(free),
                "cash_locked": _decimal(locked),
                "net_position_lots": _units(net, self.settings.size_increment),
                "observed_fill_lots": self.queue.filled,
                "observed_commission": _decimal(self.commission),
                "native_money_precision": 2,
                "money_rounding_policy": "native_v1_f64_notional_then_USD_Money_precision_2",
                "cash_semantics": "native_margin_balance_not_spot_notional_debit",
                "book_role": "recorded_observation_cache",
                "book_type": None if book is None else book.book_type.name,
                "bid_levels": 0 if book is None else len(book.bids()),
                "ask_levels": 0 if book is None else len(book.asks()),
                "orders": [self.order(order) for order in strategy.cache.orders()],
            },
            final=final,
        )

    def observe_horizon(self, strategy: Any) -> None:
        """Snapshot actual native state before the distinct administrative cleanup."""
        queue = self.queue
        current = queue.current
        state = queue.queue()
        if current is None or state is None or self.horizon_snapshot is not None:
            raise ValueError("Tagged horizon requires exactly one actual source checkpoint")
        if queue.granted != queue.offer or queue.consumed != queue.offer or queue.filled != state["own_filled_lots"]:
            raise ValueError("Tagged horizon contains an unconsumed or missing native fill")
        book = strategy.cache.order_book(self.iid)
        if book is None or not book.bids():
            raise ValueError("Actual tagged horizon has no visible native bid")
        bid_totals: dict[int, int] = {}
        for level in book.bids():
            for order in level.orders():
                ticks = _units(order.price, self.settings.price_increment)
                bid_totals[ticks] = bid_totals.get(ticks, 0) + _units(order.size, self.settings.size_increment)
        target_total = bid_totals.get(self.settings.limit_price_ticks, 0)
        if target_total != state["total_lots"]:
            raise ValueError("Actual native horizon differs from inclusive observed depth")
        best = max(bid_totals)
        mark = {"source_ref": current.source_ref, "price_ticks": best,
                "available_quantity_lots": bid_totals[best]}
        if mark != queue.horizon["mark"]:
            raise ValueError("Actual native final mark differs from frozen observation projection")
        queue.phase = "claim_horizon"
        self.account(strategy, "horizon_account_snapshot")
        self.horizon_snapshot = {
            "source_ref": current.source_ref, "native_time_ns": strategy.clock.timestamp_ns(),
            "queue_state": state, "native_target_lots": target_total,
            "mark": mark, "account": dict(cast("dict[str, object]", self.traces["account_trace"][-1]["fields"])),
        }
        queue.phase = "post_horizon_cleanup"


def run_native(replay_input: TaggedQueueReplayInput) -> dict[str, object]:
    """Run only after tagged preflight, using public matching and lifecycle hooks."""
    api = _native_api()
    api.OrderBook = importlib.import_module("nautilus_trader.model.book").OrderBook
    evidence = _Evidence(replay_input, api)
    settings, queue = evidence.settings, evidence.queue

    def price(ticks: int) -> Any:
        return api.Price.from_str(_decimal(Decimal(ticks) * settings.price_increment))

    def quantity(lots: int) -> Any:
        return api.Quantity.from_str(_decimal(Decimal(lots) * settings.size_increment))

    module_base = api.SimulationModule
    fill_base = api.FillModel
    strategy_base = api.Strategy

    class QueueModule(module_base):  # type: ignore[misc, valid-type]
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

    class QueueFill(fill_base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=settings.seed)

        def get_orderbook_for_fill_simulation(
            self, instrument: Any, order: Any, best_bid: Any, best_ask: Any
        ) -> Any:
            try:
                if (
                    instrument.id != evidence.iid
                    or order.side != api.OrderSide.BUY
                    or _units(order.price, settings.price_increment) != settings.limit_price_ticks
                ):
                    raise ValueError("Public fill hook addressed an unexpected native order")
                allowed = queue.take()
                book = api.OrderBook(instrument_id=instrument.id, book_type=api.BookType.L2_MBP)
                if allowed:
                    book.add(
                        api.BookOrder(
                            api.OrderSide.SELL,
                            price(settings.limit_price_ticks),
                            quantity(allowed),
                            1,
                        ),
                        0,
                        0,
                    )
                # An empty public book is authoritative. None enables default matching.
                return book
            except Exception as error:
                evidence.failure = error
                raise

    class QueueBuy(strategy_base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(
                api.StrategyConfig(
                    strategy_id="QueueResearch-001",
                    order_id_tag="001",
                    use_uuid_client_order_ids=False,
                    log_events=False,
                    log_commands=False,
                )
            )
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
                        evidence.iid,
                        api.OrderSide.BUY,
                        quantity(settings.quantity_lots),
                        price(settings.limit_price_ticks),
                        post_only=True,
                    )
                    evidence.command("submit", self.order, self.clock.timestamp_ns())
                    self.submit_order(self.order)
                if current.capture_seq == evidence.cancel_capture and evidence.horizon_snapshot is None:
                    if self.order is None:
                        raise ValueError("Tagged claim horizon has no represented native order")
                    evidence.observe_horizon(self)
                    if not self.order.is_closed and not self.cancel_sent:
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
                book = self.cache.order_book(evidence.iid)
                if book is None:
                    raise ValueError("Actual acceptance has no public native book")
                # Sum public BookOrder Quantities, avoiding BookLevel.size() float conversion.
                actual_depth = sum(
                    _units(order.size, settings.size_increment)
                    for level in book.bids()
                    for order in level.orders()
                    if _units(order.price, settings.price_increment) == settings.limit_price_ticks
                )
                queue.accepted(actual_depth)
                evidence.order_event(
                    self,
                    event,
                    {
                        "native_bid_lots": actual_depth,
                        "queue": queue.queue(),
                        "target_price_ticks": settings.limit_price_ticks,
                        "acceptance_role": "tagged_reconstruction_proxy",
                    },
                )
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
                        "liquidity_side": event.liquidity_side.name,
                    },
                )
                evidence.account(self, "fill_callback_account_snapshot")
            except Exception as error:
                evidence.failure = error
                raise

    engine = api.BacktestEngine(
        config=api.BacktestEngineConfig(
            trader_id=api.TraderId("QUEUERESEARCH-001"),
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
            default_leverage=Decimal(1),
            book_type=api.BookType.L2_MBP,
            modules=[QueueModule()],
            fill_model=QueueFill(),
            latency_model=api.LatencyModel(
                base_latency_nanos=0,
                insert_latency_nanos=settings.insert_latency,
                cancel_latency_nanos=settings.cancel_latency,
            ),
            use_message_queue=True,
            use_random_ids=False,
            trade_execution=True,
            bar_execution=False,
            queue_position=False,
            liquidity_consumption=True,
        )
        now = evidence.prepared.events[0].receive_time_ns
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
                margin_init=Decimal(1),
                margin_maint=Decimal(1),
                maker_fee=settings.maker_rate,
                taker_fee=settings.taker_rate,
                ts_event=now,
                ts_init=now,
            )
        )
        # Only the existing receive-order EURUSD source mapper is reused.
        engine.add_data(_make_data(cast("Any", evidence)))
        strategy = QueueBuy()
        engine.add_strategy(strategy)
        engine.run()
        if evidence.failure is not None:
            raise evidence.failure
        if queue.index != len(evidence.prepared.events) or queue.granted != queue.offer or queue.consumed != queue.offer:
            raise ValueError("Native execution did not reconcile every original source input")
        if not queue.active or len(strategy.cache.orders()) != 1:
            raise ValueError("Queue execution requires exactly one actually accepted native order")
        if evidence.horizon_snapshot is None or strategy.order is None or not strategy.order.is_closed or evidence.pending:
            raise ValueError("Tagged execution lacks actual precleanup horizon or native cleanup acknowledgement")
        state = cast("dict[str, int]", queue.horizon["state"])
        native_order = evidence.order(strategy.order)
        if native_order["filled_quantity_lots"] != state["own_filled_lots"]:
            raise ValueError("Native terminal fill quantity differs from conserved reconstruction")
        cleanup = {
            "canceled_own_lots": state["own_live_lots"],
            "projected_total_after_cleanup": state["total_lots"] - state["own_live_lots"],
            "projected_external_after_cleanup": state["external_lots"],
            "own_live_after_cleanup": 0,
            "native_status": native_order["status"],
            "native_unfilled_lots": native_order["remaining_quantity_lots"],
            "book_role": "recorded_observation_cache",
        }
        evidence.account(strategy, "final_account_snapshot", final=True)
        open_orders = [
            {"order_id": str(order.client_order_id), "status": order.status.name}
            for order in strategy.cache.orders()
            if not order.is_closed
        ]
        pending = list(evidence.pending.values())
        reason = (
            "pending_commands_at_data_end"
            if pending
            else "input_exhausted_with_open_orders"
            if open_orders
            else "input_exhausted"
        )
        # EOF is the actual final capture. No synthetic clock tick or order drain is added.
        return {
            "kind": "tagged_queue_replay_result_v1",
            "schema_version": 1,
            "bindings": replay_input.bindings,
            "engine": ENGINE,
            "environment": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "package_versions": {
                    name: metadata.version(name)
                    for name in ("nautilus_trader", "numpy", "pandas", "pyarrow", "msgspec")
                },
            },
            "execution_status": "incomplete" if pending or open_orders else "completed",
            "completeness": {
                "input_records": len(evidence.prepared.events),
                "processed_records": queue.index,
                "open_orders": open_orders,
                "pending_commands": pending,
                "stop_reason": reason,
            },
            **evidence.traces,
            "queue_trace": queue.trace,
            "hook_trace": queue.hooks,
            "horizon_snapshot": evidence.horizon_snapshot,
            "cleanup": cleanup,
        }
    finally:
        engine.dispose()
