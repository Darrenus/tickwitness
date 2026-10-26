"""Durable queue-family boundaries use synthetic callbacks and the real pure audit.

Native execution is covered separately by the remote integration suite. There is
no selectable test engine in the product interfaces or command-line parser.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import ProtocolRunError, freeze_experiment
from tickwitness.application.queue_execution import (
    freeze_queue_family,
    inspect_queue_family,
    inspect_queue_run,
    run_queue_family,
    run_queue_model,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.queue_records import (
    QueueAttemptReservation,
    load_queue_intent,
    load_queue_run_receipt,
)
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.research_contracts.queue_family import QueueFamilyValidationError
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
    LocalAttemptLedger,
)
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.queue_family_registry import LocalQueueFamilyRegistry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
FRONT, BACK = "cancel_front_first_v1", "cancel_back_first_v1"


def family_request() -> bytes:
    return canonical(
        {
            "kind": "queue_family_request_v1",
            "schema_version": 1,
            "cancel_at_capture_seq": 6,
            "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 1000},
        }
    )


@pytest.fixture
def queue_case(tmp_path, queue_result_factory):
    datasets = LocalDatasetStore(tmp_path / "data")
    development = import_events(
        (EXAMPLES / "queue-observations.jsonl").read_bytes(), lambda: datasets
    ).dataset_id
    confirmation = import_events(
        (EXAMPLES / "replay-confirmation.jsonl").read_bytes(), lambda: datasets
    ).dataset_id
    registry = LocalExecutableProtocolRegistry(tmp_path / "registry")
    request = (EXAMPLES / "experiment-request.json").read_bytes()
    source = freeze_experiment(
        request,
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        datasets_factory=lambda: datasets,
        registry_factory=lambda: registry,
    )
    families = LocalQueueFamilyRegistry(tmp_path / "registry")
    queue_request = (EXAMPLES / "queue-constraint-request.json").read_bytes()
    frozen = freeze_queue_family(
        source.protocol_id,
        family_request(),
        queue_request,
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: datasets,
        families_factory=lambda: families,
    )
    calls = []

    def replay_factory(timeout):
        calls.append(timeout)

        class CallbackEvidence:
            def run(self, replay_input):
                return queue_result_factory(replay_input)

        return CallbackEvidence()

    return SimpleNamespace(
        root=tmp_path,
        datasets=datasets,
        registry=registry,
        families=families,
        source=source,
        family=frozen.family,
        development=development,
        confirmation=confirmation,
        queue_request=queue_request,
        ledger_factory=lambda: LocalAttemptLedger(tmp_path / "runs"),
        replay_factory=replay_factory,
        replay_calls=calls,
        result_factory=queue_result_factory,
    )


def arguments(case, **changes):
    values = {
        "split": "development",
        "families_factory": lambda: case.families,
        "datasets_factory": lambda: case.datasets,
        "ledger_factory": case.ledger_factory,
        "replay_factory": case.replay_factory,
    }
    values.update(changes)
    return values


def inspect_family(case):
    return inspect_queue_family(
        case.family.family_id,
        families_factory=lambda: case.families,
        datasets_factory=lambda: case.datasets,
        ledger_factory=case.ledger_factory,
    )


def inspect_run(case, run_id):
    return inspect_queue_run(
        run_id,
        families_factory=lambda: case.families,
        datasets_factory=lambda: case.datasets,
        ledger_factory=case.ledger_factory,
    )


def test_freeze_is_durable_idempotent_source_bound_and_consumes_no_attempt(queue_case) -> None:
    case = queue_case
    repeated = freeze_queue_family(
        case.source.protocol_id,
        family_request(),
        case.queue_request,
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.datasets,
        families_factory=lambda: case.families,
    )
    assert repeated.created is False
    assert repeated.family_id == repeated.protocol_id == case.family.family_id
    assert repeated.document["family"] == case.family.document
    assert case.registry.get(case.source.protocol_id).canonical_bytes == (
        case.family.source_protocol.canonical_bytes
    )
    assert not (case.root / "runs").exists()
    inspected = inspect_family(case)
    assert inspected["budget"]["consumed_attempts"] == 0
    assert inspected["budget"]["remaining_attempts"] == 2
    assert inspected["verification"]["native_replayed"] is False
    assert case.replay_calls == []


def test_intent_source_and_constraints_are_committed_before_worker_construction(queue_case) -> None:
    case = queue_case

    def observed(timeout):
        ledger = case.ledger_factory()
        reservations = ledger.list_reservations(case.family)
        assert len(reservations) == 1
        reservation = reservations[0]
        intent = load_queue_intent(ledger.get_intent(reservation.attempt_id))
        assert intent.policy_id == FRONT
        assert intent.family == case.family
        for raw in (
            case.family.canonical_bytes,
            case.family.source_protocol.canonical_bytes,
            case.family.constraint.canonical_bytes,
            case.datasets.read_normalized(case.development),
        ):
            assert ledger.read_artifact(digest(raw)) == raw
        assert ledger.get_outcome(reservation.attempt_id) is None
        return case.replay_factory(timeout)

    submission = run_queue_model(
        case.family.family_id, FRONT, **arguments(case, replay_factory=observed)
    )
    assert submission.execution_status == "completed"
    assert submission.evaluation["filled_quantity_lots"] == 1
    assert submission.evaluation["actual_commission"] == "1"
    assert submission.evaluation["scope"]["claim_verdict_issued"] is False
    inspected = inspect_run(case, submission.run_id)
    assert inspected["evaluation"] == submission.evaluation
    assert inspected["result"]["fill_trace"][0]["fields"]["quantity_lots"] == 1
    assert inspected["family"] == case.family.document
    assert inspected["verification"]["native_replayed"] is False


def test_both_policies_consume_one_family_budget_and_the_source_owns_no_queue_slot(
    queue_case,
) -> None:
    case = queue_case
    front = run_queue_model(case.family.family_id, FRONT, **arguments(case))
    back = run_queue_model(case.family.family_id, BACK, **arguments(case))
    ledger = case.ledger_factory()
    assert ledger.get_reservation(front.attempt_id).attempt_index == 1
    assert ledger.get_reservation(back.attempt_id).attempt_index == 2
    assert front.evaluation["filled_quantity_lots"] == 1
    assert back.evaluation["filled_quantity_lots"] == 0
    assert front.evaluation["final_order_status"] == "CANCELED"
    assert back.evaluation["final_order_status"] == "CANCELED"
    assert {path.name for path in (case.root / "runs" / "slots").iterdir()} == {
        case.family.family_id
    }
    with pytest.raises(AttemptBudgetExceededError):
        run_queue_model(case.family.family_id, FRONT, **arguments(case))
    assert case.replay_calls == [30, 30]
    inspected = inspect_family(case)
    assert inspected["budget"]["consumed_attempts"] == 2
    assert inspected["budget"]["remaining_attempts"] == 0
    assert [row["policy_id"] for row in inspected["attempts"]] == [FRONT, BACK]
    assert all(row["state"] == "finalized" for row in inspected["attempts"])


def test_batch_reports_completed_pair_then_exhaustion_without_another_worker(queue_case) -> None:
    case = queue_case
    result = run_queue_family(case.family.family_id, **arguments(case))
    assert result["status"] == "completed"
    assert [row["policy_id"] for row in result["runs"]] == [FRONT, BACK]
    assert result["failures"] == result["pending_policy_ids"] == []
    exhausted = run_queue_family(case.family.family_id, **arguments(case))
    assert exhausted["status"] == "failed"
    assert exhausted["failures"][0]["code"] == "attempt_budget_exhausted"
    assert exhausted["failures"][0]["exit_code"] == 8
    assert exhausted["failures"][0]["budget_consumed"] is False
    assert exhausted["pending_policy_ids"] == [FRONT, BACK]
    assert case.replay_calls == [30, 30]


@pytest.mark.parametrize("fail_at", [1, 2])
def test_batch_stops_on_failure_and_preserves_explicit_partial_evidence(
    queue_case, fail_at
) -> None:
    case = queue_case
    count = 0

    def sometimes(timeout):
        nonlocal count
        count += 1
        if count == fail_at:
            raise RuntimeError("injected queue worker failure")
        return case.replay_factory(timeout)

    result = run_queue_family(case.family.family_id, **arguments(case, replay_factory=sometimes))
    assert result["status"] == ("failed" if fail_at == 1 else "partial")
    assert len(result["runs"]) == fail_at - 1
    assert result["failures"][0]["budget_consumed"] is True
    assert result["failures"][0]["exit_code"] == 7
    assert result["pending_policy_ids"] == ([BACK] if fail_at == 1 else [])
    assert len(case.ledger_factory().list_reservations(case.family)) == fail_at


@pytest.mark.parametrize("split", ["confirmation", "invalid", "DEVELOPMENT"])
def test_confirmation_guard_precedes_every_factory_and_input_parse(split) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Denied access must not open a boundary")

    with pytest.raises(ConfirmationAccessDenied):
        freeze_queue_family(
            "../bad",
            b"not json",
            b"not json",
            split=split,
            registry_factory=forbidden,
            datasets_factory=forbidden,
            families_factory=forbidden,
        )
    common = {
        "split": split,
        "families_factory": forbidden,
        "datasets_factory": forbidden,
        "ledger_factory": forbidden,
    }
    with pytest.raises(ConfirmationAccessDenied):
        run_queue_model("../bad", "bad", replay_factory=forbidden, **common)
    with pytest.raises(ConfirmationAccessDenied):
        run_queue_family("../bad", replay_factory=forbidden, **common)
    with pytest.raises(ConfirmationAccessDenied):
        inspect_queue_family("../bad", **common)
    with pytest.raises(ConfirmationAccessDenied):
        inspect_queue_run("../bad", **common)


def test_invalid_policy_never_reads_dataset_or_reserves_slot(queue_case) -> None:
    case = queue_case

    def forbidden():
        raise AssertionError("Invalid policy must precede input and ledger access")

    with pytest.raises(ValueError):
        run_queue_model(
            case.family.family_id,
            "best_fit_from_future",
            **arguments(case, datasets_factory=forbidden, ledger_factory=forbidden),
        )
    assert not (case.root / "runs").exists()


def test_invalid_family_request_never_opens_the_publication_registry(queue_case) -> None:
    case = queue_case

    def forbidden():
        raise AssertionError("Invalid family must never be published")

    with pytest.raises(QueueFamilyValidationError):
        freeze_queue_family(
            case.source.protocol_id,
            b"{}",
            case.queue_request,
            split="development",
            registry_factory=lambda: case.registry,
            datasets_factory=lambda: case.datasets,
            families_factory=forbidden,
        )


def test_worker_failure_is_durable_and_does_not_refund_the_shared_attempt(queue_case) -> None:
    case = queue_case

    def fail(_timeout):
        raise RuntimeError("queue worker failed")

    with pytest.raises(ProtocolRunError) as caught:
        run_queue_model(case.family.family_id, FRONT, **arguments(case, replay_factory=fail))
    ledger = case.ledger_factory()
    outcome = json.loads(ledger.get_outcome(caught.value.attempt_id))
    assert outcome["kind"] == "queue_attempt_failure_v1"
    assert outcome["intent"]["policy_id"] == FRONT
    assert load_queue_intent(ledger.get_intent(caught.value.attempt_id)).family == case.family
    inspected = inspect_family(case)
    assert inspected["budget"]["consumed_attempts"] == 1
    assert inspected["attempts"][0]["error"]["message"] == "queue worker failed"


def test_interrupt_leaves_durable_intent_and_visible_consumed_unfinalized_attempt(
    queue_case,
) -> None:
    case = queue_case

    def interrupt(_timeout):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_queue_model(case.family.family_id, FRONT, **arguments(case, replay_factory=interrupt))
    inspected = inspect_family(case)
    assert inspected["budget"]["consumed_attempts"] == 1
    assert inspected["attempts"][0]["state"] == "reserved_unfinalized"
    assert inspected["attempts"][0]["policy_id"] == FRONT
    assert inspected["attempts"][0]["outcome_id"] is None


def test_failed_audit_preserves_raw_result_for_review_without_issuing_receipt(queue_case) -> None:
    case = queue_case
    results = []

    def invalid_callbacks(_timeout):
        class Callbacks:
            def run(self, replay_input):
                result = case.result_factory(replay_input, commission_override="99")
                results.append(result)
                return result

        return Callbacks()

    with pytest.raises(ProtocolRunError) as caught:
        run_queue_model(
            case.family.family_id, FRONT, **arguments(case, replay_factory=invalid_callbacks)
        )
    ledger = case.ledger_factory()
    artifact_id = digest(results[0].canonical_bytes)
    assert ledger.read_artifact(artifact_id) == results[0].canonical_bytes
    outcome = json.loads(ledger.get_outcome(caught.value.attempt_id))
    assert outcome["kind"] == "queue_attempt_failure_v1"
    assert artifact_id in outcome["error"]["message"]


def test_outcome_disk_failure_preserves_raw_result_and_unfinalized_consumed_attempt(
    queue_case,
) -> None:
    case = queue_case
    ledger = case.ledger_factory()
    results = []

    class OutcomeWriteFailure:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def publish(self, *_args, **_kwargs):
            raise AttemptLedgerError("injected outcome write failure")

    def callbacks(_timeout):
        class Callbacks:
            def run(self, replay_input):
                result = case.result_factory(replay_input)
                results.append(result)
                return result

        return Callbacks()

    with pytest.raises(ProtocolRunError) as caught:
        run_queue_model(
            case.family.family_id,
            FRONT,
            **arguments(case, ledger_factory=OutcomeWriteFailure, replay_factory=callbacks),
        )
    assert caught.value.code == "attempt_outcome_unconfirmed"
    assert ledger.get_outcome(caught.value.attempt_id) is None
    assert ledger.read_artifact(digest(results[0].canonical_bytes)) == results[0].canonical_bytes
    assert inspect_family(case)["budget"]["remaining_attempts"] == 1


def test_conflicting_reservation_budget_never_binds_intent_or_constructs_worker(queue_case) -> None:
    case = queue_case
    ledger = case.ledger_factory()
    boundary_calls = []

    class ConflictingReservation:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def reserve(self, family):
            document = ledger.reserve(family).document
            document["max_wall_seconds"] = 59
            raw = canonical(document)
            return QueueAttemptReservation(digest(raw), raw)

        def bind_intent(self, *_args, **_kwargs):
            boundary_calls.append("intent")
            raise AssertionError("Frozen-budget mismatch must precede intent")

    def forbidden(_timeout):
        boundary_calls.append("worker")
        raise AssertionError("Frozen-budget mismatch must precede native execution")

    with pytest.raises(ProtocolRunError):
        run_queue_model(
            case.family.family_id,
            FRONT,
            **arguments(case, ledger_factory=ConflictingReservation, replay_factory=forbidden),
        )
    assert boundary_calls == []
    assert len(ledger.list_reservations(case.family)) == 1


@pytest.mark.parametrize("role", ["result", "evaluation", "intent", "source", "tape"])
def test_inspection_detects_cas_tampering_without_replaying(queue_case, role) -> None:
    case = queue_case
    submission = run_queue_model(case.family.family_id, FRONT, **arguments(case))
    receipt = load_queue_run_receipt(case.ledger_factory().read_artifact(submission.run_id))
    content_hash = {
        "result": receipt.document["bindings"]["replay_result_sha256"],
        "evaluation": receipt.document["bindings"]["evaluation_sha256"],
        "intent": submission.intent_id,
        "source": case.source.protocol_id,
        "tape": digest(case.datasets.read_normalized(case.development)),
    }[role]
    path = case.root / "runs" / "objects" / "sha256" / content_hash
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AttemptLedgerError):
        inspect_run(case, submission.run_id)
    assert case.replay_calls == [30]
