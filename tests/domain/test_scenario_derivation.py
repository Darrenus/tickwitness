"""A derived clock view preserves the original tape and cannot borrow its identity."""

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
from tickwitness.domain.assumptions.derivation import (
    CLOCK_PROFILE_ID,
    DerivedReplayView,
    derive_replay_view,
    load_derived_replay_view,
)
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def context(*, delay: int = 20_000_000, anchor: int = 11) -> ValidatedScenario:
    common = {
        "schema_version": 1,
        "source": "synthetic",
        "instrument": "EUR-USD",
        "session": "derived-clock-fixture",
    }
    records = [
        {
            **common,
            "type": "snapshot",
            "capture_seq": 10,
            "event_time_ns": 100,
            "receive_time_ns": 110,
            "last_sequence": 100,
            "bids": [[100, 5], [99, 10]],
            "asks": [[103, 10]],
        },
        {
            **common,
            "type": "delta",
            "capture_seq": 11,
            "event_time_ns": 200,
            "receive_time_ns": 210,
            "first_sequence": 101,
            "last_sequence": 101,
            "bids": [[100, 4]],
            "asks": [],
        },
        {
            **common,
            "type": "trade",
            "capture_seq": 12,
            "event_time_ns": 200,
            "receive_time_ns": 210,
            "trade_id": 'clock-时钟-"receive_time_ns":210,',
            "price_ticks": 100,
            "quantity_lots": 1,
            "aggressor_side": "sell",
        },
        {
            **common,
            "type": "delta",
            "capture_seq": 13,
            "event_time_ns": 400,
            "receive_time_ns": 410,
            "first_sequence": 102,
            "last_sequence": 102,
            "bids": [[99, 12]],
            "asks": [],
        },
    ]
    spec = build_replay_spec(
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
                "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
                "strategy": {
                    "kind": "single_limit_buy_v1",
                    "submit_capture_seq": 10,
                    "limit_price_ticks": 100,
                    "quantity_lots": 2,
                    "cancel_after_first_fill": False,
                },
                "seed": 7,
            }
        )
    )
    protocol = build_executable_protocol(
        encoded(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Original derived-view fixture",
                    "hypothesis": "The baseline mark exceeds zero.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "0",
                    "unit": "USD",
                },
                "replay_spec": spec.document,
                "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 10},
            }
        ),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
    )
    raw = b"\n".join(encoded(record) for record in records) + b"\n"
    replay_input = ReplayInput("a" * 64, normalize_events(raw).normalized_bytes, spec)
    assumptions = build_assumption_spec(
        encoded(
            {
                "kind": "assumption_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "transform": {
                    "semantic_id": "replay_receive_suffix_shift_v1",
                    "from_capture_seq": anchor,
                },
                "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
                "parameter_basis": {
                    "kind": "researcher_defined",
                    "calibration_status": "uncalibrated",
                    "calibration_evidence_refs": [],
                },
            }
        ),
        protocol=protocol,
        replay_input=replay_input,
    )
    scenario = build_scenario_spec(
        encoded(
            {
                "kind": "scenario_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "additional_delay": {"value": delay, "unit": "ns"},
            }
        ),
        assumptions=assumptions,
    )
    return validate_scenario_spec(
        scenario, assumptions, protocol=protocol, replay_input=replay_input
    )


def forged_validation(validated: ValidatedScenario, **changes: Any) -> ValidatedScenario:
    """Bypass the constructor to prove derivation does not trust a prior marker."""
    forged = object.__new__(ValidatedScenario)
    for name in ("scenario", "assumptions", "protocol", "replay_input"):
        object.__setattr__(forged, name, changes.get(name, getattr(validated, name)))
    return forged


@pytest.mark.parametrize("anchor", [10, 11, 13])
def test_only_suffix_receive_tokens_change_without_sorting_or_field_reencoding(anchor: int) -> None:
    validated = context(anchor=anchor)
    source = validated.replay_input
    source_bytes, spec_bytes, protocol_bytes = (
        source.normalized_bytes,
        source.spec.canonical_bytes,
        validated.protocol.canonical_bytes,
    )
    view = derive_replay_view(validated)
    original_lines = source_bytes.splitlines(keepends=True)
    derived_lines = view.replay_input.normalized_bytes.splitlines(keepends=True)
    assert len(original_lines) == len(derived_lines) == 4
    for original, derived in zip(original_lines, derived_lines, strict=True):
        before, after = json.loads(original), json.loads(derived)
        expected = original
        if before["capture_seq"] >= anchor:
            receive = before["receive_time_ns"]
            expected = original.replace(
                f'"receive_time_ns":{receive},'.encode(),
                f'"receive_time_ns":{receive + 20_000_000},'.encode(),
                1,
            )
        assert derived == expected
        assert after.pop("receive_time_ns") == before.pop("receive_time_ns") + (
            20_000_000 if before["capture_seq"] >= anchor else 0
        )
        assert after == before
    source_events = preflight_replay(source).events
    derived_events = preflight_replay(view.replay_input).events
    assert [event.source_ref for event in derived_events] == [
        event.source_ref for event in source_events
    ]
    assert [event.capture_seq for event in derived_events] == [10, 11, 12, 13]
    assert source.normalized_bytes == source_bytes
    assert source.spec.canonical_bytes == spec_bytes
    assert validated.protocol.canonical_bytes == protocol_bytes


