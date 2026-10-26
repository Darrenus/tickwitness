"""Candidate predicates for fixed semantic qualification, never production findings.

An observation can only be constructed from re-audited immutable execution
evidence. Its Boolean is a diagnostic for the explicit shadow marking policy;
it does not evaluate the source claim or certify observation compatibility.
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import cast

from tickwitness.domain.evidence.evaluation import (
    EvaluationValidationError,
    _decimal,
    _money,
    _number,
)
from tickwitness.domain.evidence.queue_evaluation import evaluate_queue_replay
from tickwitness.domain.replay._validation import (
    ReplayValidationError,
    canonical,
    decimal,
    digest,
    exact,
    integer,
    parse,
)
from tickwitness.domain.replay.queue_contracts import QueueReplayInput, QueueReplayResult

_LIMIT = 16 * 1024
_OBSERVATION_LIMIT = 128 * 1024
_POLICY = "qualification_flat_zero_last_visible_bid_v1"
_FIELDS = {
    "kind", "schema_version", "purpose", "metric", "unit", "comparator", "threshold",
    "evaluation_policy",
}
_SCOPE: dict[str, object] = {
    "purpose": "semantic_qualification_only",
    "scenario_kind": "MODEL_SENSITIVITY",
    "observation_scope": "finite_shadow_diagnostic",
    "source_claim_evaluated": False,
    "finding_issued": False,
    "observation_compatibility_certified": False,
    "production_use_approved": False,
}


class QualificationPredicateValidationError(EvaluationValidationError):
    """A candidate predicate or diagnostic pair violates its qualification scope."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationPredicateValidationError(message)


def _document(raw: bytes) -> dict[str, object]:
    document = exact(parse(raw, _LIMIT), _FIELDS, "Qualification predicate")
    integer(document["schema_version"], "schema_version", 1, 1)
    _require(document["kind"] == "queue_qualification_predicate_v1", "Unsupported predicate kind")
    _require(document["purpose"] == "semantic_qualification_only", "Predicate is qualification-only")
    _require(document["metric"] == "net_marked_pnl_v1" and document["unit"] == "USD",
             "Only the explicit USD marked diagnostic is supported")
    _require(document["comparator"] in ("gt", "ge", "lt", "le"), "Unsupported predicate comparator")
    threshold = decimal(document["threshold"], "threshold", precision=18)
    _require(threshold == document["threshold"], "Predicate threshold must be canonical decimal text")
    _require(document["evaluation_policy"] == _POLICY, "Unsupported qualification valuation policy")
    return document


@dataclass(frozen=True, slots=True)
class QualificationPredicate:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            document = _document(self.canonical_bytes)
            _require(canonical(document) == self.canonical_bytes, "Predicate bytes must be canonical")
        except ReplayValidationError as error:
            raise QualificationPredicateValidationError(str(error)) from error

    @property
    def predicate_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, _LIMIT)


def build_qualification_predicate(raw: bytes) -> QualificationPredicate:
    try:
        return QualificationPredicate(canonical(_document(raw)))
    except ReplayValidationError as error:
        raise QualificationPredicateValidationError(str(error)) from error


def load_qualification_predicate(raw: bytes) -> QualificationPredicate:
    return QualificationPredicate(raw)


def _valuation(replay_input: QueueReplayInput, result: QueueReplayResult,
               audit: dict[str, object]) -> dict[str, object]:
    prepared = replay_input.prepared
    instrument = cast("dict[str, object]", prepared.spec.document["instrument"])
    price_increment = _number(instrument["price_increment"], "price increment")
    size_increment = _number(instrument["size_increment"], "size increment")
    bids: dict[int, int] = {}
    mark_ref: dict[str, object] | None = None
    for event in prepared.events:
        if event.event_type == "trade":
            continue
        for price, quantity in event.bids:
            if quantity:
                bids[price] = quantity
            else:
                bids.pop(price, None)
        mark_ref = event.source_ref
    _require(bool(bids) and mark_ref is not None, "Qualification requires a final visible bid")
    ticks = max(bids)
    mark = ticks * price_increment
    quantity_lots = cast("int", audit["filled_quantity_lots"])
    quantity = quantity_lots * size_increment
    notional = Fraction(0)
    total_lots = 0
    for row in cast("list[dict[str, object]]", result.document["fill_trace"]):
        fields = cast("dict[str, object]", row["fields"])
        lots = cast("int", fields["quantity_lots"])
        notional += cast("int", fields["price_ticks"]) * price_increment * lots * size_increment
        total_lots += lots
    _require(total_lots == quantity_lots, "Qualification notional differs from audited position")
    fees = _money(audit["actual_commission"], "audited actual commission", nonnegative=True)
    if not total_lots:
        _require(notional == fees == quantity == 0, "Flat-zero policy requires no fills, position or fees")
    marked = mark * quantity
    return {
        "policy": _POLICY,
        "mark": {
            "source_ref": mark_ref, "price_ticks": ticks, "price": _decimal(mark),
            "derivation": "final_reconstructed_book_at_last_book_input",
        },
        "filled_quantity_lots": total_lots,
        "physical_quantity": _decimal(quantity),
        "fill_notional": _decimal(notional),
        "actual_commission": _decimal(fees),
        "marked_position_value": _decimal(marked),
        "net_marked_pnl": _decimal(marked - notional - fees),
        "mark_liquidity_checked": False,
        "realized_pnl": False,
    }


