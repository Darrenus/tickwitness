"""Separate frozen authority for conditional findings from sealed tagged witnesses.

This reporting contract never changes its embedded execution protocol. It owns
only a fixed finite-policy question and deterministic reporting rules; source
claim authority, historical ownership and cryptographic authorship stay absent.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.replay._validation import (
    ReplayValidationError,
    canonical,
    digest,
    exact,
    integer,
    parse,
    text,
)
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TAGGED_POLICY_IDS,
    TaggedQueueProtocol,
    load_tagged_queue_protocol,
)

MAX_TAGGED_FINDING_PROTOCOL_BYTES = 512 * 1024
FINDING_AUTHORITY_ID = "conditional_tagged_findings_v1"
FINDING_REPORT_POLICY = "tagged_finding_report_v1"
FINDING_EVIDENCE_POLICY = "sealed_tagged_pair_offline_audit_v1"
FINDING_TYPES = (
    "NOT_IDENTIFIABLE_WITHIN_MODEL",
    "COUNTEREXAMPLE_FOUND",
    "NO_COUNTEREXAMPLE_FOUND",
)
FINDING_SCOPE: dict[str, object] = {
    "phase": "development",
    "scenario_kind": "CONDITIONAL_TAGGED_INTERPRETATION",
    "observation_scope": "finite_path_conditional_tagged_reconstruction",
    "predicate_scope": "listed_frozen_policy_witnesses_only",
    "claim_truth_target": "frozen_predicate_per_hidden_allocation_v1",
    "invariance_test": "opposite_truth_witnesses_same_public_projection_v1",
    "counterexample_quantifier": "for_all_listed_policy_witnesses_v1",
    "source_claim_evaluated": False,
    "historical_owner_verified": False,
    "literal_order_insertion": False,
    "market_impact_verified": False,
    "author_signature_verified": False,
    "human_domain_approval_verified": False,
    "preregistration_verified": False,
    "full_attempt_history_verified": False,
    "admissible_world_space_exhausted": False,
    "statistical_inference_issued": False,
}
FINDING_LIMITATIONS = (
    "conditional_already_displayed_tagged_participant_only",
    "gross_flow_declarations_are_researcher_defined_and_uncalibrated",
    "public_projection_excludes_simulated_private_fills_and_post_horizon_cleanup",
    "no_actual_private_execution_observations_verified",
    "two_listed_policies_do_not_exhaust_all_admissible_worlds",
    "inventory_mark_is_not_a_liquidation_or_future_return_guarantee",
    "no_original_ledger_commitment_or_full_attempt_history_certification",
    "content_identity_is_not_author_or_human_domain_approval",
    "report_contract_is_not_verified_preregistration",
    "counterexamples_refute_conditional_listed_witness_robustness_not_actual_history",
)
FINDING_RULES: dict[str, object] = {
    "false_false": ["COUNTEREXAMPLE_FOUND"],
    "false_true": ["NOT_IDENTIFIABLE_WITHIN_MODEL", "COUNTEREXAMPLE_FOUND"],
    "true_false": ["NOT_IDENTIFIABLE_WITHIN_MODEL", "COUNTEREXAMPLE_FOUND"],
    "true_true": ["NO_COUNTEREXAMPLE_FOUND"],
    "ineligible_pair": "refuse_issuance_preserve_existing_evidence_v1",
    "invalid_or_incomplete_evidence": "validation_error_never_a_finding_v1",
}
_FIELDS = {
    "kind",
    "schema_version",
    "title",
    "subject_protocol",
    "bindings",
    "authority",
    "policies",
    "evidence_policy",
    "report_policy",
    "scope",
    "rules",
    "limitations",
}
_REQUEST_MAX_BYTES = 16 * 1024


class TaggedFindingValidationError(ProtocolValidationError):
    """A reporting authority violates its exact frozen conditional profile."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TaggedFindingValidationError(message)


def _checked_subject(subject: TaggedQueueProtocol) -> TaggedQueueProtocol:
    _require(
        type(subject) is TaggedQueueProtocol, "Finding authority requires an actual tagged protocol"
    )
    checked = load_tagged_queue_protocol(subject.canonical_bytes)
    _require(
        checked.protocol_id == subject.protocol_id, "Finding subject identity differs from content"
    )
    return checked


