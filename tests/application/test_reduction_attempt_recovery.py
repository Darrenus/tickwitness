"""Read-only recovery observations of persisted original research attempts.

These tests use the existing saved-native fixture port for preparation/result
consistency. They are not new native execution or checkpoint qualifications.
"""

import json
import socket
import sqlite3
import subprocess

import pytest
from test_reduction_execution import Proxy, forbidden
from test_reduction_execution import reduction_case as reduction_case
from test_reduction_execution import run as execute_prefix
from test_reductions import Unreadable, package, request
from test_search_findings import tree

from tickwitness.application.experiments import ProtocolRunError
from tickwitness.application.reduction_execution import inspect_reduction_attempt
from tickwitness.application.reductions import prepare_reduction_input
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.reduction_records import (
    build_reduction_failure,
    build_reduction_intent,
)
from tickwitness.domain.evidence.reduction_recovery import load_reduction_attempt_recovery
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.infrastructure.attempt_ledger import AttemptNotFoundError, LocalAttemptLedger
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def observe(value, attempt_id, **changes):
    options = {
        "expected_preparation_id": value.prepared.preparation_id,
        "expected_bundle_id": value.source.bundle_id,
        "expected_report_id": digest(value.source.artifacts["finding_report"]),
        "split": "development",
        "ledger_factory": lambda: value.ledger,
    }
    options.update(changes)
    return inspect_reduction_attempt(attempt_id, value.preparation, value.source, **options)


def reserved(value, *, bind):
    owner = value.prepared.materialization.source.validation.protocol
    reservation = value.ledger.reserve(owner)
    if bind:
        intent = build_reduction_intent(value.prepared.materialization)
        value.ledger.bind_intent(
            reservation,
            intent.canonical_bytes,
            artifacts=(value.preparation.manifest_bytes, *value.prepared.artifacts.values()),
        )
    return reservation


def guard_readonly(monkeypatch):
    for method in ("reserve", "reserve_with_nonce", "bind_intent", "publish"):
        monkeypatch.setattr(LocalAttemptLedger, method, forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)


@pytest.mark.parametrize(
    ("bind", "status", "disposition"),
    [
        (False, "reserved_without_intent", "owner_review_required"),
        (True, "reserved_unfinalized", "new_original_attempt_required_for_execution"),
    ],
)
def test_unfinished_original_slot_is_observed_without_authorizing_execution(
    reduction_case, monkeypatch, bind, status, disposition
):
    value = reduction_case
    reservation = reserved(value, bind=bind)
    before = tree(value.case.root)
    guard_readonly(monkeypatch)
    report = observe(value, reservation.attempt_id)
    assert report["status"] == status
    assert report["attempt"] == reservation.document
    assert report["recovery"] == {
        "disposition": disposition,
        "restart_mode": "frozen_origin_new_attempt_only_v1",
        "checkpoint_supported": False,
        "execution_authorized": False,
    }
    assert report["final_manifest"] is None
    assert report["bindings"]["outcome_id"] is None
    assert report["bindings"]["run_id"] is None
    assert report["verification"]["preparation_binding_verified"] is bind
    assert report["verification"]["preparation_cas_verified"] is bind
    assert report["verification"]["terminal_reverified"] is False
    assert report["verification"]["global_absence_verified"] is False
    assert observe(value, reservation.attempt_id) == report
    assert load_reduction_attempt_recovery(canonical(report)) == report
    assert tree(value.case.root) == before


def test_committed_failure_reverifies_the_original_terminal_without_new_attempt(
    reduction_case, monkeypatch
):
    value = reduction_case

    def engine(_timeout):
        raise RuntimeError("Controlled original engine construction failure")

    with pytest.raises(ProtocolRunError) as caught:
        execute_prefix(value, engine_factory=engine)
    attempt_id = caught.value.attempt_id
    outcome = value.ledger.get_outcome(attempt_id)
    before = tree(value.case.root)
    guard_readonly(monkeypatch)
    report = observe(value, attempt_id)
    assert report["status"] == "committed_failure"
    assert report["recovery"]["disposition"] == "failure_reverified"
    assert report["bindings"]["outcome_id"] == digest(outcome)
    assert report["bindings"]["run_id"] is None
    assert report["final_manifest"] is None
    assert report["verification"]["terminal_reverified"] is True
    assert observe(value, attempt_id) == report
    assert tree(value.case.root) == before


