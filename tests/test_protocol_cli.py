"""Protocol commands exercise real immutable files without running strategy code."""

import json
from pathlib import Path

import pytest

from tickwitness.cli import main


@pytest.fixture
def inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    ids = []
    for capture in (1, 3):
        event = {
            "schema_version": 1,
            "type": "snapshot",
            "source": "synthetic",
            "instrument": "TEST-USD",
            "session": "protocol-cli",
            "capture_seq": capture,
            "event_time_ns": capture * 100,
            "receive_time_ns": None,
            "last_sequence": capture * 10,
            "bids": [[99 * capture, 5]],
            "asks": [[99 * capture + 2, 5]],
        }
        name = f"capture-{capture}.jsonl"
        (tmp_path / name).write_text(json.dumps(event) + "\n")
        assert (
            main(
                [
                    "import-events",
                    name,
                    "--input-root",
                    str(tmp_path),
                    "--store",
                    str(tmp_path / "data"),
                    "--id-only",
                ]
            )
            == 0
        )
        ids.append(capsys.readouterr().out.strip())
    request = {
        "schema_version": 1,
        "claim": {
            "title": "Synthetic claim",
            "hypothesis": "The declared marked result is positive",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "0.00",
            "unit": "synthetic_quote_units",
        },
        "strategy_name": "never_executed",
        "parameters": {},
        "configuration": {
            "fee_model_id": "unbound",
            "execution_model_id": "unbound",
            "clock_policy_id": "capture_order_unbound_v1",
        },
        "budget": {"max_scenarios": 10, "max_wall_seconds": 60, "max_events": 10},
        "seed": 42,
    }
    (tmp_path / "request.json").write_text(json.dumps(request))
    (tmp_path / "strategy.py").write_text("raise RuntimeError('must never execute')\n")
    return {
        "development": ids[0],
        "confirmation": ids[1],
        "request": request,
    }


def freeze_args(tmp_path: Path, inputs: dict[str, object]) -> list[str]:
    return [
        "freeze-protocol",
        "request.json",
        "--input-root",
        str(tmp_path),
        "--strategy-source",
        "strategy.py",
        "--development-dataset",
        str(inputs["development"]),
        "--confirmation-dataset",
        str(inputs["confirmation"]),
        "--store",
        str(tmp_path / "data"),
        "--registry",
        str(tmp_path / "registry"),
    ]


def access_args(command: str, identity: str, tmp_path: Path) -> list[str]:
    return [
        command,
        identity,
        "--store",
        str(tmp_path / "data"),
        "--registry",
        str(tmp_path / "registry"),
    ]


def test_protocol_cli_complete_local_workflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], inputs: dict[str, object]
) -> None:
    args = freeze_args(tmp_path, inputs)
    assert main(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    identity = receipt["protocol_id"]
    assert receipt["created"] is True
    assert receipt["document"]["execution_ready"] is False
    assert receipt["document"]["datasets"]["confirmation"] == inputs["confirmation"]

    assert main(args) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["created"] is False
    assert repeated["protocol_id"] == identity
    assert main([*args, "--id-only"]) == 0
    assert capsys.readouterr().out.strip() == identity

    assert main(access_args("inspect-protocol", identity, tmp_path)) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["document"] == receipt["document"]
    assert "observations" not in inspected

    read = access_args("read-protocol-data", identity, tmp_path)
    assert main([*read, "--limit", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dataset_id"] == inputs["development"]
    assert result["observations"][0]["bids"] == [[99, 5]]
    assert main([*read, "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"

    assert main([*read, "--limit", "11"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_protocol"


def test_confirmation_denial_precedes_missing_repository_access(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = access_args("read-protocol-data", "0" * 64, tmp_path)

    assert main([*args, "--split", "confirmation"]) == 5

    assert json.loads(capsys.readouterr().err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "failure", ["bad_json", "unknown_field", "syntax", "symlink", "missing_data"]
)
def test_invalid_freeze_never_creates_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], inputs: dict[str, object], failure: str
) -> None:
    if failure == "bad_json":
        (tmp_path / "request.json").write_text("{broken")
    elif failure == "unknown_field":
        (tmp_path / "request.json").write_text(
            json.dumps(dict(inputs["request"], execution_ready=True))
        )
    elif failure == "syntax":
        (tmp_path / "strategy.py").write_text("def broken(")
    elif failure == "symlink":
        (tmp_path / "strategy.py").unlink()
        (tmp_path / "strategy.py").symlink_to(tmp_path / "request.json")
    else:
        inputs["confirmation"] = "0" * 64

    code = main(freeze_args(tmp_path, inputs))

    assert code == (4 if failure == "missing_data" else 2)
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize("command", ["inspect-protocol", "read-protocol-data"])
def test_missing_protocol_has_distinct_failure_and_no_store_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    assert main(access_args(command, "0" * 64, tmp_path)) == 4

    assert json.loads(capsys.readouterr().err)["error"]["code"] == "protocol_not_found"
    assert list(tmp_path.iterdir()) == []


def test_protocol_tampering_returns_integrity_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], inputs: dict[str, object]
) -> None:
    assert main([*freeze_args(tmp_path, inputs), "--id-only"]) == 0
    identity = capsys.readouterr().out.strip()
    path = tmp_path / "registry" / "protocols" / f"{identity}.json"
    original = path.read_bytes()
    path.write_bytes(original.replace(b'"execution_ready":false', b'"execution_ready":true'))

    assert main(access_args("inspect-protocol", identity, tmp_path)) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "protocol_integrity_or_publication_failure"


def test_invalid_protocol_id_rejected_before_storage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(access_args("inspect-protocol", "../escape", tmp_path))

    assert caught.value.code == 2
    assert "protocol_id" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
