"""Recompute a reduced witness's original numeric criterion without extending it.

The original finding and predicate are provenance. This assessment does not
rewrite their candidate domain or evaluate a baseline/source-claim verdict.
Actual source and committed-ledger reinspection belong to the application.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import cast

from tickwitness.domain.evidence.reduction_records import (
    ReductionRunReceipt,
    ReductionStateAudit,
    build_reduction_intent,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.domain.reduction.contracts import MaterializedReduction
from tickwitness.domain.replay.contracts import ReplayResult, load_replay_result
from tickwitness.domain.research_contracts.search_finding_protocol import (
    SearchFindingProtocol,
    load_search_finding_protocol,
)

MAX_REDUCTION_PRESERVATION_BYTES = 128 * 1024
PRESERVATION_SCOPE: Mapping[str, object] = MappingProxyType(
    {
        "phase": "development",
        "authority": "original_false_witness_numeric_criterion_v1",
        "source_claim_evaluated": False,
        "baseline_truth_evaluated": False,
        "original_finding_rewritten": False,
        "original_predicate_domain_extended": False,
        "budget_owner_changed": False,
        "global_minimum_verified": False,
        "local_minimum_verified": False,
        "checkpoint_resume_verified": False,
        "global_ledger_authenticity_verified": False,
        "author_signature_verified": False,
        "human_domain_approval_verified": False,
        "confirmation_accessed": False,
    }
)
type Row = dict[str, object]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _same(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _checked_authority(
    authority: SearchFindingProtocol, materialized: MaterializedReduction
) -> SearchFindingProtocol:
    _require(type(authority) is SearchFindingProtocol, "Preservation requires a frozen authority")
    checked = load_search_finding_protocol(authority.canonical_bytes)
    _require(checked.protocol_id == authority.protocol_id, "Finding authority identity differs")
    source = materialized.source
    _same(
        [source.finding_protocol_id, source.predicate_id],
        [checked.protocol_id, checked.document["predicate_id"]],
        "Preservation source belongs to another finding or predicate",
    )
    plan = checked.plan.document
    validated = source.validation
    _same(plan["protocol"], validated.protocol.document, "Preservation protocol differs")
    _same(plan["assumptions"], validated.assumptions.document, "Preservation assumptions differ")
    bindings = cast("Row", checked.document["bindings"])
    _same(
        [
            bindings["development_dataset_id"],
            bindings["source_normalized_sha256"],
            bindings["replay_spec_id"],
        ],
        [
            validated.replay_input.dataset_id,
            digest(validated.replay_input.normalized_bytes),
            validated.replay_input.spec.spec_id,
        ],
        "Preservation source input differs from the original authority",
    )
    proposals = [
        row
        for row in cast("list[Row]", plan["journal"])
        if row["ordinal"] == source.witness_ordinal
    ]
    _require(
        len(proposals) == 1
        and proposals[0]["status"] == "ELIGIBLE"
        and proposals[0]["scenario_id"] == validated.scenario.scenario_id,
        "Preservation source is not the selected original eligible witness",
    )
    return checked


def _observation(criterion: Row, evaluation: Row) -> Row:
    eligible = (
        evaluation["execution_status"] == "completed"
        and evaluation["valuation_status"] == "valued"
    )
    _same(
        [criterion["metric"], criterion["unit"], evaluation["unit"]],
        ["net_marked_pnl_v1", "USD", "USD"],
        "Preservation metric profile differs",
    )
    value: str | None = None
    truth: bool | None = None
    if eligible:
        raw_value = cast("Row", evaluation["valuation"])["net_marked_pnl"]
        _require(isinstance(raw_value, str), "Audited valuation has no exact numeric value")
        value = cast("str", raw_value)
        actual, threshold = Fraction(value), Fraction(cast("str", criterion["threshold"]))
        truth = {
            "gt": actual > threshold,
            "ge": actual >= threshold,
            "lt": actual < threshold,
            "le": actual <= threshold,
        }[cast("str", criterion["comparator"])]
    return {
        "eligible": eligible,
        "truth": truth,
        "value": value,
        **criterion,
        "reason": None if eligible else evaluation["ineligibility_reason"],
    }


@dataclass(frozen=True, slots=True)
class ReductionPreservationAssessment:
    authority: SearchFindingProtocol
    materialized: MaterializedReduction
    receipt: ReductionRunReceipt
    result: ReplayResult
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require(
                type(self.materialized) is MaterializedReduction
                and type(self.receipt) is ReductionRunReceipt
                and type(self.result) is ReplayResult,
                "Preservation needs actual materialization, committed receipt and raw result",
            )
            receipt = load_reduction_run_receipt(self.receipt.canonical_bytes)
            _require(receipt.run_id == self.receipt.run_id, "Reduction run identity differs")
            result = load_replay_result(self.result.canonical_bytes)
            audit = ReductionStateAudit(self.materialized, result)
            materialized = audit.materialized
            authority = _checked_authority(self.authority, materialized)
            intent = build_reduction_intent(materialized)
            document = receipt.document
            _same(document["intent"], intent.document, "Preservation receipt intent differs")
            _same(
                [document["protocol_id"], document["claim_revision_id"]],
                [intent.document["protocol_id"], intent.document["claim_revision_id"]],
                "Preservation receipt original owner differs",
            )
            _same(
                document["execution_status"],
                result.document["execution_status"],
                "Preservation receipt status differs from the actual result",
            )
            _same(
                document["bindings"],
                {
                    "replay_result_sha256": digest(result.canonical_bytes),
                    "state_audit_sha256": audit.audit_id,
                },
                "Preservation result or state-audit binding differs",
            )
            raw_attempt = canonical(cast("Row", document["attempt"]))
            attempt = AttemptReservation(digest(raw_attempt), raw_attempt)
            protocol = materialized.source.validation.protocol
            budget = cast("Row", protocol.document["budget"])
            _require(
                attempt.attempt_index <= cast("int", budget["max_attempts"])
                and attempt.document["max_wall_seconds"] == budget["max_wall_seconds"],
                "Preservation attempt differs from the original budget",
            )
            evaluation = cast("Row", audit.document["replay_evaluation"])
            _same(
                evaluation["evaluation_policy"],
                protocol.document["evaluation_policy"],
                "Preservation valuation policy differs from the original protocol",
            )
            criterion = cast("Row", cast("Row", authority.document["predicate"])["criterion"])
            observation = _observation(criterion, evaluation)
            truth = observation["truth"]
            outcome = "NOT_EVALUABLE"
            if truth is not None:
                outcome = "NOT_PRESERVED" if truth is True else "PRESERVED"
            source = materialized.source
            bindings = cast("Row", intent.document["bindings"])
            raw = canonical(
                {
                    "kind": "reduction_preservation_assessment_v1",
                    "schema_version": 1,
                    "outcome": outcome,
                    "criterion_observation": observation,
                    "source": {
                        "bundle_id": source.bundle_id,
                        "report_id": source.report_id,
                        "finding_protocol_id": authority.protocol_id,
                        "predicate_id": source.predicate_id,
                        "protocol_id": protocol.protocol_id,
                        "claim_revision_id": protocol.claim_revision_id,
                        "witness_ordinal": source.witness_ordinal,
                        "witness_run_id": source.source_run_id,
                    },
                    "candidate": {
                        "run_id": receipt.run_id,
                        "intent_id": intent.intent_id,
                        "attempt_id": attempt.attempt_id,
                        "preparation_id": bindings["preparation_id"],
                        "recipe_id": materialized.recipe.recipe_id,
                        "prefix_context_id": materialized.document["prefix_context_id"],
                        "replay_result_sha256": digest(result.canonical_bytes),
                        "state_audit_sha256": audit.audit_id,
                    },
                    "scope": dict(PRESERVATION_SCOPE),
                }
            )
            parse(raw, limit=MAX_REDUCTION_PRESERVATION_BYTES)
            object.__setattr__(self, "authority", authority)
            object.__setattr__(self, "materialized", materialized)
            object.__setattr__(self, "receipt", receipt)
            object.__setattr__(self, "result", result)
            object.__setattr__(self, "canonical_bytes", raw)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise EvidenceValidationError("Cannot assess reduced witness: " + str(error)) from error

    @property
    def assessment_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_REDUCTION_PRESERVATION_BYTES)
