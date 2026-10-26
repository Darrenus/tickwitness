"""Attack the independent queue audit with coherent, native-free callback receipts."""

import json
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.evaluation import EvaluationValidationError
from tickwitness.domain.evidence.queue_evaluation import (
    evaluate_queue_replay,
    load_queue_evaluation,
)
from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.queue_contracts import (
    QueueReplayInput,
    build_queue_replay_result,
)
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.queue_family import build_queue_family_protocol

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def queue_input(policy="cancel_front_first_v1", *, spec_changes=None, gross_churn=False):
    experiment = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    for group, changes in (spec_changes or {}).items():
        experiment["replay_spec"][group].update(changes)
    spec = build_replay_spec(canonical(experiment["replay_spec"]))
    source = build_executable_protocol(
        canonical(experiment), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    data = normalize_events((EXAMPLES / "queue-observations.jsonl").read_bytes()).normalized_bytes
    declaration = json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())
    if gross_churn:
        declaration["updates"][1].update(additions_lots=3, cancellations_lots=6)
    family = build_queue_family_protocol(
        canonical(
            {
                "kind": "queue_family_request_v1",
                "schema_version": 1,
                "cancel_at_capture_seq": 6,
                "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 1000},
            }
        ),
        source_protocol=source,
        replay_input=ReplayInput("a" * 64, data, spec),
        queue_request=canonical(declaration),
    )
    return QueueReplayInput(family, data, policy)


@pytest.mark.parametrize(
    "policy,filled", [("cancel_front_first_v1", 1), ("cancel_back_first_v1", 0)]
)
def test_same_observations_have_two_audited_queue_outcomes(
    queue_result_factory, policy, filled
) -> None:
    replay_input = queue_input(policy)
    result = queue_result_factory(replay_input)
    evaluation = evaluate_queue_replay(replay_input, result)
    document = evaluation.document
    assert evaluation == load_queue_evaluation(evaluation.canonical_bytes)
    assert evaluation.evaluation_id == digest(evaluation.canonical_bytes)
    assert document["bindings"] == replay_input.bindings
    assert document["replay_result_sha256"] == digest(result.canonical_bytes)
    assert document["filled_quantity_lots"] == filled
    assert document["actual_commission"] == ("1" if filled else "0")
    assert document["final_cash_total"] == ("9999" if filled else "10000")
    assert document["final_order_status"] == "CANCELED"
    assert document["compatible_native_raw_modes"] == [9, 16]
    assert document["scope"] == {
        "scenario_kind": "MODEL_SENSITIVITY",
        "impact_compatibility_verified": False,
        "claim_verdict_issued": False,
        "valuation_issued": False,
    }
    for absent in ("pnl", "claim_observation", "claim_verdict", "findings"):
        assert absent not in document


def test_physical_increments_and_native_usd_fee_half_cent_rounding(queue_result_factory) -> None:
    replay_input = queue_input(
        spec_changes={
            "instrument": {"price_increment": "0.25", "size_increment": "0.5"},
            "fees": {"maker_rate": "0.0004"},
        }
    )
    result = queue_result_factory(replay_input)
    fill = result.document["fill_trace"][0]["fields"]
    assert fill["price"] == "25.00"
    assert fill["quantity"] == "0.5"
    assert fill["commission"] == "0.01"
    evaluation = evaluate_queue_replay(replay_input, result).document
    assert evaluation["filled_quantity_lots"] == 1
    assert evaluation["actual_commission"] == "0.01"
    assert evaluation["final_cash_total"] == "9999.99"


