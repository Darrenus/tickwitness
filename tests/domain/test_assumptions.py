"""Pure declaration/constraint tests; no derived tape, native engine, or storage."""

from __future__ import annotations

import builtins
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from tickwitness.domain.assumptions import (
    AssumptionValidationError,
    ValidatedScenario,
    build_assumption_spec,
    build_scenario_spec,
    load_assumption_spec,
    load_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    build_executable_protocol,
)

INT64_MAX = (1 << 63) - 1


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def assumption_request() -> dict[str, Any]:
    return {
        "kind": "assumption_request_v1",
        "schema_version": 1,
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "transform": {"semantic_id": "replay_receive_suffix_shift_v1", "from_capture_seq": 2},
        "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
        "parameter_basis": {
            "kind": "researcher_defined",
            "calibration_status": "uncalibrated",
            "calibration_evidence_refs": [],
        },
    }


def scenario_request(value: int = 20_000_000) -> dict[str, object]:
    return {
        "kind": "scenario_request_v1",
        "schema_version": 1,
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "additional_delay": {"value": value, "unit": "ns"},
    }


def events() -> list[dict[str, Any]]:
    common = {
        "schema_version": 1,
        "source": "synthetic",
        "instrument": "EUR-USD",
        "session": "s05-constraint-fixture",
    }
    return [
        {
            **common,
            "type": "snapshot",
            "capture_seq": 1,
            "event_time_ns": 100,
            "receive_time_ns": 110,
            "last_sequence": 10,
            "bids": [[100, 1], [99, 10]],
            "asks": [[103, 10], [104, 10]],
        },
        {
            **common,
            "type": "delta",
            "capture_seq": 2,
            "event_time_ns": 200,
            "receive_time_ns": 210,
            "first_sequence": 11,
            "last_sequence": 11,
            "bids": [[100, 4]],
            "asks": [],
        },
    ]


