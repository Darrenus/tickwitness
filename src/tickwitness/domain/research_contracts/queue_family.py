"""Frozen ownership for two bounded external FIFO queue execution models.

The embedded v2 protocol supplies source lineage and ReplaySpec settings. It is
not execution permission for either new queue model. A family owns one shared
attempt budget; its two policies never receive independent protocol budgets.
Source revalidation is required before execution. No compatibility or finding is
established by freezing the declaration or by its pure feasibility check.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.assumptions.queue_constraints import (
    MAX_QUEUE_EVENTS,
    QueueConstraintSpec,
    QueueFeasibilityPair,
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
)
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplaySpec, load_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ENGINE_ID,
    ENGINE_VERSION,
    ExecutableProtocol,
    ProtocolValidationError,
    load_executable_protocol,
)

MAX_QUEUE_FAMILY_BYTES = 256 * 1024
QUEUE_ENGINE_SEMANTIC_ID = "nautilus_external_fifo_shadow_queue_execution_v1"
QUEUE_POLICY_IDS = ("cancel_front_first_v1", "cancel_back_first_v1")
_REQUEST_LIMIT = 16 * 1024
_REQUEST_FIELDS = {"kind", "schema_version", "cancel_at_capture_seq", "budget"}
_DOCUMENT_FIELDS = {
    "kind",
    "schema_version",
    "read_policy",
    "budget_policy",
    "source_protocol",
    "constraint",
    "bindings",
    "policies",
    "engine",
    "strategy",
    "parameter_basis",
    "scope",
    "budget",
}
_BUDGET_FIELDS = {"max_attempts", "max_wall_seconds", "max_events"}


class QueueFamilyValidationError(ProtocolValidationError):
    """A family or its input violates the frozen queue execution profile."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QueueFamilyValidationError(message)


def _equal(left: object, right: object, message: str) -> None:
    _require(canonical({"value": left}) == canonical({"value": right}), message)


def _source_profile(protocol: ExecutableProtocol) -> ExecutableProtocol:
    _require(isinstance(protocol, ExecutableProtocol), "Expected an actual source v2 protocol")
    source = load_executable_protocol(protocol.canonical_bytes)
    _require(
        (source.protocol_id, source.claim_revision_id)
        == (protocol.protocol_id, protocol.claim_revision_id),
        "Source protocol identities differ from its canonical content",
    )
    replay = cast("dict[str, object]", source.document["replay_spec"])
    execution = cast("dict[str, int]", replay["execution"])
    strategy = cast("dict[str, object]", replay["strategy"])
    _require(
        execution["insert_latency_ns"] == execution["cancel_latency_ns"] == 0,
        "Queue execution requires zero insert and cancel latency",
    )
    _require(
        strategy["submit_capture_seq"] == 1 and strategy["cancel_after_first_fill"] is False,
        "Queue execution requires capture 1 entry and an explicit family cancellation",
    )
    return source


def _build_document(
    *,
    source_protocol: ExecutableProtocol,
    constraint: QueueConstraintSpec,
    cancel_at_capture_seq: object,
    budget: object,
) -> dict[str, object]:
    source = _source_profile(source_protocol)
    _require(isinstance(constraint, QueueConstraintSpec), "Expected QueueConstraintSpec")
    checked_constraint = load_queue_constraint_spec(constraint.canonical_bytes)
    _require(
        checked_constraint.constraint_id == constraint.constraint_id,
        "Queue constraint identity differs from its canonical content",
    )
    document = source.document
    queue = checked_constraint.document
    source_bindings = cast("dict[str, object]", queue["bindings"])
    datasets = cast("dict[str, str]", document["datasets"])
    _equal(
        {
            "protocol_id": source_bindings["protocol_id"],
            "development_dataset_id": source_bindings["development_dataset_id"],
            "replay_spec_id": source_bindings["replay_spec_id"],
        },
        {
            "protocol_id": source.protocol_id,
            "development_dataset_id": datasets["development"],
            "replay_spec_id": document["replay_spec_id"],
        },
        "Queue constraint differs from the complete source protocol",
    )
    replay = cast("dict[str, object]", document["replay_spec"])
    strategy = cast("dict[str, object]", replay["strategy"])
    target = cast("dict[str, object]", queue["target"])
    _equal(
        target["price_ticks"],
        strategy["limit_price_ticks"],
        "Queue target differs from the source limit price",
    )
    cancel = integer(cancel_at_capture_seq, "cancel_at_capture_seq", 2)
    updates = cast("list[dict[str, object]]", queue["updates"])
    _require(
        cancel == updates[-1]["capture_seq"],
        "Cancellation must identify the final declared target bid checkpoint",
    )
    limits = exact(budget, _BUDGET_FIELDS, "Queue family budget")
    source_budget = cast("dict[str, int]", document["budget"])
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
        "kind": "queue_family_protocol_v1",
        "schema_version": 1,
        "read_policy": "development_only_v1",
        "budget_policy": "shared_queue_family_budget_v1",
        "source_protocol": document,
        "constraint": queue,
        "bindings": {
            "source_protocol_id": source.protocol_id,
            "development_dataset_id": datasets["development"],
            "normalized_sha256": source_bindings["normalized_sha256"],
            "replay_spec_id": document["replay_spec_id"],
            "queue_constraint_id": checked_constraint.constraint_id,
        },
        "policies": list(QUEUE_POLICY_IDS),
        "engine": {
            "id": ENGINE_ID,
            "version": ENGINE_VERSION,
            "semantic_id": QUEUE_ENGINE_SEMANTIC_ID,
        },
        "strategy": {
            "kind": "single_limit_buy_cancel_at_capture_v1",
            "submit_capture_seq": 1,
            "cancel_at_capture_seq": cancel,
        },
        "parameter_basis": queue["parameter_basis"],
        "scope": {
            "phase": "development",
            "scenario_kind": "MODEL_SENSITIVITY",
            "impact_compatibility_verified": False,
            "claim_verdict_issued": False,
        },
        "budget": checked_budget,
    }


