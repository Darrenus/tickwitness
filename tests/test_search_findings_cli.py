"""Authority lifecycle and fail-closed CLI boundaries without replay side effects."""

import json

import pytest

from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical


def arguments(command, root):
    result = [command, "invalid-id"]
    if command == "freeze-search-finding-protocol":
        result += ["missing.json", "--input-root", str(root), "--plans", str(root / "plans")]
    if command == "evaluate-search-findings":
        for name in ("plans", "store", "registry", "runs"):
            result += [f"--{name}", str(root / name)]
    return [*result, "--finding-registry", str(root / "findings")]


@pytest.mark.parametrize(
    "command",
    [
        "freeze-search-finding-protocol",
        "inspect-search-finding-protocol",
        "evaluate-search-findings",
    ],
)
def test_confirmation_rejected_before_identity_input_or_store(tmp_path, capsys, command):
    root = tmp_path / "missing"
    assert main([*arguments(command, root), "--split", "confirmation"]) == 5
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"]["code"] == "confirmation_access_denied"
    assert not root.exists()


@pytest.mark.parametrize("command", ["inspect-search-finding-protocol", "evaluate-search-findings"])
def test_missing_authority_root_is_not_created(tmp_path, capsys, command):
    root = tmp_path / "missing"
    command_args = arguments(command, root)
    command_args[1] = "a" * 64
    assert main(command_args) == 4
    assert not capsys.readouterr().out
    assert not root.exists()


def prepare_authority(case, tmp_path, capsys):
    inputs = tmp_path / "requests"
    inputs.mkdir()
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
        "search_seed": 7,
        "max_proposals": 1,
        "generator": {"kind": "grid", "values_ns": [0]},
    }
    request = {
        "kind": "search_finding_request_v1",
        "schema_version": 1,
        "title": "Saved fixture stress criterion",
        "authority": "conditional_stress_search_findings_v1",
    }
    for name, value in (("assumption", assumption), ("search", search), ("finding", request)):
        (inputs / f"{name}.json").write_bytes(canonical(value))
    plans = case.root / "plans"
    assert (
        main(
            [
                "freeze-search-plan",
                case.frozen.protocol_id,
                "assumption.json",
                "search.json",
                "--input-root",
                str(inputs),
                "--plans",
                str(plans),
                "--store",
                str(case.root / "data"),
                "--registry",
                str(case.root / "registry"),
            ]
        )
        == 0
    )
    plan_id = json.loads(capsys.readouterr().out)["plan_id"]
    findings = case.root / "findings"
    freeze = [
        "freeze-search-finding-protocol",
        plan_id,
        "finding.json",
        "--input-root",
        str(inputs),
        "--plans",
        str(plans),
        "--finding-registry",
        str(findings),
    ]
    assert main(freeze) == 0
    frozen = json.loads(capsys.readouterr().out)
    return frozen, freeze, findings, inputs


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_freeze_inspect_repeat_and_no_execution(experiment_case, tmp_path, capsys):
    case = experiment_case
    frozen, freeze, findings, _inputs = prepare_authority(case, tmp_path, capsys)
    assert frozen["created"] is True
    before = tree(case.root)
    assert (
        main(
            [
                "inspect-search-finding-protocol",
                frozen["protocol_id"],
                "--finding-registry",
                str(findings),
            ]
        )
        == 0
    )
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["protocol"] == frozen["protocol"]
    assert inspected["created"] is False
    assert main(freeze) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated == inspected
    assert tree(case.root) == before
    assert not (case.root / "runs").exists()


def test_valid_authority_does_not_create_a_missing_campaign(experiment_case, tmp_path, capsys):
    case = experiment_case
    frozen, _freeze, findings, _inputs = prepare_authority(case, tmp_path, capsys)
    command = [
        "evaluate-search-findings",
        frozen["protocol_id"],
        "--finding-registry",
        str(findings),
    ]
    for option, path in (
        ("plans", "plans"),
        ("store", "data"),
        ("registry", "registry"),
        ("runs", "runs"),
    ):
        command += [f"--{option}", str(case.root / path)]
    before = tree(case.root)
    assert main(command) == 4
    assert not capsys.readouterr().out
    assert tree(case.root) == before


def test_invalid_authority_request_does_not_publish(experiment_case, tmp_path, capsys):
    case = experiment_case
    _frozen, freeze, _findings, inputs = prepare_authority(case, tmp_path, capsys)
    (inputs / "bad.json").write_bytes(b'{"kind":"search_finding_request_v1"}')
    rejected = case.root / "rejected-findings"
    freeze[2] = "bad.json"
    freeze[-1] = str(rejected)
    assert main(freeze) == 2
    assert not capsys.readouterr().out
    assert not rejected.exists()
