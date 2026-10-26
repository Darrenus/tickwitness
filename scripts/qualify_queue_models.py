#!/usr/bin/env python3
"""Remote fixed-input qualification of public native shadow-queue extension hooks.

This original synthetic probe has no user protocol, ledger or strategy-source
entry point. It is MODEL_SENSITIVITY with an unverified no-impact shadow order;
passing does not prove observation-compatible market worlds or any finding.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tickwitness.domain.assumptions.queue_constraints import (
    build_queue_constraint_spec,
    validate_queue_constraints,
)
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.infrastructure._nautilus_native import (
    _decimal,
    _make_data,
    _native_api,
    _precision,
    _Settings,
    _units,
)

ROOT = Path(__file__).resolve().parents[1]
SECOND = 1_000_000_000
SEMANTIC_ID = "nautilus_public_shadow_fifo_queue_probe_v1"
CASE_IDS = (
    "front_back_cancel",
    "gross_churn_checkpoint",
    "no_cancel_control",
    "same_time_capture_order",
    "repeated_public_hook",
    "nontrade_empty_book",
    "late_acceptance",
    "eof_open_orders",
    "eof_pending_insert",
)
POLICIES = ("cancel_front_first_v1", "cancel_back_first_v1")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _check(case: dict[str, Any], name: str, actual: object, expected: object) -> None:
    case["checks"].append(
        {
            "name": name,
            "actual": actual,
            "expected": expected,
            "passed": _canonical(actual) == _canonical(expected),
        }
    )


def _input(case_id: str):
    rows = [
        json.loads(line)
        for line in (ROOT / "examples" / "queue-observations.jsonl").read_bytes().splitlines()
    ]
    request = json.loads((ROOT / "examples" / "queue-constraint-request.json").read_bytes())
    if case_id == "gross_churn_checkpoint":
        for update in request["updates"]:
            if update["capture_seq"] == 3:
                update["additions_lots"] = 1
                update["cancellations_lots"] = 4
        for row in rows:
            if row["capture_seq"] == 4:
                row["quantity_lots"] = 2
            elif row["capture_seq"] in (5, 6):
                row["bids"] = [[100, 3]]
    if case_id == "no_cancel_control":
        for row in rows:
            if row["capture_seq"] == 3:
                row["bids"] = [[100, 8]]
            elif row["capture_seq"] in (5, 6):
                row["bids"] = [[100, 5]]
        for update in request["updates"]:
            if update["capture_seq"] == 3:
                update["cancellations_lots"] = 0
    if case_id == "same_time_capture_order":
        now = rows[0]["receive_time_ns"]
        for row in rows:
            row["receive_time_ns"] = row["event_time_ns"] = now
    if case_id in ("eof_open_orders", "eof_pending_insert"):
        rows = rows[:5]
    normalized = normalize_events(b"\n".join(_canonical(row) for row in rows) + b"\n")
    if normalized.report["quality_status"] != "accepted":
        raise ValueError("Qualification fixture was not accepted")
    spec = json.loads((ROOT / "examples" / "replay-spec.json").read_bytes())
    spec["execution"]["insert_latency_ns"] = (
        2 * SECOND + 1
        if case_id == "late_acceptance"
        else 60 * SECOND
        if case_id == "eof_pending_insert"
        else 0
    )
    replay_spec = build_replay_spec(_canonical(spec))
    identity = hashlib.sha256(
        _canonical(
            {
                "kind": "queue_qualification_fixture_v1",
                "data_sha256": hashlib.sha256(normalized.normalized_bytes).hexdigest(),
                "spec_id": replay_spec.spec_id,
            }
        )
    ).hexdigest()
    replay_input = ReplayInput(identity, normalized.normalized_bytes, replay_spec)
    return rows, request, preflight_replay(replay_input)


def _oracle(request: dict[str, Any], prepared: Any) -> dict[str, Any]:
    protocol = build_executable_protocol(
        _canonical(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Fixed queue extension qualification",
                    "hypothesis": "No production claim is evaluated by this probe.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "0",
                    "unit": "USD",
                },
                "replay_spec": prepared.spec.document,
                "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 20},
            }
        ),
        development_dataset_id=prepared.dataset_id,
        confirmation_dataset_id="f" * 64,
    )
    spec = build_queue_constraint_spec(
        _canonical(request), protocol=protocol, replay_input=prepared.replay_input
    )
    return validate_queue_constraints(
        spec, protocol=protocol, replay_input=prepared.replay_input
    ).document


class _ShadowQueue:
    """Probe-only addressed queue observer, independently checked against domain trace."""

    def __init__(self, policy: str, request: dict[str, Any]):
        self.policy = policy
        self.updates = {update["capture_seq"]: update for update in request["updates"]}
        self.pending_trade_refs: list[int] = []
        self.current: Any = None
        self.index = 0
        self.active = False
        self.ahead = self.behind = self.external = self.observed = 0
        self.filled = 0
        self.offer = self.granted = self.consumed = 0
        self.grant_taken = False
        self.trace: list[dict[str, Any]] = []
        self.hooks: list[dict[str, Any]] = []
        self.current_row: dict[str, Any] = {}

    def queue(self):
        if not self.active:
            return None
        return {
            "ahead_lots": self.ahead,
            "behind_lots": self.behind,
            "external_lots": self.external,
        }

    def begin(self, event: Any) -> None:
        self.current = event
        before = self.queue()
        self.offer = self.granted = self.consumed = 0
        self.grant_taken = False
        flow = {
            "additions_lots": 0,
            "cancellations_lots": 0,
            "trade_lots": 0,
            "cancel_ahead_lots": 0,
            "cancel_behind_lots": 0,
        }
        if event.event_type == "trade":
            if event.price_ticks != 100 or event.aggressor_side != "sell":
                raise ValueError("Fixed probe accepts only target-price sell trades")
            quantity = event.quantity_lots
            if quantity > self.external:
                raise ValueError("Trade exceeds declared external visible depth")
            flow["trade_lots"] = quantity
            self.pending_trade_refs.append(event.capture_seq)
            if self.active:
                old_ahead = self.ahead
                self.ahead = max(0, self.ahead - quantity)
                self.behind -= max(0, quantity - old_ahead)
                self.offer = min(2 - self.filled, max(0, quantity - old_ahead))
            self.external -= quantity
        else:
            target = next((size for price, size in event.bids if price == 100), None)
            if target is not None:
                self.observed = target
                if event.event_type == "snapshot":
                    if self.index != 1 or self.active:
                        raise ValueError("Only the initial fixed snapshot can initialize depth")
                else:
                    update = self.updates.get(event.capture_seq)
                    if update is None:
                        raise ValueError("Every target checkpoint requires declared gross flow")
                    addition, cancellation = update["additions_lots"], update["cancellations_lots"]
                    if (
                        type(addition) is not int
                        or addition < 0
                        or type(cancellation) is not int
                        or cancellation < 0
                        or self.external + addition - cancellation != target
                        or update["trade_capture_seqs"] != self.pending_trade_refs
                    ):
                        raise ValueError(
                            "Declared gross flow or trade reconciliation is inconsistent"
                        )
                    self.pending_trade_refs.clear()
                    flow["additions_lots"] = addition
                    flow["cancellations_lots"] = cancellation
                    if self.active:
                        # Declared profile: add at tail, then allocate cancellations.
                        # Net depth alone cannot identify either gross quantity.
                        self.behind += addition
                        front = (
                            min(cancellation, self.ahead)
                            if self.policy == POLICIES[0]
                            else max(0, cancellation - self.behind)
                        )
                        back = cancellation - front
                        self.ahead -= front
                        self.behind -= back
                        flow["cancel_ahead_lots"] = front
                        flow["cancel_behind_lots"] = back
                self.external = target
        if self.active and (
            self.ahead < 0 or self.behind < 0 or self.ahead + self.behind != self.external
        ):
            raise ValueError("External queue conservation failed")
        self.current_row = {
            "source_ref": event.source_ref,
            "receive_time_ns": event.receive_time_ns,
            "market_observed_lots": self.observed,
            "before": before,
            "after": self.queue(),
            "flow": flow,
            "grant_limit_lots": self.offer,
            "granted_lots": 0,
            "native_filled_lots": 0,
            "own_remaining_lots": 2 - self.filled,
        }
        self.trace.append(self.current_row)

    def accepted(self) -> None:
        if self.active:
            raise ValueError("Probe order cannot be accepted twice")
        self.active = True
        self.ahead, self.behind = self.external, 0
        # Acceptance after this step's market processing cannot consume its past trade.
        self.offer = 0
        self.current_row["after"] = self.queue()
        self.current_row["accepted_here"] = True

    def take(self, *, origin: str) -> int:
        allowed = self.offer if self.active and not self.grant_taken else 0
        if self.current.event_type != "trade":
            allowed = 0
        self.grant_taken = True
        self.granted += allowed
        self.current_row["granted_lots"] = self.granted
        self.hooks.append(
            {
                "source_ref": self.current.source_ref,
                "origin": origin,
                "offered_lots": allowed,
                "cumulative_granted_lots": self.granted,
            }
        )
        return allowed

    def fill(self, quantity: int) -> None:
        if self.current.event_type != "trade" or quantity <= 0:
            raise ValueError("A shadow native fill requires a positive source trade")
        self.consumed += quantity
        if self.consumed > self.granted or self.filled + quantity > 2:
            raise ValueError("Native fill exceeded this capture's granted budget")
        self.filled += quantity
        self.current_row["native_filled_lots"] = self.consumed
        self.current_row["own_remaining_lots"] = 2 - self.filled


def _run(
    prepared: Any, policy: str, case_id: str, output: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    if metadata.version("nautilus_trader") != "1.231.0":
        raise ValueError("The queue probe requires pinned Nautilus 1.231.0")
    api = _native_api()
    api.OrderBook = importlib.import_module("nautilus_trader.model.book").OrderBook
    settings = _Settings.from_prepared(prepared)
    if (
        settings.price_increment != Decimal(1)
        or settings.size_increment != Decimal(1)
        or settings.limit_price_ticks != 100
        or settings.quantity_lots != 2
        or settings.starting_cash != Decimal(10000)
        or settings.maker_rate != Decimal("0.01")
        or settings.taker_rate != Decimal("0.02")
    ):
        raise ValueError("Fixed queue probe units, order, funding or fee assumptions changed")

    def price(ticks: int):
        return api.Price.from_str(_decimal(Decimal(ticks) * settings.price_increment))

    def quantity(lots: int):
        return api.Quantity.from_str(_decimal(Decimal(lots) * settings.size_increment))

    iid, venue = api.InstrumentId.from_str("EURUSD.SIM"), api.Venue("SIM")
    queue = _ShadowQueue(policy, request)
    orders: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    failure: list[Exception] = []
    commission = Decimal(0)
    pending: set[str] = set()
    output.update(
        {
            "engine": {"id": "nautilus-trader", "version": "1.231.0", "semantic_id": SEMANTIC_ID},
            "environment": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "package_versions": {
                    name: metadata.version(name)
                    for name in ("nautilus_trader", "numpy", "pandas", "pyarrow", "msgspec")
                },
            },
            "policy_id": policy,
            "normalized_sha256": prepared.data_sha256,
            "normalized_jsonl": prepared.replay_input.normalized_bytes.decode("utf-8"),
            "spec_id": prepared.spec.spec_id,
            "spec": prepared.spec.document,
            "declared_gross_flow_request": json.loads(_canonical(request)),
            "flow_source": "declared_gross_additions_cancellations_and_trade_references",
            "queue_trace": queue.trace,
            "hook_trace": queue.hooks,
            "order_trace": orders,
            "fill_trace": fills,
            "account_trace": accounts,
            "accepted": accepted,
            "decisions": decisions,
        }
    )

    def account(strategy: Any, label: str) -> None:
        native = strategy.portfolio.account(venue)
        if native is None:
            raise ValueError("Native account is unavailable")
        total = native.balance_total(api.USD).as_decimal()
        free = native.balance_free(api.USD).as_decimal()
        locked = native.balance_locked(api.USD).as_decimal()
        positions = strategy.cache.positions_open(instrument_id=iid)
        lots = sum(_units(position.quantity, settings.size_increment) for position in positions)
        if any(position.side.name != "LONG" for position in positions) or free + locked != total:
            raise ValueError("Native long-only account conservation failed")
        accounts.append(
            {
                "kind": label,
                "native_time_ns": strategy.clock.timestamp_ns(),
                "cash_total": format(total, "f"),
                "cash_free": format(free, "f"),
                "cash_locked": format(locked, "f"),
                "position_lots": lots,
                "commission": format(commission, "f"),
            }
        )

    class PublicQueueModule(api.SimulationModule):
        def __init__(self):
            super().__init__(api.SimulationModuleConfig())

        def pre_process(self, data):
            try:
                event = prepared.events[queue.index]
                native_id = (
                    str(data.trade_id) if event.event_type == "trade" else str(data.sequence)
                )
                expected = (
                    f"CAPTURE-{event.capture_seq}"
                    if event.event_type == "trade"
                    else str(event.capture_seq)
                )
                if native_id != expected or data.ts_init != event.receive_time_ns:
                    raise ValueError("Native source order differs from fixed qualification input")
                queue.index += 1
                queue.begin(event)
            except Exception as error:
                failure.append(error)
                raise

        def process(self, ts_now):
            pass

        def log_diagnostics(self, logger):
            pass

        def reset(self):
            pass

    class PublicQueueFill(api.FillModel):
        def __init__(self):
            super().__init__(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=7)
            self.probing_repeat = False

        def get_orderbook_for_fill_simulation(self, instrument, order, best_bid, best_ask):
            allowed = queue.take(
                origin=(
                    "explicit_repeated_public_hook_probe"
                    if self.probing_repeat
                    else "native_or_explicit_public_hook"
                )
            )
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
            if case_id == "repeated_public_hook" and allowed and not self.probing_repeat:
                self.probing_repeat = True
                duplicate = self.get_orderbook_for_fill_simulation(
                    instrument, order, best_bid, best_ask
                )
                self.probing_repeat = False
                if duplicate.best_ask_size() is not None:
                    raise ValueError("Repeated public hook exposed liquidity twice")
            # None would fall back to default matching. Empty is deliberately authoritative.
            return book

    model = PublicQueueFill()

    class ProbeBuy(api.Strategy):
        def __init__(self):
            super().__init__(
                api.StrategyConfig(
                    strategy_id="QueueProbe-001",
                    order_id_tag="001",
                    use_uuid_client_order_ids=False,
                    log_events=False,
                    log_commands=False,
                )
            )
            self.order = None
            self.cancel_sent = False

        def on_start(self):
            self.subscribe_order_book_deltas(iid, book_type=api.BookType.L2_MBP)
            self.subscribe_trade_ticks(iid)
            account(self, "initial")

        def on_order_book_deltas(self, deltas):
            try:
                current = queue.current
                if self.order is None and current.capture_seq == 1:
                    self.order = self.order_factory.limit(
                        iid,
                        api.OrderSide.BUY,
                        quantity(settings.quantity_lots),
                        price(settings.limit_price_ticks),
                        post_only=True,
                    )
                    decisions.append(
                        {
                            "action": "submit",
                            "source_ref": current.source_ref,
                            "native_time_ns": self.clock.timestamp_ns(),
                        }
                    )
                    pending.add("submit")
                    self.submit_order(self.order)
                if case_id == "nontrade_empty_book" and current.capture_seq == 3:
                    book = model.get_orderbook_for_fill_simulation(
                        self.cache.instrument(iid),
                        self.order,
                        price(100),
                        price(103),
                    )
                    if book.best_ask_size() is not None:
                        raise ValueError("Non-trade public hook exposed fill liquidity")
                if current.capture_seq == 6 and self.order is not None and not self.order.is_closed:
                    self.cancel_sent = True
                    decisions.append(
                        {
                            "action": "cancel",
                            "source_ref": current.source_ref,
                            "native_time_ns": self.clock.timestamp_ns(),
                        }
                    )
                    pending.add("cancel")
                    self.cancel_order(self.order)
            except Exception as error:
                failure.append(error)
                raise

        def on_order_accepted(self, event):
            try:
                pending.discard("submit")
                queue.accepted()
                book = self.cache.order_book(iid)
                actual_depth = _units(book.best_bid_size(), settings.size_increment)
                if actual_depth != queue.external:
                    raise ValueError("Acceptance queue differs from native public book depth")
                accepted.append(
                    {
                        "source_ref": queue.current.source_ref,
                        "native_time_ns": self.clock.timestamp_ns(),
                        "native_bid_lots": actual_depth,
                        "queue": queue.queue(),
                    }
                )
            except Exception as error:
                failure.append(error)
                raise

        def on_order_event(self, event):
            try:
                kind = type(event).__name__
                if kind in ("OrderRejected", "OrderCanceled", "OrderExpired"):
                    pending.discard("submit")
                if kind in ("OrderCanceled", "OrderCancelRejected"):
                    pending.discard("cancel")
                native = self.cache.order(event.client_order_id)
                orders.append(
                    {
                        "kind": kind,
                        "source_ref": None if queue.current is None else queue.current.source_ref,
                        "native_time_ns": self.clock.timestamp_ns(),
                        "order_id": str(event.client_order_id),
                        "status": None if native is None else native.status.name,
                        "pending_commands": sorted(pending),
                    }
                )
            except Exception as error:
                failure.append(error)
                raise

        def on_order_filled(self, event):
            nonlocal commission
            try:
                filled_quantity = _units(event.last_qty, settings.size_increment)
                queue.fill(filled_quantity)
                pending.discard("submit")
                commission += event.commission.as_decimal()
                fills.append(
                    {
                        "source_ref": queue.current.source_ref,
                        "native_time_ns": self.clock.timestamp_ns(),
                        "quantity_lots": filled_quantity,
                        "price": str(event.last_px),
                        "commission": format(event.commission.as_decimal(), "f"),
                        "liquidity_side": event.liquidity_side.name,
                        "native_trade_id": str(event.trade_id),
                    }
                )
                account(self, "fill_callback")
            except Exception as error:
                failure.append(error)
                raise

    engine = api.BacktestEngine(
        config=api.BacktestEngineConfig(
            trader_id=api.TraderId("QUEUEPROBE-001"),
            logging=api.LoggingConfig(bypass_logging=True),
            run_analysis=False,
        )
    )
    try:
        engine.add_venue(
            venue=venue,
            oms_type=api.OmsType.NETTING,
            account_type=api.AccountType.MARGIN,
            base_currency=api.USD,
            starting_balances=[api.Money.from_str("10000.00 USD")],
            default_leverage=Decimal(1),
            book_type=api.BookType.L2_MBP,
            modules=[PublicQueueModule()],
            fill_model=model,
            latency_model=api.LatencyModel(
                base_latency_nanos=0,
                insert_latency_nanos=settings.insert_latency,
                cancel_latency_nanos=0,
            ),
            use_message_queue=True,
            use_random_ids=False,
            trade_execution=True,
            bar_execution=False,
            queue_position=False,
            liquidity_consumption=True,
        )
        now = prepared.events[0].receive_time_ns
        engine.add_instrument(
            api.CurrencyPair(
                instrument_id=iid,
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
        engine.add_data(
            _make_data(
                SimpleNamespace(
                    prepared=prepared,
                    settings=settings,
                    iid=iid,
                    api=api,
                )
            )
        )
        strategy = ProbeBuy()
        engine.add_strategy(strategy)
        engine.run()
        if failure:
            raise failure[0]
        if queue.index != len(prepared.events):
            raise ValueError("Not all fixed qualification inputs were processed")
        account(strategy, "final")
        open_orders = [
            {"order_id": str(order.client_order_id), "status": order.status.name}
            for order in strategy.cache.orders()
            if not order.is_closed
        ]
        output.update(
            {
                "engine": {
                    "id": "nautilus-trader",
                    "version": "1.231.0",
                    "semantic_id": SEMANTIC_ID,
                },
                "environment": {
                    "python_version": platform.python_version(),
                    "platform": platform.platform(),
                    "package_versions": {
                        name: metadata.version(name)
                        for name in ("nautilus_trader", "numpy", "pandas", "pyarrow", "msgspec")
                    },
                },
                "scenario_kind": "MODEL_SENSITIVITY",
                "impact_unverified": True,
                "policy_id": policy,
                "queue_position": False,
                "normalized_sha256": prepared.data_sha256,
                "normalized_jsonl": prepared.replay_input.normalized_bytes.decode("utf-8"),
                "input_mapping": "existing_fixed_EURUSD_receive_order_input_mapper_only",
                "spec_id": prepared.spec.spec_id,
                "spec": prepared.spec.document,
                "accepted": accepted,
                "queue_trace": queue.trace,
                "hook_trace": queue.hooks,
                "decisions": decisions,
                "order_trace": orders,
                "fill_trace": fills,
                "account_trace": accounts,
                "filled_lots": queue.filled,
                "commission": format(commission, "f"),
                "completeness": {
                    "input_records": len(prepared.events),
                    "processed_records": queue.index,
                    "open_orders": open_orders,
                    "pending_commands": sorted(pending),
                    "stop_reason": "pending_commands_at_data_end"
                    if pending
                    else "input_exhausted_with_open_orders"
                    if open_orders
                    else "input_exhausted",
                },
                "execution_status": "incomplete" if open_orders or pending else "completed",
            }
        )
        return output
    finally:
        output.update(
            {
                "filled_lots": queue.filled,
                "commission": format(commission, "f"),
                "observed_pending_commands": sorted(pending),
                "observed_processed_records": queue.index,
            }
        )
        engine.dispose()


def run_case(case_id: str) -> dict[str, Any]:
    if case_id not in CASE_IDS:
        raise ValueError("Unknown fixed queue qualification case")
    case: dict[str, Any] = {"case_id": case_id, "checks": [], "runs": {}, "passed": False}
    try:
        rows, request, prepared = _input(case_id)
        policies = (
            POLICIES
            if case_id in (
                "front_back_cancel",
                "gross_churn_checkpoint",
                "no_cancel_control",
                "same_time_capture_order",
            )
            else POLICIES[:1]
        )
        oracle = None
        if len(policies) == 2:
            oracle = _oracle(request, prepared)
            case["external_constraint_oracle"] = oracle
        for policy in policies:
            observed: dict[str, Any] = {}
            case["runs"][policy] = observed
            _run(prepared, policy, case_id, observed, request)
            expected_fills = (
                0
                if case_id in ("no_cancel_control", "late_acceptance", "eof_pending_insert")
                or policy == POLICIES[1]
                else 1
            )
            _check(
                case,
                policy + ": actual native fill quantity",
                observed["filled_lots"],
                expected_fills,
            )
            _check(case, policy + ": exact actual fee", observed["commission"], str(expected_fills))
            final = observed["account_trace"][-1]
            _check(case, policy + ": native final position", final["position_lots"], expected_fills)
            _check(
                case,
                policy + ": native cash after actual fees",
                Decimal(final["cash_total"]) == Decimal(10000 - expected_fills),
                True,
            )
            _check(
                case,
                policy + ": native terminal clock is final real input",
                final["native_time_ns"],
                rows[-1]["receive_time_ns"],
            )
            _check(
                case,
                policy + ": all records processed",
                observed["completeness"]["processed_records"],
                len(rows),
            )
            eof = case_id in ("eof_open_orders", "eof_pending_insert")
            _check(
                case,
                policy + ": completion is explicit",
                observed["execution_status"],
                "incomplete" if eof else "completed",
            )
            canceled = [row for row in observed["order_trace"] if row["kind"] == "OrderCanceled"]
            _check(case, policy + ": cancel acknowledgement count", len(canceled), 0 if eof else 1)
            if not eof:
                _check(
                    case,
                    policy + ": cancel acknowledgement source",
                    canceled[0]["source_ref"]["capture_seq"] if canceled else None,
                    6,
                )
                _check(
                    case,
                    policy + ": no pending commands",
                    observed["completeness"]["pending_commands"],
                    [],
                )
            if oracle is not None:
                interpretation = next(
                    item for item in oracle["interpretations"] if item["policy_id"] == policy
                )
                expected = [
                    (step["source_ref"], step["flow"], step["after"])
                    for step in interpretation["trace"]
                ]
                actual = [
                    (step["source_ref"], step["flow"], step["after"])
                    for step in observed["queue_trace"]
                ]
                _check(case, policy + ": independent domain external queue trace", actual, expected)
            if case_id == "repeated_public_hook":
                repeats = [
                    row["offered_lots"]
                    for row in observed["hook_trace"]
                    if row["origin"] == "explicit_repeated_public_hook_probe"
                ]
                _check(case, "repeated public hook is empty", repeats, [0])
            if case_id == "nontrade_empty_book":
                at_delta = [
                    row["offered_lots"]
                    for row in observed["hook_trace"]
                    if row["source_ref"]["capture_seq"] == 3
                ]
                _check(case, "nontrade public hook is empty", at_delta, [0])
            if case_id == "late_acceptance":
                _check(
                    case,
                    "acceptance belongs to actual later input",
                    [row["source_ref"]["capture_seq"] for row in observed["accepted"]],
                    [5],
                )
                _check(
                    case,
                    "later acceptance snapshots current external depth",
                    observed["accepted"][0]["queue"] if observed["accepted"] else None,
                    {"ahead_lots": 2, "behind_lots": 0, "external_lots": 2},
                )
            if case_id == "eof_pending_insert":
                _check(case, "no accepted queue is fabricated", observed["accepted"], [])
                _check(
                    case,
                    "pending insert retained at EOF",
                    observed["completeness"]["pending_commands"],
                    ["submit"],
                )
        if len(policies) == 2:
            _check(
                case,
                "same exact observation bytes across interpretations",
                [run["normalized_sha256"] for run in case["runs"].values()],
                [prepared.data_sha256, prepared.data_sha256],
            )
        case["passed"] = bool(case["checks"]) and all(item["passed"] for item in case["checks"])
    except Exception as error:
        case["error"] = {"type": type(error).__name__, "message": str(error)}
    return case


def qualify() -> dict[str, Any]:
    cases = [run_case(case_id) for case_id in CASE_IDS]
    return {
        "kind": "queue_model_native_qualification_v1",
        "schema_version": 1,
        "semantic_id": SEMANTIC_ID,
        "scenario_kind": "MODEL_SENSITIVITY",
        "impact_unverified": True,
        "observation_compatibility_proved": False,
        "finding_issued": False,
        "production_queue_execution_enabled": False,
        "qualification_scope": {
            "fixed_original_cases_only": True,
            "arbitrary_user_execution_enabled": False,
        },
        "public_extension_probe_qualified": all(case["passed"] for case in cases),
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = qualify()
    raw = _canonical(report) + b"\n"
    if arguments.output is None:
        print(raw.decode("utf-8"), end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_bytes(raw)
    return 0 if report["public_extension_probe_qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
