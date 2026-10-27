"""Frozen resource admission and supervised campaign facts, without research verdicts."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol, cast

from tickwitness.application.data_access import DatasetReader
from tickwitness.application.experiments import ExecutableReader
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_execution import _plan, _subject
from tickwitness.application.search_planning import SearchPlanReader
from tickwitness.domain.evidence.run_records import identity, parse
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    CampaignBudget,
    CampaignBudgetValidationError,
    build_budget_stop,
    build_campaign_budget,
    load_allocation,
    load_budget_stop,
    load_campaign_budget,
)
from tickwitness.domain.search.plans import SearchPlan


class BudgetReader(Protocol):
    def get_budget(self, plan_id: str) -> bytes | None: ...
    def get_allocations(self, plan_id: str) -> tuple[bytes, ...]: ...
    def get_stop(self, plan_id: str) -> bytes | None: ...
    def check_tree(self, plan_id: str) -> object: ...
    def control_payload_bytes(self, plan_id: str) -> int: ...


class BudgetRepository(BudgetReader, Protocol):
    def lock(self, plan_id: str) -> AbstractContextManager[object]: ...
    def start(self, plan_id: str, raw: bytes) -> None: ...
    def write_stop(self, plan_id: str, raw: bytes) -> None: ...


class Supervision(Protocol):
    @property
    def reason(self) -> str: ...
    @property
    def exit_code(self) -> int: ...
    @property
    def elapsed_ns(self) -> int: ...
    @property
    def stdout(self) -> bytes: ...
    @property
    def stderr(self) -> bytes: ...


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Bounded campaigns permit development evidence only")


def _checked_budget(plan: SearchPlan, raw: bytes) -> CampaignBudget:
    budget = load_campaign_budget(raw)
    if (
        budget.document["plan_id"] != plan.plan_id
        or budget.document["protocol_id"] != _subject(plan).protocol_id
    ):
        raise CampaignBudgetValidationError("Campaign budget differs from the actual frozen plan")
    return budget


def _snapshot(
    plan: SearchPlan,
    *,
    budgets: BudgetReader,
    execution_inspector: Callable[[], dict[str, object] | None],
) -> dict[str, object]:
    raw = budgets.get_budget(plan.plan_id)
    if raw is None:
        raise CampaignBudgetValidationError("Bounded campaign has not been started")
    budget = _checked_budget(plan, raw)
    stop_raw = budgets.get_stop(plan.plan_id)
    stop = load_budget_stop(stop_raw, budget=budget) if stop_raw is not None else None
    budgets.check_tree(plan.plan_id)
    allocation_raw = budgets.get_allocations(plan.plan_id)
    allocations = [load_allocation(item, budget=budget) for item in allocation_raw]
    eligible = [
        row
        for row in cast("list[dict[str, object]]", plan.document["journal"])
        if row["status"] == "ELIGIBLE"
    ]
    if len(allocations) > len(eligible):
        raise CampaignBudgetValidationError("Resource admissions exceed the frozen candidate set")
    for index, allocation in enumerate(allocations, start=1):
        if allocation["index"] != index or allocation["ordinal"] != eligible[index - 1]["ordinal"]:
            raise CampaignBudgetValidationError(
                "Resource admissions are not the exact candidate prefix"
            )
    execution = execution_inspector()
    if execution is not None:
        if (
            execution.get("plan_id") != plan.plan_id
            or execution.get("protocol_id") != _subject(plan).protocol_id
        ):
            raise CampaignBudgetValidationError("Inner execution differs from the budget subject")
        admitted = {item["ordinal"] for item in allocations}
        for candidate in cast("list[dict[str, object]]", execution["candidates"]):
            if candidate["status"] != "NOT_DISPATCHED" and candidate["ordinal"] not in admitted:
                raise CampaignBudgetValidationError(
                    "Candidate executed without durable resource admission"
                )
    if budgets.get_allocations(plan.plan_id) != allocation_raw:
        raise CampaignBudgetValidationError("Resource admissions changed during inspection; retry")
    limits = cast("dict[str, int]", budget.document["limits"])
    reserved = CONTROL_RESERVE_BYTES + len(allocations) * CANDIDATE_RESERVE_BYTES
    if reserved > limits["max_storage_bytes"] or len(allocations) > limits["max_evaluations"]:
        raise CampaignBudgetValidationError("Resource admissions exceed frozen limits")
    status, reason, exit_code = "unfinalized", "terminal_record_absent", 3
    elapsed: object = None
    if stop is not None:
        reason, exit_code, elapsed = (
            cast("str", stop["reason"]),
            cast("int", stop["exit_code"]),
            stop["elapsed_ns"],
        )
        status = "completed" if reason == "completed" else "stopped"
        if reason == "completed":
            if (
                execution is None
                or execution["status"] != "completed"
                or exit_code != 0
                or len(allocations) != len(eligible)
                or cast("int", elapsed) >= limits["max_wall_time_ms"] * 1_000_000
            ):
                raise CampaignBudgetValidationError(
                    "Completion is not supported by execution and deadline"
                )
        elif reason == "time_limit":
            if cast("int", elapsed) < limits["max_wall_time_ms"] * 1_000_000:
                raise CampaignBudgetValidationError(
                    "Deadline stop contradicts the recorded elapsed time"
                )
        elif reason == "evaluation_limit":
            if len(allocations) != limits["max_evaluations"] or len(allocations) >= len(eligible):
                raise CampaignBudgetValidationError(
                    "Evaluation limit stop lacks exhausted admission evidence"
                )
        elif reason == "execution_stopped" and (
            execution is None
            or execution["status"] == "completed"
            or execution["exit_code"] != exit_code
        ):
            raise CampaignBudgetValidationError("Execution stop differs from committed inner facts")
    return {
        "kind": "bounded_search_campaign_report_v1",
        "schema_version": 1,
        "plan_id": plan.plan_id,
        "protocol_id": _subject(plan).protocol_id,
        "budget_id": budget.budget_id,
        "budget": budget.document,
        "status": status,
        "stop_reason": reason,
        "exit_code": exit_code,
        "allocations": allocations,
        "execution": execution,
        "stop": stop,
        "proposal_journal": plan.document["journal"],
        "resources": {
            "admitted_evaluations": len(allocations),
            "reserved_storage_bytes": reserved,
            "max_storage_bytes": limits["max_storage_bytes"],
            "elapsed_ns": elapsed,
            "storage_policy": "managed_new_file_payloads_v1",
            "wall_time_scope": "coordinator_execution_phase_v1",
        },
        "scope": {
            "phase": "development",
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "calibration_status": "uncalibrated",
            "claim_evaluated": False,
            "finding_issued": False,
            "full_trial_history_certified": False,
        },
        "verification": {
            "plan_recomputed": True,
            "source_revalidated": True,
            "budget_bindings_verified": True,
            "quota_reservations_verified": True,
            "execution_reaudited": execution is not None,
            "native_replayed": False,
            "runtime_limits_reenforced": False,
            "author_signature_verified": False,
            "physical_storage_usage_verified": False,
        },
    }


def inspect_bounded_search_campaign(
    plan_id: str,
    *,
    split: str,
    plans_factory: Callable[[], SearchPlanReader],
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    budgets_factory: Callable[[], BudgetReader],
    execution_inspector: Callable[[], dict[str, object] | None],
) -> dict[str, object]:
    _development(split)
    identity(plan_id)
    plan = _plan(
        plan_id,
        plans_factory=plans_factory,
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    return _snapshot(plan, budgets=budgets_factory(), execution_inspector=execution_inspector)


def run_bounded_search_campaign(
    plan_id: str,
    budget_request: bytes,
    *,
    split: str,
    plans_factory: Callable[[], SearchPlanReader],
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    budgets_factory: Callable[[], BudgetRepository],
    execution_inspector: Callable[[], dict[str, object] | None],
    supervise: Callable[[CampaignBudget], Supervision],
    nonce_factory: Callable[[], str],
) -> dict[str, object]:
    _development(split)
    identity(plan_id)
    plan = _plan(
        plan_id,
        plans_factory=plans_factory,
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    # Validate the request before opening any writable output root.
    proposed = build_campaign_budget(
        budget_request,
        plan_id=plan_id,
        protocol_id=_subject(plan).protocol_id,
        nonce=nonce_factory(),
    )
    budgets = budgets_factory()
    with budgets.lock(plan_id):
        existing = budgets.get_budget(plan_id)
        if existing is not None:
            frozen = _checked_budget(plan, existing)
            rebuilt = build_campaign_budget(
                budget_request,
                plan_id=plan_id,
                protocol_id=_subject(plan).protocol_id,
                nonce=cast("str", frozen.document["nonce"]),
            )
            if rebuilt.canonical_bytes != frozen.canonical_bytes:
                raise CampaignBudgetValidationError(
                    "Existing bounded campaign has different frozen limits"
                )
            return _snapshot(plan, budgets=budgets, execution_inspector=execution_inspector)
        inventory = cast("dict[str, object]", budgets.check_tree(plan_id))
        if budgets.control_payload_bytes(plan_id) or inventory.get("managed"):
            raise CampaignBudgetValidationError("Unstarted budget has orphaned resource records")
        budgets.start(plan_id, proposed.canonical_bytes)
        if budgets.get_budget(plan_id) != proposed.canonical_bytes:
            raise CampaignBudgetValidationError("Budget publication differs from requested limits")
        outcome = supervise(proposed)
        reason, code = "worker_failed", 7
        message: str | None = None
        if outcome.reason == "time_limit":
            reason, code = "time_limit", 8
        elif outcome.reason == "finished":
            try:
                diagnostic = parse(outcome.stdout, limit=64 * 1024)
                declared = diagnostic.get("reason")
                worker_code = diagnostic.get("exit_code")
                if (
                    declared
                    in (
                        "completed",
                        "evaluation_limit",
                        "storage_limit",
                        "time_limit",
                        "execution_stopped",
                        "execution_unfinalized",
                        "worker_failed",
                        "publication_unconfirmed",
                    )
                    and type(worker_code) is int
                    and worker_code == outcome.exit_code
                ):
                    reason, code = declared, worker_code
            except ValueError:
                message = "Coordinator did not return a valid bounded diagnostic"
        if (
            reason == "completed"
            and outcome.elapsed_ns
            >= cast("dict[str, int]", proposed.document["limits"])["max_wall_time_ms"] * 1_000_000
        ):
            reason, code = "time_limit", 8
        budgets.write_stop(
            plan_id,
            build_budget_stop(
                proposed, reason, exit_code=code, elapsed_ns=outcome.elapsed_ns, message=message
            ),
        )
        return _snapshot(plan, budgets=budgets, execution_inspector=execution_inspector)
