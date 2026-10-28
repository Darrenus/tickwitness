"""Portable content closure for scoped search evidence, with no execution authority."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_evidence import export_search_evidence, verify_search_package
from tickwitness.application.search_execution import CampaignReader
from tickwitness.cli_campaign_budgets import inspect_bounded_campaign_paths
from tickwitness.domain.evidence.run_records import EvidenceValidationError, identity
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_campaign_store import (
    LocalSearchCampaignStore,
    SearchCampaignNotFoundError,
)
from tickwitness.infrastructure.search_evidence_bundles import (
    SearchEvidenceBundle,
    export_search_evidence_bundle,
    read_search_evidence_bundle,
)
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry

COMMANDS = frozenset({"export-search-evidence", "verify-search-evidence"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    export = commands.add_parser(
        "export-search-evidence", help="Seal a pinned reaudited search report"
    )
    export.add_argument("protocol_id")
    export.add_argument("--expected-report-id", required=True)
    for name in ("plans", "store", "registry", "runs", "finding-registry", "output"):
        export.add_argument(f"--{name}", required=True, type=Path)
    verify = commands.add_parser(
        "verify-search-evidence", help="Rebuild search findings from a portable package"
    )
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--expected-bundle-id")
    for command in (export, verify):
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Search evidence permits development artifacts only")
    if arguments.command == "verify-search-evidence":
        if arguments.expected_bundle_id is not None:
            identity(arguments.expected_bundle_id)
        return verify_search_package(
            read_search_evidence_bundle(arguments.bundle),
            expected_bundle_id=arguments.expected_bundle_id,
            split=arguments.split,
        )
    identity(arguments.protocol_id)
    identity(arguments.expected_report_id)
    destination = arguments.output.resolve()
    for source in (
        arguments.plans,
        arguments.store,
        arguments.registry,
        arguments.runs,
        arguments.finding_registry,
    ):
        if destination.is_relative_to(source.resolve()):
            raise EvidenceValidationError(
                "Evidence output must be outside all original source roots"
            )

    def campaigns(plan_id: str) -> CampaignReader | None:
        budgets = LocalCampaignBudgetStore(arguments.runs, create=False)
        try:
            return LocalSearchCampaignStore(budgets.managed_root(plan_id), create=False)
        except SearchCampaignNotFoundError:
            return None

    def publish(artifacts: Mapping[str, bytes]) -> SearchEvidenceBundle:
        exported = export_search_evidence_bundle(arguments.output, artifacts)
        reread = read_search_evidence_bundle(arguments.output)
        if reread.bundle_id != exported.bundle_id or reread.artifacts != exported.artifacts:
            raise EvidenceValidationError("Published search package changed before readback")
        return reread

    return export_search_evidence(
        arguments.protocol_id,
        expected_report_id=arguments.expected_report_id,
        split=arguments.split,
        findings_factory=lambda: LocalSearchFindingRegistry(
            arguments.finding_registry, create=False
        ),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
        budgets_factory=lambda: LocalCampaignBudgetStore(arguments.runs, create=False),
        campaigns_factory=campaigns,
        ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False),
        campaign_inspector=lambda plan_id: inspect_bounded_campaign_paths(
            plan_id,
            split=arguments.split,
            plans=arguments.plans,
            registry=arguments.registry,
            store=arguments.store,
            runs=arguments.runs,
        ),
        producer_version=version("tickwitness"),
        publisher=publish,
    )
