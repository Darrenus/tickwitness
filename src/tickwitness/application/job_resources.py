"""Read operational observations without granting research execution authority."""

from typing import Protocol, cast

from tickwitness.application.jobs import JobStoreError
from tickwitness.domain.evidence.run_records import canonical, digest, identity
from tickwitness.domain.jobs import load_job_snapshot
from tickwitness.domain.jobs.control import JobControlPolicy
from tickwitness.domain.jobs.resources import JobResourceReport, build_job_resource_preview

type Row = dict[str, object]


class ResourceCatalog(Protocol):
    def get(self, job_id: str) -> Row: ...

    def resource_snapshot(self, job_id: str, snapshot_sha256: str) -> Row | None: ...


class ResourceReader(Protocol):
    def read(self) -> JobResourceReport | None: ...


def preview_job_resources(
    catalog: ResourceCatalog, job_id: str, policy: JobControlPolicy | None
) -> Row:
    """Only a frozen descriptor and optional configured ceilings are consumed."""
    snapshot = load_job_snapshot(canonical(catalog.get(identity(job_id))))
    return build_job_resource_preview(snapshot, policy)


def inspect_job_resources(
    catalog: ResourceCatalog,
    resources: ResourceReader,
    job_id: str,
    policy: JobControlPolicy | None,
) -> Row:
    key = identity(job_id)
    snapshot = load_job_snapshot(canonical(catalog.get(key)))
    current_sha = digest(canonical(snapshot))
    record = resources.read()
    document = None if record is None else record.document
    matches: bool | None = None
    status = "NOT_RECORDED"
    if document is not None:
        if (
            policy is None
            or document["job_id"] != key
            or document["policy_id"] != policy.policy_id
        ):
            raise JobStoreError("Resource report differs from this Job's frozen policy")
        captured_sha = document["catalog_snapshot_sha256"]
        if captured_sha is not None:
            observed = catalog.resource_snapshot(key, cast("str", captured_sha))
            if observed is None:
                raise JobStoreError("Resource report snapshot is not in this Catalog history")
            attempt = observed["attempt"]
            observed_attempt = None if attempt is None else cast("Row", attempt)["job_attempt_id"]
            if (
                document["catalog_state"] != observed["state"]
                or document["job_attempt_id"] != observed_attempt
            ):
                raise JobStoreError("Resource report differs from its observed Catalog snapshot")
            matches = captured_sha == current_sha
        status = "RECORDED" if document["collection_status"] == "complete" else "PARTIAL"
    return {
        "kind": "job_resource_inspection_v1",
        "schema_version": 1,
        "job_id": key,
        "policy_id": None if policy is None else policy.policy_id,
        "current_snapshot_sha256": current_sha,
        "report_id": None if record is None else record.report_id,
        "report": document,
        "report_matches_current_snapshot": matches,
        "status": status,
        "execution_authorized": False,
    }
