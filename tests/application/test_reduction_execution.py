"""Real persisted source records bind prefix runs to the original shared budget.

The positive port returns a genuine saved native golden with only its input
context identity rebound. New native timing qualification runs separately in CI.
"""

import json
import socket
import subprocess
from types import SimpleNamespace

import pytest
from test_reductions import Unreadable, package, request
from test_search_evidence_verification import proof
from test_search_findings import execute, prepare, tree

from tickwitness.application.experiments import ProtocolRunError, run_experiment
from tickwitness.application.reduction_execution import inspect_reduction_run, run_reduction_input
from tickwitness.application.reductions import prepare_reduction_input
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.reduction_records import load_reduction_failure
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest, parse
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    LocalAttemptLedger,
)
from tickwitness.infrastructure.search_evidence_bundles import export_search_evidence_bundle


def forbidden(*_args, **_kwargs):
    raise AssertionError("This path must not execute, mutate or construct a native engine")


class Proxy:
    def __init__(self, wrapped, **overrides):
        self.wrapped = wrapped
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(self.wrapped, name)


@pytest.fixture
def reduction_case(experiment_case):
    case = experiment_case
    # Freeze the original owner with spare slots before any baseline/search run.
    # The committed exhausted alpha source is never rewritten to add a budget.
    case.request["budget"]["max_attempts"] = 5
    plan_id, authority_id = prepare(case, threshold="0", values=[0])
    run_experiment(
        case.frozen.protocol_id,
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )
    execute(case, plan_id, evaluations=1)
    artifacts, _ = proof(case, plan_id, authority_id)
    source = export_search_evidence_bundle(case.root / "portable-source", artifacts)
    prepared = prepare_reduction_input(
        source,
        request(focus=4, through=7, delay=0, ordinal=1),
        expected_bundle_id=source.bundle_id,
        expected_report_id=digest(source.artifacts["finding_report"]),
    )
    return SimpleNamespace(
        case=case,
        source=source,
        prepared=prepared,
        preparation=package(prepared.artifacts),
        ledger=LocalAttemptLedger(case.root / "runs", create=False),
    )


def run(value, **overrides):
    options = {
        "expected_preparation_id": value.prepared.preparation_id,
        "split": "development",
        "ledger_factory": lambda: value.ledger,
        "engine_factory": value.case.engine_factory,
    }
    options.update(overrides)
    return run_reduction_input(value.preparation, value.source, **options)


def inspect(value, run_id, **overrides):
    options = {"source": value.source, "split": "development", "ledger_factory": lambda: value.ledger}
    options.update(overrides)
    return inspect_reduction_run(run_id, **options)


def test_original_owner_intent_and_four_artifacts_are_committed_before_engine(reduction_case):
    value = reduction_case
    calls = []
    source_before = tree(value.case.root / "portable-source")

    def engine(timeout):
        calls.append(timeout)
        owner = value.prepared.materialization.source.validation.protocol
        reservation = value.ledger.list_reservations(owner)[-1]
        assert reservation.attempt_index == 3
        assert reservation.protocol_id == value.case.frozen.protocol_id
        intent = parse(value.ledger.get_intent(reservation.attempt_id))
        assert intent["kind"] == "reduction_execution_intent_v1"
        assert intent["flags"]["from_origin_prefix_replayed"] is False
        assert value.ledger.get_outcome(reservation.attempt_id) is None
        for raw in (value.preparation.manifest_bytes, *value.prepared.artifacts.values()):
            assert value.ledger.read_artifact(digest(raw)) == raw
        return value.case.engine_factory(timeout)

    submitted = run(value, engine_factory=engine)
    assert calls == [60]
    assert submitted.execution_status == "completed"
    assert submitted.state_audit["coverage"] == {
        "source_event_count": 7, "retained_event_count": 7, "processed_records": 7,
        "warmup_event_count": 3,
        **{key: value.prepared.materialization.document["retained"][key]
           for key in ("origin_ref", "focus_ref", "through_ref")},
    }
    assert submitted.state_audit["flags"]["state_projection_audited"] is True
    for key in ("focus_state_captured", "pre_engine_end_state_captured", "checkpoint_used",
                "witness_preservation_verified", "reduced_predicate_evaluated"):
        assert submitted.state_audit["flags"][key] is False
    stored = parse(value.ledger.get_outcome(submitted.attempt_id))
    assert stored["kind"] == "reduction_run_receipt_v1"
    assert stored["protocol_id"] == value.case.frozen.protocol_id
    assert stored["bindings"]["state_audit_sha256"] == digest(canonical(submitted.state_audit))
    assert tree(value.case.root / "portable-source") == source_before


