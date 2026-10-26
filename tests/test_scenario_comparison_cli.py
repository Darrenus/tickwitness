"""CLI pairing reads committed evidence and never opens a new execution path."""

import json
from pathlib import Path

import pytest

from tickwitness.application.experiments import run_experiment
from tickwitness.application.scenario_execution import run_scenario
from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def prepare(case):
    options = {
        "split": "development",
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
        "ledger_factory": case.ledger_factory,
        "engine_factory": case.engine_factory,
    }
    left = run_experiment(case.frozen.protocol_id, **options)
    examples = Path(__file__).resolve().parents[1] / "examples"
    candidate = json.loads((examples / "scenario-request.json").read_bytes())
    candidate["additional_delay"]["value"] = 0
    right = run_scenario(
        case.frozen.protocol_id,
        (examples / "assumption-request.json").read_bytes(),
        json.dumps(candidate).encode(),
        **options,
    )
    return left, right


def command(root: Path, baseline_id: str = "0" * 64, scenario_id: str = "1" * 64) -> list[str]:
    return [
        "compare-scenario-runs",
        baseline_id,
        scenario_id,
        "--store",
        str(root / "data"),
        "--registry",
        str(root / "registry"),
        "--runs",
        str(root / "runs"),
    ]


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_cli_zero_pair_is_stable_core_only_and_opens_existing_roots_read_only(
    experiment_case, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    left, right = prepare(case)
    before = snapshot(case.root)
    opened = []

    def guard_initialization(cls, label):
        original = cls.__init__

        def read_only(self, root, *, create=True):
            assert create is False
            opened.append(label)
            original(self, root, create=create)

        monkeypatch.setattr(cls, "__init__", read_only)

    for cls, label in (
        (LocalAttemptLedger, "runs"),
        (LocalExecutableProtocolRegistry, "registry"),
        (LocalDatasetStore, "data"),
    ):
        guard_initialization(cls, label)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Comparison cannot execute or mutate an attempt")

    for name in ("reserve", "publish", "bind_intent"):
        monkeypatch.setattr(LocalAttemptLedger, name, forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    outputs = []
    for _ in range(2):
        assert main(command(case.root, left.run_id, right.run_id)) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        outputs.append(json.loads(captured.out))
    assert outputs[0] == outputs[1]
    report = outputs[0]
    comparison_id = report.pop("comparison_id")
    assert comparison_id == digest(canonical(report))
    assert report["kind"] == "scenario_comparison_v1"
    assert report["numeric_comparison"]["delta"] == "0"
    assert report["trace_comparison"]["business"]["first_divergence"] is None
    assert report["trace_comparison"]["business_trace_changed"] is False
    assert report["strictly_paired"] is False
    assert report["scope"]["baseline_claim_recomputed_for_integrity"] is True
    assert report["scope"]["scenario_claim_evaluated"] is False
    assert report["scope"]["claim_verdict_issued"] is False
    assert set(opened) == {"runs", "registry", "data"}
    assert snapshot(case.root) == before


def test_cli_confirmation_denial_precedes_invalid_ids_and_absent_roots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [*command(tmp_path, "../invalid", "not-an-id"), "--split", "confirmation"]
    assert main(args) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("side", ["baseline", "scenario"])
def test_cli_invalid_identity_precedes_storage_initialization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, side: str
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid identities cannot initialize storage")

    for cls in (LocalAttemptLedger, LocalExecutableProtocolRegistry, LocalDatasetStore):
        monkeypatch.setattr(cls, "__init__", forbidden)
    values = {"baseline": "0" * 64, "scenario": "1" * 64, side: "../invalid"}
    assert main(command(tmp_path, values["baseline"], values["scenario"])) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_research_evidence"
    assert list(tmp_path.iterdir()) == []


def test_cli_missing_roots_stay_absent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(command(tmp_path)) == 4
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "research_evidence_not_found"
    assert list(tmp_path.iterdir()) == []


def test_cli_reversed_roles_are_a_validation_error(
    experiment_case, capsys: pytest.CaptureFixture[str]
) -> None:
    case = experiment_case
    left, right = prepare(case)
    assert main(command(case.root, right.run_id, left.run_id)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_research_evidence"


def test_cli_corrupt_derived_evidence_is_a_store_error(
    experiment_case, capsys: pytest.CaptureFixture[str]
) -> None:
    case = experiment_case
    left, right = prepare(case)
    victim = case.root / "runs" / "objects" / "sha256" / right.derived_view_id
    victim.write_bytes(victim.read_bytes() + b" ")
    assert main(command(case.root, left.run_id, right.run_id)) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "research_store_integrity_or_io_failure"