def _validated(raw: bytes) -> dict[str, object]:
    try:
        document = exact(parse(raw, MAX_QUEUE_FAMILY_BYTES), _DOCUMENT_FIELDS, "Queue family")
        source = load_executable_protocol(
            canonical(cast("dict[str, object]", document["source_protocol"]))
        )
        constraint = load_queue_constraint_spec(
            canonical(cast("dict[str, object]", document["constraint"]))
        )
        strategy = exact(
            document["strategy"],
            {"kind", "submit_capture_seq", "cancel_at_capture_seq"},
            "Queue family strategy",
        )
        rebuilt = _build_document(
            source_protocol=source,
            constraint=constraint,
            cancel_at_capture_seq=strategy["cancel_at_capture_seq"],
            budget=document["budget"],
        )
        _require(
            canonical(rebuilt) == raw,
            "Queue family policies, bindings, identities or canonical encoding differ",
        )
        return rebuilt
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise QueueFamilyValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class QueueFamilyProtocol:
    """Immutable execution owner; source claim identity is lineage only."""

    protocol_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validated(self.canonical_bytes)
        _require(
            self.protocol_id == digest(self.canonical_bytes), "Queue family identity mismatch"
        )

    @property
    def family_id(self) -> str:
        return self.protocol_id

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, MAX_QUEUE_FAMILY_BYTES)

    @property
    def source_protocol(self) -> ExecutableProtocol:
        return load_executable_protocol(
            canonical(cast("dict[str, object]", self.document["source_protocol"]))
        )

    @property
    def constraint(self) -> QueueConstraintSpec:
        return load_queue_constraint_spec(
            canonical(cast("dict[str, object]", self.document["constraint"]))
        )

    @property
    def claim_revision_id(self) -> str:
        """Preserve source lineage; this family cannot evaluate the source claim."""
        return self.source_protocol.claim_revision_id


def load_queue_family_protocol(raw: bytes) -> QueueFamilyProtocol:
    """Rebuild every embedded declaration; source bytes still need actual-input checks."""
    _validated(raw)
    return QueueFamilyProtocol(digest(raw), raw)


def validate_queue_family_input(
    family: QueueFamilyProtocol, replay_input: ReplayInput
) -> QueueFeasibilityPair:
    """Recheck immutable source, flow equations, event budget and final cancel capture."""
    try:
        _require(isinstance(family, QueueFamilyProtocol), "Expected QueueFamilyProtocol")
        checked = QueueFamilyProtocol(family.protocol_id, family.canonical_bytes)
        _require(isinstance(replay_input, ReplayInput), "Expected actual ReplayInput")
        _require(isinstance(replay_input.spec, ReplaySpec), "Expected actual ReplaySpec")
        spec = load_replay_spec(replay_input.spec.canonical_bytes)
        _require(spec.spec_id == replay_input.spec.spec_id, "ReplaySpec identity mismatch")
        actual = ReplayInput(replay_input.dataset_id, replay_input.normalized_bytes, spec)
        pair = validate_queue_constraints(
            checked.constraint, protocol=checked.source_protocol, replay_input=actual
        )
        prepared = preflight_replay(actual)
        document = checked.document
        budget = cast("dict[str, int]", document["budget"])
        _require(
            len(prepared.events) <= budget["max_events"],
            "Actual input exceeds the shared family event budget",
        )
        strategy = cast("dict[str, int]", document["strategy"])
        last = prepared.events[-1]
        target = cast("dict[str, object]", checked.constraint.document["target"])
        _require(
            last.capture_seq == strategy["cancel_at_capture_seq"]
            and last.event_type == "delta"
            and target["price_ticks"] in dict(last.bids),
            "Cancellation must identify the actual final target bid checkpoint",
        )
        return pair
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise QueueFamilyValidationError(str(error)) from error


def build_queue_family_protocol(
    raw: bytes,
    *,
    source_protocol: ExecutableProtocol,
    replay_input: ReplayInput,
    queue_request: bytes,
) -> QueueFamilyProtocol:
    """Freeze a new execution owner from actual development data and explicit assumptions."""
    try:
        request = exact(parse(raw, _REQUEST_LIMIT), _REQUEST_FIELDS, "Queue family request")
        _equal(request["kind"], "queue_family_request_v1", "Unsupported queue family request")
        integer(request["schema_version"], "schema_version", 1, 1)
        source = _source_profile(source_protocol)
        constraint = build_queue_constraint_spec(
            queue_request, protocol=source, replay_input=replay_input
        )
        document = _build_document(
            source_protocol=source,
            constraint=constraint,
            cancel_at_capture_seq=request["cancel_at_capture_seq"],
            budget=request["budget"],
        )
        encoded = canonical(document)
        _require(len(encoded) <= MAX_QUEUE_FAMILY_BYTES, "Queue family exceeds 256 KiB")
        family = QueueFamilyProtocol(digest(encoded), encoded)
        validate_queue_family_input(family, replay_input)
        return family
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise QueueFamilyValidationError(str(error)) from error
