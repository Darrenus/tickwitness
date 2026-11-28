"""CLI adapters for versioned development experiments and portable evidence."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from tickwitness.application.data_access import MAX_DATA_BYTES
from tickwitness.application.datasets import DatasetRecord
from tickwitness.application.experiments import (
    export_run,
    freeze_experiment,
    inspect_attempt,
    inspect_experiment,
    run_artifacts,
    run_experiment,
    verify_package,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError, identity, parse
from tickwitness.domain.evidence.verification import verify_artifacts
from tickwitness.infrastructure.attempt_ledger import AttemptNotFoundError, LocalAttemptLedger
from tickwitness.infrastructure.evidence_bundles import export_bundle, read_bundle
from tickwitness.infrastructure.executable_registry import (
    ExecutableProtocolNotFoundError,
    ExecutableProtocolRecord,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.local_dataset_store import DatasetNotFoundError, LocalDatasetStore
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

COMMANDS = frozenset(
    {
        "freeze-experiment",
        "inspect-experiment",
        "replay-protocol",
        "inspect-attempt",
        "inspect-run",
        "export-evidence",
        "verify-evidence",
    }
)


InspectionCommand = Literal["inspect-experiment", "inspect-attempt"]
InspectionLookup = Literal[
    "executable_registry",
    "dataset_store",
    "executable_protocol",
    "referenced_dataset",
    "attempt_ledger",
    "committed_attempt",
]
InspectionCode = Literal["research_evidence_not_found", "dataset_not_found"]


class InspectionNotFoundError(ValueError):
    """Add actual lookup context without upgrading a backend's absence claim."""

    reason = "inspection_evidence_not_found"

    def __init__(
        self,
        message: str,
        *,
        code: InspectionCode,
        command: InspectionCommand,
        requested_id: str,
        lookup: InspectionLookup,
        resource_id: str | None,
    ) -> None:
        self.code = code
        self.command = command
        self.requested_id = requested_id
        self.lookup = lookup
        self.resource_id = resource_id
        super().__init__(message)


def _inspection_lookup[T](
    operation: Callable[[], T],
    *,
    not_found: (
        type[ExecutableProtocolNotFoundError]
        | type[DatasetNotFoundError]
        | type[AttemptNotFoundError]
    ),
    code: InspectionCode,
    command: InspectionCommand,
    requested_id: str,
    lookup: InspectionLookup,
    resource_id: str | None = None,
) -> T:
    try:
        return operation()
    except not_found as error:
        raise InspectionNotFoundError(
            str(error),
            code=code,
            command=command,
            requested_id=requested_id,
            lookup=lookup,
            resource_id=resource_id,
        ) from error


@dataclass(frozen=True, slots=True)
class _InspectionRegistry:
    source: LocalExecutableProtocolRegistry
    requested_id: str

    def get(self, protocol_id: str) -> ExecutableProtocolRecord:
        return _inspection_lookup(
            lambda: self.source.get(protocol_id),
            not_found=ExecutableProtocolNotFoundError,
            code="research_evidence_not_found",
            command="inspect-experiment",
            requested_id=self.requested_id,
            lookup="executable_protocol",
            resource_id=protocol_id,
        )


@dataclass(frozen=True, slots=True)
class _InspectionDatasets:
    source: LocalDatasetStore
    requested_id: str

    def get(self, dataset_id: str) -> DatasetRecord:
        return _inspection_lookup(
            lambda: self.source.get(dataset_id),
            not_found=DatasetNotFoundError,
            code="dataset_not_found",
            command="inspect-experiment",
            requested_id=self.requested_id,
            lookup="referenced_dataset",
            resource_id=dataset_id,
        )

    def read_normalized(self, dataset_id: str, *, max_bytes: int = MAX_DATA_BYTES) -> bytes:
        return self.source.read_normalized(dataset_id, max_bytes=max_bytes)


