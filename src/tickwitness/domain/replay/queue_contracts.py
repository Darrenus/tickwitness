"""Native-free inputs and bounded evidence for the separate queue execution profile."""

from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.domain.assumptions.queue_constraints import QueueFeasibilityPair
from tickwitness.domain.replay._validation import (
    MAX_RESULT_BYTES,
    ReplayValidationError,
    canonical,
    decimal,
    exact,
    identity,
    integer,
    parse,
    text,
)
from tickwitness.domain.replay.contracts import (
    PreparedReplay,
    ReplayInput,
    _json_values,
    _source_ref,
)
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import load_replay_spec
from tickwitness.domain.research_contracts.queue_family import (
    QUEUE_ENGINE_SEMANTIC_ID,
    QUEUE_POLICY_IDS,
    QueueFamilyProtocol,
    QueueFamilyValidationError,
    load_queue_family_protocol,
    validate_queue_family_input,
)

TRACE_CHANNELS = ("input_trace", "decision_trace", "order_trace", "fill_trace", "account_trace")
ENGINE = {
    "id": "nautilus-trader",
    "version": "1.231.0",
    "semantic_id": QUEUE_ENGINE_SEMANTIC_ID,
}


@dataclass(frozen=True, slots=True)
class QueueReplayInput:
    family: QueueFamilyProtocol
    normalized_bytes: bytes
    policy_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.family, QueueFamilyProtocol):
            raise ReplayValidationError("Queue replay requires an immutable queue family")
        try:
            checked = load_queue_family_protocol(self.family.canonical_bytes)
            if checked.protocol_id != self.family.protocol_id:
                raise ReplayValidationError("Queue family identity mismatch")
            if self.policy_id not in QUEUE_POLICY_IDS:
                raise ReplayValidationError("Queue replay policy is not a frozen family member")
            validate_queue_family_input(checked, self.replay_input)
        except QueueFamilyValidationError as error:
            raise ReplayValidationError(str(error)) from error

    @property
    def family_id(self) -> str:
        return self.family.protocol_id

    @property
    def replay_input(self) -> ReplayInput:
        source = self.family.source_protocol.document
        bindings = cast("dict[str, str]", self.family.document["bindings"])
        spec = load_replay_spec(canonical(cast("dict[str, object]", source["replay_spec"])))
        return ReplayInput(bindings["development_dataset_id"], self.normalized_bytes, spec)

    @property
    def prepared(self) -> PreparedReplay:
        return preflight_replay(self.replay_input)

    @property
    def feasibility(self) -> QueueFeasibilityPair:
        return validate_queue_family_input(self.family, self.replay_input)

    @property
    def bindings(self) -> dict[str, str]:
        prepared = self.prepared
        return {
            "family_id": self.family_id,
            "source_protocol_id": self.family.source_protocol.protocol_id,
            "dataset_id": prepared.dataset_id,
            "data_sha256": prepared.data_sha256,
            "spec_id": prepared.spec.spec_id,
            "constraint_id": self.family.constraint.constraint_id,
            "policy_id": self.policy_id,
        }


class QueueReplayPort(Protocol):
    def run(self, replay_input: QueueReplayInput) -> "QueueReplayResult": ...


def _rows(value: object, label: str) -> list[object]:
    if not isinstance(value, list) or len(value) > 50_000:
        raise ReplayValidationError(f"{label} must be a bounded list")
    return value


