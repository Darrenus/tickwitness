"""Pure recovery document fixtures do not authorize or simulate native retries."""

import json
from copy import deepcopy

import pytest
from test_reduction_records import prepared_case, receipt_document

from tickwitness.domain.evidence.reduction_records import (
    build_reduction_failure,
    build_reduction_intent,
    build_reduction_run_receipt,
)
from tickwitness.domain.evidence.reduction_recovery import (
    MAX_REDUCTION_RECOVERY_BYTES,
    build_reduction_attempt_recovery,
    load_reduction_attempt_recovery,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest

STATUSES = (
    "reserved_without_intent",
    "reserved_unfinalized",
    "committed_failure",
    "committed_result",
)


@pytest.fixture
def reports():
    fixture = prepared_case()
    intent = build_reduction_intent(fixture.materialized)
    receipt = build_reduction_run_receipt(receipt_document(fixture))
    failure = build_reduction_failure(
        fixture.reservation, intent, "engine_failure", "Declared offline failure observation"
    )
    intent_bindings = intent.document["bindings"]
    reports = {}
    for status, disposition in zip(
        STATUSES,
        (
            "owner_review_required",
            "new_original_attempt_required_for_execution",
            "failure_reverified",
            "result_reverified_without_execution",
        ),
        strict=True,
    ):
        bound = status != "reserved_without_intent"
        committed = status.startswith("committed_")
        result = status == "committed_result"
        reports[status] = {
            "kind": "reduction_attempt_recovery_v1",
            "schema_version": 1,
            "source": {
                "bundle_id": intent_bindings["source_bundle_id"],
                "report_id": intent_bindings["source_report_id"],
                "protocol_id": fixture.reservation.protocol_id,
            },
            "preparation_id": intent_bindings["preparation_id"],
            "attempt": fixture.reservation.document,
            "status": status,
            "recovery": {
                "disposition": disposition,
                "restart_mode": "frozen_origin_new_attempt_only_v1",
                "checkpoint_supported": False,
                "execution_authorized": False,
            },
            "bindings": {
                "intent_id": intent.intent_id if bound else None,
                "outcome_id": receipt.run_id if result else digest(failure) if committed else None,
                "run_id": receipt.run_id if result else None,
            },
            "final_manifest": receipt.document if result else None,
            "verification": {
                "source_reaudited": True,
                "preparation_recomputed": True,
                "observed_source_prefix_matched": True,
                "reservation_verified": True,
                "preparation_binding_verified": bound,
                "preparation_cas_verified": bound,
                "terminal_reverified": committed,
                "observation_only": True,
                "attempt_reserved": False,
                "native_replayed": False,
                "research_published": False,
                "job_state_changed": False,
                "checkpoint_restored": False,
                "retry_performed": False,
                "budget_refunded": False,
                "global_absence_verified": False,
                "global_ledger_authenticity_verified": False,
            },
        }
    return reports


@pytest.mark.parametrize("status", STATUSES)
def test_status_roundtrip_preserves_original_reservation_without_execution_authority(
    reports, status
):
    document = reports[status]
    raw = build_reduction_attempt_recovery(document)
    assert raw == canonical(document)
    assert load_reduction_attempt_recovery(raw) == document
    assert document["recovery"]["execution_authorized"] is False
    assert document["verification"]["observation_only"] is True
    loaded = load_reduction_attempt_recovery(raw)
    loaded["attempt"]["nonce"] = "f" * 32
    assert load_reduction_attempt_recovery(raw) == document


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize(
    "field",
    (
        "source_reaudited",
        "preparation_recomputed",
        "observed_source_prefix_matched",
        "reservation_verified",
        "preparation_binding_verified",
        "preparation_cas_verified",
        "terminal_reverified",
        "observation_only",
        "attempt_reserved",
        "native_replayed",
        "research_published",
        "job_state_changed",
        "checkpoint_restored",
        "retry_performed",
        "budget_refunded",
        "global_absence_verified",
        "global_ledger_authenticity_verified",
    ),
)
def test_rehashed_verification_flags_cannot_expand_authority_or_misstate_status(
    reports, status, field
):
    document = reports[status]
    document["verification"][field] = not document["verification"][field]
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("field", ("intent_id", "outcome_id", "run_id"))
def test_bindings_must_follow_the_observed_terminal_status(reports, status, field):
    document = reports[status]
    current = document["bindings"][field]
    document["bindings"][field] = "f" * 64 if current is None else None
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("field", ("intent_id", "outcome_id", "run_id"))
def test_successful_manifest_identity_is_recomputed_instead_of_trusting_outer_hash(reports, field):
    document = reports["committed_result"]
    document["bindings"][field] = "f" * 64
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("field", ("bundle_id", "report_id", "protocol_id", "preparation_id"))
def test_successful_manifest_cannot_be_rebound_to_another_frozen_source(reports, field):
    document = reports["committed_result"]
    if field == "preparation_id":
        document[field] = "f" * 64
    else:
        document["source"][field] = "f" * 64
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


def test_final_manifest_requires_the_same_complete_original_reservation(reports):
    document = reports["committed_result"]
    document["attempt"]["nonce"] = "f" * 32
    with pytest.raises(EvidenceValidationError, match="another original attempt"):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("status", STATUSES)
def test_successful_final_manifest_is_required_only_for_committed_result(reports, status):
    document = reports[status]
    document["final_manifest"] = (
        None if status == "committed_result" else reports["committed_result"]["final_manifest"]
    )
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("field", ("kind", "schema_version", "status", "attempt"))
@pytest.mark.parametrize("value", (None, [], {}, True, 1.0))
def test_malformed_values_are_validation_errors_instead_of_unfinished_observations(
    reports, field, value
):
    document = reports["reserved_without_intent"]
    document[field] = value
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("section", (None, "source", "recovery", "bindings", "verification"))
@pytest.mark.parametrize("change", ("extra", "missing"))
def test_exact_field_sets_reject_ambiguous_or_extended_reports(reports, section, change):
    document = reports["committed_result"]
    target = document if section is None else document[section]
    if change == "extra":
        target["unrecognized_authority"] = False
    else:
        target.pop(next(iter(target)))
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("field", ("checkpoint_supported", "execution_authorized"))
@pytest.mark.parametrize("value", (True, 0, 1))
def test_recovery_scope_never_grants_checkpoint_or_execution_capability(reports, field, value):
    document = reports["reserved_unfinalized"]
    document["recovery"][field] = value
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


def test_boolean_verification_is_not_interchangeable_with_integer_one(reports):
    document = reports["committed_result"]
    document["verification"]["terminal_reverified"] = 1
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


def test_final_manifest_retains_validated_receipt_shape(reports):
    document = reports["committed_result"]
    document["final_manifest"]["execution_status"] = "failed"
    raw_manifest = canonical(document["final_manifest"])
    document["bindings"].update(outcome_id=digest(raw_manifest), run_id=digest(raw_manifest))
    with pytest.raises(EvidenceValidationError):
        build_reduction_attempt_recovery(document)


@pytest.mark.parametrize("form", ("newline", "noncanonical", "duplicate", "oversized"))
def test_loader_rejects_noncanonical_duplicate_or_oversized_bytes(reports, form):
    document = reports["reserved_without_intent"]
    raw = build_reduction_attempt_recovery(document)
    if form == "newline":
        raw += b"\n"
    elif form == "noncanonical":
        raw = json.dumps(document, indent=2).encode()
    elif form == "duplicate":
        raw = b'{"kind":"discarded",' + raw[1:]
    else:
        raw = b" " * (MAX_REDUCTION_RECOVERY_BYTES + 1)
    with pytest.raises(EvidenceValidationError):
        load_reduction_attempt_recovery(raw)


def test_builder_does_not_mutate_the_supplied_observation(reports):
    document = reports["committed_result"]
    before = deepcopy(document)
    build_reduction_attempt_recovery(document)
    assert document == before