def _content_identity(value: str) -> str:
    try:
        return identity(value)
    except EvidenceValidationError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser(
        "freeze-experiment", help="Freeze the supported executable v2 protocol"
    )
    freeze.add_argument("input", help="Relative executable request .json")
    freeze.add_argument("--input-root", type=Path, required=True)
    freeze.add_argument("--development-dataset", required=True, type=_content_identity)
    freeze.add_argument("--confirmation-dataset", required=True, type=_content_identity)
    freeze.add_argument("--id-only", action="store_true")
    inspect = commands.add_parser("inspect-experiment", help="Verify v2 declaration references")
    inspect.add_argument("protocol_id", type=_content_identity)
    replay = commands.add_parser(
        "replay-protocol", help="Reserve budget and replay the frozen development baseline"
    )
    replay.add_argument("protocol_id", type=_content_identity)
    replay.add_argument("--split", choices=("development", "confirmation"), default="development")
    replay.add_argument("--engine-python", type=Path)
    replay.add_argument("--id-only", action="store_true")
    inspect_run = commands.add_parser("inspect-run", help="Audit a committed run and valuation")
    inspect_run.add_argument("run_id", type=_content_identity)
    exporter = commands.add_parser(
        "export-evidence", help="Atomically export a validated development evidence directory"
    )
    exporter.add_argument("run_id", type=_content_identity)
    exporter.add_argument("destination", type=Path)
    exporter.add_argument("--id-only", action="store_true")
    attempt = commands.add_parser(
        "inspect-attempt", help="Inspect consumed reservation and any final outcome"
    )
    attempt.add_argument("attempt_id", type=_content_identity)
    verifier = commands.add_parser(
        "verify-evidence", help="Offline integrity, binding and accounting verification"
    )
    verifier.add_argument("directory", type=Path)
    for command in (freeze, inspect, replay, inspect_run, exporter):
        command.add_argument("--registry", type=Path, required=True)
        command.add_argument("--store", type=Path, required=True)
    for command in (replay, inspect_run, exporter, attempt):
        command.add_argument("--runs", type=Path, required=True)


def execute(arguments: argparse.Namespace) -> tuple[dict[str, object], str]:
    if arguments.command == "freeze-experiment":
        request = read_regular_file(
            arguments.input_root,
            arguments.input,
            max_bytes=128 * 1024,
            allowed_suffixes=frozenset({".json"}),
        )
        receipt = freeze_experiment(
            request,
            development_dataset_id=arguments.development_dataset,
            confirmation_dataset_id=arguments.confirmation_dataset,
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry),
        )
        return asdict(receipt), receipt.protocol_id
    if arguments.command == "inspect-experiment":
        registry = _inspection_lookup(
            lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
            not_found=ExecutableProtocolNotFoundError,
            code="research_evidence_not_found",
            command="inspect-experiment",
            requested_id=arguments.protocol_id,
            lookup="executable_registry",
        )
        datasets = _inspection_lookup(
            lambda: LocalDatasetStore(arguments.store, create=False),
            not_found=DatasetNotFoundError,
            code="dataset_not_found",
            command="inspect-experiment",
            requested_id=arguments.protocol_id,
            lookup="dataset_store",
        )
        receipt = inspect_experiment(
            arguments.protocol_id,
            _InspectionRegistry(registry, arguments.protocol_id),
            _InspectionDatasets(datasets, arguments.protocol_id),
        )
        return asdict(receipt), receipt.protocol_id
    if arguments.command == "replay-protocol":
        submission = run_experiment(
            arguments.protocol_id,
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
        return asdict(submission), submission.run_id
    if arguments.command == "inspect-attempt":
        ledger = _inspection_lookup(
            lambda: LocalAttemptLedger(arguments.runs, create=False),
            not_found=AttemptNotFoundError,
            code="research_evidence_not_found",
            command="inspect-attempt",
            requested_id=arguments.attempt_id,
            lookup="attempt_ledger",
        )
        inspected = _inspection_lookup(
            lambda: inspect_attempt(arguments.attempt_id, ledger),
            not_found=AttemptNotFoundError,
            code="research_evidence_not_found",
            command="inspect-attempt",
            requested_id=arguments.attempt_id,
            lookup="committed_attempt",
            resource_id=arguments.attempt_id,
        )
        return inspected, arguments.attempt_id
    if arguments.command == "verify-evidence":
        result = verify_package(read_bundle(arguments.directory))
        return result, cast("str", result["bundle_id"])
    ledger = LocalAttemptLedger(arguments.runs, create=False)
    registry = LocalExecutableProtocolRegistry(arguments.registry, create=False)
    datasets = LocalDatasetStore(arguments.store, create=False)
    if arguments.command == "export-evidence":
        result = export_run(
            arguments.run_id,
            ledger=ledger,
            registry=registry,
            datasets=datasets,
            exporter=lambda artifacts: export_bundle(arguments.destination, artifacts),
        )
        return result, cast("str", result["bundle_id"])
    artifacts = run_artifacts(arguments.run_id, ledger=ledger, registry=registry, datasets=datasets)
    return {
        "run_id": arguments.run_id,
        "receipt": parse(artifacts["attempt"]),
        "evaluation": parse(artifacts["evaluation"], limit=4 * 1024 * 1024),
        "verification": verify_artifacts(artifacts),
    }, arguments.run_id
