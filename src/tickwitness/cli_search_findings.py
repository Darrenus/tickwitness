"""Freeze separate stress-report authority and re-audit local campaign conclusions."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_findings import (
    evaluate_search_findings,
    freeze_search_finding_protocol,
    inspect_search_finding_protocol,
)
from tickwitness.cli_campaign_budgets import inspect_bounded_campaign_paths
from tickwitness.domain.evidence.run_records import identity
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry

COMMANDS = frozenset(
    {
        "freeze-search-finding-protocol",
        "inspect-search-finding-protocol",
        "evaluate-search-findings",
    }
)


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser(
        "freeze-search-finding-protocol", help="Freeze a separate conditional stress criterion"
    )
    freeze.add_argument("plan_id")
    freeze.add_argument("request")
    freeze.add_argument("--input-root", required=True, type=Path)
    freeze.add_argument("--plans", required=True, type=Path)
    inspect = commands.add_parser(
        "inspect-search-finding-protocol", help="Inspect frozen stress-report authority"
    )
    inspect.add_argument("protocol_id")
    evaluate = commands.add_parser(
        "evaluate-search-findings", help="Re-audit bounded evidence and report scoped conclusions"
    )
    evaluate.add_argument("protocol_id")
    for name in ("plans", "store", "registry", "runs"):
        evaluate.add_argument(f"--{name}", required=True, type=Path)
    for command in (freeze, inspect, evaluate):
        command.add_argument("--finding-registry", required=True, type=Path)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Search findings permit development evidence only")
    if arguments.command == "freeze-search-finding-protocol":
        identity(arguments.plan_id)
        request = read_regular_file(
            arguments.input_root,
            arguments.request,
            max_bytes=16 * 1024,
            allowed_suffixes=frozenset({".json"}),
        )
        return freeze_search_finding_protocol(
            arguments.plan_id,
            request,
            split=arguments.split,
            plans_factory=lambda: LocalSearchPlanRegistry(arguments.plans, create=False),
            findings_factory=lambda: LocalSearchFindingRegistry(
                arguments.finding_registry, create=True
            ),
        )
    identity(arguments.protocol_id)
    if arguments.command == "inspect-search-finding-protocol":
        return inspect_search_finding_protocol(
            arguments.protocol_id,
            split=arguments.split,
            findings_factory=lambda: LocalSearchFindingRegistry(
                arguments.finding_registry, create=False
            ),
        )
    return evaluate_search_findings(
        arguments.protocol_id,
        split=arguments.split,
        findings_factory=lambda: LocalSearchFindingRegistry(
            arguments.finding_registry, create=False
        ),
        campaign_inspector=lambda plan_id: inspect_bounded_campaign_paths(
            plan_id,
            split=arguments.split,
            plans=arguments.plans,
            registry=arguments.registry,
            store=arguments.store,
            runs=arguments.runs,
        ),
    )
