"""Exact independent accounting audit for the pinned single-limit-buy profile.

This verifies source bindings and trace consistency, not the authenticity of a
native matching run. All monetary arithmetic uses rational integers; even a
hostile caller's Decimal context cannot round an evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from tickwitness.domain.replay._validation import (
    ReplayValidationError,
    canonical,
    digest,
    exact,
    identity,
    integer,
    parse,
    text,
)
from tickwitness.domain.replay.contracts import (
    PreparedReplay,
    ReplayEvent,
    ReplayInput,
    ReplayResult,
)
from tickwitness.domain.replay.preflight import preflight_replay

_LIMIT = 65_536
_POLICY = "last_observed_bid_mark_v1"
_ENGINE = {
    "id": "nautilus-trader",
    "version": "1.231.0",
    "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1",
}
_SOURCE_SEMANTICS = "input_step_before_native_matching_and_settlement"
_MONEY_POLICY = "native_v1_f64_notional_then_USD_Money_precision_2"
_FEE_POLICY = "v1_MakerTakerFeeModel_f64_notional_USD_Money_precision_2"
_FEE_AUDIT_POLICY = "nautilus_v1_binary64_usd_double_quantization_v1"
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_TERMINAL = {"FILLED", "CANCELED", "REJECTED", "DENIED"}
_ORDER_KINDS = {
    "OrderInitialized",
    "OrderSubmitted",
    "OrderAccepted",
    "OrderRejected",
    "OrderDenied",
    "OrderFilled",
    "OrderPendingCancel",
    "OrderCanceled",
    "OrderCancelRejected",
}
type Row = dict[str, object]


class EvaluationValidationError(ValueError):
    """The evidence cannot pass this audit or its evaluation contract is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationValidationError(message)


def _equal(left: object, right: object, message: str) -> None:
    # Canonical JSON distinguishes true from 1, unlike Python equality.
    _require(canonical({"value": left}) == canonical({"value": right}), message)


def _number(value: object, label: str, *, nonnegative: bool = False) -> Fraction:
    if not isinstance(value, str) or len(value) > 256 or _NUMBER.fullmatch(value) is None:
        raise EvaluationValidationError(f"{label} must be bounded plain decimal text")
    result = Fraction(value)
    _require(not nonnegative or result >= 0, f"{label} cannot be negative")
    return result


def _decimal(value: Fraction) -> str:
    """Render a finite rational as a unique plain decimal without Decimal operations."""
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    _require(denominator == 1, "Evaluation requires a finite decimal")
    places = max(twos, fives)
    scaled = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
    if places:
        digits = str(scaled).rjust(places + 1, "0")
        result = (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")
    else:
        result = str(scaled)
    return ("-" if value < 0 else "") + result


def _money(value: object, label: str, *, nonnegative: bool = False) -> Fraction:
    number = _number(value, label, nonnegative=nonnegative)
    _require((number * 100).denominator == 1, f"{label} violates native USD cent precision")
    return number


def _binary64(value: Fraction) -> Fraction:
    """Exact rational emulation of one finite normal IEEE-754 binary64 rounding.

    Pinned native Price/Quantity.as_f64_c casts raw integers then divides by the
    fixed scalar. Replacing this with one direct decimal-to-float conversion
    loses a rounding step. The supported physical ranges are far from subnormal
    and overflow values; neither host floats nor Decimal context are used here.
    """
    if value == 0:
        return value
    if value < 0:
        return -_binary64(-value)
    numerator, denominator = value.numerator, value.denominator
    exponent = numerator.bit_length() - denominator.bit_length()
    if value < (Fraction(2**exponent) if exponent >= 0 else Fraction(1, 2**-exponent)):
        exponent -= 1
    _require(-1022 <= exponent <= 1023, "Fee binary64 value is outside the audited normal range")
    shift = 52 - exponent
    if shift >= 0:
        numerator *= 2**shift
    else:
        denominator *= 2**-shift
    rounded, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and rounded % 2):
        rounded += 1
    return Fraction(rounded, 2**shift) if shift >= 0 else Fraction(rounded * 2**-shift)


def _native_amount(value: Fraction, precision: int) -> Fraction:
    scale = Fraction(10**precision)
    raw = value * scale
    _require(raw.denominator == 1, "Physical amount cannot map to the native fixed-point scale")
    return _binary64(_binary64(raw) / _binary64(scale))


def _native_money(value: Fraction) -> Fraction:
    # Rust f64_to_fixed_i64/i128 rounds amount*100 half away from zero for USD.
    scaled = _binary64(_binary64(value) * 100)
    _require(scaled >= 0, "This fee policy supports nonnegative money only")
    cents = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    return Fraction(cents, 100)


def _fees_by_mode(price: Fraction, quantity: Fraction, rate: Fraction) -> dict[int, Fraction]:
    """Both native raw modes are supported only when they imply the same cent fee.

    S3 results do not bind HIGH_PRECISION_MODE, so never choose a mode by looking
    at the supplied commission. Ambiguity prevents valuation/claim eligibility.
    """
    candidates: dict[int, Fraction] = {}
    for precision in (9, 16):
        notional_f64 = _binary64(
            _native_amount(quantity, precision) * _native_amount(price, precision)
        )
        notional_money = _native_money(notional_f64)
        candidates[precision] = _native_money(notional_money * rate)
    return candidates