def context(
    *,
    records: list[dict[str, Any]] | None = None,
    max_events: int = 10,
    insert: int = 0,
    cancel: int = 0,
) -> tuple[ExecutableProtocol, ReplayInput]:
    replay_spec = build_replay_spec(
        encoded(
            {
                "schema_version": 1,
                "clock_policy_id": "receive_order_v1",
                "instrument": {
                    "base_currency": "EUR",
                    "quote_currency": "USD",
                    "price_increment": "1",
                    "size_increment": "1",
                },
                "account": {"starting_cash": "10000"},
                "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
                "execution": {"insert_latency_ns": insert, "cancel_latency_ns": cancel},
                "strategy": {
                    "kind": "single_limit_buy_v1",
                    "submit_capture_seq": 1,
                    "limit_price_ticks": 100,
                    "quantity_lots": 2,
                    "cancel_after_first_fill": False,
                },
                "seed": 7,
            }
        )
    )
    request = {
        "schema_version": 2,
        "claim": {
            "title": "Original declaration-only fixture",
            "hypothesis": "The baseline mark exceeds zero.",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "0",
            "unit": "USD",
        },
        "replay_spec": replay_spec.document,
        "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": max_events},
    }
    protocol = build_executable_protocol(
        encoded(request), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    raw = (
        b"\n".join(encoded(record) for record in (events() if records is None else records)) + b"\n"
    )
    return protocol, ReplayInput("a" * 64, normalize_events(raw).normalized_bytes, replay_spec)


def build_pair(*, delay: int = 20_000_000):
    protocol, replay_input = context()
    assumptions = build_assumption_spec(
        encoded(assumption_request()), protocol=protocol, replay_input=replay_input
    )
    scenario = build_scenario_spec(encoded(scenario_request(delay)), assumptions=assumptions)
    return protocol, replay_input, assumptions, scenario


def test_exact_specs_bind_actual_inputs_and_validation_never_approves_execution() -> None:
    protocol, replay_input, assumptions, scenario = build_pair()
    request = assumption_request()
    assert assumptions.document == {
        **request,
        "kind": "assumption_spec_v1",
        "bindings": {
            "protocol_id": protocol.protocol_id,
            "development_dataset_id": replay_input.dataset_id,
            "normalized_sha256": hashlib.sha256(replay_input.normalized_bytes).hexdigest(),
            "replay_spec_id": replay_input.spec.spec_id,
        },
    }
    assert scenario.document == {
        **scenario_request(),
        "kind": "scenario_spec_v1",
        "assumption_id": assumptions.assumption_id,
    }
    validated = validate_scenario_spec(
        scenario, assumptions, protocol=protocol, replay_input=replay_input
    )
    assert validated.document == {
        "kind": "validated_scenario_constraints_v1",
        "schema_version": 1,
        "scenario_id": scenario.scenario_id,
        "assumption_id": assumptions.assumption_id,
        "bindings": assumptions.document["bindings"],
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "transform": request["transform"],
        "additional_delay": scenario_request()["additional_delay"],
        "source_bindings_verified": True,
        "input_constraints_verified": True,
        "calibration_status": "uncalibrated",
        "execution_approved": False,
    }
    assert validated.execution_approved is False
    assert assumptions.assumption_id == hashlib.sha256(assumptions.canonical_bytes).hexdigest()
    assert scenario.scenario_id == hashlib.sha256(scenario.canonical_bytes).hexdigest()
    assert load_assumption_spec(assumptions.canonical_bytes) == assumptions
    assert load_scenario_spec(scenario.canonical_bytes) == scenario


def test_equivalent_request_json_has_same_identity_but_changed_constraints_make_new_child_ids() -> (
    None
):
    protocol, replay_input, assumptions, scenario = build_pair()
    request = assumption_request()
    reordered = json.dumps(dict(reversed(list(request.items()))), indent=2).encode()
    assert (
        build_assumption_spec(reordered, protocol=protocol, replay_input=replay_input)
        == assumptions
    )
    request["additional_delay"]["maximum"] += 1
    changed = build_assumption_spec(encoded(request), protocol=protocol, replay_input=replay_input)
    assert changed.assumption_id != assumptions.assumption_id
    assert (
        build_scenario_spec(encoded(scenario_request()), assumptions=changed).scenario_id
        != scenario.scenario_id
    )


def test_specs_and_validated_views_are_detached_and_frozen() -> None:
    protocol, replay_input, assumptions, scenario = build_pair()
    validated = validate_scenario_spec(
        scenario, assumptions, protocol=protocol, replay_input=replay_input
    )
    view = assumptions.document
    view["bindings"]["protocol_id"] = "f" * 64
    validation_view = validated.document
    validation_view["execution_approved"] = True
    validation_view["transform"]["from_capture_seq"] = 999
    assert validated.document["execution_approved"] is False
    assert validated.document["transform"]["from_capture_seq"] == 2
    assert assumptions.document["bindings"]["protocol_id"] == protocol.protocol_id
    with pytest.raises(FrozenInstanceError):
        assumptions.assumption_id = "f" * 64
    with pytest.raises((ValueError, TypeError), match="execution_approved"):
        replace(validated, execution_approved=True)
    assert validated.execution_approved is False
    with pytest.raises(AssumptionValidationError, match="identity mismatch"):
        replace(assumptions, assumption_id="f" * 64)
    with pytest.raises(AssumptionValidationError, match="identity mismatch"):
        replace(scenario, scenario_id="f" * 64)


@pytest.mark.parametrize(
    "path,value",
    [
        (("kind",), "assumption_spec_v1"),
        (("schema_version",), True),
        (("scenario_kind",), "OBSERVATION_COMPATIBLE"),
        (("transform", "semantic_id"), "python_transform_v1"),
        (("transform", "from_capture_seq"), True),
        (("transform", "from_capture_seq"), 0),
        (("additional_delay", "minimum"), -1),
        (("additional_delay", "minimum"), 20_000_001),
        (("additional_delay", "maximum"), -1),
        (("additional_delay", "maximum"), 60_000_000_001),
        (("additional_delay", "maximum"), "20000000"),
        (("additional_delay", "maximum"), True),
        (("additional_delay", "unit"), "ms"),
        (("parameter_basis", "kind"), "physical_boundary"),
        (("parameter_basis", "calibration_status"), "calibrated"),
        (("parameter_basis", "calibration_evidence_refs"), ["f" * 64]),
    ],
)
def test_invalid_assumption_fields_are_rejected(path: tuple[str, ...], value: object) -> None:
    protocol, replay_input = context()
    request = assumption_request()
    target = request
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(AssumptionValidationError):
        build_assumption_spec(encoded(request), protocol=protocol, replay_input=replay_input)


@pytest.mark.parametrize(
    "extra", ["bindings", "assumption_id", "execution_approved", "source_path", "script"]
)
def test_requests_cannot_inject_bindings_ids_execution_or_code(extra: str) -> None:
    protocol, replay_input = context()
    request = assumption_request()
    request[extra] = {}
    with pytest.raises(AssumptionValidationError, match="unknown fields"):
        build_assumption_spec(encoded(request), protocol=protocol, replay_input=replay_input)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b'{"kind":"x","kind":"x"}',
        b'{"value":1.0}',
        b'{"value":1e0}',
        b'{"value":NaN}',
        b"\xff",
        b" " * 65_537,
    ],
)
def test_strict_bounded_json_rejects_float_duplicate_unicode_and_oversize(raw: bytes) -> None:
    protocol, replay_input = context()
    with pytest.raises(AssumptionValidationError):
        build_assumption_spec(raw, protocol=protocol, replay_input=replay_input)


