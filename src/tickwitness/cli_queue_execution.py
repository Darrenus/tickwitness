"""Safe command boundaries for frozen queue families and durable model runs."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.queue_execution import (
    freeze_queue_family,
    inspect_queue_family,
    inspect_queue_run,
    run_queue_family,
    run_queue_model,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.queue_semantics import inspect_queue_semantics
from tickwitness.domain.evidence.run_records import EvidenceValidationError, identity
from tickwitness.domain.research_contracts.queue_family import QUEUE_POLICY_IDS
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.queue_family_registry import LocalQueueFamilyRegistry
from tickwitness.infrastructure.queue_replay import QueueSubprocessReplayAdapter
from tickwitness.infrastructure.safe_input import read_regular_file

COMMANDS = frozenset(
    {
        "freeze-queue-family",
        "run-queue-family",
        "run-queue-model",
        "inspect-queue-family",
        "inspect-queue-run",
        "qualify-queue-pair",
    }
)


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser(
        "freeze-queue-family", help="Freeze two queue models and their shared budget"
    )
    freeze.add_argument("protocol_id", help="Existing executable v2 source protocol")
    freeze.add_argument("family_request", help="Relative family request JSON")
    freeze.add_argument("queue_request", help="Relative queue constraint request JSON")
    freeze.add_argument("--input-root", type=Path, required=True)
    freeze.add_argument("--registry", type=Path, required=True)
    for name in (
        "run-queue-family",
        "run-queue-model",
        "inspect-queue-family",
        "inspect-queue-run",
        "qualify-queue-pair",
    ):
        parser = commands.add_parser(
            name,
            help={
                "run-queue-family": "Execute both models with one shared-budget slot per call",
                "run-queue-model": "Execute one frozen model with one shared-budget slot",
                "inspect-queue-family": "Recheck source and inspect consumed shared-budget slots",
                "inspect-queue-run": "Re-audit committed queue evidence without native execution",
                "qualify-queue-pair": "Check paired queue semantics without issuing a finding",
            }[name],
        )
        parser.add_argument("run_id" if name in ("inspect-queue-run", "qualify-queue-pair") else "family_id")
        if name == "qualify-queue-pair":
            parser.add_argument("other_run_id")
        if name == "run-queue-model":
            parser.add_argument("policy_id", choices=QUEUE_POLICY_IDS)
        parser.add_argument("--runs", type=Path, required=True)
        if name.startswith("run-"):
            parser.add_argument("--engine-python", type=Path)
    for parser in (
        freeze,
        *[commands.choices[name] for name in COMMANDS if name != "freeze-queue-family"],
    ):
        parser.add_argument("--families", type=Path, required=True)
        parser.add_argument("--store", type=Path, required=True)
        parser.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    # The split guard precedes paths, factories and even malformed identities.
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Queue families permit development evidence only")
    identity(
        getattr(
            arguments,
            "protocol_id",
            getattr(arguments, "family_id", getattr(arguments, "run_id", None)),
        )
    )
    if arguments.command == "qualify-queue-pair":
        identity(arguments.other_run_id)
        if arguments.run_id == arguments.other_run_id:
            raise EvidenceValidationError("Queue pair requires two distinct committed runs")

    def families() -> LocalQueueFamilyRegistry:
        return LocalQueueFamilyRegistry(arguments.families, create=False)

    def datasets() -> LocalDatasetStore:
        return LocalDatasetStore(arguments.store, create=False)

    def ledger() -> LocalAttemptLedger:
        return LocalAttemptLedger(arguments.runs, create=arguments.command.startswith("run-"))

    def replay(timeout: int) -> QueueSubprocessReplayAdapter:
        return QueueSubprocessReplayAdapter(
            timeout_seconds=timeout, python_executable=arguments.engine_python
        )

    if arguments.command == "freeze-queue-family":
        requests = [
            read_regular_file(
                arguments.input_root,
                name,
                max_bytes=64 * 1024,
                allowed_suffixes=frozenset({".json"}),
            )
            for name in (arguments.family_request, arguments.queue_request)
        ]
        return freeze_queue_family(
            arguments.protocol_id,
            requests[0],
            requests[1],
            split=arguments.split,
            registry_factory=lambda: LocalExecutableProtocolRegistry(
                arguments.registry, create=False
            ),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            families_factory=lambda: LocalQueueFamilyRegistry(arguments.families),
        ).document
    if arguments.command == "inspect-queue-run":
        return inspect_queue_run(
            arguments.run_id,
            split=arguments.split,
            families_factory=families,
            datasets_factory=datasets,
            ledger_factory=ledger,
        )
    if arguments.command == "qualify-queue-pair":
        return inspect_queue_semantics(
            arguments.run_id, arguments.other_run_id, split=arguments.split,
            families_factory=families, datasets_factory=datasets, ledger_factory=ledger,
        )
    if arguments.command == "inspect-queue-family":
        return inspect_queue_family(
            arguments.family_id,
            split=arguments.split,
            families_factory=families,
            datasets_factory=datasets,
            ledger_factory=ledger,
        )
    if arguments.command == "run-queue-model":
        return run_queue_model(
            arguments.family_id,
            arguments.policy_id,
            split=arguments.split,
            families_factory=families,
            datasets_factory=datasets,
            ledger_factory=ledger,
            replay_factory=replay,
        ).document
    return run_queue_family(
        arguments.family_id,
        split=arguments.split,
        families_factory=families,
        datasets_factory=datasets,
        ledger_factory=ledger,
        replay_factory=replay,
    )
