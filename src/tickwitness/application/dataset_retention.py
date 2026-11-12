"""Maintenance orchestration with explicit scope and lazy IO admission."""

from collections.abc import Callable
from typing import Protocol

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.data_evidence.retention import (
    DEFAULT_MIN_AGE_SECONDS,
    DatasetRetentionPlan,
    RetentionValidationError,
    build_dataset_retention_result,
    load_dataset_retention_plan,
    load_retention_preview,
    retention_policy,
    retention_preview,
)
from tickwitness.domain.evidence.run_records import identity

type Row = dict[str, object]


class DatasetMaintenanceRepository(Protocol):
    def plan(self, min_age_seconds: int = DEFAULT_MIN_AGE_SECONDS) -> DatasetRetentionPlan: ...

    def apply(self, plan: DatasetRetentionPlan) -> Row: ...


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Dataset maintenance permits development scope only")


def plan_dataset_retention(
    repository_factory: Callable[[], DatasetMaintenanceRepository],
    *,
    min_age_seconds: int = DEFAULT_MIN_AGE_SECONDS,
    split: str = "development",
) -> Row:
    _development(split)
    policy = retention_policy(min_age_seconds)
    plan = repository_factory().plan(min_age_seconds)
    if plan.document["policy"] != policy:
        raise RetentionValidationError("Observed retention policy differs from its request")
    return retention_preview(plan)


def _refused(plan: DatasetRetentionPlan, diagnostic: str) -> Row:
    return build_dataset_retention_result(
        {
            "kind": "dataset_retention_result_v1",
            "schema_version": 1,
            "plan_id": plan.plan_id,
            "status": "REFUSED",
            "intended": plan.document["candidates"],
            "unlinked": [],
            "already_absent": [],
            "removed_logical_bytes": 0,
            "diagnostic": diagnostic,
        },
        plan=plan,
    )


def apply_dataset_retention(
    plan_reader: Callable[[], bytes],
    expected_plan_id: str,
    repository_factory: Callable[[], DatasetMaintenanceRepository],
    *,
    split: str = "development",
) -> Row:
    _development(split)
    expected = identity(expected_plan_id)
    plan = load_retention_preview(plan_reader())
    if plan.plan_id != expected:
        return _refused(plan, "plan_mismatch")
    if plan.document["status"] == "BLOCKED":
        return _refused(plan, "blocked_plan")
    # Reconstruct before handing authority to an adapter; neither an envelope
    # hash nor a preview grants permission to broaden its original candidate set.
    checked = load_dataset_retention_plan(plan.canonical_bytes)
    result = repository_factory().apply(checked)
    return build_dataset_retention_result(result, plan=checked)
