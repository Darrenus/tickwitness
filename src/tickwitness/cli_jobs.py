"""CLI composition for durable, trusted local comparison Jobs."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from tickwitness.application.jobs import JobConflictError, job_view
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import identity
from tickwitness.domain.jobs.contracts import JobValidationError, build_job_spec
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore

COMMANDS = frozenset(
    {"submit-comparison-job", "run-job", "inspect-job", "reconcile-jobs", "read-job-result"}
)
type Row = dict[str, object]


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    submit = commands.add_parser(
        "submit-comparison-job", help="Queue one pinned read-only comparison"
    )
    submit.add_argument("run_id")
    submit.add_argument("--input-root", type=Path, required=True)
    submit.add_argument("--source-evidence", required=True)
    submit.add_argument("--runs", type=Path, required=True)
    submit.add_argument("--expected-bundle-id", required=True)
    submit.add_argument("--expected-report-id", required=True)
    submit.add_argument("--lease-seconds", type=int, default=30)
    submit.add_argument("--split", choices=("development", "confirmation"), default="development")
    submit.add_argument("--jobs", type=Path, required=True)
    for name, help_text in (
        ("run-job", "Own the coordinator and execute a queued comparison Job"),
        ("inspect-job", "Read persisted and effective Job state without recovery writes"),
        ("read-job-result", "Read the canonical independently reaudited comparison result"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("job_id")
        command.add_argument("--jobs", type=Path, required=True)
        if name == "inspect-job":
            command.add_argument("--events", action="store_true")
    reconcile = commands.add_parser(
        "reconcile-jobs", help="Diagnose orphan Jobs as LOST; never resume"
    )
    reconcile.add_argument("--jobs", type=Path, required=True)


def _disjoint(jobs: Path, roots: tuple[Path, ...]) -> None:
    catalog = jobs.resolve()
    for root in roots:
        source = root.resolve()
        if catalog.is_relative_to(source) or source.is_relative_to(catalog):
            raise JobValidationError("Job Catalog and observed input/ledger trees must be disjoint")


def execute(arguments: argparse.Namespace) -> Row | str:
    if arguments.command == "submit-comparison-job":
        if arguments.split != "development":
            raise ConfirmationAccessDenied(
                "Managed comparison Jobs permit development evidence only"
            )
        spec = build_job_spec(
            {
                "run_id": arguments.run_id,
                "input_root": str(arguments.input_root.absolute()),
                "source_evidence": arguments.source_evidence,
                "runs": str(arguments.runs.absolute()),
                "expected_bundle_id": arguments.expected_bundle_id,
                "expected_report_id": arguments.expected_report_id,
                "split": arguments.split,
            },
            lease_duration_ns=arguments.lease_seconds * 1_000_000_000,
        )
        _disjoint(arguments.jobs, (arguments.input_root, arguments.runs))
        store = SqliteJobStore(arguments.jobs, create=True)
        with store.coordinator():
            store.reconcile_orphans(now_ns=time.time_ns())
            row = store.submit(spec, now_ns=time.time_ns())
        return job_view(row, now_ns=time.time_ns(), coordinator_active=False)
    if arguments.command != "reconcile-jobs":
        identity(arguments.job_id)
    store = SqliteJobStore(arguments.jobs, create=False)
    if arguments.command == "reconcile-jobs":
        with store.coordinator():
            changed = store.reconcile_orphans(now_ns=time.time_ns())
        return {
            "kind": "job_reconciliation_receipt_v1",
            "schema_version": 1,
            "jobs": [
                job_view(row, now_ns=time.time_ns(), coordinator_active=False) for row in changed
            ],
            "worker_started": False,
            "research_attempt_reserved": False,
            "automatic_retry_performed": False,
            "checkpoint_restored": False,
        }
    if arguments.command == "read-job-result":
        row = store.get(arguments.job_id)
        if row["state"] != "SUCCEEDED":
            raise JobConflictError("Only a succeeded Job has a readable result")
        raw = store.result(arguments.job_id)
        if raw is None:
            raise JobConflictError("Job result is unavailable")
        return raw.decode("utf-8")
    row = (
        run_job(store, arguments.job_id)
        if arguments.command == "run-job"
        else store.get(arguments.job_id)
    )
    view = job_view(row, now_ns=time.time_ns(), coordinator_active=store.coordinator_active())
    if arguments.command == "inspect-job" and arguments.events:
        fields = {
            "event_id",
            "event_type",
            "schema_version",
            "aggregate_id",
            "aggregate_version",
            "occurred_at_ns",
            "correlation_id",
            "causation_id",
            "snapshot_sha256",
        }
        view["events"] = [
            {key: value for key, value in event.items() if key in fields}
            for event in store.events(arguments.job_id)
        ]
        view["event_limit"] = 100
        view["complete_history_claimed"] = False
    return view
