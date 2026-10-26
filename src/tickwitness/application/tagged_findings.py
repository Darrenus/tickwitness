"""Explicit conditional finding authority and sealed report issuance.

FINAL denotes verified content closure under a frozen rubric. It does not attest
producer identity, original publication, human domain approval or trial history.
The publisher port must publish and reread the complete fixed directory.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tickwitness.application.experiments import ExecutableRecord
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_pair_evidence import (
    TaggedPairPackage,
    verify_tagged_pair_package,
)
from tickwitness.application.tagged_queue_execution import TaggedQueueReader
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
)
from tickwitness.domain.evidence.tagged_finding_report import (
    build_tagged_finding_report,
    verify_tagged_finding_artifacts,
)
from tickwitness.domain.research_contracts.tagged_finding_protocol import (
    TaggedFindingProtocol,
    TaggedFindingValidationError,
    build_tagged_finding_protocol,
    load_tagged_finding_protocol,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import load_tagged_queue_protocol


class FindingReader(Protocol):
    def get(self, protocol_id: str) -> ExecutableRecord: ...


class FindingRepository(FindingReader, Protocol):
    def seal(self, canonical_bytes: bytes) -> ExecutableRecord: ...


@dataclass(frozen=True, slots=True)
class FindingFreezeReceipt:
    protocol: TaggedFindingProtocol
    created: bool

    @property
    def document(self) -> dict[str, object]:
        return {
            "finding_protocol_id": self.protocol.protocol_id,
            "created": self.created,
            "protocol": self.protocol.document,
        }


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Tagged findings permit development evidence only")


def _load(protocol_id: str, registry: FindingReader) -> TaggedFindingProtocol:
    identity(protocol_id)
    record = registry.get(protocol_id)
    protocol = load_tagged_finding_protocol(record.canonical_bytes)
    if record.protocol_id != protocol_id or protocol.protocol_id != protocol_id:
        raise TaggedFindingValidationError("Finding registry returned a conflicting authority")
    return protocol


def freeze_finding_protocol(
    subject_protocol_id: str,
    request: bytes,
    *,
    split: str,
    subjects_factory: Callable[[], TaggedQueueReader],
    findings_factory: Callable[[], FindingRepository],
) -> FindingFreezeReceipt:
    _development(split)
    identity(subject_protocol_id)
    stored_subject = subjects_factory().get(subject_protocol_id)
    subject = load_tagged_queue_protocol(stored_subject.canonical_bytes)
    if (
        stored_subject.protocol_id != subject_protocol_id
        or subject.protocol_id != subject_protocol_id
    ):
        raise TaggedFindingValidationError("Finding subject registry returned conflicting content")
    protocol = build_tagged_finding_protocol(request, subject_protocol=subject)
    stored = findings_factory().seal(protocol.canonical_bytes)
    if (
        stored.protocol_id != protocol.protocol_id
        or stored.canonical_bytes != protocol.canonical_bytes
        or type(stored.created) is not bool
    ):
        raise TaggedFindingValidationError(
            "Finding authority publication returned conflicting content"
        )
    return FindingFreezeReceipt(protocol, stored.created)


def inspect_finding_protocol(
    protocol_id: str,
    *,
    split: str = "development",
    findings_factory: Callable[[], FindingReader],
) -> dict[str, object]:
    _development(split)
    identity(protocol_id)
    protocol = _load(protocol_id, findings_factory())
    return {"finding_protocol_id": protocol.protocol_id, "protocol": protocol.document}


def verify_finding_package(
    package: TaggedPairPackage,
    *,
    expected_bundle_id: str | None = None,
    split: str = "development",
) -> dict[str, object]:
    _development(split)
    bundle_id = identity(package.bundle_id)
    if expected_bundle_id is not None and identity(expected_bundle_id) != bundle_id:
        raise EvidenceValidationError("Finding bundle differs from the expected pinned identity")
    manifest = package.manifest_bytes
    if type(manifest) is not bytes or digest(manifest) != bundle_id:
        raise EvidenceValidationError("Finding bundle identity differs from its manifest")
    artifacts = package.artifacts
    report = verify_tagged_finding_artifacts(artifacts)
    expected = canonical(
        {
            "kind": "tagged_finding_evidence_bundle_v1",
            "schema_version": 1,
            "scope": "development_conditional_tagged_findings_v1",
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
    if manifest != expected:
        raise EvidenceValidationError("Finding manifest does not describe the verified closure")
    document = report.document
    return {
        "bundle_id": bundle_id,
        "source_pair_bundle_id": document["source_pair_bundle_id"],
        "finding_protocol_id": document["finding_protocol_id"],
        "report_id": report.report_id,
        "report": document,
        "finalization_status": "FINAL",
        "finalization_basis": "sealed_finding_evidence_content_v1",
        "integrity_verified": True,
        "bindings_verified": True,
        "source_revalidated": True,
        "queue_execution_audited": True,
        "findings_recomputed": True,
        "native_replayed": False,
        "author_signature_verified": False,
        "human_domain_approval_verified": False,
        "original_publication_verified": False,
        "confirmation_reference_checked": False,
        "full_attempt_ledger_checked": False,
        "ledger_commitment_checked": False,
    }


def issue_tagged_findings(
    finding_protocol_id: str,
    *,
    expected_source_bundle_id: str,
    split: str,
    findings_factory: Callable[[], FindingReader],
    source_factory: Callable[[], TaggedPairPackage],
    publisher: Callable[[dict[str, bytes]], TaggedPairPackage],
) -> dict[str, object]:
    """Require explicit authority and pinned sealed evidence before invoking publication."""
    _development(split)
    identity(finding_protocol_id)
    identity(expected_source_bundle_id)
    protocol = _load(finding_protocol_id, findings_factory())
    source = source_factory()
    verified_source = verify_tagged_pair_package(
        source, expected_bundle_id=expected_source_bundle_id
    )
    pair_artifacts = source.artifacts
    report = build_tagged_finding_report(protocol, pair_artifacts)
    if report.document["source_pair_bundle_id"] != verified_source["bundle_id"]:
        raise EvidenceValidationError("Finding report refers to a different sealed source pair")
    artifacts = {
        **pair_artifacts,
        "finding_protocol": protocol.canonical_bytes,
        "finding_report": report.canonical_bytes,
    }
    published = publisher(artifacts)
    if published.artifacts != artifacts:
        raise EvidenceValidationError(
            "Finding publisher returned different evidence than requested"
        )
    receipt = verify_finding_package(published)
    if (
        receipt["finding_protocol_id"] != protocol.protocol_id
        or receipt["report_id"] != report.report_id
        or receipt["source_pair_bundle_id"] != expected_source_bundle_id
    ):
        raise EvidenceValidationError("Published finding receipt differs from requested issuance")
    return receipt
