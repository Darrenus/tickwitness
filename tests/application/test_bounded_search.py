"""Original-budget integration and immutable bounded-campaign inspection."""

import secrets
from types import SimpleNamespace

import pytest

from tickwitness.application.bounded_search import (
    inspect_bounded_search_campaign,
    run_bounded_search_campaign,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_execution import inspect_search_campaign, run_search_plan
from tickwitness.application.search_planning import freeze_search_plan
from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    CampaignBudgetValidationError,
    build_budget_stop,
    load_campaign_budget,
)
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.campaign_resource_guard import (
    CampaignLimitReached,
    CampaignResourceGuard,
    activate_resource_guard,
)
from tickwitness.infrastructure.search_campaign_store import (
    LocalSearchCampaignStore,
    SearchCampaignNotFoundError,
)
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry


def prepare(case, *, values=None, seed=7):
    assumption = {
        "kind": "assumption_request_v1",
        "schema_version": 1,
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "transform": {"semantic_id": "replay_receive_suffix_shift_v1", "from_capture_seq": 2},
        "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
        "parameter_basis": {
            "kind": "researcher_defined",
            "calibration_status": "uncalibrated",
            "calibration_evidence_refs": [],
        },
    }
    grid = [0, 1] if values is None else values
    request = {
        "kind": "search_plan_request_v1",
        "schema_version": 1,
        "search_seed": seed,
        "max_proposals": len(grid),
        "generator": {"kind": "grid", "values_ns": grid},
    }
    return freeze_search_plan(
        case.frozen.protocol_id,
        canonical(assumption),
        canonical(request),
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans", create=True),
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
    )["plan_id"]


def request(*, evaluations=2, storage=512 * 1024 * 1024, wall_ms=20_000):
    return canonical(
        {
            "kind": "campaign_budget_request_v1",
            "schema_version": 1,
            "max_evaluations": evaluations,
            "max_wall_time_ms": wall_ms,
            "max_storage_bytes": storage,
        }
    )


def inner(case, plan_id):
    budgets = LocalCampaignBudgetStore(case.root / "runs", create=False)
    try:
        store = LocalSearchCampaignStore(budgets.managed_root(plan_id), create=False)
    except SearchCampaignNotFoundError:
        return None
    if store.get_campaign(plan_id) is None:
        return None
    return inspect_search_campaign(
        plan_id,
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=lambda: LocalAttemptLedger(case.root / "runs", create=False),
        campaigns_factory=lambda: store,
    )


def inline_supervisor(case, plan_id, *, expire_after_first=False):
    """Fault-inject an execution clock around genuine saved-fixture ledger commits.

    Real process deadlines and group cleanup are tested separately in infra/CI;
    this test does not label its simulated clock as a native timing measurement.
    """

    def supervise(budget):
        limits = budget.document["limits"]
        now = [1]
        deadline = limits["max_wall_time_ms"] * 1_000_000 + 1
        store = LocalCampaignBudgetStore(case.root / "runs", create=True)
        guard = CampaignResourceGuard(budget, store, lambda: now[0], deadline)

        def admit(ordinal):
            if expire_after_first and ordinal > 1:
                now[0] = deadline
            guard.admit(ordinal)

        try:
            with activate_resource_guard(guard):
                result = run_search_plan(
                    plan_id,
                    split="development",
                    plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
                    registry_factory=lambda: case.registry,
                    datasets_factory=lambda: case.data,
                    ledger_factory=lambda: LocalAttemptLedger(case.root / "runs", create=True),
                    ledger_reader_factory=lambda: LocalAttemptLedger(
                        case.root / "runs", create=False
                    ),
                    campaigns_factory=lambda: LocalSearchCampaignStore(
                        store.managed_root(plan_id), create=True
                    ),
                    engine_factory=case.engine_factory,
                    nonce_factory=lambda: secrets.token_hex(16),
                    candidate_gate=admit,
                )
            reason = "completed" if result["status"] == "completed" else "execution_stopped"
            code = result["exit_code"]
        except CampaignLimitReached as error:
            reason, code = error.reason, 8
        return SimpleNamespace(
            reason="finished",
            exit_code=code,
            elapsed_ns=now[0] - 1,
            stdout=canonical({"reason": reason, "exit_code": code}),
            stderr=b"",
        )

    return supervise


def options(case, plan_id):
    return {
        "split": "development",
        "plans_factory": lambda: LocalSearchPlanRegistry(case.root / "plans"),
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
        "budgets_factory": lambda: LocalCampaignBudgetStore(case.root / "runs", create=True),
        "execution_inspector": lambda: inner(case, plan_id),
        "supervise": inline_supervisor(case, plan_id),
        "nonce_factory": lambda: secrets.token_hex(16),
    }


def run(case, plan_id, raw=None, **changes):
    arguments = options(case, plan_id)
    arguments.update(changes)
    return run_bounded_search_campaign(plan_id, raw or request(), **arguments)


def inspect(case, plan_id):
    arguments = options(case, plan_id)
    arguments.pop("supervise")
    arguments.pop("nonce_factory")
    arguments["budgets_factory"] = lambda: LocalCampaignBudgetStore(
        case.root / "runs", create=False
    )
    return inspect_bounded_search_campaign(plan_id, **arguments)


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def forbidden(*_args, **_kwargs):
    raise AssertionError("Must not execute or open this port")


