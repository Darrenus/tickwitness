"""Native-free, bounded DTOs for the distinct inclusive tagged reconstruction."""

from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.domain.replay._validation import (
    MAX_RESULT_BYTES,
    ReplayValidationError,
    canonical,
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
from tickwitness.domain.replay.queue_contracts import _fields, _rows
from tickwitness.domain.replay.specs import load_replay_spec
from tickwitness.domain.replay.tagged_queue_model import TaggedQueueWitnessPair
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TAGGED_ENGINE_SEMANTIC_ID,
    TAGGED_POLICY_IDS,
    TaggedQueueProtocol,
    validate_tagged_queue_input,
)

TRACE_CHANNELS = ("input_trace", "decision_trace", "order_trace", "fill_trace", "account_trace")
PHASES = ("bootstrap", "observed_window", "claim_horizon", "post_horizon_cleanup")
ENGINE = {
    "id": "nautilus-trader",
    "version": "1.231.0",
    "semantic_id": TAGGED_ENGINE_SEMANTIC_ID,
}


@dataclass(frozen=True, slots=True)
class TaggedQueueReplayInput:
    protocol: TaggedQueueProtocol
    normalized_bytes: bytes
    policy_id: str

    def __post_init__(self) -> None:
        if (
            type(self.protocol) is not TaggedQueueProtocol
            or self.policy_id not in TAGGED_POLICY_IDS
        ):
            raise ReplayValidationError(
                "Tagged replay requires an immutable protocol and frozen policy"
            )
        validate_tagged_queue_input(self.protocol, self.replay_input)

    @property
    def replay_input(self) -> ReplayInput:
        doc = self.protocol.source_protocol.document
        bindings = cast("dict[str, str]", self.protocol.document["bindings"])
        spec = load_replay_spec(canonical(cast("dict[str, object]", doc["replay_spec"])))
        return ReplayInput(bindings["development_dataset_id"], self.normalized_bytes, spec)

    @property
    def prepared(self) -> PreparedReplay:
        return preflight_replay(self.replay_input)

    @property
    def witnesses(self) -> TaggedQueueWitnessPair:
        return validate_tagged_queue_input(self.protocol, self.replay_input)

    @property
    def bindings(self) -> dict[str, str]:
        prepared = self.prepared
        return {
            "protocol_id": self.protocol.protocol_id,
            "claim_revision_id": self.protocol.claim_revision_id,
            "source_protocol_id": self.protocol.source_protocol.protocol_id,
            "dataset_id": prepared.dataset_id,
            "data_sha256": prepared.data_sha256,
            "spec_id": prepared.spec.spec_id,
            "gross_constraint_id": self.protocol.constraint.constraint_id,
            "policy_id": self.policy_id,
        }


class TaggedQueueReplayPort(Protocol):
    def run(self, replay_input: TaggedQueueReplayInput) -> "TaggedQueueReplayResult": ...


