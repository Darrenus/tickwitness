"""Preservation uses original numeric criteria and reaudited reduced evidence.

These are declared offline consistency fixtures. Real native qualification is
performed by the installed remote smoke, not by these test-data transformations.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import localcontext
from types import SimpleNamespace

import pytest
from test_evaluation import _ambiguous_fixture
from test_reduction_records import prepared_case, receipt_document

from tickwitness.domain.assumptions import (
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.evidence.reduction_preservation import ReductionPreservationAssessment
from tickwitness.domain.evidence.reduction_records import (
    ReductionStateAudit,
    build_reduction_intent,
    build_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
)
from tickwitness.domain.reduction.contracts import (
    ReductionSource,
    build_reduction_recipe,
    materialize_reduction,
)
from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import (
    FINDING_AUTHORITY_ID,
    build_search_finding_protocol,
)
from tickwitness.domain.search.plans import build_search_plan


def _case(*, comparator="gt", threshold="0", pending=False, variant=None):
    original = prepared_case(pending=pending)
    validated = original.materialized.source.validation
    spec = validated.replay_input.spec
    document = original.result.document
    if variant == "ambiguous":
        changed_input, ambiguous = _ambiguous_fixture()
        assert changed_input.normalized_bytes == validated.replay_input.normalized_bytes
        spec, document = changed_input.spec, ambiguous.document
    if variant == "no_fills":
        document["fill_trace"] = []
        rejected = deepcopy(document["order_trace"][2])
        rejected.update(kind="OrderRejected", ordinal=2)
        rejected["fields"].update(status="REJECTED", reason="declared offline rejection")
        document["order_trace"] = document["order_trace"][:2] + [rejected]
        final = deepcopy(document["account_trace"][-1])
        final["ordinal"] = 1
        final["fields"].update(
            net_position_lots=0,
            observed_fill_lots=0,
            observed_commission="0",
            cash_total="10000",
            cash_free="10000",
            cash_locked="0",
        )
        final["fields"]["orders"][0].update(
            status="REJECTED", filled_quantity_lots=0, remaining_quantity_lots=2
        )
        document["account_trace"] = [document["account_trace"][0], final]
    claim = validated.protocol.document["claim"]
    claim.update(comparator=comparator, threshold=threshold)
    protocol = build_executable_protocol(
        canonical(
            {
                "schema_version": 2,
                "claim": claim,
                "replay_spec": spec.document,
                "budget": validated.protocol.document["budget"],
            }
        ),
        development_dataset_id=validated.replay_input.dataset_id,
        confirmation_dataset_id=validated.protocol.document["datasets"]["confirmation"],
    )
    replay_input = ReplayInput(
        validated.replay_input.dataset_id, validated.replay_input.normalized_bytes, spec
    )
    assumptions_request = validated.assumptions.document
    assumptions_request.pop("bindings")
    assumptions_request["kind"] = "assumption_request_v1"
    assumptions = build_assumption_spec(
        canonical(assumptions_request), protocol=protocol, replay_input=replay_input
    )
    plan = build_search_plan(
        canonical(
            {
                "kind": "search_plan_request_v1",
                "schema_version": 1,
                "search_seed": 7,
                "max_proposals": 1,
                "generator": {"kind": "grid", "values_ns": [0]},
            }
        ),
        protocol=protocol,
        assumptions=assumptions,
    )
    authority = build_search_finding_protocol(
        canonical(
            {
                "kind": "search_finding_request_v1",
                "schema_version": 1,
                "title": "Original frozen numeric criterion",
                "authority": FINDING_AUTHORITY_ID,
            }
        ),
        plan=plan,
    )
    scenario = build_scenario_spec(
        canonical(
            {
                "kind": "scenario_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "additional_delay": {"value": 0, "unit": "ns"},
            }
        ),
        assumptions=assumptions,
    )
    source = ReductionSource(
        "a" * 64,
        "b" * 64,
        authority.protocol_id,
        authority.document["predicate_id"],
        original.materialized.source.source_run_id,
        1,
        validate_scenario_spec(
            scenario, assumptions, protocol=protocol, replay_input=replay_input
        ),
    )
    recipe = build_reduction_recipe(
        canonical(
            {
                "kind": "reduction_request_v1",
                "schema_version": 1,
                "witness_ordinal": 1,
                **original.materialized.recipe.document["operators"],
            }
        ),
        source=source,
    )
    materialized = materialize_reduction(recipe, source=source)
    document.update(dataset_id=materialized.replay_input.dataset_id, spec_id=spec.spec_id)
    result = build_replay_result(document)
    attempt_document = original.reservation.document
    attempt_document["protocol_id"] = protocol.protocol_id
    raw_attempt = canonical(attempt_document)
    fixture = SimpleNamespace(
        authority=authority,
        materialized=materialized,
        result=result,
        reservation=AttemptReservation(digest(raw_attempt), raw_attempt),
    )
    fixture.receipt = build_reduction_run_receipt(receipt_document(fixture))
    return fixture


def _assessment(fixture):
    return ReductionPreservationAssessment(
        fixture.authority, fixture.materialized, fixture.receipt, fixture.result
    )


@pytest.mark.parametrize(
    ("comparator", "threshold", "truth", "outcome"),
    [
        ("gt", "0", False, "PRESERVED"),
        ("gt", "-3", True, "NOT_PRESERVED"),
        ("gt", "-2", False, "PRESERVED"),
        ("ge", "-2", True, "NOT_PRESERVED"),
        ("lt", "-2", False, "PRESERVED"),
        ("le", "-2", True, "NOT_PRESERVED"),
        ("lt", "-2.000000000000000001", False, "PRESERVED"),
        ("lt", "-1.999999999999999999", True, "NOT_PRESERVED"),
    ],
)
def test_original_numeric_criterion_has_exact_boundary_semantics(
    comparator, threshold, truth, outcome
):
    fixture = _case(comparator=comparator, threshold=threshold)
    before = fixture.authority.canonical_bytes
    with localcontext() as context:
        context.prec = 2
        assessed = _assessment(fixture)
    document = assessed.document
    assert document["kind"] == "reduction_preservation_assessment_v1"
    assert document["schema_version"] == 1
    assert document["outcome"] == outcome
    assert document["criterion_observation"] == {
        "eligible": True,
        "truth": truth,
        "value": "-2",
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "comparator": comparator,
        "threshold": threshold,
        "reason": None,
    }
    assert fixture.authority.canonical_bytes == before
    assert assessed.assessment_id == digest(assessed.canonical_bytes)


@pytest.mark.parametrize(
    ("pending", "variant", "reason"),
    [
        (True, None, "execution_incomplete"),
        (False, "no_fills", "no_fills"),
        (False, "ambiguous", "ambiguous_native_fee_model"),
    ],
)
def test_incomplete_or_ineligible_evidence_is_unknown_not_false(pending, variant, reason):
    fixture = _case(pending=pending, variant=variant)
    document = _assessment(fixture).document
    assert document["outcome"] == "NOT_EVALUABLE"
    assert document["criterion_observation"] == {
        "eligible": False,
        "truth": None,
        "value": None,
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "comparator": "gt",
        "threshold": "0",
        "reason": reason,
    }


def test_assessment_binds_both_phases_without_rewriting_old_flags_or_claim_scope():
    fixture = _case()
    old_intent = build_reduction_intent(fixture.materialized)
    old_audit = ReductionStateAudit(fixture.materialized, fixture.result)
    before = (
        old_intent.canonical_bytes,
        old_audit.canonical_bytes,
        fixture.receipt.canonical_bytes,
    )
    assessed = _assessment(fixture)
    document = assessed.document
    assert document["source"] == {
        "bundle_id": "a" * 64,
        "report_id": "b" * 64,
        "finding_protocol_id": fixture.authority.protocol_id,
        "predicate_id": fixture.authority.document["predicate_id"],
        "protocol_id": fixture.reservation.protocol_id,
        "claim_revision_id": fixture.materialized.source.validation.protocol.claim_revision_id,
        "witness_ordinal": 1,
        "witness_run_id": fixture.materialized.source.source_run_id,
    }
    assert document["candidate"] == {
        "run_id": fixture.receipt.run_id,
        "intent_id": old_intent.intent_id,
        "attempt_id": fixture.reservation.attempt_id,
        "preparation_id": old_intent.document["bindings"]["preparation_id"],
        "recipe_id": fixture.materialized.recipe.recipe_id,
        "prefix_context_id": fixture.materialized.document["prefix_context_id"],
        "replay_result_sha256": digest(fixture.result.canonical_bytes),
        "state_audit_sha256": old_audit.audit_id,
    }
    scope = document["scope"]
    assert scope["phase"] == "development"
    assert scope["authority"] == "original_false_witness_numeric_criterion_v1"
    assert all(value is False for key, value in scope.items() if key not in ("phase", "authority"))
    assert scope["source_claim_evaluated"] is False
    assert scope["original_finding_rewritten"] is False
    assert scope["original_predicate_domain_extended"] is False
    assert scope["baseline_truth_evaluated"] is False
    assert scope["global_ledger_authenticity_verified"] is False
    assert old_audit.document["flags"]["reduced_predicate_evaluated"] is False
    assert old_audit.document["flags"]["witness_preservation_verified"] is False
    assert before == (
        old_intent.canonical_bytes,
        old_audit.canonical_bytes,
        fixture.receipt.canonical_bytes,
    )
    document["criterion_observation"]["truth"] = True
    document["scope"]["source_claim_evaluated"] = True
    assert assessed.document["criterion_observation"]["truth"] is False
    assert assessed.document["scope"]["source_claim_evaluated"] is False
    with pytest.raises(FrozenInstanceError):
        assessed.canonical_bytes = b"{}"


@pytest.mark.parametrize(
    "attack", ["result_sha", "audit_sha", "status", "intent", "budget", "timeout", "owner", "claim"]
)
def test_rehashed_receipt_cannot_replace_result_owner_intent_or_budget(attack):
    fixture = _case()
    document = fixture.receipt.document
    if attack == "result_sha":
        document["bindings"]["replay_result_sha256"] = "f" * 64
    elif attack == "audit_sha":
        document["bindings"]["state_audit_sha256"] = "f" * 64
    elif attack == "status":
        document["execution_status"] = "incomplete"
    elif attack == "intent":
        document["intent"]["bindings"]["source_run_id"] = "f" * 64
    elif attack == "budget":
        document["attempt"]["attempt_index"] = 3
    elif attack == "timeout":
        document["attempt"]["max_wall_seconds"] = 59
    elif attack == "owner":
        for row in (document, document["intent"], document["attempt"]):
            row["protocol_id"] = "f" * 64
    else:
        document["claim_revision_id"] = "f" * 64
        document["intent"]["claim_revision_id"] = "f" * 64
    forged = build_reduction_run_receipt(document)
    with pytest.raises(EvidenceValidationError):
        ReductionPreservationAssessment(
            fixture.authority, fixture.materialized, forged, fixture.result
        )


@pytest.mark.parametrize("attack", ["cash", "input"])
def test_fresh_outer_hashes_cannot_replace_independent_raw_state_audit(attack):
    fixture = _case()
    raw_result = fixture.result.document
    if attack == "cash":
        raw_result["account_trace"][-1]["fields"]["cash_total"] = "9999"
    else:
        raw_result["input_trace"][1]["fields"]["bids"][0][1] += 1
    result = build_replay_result(raw_result)
    document = fixture.receipt.document
    document["bindings"]["replay_result_sha256"] = digest(result.canonical_bytes)
    document["bindings"]["state_audit_sha256"] = "f" * 64
    receipt = build_reduction_run_receipt(document)
    with pytest.raises(EvidenceValidationError):
        ReductionPreservationAssessment(fixture.authority, fixture.materialized, receipt, result)


def test_failed_native_result_is_validation_failure_not_a_preservation_verdict():
    fixture = _case()
    document = fixture.result.document
    document["execution_status"] = "failed"
    document["completeness"]["stop_reason"] = "engine_error"
    failed = build_replay_result(document)
    with pytest.raises(EvidenceValidationError, match="Failed replay"):
        ReductionPreservationAssessment(
            fixture.authority, fixture.materialized, fixture.receipt, failed
        )


def test_another_frozen_authority_cannot_supply_a_more_favorable_criterion():
    fixture = _case()
    other = _case(threshold="-3")
    with pytest.raises(EvidenceValidationError, match="finding or predicate"):
        ReductionPreservationAssessment(
            other.authority, fixture.materialized, fixture.receipt, fixture.result
        )


def test_rebound_source_ids_cannot_hide_another_frozen_protocol():
    fixture = _case()
    other = _case(threshold="-3")
    source = replace(
        fixture.materialized.source,
        finding_protocol_id=other.authority.protocol_id,
        predicate_id=other.authority.document["predicate_id"],
    )
    request = {
        "kind": "reduction_request_v1",
        "schema_version": 1,
        "witness_ordinal": source.witness_ordinal,
        **fixture.materialized.recipe.document["operators"],
    }
    materialized = materialize_reduction(
        build_reduction_recipe(canonical(request), source=source), source=source
    )
    result = fixture.result.document
    result["dataset_id"] = materialized.replay_input.dataset_id
    result = build_replay_result(result)
    with pytest.raises(EvidenceValidationError, match="protocol differs"):
        ReductionPreservationAssessment(other.authority, materialized, fixture.receipt, result)


def test_noneligible_source_ordinal_cannot_gain_original_predicate_provenance():
    fixture = _case()
    source = replace(fixture.materialized.source, witness_ordinal=2)
    request = {
        "kind": "reduction_request_v1",
        "schema_version": 1,
        "witness_ordinal": 2,
        **fixture.materialized.recipe.document["operators"],
    }
    materialized = materialize_reduction(
        build_reduction_recipe(canonical(request), source=source), source=source
    )
    result = fixture.result.document
    result["dataset_id"] = materialized.replay_input.dataset_id
    result = build_replay_result(result)
    with pytest.raises(EvidenceValidationError, match="eligible witness"):
        ReductionPreservationAssessment(
            fixture.authority, materialized, fixture.receipt, result
        )


@pytest.mark.parametrize("field", ["authority", "materialized", "receipt", "result"])
def test_duck_typed_records_cannot_replace_actual_validated_domain_values(field):
    fixture = _case()
    arguments = {
        "authority": fixture.authority,
        "materialized": fixture.materialized,
        "receipt": fixture.receipt,
        "result": fixture.result,
    }
    record = arguments[field]
    arguments[field] = SimpleNamespace(canonical_bytes=record.canonical_bytes)
    with pytest.raises(EvidenceValidationError):
        ReductionPreservationAssessment(**arguments)
