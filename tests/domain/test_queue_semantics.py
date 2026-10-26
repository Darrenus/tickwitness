"""A conserved tape and an audited probe do not certify a joint market history."""

import json
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.queue_semantics import (
    QueueSemanticsValidationError,
    load_queue_pair_qualification,
    qualify_queue_pair,
)
from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.queue_contracts import QueueReplayInput, build_queue_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.queue_family import build_queue_family_protocol

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
FRONT, BACK = "cancel_front_first_v1", "cancel_back_first_v1"


def pair_inputs(*, variant="standard", threshold="0"):
    request = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    request["claim"]["threshold"] = threshold
    spec = build_replay_spec(canonical(request["replay_spec"]))
    protocol = build_executable_protocol(canonical(request), development_dataset_id="a" * 64,
                                         confirmation_dataset_id="b" * 64)
    events = [json.loads(line) for line in (EXAMPLES / "queue-observations.jsonl").read_bytes().splitlines()]
    constraint = json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())
    if variant == "no_fills":
        events[3]["quantity_lots"] = 1
        events[4]["bids"][0][1] = events[5]["bids"][0][1] = 4
    elif variant == "no_trades":
        events = [event for event in events if event["type"] != "trade"]
        for event in events[-2:]:
            event["bids"][0][1] = 5
        constraint["updates"][2]["trade_capture_seqs"] = []
    elif variant == "gross_churn":
        constraint["updates"][1].update(additions_lots=3, cancellations_lots=6)
    data = normalize_events(b"\n".join(canonical(event) for event in events) + b"\n").normalized_bytes
    family = build_queue_family_protocol(
        (EXAMPLES / "queue-family-request.json").read_bytes(), source_protocol=protocol,
        replay_input=ReplayInput("a" * 64, data, spec), queue_request=canonical(constraint),
    )
    return tuple(QueueReplayInput(family, data, policy) for policy in (FRONT, BACK))


def report(queue_result_factory, **changes):
    front, back = pair_inputs(**changes)
    return qualify_queue_pair(front, queue_result_factory(front), back, queue_result_factory(back))


def test_native_fill_difference_is_a_joint_projection_residual_not_a_truth_finding(queue_result_factory):
    qualification = report(queue_result_factory)
    document = qualification.document
    assert qualification == load_queue_pair_qualification(qualification.canonical_bytes)
    assert qualification.qualification_id == digest(qualification.canonical_bytes)
    assert document["kind"] == "queue_pair_semantics_v1"
    assert document["scope"] == {
        "phase": "development", "scenario_kind": "MODEL_SENSITIVITY",
        "source_claim_evaluated": False, "claim_verdict_issued": False, "finding_issued": False,
    }
    assert document["observation_compatibility"]["status"] == "not_established"
    assert document["pair_relation"] == "not_evaluable"
    assert document["predicate"]["reason"] == "queue_family_claim_lineage_only"
    assert document["predicate"]["values"] == {FRONT: None, BACK: None}
    assert document["predicate"]["satisfied"] == {FRONT: None, BACK: None}
    assert document["predicate"]["truth_divergence"] is None and document["findings"] == []
    front, back = document["models"]
    assert [front["policy_id"], back["policy_id"]] == [FRONT, BACK]
    assert [front["filled_quantity_lots"], back["filled_quantity_lots"]] == [1, 0]
    for model in (front, back):
        assert model["external_only_projection"]["status"] == "verified"
        assert model["single_counted_insertion"]["projection_id"] == "literal_order_insertion_single_counted_trade_v1"
    single = front["single_counted_insertion"]
    assert single["status"] == "contradiction"
    assert single["trades"][0] == {
        "source_ref": {"line": 4, "capture_seq": 4, "event_type": "trade"},
        "receive_time_ns": 1700000002000000000,
        "public_trade_lots": 3, "external_consumed_lots": 3, "own_filled_lots": 1,
        "total_allocated_lots": 4, "over_allocation_lots": 1,
    }
    assert single["checkpoints"][-1]["recorded_external_lots"] == 2
    assert single["checkpoints"][-1]["candidate_projected_external_lots"] == 3
    assert single["checkpoints"][-1]["cumulative_own_filled_lots"] == 1
    assert single["checkpoints"][-1]["mismatch_lots"] == 1
    assert back["single_counted_insertion"]["status"] == "necessary_checks_passed"


def test_external_absolute_volume_is_checked_only_at_actual_l2_checkpoints(queue_result_factory):
    front = report(queue_result_factory).document["models"][0]
    trace = front["external_only_projection"]["trace"]
    assert [row["recorded_external_lots"] for row in trace] == [5, 8, 5, None, 2, 2]
    assert trace[3]["after"]["external_lots"] == 2
    # The last visible L2 value during the trade is still 5; it is not a new 5-lot checkpoint.
    assert trace[3]["kind"] == "trade" and trace[4]["kind"] == "checkpoint"


