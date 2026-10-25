"""The scenario CLI preserves failure lineage and inspects saved evidence without replay."""

import importlib.util
import json
from pathlib import Path

import pytest

from tickwitness.application.scenario_execution import run_scenario
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def write_requests(root: Path, *, delay: int = 0) -> tuple[bytes, bytes]:
    assumption = {
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
    scenario = {
        "kind": "scenario_request_v1",
        "schema_version": 1,
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "additional_delay": {"value": delay, "unit": "ns"},
    }
    raw = json.dumps(assumption).encode(), json.dumps(scenario).encode()
    (root / "assumption.json").write_bytes(raw[0])
    (root / "scenario.json").write_bytes(raw[1])
    return raw


def common(root: Path) -> list[str]:
    return [
        "--store",
        str(root / "data"),
        "--registry",
        str(root / "registry"),
        "--runs",
        str(root / "runs"),
    ]


def command(root: Path, protocol_id: str = "0" * 64) -> list[str]:
    return [
        "run-scenario",
        protocol_id,
        "assumption.json",
        "scenario.json",
        "--input-root",
        str(root),
        *common(root),
    ]


def inspect_failure(root: Path, attempt_id: str, capsys: pytest.CaptureFixture[str]) -> dict:
    assert (
        main(["inspect-scenario-attempt", attempt_id, "--runs", str(root / "runs")]) == 0
    )
    output = capsys.readouterr()
    assert output.err == ""
    state = json.loads(output.out)
    assert state["state"] == "finalized"
    assert state["budget_consumed"] is True
    assert state["scenario_intent"]["scope"]["baseline_claim_evaluated"] is False
    assert state["scenario_intent"]["scope"]["search_performed"] is False
    assert state["outcome"]["kind"] == "scenario_attempt_failure_v1"
    assert state["outcome"]["intent"] == state["scenario_intent"]
    return state


def test_unavailable_worker_is_consumed_and_inspectable_without_optional_native(
    experiment_case, capsys: pytest.CaptureFixture[str]
) -> None:
    case = experiment_case
    write_requests(case.root)
    unavailable = case.root / "nonexistent-engine-python"
    args = [*command(case.root, case.frozen.protocol_id), "--engine-python", str(unavailable)]
    attempts = []
    for _ in range(2):
        assert main(args) == 6
        output = capsys.readouterr()
        assert output.out == ""
        error = json.loads(output.err)["error"]
        assert error["code"] == "engine_unavailable"
        assert error["budget_consumed"] is True
        attempts.append(error["attempt_id"])
        state = inspect_failure(case.root, error["attempt_id"], capsys)
        assert state["outcome"]["error"]["code"] == "engine_unavailable"
    assert len(set(attempts)) == 2
    assert main(args) == 8
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "attempt_budget_exhausted"
    assert not unavailable.exists()


def test_installed_core_worker_missing_native_keeps_the_same_intent_receipt(
    experiment_case, capsys: pytest.CaptureFixture[str]
) -> None:
    if importlib.util.find_spec("nautilus_trader") is not None:
        pytest.skip("Missing-native path is exercised by the core-only environment")
    case = experiment_case
    write_requests(case.root)

    assert main(command(case.root, case.frozen.protocol_id)) == 6
    output = capsys.readouterr()
    assert output.out == ""
    error = json.loads(output.err)["error"]
    assert error["code"] == "engine_unavailable"
    assert error["budget_consumed"] is True
    inspect_failure(case.root, error["attempt_id"], capsys)


def test_cli_inspects_a_saved_native_zero_shift_run_without_engine_construction(
    experiment_case, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    assumption, scenario = write_requests(case.root)
    submission = run_scenario(
        case.frozen.protocol_id,
        assumption,
        scenario,
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Inspection must not construct or invoke the native worker")

    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    assert main(["inspect-scenario-run", submission.run_id, *common(case.root)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    inspected = json.loads(output.out)
    assert inspected["evaluation"] == submission.evaluation
    assert inspected["verification"]["native_replayed"] is False
    assert inspected["verification"]["derivation_recomputed"] is True
    assert inspected["verification"]["accounting_verified"] is True
    assert "claim_observation" not in inspected["evaluation"]
    assert inspected["evaluation"]["metric_observation"]["value"] == "-2"

    assert (
        main(
            [
                "inspect-scenario-attempt",
                submission.attempt_id,
                "--runs",
                str(case.root / "runs"),
            ]
        )
        == 0
    )
    state = json.loads(capsys.readouterr().out)
    assert state["state"] == "finalized"
    assert state["scenario_intent"] == inspected["receipt"]["intent"]
    assert state["outcome"]["kind"] == "scenario_run_receipt_v1"


def test_confirmation_denial_precedes_missing_request_reads_and_all_repository_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*command(tmp_path, "../invalid"), "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_invalid_scenario_fails_before_ledger_construction(
    experiment_case, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    write_requests(case.root, delay=20_000_001)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid scenario must not open the ledger or engine")

    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    assert main(command(case.root, case.frozen.protocol_id)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_scenario_contract"
    assert not (case.root / "runs").exists()


def test_missing_scenario_run_query_creates_no_ledger_registry_or_dataset_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["inspect-scenario-run", "0" * 64, *common(tmp_path)]) == 4
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "research_evidence_not_found"
    assert list(tmp_path.iterdir()) == []
