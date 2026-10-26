"""Frozen conditional tagged-participant reconstruction, separate from shadow replay.

The first observed quantity already includes the tagged order. Entry relabels an
existing tail tranche rather than adding liquidity. The source protocol and its
old constraint supply configuration and gross-flow lineage only; this protocol
owns its own claim, semantic, projection, intervention and shared attempt budget.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from tickwitness.domain.assumptions.queue_constraints import (
    MAX_QUEUE_EVENTS,
    QueueConstraintSpec,
    build_queue_constraint_spec,
    load_queue_constraint_spec,
    validate_queue_constraints,
)
from tickwitness.domain.replay._validation import (
    ReplayValidationError,
    canonical,
    digest,
    exact,
    integer,
    parse,
    text,
)
from tickwitness.domain.replay.contracts import PreparedReplay, ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplaySpec, load_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ENGINE_ID,
    ENGINE_VERSION,
    ExecutableProtocol,
    load_executable_protocol,
)
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError, _threshold

if TYPE_CHECKING:
    from tickwitness.domain.replay.tagged_queue_model import TaggedQueueWitnessPair

MAX_TAGGED_PROTOCOL_BYTES = 256 * 1024
TAGGED_ENGINE_SEMANTIC_ID = "nautilus_tagged_fifo_reconstruction_v1"
TAGGED_POLICY_IDS = ("protected_tag_front_cancel_v1", "protected_tag_back_cancel_v1")
TAGGED_MODEL = {
    "model_id": "protected_tagged_fifo_reconstruction_v1",
    "projection_id": "inclusive_tagged_fifo_total_depth_v1",
    "intervention_id": "relabel_existing_tail_quantity_v1",
    "entry_policy": "tag_existing_tail_at_capture_1_v1",
    "trade_allocation": "ahead_then_tagged_then_behind_single_count_v1",
    "cancellation_policy": "external_only_skip_protected_tagged_v1",
    "flow_timing": "adds_then_cancels_at_checkpoint_v1",
    "terminal_policy": "observe_mark_then_cancel_after_horizon_v1",
}
TAGGED_EVALUATION_POLICY = "tagged_inventory_final_visible_bid_flat_zero_v1"
TAGGED_SCOPE = {
    "phase": "development",
    "observation_scope": "finite_path_conditional_tagged_reconstruction",
    "historical_owner_verified": False,
    "literal_order_insertion": False,
    "market_impact_verified": False,
    "source_claim_evaluated": False,
    "finding_issued": False,
}
_REQUEST_LIMIT = 16 * 1024
_CLAIM_FIELDS = {"title", "hypothesis", "metric", "unit", "comparator", "threshold"}
_BUDGET_FIELDS = {"max_attempts", "max_wall_seconds", "max_events"}
_DOCUMENT_FIELDS = {
    "kind",
    "schema_version",
    "read_policy",
    "budget_policy",
    "source_protocol",
    "gross_constraint_source",
    "gross_source_usage",
    "bindings",
    "claim",
    "claim_revision_id",
    "policies",
    "engine",
    "model",
    "strategy",
    "evaluation_policy",
    "parameter_basis",
    "scope",
    "budget",
}


class TaggedQueueValidationError(ProtocolValidationError):
    """The frozen tagged reconstruction or its actual input violates its profile."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TaggedQueueValidationError(message)


