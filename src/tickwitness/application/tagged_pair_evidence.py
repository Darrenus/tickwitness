"""Seal committed tagged runs and verify portable source/economics without a ledger."""

from collections.abc import Callable
from typing import Protocol, cast

from tickwitness.application.data_access import DatasetReader
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_queue_execution import (
    TaggedQueueLedger,
    TaggedQueueReader,
    tagged_queue_run_evidence,
)
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
)
from tickwitness.domain.evidence.tagged_pair_verification import (
    assess_tagged_pair_artifacts,
    verify_tagged_pair_artifacts,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS


class TaggedPairDatasetReader(DatasetReader, Protocol):
    def read_artifacts(self, dataset_id: str) -> dict[str, bytes]: ...


class TaggedPairPackage(Protocol):
    @property
    def bundle_id(self) -> str: ...
    @property
    def manifest_bytes(self) -> bytes: ...
    @property
    def artifacts(self) -> dict[str, bytes]: ...


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Tagged pair evidence permits development only")


def tagged_pair_artifacts(
    first_run_id: str,
    second_run_id: str,
    *,
    split: str = "development",
    ledger: TaggedQueueLedger,
    protocols: TaggedQueueReader,
    datasets: TaggedPairDatasetReader,
) -> dict[str, bytes]:
    """Reaudit actual committed outcomes before preparing any destination or manifest."""
    _development(split)
    identity(first_run_id)
    identity(second_run_id)
    if first_run_id == second_run_id:
        raise EvidenceValidationError("Tagged pair requires two distinct committed runs")
    evidence = [
        tagged_queue_run_evidence(run_id, ledger=ledger, protocols=protocols, datasets=datasets)
        for run_id in (first_run_id, second_run_id)
    ]
    left, right = evidence
    protocol = left.replay_input.protocol
    if protocol.canonical_bytes != right.replay_input.protocol.canonical_bytes:
        raise EvidenceValidationError("Tagged pair runs must use the same full frozen protocol")
    by_policy = {item.replay_input.policy_id: item for item in evidence}
    if len(by_policy) != 2 or by_policy.keys() != set(TAGGED_POLICY_IDS):
        raise EvidenceValidationError("Tagged pair requires one run of each frozen policy")
    dataset_id = cast("dict[str, str]", protocol.document["bindings"])["development_dataset_id"]
    data = datasets.read_artifacts(dataset_id)
    if data.keys() != {"dataset_manifest", "raw", "normalized", "report"}:
        raise EvidenceValidationError("Tagged dataset artifact closure differs")
    artifacts = dict(data, protocol=protocol.canonical_bytes)
    for role, policy in zip(("front", "back"), TAGGED_POLICY_IDS, strict=True):
        item = by_policy[policy]
        artifacts.update(
            {
                role + "_result": item.result.canonical_bytes,
                role + "_evaluation": item.evaluation.canonical_bytes,
                role + "_receipt": item.receipt.canonical_bytes,
            }
        )
    assessment = assess_tagged_pair_artifacts(artifacts)
    artifacts["assessment"] = assessment.canonical_bytes
    return artifacts


def verify_tagged_pair_package(
    package: TaggedPairPackage,
    *,
    expected_bundle_id: str | None = None,
    split: str = "development",
) -> dict[str, object]:
    """A portable receipt verifies supplied bytes, never author or original ledger history."""
    _development(split)
    bundle_id = identity(package.bundle_id)
    if expected_bundle_id is not None and identity(expected_bundle_id) != bundle_id:
        raise EvidenceValidationError("Tagged bundle differs from the expected pinned identity")
    manifest = package.manifest_bytes
    if type(manifest) is not bytes or digest(manifest) != bundle_id:
        raise EvidenceValidationError("Tagged bundle identity differs from its manifest")
    artifacts = package.artifacts
    verified = verify_tagged_pair_artifacts(artifacts)
    expected_manifest = canonical(
        {
            "kind": "tagged_queue_pair_evidence_bundle_v1",
            "schema_version": 1,
            "scope": "development_tagged_queue_pair_v1",
            "roles": {
                role: {
                    "sha256": digest(data),
                    "size_bytes": len(data),
                    "ref": f"objects/sha256/{digest(data)}",
                }
                for role, data in artifacts.items()
            },
        }
    )
    if manifest != expected_manifest:
        raise EvidenceValidationError(
            "Tagged package manifest does not describe its artifact closure"
        )
    return {"bundle_id": bundle_id, **verified}


def export_tagged_pair(
    first_run_id: str,
    second_run_id: str,
    *,
    split: str,
    ledger_factory: Callable[[], TaggedQueueLedger],
    protocols_factory: Callable[[], TaggedQueueReader],
    datasets_factory: Callable[[], TaggedPairDatasetReader],
    exporter: Callable[[dict[str, bytes]], TaggedPairPackage],
) -> dict[str, object]:
    """No new attempts or native calls; refuse invalid evidence before publication."""
    _development(split)
    identity(first_run_id)
    identity(second_run_id)
    artifacts = tagged_pair_artifacts(
        first_run_id,
        second_run_id,
        split=split,
        ledger=ledger_factory(),
        protocols=protocols_factory(),
        datasets=datasets_factory(),
    )
    package = exporter(artifacts)
    if package.artifacts != artifacts:
        raise EvidenceValidationError("Exporter returned a different tagged pair than requested")
    return verify_tagged_pair_package(package)