def _document(title: object, subject: TaggedQueueProtocol) -> dict[str, object]:
    checked = _checked_subject(subject)
    original = checked.document
    source_bindings = cast("dict[str, str]", original["bindings"])
    return {
        "kind": "tagged_finding_protocol_v1",
        "schema_version": 1,
        "title": text(title, "finding report title", 200),
        "subject_protocol": original,
        "bindings": {
            "subject_protocol_id": checked.protocol_id,
            "claim_revision_id": checked.claim_revision_id,
            "source_protocol_id": source_bindings["source_protocol_id"],
            "dataset_id": source_bindings["development_dataset_id"],
            "normalized_sha256": source_bindings["normalized_sha256"],
            "gross_constraint_id": source_bindings["gross_constraint_id"],
            "replay_spec_id": source_bindings["replay_spec_id"],
        },
        "authority": {
            "id": FINDING_AUTHORITY_ID,
            "question": "per_interpretation_truth_and_listed_witness_robustness_v1",
            "truth_target": "frozen_predicate_per_hidden_allocation_v1",
            "invariance_test": "opposite_truth_witnesses_same_public_projection_v1",
            "counterexample_quantifier": "for_all_listed_policy_witnesses_v1",
            "allowed_finding_types": list(FINDING_TYPES),
            "eligibility": "verified_complete_same_environment_boolean_pair_v1",
            "execution_authority_extended": False,
            "source_claim_authority_granted": False,
        },
        "policies": list(TAGGED_POLICY_IDS),
        "evidence_policy": FINDING_EVIDENCE_POLICY,
        "report_policy": FINDING_REPORT_POLICY,
        "scope": dict(FINDING_SCOPE),
        "rules": dict(FINDING_RULES),
        "limitations": list(FINDING_LIMITATIONS),
    }


def _validated(raw: bytes) -> dict[str, object]:
    try:
        document = exact(
            parse(raw, MAX_TAGGED_FINDING_PROTOCOL_BYTES), _FIELDS, "Tagged finding protocol"
        )
        subject = load_tagged_queue_protocol(
            canonical(cast("dict[str, object]", document["subject_protocol"]))
        )
        rebuilt = _document(document["title"], subject)
        _require(
            canonical(rebuilt) == raw,
            "Finding authority, bindings, rules, scope or encoding differ",
        )
        return rebuilt
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise TaggedFindingValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class TaggedFindingProtocol:
    protocol_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validated(self.canonical_bytes)
        _require(
            self.protocol_id == digest(self.canonical_bytes), "Finding protocol identity mismatch"
        )

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, MAX_TAGGED_FINDING_PROTOCOL_BYTES)

    @property
    def subject_protocol(self) -> TaggedQueueProtocol:
        return load_tagged_queue_protocol(
            canonical(cast("dict[str, object]", self.document["subject_protocol"]))
        )


def load_tagged_finding_protocol(raw: bytes) -> TaggedFindingProtocol:
    _validated(raw)
    return TaggedFindingProtocol(digest(raw), raw)


def build_tagged_finding_protocol(
    raw: bytes, *, subject_protocol: TaggedQueueProtocol
) -> TaggedFindingProtocol:
    try:
        request = exact(
            parse(raw, _REQUEST_MAX_BYTES),
            {"kind", "schema_version", "title", "authority"},
            "Tagged finding request",
        )
        _require(request["kind"] == "tagged_finding_request_v1", "Unsupported finding request")
        integer(request["schema_version"], "schema_version", 1, 1)
        _require(request["authority"] == FINDING_AUTHORITY_ID, "Unsupported finding authority")
        encoded = canonical(_document(request["title"], subject_protocol))
        _require(
            len(encoded) <= MAX_TAGGED_FINDING_PROTOCOL_BYTES, "Finding protocol exceeds byte bound"
        )
        return TaggedFindingProtocol(digest(encoded), encoded)
    except (ReplayValidationError, ProtocolValidationError) as error:
        raise TaggedFindingValidationError(str(error)) from error
