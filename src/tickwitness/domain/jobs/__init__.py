"""Generic managed job state; research verdicts and budgets remain separate."""

from tickwitness.domain.jobs.contracts import (
    MAX_JOB_INTEGER,
    MAX_JOB_LEASE_NS,
    MAX_JOB_SNAPSHOT_BYTES,
    MAX_JOB_SPEC_BYTES,
    MIN_JOB_LEASE_NS,
    JobSpec,
    JobValidationError,
    build_job_spec,
    claim_job,
    effective_state,
    finish_job,
    heartbeat_job,
    load_job_snapshot,
    load_job_spec,
    lose_job,
    queued_job,
)

__all__ = [
    "MAX_JOB_INTEGER", "MAX_JOB_LEASE_NS", "MAX_JOB_SNAPSHOT_BYTES", "MAX_JOB_SPEC_BYTES",
    "MIN_JOB_LEASE_NS", "JobSpec", "JobValidationError", "build_job_spec", "claim_job",
    "effective_state", "finish_job", "heartbeat_job", "load_job_snapshot", "load_job_spec",
    "lose_job", "queued_job",
]