def _fee_candidates(price: Fraction, quantity: Fraction, rate: Fraction) -> set[Fraction]:
    return set(_fees_by_mode(price, quantity, rate).values())


def _rows(document: Row, channel: str) -> list[Row]:
    return cast("list[Row]", document[channel])


def _fields(row: Row) -> Row:
    return cast("Row", row["fields"])


@dataclass(frozen=True, slots=True)
class _Profile:
    price_increment: Fraction
    size_increment: Fraction
    cash: Fraction
    maker: Fraction
    taker: Fraction
    requested: int
    limit: int
    submit_seq: int
    insert_latency: int
    cancel_latency: int
    cancel: bool

    @classmethod
    def read(cls, prepared: PreparedReplay) -> _Profile:
        document = prepared.spec.document
        instrument = cast("Row", document["instrument"])
        account, fees = cast("Row", document["account"]), cast("Row", document["fees"])
        strategy, execution = cast("Row", document["strategy"]), cast("Row", document["execution"])
        return cls(
            _number(instrument["price_increment"], "price increment"),
            _number(instrument["size_increment"], "size increment"),
            _money(account["starting_cash"], "starting cash"),
            _number(fees["maker_rate"], "maker rate"),
            _number(fees["taker_rate"], "taker rate"),
            cast("int", strategy["quantity_lots"]),
            cast("int", strategy["limit_price_ticks"]),
            cast("int", strategy["submit_capture_seq"]),
            cast("int", execution["insert_latency_ns"]),
            cast("int", execution["cancel_latency_ns"]),
            cast("bool", strategy["cancel_after_first_fill"]),
        )


def _expected_input(event: ReplayEvent) -> Row:
    return {
        "aggressor_side": event.aggressor_side,
        "asks": [list(level) for level in event.asks],
        "bids": [list(level) for level in event.bids],
        "clock_policy_id": "receive_order_v1",
        "event_time_ns": event.event_time_ns,
        "receive_time_ns": event.receive_time_ns,
        "native_id_policy": "capture_seq_batch_sequence_or_CAPTURE_trade_id",
        "native_internal_id": f"CAPTURE-{event.capture_seq}"
        if event.event_type == "trade"
        else str(event.capture_seq),
        "native_ts_event_ns": event.receive_time_ns,
        "native_ts_init_ns": event.receive_time_ns,
        "price_ticks": event.price_ticks,
        "quantity_lots": event.quantity_lots,
        "source_clock_certified": False,
        "source_ref_semantics": _SOURCE_SEMANTICS,
        "source_sequence_first": event.first_sequence,
        "source_sequence_last": event.last_sequence,
        "source_trade_id": event.trade_id,
    }