def test_committed_result_returns_exact_existing_manifest_after_budget_exhaustion(
    reduction_case, monkeypatch
):
    value = reduction_case
    submissions = [execute_prefix(value) for _ in range(3)]
    submitted = submissions[0]
    outcome = value.ledger.get_outcome(submitted.attempt_id)
    owner = value.prepared.materialization.source.validation.protocol
    assert len(value.ledger.list_reservations(owner)) == 5
    before = tree(value.case.root)
    guard_readonly(monkeypatch)
    report = observe(value, submitted.attempt_id)
    assert report["status"] == "committed_result"
    assert report["recovery"]["disposition"] == "result_reverified_without_execution"
    assert report["bindings"] == {
        "intent_id": submitted.intent_id,
        "outcome_id": submitted.run_id,
        "run_id": submitted.run_id,
    }
    assert report["final_manifest"] == parse(outcome)
    assert canonical(report["final_manifest"]) == outcome
    assert report["verification"]["terminal_reverified"] is True
    for flag in (
        "attempt_reserved",
        "native_replayed",
        "research_published",
        "job_state_changed",
        "checkpoint_restored",
        "retry_performed",
        "budget_refunded",
        "global_absence_verified",
        "global_ledger_authenticity_verified",
    ):
        assert report["verification"][flag] is False
    assert observe(value, submitted.attempt_id) == report
    assert tree(value.case.root) == before


def test_committed_result_survives_lost_publication_acknowledgement(reduction_case, monkeypatch):
    value = reduction_case
    calls = []

    def publish(reservation, raw, **kwargs):
        calls.append(raw)
        value.ledger.publish(reservation, raw, **kwargs)
        raise OSError("Acknowledgement lost after immutable outcome commit")

    with pytest.raises(ProtocolRunError) as caught:
        execute_prefix(value, ledger_factory=lambda: Proxy(value.ledger, publish=publish))
    assert caught.value.code == "attempt_outcome_unconfirmed"
    assert len(calls) == 1
    before = tree(value.case.root)
    guard_readonly(monkeypatch)
    report = observe(value, caught.value.attempt_id)
    assert report["status"] == "committed_result"
    assert canonical(report["final_manifest"]) == calls[0]
    assert report["bindings"]["run_id"] == digest(calls[0])
    assert tree(value.case.root) == before


@pytest.mark.parametrize("split", ["confirmation", "invalid", "DEVELOPMENT"])
def test_confirmation_precedes_all_ids_packages_and_factories(split):
    with pytest.raises(ConfirmationAccessDenied):
        inspect_reduction_attempt(
            "invalid",
            Unreadable(),
            Unreadable(),
            expected_preparation_id="invalid",
            expected_bundle_id="invalid",
            expected_report_id="invalid",
            split=split,
            ledger_factory=forbidden,
        )


@pytest.mark.parametrize(
    "field", ["attempt_id", "expected_preparation_id", "expected_bundle_id", "expected_report_id"]
)
@pytest.mark.parametrize("bad", ["../escape", "A" * 64, True])
def test_invalid_identity_precedes_any_package_or_factory(field, bad):
    options = {
        "attempt_id": "0" * 64,
        "preparation": Unreadable(),
        "source": Unreadable(),
        "expected_preparation_id": "1" * 64,
        "expected_bundle_id": "2" * 64,
        "expected_report_id": "3" * 64,
        "split": "development",
        "ledger_factory": forbidden,
        field: bad,
    }
    with pytest.raises(EvidenceValidationError):
        inspect_reduction_attempt(**options)


@pytest.mark.parametrize(
    "field", ["expected_preparation_id", "expected_bundle_id", "expected_report_id"]
)
def test_wrong_pin_is_refused_before_opening_original_ledger(reduction_case, field):
    value = reduction_case
    with pytest.raises(EvidenceValidationError):
        observe(value, "0" * 64, **{field: "0" * 64, "ledger_factory": forbidden})


