"""Persisted comparisons are read-only, reaudited and pinned to the actual source.

Identity cases reuse saved native facts. Short-prefix cases are explicitly
offline consistency transformations, not a new native execution claim. Their
saved environment metadata is retained so differing metadata is never hidden by
the product comparison. Actual timing/P/NP/NE qualification runs remotely.
"""

import json
import socket
import sqlite3
import subprocess

import pytest
from test_reduction_execution import Proxy, forbidden
from test_reduction_execution import reduction_case as reduction_case
from test_reduction_execution import run as execute_prefix
from test_reduction_search import OfflinePrefixEngine
from test_reductions import Unreadable, package, request
from test_search_findings import tree

from tickwitness.application.experiments import ProtocolRunError
from tickwitness.application.reduction_comparison import (
    compare_reduction_run,
    verify_reduction_comparison,
)
from tickwitness.application.reduction_execution import run_reduction_input
from tickwitness.application.reductions import prepare_reduction_input
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def compare(value, run_id, **changes):
    options = {
        "source": value.source,
        "expected_bundle_id": value.source.bundle_id,
        "expected_report_id": digest(value.source.artifacts["finding_report"]),
        "split": "development",
        "ledger_factory": lambda: value.ledger,
    }
    options.update(changes)
    return compare_reduction_run(run_id, **options)


def verify(value, run_id, comparison, **changes):
    options = {
        "expected_comparison_id": comparison.comparison_id,
        "source": value.source,
        "expected_bundle_id": value.source.bundle_id,
        "expected_report_id": digest(value.source.artifacts["finding_report"]),
        "split": "development",
        "ledger_factory": lambda: value.ledger,
    }
    options.update(changes)
    return verify_reduction_comparison(run_id, comparison.export_bytes, **options)


class OfflineComparisonPrefixEngine(OfflinePrefixEngine):
    """Retain saved environment identity in the declared offline projection."""

    def run(self, replay_input):
        result = super().run(replay_input).document
        saved = self.value.case.engine_factory(60).run(
            self.value.prepared.materialization.replay_input
        )
        result["environment"] = saved.document["environment"]
        return build_replay_result(result)


def shorter(value, through):
    prepared = prepare_reduction_input(
        value.source,
        request(focus=4, through=through, delay=0, ordinal=1),
        expected_bundle_id=value.source.bundle_id,
        expected_report_id=digest(value.source.artifacts["finding_report"]),
    )
    return run_reduction_input(
        package(prepared.artifacts),
        value.source,
        expected_preparation_id=prepared.preparation_id,
        split="development",
        ledger_factory=lambda: value.ledger,
        engine_factory=lambda _timeout: OfflineComparisonPrefixEngine(value),
    )


