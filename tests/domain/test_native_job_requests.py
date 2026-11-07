"""Native DTOs carry frozen input and credentials, never file-store capability."""

import json

import pytest
from test_reduction_records import prepared_case

from tickwitness.domain.evidence.reduction_records import build_reduction_intent
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
)
from tickwitness.domain.jobs.contracts import execution_dispatch_nonce
from tickwitness.domain.jobs.native_requests import (
    MAX_NATIVE_JOB_REQUEST_BYTES,
    build_native_worker_request,
    load_native_worker_request,
)


@pytest.fixture
def native_request():
    fixture = prepared_case()
    job_id = "a" * 64
    document = fixture.reservation.document
    document["nonce"] = execution_dispatch_nonce(job_id)
    raw = canonical(document)
    reservation = AttemptReservation(digest(raw), raw)
    return build_native_worker_request(
        job_id=job_id,
        coordinator_id="b" * 64,
        job_attempt_id="c" * 64,
        lease_token="d" * 64,
        research_attempt=reservation,
        intent=build_reduction_intent(fixture.materialized),
        replay_input=fixture.materialized.replay_input,
        native_deadline_ns=9_000_000_000,
    )


def test_bounded_native_request_roundtrip_binds_original_slot_and_exact_frozen_input(
    native_request,
):
    document, replay, reservation, intent = load_native_worker_request(native_request)
    payload = document["payload"]
    assert reservation.document["nonce"] == execution_dispatch_nonce(document["job_id"])
    assert payload["normalized"].encode() == replay.normalized_bytes
    assert intent.document["bindings"]["prefix_context_id"] == replay.dataset_id
    assert canonical(document) == native_request
    assert set(payload) == {
        "research_attempt",
        "intent",
        "dataset_id",
        "normalized",
        "replay_spec",
        "native_deadline_ns",
    }
    assert not {"runs", "input_root", "source_evidence", "preparation", "spec", "jobs"} & set(
        document
    )


@pytest.mark.parametrize("section", [None, "payload"])
@pytest.mark.parametrize("field", ["runs", "jobs", "input_root", "engine_command", "checkpoint"])
def test_native_request_refuses_owner_locators_and_execution_extensions(
    native_request, section, field
):
    document = json.loads(native_request)
    target = document if section is None else document[section]
    target[field] = "/owner/forbidden"
    with pytest.raises(EvidenceValidationError):
        load_native_worker_request(canonical(document))


@pytest.mark.parametrize(
    "field",
    ["dataset_id", "normalized", "replay_spec", "research_attempt", "intent", "native_deadline_ns"],
)
@pytest.mark.parametrize("bad", [None, [], True, 1.0])
def test_native_request_rejects_invalid_payload_types(native_request, field, bad):
    document = json.loads(native_request)
    document["payload"][field] = bad
    with pytest.raises(EvidenceValidationError):
        load_native_worker_request(canonical(document))


@pytest.mark.parametrize("change", ["job", "nonce", "data", "context", "spec"])
def test_rehashed_native_request_cannot_substitute_frozen_identity(native_request, change):
    document = json.loads(native_request)
    payload = document["payload"]
    if change == "job":
        document["job_id"] = "0" * 64
    elif change == "nonce":
        payload["research_attempt"]["nonce"] = "0" * 32
    elif change == "data":
        payload["normalized"] += "\n"
    elif change == "context":
        payload["dataset_id"] = "0" * 64
    else:
        payload["replay_spec"]["seed"] = 98765
    with pytest.raises(EvidenceValidationError):
        load_native_worker_request(canonical(document))


@pytest.mark.parametrize("bad", [0, -1, 1 << 63, True])
def test_native_deadline_is_bounded_exact_integer(native_request, bad):
    document = json.loads(native_request)
    document["payload"]["native_deadline_ns"] = bad
    with pytest.raises(EvidenceValidationError):
        load_native_worker_request(canonical(document))


@pytest.mark.parametrize("kind", ["duplicate", "noncanonical", "oversized"])
def test_native_request_parser_rejects_ambiguous_or_oversized_bytes(native_request, kind):
    raw = native_request
    if kind == "duplicate":
        raw = b'{"job_id":"discarded",' + raw[1:]
    elif kind == "noncanonical":
        raw += b"\n"
    else:
        raw = b" " * (MAX_NATIVE_JOB_REQUEST_BYTES + 1)
    with pytest.raises(EvidenceValidationError):
        load_native_worker_request(raw)
