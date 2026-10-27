"""Admission and write charges enforce hard managed-payload envelopes before writes."""

import pytest

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    TERMINAL_RESERVE_BYTES,
    build_budget_stop,
    build_campaign_budget,
)
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.campaign_resource_guard import (
    CampaignLimitReached,
    CampaignResourceGuard,
    CampaignResourceGuardError,
    activate_resource_guard,
    charge_managed_write,
)

_PLAN = "a" * 64


def setup(tmp_path, *, evaluations=2, storage=None, now=0, deadline=1_000):
    budget = build_campaign_budget(
        canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": evaluations,
                "max_wall_time_ms": 1000,
                "max_storage_bytes": storage
                if storage is not None
                else CONTROL_RESERVE_BYTES + 2 * CANDIDATE_RESERVE_BYTES,
            }
        ),
        plan_id=_PLAN,
        protocol_id="b" * 64,
        nonce="c" * 32,
    )
    store = LocalCampaignBudgetStore(tmp_path / "runs", create=True)
    store.start(_PLAN, budget.canonical_bytes)
    clock = [now]
    guard = CampaignResourceGuard(budget, store, lambda: clock[0], deadline)
    return budget, store, clock, guard


def test_control_and_candidate_exact_edges_and_terminal_reserve(tmp_path):
    budget, store, _, guard = setup(tmp_path)
    initial = guard.usage["control_charged_bytes"]
    guard.before_write(CONTROL_RESERVE_BYTES - TERMINAL_RESERVE_BYTES - initial)
    assert guard.usage["control_charged_bytes"] == CONTROL_RESERVE_BYTES - TERMINAL_RESERVE_BYTES
    with pytest.raises(CampaignLimitReached, match="storage_limit"):
        guard.before_write(1)
    # A separate guard demonstrates candidate accounting without allocating large byte arrays.
    budget2, store2, _, candidate = setup(tmp_path / "candidate")
    candidate.admit(1)
    candidate.before_write(CANDIDATE_RESERVE_BYTES)
    assert candidate.usage["current_candidate_charged_bytes"] == CANDIDATE_RESERVE_BYTES
    with pytest.raises(CampaignLimitReached, match="storage_limit"):
        candidate.before_write(1)
    stop = build_budget_stop(budget2, "storage_limit", exit_code=8, elapsed_ns=2)
    store2.write_stop(_PLAN, stop)
    assert store2.get_stop(_PLAN) == stop
    assert store.get_budget(_PLAN) == budget.canonical_bytes


def test_storage_admission_is_before_any_original_attempt_reservation(tmp_path):
    _, store, _, guard = setup(tmp_path, storage=CONTROL_RESERVE_BYTES + CANDIDATE_RESERVE_BYTES)
    first = guard.admit(1)
    assert store.get_allocations(_PLAN) == (first,)
    with pytest.raises(CampaignLimitReached, match="storage_limit"):
        guard.admit(3)
    assert store.get_allocations(_PLAN) == (first,)
    assert not (tmp_path / "runs" / "slots").exists()
    assert guard.usage["reserved_storage_bytes"] == CONTROL_RESERVE_BYTES + CANDIDATE_RESERVE_BYTES


def test_evaluation_limit_wins_after_committed_admission_and_never_refunds(tmp_path):
    _, store, _, guard = setup(tmp_path, evaluations=1)
    guard.admit(1)
    with pytest.raises(CampaignResourceGuardError, match="reused"):
        guard.admit(1)
    with pytest.raises(CampaignLimitReached, match="evaluation_limit"):
        guard.admit(3)
    assert len(store.get_allocations(_PLAN)) == 1


def test_deadline_checked_at_admission_and_before_each_write(tmp_path):
    _, store, clock, guard = setup(tmp_path, deadline=100)
    clock[0] = 99
    guard.admit(1)
    clock[0] = 100
    with pytest.raises(CampaignLimitReached, match="time_limit"):
        guard.before_write(1)
    with pytest.raises(CampaignLimitReached, match="time_limit"):
        guard.admit(3)
    assert guard.usage["current_candidate_charged_bytes"] == 0
    assert len(store.get_allocations(_PLAN)) == 1


def test_limit_baseexception_bypasses_legacy_exception_failure_coercion(tmp_path):
    _, _, clock, guard = setup(tmp_path, deadline=100)
    clock[0] = 100
    caught = []
    with pytest.raises(CampaignLimitReached):
        try:
            guard.check_time()
        except Exception:
            caught.append("incorrect coercion")
    assert caught == []


def test_context_hook_is_opt_in_nested_and_resets_after_error(tmp_path):
    _, _, _, guard = setup(tmp_path)
    charge_managed_write(10**20)
    before = guard.usage["control_charged_bytes"]
    with activate_resource_guard(guard):
        charge_managed_write(7)
        assert guard.usage["control_charged_bytes"] == before + 7
        guard.admit(1)
        charge_managed_write(4)
        with activate_resource_guard(guard):
            charge_managed_write(5)
        with pytest.raises(CampaignLimitReached):
            charge_managed_write(CANDIDATE_RESERVE_BYTES)
        assert guard.usage["current_candidate_charged_bytes"] == 9
    charge_managed_write(10**20)
    assert guard.usage["current_candidate_charged_bytes"] == 9


def test_constructor_refuses_resume_or_budget_substitution(tmp_path):
    budget, store, _, guard = setup(tmp_path)
    guard.admit(1)
    with pytest.raises(CampaignResourceGuardError, match="resume"):
        CampaignResourceGuard(budget, store, lambda: 0, 1000)
    other, _, _, _ = setup(tmp_path / "other", evaluations=1)
    with pytest.raises(CampaignResourceGuardError, match="committed"):
        CampaignResourceGuard(other, store, lambda: 0, 1000)


def test_uncertain_allocation_publication_poisoned_guard_cannot_continue(tmp_path, monkeypatch):
    _, store, _, guard = setup(tmp_path)
    original = store.write_allocation

    def uncertain(plan_id, ordinal, raw):
        original(plan_id, ordinal, raw)
        raise OSError("commit response lost")

    monkeypatch.setattr(store, "write_allocation", uncertain)
    with pytest.raises(OSError):
        guard.admit(1)
    assert len(store.get_allocations(_PLAN)) == 1
    with pytest.raises(CampaignResourceGuardError, match="cannot continue"):
        guard.before_write(1)
    with pytest.raises(CampaignResourceGuardError, match="cannot continue"):
        guard.admit(3)


@pytest.mark.parametrize("value", [True, -1, 1.5])
def test_invalid_write_charges_are_rejected(tmp_path, value):
    _, _, _, guard = setup(tmp_path)
    with pytest.raises(CampaignResourceGuardError):
        guard.before_write(value)


def test_clock_regression_is_not_a_free_extension(tmp_path):
    _, _, clock, guard = setup(tmp_path, now=50)
    clock[0] = 49
    with pytest.raises(CampaignResourceGuardError, match="regressing"):
        guard.check_time()
