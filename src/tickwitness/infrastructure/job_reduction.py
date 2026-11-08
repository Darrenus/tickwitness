"""Trusted coordinator composition for native Jobs and original research facts."""

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import cast

from tickwitness.application.reduction_execution import (
    AuditedReductionExecution,
    PreparedReductionExecution,
    audit_reduction_execution,
    authorize_reduction_execution,
    find_reduction_execution_reservation,
    inspect_reduction_attempt,
    inspect_reduction_run,
    prepare_reduction_execution,
    publish_reduction_execution,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
)
from tickwitness.domain.jobs.contracts import (
    JobSpec,
    execution_origin_spec,
    job_dispatch_nonce,
    load_job_spec,
)
from tickwitness.domain.jobs.native_requests import check_native_input_size
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.nautilus_replay import ENGINE_VERSION, ReplayDependencyError
from tickwitness.infrastructure.reduction_bundles import LocalReductionBundles
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

type Row = dict[str, object]


@dataclass(frozen=True, slots=True)
class NativeJobPreparation:
    spec: JobSpec
    execution: PreparedReductionExecution
    ledger: LocalAttemptLedger


def prepare_native_job(spec: JobSpec) -> NativeJobPreparation:
    checked = load_job_spec(spec.canonical_bytes)
    if checked.document["operation"] not in {
        "execute_reduction_input_v1", "resolve_reduction_job_v1"
    }:
        raise EvidenceValidationError("Native preparation requires an execution Job")
    origin = execution_origin_spec(checked)
    request = cast("Row", origin.document["request"])
    root = Path(cast("str", request["input_root"]))
    source_path = root / cast("str", request["source_evidence"])
    if not source_path.resolve().is_relative_to(root.resolve()):
        raise EvidenceValidationError("Native Job source escapes the configured input root")
    source = read_search_evidence_bundle(source_path)
    preparation = LocalReductionBundles(root).read(Path(cast("str", request["preparation"])))
    execution = prepare_reduction_execution(
        preparation,
        source,
        expected_preparation_id=cast("str", request["expected_preparation_id"]),
        expected_bundle_id=cast("str", request["expected_bundle_id"]),
        expected_report_id=cast("str", request["expected_report_id"]),
        split="development",
    )
    check_native_input_size(execution.replay_input)
    ledger = LocalAttemptLedger(Path(cast("str", request["runs"])), create=False)
    # Validate actual owner/prefix even if no managed dispatch was consumed yet.
    find_reduction_execution_reservation(
        execution, ledger=ledger, nonce=job_dispatch_nonce(checked)
    )
    return NativeJobPreparation(checked, execution, ledger)


def require_native_runtime() -> None:
    """Known missing/mismatched optional dependency is refused before reserve."""
    try:
        installed = metadata.version("nautilus_trader")
    except metadata.PackageNotFoundError as error:
        raise ReplayDependencyError(
            "engine_unavailable", "Native Jobs require the pinned nautilus extra"
        ) from error
    if installed != ENGINE_VERSION:
        raise ReplayDependencyError(
            "engine_unavailable", "Native Job runtime version differs from its frozen profile"
        )


def authorize_native_job(
    prepared: NativeJobPreparation, *, fence: Callable[[], None]
) -> AttemptReservation:
    require_native_runtime()
    return authorize_reduction_execution(
        prepared.execution,
        ledger=prepared.ledger,
        reservation_nonce=job_dispatch_nonce(prepared.spec),
        fence=fence,
    )


def audit_native_job(
    prepared: NativeJobPreparation,
    reservation: AttemptReservation,
    result_raw: bytes,
) -> tuple[NativeJobPreparation, AuditedReductionExecution]:
    # Fresh reads prevent a changed locator from silently switching frozen input.
    reopened = prepare_native_job(prepared.spec)
    audited = audit_reduction_execution(reopened.execution, reservation, result_raw)
    return reopened, audited


def publish_native_job(
    prepared: NativeJobPreparation,
    reservation: AttemptReservation,
    audited: AuditedReductionExecution,
    *,
    fence: Callable[[], None],
) -> bytes:
    # This publication is deliberately not inside a failure->outcome conversion.
    # The research receipt may be durable even if readback/Catalog ACK is lost.
    submitted = publish_reduction_execution(
        prepared.execution,
        reservation,
        audited,
        ledger=prepared.ledger,
        fence=fence,
    )
    inspected = inspect_reduction_run(
        submitted.run_id,
        source=prepared.execution.source,
        split="development",
        ledger_factory=lambda: prepared.ledger,
    )
    raw = canonical(cast("Row", inspected["receipt"]))
    if raw != audited.receipt.canonical_bytes:
        raise EvidenceValidationError(
            "Committed native Job receipt differs from its independent audit"
        )
    return raw


def inspect_native_job_dispatch(spec: JobSpec) -> Row:
    prepared = prepare_native_job(spec)
    nonce = job_dispatch_nonce(prepared.spec)
    reservation = find_reduction_execution_reservation(
        prepared.execution,
        ledger=prepared.ledger,
        nonce=nonce,
    )
    recovery: Row | None = None
    if reservation is not None:
        request = cast("Row", execution_origin_spec(prepared.spec).document["request"])
        recovery = inspect_reduction_attempt(
            reservation.attempt_id,
            prepared.execution.preparation,
            prepared.execution.source,
            expected_preparation_id=cast("str", request["expected_preparation_id"]),
            expected_bundle_id=cast("str", request["expected_bundle_id"]),
            expected_report_id=cast("str", request["expected_report_id"]),
            split="development",
            ledger_factory=lambda: prepared.ledger,
        )
    return {
        "kind": "native_job_dispatch_observation_v1",
        "schema_version": 1,
        "job_id": prepared.spec.spec_id,
        "dispatch_nonce": nonce,
        "research_attempt_id": None if reservation is None else reservation.attempt_id,
        "status": "no_reservation_observed" if recovery is None else recovery["status"],
        "recovery": recovery,
        "observation_only": True,
        "execution_authorized": False,
        "job_state_changed": False,
        "automatic_retry_performed": False,
        "budget_refunded": False,
        "global_absence_verified": False,
    }
