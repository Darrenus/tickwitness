"""Export committed tagged pairs and verify their fixed portable closure offline."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_pair_evidence import export_tagged_pair, verify_tagged_pair_package
from tickwitness.domain.evidence.run_records import identity
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.tagged_evidence_bundles import export_tagged_pair_bundle, read_tagged_pair_bundle
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry

COMMANDS = frozenset({"export-tagged-queue-pair", "verify-tagged-queue-pair"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    export = commands.add_parser("export-tagged-queue-pair", help="Seal two committed tagged runs and their source closure")
    export.add_argument("first_run_id")
    export.add_argument("second_run_id")
    for name in ("store", "registry", "ledger", "output"):
        export.add_argument("--" + name, required=True, type=Path)
    verify = commands.add_parser("verify-tagged-queue-pair", help="Reaudit a sealed tagged pair without stores or native replay")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--expected-bundle-id")
    for command in (export, verify):
        command.add_argument("--split", choices=("development", "confirmation"), default="development")


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Tagged pair evidence permits development only")
    if arguments.command == "verify-tagged-queue-pair":
        if arguments.expected_bundle_id is not None:
            identity(arguments.expected_bundle_id)
        return verify_tagged_pair_package(read_tagged_pair_bundle(arguments.directory),
                                         expected_bundle_id=arguments.expected_bundle_id)
    return export_tagged_pair(arguments.first_run_id, arguments.second_run_id, split=arguments.split,
        ledger_factory=lambda: LocalAttemptLedger(arguments.ledger, create=False),
        protocols_factory=lambda: LocalTaggedQueueRegistry(arguments.registry, create=False),
        datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
        exporter=lambda artifacts: export_tagged_pair_bundle(arguments.output, artifacts))
