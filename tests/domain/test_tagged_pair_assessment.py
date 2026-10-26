"""Assessment DTO structure is strict and does not replace full semantic closure."""

import json
from dataclasses import FrozenInstanceError

import pytest
from test_tagged_pair_verification import ERRORS, actual_artifacts

from tickwitness.domain.evidence.evaluation import EvaluationValidationError
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.evidence.tagged_pair_verification import (
    MAX_ASSESSMENT_BYTES,
    TaggedPairAssessment,
    assess_tagged_pair_artifacts,
    verify_tagged_pair_artifacts,
)

ASSESSMENT_ERRORS = (*ERRORS, EvaluationValidationError)


@pytest.fixture(scope="module")
def recorded_assessments():
    return [assess_tagged_pair_artifacts(actual_artifacts(mark)) for mark in (100, 102)]


def test_assessment_constructor_roundtrip_identity_and_detached_views(recorded_assessments):
    for original in recorded_assessments:
        loaded = TaggedPairAssessment(original.canonical_bytes)
        assert loaded == original
        assert loaded.assessment_id == digest(original.canonical_bytes)
        assert loaded.document["findings"] == []
        view = loaded.document
        view["runs"][0]["valuation"]["net_marked_pnl"] = "999"
        view["bindings"]["front_result"] = "0" * 64
        assert loaded.document == original.document
        with pytest.raises(FrozenInstanceError):
            loaded.canonical_bytes = b"{}"


@pytest.mark.parametrize(
    "attack",
    [
        "missing_run",
        "extra_run",
        "swapped_runs",
        "old_policy",
        "extra_run_field",
        "run_hash",
        "result_hash",
        "evaluation_hash",
        "invalid_identity",
        "protocol_identity",
        "dataset_identity",
        "attempt_bool",
        "attempt_zero",
        "attempt_oversize",
        "duplicate_attempt",
        "duplicate_slot",
        "duplicate_intent",
        "valuation_extra",
        "valuation_policy",
        "valuation_unit",
        "valuation_eligibility",
        "valuation_reason",
        "valuation_null_pnl",
        "valuation_nonnumeric_pnl",
        "valuation_noncanonical_pnl",
        "truth_integer",
        "truth_null",
        "mark_price_bool",
        "mark_reference",
        "mark_differs",
        "horizon_extra",
        "horizon_time_bool",
        "horizon_target",
        "horizon_conservation",
        "horizon_negative",
        "horizon_own_zero",
        "horizon_position",
        "horizon_account_extra",
        "horizon_account_type",
        "horizon_cash",
        "horizon_order_leaves",
        "horizon_order_status",
        "horizon_order_count",
        "horizon_other_observation",
        "comparison_extra",
        "comparison_truth",
        "comparison_relation",
        "comparison_environment_bool",
        "comparison_reason",
        "scope",
        "findings",
    ],
)
def test_standalone_assessment_rejects_incoherent_serialized_structure(
    recorded_assessments, attack
):
    doc = recorded_assessments[1].document
    front, back = doc["runs"]
    valuation, horizon = front["valuation"], front["horizon"]
    if attack == "missing_run":
        doc["runs"].pop()
    elif attack == "extra_run":
        doc["runs"].append(back)
    elif attack == "swapped_runs":
        doc["runs"].reverse()
    elif attack == "old_policy":
        front["policy_id"] = "cancel_front_first_v1"
    elif attack == "extra_run_field":
        front["certified_owner"] = True
    elif attack in ("run_hash", "result_hash", "evaluation_hash"):
        front[
            {
                "run_hash": "run_id",
                "result_hash": "result_sha256",
                "evaluation_hash": "evaluation_sha256",
            }[attack]
        ] = "0" * 64
    elif attack == "invalid_identity":
        front["intent_id"] = "../outside"
    elif attack == "protocol_identity":
        doc["protocol_id"] = "0" * 64
    elif attack == "dataset_identity":
        doc["dataset_id"] = "0" * 64
    elif attack.startswith("attempt_"):
        front["attempt_index"] = {"attempt_bool": True, "attempt_zero": 0, "attempt_oversize": 101}[
            attack
        ]
    elif attack in ("duplicate_attempt", "duplicate_slot", "duplicate_intent"):
        key = {
            "duplicate_attempt": "attempt_id",
            "duplicate_slot": "attempt_index",
            "duplicate_intent": "intent_id",
        }[attack]
        front[key] = back[key]
    elif attack == "valuation_extra":
        valuation["source_claim_evaluated"] = True
    elif attack == "valuation_policy":
        valuation["policy_id"] = "source_claim_profit_v1"
    elif attack == "valuation_unit":
        valuation["unit"] = "EUR"
    elif attack == "valuation_eligibility":
        valuation["eligible"] = 1
    elif attack == "valuation_reason":
        valuation["reason"] = "unverified"
    elif attack == "valuation_null_pnl":
        valuation["net_marked_pnl"] = None
    elif attack == "valuation_nonnumeric_pnl":
        valuation["net_marked_pnl"] = "NaN"
    elif attack == "valuation_noncanonical_pnl":
        valuation["net_marked_pnl"] = "2.00"
    elif attack == "truth_integer":
        front["truth"] = 1
    elif attack == "truth_null":
        front["truth"] = None
    elif attack == "mark_price_bool":
        valuation["mark"]["price_ticks"] = True
    elif attack == "mark_reference":
        valuation["mark"]["source_ref"]["capture_seq"] = 0
    elif attack == "mark_differs":
        valuation["mark"]["price_ticks"] += 1
    elif attack == "horizon_extra":
        horizon["after_cleanup"] = True
    elif attack == "horizon_time_bool":
        horizon["native_time_ns"] = True
    elif attack == "horizon_target":
        horizon["native_target_lots"] += 1
    elif attack == "horizon_conservation":
        horizon["queue_state"]["external_lots"] += 1
    elif attack == "horizon_negative":
        horizon["queue_state"]["ahead_lots"] = -1
    elif attack == "horizon_own_zero":
        horizon["queue_state"]["own_filled_lots"] = 0
    elif attack == "horizon_position":
        horizon["account"]["net_position_lots"] += 1
    elif attack == "horizon_account_extra":
        horizon["account"]["trusted_author"] = True
    elif attack == "horizon_account_type":
        horizon["account"]["account_type"] = "CASH"
    elif attack == "horizon_cash":
        horizon["account"]["cash_free"] = "1"
    elif attack == "horizon_order_leaves":
        horizon["account"]["orders"][0]["remaining_quantity_lots"] += 1
    elif attack == "horizon_order_status":
        horizon["account"]["orders"][0]["status"] = "CANCELED"
    elif attack == "horizon_order_count":
        horizon["account"]["orders"] = []
    elif attack == "horizon_other_observation":
        back["horizon"]["native_time_ns"] += 1
    elif attack == "comparison_extra":
        doc["comparison"]["proof_complete"] = True
    elif attack == "comparison_truth":
        doc["comparison"]["truths"] = [False, True]
    elif attack == "comparison_relation":
        doc["comparison"]["relation"] = "same_truth_value"
    elif attack == "comparison_environment_bool":
        doc["comparison"]["same_execution_environment"] = 1
    elif attack == "comparison_reason":
        doc["comparison"]["ineligible_reason"] = "execution_environment_mismatch"
    elif attack == "scope":
        doc["scope"]["finding_issued"] = True
    else:
        doc["findings"] = [{"type": "NOT_IDENTIFIABLE_WITHIN_MODEL"}]
    with pytest.raises(ASSESSMENT_ERRORS):
        TaggedPairAssessment(canonical(doc))


