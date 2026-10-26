"""Safe request files and read-only adapters for queue constraints."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.queue_constraints import validate_queue_contracts
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.safe_input import read_regular_file

COMMAND = "validate-queue-constraints"


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        COMMAND, help="Check two external-queue allocations without executing or consuming budget"
    )
    parser.add_argument("protocol_id")
    parser.add_argument("request", help="Relative queue-constraint request .json path")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "confirmation"), default="development")


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Queue constraints permit development evidence only")
    raw = read_regular_file(
        arguments.input_root,
        arguments.request,
        max_bytes=64 * 1024,
        allowed_suffixes=frozenset({".json"}),
    )
    return validate_queue_contracts(
        arguments.protocol_id,
        raw,
        split=arguments.split,
        registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
    ).document
