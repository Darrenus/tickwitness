"""Control declarations cannot mutate legacy identities or certify missing cleanup."""

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import JobValidationError
from tickwitness.domain.jobs.control import (
    MAX_JOB_CONTROL_BYTES,
    JobControlPolicy,
    build_job_cancel_request,
    build_job_control_policy,
    build_job_control_result,
    build_job_publication_admission,
    load_job_cancel_request,
    load_job_control_policy,
    load_job_control_result,
    load_job_publication_admission,
)

JOB = "a" * 64
ATTEMPT = "b" * 64


def declared_result(**changes):
    """A structural fixture, not actual process/cleanup qualification."""
    policy = build_job_control_policy(JOB)
    return {
        "kind": "job_control_result_v1",
        "schema_version": 1,
        "job_id": JOB,
        "policy_id": policy.policy_id,
        "job_attempt_id": ATTEMPT,
        "cause": "job_deadline_exceeded",
        "catalog_state": "LOST",
        "catalog_snapshot_sha256": "c" * 64,
        "publication_admitted": False,
        "worker_started": True,
        "worker_exit_code": -9,
        "worker_group_absent": True,
        "workspace_removed": True,
        "cleanup_confirmed": True,
        "stop_confirmed": True,
        "timing_ns": {
            "elapsed": 100,
            "request_observed": None,
            "worker_reaped": 80,
            "cleanup_finished": 90,
        },
        "diagnostic": "Declared bounded stop fixture",
        **changes,
    }


def test_policy_is_frozen_exact_identity_with_finite_supported_limits():
    policy = build_job_control_policy(JOB)
    assert policy.policy_id == digest(policy.canonical_bytes)
    assert load_job_control_policy(policy.canonical_bytes) == policy
    assert policy.document == {
        "kind": "job_control_policy_v1",
        "schema_version": 1,
        "job_id": JOB,
        "limits": {
            "max_wall_ns": 120_000_000_000,
            "worker_cpu_seconds": 60,
            "max_file_bytes": 8_388_608,
            "max_open_files": 128,
            "cleanup_grace_ns": 5_000_000_000,
        },
    }
    detached = policy.document
    detached["limits"]["max_wall_ns"] = 1
    assert policy.document["limits"]["max_wall_ns"] == 120_000_000_000
    with pytest.raises(FrozenInstanceError):
        policy.policy_id = "f" * 64
    with pytest.raises(JobValidationError, match="identity"):
        JobControlPolicy("f" * 64, policy.canonical_bytes)


@pytest.mark.parametrize(
    ("field", "low", "high"),
    [
        ("max_wall_ns", 1_000_000_000, 3_600_000_000_000),
        ("worker_cpu_seconds", 1, 3600),
        ("max_file_bytes", 1024, 1024 * 1024 * 1024),
        ("max_open_files", 32, 4096),
        ("cleanup_grace_ns", 100_000_000, 5_000_000_000),
    ],
)
def test_limits_reject_boolean_overflow_and_unsupported_bounds(field, low, high):
    for value in (True, False, low - 1, high + 1, 1.0, "1", None):
        with pytest.raises(JobValidationError):
            build_job_control_policy(JOB, **{field: value})
    assert build_job_control_policy(JOB, **{field: low}).document["limits"][field] == low
    assert build_job_control_policy(JOB, **{field: high}).document["limits"][field] == high


@pytest.mark.parametrize("field", ["research_budget", "memory_bytes", "max_temp_bytes", "engine"])
def test_policy_cannot_claim_unsupported_capabilities_or_research_authority(field):
    document = build_job_control_policy(JOB).document
    document["limits"][field] = 100
    with pytest.raises(JobValidationError, match="limits"):
        load_job_control_policy(canonical(document))


@pytest.mark.parametrize("raw", [b"{}\n", b"[]", b'{"kind":1,"kind":1}', b" " * 16385])
def test_control_policy_rejects_noncanonical_duplicate_or_oversized_bytes(raw):
    with pytest.raises(JobValidationError):
        load_job_control_policy(raw)


