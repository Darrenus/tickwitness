"""Actual saved-fixture ledger audits feed readonly conditional conclusions.

The coordinator clock is explicitly injected. Process timing and native replay
qualification stay in their separate remote tests and installed-wheel workflows.
"""

import hashlib
import json
import secrets
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.bounded_search import (
    inspect_bounded_search_campaign,
    run_bounded_search_campaign,
)
from tickwitness.application.experiments import freeze_experiment, run_experiment
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_execution import inspect_search_campaign, run_search_plan
from tickwitness.application.search_findings import (
    evaluate_search_findings,
    freeze_search_finding_protocol,
    inspect_search_finding_protocol,
)
from tickwitness.application.search_planning import freeze_search_plan
from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.domain.research_contracts.search_finding_protocol import (
    SearchFindingValidationError,
)
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.campaign_resource_guard import (
    CampaignLimitReached,
    CampaignResourceGuard,
    activate_resource_guard,
)
from tickwitness.infrastructure.local_dataset_store import DatasetStoreError
from tickwitness.infrastructure.search_campaign_store import (
    LocalSearchCampaignStore,
    SearchCampaignNotFoundError,
)
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def forbidden(*_args, **_kwargs):
    raise AssertionError("Conclusion must not execute, reserve, publish or use the network")


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def finding_request(title="Finite declared receive-delay check"):
    return canonical(
        {
            "kind": "search_finding_request_v1",
            "schema_version": 1,
            "title": title,
            "authority": "conditional_stress_search_findings_v1",
        }
    )


def prepare(case, *, threshold="-3", values=None, seed=7, ambiguous=False):
    request = json.loads(canonical(case.request))
    request["claim"]["threshold"] = threshold
    if ambiguous:
        request["replay_spec"]["instrument"]["price_increment"] = "100.00065"
        request["replay_spec"]["account"]["starting_cash"] = "1000000000"
        request["replay_spec"]["fees"]["maker_rate"] = "1"
    case.frozen = freeze_experiment(
        canonical(request),
        development_dataset_id=case.development,
        confirmation_dataset_id=case.confirmation,
        datasets_factory=lambda: case.data,
        registry_factory=lambda: case.registry,
    )
    candidates = [0] if values is None else values
    plan_id = freeze_search_plan(
        case.frozen.protocol_id,
        canonical(
            {
                "kind": "assumption_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "transform": {
                    "semantic_id": "replay_receive_suffix_shift_v1",
                    "from_capture_seq": 2,
                },
                "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
                "parameter_basis": {
                    "kind": "researcher_defined",
                    "calibration_status": "uncalibrated",
                    "calibration_evidence_refs": [],
                },
            }
        ),
        canonical(
            {
                "kind": "search_plan_request_v1",
                "schema_version": 1,
                "search_seed": seed,
                "max_proposals": len(candidates),
                "generator": {"kind": "grid", "values_ns": candidates},
            }
        ),
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans", create=True),
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
    )["plan_id"]
    frozen = freeze_search_finding_protocol(
        plan_id,
        finding_request(),
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
        findings_factory=lambda: LocalSearchFindingRegistry(case.root / "findings", create=True),
    )
    return plan_id, frozen["protocol_id"]


def inner(case, plan_id):
    budgets = LocalCampaignBudgetStore(case.root / "runs")
    try:
        campaigns = LocalSearchCampaignStore(budgets.managed_root(plan_id))
    except SearchCampaignNotFoundError:
        return None
    if campaigns.get_campaign(plan_id) is None:
        return None
    return inspect_search_campaign(
        plan_id,
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=lambda: LocalAttemptLedger(case.root / "runs", create=False),
        campaigns_factory=lambda: campaigns,
    )


def inspect(case, plan_id):
    return inspect_bounded_search_campaign(
        plan_id,
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        budgets_factory=lambda: LocalCampaignBudgetStore(case.root / "runs"),
        execution_inspector=lambda: inner(case, plan_id),
    )


