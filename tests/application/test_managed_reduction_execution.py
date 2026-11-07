"""Coordinator phases reuse saved native facts without a selectable fake engine.

Real managed native execution and process failure qualification run separately
in installed remote profiles. These tests exercise original-ledger boundaries.
"""

import socket
import sqlite3
import subprocess
from dataclasses import FrozenInstanceError, replace

import pytest
from test_reduction_execution import Proxy, forbidden
from test_reduction_execution import reduction_case as reduction_case
from test_reductions import Unreadable, package
from test_search_findings import tree

from tickwitness.application.experiments import ProtocolRunError
from tickwitness.application.reduction_execution import (
    audit_reduction_execution,
    authorize_reduction_execution,
    find_reduction_execution_reservation,
    inspect_reduction_run,
    prepare_reduction_execution,
    publish_reduction_execution,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.reduction_records import (
    build_reduction_failure,
    build_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    LocalAttemptLedger,
)
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

NONCE = "a" * 32


def prepare(value, **changes):
    options = {
        "expected_preparation_id": value.prepared.preparation_id,
        "expected_bundle_id": value.source.bundle_id,
        "expected_report_id": digest(value.source.artifacts["finding_report"]),
        "split": "development",
    }
    options.update(changes)
    return prepare_reduction_execution(value.preparation, value.source, **options)


def authorize(value, execution, **changes):
    options = {"ledger": value.ledger, "reservation_nonce": NONCE, "fence": lambda: None}
    options.update(changes)
    return authorize_reduction_execution(execution, **options)


def audited_case(value):
    execution = prepare(value)
    reservation = authorize(value, execution)
    raw = value.case.engine_factory(60).run(execution.replay_input).canonical_bytes
    return execution, reservation, audit_reduction_execution(execution, reservation, raw)


def no_runtime(monkeypatch):
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)


def test_preparation_is_a_frozen_copy_without_ledger_or_native_io(reduction_case, monkeypatch):
    value = reduction_case
    before = tree(value.case.root)
    no_runtime(monkeypatch)
    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    execution = prepare(value)
    assert execution.preparation_id == value.prepared.preparation_id
    assert execution.protocol.protocol_id == value.case.frozen.protocol_id
    assert execution.protocol.document == value.case.frozen.document
    assert execution.replay_input == value.prepared.materialization.replay_input
    assert execution.intent.document["bindings"]["preparation_id"] == execution.preparation_id
    assert execution.artifacts == (
        value.preparation.manifest_bytes,
        value.prepared.artifacts["recipe"],
        value.prepared.artifacts["materialization"],
        value.prepared.artifacts["normalized"],
    )
    detached = execution.source.artifacts
    detached["finding_report"] = b"changed detached copy"
    assert execution.source.artifacts["finding_report"] != detached["finding_report"]
    value.preparation.artifacts["normalized"] = b"changed caller preparation"
    assert execution.preparation.artifacts["normalized"] == execution.replay_input.normalized_bytes
    with pytest.raises(FrozenInstanceError):
        execution._source = value.source
    assert tree(value.case.root) == before


@pytest.mark.parametrize("split", ["confirmation", "invalid", "DEVELOPMENT"])
def test_preparation_confirmation_precedes_any_identity_or_package_io(split):
    with pytest.raises(ConfirmationAccessDenied):
        prepare_reduction_execution(
            Unreadable(), Unreadable(), expected_preparation_id="invalid",
            expected_bundle_id="invalid", expected_report_id="invalid", split=split,
        )


@pytest.mark.parametrize(
    "field", ["expected_preparation_id", "expected_bundle_id", "expected_report_id"]
)
@pytest.mark.parametrize("bad", ["../invalid", "A" * 64, True])
def test_bad_pins_precede_every_package_property(field, bad):
    options = {
        "expected_preparation_id": "0" * 64, "expected_bundle_id": "1" * 64,
        "expected_report_id": "2" * 64, "split": "development", field: bad,
    }
    with pytest.raises(EvidenceValidationError):
        prepare_reduction_execution(Unreadable(), Unreadable(), **options)


