"""Bounded qualification contracts, physical book checks and trace provenance."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_DOWN, ROUND_UP, localcontext
from typing import cast

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay.contracts import (
    ReplayInput,
    build_replay_result,
    load_replay_result,
)
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import (
    ReplaySpec,
    ReplayValidationError,
    build_replay_spec,
    load_replay_spec,
)
from tickwitness.domain.research_contracts import build_frozen_protocol


def spec_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "clock_policy_id": "receive_order_v1",
        "instrument": {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "price_increment": "1.00",
            "size_increment": "1",
        },
        "account": {"starting_cash": "10000.00"},
        "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
        "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
        "strategy": {
            "kind": "single_limit_buy_v1",
            "submit_capture_seq": 1,
            "limit_price_ticks": 100,
            "quantity_lots": 2,
            "cancel_after_first_fill": False,
        },
        "seed": 7,
    }


def encoded(document: dict[str, object]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "snapshot",
        "source": "synthetic",
        "instrument": "EUR-USD",
        "session": "qualification",
        "capture_seq": 1,
        "event_time_ns": 90,
        "receive_time_ns": 100,
        "last_sequence": 10,
        "bids": [[100, 5]],
        "asks": [[102, 5]],
    }


def delta() -> dict[str, object]:
    return {
        **snapshot(),
        "type": "delta",
        "capture_seq": 2,
        "event_time_ns": 95,
        "receive_time_ns": 100,
        "first_sequence": 11,
        "last_sequence": 11,
        "bids": [[100, 4]],
        "asks": [],
    }


def replay_input(
    records: list[dict[str, object]] | None = None, spec: dict[str, object] | None = None
) -> ReplayInput:
    raw = b"".join(
        encoded(record) + b"\n"
        for record in ([snapshot(), delta()] if records is None else records)
    )
    normalized = normalize_events(raw).normalized_bytes
    return ReplayInput(
        "a" * 64, normalized, build_replay_spec(encoded(spec_document() if spec is None else spec))
    )


def reference(line: int = 1, capture_seq: int = 1) -> dict[str, object]:
    return {"line": line, "capture_seq": capture_seq, "event_type": "snapshot"}


def trace(*, source_ref: dict[str, object] | None = None, ordinal: int = 0) -> dict[str, object]:
    return {
        "kind": "input",
        "ordinal": ordinal,
        "native_time_ns": 100,
        "source_ref": reference() if source_ref is None else source_ref,
        "fields": {"original_event_time_ns": 90},
    }


def result_document() -> dict[str, object]:
    return {
        "kind": "replay_qualification_result_v1",
        "schema_version": 1,
        "engine": {
            "id": "nautilus-trader",
            "version": "1.231.0",
            "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1",
        },
        "environment": {
            "python_version": "3.12",
            "platform": "test",
            "package_versions": {"nautilus-trader": "1.231.0"},
        },
        "dataset_id": "a" * 64,
        "data_sha256": "b" * 64,
        "spec_id": "c" * 64,
        "execution_status": "completed",
        "completeness": {
            "input_records": 1,
            "processed_records": 1,
            "open_orders": [],
            "pending_commands": [],
            "stop_reason": "input_exhausted",
        },
        "input_trace": [trace()],
        "decision_trace": [],
        "order_trace": [],
        "fill_trace": [],
        "account_trace": [],
    }


def test_spec_identity_and_nested_document_views_are_immutable() -> None:
    spec = build_replay_spec(encoded(spec_document()))
    assert load_replay_spec(spec.canonical_bytes) == spec
    assert cast("dict[str, object]", spec.document["instrument"])["price_increment"] == "1"
    altered = spec.document
    cast("dict[str, object]", altered["strategy"])["kind"] = "arbitrary_python"
    assert cast("dict[str, object]", spec.document["strategy"])["kind"] == "single_limit_buy_v1"
    with pytest.raises(FrozenInstanceError):
        spec.spec_id = "0" * 64  # type: ignore[misc]
    with pytest.raises(ReplayValidationError):
        replace(spec, spec_id="0" * 64)
    with pytest.raises(ReplayValidationError):
        load_replay_spec(json.dumps(spec.document, indent=2).encode())


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "schema_version", True),
        (None, "clock_policy_id", "verified_utc"),
        ("instrument", "base_currency", "BTC"),
        ("instrument", "quote_currency", "USDT"),
        ("instrument", "price_increment", "0"),
        ("instrument", "size_increment", "-1"),
        ("instrument", "price_increment", "0.000000001"),
        ("instrument", "size_increment", "1e-3"),
        ("account", "starting_cash", "1.001"),
        ("account", "starting_cash", "0"),
        ("fees", "maker_rate", "-0.01"),
        ("fees", "taker_rate", "1.01"),
        ("execution", "insert_latency_ns", True),
        ("execution", "cancel_latency_ns", -1),
        ("execution", "insert_latency_ns", 60_000_000_001),
        ("strategy", "kind", "user_python"),
        ("strategy", "submit_capture_seq", 0),
        ("strategy", "limit_price_ticks", False),
        ("strategy", "quantity_lots", 0),
        ("strategy", "cancel_after_first_fill", 0),
        (None, "seed", -1),
        (None, "seed", 1 << 63),
    ],
)
def test_unsupported_spec_values_fail_before_native_work(
    section: str | None, field: str, value: object
) -> None:
    document = spec_document()
    target = document if section is None else cast("dict[str, object]", document[section])
    target[field] = value
    with pytest.raises(ReplayValidationError):
        build_replay_spec(encoded(document))


@pytest.mark.parametrize(
    "raw", [b"", b"[]", b"\xff", b'{"x":NaN}', b'{"x":1.0}', b'{"x":1,"x":2}', b" " * 65_537]
)
def test_spec_parser_rejects_malformed_or_over_budget_bytes(raw: bytes) -> None:
    with pytest.raises(ReplayValidationError):
        build_replay_spec(raw)


def test_unknown_fields_cannot_request_other_account_modes_or_python_execution() -> None:
    document = spec_document()
    cast("dict[str, object]", document["account"])["account_type"] = "CASH"
    with pytest.raises(ReplayValidationError, match="fields"):
        build_replay_spec(encoded(document))
    document = spec_document()
    document["strategy_source"] = "import os"
    with pytest.raises(ReplayValidationError, match="fields"):
        build_replay_spec(encoded(document))
    with pytest.raises(ReplayValidationError, match="ReplaySpec"):
        ReplayInput("a" * 64, b"{}\n", cast("object", object()))  # type: ignore[arg-type]


def test_frozen_research_declarations_never_become_executable_replay_specs() -> None:
    request = {
        "schema_version": 1,
        "claim": {
            "title": "Unapproved claim",
            "hypothesis": "A declared result",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "0",
            "unit": "USD",
        },
        "strategy_name": "unapproved_source",
        "parameters": {},
        "configuration": {
            "fee_model_id": "unbound",
            "execution_model_id": "unbound",
            "clock_policy_id": "capture_order_unbound_v1",
        },
        "budget": {"max_scenarios": 1, "max_wall_seconds": 1, "max_events": 1},
        "seed": 0,
    }
    frozen = build_frozen_protocol(
        encoded(request),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
        strategy_sha256="c" * 64,
    )
    assert frozen.document["execution_ready"] is False
    with pytest.raises(ReplayValidationError):
        build_replay_spec(frozen.canonical_bytes)
    with pytest.raises(ReplayValidationError, match="ReplaySpec"):
        ReplayInput("a" * 64, b"{}\n", cast("ReplaySpec", frozen))


def test_preflight_retains_same_time_capture_order_and_true_immutable_events() -> None:
    request = replay_input()
    prepared = preflight_replay(request)
    assert [event.capture_seq for event in prepared.events] == [1, 2]
    assert [event.receive_time_ns for event in prepared.events] == [100, 100]
    assert prepared.events[0].bids == ((100, 5),)
    assert prepared.stream == ("synthetic", "EUR-USD", "qualification")
    source_ref = prepared.events[0].source_ref
    source_ref["capture_seq"] = 999
    assert prepared.events[0].source_ref == reference()
    with pytest.raises(ReplayValidationError):
        replace(prepared, stream=(cast("str", {}), "EUR-USD", "qualification"))
    with pytest.raises(ReplayValidationError):
        replace(prepared.events[0], bids=cast("tuple[tuple[int, int], ...]", [[100, 5]]))
    with pytest.raises(FrozenInstanceError):
        request.dataset_id = "0" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_clock",
        "clock_backwards",
        "event_after_receive",
        "other_asset",
        "empty_book",
        "crossed_book",
        "absent_delete",
        "empty_delta",
        "resnapshot",
        "duplicate",
        "gap",
        "missing_trigger",
    ],
)
def test_preflight_refuses_unsupported_market_or_clock_paths(mutation: str) -> None:
    records = [snapshot(), delta()]
    spec = spec_document()
    if mutation == "unknown_clock":
        records[0]["receive_time_ns"] = None
    elif mutation == "clock_backwards":
        records[1]["receive_time_ns"] = 99
    elif mutation == "event_after_receive":
        records[0]["event_time_ns"] = 101
    elif mutation == "other_asset":
        for record in records:
            record["instrument"] = "BTC-USDT"
    elif mutation == "empty_book":
        records[1]["bids"] = [[100, 0]]
    elif mutation == "crossed_book":
        records[1]["asks"] = [[100, 1]]
    elif mutation == "absent_delete":
        records[1]["bids"] = [[99, 0]]
    elif mutation == "empty_delta":
        records[1]["bids"] = []
    elif mutation == "resnapshot":
        records[1] = {**snapshot(), "capture_seq": 2, "last_sequence": 11}
    elif mutation == "duplicate":
        records.insert(1, snapshot())
    elif mutation == "gap":
        records[1]["first_sequence"] = records[1]["last_sequence"] = 12
    else:
        cast("dict[str, object]", spec["strategy"])["submit_capture_seq"] = 99
    with pytest.raises(ReplayValidationError):
        preflight_replay(replay_input(records, spec))


def test_book_updates_are_atomic_across_both_sides() -> None:
    change = {**delta(), "bids": [[103, 2]], "asks": [[102, 0], [104, 3]]}
    assert len(preflight_replay(replay_input([snapshot(), change])).events) == 2


def test_cumulative_book_depth_and_record_quotas_are_enforced() -> None:
    initial = {
        **snapshot(),
        "bids": [[price, 1] for price in range(1, 1_001)],
        "asks": [[2_000, 1]],
    }
    with pytest.raises(ReplayValidationError, match="1000"):
        preflight_replay(replay_input([initial, {**delta(), "bids": [[1_001, 1]]}]))
    one = normalize_events(encoded(snapshot()) + b"\n").normalized_bytes
    with pytest.raises(ReplayValidationError):
        preflight_replay(
            ReplayInput("a" * 64, one * 10_001, build_replay_spec(encoded(spec_document())))
        )
    with pytest.raises(ReplayValidationError):
        ReplayInput(
            "a" * 64, b"x" * (8 * 1024 * 1024 + 1), build_replay_spec(encoded(spec_document()))
        )


def test_noncanonical_input_and_multiple_streams_do_not_reach_native_execution() -> None:
    spec = build_replay_spec(encoded(spec_document()))
    with pytest.raises(ReplayValidationError, match="canonical"):
        preflight_replay(ReplayInput("a" * 64, json.dumps(snapshot()).encode(), spec))
    other = {**snapshot(), "session": "other"}
    with pytest.raises(ReplayValidationError, match="one source"):
        preflight_replay(replay_input([snapshot(), other]))


def test_decimal_context_cannot_change_preflight_mapping_or_overflow_rejection() -> None:
    expected = preflight_replay(replay_input())
    oversized = spec_document()
    cast("dict[str, object]", oversized["strategy"])["quantity_lots"] = 100_000_000
    for rounding in (ROUND_DOWN, ROUND_UP):
        with localcontext() as context:
            context.prec = 2
            context.rounding = rounding
            assert preflight_replay(replay_input()) == expected
            with pytest.raises(ReplayValidationError, match="notional"):
                preflight_replay(replay_input(spec=oversized))


def test_native_latency_horizon_cannot_overflow_the_timestamp_contract() -> None:
    near_limit = {**snapshot(), "event_time_ns": (1 << 63) - 2, "receive_time_ns": (1 << 63) - 1}
    spec = spec_document()
    cast("dict[str, object]", spec["execution"])["insert_latency_ns"] = 1
    with pytest.raises(ReplayValidationError, match="latency horizon"):
        preflight_replay(replay_input([near_limit], spec))


def test_results_have_detached_views_and_strict_result_markers() -> None:
    result = build_replay_result(result_document())
    assert load_replay_result(result.canonical_bytes) == result
    changed = result.document
    cast("dict[str, object]", changed["engine"])["version"] = "different"
    assert cast("dict[str, object]", result.document["engine"])["version"] == "1.231.0"
    with pytest.raises(ReplayValidationError):
        load_replay_result(json.dumps(result.document, indent=2).encode())
    with pytest.raises(ReplayValidationError):
        load_replay_result(b" " * (16 * 1024 * 1024 + 1))
    bad = result_document()
    bad["research_findings"] = []
    with pytest.raises(ReplayValidationError):
        build_replay_result(bad)


def pending_command() -> dict[str, object]:
    return {
        "command_id": "cancel-1",
        "order_id": "order-1",
        "command_type": "cancel",
        "decision_ref": "decision-1",
        "source_ref": reference(),
    }


def test_native_order_terminal_does_not_resolve_a_pending_cancel() -> None:
    document = result_document()
    document["execution_status"] = "incomplete"
    completeness = cast("dict[str, object]", document["completeness"])
    completeness["pending_commands"] = [pending_command()]
    completeness["stop_reason"] = "pending_commands_at_data_end"
    document["order_trace"] = [
        {**trace(), "kind": "OrderFilled", "fields": {"order_id": "order-1", "status": "FILLED"}}
    ]
    assert build_replay_result(document).document["execution_status"] == "incomplete"
    document["execution_status"] = "completed"
    with pytest.raises(ReplayValidationError, match="completeness"):
        build_replay_result(document)


def test_open_orders_require_incomplete_and_pending_commands_take_precedence() -> None:
    document = result_document()
    completeness = cast("dict[str, object]", document["completeness"])
    completeness["open_orders"] = [{"order_id": "order-1", "status": "ACCEPTED"}]
    completeness["stop_reason"] = "input_exhausted_with_open_orders"
    document["execution_status"] = "incomplete"
    assert build_replay_result(document).document["execution_status"] == "incomplete"
    completeness["pending_commands"] = [pending_command()]
    with pytest.raises(ReplayValidationError):
        build_replay_result(document)


@pytest.mark.parametrize(
    "channel", ["decision_trace", "order_trace", "fill_trace", "account_trace", "pending_commands"]
)
def test_unprocessed_source_references_are_rejected(channel: str) -> None:
    document = result_document()
    if channel == "pending_commands":
        document["execution_status"] = "incomplete"
        completeness = cast("dict[str, object]", document["completeness"])
        completeness["pending_commands"] = [{**pending_command(), "source_ref": reference(2, 2)}]
        completeness["stop_reason"] = "pending_commands_at_data_end"
    else:
        document[channel] = [trace(source_ref=reference(2, 2))]
    with pytest.raises(ReplayValidationError, match="unprocessed input"):
        build_replay_result(document)


@pytest.mark.parametrize(
    "mutation", ["line", "capture_order", "ordinal", "float", "schema_bool", "processed_bool"]
)
def test_trace_provenance_order_types_and_completeness_are_strict(mutation: str) -> None:
    document = result_document()
    if mutation == "line":
        document["input_trace"] = [trace(source_ref=reference(2, 1))]
    elif mutation == "capture_order":
        completeness = cast("dict[str, object]", document["completeness"])
        completeness["input_records"] = completeness["processed_records"] = 2
        document["input_trace"] = [
            trace(source_ref=reference(1, 2)),
            trace(source_ref=reference(2, 1), ordinal=1),
        ]
    elif mutation == "ordinal":
        document["input_trace"] = [trace(ordinal=1)]
    elif mutation == "float":
        document["account_trace"] = [{**trace(), "fields": {"cash": 1.0}}]
    elif mutation == "schema_bool":
        document["schema_version"] = True
    else:
        cast("dict[str, object]", document["completeness"])["processed_records"] = True
    with pytest.raises(ReplayValidationError):
        build_replay_result(document)


def test_failed_partial_results_reference_only_the_processed_prefix() -> None:
    document = deepcopy(result_document())
    document["execution_status"] = "failed"
    completeness = cast("dict[str, object]", document["completeness"])
    completeness["input_records"] = 2
    completeness["stop_reason"] = "engine_error"
    assert build_replay_result(document).document["execution_status"] == "failed"
