"""Frozen resource bounds are contracts, not a new attempt budget or verdict."""

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    TERMINAL_RESERVE_BYTES,
    CampaignBudget,
    CampaignBudgetValidationError,
    build_allocation,
    build_budget_stop,
    build_campaign_budget,
    load_allocation,
    load_budget_stop,
    load_campaign_budget,
)


def request(**changes):
    return {
        "kind": "campaign_budget_request_v1", "schema_version": 1,
        "max_evaluations": 2, "max_wall_time_ms": 1_000,
        "max_storage_bytes": CONTROL_RESERVE_BYTES + 2 * CANDIDATE_RESERVE_BYTES,
        **changes,
    }


def budget(**changes):
    return build_campaign_budget(
        canonical(request(**changes)), plan_id="a" * 64, protocol_id="b" * 64, nonce="c" * 32,
    )


def test_budget_identity_exact_scope_and_detached_documents():
    frozen = budget()
    assert frozen.budget_id == hashlib.sha256(frozen.canonical_bytes).hexdigest()
    assert load_campaign_budget(frozen.canonical_bytes) == frozen
    assert budget() == frozen
    assert frozen.document["profile"] == "supervised_search_campaign_v1"
    assert frozen.document["accounting"] == {
        "control_reserve_bytes": CONTROL_RESERVE_BYTES,
        "candidate_reserve_bytes": CANDIDATE_RESERVE_BYTES,
        "terminal_reserve_bytes": TERMINAL_RESERVE_BYTES,
        "storage_policy": "managed_new_file_payloads_v1",
        "admission_policy": "nonrefundable_fixed_candidate_envelope_v1",
    }
    document = frozen.document
    document["limits"]["max_evaluations"] = 100
    assert frozen.document["limits"]["max_evaluations"] == 2
    assert not any(value is True for value in frozen.document["scope"].values())
    with pytest.raises(FrozenInstanceError):
        frozen.budget_id = "d" * 64
    with pytest.raises(CampaignBudgetValidationError):
        CampaignBudget("d" * 64, frozen.canonical_bytes)


@pytest.mark.parametrize(("field", "value"), [
    ("kind", "frozen_research_protocol_v1"), ("schema_version", True),
    ("max_evaluations", True), ("max_evaluations", 0), ("max_evaluations", 101),
    ("max_wall_time_ms", 0), ("max_wall_time_ms", 3_600_001),
    ("max_storage_bytes", CONTROL_RESERVE_BYTES - 1),
    ("max_storage_bytes", 16 * 1024 ** 3 + 1),
])
def test_request_boundaries_are_exact_integer_types(field, value):
    with pytest.raises(CampaignBudgetValidationError):
        budget(**{field: value})


@pytest.mark.parametrize("raw", [
    b"", b"{}", b'{"schema_version":1,"schema_version":1}',
    b'{"max_wall_time_ms":NaN}', b'{"max_wall_time_ms":1.0}', b" " * 65_537,
])
def test_request_rejects_unsafe_json(raw):
    with pytest.raises(CampaignBudgetValidationError):
        build_campaign_budget(raw, plan_id="a" * 64, protocol_id="b" * 64, nonce="c" * 32)


@pytest.mark.parametrize("change", ["scope", "profile", "accounting", "kind", "extra", "newline"])
def test_loader_rebuilds_every_frozen_marker_even_when_rehashed(change):
    frozen = budget()
    document = frozen.document
    if change == "scope":
        document["scope"]["findings_issued"] = True
    elif change == "profile":
        document["profile"] = "sequential_receive_delay_attempts_v1"
    elif change == "accounting":
        document["accounting"]["candidate_reserve_bytes"] = 1
    elif change == "kind":
        document["kind"] = "search_campaign_v1"
    elif change == "extra":
        document["funds_available"] = True
    raw = frozen.canonical_bytes + b"\n" if change == "newline" else canonical(document)
    with pytest.raises(CampaignBudgetValidationError):
        load_campaign_budget(raw)


