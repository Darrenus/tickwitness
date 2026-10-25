"""Public qualification commands use installed workers and machine-readable results."""

import importlib.util
import json
from pathlib import Path

import pytest

from tickwitness.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def import_sample(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    assert (
        main(
            [
                "import-events",
                "replay-partials.jsonl",
                "--input-root",
                str(EXAMPLES),
                "--store",
                str(tmp_path / "data"),
                "--id-only",
            ]
        )
        == 0
    )
    return capsys.readouterr().out.strip()


def replay_args(tmp_path: Path, identity: str) -> list[str]:
    return [
        "replay-dataset",
        identity,
        "replay-spec.json",
        "--input-root",
        str(EXAMPLES),
        "--store",
        str(tmp_path / "data"),
    ]


def test_cli_replay_and_result_file_comparison(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    identity = import_sample(tmp_path, capsys)
    native = importlib.util.find_spec("nautilus_trader") is not None
    assert main(replay_args(tmp_path, identity)) == (0 if native else 6)
    output = capsys.readouterr()
    if not native:
        assert output.out == ""
        assert json.loads(output.err)["error"]["code"] == "engine_unavailable"
        return
    result = json.loads(output.out)
    assert result["dataset_id"] == identity
    assert result["execution_status"] == "completed"
    assert len(result["fill_trace"]) == 2
    assert result["completeness"]["pending_commands"] == []
    (tmp_path / "left.json").write_text(output.out)
    (tmp_path / "right.json").write_text(output.out)

    assert main(["compare-replays", "left.json", "right.json", "--input-root", str(tmp_path)]) == 0
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["strictly_paired"] is True
    assert comparison["semantically_equal"] is True


@pytest.mark.parametrize("failure", ["unknown_data", "bad_timeout", "research_request", "symlink"])
def test_replay_input_failures_have_no_store_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    (tmp_path / "replay-spec.json").write_bytes((EXAMPLES / "replay-spec.json").read_bytes())
    args = [
        "replay-dataset",
        "0" * 64,
        "replay-spec.json",
        "--input-root",
        str(tmp_path),
        "--store",
        str(tmp_path / "missing-store"),
    ]
    if failure == "bad_timeout":
        args.extend(["--timeout-seconds", "61"])
    elif failure == "research_request":
        (tmp_path / "replay-spec.json").write_bytes(
            (EXAMPLES / "research-request.json").read_bytes()
        )
    elif failure == "symlink":
        (tmp_path / "replay-spec.json").unlink()
        (tmp_path / "replay-spec.json").symlink_to(EXAMPLES / "replay-spec.json")

    assert main(args) == (4 if failure == "unknown_data" else 2)
    output = capsys.readouterr()
    assert output.out == ""
    assert (
        json.loads(output.err)["error"]["code"]
        == {
            "unknown_data": "dataset_not_found",
            "bad_timeout": "invalid_replay",
            "research_request": "invalid_replay",
            "symlink": "unsafe_input",
        }[failure]
    )
    assert not (tmp_path / "missing-store").exists()


def test_clock_rejection_precedes_native_dependency_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = [
        json.loads(line) for line in (EXAMPLES / "replay-partials.jsonl").read_text().splitlines()
    ]
    events[0]["receive_time_ns"] = None
    (tmp_path / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    assert (
        main(
            [
                "import-events",
                "events.jsonl",
                "--input-root",
                str(tmp_path),
                "--store",
                str(tmp_path / "data"),
                "--id-only",
            ]
        )
        == 0
    )
    identity = capsys.readouterr().out.strip()

    assert main(replay_args(tmp_path, identity)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_replay"


def test_comparison_rejects_unvalidated_documents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "left.json").write_text("{}\n")
    (tmp_path / "right.json").write_text("{}\n")

    assert main(["compare-replays", "left.json", "right.json", "--input-root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_replay"