def test_canonical_view_identity_binds_source_declarations_and_actual_derived_bytes() -> None:
    validated = context()
    view = derive_replay_view(validated)
    assert view.document == {
        "kind": "derived_replay_view_v1",
        "schema_version": 1,
        "clock_profile_id": "coupled_receive_suffix_clock_v1",
        "identity_semantics": "derived_view_not_catalog_manifest_v1",
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "calibration_status": "uncalibrated",
        "source_bindings": validated.assumptions.document["bindings"],
        "assumption_id": validated.assumptions.assumption_id,
        "scenario_id": validated.scenario.scenario_id,
        "transform": validated.assumptions.document["transform"],
        "additional_delay": validated.scenario.document["additional_delay"],
        "derived": {
            "normalized_sha256": hashlib.sha256(view.replay_input.normalized_bytes).hexdigest(),
            "record_count": 4,
        },
        "execution_approved": False,
    }
    assert view.canonical_bytes == encoded(view.document)
    assert view.view_id == hashlib.sha256(view.canonical_bytes).hexdigest()
    assert view.replay_input.dataset_id == view.view_id
    assert view.view_id != validated.replay_input.dataset_id
    assert view.replay_input.spec == validated.replay_input.spec
    assert view.derived_input is view.replay_input
    assert view.document["clock_profile_id"] == CLOCK_PROFILE_ID
    assert load_derived_replay_view(view.canonical_bytes, validated=validated) == view
    assert derive_replay_view(validated) == view


def test_zero_shift_retains_bytes_but_has_independent_provenance_identity() -> None:
    validated = context(delay=0)
    zero = derive_replay_view(validated)
    assert zero.replay_input.normalized_bytes == validated.replay_input.normalized_bytes
    assert zero.view_id != validated.replay_input.dataset_id
    shifted = derive_replay_view(context())
    assert zero.view_id != shifted.view_id

    declaration = validated.assumptions.document
    declaration["additional_delay"]["maximum"] = 30_000_000
    assumptions = load_assumption_spec(encoded(declaration))
    scenario_document = validated.scenario.document
    scenario_document["assumption_id"] = assumptions.assumption_id
    scenario = load_scenario_spec(encoded(scenario_document))
    wider = derive_replay_view(
        validate_scenario_spec(
            scenario, assumptions, protocol=validated.protocol, replay_input=validated.replay_input
        )
    )
    assert wider.replay_input.normalized_bytes == zero.replay_input.normalized_bytes
    assert wider.view_id != zero.view_id


def test_view_is_frozen_detached_and_does_not_accept_supplied_derived_bytes() -> None:
    view = derive_replay_view(context())
    document = view.document
    document["source_bindings"]["development_dataset_id"] = "f" * 64
    document["derived"]["normalized_sha256"] = "f" * 64
    document["execution_approved"] = True
    assert view.document["source_bindings"]["development_dataset_id"] == "a" * 64
    assert view.document["execution_approved"] is False
    with pytest.raises(FrozenInstanceError):
        view.canonical_bytes = b"{}"
    with pytest.raises(FrozenInstanceError):
        view.replay_input = view.validated.replay_input
    with pytest.raises((TypeError, ValueError), match="canonical_bytes"):
        replace(view, canonical_bytes=b"{}")
    with pytest.raises(TypeError):
        DerivedReplayView(view.validated, canonical_bytes=b"{}")


