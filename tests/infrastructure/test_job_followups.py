"""Read-only dispatch recovery uses genuine saved-native fixture results.

These are semantic fixtures, not a new native execution qualification.
"""

import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_native_job_supervisor import queued
from test_reduction_execution import forbidden
from test_reduction_execution import reduction_case as reduction_case
from test_search_findings import tree

from tickwitness.application.jobs import JobStoreError
from tickwitness.application.reduction_execution import (
    audit_reduction_execution,
    authorize_reduction_execution,
    publish_reduction_execution,
)
from tickwitness.domain.evidence.reduction_records import build_reduction_failure
from tickwitness.domain.evidence.run_records import digest, parse
from tickwitness.domain.jobs.contracts import build_followup_job_spec, job_dispatch_nonce
from tickwitness.infrastructure import job_reduction
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.job_followups import find_committed_dispatch
from tickwitness.infrastructure.job_lineage import JobFamily
from tickwitness.infrastructure.job_reduction import prepare_native_job
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


@pytest.fixture
def dispatch_case(reduction_case, tmp_path_factory):
    origin, _, _ = queued(reduction_case, tmp_path_factory.mktemp("job-followup"))
    child = build_followup_job_spec(origin, origin.spec_id, "retry_from_origin_v1", "retry-a")
    prepared = prepare_native_job(origin)
    return reduction_case, origin, child, prepared


def reserve(prepared, dispatch):
    return authorize_reduction_execution(
        prepared.execution,
        ledger=prepared.ledger,
        reservation_nonce=job_dispatch_nonce(dispatch),
        fence=lambda: None,
    )


def commit(value, prepared, dispatch, *, failure=False):
    reservation = reserve(prepared, dispatch)
    if failure:
        outcome = build_reduction_failure(
            reservation, prepared.execution.intent, "fixture_failure", "Controlled semantic fixture"
        )
        prepared.ledger.publish(reservation, outcome)
    else:
        raw = value.case.engine_factory(60).run(prepared.execution.replay_input).canonical_bytes
        audited = audit_reduction_execution(prepared.execution, reservation, raw)
        publish_reduction_execution(
            prepared.execution, reservation, audited, ledger=prepared.ledger, fence=lambda: None
        )
        outcome = audited.receipt.canonical_bytes
    return reservation, outcome


def readonly(monkeypatch):
    for name in ("reserve", "reserve_with_nonce", "bind_intent", "publish"):
        monkeypatch.setattr(LocalAttemptLedger, name, forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(job_reduction, "require_native_runtime", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)


def test_no_reservation_or_unfinalized_nonce_never_authorizes_replay(dispatch_case, monkeypatch):
    value, origin, child, prepared = dispatch_case
    assert find_committed_dispatch(origin, (origin,)) is None
    reserve(prepared, origin)
    prepared.ledger.reserve_with_nonce(prepared.execution.protocol, job_dispatch_nonce(child))
    before = tree(value.case.root)
    readonly(monkeypatch)
    assert find_committed_dispatch(origin, (origin, child)) is None
    assert tree(value.case.root) == before


@pytest.mark.parametrize("failure", [False, True])
def test_original_result_or_failure_is_independently_verified_readonly(
    dispatch_case, monkeypatch, failure
):
    value, origin, _, prepared = dispatch_case
    reservation, outcome = commit(value, prepared, origin, failure=failure)
    before = tree(value.case.root)
    readonly(monkeypatch)
    assert find_committed_dispatch(origin, (origin,)) == (origin, outcome)
    assert find_committed_dispatch(origin, (origin,)) == (origin, outcome)
    assert parse(outcome)["attempt"] == reservation.document
    assert tree(value.case.root) == before


@pytest.mark.parametrize("failure", [False, True])
def test_stale_catalog_can_recover_registered_descendant_without_free_replay(
    dispatch_case, monkeypatch, failure
):
    value, origin, child, prepared = dispatch_case
    reserve(prepared, origin)
    family = JobFamily(origin)
    with family.locked():
        family.claim_retry(child)
    reservation, outcome = commit(value, prepared, child, failure=failure)
    before = tree(value.case.root)
    readonly(monkeypatch)
    assert find_committed_dispatch(origin, family.specs()) == (child, outcome)
    assert parse(outcome)["attempt"]["nonce"] == job_dispatch_nonce(child)
    assert reservation.attempt_index == 4
    assert tree(value.case.root) == before


def test_multiple_distinct_original_outcomes_fail_closed(dispatch_case, monkeypatch):
    value, origin, child, prepared = dispatch_case
    commit(value, prepared, origin)
    commit(value, prepared, child, failure=True)
    before = tree(value.case.root)
    readonly(monkeypatch)
    with pytest.raises(JobStoreError, match="multiple distinct"):
        find_committed_dispatch(origin, (origin, child))
    assert tree(value.case.root) == before


@pytest.mark.parametrize("missing", ["outcome", "intent", "preparation", "result"])
@pytest.mark.parametrize("corruption", ["missing", "forged"])
def test_forged_or_missing_cas_closure_is_not_acknowledged(
    dispatch_case, monkeypatch, missing, corruption
):
    value, origin, _, prepared = dispatch_case
    reservation, outcome = commit(value, prepared, origin)
    document = parse(outcome)
    targets = {
        "outcome": digest(outcome),
        "intent": prepared.execution.intent.intent_id,
        "preparation": digest(prepared.execution.artifacts[0]),
        "result": document["bindings"]["replay_result_sha256"],
    }
    root = Path(origin.document["request"]["runs"])
    target = root / "objects" / "sha256" / targets[missing]
    if corruption == "missing":
        target.unlink()
    else:
        target.write_bytes(b"{}")
    before = tree(value.case.root)
    readonly(monkeypatch)
    with pytest.raises(ValueError):
        find_committed_dispatch(origin, (origin,))
    assert reservation.document["nonce"] == job_dispatch_nonce(origin)
    assert tree(value.case.root) == before


def test_unregistered_or_wrong_family_chain_is_refused_before_any_source_io(
    dispatch_case, monkeypatch
):
    _, origin, child, _ = dispatch_case
    skipped = build_followup_job_spec(origin, child.spec_id, "retry_from_origin_v1", "skipped")
    monkeypatch.setattr("tickwitness.infrastructure.job_followups.prepare_native_job", forbidden)
    with pytest.raises(JobStoreError, match="exact next retry"):
        find_committed_dispatch(origin, (origin, skipped))


def test_an_unrelated_committed_nonce_is_not_part_of_this_family(dispatch_case, monkeypatch):
    value, origin, child, prepared = dispatch_case
    commit(value, prepared, child)
    before = tree(value.case.root)
    readonly(monkeypatch)
    assert find_committed_dispatch(origin, (origin,)) is None
    assert tree(value.case.root) == before
