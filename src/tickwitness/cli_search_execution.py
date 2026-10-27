"""Automatic development evaluations and read-only durable campaign inspection."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_execution import inspect_search_campaign, run_search_plan
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

COMMANDS = frozenset({"run-search-plan", "inspect-search-campaign"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = commands.add_parser("run-search-plan", help="Evaluate unique candidates using original protocol slots")
    inspect = commands.add_parser("inspect-search-campaign", help="Re-audit candidate/attempt/outcome associations")
    run.add_argument("--engine-python", type=Path)
    for command in (run, inspect):
        command.add_argument("plan_id")
        command.add_argument("--plans", required=True, type=Path)
        command.add_argument("--store", required=True, type=Path)
        command.add_argument("--registry", required=True, type=Path)
        command.add_argument("--runs", required=True, type=Path)
        command.add_argument("--split", choices=("development", "confirmation"), default="development")


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Search execution permits development evidence only")
    if arguments.command == "inspect-search-campaign":
        return inspect_search_campaign(
            arguments.plan_id, split=arguments.split,
            plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=False),
            registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False),
            campaigns_factory=lambda: LocalSearchCampaignStore(arguments.runs, create=False),
        )
    return run_search_plan(
        arguments.plan_id, split=arguments.split,
        plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=False),
        registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
        ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=True),
        ledger_reader_factory=lambda: LocalAttemptLedger(arguments.runs, create=False),
        campaigns_factory=lambda: LocalSearchCampaignStore(arguments.runs, create=True),
        engine_factory=lambda timeout: SubprocessReplayAdapter(
            timeout_seconds=timeout, python_executable=arguments.engine_python,
        ),
        nonce_factory=lambda: secrets.token_hex(16),
    )