def test_limits_and_binding_changes_create_new_identity():
    original = budget()
    assert budget(max_wall_time_ms=2_000).budget_id != original.budget_id
    changed = build_campaign_budget(
        canonical(request()), plan_id="d" * 64, protocol_id="b" * 64, nonce="c" * 32,
    )
    assert changed.budget_id != original.budget_id
    for bad in ("A" * 64, "../a", True):
        with pytest.raises(CampaignBudgetValidationError):
            build_campaign_budget(canonical(request()), plan_id=bad, protocol_id="b" * 64, nonce="c" * 32)


def test_allocation_charges_full_envelope_in_plan_order_not_original_attempt_slot():
    frozen = budget()
    first, second = build_allocation(frozen, 1, 1), build_allocation(frozen, 3, 2)
    assert load_allocation(first, budget=frozen)["reserved_storage_bytes"] == CONTROL_RESERVE_BYTES + CANDIDATE_RESERVE_BYTES
    assert load_allocation(second, budget=frozen)["reserved_storage_bytes"] == CONTROL_RESERVE_BYTES + 2 * CANDIDATE_RESERVE_BYTES
    assert load_allocation(second, budget=frozen)["ordinal"] == 3
    assert "attempt_id" not in json.loads(first)
    with pytest.raises(CampaignBudgetValidationError):
        build_allocation(frozen, 4, 3)
    with pytest.raises(CampaignBudgetValidationError):
        build_allocation(budget(max_storage_bytes=CONTROL_RESERVE_BYTES), 1, 1)
    with pytest.raises(CampaignBudgetValidationError):
        build_allocation(frozen, True, 1)
    forged = json.loads(first)
    forged["reserved_storage_bytes"] = 1
    with pytest.raises(CampaignBudgetValidationError):
        load_allocation(canonical(forged), budget=frozen)


@pytest.mark.parametrize(("reason", "code"), [
    ("completed", 0), ("evaluation_limit", 8), ("storage_limit", 8), ("time_limit", 8),
    ("execution_stopped", 3), ("execution_stopped", 6), ("execution_stopped", 7),
    ("execution_stopped", 8), ("execution_unfinalized", 3), ("worker_failed", 7),
    ("publication_unconfirmed", 3),
])
def test_budget_stop_has_fixed_reason_exit_and_content_bindings(reason, code):
    frozen = budget()
    raw = build_budget_stop(frozen, reason, exit_code=code, elapsed_ns=123)
    document = load_budget_stop(raw, budget=frozen)
    assert document["reason"] == reason and document["exit_code"] == code
    assert document["budget_id"] == frozen.budget_id
    assert len(raw) < TERMINAL_RESERVE_BYTES
    with pytest.raises(CampaignBudgetValidationError):
        load_budget_stop(raw, budget=budget(max_wall_time_ms=2_000))


@pytest.mark.parametrize(("reason", "code"), [
    ("completed", 8), ("time_limit", 7), ("storage_limit", 0), ("worker_failed", 6),
    ("publication_unconfirmed", 7), ("execution_unfinalized", 8), ("NO_COUNTEREXAMPLE_FOUND", 0),
])
def test_invalid_stop_never_forges_a_search_finding_or_completion(reason, code):
    with pytest.raises(CampaignBudgetValidationError):
        build_budget_stop(budget(), reason, exit_code=code, elapsed_ns=10)


@pytest.mark.parametrize("value", [True, -1, 1 << 63])
def test_elapsed_is_a_bounded_integer_not_an_attestation(value):
    with pytest.raises(CampaignBudgetValidationError):
        build_budget_stop(budget(), "time_limit", exit_code=8, elapsed_ns=value)


def test_stop_message_rejects_unsafe_values():
    for message in ("", "line\nbreak", "a" * 4_097, "\ud800"):
        with pytest.raises(CampaignBudgetValidationError):
            build_budget_stop(budget(), "worker_failed", exit_code=7, elapsed_ns=0, message=message)
