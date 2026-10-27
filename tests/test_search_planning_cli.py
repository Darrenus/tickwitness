"""Installed command boundary semantics without native workers or attempt storage."""

import json
import os

import pytest

from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def write_requests(root):
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
    search = {
        "kind": "search_plan_request_v1",
        "schema_version": 1,
        "search_seed": 17,
        "max_proposals": 4,
        "generator": {"kind": "grid", "values_ns": [0, 0, 10_000_000, 30_000_000]},
    }
    for name, value in (("assumption.json", assumption), ("search.json", search)):
        (root / name).write_text(json.dumps(value), encoding="utf-8")


def common(root):
    return [
        "--store",
        str(root / "data"),
        "--registry",
        str(root / "registry"),
        "--plans",
        str(root / "plans"),
    ]


def freeze_command(case):
    return [
        "freeze-search-plan",
        case.frozen.protocol_id,
        "assumption.json",
        "search.json",
        "--input-root",
        str(case.root),
        *common(case.root),
    ]


def snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def forbidden(*_args, **_kwargs):
    raise AssertionError("Planning must not construct a worker or ledger, or change source")


def test_cli_plan_repetition_and_inspect_are_readonly_outside_plan_namespace(
    experiment_case, capsys, monkeypatch
):
    case = experiment_case
    write_requests(case.root)
    before = snapshot(case.root)
    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "publish", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "seal", forbidden)
    assert main(freeze_command(case)) == 0
    output = capsys.readouterr()
    assert output.err == ""
    first = json.loads(output.out)
    assert first["created"] is True
    after = snapshot(case.root)
    assert {name: raw for name, raw in after.items() if not name.startswith("plans/")} == before
    assert main(freeze_command(case)) == 0
    assert json.loads(capsys.readouterr().out) == dict(first, created=False)
    monkeypatch.setattr(LocalSearchPlanRegistry, "seal", forbidden)
    assert main(["inspect-search-plan", first["plan_id"], *common(case.root)]) == 0
    assert json.loads(capsys.readouterr().out) == dict(first, created=False)
    assert snapshot(case.root) == after
    assert not (case.root / "runs").exists()


@pytest.mark.parametrize("command", ["freeze-search-plan", "inspect-search-plan"])
def test_cli_confirmation_fails_before_bad_id_missing_request_or_factories(
    tmp_path, capsys, monkeypatch, command
):
    monkeypatch.setattr(LocalSearchPlanRegistry, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "__init__", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "__init__", forbidden)
    root = tmp_path / "absent"
    arguments = [command, "invalid"]
    if command == "freeze-search-plan":
        arguments += ["missing.json", "missing.json", "--input-root", str(root)]
    assert main([*arguments, *common(root), "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert not root.exists()


def test_missing_plan_directory_is_not_created(tmp_path, capsys):
    root = tmp_path / "absent"
    assert main(["inspect-search-plan", "0" * 64, *common(root)]) == 4
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "research_evidence_not_found"
    assert not root.exists()


@pytest.mark.parametrize("attack", ["duplicate_json", "float", "unknown", "symlink", "oversize"])
def test_cli_invalid_or_unsafe_request_never_creates_plan_storage(experiment_case, capsys, attack):
    case = experiment_case
    write_requests(case.root)
    path = case.root / "search.json"
    if attack == "duplicate_json":
        path.write_bytes(b'{"schema_version":1,"schema_version":1}')
    elif attack == "float":
        path.write_bytes(b'{"schema_version":1.0}')
    elif attack == "unknown":
        request = json.loads(path.read_bytes())
        request["execute"] = True
        path.write_text(json.dumps(request))
    elif attack == "symlink":
        target = case.root / "real.json"
        path.rename(target)
        path.symlink_to(target)
    else:
        path.write_bytes(b" " * (64 * 1024 + 1))
    assert main(freeze_command(case)) == 2
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == (
        "unsafe_input" if attack in ("symlink", "oversize") else "invalid_search_plan"
    )
    assert not (case.root / "plans").exists()


def test_cli_corrupt_committed_plan_does_not_repair_it(experiment_case, capsys):
    case = experiment_case
    write_requests(case.root)
    assert main(freeze_command(case)) == 0
    result = json.loads(capsys.readouterr().out)
    path = case.root / "plans" / "search-plans" / (result["plan_id"] + ".json")
    path.write_bytes(b"{}")
    before = snapshot(case.root)
    assert main(["inspect-search-plan", result["plan_id"], *common(case.root)]) == 3
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "research_store_integrity_or_io_failure"
    assert snapshot(case.root) == before


def test_cli_fifo_request_is_refused_without_blocking(experiment_case, capsys):
    case = experiment_case
    write_requests(case.root)
    path = case.root / "search.json"
    path.unlink()
    os.mkfifo(path)
    assert main(freeze_command(case)) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "unsafe_input"
    assert not (case.root / "plans").exists()
