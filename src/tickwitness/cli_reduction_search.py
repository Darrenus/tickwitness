"""CLI for finite local reduction, cancellation and independently audited reports."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.reduction_search import (
    cancel_reduction_search,
    freeze_reduction_search,
    inspect_reduction_search,
    run_reduction_search,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.cli_reductions import _source_path
from tickwitness.domain.evidence.run_records import identity
from tickwitness.domain.reduction.search import load_reduction_search_request
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

COMMANDS = frozenset(
    {
        "freeze-reduction-search",
        "run-reduction-search",
        "inspect-reduction-search",
        "cancel-reduction-search",
    }
)


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser(
        "freeze-reduction-search", help="Freeze a finite local policy for an actual false witness"
    )
    freeze.add_argument("source", help="Relative source evidence under --input-root")
    freeze.add_argument("request", help="Relative reduction search request .json")
    freeze.add_argument("--expected-bundle-id", required=True)
    freeze.add_argument("--expected-report-id", required=True)
    run = commands.add_parser(
        "run-reduction-search", help="Reduce using only the original protocol's remaining slots"
    )
    run.add_argument("--engine-python", type=Path)
    inspect = commands.add_parser(
        "inspect-reduction-search", help="Recompute a persisted reduction search without execution"
    )
    cancel = commands.add_parser(
        "cancel-reduction-search", help="Request cancellation before dispatching another candidate"
    )
    for command in (run, inspect, cancel):
        command.add_argument("plan_id")
        command.add_argument("--source-evidence", required=True)
    for command in (freeze, run, inspect, cancel):
        command.add_argument("--input-root", required=True, type=Path)
        command.add_argument("--runs", required=True, type=Path)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Reduction search permits development evidence only")
    if arguments.command == "freeze-reduction-search":
        identity(arguments.expected_bundle_id)
        identity(arguments.expected_report_id)
        request = read_regular_file(
            arguments.input_root,
            arguments.request,
            max_bytes=16 * 1024,
            allowed_suffixes=frozenset({".json"}),
        )
        load_reduction_search_request(request)
        source_name = arguments.source
    else:
        identity(arguments.plan_id)
        source_name = arguments.source_evidence
    source = read_search_evidence_bundle(_source_path(arguments.input_root, source_name))
    def ledger_factory() -> LocalAttemptLedger:
        return LocalAttemptLedger(arguments.runs, create=False)
    if arguments.command == "freeze-reduction-search":
        return freeze_reduction_search(
            source,
            request,
            expected_bundle_id=arguments.expected_bundle_id,
            expected_report_id=arguments.expected_report_id,
            split=arguments.split,
            ledger_factory=ledger_factory,
            store_factory=lambda: LocalReductionCampaignStore(arguments.runs, create=True),
        )
    if arguments.command == "inspect-reduction-search":
        return inspect_reduction_search(
            arguments.plan_id,
            source=source,
            split=arguments.split,
            ledger_factory=ledger_factory,
            store_factory=lambda: LocalReductionCampaignStore(arguments.runs, create=False),
        )
    if arguments.command == "cancel-reduction-search":
        return cancel_reduction_search(
            arguments.plan_id,
            source=source,
            split=arguments.split,
            ledger_factory=ledger_factory,
            store_factory=lambda: LocalReductionCampaignStore(arguments.runs, create=True),
        )
    return run_reduction_search(
        arguments.plan_id,
        source=source,
        split=arguments.split,
        ledger_factory=ledger_factory,
        store_factory=lambda: LocalReductionCampaignStore(arguments.runs, create=True),
        engine_factory=lambda timeout: SubprocessReplayAdapter(
            timeout_seconds=timeout, python_executable=arguments.engine_python
        ),
    )