def test_missing_original_attempt_cannot_be_reconstructed_from_portable_source(reduction_case):
    value = reduction_case
    before = tree(value.case.root)
    with pytest.raises(AttemptNotFoundError):
        observe(value, "0" * 64)
    assert tree(value.case.root) == before


def test_reservation_from_another_owner_cannot_replace_the_original_slot(reduction_case):
    value = reduction_case
    original = reserved(value, bind=False)
    document = original.document
    document["protocol_id"] = "0" * 64
    raw = canonical(document)
    foreign = AttemptReservation(digest(raw), raw)
    actual_get = value.ledger.get_reservation

    def get(attempt):
        return foreign if attempt == foreign.attempt_id else actual_get(attempt)

    with pytest.raises(EvidenceValidationError, match="reservation differs"):
        observe(
            value,
            foreign.attempt_id,
            ledger_factory=lambda: Proxy(value.ledger, get_reservation=get),
        )


def test_unbound_slot_does_not_require_uncommitted_preparation_cas(reduction_case):
    value = reduction_case
    reservation = reserved(value, bind=False)
    manifest_sha = digest(value.preparation.manifest_bytes)
    real_read = value.ledger.read_artifact

    def read(sha, **kwargs):
        if sha == manifest_sha:
            raise AssertionError("Unbound attempt cannot claim preparation CAS authority")
        return real_read(sha, **kwargs)

    report = observe(
        value,
        reservation.attempt_id,
        ledger_factory=lambda: Proxy(value.ledger, read_artifact=read),
    )
    assert report["status"] == "reserved_without_intent"
    assert report["verification"]["preparation_binding_verified"] is False


def test_concurrent_bind_and_publication_reobserves_intent_without_inspector_writes(
    reduction_case, monkeypatch
):
    value = reduction_case
    reservation = reserved(value, bind=False)
    intent = build_reduction_intent(value.prepared.materialization)
    failure = build_reduction_failure(
        reservation, intent, "controlled_concurrent_failure", "Independent writer finished"
    )
    source_before = tree(value.case.root / "portable-source")
    intent_reads, writer_actions = [], []

    def read_intent(attempt):
        raw = value.ledger.get_intent(attempt)
        if attempt == reservation.attempt_id:
            intent_reads.append(raw)
        return raw

    def concurrently_publish(attempt):
        if attempt == reservation.attempt_id and not writer_actions:
            # This is the separate writer actor. The inspector receives only
            # the read port below; all its write methods remain forbidden.
            value.ledger.bind_intent(
                reservation,
                intent.canonical_bytes,
                artifacts=(value.preparation.manifest_bytes, *value.prepared.artifacts.values()),
            )
            writer_actions.append("intent_bound")
            value.ledger.publish(reservation, failure)
            writer_actions.append("failure_published")
        return value.ledger.get_outcome(attempt)

    port = Proxy(
        value.ledger,
        reserve=forbidden,
        reserve_with_nonce=forbidden,
        bind_intent=forbidden,
        publish=forbidden,
        get_intent=read_intent,
        get_outcome=concurrently_publish,
    )
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    report = observe(value, reservation.attempt_id, ledger_factory=lambda: port)
    assert intent_reads == [None, intent.canonical_bytes]
    assert writer_actions == ["intent_bound", "failure_published"]
    assert report["status"] == "committed_failure"
    assert report["bindings"]["outcome_id"] == digest(failure)
    assert report["verification"]["research_published"] is False
    after_writer = tree(value.case.root)
    assert observe(value, reservation.attempt_id) == report
    assert tree(value.case.root) == after_writer
    assert tree(value.case.root / "portable-source") == source_before