def execute(case, plan_id, *, evaluations=2, mode="normal", engine_factory=None):
    def supervise(budget):
        now = [1]
        deadline = budget.document["limits"]["max_wall_time_ms"] * 1_000_000 + 1
        budgets = LocalCampaignBudgetStore(case.root / "runs", create=True)
        guard = CampaignResourceGuard(budget, budgets, lambda: now[0], deadline)
        calls = []

        def admit(ordinal):
            if mode == "clean-time" and ordinal > 1:
                now[0] = deadline
            guard.admit(ordinal)

        def engine(timeout):
            calls.append(timeout)
            if len(calls) > 1:
                if mode == "active-time":
                    now[0] = deadline
                    raise CampaignLimitReached("time_limit")
                if mode == "second-failure":
                    raise RuntimeError("Injected second worker failure\nwith detail\tretained")
            return (engine_factory or case.engine_factory)(timeout)

        try:
            with activate_resource_guard(guard):
                result = run_search_plan(
                    plan_id,
                    split="development",
                    plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
                    registry_factory=lambda: case.registry,
                    datasets_factory=lambda: case.data,
                    ledger_factory=lambda: LocalAttemptLedger(case.root / "runs"),
                    ledger_reader_factory=lambda: LocalAttemptLedger(
                        case.root / "runs", create=False
                    ),
                    campaigns_factory=lambda: LocalSearchCampaignStore(
                        budgets.managed_root(plan_id), create=True
                    ),
                    engine_factory=engine,
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

    return run_bounded_search_campaign(
        plan_id,
        canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": evaluations,
                "max_wall_time_ms": 20_000,
                "max_storage_bytes": 512 * 1024 * 1024,
            }
        ),
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        budgets_factory=lambda: LocalCampaignBudgetStore(case.root / "runs", create=True),
        execution_inspector=lambda: inner(case, plan_id),
        supervise=supervise,
        nonce_factory=lambda: secrets.token_hex(16),
    )


def evaluate(case, authority_id, **changes):
    arguments = {
        "split": "development",
        "findings_factory": lambda: LocalSearchFindingRegistry(case.root / "findings"),
        "campaign_inspector": lambda plan_id: inspect(case, plan_id),
    }
    arguments.update(changes)
    return evaluate_search_findings(authority_id, **arguments)


