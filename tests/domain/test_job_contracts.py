"""Pure lifecycle rules; real coordinator/worker death is qualified remotely."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import (
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

LEASE = MIN_JOB_LEASE_NS


def request(**changes):
    return {
        "run_id": "a" * 64,
        "expected_bundle_id": "b" * 64,
        "expected_report_id": "c" * 64,
        "input_root": "/workspace/inputs",
        "runs": "/workspace/original-runs",
        "source_evidence": "source/evidence",
        "split": "development",
        **changes,
    }


def queued(*, now=10, lease=LEASE):
    return queued_job(build_job_spec(request(), lease_duration_ns=lease), now_ns=now)


def running(*, created=10, claimed=20, lease=LEASE):
    return claim_job(
        queued(now=created, lease=lease),
        coordinator_id="d" * 64,
        attempt_nonce="e" * 64,
        lease_token="f" * 64,
        now_ns=claimed,
    )


def credentials(row, **changes):
    attempt = row["attempt"]
    return {
        "coordinator_id": attempt["coordinator_id"],
        "job_attempt_id": attempt["job_attempt_id"],
        "lease_token": attempt["lease_token"],
        **changes,
    }


def heartbeat(row, *, sequence=1, now=21, **changes):
    return heartbeat_job(row, **credentials(row, **changes), sequence=sequence, now_ns=now)


def finish(row, *, result="1" * 64, failure=None, now=21, **changes):
    return finish_job(
        row, **credentials(row, **changes), result_sha256=result, failure=failure, now_ns=now
    )


def failure(**changes):
    return {
        "code": "worker_failed",
        "message": "Worker exited without a valid result",
        "worker_exit_code": -9,
        **changes,
    }


def test_spec_is_frozen_content_identity_with_explicit_operation_and_locator_pins():
    original = request()
    spec = build_job_spec(original)
    assert spec.spec_id == digest(spec.canonical_bytes)
    assert spec.document == {
        "kind": "comparison_job_spec_v1",
        "schema_version": 1,
        "operation": "compare_reduction_run_v1",
        "request": original,
        "lease_duration_ns": 30_000_000_000,
    }
    assert load_job_spec(spec.canonical_bytes) == spec
    assert build_job_spec(request()) == spec
    original["run_id"] = "0" * 64
    detached = spec.document
    detached["request"]["run_id"] = "0" * 64
    assert spec.document["request"]["run_id"] == "a" * 64
    with pytest.raises(FrozenInstanceError):
        spec.spec_id = "0" * 64
    with pytest.raises(JobValidationError, match="identity"):
        JobSpec("0" * 64, spec.canonical_bytes)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", False),
        ("run_id", "a" * 63),
        ("run_id", "A" * 64),
        ("expected_bundle_id", None),
        ("expected_report_id", "g" * 64),
        ("input_root", "relative/root"),
        ("runs", ""),
        ("runs", "/a\x00b"),
        ("input_root", "/" + "a" * 4096),
        ("source_evidence", "a" * 4097),
        ("source_evidence", ""),
        ("source_evidence", "/absolute"),
        ("source_evidence", "."),
        ("source_evidence", ".."),
        ("source_evidence", "./source"),
        ("source_evidence", "source/./nested"),
        ("source_evidence", "source/../nested"),
        ("source_evidence", "../source"),
        ("source_evidence", "source\x00name"),
        ("source_evidence", "..\\source"),
        ("source_evidence", "source\\..\\nested"),
        ("source_evidence", "\\absolute"),
        ("split", "confirmation"),
        ("split", None),
    ],
)
def test_request_must_use_development_pins_and_bounded_posix_locators(field, value):
    with pytest.raises(JobValidationError):
        build_job_spec(request(**{field: value}))


@pytest.mark.parametrize("change", ["extra", "missing", "not_object"])
def test_request_is_exact_and_cannot_add_engine_research_budget_or_retry_authority(change):
    value = request()
    if change == "extra":
        value["research_budget"] = {"max_attempts": 100}
    elif change == "missing":
        value.pop("run_id")
    else:
        value = []
    with pytest.raises(JobValidationError):
        build_job_spec(value)


@pytest.mark.parametrize(
    "lease", [True, False, 0, LEASE - 1, MAX_JOB_LEASE_NS + 1, 1.0, "1000000000"]
)
def test_lease_is_a_nonboolean_bounded_integer(lease):
    with pytest.raises(JobValidationError):
        build_job_spec(request(), lease_duration_ns=lease)


@pytest.mark.parametrize("lease", [MIN_JOB_LEASE_NS, MAX_JOB_LEASE_NS])
def test_lease_boundaries_and_absolute_locator_text_are_preserved(lease):
    spec = build_job_spec(request(input_root="/owner/../trusted-inputs"), lease_duration_ns=lease)
    assert spec.document["lease_duration_ns"] == lease
    assert spec.document["request"]["input_root"] == "/owner/../trusted-inputs"


@pytest.mark.parametrize(
    "attack", ["newline", "duplicate", "float", "schema_bool", "operation", "unknown", "oversize"]
)
def test_spec_encoding_and_descriptor_shape_are_strict(attack):
    spec = build_job_spec(request())
    document = spec.document
    if attack == "newline":
        raw = spec.canonical_bytes + b"\n"
    elif attack == "duplicate":
        raw = spec.canonical_bytes[:-1] + b',"schema_version":1}'
    elif attack == "float":
        raw = spec.canonical_bytes.replace(b'"schema_version":1', b'"schema_version":1.0')
    elif attack == "oversize":
        raw = b" " * (MAX_JOB_SPEC_BYTES + 1)
    else:
        if attack == "schema_bool":
            document["schema_version"] = True
        elif attack == "operation":
            document["operation"] = "run_native_research_v1"
        else:
            document["unknown"] = None
        raw = canonical(document)
    with pytest.raises(JobValidationError):
        load_job_spec(raw)


def test_initial_job_and_attempt_have_separate_content_bound_identities():
    spec = build_job_spec(request(), lease_duration_ns=LEASE)
    row = queued_job(spec, now_ns=10)
    assert row == {
        "kind": "job_snapshot_v1",
        "schema_version": 1,
        "job_id": spec.spec_id,
        "spec": spec.document,
        "state": "QUEUED",
        "version": 1,
        "created_at_ns": 10,
        "updated_at_ns": 10,
        "attempt": None,
        "result_sha256": None,
        "failure": None,
    }
    claimed = claim_job(
        row, coordinator_id="d" * 64, attempt_nonce="e" * 64, lease_token="f" * 64, now_ns=20
    )
    expected_id = digest(
        canonical({"job_id": row["job_id"], "attempt_number": 1, "nonce": "e" * 64})
    )
    assert claimed["state"] == "RUNNING" and claimed["version"] == 2
    assert claimed["attempt"] == {
        "job_attempt_id": expected_id,
        "attempt_number": 1,
        "nonce": "e" * 64,
        "coordinator_id": "d" * 64,
        "lease_token": "f" * 64,
        "heartbeat_sequence": 0,
        "heartbeat_at_ns": 20,
        "lease_expires_at_ns": 20 + LEASE,
    }
    assert expected_id not in (row["job_id"], request()["run_id"])
    assert row["state"] == "QUEUED" and row["attempt"] is None
    other = queued_job(build_job_spec(request(run_id="0" * 64)), now_ns=10)
    other_claim = claim_job(
        other, coordinator_id="d" * 64, attempt_nonce="e" * 64, lease_token="f" * 64, now_ns=20
    )
    assert other_claim["attempt"]["job_attempt_id"] != expected_id


def test_heartbeat_extends_lease_and_each_accepted_mutation_increments_version():
    row = running()
    before = canonical(row)
    first = heartbeat(row, sequence=1, now=21)
    second = heartbeat(first, sequence=2, now=21)
    assert first["attempt"]["heartbeat_sequence"] == 1
    assert first["attempt"]["heartbeat_at_ns"] == 21
    assert first["attempt"]["lease_expires_at_ns"] == 21 + LEASE
    assert [row["version"], first["version"], second["version"]] == [2, 3, 4]
    assert canonical(row) == before
    done = finish(second, now=22)
    assert done["state"] == "SUCCEEDED" and done["version"] == 5
    assert done["result_sha256"] == "1" * 64 and done["failure"] is None
    assert done["attempt"]["heartbeat_sequence"] == 2
    assert load_job_snapshot(canonical(done)) == done


@pytest.mark.parametrize("field", ["coordinator_id", "job_attempt_id", "lease_token"])
@pytest.mark.parametrize("operation", ["heartbeat", "finish"])
def test_worker_messages_require_exact_current_credentials(field, operation):
    row = running()
    before = canonical(row)
    action = heartbeat if operation == "heartbeat" else finish
    with pytest.raises(JobValidationError, match="credentials differ"):
        action(row, **{field: "0" * 64})
    assert canonical(row) == before


@pytest.mark.parametrize("sequence", [0, 1, 3, -1, True, 1.0, None, MAX_JOB_INTEGER + 1])
def test_duplicate_skipped_or_invalid_heartbeat_sequence_is_rejected(sequence):
    row = heartbeat(running())
    before = canonical(row)
    with pytest.raises(JobValidationError):
        heartbeat(row, sequence=sequence, now=22)
    assert canonical(row) == before


def test_lease_boundary_rejects_heartbeat_and_success_instead_of_extending_late_worker():
    row = running()
    expiry = row["attempt"]["lease_expires_at_ns"]
    last_moment = heartbeat(row, now=expiry - 1)
    assert last_moment["attempt"]["lease_expires_at_ns"] == expiry - 1 + LEASE
    for action in (heartbeat, finish):
        with pytest.raises(JobValidationError, match="lease has expired"):
            action(row, now=expiry)
    assert row["state"] == "RUNNING" and row["version"] == 2


@pytest.mark.parametrize("operation", ["heartbeat", "finish", "lose"])
def test_mutations_refuse_a_coordinator_clock_earlier_than_stored_time(operation):
    row = running()
    with pytest.raises(JobValidationError, match="clock moved backwards"):
        if operation == "lose":
            lose_job(row, reason="coordinator_lost", now_ns=19)
        elif operation == "heartbeat":
            heartbeat(row, now=19)
        else:
            finish(row, now=19)


@pytest.mark.parametrize("exit_code", [None, -255, -9, 0, 7, 255])
def test_diagnostic_failure_is_an_operational_terminal_not_a_research_result(exit_code):
    row = finish(running(), result=None, failure=failure(worker_exit_code=exit_code))
    assert row["state"] == "FAILED" and row["version"] == 3
    assert row["result_sha256"] is None
    assert row["failure"]["worker_exit_code"] == exit_code
    assert "findings" not in row and "claim_truth" not in row


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", ""),
        ("code", "x" * 129),
        ("code", False),
        ("message", "x" * 2049),
        ("message", None),
        ("worker_exit_code", -256),
        ("worker_exit_code", 256),
        ("worker_exit_code", True),
        ("worker_exit_code", 1.0),
        ("worker_exit_code", "7"),
    ],
)
def test_failure_diagnostic_shape_and_bounds_are_checked(field, value):
    with pytest.raises(JobValidationError):
        finish(running(), result=None, failure=failure(**{field: value}))


@pytest.mark.parametrize(
    ("result", "diagnostic"),
    [
        (None, None),
        ("1" * 64, failure()),
        (False, None),
        ("", None),
        ("A" * 64, None),
        (None, False),
        (None, {}),
        (None, failure(extra=True)),
    ],
)
def test_success_and_failure_are_exclusive_and_false_cannot_replace_null(result, diagnostic):
    with pytest.raises(JobValidationError):
        finish(running(), result=result, failure=diagnostic)


def test_loss_reasons_are_explicit_and_expiry_cannot_be_invented():
    row = running()
    with pytest.raises(JobValidationError, match="has not expired"):
        lose_job(row, reason="lease_expired", now_ns=21)
    expiry = row["attempt"]["lease_expires_at_ns"]
    lost = lose_job(row, reason="lease_expired", now_ns=expiry)
    assert lost["state"] == "LOST" and lost["version"] == 3
    assert lost["failure"]["code"] == "lease_expired"
    assert lost["failure"]["worker_exit_code"] is None
    owner_lost = lose_job(row, reason="coordinator_lost", now_ns=20)
    assert owner_lost["state"] == "LOST"
    assert owner_lost["failure"]["code"] == "coordinator_lost"
    assert owner_lost["result_sha256"] is None


@pytest.mark.parametrize("reason", ["timeout", "retry", "", None, [], {}])
def test_unrecognized_loss_is_typed_error_without_loose_membership_exceptions(reason):
    with pytest.raises(JobValidationError):
        lose_job(running(), reason=reason, now_ns=21)


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "FAILED", "LOST"])
def test_terminal_attempts_reject_all_late_messages_resets_and_retries(terminal):
    base = running()
    if terminal == "SUCCEEDED":
        row = finish(base)
    elif terminal == "FAILED":
        row = finish(base, result=None, failure=failure())
    else:
        row = lose_job(base, reason="coordinator_lost", now_ns=21)
    before = canonical(row)
    for action in (heartbeat, finish):
        with pytest.raises(JobValidationError, match="running job"):
            action(row, now=22)
    with pytest.raises(JobValidationError, match="queued job"):
        claim_job(
            row, coordinator_id="2" * 64, attempt_nonce="3" * 64, lease_token="4" * 64, now_ns=22
        )
    with pytest.raises(JobValidationError, match="running job"):
        lose_job(row, reason="coordinator_lost", now_ns=22)
    assert canonical(row) == before


def test_running_job_cannot_be_claimed_twice_and_queued_job_cannot_finish_or_lose():
    row = running()
    with pytest.raises(JobValidationError, match="queued job"):
        claim_job(
            row, coordinator_id="d" * 64, attempt_nonce="e" * 64, lease_token="f" * 64, now_ns=21
        )
    with pytest.raises(JobValidationError, match="running job"):
        finish_job(
            queued(),
            coordinator_id="d" * 64,
            job_attempt_id="e" * 64,
            lease_token="f" * 64,
            result_sha256="1" * 64,
            failure=None,
            now_ns=21,
        )
    with pytest.raises(JobValidationError, match="running job"):
        lose_job(queued(), reason="coordinator_lost", now_ns=21)


def test_effective_liveness_is_readonly_and_distinct_from_stored_state():
    row = running()
    before = canonical(row)
    expiry = row["attempt"]["lease_expires_at_ns"]
    assert effective_state(row, now_ns=20, coordinator_active=True) == "RUNNING"
    assert effective_state(row, now_ns=19, coordinator_active=True) == "CLOCK_UNCERTAIN"
    assert effective_state(row, now_ns=expiry, coordinator_active=True) == "LEASE_EXPIRED"
    assert effective_state(row, now_ns=19, coordinator_active=False) == "COORDINATOR_LOST"
    assert effective_state(row, now_ns=expiry, coordinator_active=False) == "COORDINATOR_LOST"
    assert canonical(row) == before and row["state"] == "RUNNING"
    assert effective_state(queued(), now_ns=0, coordinator_active=False) == "QUEUED"
    done = finish(row)
    assert effective_state(done, now_ns=0, coordinator_active=False) == "SUCCEEDED"


@pytest.mark.parametrize("value", [None, 1, "true", []])
def test_effective_activity_requires_a_boolean_observation(value):
    with pytest.raises(JobValidationError):
        effective_state(running(), now_ns=20, coordinator_active=value)


@pytest.mark.parametrize("now", [True, -1, 1.0, None, MAX_JOB_INTEGER + 1])
def test_times_are_nonboolean_bounded_integer_nanoseconds(now):
    with pytest.raises(JobValidationError):
        queued(now=now)
    with pytest.raises(JobValidationError):
        heartbeat(running(), now=now)
    with pytest.raises(JobValidationError):
        effective_state(running(), now_ns=now, coordinator_active=True)


def test_lease_and_version_addition_overflows_never_wrap_or_mutate_the_input():
    with pytest.raises(JobValidationError, match="overflows"):
        claim_job(
            queued(now=MAX_JOB_INTEGER),
            coordinator_id="d" * 64,
            attempt_nonce="e" * 64,
            lease_token="f" * 64,
            now_ns=MAX_JOB_INTEGER,
        )
    near_end = running(created=MAX_JOB_INTEGER - 2 * LEASE, claimed=MAX_JOB_INTEGER - 2 * LEASE)
    near_end = heartbeat(near_end, now=MAX_JOB_INTEGER - LEASE - 1)
    before = canonical(near_end)
    with pytest.raises(JobValidationError, match="overflows"):
        heartbeat(near_end, sequence=2, now=MAX_JOB_INTEGER - 2)
    assert canonical(near_end) == before
    maximal = running()
    maximal["version"] = MAX_JOB_INTEGER
    maximal["attempt"]["heartbeat_sequence"] = MAX_JOB_INTEGER - 2
    maximal = load_job_snapshot(canonical(maximal))
    for action in (finish, heartbeat):
        with pytest.raises(JobValidationError, match="overflows"):
            if action is heartbeat:
                action(maximal, sequence=MAX_JOB_INTEGER - 1)
            else:
                action(maximal)


@pytest.mark.parametrize(
    "attack",
    [
        "field",
        "schema_bool",
        "job_id",
        "spec",
        "state",
        "effective_state",
        "version",
        "created",
        "heartbeat",
        "expiry",
        "nonce",
        "attempt_id",
        "attempt_number",
        "running_result",
        "running_failure",
        "sequence_bool",
    ],
)
def test_saved_snapshot_cross_bindings_cannot_be_rehashed_into_valid_state(attack):
    row = running()
    if attack == "field":
        row["extra"] = None
    elif attack == "schema_bool":
        row["schema_version"] = True
    elif attack == "job_id":
        row["job_id"] = "0" * 64
    elif attack == "spec":
        row["spec"]["request"]["run_id"] = "0" * 64
    elif attack == "state":
        row["state"] = []
    elif attack == "effective_state":
        row["state"] = "LEASE_EXPIRED"
    elif attack == "version":
        row["version"] += 1
    elif attack == "created":
        row["created_at_ns"] = row["updated_at_ns"] + 1
    elif attack == "heartbeat":
        row["attempt"]["heartbeat_at_ns"] -= 1
    elif attack == "expiry":
        row["attempt"]["lease_expires_at_ns"] += 1
    elif attack == "nonce":
        row["attempt"]["nonce"] = "0" * 64
    elif attack == "attempt_id":
        row["attempt"]["job_attempt_id"] = "0" * 64
    elif attack == "attempt_number":
        row["attempt"]["attempt_number"] = 2
    elif attack == "running_result":
        row["result_sha256"] = "1" * 64
    elif attack == "running_failure":
        row["failure"] = failure()
    else:
        row["attempt"]["heartbeat_sequence"] = False
    with pytest.raises(JobValidationError):
        load_job_snapshot(canonical(row))


def test_queued_and_terminal_snapshot_invariants_survive_saved_shape_validation():
    queued_row = queued()
    queued_row["updated_at_ns"] += 1
    with pytest.raises(JobValidationError, match="Queued job"):
        load_job_snapshot(canonical(queued_row))
    success = finish(running())
    success["failure"] = failure()
    with pytest.raises(JobValidationError, match="Succeeded job"):
        load_job_snapshot(canonical(success))
    lost = lose_job(running(), reason="coordinator_lost", now_ns=21)
    lost["failure"]["code"] = "lease_expired"
    with pytest.raises(JobValidationError, match="predates"):
        load_job_snapshot(canonical(lost))


def test_snapshot_encoding_and_views_are_detached_without_recovery_side_effects():
    row = running()
    raw = canonical(row)
    loaded = load_job_snapshot(raw)
    loaded["attempt"]["nonce"] = "0" * 64
    assert load_job_snapshot(raw) == row
    with pytest.raises(JobValidationError):
        load_job_snapshot(raw + b"\n")
    with pytest.raises(JobValidationError):
        load_job_snapshot(raw[:-1] + b',"schema_version":1}')
    with pytest.raises(JobValidationError):
        load_job_snapshot(b" " * (MAX_JOB_SNAPSHOT_BYTES + 1))
    with pytest.raises(JobValidationError):
        queued_job(replace(build_job_spec(request()), spec_id="0" * 64), now_ns=0)


def test_input_failure_mapping_is_detached_after_the_transition():
    diagnostic = failure()
    row = finish(running(), result=None, failure=diagnostic)
    before = deepcopy(row)
    diagnostic["message"] = "mutated"
    assert row == before


@pytest.mark.parametrize("value", [None, {}, [], "spec"])
def test_queue_requires_a_frozen_spec_and_snapshot_loader_requires_canonical_bytes(value):
    with pytest.raises(JobValidationError):
        queued_job(value, now_ns=0)
    with pytest.raises(JobValidationError):
        load_job_snapshot(value)
