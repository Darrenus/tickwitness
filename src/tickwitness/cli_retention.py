"""Explicit planning/application of a bounded DatasetStore retention snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.dataset_retention import (
    apply_dataset_retention,
    plan_dataset_retention,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.data_evidence.retention import (
    DEFAULT_MIN_AGE_SECONDS,
    MAX_RETENTION_PREVIEW_BYTES,
)
from tickwitness.infrastructure.dataset_retention import LocalDatasetMaintenance
from tickwitness.infrastructure.safe_input import InputReadError, read_regular_file

COMMANDS = frozenset({"plan-dataset-retention", "apply-dataset-retention"})
type Row = dict[str, object]


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    planner = commands.add_parser(
        "plan-dataset-retention", help="Plan proven DatasetStore CAS orphans"
    )
    planner.add_argument("--min-age-seconds", type=int, default=DEFAULT_MIN_AGE_SECONDS)
    apply = commands.add_parser(
        "apply-dataset-retention", help="Revalidate and apply an exact retention plan"
    )
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--expected-plan-id", required=True)
    for command in (planner, apply):
        command.add_argument("--store", type=Path, required=True)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> Row:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Dataset maintenance permits development scope only")

    def repository() -> LocalDatasetMaintenance:
        return LocalDatasetMaintenance(arguments.store)

    if arguments.command == "plan-dataset-retention":
        return plan_dataset_retention(repository, min_age_seconds=arguments.min_age_seconds)

    def read_plan() -> bytes:
        # The owner-selected file is external input, never a deletion pathname.
        # Resolve its trusted parent (including macOS /tmp) but not the file.
        path = arguments.plan
        try:
            parent = path.parent.resolve()
        except (OSError, RuntimeError) as error:
            raise InputReadError("Cannot resolve the retention input parent") from error
        return read_regular_file(
            parent,
            path.name,
            max_bytes=MAX_RETENTION_PREVIEW_BYTES + 1,
            allowed_suffixes=frozenset({path.name}),
        )

    return apply_dataset_retention(read_plan, arguments.expected_plan_id, repository)