class _Audit:
    def __init__(self, prepared: PreparedReplay, result: ReplayResult) -> None:
        self.prepared, self.result = prepared, result
        self.document = result.document
        self.profile = _Profile.read(prepared)
        self.processed = cast(
            "int", cast("Row", self.document["completeness"])["processed_records"]
        )
        self.events = prepared.events[: self.processed]
        self.by_line = {event.line: event for event in self.events}
        self.order_id: str | None = None
        self.quantity = 0
        self.notional = Fraction(0)
        self.commission = Fraction(0)
        self.declared_fee = Fraction(0)
        self.prefixes: list[tuple[int, Fraction]] = []
        self.commands: dict[str, Row] = {}
        self.mark: Row | None = None
        self.book_counts: dict[int, tuple[int, int]] = {}
        self.ambiguous_fees: list[int] = []
        self.compatible_modes = {9, 16}

    def event(self, row: Row) -> ReplayEvent:
        reference = row["source_ref"]
        _require(isinstance(reference, dict), "Native callback requires an actual input source")
        ref = cast("Row", reference)
        event = self.by_line.get(cast("int", ref["line"]))
        _require(event is not None, "Callback refers to an unprocessed source input")
        assert event is not None
        _equal(ref, event.source_ref, "Callback source_ref does not match its source record")
        _equal(row["native_time_ns"], event.receive_time_ns, "Callback clock/source mismatch")
        return event

    def bindings_and_inputs(self) -> None:
        document, prepared = self.document, self.prepared
        _equal(document["engine"], _ENGINE, "Unsupported engine version or replay semantic")
        environment = cast("Row", document["environment"])
        packages = cast("Row", environment["package_versions"])
        _equal(packages.get("nautilus_trader"), "1.231.0", "Environment native version mismatch")
        for key, expected in (
            ("dataset_id", prepared.dataset_id),
            ("data_sha256", prepared.data_sha256),
            ("spec_id", prepared.spec.spec_id),
        ):
            _equal(document[key], expected, "Replay input binding mismatch: " + key)
        completeness = cast("Row", document["completeness"])
        _equal(completeness["input_records"], len(prepared.events), "Input record count mismatch")
        inputs = _rows(document, "input_trace")
        _require(len(inputs) == len(self.events), "Processed input prefix length mismatch")
        bids: dict[int, int] = {}
        asks: dict[int, int] = {}
        for row, event in zip(inputs, self.events, strict=True):
            _equal(row["kind"], "input_processed", "Unsupported input trace kind")
            self.event(row)
            _equal(_fields(row), _expected_input(event), "Input trace differs from sealed source")
            if event.event_type != "trade":
                for book, updates in ((bids, event.bids), (asks, event.asks)):
                    for price, quantity in updates:
                        if quantity:
                            book[price] = quantity
                        else:
                            _require(price in book, "Source delta deletes an absent level")
                            del book[price]
                _require(bool(bids) and bool(asks) and max(bids) < min(asks), "Invalid source book")
                best = max(bids)
                self.mark = {
                    "source_ref": event.source_ref,
                    "native_time_ns": event.receive_time_ns,
                    "price_ticks": best,
                    "price": _decimal(best * self.profile.price_increment),
                    "available_quantity_lots": bids[best],
                }
            self.book_counts[event.line] = (len(bids), len(asks))
        for channel in ("decision_trace", "order_trace", "fill_trace"):
            previous_line = 0
            for row in _rows(document, channel):
                event = self.event(row)
                _require(event.line >= previous_line, "Callback source order runs backwards")
                previous_line = event.line

    def decisions(self) -> None:
        rows = _rows(self.document, "decision_trace")
        _require(len(rows) <= 2, "Only one submit and at most one cancel are supported")
        if self.document["execution_status"] != "failed":
            _require(bool(rows), "Completed input processing must issue the selected order")
        for ordinal, row in enumerate(rows):
            event, fields = self.event(row), _fields(row)
            action = "submit" if ordinal == 0 else "cancel"
            order_id = text(fields.get("order_id"), "order_id")
            if ordinal == 0:
                self.order_id = order_id
                _equal(
                    event.capture_seq, self.profile.submit_seq, "Submit source differs from spec"
                )
            else:
                _require(self.profile.cancel, "Cancel contradicts the built-in strategy spec")
                _equal(order_id, self.order_id, "Cancel switches the single order")
            expected: Row = {
                "decision_ref": f"decision-{ordinal}",
                "command_id": f"command-{ordinal}",
                "action": action,
                "order_id": order_id,
                "strategy_kind": "single_limit_buy_v1",
                "limit_price_ticks": self.profile.limit,
                "quantity_lots": self.profile.requested,
                "post_only": True,
                "cause": "selected_capture" if ordinal == 0 else "first_partial_fill",
            }
            _equal(row["kind"], "command_issued", "Unsupported decision kind")
            _equal(fields, expected, "Decision fields contradict the built-in spec")
            self.commands[f"command-{ordinal}"] = {
                "command_id": f"command-{ordinal}",
                "order_id": order_id,
                "command_type": action,
                "decision_ref": f"decision-{ordinal}",
                "source_ref": event.source_ref,
            }

    def fills(self) -> None:
        seen: set[str] = set()
        per_source_quantity: dict[int, int] = {}
        rows = _rows(self.document, "fill_trace")
        for row in rows:
            event, fields = self.event(row), _fields(row)
            exact(
                fields,
                {
                    "order_id",
                    "native_trade_id",
                    "price_ticks",
                    "quantity_lots",
                    "price",
                    "quantity",
                    "commission",
                    "commission_currency",
                    "declared_fee_rate",
                    "exact_decimal_fee_before_native_quantization",
                    "native_commission_minus_exact_decimal_fee",
                    "native_fee_policy",
                    "liquidity_side",
                    "native_event_ts_ns",
                    "native_init_ts_ns",
                    "source_ref_semantics",
                },
                "fill fields",
            )
            _equal(row["kind"], "OrderFilled", "Unsupported fill kind")
            _require(self.order_id is not None, "Fill without a submitted order")
            _equal(fields["order_id"], self.order_id, "Fill switches the single order")
            native_id = text(fields["native_trade_id"], "native_trade_id", 256)
            _require(native_id not in seen, "Duplicate native fill trade ID")
            seen.add(native_id)
            lots = integer(fields["quantity_lots"], "fill quantity_lots", 1)
            ticks = integer(fields["price_ticks"], "fill price_ticks", 1)
            _require(ticks == self.profile.limit, "Audited maker fill must equal the frozen limit")
            _require(
                event.event_type == "trade",
                "Non-trade-triggered maker fill is outside the audited profile",
            )
            _require(
                self.quantity + lots <= self.profile.requested, "Cumulative fill exceeds order"
            )
            price, quantity = (
                ticks * self.profile.price_increment,
                lots * self.profile.size_increment,
            )
            _require(_number(fields["price"], "fill price") == price, "Fill price unit mismatch")
            _require(
                _number(fields["quantity"], "fill quantity") == quantity,
                "Fill quantity unit mismatch",
            )
            _equal(fields["commission_currency"], "USD", "Commission currency must be USD")
            _equal(fields["liquidity_side"], "MAKER", "Post-only buy profile requires maker fills")
            _equal(fields["native_fee_policy"], _FEE_POLICY, "Unknown native fee policy")
            _equal(fields["source_ref_semantics"], _SOURCE_SEMANTICS, "Unknown fill source policy")
            _require(
                _number(fields["declared_fee_rate"], "declared fee rate") == self.profile.maker,
                "Fill rate differs from the spec",
            )
            commission = _money(fields["commission"], "actual commission", nonnegative=True)
            by_mode = _fees_by_mode(price, quantity, self.profile.maker)
            candidates = set(by_mode.values())
            _require(
                commission in candidates,
                "Actual commission contradicts the pinned native fee model",
            )
            if len(candidates) != 1:
                self.ambiguous_fees.append(cast("int", row["ordinal"]))
            self.compatible_modes.intersection_update(
                mode for mode, amount in by_mode.items() if amount == commission
            )
            _require(
                bool(self.compatible_modes), "Actual commissions mix incompatible native raw modes"
            )
            theoretical = price * quantity * self.profile.maker
            _require(
                _number(fields["exact_decimal_fee_before_native_quantization"], "theoretical fee")
                == theoretical,
                "Declared theoretical fee is not exact",
            )
            _require(
                _number(
                    fields["native_commission_minus_exact_decimal_fee"], "native fee difference"
                )
                == commission - theoretical,
                "Native fee difference is inconsistent",
            )
            for key in ("native_event_ts_ns", "native_init_ts_ns"):
                _equal(fields[key], event.receive_time_ns, "Fill native clock mismatch")
            submit = _rows(self.document, "decision_trace")[0]
            _require(
                event.line >= self.event(submit).line
                and event.receive_time_ns
                >= cast("int", submit["native_time_ns"]) + self.profile.insert_latency,
                "Fill precedes submission or the declared insertion delay",
            )
            if event.event_type == "trade":
                _require(
                    event.aggressor_side == "sell", "Buy maker fill refers to a buy-side trade"
                )
                _require(
                    event.price_ticks is not None and event.price_ticks <= self.profile.limit,
                    "Buy fill refers to an incompatible source trade price",
                )
                per_source_quantity[event.line] = per_source_quantity.get(event.line, 0) + lots
                _require(
                    per_source_quantity[event.line] <= cast("int", event.quantity_lots),
                    "Fills exceed the triggering public trade quantity",
                )
            self.quantity += lots
            self.notional += price * quantity
            self.commission += commission
            self.declared_fee += theoretical
            self.prefixes.append((self.quantity, self.commission))
        decisions = _rows(self.document, "decision_trace")
        should_cancel = (
            bool(rows) and cast("int", _fields(rows[0])["quantity_lots"]) < self.profile.requested
        )
        should_cancel = should_cancel and self.profile.cancel
        if self.document["execution_status"] != "failed":
            _equal(
                len(decisions), 2 if should_cancel else 1, "Missing or unexpected first-fill cancel"
            )
        if len(decisions) == 2:
            _require(should_cancel, "Cancel requires a first partial fill")
            _equal(
                decisions[1]["source_ref"], rows[0]["source_ref"], "Cancel source is not first fill"
            )
            _equal(
                decisions[1]["native_time_ns"],
                rows[0]["native_time_ns"],
                "Cancel time differs from first fill",
            )

    def orders(self) -> str | None:
        rows = _rows(self.document, "order_trace")
        pending = {"command-0": self.commands["command-0"]} if self.commands else {}
        fill_rows = _rows(self.document, "fill_trace")
        fill_index, seen, final_status = 0, set(), None
        for row in rows:
            event, fields, kind = self.event(row), _fields(row), cast("str", row["kind"])
            _require(self.order_id is not None, "Order lifecycle without a submit decision")
            if row["ordinal"] == 0:
                _equal(kind, "OrderInitialized", "Order lifecycle must start with initialization")
            allowed = {
                "order_id",
                "status",
                "native_event_ts_ns",
                "native_init_ts_ns",
                "pending_command_ids",
            }
            if "reason" in fields:
                allowed.add("reason")
                text(fields["reason"], "order reason", 4096)
            exact(fields, allowed, "order fields")
            _require(kind in _ORDER_KINDS, "Unsupported single-order lifecycle event")
            _require(
                final_status not in _TERMINAL or kind == "OrderCancelRejected",
                "Order lifecycle continues after a terminal receipt",
            )
            _equal(fields["order_id"], self.order_id, "Order trace switches the single order")
            for key in ("native_event_ts_ns", "native_init_ts_ns"):
                _equal(fields[key], event.receive_time_ns, "Order native clock mismatch")
            if kind != "OrderFilled":
                _require(kind not in seen, "Duplicate single-order lifecycle event")
                seen.add(kind)
            if kind in ("OrderInitialized", "OrderSubmitted", "OrderDenied"):
                submit = _rows(self.document, "decision_trace")[0]
                _equal(
                    row["source_ref"], submit["source_ref"], "Submission lifecycle source mismatch"
                )
                _equal(
                    row["native_time_ns"],
                    submit["native_time_ns"],
                    "Submission lifecycle time mismatch",
                )
            if kind in ("OrderAccepted", "OrderRejected"):
                _require("OrderSubmitted" in seen, "Remote receipt lacks a submitted command")
                issued_at = cast("int", _rows(self.document, "decision_trace")[0]["native_time_ns"])
                _require(
                    event.receive_time_ns >= issued_at + self.profile.insert_latency,
                    "Remote order receipt precedes the declared insertion delay",
                )
            if kind == "OrderPendingCancel":
                _require(
                    "command-1" in self.commands, "Pending cancellation without a cancel decision"
                )
                pending["command-1"] = self.commands["command-1"]
                cancel = _rows(self.document, "decision_trace")[1]
                _equal(
                    row["source_ref"],
                    cancel["source_ref"],
                    "Pending-cancel source differs from its decision",
                )
                _equal(
                    row["native_time_ns"],
                    cancel["native_time_ns"],
                    "Pending-cancel time differs from its decision",
                )
            if kind in ("OrderAccepted", "OrderRejected", "OrderDenied", "OrderFilled"):
                pending.pop("command-0", None)
            if kind in ("OrderCanceled", "OrderCancelRejected"):
                _require("command-1" in pending, "Cancel receipt without a pending cancel")
                issued = _rows(self.document, "decision_trace")[1]
                _require(
                    event.receive_time_ns
                    >= cast("int", issued["native_time_ns"]) + self.profile.cancel_latency,
                    "Cancellation receipt precedes the declared delay",
                )
                pending.pop("command-1")
                if kind == "OrderCancelRejected":
                    _equal(
                        fields["status"],
                        final_status,
                        "Cancel rejection changes the cached order state",
                    )
            if kind == "OrderFilled":
                _require(
                    "OrderSubmitted" in seen and "OrderAccepted" in seen,
                    "Limit fill lacks required submitted/accepted lifecycle receipts",
                )
                _require(fill_index < len(fill_rows), "Order trace invents a fill callback")
                matching = fill_rows[fill_index]
                _equal(row["source_ref"], matching["source_ref"], "Order/fill source mismatch")
                _equal(
                    row["native_time_ns"], matching["native_time_ns"], "Order/fill time mismatch"
                )
                status = (
                    "FILLED"
                    if self.prefixes[fill_index][0] == self.profile.requested
                    else "PARTIALLY_FILLED"
                )
                if fields["status"] == "PENDING_CANCEL":
                    _require(
                        "command-1" in pending
                        and "OrderPendingCancel" in seen
                        and status == "PARTIALLY_FILLED",
                        "Unbacked pending-cancel fill status",
                    )
                else:
                    _equal(fields["status"], status, "Order fill status mismatch")
                fill_index += 1
            else:
                expected_status = {
                    "OrderInitialized": None,
                    "OrderSubmitted": "SUBMITTED",
                    "OrderAccepted": "ACCEPTED",
                    "OrderRejected": "REJECTED",
                    "OrderDenied": "DENIED",
                    "OrderPendingCancel": "PENDING_CANCEL",
                    "OrderCanceled": "CANCELED",
                }.get(kind, fields["status"])
                _equal(fields["status"], expected_status, "Order lifecycle status mismatch")
            _equal(fields["pending_command_ids"], list(pending), "Order receipt ledger mismatch")
            final_status = cast("str | None", fields["status"])
        _require(fill_index == len(fill_rows), "Fill trace lacks corresponding order callbacks")
        if self.document["execution_status"] != "failed":
            _require("OrderInitialized" in seen and bool(rows), "Missing single-order lifecycle")
        if "command-1" in self.commands and not ({"OrderCanceled", "OrderCancelRejected"} & seen):
            pending["command-1"] = self.commands["command-1"]
        completeness = cast("Row", self.document["completeness"])
        _equal(
            completeness["pending_commands"],
            list(pending.values()),
            "Final pending-command ledger mismatch",
        )
        return final_status

    def accounts(self, final_status: str | None) -> None:
        accounts, fills = _rows(self.document, "account_trace"), _rows(self.document, "fill_trace")
        failed = self.document["execution_status"] == "failed"
        if not accounts:
            _require(failed and not fills, "Missing native account evidence")
            return
        _require(
            accounts[0]["kind"] == "initial_account_snapshot", "Missing initial account snapshot"
        )
        callbacks = [row for row in accounts if row["kind"] == "fill_callback_account_snapshot"]
        final = [row for row in accounts if row["kind"] == "final_account_snapshot"]
        _require(len(callbacks) == len(fills), "Missing or duplicated fill account snapshot")
        _require(
            len(final) <= 1 and (failed or len(final) == 1),
            "Missing/duplicate final account snapshot",
        )
        expected_kinds = ["initial_account_snapshot"] + ["fill_callback_account_snapshot"] * len(
            fills
        )
        if final:
            expected_kinds.append("final_account_snapshot")
        _equal(
            [row["kind"] for row in accounts],
            expected_kinds,
            "Unsupported account snapshot ordering",
        )
        for ordinal, row in enumerate(accounts):
            fields = _fields(row)
            exact(
                fields,
                {
                    "account_type",
                    "ask_levels",
                    "bid_levels",
                    "book_type",
                    "cash_free",
                    "cash_locked",
                    "cash_semantics",
                    "cash_total",
                    "currency",
                    "money_rounding_policy",
                    "native_money_precision",
                    "net_position_lots",
                    "observed_commission",
                    "observed_fill_lots",
                    "oms_type",
                    "orders",
                },
                "account fields",
            )
            for key, expected in (
                ("account_type", "MARGIN"),
                ("oms_type", "NETTING"),
                ("currency", "USD"),
                ("native_money_precision", 2),
                ("money_rounding_policy", _MONEY_POLICY),
                ("cash_semantics", "native_margin_balance_not_spot_notional_debit"),
                ("book_type", "L2_MBP"),
            ):
                _equal(fields[key], expected, "Unsupported account policy: " + key)
            initial, is_final = ordinal == 0, row["kind"] == "final_account_snapshot"
            quantity, commission = (
                (0, Fraction(0))
                if initial
                else ((self.quantity, self.commission) if is_final else self.prefixes[ordinal - 1])
            )
            if initial or is_final:
                _equal(row["source_ref"], None, "Bootstrap/final account must have null source")
                now = (
                    self.events[-1].receive_time_ns
                    if is_final and self.events
                    else self.prepared.events[0].receive_time_ns
                )
                _equal(row["native_time_ns"], now, "Bootstrap/final account clock mismatch")
            else:
                self.event(row)
                _equal(
                    row["source_ref"],
                    fills[ordinal - 1]["source_ref"],
                    "Fill/account source mismatch",
                )
                _equal(
                    row["native_time_ns"],
                    fills[ordinal - 1]["native_time_ns"],
                    "Fill/account clock mismatch",
                )
            _equal(
                fields["net_position_lots"],
                quantity,
                "Native position differs from the independent fill ledger",
            )
            _equal(fields["observed_fill_lots"], quantity, "Observed fill ledger mismatch")
            _require(
                _money(fields["observed_commission"], "observed commission", nonnegative=True)
                == commission,
                "Observed commission differs from fills",
            )
            total = _money(fields["cash_total"], "cash total")
            free, locked = (
                _money(fields["cash_free"], "cash free"),
                _money(fields["cash_locked"], "cash locked", nonnegative=True),
            )
            _require(
                total == self.profile.cash - commission,
                "Margin cash differs from starting cash minus actual fees",
            )
            _require(free + locked == total, "Native locked plus free cash differs from total")
            for key in ("bid_levels", "ask_levels"):
                integer(fields[key], key, 0, 1000)
                _require(
                    (fields[key] == 0) == initial, "Unexpected empty native account book cache"
                )
            if is_final and self.events:
                _equal(
                    [fields["bid_levels"], fields["ask_levels"]],
                    list(self.book_counts[self.events[-1].line]),
                    "Final native book level counts differ from source",
                )
            elif not initial:
                event = self.event(row)
                choices = {self.book_counts[event.line]}
                if event.line > 1:
                    choices.add(self.book_counts[event.line - 1])
                _require(
                    (cast("int", fields["bid_levels"]), cast("int", fields["ask_levels"]))
                    in choices,
                    "Callback native book cache differs from adjacent source states",
                )
            order_values = fields["orders"]
            _require(isinstance(order_values, list), "Account orders must be a list")
            orders = cast("list[object]", order_values)
            if initial:
                _equal(orders, [], "Initial account already has an order")
                _require(locked == 0 and free == self.profile.cash, "Initial margin cash is locked")
                continue
            _require(len(orders) == 1, "Account must contain the single built-in order")
            order = exact(
                orders[0],
                {
                    "order_id",
                    "status",
                    "quantity_lots",
                    "filled_quantity_lots",
                    "remaining_quantity_lots",
                },
                "cached account order",
            )
            _equal(order["order_id"], self.order_id, "Cached account switches the single order")
            _equal(
                order["quantity_lots"],
                self.profile.requested,
                "Cached requested order quantity mismatch",
            )
            _equal(order["filled_quantity_lots"], quantity, "Cached filled order quantity mismatch")
            _equal(
                order["remaining_quantity_lots"],
                self.profile.requested - quantity,
                "Cached remaining order quantity mismatch",
            )
            status = (
                final_status
                if is_final
                else "FILLED"
                if quantity == self.profile.requested
                else "PARTIALLY_FILLED"
            )
            _equal(order["status"], status, "Cached order status differs from lifecycle")
            _require(
                status != "FILLED" or quantity == self.profile.requested,
                "Filled order has missing quantity",
            )
            _require(
                status not in ("REJECTED", "DENIED") or quantity == 0, "Rejected order has fills"
            )
            if is_final:
                expected_open = (
                    [] if status in _TERMINAL else [{"order_id": self.order_id, "status": status}]
                )
                _equal(
                    cast("Row", self.document["completeness"])["open_orders"],
                    expected_open,
                    "Final open-order completeness differs from native account",
                )

    def run(self) -> Row:
        self.bindings_and_inputs()
        self.decisions()
        self.fills()
        self.accounts(self.orders())
        status = cast("str", self.document["execution_status"])
        reason = (
            "execution_" + status
            if status != "completed"
            else "no_fills"
            if not self.quantity
            else "ambiguous_native_fee_model"
            if self.ambiguous_fees
            else None
        )
        valued = reason is None
        mark = self.mark if valued else None
        valuation: Row | None = None
        if valued:
            _require(mark is not None, "Valuation lacks a final source bid")
            assert mark is not None
            gross = (
                self.quantity * self.profile.size_increment * _number(mark["price"], "mark price")
                - self.notional
            )
            valuation = {
                "realized_pnl": "0",
                "gross_unrealized_pnl": _decimal(gross),
                "net_marked_pnl": _decimal(gross - self.commission),
            }
        return {
            "kind": "replay_evaluation_v1",
            "schema_version": 1,
            "evaluation_policy": _POLICY,
            "bindings": {
                "dataset_id": self.prepared.dataset_id,
                "data_sha256": self.prepared.data_sha256,
                "spec_id": self.prepared.spec.spec_id,
                "result_sha256": digest(self.result.canonical_bytes),
                "engine": dict(_ENGINE),
            },
            "audit_status": "verified",
            "execution_status": status,
            "valuation_status": "valued" if valued else "not_eligible",
            "ineligibility_reason": reason,
            "unit": "USD",
            "fee_model_verification": {
                "policy_id": _FEE_AUDIT_POLICY,
                "status": "not_applicable"
                if not self.prefixes
                else "ambiguous"
                if self.ambiguous_fees
                else "verified_unique",
                "raw_precision_candidates": [9, 16],
                "ambiguous_fill_ordinals": list(self.ambiguous_fees),
            },
            "mark": mark,
            "ledger": {
                "fill_count": len(self.prefixes),
                "requested_quantity_lots": self.profile.requested,
                "filled_quantity_lots": self.quantity,
                "position_quantity": _decimal(self.quantity * self.profile.size_increment),
                "fill_notional": _decimal(self.notional),
                "actual_commission": _decimal(self.commission),
                "declared_decimal_commission": _decimal(self.declared_fee),
                "native_commission_difference": _decimal(self.commission - self.declared_fee),
            },
            "valuation": valuation,
        }


