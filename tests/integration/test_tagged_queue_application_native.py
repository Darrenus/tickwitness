"""Actual native execution closes durable application success and failure evidence."""

from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import ProtocolRunError, freeze_experiment
from tickwitness.application.tagged_queue_execution import (
    freeze_tagged_queue,
    inspect_tagged_queue,
    inspect_tagged_queue_run,
    run_tagged_queue_model,
    run_tagged_queue_pair,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError, digest
from tickwitness.domain.evidence.tagged_queue_records import (
    load_tagged_queue_failure,
    load_tagged_queue_intent,
    load_tagged_queue_run_receipt,
)
from tickwitness.domain.replay.tagged_queue_contracts import build_tagged_queue_replay_result
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS
from tickwitness.infrastructure.attempt_ledger import AttemptBudgetExceededError, LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry
from tickwitness.infrastructure.tagged_queue_replay import NautilusTaggedQueueReplayAdapter

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _native_installed() -> bool:
    try:
        return metadata.version("nautilus_trader") == "1.231.0"
    except metadata.PackageNotFoundError:
        return False


pytestmark = pytest.mark.skipif(
    not _native_installed(), reason="optional pinned Nautilus extra absent"
)


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def tagged_native_app(tmp_path):
    data = LocalDatasetStore(tmp_path / "data")
    development, confirmation = (
        import_events((EXAMPLES / name).read_bytes(), lambda: data).dataset_id
        for name in ("queue-observations.jsonl", "replay-confirmation.jsonl")
    )
    sources = LocalExecutableProtocolRegistry(tmp_path / "registry")
    source = freeze_experiment(
        (EXAMPLES / "experiment-request.json").read_bytes(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        datasets_factory=lambda: data,
        registry_factory=lambda: sources,
    )
    protocols = LocalTaggedQueueRegistry(tmp_path / "registry", create=True)
    frozen = freeze_tagged_queue(
        source.protocol_id,
        (EXAMPLES / "tagged-queue-request.json").read_bytes(),
        (EXAMPLES / "queue-constraint-request.json").read_bytes(),
        split="development",
        registry_factory=lambda: sources,
        datasets_factory=lambda: data,
        protocols_factory=lambda: protocols,
    )
    ledger = LocalAttemptLedger(tmp_path / "ledger")
    return SimpleNamespace(
        root=tmp_path,
        protocol=frozen.protocol,
        ledger=ledger,
        factories={
            "protocols_factory": lambda: protocols,
            "datasets_factory": lambda: data,
            "ledger_factory": lambda: ledger,
        },
    )


def _reserved_intent(case, expected_count):
    reservations = case.ledger.list_reservations(case.protocol)
    assert len(reservations) == expected_count
    reservation = reservations[-1]
    intent = load_tagged_queue_intent(case.ledger.get_intent(reservation.attempt_id))
    assert intent.protocol == case.protocol
    for raw in (
        case.protocol.canonical_bytes,
        case.protocol.source_protocol.canonical_bytes,
        case.protocol.constraint.canonical_bytes,
    ):
        assert case.ledger.read_artifact(digest(raw)) == raw
    return reservation, intent


def test_actual_native_pair_commits_independently_reinspectable_success(tagged_native_app, monkeypatch):
    case = tagged_native_app
    calls = []

    def native(timeout):
        reservation, intent = _reserved_intent(case, len(calls) + 1)
        assert timeout == reservation.document["max_wall_seconds"] == 30
        calls.append(intent.policy_id)
        return NautilusTaggedQueueReplayAdapter()

    pair = run_tagged_queue_pair(
        case.protocol.protocol_id, split="development", replay_factory=native, **case.factories
    )
    assert calls == list(TAGGED_POLICY_IDS)
    assert pair["status"] == "completed" and pair["failures"] == []
    front, back = pair["runs"]
    assert front["attempt_id"] != back["attempt_id"]
    assert [item["evaluation"]["filled_quantity_lots"] for item in (front, back)] == [2, 0]
    assert [item["evaluation"]["actual_commission"] for item in (front, back)] == ["2", "0"]
    assert [item["evaluation"]["valuation"]["net_marked_pnl"] for item in (front, back)] == ["-2", "0"]
    for item in (front, back):
        outcome = case.ledger.get_outcome(item["attempt_id"])
        receipt = load_tagged_queue_run_receipt(outcome)
        assert receipt.run_id == item["run_id"]
        assert receipt.intent_id == item["intent_id"]
        assert receipt.document["claim_revision_id"] == case.protocol.claim_revision_id
        assert item["evaluation"]["claim_evaluation"]["truth"] is False
        assert item["evaluation"]["findings"] == []
        assert item["evaluation"]["scope"]["source_claim_evaluated"] is False
    before = _tree(case.root)

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only inspection cannot invoke the native runtime")

    monkeypatch.setattr(NautilusTaggedQueueReplayAdapter, "run", forbidden)
    for item in (front, back):
        inspected = inspect_tagged_queue_run(item["run_id"], **case.factories)
        assert inspected["evaluation"] == item["evaluation"]
        assert inspected["verification"]["native_replayed"] is False
        assert inspected["verification"]["queue_execution_audited"] is True
        assert inspected["result"]["execution_status"] == "completed"
    report = inspect_tagged_queue(case.protocol.protocol_id, **case.factories)
    assert report["budget"]["consumed_attempts"] == 2
    assert report["budget"]["remaining_attempts"] == 0
    with pytest.raises(AttemptBudgetExceededError):
        case.ledger.reserve(case.protocol)
    assert before == _tree(case.root)


def test_second_failure_retains_first_actual_native_receipt_and_stops(tagged_native_app, monkeypatch):
    case = tagged_native_app
    calls = []

    def native_then_failure(timeout):
        _, intent = _reserved_intent(case, len(calls) + 1)
        assert timeout == 30
        calls.append(intent.policy_id)
        if len(calls) == 2:
            raise ReplayProcessError("engine_timeout", "Injected second-policy worker timeout")
        return NautilusTaggedQueueReplayAdapter()

    pair = run_tagged_queue_pair(
        case.protocol.protocol_id,
        split="development",
        replay_factory=native_then_failure,
        **case.factories,
    )
    assert pair["status"] == "partial" and len(pair["runs"]) == len(pair["failures"]) == 1
    assert calls == list(TAGGED_POLICY_IDS)
    assert pair["pending_policy_ids"] == []
    first, failure = pair["runs"][0], pair["failures"][0]
    assert first["policy_id"] == TAGGED_POLICY_IDS[0]
    assert first["evaluation"]["filled_quantity_lots"] == 2
    assert first["evaluation"]["valuation"]["net_marked_pnl"] == "-2"
    assert failure["policy_id"] == TAGGED_POLICY_IDS[1]
    assert failure["code"] == "engine_timeout" and failure["budget_consumed"] is True
    receipt = load_tagged_queue_run_receipt(case.ledger.get_outcome(first["attempt_id"]))
    assert receipt.run_id == first["run_id"]
    failed = load_tagged_queue_failure(case.ledger.get_outcome(failure["attempt_id"]))
    assert failed["intent"]["policy_id"] == TAGGED_POLICY_IDS[1]
    report = inspect_tagged_queue(case.protocol.protocol_id, **case.factories)
    assert report["budget"]["consumed_attempts"] == 2
    assert report["budget"]["remaining_attempts"] == 0
    assert [row["outcome_kind"] for row in report["attempts"]] == [
        "tagged_queue_run_receipt_v1", "tagged_queue_attempt_failure_v1"
    ]
    before = _tree(case.root)
    monkeypatch.setattr(NautilusTaggedQueueReplayAdapter, "run",
                        lambda *args: pytest.fail("Inspection must not replay native"))
    inspected = inspect_tagged_queue_run(first["run_id"], **case.factories)
    assert inspected["evaluation"] == first["evaluation"]
    assert inspected["verification"]["native_replayed"] is False
    assert _tree(case.root) == before


@pytest.mark.parametrize("mutation", ["flow", "source_binding", "horizon_depth"])
def test_audit_rejection_preserves_raw_actual_native_diagnostic_without_success_receipt(
    tagged_native_app, mutation
):
    case = tagged_native_app
    raw_results = []

    class TamperedAdapter:
        def run(self, replay_input):
            actual = NautilusTaggedQueueReplayAdapter().run(replay_input)
            document = actual.document
            if mutation == "flow":
                trade = next(row for row in document["queue_trace"] if row["kind"] == "trade")
                trade["flow"]["own_trade_lots"] += 1
            elif mutation == "source_binding":
                document["bindings"]["data_sha256"] = "0" * 64
            else:
                document["horizon_snapshot"]["native_target_lots"] += 1
            # This is a bounded structurally valid DTO, rejected by the independent audit.
            result = build_tagged_queue_replay_result(document)
            raw_results.append(result.canonical_bytes)
            return result

    def tampered(timeout):
        _, intent = _reserved_intent(case, 1)
        assert timeout == 30 and intent.policy_id == TAGGED_POLICY_IDS[0]
        return TamperedAdapter()

    with pytest.raises(ProtocolRunError) as raised:
        run_tagged_queue_model(
            case.protocol.protocol_id,
            TAGGED_POLICY_IDS[0],
            split="development",
            replay_factory=tampered,
            **case.factories,
        )
    assert len(raw_results) == 1
    raw = raw_results[0]
    raw_sha = digest(raw)
    assert case.ledger.read_artifact(raw_sha) == raw
    reservation = case.ledger.list_reservations(case.protocol)[0]
    assert raised.value.attempt_id == reservation.attempt_id
    failed = load_tagged_queue_failure(case.ledger.get_outcome(reservation.attempt_id))
    assert failed["kind"] == "tagged_queue_attempt_failure_v1"
    assert failed["claim_revision_id"] == case.protocol.claim_revision_id
    assert failed["intent"]["policy_id"] == TAGGED_POLICY_IDS[0]
    assert "Diagnostic replay_result_sha256=" + raw_sha in failed["error"]["message"]
    assert "execution_status" not in failed
    report = inspect_tagged_queue(case.protocol.protocol_id, **case.factories)
    assert report["budget"]["consumed_attempts"] == 1
    assert report["budget"]["remaining_attempts"] == 1
    assert report["attempts"][0]["outcome_kind"] == "tagged_queue_attempt_failure_v1"
    assert report["attempts"][0]["budget_consumed"] is True
    before = _tree(case.root)
    with pytest.raises(EvidenceValidationError):
        inspect_tagged_queue_run(raw_sha, **case.factories)
    assert _tree(case.root) == before