def test_completed_positive_scope_reuses_baseline_budget_and_is_strictly_readonly(
    experiment_case, monkeypatch
):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    baseline = run_experiment(
        case.frozen.protocol_id,
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )
    campaign = execute(case, plan_id)
    candidate = campaign["execution"]["candidates"][0]
    assert candidate["attempt_index"] == 2 and candidate["attempt_id"] != baseline.attempt_id
    before = tree(case.root)
    for name in ("reserve", "reserve_with_nonce", "bind_intent", "publish"):
        monkeypatch.setattr(LocalAttemptLedger, name, forbidden)
    for name in ("start", "write_allocation", "write_stop"):
        monkeypatch.setattr(LocalCampaignBudgetStore, name, forbidden)
    for name in ("start", "write_dispatch", "write_link", "write_result", "write_stop"):
        monkeypatch.setattr(LocalSearchCampaignStore, name, forbidden)
    monkeypatch.setattr(LocalSearchFindingRegistry, "freeze", forbidden)
    monkeypatch.setattr(BoundedReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    receipt = evaluate(case, authority_id)
    assert receipt["kind"] == "search_finding_receipt_v1"
    assert receipt["report"]["outcome"] == "NO_COUNTEREXAMPLE_FOUND"
    assert receipt["report"]["coverage"]["coverage_complete_for_plan"] is True
    assert receipt["report"]["candidate_assessments"][0]["truth"] is True
    assert receipt["report"]["scope"]["source_claim_evaluated"] is False
    assert receipt["finalization_status"] == "LOCAL_REAUDITED"
    assert receipt["verification"]["native_replayed"] is False
    assert receipt["verification"]["attempt_reserved"] is False
    assert evaluate(case, authority_id) == receipt
    inspected = inspect_search_finding_protocol(
        authority_id,
        split="development",
        findings_factory=lambda: LocalSearchFindingRegistry(case.root / "findings"),
    )
    assert inspected["created"] is False
    assert tree(case.root) == before
    assert campaign["scope"]["finding_issued"] is False
    assert candidate["evaluation"]["scope"]["search_performed"] is False


@pytest.mark.parametrize("mode", ["evaluation", "clean-time"])
def test_clean_budget_prefix_can_report_only_its_actual_positive_subset(experiment_case, mode):
    case = experiment_case
    plan_id, authority_id = prepare(case, values=[0, 1])
    campaign = execute(case, plan_id, evaluations=1 if mode == "evaluation" else 2, mode=mode)
    assert campaign["status"] == "stopped" and campaign["exit_code"] == 8
    receipt = evaluate(case, authority_id)
    report = receipt["report"]
    assert report["outcome"] == "NO_COUNTEREXAMPLE_FOUND"
    assert report["coverage"]["true_ordinals"] == [1]
    assert report["coverage"]["unevaluated_ordinals"] == [2]
    assert report["coverage"]["coverage_complete_for_plan"] is False
    assert [row["status"] for row in report["candidate_assessments"]] == [
        "COMPLETED",
        "NOT_DISPATCHED",
    ]


def test_time_exhaustion_with_a_consumed_unfinalized_attempt_is_not_positive(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case, values=[0, 1])
    campaign = execute(case, plan_id, mode="active-time")
    assert campaign["stop_reason"] == "time_limit"
    assert campaign["execution"]["counts"]["reserved"] == 2
    receipt = evaluate(case, authority_id)
    assert receipt["report"]["outcome"] == "NOT_EVALUABLE"
    assert receipt["report"]["finding_issued"] is False
    assert [row["status"] for row in receipt["report"]["candidate_assessments"]] == [
        "COMPLETED",
        "RESERVED_UNFINALIZED",
    ]


@pytest.mark.parametrize(
    "threshold,expected",
    [("-3", "NOT_EVALUABLE"), ("0", "COUNTEREXAMPLE_FOUND")],
)
def test_later_failure_never_erases_a_false_witness_or_invents_a_positive_conclusion(
    experiment_case, threshold, expected
):
    case = experiment_case
    plan_id, authority_id = prepare(case, threshold=threshold, values=[0, 1])
    campaign = execute(case, plan_id, mode="second-failure")
    assert campaign["execution"]["counts"]["failed"] == 1
    before = tree(case.root)
    receipt = evaluate(case, authority_id)
    report = receipt["report"]
    assert report["outcome"] == expected
    assert report["coverage"]["audited_ordinals"] == [1]
    assert report["coverage"]["coverage_complete_for_plan"] is False
    assert report["candidate_assessments"][1]["error"]["message"] == (
        "Injected second worker failure\nwith detail\tretained"
    )
    assert [row["ordinal"] for row in report["witnesses"]] == (
        [1] if expected == "COUNTEREXAMPLE_FOUND" else []
    )
    assert tree(case.root) == before


def ambiguous_engine(_timeout):
    """Transform a saved callback fixture into the existing fee-ambiguity oracle."""

    def money(cents):
        return f"{cents // 100}.{cents % 100:02d}"

    class Engine:
        def run(self, replay_input):
            document = json.loads(
                (Path(__file__).parents[1] / "fixtures" / "evidence-result.json").read_bytes()
            )
            document.update(dataset_id=replay_input.dataset_id, spec_id=replay_input.spec.spec_id)
            assert (
                document["data_sha256"] == hashlib.sha256(replay_input.normalized_bytes).hexdigest()
            )
            for fill in document["fill_trace"]:
                fill["fields"].update(
                    price="10000.065",
                    commission="10000.06",
                    declared_fee_rate="1",
                    exact_decimal_fee_before_native_quantization="10000.065",
                    native_commission_minus_exact_decimal_fee="-0.005",
                )
            for row in document["account_trace"]:
                fields = row["fields"]
                count = fields["observed_fill_lots"]
                total = 100_000_000_000 - count * 1_000_006
                locked = int(fields["cash_locked"]) * 100
                fields.update(
                    cash_total=money(total),
                    cash_free=money(total - locked),
                    observed_commission=money(count * 1_000_006),
                )
            return build_replay_result(document)

    return Engine()


def test_audited_completed_but_fee_ambiguous_metric_remains_unknown(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case, ambiguous=True)
    campaign = execute(case, plan_id, engine_factory=ambiguous_engine)
    candidate = campaign["execution"]["candidates"][0]
    assert candidate["status"] == "COMPLETED" and candidate["raw_result_audited"] is True
    assert candidate["evaluation"]["metric_observation"]["eligible"] is False
    assert candidate["evaluation"]["replay_evaluation"]["ineligibility_reason"] == (
        "ambiguous_native_fee_model"
    )
    receipt = evaluate(case, authority_id)
    assert receipt["report"]["outcome"] == "NOT_EVALUABLE"
    assert receipt["report"]["coverage"]["unknown_ordinals"] == [1]
    assert receipt["report"]["candidate_assessments"][0]["truth"] is None


def test_zero_eligible_candidates_never_create_a_vacuous_positive_result(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case, values=[30_000_000])
    campaign = execute(case, plan_id, engine_factory=forbidden)
    assert campaign["status"] == "completed"
    receipt = evaluate(case, authority_id)
    assert receipt["report"]["outcome"] == "NOT_EVALUABLE"
    assert receipt["report"]["coverage"]["eligible_ordinals"] == []
    assert receipt["report"]["coverage"]["coverage_complete_for_plan"] is False


def test_reauditing_changed_actual_source_fails_instead_of_publishing_a_finding(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    execute(case, plan_id)
    raw = case.root / "data" / "objects" / "sha256" / hashlib.sha256(case.raw).hexdigest()
    raw.write_bytes(case.raw + b" ")
    before = tree(case.root)
    with pytest.raises(DatasetStoreError):
        evaluate(case, authority_id)
    assert tree(case.root) == before


@pytest.mark.parametrize("operation", ["freeze", "inspect", "evaluate"])
def test_confirmation_is_denied_before_identity_and_ports(operation):
    with pytest.raises(ConfirmationAccessDenied):
        if operation == "freeze":
            freeze_search_finding_protocol(
                "bad",
                b"bad",
                split="confirmation",
                plans_factory=forbidden,
                findings_factory=forbidden,
            )
        elif operation == "inspect":
            inspect_search_finding_protocol("bad", split="confirmation", findings_factory=forbidden)
        else:
            evaluate_search_findings(
                "bad",
                split="confirmation",
                findings_factory=forbidden,
                campaign_inspector=forbidden,
            )


def test_invalid_finding_request_never_opens_the_writer(experiment_case):
    case = experiment_case
    plan_id, _authority_id = prepare(case)
    with pytest.raises(SearchFindingValidationError):
        freeze_search_finding_protocol(
            plan_id,
            b'{"schema_version":true}',
            split="development",
            plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
            findings_factory=forbidden,
        )


def test_wrong_authority_is_rejected_before_campaign_inspection(experiment_case):
    case = experiment_case
    _plan_id, authority_id = prepare(case)
    actual = LocalSearchFindingRegistry(case.root / "findings").get(authority_id)
    with pytest.raises(SearchFindingValidationError, match="different authority"):
        evaluate_search_findings(
            "f" * 64,
            split="development",
            findings_factory=lambda: SimpleNamespace(get=lambda _identity: actual),
            campaign_inspector=forbidden,
        )
