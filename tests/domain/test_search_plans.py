"""Candidate plans preserve raw proposal coverage and cannot authorize execution."""

from __future__ import annotations

import builtins
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest
from test_scenario_derivation import context

from tickwitness.domain.assumptions.specs import (
    build_scenario_spec,
    load_assumption_spec,
)
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.search import plans
from tickwitness.domain.search.plans import (
    MAX_SEARCH_PLAN_BYTES,
    SearchPlan,
    SearchPlanValidationError,
    build_search_plan,
    load_search_plan,
)


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def declaration(
    *, count: int = 6, seed: int = 7, values: list[int] | None = None
) -> dict[str, Any]:
    return {
        "kind": "search_plan_request_v1",
        "schema_version": 1,
        "search_seed": seed,
        "max_proposals": count,
        "generator": {"kind": "grid", "values_ns": values or [3, 0, 3, 20_000_001, 20_000_001, 9]},
    }


def plan(declaration_value: dict[str, Any] | None = None) -> SearchPlan:
    validated = context()
    return build_search_plan(
        encoded(declaration_value if declaration_value is not None else declaration()),
        protocol=validated.protocol,
        assumptions=validated.assumptions,
    )


def test_grid_keeps_order_duplicates_and_rejections_without_refill() -> None:
    frozen = plan()
    document = frozen.document
    journal = document["journal"]
    assert [row["delay_ns"] for row in journal] == [3, 0, 3, 20_000_001, 20_000_001, 9]
    assert [row["status"] for row in journal] == [
        "ELIGIBLE",
        "ELIGIBLE",
        "DUPLICATE",
        "REJECTED",
        "DUPLICATE",
        "ELIGIBLE",
    ]
    assert [row["duplicate_of"] for row in journal] == [None, None, 1, None, 4, None]
    assert [row["reason"] for row in journal] == [
        None,
        None,
        "duplicate_proposal",
        "outside_assumption_range",
        "duplicate_proposal",
        None,
    ]
    assert journal[2]["scenario_id"] == journal[0]["scenario_id"]
    assert journal[3]["scenario_id"] is None
    assert journal[4]["scenario_id"] is None
    assert document["counts"] == {"proposed": 6, "eligible": 3, "duplicate": 2, "rejected": 1}
    assert document["generation_stop"] == "grid_exhausted"
    assert [row["ordinal"] for row in journal] == list(range(1, 7))


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_proposal_limit_is_raw_prefix_not_unique_eligible_count(count: int) -> None:
    frozen = plan(declaration(count=count))
    assert frozen.document["journal"] == plan().document["journal"][:count]
    assert frozen.document["counts"]["proposed"] == count
    assert frozen.document["generation_stop"] == "proposal_limit"
    assert frozen.plan_id != plan().plan_id


@pytest.mark.parametrize("count", [6, 7, 1_024])
def test_grid_exhaustion_wins_when_all_input_proposals_are_generated(count: int) -> None:
    frozen = plan(declaration(count=count))
    assert frozen.document["generation_stop"] == "grid_exhausted"
    assert frozen.document["counts"]["proposed"] == 6


def test_eligible_identity_is_existing_scenario_contract_including_zero_shift() -> None:
    validated = context()
    frozen = plan(declaration(values=[0, 3, 20_000_000], count=3))
    for row in frozen.document["journal"]:
        scenario = build_scenario_spec(
            encoded(
                {
                    "kind": "scenario_request_v1",
                    "schema_version": 1,
                    "scenario_kind": "COUNTERFACTUAL_STRESS",
                    "additional_delay": {"value": row["delay_ns"], "unit": "ns"},
                }
            ),
            assumptions=validated.assumptions,
        )
        assert row["scenario_id"] == scenario.scenario_id
        assert row["scenario_id"] != validated.replay_input.dataset_id


def test_plan_is_canonical_immutable_detached_and_explicitly_nonexecuting() -> None:
    frozen = plan()
    assert frozen.canonical_bytes == encoded(frozen.document)
    assert frozen.plan_id == hashlib.sha256(frozen.canonical_bytes).hexdigest()
    assert load_search_plan(frozen.canonical_bytes) == frozen
    assert plan() == frozen
    document = frozen.document
    document["journal"][0]["status"] = "EXECUTED"
    document["protocol"]["budget"]["max_attempts"] = 100
    document["scope"]["execution_performed"] = True
    assert frozen.document["journal"][0]["status"] == "ELIGIBLE"
    assert frozen.document["protocol"]["budget"]["max_attempts"] == 2
    assert frozen.document["scope"] == {
        "phase": "development",
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "calibration_status": "uncalibrated",
        "source_validated": False,
        "execution_performed": False,
        "attempt_budget_reserved": False,
        "claim_evaluated": False,
        "findings_issued": False,
    }
    with pytest.raises(FrozenInstanceError):
        frozen.plan_id = "f" * 64
    with pytest.raises(SearchPlanValidationError, match="identity"):
        replace(frozen, plan_id="f" * 64)


