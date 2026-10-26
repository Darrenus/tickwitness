"""Installed command boundaries preserve queue-validation scope and source evidence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment
from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def saved_case(root: Path):
    data = LocalDatasetStore(root / "data")
    development = import_events(
        (EXAMPLES / "queue-observations.jsonl").read_bytes(), lambda: data
    ).dataset_id
    confirmation = import_events(
        (EXAMPLES / "replay-confirmation.jsonl").read_bytes(), lambda: data
    ).dataset_id
    registry = LocalExecutableProtocolRegistry(root / "registry")
    frozen = freeze_experiment(
        (EXAMPLES / "experiment-request.json").read_bytes(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
    )
    return SimpleNamespace(root=root, data=data, registry=registry, frozen=frozen)


def command(root: Path, protocol_id: str = "0" * 64, *, source=None, name=None) -> list[str]:
    return [
        "validate-queue-constraints", protocol_id,
        "queue-constraint-request.json" if name is None else name,
        "--input-root", str(EXAMPLES if source is None else source),
        "--store", str(root / "data"), "--registry", str(root / "registry"),
    ]


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_cli_two_allocations_are_stable_native_free_and_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = saved_case(tmp_path)
    before = snapshot(tmp_path)
    opened = []

    def read_only_initialization(cls, label):
        original = cls.__init__

        def guard(self, root, *, create=True):
            assert create is False
            opened.append(label)
            original(self, root, create=create)

        monkeypatch.setattr(cls, "__init__", guard)

    for cls, label in ((LocalDatasetStore, "data"), (LocalExecutableProtocolRegistry, "registry")):
        read_only_initialization(cls, label)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Queue validation cannot construct execution or write evidence")

    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "publish", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "seal", forbidden)
    outputs = []
    for _ in range(2):
        assert main(command(tmp_path, saved.frozen.protocol_id)) == 0
        output = capsys.readouterr()
        assert output.err == ""
        outputs.append(json.loads(output.out))
    assert outputs[0] == outputs[1]
    document = outputs[0]
    assert document["constraint_id"] == digest(canonical(document["constraint"]))
    assert document["validation_id"] == digest(canonical(document["validation"]))
    assert document["validation"]["classification"] == "MODEL_SENSITIVITY_CANDIDATE"
    for field in (
        "actual_acceptance_verified", "impact_compatibility_verified",
        "native_execution_verified", "execution_approved",
    ):
        assert document["validation"][field] is False
    front, back = document["validation"]["interpretations"]
    assert front["final_state"] == {"ahead_lots": 0, "behind_lots": 2, "external_lots": 2}
    assert back["final_state"] == {"ahead_lots": 2, "behind_lots": 0, "external_lots": 2}
    assert set(opened) == {"registry", "data"}
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "runs").exists()


def test_cli_confirmation_denial_precedes_missing_request_and_all_adapters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Confirmation request cannot initialize storage or execution")

    for cls in (LocalDatasetStore, LocalExecutableProtocolRegistry, LocalAttemptLedger, SubprocessReplayAdapter):
        monkeypatch.setattr(cls, "__init__", forbidden)
    args = command(tmp_path, "../invalid", source=tmp_path / "missing", name="absent.json")
    assert main([*args, "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("protocol_id", ["../escape", "A" * 64, "0" * 63])
def test_cli_bad_identity_rejects_before_storage_initialization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, protocol_id
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid identity cannot initialize storage")

    monkeypatch.setattr(LocalDatasetStore, "__init__", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "__init__", forbidden)
    assert main(command(tmp_path, protocol_id)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_queue_constraints"
    assert list(tmp_path.iterdir()) == []


def test_cli_missing_roots_are_not_created(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(command(tmp_path)) == 4
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "research_evidence_not_found"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mutation", ["double_count", "missing_trade", "duplicate_trade", "bool", "limit", "unit", "self_binding", "observation_label"])
def test_cli_illegal_gross_flow_or_proof_claim_is_a_validation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutation: str
) -> None:
    saved = saved_case(tmp_path)
    proposed = json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())
    if mutation == "double_count":
        proposed["updates"][2]["cancellations_lots"] = 3
    elif mutation == "missing_trade":
        proposed["updates"][2]["trade_capture_seqs"] = []
    elif mutation == "duplicate_trade":
        proposed["updates"][2]["trade_capture_seqs"] = [4, 4]
    elif mutation == "bool":
        proposed["updates"][1]["cancellations_lots"] = True
    elif mutation == "limit":
        proposed["updates"][1]["additions_lots"] = 1_000_000_001
    elif mutation == "unit":
        proposed["updates"][1]["unit"] = "seconds"
    elif mutation == "self_binding":
        proposed["bindings"] = {"protocol_id": saved.frozen.protocol_id}
    else:
        proposed["classification"] = "OBSERVATION_COMPATIBLE"
    path = tmp_path / "proposed.json"
    path.write_text(json.dumps(proposed), encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(command(tmp_path, saved.frozen.protocol_id, source=tmp_path, name=path.name)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_queue_constraints"
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "runs").exists()


def test_cli_unknown_or_missing_request_is_safe_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(command(tmp_path, source=tmp_path / "absent", name="missing.json")) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "unsafe_input"
    assert list(tmp_path.iterdir()) == []
