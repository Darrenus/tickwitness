"""Explicit one-time confirmation access under a fixed dataset-root ledger."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from tickwitness.application.confirmation import (
    ConfirmationRepository,
    ExposureRepository,
    SourceReader,
    SourceRecord,
    freeze_confirmation_protocol,
    inspect_confirmation_protocol,
    open_confirmation_protocol,
)
from tickwitness.application.data_access import DatasetReader
from tickwitness.domain.research_contracts.protocols import _hash
from tickwitness.infrastructure.executable_registry import (
    ExecutableRegistryError,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.local_confirmation import (
    LocalConfirmationExposureLedger,
    LocalConfirmationRegistry,
)
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import (
    LocalProtocolRegistry,
    ProtocolNotFoundError,
)
from tickwitness.infrastructure.safe_input import read_regular_file

COMMANDS = frozenset(
    {"freeze-confirmation-protocol", "inspect-confirmation-protocol", "open-confirmation-protocol"}
)


class _Factories(TypedDict):
    source_factory: Callable[[], SourceReader]
    datasets_factory: Callable[[], DatasetReader]
    confirmations_factory: Callable[[], ConfirmationRepository]
    exposures_factory: Callable[[], ExposureRepository]


def _identity(value: str) -> str:
    try:
        return _hash(value, "protocol_id")
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


class _SourceRegistry:
    """The old registries remain responsible for their own immutable closure."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def get(self, protocol_id: str) -> SourceRecord:
        try:
            return LocalExecutableProtocolRegistry(self._root, create=False).get(protocol_id)
        except ExecutableRegistryError as executable_error:
            try:
                return LocalProtocolRegistry(self._root, create=False).get(protocol_id)
            except ProtocolNotFoundError:
                raise executable_error from None


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser(
        "freeze-confirmation-protocol", help="Freeze one whole confirmation-window release"
    )
    freeze.add_argument("source_protocol_id", type=_identity)
    freeze.add_argument("input", help="Relative confirmation request .json")
    freeze.add_argument("--input-root", type=Path, required=True)
    freeze.add_argument("--id-only", action="store_true")
    inspect = commands.add_parser(
        "inspect-confirmation-protocol", help="Inspect declarations and recorded exposure only"
    )
    opening = commands.add_parser(
        "open-confirmation-protocol", help="Irreversibly consume and release the whole window once"
    )
    for command in (inspect, opening):
        command.add_argument("protocol_id", type=_identity)
    for command in (freeze, inspect, opening):
        command.add_argument("--store", type=Path, required=True)
        command.add_argument("--registry", type=Path, required=True)


def execute(arguments: argparse.Namespace) -> tuple[dict[str, object], str]:
    factories: _Factories = {
        "source_factory": lambda: _SourceRegistry(arguments.registry),
        "datasets_factory": lambda: LocalDatasetStore(arguments.store, create=False),
        "confirmations_factory": lambda: LocalConfirmationRegistry(
            arguments.store, create=arguments.command == "freeze-confirmation-protocol"
        ),
        "exposures_factory": lambda: LocalConfirmationExposureLedger(
            arguments.store, create=arguments.command == "freeze-confirmation-protocol"
        ),
    }
    if arguments.command == "freeze-confirmation-protocol":
        request = read_regular_file(
            arguments.input_root,
            arguments.input,
            max_bytes=64 * 1024,
            allowed_suffixes=frozenset({".json"}),
        )
        receipt = freeze_confirmation_protocol(
            request, source_protocol_id=arguments.source_protocol_id, **factories
        )
    elif arguments.command == "inspect-confirmation-protocol":
        receipt = inspect_confirmation_protocol(arguments.protocol_id, **factories)
    else:
        receipt = open_confirmation_protocol(arguments.protocol_id, **factories)
    return receipt, str(receipt["protocol_id"])