@pytest.mark.parametrize(
    "change", ["missing-unit", "wrong-kind", "boolean", "negative", "outside", "injected-id"]
)
def test_invalid_scenario_requests_are_rejected(change: str) -> None:
    _, _, assumptions, _ = build_pair()
    request = scenario_request()
    if change == "missing-unit":
        del request["additional_delay"]["unit"]
    elif change == "wrong-kind":
        request["scenario_kind"] = "OBSERVATION_COMPATIBLE"
    elif change == "boolean":
        request["additional_delay"]["value"] = True
    elif change == "negative":
        request["additional_delay"]["value"] = -1
    elif change == "outside":
        request["additional_delay"]["value"] = 20_000_001
    else:
        request["assumption_id"] = assumptions.assumption_id
    with pytest.raises(AssumptionValidationError):
        build_scenario_spec(encoded(request), assumptions=assumptions)


def test_zero_delay_is_only_a_valid_intent_and_does_not_transform_or_execute_input() -> None:
    protocol, replay_input, assumptions, scenario = build_pair(delay=0)
    source_bytes, spec_bytes, protocol_bytes = (
        replay_input.normalized_bytes,
        replay_input.spec.canonical_bytes,
        protocol.canonical_bytes,
    )
    validated = validate_scenario_spec(
        scenario, assumptions, protocol=protocol, replay_input=replay_input
    )
    assert validated.document["additional_delay"] == {"value": 0, "unit": "ns"}
    assert validated.document["execution_approved"] is False
    assert replay_input.normalized_bytes == source_bytes
    assert replay_input.spec.canonical_bytes == spec_bytes
    assert protocol.canonical_bytes == protocol_bytes


@pytest.mark.parametrize("delay", [0, 20_000_000])
def test_even_zero_delay_requires_an_existing_capture_anchor(delay: int) -> None:
    protocol, replay_input = context()
    request = assumption_request()
    request["transform"]["from_capture_seq"] = 3
    with pytest.raises(AssumptionValidationError, match="actual development input"):
        build_assumption_spec(encoded(request), protocol=protocol, replay_input=replay_input)
    assumptions = build_assumption_spec(
        encoded(assumption_request()), protocol=protocol, replay_input=replay_input
    )
    document = assumptions.document
    document["transform"]["from_capture_seq"] = 3
    loaded = load_assumption_spec(encoded(document))
    scenario = build_scenario_spec(encoded(scenario_request(delay)), assumptions=loaded)
    with pytest.raises(AssumptionValidationError, match="actual development input"):
        validate_scenario_spec(scenario, loaded, protocol=protocol, replay_input=replay_input)


@pytest.mark.parametrize(
    "field", ["protocol_id", "development_dataset_id", "normalized_sha256", "replay_spec_id"]
)
def test_loader_does_not_certify_forged_external_bindings(field: str) -> None:
    protocol, replay_input, assumptions, scenario = build_pair()
    document = assumptions.document
    document["bindings"][field] = "f" * 64
    loaded = load_assumption_spec(encoded(document))
    child = build_scenario_spec(encoded(scenario_request()), assumptions=loaded)
    with pytest.raises(AssumptionValidationError, match="actual source bindings"):
        validate_scenario_spec(child, loaded, protocol=protocol, replay_input=replay_input)
    assert scenario.document["assumption_id"] == assumptions.assumption_id


def test_confirmation_input_and_wrong_replay_spec_are_rejected() -> None:
    protocol, replay_input = context()
    confirmation = ReplayInput("b" * 64, replay_input.normalized_bytes, replay_input.spec)
    with pytest.raises(AssumptionValidationError, match="never confirmation"):
        build_assumption_spec(
            encoded(assumption_request()), protocol=protocol, replay_input=confirmation
        )
    changed = replay_input.spec.document
    changed["seed"] = 8
    switched = ReplayInput(
        replay_input.dataset_id, replay_input.normalized_bytes, build_replay_spec(encoded(changed))
    )
    with pytest.raises(AssumptionValidationError, match="replay spec binding"):
        build_assumption_spec(
            encoded(assumption_request()), protocol=protocol, replay_input=switched
        )


