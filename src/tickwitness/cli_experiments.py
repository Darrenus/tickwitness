"""CLI adapters for versioned development experiments and portable evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import cast

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
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.evidence_bundles import export_bundle, read_bundle
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
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
        receipt = inspect_experiment(
            arguments.protocol_id,
            LocalExecutableProtocolRegistry(arguments.registry, create=False),
            LocalDatasetStore(arguments.store, create=False),
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
        return inspect_attempt(
            arguments.attempt_id, LocalAttemptLedger(arguments.runs, create=False)
        ), arguments.attempt_id
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
