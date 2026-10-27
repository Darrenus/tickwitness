"""Separate bounded-campaign entry point; legacy execution profiles remain readable."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path
from typing import cast

from tickwitness.application.bounded_search import (
    inspect_bounded_search_campaign,
    run_bounded_search_campaign,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_execution import inspect_search_campaign
from tickwitness.domain.evidence.run_records import identity
from tickwitness.domain.search.budgets import CampaignBudget, CampaignBudgetValidationError
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.campaign_supervisor import CampaignSupervision, supervise_campaign
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.search_campaign_store import (
    LocalSearchCampaignStore,
    SearchCampaignNotFoundError,
)
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry

COMMANDS = frozenset({"run-bounded-search-plan", "inspect-bounded-search-campaign"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = commands.add_parser("run-bounded-search-plan", help="Execute with a frozen total deadline and payload admission quota")
    run.add_argument("plan_id")
    run.add_argument("budget_request")
    run.add_argument("--input-root", required=True, type=Path)
    run.add_argument("--engine-python", type=Path)
    inspect = commands.add_parser("inspect-bounded-search-campaign", help="Re-audit bounded execution without re-running resource limits")
    inspect.add_argument("plan_id")
    for command in (run, inspect):
        command.add_argument("--plans", required=True, type=Path)
        command.add_argument("--store", required=True, type=Path)
        command.add_argument("--registry", required=True, type=Path)
        command.add_argument("--runs", required=True, type=Path)
        command.add_argument("--split", choices=("development", "confirmation"), default="development")


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Bounded campaigns permit development evidence only")
    identity(arguments.plan_id)

    def inner() -> dict[str, object] | None:
        budgets = LocalCampaignBudgetStore(arguments.runs, create=False)
        try:
            campaigns = LocalSearchCampaignStore(budgets.managed_root(arguments.plan_id), create=False)
        except SearchCampaignNotFoundError:
            return None
        if campaigns.get_campaign(arguments.plan_id) is None:
            if any(campaigns.check_tree(arguments.plan_id).values()):
                raise CampaignBudgetValidationError("Bounded execution has orphaned records without a header")
            return None
        return inspect_search_campaign(
            arguments.plan_id, split="development",
            plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=False),
            registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False),
            campaigns_factory=lambda: campaigns,
        )

    if arguments.command == "inspect-bounded-search-campaign":
        return inspect_bounded_search_campaign(
            arguments.plan_id, split=arguments.split,
            plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=False),
            registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            budgets_factory=lambda: LocalCampaignBudgetStore(arguments.runs, create=False),
            execution_inspector=inner,
        )
    request = read_regular_file(arguments.input_root, arguments.budget_request,
                                max_bytes=64 * 1024, allowed_suffixes=frozenset({".json"}))

    def supervise(budget: CampaignBudget) -> CampaignSupervision:
        limits = cast("dict[str, int]", budget.document["limits"])
        return supervise_campaign(
            {"schema_version": 1, "plan_id": arguments.plan_id, "budget_id": budget.budget_id,
             "runs": str(arguments.runs.absolute()), "plans": str(arguments.plans.absolute()),
             "store": str(arguments.store.absolute()), "registry": str(arguments.registry.absolute()),
             "engine_python": None if arguments.engine_python is None else str(arguments.engine_python.absolute())},
            timeout_ms=limits["max_wall_time_ms"],
        )

    return run_bounded_search_campaign(
        arguments.plan_id, request, split=arguments.split,
        plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=False),
        registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
        budgets_factory=lambda: LocalCampaignBudgetStore(arguments.runs, create=True),
        execution_inspector=inner, supervise=supervise, nonce_factory=lambda: secrets.token_hex(16),
    )