@dataclass(frozen=True, slots=True)
class QualificationPredicateObservation:
    replay_input: QueueReplayInput
    result: QueueReplayResult
    predicate: QualificationPredicate
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        _require(type(self.replay_input) is QueueReplayInput and type(self.result) is QueueReplayResult,
                 "Predicate observation requires actual immutable queue evidence")
        _require(type(self.predicate) is QualificationPredicate, "Expected a frozen candidate predicate")
        predicate = load_qualification_predicate(self.predicate.canonical_bytes)
        audit = evaluate_queue_replay(self.replay_input, self.result)
        document = audit.document
        ambiguous = bool(document["ambiguous_fee_fill_ordinals"])
        valuation = None if ambiguous else _valuation(self.replay_input, self.result, document)
        value: str | None = None
        satisfied: bool | None = None
        if valuation is not None:
            value = cast("str", valuation["net_marked_pnl"])
            number = Fraction(value)
            threshold = Fraction(cast("str", predicate.document["threshold"]))
            satisfied = {
                "gt": number > threshold, "ge": number >= threshold,
                "lt": number < threshold, "le": number <= threshold,
            }[cast("str", predicate.document["comparator"])]
        encoded = canonical({
            "kind": "queue_qualification_predicate_observation_v1", "schema_version": 1,
            "predicate_id": predicate.predicate_id, "predicate": predicate.document,
            "bindings": self.replay_input.bindings,
            "replay_result_sha256": digest(self.result.canonical_bytes),
            "evaluation_sha256": audit.evaluation_id,
            "scope": dict(_SCOPE), "eligible": not ambiguous, "satisfied": satisfied,
            "value": value, "reason": "ambiguous_native_fee_quantization" if ambiguous else "eligible",
            "valuation": valuation, "audit": document, "findings": [],
        })
        _require(len(encoded) <= _OBSERVATION_LIMIT, "Qualification observation exceeds its byte bound")
        object.__setattr__(self, "canonical_bytes", encoded)

    @property
    def observation_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, _OBSERVATION_LIMIT)


def qualify_predicate(replay_input: QueueReplayInput, result: QueueReplayResult,
                      predicate: QualificationPredicate) -> QualificationPredicateObservation:
    return QualificationPredicateObservation(replay_input, result, predicate)


def compare_qualification_predicates(front: QualificationPredicateObservation,
                                    back: QualificationPredicateObservation) -> dict[str, object]:
    observations = (front, back)
    checked: list[QualificationPredicateObservation] = []
    for observation in observations:
        _require(type(observation) is QualificationPredicateObservation,
                 "Pairing requires re-auditable observations, not supplied truth flags")
        rebuilt = qualify_predicate(observation.replay_input, observation.result, observation.predicate)
        _require(rebuilt.canonical_bytes == observation.canonical_bytes,
                 "Qualification observation identity differs from recomputation")
        checked.append(rebuilt)
    left, right = checked
    _require(left.predicate.canonical_bytes == right.predicate.canonical_bytes,
             "Diagnostic pair predicates differ")
    _require(left.replay_input.family.canonical_bytes == right.replay_input.family.canonical_bytes,
             "Diagnostic pair frozen families differ")
    _require(left.replay_input.normalized_bytes == right.replay_input.normalized_bytes,
             "Diagnostic pair source bytes differ")
    _require(canonical(cast("dict[str, object]", left.result.document["environment"]))
             == canonical(cast("dict[str, object]", right.result.document["environment"])),
             "Diagnostic pair execution environments differ")
    _require((left.replay_input.policy_id, right.replay_input.policy_id)
             == ("cancel_front_first_v1", "cancel_back_first_v1"),
             "Diagnostic pair requires the frozen front/back order")
    documents = [left.document, right.document]
    eligible = all(document["eligible"] is True for document in documents)
    status = (
        "DIAGNOSTIC_PREDICATE_NOT_EVALUABLE" if not eligible
        else "DIAGNOSTIC_PREDICATE_DISAGREEMENT"
        if documents[0]["satisfied"] is not documents[1]["satisfied"]
        else "DIAGNOSTIC_PREDICATE_AGREEMENT"
    )
    return {
        "kind": "queue_qualification_predicate_pair_v1", "schema_version": 1,
        "predicate_id": left.predicate.predicate_id,
        "observation_ids": [left.observation_id, right.observation_id],
        "family_id": left.replay_input.family_id, "scope": dict(_SCOPE),
        "diagnostic_status": status, "observations": documents,
        "findings": [], "promotion_approved": False,
    }
