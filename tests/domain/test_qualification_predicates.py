"""Candidate truth semantics never turn unknowns or shadow differences into findings."""

import json
from dataclasses import fields
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.evaluation import EvaluationValidationError
from tickwitness.domain.evidence.qualification_predicates import (
    QualificationPredicate,
    QualificationPredicateObservation,
    QualificationPredicateValidationError,
    build_qualification_predicate,
    compare_qualification_predicates,
    load_qualification_predicate,
    qualify_predicate,
)
from tickwitness.domain.replay._validation import ReplayValidationError, canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.queue_contracts import QueueReplayInput, build_queue_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.queue_family import build_queue_family_protocol

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
FRONT, BACK = "cancel_front_first_v1", "cancel_back_first_v1"


def request(**changes):
    return {
        "kind": "queue_qualification_predicate_v1", "schema_version": 1,
        "purpose": "semantic_qualification_only", "metric": "net_marked_pnl_v1", "unit": "USD",
        "comparator": "gt", "threshold": "0",
        "evaluation_policy": "qualification_flat_zero_last_visible_bid_v1", **changes,
    }


def candidate(**changes):
    return build_qualification_predicate(canonical(request(**changes)))


def replay(policy=FRONT, *, mark=100, spec_changes=None):
    source = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    for group, changes in (spec_changes or {}).items():
        source["replay_spec"][group].update(changes)
    observations = [json.loads(line) for line in (EXAMPLES / "queue-observations.jsonl").read_bytes().splitlines()]
    if mark != 100:
        observations[-1]["bids"].append([mark, 7])
    raw = b"\n".join(canonical(row) for row in observations) + b"\n"
    data = normalize_events(raw).normalized_bytes
    spec = build_replay_spec(canonical(source["replay_spec"]))
    protocol = build_executable_protocol(canonical(source), development_dataset_id="a" * 64,
                                         confirmation_dataset_id="b" * 64)
    family = build_queue_family_protocol(
        (EXAMPLES / "queue-family-request.json").read_bytes(),
        source_protocol=protocol, replay_input=ReplayInput("a" * 64, data, spec),
        queue_request=(EXAMPLES / "queue-constraint-request.json").read_bytes(),
    )
    return QueueReplayInput(family, data, policy)


def observation(factory, policy=FRONT, *, mark=100, predicate=None, spec_changes=None):
    replay_input = replay(policy, mark=mark, spec_changes=spec_changes)
    return qualify_predicate(replay_input, factory(replay_input), predicate or candidate())


def test_predicate_is_frozen_canonical_detached_and_separate_from_a_production_claim() -> None:
    raw = json.dumps(request(), indent=2).encode()
    value = build_qualification_predicate(raw)
    assert value == load_qualification_predicate(value.canonical_bytes)
    assert value.predicate_id == digest(value.canonical_bytes)
    assert value.canonical_bytes == canonical(request())
    detached = value.document
    detached["threshold"] = "1"
    assert value.document["threshold"] == "0"
    assert candidate(threshold="1").predicate_id != value.predicate_id
    assert candidate(comparator="ge").predicate_id != value.predicate_id
    with pytest.raises(QualificationPredicateValidationError):
        QualificationPredicate(raw)


@pytest.mark.parametrize("changes", [
    {"kind": "claim_spec_v1"}, {"schema_version": True}, {"purpose": "production"},
    {"metric": "cash_total"}, {"unit": "EUR"}, {"comparator": "eq"},
    {"evaluation_policy": "last_observed_bid_mark_v1"}, {"eligible": True},
    {"threshold": "0.0"}, {"threshold": "+0"}, {"threshold": "-0"},
    {"threshold": "1e2"}, {"threshold": "NaN"}, {"threshold": True},
    {"threshold": "0.0000000000000000001"}, {"threshold": "1" * 29},
])
def test_unknown_or_noncanonical_candidate_policies_and_thresholds_are_rejected(changes) -> None:
    with pytest.raises(QualificationPredicateValidationError):
        candidate(**changes)


