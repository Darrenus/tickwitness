"""Saved native zero-shift evidence exercises durable scenario execution boundaries."""

import json

import pytest

from tickwitness.application.experiments import (
    ProtocolRunError,
    export_run,
    inspect_attempt,
    run_experiment,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.scenario_execution import inspect_scenario_run, run_scenario
from tickwitness.domain.assumptions import AssumptionValidationError
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.domain.evidence.scenario_records import (
    build_scenario_run_receipt,
    load_scenario_run_receipt,
)
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
)
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def requests(*, delay: int = 0) -> tuple[bytes, bytes]:
    return (
        json.dumps(
            {
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
        ).encode(),
        json.dumps(
            {
                "kind": "scenario_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "additional_delay": {"value": delay, "unit": "ns"},
            }
        ).encode(),
    )


def run(case, *, delay: int = 0, **changes):
    arguments = {
        "split": "development",
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
        "ledger_factory": case.ledger_factory,
        "engine_factory": case.engine_factory,
    }
    arguments.update(changes)
    return run_scenario(case.frozen.protocol_id, *requests(delay=delay), **arguments)


def first_reservation(case) -> AttemptReservation:
    raw = (case.root / "runs" / "slots" / case.frozen.protocol_id / "0001.json").read_bytes()
    return AttemptReservation(digest(raw), raw)


def test_zero_shift_saved_native_result_has_distinct_intent_and_no_baseline_claim(
    experiment_case,
) -> None:
    case = experiment_case
    source = case.data.read_normalized(case.development)
    catalog = tuple(record.dataset_id for record in case.data.list_datasets())
    submission = run(case)
    ledger = case.ledger_factory()
    intent_raw = ledger.get_intent(submission.attempt_id)
    assert intent_raw is not None
    intent = parse(intent_raw)
    receipt = load_scenario_run_receipt(ledger.read_artifact(submission.run_id))
    assert receipt.intent_id == submission.intent_id == digest(intent_raw)
    assert receipt.document["attempt"] == ledger.get_reservation(submission.attempt_id).document
    assert receipt.document["intent"] == intent
    assert intent["bindings"]["development_dataset_id"] == case.development
    assert intent["bindings"]["source_normalized_sha256"] == digest(source)
    assert intent["bindings"]["derived_normalized_sha256"] == digest(source)
    assert intent["bindings"]["derived_view_id"] == submission.derived_view_id
    assert submission.derived_view_id != case.development
    assert intent["scope"]["baseline_claim_evaluated"] is False
    assert intent["scope"]["search_performed"] is False
    assert submission.execution_status == "completed"
    assert submission.evaluation["metric_observation"] == {
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "eligible": True,
        "value": "-2",
    }
    assert "claim_observation" not in submission.evaluation
    assert "satisfied" not in submission.evaluation["metric_observation"]
    assert case.data.read_normalized(case.development) == source
    assert tuple(record.dataset_id for record in case.data.list_datasets()) == catalog
    assert {path.name for path in (case.root / "runs" / "slots").iterdir()} == {
        case.frozen.protocol_id
    }


def test_baseline_and_scenarios_share_the_original_protocol_budget(experiment_case) -> None:
    case = experiment_case
    baseline = run_experiment(
        case.frozen.protocol_id,
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )
    scenario = run(case)
    ledger = case.ledger_factory()
    assert ledger.get_reservation(baseline.attempt_id).attempt_index == 1
    assert ledger.get_reservation(scenario.attempt_id).attempt_index == 2
    assert ledger.get_intent(baseline.attempt_id) is None

    def forbidden(_timeout):
        raise AssertionError("Exhausted budget must not construct an engine")

    with pytest.raises(AttemptBudgetExceededError):
        run(case, engine_factory=forbidden)
    assert len(list((case.root / "runs" / "slots" / case.frozen.protocol_id).iterdir())) == 2


@pytest.mark.parametrize("split", ["confirmation", "invalid", "DEVELOPMENT"])
def test_confirmation_denial_precedes_requests_and_every_factory(split: str) -> None:
    def forbidden(*_args):
        raise AssertionError("Denied scenario access must not open any boundary")

    with pytest.raises(ConfirmationAccessDenied):
        run_scenario(
            "../invalid",
            b"not json",
            b"not json",
            split=split,
            registry_factory=forbidden,
            datasets_factory=forbidden,
            ledger_factory=forbidden,
            engine_factory=forbidden,
        )


@pytest.mark.parametrize("delay", [-1, 20_000_001, True])
def test_invalid_scenario_never_constructs_a_ledger_or_engine(experiment_case, delay) -> None:
    case = experiment_case

    def forbidden(*_args):
        raise AssertionError("Invalid scenario must fail before consuming a slot")

    with pytest.raises(AssumptionValidationError):
        run(case, delay=delay, ledger_factory=forbidden, engine_factory=forbidden)
    assert not (case.root / "runs").exists()


def test_intent_and_its_artifacts_are_persisted_before_engine_construction(experiment_case) -> None:
    case = experiment_case
    calls = []

    def observed_engine(timeout):
        ledger = case.ledger_factory()
        reservation = first_reservation(case)
        intent_raw = ledger.get_intent(reservation.attempt_id)
        assert intent_raw is not None
        intent = parse(intent_raw)
        bindings = intent["bindings"]
        for key in ("assumption_id", "scenario_id", "derived_view_id", "derived_normalized_sha256"):
            assert ledger.read_artifact(bindings[key])
        assert ledger.get_outcome(reservation.attempt_id) is None
        calls.append(reservation.attempt_id)
        saved_native = case.engine_factory(timeout)

        class SavedNativeResult:
            def run(self, replay_input):
                assert replay_input.dataset_id == bindings["derived_view_id"]
                assert (
                    digest(replay_input.normalized_bytes) == bindings["derived_normalized_sha256"]
                )
                return saved_native.run(replay_input)

        return SavedNativeResult()

    submission = run(case, engine_factory=observed_engine)
    assert calls == [submission.attempt_id]


@pytest.mark.parametrize("failure", [RuntimeError("engine failed"), ValueError()])
def test_engine_failure_keeps_intent_and_consumes_each_reserved_slot(
    experiment_case, failure: Exception
) -> None:
    case = experiment_case

    def fail(_timeout):
        raise failure

    attempts = []
    for _ in range(2):
        with pytest.raises(ProtocolRunError) as caught:
            run(case, engine_factory=fail)
        attempts.append(caught.value.attempt_id)
        ledger = case.ledger_factory()
        state = inspect_attempt(caught.value.attempt_id, ledger)
        assert state["budget_consumed"] is True
        assert state["state"] == "finalized"
        assert state["outcome"]["kind"] == "scenario_attempt_failure_v1"
        assert state["outcome"]["intent"] == parse(ledger.get_intent(caught.value.attempt_id))
        assert state["outcome"]["error"]["message"]
    assert len(set(attempts)) == 2
    with pytest.raises(AttemptBudgetExceededError):
        run(case)


def test_keyboard_interrupt_leaves_consumed_slot_with_durable_candidate_identity(
    experiment_case,
) -> None:
    case = experiment_case

    def interrupt(_timeout):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run(case, engine_factory=interrupt)
    reservation = first_reservation(case)
    ledger = case.ledger_factory()
    assert ledger.get_intent(reservation.attempt_id) is not None
    assert ledger.get_outcome(reservation.attempt_id) is None
    state = inspect_attempt(reservation.attempt_id, ledger)
    assert state["state"] == "reserved_unfinalized"
    assert state["budget_consumed"] is True
    second = run(case)
    assert ledger.get_reservation(second.attempt_id).attempt_index == 2
    with pytest.raises(AttemptBudgetExceededError):
        run(case)


def test_intent_publication_failure_forbids_engine_and_does_not_refund(experiment_case) -> None:
    case = experiment_case
    ledger = case.ledger_factory()

    class IntentWriteFailure:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def bind_intent(self, *_args, **_kwargs):
            raise AttemptLedgerError("injected intent disk failure")

    def forbidden(_timeout):
        raise AssertionError("Uncommitted intent must never reach native execution")

    with pytest.raises(ProtocolRunError) as caught:
        run(case, ledger_factory=IntentWriteFailure, engine_factory=forbidden)
    assert ledger.get_reservation(caught.value.attempt_id).attempt_index == 1
    assert ledger.get_intent(caught.value.attempt_id) is None
    assert inspect_attempt(caught.value.attempt_id, ledger)["budget_consumed"] is True


@pytest.mark.parametrize("change", [{"max_wall_seconds": 59}, {"attempt_index": 3}])
def test_conflicting_reservation_budget_is_rejected_before_intent_or_engine(
    experiment_case, change: dict
) -> None:
    case = experiment_case
    ledger = case.ledger_factory()
    boundary_calls = []

    class ConflictingReservation:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def reserve(self, protocol):
            document = ledger.reserve(protocol).document
            document.update(change)
            raw = canonical(document)
            return AttemptReservation(digest(raw), raw)

        def bind_intent(self, *_args, **_kwargs):
            boundary_calls.append("intent")
            raise AssertionError("Frozen-budget mismatch must precede intent publication")

    def forbidden(_timeout):
        boundary_calls.append("engine")
        raise AssertionError("Frozen-budget mismatch must precede native execution")

    with pytest.raises(ProtocolRunError):
        run(case, ledger_factory=ConflictingReservation, engine_factory=forbidden)
    assert boundary_calls == []
    reservation = first_reservation(case)
    assert ledger.get_intent(reservation.attempt_id) is None
    assert inspect_attempt(reservation.attempt_id, ledger)["budget_consumed"] is True


def test_outcome_publication_failure_retains_intent_and_unfinalized_reservation(
    experiment_case,
) -> None:
    case = experiment_case
    ledger = case.ledger_factory()

    class OutcomeWriteFailure:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def publish(self, *_args, **_kwargs):
            raise AttemptLedgerError("injected outcome disk failure")

    with pytest.raises(ProtocolRunError) as caught:
        run(case, ledger_factory=OutcomeWriteFailure)
    assert caught.value.code == "attempt_outcome_unconfirmed"
    assert ledger.get_intent(caught.value.attempt_id) is not None
    assert ledger.get_outcome(caught.value.attempt_id) is None
    assert inspect_attempt(caught.value.attempt_id, ledger)["budget_consumed"] is True


def test_committed_outcome_is_recoverable_if_the_returned_identity_conflicts(
    experiment_case,
) -> None:
    case = experiment_case
    ledger = case.ledger_factory()

    class ConflictingPublicationReply:
        def __getattr__(self, name):
            return getattr(ledger, name)

        def publish(self, *args, **kwargs):
            ledger.publish(*args, **kwargs)
            return "f" * 64

    with pytest.raises(ProtocolRunError) as caught:
        run(case, ledger_factory=ConflictingPublicationReply)
    assert caught.value.code == "attempt_outcome_unconfirmed"
    outcome = ledger.get_outcome(caught.value.attempt_id)
    assert outcome is not None
    receipt = load_scenario_run_receipt(outcome)
    recovered = inspect_scenario_run(
        receipt.run_id, ledger=ledger, registry=case.registry, datasets=case.data
    )
    assert recovered["run_id"] == receipt.run_id
    assert recovered["verification"]["native_replayed"] is False
    assert ledger.get_reservation(caught.value.attempt_id).attempt_index == 1


def test_inspection_recomputes_existing_evidence_without_constructing_an_engine(
    experiment_case, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    submission = run(case)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Inspection must recompute evidence without native replay")

    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    inspected = inspect_scenario_run(
        submission.run_id,
        ledger=case.ledger_factory(),
        registry=case.registry,
        datasets=case.data,
    )
    assert inspected["evaluation"] == submission.evaluation
    assert inspected["verification"]["derivation_recomputed"] is True
    assert inspected["verification"]["accounting_verified"] is True
    assert inspected["verification"]["native_replayed"] is False
    assert inspected["verification"]["confirmation_reference_checked"] is False
    assert inspected["verification"]["full_attempt_ledger_checked"] is False


@pytest.mark.parametrize("change", [{"max_wall_seconds": 59}, {"attempt_index": 3}])
def test_inspection_rejects_self_consistent_reservation_outside_frozen_budget(
    experiment_case, change: dict
) -> None:
    case = experiment_case
    submission = run(case)
    ledger = case.ledger_factory()
    document = load_scenario_run_receipt(ledger.read_artifact(submission.run_id)).document
    document["attempt"].update(change)
    forged = build_scenario_run_receipt(document)
    reservation_raw = canonical(document["attempt"])
    reservation = AttemptReservation(digest(reservation_raw), reservation_raw)
    original_intent = ledger.get_intent(submission.attempt_id)

    class SelfConsistentPort:
        def read_artifact(self, content_hash, **limits):
            if content_hash == forged.run_id:
                return forged.canonical_bytes
            return ledger.read_artifact(content_hash, **limits)

        def get_reservation(self, attempt_id):
            assert attempt_id == reservation.attempt_id
            return reservation

        def get_outcome(self, attempt_id):
            assert attempt_id == reservation.attempt_id
            return forged.canonical_bytes

        def get_intent(self, attempt_id):
            assert attempt_id == reservation.attempt_id
            return original_intent

    class NoDataRead:
        def get(self, _dataset_id):
            raise AssertionError("Budget mismatch must be rejected before dataset access")

        def read_normalized(self, _dataset_id, **_limits):
            raise AssertionError("Budget mismatch must be rejected before observation access")

    with pytest.raises(EvidenceValidationError, match="frozen budget"):
        inspect_scenario_run(
            forged.run_id,
            ledger=SelfConsistentPort(),
            registry=case.registry,
            datasets=NoDataRead(),
        )


@pytest.mark.parametrize("role", ["derivation", "derived_tape", "result", "evaluation", "intent"])
def test_inspection_rejects_real_cas_tampering(experiment_case, role: str) -> None:
    case = experiment_case
    submission = run(case)
    ledger = case.ledger_factory()
    receipt = load_scenario_run_receipt(ledger.read_artifact(submission.run_id)).document
    intent_bindings = receipt["intent"]["bindings"]
    content_hash = {
        "derivation": intent_bindings["derived_view_id"],
        "derived_tape": intent_bindings["derived_normalized_sha256"],
        "result": receipt["bindings"]["replay_result_sha256"],
        "evaluation": receipt["bindings"]["evaluation_sha256"],
        "intent": submission.intent_id,
    }[role]
    path = case.root / "runs" / "objects" / "sha256" / content_hash
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(AttemptLedgerError):
        inspect_scenario_run(
            submission.run_id, ledger=ledger, registry=case.registry, datasets=case.data
        )


def test_baseline_export_refuses_scenario_before_reading_data_or_creating_output(
    experiment_case,
) -> None:
    case = experiment_case
    submission = run(case)

    class NoDatasetRead:
        def read_artifacts(self, _identity):
            raise AssertionError("Baseline export must reject scenario scope before data access")

    def forbidden(_artifacts):
        raise AssertionError("A scenario cannot be emitted as a baseline bundle")

    with pytest.raises(EvidenceValidationError):
        export_run(
            submission.run_id,
            ledger=case.ledger_factory(),
            registry=case.registry,
            datasets=NoDatasetRead(),
            exporter=forbidden,
        )
