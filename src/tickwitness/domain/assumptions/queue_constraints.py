"""Bounded external shadow-queue constraints; never native execution evidence.

Gross flow and FIFO ordering are declared model assumptions. Absolute L2 depth
and trades do not identify real cancellation positions or certify market impact.
"""

from dataclasses import dataclass, field
from typing import cast

from tickwitness.domain.replay._validation import (
    ReplayValidationError,
    canonical,
    digest,
    exact,
    identity,
    integer,
    parse,
)
from tickwitness.domain.replay.contracts import PreparedReplay, ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplaySpec
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    ProtocolValidationError,
)

PROFILE_ID = "external_fifo_shadow_queue_v1"
CLASSIFICATION = "MODEL_SENSITIVITY_CANDIDATE"
MAX_QUEUE_EVENTS = 1_000
MAX_QUEUE_LOTS = 1_000_000_000
_SPEC_LIMIT = 65_536
_PAIR_LIMIT = 2 * 1024 * 1024
_REQUEST_FIELDS = {
    "kind", "schema_version", "model_profile_id", "entry_capture_seq", "parameter_basis",
    "assumptions", "updates",
}
_ASSUMPTIONS: dict[str, object] = {
    "priority": "fifo",
    "hidden_liquidity": "excluded",
    "impact": "shadow_no_impact_unverified",
    "flow_timing": "adds_then_cancels_at_checkpoint_v1",
}
_BASIS: dict[str, object] = {
    "kind": "researcher_defined",
    "calibration_status": "uncalibrated",
    "calibration_evidence_refs": [],
}
_FLAGS: dict[str, object] = {
    "classification": CLASSIFICATION,
    "actual_acceptance_verified": False,
    "impact_compatibility_verified": False,
    "native_execution_verified": False,
    "execution_approved": False,
}