@pytest.mark.parametrize("raw", [b'{"kind":"x","kind":"y"}', b"{}", b"[]", b"x" * 16385])
def test_candidate_json_is_exact_bounded_and_duplicate_safe(raw) -> None:
    with pytest.raises(QualificationPredicateValidationError):
        build_qualification_predicate(raw)


@pytest.mark.parametrize("comparator,expected", [("gt", False), ("ge", True), ("lt", False), ("le", True)])
def test_all_four_comparators_treat_exact_equality_without_float_rounding(
    queue_result_factory, comparator, expected
) -> None:
    observed = observation(queue_result_factory, BACK, predicate=candidate(comparator=comparator))
    assert observed.document["eligible"] is True
    assert observed.document["value"] == "0"
    assert observed.document["satisfied"] is expected


@pytest.mark.parametrize("mark,comparator,values,truths,status", [
    (100, "gt", ["-1", "0"], [False, False], "DIAGNOSTIC_PREDICATE_AGREEMENT"),
    (102, "gt", ["1", "0"], [True, False], "DIAGNOSTIC_PREDICATE_DISAGREEMENT"),
    (102, "ge", ["1", "0"], [True, True], "DIAGNOSTIC_PREDICATE_AGREEMENT"),
])
def test_quantity_or_value_difference_does_not_imply_predicate_disagreement(
    queue_result_factory, mark, comparator, values, truths, status
) -> None:
    predicate = candidate(comparator=comparator)
    pair = [observation(queue_result_factory, policy, mark=mark, predicate=predicate) for policy in (FRONT, BACK)]
    documents = [item.document for item in pair]
    assert [item["value"] for item in documents] == values
    assert [item["satisfied"] for item in documents] == truths
    assert [item["valuation"]["filled_quantity_lots"] for item in documents] == [1, 0]
    assert [item["valuation"]["actual_commission"] for item in documents] == ["1", "0"]
    assert documents[0]["valuation"]["mark"]["price_ticks"] == mark
    report = compare_qualification_predicates(*pair)
    assert report["diagnostic_status"] == status
    assert report["predicate_id"] == predicate.predicate_id
    assert report["observation_ids"] == [item.observation_id for item in pair]
    assert report["findings"] == [] and report["promotion_approved"] is False
    assert report["scope"]["source_claim_evaluated"] is False
    assert report["scope"]["finding_issued"] is False
    assert report["scope"]["observation_compatibility_certified"] is False
    assert report["scope"]["production_use_approved"] is False
    assert all(item["scope"] == report["scope"] and item["findings"] == [] for item in documents)


def test_marking_uses_physical_units_actual_fills_and_fee_without_spot_cash_debit(queue_result_factory) -> None:
    observed = observation(queue_result_factory, mark=102, spec_changes={
        "instrument": {"price_increment": "0.25", "size_increment": "0.5"},
        "fees": {"maker_rate": "0.0004"},
    })
    document = observed.document
    assert document["value"] == "0.24"
    assert document["valuation"]["mark"]["price"] == "25.5"
    assert document["valuation"]["physical_quantity"] == "0.5"
    assert document["valuation"]["fill_notional"] == "12.5"
    assert document["valuation"]["marked_position_value"] == "12.75"
    assert document["valuation"]["actual_commission"] == "0.01"
    assert document["audit"]["final_cash_total"] == "9999.99"
    assert document["value"] != document["audit"]["final_cash_total"]
    assert document["valuation"]["mark_liquidity_checked"] is False
    assert document["valuation"]["realized_pnl"] is False
    assert document["bindings"] == observed.replay_input.bindings
    assert document["replay_result_sha256"] == digest(observed.result.canonical_bytes)


