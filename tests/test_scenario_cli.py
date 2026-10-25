"""The real scenario CLI checks bounded files and saved data without executing them."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def write_requests(root: Path) -> tuple[dict, dict]:
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
        "additional_delay": {"value": 20_000_000, "unit": "ns"},
    }
    (root / "assumption.json").write_text(json.dumps(assumption), encoding="utf-8")
    (root / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    return assumption, scenario


def arguments(
    root: Path,
    protocol_id: str = "0" * 64,
    *,
    assumption: str = "assumption.json",
    scenario: str = "scenario.json",
    input_root: Path | None = None,
) -> list[str]:
    return [
        "validate-scenario",
        protocol_id,
        assumption,
        scenario,
        "--input-root",
        str(root if input_root is None else input_root),
        "--store",
        str(root / "data"),
        "--registry",
        str(root / "registry"),
    ]


def test_real_cli_validation_is_stable_without_native_or_attempts(
    experiment_case, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    assumption, scenario = write_requests(case.root)
    original = case.data.read_normalized(case.development)
    inventory = tuple(record.dataset_id for record in case.data.list_datasets())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Scenario validation cannot start an engine or reserve an attempt")

    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "publish", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "seal", forbidden)
    command = arguments(case.root, case.frozen.protocol_id)
    assert main(command) == 0
    output = capsys.readouterr()
    assert output.err == ""
    first = json.loads(output.out)
    assert first.keys() == {"assumption", "scenario", "validation"}
    validation = first["validation"]
    assert validation["kind"] == "validated_scenario_constraints_v1"
    assert validation["source_bindings_verified"] is True
    assert validation["input_constraints_verified"] is True
    assert validation["execution_approved"] is False
    assert validation["calibration_status"] == "uncalibrated"
    assert validation["scenario_kind"] == "COUNTERFACTUAL_STRESS"
    assert validation["additional_delay"] == {"value": 20_000_000, "unit": "ns"}
    assert validation["bindings"] == {
        "protocol_id": case.frozen.protocol_id,
        "development_dataset_id": case.development,
        "normalized_sha256": hashlib.sha256(original).hexdigest(),
        "replay_spec_id": case.frozen.document["replay_spec_id"],
    }
    assert first["scenario"]["assumption_id"] == validation["assumption_id"]

    for name, request in (("assumption", assumption), ("scenario", scenario)):
        (case.root / f"{name}.json").write_text(
            json.dumps(request, sort_keys=True, indent=2), encoding="utf-8"
        )
    assert main([*command, "--split", "development"]) == 0
    repeated = capsys.readouterr()
    assert repeated.err == ""
    assert json.loads(repeated.out) == first
    assert case.data.read_normalized(case.development) == original
    assert tuple(record.dataset_id for record in case.data.list_datasets()) == inventory
    assert not (case.root / "runs").exists()


@pytest.mark.parametrize("protocol_id", ["0" * 64, "../invalid-protocol"])
def test_confirmation_is_denied_before_missing_or_unsafe_requests_and_repositories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], protocol_id: str
) -> None:
    command = arguments(
        tmp_path,
        protocol_id,
        assumption="../outside.json",
        scenario="missing.json",
        input_root=tmp_path / "missing-input-root",
    )
    assert main([*command, "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("role", ["assumption", "scenario"])
@pytest.mark.parametrize(
    "failure", ["traversal", "absolute", "extension", "symlink", "parent_symlink", "fifo", "size"]
)
def test_unsafe_request_files_fail_before_repository_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], role: str, failure: str
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    write_requests(input_root)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    relative = f"{role}.json"
    selected = input_root / relative
    if failure == "traversal":
        relative = "../outside.json"
    elif failure == "absolute":
        relative = str(outside)
    elif failure == "extension":
        relative = "request.txt"
        (input_root / relative).write_bytes(selected.read_bytes())
    elif failure == "symlink":
        selected.unlink()
        selected.symlink_to(outside)
    elif failure == "parent_symlink":
        (input_root / "linked").symlink_to(tmp_path, target_is_directory=True)
        relative = "linked/outside.json"
    elif failure == "fifo":
        selected.unlink()
        os.mkfifo(selected)
    else:
        selected.write_bytes(b" " * (64 * 1024 + 1))
    names = {role: relative}

    assert main(arguments(tmp_path, input_root=input_root, **names)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "unsafe_input"
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "registry").exists()
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("role", ["assumption", "scenario"])
@pytest.mark.parametrize("raw", [b"\xff", b"{broken", b'{"kind":"one","kind":"two"}'])
def test_invalid_json_requests_have_a_distinct_contract_failure(
    experiment_case, capsys: pytest.CaptureFixture[str], role: str, raw: bytes
) -> None:
    case = experiment_case
    write_requests(case.root)
    (case.root / f"{role}.json").write_bytes(raw)

    assert main(arguments(case.root, case.frozen.protocol_id)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_scenario_contract"
    assert not (case.root / "runs").exists()


@pytest.mark.parametrize("failure", ["range", "kind", "calibration", "binding"])
def test_invalid_or_overclaimed_scenario_contract_is_not_a_successful_validation(
    experiment_case, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    case = experiment_case
    assumption, scenario = write_requests(case.root)
    if failure == "range":
        scenario["additional_delay"]["value"] = 20_000_001
    elif failure == "kind":
        scenario["scenario_kind"] = "COMPATIBLE_WORLD"
    elif failure == "calibration":
        assumption["parameter_basis"]["calibration_status"] = "calibrated"
    else:
        assumption["bindings"] = {"development_dataset_id": case.confirmation}
    for name, request in (("assumption", assumption), ("scenario", scenario)):
        (case.root / f"{name}.json").write_text(json.dumps(request), encoding="utf-8")

    assert main(arguments(case.root, case.frozen.protocol_id)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_scenario_contract"
    assert not (case.root / "runs").exists()


@pytest.mark.parametrize("protocol_id", ["../escape", "A" * 64, "0" * 63])
def test_invalid_protocol_identity_never_creates_repositories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], protocol_id: str
) -> None:
    write_requests(tmp_path)

    assert main(arguments(tmp_path, protocol_id)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_scenario_contract"
    assert {path.name for path in tmp_path.iterdir()} == {"assumption.json", "scenario.json"}


def test_missing_protocol_has_a_not_found_error_without_creating_any_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_requests(tmp_path)

    assert main(arguments(tmp_path)) == 4
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "research_evidence_not_found"
    assert {path.name for path in tmp_path.iterdir()} == {"assumption.json", "scenario.json"}


@pytest.mark.parametrize("role", ["raw", "protocol"])
def test_real_stored_evidence_tampering_is_an_integrity_failure(
    experiment_case, capsys: pytest.CaptureFixture[str], role: str
) -> None:
    case = experiment_case
    write_requests(case.root)
    if role == "raw":
        path = case.root / "data" / "objects" / "sha256" / hashlib.sha256(case.raw).hexdigest()
        code = "store_integrity_or_publication_failure"
    else:
        path = case.root / "registry" / "protocols" / f"{case.frozen.protocol_id}.json"
        code = "research_store_integrity_or_io_failure"
    path.write_bytes(path.read_bytes() + b" ")

    assert main(arguments(case.root, case.frozen.protocol_id)) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == code
    assert not (case.root / "runs").exists()