@pytest.mark.parametrize("limit", ["evaluation", "storage", "time"])
def test_limit_preserves_first_committed_result_and_does_not_dispatch_suffix(
    experiment_case, limit
):
    case = experiment_case
    plan_id = prepare(case)
    raw = (
        request(evaluations=1)
        if limit == "evaluation"
        else request(storage=CONTROL_RESERVE_BYTES + CANDIDATE_RESERVE_BYTES)
        if limit == "storage"
        else request()
    )
    report = run(
        case,
        plan_id,
        raw,
        supervise=inline_supervisor(case, plan_id, expire_after_first=limit == "time"),
    )
    assert report["status"] == "stopped" and report["exit_code"] == 8
    assert report["stop_reason"] == limit + "_limit"
    assert [item["status"] for item in report["execution"]["candidates"]] == [
        "COMPLETED",
        "NOT_DISPATCHED",
    ]
    assert report["execution"]["candidates"][0]["evaluation"]["metric_observation"]["value"] == "-2"
    assert report["resources"]["admitted_evaluations"] == 1
    assert report["resources"]["reserved_storage_bytes"] <= report["resources"]["max_storage_bytes"]
    before = tree(case.root)
    assert inspect(case, plan_id) == report
    assert run(case, plan_id, raw, supervise=forbidden) == report
    assert tree(case.root) == before


def test_zero_candidate_capacity_stops_before_original_slot(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    report = run(case, plan_id, request(storage=CONTROL_RESERVE_BYTES))
    assert report["stop_reason"] == "storage_limit" and report["exit_code"] == 8
    assert report["allocations"] == []
    assert report["execution"]["counts"]["reserved"] == 0
    assert all(item["status"] == "NOT_DISPATCHED" for item in report["execution"]["candidates"])


def test_shared_original_protocol_budget_cannot_be_reset_by_another_bounded_plan(experiment_case):
    case = experiment_case
    plan_id = prepare(case, values=[0])
    first = run(case, plan_id)
    second_id = prepare(case, values=[0], seed=8)
    second = run(case, second_id)
    third_id = prepare(case, values=[0], seed=9)
    third = run(case, third_id)
    assert first["status"] == second["status"] == "completed"
    assert first["execution"]["candidates"][0]["attempt_index"] == 1
    assert second["execution"]["candidates"][0]["attempt_index"] == 2
    assert third["stop_reason"] == "execution_stopped" and third["exit_code"] == 8
    assert third["execution"]["candidates"][0]["status"] == "BUDGET_EXHAUSTED"


def test_deadline_before_coordinator_start_has_no_inner_execution_and_stable_elapsed(
    experiment_case,
):
    case = experiment_case
    plan_id = prepare(case)

    def timeout(_budget):
        return SimpleNamespace(
            reason="time_limit", exit_code=8, elapsed_ns=20_000_000_001, stdout=b"", stderr=b""
        )

    report = run(case, plan_id, supervise=timeout)
    assert report["execution"] is None and report["allocations"] == []
    assert report["stop_reason"] == "time_limit" and report["exit_code"] == 8
    assert inspect(case, plan_id) == report
    assert report["verification"]["execution_reaudited"] is False


def test_changed_budget_cannot_overwrite_or_resume_existing_campaign(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    run(case, plan_id, request(evaluations=1))
    before = tree(case.root)
    with pytest.raises(CampaignBudgetValidationError, match="different frozen limits"):
        run(case, plan_id, request(evaluations=2), supervise=forbidden)
    assert tree(case.root) == before


def test_time_stop_rewrite_cannot_claim_impossible_elapsed(experiment_case):
    case = experiment_case
    plan_id = prepare(case, values=[0])
    run(case, plan_id)
    budgets = LocalCampaignBudgetStore(case.root / "runs")
    budget = load_campaign_budget(budgets.get_budget(plan_id))
    raw = build_budget_stop(budget, "time_limit", exit_code=8, elapsed_ns=0)
    path = case.root / "runs" / "bounded-search-campaigns" / plan_id / "stop.json"
    path.write_bytes(raw)
    with pytest.raises(CampaignBudgetValidationError, match="elapsed"):
        inspect(case, plan_id)


@pytest.mark.parametrize("operation", ["run", "inspect"])
def test_confirmation_denied_before_identity_and_all_ports(operation):
    arguments = {
        "split": "confirmation",
        "plans_factory": forbidden,
        "registry_factory": forbidden,
        "datasets_factory": forbidden,
        "budgets_factory": forbidden,
        "execution_inspector": forbidden,
    }
    with pytest.raises(ConfirmationAccessDenied):
        if operation == "run":
            run_bounded_search_campaign(
                "bad", b"bad", supervise=forbidden, nonce_factory=forbidden, **arguments
            )
        else:
            inspect_bounded_search_campaign("bad", **arguments)


def test_invalid_request_never_opens_writable_output(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    with pytest.raises(CampaignBudgetValidationError):
        run(
            case,
            plan_id,
            b'{"schema_version":true}',
            budgets_factory=forbidden,
            supervise=forbidden,
        )
    assert not (case.root / "runs").exists()


def test_supervisor_malformed_diagnostic_does_not_fake_completion(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    report = run(
        case,
        plan_id,
        supervise=lambda budget: SimpleNamespace(
            reason="finished", exit_code=0, elapsed_ns=1, stdout=b"malformed", stderr=b""
        ),
    )
    assert report["status"] == "stopped" and report["stop_reason"] == "worker_failed"
    assert report["execution"] is None
