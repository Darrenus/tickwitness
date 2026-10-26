"""Queue CLI exercises durable stores and the real audit behind a controlled engine port."""

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
from tickwitness.infrastructure.queue_family_registry import LocalQueueFamilyRegistry
from tickwitness.infrastructure.queue_replay import QueueSubprocessReplayAdapter
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
POLICIES = ("cancel_front_first_v1", "cancel_back_first_v1")
COMMANDS = (
    "freeze-queue-family",
    "run-queue-family",
    "run-queue-model",
    "inspect-queue-family",
    "inspect-queue-run",
)


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
    (root / "family.json").write_bytes(canonical({
        "kind": "queue_family_request_v1", "schema_version": 1,
        "cancel_at_capture_seq": 6,
        "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 1000},
    }))
    (root / "queue.json").write_bytes((EXAMPLES / "queue-constraint-request.json").read_bytes())
    return SimpleNamespace(root=root, data=data, registry=registry, frozen=frozen)


def command(root: Path, name: str, identity: str = "0" * 64,
            *, family_request="family.json", queue_request="queue.json", input_root=None):
    args = [name, identity]
    if name == "freeze-queue-family":
        args.extend([family_request, queue_request, "--input-root", str(input_root or root),
                     "--registry", str(root / "registry")])
    else:
        if name == "run-queue-model":
            args.append(POLICIES[0])
        args.extend(["--runs", str(root / "runs")])
    return [*args, "--families", str(root / "families"), "--store", str(root / "data")]


def freeze(case, capsys):
    assert main(command(case.root, "freeze-queue-family", case.frozen.protocol_id)) == 0
    output = capsys.readouterr()
    assert output.err == ""
    return json.loads(output.out)


def snapshot(root: Path):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


def forbidden(*_args, **_kwargs):
    raise AssertionError("This command must not read files or initialize storage/execution")


def test_freeze_pair_and_readonly_inspection_reaudit_committed_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    queue_result_factory,
) -> None:
    case = saved_case(tmp_path)
    frozen = freeze(case, capsys)
    assert frozen["created"] is True
    assert frozen["family_id"] == digest(canonical(frozen["family"]))
    assert frozen["family"]["source_protocol"] == case.frozen.document
    assert frozen["family"]["policies"] == list(POLICIES)
    repeated = freeze(case, capsys)
    assert repeated["created"] is False
    assert repeated["family_id"] == frozen["family_id"]
    calls = []

    def engine_run(_self, request):
        calls.append(request)
        return queue_result_factory(request)

    monkeypatch.setattr(QueueSubprocessReplayAdapter, "run", engine_run)
    assert main(command(tmp_path, "run-queue-family", frozen["family_id"])) == 0
    output = capsys.readouterr()
    assert output.err == ""
    pair = json.loads(output.out)
    assert pair["status"] == "completed" and pair["failures"] == []
    assert pair["failed_policy_ids"] == pair["pending_policy_ids"] == []
    assert [row["policy_id"] for row in pair["runs"]] == list(POLICIES)
    assert [row["evaluation"]["filled_quantity_lots"] for row in pair["runs"]] == [1, 0]
    assert [row["evaluation"]["actual_commission"] for row in pair["runs"]] == ["1", "0"]
    assert len({row["attempt_id"] for row in pair["runs"]}) == 2
    assert len(calls) == 2 and calls[0].normalized_bytes == calls[1].normalized_bytes
    before = snapshot(tmp_path)
    opened = []

    def readonly(cls, label):
        original = cls.__init__

        def initialize(self, root, *, create=True):
            assert create is False
            opened.append(label)
            original(self, root, create=create)

        monkeypatch.setattr(cls, "__init__", initialize)

    for cls, label in ((LocalDatasetStore, "data"), (LocalQueueFamilyRegistry, "families"),
                       (LocalAttemptLedger, "runs")):
        readonly(cls, label)
    monkeypatch.setattr(QueueSubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "__init__", forbidden)
    for cls, method in ((LocalDatasetStore, "publish"), (LocalQueueFamilyRegistry, "seal"),
                        (LocalAttemptLedger, "reserve"), (LocalAttemptLedger, "bind_intent"),
                        (LocalAttemptLedger, "publish")):
        monkeypatch.setattr(cls, method, forbidden)
    assert main(command(tmp_path, "inspect-queue-family", frozen["family_id"])) == 0
    output = capsys.readouterr()
    assert output.err == ""
    inspected_family = json.loads(output.out)
    assert inspected_family["budget"]["consumed_attempts"] == 2
    assert inspected_family["budget"]["remaining_attempts"] == 0
    assert inspected_family["verification"]["native_replayed"] is False
    assert inspected_family["verification"]["source_bindings_verified"] is True
    assert len(inspected_family["attempts"]) == 2
    for submission in pair["runs"]:
        assert main(command(tmp_path, "inspect-queue-run", submission["run_id"])) == 0
        output = capsys.readouterr()
        assert output.err == ""
        inspected = json.loads(output.out)
        assert inspected["evaluation"] == submission["evaluation"]
        assert inspected["receipt"]["intent"]["policy_id"] == submission["policy_id"]
        assert inspected["verification"]["queue_execution_audited"] is True
        assert inspected["verification"]["native_replayed"] is False
        assert inspected["evaluation"]["scope"]["impact_compatibility_verified"] is False
        assert inspected["evaluation"]["scope"]["claim_verdict_issued"] is False
        assert inspected["evaluation"]["scope"]["valuation_issued"] is False
    assert set(opened) == {"data", "families", "runs"}
    assert len(calls) == 2
    assert snapshot(tmp_path) == before


