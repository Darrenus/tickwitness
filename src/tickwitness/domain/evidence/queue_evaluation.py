"""Independent source, queue, grant, lifecycle and margin-account audit.

This audit consumes immutable input and actual native callbacks. It never calls
the engine, imports its queue implementation, or interprets a model as evidence
of observable priority, impact compatibility, strategy value or claim truth.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from tickwitness.domain.evidence.evaluation import (
    EvaluationValidationError,
    _Profile,
    _decimal,
    _equal,
    _expected_input,
    _fees_by_mode,
    _money,
    _number,
    _require,
)
from tickwitness.domain.replay._validation import (
    ReplayValidationError,
    canonical,
    digest,
    exact,
    identity,
    integer,
    parse,
)
from tickwitness.domain.replay.contracts import ReplayEvent
from tickwitness.domain.replay.queue_contracts import (
    ENGINE,
    QueueReplayInput,
    QueueReplayResult,
    load_queue_replay_result,
)

Row = dict[str, object]
_LIMIT = 64 * 1024
_AUDIT = "queue_source_grant_margin_audit_v1"
_SCOPE: Row = {
    "scenario_kind": "MODEL_SENSITIVITY",
    "impact_compatibility_verified": False,
    "claim_verdict_issued": False,
    "valuation_issued": False,
}


def _rows(document: Row, channel: str) -> list[Row]:
    return cast("list[Row]", document[channel])


def _fields(row: Row) -> Row:
    return cast("Row", row["fields"])


class _QueueAudit:
    def __init__(self, supplied: QueueReplayInput, result: QueueReplayResult) -> None:
        self.input = QueueReplayInput(supplied.family, supplied.normalized_bytes, supplied.policy_id)
        self.result = load_queue_replay_result(result.canonical_bytes)
        self.document = self.result.document
        self.events = self.input.prepared.events
        self.by_line = {event.line: event for event in self.events}
        self.profile = _Profile.read(self.input.prepared)
        self.quantity = 0
        self.commission = Fraction(0)
        self.prefixes: list[tuple[int, Fraction]] = []
        self.fills_by_line: dict[int, int] = {}
        self.book_counts: dict[int, tuple[int, int]] = {}
        self.compatible_modes = {9, 16}
        self.ambiguous: list[int] = []
        self.order_id: str | None = None

    def event(self, row: Row) -> ReplayEvent:
        ref = cast("Row", row["source_ref"])
        _require(isinstance(ref, dict), "Queue callback requires a real input context")
        event = self.by_line.get(cast("int", ref.get("line")))
        _require(event is not None, "Queue callback refers to an unknown input")
        assert event is not None
        _equal(ref, event.source_ref, "Queue callback source differs from sealed input")
        if "native_time_ns" in row:
            _equal(row["native_time_ns"], event.receive_time_ns, "Queue callback clock differs")
        return event

    def inputs(self) -> None:
        _equal(self.document["bindings"], self.input.bindings, "Queue execution binding mismatch")
        _equal(self.document["engine"], ENGINE, "Queue engine profile mismatch")
        environment = cast("Row", self.document["environment"])
        _equal(cast("Row", environment["package_versions"]).get("nautilus_trader"),
               "1.231.0", "Queue native dependency version mismatch")
        complete = cast("Row", self.document["completeness"])
        _equal([complete["input_records"], complete["processed_records"]],
               [len(self.events), len(self.events)], "Queue execution omits source input")
        inputs = _rows(self.document, "input_trace")
        _equal(len(inputs), len(self.events), "Queue input trace is incomplete")
        bids: dict[int, int] = {}
        asks: dict[int, int] = {}
        for event, row in zip(self.events, inputs, strict=True):
            _equal(row["kind"], "input_processed", "Unsupported queue input kind")
            _equal(self.event(row).source_ref, event.source_ref, "Queue input order differs")
            _equal(_fields(row), _expected_input(event), "Queue input differs from sealed source")
            if event.event_type != "trade":
                for book, changes in ((bids, event.bids), (asks, event.asks)):
                    for price, quantity in changes:
                        if quantity:
                            book[price] = quantity
                        else:
                            _require(price in book, "Queue source deletes an absent level")
                            del book[price]
            self.book_counts[event.line] = len(bids), len(asks)
        for channel in ("decision_trace", "order_trace", "fill_trace"):
            previous = 0
            for row in _rows(self.document, channel):
                event = self.event(row)
                _require(event.line >= previous, "Queue callback input order runs backwards")
                previous = event.line

    def decisions(self) -> None:
        rows = _rows(self.document, "decision_trace")
        _require(1 <= len(rows) <= 2, "Queue execution requires exactly one single-order submit")
        family_strategy = cast("Row", self.input.family.document["strategy"])
        for ordinal, row in enumerate(rows):
            fields, event = _fields(row), self.event(row)
            if ordinal == 0:
                self.order_id = cast("str", fields.get("order_id"))
                _require(isinstance(self.order_id, str) and bool(self.order_id), "Missing queue order ID")
            action = "submit" if ordinal == 0 else "cancel"
            _equal(row["kind"], "command_issued", "Unsupported queue decision")
            _equal(event.capture_seq, 1 if ordinal == 0 else family_strategy["cancel_at_capture_seq"],
                   "Queue decision differs from frozen capture")
            _equal(fields, {
                "decision_ref": f"decision-{ordinal}", "command_id": f"command-{ordinal}",
                "action": action, "order_id": self.order_id,
                "strategy_kind": "single_limit_buy_cancel_at_capture_v1",
                "limit_price_ticks": self.profile.limit, "quantity_lots": self.profile.requested,
                "post_only": True, "cause": "selected_capture" if ordinal == 0 else "family_cancel_capture",
            }, "Queue decision contradicts frozen strategy")

    def fills(self) -> None:
        ids: set[str] = set()
        for row in _rows(self.document, "fill_trace"):
            event, fields = self.event(row), _fields(row)
            _equal(row["kind"], "OrderFilled", "Unsupported queue fill callback")
            _equal(fields["order_id"], self.order_id, "Queue fill switches orders")
            trade_id = cast("str", fields["native_trade_id"])
            _require(trade_id not in ids, "Duplicate native queue fill ID")
            ids.add(trade_id)
            _require(event.event_type == "trade" and event.aggressor_side == "sell",
                     "Queue fill lacks a matching aggressor trade")
            _equal(event.price_ticks, self.profile.limit, "Queue fill trade has another price")
            lots = integer(fields["quantity_lots"], "fill lots", 1)
            _equal(fields["price_ticks"], self.profile.limit, "Queue fill price differs from limit")
            price, quantity = self.profile.limit * self.profile.price_increment, lots * self.profile.size_increment
            _require(_number(fields["price"], "fill price") == price, "Queue fill price unit mismatch")
            _require(_number(fields["quantity"], "fill quantity") == quantity, "Queue fill size unit mismatch")
            _equal(fields["commission_currency"], "USD", "Queue commission currency differs")
            _equal(fields["liquidity_side"], "MAKER", "Queue post-only fill is not maker")
            commission = _money(fields["commission"], "queue commission", nonnegative=True)
            modes = _fees_by_mode(price, quantity, self.profile.maker)
            self.compatible_modes.intersection_update(mode for mode, value in modes.items() if value == commission)
            _require(bool(self.compatible_modes), "Queue native fees violate the pinned fee model")
            if len(set(modes.values())) != 1:
                self.ambiguous.append(cast("int", row["ordinal"]))
            self.quantity += lots
            self.commission += commission
            _require(self.quantity <= self.profile.requested, "Queue fills exceed requested quantity")
            self.prefixes.append((self.quantity, self.commission))
            self.fills_by_line[event.line] = self.fills_by_line.get(event.line, 0) + lots
        _equal(len(_rows(self.document, "decision_trace")),
               1 if self.quantity == self.profile.requested else 2,
               "Missing final-capture cancellation or unexpected cancellation after full fill")

    def queues(self) -> None:
        interpretations = cast("list[Row]", self.input.feasibility.document["interpretations"])
        selected = next(row for row in interpretations if row["policy_id"] == self.input.policy_id)
        pure = {cast("int", cast("Row", row["source_ref"])["line"]): row
                for row in cast("list[Row]", selected["trace"])}
        hooks: dict[int, list[Row]] = {}
        previous = 0
        for hook in _rows(self.document, "hook_trace"):
            event = self.event(hook)
            _require(event.line >= previous, "Queue hook order runs backwards")
            previous = event.line
            _equal(hook["origin"], "native_public_fill_simulation_hook", "Unknown queue hook origin")
            hooks.setdefault(event.line, []).append(hook)
        remaining = self.profile.requested
        state: Row | None = None
        observed = 0
        for event, row in zip(self.events, _rows(self.document, "queue_trace"), strict=True):
            _equal(self.event(row).source_ref, event.source_ref, "Queue state input order differs")
            _equal(row["receive_time_ns"], event.receive_time_ns, "Queue receive clock mismatch")
            transition = pure.get(event.line)
            before = state
            flow: Row = {key: 0 for key in ("additions_lots", "cancellations_lots", "trade_lots",
                                           "cancel_ahead_lots", "cancel_behind_lots")}
            if transition is not None:
                _equal(transition["before"], before, "Pure queue predecessor differs")
                flow, state = cast("Row", transition["flow"]), cast("Row", transition["after"])
            _equal(row["before"], before, "Native queue predecessor differs")
            _equal(row["after"], state, "Native queue violates external flow conservation")
            _equal(row["flow"], flow, "Native queue rewrites declared gross flow")
            for price, quantity in event.bids:
                if price == self.profile.limit:
                    observed = quantity
            _equal(row["market_observed_lots"], observed, "Native queue public depth differs")
            capacity = 0
            if event.event_type == "trade":
                assert before is not None
                capacity = min(remaining, max(0, cast("int", event.quantity_lots) - cast("int", before["ahead_lots"])))
            _equal(row["grant_limit_lots"], capacity, "Queue grant capacity differs from independent FIFO frontier")
            granted = 0
            for hook in hooks.get(event.line, []):
                offered = cast("int", hook["offered_lots"])
                _require(offered <= capacity - granted, "Public hook reuses a trade allocation")
                granted += offered
                _equal(hook["cumulative_granted_lots"], granted, "Hook cumulative grant mismatch")
            filled = self.fills_by_line.get(event.line, 0)
            _require(filled <= granted <= capacity, "Native fills exceed granted queue allocation")
            _equal(row["granted_lots"], granted, "Queue grants disagree with actual hooks")
            _equal(row["native_filled_lots"], filled, "Queue fills disagree with actual callbacks")
            remaining -= filled
            _equal(row["own_remaining_lots"], remaining, "Queue remaining quantity differs from fills")
            _equal(row["accepted_here"], event.line == 1, "Queue actual acceptance must be at entry")

    def orders(self) -> str:
        rows = _rows(self.document, "order_trace")
        _require(bool(rows), "Missing native queue lifecycle")
        seen: set[str] = set()
        fill_index, cumulative = 0, 0
        pending = ["command-0"]
        status: object = None
        decisions = _rows(self.document, "decision_trace")
        for row in rows:
            event, fields, kind = self.event(row), _fields(row), cast("str", row["kind"])
            _equal(fields["event_type"], kind, "Queue lifecycle kind mismatch")
            _equal(fields["order_id"], self.order_id, "Queue lifecycle switches orders")
            _require(status not in ("FILLED", "CANCELED", "REJECTED", "DENIED"),
                     "Queue lifecycle continues after a terminal receipt")
            if kind != "OrderFilled":
                _require(kind not in seen, "Duplicate queue lifecycle event")
                seen.add(kind)
            if kind == "OrderInitialized":
                _require(row["ordinal"] == 0 and event.line == 1, "Queue lifecycle must initialize at entry")
                status = fields["status"]
                _require(status in (None, "INITIALIZED"), "Invalid initialized queue status")
            elif kind == "OrderSubmitted":
                _require("OrderInitialized" in seen and event.line == 1, "Queue submit lacks initialization")
                status = "SUBMITTED"
            elif kind == "OrderAccepted":
                _require("OrderSubmitted" in seen and event.line == 1, "Queue acceptance lacks entry submission")
                state = cast("Row", _rows(self.document, "queue_trace")[0]["after"])
                _equal(fields["actual_acceptance"], {
                    "native_bid_lots": state["external_lots"], "queue": state,
                    "target_price_ticks": self.profile.limit,
                }, "Actual acceptance depth/queue differs from source")
                pending.remove("command-0")
                status = "ACCEPTED"
            elif kind == "OrderFilled":
                _require("OrderAccepted" in seen, "Queue fill precedes actual acceptance")
                fills = _rows(self.document, "fill_trace")
                _require(fill_index < len(fills), "Queue lifecycle invents fills")
                _equal(row["source_ref"], fills[fill_index]["source_ref"], "Queue lifecycle fill source mismatch")
                cumulative = self.prefixes[fill_index][0]
                fill_index += 1
                status = "FILLED" if cumulative == self.profile.requested else "PARTIALLY_FILLED"
            elif kind == "OrderPendingCancel":
                _require("OrderAccepted" in seen and len(decisions) == 2,
                         "Queue pending cancellation has no accepted command")
                _equal(row["source_ref"], decisions[1]["source_ref"], "Queue cancel source differs")
                pending.append("command-1")
                status = "PENDING_CANCEL"
            elif kind == "OrderCanceled":
                _require("command-1" in pending, "Queue cancellation lacks a pending command")
                _equal(row["source_ref"], decisions[1]["source_ref"], "Queue cancel receipt source differs")
                pending.remove("command-1")
                status = "CANCELED"
            else:
                raise EvaluationValidationError("Unsupported or rejected queue lifecycle")
            _equal(fields["status"], status, "Queue lifecycle status mismatch")
            _equal(fields["pending_commands"], pending, "Queue command acknowledgement mismatch")
            if kind != "OrderAccepted":
                _equal(fields["actual_acceptance"], None, "Unexpected queue acceptance evidence")
            for key, expected in (("quantity_lots", self.profile.requested),
                                  ("filled_quantity_lots", cumulative),
                                  ("remaining_quantity_lots", self.profile.requested - cumulative)):
                _equal(fields[key], None if kind == "OrderInitialized" and status is None else expected,
                       "Queue order quantity differs from fill ledger")
        _require("OrderAccepted" in seen, "Queue execution lacks actual acceptance")
        _equal(fill_index, len(self.prefixes), "Queue fill lacks native lifecycle callback")
        expected_status = "FILLED" if self.quantity == self.profile.requested else "CANCELED"
        _equal(status, expected_status, "Queue execution has no terminal native order receipt")
        complete = cast("Row", self.document["completeness"])
        _equal(complete["pending_commands"], [], "Queue execution retains pending commands")
        _equal(complete["open_orders"], [], "Queue execution retains open orders")
        _equal(self.document["execution_status"], "completed", "Queue execution is incomplete")
        return expected_status

    def accounts(self, final_status: str) -> None:
        rows = _rows(self.document, "account_trace")
        fills = _rows(self.document, "fill_trace")
        expected_kinds = ["initial_account_snapshot"] + ["fill_callback_account_snapshot"] * len(fills) + ["final_account_snapshot"]
        _equal([row["kind"] for row in rows], expected_kinds, "Queue account snapshots are incomplete")
        for index, row in enumerate(rows):
            fields = _fields(row)
            initial, final = index == 0, index == len(rows) - 1
            quantity, fees = (0, Fraction(0)) if initial else (self.quantity, self.commission) if final else self.prefixes[index - 1]
            if initial or final:
                _equal(row["source_ref"], None, "Queue boundary account has an input context")
                _equal(row["native_time_ns"], self.events[0 if initial else -1].receive_time_ns,
                       "Queue boundary account clock mismatch")
            else:
                self.event(row)
                _equal(row["source_ref"], fills[index - 1]["source_ref"], "Queue fill account source mismatch")
            for key, expected in (("account_type", "MARGIN"), ("oms_type", "NETTING"),
                                  ("currency", "USD"), ("native_money_precision", 2),
                                  ("money_rounding_policy", "native_v1_f64_notional_then_USD_Money_precision_2"),
                                  ("cash_semantics", "native_margin_balance_not_spot_notional_debit"),
                                  ("net_position_lots", quantity), ("observed_fill_lots", quantity)):
                _equal(fields[key], expected, "Queue native account profile/position mismatch")
            _require(_money(fields["observed_commission"], "observed fees", nonnegative=True) == fees,
                     "Queue account fee ledger differs from actual fills")
            total = _money(fields["cash_total"], "queue cash")
            free = _money(fields["cash_free"], "queue free cash")
            locked = _money(fields["cash_locked"], "queue locked cash", nonnegative=True)
            _require(total == self.profile.cash - fees and free + locked == total,
                     "Queue margin cash differs from starting cash minus actual fees")
            _equal(fields["book_type"], "L2_MBP", "Queue native book type mismatch")
            counts = fields["bid_levels"], fields["ask_levels"]
            if initial:
                _equal(counts, (0, 0), "Initial queue account already has book levels")
                _equal(fields["orders"], [], "Initial queue account already has orders")
                _require(locked == 0 and free == self.profile.cash, "Initial queue account has locked cash")
                continue
            event = self.events[-1] if final else self.event(row)
            choices = {self.book_counts[event.line]}
            if not final and event.line > 1:
                choices.add(self.book_counts[event.line - 1])
            _require(counts in choices, "Queue native book counts differ from adjacent source states")
            status = final_status if final else "FILLED" if quantity == self.profile.requested else "PARTIALLY_FILLED"
            _equal(fields["orders"], [{
                "order_id": self.order_id, "status": status, "quantity_lots": self.profile.requested,
                "filled_quantity_lots": quantity, "remaining_quantity_lots": self.profile.requested - quantity,
            }], "Queue cached order disagrees with lifecycle/fills")

    def run(self) -> Row:
        self.inputs()
        self.decisions()
        self.fills()
        self.queues()
        final = self.orders()
        self.accounts(final)
        return {
            "kind": "queue_replay_evaluation_v1", "schema_version": 1,
            "audit_policy": _AUDIT, "bindings": self.input.bindings,
            "replay_result_sha256": digest(self.result.canonical_bytes),
            "scope": dict(_SCOPE), "status": "verified",
            "input_records": len(self.events), "filled_quantity_lots": self.quantity,
            "actual_commission": _decimal(self.commission),
            "final_cash_total": _decimal(self.profile.cash - self.commission),
            "final_order_status": final, "compatible_native_raw_modes": sorted(self.compatible_modes),
            "ambiguous_fee_fill_ordinals": self.ambiguous,
        }


@dataclass(frozen=True, slots=True)
class QueueReplayEvaluation:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        document = parse(self.canonical_bytes, _LIMIT)
        exact(document, {"kind", "schema_version", "audit_policy", "bindings", "replay_result_sha256",
                         "scope", "status", "input_records", "filled_quantity_lots", "actual_commission",
                         "final_cash_total", "final_order_status", "compatible_native_raw_modes",
                         "ambiguous_fee_fill_ordinals"}, "Queue evaluation")
        _equal([document["kind"], document["schema_version"], document["audit_policy"], document["status"]],
               ["queue_replay_evaluation_v1", 1, _AUDIT, "verified"], "Unsupported queue evaluation")
        _equal(document["scope"], _SCOPE, "Queue evaluation exceeds model-sensitivity scope")
        bindings = exact(document["bindings"], {"family_id", "source_protocol_id", "dataset_id", "data_sha256",
                                             "spec_id", "constraint_id", "policy_id"}, "Queue evaluation bindings")
        for key, value in bindings.items():
            if key != "policy_id":
                identity(value, key)
        _require(bindings["policy_id"] in ("cancel_front_first_v1", "cancel_back_first_v1"), "Unknown queue policy")
        identity(document["replay_result_sha256"], "replay_result_sha256")
        integer(document["input_records"], "input_records", 1, 1000)
        integer(document["filled_quantity_lots"], "filled_quantity_lots")
        _money(document["actual_commission"], "actual commission", nonnegative=True)
        _money(document["final_cash_total"], "final cash")
        _require(document["final_order_status"] in ("FILLED", "CANCELED"), "Queue evaluation requires terminal order")
        modes = document["compatible_native_raw_modes"]
        _require(modes in ([9], [16], [9, 16]), "Invalid queue native raw modes")
        ordinals = document["ambiguous_fee_fill_ordinals"]
        _require(isinstance(ordinals, list) and len(ordinals) <= 50_000, "Invalid ambiguous fee ordinals")
        previous = -1
        for item in cast("list[object]", ordinals):
            previous = integer(item, "fee ordinal", previous + 1, 49_999)
        _require(self.canonical_bytes == canonical(document), "Queue evaluation is not canonical")

    @property
    def evaluation_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, _LIMIT)


def evaluate_queue_replay(replay_input: QueueReplayInput, result: QueueReplayResult) -> QueueReplayEvaluation:
    try:
        return QueueReplayEvaluation(canonical(_QueueAudit(replay_input, result).run()))
    except ReplayValidationError as error:
        raise EvaluationValidationError(str(error)) from error


def load_queue_evaluation(raw: bytes) -> QueueReplayEvaluation:
    try:
        return QueueReplayEvaluation(raw)
    except ReplayValidationError as error:
        raise EvaluationValidationError(str(error)) from error
