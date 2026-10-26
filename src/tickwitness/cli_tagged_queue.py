"""Safe CLI boundaries for frozen tagged-participant reconstruction."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_queue_execution import (
    freeze_tagged_queue, inspect_tagged_queue, inspect_tagged_queue_run,
    run_tagged_queue_model, run_tagged_queue_pair,
)
from tickwitness.domain.evidence.run_records import identity
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry
from tickwitness.infrastructure.tagged_queue_replay import TaggedQueueSubprocessReplayAdapter

COMMANDS = frozenset({"freeze-tagged-queue", "inspect-tagged-queue", "run-tagged-queue-pair",
                      "run-tagged-queue-model", "inspect-tagged-queue-run"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser("freeze-tagged-queue", help="Freeze tagged claim, public projection, intervention and shared budget")
    freeze.add_argument("source_protocol_id")
    freeze.add_argument("request")
    freeze.add_argument("queue_request")
    freeze.add_argument("--input-root", required=True, type=Path)
    parsers = [freeze]
    for name in ("inspect-tagged-queue", "run-tagged-queue-pair", "run-tagged-queue-model", "inspect-tagged-queue-run"):
        command = commands.add_parser(name, help="Verify or execute conditional tagged reconstruction")
        command.add_argument("run_id" if name == "inspect-tagged-queue-run" else "protocol_id")
        command.add_argument("--ledger", required=True, type=Path)
        if name == "run-tagged-queue-model":
            command.add_argument("policy_id", choices=TAGGED_POLICY_IDS)
        if name.startswith("run-"):
            command.add_argument("--engine-python", type=Path)
        parsers.append(command)
    for command in parsers:
        command.add_argument("--store", required=True, type=Path)
        command.add_argument("--registry", required=True, type=Path)
        command.add_argument("--split", choices=("development", "confirmation"), default="development")


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    # Refuse confirmation before reading files, constructing repositories or a worker.
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Tagged reconstruction permits development only")
    if arguments.command == "freeze-tagged-queue":
        identity(arguments.source_protocol_id)
        request, gross = (read_regular_file(arguments.input_root, name, max_bytes=64 * 1024,
                                           allowed_suffixes=frozenset({".json"}))
                          for name in (arguments.request, arguments.queue_request))
        return freeze_tagged_queue(arguments.source_protocol_id, request, gross,
            split=arguments.split,
            registry_factory=lambda: LocalExecutableProtocolRegistry(arguments.registry, create=False),
            datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            protocols_factory=lambda: LocalTaggedQueueRegistry(arguments.registry, create=True)).document

    def protocols() -> LocalTaggedQueueRegistry:
        return LocalTaggedQueueRegistry(arguments.registry, create=False)

    def datasets() -> LocalDatasetStore:
        return LocalDatasetStore(arguments.store, create=False)

    def ledger() -> LocalAttemptLedger:
        return LocalAttemptLedger(arguments.ledger, create=arguments.command.startswith("run-"))

    if arguments.command == "inspect-tagged-queue-run":
        return inspect_tagged_queue_run(arguments.run_id, split=arguments.split,
            protocols_factory=protocols, datasets_factory=datasets, ledger_factory=ledger)
    if arguments.command == "inspect-tagged-queue":
        return inspect_tagged_queue(arguments.protocol_id, split=arguments.split,
            protocols_factory=protocols, datasets_factory=datasets, ledger_factory=ledger)

    def replay(timeout: int) -> TaggedQueueSubprocessReplayAdapter:
        return TaggedQueueSubprocessReplayAdapter(timeout_seconds=timeout, python_executable=arguments.engine_python)

    if arguments.command == "run-tagged-queue-model":
        return run_tagged_queue_model(arguments.protocol_id, arguments.policy_id, split=arguments.split,
            protocols_factory=protocols, datasets_factory=datasets, ledger_factory=ledger,
            replay_factory=replay).document
    return run_tagged_queue_pair(arguments.protocol_id, split=arguments.split,
        protocols_factory=protocols, datasets_factory=datasets, ledger_factory=ledger,
        replay_factory=replay)
