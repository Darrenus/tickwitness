"""Pure managed-native bindings; these saved-result fixtures are not new native runs."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_job_contracts import request as comparison_request
from test_reduction_records import prepared_case, receipt_document

from tickwitness.application.jobs import job_view
from tickwitness.domain.evidence.reduction_records import build_reduction_run_receipt
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.domain.jobs import (
    MAX_JOB_LEASE_NS,
    MAX_JOB_SPEC_BYTES,
    MIN_JOB_LEASE_NS,
    JobValidationError,
    assert_active_job,
    build_execution_job_spec,
    build_job_spec,
    check_job_result,
    claim_job,
    execution_dispatch_nonce,
    finish_job,
    heartbeat_job,
    job_dispatch_nonce,
    load_job_snapshot,
    load_job_spec,
    lose_job,
    queued_job,
)

LEASE = MIN_JOB_LEASE_NS


def execution_request(**changes):
    return {
        "preparation": "/owner/preparations/prefix",
        "expected_preparation_id": "a" * 64,
        "expected_bundle_id": "b" * 64,
        "expected_report_id": "c" * 64,
        "input_root": "/owner/inputs",
        "source_evidence": "portable/source",
        "runs": "/owner/original-runs",
        "split": "development",
        "engine_runtime": "coordinator_interpreter_v1",
        "restart_mode": "frozen_origin_new_attempt_only_v1",
        **changes,
    }


def execution_case(*, pending=False):
    fixture = prepared_case(pending=pending)
    document = receipt_document(fixture)
    bindings = document["intent"]["bindings"]
    request = execution_request(
        expected_preparation_id=bindings["preparation_id"],
        expected_bundle_id=bindings["source_bundle_id"],
        expected_report_id=bindings["source_report_id"],
    )
    spec = build_execution_job_spec(request, lease_duration_ns=LEASE)
    document["attempt"]["nonce"] = job_dispatch_nonce(spec)
    receipt = build_reduction_run_receipt(document)
    return SimpleNamespace(spec=spec, request=request, receipt=receipt, fixture=fixture)


def running_native(spec=None):
    if spec is None:
        spec = build_execution_job_spec(execution_request(), lease_duration_ns=LEASE)
    return claim_job(
        queued_job(spec, now_ns=10),
        coordinator_id="d" * 64,
        attempt_nonce="e" * 64,
        lease_token="f" * 64,
        now_ns=20,
    )


def active_options(row, **changes):
    attempt = row["attempt"]
    return {
        "coordinator_id": attempt["coordinator_id"],
        "job_attempt_id": attempt["job_attempt_id"],
        "lease_token": attempt["lease_token"],
        "now_ns": 21,
        **changes,
    }


def test_new_operation_freezes_exact_policies_and_does_not_change_comparison_identity():
    request = execution_request()
    spec = build_execution_job_spec(request)
    assert spec.document == {
        "kind": "reduction_execution_job_spec_v1",
        "schema_version": 1,
        "operation": "execute_reduction_input_v1",
        "request": request,
        "lease_duration_ns": 30_000_000_000,
    }
    assert spec.spec_id == digest(spec.canonical_bytes)
    assert load_job_spec(spec.canonical_bytes) == spec
    request["engine_runtime"] = "changed"
    assert spec.document["request"]["engine_runtime"] == "coordinator_interpreter_v1"
    comparison = build_job_spec(comparison_request())
    assert comparison.canonical_bytes == canonical(
        {
            "kind": "comparison_job_spec_v1",
            "schema_version": 1,
            "operation": "compare_reduction_run_v1",
            "request": comparison_request(),
            "lease_duration_ns": 30_000_000_000,
        }
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("preparation", "relative/prefix"),
        ("preparation", "/prefix\x00hidden"),
        ("input_root", False),
        ("runs", "/" + "r" * 4096),
        ("source_evidence", "../escape"),
        ("source_evidence", "source\\escape"),
        ("source_evidence", "/absolute"),
        ("source_evidence", "source/./nested"),
        ("expected_preparation_id", "A" * 64),
        ("expected_bundle_id", "b" * 63),
        ("expected_report_id", None),
        ("split", "confirmation"),
        ("engine_runtime", "arbitrary_command_v1"),
        ("engine_runtime", {"command": "/bin/sh"}),
        ("restart_mode", "checkpoint_resume_v1"),
        ("restart_mode", True),
    ],
)
def test_execution_request_cannot_add_runtime_or_recovery_authority(field, value):
    with pytest.raises(JobValidationError):
        build_execution_job_spec(execution_request(**{field: value}))


@pytest.mark.parametrize("attack", ["extra", "missing", "not_object"])
def test_execution_request_is_exact_and_has_no_budget_override(attack):
    request = execution_request()
    if attack == "extra":
        request["max_attempts"] = 100
    elif attack == "missing":
        request.pop("engine_runtime")
    else:
        request = []
    with pytest.raises(JobValidationError):
        build_execution_job_spec(request)


@pytest.mark.parametrize("lease", [True, 0, LEASE - 1, MAX_JOB_LEASE_NS + 1, 1.0])
def test_execution_lease_remains_a_strict_bounded_integer(lease):
    with pytest.raises(JobValidationError):
        build_execution_job_spec(execution_request(), lease_duration_ns=lease)


@pytest.mark.parametrize("attack", ["kind", "operation", "schema_bool", "newline", "oversize"])
def test_execution_descriptor_cannot_alias_comparison_or_noncanonical_shapes(attack):
    spec = build_execution_job_spec(execution_request())
    document = spec.document
    if attack == "kind":
        document["kind"] = "comparison_job_spec_v1"
    elif attack == "operation":
        document["operation"] = "compare_reduction_run_v1"
    elif attack == "schema_bool":
        document["schema_version"] = True
    raw = canonical(document)
    if attack == "newline":
        raw += b"\n"
    elif attack == "oversize":
        raw = b" " * (MAX_JOB_SPEC_BYTES + 1)
    with pytest.raises(JobValidationError):
        load_job_spec(raw)


def test_dispatch_nonce_is_deterministic_domain_separated_and_immutable_before_claim():
    spec = build_execution_job_spec(execution_request())
    expected = digest(
        canonical({"kind": "reduction_job_dispatch_nonce_v1", "job_id": spec.spec_id})
    )[:32]
    assert job_dispatch_nonce(spec) == execution_dispatch_nonce(spec.spec_id) == expected
    assert len(expected) == 32
    row = running_native(spec)
    assert job_dispatch_nonce(load_job_spec(canonical(row["spec"]))) == expected
    assert expected != row["attempt"]["nonce"]
    relocated = build_execution_job_spec(execution_request(preparation="/relocated/prefix"))
    assert job_dispatch_nonce(relocated) != expected
    with pytest.raises(JobValidationError):
        job_dispatch_nonce(build_job_spec(comparison_request()))


@pytest.mark.parametrize("job_id", [None, True, "A" * 64, "0" * 63])
def test_dispatch_nonce_requires_a_complete_frozen_job_identity(job_id):
    with pytest.raises(EvidenceValidationError):
        execution_dispatch_nonce(job_id)


@pytest.mark.parametrize("pending", [False, True])
def test_native_result_is_the_existing_receipt_including_valid_incomplete_runs(pending):
    value = execution_case(pending=pending)
    assert check_job_result(value.spec, value.receipt.canonical_bytes) == value.receipt.run_id
    assert value.receipt.document["execution_status"] == ("incomplete" if pending else "completed")
    assert value.receipt.document["attempt"]["nonce"] == job_dispatch_nonce(value.spec)


@pytest.mark.parametrize(
    "pin", ["expected_preparation_id", "expected_bundle_id", "expected_report_id"]
)
def test_self_consistent_receipt_cannot_publish_for_different_frozen_pins(pin):
    value = execution_case()
    altered = build_execution_job_spec({**value.request, pin: "0" * 64}, lease_duration_ns=LEASE)
    # Isolate the pin mismatch from the dispatch-nonce mismatch.
    document = value.receipt.document
    document["attempt"]["nonce"] = job_dispatch_nonce(altered)
    receipt = build_reduction_run_receipt(document)
    with pytest.raises(JobValidationError, match="pins"):
        check_job_result(altered, receipt.canonical_bytes)


def test_receipt_from_another_dispatch_cannot_be_reused_with_its_own_valid_hash():
    value = execution_case()
    document = value.receipt.document
    document["attempt"]["nonce"] = "0" * 32
    receipt = build_reduction_run_receipt(document)
    with pytest.raises(JobValidationError, match="dispatch nonce"):
        check_job_result(value.spec, receipt.canonical_bytes)


def test_raw_result_or_ack_envelope_is_not_an_original_final_manifest():
    value = execution_case()
    for raw in (
        value.fixture.result.canonical_bytes,
        canonical({"receipt": value.receipt.document, "job_succeeded": True}),
        value.receipt.canonical_bytes + b"\n",
    ):
        with pytest.raises(EvidenceValidationError):
            check_job_result(value.spec, raw)


def test_active_admission_is_detached_readonly_and_never_renews_or_advances():
    row = running_native()
    before = deepcopy(row)
    checked = assert_active_job(row, **active_options(row))
    assert checked == before == row
    assert checked is not row
    checked["attempt"]["heartbeat_sequence"] = 100
    assert row == before
    assert load_job_snapshot(canonical(row)) == row


def test_queued_job_has_no_active_research_publication_authority():
    running = running_native()
    queued = queued_job(load_job_spec(canonical(running["spec"])), now_ns=10)
    with pytest.raises(JobValidationError, match="Only a running job"):
        assert_active_job(queued, **active_options(running))


@pytest.mark.parametrize(
    "changes",
    [
        {"coordinator_id": "0" * 64},
        {"job_attempt_id": "0" * 64},
        {"lease_token": "0" * 64},
        {"now_ns": 19},
        {"now_ns": 20 + LEASE},
        {"now_ns": True},
    ],
)
def test_stale_or_expired_admission_is_rejected_without_changing_the_job(changes):
    row = running_native()
    before = deepcopy(row)
    with pytest.raises(JobValidationError):
        assert_active_job(row, **active_options(row, **changes))
    assert row == before


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "FAILED", "LOST"])
def test_terminal_jobs_never_regain_research_publication_authority(terminal):
    row = running_native()
    options = active_options(row)
    if terminal == "LOST":
        finished = lose_job(row, reason="coordinator_lost", now_ns=21)
    else:
        finished = finish_job(
            row,
            **options,
            result_sha256="0" * 64 if terminal == "SUCCEEDED" else None,
            failure=(
                None
                if terminal == "SUCCEEDED"
                else {"code": "worker_died", "message": "Killed", "worker_exit_code": -9}
            ),
        )
    with pytest.raises(JobValidationError):
        assert_active_job(finished, **active_options(finished, now_ns=22))
    view = job_view(finished, now_ns=22, coordinator_active=False)
    expected = True if terminal == "SUCCEEDED" else None
    assert view["scope"]["operation"] == "execute_reduction_input_v1"
    assert view["scope"]["research_attempt_reserved"] is expected
    assert view["scope"]["native_replayed"] is expected


def test_unfinished_native_catalog_view_does_not_assert_unconsumed_research_budget():
    spec = build_execution_job_spec(execution_request())
    for row in (queued_job(spec, now_ns=10), running_native(spec)):
        view = job_view(row, now_ns=21, coordinator_active=True)
        assert view["scope"]["research_attempt_reserved"] is None
        assert view["scope"]["native_replayed"] is None
        assert view["scope"]["automatic_retry_supported"] is False
        assert view["scope"]["checkpoint_resume_verified"] is False