@pytest.mark.parametrize("operation", ["find", "authorize"])
@pytest.mark.parametrize("nonce", ["a" * 31, "A" * 32, True, "../invalid"])
def test_invalid_nonce_precedes_context_and_ledger_access(operation, nonce):
    with pytest.raises(EvidenceValidationError, match="nonce requires"):
        if operation == "find":
            find_reduction_execution_reservation(Unreadable(), ledger=Unreadable(), nonce=nonce)
        else:
            authorize_reduction_execution(
                Unreadable(), ledger=Unreadable(), reservation_nonce=nonce, fence=forbidden
            )


def test_original_reservation_and_binding_have_distinct_current_fences(reduction_case):
    value, actions = reduction_case, []
    execution = prepare(value)
    assert find_reduction_execution_reservation(execution, ledger=value.ledger, nonce=NONCE) is None

    def fence():
        actions.append("fence")

    def reserve(protocol, nonce):
        assert actions == ["fence"]
        actions.append("reserve")
        return value.ledger.reserve_with_nonce(protocol, nonce)

    def bind(reservation, raw, **kwargs):
        assert actions == ["fence", "reserve", "fence"]
        actions.append("bind")
        return value.ledger.bind_intent(reservation, raw, **kwargs)

    reservation = authorize(
        value, execution, fence=fence,
        ledger=Proxy(value.ledger, reserve_with_nonce=reserve, bind_intent=bind),
    )
    assert actions == ["fence", "reserve", "fence", "bind"]
    assert reservation.attempt_index == 3
    assert reservation.document["nonce"] == NONCE
    assert find_reduction_execution_reservation(
        execution, ledger=value.ledger, nonce=NONCE
    ) == reservation
    assert value.ledger.get_intent(reservation.attempt_id) == execution.intent.canonical_bytes
    assert value.ledger.get_outcome(reservation.attempt_id) is None
    for raw in (execution.intent.canonical_bytes, *execution.artifacts):
        assert value.ledger.read_artifact(digest(raw)) == raw


@pytest.mark.parametrize("state", ["unbound", "bound", "committed"])
def test_any_existing_original_nonce_refuses_another_execution(reduction_case, state):
    value = reduction_case
    execution = prepare(value)
    if state == "unbound":
        reservation = value.ledger.reserve_with_nonce(execution.protocol, NONCE)
    else:
        reservation = authorize(value, execution)
    if state == "committed":
        failure = build_reduction_failure(
            reservation, execution.intent, "controlled_failure", "Already finalized"
        )
        value.ledger.publish(reservation, failure)
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError, match="already consumed"):
        authorize(value, execution, fence=forbidden)
    assert tree(value.case.root) == before


@pytest.mark.parametrize("at", ["reserve", "bind"])
def test_stale_fence_never_performs_its_next_original_write(reduction_case, at):
    value, calls = reduction_case, []
    execution = prepare(value)
    before = tree(value.case.root)

    def fence():
        calls.append("fence")
        if at == "reserve" or len(calls) == 2:
            raise RuntimeError("Current owner no longer authorizes this write")

    with pytest.raises(RuntimeError, match="Current owner"):
        authorize(value, execution, fence=fence)
    observed = find_reduction_execution_reservation(execution, ledger=value.ledger, nonce=NONCE)
    if at == "reserve":
        assert observed is None
        assert tree(value.case.root) == before
    else:
        assert observed.attempt_index == 3
        assert value.ledger.get_intent(observed.attempt_id) is None
        assert value.ledger.get_outcome(observed.attempt_id) is None