@pytest.mark.parametrize(
    "artifact", ["intent", "manifest", "recipe", "materialization", "normalized"]
)
def test_bound_attempt_requires_every_exact_preparation_and_intent_cas(reduction_case, artifact):
    value = reduction_case
    reservation = reserved(value, bind=True)
    if artifact == "intent":
        target = digest(value.ledger.get_intent(reservation.attempt_id))
    elif artifact == "manifest":
        target = digest(value.preparation.manifest_bytes)
    else:
        target = digest(value.prepared.artifacts[artifact])
    real_read = value.ledger.read_artifact

    def read(sha, **kwargs):
        return b"changed CAS bytes" if sha == target else real_read(sha, **kwargs)

    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        observe(
            value,
            reservation.attempt_id,
            ledger_factory=lambda: Proxy(value.ledger, read_artifact=read),
        )
    assert tree(value.case.root) == before


def test_another_valid_preparation_cannot_rebind_an_existing_attempt(reduction_case):
    value = reduction_case
    reservation = reserved(value, bind=True)
    other = prepare_reduction_input(
        value.source,
        request(focus=4, through=6, delay=0, ordinal=1),
        expected_bundle_id=value.source.bundle_id,
        expected_report_id=digest(value.source.artifacts["finding_report"]),
    )
    with pytest.raises(EvidenceValidationError, match="intent differs"):
        inspect_reduction_attempt(
            reservation.attempt_id,
            package(other.artifacts),
            value.source,
            expected_preparation_id=other.preparation_id,
            expected_bundle_id=value.source.bundle_id,
            expected_report_id=digest(value.source.artifacts["finding_report"]),
            split="development",
            ledger_factory=lambda: value.ledger,
        )


def test_baseline_attempt_is_not_classified_as_unfinished_reduction(reduction_case):
    value = reduction_case
    owner = value.prepared.materialization.source.validation.protocol
    baseline = value.ledger.list_reservations(owner)[0]
    with pytest.raises(EvidenceValidationError, match="no observed immutable reduction intent"):
        observe(value, baseline.attempt_id)


def test_scenario_intent_cannot_be_treated_as_a_reduction_binding(reduction_case):
    value = reduction_case
    owner = value.prepared.materialization.source.validation.protocol
    scenario = value.ledger.list_reservations(owner)[1]
    with pytest.raises(EvidenceValidationError, match="Reduction intent"):
        observe(value, scenario.attempt_id)


def test_malformed_terminal_is_not_classified_as_unfinished(reduction_case):
    value = reduction_case
    reservation = reserved(value, bind=True)
    malformed = canonical({"kind": "unknown_terminal", "attempt": reservation.document})
    real_outcome, real_read = value.ledger.get_outcome, value.ledger.read_artifact

    def outcome(attempt):
        return malformed if attempt == reservation.attempt_id else real_outcome(attempt)

    def read(sha, **kwargs):
        return malformed if sha == digest(malformed) else real_read(sha, **kwargs)

    with pytest.raises(EvidenceValidationError, match="not a reduction result or failure"):
        observe(
            value,
            reservation.attempt_id,
            ledger_factory=lambda: Proxy(value.ledger, get_outcome=outcome, read_artifact=read),
        )


def test_rehashed_result_audit_is_recomputed_instead_of_trusting_saved_flags(reduction_case):
    value = reduction_case
    submitted = execute_prefix(value)
    receipt = parse(value.ledger.get_outcome(submitted.attempt_id))
    forged = json.loads(canonical(submitted.state_audit))
    forged["flags"]["checkpoint_resume_verified"] = True
    forged_raw = canonical(forged)
    receipt["bindings"]["state_audit_sha256"] = digest(forged_raw)
    forged_receipt = canonical(receipt)
    real_read, real_outcome = value.ledger.read_artifact, value.ledger.get_outcome

    def read(sha, **kwargs):
        if sha == digest(forged_receipt):
            return forged_receipt
        if sha == digest(forged_raw):
            return forged_raw
        return real_read(sha, **kwargs)

    def outcome(attempt):
        return forged_receipt if attempt == submitted.attempt_id else real_outcome(attempt)

    with pytest.raises(EvidenceValidationError, match="audit differs"):
        observe(
            value,
            submitted.attempt_id,
            ledger_factory=lambda: Proxy(value.ledger, read_artifact=read, get_outcome=outcome),
        )