def test_identity_is_deterministic_readonly_after_original_budget_is_exhausted(
    reduction_case, monkeypatch
):
    value = reduction_case
    submitted = [execute_prefix(value) for _ in range(3)]
    owner = value.prepared.materialization.source.validation.protocol
    assert len(value.ledger.list_reservations(owner)) == 5
    before = tree(value.case.root)
    for method in ("reserve", "reserve_with_nonce", "bind_intent", "publish"):
        monkeypatch.setattr(LocalAttemptLedger, method, forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    result = compare(value, submitted[0].run_id)
    repeated = compare(value, submitted[0].run_id)
    verified = verify(value, submitted[0].run_id, result)
    assert result.canonical_bytes == repeated.canonical_bytes == verified.canonical_bytes
    assert result.comparison_id == digest(result.canonical_bytes)
    assert result.document["both_false_witnesses"] is True
    assert result.document["original_observation"]["truth"] is False
    assert result.document["reduced_assessment"]["outcome"] == "PRESERVED"
    assert result.document["bindings"]["original"]["run_id"] == (
        value.prepared.materialization.source.source_run_id
    )
    assert result.document["bindings"]["reduced"]["run_id"] == submitted[0].run_id
    assert json.loads(result.export_bytes)["comparison_id"] == result.comparison_id
    assert tree(value.case.root) == before
    assert len(value.ledger.list_reservations(owner)) == 5


@pytest.mark.parametrize(
    ("through", "outcome", "both"), [(6, "PRESERVED", True), (4, "NOT_EVALUABLE", None)]
)
def test_actual_persisted_offline_prefix_keeps_unknown_distinct_from_preserved(
    reduction_case, through, outcome, both
):
    value = reduction_case
    submitted = shorter(value, through)
    before = tree(value.case.root)
    result = compare(value, submitted.run_id)
    assessment = result.document["reduced_assessment"]
    assert result.document["both_false_witnesses"] is both
    assert assessment["outcome"] == outcome
    assert result.document["original_observation"]["value"] == "-2"
    if both is None:
        assert assessment["criterion_observation"]["truth"] is None
        assert assessment["criterion_observation"]["value"] is None
    else:
        assert assessment["criterion_observation"]["truth"] is False
    assert verify(value, submitted.run_id, result).export_bytes == result.export_bytes
    assert tree(value.case.root) == before


@pytest.mark.parametrize("operation", ["compare", "verify"])
@pytest.mark.parametrize("split", ["confirmation", "invalid", "DEVELOPMENT"])
def test_confirmation_precedes_every_evidence_property_identifier_and_factory(operation, split):
    options = {
        "source": Unreadable(),
        "expected_bundle_id": "invalid",
        "expected_report_id": "invalid",
        "split": split,
        "ledger_factory": forbidden,
    }
    with pytest.raises(ConfirmationAccessDenied):
        if operation == "compare":
            compare_reduction_run("invalid", **options)
        else:
            verify_reduction_comparison(
                "invalid", Unreadable(), expected_comparison_id="invalid", **options
            )


@pytest.mark.parametrize("field", ["run_id", "expected_bundle_id", "expected_report_id"])
@pytest.mark.parametrize("bad", ["../escape", "A" * 64, True])
def test_bad_identity_precedes_evidence_and_factory(field, bad):
    options = {
        "run_id": "0" * 64,
        "source": Unreadable(),
        "expected_bundle_id": "1" * 64,
        "expected_report_id": "2" * 64,
        "split": "development",
        "ledger_factory": forbidden,
        field: bad,
    }
    with pytest.raises(EvidenceValidationError):
        compare_reduction_run(**options)


@pytest.mark.parametrize("field", ["expected_bundle_id", "expected_report_id"])
def test_valid_but_wrong_source_pin_precedes_ledger(reduction_case, field):
    value = reduction_case
    submitted = execute_prefix(value)
    with pytest.raises(EvidenceValidationError):
        compare(value, submitted.run_id, **{field: "0" * 64, "ledger_factory": forbidden})


def test_complete_source_validation_precedes_ledger_construction(reduction_case):
    value = reduction_case
    submitted = execute_prefix(value)
    with pytest.raises(EvidenceValidationError):
        compare(
            value,
            submitted.run_id,
            source=Proxy(value.source, manifest_bytes=b"{}"),
            ledger_factory=forbidden,
        )


@pytest.mark.parametrize("raw", [b"{}", b"{", b"[]", b'{"schema_version":1.0}', b"{}\n"])
def test_invalid_export_is_rejected_before_source_or_factory(raw):
    with pytest.raises(EvidenceValidationError):
        verify_reduction_comparison(
            "0" * 64,
            raw,
            expected_comparison_id="1" * 64,
            source=Unreadable(),
            expected_bundle_id="2" * 64,
            expected_report_id="3" * 64,
            split="development",
            ledger_factory=forbidden,
        )


def test_valid_export_with_wrong_pin_precedes_source_and_factory(reduction_case):
    value = reduction_case
    submitted = execute_prefix(value)
    exported = compare(value, submitted.run_id)
    with pytest.raises(EvidenceValidationError, match="expected pin"):
        verify(
            value,
            submitted.run_id,
            exported,
            expected_comparison_id="0" * 64,
            source=Unreadable(),
            ledger_factory=forbidden,
        )


@pytest.mark.parametrize("attack", ["verdict", "source", "extra_field"])
def test_rehashed_comparison_still_requires_independent_actual_evidence(reduction_case, attack):
    value = reduction_case
    submitted = execute_prefix(value)
    exported = compare(value, submitted.run_id)
    envelope = json.loads(exported.export_bytes)
    if attack == "verdict":
        envelope["report"]["both_false_witnesses"] = False
    elif attack == "source":
        envelope["report"]["bindings"]["source"]["report_id"] = "0" * 64
    else:
        envelope["report"]["invented_proof"] = True
    envelope["comparison_id"] = digest(canonical(envelope["report"]))
    forged = canonical(envelope)
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        verify_reduction_comparison(
            submitted.run_id,
            forged,
            expected_comparison_id=envelope["comparison_id"],
            source=value.source,
            expected_bundle_id=value.source.bundle_id,
            expected_report_id=digest(value.source.artifacts["finding_report"]),
            split="development",
            ledger_factory=lambda: value.ledger,
        )
    assert tree(value.case.root) == before


def test_valid_comparison_cannot_be_reused_for_another_actual_attempt(reduction_case):
    value = reduction_case
    first, second = execute_prefix(value), execute_prefix(value)
    exported = compare(value, first.run_id)
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError, match="independently recomputed"):
        verify(value, second.run_id, exported)
    assert tree(value.case.root) == before