@pytest.mark.parametrize("at", ["reserve", "bind"])
def test_lost_authorization_ack_keeps_consumed_nonce_without_repair(reduction_case, at):
    value = reduction_case
    execution = prepare(value)

    def reserve(protocol, nonce):
        committed = value.ledger.reserve_with_nonce(protocol, nonce)
        if at == "reserve":
            raise OSError("Reservation acknowledgment lost")
        return committed

    def bind(reservation, raw, **kwargs):
        value.ledger.bind_intent(reservation, raw, **kwargs)
        raise OSError("Intent acknowledgment lost")

    with pytest.raises(OSError, match="acknowledgment lost"):
        authorize(
            value, execution,
            ledger=Proxy(value.ledger, reserve_with_nonce=reserve, bind_intent=bind),
        )
    observed = find_reduction_execution_reservation(execution, ledger=value.ledger, nonce=NONCE)
    assert observed.attempt_index == 3
    assert (value.ledger.get_intent(observed.attempt_id) is not None) is (at == "bind")
    assert value.ledger.get_outcome(observed.attempt_id) is None
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError, match="already consumed"):
        authorize(value, execution, fence=forbidden)
    assert tree(value.case.root) == before


def test_original_budget_exhaustion_cannot_be_replaced_by_a_named_dispatch(reduction_case):
    value = reduction_case
    execution = prepare(value)
    for nonce in ("1" * 32, "2" * 32, "3" * 32):
        value.ledger.reserve_with_nonce(execution.protocol, nonce)
    before = tree(value.case.root)
    with pytest.raises(AttemptBudgetExceededError):
        authorize(value, execution)
    assert len(value.ledger.list_reservations(execution.protocol)) == 5
    assert tree(value.case.root) == before


def test_changed_original_prefix_is_rejected_before_admission(reduction_case):
    value = reduction_case
    execution = prepare(value)
    with pytest.raises(EvidenceValidationError, match="shorter"):
        authorize(
            value, execution, fence=forbidden,
            ledger=Proxy(value.ledger, list_reservations=lambda _protocol: ()),
        )


def test_named_reservation_must_match_the_requested_dispatch_nonce(reduction_case):
    value = reduction_case
    execution = prepare(value)

    def reserve(protocol, _nonce):
        return value.ledger.reserve_with_nonce(protocol, "b" * 32)

    with pytest.raises(EvidenceValidationError, match="Named execution reservation differs"):
        authorize(
            value, execution,
            ledger=Proxy(value.ledger, reserve_with_nonce=reserve, bind_intent=forbidden),
        )
    suffix = value.ledger.list_reservations(execution.protocol)[-1]
    assert suffix.attempt_index == 3
    assert suffix.document["nonce"] == "b" * 32
    assert value.ledger.get_intent(suffix.attempt_id) is None
    assert value.ledger.get_outcome(suffix.attempt_id) is None


def test_result_audit_is_pure_and_submission_projection_does_not_mutate_bytes(
    reduction_case, monkeypatch
):
    value = reduction_case
    execution = prepare(value)
    reservation = authorize(value, execution)
    result = value.case.engine_factory(60).run(execution.replay_input)
    before = tree(value.case.root)
    no_runtime(monkeypatch)
    for name in ("reserve", "reserve_with_nonce", "bind_intent", "publish", "__init__"):
        monkeypatch.setattr(LocalAttemptLedger, name, forbidden)
    audited = audit_reduction_execution(execution, reservation, result.canonical_bytes)
    assert audited.receipt.document["attempt"] == reservation.document
    assert audited.result_bytes == result.canonical_bytes
    assert audited.submission.attempt_id == reservation.attempt_id
    assert audited.submission.state_audit["flags"]["from_origin_prefix_replayed"] is True
    detached = audited.submission.state_audit
    detached["flags"]["checkpoint_resume_verified"] = True
    assert audited.submission.state_audit["flags"]["checkpoint_resume_verified"] is False
    assert tree(value.case.root) == before


def test_invalid_raw_result_does_not_publish_a_research_failure(reduction_case):
    value = reduction_case
    execution = prepare(value)
    reservation = authorize(value, execution)
    result = value.case.engine_factory(60).run(execution.replay_input).document
    result["account_trace"][-1]["fields"]["cash_total"] = "1"
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        audit_reduction_execution(
            execution, reservation, build_replay_result(result).canonical_bytes
        )
    assert value.ledger.get_outcome(reservation.attempt_id) is None
    assert tree(value.case.root) == before


