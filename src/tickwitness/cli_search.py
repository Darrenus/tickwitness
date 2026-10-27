"""Development-only proposal planning; no replay, attempt ledger or search verdict."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_planning import freeze_search_plan, inspect_search_plan
from tickwitness.domain.evidence.run_records import identity
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry

COMMANDS = frozenset({"freeze-search-plan", "inspect-search-plan"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser(
        "freeze-search-plan", help="Freeze a receive-delay proposal journal"
    )
    freeze.add_argument("protocol_id")
    freeze.add_argument("assumption_request")
    freeze.add_argument("search_request")
    freeze.add_argument("--input-root", required=True, type=Path)
    inspect = commands.add_parser(
        "inspect-search-plan",
        help="Rebuild proposals and revalidate their actual development source",
    )
    inspect.add_argument("plan_id")
    for command in (freeze, inspect):
        command.add_argument("--registry", required=True, type=Path)
        command.add_argument("--store", required=True, type=Path)
        command.add_argument("--plans", required=True, type=Path)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Search planning permits development evidence only")
    if arguments.command == "inspect-search-plan":
        return inspect_search_plan(
            arguments.plan_id,
            split=arguments.split,
            registry_factory=lambda: LocalExecutableProtocolRegistry(
                arguments.registry, create=False
            ),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=False),
        )
    identity(arguments.protocol_id)
    assumption, search = (
        read_regular_file(
            arguments.input_root,
            name,
            max_bytes=64 * 1024,
            allowed_suffixes=frozenset({".json"}),
        )
        for name in (arguments.assumption_request, arguments.search_request)
    )
    return freeze_search_plan(
        arguments.protocol_id,
        assumption,
        search,
        split=arguments.split,
        registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
        plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=True),
    )