def evaluate_replay(replay_input: ReplayInput, result: ReplayResult) -> ReplayEvaluation:
    """Audit supplied evidence and value only a completed, closed, nonempty fill ledger."""
    try:
        prepared = preflight_replay(replay_input)
        if not isinstance(result, ReplayResult):
            raise EvaluationValidationError("Evaluation requires a ReplayResult")
        document = _Audit(prepared, result).run()
        encoded = canonical(document)
        return ReplayEvaluation(digest(encoded), encoded)
    except ReplayValidationError as error:
        raise EvaluationValidationError(str(error)) from error


def _validate_evaluation(document: Row) -> None:
    exact(
        document,
        {
            "kind",
            "schema_version",
            "evaluation_policy",
            "bindings",
            "audit_status",
            "execution_status",
            "valuation_status",
            "ineligibility_reason",
            "unit",
            "mark",
            "ledger",
            "valuation",
            "fee_model_verification",
        },
        "ReplayEvaluation",
    )
    _equal(document["kind"], "replay_evaluation_v1", "Unsupported evaluation kind")
    _equal(document["schema_version"], 1, "Unsupported evaluation version")
    _equal(document["evaluation_policy"], _POLICY, "Unsupported evaluation policy")
    _equal(document["audit_status"], "verified", "Unsupported audit status")
    _equal(document["unit"], "USD", "Evaluation unit must be USD")
    bindings = exact(
        document["bindings"],
        {"dataset_id", "data_sha256", "spec_id", "result_sha256", "engine"},
        "evaluation bindings",
    )
    for key in ("dataset_id", "data_sha256", "spec_id", "result_sha256"):
        identity(bindings[key], key)
    _equal(bindings["engine"], _ENGINE, "Unsupported evaluation engine")
    ledger = exact(
        document["ledger"],
        {
            "fill_count",
            "requested_quantity_lots",
            "filled_quantity_lots",
            "position_quantity",
            "fill_notional",
            "actual_commission",
            "declared_decimal_commission",
            "native_commission_difference",
        },
        "evaluation ledger",
    )
    count = integer(ledger["fill_count"], "fill_count", 0, 50_000)
    requested = integer(ledger["requested_quantity_lots"], "requested_quantity_lots", 1)
    filled = integer(ledger["filled_quantity_lots"], "filled_quantity_lots", 0, requested)
    _require((count == 0) == (filled == 0), "Fill count/quantity contradiction")
    _require(count <= filled, "Fill count exceeds positive integer lot quantity")
    fee_verification = exact(
        document["fee_model_verification"],
        {"policy_id", "status", "raw_precision_candidates", "ambiguous_fill_ordinals"},
        "fee model verification",
    )
    _equal(fee_verification["policy_id"], _FEE_AUDIT_POLICY, "Unsupported fee audit policy")
    _equal(fee_verification["raw_precision_candidates"], [9, 16], "Native raw modes differ")
    ambiguous = fee_verification["ambiguous_fill_ordinals"]
    _require(isinstance(ambiguous, list), "Ambiguous fee ordinals must be a list")
    ambiguous_ordinals = cast("list[object]", ambiguous)
    checked_ordinals = [
        integer(item, "ambiguous fill ordinal", 0, count - 1) for item in ambiguous_ordinals
    ]
    _equal(
        checked_ordinals,
        sorted(set(checked_ordinals)),
        "Ambiguous fee ordinals must be ordered/unique",
    )
    _equal(
        fee_verification["status"],
        "not_applicable" if not count else "ambiguous" if checked_ordinals else "verified_unique",
        "Fee verification status contradicts fills",
    )
    numbers: dict[str, Fraction] = {}
    for key in (
        "position_quantity",
        "fill_notional",
        "actual_commission",
        "declared_decimal_commission",
        "native_commission_difference",
    ):
        value = _number(ledger[key], key, nonnegative=key != "native_commission_difference")
        _equal(ledger[key], _decimal(value), "Evaluation decimal is not canonical")
        numbers[key] = value
    _money(ledger["actual_commission"], "actual commission", nonnegative=True)
    _require(
        numbers["actual_commission"] - numbers["declared_decimal_commission"]
        == numbers["native_commission_difference"],
        "Evaluation fee difference contradiction",
    )
    _require(
        (numbers["position_quantity"] == 0) == (filled == 0), "Evaluation position contradiction"
    )
    _require((numbers["fill_notional"] == 0) == (filled == 0), "Evaluation notional contradiction")
    if not filled:
        _require(
            numbers["actual_commission"] == numbers["declared_decimal_commission"] == 0,
            "No-fill evaluation has commissions",
        )
    status, reason = document["execution_status"], document["ineligibility_reason"]
    _require(status in ("completed", "incomplete", "failed"), "Invalid evaluated execution status")
    expected_reason = (
        "execution_" + cast("str", status)
        if status != "completed"
        else "no_fills"
        if not filled
        else "ambiguous_native_fee_model"
        if checked_ordinals
        else None
    )
    _equal(reason, expected_reason, "Ineligibility reason contradicts execution/fills")
    if reason is not None:
        _equal(document["valuation_status"], "not_eligible", "Ineligible execution has valuation")
        _equal(document["mark"], None, "Ineligible execution cannot carry a valuation mark")
        _equal(document["valuation"], None, "Ineligible execution cannot carry PnL")
        return
    _equal(document["valuation_status"], "valued", "Eligible execution lacks valuation")
    mark = exact(
        document["mark"],
        {"source_ref", "native_time_ns", "price_ticks", "price", "available_quantity_lots"},
        "mark",
    )
    reference = exact(mark["source_ref"], {"line", "capture_seq", "event_type"}, "mark source")
    integer(reference["line"], "mark line", 1, 10_000)
    integer(reference["capture_seq"], "mark capture_seq", 1)
    _require(reference["event_type"] in ("snapshot", "delta"), "Mark must refer to a source book")
    integer(mark["native_time_ns"], "mark time")
    integer(mark["price_ticks"], "mark price_ticks", 1)
    integer(mark["available_quantity_lots"], "mark available quantity", 1)
    price = _number(mark["price"], "mark price", nonnegative=True)
    _require(price > 0, "Mark price must be positive")
    _equal(mark["price"], _decimal(price), "Mark decimal is not canonical")
    valuation = exact(
        document["valuation"],
        {"realized_pnl", "gross_unrealized_pnl", "net_marked_pnl"},
        "valuation",
    )
    _equal(valuation["realized_pnl"], "0", "Single buy profile cannot realize a closing PnL")
    gross = numbers["position_quantity"] * price - numbers["fill_notional"]
    _equal(valuation["gross_unrealized_pnl"], _decimal(gross), "Gross mark valuation contradiction")
    _equal(
        valuation["net_marked_pnl"],
        _decimal(gross - numbers["actual_commission"]),
        "Net mark valuation contradiction",
    )


@dataclass(frozen=True, slots=True)
class ReplayEvaluation:
    evaluation_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            document = parse(self.canonical_bytes, _LIMIT)
            _validate_evaluation(document)
            _require(
                canonical(document) == self.canonical_bytes, "Evaluation encoding must be canonical"
            )
            _equal(self.evaluation_id, digest(self.canonical_bytes), "Evaluation identity mismatch")
        except ReplayValidationError as error:
            raise EvaluationValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, _LIMIT)


def load_replay_evaluation(raw: bytes) -> ReplayEvaluation:
    """Validate format/identity/arithmetic; source audit still requires evaluate_replay."""
    try:
        parse(raw, _LIMIT)
        return ReplayEvaluation(digest(raw), raw)
    except ReplayValidationError as error:
        raise EvaluationValidationError(str(error)) from error
