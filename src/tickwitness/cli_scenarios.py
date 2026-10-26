"""Safe CLI boundaries for declared receive-clock stress and durable evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from tickwitness.application.experiments import inspect_attempt
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.scenario_comparison import compare_scenario_runs
from tickwitness.application.scenario_execution import inspect_scenario_run, run_scenario
from tickwitness.application.scenarios import validate_scenario_contracts
from tickwitness.domain.evidence.run_records import parse
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

COMMAND = "validate-scenario"
COMMANDS = frozenset(
    {COMMAND, "run-scenario", "inspect-scenario-run", "inspect-scenario-attempt", "compare-scenario-runs"}
)


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    validate = commands.add_parser(
        COMMAND, help="Check development input constraints without execution or budget use"
    )
    execute = commands.add_parser(
        "run-scenario", help="Consume parent-protocol budget for coupled receive-clock stress"
    )
    for parser in (validate, execute):
        parser.add_argument("protocol_id")
        parser.add_argument("assumption_request", help="Relative assumption request .json path")
        parser.add_argument("scenario_request", help="Relative scenario request .json path")
        parser.add_argument("--input-root", type=Path, required=True)
        parser.add_argument("--store", type=Path, required=True)
        parser.add_argument("--registry", type=Path, required=True)
        parser.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )
    execute.add_argument("--runs", type=Path, required=True)
    execute.add_argument("--engine-python", type=Path)
    inspect = commands.add_parser(
        "inspect-scenario-run", help="Recompute a committed scenario view and accounting"
    )
    inspect.add_argument("run_id")
    inspect.add_argument("--runs", type=Path, required=True)
    inspect.add_argument("--registry", type=Path, required=True)
    inspect.add_argument("--store", type=Path, required=True)
    attempt = commands.add_parser(
        "inspect-scenario-attempt", help="Inspect consumed slot, persistent intent and outcome"
    )
    attempt.add_argument("attempt_id")
    attempt.add_argument("--runs", type=Path, required=True)
    comparison = commands.add_parser(
        "compare-scenario-runs", help="Re-audit a committed baseline/scenario pair and locate changes"
    )
    comparison.add_argument("baseline_run_id")
    comparison.add_argument("scenario_run_id")
    comparison.add_argument("--runs", type=Path, required=True)
    comparison.add_argument("--registry", type=Path, required=True)
    comparison.add_argument("--store", type=Path, required=True)
    comparison.add_argument(
        "--split", choices=("development", "confirmation"), default="development"
    )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "compare-scenario-runs":
        comparison = compare_scenario_runs(
            arguments.baseline_run_id,
            arguments.scenario_run_id,
            split=arguments.split,
            ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False),
            registry_factory=lambda: LocalExecutableProtocolRegistry(
                arguments.registry, create=False
            ),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
        )
        return {"comparison_id": comparison.comparison_id, **comparison.document}
    if arguments.command == "inspect-scenario-attempt":
        ledger = LocalAttemptLedger(arguments.runs, create=False)
        output = inspect_attempt(arguments.attempt_id, ledger)
        intent = ledger.get_intent(arguments.attempt_id)
        return {**output, "scenario_intent": None if intent is None else parse(intent)}
    if arguments.command == "inspect-scenario-run":
        return inspect_scenario_run(
            arguments.run_id,
            ledger=LocalAttemptLedger(arguments.runs, create=False),
            registry=LocalExecutableProtocolRegistry(arguments.registry, create=False),
            datasets=LocalDatasetStore(arguments.store, create=False),
        )
    # Deny confirmation even before opening the user-supplied request files.
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Scenario contracts permit development evidence only")
    requests = [
        read_regular_file(
            arguments.input_root,
            name,
            max_bytes=64 * 1024,
            allowed_suffixes=frozenset({".json"}),
        )
        for name in (arguments.assumption_request, arguments.scenario_request)
    ]
    if arguments.command == "run-scenario":
        return asdict(
            run_scenario(
                arguments.protocol_id,
                requests[0],
                requests[1],
                split=arguments.split,
                registry_factory=lambda: LocalExecutableProtocolRegistry(
                    arguments.registry, create=False
                ),
                datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
                ledger_factory=lambda: LocalAttemptLedger(arguments.runs),
                engine_factory=lambda timeout: SubprocessReplayAdapter(
                    timeout_seconds=timeout, python_executable=arguments.engine_python
                ),
            )
        )
    receipt = validate_scenario_contracts(
        arguments.protocol_id,
        requests[0],
        requests[1],
        split=arguments.split,
        registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
    )
    return receipt.document