@pytest.mark.parametrize("variant", ["no_fills", "no_trades"])
def test_no_residual_is_only_a_necessary_check_never_a_compatibility_certificate(queue_result_factory, variant):
    document = report(queue_result_factory, variant=variant).document
    assert all(model["filled_quantity_lots"] == 0 for model in document["models"])
    assert all(model["single_counted_insertion"]["status"] == "necessary_checks_passed"
               for model in document["models"])
    assert document["observation_compatibility"]["status"] == "not_established"
    assert document["predicate"]["status"] == "not_evaluable"
    assert document["findings"] == []


def test_full_order_fill_and_declared_gross_churn_remain_accounting_diagnostics(queue_result_factory):
    document = report(queue_result_factory, variant="gross_churn").document
    front = document["models"][0]
    assert front["filled_quantity_lots"] == 2
    assert front["single_counted_insertion"]["trades"][0]["total_allocated_lots"] == 5
    assert front["single_counted_insertion"]["checkpoints"][-1]["candidate_projected_external_lots"] == 4
    assert document["predicate"]["values"][FRONT] is None


def test_pair_order_is_normalized_and_documents_are_detached(queue_result_factory):
    front, back = pair_inputs()
    fresult, bresult = queue_result_factory(front), queue_result_factory(back)
    forward = qualify_queue_pair(front, fresult, back, bresult)
    assert forward == qualify_queue_pair(back, bresult, front, fresult)
    altered = forward.document
    altered["models"][0]["single_counted_insertion"]["trades"][0]["own_filled_lots"] = 999
    assert forward.document["models"][0]["single_counted_insertion"]["trades"][0]["own_filled_lots"] == 1


@pytest.mark.parametrize("problem", ["same_policy", "cross_family", "swapped_results", "environment", "fees", "input_clock"])
def test_incompatible_or_invalid_execution_evidence_is_rejected_before_diagnostics(queue_result_factory, problem):
    front, back = pair_inputs()
    fresult, bresult = queue_result_factory(front), queue_result_factory(back)
    if problem == "same_policy":
        back, bresult = front, fresult
    elif problem == "cross_family":
        back = pair_inputs(threshold="-1")[1]
        bresult = queue_result_factory(back)
    elif problem == "swapped_results":
        fresult, bresult = bresult, fresult
    else:
        document = fresult.document
        if problem == "environment":
            document["environment"]["platform"] = "another-platform"
        elif problem == "fees":
            document["fill_trace"][0]["fields"]["commission"] = "99"
        else:
            document["input_trace"][0]["fields"]["event_time_ns"] += 1
        fresult = build_queue_replay_result(document)
    with pytest.raises(QueueSemanticsValidationError):
        qualify_queue_pair(front, fresult, back, bresult)


@pytest.mark.parametrize("mutation", ["scope", "compatibility", "truth", "value", "finding", "proof", "version",
                                      "residual", "checkpoint", "projection_status", "external_flow", "recorded_trade",
                                      "policy_order", "fee", "claim_binding", "noncanonical"])
def test_loaded_report_cannot_be_promoted_or_rewrite_arithmetic(queue_result_factory, mutation):
    document = report(queue_result_factory).document
    front = document["models"][0]
    if mutation == "scope":
        document["scope"]["source_claim_evaluated"] = True
    elif mutation == "compatibility":
        document["observation_compatibility"]["status"] = "verified"
    elif mutation == "truth":
        document["predicate"]["satisfied"][FRONT] = True
    elif mutation == "value":
        document["predicate"]["values"][BACK] = "0"
    elif mutation == "finding":
        document["findings"] = [{"type": "NOT_IDENTIFIABLE_WITHIN_MODEL"}]
    elif mutation == "proof":
        document["proof"] = True
    elif mutation == "version":
        document["schema_version"] = True
    elif mutation == "residual":
        front["single_counted_insertion"]["trades"][0]["over_allocation_lots"] = 0
    elif mutation == "checkpoint":
        front["single_counted_insertion"]["checkpoints"][-1]["candidate_projected_external_lots"] += 1
    elif mutation == "projection_status":
        front["single_counted_insertion"]["status"] = "verified"
    elif mutation == "external_flow":
        front["external_only_projection"]["trace"][2]["flow"]["cancel_behind_lots"] += 1
    elif mutation == "recorded_trade":
        front["external_only_projection"]["trace"][3]["recorded_external_lots"] = 5
    elif mutation == "policy_order":
        document["models"].reverse()
    elif mutation == "fee":
        front["actual_commission"] = "0.001"
    elif mutation == "claim_binding":
        document["predicate"]["source_claim_revision_id"] = "0" * 64
    raw = canonical(document)
    if mutation == "noncanonical":
        raw = json.dumps(document, indent=2).encode()
    with pytest.raises(QueueSemanticsValidationError):
        load_queue_pair_qualification(raw)
