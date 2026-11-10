"""CLI composition for durable local comparison and native reduction Jobs."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import cast

from tickwitness.application.jobs import JobConflictError, job_view
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import canonical, identity, parse
from tickwitness.domain.jobs.contracts import (
    JobValidationError,
    build_execution_job_spec,
    build_followup_job_spec,
    build_job_spec,
    execution_origin_spec,
    load_job_spec,
)
from tickwitness.domain.jobs.control import build_job_control_policy, control_key
from tickwitness.infrastructure.job_control_runtime import reclaim_workspaces, validate_worker_limits
from tickwitness.infrastructure.job_controls import JobControlStore
from tickwitness.infrastructure.job_followups import find_committed_dispatch
from tickwitness.infrastructure.job_lineage import JobFamily
from tickwitness.infrastructure.job_reduction import inspect_native_job_dispatch
from tickwitness.infrastructure.job_supervisor import run_job
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore

COMMANDS = frozenset(
    {
        "submit-comparison-job",
        "submit-reduction-job",
        "retry-reduction-job",
        "recover-reduction-job",
        "run-job",
        "inspect-job",
        "inspect-reduction-job",
        "reconcile-jobs",
        "read-job-result",
        "configure-job-control",
        "cancel-job",
        "inspect-job-control",
        "reclaim-job-workspaces",
    }
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
    native = commands.add_parser(
        "submit-reduction-job", help="Queue one frozen native execution under the original budget"
    )
    native.add_argument("preparation", type=Path)
    native.add_argument("--expected-preparation-id", required=True)
    native.add_argument("--expected-bundle-id", required=True)
    native.add_argument("--expected-report-id", required=True)
    native.add_argument("--source-evidence", required=True)
    native.add_argument("--input-root", type=Path, required=True)
    native.add_argument("--runs", type=Path, required=True)
    native.add_argument("--jobs", type=Path, required=True)
    native.add_argument("--lease-seconds", type=int, default=30)
    native.add_argument("--split", choices=("development", "confirmation"), default="development")
    for name, option, help_text in (
        ("retry-reduction-job", "--retry-key", "Queue an explicit retry under a new original slot"),
        ("recover-reduction-job", "--recovery-key", "Queue acknowledgment of a committed outcome"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("parent_job_id")
        if name == "retry-reduction-job":
            command.add_argument(option, dest="idempotency_key", required=True)
        else:
            command.add_argument(option, dest="idempotency_key", default="acknowledgment-v1")
        command.add_argument("--jobs", type=Path, required=True)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )
    for name, help_text in (
        ("run-job", "Own the coordinator and execute one allowlisted queued Job"),
        ("inspect-job", "Read persisted and effective Job state without recovery writes"),
        ("inspect-reduction-job", "Read the original native dispatch and research recovery facts"),
        ("read-job-result", "Read the exact independently verified operation result"),
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
    for name, help_text in (
        ("configure-job-control", "Freeze controls for one queued Job"),
        ("cancel-job", "Request cancellation before irreversible publication admission"),
        ("inspect-job-control", "Read control intent, actual stop and cleanup facts"),
        ("reclaim-job-workspaces", "Reclaim only verified inactive scratch for one Job"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("job_id")
        command.add_argument("--jobs", type=Path, required=True)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )
        if name == "configure-job-control":
            command.add_argument("--wall-seconds", type=int, default=120)
            command.add_argument("--worker-cpu-seconds", type=int, default=60)
            command.add_argument("--max-file-bytes", type=int, default=8 * 1024 * 1024)
            command.add_argument("--max-open-files", type=int, default=128)
        elif name == "cancel-job":
            command.add_argument("--cancel-key", required=True)


def _disjoint(jobs: Path, roots: tuple[Path, ...]) -> None:
    catalog = jobs.resolve()
    for root in roots:
        source = root.resolve()
        if catalog.is_relative_to(source) or source.is_relative_to(catalog):
            raise JobValidationError("Job Catalog and observed input/ledger trees must be disjoint")


def execute(arguments: argparse.Namespace) -> Row | str:
    if arguments.command in {
        "configure-job-control",
        "cancel-job",
        "inspect-job-control",
        "reclaim-job-workspaces",
    }:
        return _control_command(arguments)
    if arguments.command in {"retry-reduction-job", "recover-reduction-job"}:
        if arguments.split != "development":
            raise ConfirmationAccessDenied("Managed followups permit development evidence only")
        parent_id = identity(arguments.parent_job_id)
        store = SqliteJobStore(arguments.jobs, create=False)
        with store.coordinator():
            store.reconcile_orphans(now_ns=time.time_ns())
            parent = store.get(parent_id)
            origin = execution_origin_spec(load_job_spec(canonical(cast("Row", parent["spec"]))))
            spec = build_followup_job_spec(
                origin,
                parent_id,
                "retry_from_origin_v1"
                if arguments.command == "retry-reduction-job"
                else "acknowledge_committed_v1",
                arguments.idempotency_key,
            )
            row = store.submit(spec, now_ns=time.time_ns())
        return job_view(row, now_ns=time.time_ns(), coordinator_active=False)
    if arguments.command == "submit-reduction-job":
        if arguments.split != "development":
            raise ConfirmationAccessDenied("Managed native Jobs permit development evidence only")
        spec = build_execution_job_spec(
            {
                "preparation": str(arguments.preparation.absolute()),
                "expected_preparation_id": arguments.expected_preparation_id,
                "expected_bundle_id": arguments.expected_bundle_id,
                "expected_report_id": arguments.expected_report_id,
                "source_evidence": arguments.source_evidence,
                "input_root": str(arguments.input_root.absolute()),
                "runs": str(arguments.runs.absolute()),
                "split": arguments.split,
                "engine_runtime": "coordinator_interpreter_v1",
                "restart_mode": "frozen_origin_new_attempt_only_v1",
            },
            lease_duration_ns=arguments.lease_seconds * 1_000_000_000,
        )
        _disjoint(arguments.jobs, (arguments.input_root, arguments.runs, arguments.preparation))
        source, runs = arguments.input_root.resolve(), arguments.runs.resolve()
        if source.is_relative_to(runs) or runs.is_relative_to(source):
            raise JobValidationError("Native input and original ledger trees must be disjoint")
        preparation = arguments.preparation.resolve()
        if preparation.is_relative_to(runs) or runs.is_relative_to(preparation):
            raise JobValidationError(
                "Native preparation and original ledger trees must be disjoint"
            )
        store = SqliteJobStore(arguments.jobs, create=True)
        with store.coordinator():
            store.reconcile_orphans(now_ns=time.time_ns())
            row = store.submit(spec, now_ns=time.time_ns())
        return job_view(row, now_ns=time.time_ns(), coordinator_active=False)
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
    if arguments.command == "inspect-reduction-job":
        spec = load_job_spec(canonical(cast("Row", row["spec"])))
        if spec.document["operation"] == "resolve_reduction_job_v1":
            origin = execution_origin_spec(spec)
            family = JobFamily(origin)
            specs = family.specs()
            committed = find_committed_dispatch(origin, specs)
            return {
                "kind": "reduction_job_resolution_observation_v1",
                "schema_version": 1,
                "job": view,
                "origin_job_id": origin.spec_id,
                "registered_dispatch_job_ids": [item.spec_id for item in specs],
                "committed_dispatch_job_id": None if committed is None else committed[0].spec_id,
                "outcome": None if committed is None else parse(committed[1]),
                "observation_only": True,
                "execution_authorized": False,
                "job_state_changed": False,
                "budget_refunded": False,
            }
        return {
            "kind": "native_job_inspection_v1",
            "schema_version": 1,
            "job": view,
            "dispatch": inspect_native_job_dispatch(spec),
        }
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


def _control_command(arguments: argparse.Namespace) -> Row:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Managed controls permit development evidence only")
    job_id = identity(arguments.job_id)
    if arguments.command == "cancel-job":
        control_key(arguments.cancel_key)
    store = SqliteJobStore(arguments.jobs, create=False)
    control = JobControlStore(store.root, job_id)
    if arguments.command == "configure-job-control":
        policy = build_job_control_policy(
            job_id,
            max_wall_ns=arguments.wall_seconds * 1_000_000_000,
            worker_cpu_seconds=arguments.worker_cpu_seconds,
            max_file_bytes=arguments.max_file_bytes,
            max_open_files=arguments.max_open_files,
        )
        validate_worker_limits(policy)
        with store.coordinator():
            row = store.get(job_id)
            existing = control.policy()
            if existing is None and row["state"] != "QUEUED":
                raise JobConflictError("Control policy must be frozen before the first claim")
            control.configure(policy)
        return {
            "kind": "job_control_configuration_v1",
            "schema_version": 1,
            "job_id": job_id,
            "policy_id": policy.policy_id,
            "policy": policy.document,
        }
    row = store.get(job_id)
    if arguments.command == "cancel-job":
        # request_cancel can read an already committed immutable admission
        # marker while the publisher still owns the gate. Do not precede that
        # positive fast path with a shared-gate policy read.
        observed = control.request_cancel(
            arguments.cancel_key, now_ns=time.time_ns(), snapshot=row
        )
        if observed["status"] in {"accepted", "already_requested"} and row["state"] == "QUEUED":
            try:
                run_job(store, job_id)
            except JobConflictError:
                pass
        return observed
    policy = control.policy()
    if arguments.command == "inspect-job-control":
        request = control.cancel_request() if policy is not None else None
        admission = control.publication_admission() if policy is not None else None
        result = control.result() if policy is not None else None
        status = "UNCONFIGURED"
        if result is not None:
            if result["stop_confirmed"]:
                status = (
                    "STOP_CONFIRMED"
                    if row["state"] in {"FAILED", "LOST"}
                    else "STOPPED_CATALOG_UNCONFIRMED"
                )
            else:
                status = "FINISHED" if result["cause"] == "finished" else "STOP_UNCONFIRMED"
        elif admission is not None:
            status = "PUBLICATION_ADMITTED"
        elif request is not None:
            status = "CANCEL_REQUESTED"
        elif policy is not None:
            status = "RUNNING" if row["state"] == "RUNNING" else "CONFIGURED"
        return {
            "kind": "job_control_inspection_v1",
            "schema_version": 1,
            "job": job_view(
                row, now_ns=time.time_ns(), coordinator_active=store.coordinator_active()
            ),
            "policy": None if policy is None else policy.document,
            "policy_id": None if policy is None else policy.policy_id,
            "cancel_request": request,
            "publication_admission": admission,
            "control_result": result,
            "status": status,
        }
    if policy is None:
        raise JobConflictError("Job has no frozen control policy")
    if arguments.command == "reclaim-job-workspaces":
        with store.coordinator():
            store.reconcile_orphans(now_ns=time.time_ns())
            return reclaim_workspaces(control, store.get(job_id))
    raise JobValidationError("Unsupported Job control command")
