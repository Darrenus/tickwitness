"""Frozen family members execute original, variable user inputs through public hooks."""

import json
import sys
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay._validation import ReplayValidationError, canonical
from tickwitness.domain.replay.contracts import ReplayInput, load_replay_result
from tickwitness.domain.replay.queue_contracts import QueueReplayInput, load_queue_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.queue_family import build_queue_family_protocol
from tickwitness.infrastructure._queue_native import _ShadowQueue
from tickwitness.infrastructure._queue_worker import _request
from tickwitness.infrastructure.queue_replay import (
    NautilusQueueReplayAdapter,
    QueueSubprocessReplayAdapter,
)
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
POLICIES = ("cancel_front_first_v1", "cancel_back_first_v1")


def _native_installed() -> bool:
    try:
        return metadata.version("nautilus_trader") == "1.231.0"
    except metadata.PackageNotFoundError:
        return False


native = pytest.mark.skipif(not _native_installed(), reason="optional pinned Nautilus extra absent")


def context(case="standard", policy=POLICIES[0]):
    rows = [json.loads(line) for line in (EXAMPLES / "queue-observations.jsonl").read_bytes().splitlines()]
    declaration = json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())
    experiment = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    if case == "same_time":
        for row in rows:
            row["receive_time_ns"] = rows[0]["receive_time_ns"]
            row["event_time_ns"] = rows[0]["event_time_ns"]
    if case == "no_cancel":
        rows[2]["bids"] = [[100, 8]]
        rows[4]["bids"] = rows[5]["bids"] = [[100, 5]]
        declaration["updates"][1]["cancellations_lots"] = 0
    if case == "gross_churn":
        declaration["updates"][1].update(additions_lots=3, cancellations_lots=6)
    if case == "variable":
        for row in rows:
            for side in ("bids", "asks"):
                if side in row:
                    row[side] = [[price + 300, size] for price, size in row[side]]
            if "price_ticks" in row:
                row["price_ticks"] += 300
        last = dict(rows[-1])
        last.update(capture_seq=7, first_sequence=15, last_sequence=15,
                    receive_time_ns=rows[-1]["receive_time_ns"] + 1,
                    event_time_ns=rows[-1]["event_time_ns"] + 1)
        rows.append(last)
        declaration["updates"].append({"capture_seq": 7, "additions_lots": 0,
                                      "cancellations_lots": 0, "trade_capture_seqs": []})
        experiment["replay_spec"]["instrument"].update(price_increment="0.25", size_increment="0.01")
        experiment["replay_spec"]["strategy"].update(limit_price_ticks=400, quantity_lots=3)
        experiment["replay_spec"]["account"]["starting_cash"] = "12345.67"
    normalized = normalize_events(b"\n".join(canonical(row) for row in rows) + b"\n").normalized_bytes
    source = build_executable_protocol(canonical(experiment), development_dataset_id="a" * 64,
                                       confirmation_dataset_id="b" * 64)
    spec = build_replay_spec(canonical(experiment["replay_spec"]))
    replay_input = ReplayInput("a" * 64, normalized, spec)
    family = build_queue_family_protocol(
        canonical({"kind": "queue_family_request_v1", "schema_version": 1,
                   "cancel_at_capture_seq": rows[-1]["capture_seq"],
                   "budget": {"max_attempts": 4, "max_wall_seconds": 60, "max_events": 1000}}),
        source_protocol=source, replay_input=replay_input, queue_request=canonical(declaration),
    )
    return QueueReplayInput(family, normalized, policy)


@native
@pytest.mark.parametrize("case,front_lots", [("standard", 1), ("same_time", 1),
                                           ("no_cancel", 0), ("gross_churn", 2), ("variable", 1)])