class QueueConstraintValidationError(ReplayValidationError):
    """The declaration cannot satisfy this bounded external-queue profile."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QueueConstraintValidationError(message)


def _equal(left: object, right: object, message: str) -> None:
    _require(canonical({"value": left}) == canonical({"value": right}), message)


def _document(raw: bytes, *, request: bool) -> dict[str, object]:
    document = parse(raw, _SPEC_LIMIT)
    fields = _REQUEST_FIELDS if request else _REQUEST_FIELDS | {"bindings", "target", *_FLAGS}
    exact(document, fields, "Queue constraint")
    _equal(
        document["kind"],
        "queue_constraint_request_v1" if request else "queue_constraint_spec_v1",
        "Unsupported queue constraint kind",
    )
    integer(document["schema_version"], "schema_version", 1, 1)
    _equal(document["model_profile_id"], PROFILE_ID, "Unsupported queue model profile")
    integer(document["entry_capture_seq"], "entry_capture_seq", 1, 1)
    _equal(document["parameter_basis"], _BASIS, "Queue basis must remain researcher-defined and uncalibrated")
    _equal(document["assumptions"], _ASSUMPTIONS, "Unsupported queue assumptions")
    updates = document["updates"]
    _require(type(updates) is list and 0 < len(updates) < MAX_QUEUE_EVENTS, "Queue updates must be a bounded nonempty list")
    previous = 1
    total = 0
    used_trades: set[int] = set()
    for value in cast("list[object]", updates):
        update = exact(
            value,
            {"capture_seq", "additions_lots", "cancellations_lots", "trade_capture_seqs"},
            "Queue update",
        )
        capture = integer(update["capture_seq"], "update capture_seq", previous + 1)
        additions = integer(update["additions_lots"], "additions_lots", 0, MAX_QUEUE_LOTS)
        cancellations = integer(update["cancellations_lots"], "cancellations_lots", 0, MAX_QUEUE_LOTS)
        total += additions + cancellations
        _require(total <= MAX_QUEUE_LOTS, "Declared gross flow exceeds the queue software limit")
        trades = update["trade_capture_seqs"]
        _require(type(trades) is list and len(trades) <= MAX_QUEUE_EVENTS, "Trade references must be a bounded list")
        last_trade = previous
        for trade in cast("list[object]", trades):
            capture_trade = integer(trade, "trade capture_seq", last_trade + 1, capture - 1)
            _require(capture_trade not in used_trades, "Each trade may be reconciled only once")
            used_trades.add(capture_trade)
            last_trade = capture_trade
        previous = capture
    if not request:
        bindings = exact(
            document["bindings"],
            {"protocol_id", "development_dataset_id", "normalized_sha256", "replay_spec_id"},
            "Queue source bindings",
        )
        for label, value in bindings.items():
            identity(value, label)
        target = exact(document["target"], {"source", "instrument", "session", "side", "price_ticks"}, "Queue target")
        for label in ("source", "instrument", "session"):
            _require(isinstance(target[label], str) and 0 < len(target[label]) <= 128, "Queue stream marker is invalid")
        _equal(target["instrument"], "EUR-USD", "Unsupported queue instrument")
        _equal(target["side"], "bid", "Only the external bid queue is supported")
        integer(target["price_ticks"], "queue price_ticks", 1)
        for key, expected in _FLAGS.items():
            _equal(document[key], expected, "Queue constraint cannot approve execution or compatibility")
    return document


@dataclass(frozen=True, slots=True)
class QueueConstraintSpec:
    constraint_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            document = _document(self.canonical_bytes, request=False)
            _require(canonical(document) == self.canonical_bytes, "QueueConstraintSpec must be canonical")
            _require(identity(self.constraint_id, "constraint_id") == digest(self.canonical_bytes), "Queue constraint identity mismatch")
        except ReplayValidationError as error:
            raise QueueConstraintValidationError(str(error)) from error

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, _SPEC_LIMIT)


def _context(
    protocol: ExecutableProtocol, replay_input: ReplayInput
) -> tuple[ExecutableProtocol, PreparedReplay, dict[str, object], dict[str, object]]:
    _require(isinstance(protocol, ExecutableProtocol) and isinstance(replay_input, ReplayInput) and isinstance(replay_input.spec, ReplaySpec), "Queue constraints require actual immutable protocol and input")
    checked_protocol = ExecutableProtocol(protocol.protocol_id, protocol.claim_revision_id, protocol.canonical_bytes)
    checked_spec = ReplaySpec(replay_input.spec.spec_id, replay_input.spec.canonical_bytes)
    checked_input = ReplayInput(replay_input.dataset_id, replay_input.normalized_bytes, checked_spec)
    document = checked_protocol.document
    datasets = cast("dict[str, str]", document["datasets"])
    _require(checked_input.dataset_id == datasets["development"], "Queue input differs from the protocol development dataset")
    _equal(checked_spec.spec_id, document["replay_spec_id"], "Queue ReplaySpec differs from the frozen protocol")
    prepared = preflight_replay(checked_input)
    budget = cast("dict[str, int]", document["budget"])
    _require(len(prepared.events) <= min(budget["max_events"], MAX_QUEUE_EVENTS), "Queue input exceeds the declared event budget or software limit")
    strategy = cast("dict[str, object]", checked_spec.document["strategy"])
    execution = cast("dict[str, int]", checked_spec.document["execution"])
    _require(strategy["submit_capture_seq"] == 1 and prepared.events[0].capture_seq == 1, "Declared entry must be the initial capture 1 snapshot")
    _require(execution["insert_latency_ns"] == 0, "Queue qualification requires zero insert latency; acceptance remains unverified")
    target: dict[str, object] = {
        "source": prepared.stream[0], "instrument": prepared.stream[1], "session": prepared.stream[2],
        "side": "bid", "price_ticks": strategy["limit_price_ticks"],
    }
    bindings: dict[str, object] = {
        "protocol_id": checked_protocol.protocol_id,
        "development_dataset_id": checked_input.dataset_id,
        "normalized_sha256": digest(checked_input.normalized_bytes),
        "replay_spec_id": checked_spec.spec_id,
    }
    return checked_protocol, prepared, bindings, target


def _source_constraints(
    document: dict[str, object], prepared: PreparedReplay
) -> tuple[int, dict[int, dict[str, object]]]:
    price = cast("int", cast("dict[str, object]", document["target"])["price_ticks"])
    initial = dict(prepared.events[0].bids).get(price)
    _require(initial is not None and initial > 0, "The initial snapshot must expose the target bid queue")
    _require(cast("int", initial) <= MAX_QUEUE_LOTS, "Initial queue exceeds the software limit")
    updates = {
        cast("int", update["capture_seq"]): update
        for update in cast("list[dict[str, object]]", document["updates"])
    }
    checkpoints = [
        event.capture_seq for event in prepared.events[1:]
        if event.event_type == "delta" and price in dict(event.bids)
    ]
    _equal(list(updates), checkpoints, "Every target-price checkpoint requires exactly one ordered update")
    previous_volume = cast("int", initial)
    pending: list[int] = []
    trade_total = 0
    gross_total = previous_volume
    for event in prepared.events[1:]:
        if event.event_type == "trade":
            _require(event.aggressor_side == "sell" and event.price_ticks == price, "Queue qualification supports only target-price sell trades")
            pending.append(event.capture_seq)
            trade_total += cast("int", event.quantity_lots)
            gross_total += cast("int", event.quantity_lots)
            _require(gross_total <= MAX_QUEUE_LOTS, "Observed queue flow exceeds the software limit")
        elif event.capture_seq in updates:
            update = updates[event.capture_seq]
            _equal(update["trade_capture_seqs"], pending, "Trade references must equal the complete ordered checkpoint interval")
            additions = cast("int", update["additions_lots"])
            cancellations = cast("int", update["cancellations_lots"])
            observed = dict(event.bids)[price]
            expected = previous_volume + additions - cancellations - trade_total
            _require(0 <= expected <= MAX_QUEUE_LOTS and expected == observed, "External queue conservation failed; trades must not be counted twice")
            gross_total += additions + cancellations
            _require(gross_total <= MAX_QUEUE_LOTS, "Total queue flow exceeds the software limit")
            previous_volume = observed
            pending = []
            trade_total = 0
    _require(not pending, "Every target trade requires a later absolute checkpoint; EOF reconciliation is pending")
    return cast("int", initial), updates


def _state(ahead: int, behind: int) -> dict[str, object]:
    return {"ahead_lots": ahead, "behind_lots": behind, "external_lots": ahead + behind}


def _interpretation(
    prepared: PreparedReplay, initial: int, updates: dict[int, dict[str, object]], *, front_first: bool
) -> dict[str, object]:
    ahead, behind = initial, 0
    zero: dict[str, object] = {
        "additions_lots": 0, "cancellations_lots": 0, "trade_lots": 0,
        "cancel_ahead_lots": 0, "cancel_behind_lots": 0,
    }
    entry = prepared.events[0]
    trace: list[dict[str, object]] = [{
        "kind": "declared_entry", "source_ref": entry.source_ref,
        "receive_time_ns": entry.receive_time_ns, "before": None, "flow": dict(zero),
        "after": _state(ahead, behind),
    }]
    for event in prepared.events[1:]:
        before = _state(ahead, behind)
        flow = dict(zero)
        if event.event_type == "trade":
            quantity = cast("int", event.quantity_lots)
            _require(quantity <= ahead + behind, "Target trade exceeds the declared visible external queue")
            consumed_ahead = min(quantity, ahead)
            ahead -= consumed_ahead
            behind -= quantity - consumed_ahead
            flow["trade_lots"] = quantity
            kind = "trade"
        elif event.capture_seq in updates:
            update = updates[event.capture_seq]
            additions, cancellations = (
                cast("int", update["additions_lots"]), cast("int", update["cancellations_lots"])
            )
            behind += additions
            _require(cancellations <= ahead + behind, "Cancellation exceeds the external queue")
            if front_first:
                cancel_ahead = min(cancellations, ahead)
                cancel_behind = cancellations - cancel_ahead
            else:
                cancel_behind = min(cancellations, behind)
                cancel_ahead = cancellations - cancel_behind
            ahead -= cancel_ahead
            behind -= cancel_behind
            flow.update({
                "additions_lots": additions, "cancellations_lots": cancellations,
                "cancel_ahead_lots": cancel_ahead, "cancel_behind_lots": cancel_behind,
            })
            kind = "checkpoint"
        else:
            continue
        _require(ahead >= 0 and behind >= 0 and ahead + behind <= MAX_QUEUE_LOTS, "Queue state is negative or exceeds its software limit")
        trace.append({
            "kind": kind, "source_ref": event.source_ref, "receive_time_ns": event.receive_time_ns,
            "before": before, "flow": flow, "after": _state(ahead, behind),
        })
    return {
        "policy_id": "cancel_front_first_v1" if front_first else "cancel_back_first_v1",
        "trace": trace, "final_state": _state(ahead, behind),
    }


@dataclass(frozen=True, slots=True)
class QueueFeasibilityPair:
    constraint: QueueConstraintSpec
    protocol: ExecutableProtocol
    replay_input: ReplayInput
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require(isinstance(self.constraint, QueueConstraintSpec), "Expected QueueConstraintSpec")
            constraint = QueueConstraintSpec(self.constraint.constraint_id, self.constraint.canonical_bytes)
            _, prepared, bindings, target = _context(self.protocol, self.replay_input)
            document = constraint.document
            _equal(document["bindings"], bindings, "Queue source bindings mismatch")
            _equal(document["target"], target, "Queue target differs from actual source and strategy")
            initial, updates = _source_constraints(document, prepared)
            raw = canonical({
                "kind": "queue_feasibility_pair_v1", "schema_version": 1,
                "constraint_id": constraint.constraint_id, "model_profile_id": PROFILE_ID,
                "bindings": bindings, "target": target,
                "parameter_basis": document["parameter_basis"], "assumptions": document["assumptions"],
                **_FLAGS,
                "source_bindings_verified": True, "flow_conservation_verified": True,
                "interpretations": [
                    _interpretation(prepared, initial, updates, front_first=True),
                    _interpretation(prepared, initial, updates, front_first=False),
                ],
            })
            _require(len(raw) <= _PAIR_LIMIT, "Queue pair exceeds its 2 MiB report limit")
            object.__setattr__(self, "canonical_bytes", raw)
        except (ReplayValidationError, ProtocolValidationError) as error:
            raise QueueConstraintValidationError(str(error)) from error

    @property
    def validation_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, _PAIR_LIMIT)


def build_queue_constraint_spec(
    raw: bytes, *, protocol: ExecutableProtocol, replay_input: ReplayInput
) -> QueueConstraintSpec:
    try:
        request = _document(raw, request=True)
        _, _, bindings, target = _context(protocol, replay_input)
        encoded = canonical({
            **request, "kind": "queue_constraint_spec_v1", "bindings": bindings, "target": target,
            **_FLAGS,
        })
        constraint = QueueConstraintSpec(digest(encoded), encoded)
        validate_queue_constraints(constraint, protocol=protocol, replay_input=replay_input)
        return constraint
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise QueueConstraintValidationError(str(error)) from error


def load_queue_constraint_spec(raw: bytes) -> QueueConstraintSpec:
    """Validate canonical structure and identity; external source is not yet verified."""
    _require(isinstance(raw, bytes) and 0 < len(raw) <= _SPEC_LIMIT, "Queue spec must be immutable bytes within 64 KiB")
    return QueueConstraintSpec(digest(raw), raw)


def validate_queue_constraints(
    constraint: QueueConstraintSpec, *, protocol: ExecutableProtocol, replay_input: ReplayInput
) -> QueueFeasibilityPair:
    return QueueFeasibilityPair(constraint, protocol, replay_input)