def test_pair_and_single_model_share_budget_and_exhaustion_returns_exit_eight(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    queue_result_factory,
) -> None:
    case = saved_case(tmp_path)
    family_id = freeze(case, capsys)["family_id"]
    calls = []

    def engine_run(_self, request):
        calls.append(request.policy_id)
        return queue_result_factory(request)

    monkeypatch.setattr(QueueSubprocessReplayAdapter, "run", engine_run)
    assert main(command(tmp_path, "run-queue-family", family_id)) == 0
    capsys.readouterr()
    before = snapshot(tmp_path)
    assert main(command(tmp_path, "run-queue-family", family_id)) == 8
    output = capsys.readouterr()
    assert output.err == ""
    exhausted = json.loads(output.out)
    assert exhausted["status"] == "failed" and exhausted["runs"] == []
    assert exhausted["failures"][0]["code"] == "attempt_budget_exhausted"
    assert exhausted["failures"][0]["attempt_id"] is None
    assert exhausted["failures"][0]["budget_consumed"] is False
    assert main(command(tmp_path, "run-queue-model", family_id)) == 8
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "attempt_budget_exhausted"
    assert calls == list(POLICIES)
    assert snapshot(tmp_path) == before


def test_partial_pair_preserves_success_and_failure_and_returns_worker_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    queue_result_factory,
) -> None:
    case = saved_case(tmp_path)
    family_id = freeze(case, capsys)["family_id"]

    def engine_run(_self, request):
        if request.policy_id == POLICIES[1]:
            raise ReplayProcessError("engine_unavailable", "Controlled unavailable worker", 6)
        return queue_result_factory(request)

    monkeypatch.setattr(QueueSubprocessReplayAdapter, "run", engine_run)
    assert main(command(tmp_path, "run-queue-family", family_id)) == 6
    output = capsys.readouterr()
    assert output.err == ""
    partial = json.loads(output.out)
    assert partial["status"] == "partial"
    assert [row["policy_id"] for row in partial["runs"]] == [POLICIES[0]]
    assert partial["failed_policy_ids"] == [POLICIES[1]]
    failure = partial["failures"][0]
    assert failure["code"] == "engine_unavailable" and failure["exit_code"] == 6
    assert failure["budget_consumed"] is True
    assert failure["attempt_id"] != partial["runs"][0]["attempt_id"]
    monkeypatch.setattr(QueueSubprocessReplayAdapter, "__init__", forbidden)
    assert main(command(tmp_path, "inspect-queue-run", partial["runs"][0]["run_id"])) == 0
    assert json.loads(capsys.readouterr().out)["evaluation"]["status"] == "verified"
    assert main(command(tmp_path, "inspect-queue-family", family_id)) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["budget"]["consumed_attempts"] == 2
    assert inspected["budget"]["remaining_attempts"] == 0
    finalized_failure = next(row for row in inspected["attempts"] if row["attempt_id"] == failure["attempt_id"])
    assert finalized_failure["state"] == "finalized"
    assert finalized_failure["outcome_kind"] == "queue_attempt_failure_v1"
    assert finalized_failure["error"]["code"] == "engine_unavailable"