def test_ambiguous_fee_cannot_be_turned_into_false_even_under_an_easy_threshold(queue_result_factory) -> None:
    changes = {"instrument": {"price_increment": "100.00065"},
               "account": {"starting_cash": "1000000000"}, "fees": {"maker_rate": "1"}}
    predicate = candidate(threshold="1000000000000")
    source = replay(FRONT, spec_changes=changes)
    result = queue_result_factory(source, commission_override="10000.06")
    front = qualify_predicate(source, result, predicate)
    assert front.document["audit"]["ambiguous_fee_fill_ordinals"] == [0]
    assert front.document["eligible"] is False
    assert front.document["value"] is front.document["satisfied"] is front.document["valuation"] is None
    assert front.document["reason"] == "ambiguous_native_fee_quantization"
    back = observation(queue_result_factory, BACK, predicate=predicate, spec_changes=changes)
    assert back.document["eligible"] is True and back.document["satisfied"] is False
    paired = compare_qualification_predicates(front, back)
    assert paired["diagnostic_status"] == "DIAGNOSTIC_PREDICATE_NOT_EVALUABLE"
    assert paired["findings"] == []


@pytest.mark.parametrize("attack", ["clock", "fee", "input", "unacknowledged_eof"])
def test_invalid_or_incomplete_execution_cannot_create_an_observation(queue_result_factory, attack) -> None:
    source = replay()
    document = queue_result_factory(source).document
    if attack == "clock":
        document["fill_trace"][0]["native_time_ns"] += 1
    elif attack == "fee":
        document["fill_trace"][0]["fields"]["commission"] = "99"
    elif attack == "input":
        document["input_trace"][0]["fields"]["bids"][0][1] += 1
    else:
        document["execution_status"] = "incomplete"
        document["completeness"].update(
            stop_reason="input_exhausted_with_open_orders",
            open_orders=[{"order_id": document["decision_trace"][0]["fields"]["order_id"],
                          "status": "ACCEPTED"}],
        )
    result = build_queue_replay_result(document)
    with pytest.raises(EvaluationValidationError):
        qualify_predicate(source, result, candidate())


@pytest.mark.parametrize("mismatch", ["predicate", "data", "policy", "environment", "forged_truth", "duck"])
def test_pair_refuses_mixed_contracts_and_supplied_proof_flags(queue_result_factory, mismatch) -> None:
    front = observation(queue_result_factory)
    back = observation(queue_result_factory, BACK)
    if mismatch == "predicate":
        back = observation(queue_result_factory, BACK, predicate=candidate(comparator="ge"))
    elif mismatch == "data":
        back = observation(queue_result_factory, BACK, mark=102)
    elif mismatch == "policy":
        back = observation(queue_result_factory, FRONT)
    elif mismatch == "environment":
        result = back.result.document
        result["environment"]["platform"] = "different diagnostic platform"
        back = qualify_predicate(back.replay_input, build_queue_replay_result(result), back.predicate)
    elif mismatch == "forged_truth":
        document = back.document
        document.update(eligible=True, value="1", satisfied=True)
        object.__setattr__(back, "canonical_bytes", canonical(document))
    else:
        back = {"eligible": True, "satisfied": True, "predicate_id": front.predicate.predicate_id}
    with pytest.raises(QualificationPredicateValidationError):
        compare_qualification_predicates(front, back)


def test_observation_has_no_public_constructor_for_caller_supplied_truth_or_eligibility(queue_result_factory) -> None:
    observed = observation(queue_result_factory)
    assert {item.name for item in fields(QualificationPredicateObservation) if item.init} == {
        "replay_input", "result", "predicate",
    }
    with pytest.raises(TypeError):
        QualificationPredicateObservation(observed.replay_input, observed.result, observed.predicate,
                                          eligible=True, satisfied=True)
    detached = observed.document
    detached["scope"]["source_claim_evaluated"] = True
    assert observed.document["scope"]["source_claim_evaluated"] is False


def test_unapproved_policy_is_rejected_before_any_candidate_truth_can_exist(queue_result_factory) -> None:
    source = replay()
    with pytest.raises(ReplayValidationError):
        QueueReplayInput(source.family, source.normalized_bytes, "front_is_compatible")
