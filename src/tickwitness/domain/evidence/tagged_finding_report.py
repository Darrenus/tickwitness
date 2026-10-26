"""Deterministic conditional findings from a completely reaudited sealed pair.

The report owns no execution permission and certifies no authentic producer.
Standalone parsing checks its frozen rubric; only the full fourteen-artifact
verification re-establishes source/economic semantics. Filesystem publication is
an application concern and is never asserted by this pure domain object.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.tagged_pair_verification import (
    ARTIFACT_ROLES,
    MAX_ASSESSMENT_BYTES,
    PAYLOAD_LIMITS,
    TaggedPairAssessment,
    verify_tagged_pair_artifacts,
)
from tickwitness.domain.replay._validation import exact
from tickwitness.domain.research_contracts.tagged_finding_protocol import (
    FINDING_LIMITATIONS,
    FINDING_REPORT_POLICY,
    FINDING_SCOPE,
    MAX_TAGGED_FINDING_PROTOCOL_BYTES,
    TaggedFindingProtocol,
    load_tagged_finding_protocol,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS

Row = dict[str, object]
MAX_TAGGED_FINDING_REPORT_BYTES = 512 * 1024
FINDING_ARTIFACT_ROLES = ARTIFACT_ROLES | {"finding_protocol", "finding_report"}
_TRUTH_TARGET = "per_interpretation_predicate_truth_given_public_observations_v1"
_FINALIZATION: Row = {
    "source_evidence_state": "CONTENT_CLOSED",
    "report_publication_state": "UNASSERTED",
}
_REPORT_FIELDS = {
    "kind",
    "schema_version",
    "report_policy",
    "finding_protocol",
    "finding_protocol_id",
    "subject_protocol_id",
    "claim_revision_id",
    "source_pair_bundle_id",
    "assessment",
    "assessment_id",
    "evidence_bindings",
    "scope",
    "execution_status",
    "finalization",
    "findings",
    "completeness",
    "limitations",
}


class TaggedFindingIneligibleError(EvidenceValidationError):
    """Valid source pair is retained but does not meet this reporting authority."""

    code = "tagged_finding_ineligible"
    exit_code = 9

    def __init__(self, reason: str, source_pair_bundle_id: str) -> None:
        self.reason = reason
        self.source_pair_bundle_id = source_pair_bundle_id
        super().__init__(
            "Verified tagged evidence is not issuable under this frozen report authority: "
            + reason
            + ". Existing evidence remains unchanged; no finding report is issued."
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _equal(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _pair(artifacts: dict[str, bytes]) -> dict[str, bytes]:
    _require(
        type(artifacts) is dict and artifacts.keys() == ARTIFACT_ROLES,
        "Finding evidence requires the exact twelve source-pair roles",
    )
    limits = {**PAYLOAD_LIMITS, "assessment": MAX_ASSESSMENT_BYTES}
    for role, data in artifacts.items():
        _require(
            type(data) is bytes and 0 < len(data) <= limits[role],
            "Finding source artifact is empty, mutable or oversized: " + role,
        )
    return dict(artifacts)


def tagged_pair_bundle_id(pair_artifacts: dict[str, bytes]) -> str:
    """Compute fixed-envelope identity only; this helper does not audit its payload."""
    artifacts = _pair(pair_artifacts)
    manifest = canonical(
        {
            "kind": "tagged_queue_pair_evidence_bundle_v1",
            "schema_version": 1,
            "scope": "development_tagged_queue_pair_v1",
            "roles": {
                role: {
                    "sha256": digest(data),
                    "size_bytes": len(data),
                    "ref": "objects/sha256/" + digest(data),
                }
                for role, data in artifacts.items()
            },
        }
    )
    return digest(manifest)


def _checked_protocol(protocol: TaggedFindingProtocol) -> TaggedFindingProtocol:
    _require(type(protocol) is TaggedFindingProtocol, "Findings require an actual frozen authority")
    checked = load_tagged_finding_protocol(protocol.canonical_bytes)
    _require(checked.protocol_id == protocol.protocol_id, "Finding authority identity differs")
    return checked


def _scope(protocol: TaggedFindingProtocol, assessment: TaggedPairAssessment, pair_id: str) -> Row:
    source = protocol.subject_protocol
    bindings = cast("Row", source.document["bindings"])
    model = cast("Row", source.document["model"])
    return {
        **FINDING_SCOPE,
        "finding_protocol_id": protocol.protocol_id,
        "subject_protocol_id": source.protocol_id,
        "claim_revision_id": source.claim_revision_id,
        "source_protocol_id": bindings["source_protocol_id"],
        "dataset_id": bindings["development_dataset_id"],
        "normalized_sha256": bindings["normalized_sha256"],
        "gross_constraint_id": bindings["gross_constraint_id"],
        "source_pair_bundle_id": pair_id,
        "assessment_id": assessment.assessment_id,
        "witness_pair_id": assessment.document["witness_pair_id"],
        "model_id": model["model_id"],
        "projection_id": model["projection_id"],
        "intervention_id": model["intervention_id"],
        "evaluated_policy_ids": list(TAGGED_POLICY_IDS),
        "claim_truth_target": "frozen_predicate_per_hidden_allocation_v1",
        "counterexample_quantifier": "for_all_listed_policy_witnesses_v1",
    }


def _witness(run: Row) -> Row:
    return {
        key: run[key]
        for key in (
            "role",
            "policy_id",
            "run_id",
            "attempt_id",
            "attempt_index",
            "intent_id",
            "result_sha256",
            "evaluation_sha256",
            "truth",
        )
    }


def _document(
    protocol: TaggedFindingProtocol,
    assessment: TaggedPairAssessment,
    pair_id: str,
    evidence_bindings: Row,
) -> Row:
    subject = protocol.subject_protocol
    adoc = assessment.document
    _equal(
        adoc["protocol_id"],
        subject.protocol_id,
        "Finding assessment belongs to a different subject",
    )
    _equal(adoc["claim_revision_id"], subject.claim_revision_id, "Finding assessment claim differs")
    pair_bindings = exact(evidence_bindings, set(ARTIFACT_ROLES), "Finding source bindings")
    for value in pair_bindings.values():
        identity(value)
    _equal(
        pair_bindings["protocol"],
        subject.protocol_id,
        "Finding protocol bytes differ from source role",
    )
    _equal(
        pair_bindings["assessment"],
        assessment.assessment_id,
        "Finding assessment bytes differ from source role",
    )
    _equal(
        {role: value for role, value in pair_bindings.items() if role != "assessment"},
        adoc["bindings"],
        "Finding source roles differ from assessment bindings",
    )
    identity(pair_id)
    comparison = cast("Row", adoc["comparison"])
    _require(
        comparison["ineligible_reason"] is None
        and comparison["same_execution_environment"] is True,
        "Finding report requires an eligible controlled pair",
    )
    runs = cast("list[Row]", adoc["runs"])
    _require(
        all(type(run["truth"]) is bool for run in runs),
        "Finding report requires two boolean truths",
    )
    witnesses = [_witness(run) for run in runs]
    false_witnesses = [item for item in witnesses if item["truth"] is False]
    true_witnesses = [item for item in witnesses if item["truth"] is True]
    scope = _scope(protocol, assessment, pair_id)
    findings: list[Row] = []
    if false_witnesses and true_witnesses:
        findings.append(
            {
                "type": "NOT_IDENTIFIABLE_WITHIN_MODEL",
                "scope": scope,
                "conclusion_target": _TRUTH_TARGET,
                "witnesses": witnesses,
                "limitations": list(FINDING_LIMITATIONS),
            }
        )
    if false_witnesses:
        findings.append(
            {
                "type": "COUNTEREXAMPLE_FOUND",
                "scope": scope,
                "conclusion_target": "robust_satisfaction_across_listed_witnesses_v1",
                "witnesses": false_witnesses,
                "limitations": list(FINDING_LIMITATIONS),
            }
        )
    else:
        findings.append(
            {
                "type": "NO_COUNTEREXAMPLE_FOUND",
                "scope": scope,
                "conclusion_target": "robust_satisfaction_across_listed_witnesses_v1",
                "witnesses": witnesses,
                "limitations": list(FINDING_LIMITATIONS),
            }
        )
    return {
        "kind": "tagged_finding_report_v1",
        "schema_version": 1,
        "report_policy": FINDING_REPORT_POLICY,
        "finding_protocol": protocol.document,
        "finding_protocol_id": protocol.protocol_id,
        "subject_protocol_id": subject.protocol_id,
        "claim_revision_id": subject.claim_revision_id,
        "source_pair_bundle_id": pair_id,
        "assessment": adoc,
        "assessment_id": assessment.assessment_id,
        "evidence_bindings": pair_bindings,
        "scope": scope,
        "execution_status": "completed",
        "finalization": dict(_FINALIZATION),
        "findings": findings,
        "completeness": {
            "planned_policy_ids": list(TAGGED_POLICY_IDS),
            "audited_policy_ids": list(TAGGED_POLICY_IDS),
            "eligible_policy_ids": list(TAGGED_POLICY_IDS),
            "coverage_complete_for_listed_policies": True,
            "admissible_world_space_exhausted": False,
            "full_attempt_history_available": False,
            "unexplored_scope": [
                "other_admissible_hidden_allocations",
                "other_datasets_or_claims",
                "real_private_execution_observations",
                "actual_insertion_and_market_impact",
                "confirmation_observations",
                "complete_attempt_history",
            ],
        },
        "limitations": list(FINDING_LIMITATIONS),
    }


@dataclass(frozen=True, slots=True)
class TaggedFindingReport:
    """Content-closed report candidate; publication is unasserted by the domain."""

    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            doc = exact(
                parse(self.canonical_bytes, limit=MAX_TAGGED_FINDING_REPORT_BYTES),
                _REPORT_FIELDS,
                "Tagged finding report",
            )
            protocol = load_tagged_finding_protocol(canonical(cast("Row", doc["finding_protocol"])))
            assessment = TaggedPairAssessment(canonical(cast("Row", doc["assessment"])))
            rebuilt = _document(
                protocol,
                assessment,
                identity(doc["source_pair_bundle_id"]),
                cast("Row", doc["evidence_bindings"]),
            )
            _require(
                canonical(rebuilt) == self.canonical_bytes,
                "Finding report bindings, scope, findings, coverage or encoding differ",
            )
        except EvidenceValidationError:
            raise
        except ValueError as error:
            raise EvidenceValidationError(str(error)) from error

    @property
    def report_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_TAGGED_FINDING_REPORT_BYTES)


def build_tagged_finding_report(
    protocol: TaggedFindingProtocol,
    pair_artifacts: dict[str, bytes],
) -> TaggedFindingReport:
    """Reaudit source and both native witnesses before applying the fixed authority."""
    try:
        checked = _checked_protocol(protocol)
        artifacts = _pair(pair_artifacts)
        verified = verify_tagged_pair_artifacts(artifacts)
        _require(
            artifacts["protocol"] == checked.subject_protocol.canonical_bytes,
            "Finding evidence differs from the full frozen subject protocol",
        )
        assessment = TaggedPairAssessment(artifacts["assessment"])
        pair_id = tagged_pair_bundle_id(artifacts)
        comparison = cast("Row", cast("Row", verified["assessment"])["comparison"])
        reason = comparison["ineligible_reason"]
        if reason is not None:
            raise TaggedFindingIneligibleError(cast("str", reason), pair_id)
        return TaggedFindingReport(
            canonical(
                _document(
                    checked,
                    assessment,
                    pair_id,
                    {role: digest(data) for role, data in artifacts.items()},
                )
            )
        )
    except EvidenceValidationError:
        raise
    except ValueError as error:
        raise EvidenceValidationError(str(error)) from error


def load_tagged_finding_report(raw: bytes) -> TaggedFindingReport:
    return TaggedFindingReport(raw)


def verify_tagged_finding_artifacts(artifacts: dict[str, bytes]) -> TaggedFindingReport:
    """Reconstruct the complete report, including its source twelve-role closure."""
    _require(
        type(artifacts) is dict and artifacts.keys() == FINDING_ARTIFACT_ROLES,
        "Finding package requires exactly fourteen fixed artifact roles",
    )
    _require(
        type(artifacts["finding_protocol"]) is bytes
        and 0 < len(artifacts["finding_protocol"]) <= MAX_TAGGED_FINDING_PROTOCOL_BYTES,
        "Finding protocol bytes exceed their bound",
    )
    _require(
        type(artifacts["finding_report"]) is bytes
        and 0 < len(artifacts["finding_report"]) <= MAX_TAGGED_FINDING_REPORT_BYTES,
        "Finding report bytes exceed their bound",
    )
    try:
        protocol = load_tagged_finding_protocol(artifacts["finding_protocol"])
        expected = build_tagged_finding_report(
            protocol, {role: data for role, data in artifacts.items() if role in ARTIFACT_ROLES}
        )
    except EvidenceValidationError:
        raise
    except ValueError as error:
        raise EvidenceValidationError(str(error)) from error
    _require(
        expected.canonical_bytes == artifacts["finding_report"],
        "Sealed finding report does not reproduce from its authority and source evidence",
    )
    return expected
