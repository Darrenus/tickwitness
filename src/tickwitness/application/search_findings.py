"""Separate stress conclusions from actual, read-only bounded-campaign audits.

The reporting authority freezes a numeric criterion, not execution permission or
verified preregistration. No application entry point accepts caller-supplied JSON
as a substitute for the source/plan/ledger inspector.
"""

from collections.abc import Callable
from typing import Protocol

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_planning import SearchPlanReader
from tickwitness.domain.evidence.run_records import identity
from tickwitness.domain.evidence.search_finding_report import build_search_finding_report
from tickwitness.domain.research_contracts.search_finding_protocol import (
    SearchFindingProtocol,
    SearchFindingValidationError,
    build_search_finding_protocol,
    load_search_finding_protocol,
)
from tickwitness.domain.search.plans import load_search_plan


class SearchFindingReader(Protocol):
    def get(self, protocol_id: str) -> SearchFindingProtocol: ...


class SearchFindingRepository(SearchFindingReader, Protocol):
    def freeze(self, protocol: SearchFindingProtocol) -> bool: ...


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Search findings permit development evidence only")


def _authority(protocol_id: str, reader: SearchFindingReader) -> SearchFindingProtocol:
    record = reader.get(protocol_id)
    if type(record) is not SearchFindingProtocol:
        raise SearchFindingValidationError("Registry did not return an actual finding authority")
    checked = load_search_finding_protocol(record.canonical_bytes)
    if record.protocol_id != protocol_id or checked.protocol_id != protocol_id:
        raise SearchFindingValidationError("Finding registry returned a different authority")
    return checked


def freeze_search_finding_protocol(
    plan_id: str,
    request: bytes,
    *,
    split: str,
    plans_factory: Callable[[], SearchPlanReader],
    findings_factory: Callable[[], SearchFindingRepository],
) -> dict[str, object]:
    _development(split)
    identity(plan_id)
    record = plans_factory().get(plan_id)
    plan = load_search_plan(record.canonical_bytes)
    if record.plan_id != plan_id or plan.plan_id != plan_id:
        raise SearchFindingValidationError("Finding subject differs from the requested plan")
    authority = build_search_finding_protocol(request, plan=plan)
    repository = findings_factory()
    created = repository.freeze(authority)
    if type(created) is not bool:
        raise SearchFindingValidationError("Finding publication returned an invalid created flag")
    committed = _authority(authority.protocol_id, repository)
    if committed.canonical_bytes != authority.canonical_bytes:
        raise SearchFindingValidationError("Published finding authority differs from the request")
    return {
        "kind": "search_finding_protocol_receipt_v1",
        "schema_version": 1,
        "protocol_id": authority.protocol_id,
        "created": created,
        "protocol": authority.document,
        "verification": {
            "authority_recomputed": True,
            "plan_declaration_recomputed": True,
            "source_revalidated": False,
            "native_replayed": False,
            "attempt_reserved": False,
            "preregistration_verified": False,
        },
    }


def inspect_search_finding_protocol(
    protocol_id: str,
    *,
    split: str,
    findings_factory: Callable[[], SearchFindingReader],
) -> dict[str, object]:
    _development(split)
    identity(protocol_id)
    authority = _authority(protocol_id, findings_factory())
    return {
        "kind": "search_finding_protocol_receipt_v1",
        "schema_version": 1,
        "protocol_id": authority.protocol_id,
        "created": False,
        "protocol": authority.document,
        "verification": {
            "authority_recomputed": True,
            "plan_declaration_recomputed": True,
            "source_revalidated": False,
            "native_replayed": False,
            "attempt_reserved": False,
            "preregistration_verified": False,
        },
    }


def evaluate_search_findings(
    protocol_id: str,
    *,
    split: str,
    findings_factory: Callable[[], SearchFindingReader],
    campaign_inspector: Callable[[str], dict[str, object]],
) -> dict[str, object]:
    _development(split)
    identity(protocol_id)
    authority = _authority(protocol_id, findings_factory())
    campaign = campaign_inspector(authority.plan.plan_id)
    # These facts are supplied by the actual application inspector. A bare
    # self-reported report is not an evidence port exposed by the CLI.
    verification = campaign.get("verification")
    if (
        campaign.get("kind") != "bounded_search_campaign_report_v1"
        or type(campaign.get("schema_version")) is not int
        or campaign.get("schema_version") != 1
        or not isinstance(verification, dict)
        or any(
            verification.get(name) is not True
            for name in (
                "plan_recomputed",
                "source_revalidated",
                "budget_bindings_verified",
                "quota_reservations_verified",
            )
        )
        or verification.get("execution_reaudited") is not (campaign.get("execution") is not None)
        or campaign.get("plan_id") != authority.plan.plan_id
    ):
        raise SearchFindingValidationError("Finding input is not a reaudited bounded campaign")
    report = build_search_finding_report(authority, campaign=campaign)
    # Snapshot-derived reports are local reaudits. They are not the independent
    # portable sealed evidence closure planned for Sprint 8.
    return {
        "kind": "search_finding_receipt_v1",
        "schema_version": 1,
        "report_id": report.report_id,
        "report": report.document,
        "finalization_status": "LOCAL_REAUDITED",
        "verification": {
            "authority_recomputed": True,
            "plan_recomputed": True,
            "source_revalidated": True,
            "budget_bindings_verified": True,
            "quota_reservations_verified": True,
            "execution_reaudited": campaign.get("execution") is not None,
            "findings_recomputed": True,
            "source_snapshot_sha256_recomputed": True,
            "native_replayed": False,
            "attempt_reserved": False,
            "runtime_limits_reenforced": False,
            "portable_evidence_verified": False,
            "author_signature_verified": False,
            "human_domain_approval_verified": False,
            "preregistration_verified": False,
            "full_attempt_history_verified": False,
        },
    }
