#!/usr/bin/env python3
"""S01 feasibility probe only; synthetic input, no exchange/network access.

Drive the public Python interface at feed/order-response boundaries. This is not
a production adapter or a complete per-fill event sink. See the research note.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
from hftbacktest import BacktestAsset, FILLED, GTX, LIMIT, HashMapMarketDepthBacktest
from hftbacktest.types import (
    BUY_EVENT,
    DEPTH_EVENT,
    EXCH_EVENT,
    LOCAL_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
    event_dtype,
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def build_input() -> tuple[np.ndarray, list[dict]]:
    """Artificial nanosecond times, lot/tick=1, visible queue initially 2."""
    t = 1_000_000_000
    flags = EXCH_EVENT | LOCAL_EVENT
    rows = [
        (DEPTH_EVENT | BUY_EVENT | flags, t, t + 100, 99.0, 2.0, 0, 0, 0.0),
        (DEPTH_EVENT | SELL_EVENT | flags, t + 1, t + 101, 101.0, 2.0, 0, 0, 0.0),
        (TRADE_EVENT | SELL_EVENT | flags, t + 1000, t + 1100, 99.0, 3.0, 0, 0, 0.0),
        (DEPTH_EVENT | BUY_EVENT | flags, t + 2000, t + 2100, 99.0, 2.0, 0, 0, 0.0),
        (DEPTH_EVENT | SELL_EVENT | flags, t + 2001, t + 2101, 101.0, 2.0, 0, 0, 0.0),
        (TRADE_EVENT | BUY_EVENT | flags, t + 3000, t + 3100, 101.0, 3.0, 0, 0, 0.0),
        (DEPTH_EVENT | BUY_EVENT | flags, t + 4000, t + 4100, 99.0, 2.0, 0, 0, 0.0),
        (DEPTH_EVENT | SELL_EVENT | flags, t + 4001, t + 4101, 101.0, 2.0, 0, 0, 0.0),
    ]
    data = np.array(rows, dtype=event_dtype)
    named_rows = []
    for index, row in enumerate(data):
        record = {name: row[name].item() for name in event_dtype.names}
        record["input_id"] = f"synthetic-{index:03d}"
        named_rows.append(record)
    return data, named_rows


def snapshot(hbt, boundary: str, return_code: int, input_rows: list[dict]) -> dict:
    state = hbt.state_values(0)
    depth = hbt.depth(0)
    orders = []
    for order_id in (1, 2):
        order = hbt.orders(0).get(order_id)
        if order is None:
            continue
        orders.append(
            {
                "order_id": int(order.order_id),
                "side": int(order.side),
                "status": int(order.status),
                "request_status": int(order.req),
                "price": float(order.price),
                "quantity": float(order.qty),
                "leaves_quantity": float(order.leaves_qty),
                "last_exec_quantity": float(order.exec_qty),
                "last_exec_price": float(order.exec_price),
                "exchange_timestamp_ns": int(order.exch_timestamp),
                "local_timestamp_ns": int(order.local_timestamp),
            }
        )
    now = int(hbt.current_timestamp)
    return {
        "boundary": boundary,
        "return_code": return_code,
        "timestamp_ns": now,
        "available_input_ids": [r["input_id"] for r in input_rows if r["local_ts"] <= now],
        "best_bid": finite_or_none(depth.best_bid),
        "best_ask": finite_or_none(depth.best_ask),
        "orders": orders,
        "position": float(state.position),
        "cash_balance_excluding_fee": float(state.balance),
        "accumulated_fee": float(state.fee),
        "num_trades": int(state.num_trades),
        "trading_volume": float(state.trading_volume),
        "trading_value": float(state.trading_value),
    }


def run() -> dict:
    if importlib.metadata.version("hftbacktest") != "2.4.4":
        raise RuntimeError("This spike was validated only with hftbacktest==2.4.4")
    data, input_rows = build_input()
    config = {
        "linear_contract_size": 1.0,
        "tick_size": 1.0,
        "lot_size": 1.0,
        "entry_latency_ns": 10,
        "response_latency_ns": 10,
        "feed_latency_ns": 100,
        "queue_model": "risk_adverse_queue_model",
        "exchange_model": "partial_fill_exchange",
        "maker_fee_rate": 0.001,
        "taker_fee_rate": 0.002,
        "strategy": "one passive buy at 99; after observed fill one passive sell at 101",
    }
    asset = (
        BacktestAsset()
        .data([data])
        .linear_asset(1.0)
        .tick_size(1.0)
        .lot_size(1.0)
        .constant_order_latency(10, 10)
        .risk_adverse_queue_model()
        .partial_fill_exchange()
        .trading_value_fee_model(0.001, 0.002)
        .last_trades_capacity(10)
        .parallel_load(False)
    )
    hbt = HashMapMarketDepthBacktest([asset])
    trace = []
    decisions = []
    buy_submitted = False
    sell_submitted = False
    try:
        for _ in range(64):
            rc = int(hbt.wait_next_feed(True, 10_000))
            trace.append(snapshot(hbt, "feed_or_response", rc, input_rows))
            if rc == 1:
                break
            if rc not in (0, 2, 3):
                raise RuntimeError(f"Unexpected engine return code {rc}")
            depth = hbt.depth(0)
            if not buy_submitted and math.isfinite(depth.best_bid) and math.isfinite(depth.best_ask):
                decision = {
                    "decision_id": "decision-buy",
                    "timestamp_ns": int(hbt.current_timestamp),
                    "observed_input_ids": trace[-1]["available_input_ids"],
                    "action": "submit_buy",
                    "order_id": 1,
                    "price": 99.0,
                    "quantity": 1.0,
                }
                decision["return_code"] = int(hbt.submit_buy_order(0, 1, 99.0, 1.0, GTX, LIMIT, False))
                assert decision["return_code"] == 0
                decisions.append(decision)
                buy_submitted = True
                trace.append(snapshot(hbt, "after_submit_buy", 0, input_rows))
            buy = hbt.orders(0).get(1)
            if buy_submitted and not sell_submitted and buy is not None and buy.status == FILLED:
                decision = {
                    "decision_id": "decision-sell",
                    "timestamp_ns": int(hbt.current_timestamp),
                    "observed_input_ids": trace[-1]["available_input_ids"],
                    "trigger": "observed order 1 FILLED response",
                    "action": "submit_sell",
                    "order_id": 2,
                    "price": 101.0,
                    "quantity": 1.0,
                }
                decision["return_code"] = int(hbt.submit_sell_order(0, 2, 101.0, 1.0, GTX, LIMIT, False))
                assert decision["return_code"] == 0
                decisions.append(decision)
                sell_submitted = True
                trace.append(snapshot(hbt, "after_submit_sell", 0, input_rows))
        else:
            raise RuntimeError("Safety iteration bound reached")

        final = trace[-1]
        assert buy_submitted and sell_submitted
        assert final["position"] == 0.0
        assert final["num_trades"] == 2
        assert final["cash_balance_excluding_fee"] == 2.0
        assert math.isclose(final["accumulated_fee"], 0.2, rel_tol=0.0, abs_tol=1e-12)
        assert all(order["status"] == FILLED for order in final["orders"])
        return {
            "spike_schema": "hftbacktest-feasibility-v1",
            "config": config,
            "inputs": input_rows,
            "decisions": decisions,
            "trace": trace,
            "summary": {
                "input_events": len(input_rows),
                "decisions": len(decisions),
                "fills_observed_in_this_fixture": final["num_trades"],
                "position": final["position"],
                "gross_cash_change": final["cash_balance_excluding_fee"],
                "fees": final["accumulated_fee"],
                "net_cash_change": final["cash_balance_excluding_fee"] - final["accumulated_fee"],
                "complete_per_fill_event_sink_verified": False,
                "checkpoint_resume_verified": False,
            },
        }
    finally:
        hbt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = run()
    encoded = canonical_bytes(payload)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "trace.json").write_bytes(encoded + b"\n")
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": {name: importlib.metadata.version(name) for name in ("hftbacktest", "numpy", "numba", "llvmlite")},
        "trace_sha256": hashlib.sha256(encoded + b"\n").hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (args.output_dir / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    print(json.dumps({"summary": payload["summary"], "trace_sha256": environment["trace_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
