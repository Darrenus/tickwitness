"""Prefix records audit actual trace content without exporting resumable state.

Financial fixtures reuse the original saved native result. The pending-cancel
case is a declared offline consistency fixture, never claimed as a native run.
Real prefix execution is qualified separately by the installed native smoke.
"""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_scenario_records import case

from tickwitness.domain.assumptions import (
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.evidence.reduction_records import (
    INTENT_FLAGS,
    REDUCTION_SCOPE,
    STATE_AUDIT_FLAGS,
    STATE_BOUNDARY,
    ReductionStateAudit,
    build_reduction_failure,
    build_reduction_intent,
    build_reduction_run_receipt,
    load_reduction_failure,
    load_reduction_intent,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
)
from tickwitness.domain.reduction.contracts import (
    ReductionSource,
    build_reduction_manifest,
    build_reduction_recipe,
    materialize_reduction,
)
from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol


def prepared_case(*, pending=False):
    fixture = case()
    validation = fixture.view.validated
    document = fixture.result.document
    protocol = fixture.protocol
    if pending:
        spec = validation.replay_input.spec.document
        spec["strategy"]["cancel_after_first_fill"] = True
        spec["execution"]["cancel_latency_ns"] = 5_000_000_000
        spec = build_replay_spec(canonical(spec))
        protocol = build_executable_protocol(
            canonical(
                {
                    "schema_version": 2,
                    "claim": protocol.document["claim"],
                    "replay_spec": spec.document,
                    "budget": protocol.document["budget"],
                }
            ),
            development_dataset_id=validation.replay_input.dataset_id,
            confirmation_dataset_id="b" * 64,
        )
        replay_input = ReplayInput(
            validation.replay_input.dataset_id, validation.replay_input.normalized_bytes, spec
        )
        assumption_request = validation.assumptions.document
        assumption_request.pop("bindings")
        assumption_request["kind"] = "assumption_request_v1"
        assumptions = build_assumption_spec(
            canonical(assumption_request), protocol=protocol, replay_input=replay_input
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
        validation = validate_scenario_spec(
            scenario, assumptions, protocol=protocol, replay_input=replay_input
        )
        document["spec_id"] = spec.spec_id
        first_fill = document["fill_trace"][0]
        cancel = deepcopy(document["decision_trace"][0])
        cancel.update(
            ordinal=1,
            source_ref=first_fill["source_ref"],
            native_time_ns=first_fill["native_time_ns"],
        )
        cancel["fields"].update(
            action="cancel", cause="first_partial_fill",
            command_id="command-1", decision_ref="decision-1",
        )
        document["decision_trace"].append(cancel)
        first_order_fill = next(
            row for row in document["order_trace"] if row["kind"] == "OrderFilled"
        )
        pending_row = deepcopy(first_order_fill)
        pending_row["kind"] = "OrderPendingCancel"
        pending_row["fields"].update(status="PENDING_CANCEL", pending_command_ids=["command-1"])
        position = document["order_trace"].index(first_order_fill)
        document["order_trace"].insert(position, pending_row)
        for ordinal, row in enumerate(document["order_trace"]):
            row["ordinal"] = ordinal
            if ordinal >= position:
                row["fields"]["pending_command_ids"] = ["command-1"]
        first_order_fill["fields"]["status"] = "PENDING_CANCEL"
        document["execution_status"] = "incomplete"
        document["completeness"].update(
            stop_reason="pending_commands_at_data_end",
            pending_commands=[
                {
                    "command_id": "command-1",
                    "order_id": first_fill["fields"]["order_id"],
                    "command_type": "cancel",
                    "decision_ref": "decision-1",
                    "source_ref": first_fill["source_ref"],
                }
            ],
        )
    source = ReductionSource(
        "a" * 64, "b" * 64, "c" * 64, "d" * 64,
        digest(fixture.result.canonical_bytes), 3, validation,
    )
    recipe = build_reduction_recipe(
        canonical(
            {
                "kind": "reduction_request_v1", "schema_version": 1, "witness_ordinal": 3,
                "focus_from_capture_seq": 4, "through_capture_seq": 7, "additional_delay_ns": 0,
            }
        ),
        source=source,
    )
    materialized = materialize_reduction(recipe, source=source)
    document["dataset_id"] = materialized.replay_input.dataset_id
    result = build_replay_result(document)
    reservation = fixture.reservation.document
    reservation["protocol_id"] = protocol.protocol_id
    raw_reservation = canonical(reservation)
    return SimpleNamespace(
        materialized=materialized,
        result=result,
        reservation=AttemptReservation(digest(raw_reservation), raw_reservation),
    )


def receipt_document(fixture):
    intent = build_reduction_intent(fixture.materialized)
    audit = ReductionStateAudit(fixture.materialized, fixture.result)
    return {
        "kind": "reduction_run_receipt_v1", "schema_version": 1,
        "attempt": fixture.reservation.document,
        "protocol_id": intent.document["protocol_id"],
        "claim_revision_id": intent.document["claim_revision_id"],
        "scope": dict(REDUCTION_SCOPE), "intent": intent.document,
        "execution_status": fixture.result.document["execution_status"],
        "bindings": {
            "replay_result_sha256": digest(fixture.result.canonical_bytes),
            "state_audit_sha256": audit.audit_id,
        },
    }


@pytest.mark.parametrize("pending", [False, True])
def test_full_prefix_account_order_and_pending_projections_are_independently_audited(pending):
    fixture = prepared_case(pending=pending)
    materialized, result = fixture.materialized, fixture.result
    intent = build_reduction_intent(materialized)
    manifest = build_reduction_manifest(
        {
            "recipe": materialized.recipe.canonical_bytes,
            "materialization": materialized.canonical_bytes,
            "normalized": materialized.replay_input.normalized_bytes,
        }
    )
    assert intent.document["bindings"]["preparation_id"] == digest(manifest)
    assert intent.document["bindings"]["preparation_manifest_sha256"] == digest(manifest)
    assert intent.document["protocol_id"] == fixture.reservation.protocol_id
    assert intent.document["flags"] == dict(INTENT_FLAGS)
    assert not any(intent.document["flags"].values())
    audit = ReductionStateAudit(materialized, result)
    document = audit.document
    assert document["state_boundary"] == STATE_BOUNDARY
    assert document["initial_account"] == result.document["account_trace"][0]
    assert document["terminal_state"]["account"] == result.document["account_trace"][-1]
    assert document["terminal_state"]["pending_commands"] == result.document["completeness"]["pending_commands"]
    assert document["coverage"]["processed_records"] == document["coverage"]["retained_event_count"] == 7
    assert document["coverage"]["warmup_event_count"] == 3
    assert document["flags"] == dict(STATE_AUDIT_FLAGS)
    assert document["replay_evaluation"]["audit_status"] == "verified"
    if pending:
        assert document["execution_status"] == "incomplete"
        assert document["terminal_state"]["open_orders"] == []
        assert document["terminal_state"]["account"]["fields"]["orders"][0]["status"] == "FILLED"
        assert len(document["terminal_state"]["pending_commands"]) == 1
        assert document["replay_evaluation"]["valuation_status"] == "not_eligible"
        assert document["replay_evaluation"]["valuation"] is None
    altered = audit.document
    altered["flags"]["checkpoint_used"] = True
    assert audit.document["flags"]["checkpoint_used"] is False
    assert load_reduction_intent(intent.canonical_bytes) == intent
    receipt = build_reduction_run_receipt(receipt_document(fixture))
    assert receipt.intent_id == intent.intent_id
    assert load_reduction_run_receipt(receipt.canonical_bytes) == receipt


@pytest.mark.parametrize("attack", ["position", "cash", "leaves", "warmup", "pending", "binding"])
def test_rehashed_state_or_trace_tampering_cannot_pass_audit(attack):
    fixture = prepared_case()
    document = fixture.result.document
    final = document["account_trace"][-1]["fields"]
    if attack == "position":
        final["net_position_lots"] += 1
    elif attack == "cash":
        final["cash_total"] = "10000"
    elif attack == "leaves":
        final["orders"][0]["remaining_quantity_lots"] = 1
    elif attack == "warmup":
        document["input_trace"][1]["fields"]["receive_time_ns"] += 1
    elif attack == "pending":
        document["execution_status"] = "incomplete"
        document["completeness"].update(
            stop_reason="pending_commands_at_data_end",
            pending_commands=[
                {
                    "command_id": "command-0",
                    "order_id": final["orders"][0]["order_id"],
                    "command_type": "submit", "decision_ref": "decision-0",
                    "source_ref": document["decision_trace"][0]["source_ref"],
                }
            ],
        )
    else:
        document["dataset_id"] = "0" * 64
    with pytest.raises(EvidenceValidationError):
        ReductionStateAudit(fixture.materialized, build_replay_result(document))


def test_failed_or_partially_processed_result_cannot_claim_full_origin_replay():
    fixture = prepared_case()
    failed = fixture.result.document
    failed["execution_status"] = "failed"
    failed["completeness"]["stop_reason"] = "engine_error"
    with pytest.raises(EvidenceValidationError, match="Failed replay"):
        ReductionStateAudit(fixture.materialized, build_replay_result(failed))
    partial = fixture.result.document
    partial["execution_status"] = "incomplete"
    partial["completeness"].update(
        processed_records=6,
        stop_reason="input_exhausted_with_open_orders",
        open_orders=[{"order_id": "partial-invalid", "status": "ACCEPTED"}],
    )
    for channel in ("input_trace", "decision_trace", "order_trace", "fill_trace", "account_trace"):
        rows = [row for row in partial[channel] if row["source_ref"] is None or row["source_ref"]["line"] <= 6]
        for ordinal, row in enumerate(rows):
            row["ordinal"] = ordinal
        partial[channel] = rows
    with pytest.raises(EvidenceValidationError, match="every retained prefix"):
        ReductionStateAudit(fixture.materialized, build_replay_result(partial))


def test_fake_completion_cannot_erase_a_real_outstanding_cancel():
    fixture = prepared_case(pending=True)
    document = fixture.result.document
    document["execution_status"] = "completed"
    document["completeness"].update(pending_commands=[], stop_reason="input_exhausted")
    with pytest.raises(EvidenceValidationError, match="pending-command"):
        ReductionStateAudit(fixture.materialized, build_replay_result(document))


@pytest.mark.parametrize("target", ["intent", "receipt"])
def test_record_markers_flags_and_original_owner_are_strict(target):
    fixture = prepared_case()
    intent = build_reduction_intent(fixture.materialized)
    document = intent.document if target == "intent" else receipt_document(fixture)
    loader = load_reduction_intent if target == "intent" else load_reduction_run_receipt
    changed = deepcopy(document)
    changed["schema_version"] = True
    with pytest.raises(EvidenceValidationError):
        loader(canonical(changed))
    changed = deepcopy(document)
    if target == "intent":
        changed["flags"]["from_origin_prefix_replayed"] = True
    else:
        changed["attempt"]["protocol_id"] = "0" * 64
    with pytest.raises(EvidenceValidationError):
        loader(canonical(changed))
    with pytest.raises(EvidenceValidationError):
        replace(intent, intent_id="0" * 64)
    with pytest.raises(TypeError):
        STATE_AUDIT_FLAGS["checkpoint_used"] = True


def test_failure_preserves_actual_reservation_intent_and_multiline_error():
    fixture = prepared_case()
    intent = build_reduction_intent(fixture.materialized)
    raw = build_reduction_failure(fixture.reservation, intent, "engine_timeout", "timed out\nstate unconfirmed")
    failure = load_reduction_failure(raw)
    assert failure["attempt"] == fixture.reservation.document
    assert failure["intent"] == intent.document
    assert failure["error"]["message"] == "timed out\nstate unconfirmed"
    assert "state_audit" not in failure
    changed = deepcopy(failure)
    changed["error"]["code"] = "../retry"
    with pytest.raises(EvidenceValidationError):
        load_reduction_failure(canonical(changed))


def test_intent_rebuild_rejects_a_forged_materialization():
    fixture = prepared_case()
    materialized = fixture.materialized
    forged = materialized.document
    forged["flags"]["checkpoint_used"] = True
    object.__setattr__(materialized, "canonical_bytes", canonical(forged))
    with pytest.raises(EvidenceValidationError, match="does not reproduce"):
        build_reduction_intent(materialized)