@pytest.mark.parametrize("name", COMMANDS)
def test_confirmation_denial_precedes_request_reads_and_all_factories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, name,
) -> None:
    import tickwitness.cli_queue_execution as queue_cli

    monkeypatch.setattr(queue_cli, "read_regular_file", forbidden)
    for cls in (LocalDatasetStore, LocalExecutableProtocolRegistry, LocalQueueFamilyRegistry,
                LocalAttemptLedger, QueueSubprocessReplayAdapter):
        monkeypatch.setattr(cls, "__init__", forbidden)
    args = command(tmp_path, name, "../invalid", family_request="missing.json",
                   queue_request="absent.json", input_root=tmp_path / "missing")
    assert main([*args, "--split", "confirmation"]) == 5
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", COMMANDS)
@pytest.mark.parametrize("bad_id", ["../escape", "A" * 64, "0" * 63])
def test_bad_identity_precedes_repository_or_engine_initialization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    name, bad_id,
) -> None:
    (tmp_path / "family.json").write_text("{}", encoding="utf-8")
    (tmp_path / "queue.json").write_text("{}", encoding="utf-8")
    for cls in (LocalDatasetStore, LocalExecutableProtocolRegistry, LocalQueueFamilyRegistry,
                LocalAttemptLedger, QueueSubprocessReplayAdapter):
        monkeypatch.setattr(cls, "__init__", forbidden)
    before = snapshot(tmp_path)
    assert main(command(tmp_path, name, bad_id)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] in {
        "invalid_research_evidence", "invalid_protocol", "invalid_replay",
    }
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("request_field", ["family_request", "queue_request"])
@pytest.mark.parametrize("unsafe", ["traversal", "absolute", "leaf_symlink", "directory_symlink", "suffix"])
def test_freeze_request_paths_are_confined_before_repository_open(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    request_field, unsafe,
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    (input_root / "family.json").write_text("{}", encoding="utf-8")
    (input_root / "queue.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    if unsafe == "traversal":
        name = "../outside.json"
    elif unsafe == "absolute":
        name = str(target)
    elif unsafe == "leaf_symlink":
        (input_root / "linked.json").symlink_to(target)
        name = "linked.json"
    elif unsafe == "directory_symlink":
        (input_root / "linked").symlink_to(tmp_path, target_is_directory=True)
        name = "linked/outside.json"
    else:
        (input_root / "request.txt").write_text("{}", encoding="utf-8")
        name = "request.txt"
    for cls in (LocalDatasetStore, LocalExecutableProtocolRegistry, LocalQueueFamilyRegistry,
                LocalAttemptLedger, QueueSubprocessReplayAdapter):
        monkeypatch.setattr(cls, "__init__", forbidden)
    args = command(tmp_path, "freeze-queue-family", "a" * 64, input_root=input_root,
                   **{request_field: name})
    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "unsafe_input"
    for name in ("data", "registry", "families", "runs"):
        assert not (tmp_path / name).exists()
