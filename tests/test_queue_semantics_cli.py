"""The semantic read path cannot execute models or manufacture verdict authority."""

import json
from pathlib import Path

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment
from tickwitness.application.queue_execution import freeze_queue_family, run_queue_family
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.queue_family_registry import LocalQueueFamilyRegistry
from tickwitness.infrastructure.queue_replay import QueueSubprocessReplayAdapter

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def command(root, left="0" * 64, right="1" * 64):
    return [
        "qualify-queue-pair",
        left,
        right,
        "--store",
        str(root / "data"),
        "--families",
        str(root / "families"),
        "--runs",
        str(root / "runs"),
    ]


def forbidden(*_args, **_kwargs):
    raise AssertionError("Semantic qualification must not open forbidden storage or execution")


def snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_installed_command_rechecks_durable_pair_without_execution_or_mutation(
    tmp_path,
    capsys,
    monkeypatch,
    queue_result_factory,
):
    data = LocalDatasetStore(tmp_path / "data")
    ids = [
        import_events((EXAMPLES / name).read_bytes(), lambda: data).dataset_id
        for name in ("queue-observations.jsonl", "replay-confirmation.jsonl")
    ]
    registry = LocalExecutableProtocolRegistry(tmp_path / "registry")
    source = freeze_experiment(
        (EXAMPLES / "experiment-request.json").read_bytes(),
        development_dataset_id=ids[0],
        confirmation_dataset_id=ids[1],
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
    )
    families = LocalQueueFamilyRegistry(tmp_path / "families")
    family = freeze_queue_family(
        source.protocol_id,
        (EXAMPLES / "queue-family-request.json").read_bytes(),
        (EXAMPLES / "queue-constraint-request.json").read_bytes(),
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        families_factory=lambda: families,
    )
    ledger = LocalAttemptLedger(tmp_path / "runs")

    class Engine:
        def run(self, replay_input):
            return queue_result_factory(replay_input)

    submissions = run_queue_family(
        family.family_id,
        split="development",
        families_factory=lambda: families,
        datasets_factory=lambda: data,
        ledger_factory=lambda: ledger,
        replay_factory=lambda _: Engine(),
    )
    left, right = [row["run_id"] for row in submissions["runs"]]
    before = snapshot(tmp_path)
    for owner, method in (
        (LocalAttemptLedger, "reserve"),
        (LocalAttemptLedger, "bind_intent"),
        (LocalAttemptLedger, "publish"),
        (LocalDatasetStore, "publish"),
        (LocalQueueFamilyRegistry, "seal"),
        (QueueSubprocessReplayAdapter, "__init__"),
    ):
        monkeypatch.setattr(owner, method, forbidden)
    outputs = []
    for a, b in ((left, right), (right, left)):
        assert main(command(tmp_path, a, b)) == 0
        output = capsys.readouterr()
        assert output.err == ""
        outputs.append(json.loads(output.out))
    assert outputs[0] == outputs[1]
    qualified = outputs[0]
    assert qualified["observation_compatibility"]["status"] == "not_established"
    assert qualified["predicate"]["truth_divergence"] is None
    assert qualified["predicate"]["satisfied"] == {
        "cancel_front_first_v1": None,
        "cancel_back_first_v1": None,
    }
    assert qualified["findings"] == []
    assert qualified["scope"]["source_claim_evaluated"] is False
    assert qualified["verification"]["native_replayed"] is False
    front, back = qualified["models"]
    assert front["single_counted_insertion"]["status"] == "contradiction"
    assert front["single_counted_insertion"]["checkpoints"][-1]["mismatch_lots"] == 1
    assert back["single_counted_insertion"]["status"] == "necessary_checks_passed"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "left,right", [("bad-id", "1" * 64), ("0" * 64, "../bad"), ("0" * 64, "0" * 64)]
)
def test_id_rejection_precedes_all_factories(tmp_path, capsys, monkeypatch, left, right):
    for owner in (
        LocalDatasetStore,
        LocalQueueFamilyRegistry,
        LocalAttemptLedger,
        QueueSubprocessReplayAdapter,
    ):
        monkeypatch.setattr(owner, "__init__", forbidden)
    assert main(command(tmp_path, left, right)) == 2
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err)["error"]
    assert list(tmp_path.iterdir()) == []


def test_confirmation_denial_precedes_bad_ids_and_all_factories(tmp_path, capsys, monkeypatch):
    for owner in (
        LocalDatasetStore,
        LocalQueueFamilyRegistry,
        LocalAttemptLedger,
        QueueSubprocessReplayAdapter,
    ):
        monkeypatch.setattr(owner, "__init__", forbidden)
    assert main([*command(tmp_path, "../invalid", "also-invalid"), "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_missing_evidence_roots_are_not_created(tmp_path, capsys):
    assert main(command(tmp_path)) == 4
    assert json.loads(capsys.readouterr().err)["error"]
    assert list(tmp_path.iterdir()) == []
