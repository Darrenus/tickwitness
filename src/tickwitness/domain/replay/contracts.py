"""Native-free immutable replay input/output and the engine port."""

from dataclasses import dataclass
from typing import Protocol

from tickwitness.domain.replay._validation import (
    MAX_DATA_BYTES,
    MAX_EVENTS,
    MAX_RESULT_BYTES,
    ReplayValidationError,
    canonical,
    digest,
    exact,
    identity,
    integer,
    parse,
    text,
)
from tickwitness.domain.replay.specs import ReplaySpec

TRACE_CHANNELS = ("input_trace", "decision_trace", "order_trace", "fill_trace", "account_trace")


@dataclass(frozen=True, slots=True)
class ReplayInput:
    dataset_id: str
    normalized_bytes: bytes
    spec: ReplaySpec

    def __post_init__(self) -> None:
        identity(self.dataset_id, "dataset_id")
        if (
            not isinstance(self.normalized_bytes, bytes)
            or not 0 < len(self.normalized_bytes) <= MAX_DATA_BYTES
        ):
            raise ReplayValidationError("Replay input requires immutable bytes within 8 MiB")
        if not isinstance(self.spec, ReplaySpec):
            raise ReplayValidationError("Replay requires a ReplaySpec, never a FrozenProtocol")


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    line: int
    capture_seq: int
    event_type: str
    event_time_ns: int
    receive_time_ns: int
    last_sequence: int | None = None
    first_sequence: int | None = None
    bids: tuple[tuple[int, int], ...] = ()
    asks: tuple[tuple[int, int], ...] = ()
    trade_id: str | None = None
    price_ticks: int | None = None
    quantity_lots: int | None = None
    aggressor_side: str | None = None

    def __post_init__(self) -> None:
        for label in ("line", "capture_seq"):
            integer(getattr(self, label), label, 1)
        integer(self.event_time_ns, "event_time_ns")
        integer(self.receive_time_ns, "receive_time_ns")
        if self.event_type not in ("snapshot", "delta", "trade"):
            raise ReplayValidationError("Unsupported replay event type")
        for levels in (self.bids, self.asks):
            if type(levels) is not tuple or any(
                type(level) is not tuple or len(level) != 2 for level in levels
            ):
                raise ReplayValidationError("ReplayEvent levels must be immutable tuples")
            for price, quantity in levels:
                integer(price, "price_ticks", 1)
                integer(quantity, "quantity_lots")
        for label in ("last_sequence", "first_sequence"):
            value = getattr(self, label)
            if value is not None:
                integer(value, label)
        for label in ("price_ticks", "quantity_lots"):
            value = getattr(self, label)
            if value is not None:
                integer(value, label, 1)
        if self.trade_id is not None:
            text(self.trade_id, "trade_id", 256)
        if self.aggressor_side is not None and self.aggressor_side not in ("buy", "sell"):
            raise ReplayValidationError("Unsupported aggressor_side")

    @property
    def source_ref(self) -> dict[str, object]:
        return {"line": self.line, "capture_seq": self.capture_seq, "event_type": self.event_type}


@dataclass(frozen=True, slots=True)
class PreparedReplay:
    replay_input: ReplayInput
    spec: ReplaySpec
    dataset_id: str
    data_sha256: str
    stream: tuple[str, str, str]
    events: tuple[ReplayEvent, ...]

    def __post_init__(self) -> None:
        if type(self.events) is not tuple or any(
            not isinstance(event, ReplayEvent) for event in self.events
        ):
            raise ReplayValidationError("Prepared events must be immutable ReplayEvent tuples")
        if type(self.stream) is not tuple or len(self.stream) != 3:
            raise ReplayValidationError("Prepared stream must be an immutable three-part identity")
        for component in self.stream:
            text(component, "stream component", 256)
        if (
            not isinstance(self.replay_input, ReplayInput)
            or not isinstance(self.spec, ReplaySpec)
            or self.spec != self.replay_input.spec
        ):
            raise ReplayValidationError("Prepared replay must bind its immutable ReplayInput spec")
        if self.dataset_id != self.replay_input.dataset_id or self.data_sha256 != digest(
            self.replay_input.normalized_bytes
        ):
            raise ReplayValidationError("Prepared replay input identities do not match")


class ReplayPort(Protocol):
    def run(self, replay_input: ReplayInput) -> "ReplayResult": ...


def _source_ref(value: object, *, nullable: bool = False) -> dict[str, object] | None:
    if nullable and value is None:
        return None
    reference = exact(value, {"line", "capture_seq", "event_type"}, "source_ref")
    integer(reference["line"], "source_ref.line", 1, MAX_EVENTS)
    integer(reference["capture_seq"], "source_ref.capture_seq", 1)
    if reference["event_type"] not in ("snapshot", "delta", "trade"):
        raise ReplayValidationError("Invalid source_ref event type")
    return reference


def _json_values(value: object, depth: int = 0) -> None:
    if depth > 8:
        raise ReplayValidationError("Trace fields exceed bounded JSON nesting")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        integer(value, "trace integer", -(1 << 63))
        return
    if isinstance(value, str):
        if len(value) > 4_096:
            raise ReplayValidationError("Trace string exceeds 4096 characters")
        try:
            value.encode("utf-8")
        except UnicodeError as error:
            raise ReplayValidationError("Trace string has invalid Unicode") from error
        return
    if isinstance(value, dict) and len(value) <= 128:
        for key, item in value.items():
            text(key, "trace field name", 128)
            _json_values(item, depth + 1)
        return
    if isinstance(value, list) and len(value) <= MAX_EVENTS:
        for item in value:
            _json_values(item, depth + 1)
        return
    raise ReplayValidationError("Trace fields must be bounded JSON without floats")


