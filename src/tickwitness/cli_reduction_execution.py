"""Execute origin prefixes against the source protocol's existing attempt ledger."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from tickwitness.application.reduction_execution import (
    inspect_reduction_run,
    run_reduction_input,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.cli_reductions import _source_path
from tickwitness.domain.evidence.run_records import EvidenceValidationError, identity
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.reduction_bundles import LocalReductionBundles
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

COMMANDS = frozenset({"run-reduction-input", "inspect-reduction-run"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = commands.add_parser(
        "run-reduction-input", help="Replay a complete prefix using the original shared budget"
    )
    run.add_argument("preparation", type=Path)
    run.add_argument("--expected-preparation-id", required=True)
    run.add_argument("--engine-python", type=Path)
    inspect = commands.add_parser(
        "inspect-reduction-run", help="Rebuild committed prefix state evidence without replay"
    )
    inspect.add_argument("run_id")
    for command in (run, inspect):
        command.add_argument("--source-evidence", required=True)
        command.add_argument("--input-root", type=Path, required=True)
        command.add_argument("--runs", type=Path, required=True)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Reduction execution permits development evidence only")
    if arguments.command == "run-reduction-input":
        identity(arguments.expected_preparation_id)
        preparation = LocalReductionBundles(arguments.input_root).read(arguments.preparation)
        if preparation.preparation_id != arguments.expected_preparation_id:
            raise EvidenceValidationError("Preparation differs from expected-preparation-id")
    else:
        identity(arguments.run_id)
    source = read_search_evidence_bundle(
        _source_path(arguments.input_root, arguments.source_evidence)
    )
    if arguments.command == "inspect-reduction-run":
        return inspect_reduction_run(
            arguments.run_id,
            source=source,
            split=arguments.split,
            ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False),
        )
    result = run_reduction_input(
        preparation,
        source,
        expected_preparation_id=arguments.expected_preparation_id,
        split=arguments.split,
        ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False),
        engine_factory=lambda timeout: SubprocessReplayAdapter(
            timeout_seconds=timeout, python_executable=arguments.engine_python
        ),
    )
    return asdict(result)