@pytest.mark.parametrize("environment_equal", [True, False])
def test_structural_ineligibility_requires_null_truth_and_explicit_comparison_reason(
    recorded_assessments, environment_equal
):
    doc = recorded_assessments[1].document
    doc["runs"][0]["valuation"].update(
        eligible=False, reason="native_fee_rounding_ambiguous", net_marked_pnl=None
    )
    doc["runs"][0]["truth"] = None
    doc["comparison"].update(
        relation="ineligible",
        truths=[None, False],
        same_execution_environment=environment_equal,
        ineligible_reason="claim_evaluation_ineligible"
        if environment_equal
        else "execution_environment_mismatch",
    )
    assert TaggedPairAssessment(canonical(doc)).document == doc
    doc["comparison"]["relation"] = "opposite_truth_values"
    with pytest.raises(ASSESSMENT_ERRORS):
        TaggedPairAssessment(canonical(doc))


def test_a_structurally_coherent_self_attestation_is_not_full_semantic_verification(
    recorded_assessments,
):
    artifacts = actual_artifacts(102)
    doc = recorded_assessments[1].document
    doc["runs"][0]["truth"] = False
    doc["comparison"].update(truths=[False, False], relation="same_truth_value")
    # This DTO does not contain the full protocol or its numeric threshold.
    changed = TaggedPairAssessment(canonical(doc))
    assert changed.assessment_id != recorded_assessments[1].assessment_id
    with pytest.raises(ASSESSMENT_ERRORS, match="does not reproduce"):
        verify_tagged_pair_artifacts({**artifacts, "assessment": changed.canonical_bytes})


@pytest.mark.parametrize("invalid", [b"", b"{}", b'{"kind":1,"kind":2}', b'{"x":NaN}'])
def test_malformed_or_duplicate_assessment_json_is_rejected(invalid):
    with pytest.raises(ASSESSMENT_ERRORS):
        TaggedPairAssessment(invalid)


def test_assessment_byte_and_canonical_bounds_are_enforced(recorded_assessments):
    with pytest.raises(ASSESSMENT_ERRORS):
        TaggedPairAssessment(recorded_assessments[0].canonical_bytes + b"\n")
    with pytest.raises(ASSESSMENT_ERRORS):
        TaggedPairAssessment(b"x" * (MAX_ASSESSMENT_BYTES + 1))
    noncanonical = json.dumps(recorded_assessments[0].document, indent=2).encode()
    with pytest.raises(ASSESSMENT_ERRORS):
        TaggedPairAssessment(noncanonical)
