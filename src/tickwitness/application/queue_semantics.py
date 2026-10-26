"""Read-only semantic qualification of two committed queue-family model runs."""

from collections.abc import Callable
from typing import cast

from tickwitness.application.data_access import DatasetReader
from tickwitness.application.queue_execution import (
    QueueFamilyReader,
    QueueLedger,
    queue_run_evidence,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.queue_semantics import qualify_queue_pair
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
)
from tickwitness.domain.research_contracts.queue_family import QUEUE_POLICY_IDS


def inspect_queue_semantics(
    left_run_id: str,
    right_run_id: str,
    *,
    split: str,
    families_factory: Callable[[], QueueFamilyReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], QueueLedger],
) -> dict[str, object]:
    """Re-audit actual source and closed attempts without reserving or replaying."""
    if split != "development":
        raise ConfirmationAccessDenied("Queue semantics permit development evidence only")
    identity(left_run_id)
    identity(right_run_id)
    if left_run_id == right_run_id:
        raise EvidenceValidationError("Queue semantics require distinct committed model runs")
    ledger, families, datasets = ledger_factory(), families_factory(), datasets_factory()
    left = queue_run_evidence(left_run_id, ledger=ledger, families=families, datasets=datasets)
    right = queue_run_evidence(right_run_id, ledger=ledger, families=families, datasets=datasets)
    left_attempt = cast("dict[str, object]", left.receipt.document["attempt"])
    right_attempt = cast("dict[str, object]", right.receipt.document["attempt"])
    if left_attempt["attempt_index"] == right_attempt["attempt_index"] or canonical(
        left_attempt
    ) == canonical(right_attempt):
        raise EvidenceValidationError("Queue pair must consume different attempts and indexes")
    qualification = qualify_queue_pair(
        left.replay_input, left.result, right.replay_input, right.result
    )
    ordered = {item.replay_input.policy_id: item for item in (left, right)}
    runs: list[dict[str, object]] = []
    for policy in QUEUE_POLICY_IDS:
        evidence = ordered[policy]
        attempt = cast("dict[str, object]", evidence.receipt.document["attempt"])
        runs.append(
            {
                "policy_id": policy,
                "run_id": evidence.receipt.run_id,
                "attempt_id": digest(canonical(attempt)),
                "attempt_index": attempt["attempt_index"],
            }
        )
    report: dict[str, object] = {
        "qualification_id": qualification.qualification_id,
        **qualification.document,
        "runs": runs,
        "verification": {
            "kind": "queue_semantics_ledger_verification_v1",
            "committed_runs_verified": True,
            "distinct_attempts_verified": True,
            "source_revalidated": True,
            "native_execution_reaudited": True,
            "native_replayed": False,
            "budget_consumed": False,
            "observation_compatibility_certified": False,
            "source_claim_evaluated": False,
            "finding_issued": False,
            "confirmation_reference_checked": False,
            "full_attempt_ledger_checked": False,
            "author_signature_verified": False,
        },
    }
    return {"inspection_id": digest(canonical(report)), **report}