@pytest.mark.parametrize(
    "policy,filled,status",
    [
        ("cancel_front_first_v1", 2, "FILLED"),
        ("cancel_back_first_v1", 0, "CANCELED"),
    ],
)
def test_declared_gross_churn_changes_frontier_while_public_depth_stays_the_same(
    queue_result_factory, policy, filled, status
) -> None:
    ordinary = queue_input(policy)
    churn = queue_input(policy, gross_churn=True)
    assert ordinary.normalized_bytes == churn.normalized_bytes
    result = queue_result_factory(churn)
    document = evaluate_queue_replay(churn, result).document
    assert result.document["queue_trace"][2]["flow"]["additions_lots"] == 3
    assert result.document["queue_trace"][2]["flow"]["cancellations_lots"] == 6
    assert document["filled_quantity_lots"] == filled
    assert document["final_order_status"] == status
    assert len(result.document["decision_trace"]) == (1 if filled == 2 else 2)


def omitted_front_fill(queue_result_factory, *, retain_grant):
    """Keep the front frontier but replace settlement with coherent no-fill callbacks."""
    replay_input = queue_input()
    document = queue_result_factory(replay_input).document
    no_fill_input = QueueReplayInput(
        replay_input.family, replay_input.normalized_bytes, "cancel_back_first_v1"
    )
    no_fill = queue_result_factory(no_fill_input).document
    # These channels agree with one another: zero fees/position, no fill event,
    # and a genuinely acknowledged final cancellation. The lie is the omitted
    # deterministic matching opportunity, not an account/lifecycle inconsistency.
    for channel in ("decision_trace", "order_trace", "fill_trace", "account_trace"):
        document[channel] = no_fill[channel]
    if not retain_grant:
        document["hook_trace"] = []
    for row in document["queue_trace"]:
        row["granted_lots"] = row["grant_limit_lots"] if retain_grant else 0
        row["native_filled_lots"] = 0
        row["own_remaining_lots"] = 2
    assert document["queue_trace"][3]["grant_limit_lots"] == 1
    assert document["fill_trace"] == []
    assert document["account_trace"][-1]["fields"]["cash_total"] == "10000"
    assert document["order_trace"][-1]["kind"] == "OrderCanceled"
    return replay_input, build_queue_replay_result(document)


def test_front_opportunity_cannot_disappear_with_all_grants_fills_and_fees(
    queue_result_factory,
) -> None:
    replay_input, result = omitted_front_fill(queue_result_factory, retain_grant=False)
    assert result.document["hook_trace"] == []
    assert result.document["queue_trace"][3]["granted_lots"] == 0
    with pytest.raises(EvaluationValidationError, match="deterministic queue allocation"):
        evaluate_queue_replay(replay_input, result)


def test_actual_positive_grant_requires_matching_fill_callbacks_and_settlement(
    queue_result_factory,
) -> None:
    replay_input, result = omitted_front_fill(queue_result_factory, retain_grant=True)
    assert result.document["hook_trace"][0]["offered_lots"] == 1
    assert result.document["queue_trace"][3]["granted_lots"] == 1
    assert result.document["queue_trace"][3]["native_filled_lots"] == 0
    with pytest.raises(EvaluationValidationError, match="deterministic queue allocation"):
        evaluate_queue_replay(replay_input, result)