def test_cancel_and_publication_have_distinct_exact_bound_documents():
    policy = build_job_control_policy(JOB)
    cancel = build_job_cancel_request(policy, key="cancel-1", now_ns=123)
    admission = build_job_publication_admission(policy, ATTEMPT, now_ns=124)
    assert cancel == load_job_cancel_request(canonical(cancel))
    assert admission == load_job_publication_admission(canonical(admission))
    assert cancel["policy_id"] == admission["policy_id"] == policy.policy_id
    assert cancel["requested_at_ns"] == 123 and admission["job_attempt_id"] == ATTEMPT
    for loader, document in (
        (load_job_cancel_request, cancel),
        (load_job_publication_admission, admission),
    ):
        with pytest.raises(JobValidationError):
            loader(canonical({**document, "lease_token": "f" * 64}))
        with pytest.raises(JobValidationError):
            loader(canonical({**document, "policy_id": "not-an-identity"}))


@pytest.mark.parametrize("key", ["", ".hidden", "a b", "../a", "中文", "a" * 129, None])
def test_cancellation_keys_are_bounded_explicit_ascii(key):
    with pytest.raises(JobValidationError, match="key"):
        build_job_cancel_request(build_job_control_policy(JOB), key=key, now_ns=1)


@pytest.mark.parametrize("now", [True, -1, 1 << 63, 1.0, None])
def test_cancellation_and_admission_require_exact_integer_utc(now):
    policy = build_job_control_policy(JOB)
    with pytest.raises(JobValidationError):
        build_job_cancel_request(policy, key="valid", now_ns=now)
    with pytest.raises(JobValidationError):
        build_job_publication_admission(policy, ATTEMPT, now_ns=now)


def test_control_result_retains_actual_lost_state_without_inventing_cancelled_snapshot():
    document = declared_result()
    assert build_job_control_result(document) == document
    assert load_job_control_result(canonical(document)) == document
    assert document["catalog_state"] == "LOST"
    assert "lease_token" not in document and "coordinator_id" not in document
    document["catalog_state"] = "CANCELLED"
    with pytest.raises(JobValidationError, match="state"):
        build_job_control_result(document)


@pytest.mark.parametrize(
    "change",
    [
        {"worker_group_absent": False},
        {"workspace_removed": False},
        {"cleanup_confirmed": False},
        {"worker_exit_code": None},
        {"stop_confirmed": "yes"},
        {"cause": "finished"},
        {"cause": "coordinator_interrupted"},
        {"catalog_state": "SUCCEEDED"},
        {"cause": "job_cancelled", "publication_admitted": True},
        {"catalog_snapshot_sha256": None},
        {"catalog_state": None},
        {"worker_started": False},
        {"diagnostic": "x" * 2049},
        {"lease_token": "d" * 64},
    ],
)
def test_receipt_cannot_certify_missing_cleanup_exit_or_unsupported_claims(change):
    with pytest.raises(JobValidationError):
        build_job_control_result(declared_result(**change))


@pytest.mark.parametrize(
    "name", ["elapsed", "request_observed", "worker_reaped", "cleanup_finished"]
)
@pytest.mark.parametrize("value", [-1, 1 << 63, True, 1.0])
def test_timing_offsets_are_bounded_elapsed_integers(name, value):
    document = declared_result()
    document["timing_ns"][name] = value
    with pytest.raises(JobValidationError):
        build_job_control_result(document)


def test_uncertainty_and_preclaim_errors_remain_explicit_without_false_cleanup():
    document = declared_result(
        job_attempt_id=None,
        cause="job_control_error",
        catalog_state=None,
        catalog_snapshot_sha256=None,
        worker_started=False,
        worker_exit_code=None,
        worker_group_absent=False,
        workspace_removed=False,
        cleanup_confirmed=False,
        stop_confirmed=False,
        timing_ns={
            "elapsed": 0,
            "request_observed": None,
            "worker_reaped": None,
            "cleanup_finished": None,
        },
    )
    assert build_job_control_result(document) == document
    changed = deepcopy(document)
    changed["stop_confirmed"] = True
    with pytest.raises(JobValidationError, match="Confirmed stop"):
        build_job_control_result(changed)
    with pytest.raises(JobValidationError):
        load_job_control_result(b"x" * (MAX_JOB_CONTROL_BYTES + 1))
