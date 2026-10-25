#!/usr/bin/env python3
"""S2 selection probes: queue estimates, partial-fill polling, and EOF.

Offline synthetic research only. Does not implement an adapter, a custom Rust
queue model, or a certified observation-compatible-world verifier.
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
from hftbacktest import FILLED, GTX, LIMIT, BacktestAsset, HashMapMarketDepthBacktest
from hftbacktest.order import PARTIALLY_FILLED
from hftbacktest.types import (
    BUY_EVENT,
    DEPTH_EVENT,
    EXCH_EVENT,
    LOCAL_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
    event_dtype,
)

BASE = 1_000_000_000
MODELS = (
    ("risk_adverse", None),
    ("log_prob", None),
    ("log_prob2", None),
    ("power_prob", 2.0),
    ("power_prob2", 2.0),
    ("power_prob3", 2.0),
    ("power_prob2", 16.0),
)


def row(offset: int, kind: int, side: int, price: float, qty: float, role: str) -> dict:
    return {
        "ev": kind | side | EXCH_EVENT | LOCAL_EVENT,
        "exch_ts": BASE + offset,
        "local_ts": BASE + offset + 100,
        "px": price,
        "qty": qty,
        "order_id": 0,
        "ival": 0,
        "fval": 0.0,
        "role": role,
    }


def queue_rows(cancel: bool) -> list[dict]:
    rows = [
        row(0, DEPTH_EVENT, BUY_EVENT, 100.0, 1000.0, "A_initial_front"),
        row(1, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "A_initial_ask"),
        row(1000, DEPTH_EVENT, BUY_EVENT, 100.0, 2000.0, "B_add_behind"),
    ]
    if cancel:
        rows.append(row(2000, DEPTH_EVENT, BUY_EVENT, 100.0, 1000.0, "C_cancel_unknown_location"))
    rows.extend(
        [
            row(3000, TRADE_EVENT, SELL_EVENT, 100.0, 1.0 if cancel else 1001.0, "D_trade"),
            row(4000, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "tail_guard_1"),
            row(5000, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "tail_guard_2"),
        ]
    )
    return rows


def partial_rows(same_exchange_time: bool = False) -> list[dict]:
    second = 1000 if same_exchange_time else 2000
    specs = [
        row(0, DEPTH_EVENT, BUY_EVENT, 100.0, 1.0, "initial_front_one"),
        row(1, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "initial_ask"),
        row(500, DEPTH_EVENT, BUY_EVENT, 100.0, 4.0, "add_three_behind"),
        row(1000, TRADE_EVENT, SELL_EVENT, 100.0, 2.0, "trade_clear_front_fill_one"),
        row(
            1000 if same_exchange_time else 1001,
            DEPTH_EVENT,
            BUY_EVENT,
            100.0,
            2.0,
            "depth_after_first_trade",
        ),
        row(second, TRADE_EVENT, SELL_EVENT, 100.0, 1.0, "trade_fill_remaining_one"),
        row(
            second if same_exchange_time else second + 1,
            DEPTH_EVENT,
            BUY_EVENT,
            100.0,
            1.0,
            "depth_after_second_trade",
        ),
        row(4000, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "tail_guard_1"),
        row(5000, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "tail_guard_2"),
    ]
    # Preserve row order for equal exchange timestamps while the local stream
    # receives the four messages in distinct one-nanosecond steps.
    if same_exchange_time:
        for index in range(3, 7):
            specs[index]["local_ts"] = BASE + 1100 + index - 3
    return specs


def eof_rows(guard: str) -> list[dict]:
    rows = [
        row(0, DEPTH_EVENT, BUY_EVENT, 100.0, 1.0, "initial_front_one"),
        row(1, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "initial_ask"),
        row(500, DEPTH_EVENT, BUY_EVENT, 100.0, 4.0, "add_three_behind"),
        row(1000, TRADE_EVENT, SELL_EVENT, 100.0, 2.0, "final_trade_expected_fill_one"),
    ]
    if guard == "before_response":
        rows.append(row(1050, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "tail_guard_before_response"))
    elif guard == "after_response":
        rows.extend(
            [
                row(1500, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "tail_guard_after_response_1"),
                row(1600, DEPTH_EVENT, SELL_EVENT, 103.0, 1000.0, "tail_guard_after_response_2"),
            ]
        )
    return rows


def exact_oracle(cancel_front: bool, cancel: bool = True) -> dict:
    """Integer queue oracle; an expected world, not an executed HFT witness."""
    front, back = 1000, 0
    path = [{"step": "accepted", "front": front, "back": back}]
    back += 1000
    path.append({"step": "B", "front": front, "back": back})
    if cancel:
        if cancel_front:
            front -= 1000
        else:
            back -= 1000
        path.append({"step": "C", "front": front, "back": back})
    trade = 1 if cancel else 1001
    fill = min(1, max(0, trade - front))
    pnl = fill * 102 - fill * 100 - fill
    return {
        "world": "Q-front" if cancel_front else "Q-back",
        "status": "INTEGER_ORACLE_ONLY_NOT_ENGINE_WITNESS",
        "queue_path": path,
        "expected_fill": fill,
        "fixed_fee_if_filled": fill,
        "net_marked_pnl": pnl,
        "claim_truth": pnl > 0,
    }


def source_estimate(model: str, exponent: float | None) -> dict:
    """Pinned queue.rs formula for this symmetric fixture; not engine state."""
    if model == "risk_adverse":
        ahead = 1000.0
    elif model in ("log_prob", "power_prob"):
        ahead = 500.0
    elif model == "log_prob2":
        ahead = 1000.0 * math.log1p(1000.0) / math.log1p(2000.0)
    elif model == "power_prob2":
        ahead = 1000.0 * (0.5**exponent)
    elif model == "power_prob3":
        ahead = 1000.0 * (1.0 - 0.5**exponent)
    else:
        raise ValueError(model)
    executable = max(0, math.floor((1.0 - ahead) + 0.5))
    return {
        "ahead_after_C": ahead,
        "expected_fill_after_one_lot_trade_using_rust_round": min(1, executable),
        "provenance": "SOURCE_DERIVED_NOT_PUBLIC_ENGINE_QUEUE_OBSERVATION",
    }


def observe(hbt, stage: str, rc: int) -> dict:
    state = hbt.state_values(0)
    depth = hbt.depth(0)
    order = hbt.orders(0).get(1)
    feed_latency = hbt.feed_latency(0)
    order_latency = hbt.order_latency(0)
    order_out = None
    if order is not None:
        has_execution = order.status in (PARTIALLY_FILLED, FILLED)
        order_out = {
            "status": int(order.status),
            "request_status": int(order.req),
            "quantity": float(order.qty),
            "leaves_qty": float(order.leaves_qty),
            "last_exec_qty": float(order.exec_qty) if has_execution else None,
            "last_exec_price": float(order.exec_price) if has_execution else None,
            "exchange_timestamp_ns": int(order.exch_timestamp),
            "request_local_timestamp_ns": int(order.local_timestamp),
        }
    return {
        "stage": stage,
        "return_code": rc,
        "timestamp_ns": int(hbt.current_timestamp),
        "best_bid": float(depth.best_bid) if math.isfinite(depth.best_bid) else None,
        "best_ask": float(depth.best_ask) if math.isfinite(depth.best_ask) else None,
        "bid_qty": float(depth.bid_qty_at_tick(100)),
        "last_processed_feed": None
        if feed_latency is None
        else {
            "exchange_timestamp_ns": int(feed_latency[0]),
            "local_timestamp_ns": int(feed_latency[1]),
        },
        "last_processed_order_response": None
        if order_latency is None
        else {
            "request_timestamp_ns": int(order_latency[0]),
            "exchange_timestamp_ns": int(order_latency[1]),
            "response_timestamp_ns": int(order_latency[2]),
        },
        "order": order_out,
        "position": float(state.position),
        "cash_excluding_fee": float(state.balance),
        "fee": float(state.fee),
        "num_trades": int(state.num_trades),
        "trading_volume": float(state.trading_volume),
    }


def execute(
    case_id: str,
    rows: list[dict],
    model: str = "risk_adverse",
    exponent: float | None = None,
    order_qty: float = 1.0,
    response_latency: int = 10,
    coarse: bool = False,
) -> dict:
    data = np.array([tuple(r[name] for name in event_dtype.names) for r in rows], dtype=event_dtype)
    asset = (
        BacktestAsset()
        .data([data])
        .linear_asset(1.0)
        .tick_size(1.0)
        .lot_size(1.0)
        .constant_order_latency(10, response_latency)
        .partial_fill_exchange()
        .flat_per_trade_fee_model(1.0, 1.0)
        .parallel_load(False)
    )
    methods = {
        "risk_adverse": "risk_adverse_queue_model",
        "log_prob": "log_prob_queue_model",
        "log_prob2": "log_prob_queue_model2",
        "power_prob": "power_prob_queue_model",
        "power_prob2": "power_prob_queue_model2",
        "power_prob3": "power_prob_queue_model3",
    }
    method = getattr(asset, methods[model])
    asset = method() if exponent is None else method(exponent)
    hbt = HashMapMarketDepthBacktest([asset])
    trace, decisions = [], []
    submitted = False
    try:
        for _ in range(128):
            rc = int(hbt.wait_next_feed(True, 10_000))
            trace.append(observe(hbt, "wait_next_feed", rc))
            if rc == 1:
                break
            if rc not in (0, 2, 3):
                raise RuntimeError(f"unexpected return {rc}")
            d = hbt.depth(0)
            if not submitted and math.isfinite(d.best_bid) and math.isfinite(d.best_ask):
                rc_submit = int(hbt.submit_buy_order(0, 1, 100.0, order_qty, GTX, LIMIT, False))
                decisions.append(
                    {
                        "timestamp_ns": int(hbt.current_timestamp),
                        "order_id": 1,
                        "action": "BUY",
                        "price": 100.0,
                        "qty": order_qty,
                        "return_code": rc_submit,
                    }
                )
                if rc_submit != 0:
                    raise RuntimeError(f"submit return {rc_submit}")
                submitted = True
                trace.append(observe(hbt, "after_submit", rc_submit))
                if coarse:
                    rc_elapsed = int(hbt.elapse(3500))
                    trace.append(observe(hbt, "coarse_elapse_3500ns", rc_elapsed))
        else:
            raise RuntimeError("bounded loop exhausted")
        first_eof_index = len(trace) - 1
        # Explicitly test whether the public API drains pending work after EOD.
        for _ in range(2):
            rc = int(hbt.wait_next_feed(True, 10_000))
            trace.append(observe(hbt, "post_eof_wait", rc))
        rc = int(hbt.elapse(10_000))
        trace.append(observe(hbt, "post_eof_elapse", rc))
        observations, order_observations = [], []
        prev_trades, prev_position, prev_cash, prev_fee = 0, 0.0, 0.0, 0.0
        prev_order_filled = 0.0
        for index, sample in enumerate(trace):
            delta = sample["num_trades"] - prev_trades
            if delta > 0:
                observations.append(
                    {
                        "trace_index": index,
                        "timestamp_ns": sample["timestamp_ns"],
                        "trade_count_delta": delta,
                        "position_delta": sample["position"] - prev_position,
                        "cash_delta": sample["cash_excluding_fee"] - prev_cash,
                        "fee_delta": sample["fee"] - prev_fee,
                        "last_exec_qty": sample["order"]["last_exec_qty"],
                    }
                )
            prev_trades, prev_position = sample["num_trades"], sample["position"]
            prev_cash, prev_fee = sample["cash_excluding_fee"], sample["fee"]
            order = sample["order"]
            if order is not None:
                filled_from_leaves = order["quantity"] - order["leaves_qty"]
                if filled_from_leaves > prev_order_filled:
                    order_observations.append(
                        {
                            "trace_index": index,
                            "poll_timestamp_ns": sample["timestamp_ns"],
                            "filled_qty_delta_from_leaves": filled_from_leaves - prev_order_filled,
                            "last_exec_qty": order["last_exec_qty"],
                            "order_status": order["status"],
                            "last_processed_order_response": sample[
                                "last_processed_order_response"
                            ],
                            "note": (
                                "Derived for this no-cancel, no-modify fixture; "
                                "not a general fill event sink."
                            ),
                        }
                    )
                prev_order_filled = filled_from_leaves
        final = trace[-1]
        processed_times = [
            sample[field][key]
            for sample in trace
            for field, key in (
                ("last_processed_feed", "local_timestamp_ns"),
                ("last_processed_order_response", "response_timestamp_ns"),
            )
            if sample[field] is not None
        ]
        final_order_filled = (
            0.0 if final["order"] is None else order_qty - final["order"]["leaves_qty"]
        )
        return {
            "case_id": case_id,
            "status": "EXECUTED",
            "model": model,
            "exponent": exponent,
            "config": {
                "order_qty": order_qty,
                "entry_latency_ns": 10,
                "response_latency_ns": response_latency,
                "flat_fee_per_fill": 1.0,
                "coarse_polling": coarse,
                "engine": "hftbacktest==2.4.4",
            },
            "inputs": [dict(r, input_id=f"{case_id}-{index:02d}") for index, r in enumerate(rows)],
            "decisions": decisions,
            "trace": trace,
            "state_trade_count_changes": observations,
            "order_execution_observations": order_observations,
            "summary": {
                "position": final["position"],
                "cash_excluding_fee": final["cash_excluding_fee"],
                "fee": final["fee"],
                "num_trades": final["num_trades"],
                "net_marked_pnl_at_102": final["position"] * 102
                + final["cash_excluding_fee"]
                - final["fee"],
                "first_eof_trace_index": first_eof_index,
                "first_eof_time_ns": trace[first_eof_index]["timestamp_ns"],
                "last_scheduled_local_time_ns": max(r["local_ts"] for r in rows),
                "latest_processed_event_time_ns": max(processed_times),
                "order_filled_qty_from_leaves": final_order_filled,
                "local_position_matches_order_filled_qty": final["position"] == final_order_filled,
                "terminal_current_timestamp_covers_processed_events": final["timestamp_ns"]
                >= max(processed_times),
                "public_queue_ahead_available": False,
                "fill_event_sink_certified": False,
                "observation_compatible_witness_certified": False,
            },
        }
    finally:
        hbt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if importlib.metadata.version("hftbacktest") != "2.4.4":
        raise RuntimeError("pin hftbacktest==2.4.4")
    cases = []
    for cancel in (True, False):
        for model, exponent in MODELS:
            suffix = "" if exponent is None else f"-{exponent:g}"
            name = f"{'cancel' if cancel else 'no-cancel-control'}-{model}{suffix}"
            try:
                result = execute(name, queue_rows(cancel), model, exponent)
                if cancel:
                    result["source_derived_estimate"] = source_estimate(model, exponent)
                cases.append(result)
            except Exception as exc:
                cases.append({"case_id": name, "status": "ERROR", "exception": repr(exc)})
    for name, rows, qty, response, coarse in (
        ("partial-separated", partial_rows(), 2.0, 10, False),
        ("partial-same-exchange-time", partial_rows(True), 2.0, 10, False),
        ("partial-coarse-poll", partial_rows(), 2.0, 10, True),
        ("eof-no-guard", eof_rows("none"), 1.0, 200, False),
        ("eof-guard-before-response", eof_rows("before_response"), 1.0, 200, False),
        ("eof-guard-after-response", eof_rows("after_response"), 1.0, 200, False),
    ):
        try:
            cases.append(
                execute(name, rows, order_qty=qty, response_latency=response, coarse=coarse)
            )
        except Exception as exc:
            cases.append({"case_id": name, "status": "ERROR", "exception": repr(exc)})
    controls = [case for case in cases if case["case_id"].startswith("no-cancel-control-")]
    partial_mismatch = any(
        case["case_id"].startswith("partial-")
        and case.get("summary", {}).get("local_position_matches_order_filled_qty") is False
        for case in cases
    )
    stale_clock = any(
        case.get("summary", {}).get("terminal_current_timestamp_covers_processed_events") is False
        for case in cases
    )
    payload = {
        "schema": "hft-selection-probe-v1",
        "observed_client_date": "2026-10-25",
        "normalization": (
            "No wall-clock timestamp, random run ID, native pointer, or environment path included."
        ),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name) for name in ("hftbacktest", "numpy", "numba")
            },
        },
        "exact_integer_oracles": {
            "cancel": [exact_oracle(True), exact_oracle(False)],
            "no_cancel_control": [exact_oracle(True, False), exact_oracle(False, False)],
        },
        "cases": cases,
        "selection_gates": {
            "bounded_single_fill_replay_candidate": len(controls) == len(MODELS)
            and all(
                case["status"] == "EXECUTED"
                and case["summary"]["position"] == 1.0
                and case["summary"]["local_position_matches_order_filled_qty"]
                for case in controls
            ),
            "exact_front_and_back_l2_witness_gate": "CLOSED_NOT_EXPRESSED_BY_PUBLIC_BUILTINS",
            "partial_fill_local_accounting_gate": "CLOSED_OBSERVED_MISMATCH"
            if partial_mismatch
            else "REQUIRES_REVIEW",
            "lossless_per_fill_poll_trace_gate": "CLOSED_SAME_TIME_AND_COARSE_POLL_COLLAPSE",
            "terminal_current_timestamp_gate": "CLOSED_STALE_CLOCK_OBSERVED"
            if stale_clock
            else "REQUIRES_REVIEW",
            "note": "EXECUTED means the probe ran, not that its correctness expectation passed.",
        },
        "limits": [
            "Fixed synthetic fixtures; no live market data or trading.",
            "Integer oracle is not an HFT engine witness or a certified feasibility checker.",
            "Probability models are estimated queue positions, "
            "not sampled explicit cancellation worlds.",
            "power_prob2 exponent16 is a rounding-sensitivity diagnostic, "
            "not a calibrated front-world model.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        json.dumps(
            [
                {
                    "case_id": c["case_id"],
                    "status": c["status"],
                    "summary": c.get("summary"),
                    "order_execution_observations": c.get("order_execution_observations"),
                }
                for c in cases
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
