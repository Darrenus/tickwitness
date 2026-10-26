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
from tickwitness.domain.research_contracts.queue_family import QUEUE_POLICY_IDS
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.queue_family_registry import LocalQueueFamilyRegistry
from tickwitness.infrastructure.queue_replay import QueueSubprocessReplayAdapter
from tickwitness.infrastructure.safe_input import read_regular_file

COMMANDS = frozenset({"freeze-queue-family", "run-queue-family", "run-queue-model",
                      "inspect-queue-family", "inspect-queue-run"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser("freeze-queue-family", help="Freeze two queue models and their shared budget")
    freeze.add_argument("protocol_id", help="Existing executable v2 source protocol")
    freeze.add_argument("family_request", help="Relative family request JSON")
    freeze.add_argument("queue_request", help="Relative queue constraint request JSON")
    freeze.add_argument("--input-root", type=Path, required=True)
    freeze.add_argument("--registry", type=Path, required=True)
    for name in ("run-queue-family", "run-queue-model", "inspect-queue-family", "inspect-queue-run"):
        parser = commands.add_parser(name, help={
            "run-queue-family": "Execute the frozen front/back models, consuming one slot per call",
            "run-queue-model": "Explicitly execute one frozen model with one shared-budget slot",
            "inspect-queue-family": "Recheck source and inspect consumed shared-budget slots",
            "inspect-queue-run": "Re-audit committed queue evidence without native execution",
        }[name])
        parser.add_argument("run_id" if name == "inspect-queue-run" else "family_id")
        if name == "run-queue-model":
            parser.add_argument("policy_id", choices=QUEUE_POLICY_IDS)
        parser.add_argument("--runs", type=Path, required=True)
        if name.startswith("run-"):
            parser.add_argument("--engine-python", type=Path)
    for parser in (freeze, *[commands.choices[name] for name in COMMANDS if name != "freeze-queue-family"]):
        parser.add_argument("--families", type=Path, required=True)
        parser.add_argument("--store", type=Path, required=True)
        parser.add_argument("--split", choices=("development", "confirmation"), default="development")


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    # The split guard precedes paths, factories and even malformed identities.
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Queue families permit development evidence only")
    common = {
        "split": arguments.split,
        "families_factory": lambda: LocalQueueFamilyRegistry(arguments.families, create=False),
        "datasets_factory": lambda: LocalDatasetStore(arguments.store, create=False),
    }
    if arguments.command == "freeze-queue-family":
        requests = [read_regular_file(arguments.input_root, name, max_bytes=64 * 1024,
                                     allowed_suffixes=frozenset({".json"}))
                    for name in (arguments.family_request, arguments.queue_request)]
        return freeze_queue_family(
            arguments.protocol_id, requests[0], requests[1], split=arguments.split,
            registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            families_factory=lambda: LocalQueueFamilyRegistry(arguments.families),
        ).document
    if arguments.command == "inspect-queue-run":
        return inspect_queue_run(arguments.run_id, **common,
                                 ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False))
    if arguments.command == "inspect-queue-family":
        return inspect_queue_family(arguments.family_id, **common,
                                    ledger_factory=lambda: LocalAttemptLedger(arguments.runs, create=False))
    execute_common = {
        **common,
        "ledger_factory": lambda: LocalAttemptLedger(arguments.runs),
        "replay_factory": lambda timeout: QueueSubprocessReplayAdapter(
            timeout_seconds=timeout, python_executable=arguments.engine_python),
    }
    if arguments.command == "run-queue-model":
        return run_queue_model(arguments.family_id, arguments.policy_id, **execute_common).document
    return run_queue_family(arguments.family_id, **execute_common)
