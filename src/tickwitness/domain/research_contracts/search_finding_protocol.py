"""Separate frozen authority for a finite conditional stress-search question.

The copied numeric criterion creates a new conditional predicate. It does not
extend the source protocol's claim authority, execution permission or budget.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse
from tickwitness.domain.research_contracts.protocols import (
    ProtocolValidationError,
    _integer,
    _object,
    _parse,
    _text,
)
from tickwitness.domain.search.plans import SearchPlan, load_search_plan

MAX_SEARCH_FINDING_PROTOCOL_BYTES = 3 * 1024 * 1024
FINDING_AUTHORITY_ID = "conditional_stress_search_findings_v1"
FINDING_REPORT_POLICY = "scoped_stress_search_findings_v1"
FINDING_TYPES = ("COUNTEREXAMPLE_FOUND", "NO_COUNTEREXAMPLE_FOUND", "NOT_EVALUABLE")
FINDING_SCOPE: dict[str, object] = {
    "phase": "development",
    "scenario_kind": "COUNTERFACTUAL_STRESS",
    "calibration_status": "uncalibrated",
    "predicate_scope": "frozen_eligible_candidate_set_v1",
    "source_claim_evaluated": False,
    "continuous_delay_space_exhausted": False,
    "confirmation_accessed": False,
    "market_probability_inferred": False,
    "future_returns_guaranteed": False,
    "preregistration_verified": False,
    "author_signature_verified": False,
    "human_domain_approval_verified": False,
    "full_trial_history_certified": False,
}
FINDING_LIMITATIONS = (
    "criterion_copied_from_source_claim_is_a_new_conditional_stress_predicate",
    "uncalibrated_stress_is_not_actual_history_or_a_market_probability_model",
    "no_baseline_truth_or_baseline_flip_is_issued",
    "finite_proposals_do_not_exhaust_continuous_delay_space",
    "duplicate_and_rejected_proposals_are_not_evaluated_coverage",
    "no_counterexample_applies_only_to_the_explicit_audited_subset",
    "budget_stop_does_not_make_an_unassessed_candidate_true",
    "content_consistency_is_not_source_or_ledger_reaudit",
    "reporting_authority_is_not_verified_preregistration",
    "original_budget_is_shared_and_never_extended_or_refunded",
    "portable_sealed_search_evidence_is_not_issued",
    "runtime_environment_not_harmonized",
    "no_delay_only_causal_attribution",
)
FINDING_RULES: dict[str, object] = {
    "terminal_false_witness": "COUNTEREXAMPLE_FOUND",
    "nonempty_all_true_clean_completion_or_budget_stop": "NO_COUNTEREXAMPLE_FOUND",
    "valid_but_unknown_empty_failed_unfinalized": "NOT_EVALUABLE",
    "invalid_evidence": "validation_error_never_a_finding_v1",
    "false_witness_dominates_later_operational_failure": True,
    "outer_terminal_required": True,
    "partial_no_counterexample_never_asserts_full_predicate": True,
}
_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "title",
        "plan",
        "bindings",
        "predicate",
        "predicate_id",
        "authority",
        "report_policy",
        "scope",
        "rules",
        "limitations",
    }
)


class SearchFindingValidationError(ProtocolValidationError):
    """A reporting authority differs from its exact frozen conditional profile."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SearchFindingValidationError(message)


def _checked_plan(plan: SearchPlan) -> SearchPlan:
    _require(type(plan) is SearchPlan, "Finding authority requires an actual SearchPlan")
    checked = load_search_plan(plan.canonical_bytes)
    _require(checked.plan_id == plan.plan_id, "Finding plan identity differs from content")
    return checked


