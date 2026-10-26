"""Committed pair semantics are inspected through source/CAS closure, without writes."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment
from tickwitness.application.queue_execution import freeze_queue_family, run_queue_model
from tickwitness.application.queue_semantics import inspect_queue_semantics
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.queue_family_registry import LocalQueueFamilyRegistry
from tickwitness.infrastructure.queue_replay import QueueSubprocessReplayAdapter

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
FRONT, BACK = "cancel_front_first_v1", "cancel_back_first_v1"


@pytest.fixture
def saved_pair(tmp_path, queue_result_factory):
    data = LocalDatasetStore(tmp_path / "data")
    development, confirmation = [
        import_events((EXAMPLES / name).read_bytes(), lambda: data).dataset_id
        for name in ("queue-observations.jsonl", "replay-confirmation.jsonl")
    ]
    registry = LocalExecutableProtocolRegistry(tmp_path / "registry")
    source = freeze_experiment(
        (EXAMPLES / "experiment-request.json").read_bytes(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
    )
    families = LocalQueueFamilyRegistry(tmp_path / "families")
    family_request = json.loads((EXAMPLES / "queue-family-request.json").read_bytes())
    family_request["budget"]["max_attempts"] = 4
    family = freeze_queue_family(
        source.protocol_id,
        canonical(family_request),
        (EXAMPLES / "queue-constraint-request.json").read_bytes(),
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        families_factory=lambda: families,
    ).family
    ledger = LocalAttemptLedger(tmp_path / "runs")

    class NativeFreeCallbacks:
        def run(self, replay_input):
            return queue_result_factory(replay_input)

    arguments = {
        "split": "development",
        "families_factory": lambda: families,
        "datasets_factory": lambda: data,
        "ledger_factory": lambda: ledger,
        "replay_factory": lambda timeout: NativeFreeCallbacks(),
    }
    front, back = [
        run_queue_model(family.family_id, policy, **arguments) for policy in (FRONT, BACK)
    ]
    return SimpleNamespace(
        root=tmp_path,
        data=data,
        registry=registry,
        families=families,
        family=family,
        ledger=ledger,
        front=front,
        back=back,
        run_arguments=arguments,
        source=source,
        family_request=family_request,
        result_factory=queue_result_factory,
    )


def inspect(case, left=None, right=None):
    return inspect_queue_semantics(
        left or case.front.run_id,
        right or case.back.run_id,
        split="development",
        families_factory=lambda: LocalQueueFamilyRegistry(case.root / "families", create=False),
        datasets_factory=lambda: LocalDatasetStore(case.root / "data", create=False),
        ledger_factory=lambda: LocalAttemptLedger(case.root / "runs", create=False),
    )


def snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def forbidden(*args, **kwargs):
    raise AssertionError("Semantic inspection cannot write, reserve or execute")


def test_readonly_pair_is_source_reaudited_and_binds_actual_committed_runs(saved_pair, monkeypatch):
    case = saved_pair
    before = snapshot(case.root)
    for method in ("reserve", "bind_intent", "publish"):
        monkeypatch.setattr(LocalAttemptLedger, method, forbidden)
    monkeypatch.setattr(LocalDatasetStore, "publish", forbidden)
    monkeypatch.setattr(LocalQueueFamilyRegistry, "seal", forbidden)
    monkeypatch.setattr(QueueSubprocessReplayAdapter, "__init__", forbidden)
    report = inspect(case)
    assert report == inspect(case, case.back.run_id, case.front.run_id)
    assert snapshot(case.root) == before
    assert report["qualification_id"] == digest(
        canonical(
            {
                key: value
                for key, value in report.items()
                if key not in ("qualification_id", "inspection_id", "runs", "verification")
            }
        )
    )
    assert report["inspection_id"] == digest(
        canonical({key: value for key, value in report.items() if key != "inspection_id"})
    )
    assert report["runs"] == [
        {
            "policy_id": FRONT,
            "run_id": case.front.run_id,
            "attempt_id": case.front.attempt_id,
            "attempt_index": 1,
        },
        {
            "policy_id": BACK,
            "run_id": case.back.run_id,
            "attempt_id": case.back.attempt_id,
            "attempt_index": 2,
        },
    ]
    assert report["bindings"]["family_id"] == case.family.family_id
    assert report["verification"]["native_replayed"] is False
    assert report["verification"]["budget_consumed"] is False
    assert report["verification"]["source_revalidated"] is True
    assert report["observation_compatibility"]["status"] == "not_established"
    assert report["predicate"]["satisfied"] == {FRONT: None, BACK: None}
    assert report["findings"] == []


def test_same_policy_repeated_in_another_real_attempt_is_not_two_interpretations(saved_pair):
    case = saved_pair
    another_front = run_queue_model(case.family.family_id, FRONT, **case.run_arguments)
    assert another_front.attempt_id != case.front.attempt_id
    with pytest.raises(EvidenceValidationError, match="exactly front and back"):
        inspect(case, case.front.run_id, another_front.run_id)


def test_distinct_run_ids_from_different_families_cannot_be_combined(saved_pair):
    case = saved_pair
    request = dict(case.family_request, budget={**case.family_request["budget"], "max_attempts": 3})
    family = freeze_queue_family(
        case.source.protocol_id,
        canonical(request),
        (EXAMPLES / "queue-constraint-request.json").read_bytes(),
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        families_factory=lambda: case.families,
    ).family
    another_back = run_queue_model(family.family_id, BACK, **case.run_arguments)
    with pytest.raises(EvidenceValidationError):
        inspect(case, case.front.run_id, another_back.run_id)


@pytest.mark.parametrize("split", ["confirmation", "invalid"])
def test_split_denial_precedes_bad_ids_and_every_factory(split):
    with pytest.raises(ConfirmationAccessDenied):
        inspect_queue_semantics(
            "bad-left",
            "bad-right",
            split=split,
            families_factory=forbidden,
            datasets_factory=forbidden,
            ledger_factory=forbidden,
        )


@pytest.mark.parametrize(
    "left,right", [("../bad", "0" * 64), ("0" * 64, "A" * 64), ("0" * 64, "0" * 64)]
)
def test_invalid_or_identical_ids_fail_before_factories(left, right):
    with pytest.raises(EvidenceValidationError):
        inspect_queue_semantics(
            left,
            right,
            split="development",
            families_factory=forbidden,
            datasets_factory=forbidden,
            ledger_factory=forbidden,
        )


@pytest.mark.parametrize("artifact", ["result", "intent", "evaluation", "source"])
def test_actual_artifact_corruption_cannot_become_an_insufficient_evidence_finding(
    saved_pair, artifact
):
    case = saved_pair
    original = case.ledger.read_artifact
    receipt = json.loads(original(case.front.run_id))
    selected = {
        "result": receipt["bindings"]["replay_result_sha256"],
        "intent": case.front.intent_id,
        "evaluation": receipt["bindings"]["evaluation_sha256"],
        "source": case.family.document["bindings"]["normalized_sha256"],
    }[artifact]

    class CorruptRead:
        def __getattr__(self, name):
            return getattr(case.ledger, name)

        def get_intent(self, attempt_id):
            raw = case.ledger.get_intent(attempt_id)
            return (
                raw + b" " if artifact == "intent" and attempt_id == case.front.attempt_id else raw
            )

        def read_artifact(self, content_hash, **kwargs):
            raw = original(content_hash, **kwargs)
            return raw + b" " if content_hash == selected else raw

    with pytest.raises(ValueError):
        inspect_queue_semantics(
            case.front.run_id,
            case.back.run_id,
            split="development",
            families_factory=lambda: case.families,
            datasets_factory=lambda: case.data,
            ledger_factory=lambda: CorruptRead(),
        )
