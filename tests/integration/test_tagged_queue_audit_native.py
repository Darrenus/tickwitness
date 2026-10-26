"""Independent audits accept conserved native worlds and reject altered evidence."""

from decimal import Decimal

import pytest
from test_tagged_queue_native import context, native

from tickwitness.domain.evidence.evaluation import EvaluationValidationError
from tickwitness.domain.evidence.tagged_queue_evaluation import (
    evaluate_tagged_queue_replay,
    load_tagged_queue_evaluation,
)
from tickwitness.domain.replay._validation import ReplayValidationError, canonical
from tickwitness.domain.replay.tagged_queue_contracts import (
    TaggedQueueReplayInput,
    build_tagged_queue_replay_result,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS
from tickwitness.infrastructure.tagged_queue_replay import NautilusTaggedQueueReplayAdapter


@native
@pytest.mark.parametrize("case,comparator,pnl,truth", [
    ("standard", "gt", ["-2", "0"], [False, False]),
    ("high_mark", "gt", ["2", "0"], [True, False]),
    ("high_mark", "ge", ["2", "0"], [True, True]),
    ("same_time", "gt", ["-2", "0"], [False, False]),
    ("no_cancel", "ge", ["0", "0"], [True, True]),
    ("variable", "gt", ["-0.03", "-0.01"], [False, False]),
])
def test_actual_paired_tagged_claim_has_frozen_truth_semantics(case, comparator, pnl, truth):
    front = context(case, comparator=comparator)
    inputs = [front, TaggedQueueReplayInput(front.protocol, front.normalized_bytes, TAGGED_POLICY_IDS[1])]
    evaluations = [evaluate_tagged_queue_replay(request, NautilusTaggedQueueReplayAdapter().run(request)) for request in inputs]
    assert [evaluation.document["valuation"]["net_marked_pnl"] for evaluation in evaluations] == pnl
    assert [evaluation.document["claim_evaluation"]["truth"] for evaluation in evaluations] == truth
    for request, evaluation in zip(inputs, evaluations, strict=True):
        doc = evaluation.document
        assert doc["status"] == "verified"
        assert doc["scope"]["source_claim_evaluated"] is False
        assert doc["scope"]["historical_owner_verified"] is False
        assert doc["scope"]["literal_order_insertion"] is False
        assert doc["findings"] == []
        assert doc["valuation"]["eligible"] is True
        assert doc["claim_evaluation"]["claim_revision_id"] == request.protocol.claim_revision_id
        assert load_tagged_queue_evaluation(evaluation.canonical_bytes) == evaluation
        assert Decimal(doc["final_cash_total"]) == Decimal(request.prepared.spec.document["account"]["starting_cash"]) - Decimal(doc["actual_commission"])


@pytest.fixture(scope="module")
def actual_pair():
    front = context()
    back = TaggedQueueReplayInput(front.protocol, front.normalized_bytes, TAGGED_POLICY_IDS[1])
    return [(request, NautilusTaggedQueueReplayAdapter().run(request)) for request in (front, back)]


@native
@pytest.mark.parametrize("mutation", [
    "source_clock", "source_ref", "acceptance_role", "old_semantic", "double_trade",
    "native_fill", "native_grant", "missing_fill", "missing_fill_receipt", "missing_cancel_receipt",
    "horizon_account", "horizon_mark", "horizon_total", "cleanup_depth", "cleanup_unfilled",
    "fee", "cash", "input_phase", "order_phase", "fill_phase", "horizon_phase", "early_cleanup_hook",
])
def test_changed_native_evidence_is_never_verified(actual_pair, mutation):
    index = 1 if mutation in ("missing_cancel_receipt", "cleanup_unfilled") else 0
    request, result = actual_pair[index]
    doc = result.document
    if mutation == "source_clock":
        doc["input_trace"][0]["fields"]["native_ts_event_ns"] += 1
    elif mutation == "source_ref":
        doc["fill_trace"][0]["source_ref"] = doc["input_trace"][2]["source_ref"]
    elif mutation == "acceptance_role":
        next(row for row in doc["order_trace"] if row["kind"] == "OrderAccepted")["fields"]["actual_acceptance"]["acceptance_role"] = "historical_arrival"
    elif mutation == "old_semantic":
        doc["engine"]["semantic_id"] = "nautilus_external_fifo_shadow_queue_execution_v1"
    elif mutation == "double_trade":
        doc["queue_trace"][3]["flow"]["external_trade_behind_lots"] += 1
    elif mutation == "native_fill":
        doc["fill_trace"][0]["fields"]["quantity_lots"] = 1
        doc["fill_trace"][0]["fields"]["quantity"] = "1"
    elif mutation == "native_grant":
        doc["queue_trace"][3]["granted_lots"] += 1
    elif mutation == "missing_fill":
        doc["fill_trace"] = []
    elif mutation in ("missing_fill_receipt", "missing_cancel_receipt"):
        kind = "OrderFilled" if mutation == "missing_fill_receipt" else "OrderCanceled"
        doc["order_trace"] = [row for row in doc["order_trace"] if row["kind"] != kind]
        for ordinal, row in enumerate(doc["order_trace"]):
            row["ordinal"] = ordinal
    elif mutation == "horizon_account":
        doc["horizon_snapshot"]["account"]["net_position_lots"] += 1
    elif mutation == "horizon_mark":
        doc["horizon_snapshot"]["mark"]["price_ticks"] += 1
    elif mutation == "horizon_total":
        doc["horizon_snapshot"]["native_target_lots"] += 1
    elif mutation == "cleanup_depth":
        doc["cleanup"]["projected_total_after_cleanup"] += 1
    elif mutation == "cleanup_unfilled":
        doc["cleanup"]["native_unfilled_lots"] = 0
    elif mutation == "fee":
        doc["fill_trace"][0]["fields"]["commission"] = "3"
    elif mutation == "cash":
        doc["account_trace"][-1]["fields"]["cash_total"] = "9997"
        doc["account_trace"][-1]["fields"]["cash_free"] = "9997"
        doc["account_trace"][-1]["fields"]["cash_locked"] = "0"
    elif mutation == "input_phase":
        doc["input_trace"][0]["phase"] = "claim_horizon"
    elif mutation == "order_phase":
        next(row for row in doc["order_trace"] if row["kind"] == "OrderAccepted")["phase"] = "post_horizon_cleanup"
    elif mutation == "fill_phase":
        doc["fill_trace"][0]["phase"] = "post_horizon_cleanup"
    elif mutation == "horizon_phase":
        next(row for row in doc["account_trace"] if row["kind"] == "horizon_account_snapshot")["phase"] = "post_horizon_cleanup"
    else:
        doc["hook_trace"].insert(0, {"source_ref": doc["input_trace"][0]["source_ref"],
            "origin": "native_public_fill_simulation_hook", "offered_lots": 0,
            "cumulative_granted_lots": 0, "phase": "post_horizon_cleanup"})
    with pytest.raises((ReplayValidationError, EvaluationValidationError)):
        evaluate_tagged_queue_replay(request, build_tagged_queue_replay_result(doc))


@native
@pytest.mark.parametrize("mutation", ["numeric_truth", "wrong_truth", "eligible_int", "extra_valuation",
    "missing_mark", "foreign_claim", "unsupported_comparator", "ineligible_truth", "out_of_range_ambiguity"])
def test_persisted_evaluation_loader_rejects_forged_nested_claims(actual_pair, mutation):
    request, result = actual_pair[0]
    doc = evaluate_tagged_queue_replay(request, result).document
    if mutation == "numeric_truth":
        doc["claim_evaluation"]["truth"] = 0
    elif mutation == "wrong_truth":
        doc["claim_evaluation"]["truth"] = True
    elif mutation == "eligible_int":
        doc["valuation"]["eligible"] = 1
    elif mutation == "extra_valuation":
        doc["valuation"]["extra"] = "ignored"
    elif mutation == "missing_mark":
        del doc["valuation"]["mark"]["source_ref"]
    elif mutation == "foreign_claim":
        doc["claim_evaluation"]["claim_revision_id"] = "f" * 64
    elif mutation == "unsupported_comparator":
        doc["claim_evaluation"]["comparator"] = "eq"
    elif mutation == "ineligible_truth":
        doc["ambiguous_fee_fill_ordinals"] = [0]
        doc["valuation"]["eligible"] = False
        doc["valuation"]["reason"] = "native_fee_rounding_ambiguous"
        doc["valuation"]["net_marked_pnl"] = None
    else:
        doc["ambiguous_fee_fill_ordinals"] = [2]
    with pytest.raises((ReplayValidationError, EvaluationValidationError)):
        load_tagged_queue_evaluation(canonical(doc))