def _document(title: object, plan: SearchPlan) -> dict[str, object]:
    checked = _checked_plan(plan)
    source = checked.document
    protocol = cast("dict[str, object]", source["protocol"])
    claim = cast("dict[str, object]", protocol["claim"])
    assumptions = cast("dict[str, object]", source["assumptions"])
    binding = cast("dict[str, object]", assumptions["bindings"])
    criterion = {key: claim[key] for key in ("metric", "comparator", "threshold", "unit")}
    _require(criterion["unit"] == "USD", "Conditional stress criterion requires USD")
    predicate: dict[str, object] = {
        "kind": "conditional_stress_predicate_v1",
        "criterion_origin": "source_claim_numeric_criterion_only_v1",
        "criterion": criterion,
        "quantifier": "for_all_frozen_eligible_candidates_v1",
        "plan_id": checked.plan_id,
        "scope": dict(FINDING_SCOPE),
    }
    return {
        "kind": "search_finding_protocol_v1",
        "schema_version": 1,
        "title": _text(title, "search finding title", 200),
        "plan": source,
        "bindings": {
            "plan_id": checked.plan_id,
            "source_protocol_id": source["protocol_id"],
            "source_claim_revision_id": protocol["claim_revision_id"],
            "assumption_id": source["assumption_id"],
            "development_dataset_id": binding["development_dataset_id"],
            "source_normalized_sha256": binding["normalized_sha256"],
            "replay_spec_id": protocol["replay_spec_id"],
        },
        "predicate": predicate,
        "predicate_id": digest(canonical(predicate)),
        "authority": {
            "id": FINDING_AUTHORITY_ID,
            "allowed_outcomes": list(FINDING_TYPES),
            "source_claim_authority_granted": False,
            "execution_authority_extended": False,
            "budget_owner_changed": False,
        },
        "report_policy": FINDING_REPORT_POLICY,
        "scope": dict(FINDING_SCOPE),
        "rules": dict(FINDING_RULES),
        "limitations": list(FINDING_LIMITATIONS),
    }


def _validated(raw: bytes) -> dict[str, object]:
    value = _object(
        parse(raw, limit=MAX_SEARCH_FINDING_PROTOCOL_BYTES), _FIELDS, "Search finding protocol"
    )
    plan = load_search_plan(canonical(cast("dict[str, object]", value["plan"])))
    expected = _document(value["title"], plan)
    _require(canonical(expected) == raw, "Finding authority, predicate, bindings or scope differ")
    return expected


@dataclass(frozen=True, slots=True)
class SearchFindingProtocol:
    protocol_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated(self.canonical_bytes)
            _require(
                identity(self.protocol_id) == digest(self.canonical_bytes),
                "Finding protocol identity mismatch",
            )
        except ValueError as error:
            raise SearchFindingValidationError(str(error)) from error

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=MAX_SEARCH_FINDING_PROTOCOL_BYTES)

    @property
    def plan(self) -> SearchPlan:
        return load_search_plan(canonical(cast("dict[str, object]", self.document["plan"])))


def load_search_finding_protocol(raw: bytes) -> SearchFindingProtocol:
    try:
        return SearchFindingProtocol(digest(raw), raw)
    except ValueError as error:
        raise SearchFindingValidationError(str(error)) from error


def build_search_finding_protocol(raw: bytes, *, plan: SearchPlan) -> SearchFindingProtocol:
    try:
        request = _object(
            _parse(raw, max_bytes=16 * 1024),
            frozenset({"kind", "schema_version", "title", "authority"}),
            "Search finding request",
        )
        _require(
            request["kind"] == "search_finding_request_v1", "Unsupported search finding request"
        )
        _integer(request["schema_version"], "schema_version", 1, 1)
        _require(
            request["authority"] == FINDING_AUTHORITY_ID, "Unsupported search finding authority"
        )
        encoded = canonical(_document(request["title"], plan))
        _require(
            len(encoded) <= MAX_SEARCH_FINDING_PROTOCOL_BYTES,
            "Search finding protocol exceeds byte bound",
        )
        return SearchFindingProtocol(digest(encoded), encoded)
    except ValueError as error:
        raise SearchFindingValidationError(str(error)) from error
