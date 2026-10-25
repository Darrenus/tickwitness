#!/usr/bin/env python3
"""Remote qualification of the existing step-coupled receive-order model.

Run with an installed TickWitness/native environment, preferably Python -I.
Original fixtures only: no strategy source, exchange connection, trial ledger,
production Scenario DTO, or data-store publication. This is not a performance
benchmark or an independent venue-clock/delayed-observer implementation.

Every oracle below is a hypothesis frozen before the remote run. Unexpected
native behavior produces a failed case and retained evidence, never a relaxed
oracle. A passing report still does not enable production scenario execution.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence import evaluate_replay
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.infrastructure.nautilus_replay import NautilusReplayAdapter

ROOT = Path(__file__).resolve().parents[1]
BASE = 1_700_000_000_000_000_000
SECOND = 1_000_000_000
CASE_IDS = (
    "zero_delay",
    "full_stream_translation",
    "suffix_without_command_latency",
    "insert_step_control",
    "cancel_same_time_step_counterexample",
    "cancel_business_difference",
    "same_time_capture_order",
    "eof_pending_submit",
    "eof_filled_pending_cancel",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def _records(fixture: str, count: int | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (ROOT / "examples" / fixture).read_bytes().splitlines()]
    return rows if count is None else rows[:count]


def _shift(records: list[dict[str, Any]], anchor: int, delay: int) -> list[dict[str, Any]]:
    """Qualification-only handwritten transform; no sorting, clamp, or source mutation."""
    assert type(anchor) is int and type(delay) is int and delay >= 0
    assert any(record["capture_seq"] == anchor for record in records)
    shifted = copy.deepcopy(records)
    for original, changed in zip(records, shifted, strict=True):
        if changed["capture_seq"] >= anchor:
            changed["receive_time_ns"] += delay
        assert changed["receive_time_ns"] >= original["receive_time_ns"]
        assert {key: value for key, value in original.items() if key != "receive_time_ns"} == {
            key: value for key, value in changed.items() if key != "receive_time_ns"
        }
    return shifted


def _input(records: list[dict[str, Any]], changes: dict[str, dict[str, object]]) -> ReplayInput:
    spec = json.loads((ROOT / "examples" / "clock-spec.json").read_bytes())
    for group, values in changes.items():
        spec[group].update(values)
    replay_spec = build_replay_spec(_canonical(spec))
    normalized = normalize_events(
        b"\n".join(_canonical(row) for row in records) + b"\n"
    ).normalized_bytes
    # An explicit qualification-fixture identity, not a production dataset manifest.
    identity = hashlib.sha256(
        _canonical(
            {
                "kind": "clock_qualification_input_identity_v1",
                "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
                "replay_spec_id": replay_spec.spec_id,
            }
        )
    ).hexdigest()
    return ReplayInput(identity, normalized, replay_spec)


def _execute(
    case: dict[str, Any],
    label: str,
    records: list[dict[str, Any]],
    changes: dict[str, dict[str, object]] | None = None,
) -> dict[str, Any]:
    replay_input = _input(records, changes or {})
    result = NautilusReplayAdapter().run(replay_input)
    document = result.document
    evaluation = evaluate_replay(replay_input, result).document
    case["runs"][label] = {
        "input_identity_policy": "clock_qualification_input_identity_v1",
        "dataset_id": replay_input.dataset_id,
        "normalized_sha256": hashlib.sha256(replay_input.normalized_bytes).hexdigest(),
        "replay_spec": replay_input.spec.document,
        "replay_spec_id": replay_input.spec.spec_id,
        "result_sha256": hashlib.sha256(result.canonical_bytes).hexdigest(),
        "result": document,
        "evaluation": evaluation,
    }
    _check(
        case,
        f"{label}: all input records processed",
        document["completeness"]["processed_records"],
        len(records),
    )
    for row, source in zip(document["input_trace"], records, strict=True):
        fields = row["fields"]
        _check(
            case,
            f"{label}: capture {source['capture_seq']} source mapping",
            {
                "source_ref": row["source_ref"],
                "event": fields["event_time_ns"],
                "receive": fields["receive_time_ns"],
                "native_event": fields["native_ts_event_ns"],
                "native_init": fields["native_ts_init_ns"],
                "clock": row["native_time_ns"],
            },
            {
                "source_ref": {
                    "line": row["ordinal"] + 1,
                    "capture_seq": source["capture_seq"],
                    "event_type": source["type"],
                },
                "event": source["event_time_ns"],
                "receive": source["receive_time_ns"],
                "native_event": source["receive_time_ns"],
                "native_init": source["receive_time_ns"],
                "clock": source["receive_time_ns"],
            },
        )
    return document


def _check(case: dict[str, Any], name: str, actual: object, expected: object) -> None:
    passed = _canonical(actual) == _canonical(expected)
    case["checks"].append({"name": name, "passed": passed, "actual": actual, "expected": expected})


def _projection(document: dict[str, Any]) -> dict[str, Any]:
    """Declared economic/callback view; full identifiers and times remain in raw evidence."""
    order_id = document["decision_trace"][0]["fields"]["order_id"]

    def normalize(value: object) -> object:
        if isinstance(value, str):
            return value.replace(order_id, "order-0")
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {
                key: normalize(item)
                for key, item in value.items()
                if key
                not in {
                    "native_time_ns",
                    "native_event_ts_ns",
                    "native_init_ts_ns",
                    "native_trade_id",
                }
            }
        return value

    return {
        channel: normalize(document[channel])
        for channel in (
            "decision_trace",
            "order_trace",
            "fill_trace",
            "account_trace",
            "execution_status",
            "completeness",
        )
    }


def _receipt(document: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((row for row in document["order_trace"] if row["kind"] == kind), None)


def _summary(document: dict[str, Any]) -> dict[str, Any]:
    final = document["account_trace"][-1]["fields"]
    return {
        "fills": len(document["fill_trace"]),
        "position_lots": final["net_position_lots"],
        "commission": final["observed_commission"],
        "cash": final["cash_total"],
        "status": document["execution_status"],
    }


def _pair_environment(
    case: dict[str, Any], baseline: dict[str, Any], shifted: dict[str, Any]
) -> None:
    _check(
        case,
        "same engine and environment",
        [shifted["engine"], shifted["environment"]],
        [baseline["engine"], baseline["environment"]],
    )


def run_case(case_id: str) -> dict[str, Any]:
    if case_id not in CASE_IDS:
        raise ValueError("Unknown clock qualification case")
    case: dict[str, Any] = {"case_id": case_id, "checks": [], "runs": {}, "passed": False}
    try:
        if case_id in ("zero_delay", "full_stream_translation", "suffix_without_command_latency"):
            rows = _records("clock-partials.jsonl")
            anchor, delay = {
                "zero_delay": (2, 0),
                "full_stream_translation": (1, 50_000_000),
                "suffix_without_command_latency": (2, 500_000_000),
            }[case_id]
            case["parameters"] = {"from_capture_seq": anchor, "additional_delay_ns": delay}
            a = _execute(case, "baseline", rows)
            b = _execute(case, "shifted", _shift(rows, anchor, delay))
            _pair_environment(case, a, b)
            _check(case, "economic/callback projection unchanged", _projection(b), _projection(a))
            _check(
                case,
                "exact cash/quantity/fee baseline",
                _summary(a),
                {
                    "fills": 2,
                    "position_lots": 2,
                    "commission": "2",
                    "cash": "9998",
                    "status": "completed",
                },
            )
            if delay == 0:
                _check(case, "zero shift full semantic bytes", b, a)
            if anchor == 1:
                for channel in (
                    "input_trace",
                    "decision_trace",
                    "order_trace",
                    "fill_trace",
                    "account_trace",
                ):
                    _check(
                        case,
                        channel + " global native clock translation",
                        [row["native_time_ns"] for row in b[channel]],
                        [row["native_time_ns"] + delay for row in a[channel]],
                    )
        elif case_id == "insert_step_control":
            rows = _records("clock-insert.jsonl")
            changes = {
                "strategy": {"limit_price_ticks": 99, "quantity_lots": 1},
                "execution": {"insert_latency_ns": 2 * SECOND},
            }
            case["parameters"] = {
                "from_capture_seq": 2,
                "additional_delay_ns": 2 * SECOND,
                "nominal_insert_due_offset_ns": 2 * SECOND,
            }
            a = _execute(case, "baseline", rows, changes)
            b = _execute(case, "shifted", _shift(rows, 2, 2 * SECOND), changes)
            _pair_environment(case, a, b)
            for label, document, capture in (("baseline", a, 3), ("shifted", b, 2)):
                receipt = _receipt(document, "OrderAccepted")
                _check(
                    case,
                    label + " accepted at market step, not autonomous due time",
                    None
                    if receipt is None
                    else [receipt["source_ref"]["capture_seq"], receipt["native_time_ns"]],
                    [capture, BASE + 3 * SECOND],
                )
                _check(
                    case,
                    label + " unfilled open order is incomplete",
                    document["completeness"]["stop_reason"],
                    "input_exhausted_with_open_orders",
                )
        elif case_id in ("cancel_same_time_step_counterexample", "cancel_business_difference"):
            business = case_id == "cancel_business_difference"
            rows = _records("clock-partials.jsonl" if business else "clock-same-time.jsonl")
            anchor, latency = (4, 1_500_000_000) if business else (5, SECOND)
            changes = {
                "strategy": {"cancel_after_first_fill": True},
                "execution": {"cancel_latency_ns": latency},
            }
            case["parameters"] = {
                "from_capture_seq": anchor,
                "additional_delay_ns": 2 * SECOND,
                "cancel_latency_ns": latency,
            }
            a = _execute(case, "baseline", rows, changes)
            b = _execute(case, "shifted", _shift(rows, anchor, 2 * SECOND), changes)
            _pair_environment(case, a, b)
            _check(
                case,
                "baseline two fills and exact accounts",
                _summary(a),
                {
                    "fills": 2,
                    "position_lots": 2,
                    "commission": "2",
                    "cash": "9998",
                    "status": "completed",
                },
            )
            _check(
                case,
                "baseline delayed cancel rejected at capture 7",
                None
                if _receipt(a, "OrderCancelRejected") is None
                else _receipt(a, "OrderCancelRejected")["source_ref"]["capture_seq"],
                7,
            )
            if business:
                _check(
                    case,
                    "benign delayed book step settles cancel before next trade",
                    _summary(b),
                    {
                        "fills": 1,
                        "position_lots": 1,
                        "commission": "1",
                        "cash": "9999",
                        "status": "completed",
                    },
                )
                canceled = _receipt(b, "OrderCanceled")
                _check(
                    case,
                    "shifted cancel source is benign capture 4",
                    None
                    if canceled is None
                    else [canceled["source_ref"]["capture_seq"], canceled["native_time_ns"]],
                    [4, BASE + 3 * SECOND + 1],
                )
                _check(
                    case,
                    "baseline/shifted are both independently valued",
                    [
                        case["runs"][label]["evaluation"]["valuation_status"]
                        for label in ("baseline", "shifted")
                    ],
                    ["valued", "valued"],
                )
                _check(
                    case,
                    "known fee-only net-mark difference",
                    [
                        case["runs"][label]["evaluation"]["valuation"]["net_marked_pnl"]
                        for label in ("baseline", "shifted")
                    ],
                    ["-2", "-1"],
                )
            else:
                _check(
                    case,
                    "trade step executes before already due cancel drains",
                    _summary(b),
                    _summary(a),
                )
                rejected = _receipt(b, "OrderCancelRejected")
                _check(
                    case,
                    "cancel rejection now refers to capture 5",
                    None
                    if rejected is None
                    else [rejected["source_ref"]["capture_seq"], rejected["native_time_ns"]],
                    [5, BASE + 3 * SECOND],
                )
        elif case_id == "same_time_capture_order":
            document = _execute(case, "same_time", _records("clock-same-time.jsonl"))
            _check(
                case,
                "equal timestamps preserve capture order",
                [row["source_ref"]["capture_seq"] for row in document["fill_trace"]],
                [3, 5],
            )
            _check(
                case,
                "both fills at the same declared native time",
                [row["native_time_ns"] for row in document["fill_trace"]],
                [BASE + SECOND, BASE + SECOND],
            )
        elif case_id == "eof_pending_submit":
            rows = _records("clock-insert.jsonl", 2)
            changes = {
                "strategy": {"submit_capture_seq": 2, "limit_price_ticks": 99, "quantity_lots": 1},
                "execution": {"insert_latency_ns": 2 * SECOND},
            }
            for label, records in (("baseline", rows), ("shifted", _shift(rows, 2, 2 * SECOND))):
                document = _execute(case, label, records, changes)
                complete = document["completeness"]
                _check(
                    case,
                    label + " EOF keeps submit in flight",
                    [
                        document["execution_status"],
                        complete["stop_reason"],
                        [command["command_type"] for command in complete["pending_commands"]],
                    ],
                    ["incomplete", "pending_commands_at_data_end", ["submit"]],
                )
                _check(
                    case,
                    label + " does not invent guard data or future clock",
                    [
                        complete["processed_records"],
                        document["account_trace"][-1]["native_time_ns"],
                    ],
                    [2, records[-1]["receive_time_ns"]],
                )
        elif case_id == "eof_filled_pending_cancel":
            rows = _records("clock-same-time.jsonl", 5)
            changes = {
                "strategy": {"cancel_after_first_fill": True},
                "execution": {"cancel_latency_ns": SECOND},
            }
            a = _execute(case, "baseline", rows, changes)
            b = _execute(case, "shifted", _shift(rows, 5, 2 * SECOND), changes)
            _check(
                case,
                "FILLED does not acknowledge pending cancel",
                [
                    a["execution_status"],
                    a["account_trace"][-1]["fields"]["orders"][0]["status"],
                    [command["command_type"] for command in a["completeness"]["pending_commands"]],
                ],
                ["incomplete", "FILLED", ["cancel"]],
            )
            _check(
                case,
                "later genuine input can settle cancel at EOF",
                [
                    b["execution_status"],
                    b["completeness"]["processed_records"],
                    b["completeness"]["pending_commands"],
                    b["account_trace"][-1]["native_time_ns"],
                ],
                ["completed", 5, [], BASE + 3 * SECOND],
            )
        case["passed"] = bool(case["checks"]) and all(check["passed"] for check in case["checks"])
    except Exception as error:
        case["error"] = {
            "type": type(error).__name__,
            "code": getattr(error, "code", None),
            "message": str(error),
        }
    return case


def qualify() -> dict[str, Any]:
    cases = [run_case(case_id) for case_id in CASE_IDS]
    return {
        "kind": "scenario_clock_qualification_v1",
        "schema_version": 1,
        "model_under_test": "step_coupled_receive_order_v1",
        "transform_under_test": "replay_receive_suffix_shift_v1",
        "coupled_model_qualified": all(case["passed"] for case in cases),
        "independent_venue_observer_model": "unsupported",
        "scenario_execution_enabled": False,
        "claims": {
            "native_clock_source_certified": False,
            "historical_compatibility_verified": False,
            "performance_benchmarked": False,
            "production_scenario_workflow_qualified": False,
        },
        "projection_policy": {
            "id": "economic_capture_projection_v1",
            "order_ids": "mapped to order-0 by submit decision",
            "excluded_fields": [
                "native_time_ns",
                "native_event_ts_ns",
                "native_init_ts_ns",
                "native_trade_id",
            ],
            "raw_results_preserved": True,
        },
        "fixture_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "examples").glob("clock-*"))
            if path.is_file()
        },
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the JSON report for a CI artifact")
    arguments = parser.parse_args()
    report = qualify()
    raw = _canonical(report) + b"\n"
    if arguments.output is None:
        print(raw.decode(), end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_bytes(raw)
    return 0 if report["coupled_model_qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