@pytest.mark.parametrize(
    "problem",
    ["unknown_receive", "nonmonotone", "event_after_receive", "gap", "duplicate", "crossed"],
)
def test_complete_preflight_remains_required_and_unknown_receive_is_never_filled(
    problem: str,
) -> None:
    records = events()
    if problem == "unknown_receive":
        records[1]["receive_time_ns"] = None
    elif problem == "nonmonotone":
        records[1].update(event_time_ns=90, receive_time_ns=100)
    elif problem == "event_after_receive":
        records[1]["event_time_ns"] = 211
    elif problem == "gap":
        records[1].update(first_sequence=12, last_sequence=12)
    elif problem == "duplicate":
        records.insert(1, records[0].copy())
    else:
        records[1]["bids"] = [[103, 4]]
    protocol, replay_input = context(records=records)
    original = replay_input.normalized_bytes
    with pytest.raises(AssumptionValidationError, match="preflight"):
        build_assumption_spec(
            encoded(assumption_request()), protocol=protocol, replay_input=replay_input
        )
    assert replay_input.normalized_bytes == original
    if problem == "unknown_receive":
        assert json.loads(original.splitlines()[-1])["receive_time_ns"] is None


def test_frozen_event_budget_is_part_of_input_constraints() -> None:
    protocol, replay_input = context(max_events=1)
    with pytest.raises(AssumptionValidationError, match="frozen event budget"):
        build_assumption_spec(
            encoded(assumption_request()), protocol=protocol, replay_input=replay_input
        )


def test_declared_maximum_and_candidate_horizon_reject_overflow_without_clamping() -> None:
    records = events()
    for index, record in enumerate(records):
        receive = INT64_MAX - 200 + index * 100
        record.update(event_time_ns=receive - 1, receive_time_ns=receive)
    protocol, replay_input = context(records=records, insert=40, cancel=40)
    request = assumption_request()
    request["additional_delay"].update(minimum=0, maximum=20)
    assumptions = build_assumption_spec(
        encoded(request), protocol=protocol, replay_input=replay_input
    )
    candidate = build_scenario_spec(encoded(scenario_request(20)), assumptions=assumptions)
    assert (
        validate_scenario_spec(
            candidate, assumptions, protocol=protocol, replay_input=replay_input
        ).execution_approved
        is False
    )
    request["additional_delay"]["maximum"] = 21
    with pytest.raises(AssumptionValidationError, match="horizon exceeds int64"):
        build_assumption_spec(encoded(request), protocol=protocol, replay_input=replay_input)
    loaded = load_assumption_spec(
        encoded({**assumptions.document, "additional_delay": request["additional_delay"]})
    )
    zero = build_scenario_spec(encoded(scenario_request(0)), assumptions=loaded)
    with pytest.raises(AssumptionValidationError, match="horizon exceeds int64"):
        validate_scenario_spec(zero, loaded, protocol=protocol, replay_input=replay_input)


def test_loaders_require_canonical_encoding_and_scenario_context_cannot_switch_assumptions() -> (
    None
):
    protocol, replay_input, assumptions, scenario = build_pair()
    for loader, raw in (
        (load_assumption_spec, assumptions.canonical_bytes),
        (load_scenario_spec, scenario.canonical_bytes),
    ):
        with pytest.raises(AssumptionValidationError, match="canonical"):
            loader(raw + b"\n")
    document = scenario.document
    document["assumption_id"] = "f" * 64
    loaded = load_scenario_spec(encoded(document))
    with pytest.raises(AssumptionValidationError, match="assumption identity mismatch"):
        validate_scenario_spec(loaded, assumptions, protocol=protocol, replay_input=replay_input)
    with pytest.raises(AssumptionValidationError, match="assumption identity mismatch"):
        ValidatedScenario(loaded, assumptions, protocol, replay_input)


def test_domain_validation_does_not_import_native_or_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "sqlite3" or name.startswith(("nautilus_trader", "tickwitness.infrastructure")):
            raise AssertionError("Declaration validation must stay native/storage free")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    protocol, replay_input, assumptions, scenario = build_pair()
    assert (
        validate_scenario_spec(
            scenario, assumptions, protocol=protocol, replay_input=replay_input
        ).execution_approved
        is False
    )