def _result(document: dict[str, object]) -> None:
    exact(
        document,
        {
            "kind",
            "schema_version",
            "engine",
            "environment",
            "dataset_id",
            "data_sha256",
            "spec_id",
            "execution_status",
            "completeness",
            *TRACE_CHANNELS,
        },
        "ReplayResult",
    )
    integer(document["schema_version"], "schema_version", 1, 1)
    if document["kind"] != "replay_qualification_result_v1":
        raise ReplayValidationError("Unsupported replay result kind")
    for name in ("dataset_id", "data_sha256", "spec_id"):
        identity(document[name], name)
    engine = exact(document["engine"], {"id", "version", "semantic_id"}, "engine")
    for key, value in engine.items():
        text(value, "engine." + key, 256)
    environment = exact(
        document["environment"], {"python_version", "platform", "package_versions"}, "environment"
    )
    text(environment["python_version"], "python_version")
    text(environment["platform"], "platform", 512)
    packages = environment["package_versions"]
    if not isinstance(packages, dict) or not 1 <= len(packages) <= 128:
        raise ReplayValidationError("package_versions must bind at least one dependency version")
    for key, value in packages.items():
        text(key, "package name")
        text(value, "package version")
    completeness = exact(
        document["completeness"],
        {"input_records", "processed_records", "open_orders", "pending_commands", "stop_reason"},
        "completeness",
    )
    count = integer(completeness["input_records"], "input_records", 1, MAX_EVENTS)
    processed = integer(completeness["processed_records"], "processed_records", 0, count)
    orders, pending = completeness["open_orders"], completeness["pending_commands"]
    if (
        not isinstance(orders, list)
        or len(orders) > MAX_EVENTS
        or not isinstance(pending, list)
        or len(pending) > MAX_EVENTS
    ):
        raise ReplayValidationError("Open orders and pending commands must be bounded lists")
    for order in orders:
        row = exact(order, {"order_id", "status"}, "open order")
        text(row["order_id"], "order_id")
        text(row["status"], "order status")
    referenced_inputs: list[bytes] = []
    for command in pending:
        row = exact(
            command,
            {"command_id", "order_id", "command_type", "decision_ref", "source_ref"},
            "pending command",
        )
        for key in ("command_id", "order_id", "decision_ref"):
            text(row[key], key)
        if row["command_type"] not in ("submit", "cancel"):
            raise ReplayValidationError("Pending command must be submit or cancel")
        reference = _source_ref(row["source_ref"])
        if reference is not None:
            referenced_inputs.append(canonical(reference))
    status, reason = document["execution_status"], completeness["stop_reason"]
    if status == "completed":
        valid = processed == count and not orders and not pending and reason == "input_exhausted"
    elif status == "incomplete":
        valid = processed == count and (
            (bool(pending) and reason == "pending_commands_at_data_end")
            or (not pending and bool(orders) and reason == "input_exhausted_with_open_orders")
        )
    elif status == "failed":
        valid = reason == "engine_error"
    else:
        valid = False
    if not valid:
        raise ReplayValidationError("Execution status and completeness do not agree")
    input_references: set[bytes] = set()
    last_capture_seq = 0
    for channel in TRACE_CHANNELS:
        rows = document[channel]
        if not isinstance(rows, list) or len(rows) > 50_000:
            raise ReplayValidationError("Trace channel must be a bounded list")
        for ordinal, row_value in enumerate(rows):
            row = exact(
                row_value, {"kind", "ordinal", "native_time_ns", "source_ref", "fields"}, channel
            )
            text(row["kind"], "trace kind")
            integer(row["ordinal"], "ordinal", ordinal, ordinal)
            integer(row["native_time_ns"], "native_time_ns")
            reference = _source_ref(row["source_ref"], nullable=channel != "input_trace")
            if reference is not None:
                encoded_reference = canonical(reference)
                if channel == "input_trace":
                    capture_seq = integer(reference["capture_seq"], "capture_seq", 1)
                    if reference["line"] != ordinal + 1 or capture_seq <= last_capture_seq:
                        raise ReplayValidationError(
                            "input_trace must preserve its ordered input prefix"
                        )
                    input_references.add(encoded_reference)
                    last_capture_seq = capture_seq
                else:
                    referenced_inputs.append(encoded_reference)
            if not isinstance(row["fields"], dict):
                raise ReplayValidationError("Trace fields must be an object")
            _json_values(row["fields"])
        if channel == "input_trace" and len(rows) != processed:
            raise ReplayValidationError("input_trace must identify every processed input")
    if any(reference not in input_references for reference in referenced_inputs):
        raise ReplayValidationError("Trace or pending command refers to an unprocessed input")


@dataclass(frozen=True, slots=True)
class ReplayResult:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        document = parse(self.canonical_bytes, MAX_RESULT_BYTES)
        _result(document)
        if canonical(document) != self.canonical_bytes:
            raise ReplayValidationError("ReplayResult must use exact canonical encoding")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, MAX_RESULT_BYTES)


def load_replay_result(raw: bytes) -> ReplayResult:
    return ReplayResult(raw)


def build_replay_result(document: dict[str, object]) -> ReplayResult:
    _result(document)
    return ReplayResult(canonical(document))
