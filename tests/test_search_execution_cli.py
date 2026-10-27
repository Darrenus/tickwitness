"""CLI errors and persistent automatic evaluation use the same application boundary."""

import json

import pytest

from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError, SubprocessReplayAdapter


def args(case, command, plan_id):
    return [
        command,
        plan_id,
        "--plans",
        str(case.root / "plans"),
        "--store",
        str(case.root / "data"),
        "--registry",
        str(case.root / "registry"),
        "--runs",
        str(case.root / "runs"),
    ]


def setup_plan(case):
    root = case.root
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
    request = {
        "kind": "search_plan_request_v1",
        "schema_version": 1,
        "search_seed": 3,
        "max_proposals": 3,
        "generator": {"kind": "grid", "values_ns": [0, 0, 1]},
    }
    (root / "assumption.json").write_text(json.dumps(assumption))
    (root / "search.json").write_text(json.dumps(request))
    from tickwitness.application.search_planning import freeze_search_plan
    from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry

    return freeze_search_plan(
        case.frozen.protocol_id,
        json.dumps(assumption).encode(),
        json.dumps(request).encode(),
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        plans_factory=lambda: LocalSearchPlanRegistry(root / "plans", create=True),
    )["plan_id"]


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def forbidden(*_args, **_kwargs):
    raise AssertionError("Forbidden work before denial or during read-only inspection")


@pytest.mark.parametrize("command", ["run-search-plan", "inspect-search-campaign"])
def test_confirmation_fails_before_ids_io_and_factories(tmp_path, capsys, monkeypatch, command):
    root = tmp_path / "never-created"
    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(LocalSearchCampaignStore, "__init__", forbidden)
    assert (
        main(
            [
                command,
                "invalid-id",
                "--plans",
                str(root / "plans"),
                "--store",
                str(root / "store"),
                "--registry",
                str(root / "registry"),
                "--runs",
                str(root / "runs"),
                "--split",
                "confirmation",
            ]
        )
        == 5
    )
    output = capsys.readouterr()
    assert (
        not output.out and json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    )
    assert not root.exists()


def test_missing_plan_does_not_construct_runs(tmp_path, capsys):
    root = tmp_path / "absent"
    assert (
        main(
            [
                "run-search-plan",
                "0" * 64,
                "--plans",
                str(root / "plans"),
                "--store",
                str(root / "store"),
                "--registry",
                str(root / "registry"),
                "--runs",
                str(root / "runs"),
            ]
        )
        == 4
    )
    output = capsys.readouterr()
    assert (
        not output.out and json.loads(output.err)["error"]["code"] == "research_evidence_not_found"
    )
    assert not root.exists()


def test_failure_report_uses_stdout_and_repeat_inspection_never_reexecutes(
    experiment_case, capsys, monkeypatch
):
    case = experiment_case
    plan_id = setup_plan(case)

    def missing_engine(*_args, **_kwargs):
        raise ReplayProcessError("engine_unavailable", "optional native extra is unavailable", 6)

    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", missing_engine)
    assert main(args(case, "run-search-plan", plan_id)) == 6
    output = capsys.readouterr()
    assert output.err == ""
    report = json.loads(output.out)
    assert report["status"] == "stopped" and report["counts"]["reserved"] == 1
    assert report["candidates"][0]["status"] == "FAILED"
    assert report["candidates"][1]["status"] == "NOT_DISPATCHED"
    before = tree(case.root)
    monkeypatch.setattr(LocalAttemptLedger, "reserve_with_nonce", forbidden)
    monkeypatch.setattr(LocalAttemptLedger, "publish", forbidden)
    monkeypatch.setattr(LocalSearchCampaignStore, "write_dispatch", forbidden)
    monkeypatch.setattr(LocalSearchCampaignStore, "write_stop", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    assert main(args(case, "inspect-search-campaign", plan_id)) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert main(args(case, "run-search-plan", plan_id)) == 6
    assert json.loads(capsys.readouterr().out) == report
    assert tree(case.root) == before


def test_repeated_run_does_not_recreate_deleted_ledger_directory(
    experiment_case, capsys, monkeypatch
):
    case = experiment_case
    plan_id = setup_plan(case)

    def missing_engine(*_args, **_kwargs):
        raise ReplayProcessError("engine_unavailable", "missing engine", 6)

    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", missing_engine)
    assert main(args(case, "run-search-plan", plan_id)) == 6
    capsys.readouterr()
    # Keep records intact while removing an otherwise empty mandatory namespace.
    path = case.root / "runs" / "slots"
    moved = case.root / "original-slots"
    path.rename(moved)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    assert main(args(case, "run-search-plan", plan_id)) == 3
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "research_store_integrity_or_io_failure"
    assert not path.exists()