@pytest.mark.parametrize(
    "attack",
    [
        "source_clock",
        "receive_clock",
        "source_sequence",
        "source_trade",
        "source_prices",
        "callback_clock",
        "callback_source",
        "future_trade",
        "changed_binding",
        "dependency_version",
        "queue_before",
        "queue_after",
        "gross_flow",
        "queue_observed",
        "queue_clock",
        "capacity",
        "grant",
        "queue_fill",
        "queue_remaining",
        "acceptance_capture",
        "hook_origin",
        "duplicate_grant",
        "missing_hook",
        "hook_future",
        "fill_units",
        "fill_price",
        "fill_fee",
        "fill_currency",
        "fill_liquidity",
        "fill_order",
        "duplicate_fill",
        "missing_lifecycle_fill",
        "acceptance_depth",
        "acceptance_queue",
        "acknowledgement",
        "lifecycle_quantity",
        "cancel_before_frozen_capture",
        "cash_total",
        "cash_conservation",
        "cash_semantics",
        "position",
        "observed_fees",
        "account_order",
        "account_book",
        "boundary_clock",
        "boundary_context",
        "missing_account",
        "lifecycle_terminal",
    ],
)
def test_source_grants_settlement_and_lifecycle_tampering_is_rejected(
    queue_result_factory, attack
) -> None:
    replay_input = queue_input()
    document = queue_result_factory(replay_input).document
    inputs, queue = document["input_trace"], document["queue_trace"]
    fill = document["fill_trace"][0]
    order = document["order_trace"]
    account = document["account_trace"]
    if attack == "source_clock":
        inputs[3]["fields"]["event_time_ns"] += 1
    elif attack == "receive_clock":
        inputs[3]["fields"]["native_ts_event_ns"] += 1
    elif attack == "source_sequence":
        inputs[1]["fields"]["source_sequence_first"] += 1
    elif attack == "source_trade":
        inputs[3]["fields"]["source_trade_id"] = "another-source-trade"
    elif attack == "source_prices":
        inputs[1]["fields"]["bids"][0][1] += 1
    elif attack == "callback_clock":
        fill["native_time_ns"] += 1
    elif attack == "callback_source":
        fill["source_ref"] = inputs[4]["source_ref"]
        fill["native_time_ns"] = inputs[4]["native_time_ns"]
    elif attack == "future_trade":
        fill["source_ref"] = inputs[0]["source_ref"]
        fill["native_time_ns"] = inputs[0]["native_time_ns"]
    elif attack == "changed_binding":
        document["bindings"]["data_sha256"] = "0" * 64
    elif attack == "dependency_version":
        document["environment"]["package_versions"]["nautilus_trader"] = "1.0.0"
    elif attack == "queue_before":
        queue[3]["before"]["ahead_lots"] += 1
    elif attack == "queue_after":
        queue[3]["after"]["behind_lots"] += 1
    elif attack == "gross_flow":
        queue[2]["flow"]["additions_lots"] += 1
    elif attack == "queue_observed":
        queue[3]["market_observed_lots"] += 1
    elif attack == "queue_clock":
        queue[3]["receive_time_ns"] += 1
    elif attack == "capacity":
        queue[3]["grant_limit_lots"] += 1
    elif attack == "grant":
        queue[3]["granted_lots"] += 1
    elif attack == "queue_fill":
        queue[3]["native_filled_lots"] += 1
    elif attack == "queue_remaining":
        queue[3]["own_remaining_lots"] += 1
    elif attack == "acceptance_capture":
        queue[0]["accepted_here"] = False
    elif attack == "hook_origin":
        document["hook_trace"][0]["origin"] = "reconstructed_after_execution"
    elif attack == "duplicate_grant":
        duplicate = dict(document["hook_trace"][0])
        duplicate["cumulative_granted_lots"] = 2
        document["hook_trace"].append(duplicate)
    elif attack == "missing_hook":
        document["hook_trace"] = []
    elif attack == "hook_future":
        document["hook_trace"][0]["source_ref"] = inputs[0]["source_ref"]
    elif attack == "fill_units":
        fill["fields"]["quantity"] = "2"
    elif attack == "fill_price":
        fill["fields"]["price"] = "101"
    elif attack == "fill_fee":
        fill["fields"]["commission"] = "0.99"
    elif attack == "fill_currency":
        fill["fields"]["commission_currency"] = "EUR"
    elif attack == "fill_liquidity":
        fill["fields"]["liquidity_side"] = "TAKER"
    elif attack == "fill_order":
        fill["fields"]["order_id"] = "different-order"
    elif attack == "duplicate_fill":
        duplicate = json.loads(canonical(fill))
        duplicate["ordinal"] = 1
        document["fill_trace"].append(duplicate)
    elif attack == "missing_lifecycle_fill":
        document["order_trace"] = [row for row in order if row["kind"] != "OrderFilled"]
        for index, row in enumerate(document["order_trace"]):
            row["ordinal"] = index
    elif attack == "acceptance_depth":
        order[2]["fields"]["actual_acceptance"]["native_bid_lots"] += 1
    elif attack == "acceptance_queue":
        order[2]["fields"]["actual_acceptance"]["queue"]["ahead_lots"] -= 1
    elif attack == "acknowledgement":
        order[2]["fields"]["pending_commands"] = ["command-0"]
    elif attack == "lifecycle_quantity":
        order[-1]["fields"]["filled_quantity_lots"] = 0
    elif attack == "cancel_before_frozen_capture":
        cancel = document["decision_trace"][1]
        cancel["source_ref"] = inputs[4]["source_ref"]
        cancel["native_time_ns"] = inputs[4]["native_time_ns"]
    elif attack == "cash_total":
        account[-1]["fields"].update(cash_total="9998", cash_free="9998")
    elif attack == "cash_conservation":
        account[-1]["fields"]["cash_locked"] = "1"
    elif attack == "cash_semantics":
        account[-1]["fields"]["cash_semantics"] = "spot_notional_debit"
    elif attack == "position":
        account[-1]["fields"]["net_position_lots"] = 2
    elif attack == "observed_fees":
        account[-1]["fields"]["observed_commission"] = "2"
    elif attack == "account_order":
        account[-1]["fields"]["orders"][0]["status"] = "FILLED"
    elif attack == "account_book":
        account[-1]["fields"]["bid_levels"] = 1
    elif attack == "boundary_clock":
        account[-1]["native_time_ns"] += 1
    elif attack == "boundary_context":
        account[-1]["source_ref"] = inputs[-1]["source_ref"]
    elif attack == "missing_account":
        document["account_trace"].pop(1)
        for index, row in enumerate(document["account_trace"]):
            row["ordinal"] = index
    else:
        order[-1]["fields"]["status"] = "ACCEPTED"
    result = build_queue_replay_result(document)
    with pytest.raises(EvaluationValidationError):
        evaluate_queue_replay(replay_input, result)


