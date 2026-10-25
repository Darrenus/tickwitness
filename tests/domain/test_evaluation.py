"""Offline accounting tests using hand-checkable original synthetic native-shaped evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence import (
    EvaluationValidationError,
    ReplayEvaluation,
    evaluate_replay,
    load_replay_evaluation,
)
from tickwitness.domain.evidence.evaluation import _binary64, _fee_candidates
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult, build_replay_result
from tickwitness.domain.replay.specs import build_replay_spec

BASE = 1_700_000_000_000_000_000
SECOND = 1_000_000_000
ORDER = "O-fixture-single-1"
SOURCE_POLICY = "input_step_before_native_matching_and_settlement"
MONEY_POLICY = "native_v1_f64_notional_then_USD_Money_precision_2"
FEE_POLICY = "v1_MakerTakerFeeModel_f64_notional_USD_Money_precision_2"


def _row(kind: str, ordinal: int, sequence: int | None, fields: dict[str, Any]) -> dict[str, Any]:
    offsets = [0, SECOND // 2, SECOND, SECOND + 1, 2 * SECOND, 2 * SECOND + 1, 3 * SECOND]
    types = ["snapshot", "delta", "trade", "delta", "trade", "delta", "delta"]
    return {
        "kind": kind,
        "ordinal": ordinal,
        "native_time_ns": BASE + offsets[(sequence or 1) - 1],
        "source_ref": None
        if sequence is None
        else {"line": sequence, "capture_seq": sequence, "event_type": types[sequence - 1]},
        "fields": fields,
    }


def _account(
    quantity: int, cash: str, free: str, locked: str, fee: str, status: str | None
) -> dict[str, Any]:
    return {
        "account_type": "MARGIN",
        "oms_type": "NETTING",
        "currency": "USD",
        "cash_total": cash,
        "cash_free": free,
        "cash_locked": locked,
        "cash_semantics": "native_margin_balance_not_spot_notional_debit",
        "money_rounding_policy": MONEY_POLICY,
        "native_money_precision": 2,
        "net_position_lots": quantity,
        "observed_fill_lots": quantity,
        "observed_commission": fee,
        "book_type": "L2_MBP",
        "bid_levels": 0 if status is None else 2,
        "ask_levels": 0 if status is None else 2,
        "orders": []
        if status is None
        else [
            {
                "order_id": ORDER,
                "status": status,
                "quantity_lots": 2,
                "filled_quantity_lots": quantity,
                "remaining_quantity_lots": 2 - quantity,
            }
        ],
    }


def _fixture() -> tuple[ReplayInput, ReplayResult]:
    """Two maker fills of 1 EUR at USD100, fee USD1 each; no closing sale."""
    common = {
        "schema_version": 1,
        "source": "synthetic",
        "instrument": "EUR-USD",
        "session": "audit-fixture-v1",
    }
    records: list[dict[str, Any]] = [
        {
            "type": "snapshot",
            "last_sequence": 10,
            "bids": [[100, 1], [99, 10]],
            "asks": [[103, 10], [104, 10]],
        },
        {
            "type": "delta",
            "first_sequence": 11,
            "last_sequence": 11,
            "bids": [[100, 4]],
            "asks": [],
        },
        {
            "type": "trade",
            "trade_id": "public-1",
            "price_ticks": 100,
            "quantity_lots": 2,
            "aggressor_side": "sell",
        },
        {
            "type": "delta",
            "first_sequence": 12,
            "last_sequence": 12,
            "bids": [[100, 2]],
            "asks": [],
        },
        {
            "type": "trade",
            "trade_id": "public-2",
            "price_ticks": 100,
            "quantity_lots": 1,
            "aggressor_side": "sell",
        },
        {
            "type": "delta",
            "first_sequence": 13,
            "last_sequence": 13,
            "bids": [[100, 1]],
            "asks": [],
        },
        {
            "type": "delta",
            "first_sequence": 14,
            "last_sequence": 14,
            "bids": [[100, 1]],
            "asks": [],
        },
    ]
    offsets = [0, SECOND // 2, SECOND, SECOND + 1, 2 * SECOND, 2 * SECOND + 1, 3 * SECOND]
    for sequence, (record, offset) in enumerate(zip(records, offsets, strict=True), start=1):
        record.update(
            common,
            capture_seq=sequence,
            event_time_ns=BASE + offset - 100,
            receive_time_ns=BASE + offset,
        )
    normalized = normalize_events(
        b"\n".join(json.dumps(record).encode() for record in records) + b"\n"
    ).normalized_bytes
    spec = build_replay_spec(
        json.dumps(
            {
                "schema_version": 1,
                "clock_policy_id": "receive_order_v1",
                "instrument": {
                    "base_currency": "EUR",
                    "quote_currency": "USD",
                    "price_increment": "1",
                    "size_increment": "1",
                },
                "account": {"starting_cash": "10000"},
                "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
                "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
                "strategy": {
                    "kind": "single_limit_buy_v1",
                    "submit_capture_seq": 1,
                    "limit_price_ticks": 100,
                    "quantity_lots": 2,
                    "cancel_after_first_fill": False,
                },
                "seed": 7,
            }
        ).encode()
    )
    replay_input = ReplayInput("a" * 64, normalized, spec)
    inputs = []
    for sequence, record in enumerate(records, start=1):
        inputs.append(
            _row(
                "input_processed",
                sequence - 1,
                sequence,
                {
                    "event_time_ns": record["event_time_ns"],
                    "receive_time_ns": record["receive_time_ns"],
                    "native_ts_event_ns": record["receive_time_ns"],
                    "native_ts_init_ns": record["receive_time_ns"],
                    "clock_policy_id": "receive_order_v1",
                    "source_clock_certified": False,
                    "source_sequence_first": record.get("first_sequence"),
                    "source_sequence_last": record.get("last_sequence"),
                    "source_trade_id": record.get("trade_id"),
                    "native_internal_id": f"CAPTURE-{sequence}"
                    if record["type"] == "trade"
                    else str(sequence),
                    "native_id_policy": "capture_seq_batch_sequence_or_CAPTURE_trade_id",
                    "bids": record.get("bids", []),
                    "asks": record.get("asks", []),
                    "price_ticks": record.get("price_ticks"),
                    "quantity_lots": record.get("quantity_lots"),
                    "aggressor_side": record.get("aggressor_side"),
                    "source_ref_semantics": SOURCE_POLICY,
                },
            )
        )
    decision = _row(
        "command_issued",
        0,
        1,
        {
            "action": "submit",
            "cause": "selected_capture",
            "command_id": "command-0",
            "decision_ref": "decision-0",
            "order_id": ORDER,
            "post_only": True,
            "strategy_kind": "single_limit_buy_v1",
            "limit_price_ticks": 100,
            "quantity_lots": 2,
        },
    )
    fills = [
        _row(
            "OrderFilled",
            ordinal,
            sequence,
            {
                "order_id": ORDER,
                "native_trade_id": f"native-fill-{ordinal + 1}",
                "price": "100",
                "price_ticks": 100,
                "quantity": "1",
                "quantity_lots": 1,
                "commission": "1",
                "commission_currency": "USD",
                "declared_fee_rate": "0.01",
                "exact_decimal_fee_before_native_quantization": "1.00",
                "native_commission_minus_exact_decimal_fee": "0.00",
                "native_fee_policy": FEE_POLICY,
                "liquidity_side": "MAKER",
                "native_event_ts_ns": BASE + offsets[sequence - 1],
                "native_init_ts_ns": BASE + offsets[sequence - 1],
                "source_ref_semantics": SOURCE_POLICY,
            },
        )
        for ordinal, sequence in enumerate((3, 5))
    ]
    lifecycle = [
        ("OrderInitialized", None, 1, ["command-0"]),
        ("OrderSubmitted", "SUBMITTED", 1, ["command-0"]),
        ("OrderAccepted", "ACCEPTED", 1, []),
        ("OrderFilled", "PARTIALLY_FILLED", 3, []),
        ("OrderFilled", "FILLED", 5, []),
    ]
    orders = [
        _row(
            kind,
            ordinal,
            sequence,
            {
                "order_id": ORDER,
                "status": status,
                "pending_command_ids": pending,
                "native_event_ts_ns": BASE + offsets[sequence - 1],
                "native_init_ts_ns": BASE + offsets[sequence - 1],
            },
        )
        for ordinal, (kind, status, sequence, pending) in enumerate(lifecycle)
    ]
    accounts = [
        _row("initial_account_snapshot", 0, None, _account(0, "10000", "10000", "0", "0", None)),
        _row(
            "fill_callback_account_snapshot",
            1,
            3,
            _account(1, "9999", "9699", "300", "1", "PARTIALLY_FILLED"),
        ),
        _row(
            "fill_callback_account_snapshot",
            2,
            5,
            _account(2, "9998", "9798", "200", "2", "FILLED"),
        ),
        _row("final_account_snapshot", 3, None, _account(2, "9998", "9798", "200", "2", "FILLED")),
    ]
    accounts[-1]["native_time_ns"] = BASE + 3 * SECOND
    document = {
        "kind": "replay_qualification_result_v1",
        "schema_version": 1,
        "engine": {
            "id": "nautilus-trader",
            "version": "1.231.0",
            "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1",
        },
        "environment": {
            "python_version": "3.12.14",
            "platform": "offline-synthetic-test",
            "package_versions": {"nautilus_trader": "1.231.0"},
        },
        "dataset_id": replay_input.dataset_id,
        "data_sha256": hashlib.sha256(normalized).hexdigest(),
        "spec_id": spec.spec_id,
        "execution_status": "completed",
        "completeness": {
            "input_records": 7,
            "processed_records": 7,
            "open_orders": [],
            "pending_commands": [],
            "stop_reason": "input_exhausted",
        },
        "input_trace": inputs,
        "decision_trace": [decision],
        "fill_trace": fills,
        "order_trace": orders,
        "account_trace": accounts,
    }
    return replay_input, build_replay_result(document)


def _changed_result(change) -> tuple[ReplayInput, ReplayResult]:
    replay_input, result = _fixture()
    document = result.document
    change(document)
    return replay_input, build_replay_result(document)


def test_hand_calculated_mark_valuation_and_bindings() -> None:
    replay_input, result = _fixture()
    evaluated = evaluate_replay(replay_input, result)
    document = evaluated.document
    assert document["audit_status"] == "verified"
    assert document["valuation_status"] == "valued"
    assert document["valuation"] == {
        "realized_pnl": "0",
        "gross_unrealized_pnl": "0",
        "net_marked_pnl": "-2",
    }
    assert document["ledger"] == {
        "fill_count": 2,
        "requested_quantity_lots": 2,
        "filled_quantity_lots": 2,
        "position_quantity": "2",
        "fill_notional": "200",
        "actual_commission": "2",
        "declared_decimal_commission": "2",
        "native_commission_difference": "0",
    }
    assert (
        document["bindings"]["result_sha256"] == hashlib.sha256(result.canonical_bytes).hexdigest()
    )
    assert document["mark"] == {
        "source_ref": {"line": 7, "capture_seq": 7, "event_type": "delta"},
        "native_time_ns": BASE + 3 * SECOND,
        "price_ticks": 100,
        "price": "100",
        "available_quantity_lots": 1,
    }
    assert load_replay_evaluation(evaluated.canonical_bytes) == evaluated
    document["ledger"]["actual_commission"] = "0"
    assert evaluated.document["ledger"]["actual_commission"] == "2"


def test_bid_mark_uses_reconstructed_last_book_not_last_trade_or_ask() -> None:
    replay_input, result = _fixture()
    records = [json.loads(line) for line in replay_input.normalized_bytes.splitlines()]
    records[-1]["bids"] = [[100, 0], [101, 1]]
    normalized = normalize_events(
        b"\n".join(json.dumps(record).encode() for record in records) + b"\n"
    ).normalized_bytes
    changed = ReplayInput("b" * 64, normalized, replay_input.spec)
    document = result.document
    document["dataset_id"] = changed.dataset_id
    document["data_sha256"] = hashlib.sha256(normalized).hexdigest()
    document["input_trace"][-1]["fields"]["bids"] = [[100, 0], [101, 1]]
    evaluated = evaluate_replay(changed, build_replay_result(document)).document
    assert evaluated["mark"]["price"] == "101"
    assert evaluated["valuation"] == {
        "realized_pnl": "0",
        "gross_unrealized_pnl": "2",
        "net_marked_pnl": "0",
    }


def test_global_decimal_precision_and_rounding_cannot_change_evaluation() -> None:
    replay_input, result = _fixture()
    reference = evaluate_replay(replay_input, result).canonical_bytes
    with localcontext() as context:
        context.prec = 1
        context.Emax = 1
        context.Emin = -1
        assert evaluate_replay(replay_input, result).canonical_bytes == reference


def test_fractional_increments_and_actual_zero_native_fee_remain_exact() -> None:
    replay_input, result = _fixture()
    spec = replay_input.spec.document
    spec["instrument"].update(price_increment="0.01", size_increment="0.1")
    changed = ReplayInput(
        replay_input.dataset_id,
        replay_input.normalized_bytes,
        build_replay_spec(json.dumps(spec).encode()),
    )
    document = result.document
    document["spec_id"] = changed.spec.spec_id
    for fill in document["fill_trace"]:
        fill["fields"].update(
            price="1.00",
            quantity="0.1",
            commission="0",
            exact_decimal_fee_before_native_quantization="0.00100",
            native_commission_minus_exact_decimal_fee="-0.00100",
        )
    for index, account in enumerate(document["account_trace"][1:], start=1):
        account["fields"].update(
            cash_total="10000",
            cash_free="9999.7" if index == 1 else "9999.8",
            cash_locked="0.3" if index == 1 else "0.2",
            observed_commission="0",
        )
    evaluated = evaluate_replay(changed, build_replay_result(document)).document
    assert evaluated["ledger"]["position_quantity"] == "0.2"
    assert evaluated["ledger"]["fill_notional"] == "0.2"
    assert evaluated["ledger"]["declared_decimal_commission"] == "0.002"
    assert evaluated["ledger"]["native_commission_difference"] == "-0.002"
    assert evaluated["valuation"]["net_marked_pnl"] == "0"


@pytest.mark.parametrize(
    "price,quantity,rate,expected",
    [
        ("1", "0.1", "0.05", "0.01"),
        ("1", "0.1", "0.04999999", "0"),
        ("1", "0.1", "0.05000001", "0.01"),
        ("0.005", "1", "0.5", "0.01"),
        ("1000000000", "1", "0.00000001", "10"),
    ],
)
def test_exact_native_fee_quantization_half_near_half_two_stages_and_large_notional(
    price: str, quantity: str, rate: str, expected: str
) -> None:
    assert _fee_candidates(Fraction(price), Fraction(quantity), Fraction(rate)) == {
        Fraction(expected)
    }


@pytest.mark.parametrize(
    "value",
    [
        Fraction(2**53 + 1),
        Fraction(2**53 + 3),
        Fraction("0.1"),
        Fraction("0.005"),
        Fraction("10000.065"),
        Fraction("10000000000000000000000001"),
    ],
)
def test_integer_binary64_emulation_agrees_with_independent_ieee_float_conversion(
    value: Fraction,
) -> None:
    assert _binary64(value) == Fraction.from_float(float(value))


@pytest.mark.parametrize("actual", ["0", "0.99", "1.01"])
def test_self_consistent_zero_or_one_cent_commission_rewrite_is_rejected(actual: str) -> None:
    def rewritten(document):
        amount = Decimal(actual)
        for fill in document["fill_trace"]:
            fill["fields"].update(
                commission=actual, native_commission_minus_exact_decimal_fee=format(amount - 1, "f")
            )
        for ordinal, account in enumerate(document["account_trace"][1:], start=1):
            count = min(ordinal, 2)
            fields = account["fields"]
            accumulated = count * amount
            cash = Decimal("10000") - accumulated
            fields.update(
                observed_commission=format(accumulated, "f"),
                cash_total=format(cash, "f"),
                cash_free=format(cash - Decimal(fields["cash_locked"]), "f"),
            )

    replay_input, result = _changed_result(rewritten)
    with pytest.raises(EvaluationValidationError, match="pinned native fee model"):
        evaluate_replay(replay_input, result)


def _ambiguous_fixture(actual: str = "10000.06") -> tuple[ReplayInput, ReplayResult]:
    replay_input, result = _fixture()
    spec = replay_input.spec.document
    spec["instrument"]["price_increment"] = "100.00065"
    spec["account"]["starting_cash"] = "1000000000"
    spec["fees"]["maker_rate"] = "1"
    changed = ReplayInput(
        replay_input.dataset_id,
        replay_input.normalized_bytes,
        build_replay_spec(json.dumps(spec).encode()),
    )
    document = result.document
    document["spec_id"] = changed.spec.spec_id
    fee, price = Decimal(actual), Decimal("10000.065")
    for fill in document["fill_trace"]:
        fill["fields"].update(
            price="10000.065",
            commission=actual,
            declared_fee_rate="1",
            exact_decimal_fee_before_native_quantization="10000.065",
            native_commission_minus_exact_decimal_fee=format(fee - price, "f"),
        )
    initial = document["account_trace"][0]["fields"]
    initial.update(cash_total="1000000000", cash_free="1000000000")
    for ordinal, account in enumerate(document["account_trace"][1:], start=1):
        count = min(ordinal, 2)
        cash = Decimal("1000000000") - fee * count
        account["fields"].update(
            observed_commission=format(fee * count, "f"),
            cash_total=format(cash, "f"),
            cash_free=format(cash - Decimal(account["fields"]["cash_locked"]), "f"),
        )
    return changed, build_replay_result(document)


@pytest.mark.parametrize("actual", ["10000.06", "10000.07"])
def test_ambiguous_native_raw_mode_cannot_be_selected_from_supplied_fee(actual: str) -> None:
    replay_input, result = _ambiguous_fixture(actual)
    evaluated = evaluate_replay(replay_input, result).document
    assert evaluated["valuation_status"] == "not_eligible"
    assert evaluated["ineligibility_reason"] == "ambiguous_native_fee_model"
    assert evaluated["valuation"] is evaluated["mark"] is None
    assert evaluated["fee_model_verification"] == {
        "policy_id": "nautilus_v1_binary64_usd_double_quantization_v1",
        "status": "ambiguous",
        "raw_precision_candidates": [9, 16],
        "ambiguous_fill_ordinals": [0, 1],
    }


def test_last_trade_is_not_used_as_the_mark_source() -> None:
    replay_input, result = _fixture()
    records = [json.loads(line) for line in replay_input.normalized_bytes.splitlines()]
    last = records[-1]
    for key in ("bids", "asks", "first_sequence", "last_sequence"):
        del last[key]
    last.update(
        type="trade", trade_id="public-last", price_ticks=102, quantity_lots=1, aggressor_side="buy"
    )
    normalized = normalize_events(
        b"\n".join(json.dumps(record).encode() for record in records) + b"\n"
    ).normalized_bytes
    changed = ReplayInput("b" * 64, normalized, replay_input.spec)
    document = result.document
    document.update(
        dataset_id=changed.dataset_id, data_sha256=hashlib.sha256(normalized).hexdigest()
    )
    row = document["input_trace"][-1]
    row["source_ref"]["event_type"] = "trade"
    row["fields"].update(
        bids=[],
        asks=[],
        source_sequence_first=None,
        source_sequence_last=None,
        source_trade_id="public-last",
        native_internal_id="CAPTURE-7",
        price_ticks=102,
        quantity_lots=1,
        aggressor_side="buy",
    )
    evaluated = evaluate_replay(changed, build_replay_result(document)).document
    assert evaluated["mark"]["source_ref"] == {"line": 6, "capture_seq": 6, "event_type": "delta"}
    assert evaluated["mark"]["price"] == "100"


@pytest.mark.parametrize("index", [0, 1, 3])
def test_missing_account_evidence_is_rejected(index: int) -> None:
    def removed(document):
        del document["account_trace"][index]
        for ordinal, row in enumerate(document["account_trace"]):
            row["ordinal"] = ordinal

    replay_input, result = _changed_result(removed)
    with pytest.raises(EvaluationValidationError):
        evaluate_replay(replay_input, result)


@pytest.mark.parametrize(
    "channel,index,key,value",
    [
        ("input_trace", 0, "source_clock_certified", 0),
        ("input_trace", 0, "bids", [[100, 2], [99, 10]]),
        ("input_trace", 2, "source_trade_id", "invented"),
        ("input_trace", 1, "source_sequence_first", 999),
        ("input_trace", 3, "native_ts_event_ns", BASE),
        ("decision_trace", 0, "post_only", 1),
        ("decision_trace", 0, "limit_price_ticks", 99),
        ("fill_trace", 0, "quantity_lots", True),
        ("fill_trace", 0, "quantity", "2"),
        ("fill_trace", 0, "price", "100.01"),
        ("fill_trace", 0, "price_ticks", 101),
        ("fill_trace", 0, "order_id", "other-order"),
        ("fill_trace", 0, "commission_currency", "EUR"),
        ("fill_trace", 0, "commission", "-1"),
        ("fill_trace", 0, "commission", "0.001"),
        ("fill_trace", 0, "declared_fee_rate", "0.02"),
        ("fill_trace", 0, "exact_decimal_fee_before_native_quantization", "1.01"),
        ("fill_trace", 0, "native_commission_minus_exact_decimal_fee", "1"),
        ("account_trace", 1, "net_position_lots", True),
        ("account_trace", 1, "net_position_lots", 9),
        ("account_trace", 2, "observed_commission", "1"),
        ("account_trace", 3, "cash_semantics", "spot"),
        ("account_trace", 3, "native_money_precision", True),
    ],
)
def test_schema_valid_but_forged_trace_values_are_rejected(
    channel: str, index: int, key: str, value: object
) -> None:
    replay_input, result = _changed_result(
        lambda document: document[channel][index]["fields"].update({key: value})
    )
    with pytest.raises(EvaluationValidationError):
        evaluate_replay(replay_input, result)


def test_rewriting_cash_and_free_together_cannot_forge_a_consistent_gain() -> None:
    def forged(document):
        final = document["account_trace"][-1]["fields"]
        final.update(cash_total="10008", cash_free="9808")

    replay_input, result = _changed_result(forged)
    assert result.document["account_trace"][-1]["fields"]["cash_total"] == "10008"
    with pytest.raises(EvaluationValidationError, match="starting cash minus actual fees"):
        evaluate_replay(replay_input, result)


def test_duplicate_fill_identity_is_rejected_even_with_valid_result_schema() -> None:
    replay_input, result = _changed_result(
        lambda document: document["fill_trace"][1]["fields"].update(native_trade_id="native-fill-1")
    )
    with pytest.raises(EvaluationValidationError, match="Duplicate native fill"):
        evaluate_replay(replay_input, result)


def test_lifecycle_cannot_fill_after_a_terminal_rejection() -> None:
    def rejected(document):
        document["order_trace"][2]["kind"] = "OrderRejected"
        document["order_trace"][2]["fields"]["status"] = "REJECTED"

    replay_input, result = _changed_result(rejected)
    with pytest.raises(EvaluationValidationError, match="terminal"):
        evaluate_replay(replay_input, result)


def test_limit_fills_require_submitted_and_accepted_receipts() -> None:
    def omitted(document):
        document["order_trace"] = [document["order_trace"][0], *document["order_trace"][3:]]
        for ordinal, row in enumerate(document["order_trace"]):
            row["ordinal"] = ordinal

    replay_input, result = _changed_result(omitted)
    with pytest.raises(EvaluationValidationError, match="submitted/accepted"):
        evaluate_replay(replay_input, result)


def test_pending_cancel_fill_status_requires_a_real_pending_cancel() -> None:
    replay_input, result = _changed_result(
        lambda document: document["order_trace"][3]["fields"].update(status="PENDING_CANCEL")
    )
    with pytest.raises(EvaluationValidationError, match="Unbacked pending-cancel"):
        evaluate_replay(replay_input, result)


def test_order_initialization_cannot_follow_remote_acceptance() -> None:
    def reordered(document):
        rows = document["order_trace"]
        document["order_trace"] = [rows[1], rows[2], rows[0], *rows[3:]]
        for ordinal, row in enumerate(document["order_trace"]):
            row["ordinal"] = ordinal
        document["order_trace"][2]["fields"]["pending_command_ids"] = []

    replay_input, result = _changed_result(reordered)
    with pytest.raises(EvaluationValidationError, match="start with initialization"):
        evaluate_replay(replay_input, result)


def test_maker_buy_cannot_claim_an_arbitrary_improved_fill_price() -> None:
    replay_input, result = _changed_result(
        lambda document: document["fill_trace"][0]["fields"].update(price="1", price_ticks=1)
    )
    with pytest.raises(EvaluationValidationError, match="equal the frozen limit"):
        evaluate_replay(replay_input, result)


def test_final_book_cache_count_must_match_reconstructed_source() -> None:
    replay_input, result = _changed_result(
        lambda document: document["account_trace"][-1]["fields"].update(bid_levels=1)
    )
    with pytest.raises(EvaluationValidationError, match="book level counts"):
        evaluate_replay(replay_input, result)


@pytest.mark.parametrize("binding", ["dataset_id", "data_sha256", "spec_id"])
def test_rebound_result_hash_does_not_excuse_wrong_input_binding(binding: str) -> None:
    replay_input, result = _changed_result(lambda document: document.update({binding: "f" * 64}))
    with pytest.raises(EvaluationValidationError, match="binding mismatch"):
        evaluate_replay(replay_input, result)


def test_pending_cancel_with_filled_order_is_not_eligible_for_valuation() -> None:
    replay_input, result = _fixture()
    spec = replay_input.spec.document
    spec["strategy"]["cancel_after_first_fill"] = True
    spec["execution"]["cancel_latency_ns"] = 5 * SECOND
    replay_input = ReplayInput(
        replay_input.dataset_id,
        replay_input.normalized_bytes,
        build_replay_spec(json.dumps(spec).encode()),
    )
    document = result.document
    document["spec_id"] = replay_input.spec.spec_id
    cancel = copy.deepcopy(document["decision_trace"][0])
    cancel.update(
        ordinal=1, source_ref=document["fill_trace"][0]["source_ref"], native_time_ns=BASE + SECOND
    )
    cancel["fields"].update(
        action="cancel",
        cause="first_partial_fill",
        command_id="command-1",
        decision_ref="decision-1",
    )
    document["decision_trace"].append(cancel)
    pending = _row(
        "OrderPendingCancel",
        3,
        3,
        {
            "order_id": ORDER,
            "status": "PENDING_CANCEL",
            "pending_command_ids": ["command-1"],
            "native_event_ts_ns": BASE + SECOND,
            "native_init_ts_ns": BASE + SECOND,
        },
    )
    document["order_trace"].insert(3, pending)
    for ordinal, row in enumerate(document["order_trace"]):
        row["ordinal"] = ordinal
        if ordinal >= 4:
            row["fields"]["pending_command_ids"] = ["command-1"]
    document["order_trace"][4]["fields"]["status"] = "PENDING_CANCEL"
    document["execution_status"] = "incomplete"
    document["completeness"].update(
        stop_reason="pending_commands_at_data_end",
        pending_commands=[
            {
                "command_id": "command-1",
                "order_id": ORDER,
                "command_type": "cancel",
                "decision_ref": "decision-1",
                "source_ref": document["fill_trace"][0]["source_ref"],
            }
        ],
    )
    evaluated = evaluate_replay(replay_input, build_replay_result(document)).document
    assert evaluated["valuation_status"] == "not_eligible"
    assert evaluated["ineligibility_reason"] == "execution_incomplete"
    assert evaluated["valuation"] is evaluated["mark"] is None
    assert evaluated["ledger"]["filled_quantity_lots"] == 2


def test_failed_execution_never_acquires_a_pnl_even_if_full_traces_are_present() -> None:
    replay_input, result = _changed_result(
        lambda document: (
            document.update(execution_status="failed"),
            document["completeness"].update(stop_reason="engine_error"),
        )
    )
    evaluated = evaluate_replay(replay_input, result).document
    assert evaluated["ineligibility_reason"] == "execution_failed"
    assert evaluated["valuation"] is None


def test_completed_rejected_order_with_no_fills_does_not_become_zero_profit_success() -> None:
    replay_input, result = _fixture()
    document = result.document
    document["fill_trace"] = []
    document["order_trace"] = document["order_trace"][:2]
    rejected = _row(
        "OrderRejected",
        2,
        1,
        {
            "order_id": ORDER,
            "status": "REJECTED",
            "pending_command_ids": [],
            "native_event_ts_ns": BASE,
            "native_init_ts_ns": BASE,
            "reason": "fixed synthetic rejection",
        },
    )
    document["order_trace"].append(rejected)
    final = _row(
        "final_account_snapshot", 1, None, _account(0, "10000", "10000", "0", "0", "REJECTED")
    )
    final["native_time_ns"] = BASE + 3 * SECOND
    document["account_trace"] = [document["account_trace"][0], final]
    evaluated = evaluate_replay(replay_input, build_replay_result(document)).document
    assert evaluated["ineligibility_reason"] == "no_fills"
    assert evaluated["valuation"] is None


def test_evaluation_loader_checks_arithmetic_canonical_text_and_identity() -> None:
    replay_input, result = _fixture()
    evaluated = evaluate_replay(replay_input, result)
    with pytest.raises(EvaluationValidationError, match="identity"):
        ReplayEvaluation("f" * 64, evaluated.canonical_bytes)
    document = evaluated.document
    document["valuation"]["net_marked_pnl"] = "1"
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(EvaluationValidationError, match="Net mark"):
        load_replay_evaluation(raw)
    document = evaluated.document
    document["ledger"]["actual_commission"] = "2.0"
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(EvaluationValidationError, match="canonical"):
        load_replay_evaluation(raw)


def test_offline_reaudit_rejects_self_consistent_evaluation_rehash_after_source_forgery() -> None:
    replay_input, result = _fixture()
    document = result.document
    document["input_trace"][-1]["fields"]["bids"] = [[101, 1]]
    forged = build_replay_result(document)
    # A fresh valid outer hash cannot repair the contradiction with the sealed source.
    assert (
        hashlib.sha256(forged.canonical_bytes).hexdigest()
        != hashlib.sha256(result.canonical_bytes).hexdigest()
    )
    with pytest.raises(EvaluationValidationError, match="sealed source"):
        evaluate_replay(replay_input, forged)