def random_declaration(*, seed: int = 7, count: int = 8, low: int = 0, high: int = 60_000_000_000):
    return {
        **declaration(seed=seed, count=count),
        "generator": {
            "kind": "random_integer_with_replacement",
            "minimum_ns": low,
            "maximum_ns": high,
        },
    }


@pytest.mark.parametrize("seed", [0, 1, 7, (1 << 63) - 1])
def test_random_counter_encoding_matches_independent_explicit_sha256_oracle(seed: int) -> None:
    # The independent oracle fixes byte encoding, domain separator, endian and
    # the unbiased cutoff. It does not call any planner random helper.
    bound = 60_000_000_001
    cutoff = ((1 << 256) // bound) * bound
    samples = []
    counter = 0
    while len(samples) < 8:
        payload = (
            b"TickWitness/search-delay/sha256-counter-rejection/v1\x00"
            + seed.to_bytes(length=8, byteorder="big", signed=False)
            + counter.to_bytes(length=8, byteorder="big", signed=False)
        )
        value = int(hashlib.sha256(payload).hexdigest(), 16)
        if value < cutoff:
            samples.append(value % bound)
        counter += 1
    frozen = plan(random_declaration(seed=seed))
    assert [row["delay_ns"] for row in frozen.document["journal"]] == samples
    assert frozen.document["random_policy"] == "sha256_counter_rejection_v1"
    assert frozen.document["generation_stop"] == "proposal_limit"
    assert frozen.document["protocol"]["replay_spec"]["seed"] == 7


@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_random_prefix_is_stable_under_larger_proposal_budget(count: int) -> None:
    short = plan(random_declaration(count=count))
    longer = plan(random_declaration(count=8))
    assert short.document["journal"] == longer.document["journal"][:count]
    assert short.plan_id != longer.plan_id


def test_random_is_with_replacement_and_duplicates_count_against_raw_limit() -> None:
    frozen = plan(random_declaration(count=5, low=3, high=3))
    journal = frozen.document["journal"]
    assert [row["delay_ns"] for row in journal] == [3] * 5
    assert [row["status"] for row in journal] == ["ELIGIBLE"] + ["DUPLICATE"] * 4
    assert [row["duplicate_of"] for row in journal] == [None, 1, 1, 1, 1]
    assert frozen.document["counts"] == {
        "proposed": 5,
        "eligible": 1,
        "duplicate": 4,
        "rejected": 0,
    }


def test_random_rejection_advances_raw_counter_without_creating_a_proposal(monkeypatch) -> None:
    original = hashlib.sha256
    seen = []

    class Draw:
        def __init__(self, value: int):
            self.value = value

        def digest(self):
            return self.value.to_bytes(32, "big")

    def injected(payload=b"", **kwargs):
        if payload.startswith(b"TickWitness/search-delay/sha256-counter-rejection/v1\0"):
            counter = int.from_bytes(payload[-8:], "big")
            seen.append(counter)
            return Draw((1 << 256) - 1 if counter == 0 else counter)
        return original(payload, **kwargs)

    monkeypatch.setattr(plans.hashlib, "sha256", injected)
    frozen = plan(random_declaration(count=2, low=0, high=2))
    assert [row["delay_ns"] for row in frozen.document["journal"]] == [1, 2]
    assert frozen.document["counts"]["proposed"] == 2
    assert seen[:3] == [0, 1, 2]


def test_pathological_random_stream_fails_closed_at_fixed_raw_draw_bound(monkeypatch) -> None:
    original = hashlib.sha256

    class Draw:
        def digest(self):
            return b"\xff" * 32

    def injected(payload=b"", **kwargs):
        if payload.startswith(b"TickWitness/search-delay/sha256-counter-rejection/v1\0"):
            return Draw()
        return original(payload, **kwargs)

    monkeypatch.setattr(plans, "_MAX_RANDOM_DRAWS", 3)
    monkeypatch.setattr(plans.hashlib, "sha256", injected)
    with pytest.raises(SearchPlanValidationError, match="raw-draw"):
        plan(random_declaration(count=1, low=0, high=2))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "search_plan_v1"),
        ("schema_version", True),
        ("schema_version", 2),
        ("search_seed", True),
        ("search_seed", -1),
        ("search_seed", 1 << 63),
        ("max_proposals", True),
        ("max_proposals", 0),
        ("max_proposals", 1_025),
        ("generator", {}),
        ("generator", {"kind": "adaptive"}),
        ("generator", {"kind": "grid", "values_ns": []}),
        ("generator", {"kind": "grid", "values_ns": [True]}),
        ("generator", {"kind": "grid", "values_ns": [-1]}),
        ("generator", {"kind": "grid", "values_ns": [60_000_000_001]}),
        ("generator", {"kind": "grid", "values_ns": [0] * 1_025}),
        ("generator", {"kind": "grid", "values_ns": [0], "sort": True}),
        (
            "generator",
            {"kind": "random_integer_with_replacement", "minimum_ns": 2, "maximum_ns": 1},
        ),
        (
            "generator",
            {"kind": "random_integer_with_replacement", "minimum_ns": False, "maximum_ns": 2},
        ),
        (
            "generator",
            {
                "kind": "random_integer_with_replacement",
                "minimum_ns": 0,
                "maximum_ns": 60_000_000_001,
            },
        ),
    ],
)
def test_request_rejects_unsupported_missing_and_unbounded_values(field, value) -> None:
    request_value = declaration()
    request_value[field] = value
    with pytest.raises(SearchPlanValidationError):
        plan(request_value)


