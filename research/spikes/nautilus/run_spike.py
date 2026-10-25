"""S01-01 feasibility probe for the pinned NautilusTrader v1 API.

Synthetic, offline data only. This is neither a product adapter nor a benchmark.
The strategy's decision records are explicit instrumentation written for this
probe; the engine does not expose arbitrary strategies' private reasoning.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from decimal import Decimal
from pathlib import Path

import nautilus_trader
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, LatencyModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import EUR, USD
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AccountType, BookType, OmsType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy


EXPECTED_VERSION = "1.231.0"
INSTRUMENT_ID = InstrumentId.from_str("EURUSD.SIM")
START_NS = 1_700_000_000_000_000_000
BID_PRICES = ("1.00000", "1.00005", "1.00015", "1.00010", "1.00002", "1.00000", "1.00000")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def make_instrument() -> CurrencyPair:
    return CurrencyPair(
        instrument_id=INSTRUMENT_ID,
        raw_symbol=Symbol("EURUSD"),
        base_currency=EUR,
        quote_currency=USD,
        price_precision=5,
        size_precision=0,
        price_increment=Price.from_str("0.00001"),
        size_increment=Quantity.from_int(1),
        lot_size=Quantity.from_int(1),
        min_quantity=Quantity.from_int(1),
        margin_init=Decimal("1"),
        margin_maint=Decimal("1"),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=START_NS,
        ts_init=START_NS,
    )


def make_quotes() -> list[QuoteTick]:
    return [
        QuoteTick(
            instrument_id=INSTRUMENT_ID,
            bid_price=Price.from_str(bid),
            ask_price=Price.from_str(format(Decimal(bid) + Decimal("0.00002"), ".5f")),
            bid_size=Quantity.from_int(10_000),
            ask_size=Quantity.from_int(10_000),
            ts_event=START_NS + index * 1_000_000_000,
            ts_init=START_NS + index * 1_000_000_000,
        )
        for index, bid in enumerate(BID_PRICES)
    ]


def quote_record(tick: QuoteTick) -> dict[str, object]:
    return {
        "type": "QuoteTick",
        "instrument_id": str(tick.instrument_id),
        "ts_event": str(tick.ts_event),
        "ts_init": str(tick.ts_init),
        "bid": str(tick.bid_price),
        "ask": str(tick.ask_price),
        "bid_size": str(tick.bid_size),
        "ask_size": str(tick.ask_size),
    }


class TwoDecisions(Strategy):
    """Buy on quote 0 and sell on quote 3, independently of the fill outcome."""

    def __init__(self) -> None:
        super().__init__(
            StrategyConfig(
                strategy_id="Probe-001",
                order_id_tag="001",
                use_uuid_client_order_ids=False,
                log_events=False,
                log_commands=False,
            )
        )
        self.inputs: list[dict[str, object]] = []
        self.decisions: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []
        self.fills: list[dict[str, object]] = []

    def on_start(self) -> None:
        self.subscribe_quote_ticks(INSTRUMENT_ID)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        ordinal = len(self.inputs)
        self.inputs.append(quote_record(tick))
        if ordinal not in (0, 3):
            return
        side = OrderSide.BUY if ordinal == 0 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=INSTRUMENT_ID,
            order_side=side,
            quantity=Quantity.from_int(1000),
        )
        self.decisions.append(
            {
                "input_ordinal": ordinal,
                "clock_ns": str(self.clock.timestamp_ns()),
                "side": side.name,
                "quantity": "1000",
                "client_order_id": str(order.client_order_id),
            }
        )
        self.submit_order(order)

    def on_order_event(self, event: object) -> None:
        # UUID event IDs are deliberately omitted from semantic determinism.
        row = {
            "type": type(event).__name__,
            "client_order_id": str(event.client_order_id),
            "ts_event": str(event.ts_event),
            "ts_init": str(event.ts_init),
        }
        self.events.append(row)

    def on_order_filled(self, event: object) -> None:
        self.fills.append(
            {
                "client_order_id": str(event.client_order_id),
                "side": event.order_side.name,
                "quantity": str(event.last_qty),
                "price": str(event.last_px),
                "commission": str(event.commission),
                "liquidity_side": event.liquidity_side.name,
                "ts_event": str(event.ts_event),
                "ts_init": str(event.ts_init),
            }
        )


def run_once(insert_latency_ns: int) -> dict[str, object]:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("PROBE-001"),
            logging=LoggingConfig(bypass_logging=True),
            run_analysis=False,
        )
    )
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(10_000, USD)],
        default_leverage=Decimal("1"),
        book_type=BookType.L1_MBP,
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=7),
        latency_model=LatencyModel(base_latency_nanos=0, insert_latency_nanos=insert_latency_ns),
        use_message_queue=True,
        use_random_ids=False,
        trade_execution=False,
        bar_execution=False,
        queue_position=False,
        liquidity_consumption=True,
    )
    engine.add_instrument(make_instrument())
    engine.add_data(make_quotes())
    strategy = TwoDecisions()
    engine.add_strategy(strategy)
    try:
        engine.run()
        account = engine.cache.account_for_venue(Venue("SIM"))
        report = engine.trader.generate_account_report(Venue("SIM"))
        # Account report rows are snapshots from engine account state events.
        account_rows = report.reset_index().to_dict(orient="records")
        for row in account_rows:
            row["ts_event_ns"] = str(row.pop("index").value)
        positions = engine.cache.positions()
        assert len(strategy.inputs) == 7
        assert len(strategy.decisions) == 2
        assert len(strategy.fills) == 2, strategy.fills
        assert all(position.is_closed for position in positions), positions
        buy, sell = strategy.fills
        realized = (Decimal(sell["price"]) - Decimal(buy["price"])) * Decimal("1000")
        final_cash = account.balance_total(USD).as_decimal()
        assert final_cash == Decimal("10000") + realized, (final_cash, realized)
        return {
            "scenario_kind": "BASELINE" if insert_latency_ns == 0 else "COUNTERFACTUAL_STRESS",
            "insert_latency_ns": str(insert_latency_ns),
            "input_trace": strategy.inputs,
            "decisions": strategy.decisions,
            "order_events": strategy.events,
            "fills": strategy.fills,
            "account_report": account_rows,
            "final_cash_usd": str(final_cash),
            "realized_pnl_usd": str(realized),
            "closed_positions": len(positions),
        }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if nautilus_trader.__version__ != EXPECTED_VERSION:
        raise SystemExit(f"Expected v1 {EXPECTED_VERSION}, got {nautilus_trader.__version__}; do not mix v2 API")
    first = run_once(0)
    second = run_once(0)
    assert first == second, "Normalized baseline semantic traces differ"
    delayed = run_once(1_500_000_000)
    assert Decimal(first["realized_pnl_usd"]) > 0
    assert Decimal(delayed["realized_pnl_usd"]) < 0
    assert [fill["price"] for fill in first["fills"]] == ["1.00002", "1.00010"]
    # In this v1 setup, delayed commands settle at the next market-data step,
    # not at an independently inserted 1.5-second event.
    assert [fill["price"] for fill in delayed["fills"]] == ["1.00017", "1.00000"]
    metadata = importlib.metadata.distribution("nautilus_trader")
    result = {
        "status": "EXECUTED_SYNTHETIC_PROBE",
        "engine_version": nautilus_trader.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "package_license_expression": metadata.metadata.get("License-Expression"),
        "package_license": metadata.metadata.get("License"),
        "package_requires_python": metadata.metadata.get("Requires-Python"),
        "wheel_metadata": metadata.read_text("WHEEL"),
        "dependencies": {
            dist.metadata["Name"]: dist.version
            for dist in sorted(importlib.metadata.distributions(), key=lambda dist: dist.metadata["Name"].lower())
        },
        "determinism": {
            "baseline_runs": 2,
            "semantic_traces_equal": True,
            "semantic_sha256": digest(first),
            "semantic_sha256_repeat": digest(second),
            "excluded": ["random event UUIDs", "engine instance/run IDs", "wall-clock runtime", "logging"],
            "scope": "same interpreter, package versions, machine and fixture; not cross-platform bitwise proof",
        },
        "baseline": first,
        "baseline_repeat": second,
        "delayed_order_stress": delayed,
        "limits": [
            "Original synthetic L1 quotes; not real exchange data or a profitable strategy claim",
            "No exchange connection, network data, credentials or live execution",
            "Decision trace is explicitly instrumented in this strategy; not arbitrary-strategy reasoning extraction",
            "No L2 queue inference, partial fill, fees, custom FillModel or checkpoint restoration tested",
            "Extra order latency is a counterfactual stress scenario, not an observation-compatible historical explanation",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "engine_version": EXPECTED_VERSION,
        "determinism": result["determinism"],
        "baseline_pnl_usd": first["realized_pnl_usd"],
        "stress_pnl_usd": delayed["realized_pnl_usd"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
