"""Public bounded commands reject confirmation and unsafe requests before output IO."""

import json
from types import SimpleNamespace

import pytest

from tickwitness.cli import main
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.campaign_supervisor import CampaignSupervision
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.application.search_planning import freeze_search_plan
from tickwitness.domain.evidence.run_records import canonical


def forbidden(*_args, **_kwargs):
    raise AssertionError("Must deny before output IO or supervisor")


def common(root):
    return ["--plans", str(root / "plans"), "--store", str(root / "data"),
            "--registry", str(root / "registry"), "--runs", str(root / "runs")]


def prepare(case):
    assumption = {"kind": "assumption_request_v1", "schema_version": 1,
                  "scenario_kind": "COUNTERFACTUAL_STRESS",
                  "transform": {"semantic_id": "replay_receive_suffix_shift_v1", "from_capture_seq": 2},
                  "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
                  "parameter_basis": {"kind": "researcher_defined", "calibration_status": "uncalibrated",
                                      "calibration_evidence_refs": []}}
    request = {"kind": "search_plan_request_v1", "schema_version": 1, "search_seed": 7,
               "max_proposals": 1, "generator": {"kind": "grid", "values_ns": [0]}}
    return freeze_search_plan(
        case.frozen.protocol_id, canonical(assumption), canonical(request), split="development",
        registry_factory=lambda: case.registry, datasets_factory=lambda: case.data,
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans", create=True),
    )["plan_id"]


@pytest.mark.parametrize("command", ["run-bounded-search-plan", "inspect-bounded-search-campaign"])
def test_confirmation_denied_before_id_file_and_output(tmp_path, capsys, monkeypatch, command):
    root = tmp_path / "absent"
    monkeypatch.setattr(LocalCampaignBudgetStore, "__init__", forbidden)
    extra = ["missing.json", "--input-root", str(root)] if command.startswith("run-") else []
    assert main([command, "bad", *extra, *common(root), "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert not root.exists()


def test_invalid_budget_does_not_create_runs(experiment_case, capsys, monkeypatch):
    case = experiment_case
    plan_id = prepare(case)
    (case.root / "bad.json").write_bytes(b'{"schema_version":true}')
    monkeypatch.setattr(LocalCampaignBudgetStore, "__init__", forbidden)
    assert main(["run-bounded-search-plan", plan_id, "bad.json", "--input-root", str(case.root),
                 *common(case.root)]) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]["code"] == "invalid_research_evidence"
    assert not (case.root / "runs").exists()


def test_time_limit_report_is_stdout_repeat_and_inspect_never_supervise(experiment_case, capsys, monkeypatch):
    case = experiment_case
    plan_id = prepare(case)
    budget = {"kind": "campaign_budget_request_v1", "schema_version": 1,
              "max_evaluations": 1, "max_wall_time_ms": 1, "max_storage_bytes": 32 * 1024 * 1024}
    (case.root / "budget.json").write_bytes(canonical(budget))
    calls = []
    def timed(payload, *, timeout_ms):
        calls.append(timeout_ms)
        return CampaignSupervision("time_limit", 8, 1_000_001, b"", b"")
    monkeypatch.setattr("tickwitness.cli_campaign_budgets.supervise_campaign", timed)
    command = ["run-bounded-search-plan", plan_id, "budget.json", "--input-root", str(case.root), *common(case.root)]
    assert main(command) == 8
    output = capsys.readouterr()
    assert not output.err
    report = json.loads(output.out)
    assert report["stop_reason"] == "time_limit" and report["execution"] is None
    assert calls == [1]
    monkeypatch.setattr("tickwitness.cli_campaign_budgets.supervise_campaign", forbidden)
    assert main(command) == 8
    assert json.loads(capsys.readouterr().out) == report
    assert main(["inspect-bounded-search-campaign", plan_id, *common(case.root)]) == 0
    assert json.loads(capsys.readouterr().out) == report