@pytest.mark.parametrize(
    "change", ["extra", "missing", "float", "duplicate", "nan", "oversized", "empty", "mutable"]
)
def test_request_parser_rejects_nonexact_or_unsafe_json(change: str) -> None:
    request_value = declaration()
    raw = encoded(request_value)
    if change == "extra":
        request_value["execution_authority"] = True
        raw = encoded(request_value)
    elif change == "missing":
        del request_value["search_seed"]
        raw = encoded(request_value)
    elif change == "float":
        raw = raw.replace(b'"search_seed":7', b'"search_seed":7.0')
    elif change == "duplicate":
        raw = raw.replace(b'"search_seed":7', b'"search_seed":7,"search_seed":7')
    elif change == "nan":
        raw = raw.replace(b'"search_seed":7', b'"search_seed":NaN')
    elif change == "oversized":
        raw = b" " * 65_537
    elif change == "empty":
        raw = b""
    else:
        raw = bytearray(raw)
    validated = context()
    with pytest.raises(SearchPlanValidationError):
        build_search_plan(raw, protocol=validated.protocol, assumptions=validated.assumptions)


@pytest.mark.parametrize(
    "change",
    [
        "protocol",
        "dataset",
        "spec",
        "assumption_identity",
        "protocol_identity",
        "subject_type",
        "assumption_type",
    ],
)
def test_context_is_revalidated_without_trusting_old_identity_markers(change: str) -> None:
    validated = context()
    subject, assumptions = validated.protocol, validated.assumptions
    if change in {"protocol", "dataset", "spec"}:
        document = assumptions.document
        key = {
            "protocol": "protocol_id",
            "dataset": "development_dataset_id",
            "spec": "replay_spec_id",
        }[change]
        document["bindings"][key] = "f" * 64
        assumptions = load_assumption_spec(encoded(document))
    elif change == "assumption_identity":
        object.__setattr__(assumptions, "assumption_id", "f" * 64)
    elif change == "protocol_identity":
        object.__setattr__(subject, "protocol_id", "f" * 64)
    elif change == "subject_type":
        subject = subject.document
    else:
        assumptions = assumptions.document
    with pytest.raises(SearchPlanValidationError):
        build_search_plan(encoded(declaration()), protocol=subject, assumptions=assumptions)


