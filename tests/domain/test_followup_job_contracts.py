"""Explicit resolution contracts with offline receipts, never free native retries."""

from copy import deepcopy

import pytest
from test_native_job_contracts import execution_case, execution_request

from tickwitness.application.jobs import job_view
from tickwitness.domain.evidence.reduction_records import (
    build_reduction_failure,
    build_reduction_run_receipt,
    load_reduction_intent,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.domain.jobs import (
    MAX_FOLLOWUP_ANCESTRY,
    MAX_FOLLOWUP_RESULT_BYTES,
    JobValidationError,
    build_execution_job_spec,
    build_followup_job_spec,
    build_followup_result,
    check_job_result,
    claim_job,
    execution_origin_spec,
    finish_job,
    job_dispatch_nonce,
    load_job_spec,
    lose_job,
    queued_job,
    validate_followup_context,
)

RETRY = "retry_from_origin_v1"
ACK = "acknowledge_committed_v1"


def terminal(spec, state="FAILED"):
    running = claim_job(
        queued_job(spec, now_ns=10),
        coordinator_id="d" * 64,
        attempt_nonce="e" * 64,
        lease_token="f" * 64,
        now_ns=20,
    )
    if state == "LOST":
        return lose_job(running, reason="coordinator_lost", now_ns=21)
    attempt = running["attempt"]
    return finish_job(
        running,
        coordinator_id=attempt["coordinator_id"],
        job_attempt_id=attempt["job_attempt_id"],
        lease_token=attempt["lease_token"],
        result_sha256="0" * 64 if state == "SUCCEEDED" else None,
        failure=(
            None
            if state == "SUCCEEDED"
            else {"code": "worker_died", "message": "Interrupted", "worker_exit_code": -9}
        ),
        now_ns=21,
    )


def receipt_for_dispatch(case, dispatch):
    document = case.receipt.document
    document["attempt"]["nonce"] = job_dispatch_nonce(dispatch)
    return build_reduction_run_receipt(document)


def failure_for_dispatch(case, dispatch):
    receipt = receipt_for_dispatch(case, dispatch)
    document = receipt.document
    raw_attempt = canonical(document["attempt"])
    reservation = AttemptReservation(digest(raw_attempt), raw_attempt)
    intent = load_reduction_intent(canonical(document["intent"]))
    return build_reduction_failure(
        reservation, intent, "engine_failure", "Declared offline failure"
    )


def test_followup_identity_freezes_original_once_inherits_lease_and_scopes_the_key():
    origin = build_execution_job_spec(execution_request(), lease_duration_ns=7_000_000_000)
    child = build_followup_job_spec(origin, origin.spec_id, RETRY, "retry-A.1")
    assert child.document == {
        "kind": "reduction_followup_job_spec_v1",
        "schema_version": 1,
        "operation": "resolve_reduction_job_v1",
        "request": {
            "origin_spec": origin.document,
            "parent_job_id": origin.spec_id,
            "mode": RETRY,
            "idempotency_key": "retry-A.1",
        },
        "lease_duration_ns": 7_000_000_000,
    }
    assert child.spec_id == digest(child.canonical_bytes)
    assert load_job_spec(child.canonical_bytes) == child
    assert execution_origin_spec(child) == origin
    assert execution_origin_spec(origin) == origin
    assert build_followup_job_spec(origin, origin.spec_id, RETRY, "retry-A.1") == child
    assert build_followup_job_spec(origin, origin.spec_id, ACK, "retry-A.1") != child
    assert build_followup_job_spec(origin, "f" * 64, RETRY, "retry-A.1") != child
    assert build_followup_job_spec(origin, origin.spec_id, RETRY, "retry-B") != child
    assert job_dispatch_nonce(child) != job_dispatch_nonce(origin)
    with pytest.raises(JobValidationError):
        job_dispatch_nonce(build_followup_job_spec(origin, origin.spec_id, ACK, "ack-v1"))


@pytest.mark.parametrize(
    "key", ["", ".start", "_start", "-start", "a/b", "a b", "é", "a" * 129, True]
)
def test_followup_keys_are_bounded_ascii_identifiers(key):
    origin = build_execution_job_spec(execution_request())
    with pytest.raises(JobValidationError):
        build_followup_job_spec(origin, origin.spec_id, RETRY, key)


@pytest.mark.parametrize("key", ["a", "0", "A._-9", "a" * 128])
def test_followup_key_boundaries_are_preserved(key):
    origin = build_execution_job_spec(execution_request())
    assert build_followup_job_spec(origin, origin.spec_id, ACK, key).document["request"][
        "idempotency_key"
    ] == key


@pytest.mark.parametrize(
    "attack", ["extra", "missing", "lease", "mode", "recursive", "operation", "boolean_schema"]
)
def test_descriptor_cannot_mutate_frozen_policies_or_embed_recursive_history(attack):
    origin = build_execution_job_spec(execution_request())
    child = build_followup_job_spec(origin, origin.spec_id, RETRY, "A")
    document = child.document
    if attack == "extra":
        document["request"]["budget_override"] = 100
    elif attack == "missing":
        document["request"].pop("parent_job_id")
    elif attack == "lease":
        document["lease_duration_ns"] -= 1
    elif attack == "mode":
        document["request"]["mode"] = "automatic_resume"
    elif attack == "recursive":
        document["request"]["origin_spec"] = child.document
    elif attack == "operation":
        document["operation"] = "execute_reduction_input_v1"
    else:
        document["schema_version"] = True
    with pytest.raises(JobValidationError):
        load_job_spec(canonical(document))
    with pytest.raises(JobValidationError):
        build_followup_job_spec(child, child.spec_id, RETRY, "nested")


@pytest.mark.parametrize("state", ["FAILED", "LOST", "SUCCEEDED"])
def test_context_requires_exact_local_original_and_terminal_retry_ancestors(state):
    origin = build_execution_job_spec(execution_request())
    first = build_followup_job_spec(origin, origin.spec_id, RETRY, "A")
    second = build_followup_job_spec(origin, first.spec_id, ACK, "ack-A")
    rows = {origin.spec_id: terminal(origin, state), first.spec_id: terminal(first, state)}
    before = deepcopy(rows)
    ancestry = validate_followup_context(second, rows.__getitem__)
    assert ancestry == (rows[origin.spec_id], rows[first.spec_id])
    ancestry[0]["failure"] = None
    assert rows == before


def test_running_or_queued_parent_needs_explicit_reconciliation_not_implicit_resume():
    origin = build_execution_job_spec(execution_request())
    child = build_followup_job_spec(origin, origin.spec_id, ACK, "ack")
    queued = queued_job(origin, now_ns=10)
    running = claim_job(
        queued, coordinator_id="d" * 64, attempt_nonce="e" * 64,
        lease_token="f" * 64, now_ns=20,
    )
    for row in (queued, running):
        with pytest.raises(JobValidationError, match="durably terminal"):
            validate_followup_context(child, lambda _id: row)


def test_ack_only_parent_and_missing_or_foreign_history_fail_closed():
    origin = build_execution_job_spec(execution_request())
    ack = build_followup_job_spec(origin, origin.spec_id, ACK, "ack")
    child = build_followup_job_spec(origin, ack.spec_id, RETRY, "retry")
    rows = {origin.spec_id: terminal(origin), ack.spec_id: terminal(ack)}
    with pytest.raises(JobValidationError, match="acknowledgment-only"):
        validate_followup_context(child, rows.__getitem__)
    child = build_followup_job_spec(origin, origin.spec_id, ACK, "missing")
    with pytest.raises(KeyError):
        validate_followup_context(child, {}.__getitem__)
    other = build_execution_job_spec(execution_request(preparation="/another/prefix"))
    with pytest.raises(JobValidationError, match="another parent"):
        validate_followup_context(child, lambda _id: terminal(other))


def test_dispatch_chain_bound_includes_original_but_ack_record_needs_no_extra_dispatch():
    origin = build_execution_job_spec(execution_request())
    current = origin
    rows = {origin.spec_id: terminal(origin)}
    for index in range(1, MAX_FOLLOWUP_ANCESTRY):
        current = build_followup_job_spec(origin, current.spec_id, RETRY, f"retry-{index}")
        assert len(validate_followup_context(current, rows.__getitem__)) == index
        rows[current.spec_id] = terminal(current)
    assert len(rows) == MAX_FOLLOWUP_ANCESTRY
    ack = build_followup_job_spec(origin, current.spec_id, ACK, "final-ack")
    assert len(validate_followup_context(ack, rows.__getitem__)) == MAX_FOLLOWUP_ANCESTRY
    retry = build_followup_job_spec(origin, current.spec_id, RETRY, "overflow")
    with pytest.raises(JobValidationError, match="bounded original dispatch chain"):
        validate_followup_context(retry, rows.__getitem__)


@pytest.mark.parametrize("outcome_kind", ["completed", "incomplete", "failure"])
def test_ack_wrapper_preserves_exact_original_receipt_or_failure_without_research_authority(
    outcome_kind
):
    case = execution_case(pending=outcome_kind == "incomplete")
    spec = build_followup_job_spec(case.spec, case.spec.spec_id, ACK, "ack-v1")
    raw_outcome = (
        failure_for_dispatch(case, case.spec)
        if outcome_kind == "failure"
        else case.receipt.canonical_bytes
    )
    raw = build_followup_result(spec, case.spec, raw_outcome, "acknowledged_committed")
    assert check_job_result(spec, raw) == digest(raw)
    document = parse(raw, limit=MAX_FOLLOWUP_RESULT_BYTES)
    assert document == {
        "kind": "reduction_job_resolution_v1", "schema_version": 1,
        "job_id": spec.spec_id, "origin_job_id": case.spec.spec_id,
        "parent_job_id": case.spec.spec_id, "action": "acknowledged_committed",
        "dispatch_job_id": case.spec.spec_id, "outcome": parse(raw_outcome),
    }
    assert canonical(document["outcome"]) == raw_outcome


def test_replay_wrapper_requires_current_retry_dispatch_and_its_result_not_failure():
    case = execution_case()
    spec = build_followup_job_spec(case.spec, case.spec.spec_id, RETRY, "retry-A")
    receipt = receipt_for_dispatch(case, spec)
    raw = build_followup_result(spec, spec, receipt.canonical_bytes, "replayed_from_origin")
    assert check_job_result(spec, raw) == digest(raw)
    assert parse(raw, limit=MAX_FOLLOWUP_RESULT_BYTES)["dispatch_job_id"] == spec.spec_id
    with pytest.raises(JobValidationError, match="current retry dispatch"):
        build_followup_result(spec, case.spec, case.receipt.canonical_bytes, "replayed_from_origin")
    with pytest.raises(JobValidationError, match="current retry dispatch"):
        build_followup_result(spec, spec, failure_for_dispatch(case, spec), "replayed_from_origin")
    ack = build_followup_job_spec(case.spec, spec.spec_id, ACK, "ack")
    with pytest.raises(JobValidationError, match="current retry dispatch"):
        build_followup_result(ack, spec, receipt.canonical_bytes, "replayed_from_origin")
    # A retry request may instead acknowledge an already committed ancestor.
    raw = build_followup_result(
        spec, case.spec, case.receipt.canonical_bytes, "acknowledged_committed"
    )
    assert check_job_result(spec, raw) == digest(raw)


@pytest.mark.parametrize(
    "field",
    [
        "job_id", "origin_job_id", "parent_job_id", "dispatch_job_id",
        "action", "schema_version", "extra", "outcome",
    ],
)
def test_rehashed_resolution_wrapper_cannot_change_identity_scope_or_actual_dispatch(field):
    case = execution_case()
    spec = build_followup_job_spec(case.spec, case.spec.spec_id, ACK, "ack")
    raw = build_followup_result(
        spec, case.spec, case.receipt.canonical_bytes, "acknowledged_committed"
    )
    document = parse(raw, limit=MAX_FOLLOWUP_RESULT_BYTES)
    if field in ("job_id", "origin_job_id", "parent_job_id", "dispatch_job_id"):
        document[field] = "0" * 64
    elif field == "action":
        document[field] = "automatic_retry"
    elif field == "schema_version":
        document[field] = True
    elif field == "outcome":
        document[field]["attempt"]["nonce"] = "0" * 32
    else:
        document[field] = False
    with pytest.raises((JobValidationError, EvidenceValidationError)):
        check_job_result(spec, canonical(document))


def test_ack_cannot_bind_an_unrelated_frozen_dispatch_or_expand_the_original_pins():
    case = execution_case()
    spec = build_followup_job_spec(case.spec, case.spec.spec_id, ACK, "ack")
    other = build_execution_job_spec({**case.request, "expected_report_id": "0" * 64})
    with pytest.raises(JobValidationError, match="another frozen original"):
        build_followup_result(spec, other, case.receipt.canonical_bytes, "acknowledged_committed")
    document = case.receipt.document
    document["intent"]["bindings"]["source_report_id"] = "0" * 64
    altered = build_reduction_run_receipt(document)
    with pytest.raises(JobValidationError, match="origin pins"):
        build_followup_result(spec, case.spec, altered.canonical_bytes, "acknowledged_committed")


def test_followup_snapshot_alone_never_claims_that_ack_executed_or_reserved():
    origin = build_execution_job_spec(execution_request())
    for mode in (RETRY, ACK):
        spec = build_followup_job_spec(origin, origin.spec_id, mode, "A")
        for row in (queued_job(spec, now_ns=10), terminal(spec, "SUCCEEDED")):
            view = job_view(row, now_ns=22, coordinator_active=False)
            assert view["scope"]["operation"] == "resolve_reduction_job_v1"
            assert view["scope"]["research_attempt_reserved"] is None
            assert view["scope"]["native_replayed"] is None
            assert view["scope"]["automatic_retry_supported"] is False
