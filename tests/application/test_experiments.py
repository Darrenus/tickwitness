"""Real stores and append-only attempts support a portable, independently audited workflow."""

import json
import shutil

import pytest

from tickwitness.application.experiments import (
    ProtocolRunError,
    export_run,
    freeze_experiment,
    inspect_attempt,
    run_artifacts,
    run_experiment,
    verify_package,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    build_run_receipt,
    digest,
    load_run_receipt,
)
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.infrastructure.attempt_ledger import AttemptBudgetExceededError
from tickwitness.infrastructure.evidence_bundles import export_bundle, read_bundle


def run(case, **changes):
    arguments = dict(
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )
    arguments.update(changes)
    return run_experiment(case.frozen.protocol_id, **arguments)


def test_real_freeze_run_export_move_and_offline_verify(experiment_case) -> None:
    case = experiment_case
    submission = run(case)
    observation = submission.evaluation["claim_observation"]
    assert observation == {
        "eligible": True,
        "satisfied": True,
        "value": "-2",
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "comparator": "gt",
        "threshold": "-3",
    }
    ledger = case.ledger_factory()
    inspected = inspect_attempt(submission.attempt_id, ledger)
    assert inspected["budget_consumed"] is True
    assert inspected["state"] == "finalized"
    assert inspected["outcome"]["execution_status"] == "completed"
    destination = case.root / "bundle"
    receipt = export_run(
        submission.run_id,
        ledger=ledger,
        registry=case.registry,
        datasets=case.data,
        exporter=lambda artifacts: export_bundle(destination, artifacts),
    )
    moved = case.root / "moved"
    destination.rename(moved)
    for name in ("data", "registry", "runs"):
        shutil.rmtree(case.root / name)
    verified = verify_package(read_bundle(moved))
    assert verified == receipt
    assert verified["native_replayed"] is False
    assert verified["confirmation_reference_checked"] is False
    assert verified["full_attempt_ledger_checked"] is False
    assert verified["accounting_verified"] is True


@pytest.mark.parametrize("split", ["confirmation", "invalid"])
def test_confirmation_denial_precedes_all_factory_access(split: str) -> None:
    def forbidden(*args):
        raise AssertionError("No infrastructure may be opened")

    with pytest.raises(ConfirmationAccessDenied):
        run_experiment(
            "0" * 64,
            split=split,
            registry_factory=forbidden,
            datasets_factory=forbidden,
            ledger_factory=forbidden,
            engine_factory=forbidden,
        )


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("native failed"), ValueError(), ValueError("\ud800"), ValueError("📉" * 4096)],
)
def test_failed_attempt_is_recorded_and_never_refunded(experiment_case, failure: Exception) -> None:
    case = experiment_case

    def fail(_timeout):
        raise failure

    attempts = []
    for _ in range(2):
        with pytest.raises(ProtocolRunError) as caught:
            run(case, engine_factory=fail)
        attempts.append(caught.value.attempt_id)
        state = inspect_attempt(caught.value.attempt_id, case.ledger_factory())
        assert state["outcome"]["kind"] == "replay_attempt_failure_v1"
        assert state["outcome"]["error"]["message"]
    assert attempts[0] != attempts[1]
    with pytest.raises(AttemptBudgetExceededError):
        run(case)


def test_interruption_retains_unfinalized_consumed_reservation(experiment_case) -> None:
    case = experiment_case

    def interrupt(_timeout):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run(case, engine_factory=interrupt)
    slot = case.root / "runs" / "slots" / case.frozen.protocol_id / "0001.json"
    reservation = AttemptReservation(digest(slot.read_bytes()), slot.read_bytes())
    state = inspect_attempt(reservation.attempt_id, case.ledger_factory())
    assert state["state"] == "reserved_unfinalized"
    assert state["budget_consumed"] is True
    successful = run(case)
    assert (
        inspect_attempt(successful.attempt_id, case.ledger_factory())["reservation"][
            "attempt_index"
        ]
        == 2
    )
    with pytest.raises(AttemptBudgetExceededError):
        run(case)


def test_export_rejects_confirm_binding_before_reading_its_observations(experiment_case) -> None:
    case = experiment_case
    first = run(case)
    ledger = case.ledger_factory()
    original = load_run_receipt(ledger.read_artifact(first.run_id)).document
    protocol = load_executable_protocol(case.registry.get(case.frozen.protocol_id).canonical_bytes)
    reservation = ledger.reserve(protocol)
    original["attempt"] = reservation.document
    original["bindings"]["dataset_id"] = case.confirmation
    forged = build_run_receipt(original)
    ledger.publish(reservation, forged.canonical_bytes)

    class NoObservationRead:
        def read_artifacts(self, identity):
            raise AssertionError("Receipt binding must be checked before reading observations")

    with pytest.raises(EvidenceValidationError, match="development inputs"):
        run_artifacts(
            forged.run_id, ledger=ledger, registry=case.registry, datasets=NoObservationRead()
        )


def test_failed_preflight_creates_no_executable_registry(experiment_case) -> None:
    case = experiment_case
    invalid = dict(
        case.request, budget={"max_attempts": 1, "max_wall_seconds": 60, "max_events": 1}
    )

    def forbidden():
        raise AssertionError("Rejected event budget must not open a registry")

    with pytest.raises(ValueError, match="event budget"):
        freeze_experiment(
            json.dumps(invalid).encode(),
            development_dataset_id=case.development,
            confirmation_dataset_id=case.confirmation,
            datasets_factory=lambda: case.data,
            registry_factory=forbidden,
        )