@pytest.mark.parametrize(
    "change",
    [
        "journal_value",
        "scenario_id",
        "duplicate",
        "status",
        "counts",
        "stop",
        "scope",
        "policy",
        "seed",
        "id",
        "assumption_id",
        "schema_version",
        "budget",
        "extra",
        "newline",
    ],
)
def test_loader_recomputes_proposals_instead_of_trusting_all_rehashed_content(change: str) -> None:
    frozen = plan()
    document = frozen.document
    if change == "journal_value":
        document["journal"][0]["delay_ns"] = 4
    elif change == "scenario_id":
        document["journal"][0]["scenario_id"] = "f" * 64
    elif change == "duplicate":
        document["journal"][2]["duplicate_of"] = 2
    elif change == "status":
        document["journal"][3]["status"] = "ELIGIBLE"
    elif change == "counts":
        document["counts"]["eligible"] = 4
    elif change == "stop":
        document["generation_stop"] = "proposal_limit"
    elif change == "scope":
        document["scope"]["source_validated"] = True
    elif change == "policy":
        document["random_policy"] = "python_random_v1"
    elif change == "seed":
        # Grid does not consume the seed, so this changes the exact declaration
        # and legitimately creates a different plan rather than invalid content.
        document["protocol"]["replay_spec"]["seed"] = 9
    elif change == "id":
        document["protocol_id"] = "f" * 64
    elif change == "assumption_id":
        document["assumption_id"] = "f" * 64
    elif change == "schema_version":
        document["schema_version"] = True
    elif change == "budget":
        document["protocol"]["budget"]["max_attempts"] = 3
    elif change == "extra":
        document["finding"] = "NO_COUNTEREXAMPLE_FOUND"
    raw = frozen.canonical_bytes + b"\n" if change == "newline" else encoded(document)
    with pytest.raises(SearchPlanValidationError):
        load_search_plan(raw)
    with pytest.raises(SearchPlanValidationError):
        SearchPlan(hashlib.sha256(raw).hexdigest(), raw)


def test_valid_changed_request_is_new_plan_not_a_preregistration_claim() -> None:
    original = plan()
    document = original.document
    document["request"]["search_seed"] = 8
    changed = load_search_plan(encoded(document))
    assert changed.plan_id != original.plan_id
    assert changed.document["journal"] == original.document["journal"]
    assert "preregistered" not in changed.document["scope"]


def test_changed_random_seed_cannot_keep_the_previous_candidate_journal() -> None:
    frozen = plan(random_declaration())
    document = frozen.document
    document["request"]["search_seed"] = 8
    raw = encoded(document)
    with pytest.raises(SearchPlanValidationError, match="does not reproduce"):
        SearchPlan(hashlib.sha256(raw).hexdigest(), raw)


def test_rehashed_new_subject_and_assumptions_cannot_keep_old_scenario_identities() -> None:
    frozen = plan()
    document = frozen.document
    document["protocol"]["budget"]["max_attempts"] = 3
    document["protocol_id"] = hashlib.sha256(encoded(document["protocol"])).hexdigest()
    document["assumptions"]["bindings"]["protocol_id"] = document["protocol_id"]
    document["assumption_id"] = hashlib.sha256(encoded(document["assumptions"])).hexdigest()
    raw = encoded(document)
    with pytest.raises(SearchPlanValidationError, match="does not reproduce"):
        SearchPlan(hashlib.sha256(raw).hexdigest(), raw)


@pytest.mark.parametrize("raw", [b"", bytearray(b"{}"), b" " * (MAX_SEARCH_PLAN_BYTES + 1)])
def test_loader_rejects_mutable_empty_and_oversized_content(raw) -> None:
    with pytest.raises(SearchPlanValidationError):
        load_search_plan(raw)


def test_domain_stays_io_and_native_free(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in {"sqlite3", "socket", "subprocess"} or name.startswith(
            ("nautilus_trader", "tickwitness.infrastructure", "tickwitness.application")
        ):
            raise AssertionError("Candidate planning cannot import IO or execution")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    frozen = plan()
    assert frozen.document["scope"]["execution_performed"] is False
    assert load_search_plan(frozen.canonical_bytes) == frozen


def test_boundaries_and_nonzero_assumption_lower_bound_are_explicit() -> None:
    validated = context()
    document = validated.assumptions.document
    document["additional_delay"] = {"minimum": 5, "maximum": 60_000_000_000, "unit": "ns"}
    assumptions = load_assumption_spec(encoded(document))
    frozen = build_search_plan(
        encoded(declaration(values=[0, 5, 60_000_000_000], count=3)),
        protocol=validated.protocol,
        assumptions=assumptions,
    )
    assert [row["status"] for row in frozen.document["journal"]] == [
        "REJECTED",
        "ELIGIBLE",
        "ELIGIBLE",
    ]
    # These are declaration-only bindings; actual source horizon validation is
    # deliberately the application boundary, not a misleading domain marker.
    assert frozen.document["scope"]["source_validated"] is False
    assert load_executable_protocol(encoded(frozen.document["protocol"])) == validated.protocol
