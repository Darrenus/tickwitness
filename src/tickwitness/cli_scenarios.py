"""Safe CLI files and storage adapters for read-only stress-contract validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.scenarios import validate_scenario_contracts
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.safe_input import read_regular_file

COMMAND = "validate-scenario"


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        COMMAND, help="Check a declared stress candidate against development input constraints"
    )
    parser.add_argument("protocol_id")
    parser.add_argument("assumption_request", help="Relative assumption request .json path")
    parser.add_argument("scenario_request", help="Relative scenario request .json path")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "confirmation"), default="development")


def execute(arguments: argparse.Namespace) -> dict[str, object]:
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
    receipt = validate_scenario_contracts(
        arguments.protocol_id,
        requests[0],
        requests[1],
        split=arguments.split,
        registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
    )
    return receipt.document