def test_paired_native_models_keep_source_and_capture_budgets(case, front_lots) -> None:
    front_input = context(case)
    original = front_input.normalized_bytes
    back_input = QueueReplayInput(front_input.family, original, POLICIES[1])
    front = NautilusQueueReplayAdapter().run(front_input)
    back = NautilusQueueReplayAdapter().run(back_input)
    documents = [front.document, back.document]
    assert [sum(row["fields"]["quantity_lots"] for row in doc["fill_trace"])
            for doc in documents] == [front_lots, 0]
    for request, result in zip((front_input, back_input), (front, back), strict=True):
        doc = result.document
        assert doc["kind"] == "queue_replay_result_v1"
        assert load_queue_replay_result(result.canonical_bytes) == result
        with pytest.raises(ReplayValidationError):
            load_replay_result(result.canonical_bytes)
        assert doc["bindings"] == request.bindings
        assert doc["execution_status"] == "completed"
        assert doc["completeness"]["processed_records"] == len(request.prepared.events)
        assert doc["completeness"]["open_orders"] == []
        assert doc["completeness"]["pending_commands"] == []
        assert [row["source_ref"] for row in doc["input_trace"]] == [event.source_ref for event in request.prepared.events]
        accepted = [row for row in doc["order_trace"] if row["kind"] == "OrderAccepted"]
        assert len(accepted) == 1
        assert accepted[0]["source_ref"]["capture_seq"] == 1
        assert accepted[0]["fields"]["actual_acceptance"]["native_bid_lots"] == 5
        assert doc["queue_trace"][0]["accepted_here"] is True
        assert doc["queue_trace"][0]["after"] == {"ahead_lots": 5, "behind_lots": 0, "external_lots": 5}
        for row in doc["queue_trace"]:
            cap = row["source_ref"]["capture_seq"]
            grants = [hook for hook in doc["hook_trace"] if hook["source_ref"]["capture_seq"] == cap]
            fills = [fill for fill in doc["fill_trace"] if fill["source_ref"]["capture_seq"] == cap]
            assert row["granted_lots"] == sum(hook["offered_lots"] for hook in grants)
            assert row["native_filled_lots"] == sum(fill["fields"]["quantity_lots"] for fill in fills)
            assert 0 <= row["native_filled_lots"] <= row["granted_lots"] <= row["grant_limit_lots"]
            if row["source_ref"]["event_type"] != "trade":
                assert row["granted_lots"] == row["native_filled_lots"] == 0
        final = doc["account_trace"][-1]
        assert final["kind"] == "final_account_snapshot" and final["source_ref"] is None
        state = final["fields"]
        assert Decimal(state["cash_free"]) + Decimal(state["cash_locked"]) == Decimal(state["cash_total"])
        assert state["net_position_lots"] == sum(row["fields"]["quantity_lots"] for row in doc["fill_trace"])
        assert len([row for row in doc["account_trace"] if row["kind"] == "fill_callback_account_snapshot"]) == len(doc["fill_trace"])
        for fill in doc["fill_trace"]:
            assert fill["source_ref"]["capture_seq"] == 4
            assert fill["fields"]["commission_currency"] == "USD"
            assert fill["fields"]["liquidity_side"] == "MAKER"
        cancel = [row for row in doc["decision_trace"] if row["fields"]["action"] == "cancel"]
        if state["orders"][0]["status"] != "FILLED":
            assert len(cancel) == 1
            assert cancel[0]["source_ref"]["capture_seq"] == request.prepared.events[-1].capture_seq
            assert state["orders"][0]["status"] == "CANCELED"
    assert front_input.normalized_bytes == back_input.normalized_bytes == original
    if case == "variable":
        assert documents[0]["fill_trace"][0]["fields"]["price_ticks"] == 400
        assert Decimal(documents[0]["fill_trace"][0]["fields"]["quantity"]) == Decimal("0.01")
        assert Decimal(documents[0]["account_trace"][-1]["fields"]["cash_total"]) == Decimal("12345.66")
        assert documents[0]["decision_trace"][-1]["source_ref"]["capture_seq"] == 7


@native
def test_installed_queue_worker_has_distinct_result_and_semantics() -> None:
    request = context("variable")
    result = QueueSubprocessReplayAdapter().run(request)
    assert result.document["bindings"] == request.bindings
    assert result.document["engine"]["semantic_id"] == "nautilus_external_fifo_shadow_queue_execution_v1"
    assert result.document["execution_status"] == "completed"


def test_capture_budget_cannot_be_granted_twice_or_consumed_on_a_nontrade() -> None:
    from tickwitness.infrastructure._nautilus_native import _Settings

    request = context()
    queue = _ShadowQueue(request, _Settings.from_prepared(request.prepared))
    for event in request.prepared.events[:4]:
        queue.index += 1
        queue.begin(event)
        if event.capture_seq == 1:
            assert queue.take() == 0
            queue.accepted()
        if event.capture_seq == 3:
            assert queue.take() == 0
            with pytest.raises(ValueError, match="source trade"):
                queue.fill(1)
    assert queue.take() == 1
    assert queue.take() == 0
    queue.fill(1)
    with pytest.raises(ValueError, match="budget"):
        queue.fill(1)


@pytest.mark.parametrize("raw", [b"", b"{}", b'{"kind":"x","kind":"x"}',
                                 b'{"schema_version":1.0}', b'{"schema_version":NaN}'])
def test_worker_rejects_unsupported_or_ambiguous_json(raw) -> None:
    with pytest.raises(ReplayValidationError):
        _request(raw)


def test_worker_revalidates_original_data_and_rejects_paths() -> None:
    request = context()
    envelope = {"kind": "queue_replay_worker_request_v1", "schema_version": 1,
                "family": request.family.canonical_bytes.decode(),
                "normalized": request.normalized_bytes.decode(), "policy_id": request.policy_id}
    assert _request(canonical(envelope)) == request
    envelope["path"] = "/tmp/untrusted"
    with pytest.raises(ReplayValidationError):
        _request(canonical(envelope))


def test_real_queue_supervisor_bounds_and_rejects_other_result_kinds(tmp_path: Path) -> None:
    interpreter = tmp_path / "worker"
    interpreter.write_text(f"#!{sys.executable}\nprint('{{}}')\n")
    interpreter.chmod(0o700)
    with pytest.raises(ReplayProcessError) as caught:
        QueueSubprocessReplayAdapter(python_executable=interpreter).run(context())
    assert caught.value.code == "engine_invalid_result"
    interpreter.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(10)\n")
    with pytest.raises(ReplayProcessError) as caught:
        QueueSubprocessReplayAdapter(timeout_seconds=1, python_executable=interpreter).run(context())
    assert caught.value.code == "engine_timeout"
    interpreter.write_text(f"#!{sys.executable}\nimport os\nos.write(2, b'x' * 70000)\n")
    with pytest.raises(ReplayProcessError) as caught:
        QueueSubprocessReplayAdapter(python_executable=interpreter).run(context())
    assert caught.value.code == "engine_output_limit"
