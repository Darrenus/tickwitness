"""Read-only verification of actual original outcomes across a dispatch family."""

from typing import cast

from tickwitness.application.jobs import JobStoreError
from tickwitness.application.reduction_execution import (
    find_reduction_execution_reservation,
    inspect_reduction_attempt,
)
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs.contracts import JobSpec, job_dispatch_nonce
from tickwitness.infrastructure.job_lineage import checked_family_specs
from tickwitness.infrastructure.job_reduction import prepare_native_job

type Row = dict[str, object]


def find_committed_dispatch(
    origin_spec: JobSpec, specs: tuple[JobSpec, ...]
) -> tuple[JobSpec, bytes] | None:
    """Reaudit a family's committed receipt or failure, never authorize execution.

    The absence of an observed outcome is not a global authenticity guarantee.
    Retry coordinators hold the shared family lock across this check and their
    subsequent publication; acknowledgment readers make no research writes.
    """
    chain = checked_family_specs(origin_spec, specs)
    prepared = prepare_native_job(chain[0])
    request = cast("Row", chain[0].document["request"])
    committed: tuple[JobSpec, bytes] | None = None
    for dispatch in chain:
        reservation = find_reduction_execution_reservation(
            prepared.execution,
            ledger=prepared.ledger,
            nonce=job_dispatch_nonce(dispatch),
        )
        if reservation is None:
            continue
        report = inspect_reduction_attempt(
            reservation.attempt_id,
            prepared.execution.preparation,
            prepared.execution.source,
            expected_preparation_id=cast("str", request["expected_preparation_id"]),
            expected_bundle_id=cast("str", request["expected_bundle_id"]),
            expected_report_id=cast("str", request["expected_report_id"]),
            split="development",
            ledger_factory=lambda: prepared.ledger,
        )
        if report["status"] not in {"committed_result", "committed_failure"}:
            continue
        outcome = prepared.ledger.get_outcome(reservation.attempt_id)
        bindings = cast("Row", report["bindings"])
        if (
            outcome is None
            or digest(outcome) != bindings["outcome_id"]
            or prepared.ledger.read_artifact(digest(outcome)) != outcome
            or (
                report["status"] == "committed_result"
                and canonical(cast("Row", report["final_manifest"])) != outcome
            )
        ):
            raise JobStoreError(
                "Observed family outcome differs from its independently verified terminal"
            )
        if committed is not None and committed[1] != outcome:
            raise JobStoreError("Original Job family contains multiple distinct committed outcomes")
        committed = dispatch, outcome
    return committed
