"""The public v2 CLI completes real native flows or records a consumed failure."""

import importlib.util
import json
from pathlib import Path

import pytest

from tickwitness.cli import main


def common(case) -> list[str]:
    return ["--store", str(case.root / "data"), "--registry", str(case.root / "registry")]


def execution(case) -> list[str]:
    return [
        "replay-protocol",
        case.frozen.protocol_id,
        *common(case),
        "--runs",
        str(case.root / "runs"),
    ]


def test_executable_cli_complete_or_consumed_missing_dependency(
    experiment_case, capsys: pytest.CaptureFixture[str]
) -> None:
    case = experiment_case
    (case.root / "experiment.json").write_text(json.dumps(case.request))
    assert (
        main(
            [
                "freeze-experiment",
                "experiment.json",
                "--input-root",
                str(case.root),
                "--development-dataset",
                case.development,
                "--confirmation-dataset",
                case.confirmation,
                *common(case),
                "--id-only",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == case.frozen.protocol_id
    assert main(["inspect-experiment", case.frozen.protocol_id, *common(case)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["document"]["read_policy"] == "development_only_v1"
    native = importlib.util.find_spec("nautilus_trader") is not None

    assert main(execution(case)) == (0 if native else 6)
    output = capsys.readouterr()
    if not native:
        failure = json.loads(output.err)["error"]
        assert output.out == ""
        assert failure["budget_consumed"] is True
        assert (
            main(["inspect-attempt", failure["attempt_id"], "--runs", str(case.root / "runs")]) == 0
        )
        state = json.loads(capsys.readouterr().out)
        assert state["outcome"]["error"]["code"] == "engine_unavailable"
        assert main(execution(case)) == 6
        capsys.readouterr()
        assert main(execution(case)) == 8
        assert json.loads(capsys.readouterr().err)["error"]["code"] == "attempt_budget_exhausted"
        return
    submission = json.loads(output.out)
    assert submission["evaluation"]["claim_observation"]["value"] == "-2"
    assert submission["evaluation"]["claim_observation"]["satisfied"] is True
    run_id = submission["run_id"]
    assert main(["inspect-run", run_id, *common(case), "--runs", str(case.root / "runs")]) == 0
    assert json.loads(capsys.readouterr().out)["verification"]["native_replayed"] is False
    target = case.root / "exported"
    assert (
        main(
            [
                "export-evidence",
                run_id,
                str(target),
                *common(case),
                "--runs",
                str(case.root / "runs"),
            ]
        )
        == 0
    )
    exported = json.loads(capsys.readouterr().out)
    assert main(["verify-evidence", str(target)]) == 0
    assert json.loads(capsys.readouterr().out) == exported
    assert (
        main(
            [
                "export-evidence",
                run_id,
                str(target),
                *common(case),
                "--runs",
                str(case.root / "runs"),
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "bundle_destination_exists"


def test_confirmation_replay_does_not_create_any_repositories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "replay-protocol",
                "0" * 64,
                "--split",
                "confirmation",
                "--store",
                str(tmp_path / "data"),
                "--registry",
                str(tmp_path / "registry"),
                "--runs",
                str(tmp_path / "runs"),
            ]
        )
        == 5
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_invalid_executable_identity_fails_argument_parsing_before_io(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["inspect-attempt", "../escape", "--runs", str(tmp_path / "runs")])
    assert caught.value.code == 2
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []


def test_unknown_attempt_never_creates_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["inspect-attempt", "0" * 64, "--runs", str(tmp_path / "runs")]) == 4
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "research_evidence_not_found"
    assert not (tmp_path / "runs").exists()