@pytest.mark.parametrize(
    "change", ["source_identity", "source_bytes", "spec", "anchor", "candidate", "unknown_clock"]
)
def test_derivation_revalidates_complete_context_instead_of_trusting_prior_markers(
    change: str,
) -> None:
    validated = context()
    source = validated.replay_input
    changes: dict[str, Any] = {}
    if change == "source_identity":
        changes["replay_input"] = ReplayInput("b" * 64, source.normalized_bytes, source.spec)
    elif change == "source_bytes":
        changed = source.normalized_bytes.replace(b'"quantity_lots":1', b'"quantity_lots":2')
        changes["replay_input"] = ReplayInput(source.dataset_id, changed, source.spec)
    elif change == "spec":
        document = source.spec.document
        document["seed"] = 8
        changes["replay_input"] = ReplayInput(
            source.dataset_id, source.normalized_bytes, build_replay_spec(encoded(document))
        )
    elif change == "candidate":
        document = validated.scenario.document
        document["additional_delay"]["value"] = 20_000_001
        changes["scenario"] = load_scenario_spec(encoded(document))
    else:
        document = validated.assumptions.document
        if change == "anchor":
            document["transform"]["from_capture_seq"] = 21
        else:
            records = [json.loads(line) for line in source.normalized_bytes.splitlines()]
            records[1]["receive_time_ns"] = None
            changed = normalize_events(b"\n".join(encoded(row) for row in records) + b"\n")
            changes["replay_input"] = ReplayInput(
                source.dataset_id, changed.normalized_bytes, source.spec
            )
            document["bindings"]["normalized_sha256"] = hashlib.sha256(
                changed.normalized_bytes
            ).hexdigest()
        assumptions = load_assumption_spec(encoded(document))
        scenario_document = validated.scenario.document
        scenario_document["assumption_id"] = assumptions.assumption_id
        changes["assumptions"] = assumptions
        changes["scenario"] = load_scenario_spec(encoded(scenario_document))
    with pytest.raises(AssumptionValidationError):
        derive_replay_view(forged_validation(validated, **changes))


def test_tampered_frozen_identity_is_not_accepted_as_a_prevalidated_value() -> None:
    validated = context()
    assumptions = load_assumption_spec(validated.assumptions.canonical_bytes)
    object.__setattr__(assumptions, "assumption_id", "f" * 64)
    with pytest.raises(AssumptionValidationError, match="identity mismatch"):
        derive_replay_view(forged_validation(validated, assumptions=assumptions))


@pytest.mark.parametrize("problem", ["reordered", "overflow"])
def test_revalidated_source_is_never_sorted_or_clamped_even_for_zero_shift(problem: str) -> None:
    validated = context(delay=0)
    source = validated.replay_input
    records = [json.loads(line) for line in source.normalized_bytes.splitlines()]
    if problem == "reordered":
        records[1], records[2] = records[2], records[1]
    else:
        for index, record in enumerate(records):
            receive = (1 << 63) - 5 + index
            record.update(event_time_ns=receive - 1, receive_time_ns=receive)
    changed = normalize_events(b"\n".join(encoded(record) for record in records) + b"\n")
    replay_input = ReplayInput(source.dataset_id, changed.normalized_bytes, source.spec)
    declaration = validated.assumptions.document
    declaration["bindings"]["normalized_sha256"] = hashlib.sha256(
        changed.normalized_bytes
    ).hexdigest()
    assumptions = load_assumption_spec(encoded(declaration))
    scenario_document = validated.scenario.document
    scenario_document["assumption_id"] = assumptions.assumption_id
    scenario = load_scenario_spec(encoded(scenario_document))
    forged = forged_validation(
        validated, assumptions=assumptions, scenario=scenario, replay_input=replay_input
    )
    with pytest.raises(AssumptionValidationError):
        derive_replay_view(forged)
    assert replay_input.normalized_bytes == changed.normalized_bytes


@pytest.mark.parametrize("value", [None, {}, b"validated", True])
def test_derivation_requires_a_validated_scenario_value(value: object) -> None:
    with pytest.raises(AssumptionValidationError, match="ValidatedScenario"):
        derive_replay_view(value)


@pytest.mark.parametrize("change", ["hash", "source", "profile", "count", "extra", "newline"])
def test_loader_recomputes_rather_than_accepting_self_consistent_modified_json(change: str) -> None:
    validated = context()
    view = derive_replay_view(validated)
    document = view.document
    if change == "hash":
        document["derived"]["normalized_sha256"] = "f" * 64
    elif change == "source":
        document["source_bindings"]["development_dataset_id"] = "b" * 64
    elif change == "profile":
        document["clock_profile_id"] = "independent_feed_latency_v1"
    elif change == "count":
        document["derived"]["record_count"] = True
    elif change == "extra":
        document["execution_result"] = "completed"
    raw = view.canonical_bytes + b"\n" if change == "newline" else encoded(document)
    with pytest.raises(AssumptionValidationError, match="does not reproduce"):
        load_derived_replay_view(raw, validated=validated)


@pytest.mark.parametrize("raw", [b"", bytearray(b"{}"), b" " * 65_537])
def test_loader_rejects_mutable_empty_and_oversized_payloads_before_context(raw) -> None:
    with pytest.raises(AssumptionValidationError, match="immutable bytes"):
        load_derived_replay_view(raw, validated=None)


def test_derivation_stays_native_storage_and_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in {"sqlite3", "socket", "subprocess"} or name.startswith(
            ("nautilus_trader", "tickwitness.infrastructure", "tickwitness.application")
        ):
            raise AssertionError("Pure derivation cannot import an execution or IO boundary")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    validated = context()
    assert derive_replay_view(validated).document["execution_approved"] is False