def test_inspector_reaudits_persisted_bytes_readonly_with_later_live_suffix(reduction_case, monkeypatch):
    value = reduction_case
    first, second = run(value), run(value)
    before = tree(value.case.root)
    for name in ("reserve", "bind_intent", "publish"):
        monkeypatch.setattr(value.ledger, name, forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    report = inspect(value, first.run_id)
    assert report["run_id"] == first.run_id and report["run_id"] != second.run_id
    assert report["attempt_id"] == first.attempt_id
    assert report["budget"]["attempt_index"] == 3
    assert report["budget"]["max_attempts"] == 5
    assert report["state_audit"] == first.state_audit
    assert report["preparation"]["preparation_id"] == value.prepared.preparation_id
    assert report["verification"]["observed_source_prefix_matched"] is True
    assert report["verification"]["state_audit_recomputed"] is True
    for flag in ("native_replayed", "attempt_reserved", "full_attempt_history_verified",
                 "global_ledger_authenticity_verified", "source_claim_authority_extended"):
        assert report["verification"][flag] is False
    assert tree(value.case.root) == before


def test_original_budget_exhaustion_precedes_engine_construction(reduction_case):
    value = reduction_case
    for _ in range(3):
        run(value)
    with pytest.raises(AttemptBudgetExceededError):
        run(value, engine_factory=forbidden)
    owner = value.prepared.materialization.source.validation.protocol
    assert len(value.ledger.list_reservations(owner)) == 5


def test_empty_existing_ledger_cannot_restore_portable_reservations(reduction_case):
    value = reduction_case
    empty = LocalAttemptLedger(value.case.root / "empty")
    before = tree(value.case.root / "empty")
    with pytest.raises(EvidenceValidationError, match="shorter"):
        run(value, ledger_factory=lambda: Proxy(empty, reserve=forbidden), engine_factory=forbidden)
    assert tree(value.case.root / "empty") == before


@pytest.mark.parametrize("attack", ["short_prefix", "replacement", "intent", "outcome", "cas"])
def test_all_observed_source_records_must_match_before_reserving(reduction_case, attack):
    value = reduction_case
    owner = value.prepared.materialization.source.validation.protocol
    prefix = value.ledger.list_reservations(owner)
    changes = {"reserve": forbidden}
    if attack == "short_prefix":
        changes["list_reservations"] = lambda _owner: prefix[:1]
    elif attack == "replacement":
        # Slot one matters even though only slot two is a selected search witness.
        changes["list_reservations"] = lambda _owner: (prefix[1],)
    elif attack in ("intent", "outcome"):
        changes["get_" + attack] = lambda _attempt: b"wrong live bytes"
    else:
        changes["read_artifact"] = lambda _sha, **_kwargs: b"wrong live CAS"
    before = tree(value.case.root / "runs")
    with pytest.raises(EvidenceValidationError):
        run(value, ledger_factory=lambda: Proxy(value.ledger, **changes), engine_factory=forbidden)
    assert tree(value.case.root / "runs") == before


def test_preparation_rehash_cannot_authorize_a_changed_prefix(reduction_case):
    value = reduction_case
    artifacts = value.prepared.artifacts
    lines = artifacts["normalized"].splitlines(keepends=True)
    artifacts["normalized"] = b"".join(lines[1:])
    changed = package(artifacts)
    with pytest.raises(EvidenceValidationError):
        run_reduction_input(
            changed, value.source, expected_preparation_id=changed.preparation_id,
            split="development", ledger_factory=forbidden, engine_factory=forbidden,
        )


@pytest.mark.parametrize("attack", ["warmup", "input_binding", "cash", "pending", "failed", "early"])
def test_invalid_native_projection_consumes_failure_without_success_audit(reduction_case, attack):
    value = reduction_case

    class InvalidEngine:
        def run(self, replay_input):
            result = value.case.engine_factory(60).run(replay_input).document
            if attack == "warmup":
                result["input_trace"].pop(0)
            elif attack == "input_binding":
                result["data_sha256"] = "0" * 64
            elif attack == "cash":
                result["account_trace"][-1]["fields"]["cash_total"] = "10000"
            elif attack == "pending":
                result["completeness"]["pending_commands"] = [{"invented": True}]
            elif attack == "failed":
                result["execution_status"] = "failed"
            else:
                result["completeness"]["processed_records"] -= 1
            return build_replay_result(result)

    with pytest.raises(ProtocolRunError) as caught:
        run(value, engine_factory=lambda _timeout: InvalidEngine())
    assert caught.value.code == "reduction_run_failed"
    failure = load_reduction_failure(value.ledger.get_outcome(caught.value.attempt_id))
    assert failure["attempt"]["attempt_index"] == 3
    assert failure["protocol_id"] == value.case.frozen.protocol_id
    assert "state_audit_sha256" not in failure
    assert len(value.ledger.list_reservations(value.prepared.materialization.source.validation.protocol)) == 3


@pytest.mark.parametrize("mode", ["raise_before", "raise_after", "wrong_id"])
def test_intent_binding_failure_never_constructs_engine_or_refunds(reduction_case, mode):
    value = reduction_case

    def bind(reservation, raw, **kwargs):
        if mode == "raise_before":
            raise OSError("Intent not published")
        committed = value.ledger.bind_intent(reservation, raw, **kwargs)
        if mode == "raise_after":
            raise OSError("Intent publication acknowledgement uncertain")
        assert committed == digest(raw)
        return "0" * 64

    with pytest.raises(ProtocolRunError) as caught:
        run(value, ledger_factory=lambda: Proxy(value.ledger, bind_intent=bind), engine_factory=forbidden)
    owner = value.prepared.materialization.source.validation.protocol
    assert len(value.ledger.list_reservations(owner)) == 3
    if mode == "raise_before":
        assert caught.value.code == "attempt_outcome_unconfirmed"
        assert value.ledger.get_outcome(caught.value.attempt_id) is None
    else:
        assert load_reduction_failure(value.ledger.get_outcome(caught.value.attempt_id))


@pytest.mark.parametrize("mode", ["raise_after", "wrong_id", "readback_failure"])
def test_late_success_publication_failure_preserves_receipt_without_second_publish(reduction_case, mode):
    value = reduction_case
    calls = []
    published = [False]

    def publish(reservation, raw, **kwargs):
        calls.append(raw)
        committed = value.ledger.publish(reservation, raw, **kwargs)
        published[0] = True
        if mode == "raise_after":
            raise OSError("Parent sync acknowledgement uncertain")
        return "0" * 64 if mode == "wrong_id" else committed

    def outcome(attempt):
        if mode == "readback_failure" and published[0]:
            raise OSError("Readback unavailable after publication")
        return value.ledger.get_outcome(attempt)

    with pytest.raises(ProtocolRunError, match="remains consumed") as caught:
        run(value, ledger_factory=lambda: Proxy(value.ledger, publish=publish, get_outcome=outcome))
    assert caught.value.code == "attempt_outcome_unconfirmed"
    assert len(calls) == 1
    assert parse(calls[0])["kind"] == "reduction_run_receipt_v1"
    assert value.ledger.get_outcome(caught.value.attempt_id) == calls[0]
    assert inspect(value, digest(calls[0]))["receipt"] == parse(calls[0])


def test_keyboard_interrupt_leaves_consumed_intent_with_no_outcome(reduction_case):
    value = reduction_case

    class Interrupted:
        def run(self, _input):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(value, engine_factory=lambda _timeout: Interrupted())
    last = value.ledger.list_reservations(value.prepared.materialization.source.validation.protocol)[-1]
    assert last.attempt_index == 3
    assert value.ledger.get_intent(last.attempt_id) is not None
    assert value.ledger.get_outcome(last.attempt_id) is None


def test_timeout_diagnostic_is_bounded_after_json_escaping_and_keeps_attempt_id(reduction_case):
    value = reduction_case

    class TimedOut(TimeoutError):
        code = "native_timeout"
        exit_code = 6

    def timed_out(_timeout):
        raise TimedOut("\x00" * 4096)

    with pytest.raises(ProtocolRunError) as caught:
        run(value, engine_factory=timed_out)
    assert caught.value.code == "native_timeout"
    assert caught.value.exit_code == 6
    raw = value.ledger.get_outcome(caught.value.attempt_id)
    assert 0 < len(raw) <= 16 * 1024
    failure = load_reduction_failure(raw)
    assert failure["attempt"]["attempt_index"] == 3
    assert 0 < len(failure["error"]["message"]) < 4096


def test_failure_outcome_publication_error_does_not_refund_or_return_success(reduction_case):
    value = reduction_case

    def failed_engine(_timeout):
        raise RuntimeError("Actual worker construction failed")

    def failed_publication(*_args, **_kwargs):
        raise OSError("No outcome acknowledgement")

    with pytest.raises(ProtocolRunError) as caught:
        run(value, engine_factory=failed_engine,
            ledger_factory=lambda: Proxy(value.ledger, publish=failed_publication))
    assert caught.value.code == "attempt_outcome_unconfirmed"
    assert value.ledger.get_intent(caught.value.attempt_id) is not None
    assert value.ledger.get_outcome(caught.value.attempt_id) is None
    assert value.ledger.get_reservation(caught.value.attempt_id).attempt_index == 3


def test_invalid_pin_precedes_any_package_property_or_factory():
    with pytest.raises(EvidenceValidationError):
        run_reduction_input(
            Unreadable(), Unreadable(), expected_preparation_id="invalid", split="development",
            ledger_factory=forbidden, engine_factory=forbidden,
        )


@pytest.mark.parametrize("operation", ["run", "inspect"])
def test_confirmation_denial_precedes_all_packages_factories_and_identifiers(operation):
    with pytest.raises(ConfirmationAccessDenied):
        if operation == "run":
            run_reduction_input(
                Unreadable(), Unreadable(), expected_preparation_id="invalid", split="confirmation",
                ledger_factory=forbidden, engine_factory=forbidden,
            )
        else:
            inspect_reduction_run("invalid", source=Unreadable(), split="confirmation", ledger_factory=forbidden)


def test_inspection_rejects_rehashed_audit_instead_of_trusting_saved_flags(reduction_case):
    value = reduction_case
    submitted = run(value)
    receipt = parse(value.ledger.get_outcome(submitted.attempt_id))
    forged = json.loads(canonical(submitted.state_audit))
    forged["flags"]["checkpoint_resume_verified"] = True
    forged_raw = canonical(forged)
    receipt["bindings"]["state_audit_sha256"] = digest(forged_raw)
    forged_receipt = canonical(receipt)
    real_read = value.ledger.read_artifact

    def read(sha, **kwargs):
        if sha == digest(forged_receipt):
            return forged_receipt
        if sha == digest(forged_raw):
            return forged_raw
        return real_read(sha, **kwargs)

    proxy = Proxy(value.ledger, read_artifact=read, get_outcome=lambda _attempt: forged_receipt)
    # Source observed outcomes must still be exact; only override the new slot.
    proxy.get_outcome = lambda attempt: forged_receipt if attempt == submitted.attempt_id else value.ledger.get_outcome(attempt)
    with pytest.raises(EvidenceValidationError, match="audit differs"):
        inspect(value, digest(forged_receipt), ledger_factory=lambda: proxy)