def _equal(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _source(source: ExecutableProtocol) -> ExecutableProtocol:
    _require(
        type(source) is ExecutableProtocol,
        "Tagged reconstruction requires an actual source v2 protocol",
    )
    checked = load_executable_protocol(source.canonical_bytes)
    _require(
        (checked.protocol_id, checked.claim_revision_id)
        == (source.protocol_id, source.claim_revision_id),
        "Source protocol identities differ",
    )
    replay = cast("dict[str, object]", checked.document["replay_spec"])
    strategy = cast("dict[str, object]", replay["strategy"])
    execution = cast("dict[str, int]", replay["execution"])
    _require(
        strategy["submit_capture_seq"] == 1 and strategy["cancel_after_first_fill"] is False,
        "Tagged reconstruction requires capture 1 representation and no first-fill cancellation",
    )
    _require(
        execution["insert_latency_ns"] == execution["cancel_latency_ns"] == 0,
        "Tagged reconstruction requires zero native insert and cancel latency",
    )
    return checked


def _claim(value: object) -> dict[str, object]:
    claim = exact(value, _CLAIM_FIELDS, "Tagged queue claim")
    _equal(
        [claim["metric"], claim["unit"]],
        ["tagged_inventory_net_marked_pnl_v1", "USD"],
        "Tagged claim requires its own USD inventory marking metric",
    )
    _require(claim["comparator"] in ("gt", "ge", "lt", "le"), "Unsupported tagged comparator")
    return {
        "title": text(claim["title"], "claim title", 200),
        "hypothesis": text(claim["hypothesis"], "claim hypothesis", 2000),
        "metric": "tagged_inventory_net_marked_pnl_v1",
        "unit": "USD",
        "comparator": claim["comparator"],
        "threshold": _threshold(claim["threshold"]),
    }


def _build_document(
    *,
    source: ExecutableProtocol,
    constraint: QueueConstraintSpec,
    claim: object,
    budget: object,
    horizon_capture_seq: object,
) -> dict[str, object]:
    source = _source(source)
    _require(type(constraint) is QueueConstraintSpec, "Expected source-bound gross declaration")
    checked_constraint = load_queue_constraint_spec(constraint.canonical_bytes)
    _require(
        checked_constraint.constraint_id == constraint.constraint_id,
        "Gross constraint identity differs from canonical content",
    )
    constraint = checked_constraint
    source_doc, gross = source.document, constraint.document
    bindings = cast("dict[str, str]", gross["bindings"])
    datasets = cast("dict[str, str]", source_doc["datasets"])
    _equal(
        [bindings["protocol_id"], bindings["development_dataset_id"], bindings["replay_spec_id"]],
        [source.protocol_id, datasets["development"], source_doc["replay_spec_id"]],
        "Gross declaration differs from full source protocol",
    )
    replay = cast("dict[str, object]", source_doc["replay_spec"])
    strategy = cast("dict[str, object]", replay["strategy"])
    target = cast("dict[str, object]", gross["target"])
    _equal(
        target["price_ticks"],
        strategy["limit_price_ticks"],
        "Tagged target differs from source limit",
    )
    horizon = integer(horizon_capture_seq, "horizon_capture_seq", 2)
    updates = cast("list[dict[str, object]]", gross["updates"])
    _equal(horizon, updates[-1]["capture_seq"], "Horizon must be the final target checkpoint")
    checked_claim = _claim(claim)
    limits = exact(budget, _BUDGET_FIELDS, "Tagged shared budget")
    source_budget = cast("dict[str, int]", source_doc["budget"])
    checked_budget = {
        "max_attempts": integer(limits["max_attempts"], "max_attempts", 2, 100),
        "max_wall_seconds": integer(limits["max_wall_seconds"], "max_wall_seconds", 1, 60),
        "max_events": integer(
            limits["max_events"],
            "max_events",
            1,
            min(source_budget["max_events"], MAX_QUEUE_EVENTS),
        ),
    }
    return {
        "kind": "tagged_queue_reconstruction_protocol_v1",
        "schema_version": 1,
        "read_policy": "development_only_v1",
        "budget_policy": "shared_tagged_queue_budget_v1",
        "source_protocol": source_doc,
        "gross_constraint_source": gross,
        "gross_source_usage": "source_and_gross_flow_lineage_only_v1",
        "bindings": {
            "source_protocol_id": source.protocol_id,
            "development_dataset_id": datasets["development"],
            "normalized_sha256": bindings["normalized_sha256"],
            "replay_spec_id": source_doc["replay_spec_id"],
            "gross_constraint_id": constraint.constraint_id,
        },
        "claim": checked_claim,
        "claim_revision_id": digest(canonical(checked_claim)),
        "policies": list(TAGGED_POLICY_IDS),
        "engine": {
            "id": ENGINE_ID,
            "version": ENGINE_VERSION,
            "semantic_id": TAGGED_ENGINE_SEMANTIC_ID,
        },
        "model": dict(TAGGED_MODEL),
        "strategy": {
            "kind": "tagged_passive_order_at_entry_v1",
            "entry_capture_seq": 1,
            "horizon_capture_seq": horizon,
            "tagged_quantity_lots": strategy["quantity_lots"],
            "target_price_ticks": strategy["limit_price_ticks"],
        },
        "evaluation_policy": TAGGED_EVALUATION_POLICY,
        "parameter_basis": gross["parameter_basis"],
        "scope": dict(TAGGED_SCOPE),
        "budget": checked_budget,
    }


def _validated(raw: bytes) -> dict[str, object]:
    try:
        doc = exact(
            parse(raw, MAX_TAGGED_PROTOCOL_BYTES), _DOCUMENT_FIELDS, "Tagged queue protocol"
        )
        source = load_executable_protocol(
            canonical(cast("dict[str, object]", doc["source_protocol"]))
        )
        constraint = load_queue_constraint_spec(
            canonical(cast("dict[str, object]", doc["gross_constraint_source"]))
        )
        strategy = exact(
            doc["strategy"],
            {
                "kind",
                "entry_capture_seq",
                "horizon_capture_seq",
                "tagged_quantity_lots",
                "target_price_ticks",
            },
            "Tagged strategy",
        )
        rebuilt = _build_document(
            source=source,
            constraint=constraint,
            claim=doc["claim"],
            budget=doc["budget"],
            horizon_capture_seq=strategy["horizon_capture_seq"],
        )
        _require(
            canonical(rebuilt) == raw,
            "Tagged protocol identity, policies, scope or encoding differ",
        )
        return rebuilt
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise TaggedQueueValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class TaggedQueueProtocol:
    protocol_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validated(self.canonical_bytes)
        _require(
            self.protocol_id == digest(self.canonical_bytes), "Tagged protocol identity mismatch"
        )

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, MAX_TAGGED_PROTOCOL_BYTES)

    @property
    def claim_revision_id(self) -> str:
        return cast("str", self.document["claim_revision_id"])

    @property
    def source_protocol(self) -> ExecutableProtocol:
        return load_executable_protocol(
            canonical(cast("dict[str, object]", self.document["source_protocol"]))
        )

    @property
    def constraint(self) -> QueueConstraintSpec:
        """Preserve the old declaration as source/gross lineage, never new-model permission."""
        return load_queue_constraint_spec(
            canonical(cast("dict[str, object]", self.document["gross_constraint_source"]))
        )