def test_publication_reaudits_and_fences_one_original_receipt(reduction_case, monkeypatch):
    value, actions = reduction_case, []
    execution, reservation, audited = audited_case(value)
    no_runtime(monkeypatch)

    def fence():
        actions.append("fence")

    def publish(actual, raw, **kwargs):
        assert actions == ["fence"]
        assert actual == reservation
        assert raw == audited.receipt.canonical_bytes
        actions.append("publish")
        return value.ledger.publish(actual, raw, **kwargs)

    submitted = publish_reduction_execution(
        execution, reservation, audited,
        ledger=Proxy(value.ledger, publish=publish), fence=fence,
    )
    assert actions == ["fence", "publish"]
    assert submitted == audited.submission
    assert value.ledger.get_outcome(reservation.attempt_id) == audited.receipt.canonical_bytes
    inspected = inspect_reduction_run(
        submitted.run_id, source=execution.source, split="development",
        ledger_factory=lambda: value.ledger,
    )
    assert inspected["receipt"] == audited.receipt.document
    assert inspected["state_audit"] == submitted.state_audit


def test_stale_publication_fence_leaves_consumed_intent_unfinalized(reduction_case):
    value = reduction_case
    execution, reservation, audited = audited_case(value)
    before = tree(value.case.root)

    def fence():
        raise RuntimeError("Stale coordinator cannot publish")

    with pytest.raises(RuntimeError, match="Stale coordinator"):
        publish_reduction_execution(
            execution, reservation, audited,
            ledger=Proxy(value.ledger, publish=forbidden), fence=fence,
        )
    assert tree(value.case.root) == before
    assert value.ledger.get_outcome(reservation.attempt_id) is None


@pytest.mark.parametrize("artifact", ["audit", "receipt", "result"])
def test_publication_recomputes_bytes_instead_of_trusting_audited_flags(reduction_case, artifact):
    value = reduction_case
    execution, reservation, audited = audited_case(value)
    if artifact == "result":
        changed = parse(audited.result_bytes)
        changed["account_trace"][-1]["fields"]["cash_total"] = "1"
        altered = replace(audited, result_bytes=build_replay_result(changed).canonical_bytes)
    else:
        changed = parse(audited.audit_bytes)
        changed["flags"]["focus_state_captured"] = True
        changed_raw = canonical(changed)
        altered = replace(audited, audit_bytes=changed_raw)
        if artifact == "receipt":
            receipt = audited.receipt.document
            receipt["bindings"]["state_audit_sha256"] = digest(changed_raw)
            altered = replace(altered, receipt=build_reduction_run_receipt(receipt))
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        publish_reduction_execution(
            execution, reservation, altered,
            ledger=Proxy(value.ledger, publish=forbidden), fence=forbidden,
        )
    assert tree(value.case.root) == before


def test_publication_reprepares_frozen_input_before_any_actual_write(reduction_case):
    value = reduction_case
    execution, reservation, audited = audited_case(value)
    changed = execution.preparation.artifacts
    changed["normalized"] = changed["normalized"].splitlines(keepends=True)[0]
    altered = replace(execution, _preparation=package(changed))
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        publish_reduction_execution(
            altered, reservation, audited,
            ledger=Proxy(value.ledger, publish=forbidden), fence=forbidden,
        )
    assert tree(value.case.root) == before


def test_audited_result_cannot_be_published_for_another_original_attempt(reduction_case):
    value = reduction_case
    execution, _reservation, audited = audited_case(value)
    another = authorize(value, execution, reservation_nonce="b" * 32)
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError, match="recomputation"):
        publish_reduction_execution(
            execution, another, audited,
            ledger=Proxy(value.ledger, publish=forbidden), fence=forbidden,
        )
    assert tree(value.case.root) == before
    assert value.ledger.get_outcome(another.attempt_id) is None