@pytest.mark.parametrize("pending", [False, True])
def test_true_eof_with_open_or_unacknowledged_cancel_cannot_be_a_verified_execution(
    queue_result_factory, pending
) -> None:
    replay_input = queue_input()
    document = queue_result_factory(replay_input).document
    document["execution_status"] = "incomplete"
    document["order_trace"].pop()  # Remove the terminal cancellation acknowledgement.
    if pending:
        decision = document["decision_trace"][-1]
        document["completeness"].update(
            stop_reason="pending_commands_at_data_end",
            open_orders=[{"order_id": decision["fields"]["order_id"], "status": "PENDING_CANCEL"}],
            pending_commands=[
                {
                    "command_id": "command-1",
                    "order_id": decision["fields"]["order_id"],
                    "command_type": "cancel",
                    "decision_ref": "decision-1",
                    "source_ref": decision["source_ref"],
                }
            ],
        )
    else:
        document["order_trace"].pop()
        document["decision_trace"].pop()
        document["completeness"].update(
            stop_reason="input_exhausted_with_open_orders",
            open_orders=[{"order_id": "fixture-queue-order-1", "status": "PARTIALLY_FILLED"}],
        )
    result = build_queue_replay_result(document)
    with pytest.raises(EvaluationValidationError):
        evaluate_queue_replay(replay_input, result)


@pytest.mark.parametrize("mutation", ["scope", "version", "money", "extra", "modes"])
def test_evaluation_loader_remains_strict_and_cannot_gain_a_claim_verdict(
    queue_result_factory, mutation
) -> None:
    replay_input = queue_input()
    document = evaluate_queue_replay(replay_input, queue_result_factory(replay_input)).document
    if mutation == "scope":
        document["scope"]["claim_verdict_issued"] = True
    elif mutation == "version":
        document["schema_version"] = True
    elif mutation == "money":
        document["actual_commission"] = "0.001"
    elif mutation == "extra":
        document["finding"] = "approved"
    else:
        document["compatible_native_raw_modes"] = [9, 9]
    with pytest.raises(EvaluationValidationError):
        load_queue_evaluation(canonical(document))
