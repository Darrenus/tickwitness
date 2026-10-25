"""Receipt identities are immutable and malformed structures fail predictably."""

from dataclasses import FrozenInstanceError, replace

import pytest

from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    RunReceipt,
    canonical,
    digest,
)


def reservation_document():
    return {
        "kind": "replay_attempt_reservation_v1",
        "schema_version": 1,
        "protocol_id": "a" * 64,
        "attempt_index": 1,
        "nonce": "b" * 32,
        "max_wall_seconds": 60,
        "created_at_utc": "2026-10-26T00:00:00.000000+00:00",
    }


def receipt_document():
    return {
        "kind": "research_run_receipt_v1",
        "schema_version": 1,
        "attempt": reservation_document(),
        "protocol_id": "a" * 64,
        "claim_revision_id": "c" * 64,
        "execution_status": "completed",
        "scope": {"phase": "development", "scenario_id": "baseline_v1", "search_performed": False},
        "bindings": {
            key: "d" * 64
            for key in (
                "dataset_id",
                "data_sha256",
                "replay_spec_id",
                "replay_result_sha256",
                "evaluation_sha256",
            )
        },
    }


@pytest.mark.parametrize("status", [[], {}, True, 1, None, "failed"])
def test_invalid_status_is_a_validation_error_not_unhashable_exception(status: object) -> None:
    raw = canonical(dict(receipt_document(), execution_status=status))
    with pytest.raises(EvidenceValidationError):
        RunReceipt(digest(raw), raw)


def test_reservation_rejects_invalid_utc_calendar() -> None:
    raw = canonical(dict(reservation_document(), created_at_utc="2026-99-26T00:00:00.000000+00:00"))
    with pytest.raises(EvidenceValidationError, match="timestamp"):
        AttemptReservation(digest(raw), raw)


def test_detached_views_and_direct_constructor_cannot_mutate_identity() -> None:
    raw = canonical(receipt_document())
    receipt = RunReceipt(digest(raw), raw)
    view = receipt.document
    view["bindings"]["dataset_id"] = "e" * 64
    assert receipt.document["bindings"]["dataset_id"] == "d" * 64
    with pytest.raises(FrozenInstanceError):
        receipt.run_id = "f" * 64
    with pytest.raises(EvidenceValidationError):
        replace(receipt, run_id="f" * 64)
    with pytest.raises(EvidenceValidationError):
        RunReceipt(receipt.run_id, bytearray(raw))
