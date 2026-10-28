"""Pure legal-prefix plans bind more than a book image and never assert runtime state."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_assumptions import assumption_request, context, encoded, events, scenario_request

from tickwitness.domain.assumptions import (
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.reduction.contracts import (
    FLAGS,
    SCOPE,
    ReductionSource,
    ReductionValidationError,
    build_reduction_manifest,
    build_reduction_recipe,
    load_reduction_recipe,
    load_reduction_request,
    materialize_reduction,
    role_limit,
)


def source(*, insert=0, trade_quantity=1):
    records = events()
    common = {
        key: value
        for key, value in records[0].items()
        if key in ("schema_version", "source", "instrument", "session")
    }
    records.extend(
        [
            {
                **common,
                "type": "trade",
                "capture_seq": 3,
                "event_time_ns": 300,
                "receive_time_ns": 310,
                "trade_id": "prefix-trade",
                "price_ticks": 100,
                "quantity_lots": trade_quantity,
                "aggressor_side": "sell",
            },
            {
                **common,
                "type": "delta",
                "capture_seq": 4,
                "event_time_ns": 400,
                "receive_time_ns": 410,
                "first_sequence": 12,
                "last_sequence": 12,
                "bids": [[100, 8]],
                "asks": [],
            },
        ]
    )
    protocol, replay_input = context(records=records, insert=insert)
    assumptions = build_assumption_spec(
        encoded(assumption_request()), protocol=protocol, replay_input=replay_input
    )
    scenario = build_scenario_spec(encoded(scenario_request()), assumptions=assumptions)
    validation = validate_scenario_spec(
        scenario, assumptions, protocol=protocol, replay_input=replay_input
    )
    return ReductionSource("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64, 3, validation)


def request(*, focus=1, through=4, delay=20_000_000):
    return canonical(
        {
            "kind": "reduction_request_v1",
            "schema_version": 1,
            "witness_ordinal": 3,
            "focus_from_capture_seq": focus,
            "through_capture_seq": through,
            "additional_delay_ns": delay,
        }
    )


def test_identity_input_and_detached_plans_never_alias_runtime_state():
    actual = source()
    recipe = build_reduction_recipe(request(), source=actual)
    prepared = materialize_reduction(recipe, source=actual)
    original = derive_replay_view(actual.validation)
    assert prepared.replay_input.normalized_bytes == original.replay_input.normalized_bytes
    assert prepared.replay_input.spec == actual.validation.replay_input.spec
    assert prepared.replay_input.dataset_id == prepared.document["prefix_context_id"]
    assert prepared.replay_input.dataset_id not in (
        actual.validation.replay_input.dataset_id,
        original.view_id,
    )
    assert prepared.document["retained"]["warmup_event_count"] == 0
    assert prepared.document["retained"]["warmup_normalized_sha256"] == digest(b"")
    assert prepared.document["changes"] == {
        "strictly_shorter_input": False,
        "parameter_contracted": False,
        "focus_window_narrowed": False,
    }
    assert prepared.document["flags"] == dict(FLAGS)
    view = prepared.document
    view["flags"]["initial_state_materialized"] = True
    assert prepared.document["flags"]["initial_state_materialized"] is False
    assert load_reduction_recipe(recipe.canonical_bytes) == recipe
    with pytest.raises(ReductionValidationError):
        replace(recipe, recipe_id="0" * 64)
    with pytest.raises(TypeError):
        FLAGS["native_replayed"] = True
    with pytest.raises(TypeError):
        SCOPE["budget_owner_changed"] = True


def test_focus_keeps_full_warmup_and_delay_is_rederived_before_cutting():
    actual = source()
    recipe = build_reduction_recipe(request(focus=3, through=3, delay=10_000_000), source=actual)
    prepared = materialize_reduction(recipe, source=actual)
    descriptor = prepared.document
    assert [event.capture_seq for event in prepared.prepared.events] == [1, 2, 3]
    assert prepared.prepared.events[0].receive_time_ns == 110
    assert prepared.prepared.events[1].receive_time_ns == 210 + 10_000_000
    assert descriptor["retained"]["warmup_event_count"] == 2
    lines = prepared.replay_input.normalized_bytes.splitlines(keepends=True)
    assert descriptor["retained"]["warmup_normalized_sha256"] == digest(b"".join(lines[:2]))
    assert descriptor["prefix_context_id"] == digest(canonical(descriptor["prefix_context"]))
    assert descriptor["changes"] == {
        "strictly_shorter_input": True,
        "parameter_contracted": True,
        "focus_window_narrowed": True,
    }


@pytest.mark.parametrize("change", ["spec", "prefix", "scenario", "focus"])
def test_context_identity_invalidates_for_state_relevant_changes(change):
    original = source()
    recipe = build_reduction_recipe(request(focus=4), source=original)
    previous = materialize_reduction(recipe, source=original)
    actual = (
        source(insert=1)
        if change == "spec"
        else source(trade_quantity=2)
        if change == "prefix"
        else original
    )
    changed_request = request(
        focus=3 if change == "focus" else 4,
        delay=10_000_000 if change == "scenario" else 20_000_000,
    )
    changed = materialize_reduction(
        build_reduction_recipe(changed_request, source=actual), source=actual
    )
    assert changed.document["prefix_context_id"] != previous.document["prefix_context_id"]
    if change in ("spec", "prefix"):
        with pytest.raises(ReductionValidationError, match="actual witness"):
            materialize_reduction(recipe, source=actual)


@pytest.mark.parametrize(
    "changes",
    [
        {"focus": 5},
        {"focus": 4, "through": 3},
        {"through": 1},
        {"delay": 20_000_001},
        {"delay": -1},
    ],
)
def test_invalid_reduction_never_repairs_or_replaces_input(changes):
    with pytest.raises(ReductionValidationError):
        build_reduction_recipe(request(**changes), source=source())


@pytest.mark.parametrize(
    "changes",
    [
        {"checkpoint_id": "f" * 64},
        {"seed": 9},
        {"schema_version": True},
        {"witness_ordinal": True},
        {"additional_delay_ns": 1.0},
    ],
)
def test_unknown_operators_and_ambiguous_types_are_not_legal_requests(changes):
    import json

    document = json.loads(request())
    document.update(changes)
    with pytest.raises(ReductionValidationError):
        load_reduction_request(canonical(document))


def test_recipe_scope_and_canonical_manifest_cannot_be_forged():
    actual = source()
    recipe = build_reduction_recipe(request(), source=actual)
    prepared = materialize_reduction(recipe, source=actual)
    for field in ("checkpoint_used", "initial_state_materialized", "witness_preservation_verified"):
        changed = deepcopy(recipe.document)
        changed["flags"][field] = True
        with pytest.raises(ReductionValidationError):
            load_reduction_recipe(canonical(changed))
    artifacts = {
        "recipe": recipe.canonical_bytes,
        "materialization": prepared.canonical_bytes,
        "normalized": prepared.replay_input.normalized_bytes,
    }
    manifest = build_reduction_manifest(artifacts)
    assert b"reduction_preparation_bundle_v1" in manifest
    assert role_limit("normalized") == 8 * 1024 * 1024
    with pytest.raises(ReductionValidationError):
        build_reduction_manifest({**artifacts, "checkpoint": b"{}"})
    with pytest.raises(ReductionValidationError):
        build_reduction_manifest({**artifacts, "materialization": prepared.canonical_bytes + b"\n"})