def _queue(value: object, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    state = exact(value, {"ahead_lots", "behind_lots", "external_lots"}, "queue state")
    for key, item in state.items():
        integer(item, key)


def _order(value: object) -> None:
    row = exact(
        value,
        {"order_id", "status", "quantity_lots", "filled_quantity_lots", "remaining_quantity_lots"},
        "native order",
    )
    text(row["order_id"], "order_id")
    text(row["status"], "order status")
    for key in ("quantity_lots", "filled_quantity_lots", "remaining_quantity_lots"):
        integer(row[key], key)


def _fields(channel: str, value: object) -> None:
    if not isinstance(value, dict):
        raise ReplayValidationError("Queue trace fields must be an object")
    _json_values(value)
    if channel == "input_trace":
        exact(
            value,
            {
                "event_time_ns",
                "receive_time_ns",
                "native_ts_event_ns",
                "native_ts_init_ns",
                "clock_policy_id",
                "source_clock_certified",
                "source_sequence_first",
                "source_sequence_last",
                "source_trade_id",
                "native_internal_id",
                "native_id_policy",
                "bids",
                "asks",
                "price_ticks",
                "quantity_lots",
                "aggressor_side",
                "source_ref_semantics",
            },
            "queue input fields",
        )
    elif channel == "decision_trace":
        exact(
            value,
            {
                "decision_ref",
                "command_id",
                "action",
                "order_id",
                "strategy_kind",
                "limit_price_ticks",
                "quantity_lots",
                "post_only",
                "cause",
            },
            "queue decision fields",
        )
    elif channel == "fill_trace":
        row = exact(
            value,
            {
                "order_id",
                "native_trade_id",
                "price_ticks",
                "quantity_lots",
                "price",
                "quantity",
                "commission",
                "commission_currency",
                "liquidity_side",
            },
            "queue fill fields",
        )
        for key in ("order_id", "native_trade_id", "commission_currency", "liquidity_side"):
            text(row[key], key)
        for key in ("price_ticks", "quantity_lots"):
            integer(row[key], key, 1)
        for key in ("price", "quantity", "commission"):
            decimal(row[key], key, precision=18)
    elif channel == "order_trace":
        row = exact(
            value,
            {
                "order_id",
                "event_type",
                "status",
                "quantity_lots",
                "filled_quantity_lots",
                "remaining_quantity_lots",
                "pending_commands",
                "actual_acceptance",
            },
            "queue order fields",
        )
        text(row["order_id"], "order_id")
        text(row["event_type"], "event_type")
        if row["status"] is not None:
            text(row["status"], "order status")
        for key in ("quantity_lots", "filled_quantity_lots", "remaining_quantity_lots"):
            if row[key] is not None:
                integer(row[key], key)
        for item in _rows(row["pending_commands"], "pending command IDs"):
            text(item, "pending command ID")
        if row["actual_acceptance"] is not None:
            accepted = exact(
                row["actual_acceptance"],
                {"native_bid_lots", "queue", "target_price_ticks"},
                "actual acceptance",
            )
            integer(accepted["native_bid_lots"], "native_bid_lots")
            integer(accepted["target_price_ticks"], "target_price_ticks", 1)
            _queue(accepted["queue"])
    elif channel == "account_trace":
        row = exact(
            value,
            {
                "account_type",
                "oms_type",
                "currency",
                "cash_total",
                "cash_free",
                "cash_locked",
                "net_position_lots",
                "observed_fill_lots",
                "observed_commission",
                "native_money_precision",
                "money_rounding_policy",
                "cash_semantics",
                "book_type",
                "bid_levels",
                "ask_levels",
                "orders",
            },
            "queue account fields",
        )
        for key in ("cash_total", "cash_free", "cash_locked", "observed_commission"):
            decimal(row[key], key, precision=18)
        for key in (
            "net_position_lots",
            "observed_fill_lots",
            "native_money_precision",
            "bid_levels",
            "ask_levels",
        ):
            integer(row[key], key)
        for item in _rows(row["orders"], "account orders"):
            _order(item)


def _result(document: dict[str, object]) -> None:
    exact(
        document,
        {
            "kind",
            "schema_version",
            "bindings",
            "engine",
            "environment",
            "execution_status",
            "completeness",
            *TRACE_CHANNELS,
            "queue_trace",
            "hook_trace",
        },
        "QueueReplayResult",
    )
    if document["kind"] != "queue_replay_result_v1":
        raise ReplayValidationError("Unsupported queue replay result kind")
    integer(document["schema_version"], "schema_version", 1, 1)
    bindings = exact(
        document["bindings"],
        {
            "family_id",
            "source_protocol_id",
            "dataset_id",
            "data_sha256",
            "spec_id",
            "constraint_id",
            "policy_id",
        },
        "queue result bindings",
    )
    for key, value in bindings.items():
        if key != "policy_id":
            identity(value, key)
    if bindings["policy_id"] not in QUEUE_POLICY_IDS:
        raise ReplayValidationError("Queue result requires a frozen policy")
    if canonical({"engine": document["engine"]}) != canonical({"engine": ENGINE}):
        raise ReplayValidationError("Queue result engine identity differs")
    environment = exact(
        document["environment"], {"python_version", "platform", "package_versions"}, "environment"
    )
    text(environment["python_version"], "python_version")
    text(environment["platform"], "platform", 512)
    packages = environment["package_versions"]
    if not isinstance(packages, dict) or not 1 <= len(packages) <= 128:
        raise ReplayValidationError("Queue result must bind dependency versions")
    for key, value in packages.items():
        text(key, "package name")
        text(value, "package version")
    completeness = exact(
        document["completeness"],
        {"input_records", "processed_records", "open_orders", "pending_commands", "stop_reason"},
        "queue completeness",
    )
    count = integer(completeness["input_records"], "input_records", 1, 1000)
    processed = integer(completeness["processed_records"], "processed_records", 0, count)
    for order in _rows(completeness["open_orders"], "open orders"):
        row = exact(order, {"order_id", "status"}, "open order")
        text(row["order_id"], "order_id")
        text(row["status"], "order status")
    references: list[bytes] = []
    pending = _rows(completeness["pending_commands"], "pending commands")
    for item in pending:
        row = exact(
            item,
            {"command_id", "order_id", "command_type", "decision_ref", "source_ref"},
            "pending command",
        )
        for key in ("command_id", "order_id", "decision_ref"):
            text(row[key], key)
        if row["command_type"] not in ("submit", "cancel"):
            raise ReplayValidationError("Unsupported queue command")
        references.append(canonical(cast("dict[str, object]", _source_ref(row["source_ref"]))))
    reason = completeness["stop_reason"]
    open_orders = completeness["open_orders"]
    valid = processed == count and (
        (
            document["execution_status"] == "completed"
            and not pending
            and not open_orders
            and reason == "input_exhausted"
        )
        or (
            document["execution_status"] == "incomplete"
            and (
                (bool(pending) and reason == "pending_commands_at_data_end")
                or (
                    not pending
                    and bool(open_orders)
                    and reason == "input_exhausted_with_open_orders"
                )
            )
        )
    )
    if not valid:
        raise ReplayValidationError("Queue execution status and completeness disagree")
    inputs: set[bytes] = set()
    previous_capture = 0
    for channel in TRACE_CHANNELS:
        rows = _rows(document[channel], channel)
        if channel == "input_trace" and len(rows) != processed:
            raise ReplayValidationError("Queue input trace omits a processed input")
        for ordinal, item in enumerate(rows):
            row = exact(
                item, {"kind", "ordinal", "native_time_ns", "source_ref", "fields"}, channel
            )
            text(row["kind"], "trace kind")
            integer(row["ordinal"], "ordinal", ordinal, ordinal)
            integer(row["native_time_ns"], "native_time_ns")
            ref = _source_ref(row["source_ref"], nullable=channel != "input_trace")
            if ref is not None:
                encoded = canonical(ref)
                if channel == "input_trace":
                    capture = integer(ref["capture_seq"], "capture_seq", previous_capture + 1)
                    if ref["line"] != ordinal + 1:
                        raise ReplayValidationError("Queue input trace line order differs")
                    inputs.add(encoded)
                    previous_capture = capture
                else:
                    references.append(encoded)
            _fields(channel, row["fields"])
    queue_rows = _rows(document["queue_trace"], "queue_trace")
    if len(queue_rows) != processed:
        raise ReplayValidationError("Queue trace must represent every processed source input")
    for item in queue_rows:
        row = exact(
            item,
            {
                "source_ref",
                "receive_time_ns",
                "market_observed_lots",
                "before",
                "after",
                "flow",
                "grant_limit_lots",
                "granted_lots",
                "native_filled_lots",
                "own_remaining_lots",
                "accepted_here",
            },
            "queue row",
        )
        references.append(canonical(cast("dict[str, object]", _source_ref(row["source_ref"]))))
        _queue(row["before"], nullable=True)
        _queue(row["after"], nullable=True)
        for key in (
            "receive_time_ns",
            "market_observed_lots",
            "grant_limit_lots",
            "granted_lots",
            "native_filled_lots",
            "own_remaining_lots",
        ):
            integer(row[key], key)
        if type(row["accepted_here"]) is not bool:
            raise ReplayValidationError("accepted_here must be a boolean")
        flow = exact(
            row["flow"],
            {
                "additions_lots",
                "cancellations_lots",
                "trade_lots",
                "cancel_ahead_lots",
                "cancel_behind_lots",
            },
            "queue flow",
        )
        for key, value in flow.items():
            integer(value, key)
    for item in _rows(document["hook_trace"], "hook_trace"):
        row = exact(
            item, {"source_ref", "origin", "offered_lots", "cumulative_granted_lots"}, "queue hook"
        )
        references.append(canonical(cast("dict[str, object]", _source_ref(row["source_ref"]))))
        text(row["origin"], "hook origin")
        integer(row["offered_lots"], "offered_lots")
        integer(row["cumulative_granted_lots"], "cumulative_granted_lots")
    if any(reference not in inputs for reference in references):
        raise ReplayValidationError("Queue evidence refers to an unprocessed input")


@dataclass(frozen=True, slots=True)
class QueueReplayResult:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        document = parse(self.canonical_bytes, MAX_RESULT_BYTES)
        _result(document)
        if canonical(document) != self.canonical_bytes:
            raise ReplayValidationError("Queue result requires exact canonical JSON")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, MAX_RESULT_BYTES)


def load_queue_replay_result(raw: bytes) -> QueueReplayResult:
    return QueueReplayResult(raw)


def build_queue_replay_result(document: dict[str, object]) -> QueueReplayResult:
    _result(document)
    return QueueReplayResult(canonical(document))
