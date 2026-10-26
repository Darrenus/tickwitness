"""A public trade is partitioned once across external ahead, tagged, external behind."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TaggedQueueValidationError,
    build_tagged_queue_protocol,
    validate_tagged_queue_input,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def rows() -> list[dict]:
    return [
        json.loads(line)
        for line in (EXAMPLES / "queue-observations.jsonl").read_bytes().splitlines()
    ]


def declaration() -> dict:
    return json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())


def pair(*, records=None, gross=None, quantity=2, spec_changes=None):
    records = rows() if records is None else records
    data = normalize_events(b"\n".join(canonical(row) for row in records) + b"\n").normalized_bytes
    source = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    source["replay_spec"]["strategy"]["quantity_lots"] = quantity
    for group, values in (spec_changes or {}).items():
        source["replay_spec"][group].update(values)
    spec = build_replay_spec(canonical(source["replay_spec"]))
    source_protocol = build_executable_protocol(
        canonical(source), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    actual = ReplayInput("a" * 64, data, spec)
    request = {
        "kind": "tagged_queue_request_v1",
        "schema_version": 1,
        "claim": {
            "title": "Tagged net mark",
            "hypothesis": "The conditional net mark is positive.",
            "metric": "tagged_inventory_net_marked_pnl_v1",
            "unit": "USD",
            "comparator": "gt",
            "threshold": "0",
        },
        "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 1000},
    }
    protocol = build_tagged_queue_protocol(
        canonical(request),
        source_protocol=source_protocol,
        replay_input=actual,
        queue_request=canonical(declaration() if gross is None else gross),
    )
    return validate_tagged_queue_input(protocol, actual)


def assert_conserved(document: dict, quantity: int) -> None:
    for interpretation in document["interpretations"]:
        previous = None
        for row in interpretation["trace"]:
            before, after, flow = row["before"], row["after"], row["flow"]
            assert before == previous
            assert after["external_lots"] == after["ahead_lots"] + after["behind_lots"]
            assert after["total_lots"] == after["external_lots"] + after["own_live_lots"]
            assert after["own_live_lots"] + after["own_filled_lots"] == quantity
            assert all(type(value) is int and value >= 0 for value in after.values())
            assert flow["trade_lots"] == (
                flow["external_trade_ahead_lots"]
                + flow["own_trade_lots"]
                + flow["external_trade_behind_lots"]
            )
            assert (
                flow["cancellations_lots"] == flow["cancel_ahead_lots"] + flow["cancel_behind_lots"]
            )
            assert row["own_fill_grant_lots"] == flow["own_trade_lots"]
            if before is not None:
                assert after["total_lots"] == (
                    before["total_lots"]
                    + flow["additions_lots"]
                    - flow["cancellations_lots"]
                    - flow["trade_lots"]
                )
                assert (
                    after["own_filled_lots"] == before["own_filled_lots"] + flow["own_trade_lots"]
                )
            if row["observed_total_lots"] is not None:
                assert after["total_lots"] == row["observed_total_lots"]
            previous = after
        assert interpretation["horizon"]["state"] == previous
        assert interpretation["horizon"]["post_horizon_cancel_lots"] == previous["own_live_lots"]


def test_standard_witness_relabels_two_existing_lots_and_removes_double_count() -> None:
    witness = pair()
    doc = witness.document
    assert witness.witness_id == digest(witness.canonical_bytes)
    assert doc["kind"] == "tagged_queue_witness_pair_v1"
    front, back = doc["interpretations"]
    assert front["trace"][0]["after"] == {
        "ahead_lots": 3,
        "own_live_lots": 2,
        "behind_lots": 0,
        "external_lots": 3,
        "total_lots": 5,
        "own_filled_lots": 0,
    }
    assert front["trace"][2]["after"]["ahead_lots"] == 0
    assert back["trace"][2]["after"]["ahead_lots"] == 3
    assert front["trace"][3]["flow"]["own_trade_lots"] == 2
    assert front["trace"][3]["flow"]["external_trade_behind_lots"] == 1
    assert back["trace"][3]["flow"]["own_trade_lots"] == 0
    assert back["trace"][3]["flow"]["external_trade_ahead_lots"] == 3
    assert front["horizon"]["state"] == {
        "ahead_lots": 0,
        "own_live_lots": 0,
        "behind_lots": 2,
        "external_lots": 2,
        "total_lots": 2,
        "own_filled_lots": 2,
    }
    assert back["horizon"]["state"] == {
        "ahead_lots": 0,
        "own_live_lots": 2,
        "behind_lots": 0,
        "external_lots": 0,
        "total_lots": 2,
        "own_filled_lots": 0,
    }
    assert front["horizon"]["post_horizon_cancel_lots"] == 0
    assert back["horizon"]["post_horizon_cancel_lots"] == 2
    assert [row["after"]["total_lots"] for row in front["trace"]] == [5, 8, 5, 2, 2, 2]
    assert [row["after"]["total_lots"] for row in back["trace"]] == [5, 8, 5, 2, 2, 2]
    assert_conserved(doc, 2)
    assert b'"native_execution_verified":true' not in witness.canonical_bytes
    assert b'"claim_observation"' not in witness.canonical_bytes


def test_single_trade_can_consume_all_three_regions_without_duplicating_a_lot() -> None:
    records, gross = rows(), declaration()
    records[1]["bids"] = [[100, 10]]
    records[2]["bids"] = [[100, 8]]
    records[3]["quantity_lots"] = 6
    gross["updates"][0]["additions_lots"] = 5
    gross["updates"][1]["cancellations_lots"] = 2
    doc = pair(records=records, gross=gross).document
    trade = doc["interpretations"][0]["trace"][3]["flow"]
    assert [
        trade[key]
        for key in (
            "external_trade_ahead_lots",
            "own_trade_lots",
            "external_trade_behind_lots",
            "trade_lots",
        )
    ] == [1, 2, 3, 6]
    assert_conserved(doc, 2)


def test_partial_tagged_fill_remains_live_until_horizon_then_declares_only_cleanup() -> None:
    records = rows()
    records[3]["quantity_lots"] = 1
    records[4]["bids"] = records[5]["bids"] = [[100, 4]]
    doc = pair(records=records).document
    front, back = doc["interpretations"]
    assert front["horizon"]["state"]["own_filled_lots"] == 1
    assert front["horizon"]["post_horizon_cancel_lots"] == 1
    assert back["horizon"]["state"]["own_filled_lots"] == 0
    assert back["horizon"]["post_horizon_cancel_lots"] == 2
    assert all(len(value["trace"]) == len(records) for value in doc["interpretations"])
    assert all(value["trace"][-1]["after"]["own_live_lots"] > 0 for value in doc["interpretations"])
    assert_conserved(doc, 2)


def test_no_cancellation_control_keeps_both_worlds_identical() -> None:
    records, gross = rows(), declaration()
    records[2]["bids"] = [[100, 8]]
    records[4]["bids"] = records[5]["bids"] = [[100, 5]]
    gross["updates"][1]["cancellations_lots"] = 0
    doc = pair(records=records, gross=gross).document
    front, back = doc["interpretations"]
    assert front["trace"] == back["trace"]
    assert front["horizon"] == back["horizon"]
    assert front["horizon"]["state"]["own_filled_lots"] == 0
    assert_conserved(doc, 2)


def test_no_trade_window_has_no_fill_and_no_synthetic_cleanup_market_event() -> None:
    records, gross = rows()[:3], declaration()
    gross["updates"] = gross["updates"][:2]
    doc = pair(records=records, gross=gross).document
    for value in doc["interpretations"]:
        assert len(value["trace"]) == 3
        assert value["horizon"]["state"]["own_filled_lots"] == 0
        assert value["horizon"]["post_horizon_cancel_lots"] == 2
        assert value["horizon"]["source_ref"]["capture_seq"] == 3
    assert_conserved(doc, 2)


@pytest.mark.parametrize("quantity", [1, 3, 5])
def test_general_tagged_size_is_a_partition_of_actual_initial_depth(quantity) -> None:
    doc = pair(quantity=quantity).document
    assert doc["interpretations"][0]["trace"][0]["after"]["ahead_lots"] == 5 - quantity
    assert_conserved(doc, quantity)


def test_tagged_size_cannot_exceed_already_observed_initial_quantity() -> None:
    with pytest.raises(TaggedQueueValidationError, match="exceeds initial"):
        pair(quantity=6)


def test_external_cancel_cannot_consume_protected_tagged_quantity() -> None:
    records, gross = rows()[:3], declaration()
    records[2]["bids"] = [[100, 1]]
    gross["updates"] = gross["updates"][:2]
    gross["updates"][1]["cancellations_lots"] = 7
    with pytest.raises(TaggedQueueValidationError, match="protected tagged"):
        pair(records=records, gross=gross)


def test_freeze_rejects_pair_when_only_back_world_cannot_protect_tagged_order() -> None:
    records, gross = rows(), declaration()
    records[-1]["bids"] = [[100, 1]]
    gross["updates"][-1]["cancellations_lots"] = 1
    with pytest.raises(TaggedQueueValidationError, match="protected tagged"):
        pair(records=records, gross=gross)


def test_explicit_gross_churn_is_not_inferred_from_the_net_change() -> None:
    gross = declaration()
    gross["updates"][1].update(additions_lots=2, cancellations_lots=5)
    doc = pair(gross=gross).document
    front, back = doc["interpretations"]
    assert front["trace"][2]["flow"]["additions_lots"] == 2
    assert front["trace"][2]["flow"]["cancellations_lots"] == 5
    assert front["horizon"]["state"]["own_filled_lots"] == 2
    assert back["horizon"]["state"]["own_filled_lots"] == 0
    assert_conserved(doc, 2)


def test_mark_uses_actual_final_best_bid_instead_of_the_tagged_target_price() -> None:
    records = rows()
    records[-1]["bids"] = [[100, 2], [102, 7]]
    doc = pair(records=records).document
    for value in doc["interpretations"]:
        assert value["horizon"]["mark"] == {
            "source_ref": {"line": 6, "capture_seq": 6, "event_type": "delta"},
            "price_ticks": 102,
            "available_quantity_lots": 7,
        }
    assert_conserved(doc, 2)


def test_deleted_best_bid_is_not_retained_as_a_future_or_stale_mark() -> None:
    records = rows()
    records[4]["bids"] = [[100, 2], [102, 7]]
    records[5]["bids"] = [[100, 2], [102, 0]]
    doc = pair(records=records).document
    assert all(value["horizon"]["mark"]["price_ticks"] == 100 for value in doc["interpretations"])


def test_unrelated_source_updates_are_preserved_without_hidden_queue_flow() -> None:
    records, gross = rows(), declaration()
    extra = dict(records[-1])
    extra.update(bids=[], asks=[[104, 11]])
    records[-1].update(capture_seq=7, first_sequence=15, last_sequence=15)
    records.insert(-1, extra)
    gross["updates"][-1]["capture_seq"] = 7
    doc = pair(records=records, gross=gross).document
    for value in doc["interpretations"]:
        unrelated = value["trace"][-2]
        assert unrelated["kind"] == "unrelated"
        assert unrelated["before"] == unrelated["after"]
        assert unrelated["observed_total_lots"] is None
        assert set(unrelated["flow"].values()) == {0}
        assert len(value["trace"]) == 7
    assert_conserved(doc, 2)


def test_same_time_inputs_remain_in_capture_order_and_units_do_not_change_lot_conservation() -> (
    None
):
    records = rows()
    for row in records:
        row["receive_time_ns"] = 1_700_000_000_000_000_000
        row["event_time_ns"] = 1_699_999_999_999_999_900
    doc = pair(
        records=records,
        spec_changes={"instrument": {"price_increment": "0.01", "size_increment": "0.1"}},
    ).document
    for value in doc["interpretations"]:
        assert [row["source_ref"]["capture_seq"] for row in value["trace"]] == list(range(1, 7))
    assert_conserved(doc, 2)


def test_witness_is_immutable_and_views_are_detached() -> None:
    witness = pair()
    original = witness.canonical_bytes
    doc = witness.document
    doc["interpretations"][0]["trace"][0]["after"]["own_live_lots"] = 999
    assert witness.document["interpretations"][0]["trace"][0]["after"]["own_live_lots"] == 2
    assert witness.canonical_bytes == original
    with pytest.raises(FrozenInstanceError):
        witness.canonical_bytes = b"{}"
