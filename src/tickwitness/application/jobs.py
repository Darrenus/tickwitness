"""Managed operation ports and redacted views, separate from research attempts."""

from contextlib import AbstractContextManager
from typing import Protocol, cast

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.jobs import JobSpec, effective_state, load_job_snapshot

type Row = dict[str, object]


class JobStoreError(ValueError):
    """Catalog integrity or IO failed; a publication may be unconfirmed."""

    code = "job_store_integrity_or_io_failure"
    exit_code = 3


class JobNotFoundError(JobStoreError):
    """The requested catalog or managed job does not exist."""

    code = "job_not_found"
    exit_code = 4


class JobConflictError(JobStoreError):
    """Ownership, version or terminal state prevents a requested mutation."""

    code = "job_conflict"
    exit_code = 9


class JobRepository(Protocol):
    def coordinator(self) -> AbstractContextManager[str]: ...

    def coordinator_active(self) -> bool: ...

    def submit(self, spec: JobSpec, *, now_ns: int) -> Row: ...

    def get(self, job_id: str) -> Row: ...

    def events(self, job_id: str, *, limit: int = 100) -> list[Row]: ...

    def result(self, job_id: str) -> bytes | None: ...

    def claim(
        self, job_id: str, *, expected_version: int, coordinator_id: str,
        attempt_nonce: str, lease_token: str, now_ns: int,
    ) -> Row: ...

    def heartbeat(
        self, job_id: str, *, expected_version: int, coordinator_id: str,
        job_attempt_id: str, lease_token: str, sequence: int, now_ns: int,
    ) -> Row: ...

    def complete(
        self, job_id: str, raw: bytes, *, expected_version: int, coordinator_id: str,
        job_attempt_id: str, lease_token: str, now_ns: int,
    ) -> Row: ...

    def fail(
        self, job_id: str, failure: Row, *, expected_version: int, coordinator_id: str,
        job_attempt_id: str, lease_token: str, now_ns: int,
    ) -> Row: ...

    def mark_lost(
        self, job_id: str, *, expected_version: int, reason: str, now_ns: int,
    ) -> Row: ...

    def reconcile_orphans(self, *, now_ns: int) -> list[Row]: ...


def job_view(row: Row, *, now_ns: int, coordinator_active: bool) -> Row:
    """Project internal state without exposing bearer credentials or retry claims."""
    checked = load_job_snapshot(canonical(row))
    attempt = checked["attempt"]
    if attempt is not None:
        attempt = dict(cast("Row", attempt))
        attempt.pop("lease_token")
        attempt.pop("nonce")
    return {
        "kind": "job_view_v1",
        "schema_version": 1,
        "job_id": checked["job_id"],
        "spec": checked["spec"],
        "stored_state": checked["state"],
        "state": effective_state(checked, now_ns=now_ns, coordinator_active=coordinator_active),
        "version": checked["version"],
        "created_at_ns": checked["created_at_ns"],
        "updated_at_ns": checked["updated_at_ns"],
        "attempt": attempt,
        "result_sha256": checked["result_sha256"],
        "failure": checked["failure"],
        "scope": {
            "operation": "compare_reduction_run_v1",
            "job_attempt_is_research_attempt": False,
            "research_attempt_reserved": False,
            "native_replayed": False,
            "automatic_retry_supported": False,
            "checkpoint_resume_verified": False,
            "strong_cancellation_verified": False,
            "global_history_authenticated": False,
            "human_domain_approval_verified": False,
        },
    }
