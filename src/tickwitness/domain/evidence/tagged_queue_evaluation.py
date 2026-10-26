"""Independent source/allocation/lifecycle audit of inclusive tagged reconstruction.

No native imports or runtime queue implementation are used. Public total depth
includes the tagged quantity; cleanup is after the valuation horizon. Truth is
conditional on this frozen model and is never a verdict on the source claim.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from tickwitness.domain.evidence.evaluation import (
    EvaluationValidationError, _decimal, _equal, _expected_input, _fees_by_mode,
    _money, _number, _Profile, _require,
)
from tickwitness.domain.replay._validation import (
    ReplayValidationError, canonical, digest, exact, identity, integer, parse,
)
from tickwitness.domain.replay.contracts import ReplayEvent, _source_ref
from tickwitness.domain.replay.tagged_queue_contracts import (
    ENGINE, TaggedQueueReplayInput, TaggedQueueReplayResult, load_tagged_queue_replay_result,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS

Row = dict[str, object]
_LIMIT = 64 * 1024
_AUDIT = "tagged_source_conserved_allocation_margin_audit_v1"
_SCOPE: Row = {
    "observation_scope": "finite_path_conditional_tagged_reconstruction",
    "source_claim_evaluated": False, "historical_owner_verified": False,
    "literal_order_insertion": False, "market_impact_verified": False, "finding_issued": False,
}


def _rows(document: Row, channel: str) -> list[Row]:
    return cast("list[Row]", document[channel])


def _fields(row: Row) -> Row:
    return cast("Row", row["fields"])


def _state(a: int, r: int, b: int, f: int) -> Row:
    _require(min(a, r, b, f) >= 0, "Negative reconstructed tagged queue")
    return {"ahead_lots": a, "own_live_lots": r, "behind_lots": b,
            "external_lots": a + b, "total_lots": a + r + b, "own_filled_lots": f}


class _TaggedAudit:
    def __init__(self, supplied: TaggedQueueReplayInput, result: TaggedQueueReplayResult) -> None:
        self.input = TaggedQueueReplayInput(supplied.protocol, supplied.normalized_bytes, supplied.policy_id)
        self.result = load_tagged_queue_replay_result(result.canonical_bytes)
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
        self.final_state: Row = {}
        self.mark: Row = {}

    def event(self, row: Row) -> ReplayEvent:
        ref = row["source_ref"]
        _require(isinstance(ref, dict), "Tagged callback requires actual source context")
        event = self.by_line.get(cast("int", cast("Row", ref).get("line")))
        _require(event is not None, "Unknown tagged callback source")
        assert event is not None
        _equal(ref, event.source_ref, "Tagged callback differs from sealed source")
        if "native_time_ns" in row:
            _equal(row["native_time_ns"], event.receive_time_ns, "Tagged native clock differs")
        return event

    def inputs(self) -> None:
        _equal(self.document["bindings"], self.input.bindings, "Tagged result binding mismatch")
        _equal(self.document["engine"], ENGINE, "Tagged engine semantic mismatch")
        env = cast("Row", self.document["environment"])
        _equal(cast("Row", env["package_versions"]).get("nautilus_trader"), "1.231.0", "Wrong native dependency")
        complete = cast("Row", self.document["completeness"])
        _equal([complete["input_records"], complete["processed_records"]],
               [len(self.events)] * 2, "Tagged result omits input")
        bids: dict[int, int] = {}
        asks: dict[int, int] = {}
        inputs = _rows(self.document, "input_trace")
        _equal(len(inputs), len(self.events), "Tagged input count differs")
        mark_ref: Row | None = None
        for event, row in zip(self.events, inputs, strict=True):
            _equal([row["kind"], row["phase"]], ["input_processed", "observed_window"], "Wrong tagged input phase")
            _equal(self.event(row).source_ref, event.source_ref, "Tagged source order differs")
            _equal(_fields(row), _expected_input(event), "Tagged input rewrites source")
            if event.event_type != "trade":
                for book, changes in ((bids, event.bids), (asks, event.asks)):
                    for price, quantity in changes:
                        if quantity:
                            book[price] = quantity
                        else:
                            _require(price in book, "Tagged source deletes absent level")
                            del book[price]
                mark_ref = event.source_ref
            self.book_counts[event.line] = len(bids), len(asks)
        _require(bool(bids) and mark_ref is not None, "No final visible bid for tagged mark")
        best = max(bids)
        self.mark = {"source_ref": mark_ref, "price_ticks": best, "available_quantity_lots": bids[best]}
        for channel in ("decision_trace", "order_trace", "fill_trace"):
            previous = 0
            for row in _rows(self.document, channel):
                event = self.event(row)
                _require(event.line >= previous, "Tagged callbacks run backwards")
                previous = event.line

    def decisions(self) -> None:
        rows = _rows(self.document, "decision_trace")
        _require(1 <= len(rows) <= 2, "Tagged replay requires a single represented order")
        for ordinal, row in enumerate(rows):
            fields, event = _fields(row), self.event(row)
            if ordinal == 0:
                self.order_id = cast("str", fields.get("order_id"))
                _require(isinstance(self.order_id, str) and bool(self.order_id), "Missing tagged order ID")
            _equal(row["kind"], "command_issued", "Unsupported tagged decision")
            _equal(event.line, 1 if ordinal == 0 else len(self.events), "Tagged command outside entry/cleanup")
            _equal(row["phase"], "observed_window" if ordinal == 0 else "post_horizon_cleanup", "Tagged command phase differs")
            _equal(fields, {
                "decision_ref": f"decision-{ordinal}", "command_id": f"command-{ordinal}",
                "action": "submit" if ordinal == 0 else "cancel", "order_id": self.order_id,
                "strategy_kind": "tagged_passive_order_at_entry_v1", "limit_price_ticks": self.profile.limit,
                "quantity_lots": self.profile.requested, "post_only": True,
                "cause": "entry_tag_representation" if ordinal == 0 else "post_horizon_cleanup",
            }, "Tagged decision differs from frozen intervention")

    def fills(self) -> None:
        ids: set[str] = set()
        for row in _rows(self.document, "fill_trace"):
            event, fields = self.event(row), _fields(row)
            _equal([row["kind"], row["phase"]], ["OrderFilled", "observed_window"], "Fill outside observed window")
            _equal(fields["order_id"], self.order_id, "Tagged fill switches order")
            trade_id = cast("str", fields["native_trade_id"])
            _require(trade_id not in ids, "Duplicate tagged native fill")
            ids.add(trade_id)
            _require(event.event_type == "trade" and event.aggressor_side == "sell", "Fill lacks aggressor source trade")
            _equal(event.price_ticks, self.profile.limit, "Fill source trade price differs")
            lots = integer(fields["quantity_lots"], "fill lots", 1)
            _equal(fields["price_ticks"], self.profile.limit, "Tagged fill differs from limit")
            price, quantity = self.profile.limit * self.profile.price_increment, lots * self.profile.size_increment
            _require(_number(fields["price"], "fill price") == price, "Tagged fill price unit differs")
            _require(_number(fields["quantity"], "fill quantity") == quantity, "Tagged fill size unit differs")
            _equal([fields["commission_currency"], fields["liquidity_side"]], ["USD", "MAKER"], "Tagged fee profile differs")
            fee = _money(fields["commission"], "tagged fee", nonnegative=True)
            modes = _fees_by_mode(price, quantity, self.profile.maker)
            self.compatible_modes.intersection_update(mode for mode, value in modes.items() if value == fee)
            _require(bool(self.compatible_modes), "Tagged native fee violates pinned rounding model")
            if len(set(modes.values())) != 1:
                self.ambiguous.append(cast("int", row["ordinal"]))
            self.quantity += lots
            self.commission += fee
            _require(self.quantity <= self.profile.requested, "Tagged fills exceed quantity")
            self.prefixes.append((self.quantity, self.commission))
            self.fills_by_line[event.line] = self.fills_by_line.get(event.line, 0) + lots
        _equal(len(_rows(self.document, "decision_trace")), 1 if self.quantity == self.profile.requested else 2,
               "Missing cleanup or cancellation after full fill")

    def queues(self) -> None:
        # Reconstruct independently of the runtime and the pure witness implementation.
        a = dict(self.events[0].bids)[self.profile.limit] - self.profile.requested
        r, b, f = self.profile.requested, 0, 0
        updates = {cast("int", row["capture_seq"]): row for row in
                   cast("list[Row]", self.input.protocol.constraint.document["updates"])}
        hooks: dict[int, list[Row]] = {}
        previous = 0
        for hook in _rows(self.document, "hook_trace"):
            event = self.event(hook)
            _require(event.line >= previous, "Tagged hooks run backwards")
            previous = event.line
            _equal(hook["origin"], "native_public_fill_simulation_hook", "Unknown tagged hook")
            # Cleanup hooks can observe a book, but have no execution capacity.
            _require(hook["phase"] in ("observed_window", "post_horizon_cleanup"), "Wrong hook phase")
            if hook["phase"] == "post_horizon_cleanup":
                _equal(event.line, len(self.events), "Cleanup hook before claim horizon")
            hooks.setdefault(event.line, []).append(hook)
        _equal(len(_rows(self.document, "queue_trace")), len(self.events), "Missing tagged queue step")
        for event, row in zip(self.events, _rows(self.document, "queue_trace"), strict=True):
            before = None if event.line == 1 else _state(a, r, b, f)
            flow: Row = {key: 0 for key in ("additions_lots", "cancellations_lots", "trade_lots",
                "cancel_ahead_lots", "cancel_behind_lots", "external_trade_ahead_lots", "own_trade_lots", "external_trade_behind_lots")}
            observed: int | None = None
            kind = "entry" if event.line == 1 else "unrelated"
            own_fill = 0
            if event.line == 1:
                observed = a + r
            elif event.event_type == "trade":
                t = cast("int", event.quantity_lots)
                _require(t <= a + r + b, "Trade exceeds tagged total")
                ta = min(t, a)
                own_fill = min(t - ta, r)
                tb = t - ta - own_fill
                a, r, b, f = a - ta, r - own_fill, b - tb, f + own_fill
                flow.update(trade_lots=t, external_trade_ahead_lots=ta, own_trade_lots=own_fill, external_trade_behind_lots=tb)
                kind = "trade"
            elif event.capture_seq in updates:
                update = updates[event.capture_seq]
                added, canceled = cast("int", update["additions_lots"]), cast("int", update["cancellations_lots"])
                b += added
                _require(canceled <= a + b, "Cancellation consumes protected tagged quantity")
                if self.input.policy_id == TAGGED_POLICY_IDS[0]:
                    ca, cb = min(canceled, a), max(0, canceled - a)
                else:
                    cb, ca = min(canceled, b), max(0, canceled - b)
                a, b = a - ca, b - cb
                flow.update(additions_lots=added, cancellations_lots=canceled, cancel_ahead_lots=ca, cancel_behind_lots=cb)
                observed = dict(event.bids)[self.profile.limit]
                kind = "checkpoint"
            after = _state(a, r, b, f)
            _equal(r + f, self.profile.requested, "Tagged quantity created or canceled before horizon")
            if observed is not None:
                _equal(a + r + b, observed, "Tagged projection violates observed total")
            granted = 0
            for hook in hooks.get(event.line, []):
                offered = integer(hook["offered_lots"], "hook grant")
                _require(offered <= own_fill - granted, "Trade capacity reused by native hook")
                if hook["phase"] == "post_horizon_cleanup":
                    _equal(offered, 0, "Cleanup granted execution capacity")
                granted += offered
                _equal(hook["cumulative_granted_lots"], granted, "Tagged cumulative grant differs")
            actual = self.fills_by_line.get(event.line, 0)
            _equal([granted, actual], [own_fill, own_fill], "Tagged native grant/fill omits or exceeds single allocation")
            _equal(row, {"kind": kind, "source_ref": event.source_ref, "receive_time_ns": event.receive_time_ns,
                "before": before, "flow": flow, "after": after, "observed_total_lots": observed,
                "own_fill_grant_lots": own_fill, "granted_lots": granted,
                "native_filled_lots": actual, "accepted_here": event.line == 1}, "Tagged allocation differs from independent reconstruction")
        self.final_state = _state(a, r, b, f)
        horizon = cast("Row", self.document["horizon_snapshot"])
        _equal({key: value for key, value in horizon.items() if key != "account"}, {
            "source_ref": self.events[-1].source_ref, "native_time_ns": self.events[-1].receive_time_ns,
            "queue_state": self.final_state, "native_target_lots": a + r + b, "mark": self.mark,
        }, "Native precleanup horizon differs from actual source/reconstruction")
        _equal(self.document["cleanup"], {
            "canceled_own_lots": r, "projected_total_after_cleanup": a + b,
            "projected_external_after_cleanup": a + b, "own_live_after_cleanup": 0,
            "native_status": "FILLED" if r == 0 else "CANCELED", "native_unfilled_lots": r,
            "book_role": "recorded_observation_cache",
        }, "Cleanup confuses cached observed depth, live order or native leaves")

    def orders(self) -> str:
        rows = _rows(self.document, "order_trace")
        _require(bool(rows), "Missing tagged native lifecycle")
        seen: set[str] = set()
        pending = ["command-0"]
        status: object = None
        fill_index, cumulative = 0, 0
        for row in rows:
            event, fields, kind = self.event(row), _fields(row), cast("str", row["kind"])
            cleanup = kind in ("OrderPendingCancel", "OrderCanceled")
            _equal(row["phase"], "post_horizon_cleanup" if cleanup else "observed_window", "Order lifecycle phase differs")
            _equal(fields["event_type"], kind, "Tagged lifecycle kind differs")
            _equal(fields["order_id"], self.order_id, "Tagged lifecycle switches order")
            _require(status not in ("FILLED", "CANCELED", "REJECTED", "DENIED"), "Lifecycle after terminal tagged receipt")
            if kind != "OrderFilled":
                _require(kind not in seen, "Duplicate tagged lifecycle event")
                seen.add(kind)
            if kind == "OrderInitialized":
                _require(row["ordinal"] == 0 and event.line == 1, "Tagged order must initialize at entry")
                status = fields["status"]
                _require(status in (None, "INITIALIZED"), "Invalid initialized tagged status")
            elif kind == "OrderSubmitted":
                _require("OrderInitialized" in seen and event.line == 1, "Tagged submit lacks entry initialization")
                status = "SUBMITTED"
            elif kind == "OrderAccepted":
                _require("OrderSubmitted" in seen and event.line == 1, "Tagged acceptance lacks entry submit")
                initial = cast("Row", _rows(self.document, "queue_trace")[0]["after"])
                _equal(fields["actual_acceptance"], {"native_bid_lots": initial["total_lots"],
                    "queue": initial, "target_price_ticks": self.profile.limit,
                    "acceptance_role": "tagged_reconstruction_proxy"}, "Acceptance differs from inclusive entry proxy")
                pending.remove("command-0")
                status = "ACCEPTED"
            elif kind == "OrderFilled":
                _require("OrderAccepted" in seen, "Tagged fill before acceptance")
                fills = _rows(self.document, "fill_trace")
                _require(fill_index < len(fills), "Tagged lifecycle invents fill")
                _equal(row["source_ref"], fills[fill_index]["source_ref"], "Tagged fill lifecycle source differs")
                cumulative = self.prefixes[fill_index][0]
                fill_index += 1
                status = "FILLED" if cumulative == self.profile.requested else "PARTIALLY_FILLED"
            elif kind == "OrderPendingCancel":
                _require("OrderAccepted" in seen and len(_rows(self.document, "decision_trace")) == 2,
                         "Tagged cancel has no accepted command")
                _equal(event.line, len(self.events), "Cancellation before claim horizon")
                pending.append("command-1")
                status = "PENDING_CANCEL"
            elif kind == "OrderCanceled":
                _require("command-1" in pending, "Tagged cancel lacks pending command")
                _equal(event.line, len(self.events), "Cancel receipt outside posthorizon cleanup")
                pending.remove("command-1")
                status = "CANCELED"
            else:
                raise EvaluationValidationError("Unsupported/rejected tagged lifecycle")
            _equal(fields["status"], status, "Tagged lifecycle status differs")
            _equal(fields["pending_commands"], pending, "Tagged pending acknowledgements differ")
            if kind != "OrderAccepted":
                _equal(fields["actual_acceptance"], None, "Unexpected tagged acceptance evidence")
            for key, expected in (("quantity_lots", self.profile.requested), ("filled_quantity_lots", cumulative),
                                  ("remaining_quantity_lots", self.profile.requested - cumulative)):
                _equal(fields[key], None if kind == "OrderInitialized" and status is None else expected,
                       "Tagged native leaves differ from actual fills")
        _require("OrderAccepted" in seen, "No actual tagged acceptance")
        _equal(fill_index, len(self.prefixes), "Tagged fill lacks order callback")
        final = "FILLED" if self.quantity == self.profile.requested else "CANCELED"
        _equal(status, final, "No terminal tagged native receipt")
        complete = cast("Row", self.document["completeness"])
        _equal([complete["pending_commands"], complete["open_orders"], self.document["execution_status"]],
               [[], [], "completed"], "Tagged execution remains incomplete")
        return final

    def accounts(self, final_status: str) -> None:
        rows, fills = _rows(self.document, "account_trace"), _rows(self.document, "fill_trace")
        _equal([row["kind"] for row in rows], ["initial_account_snapshot"] +
               ["fill_callback_account_snapshot"] * len(fills) + ["horizon_account_snapshot", "final_account_snapshot"],
               "Missing tagged account boundaries")
        for index, row in enumerate(rows):
            fields = _fields(row)
            initial, horizon, final = index == 0, index == len(rows) - 2, index == len(rows) - 1
            quantity, fees = (0, Fraction(0)) if initial else (self.quantity, self.commission) if horizon or final else self.prefixes[index - 1]
            phase = "bootstrap" if initial else "claim_horizon" if horizon else "post_horizon_cleanup" if final else "observed_window"
            _equal(row["phase"], phase, "Tagged account phase differs")
            if initial or final:
                _equal(row["source_ref"], None, "Boundary account unexpectedly source-contextual")
                _equal(row["native_time_ns"], self.events[0 if initial else -1].receive_time_ns, "Boundary account clock differs")
            else:
                event = self.event(row)
                _equal(event.source_ref, self.events[-1].source_ref if horizon else fills[index - 1]["source_ref"], "Tagged account source differs")
            for key, expected in (("account_type", "MARGIN"), ("oms_type", "NETTING"), ("currency", "USD"),
                ("native_money_precision", 2), ("money_rounding_policy", "native_v1_f64_notional_then_USD_Money_precision_2"),
                ("cash_semantics", "native_margin_balance_not_spot_notional_debit"), ("net_position_lots", quantity),
                ("observed_fill_lots", quantity), ("book_type", "L2_MBP"), ("book_role", "recorded_observation_cache")):
                _equal(fields[key], expected, "Tagged native account profile differs")
            _require(_money(fields["observed_commission"], "observed tagged fees", nonnegative=True) == fees,
                     "Account fees differ from actual tagged fills")
            total = _money(fields["cash_total"], "tagged cash")
            free = _money(fields["cash_free"], "tagged free cash")
            locked = _money(fields["cash_locked"], "tagged locked cash", nonnegative=True)
            _require(total == self.profile.cash - fees and free + locked == total, "Tagged margin cash mismatch")
            counts = fields["bid_levels"], fields["ask_levels"]
            if initial:
                _equal(counts, (0, 0), "Initial tagged book is not empty")
                _equal(fields["orders"], [], "Initial tagged account has order")
                _require(locked == 0 and free == self.profile.cash, "Initial tagged cash locked")
                continue
            event = self.events[-1] if horizon or final else self.event(row)
            choices = {self.book_counts[event.line]}
            if not (horizon or final) and event.line > 1:
                choices.add(self.book_counts[event.line - 1])
            _require(counts in choices, "Tagged cached book differs from adjacent actual source states")
            status = final_status if final else "FILLED" if quantity == self.profile.requested else "PARTIALLY_FILLED" if quantity else "ACCEPTED"
            _equal(fields["orders"], [{"order_id": self.order_id, "status": status,
                "quantity_lots": self.profile.requested, "filled_quantity_lots": quantity,
                "remaining_quantity_lots": self.profile.requested - quantity}], "Tagged account order differs")
            if horizon:
                _equal(fields, cast("Row", self.document["horizon_snapshot"])["account"], "Horizon account copied from different phase")

    def run(self) -> Row:
        self.inputs()
        self.decisions()
        self.fills()
        self.queues()
        final = self.orders()
        self.accounts(final)
        claim = cast("Row", self.input.protocol.document["claim"])
        mark = cast("int", self.mark["price_ticks"]) * self.profile.price_increment
        pnl = self.quantity * self.profile.size_increment * (mark - self.profile.limit * self.profile.price_increment) - self.commission
        threshold = _number(claim["threshold"], "tagged threshold")
        comparator = claim["comparator"]
        truth = pnl > threshold if comparator == "gt" else pnl >= threshold if comparator == "ge" else pnl < threshold if comparator == "lt" else pnl <= threshold
        eligible = not self.ambiguous
        return {
            "kind": "tagged_queue_replay_evaluation_v1", "schema_version": 1, "audit_policy": _AUDIT,
            "bindings": self.input.bindings, "replay_result_sha256": digest(self.result.canonical_bytes),
            "scope": dict(_SCOPE), "status": "verified", "input_records": len(self.events),
            "filled_quantity_lots": self.quantity, "actual_commission": _decimal(self.commission),
            "final_cash_total": _decimal(self.profile.cash - self.commission), "final_order_status": final,
            "compatible_native_raw_modes": sorted(self.compatible_modes), "ambiguous_fee_fill_ordinals": self.ambiguous,
            "valuation": {"policy_id": self.input.protocol.document["evaluation_policy"], "eligible": eligible,
                "reason": None if eligible else "native_fee_rounding_ambiguous", "mark": self.mark,
                "net_marked_pnl": _decimal(pnl) if eligible else None, "unit": "USD",
                "interpretation": "conditional_tagged_inventory_mark_not_liquidation"},
            "claim_evaluation": {"claim_revision_id": self.input.protocol.claim_revision_id,
                "comparator": comparator, "threshold": claim["threshold"], "truth": truth if eligible else None},
            "findings": [],
        }


@dataclass(frozen=True, slots=True)
class TaggedQueueReplayEvaluation:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        doc = parse(self.canonical_bytes, _LIMIT)
        exact(doc, {"kind", "schema_version", "audit_policy", "bindings", "replay_result_sha256", "scope", "status",
            "input_records", "filled_quantity_lots", "actual_commission", "final_cash_total", "final_order_status",
            "compatible_native_raw_modes", "ambiguous_fee_fill_ordinals", "valuation", "claim_evaluation", "findings"}, "Tagged evaluation")
        _equal([doc["kind"], doc["schema_version"], doc["audit_policy"], doc["status"]],
               ["tagged_queue_replay_evaluation_v1", 1, _AUDIT, "verified"], "Unsupported tagged evaluation")
        _equal(doc["scope"], _SCOPE, "Tagged evaluation scope exceeds contract")
        _equal(doc["findings"], [], "Tagged evaluation cannot issue findings")
        bindings = exact(doc["bindings"], {"protocol_id", "claim_revision_id", "source_protocol_id", "dataset_id",
            "data_sha256", "spec_id", "gross_constraint_id", "policy_id"}, "Tagged evaluation bindings")
        for key, value in bindings.items():
            if key != "policy_id":
                identity(value, key)
        _require(bindings["policy_id"] in TAGGED_POLICY_IDS, "Unknown tagged policy")
        identity(doc["replay_result_sha256"], "result hash")
        integer(doc["input_records"], "input_records", 1, 1000)
        integer(doc["filled_quantity_lots"], "filled lots")
        _money(doc["actual_commission"], "actual tagged fees", nonnegative=True)
        _money(doc["final_cash_total"], "final tagged cash")
        _require(doc["final_order_status"] in ("FILLED", "CANCELED"), "Tagged order is not terminal")
        _require(doc["compatible_native_raw_modes"] in ([9], [16], [9, 16]), "Invalid tagged money modes")
        ambiguities = doc["ambiguous_fee_fill_ordinals"]
        _require(isinstance(ambiguities, list), "Ambiguous fee ordinals must be a list")
        assert isinstance(ambiguities, list)
        previous = -1
        for ordinal in ambiguities:
            previous = integer(ordinal, "ambiguous fee ordinal", previous + 1,
                               cast("int", doc["filled_quantity_lots"]) - 1)
        valuation = exact(doc["valuation"], {"policy_id", "eligible", "reason", "mark",
            "net_marked_pnl", "unit", "interpretation"}, "Tagged valuation")
        _equal([valuation["policy_id"], valuation["unit"], valuation["interpretation"]],
               ["tagged_inventory_final_visible_bid_flat_zero_v1", "USD",
                "conditional_tagged_inventory_mark_not_liquidation"], "Unsupported tagged valuation policy")
        _require(type(valuation["eligible"]) is bool, "Tagged valuation eligibility must be boolean")
        eligible = not ambiguities
        _equal(valuation["eligible"], eligible, "Tagged valuation ignores ambiguous native fees")
        mark = exact(valuation["mark"], {"source_ref", "price_ticks", "available_quantity_lots"}, "Tagged valuation mark")
        _source_ref(mark["source_ref"])
        integer(mark["price_ticks"], "tagged mark price", 1)
        integer(mark["available_quantity_lots"], "tagged mark depth", 1)
        claim = exact(doc["claim_evaluation"], {"claim_revision_id", "comparator", "threshold", "truth"}, "Tagged claim evaluation")
        _equal(claim["claim_revision_id"], bindings["claim_revision_id"], "Tagged claim revision differs from bindings")
        comparator = claim["comparator"]
        _require(comparator in ("gt", "ge", "lt", "le"), "Unsupported tagged claim comparator")
        threshold = _number(claim["threshold"], "tagged claim threshold")
        _equal(claim["threshold"], _decimal(threshold), "Noncanonical tagged threshold")
        if eligible:
            _equal(valuation["reason"], None, "Eligible tagged valuation has exclusion reason")
            pnl = _number(valuation["net_marked_pnl"], "tagged net marked PnL")
            _equal(valuation["net_marked_pnl"], _decimal(pnl), "Noncanonical tagged marked PnL")
            _require(type(claim["truth"]) is bool, "Eligible tagged truth must be boolean")
            truth = pnl > threshold if comparator == "gt" else pnl >= threshold if comparator == "ge" else pnl < threshold if comparator == "lt" else pnl <= threshold
            _equal(claim["truth"], truth, "Tagged claim truth differs from its valuation")
        else:
            _equal([valuation["reason"], valuation["net_marked_pnl"], claim["truth"]],
                   ["native_fee_rounding_ambiguous", None, None], "Ambiguous tagged valuation must withhold truth")
        _require(canonical(doc) == self.canonical_bytes, "Noncanonical tagged evaluation")

    @property
    def evaluation_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, _LIMIT)


def evaluate_tagged_queue_replay(replay_input: TaggedQueueReplayInput, result: TaggedQueueReplayResult) -> TaggedQueueReplayEvaluation:
    try:
        return TaggedQueueReplayEvaluation(canonical(_TaggedAudit(replay_input, result).run()))
    except ReplayValidationError as error:
        raise EvaluationValidationError(str(error)) from error


def load_tagged_queue_evaluation(raw: bytes) -> TaggedQueueReplayEvaluation:
    try:
        return TaggedQueueReplayEvaluation(raw)
    except ReplayValidationError as error:
        raise EvaluationValidationError(str(error)) from error