def _state(value: object, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    row = exact(
        value,
        {
            "ahead_lots",
            "own_live_lots",
            "behind_lots",
            "external_lots",
            "total_lots",
            "own_filled_lots",
        },
        "tagged state",
    )
    for key, item in row.items():
        integer(item, key)


def _account(value: object) -> None:
    if not isinstance(value, dict) or value.get("book_role") != "recorded_observation_cache":
        raise ReplayValidationError("Tagged account requires the recorded observation cache role")
    _fields("account_trace", {key: item for key, item in value.items() if key != "book_role"})


def _trace_fields(channel: str, value: object) -> None:
    if channel == "account_trace":
        _account(value)
    elif channel != "order_trace":
        _fields(channel, value)
    else:
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
            "tagged order fields",
        )
        _json_values(row)
        for key in ("order_id", "event_type"):
            text(row[key], key)
        if row["status"] is not None:
            text(row["status"], "status")
        for key in ("quantity_lots", "filled_quantity_lots", "remaining_quantity_lots"):
            if row[key] is not None:
                integer(row[key], key)
        for item in _rows(row["pending_commands"], "pending command IDs"):
            text(item, "pending command ID")
        if row["actual_acceptance"] is not None:
            accepted = exact(
                row["actual_acceptance"],
                {"native_bid_lots", "queue", "target_price_ticks", "acceptance_role"},
                "tagged actual acceptance",
            )
            integer(accepted["native_bid_lots"], "native_bid_lots")
            integer(accepted["target_price_ticks"], "target_price_ticks", 1)
            _state(accepted["queue"])
            if accepted["acceptance_role"] != "tagged_reconstruction_proxy":
                raise ReplayValidationError("Actual acceptance is only a reconstruction proxy")


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
            "horizon_snapshot",
            "cleanup",
        },
        "TaggedQueueReplayResult",
    )
    if document["kind"] != "tagged_queue_replay_result_v1":
        raise ReplayValidationError("Unsupported tagged replay result kind")
    integer(document["schema_version"], "schema_version", 1, 1)
    bindings = exact(
        document["bindings"],
        {
            "protocol_id",
            "claim_revision_id",
            "source_protocol_id",
            "dataset_id",
            "data_sha256",
            "spec_id",
            "gross_constraint_id",
            "policy_id",
        },
        "tagged bindings",
    )
    for key, value in bindings.items():
        if key != "policy_id":
            identity(value, key)
    if bindings["policy_id"] not in TAGGED_POLICY_IDS or canonical(
        {"engine": document["engine"]}
    ) != canonical({"engine": ENGINE}):
        raise ReplayValidationError("Tagged engine or frozen policy differs")
    environment = exact(
        document["environment"],
        {"python_version", "platform", "package_versions"},
        "tagged environment",
    )
    text(environment["python_version"], "python_version")
    text(environment["platform"], "platform", 512)
    packages = environment["package_versions"]
    if not isinstance(packages, dict) or not 1 <= len(packages) <= 128:
        raise ReplayValidationError("Tagged result must bind dependency versions")
    for key, value in packages.items():
        text(key, "package name")
        text(value, "package version")
    completeness = exact(
        document["completeness"],
        {"input_records", "processed_records", "open_orders", "pending_commands", "stop_reason"},
        "tagged completeness",
    )
    count = integer(completeness["input_records"], "input_records", 1, 1000)
    integer(completeness["processed_records"], "processed_records", count, count)
    if (
        document["execution_status"] != "completed"
        or completeness["open_orders"] != []
        or completeness["pending_commands"] != []
        or completeness["stop_reason"] != "input_exhausted"
    ):
        raise ReplayValidationError("Tagged reconstruction requires completed actual cleanup")
    inputs: set[bytes] = set()
    references: list[bytes] = []
    previous_capture = 0
    for channel in TRACE_CHANNELS:
        rows = _rows(document[channel], channel)
        if channel == "input_trace" and len(rows) != count:
            raise ReplayValidationError("Tagged input trace omits source input")
        for ordinal, item in enumerate(rows):
            row = exact(
                item,
                {"kind", "ordinal", "native_time_ns", "source_ref", "phase", "fields"},
                channel,
            )
            text(row["kind"], "trace kind")
            integer(row["ordinal"], "ordinal", ordinal, ordinal)
            integer(row["native_time_ns"], "native_time_ns")
            if row["phase"] not in PHASES:
                raise ReplayValidationError("Unsupported tagged logical phase")
            ref = _source_ref(row["source_ref"], nullable=channel != "input_trace")
            if ref is not None:
                encoded = canonical(ref)
                if channel == "input_trace":
                    previous_capture = integer(
                        ref["capture_seq"], "capture_seq", previous_capture + 1
                    )
                    if ref["line"] != ordinal + 1:
                        raise ReplayValidationError("Tagged input source order differs")
                    inputs.add(encoded)
                else:
                    references.append(encoded)
            _trace_fields(channel, row["fields"])
    queue_rows = _rows(document["queue_trace"], "queue_trace")
    if len(queue_rows) != count:
        raise ReplayValidationError("Tagged queue trace omits source input")
    for item in queue_rows:
        row = exact(
            item,
            {
                "kind",
                "source_ref",
                "receive_time_ns",
                "before",
                "flow",
                "after",
                "observed_total_lots",
                "own_fill_grant_lots",
                "granted_lots",
                "native_filled_lots",
                "accepted_here",
            },
            "tagged queue row",
        )
        references.append(canonical(cast("dict[str, object]", _source_ref(row["source_ref"]))))
        text(row["kind"], "queue row kind")
        _state(row["before"], nullable=True)
        _state(row["after"])
        for key in ("receive_time_ns", "own_fill_grant_lots", "granted_lots", "native_filled_lots"):
            integer(row[key], key)
        if row["observed_total_lots"] is not None:
            integer(row["observed_total_lots"], "observed_total_lots")
        if type(row["accepted_here"]) is not bool:
            raise ReplayValidationError("accepted_here must be boolean")
        flow = exact(
            row["flow"],
            {
                "additions_lots",
                "cancellations_lots",
                "trade_lots",
                "cancel_ahead_lots",
                "cancel_behind_lots",
                "external_trade_ahead_lots",
                "own_trade_lots",
                "external_trade_behind_lots",
            },
            "tagged flow",
        )
        for key, value in flow.items():
            integer(value, key)
    for item in _rows(document["hook_trace"], "hook_trace"):
        row = exact(
            item,
            {"source_ref", "origin", "offered_lots", "cumulative_granted_lots", "phase"},
            "tagged hook",
        )
        references.append(canonical(cast("dict[str, object]", _source_ref(row["source_ref"]))))
        text(row["origin"], "hook origin")
        for key in ("offered_lots", "cumulative_granted_lots"):
            integer(row[key], key)
        if row["phase"] not in PHASES:
            raise ReplayValidationError("Unsupported hook phase")
    horizon = exact(
        document["horizon_snapshot"],
        {"source_ref", "native_time_ns", "queue_state", "native_target_lots", "mark", "account"},
        "tagged horizon",
    )
    references.append(canonical(cast("dict[str, object]", _source_ref(horizon["source_ref"]))))
    _state(horizon["queue_state"])
    integer(horizon["native_time_ns"], "native_time_ns")
    integer(horizon["native_target_lots"], "native_target_lots")
    mark = exact(
        horizon["mark"], {"source_ref", "price_ticks", "available_quantity_lots"}, "tagged mark"
    )
    references.append(canonical(cast("dict[str, object]", _source_ref(mark["source_ref"]))))
    integer(mark["price_ticks"], "price_ticks", 1)
    integer(mark["available_quantity_lots"], "available_quantity_lots", 1)
    _account(horizon["account"])
    cleanup = exact(
        document["cleanup"],
        {
            "canceled_own_lots",
            "projected_total_after_cleanup",
            "projected_external_after_cleanup",
            "own_live_after_cleanup",
            "native_status",
            "native_unfilled_lots",
            "book_role",
        },
        "tagged cleanup",
    )
    for key in (
        "canceled_own_lots",
        "projected_total_after_cleanup",
        "projected_external_after_cleanup",
        "own_live_after_cleanup",
        "native_unfilled_lots",
    ):
        integer(cleanup[key], key)
    if cleanup["book_role"] != "recorded_observation_cache" or cleanup["native_status"] not in (
        "CANCELED",
        "FILLED",
    ):
        raise ReplayValidationError("Tagged cleanup lacks a terminal native order")
    if any(reference not in inputs for reference in references):
        raise ReplayValidationError("Tagged evidence refers to an unprocessed input")


@dataclass(frozen=True, slots=True)
class TaggedQueueReplayResult:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        document = parse(self.canonical_bytes, MAX_RESULT_BYTES)
        _result(document)
        if canonical(document) != self.canonical_bytes:
            raise ReplayValidationError("Tagged result requires exact canonical JSON")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, MAX_RESULT_BYTES)


def load_tagged_queue_replay_result(raw: bytes) -> TaggedQueueReplayResult:
    return TaggedQueueReplayResult(raw)


def build_tagged_queue_replay_result(document: dict[str, object]) -> TaggedQueueReplayResult:
    return TaggedQueueReplayResult(canonical(document))