def load_tagged_queue_protocol(raw: bytes) -> TaggedQueueProtocol:
    _validated(raw)
    return TaggedQueueProtocol(digest(raw), raw)


def _checked_input(
    protocol: TaggedQueueProtocol, replay_input: ReplayInput
) -> tuple[TaggedQueueProtocol, PreparedReplay]:
    _require(type(protocol) is TaggedQueueProtocol, "Expected immutable tagged queue protocol")
    checked = TaggedQueueProtocol(protocol.protocol_id, protocol.canonical_bytes)
    _require(type(replay_input) is ReplayInput, "Expected actual ReplayInput")
    _require(type(replay_input.spec) is ReplaySpec, "Expected actual ReplaySpec")
    spec = load_replay_spec(replay_input.spec.canonical_bytes)
    _require(spec.spec_id == replay_input.spec.spec_id, "Replay spec identity mismatch")
    actual = ReplayInput(replay_input.dataset_id, replay_input.normalized_bytes, spec)
    validate_queue_constraints(
        checked.constraint, protocol=checked.source_protocol, replay_input=actual
    )
    prepared = preflight_replay(actual)
    doc = checked.document
    budget = cast("dict[str, int]", doc["budget"])
    _require(len(prepared.events) <= budget["max_events"], "Tagged event budget exceeded")
    strategy = cast("dict[str, int]", doc["strategy"])
    last = prepared.events[-1]
    _require(
        last.capture_seq == strategy["horizon_capture_seq"]
        and last.event_type == "delta"
        and strategy["target_price_ticks"] in dict(last.bids),
        "Tagged horizon must be the actual final target bid checkpoint",
    )
    return checked, prepared


def validate_tagged_queue_input(
    protocol: TaggedQueueProtocol, replay_input: ReplayInput
) -> "TaggedQueueWitnessPair":
    from tickwitness.domain.replay.tagged_queue_model import TaggedQueueWitnessPair

    try:
        return TaggedQueueWitnessPair(protocol, replay_input)
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise TaggedQueueValidationError(str(error)) from error


def build_tagged_queue_protocol(
    raw: bytes,
    *,
    source_protocol: ExecutableProtocol,
    replay_input: ReplayInput,
    queue_request: bytes,
) -> TaggedQueueProtocol:
    try:
        request = exact(
            parse(raw, _REQUEST_LIMIT),
            {"kind", "schema_version", "claim", "budget"},
            "Tagged queue request",
        )
        _equal(request["kind"], "tagged_queue_request_v1", "Unsupported tagged queue request")
        integer(request["schema_version"], "schema_version", 1, 1)
        source = _source(source_protocol)
        constraint = build_queue_constraint_spec(
            queue_request, protocol=source, replay_input=replay_input
        )
        prepared = preflight_replay(replay_input)
        doc = _build_document(
            source=source,
            constraint=constraint,
            claim=request["claim"],
            budget=request["budget"],
            horizon_capture_seq=prepared.events[-1].capture_seq,
        )
        encoded = canonical(doc)
        _require(
            len(encoded) <= MAX_TAGGED_PROTOCOL_BYTES, "Tagged protocol exceeds its byte bound"
        )
        protocol = TaggedQueueProtocol(digest(encoded), encoded)
        validate_tagged_queue_input(protocol, replay_input)
        return protocol
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise TaggedQueueValidationError(str(error)) from error
