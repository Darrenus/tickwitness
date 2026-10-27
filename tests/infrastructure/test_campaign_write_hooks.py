"""Budget guards stop managed payloads before creating staging files."""

import time

import pytest

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    build_campaign_budget,
)
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.campaign_resource_guard import (
    CampaignLimitReached,
    CampaignResourceGuard,
    activate_resource_guard,
)
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore


def test_full_candidate_lane_blocks_ledger_and_result_before_any_new_payload(experiment_case):
    case = experiment_case
    plan_id = "1" * 64
    budget = build_campaign_budget(
        canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": 1,
                "max_wall_time_ms": 20_000,
                "max_storage_bytes": CONTROL_RESERVE_BYTES + CANDIDATE_RESERVE_BYTES,
            }
        ),
        plan_id=plan_id,
        protocol_id=case.frozen.protocol_id,
        nonce="2" * 32,
    )
    store = LocalCampaignBudgetStore(case.root / "runs", create=True)
    store.start(plan_id, budget.canonical_bytes)
    guard = CampaignResourceGuard(
        budget, store, time.monotonic_ns, time.monotonic_ns() + 20_000_000_000
    )
    guard.admit(1)
    guard.before_write(CANDIDATE_RESERVE_BYTES)
    owner = load_executable_protocol(case.registry.get(case.frozen.protocol_id).canonical_bytes)
    ledger = LocalAttemptLedger(case.root / "runs")
    campaigns = LocalSearchCampaignStore(store.managed_root(plan_id), create=True)
    with activate_resource_guard(guard):
        with pytest.raises(CampaignLimitReached, match="storage_limit"):
            ledger.reserve_with_nonce(owner, "3" * 32)
        with pytest.raises(CampaignLimitReached, match="storage_limit"):
            campaigns.write_result(plan_id, 1, b"must never be written")
    assert ledger.list_reservations(owner) == ()
    assert list((case.root / "runs" / "objects" / "sha256").iterdir()) == []
    assert campaigns.get_result(plan_id, 1) is None
    assert not list(store.managed_root(plan_id).rglob(".pending-*"))
