"""A frozen finite neighborhood cannot manufacture execution or budget authority."""

from dataclasses import replace

import pytest
from test_reduction_contracts import request as input_request
from test_reduction_contracts import source

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.reduction.contracts import (
    ReductionValidationError,
    build_reduction_recipe,
    materialize_reduction,
)
from tickwitness.domain.reduction.search import (
    SEARCH_SCOPE,
    build_reduction_search_plan,
    initial_point,
    load_reduction_search_plan,
    load_reduction_search_request,
    point_cost,
    reduction_neighbors,
    reduction_request,
)


def search_request(*, focus=1, steps=10):
    return canonical(
        {
            "kind": "reduction_search_request_v1",
            "schema_version": 1,
            "witness_ordinal": 3,
            "focus_from_capture_seq": focus,
            "max_steps": steps,
            "max_wall_time_ms": 120_000,
        }
    )


def plan(*, focus=1):
    selected = source()
    prepared = materialize_reduction(
        build_reduction_recipe(input_request(focus=focus), source=selected), source=selected
    )
    return build_reduction_search_plan(search_request(focus=focus), materialization=prepared)


def test_plan_freezes_original_authority_budget_focus_and_actual_neighbors():
    frozen = plan()
    assert load_reduction_search_plan(frozen.canonical_bytes) == frozen
    assert frozen.document["scope"] == dict(SEARCH_SCOPE)
    assert frozen.document["original_budget"] == source().validation.protocol.document["budget"]
    original = initial_point(frozen)
    assert original == {"through_capture_seq": 4, "additional_delay_ns": 20_000_000}
    assert point_cost(frozen, original) == (4, 20_000_000)
    neighbors = reduction_neighbors(frozen, original)
    assert neighbors == (
        {"through_capture_seq": 4, "additional_delay_ns": 10_000_000},
        {"through_capture_seq": 3, "additional_delay_ns": 20_000_000},
    )
    for candidate in neighbors:
        assert point_cost(frozen, candidate) < point_cost(frozen, original)
        request = reduction_request(frozen, candidate)
        materialized = materialize_reduction(
            build_reduction_recipe(request, source=source()), source=source()
        )
        assert materialized.document["retained"]["event_count"] == point_cost(frozen, candidate)[0]
        assert materialized.document["flags"]["attempt_reserved"] is False
        assert materialized.document["flags"]["native_replayed"] is False
    detached = frozen.document
    detached["scope"]["budget_owner_changed"] = True
    assert frozen.document["scope"]["budget_owner_changed"] is False


def test_fixed_focus_and_anchor_are_retained_and_metadata_does_not_reduce_cost():
    frozen = plan(focus=3)
    endpoint = {"through_capture_seq": 3, "additional_delay_ns": 20_000_000}
    assert frozen.document["minimum_through_capture_seq"] == 3
    assert reduction_neighbors(frozen, endpoint) == (
        {"through_capture_seq": 3, "additional_delay_ns": 10_000_000},
    )
    assert point_cost(frozen, endpoint) == (3, 20_000_000)
    with pytest.raises(ReductionValidationError):
        point_cost(frozen, {"through_capture_seq": 2, "additional_delay_ns": 0})
    with pytest.raises(ReductionValidationError):
        point_cost(frozen, {**endpoint, "focus_from_capture_seq": 4})


def test_decreasing_operators_use_actual_capture_indices_and_respect_delay_minimum():
    document = plan().document
    document["source_capture_seqs"] = [1, 5, 9, 20]
    document["minimum_through_capture_seq"] = 5
    document["initial"]["through_capture_seq"] = 20
    document["minimum_delay_ns"] = 15_000_000
    frozen = load_reduction_search_plan(canonical(document))
    original = initial_point(frozen)
    assert point_cost(frozen, original) == (4, 20_000_000)
    assert reduction_neighbors(frozen, original) == (
        {"through_capture_seq": 9, "additional_delay_ns": 20_000_000},
    )
    assert (
        reduction_neighbors(frozen, {"through_capture_seq": 5, "additional_delay_ns": 20_000_000})
        == ()
    )
    with pytest.raises(ReductionValidationError):
        point_cost(frozen, {"through_capture_seq": 19, "additional_delay_ns": 20_000_000})


def test_every_accepted_operator_path_strictly_decreases_without_continuous_space_claim():
    frozen = plan()
    current = initial_point(frozen)
    visited = {point_cost(frozen, current)}
    for _ in range(100):
        neighbors = reduction_neighbors(frozen, current)
        if not neighbors:
            break
        candidate = neighbors[0]
        cost = point_cost(frozen, candidate)
        assert cost < point_cost(frozen, current) and cost not in visited
        visited.add(cost)
        current = candidate
    else:
        pytest.fail("The finite decreasing policy did not reach its declared boundary")
    assert frozen.document["scope"]["local_minimum_verified"] is False
    assert frozen.document["scope"]["global_minimum_verified"] is False


@pytest.mark.parametrize("change", ["prefix", "delay", "focus"])
def test_plan_cannot_start_from_an_unevaluated_reduction_disguised_as_source(change):
    selected = source()
    prepared = materialize_reduction(
        build_reduction_recipe(
            input_request(
                through=3 if change == "prefix" else 4,
                delay=10_000_000 if change == "delay" else 20_000_000,
                focus=3 if change == "focus" else 1,
            ),
            source=selected,
        ),
        source=selected,
    )
    with pytest.raises(ReductionValidationError):
        build_reduction_search_plan(search_request(), materialization=prepared)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("witness_ordinal", False),
        ("focus_from_capture_seq", 0),
        ("max_steps", 0),
        ("max_steps", 101),
        ("max_steps", True),
        ("max_wall_time_ms", 0),
        ("max_wall_time_ms", 86_400_001),
    ],
)
def test_search_request_rejects_ambiguous_or_unbounded_admission(field, value):
    request = load_reduction_search_request(search_request())
    request[field] = value
    with pytest.raises(ReductionValidationError):
        load_reduction_search_request(canonical(request))


@pytest.mark.parametrize("attack", ["authority", "policy", "budget", "captures", "unknown"])
def test_rehashed_plan_cannot_change_frozen_scope_policy_or_structural_bounds(attack):
    document = plan().document
    if attack == "authority":
        document["scope"]["source_claim_evaluated"] = True
    elif attack == "policy":
        document["policy"]["cancellation"] = "kill_and_refund"
    elif attack == "budget":
        document["original_budget"]["max_attempts"] = 101
    elif attack == "captures":
        document["source_capture_seqs"] = [1, 2, 2, 4]
    else:
        document["checkpoint"] = {}
    with pytest.raises(ReductionValidationError):
        load_reduction_search_plan(canonical(document))


def test_noncanonical_and_mutated_typed_plans_never_drive_a_new_policy():
    frozen = plan()
    with pytest.raises(ReductionValidationError):
        load_reduction_search_plan(frozen.canonical_bytes + b"\n")
    with pytest.raises(ReductionValidationError):
        replace(frozen, plan_id="0" * 64)
    object.__setattr__(frozen, "plan_id", "0" * 64)
    with pytest.raises(ReductionValidationError):
        reduction_neighbors(frozen, {"through_capture_seq": 4, "additional_delay_ns": 0})