@pytest.mark.parametrize(
    "artifact", ["intent", "manifest", "recipe", "materialization", "normalized"]
)
def test_publication_requires_original_preexecution_cas_closure(reduction_case, artifact):
    value = reduction_case
    execution, reservation, audited = audited_case(value)
    if artifact == "intent":
        target = execution.intent.intent_id
    elif artifact == "manifest":
        target = execution.preparation_id
    else:
        target = digest(execution.preparation.artifacts[artifact])
    real_read = value.ledger.read_artifact

    def read(sha, **kwargs):
        return b"changed exact CAS" if sha == target else real_read(sha, **kwargs)

    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        publish_reduction_execution(
            execution, reservation, audited,
            ledger=Proxy(value.ledger, read_artifact=read, publish=forbidden), fence=forbidden,
        )
    assert tree(value.case.root) == before


def test_existing_outcome_is_never_overwritten_or_implicitly_recovered(reduction_case):
    value = reduction_case
    execution, reservation, audited = audited_case(value)
    failure = build_reduction_failure(
        reservation, execution.intent, "controlled_existing_failure", "Terminal remains immutable"
    )
    value.ledger.publish(reservation, failure)
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError, match="already has an outcome"):
        publish_reduction_execution(
            execution, reservation, audited,
            ledger=Proxy(value.ledger, publish=forbidden), fence=forbidden,
        )
    assert value.ledger.get_outcome(reservation.attempt_id) == failure
    assert tree(value.case.root) == before


@pytest.mark.parametrize("mode", ["before", "after", "wrong_id", "outcome_read", "artifact_read"])
def test_publication_uncertainty_never_writes_a_compensating_failure(reduction_case, mode):
    value = reduction_case
    execution, reservation, audited = audited_case(value)
    calls, committed = [], []
    real_outcome, real_read = value.ledger.get_outcome, value.ledger.read_artifact

    def publish(actual, raw, **kwargs):
        calls.append(raw)
        if mode == "before":
            raise OSError("Outcome publication unconfirmed before return")
        result = value.ledger.publish(actual, raw, **kwargs)
        committed.append(result)
        if mode == "after":
            raise OSError("Committed receipt acknowledgment lost")
        return "0" * 64 if mode == "wrong_id" else result

    def outcome(attempt):
        if mode == "outcome_read" and committed and attempt == reservation.attempt_id:
            raise OSError("Readback unavailable after actual receipt commit")
        return real_outcome(attempt)

    def read(sha, **kwargs):
        if mode == "artifact_read" and committed and sha == digest(audited.audit_bytes):
            raise OSError("Artifact readback unavailable after actual receipt commit")
        return real_read(sha, **kwargs)

    with pytest.raises(ProtocolRunError) as caught:
        publish_reduction_execution(
            execution, reservation, audited,
            ledger=Proxy(value.ledger, publish=publish, get_outcome=outcome, read_artifact=read),
            fence=lambda: None,
        )
    assert caught.value.code == "attempt_outcome_unconfirmed"
    assert caught.value.exit_code == 3
    assert caught.value.attempt_id == reservation.attempt_id
    assert calls == [audited.receipt.canonical_bytes]
    actual = value.ledger.get_outcome(reservation.attempt_id)
    assert actual == (None if mode == "before" else audited.receipt.canonical_bytes)
    assert len(value.ledger.list_reservations(execution.protocol)) == 3


def test_nonce_lookup_rejects_multiple_actual_prefix_matches(reduction_case):
    value = reduction_case
    execution = prepare(value)
    original = value.ledger.reserve_with_nonce(execution.protocol, NONCE)
    document = original.document
    document["attempt_index"] = 4
    raw = canonical(document)
    duplicate = AttemptReservation(digest(raw), raw)
    prefix = value.ledger.list_reservations(execution.protocol)
    get = value.ledger.get_reservation
    def reservation(attempt):
        return duplicate if attempt == duplicate.attempt_id else get(attempt)

    port = Proxy(
        value.ledger, list_reservations=lambda _protocol: (*prefix, duplicate),
        get_reservation=reservation,
    )
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError, match="more than one"):
        find_reduction_execution_reservation(execution, ledger=port, nonce=NONCE)
    assert tree(value.case.root) == before