def test_empty_existing_ledger_cannot_restore_source_slots(reduction_case):
    value = reduction_case
    submitted = execute_prefix(value)
    empty = LocalAttemptLedger(value.case.root / "empty")
    before = tree(value.case.root / "empty")
    with pytest.raises(EvidenceValidationError, match="shorter"):
        compare(value, submitted.run_id, ledger_factory=lambda: empty)
    assert tree(value.case.root / "empty") == before


def test_original_scenario_cannot_be_substituted_for_a_reduced_execution(reduction_case):
    value = reduction_case
    original = value.prepared.materialization.source.source_run_id
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        compare(value, original)
    assert tree(value.case.root) == before


@pytest.mark.parametrize("changed", ["result", "outcome", "intent"])
def test_observed_reduction_evidence_is_rechecked_after_domain_computation(reduction_case, changed):
    value = reduction_case
    submitted = execute_prefix(value)
    outcome = value.ledger.get_outcome(submitted.attempt_id)
    result_sha = parse(outcome)["bindings"]["replay_result_sha256"]
    before = tree(value.case.root)
    calls = []
    real_read = value.ledger.read_artifact
    real_outcome, real_intent = value.ledger.get_outcome, value.ledger.get_intent

    def read(sha, **kwargs):
        if changed == "result" and sha == result_sha:
            calls.append(sha)
            if len(calls) >= 3:
                return b"{}"
        return real_read(sha, **kwargs)

    def get(attempt, original, target):
        if changed == target and attempt == submitted.attempt_id:
            calls.append(attempt)
            if len(calls) >= 3:
                return b"{}"
        return original(attempt)

    proxy = Proxy(
        value.ledger,
        read_artifact=read,
        get_outcome=lambda attempt: get(attempt, real_outcome, "outcome"),
        get_intent=lambda attempt: get(attempt, real_intent, "intent"),
    )
    with pytest.raises(EvidenceValidationError):
        compare(value, submitted.run_id, ledger_factory=lambda: proxy)
    assert len(calls) >= 3
    assert tree(value.case.root) == before


def test_malformed_actual_result_is_never_downgraded_to_unknown(reduction_case):
    value = reduction_case
    submitted = execute_prefix(value)
    outcome = parse(value.ledger.get_outcome(submitted.attempt_id))
    result_sha = outcome["bindings"]["replay_result_sha256"]
    real_read = value.ledger.read_artifact
    proxy = Proxy(
        value.ledger,
        read_artifact=lambda sha, **kwargs: (
            b"{}" if sha == result_sha else real_read(sha, **kwargs)
        ),
    )
    before = tree(value.case.root)
    with pytest.raises((EvidenceValidationError, ReplayValidationError)):
        compare(value, submitted.run_id, ledger_factory=lambda: proxy)
    assert tree(value.case.root) == before


def test_failed_execution_has_no_comparison_and_cannot_be_repaired(reduction_case, monkeypatch):
    value = reduction_case
    with pytest.raises(ProtocolRunError) as caught:
        execute_prefix(value, engine_factory=forbidden)
    failed = value.ledger.get_outcome(caught.value.attempt_id)
    before = tree(value.case.root)
    for method in ("reserve", "reserve_with_nonce", "bind_intent", "publish"):
        monkeypatch.setattr(value.ledger, method, forbidden)
    with pytest.raises(EvidenceValidationError):
        compare(value, digest(failed))
    assert tree(value.case.root) == before


def test_external_source_is_snapshotted_once_instead_of_reread_after_validation(reduction_case):
    value = reduction_case
    submitted = execute_prefix(value)

    class ChangingSource:
        bundle_id = value.source.bundle_id
        manifest_bytes = value.source.manifest_bytes

        def __init__(self):
            self.reads = 0

        @property
        def artifacts(self):
            self.reads += 1
            return value.source.artifacts if self.reads == 1 else {"normalized": b"changed"}

    changing = ChangingSource()
    result = compare(value, submitted.run_id, source=changing)
    assert result.document["both_false_witnesses"] is True
    assert changing.reads == 1
