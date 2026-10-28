"""Portable memory reaudits from actual saved-fixture ledger records.

The fixture coordinator injects its clock; it is not a new native timing result.
Production export collection is tested separately from this fixed proof builder.
"""

import json
import shutil
import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_search_findings import ambiguous_engine, evaluate, execute, prepare

from tickwitness.application.search_evidence_verification import (
    _diagnostics,
    inspect_search_artifacts,
    verify_search_artifacts,
)
from tickwitness.application.experiments import run_experiment
from tickwitness.domain.evidence.run_records import canonical, digest, parse
from tickwitness.domain.evidence.search_evidence import SearchEvidenceValidationError, validate_snapshot
from tickwitness.domain.search.budgets import build_budget_stop, build_campaign_budget
from tickwitness.domain.search.execution import load_campaign, load_dispatch
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore, SearchCampaignNotFoundError
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry


def proof(case, plan_id, authority_id):
    """Capture real records with explicit expected closure, not saved audit flags."""
    authority = LocalSearchFindingRegistry(case.root / "findings").get(authority_id)
    pdoc = authority.plan.document
    artifacts = case.data.read_artifacts(pdoc["protocol"]["datasets"]["development"])
    artifacts["finding_protocol"] = authority.canonical_bytes
    budgets = LocalCampaignBudgetStore(case.root / "runs")
    artifacts["budget"] = budgets.get_budget(plan_id)
    allocations = []
    for raw in budgets.get_allocations(plan_id):
        ordinal = parse(raw)["ordinal"]
        allocations.append(ordinal)
        artifacts[f"allocation/{ordinal:04}"] = raw
    outer = budgets.get_stop(plan_id)
    if outer is not None:
        artifacts["outer_stop"] = outer
    campaigns = None
    header = None
    try:
        campaigns = LocalSearchCampaignStore(budgets.managed_root(plan_id))
        header = campaigns.get_campaign(plan_id)
    except SearchCampaignNotFoundError:
        pass
    reservations = []
    attempts = []
    candidates = []
    selected = set()
    cas = set()
    ledger = None
    original = ()
    campaign = None
    if header is not None:
        artifacts["campaign"] = header
        campaign = load_campaign(header)
        stop = campaigns.get_stop(plan_id)
        if stop is not None:
            artifacts["inner_stop"] = stop
        ledger = LocalAttemptLedger(case.root / "runs", create=False)
        protocol = load_executable_protocol(canonical(pdoc["protocol"]))
        original = ledger.list_reservations(protocol)
        for item in original:
            artifacts[f"reservation/{item.attempt_index:04}"] = item.canonical_bytes
            reservations.append({"index": item.attempt_index, "attempt_id": item.attempt_id})
            cas.add(item.attempt_id)
    for proposal in pdoc["journal"]:
        if proposal["status"] != "ELIGIBLE":
            continue
        ordinal = proposal["ordinal"]
        row = {"ordinal": ordinal, "dispatch": False, "link": False, "result": False}
        if header is not None:
            for field in ("dispatch", "link", "result"):
                raw = getattr(campaigns, "get_" + field)(plan_id, ordinal)
                row[field] = raw is not None
                if raw is not None:
                    artifacts[f"candidate/{ordinal:04}/{field}"] = raw
            if row["dispatch"]:
                dispatch = load_dispatch(artifacts[f"candidate/{ordinal:04}/dispatch"], campaign=campaign)
                for reservation in original:
                    if reservation.document["nonce"] == dispatch.document["reservation_nonce"]:
                        selected.add(reservation.attempt_id)
        candidates.append(row)
    for reservation in (() if ledger is None else original):
        attempt_id = reservation.attempt_id
        if attempt_id not in selected:
            continue
        intent, outcome = ledger.get_intent(attempt_id), ledger.get_outcome(attempt_id)
        attempts.append({"attempt_id": attempt_id, "intent": intent is not None, "outcome": outcome is not None})
        if intent is not None:
            artifacts[f"attempt/{attempt_id}/intent"] = intent
            cas.add(digest(intent))
            bindings = parse(intent)["bindings"]
            cas.update(bindings[name] for name in ("assumption_id", "scenario_id", "derived_view_id", "derived_normalized_sha256"))
        if outcome is not None:
            artifacts[f"attempt/{attempt_id}/outcome"] = outcome
            cas.add(digest(outcome))
            document = parse(outcome)
            if document["kind"] == "scenario_run_receipt_v1":
                cas.update(document["bindings"][name] for name in ("replay_result_sha256", "evaluation_sha256"))
    for sha in cas:
        artifacts["cas/" + sha] = ledger.read_artifact(sha)
    snapshot = {
        "kind": "search_evidence_snapshot_v1", "schema_version": 1,
        "finding_protocol_id": authority_id, "plan_id": plan_id, "protocol_id": pdoc["protocol_id"],
        "dataset_id": pdoc["protocol"]["datasets"]["development"],
        "budget_id": digest(artifacts["budget"]), "producer_version": "saved-fixture-proof-v1",
        "allocations": allocations, "outer_stop": outer is not None,
        "inner_campaign": header is not None, "inner_stop": "inner_stop" in artifacts,
        "ledger_prefix_observed": header is not None, "reservations": reservations,
        "candidates": candidates, "attempts": attempts, "cas": sorted(cas),
    }
    artifacts["snapshot"] = canonical(snapshot)
    finding = evaluate(case, authority_id)
    artifacts["finding_report"] = canonical(finding["report"])
    bounded, rebuilt, diagnostics = inspect_search_artifacts(artifacts)
    assert canonical(rebuilt["report"]) == artifacts["finding_report"]
    assert rebuilt["report_id"] == finding["report_id"]
    artifacts["diagnostics"] = canonical(diagnostics)
    return artifacts, bounded


@pytest.mark.parametrize("threshold,outcome", [("-3", "NO_COUNTEREXAMPLE_FOUND"), ("0", "COUNTEREXAMPLE_FOUND")])
def test_actual_closed_proof_survives_original_workspace_deletion_and_forbids_io(
    experiment_case, monkeypatch, threshold, outcome
):
    case = experiment_case
    plan_id, authority_id = prepare(case, threshold=threshold)
    run_experiment(case.frozen.protocol_id, split="development",
        registry_factory=lambda: case.registry, datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory, engine_factory=case.engine_factory)
    execute(case, plan_id)
    artifacts, _bounded = proof(case, plan_id, authority_id)
    expected = evaluate(case, authority_id)
    shutil.rmtree(case.root)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Portable verifier cannot access stores, SQLite, native or network")

    with monkeypatch.context() as guarded:
        guarded.setattr(LocalDatasetStore, "__init__", forbidden)
        guarded.setattr(LocalAttemptLedger, "__init__", forbidden)
        guarded.setattr(subprocess, "Popen", forbidden)
        guarded.setattr(socket, "socket", forbidden)
        guarded.setattr(sqlite3, "connect", forbidden)
        result = verify_search_artifacts(artifacts)
        repeated = verify_search_artifacts(artifacts)
    assert result == repeated
    assert result["report"] == expected["report"]
    assert result["report_id"] == expected["report_id"]
    assert result["report"]["outcome"] == outcome
    assert result["diagnostics"]["pairs"] == []
    assert result["finalization_status"] == "FINAL"
    assert result["verification"]["ledger_content_reconstructed"] is True
    assert [row["index"] for row in result["snapshot"]["reservations"]] == [1, 2]
    assert len(result["snapshot"]["attempts"]) == 1
    for key in ("native_replayed", "attempt_reserved", "original_publication_verified", "full_attempt_history_verified", "producer_version_authenticated"):
        assert result["verification"][key] is False


@pytest.mark.parametrize("mode,outcome", [("clean-time", "NO_COUNTEREXAMPLE_FOUND"), ("active-time", "NOT_EVALUABLE"), ("second-failure", "NOT_EVALUABLE")])
def test_budget_prefix_inflight_and_multiline_failure_keep_their_original_semantics(experiment_case, mode, outcome):
    case = experiment_case
    plan_id, authority_id = prepare(case, values=[0, 1])
    execute(case, plan_id, mode=mode)
    artifacts, _bounded = proof(case, plan_id, authority_id)
    result = verify_search_artifacts(artifacts)
    assert result["report"]["outcome"] == outcome
    assert result["report"]["planned_predicate_truth"] is None
    assert result["report"]["coverage"]["unevaluated_ordinals"] == [2]
    if mode == "second-failure":
        assert "\nwith detail\tretained" in result["report"]["candidate_assessments"][1]["error"]["message"]


def test_false_witness_remains_counterexample_when_later_failure_is_sealed(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case, threshold="0", values=[0, 1])
    execute(case, plan_id, mode="second-failure")
    artifacts, _bounded = proof(case, plan_id, authority_id)
    result = verify_search_artifacts(artifacts)
    assert result["report"]["outcome"] == "COUNTEREXAMPLE_FOUND"
    assert result["report"]["coverage"]["false_ordinals"] == [1]


def test_outer_only_deadline_never_invents_an_observed_empty_ledger(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    budget = build_campaign_budget(canonical({"kind": "campaign_budget_request_v1", "schema_version": 1,
        "max_evaluations": 2, "max_wall_time_ms": 1, "max_storage_bytes": 512 * 1024 * 1024}),
        plan_id=plan_id, protocol_id=case.frozen.protocol_id, nonce="e" * 32)
    budgets = LocalCampaignBudgetStore(case.root / "runs", create=True)
    budgets.start(plan_id, budget.canonical_bytes)
    budgets.write_stop(plan_id, build_budget_stop(budget, "time_limit", exit_code=8, elapsed_ns=1_000_000))
    artifacts, _bounded = proof(case, plan_id, authority_id)
    result = verify_search_artifacts(artifacts)
    assert result["report"]["outcome"] == "NOT_EVALUABLE"
    assert result["snapshot"]["ledger_prefix_observed"] is False
    assert result["snapshot"]["reservations"] == []
    assert result["verification"]["reservation_prefix_reconstructed"] is False
    assert result["verification"]["ledger_content_reconstructed"] is False
    assert not (case.root / "runs" / "slots").exists()


@pytest.mark.parametrize("attack", ["snapshot_bool", "missing_intent_cas", "omitted_reservation", "extra_role", "rehashed_finding", "rehashed_diagnostics", "raw_source"])
def test_role_presence_and_rehashed_outputs_cannot_replace_independent_reaudit(experiment_case, attack):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    execute(case, plan_id)
    artifacts, _bounded = proof(case, plan_id, authority_id)
    snapshot = parse(artifacts["snapshot"])
    if attack == "snapshot_bool":
        snapshot["outer_stop"] = 1
    elif attack == "missing_intent_cas":
        attempt_id = snapshot["attempts"][0]["attempt_id"]
        intent = artifacts[f"attempt/{attempt_id}/intent"]
        del artifacts["cas/" + digest(intent)]
    elif attack == "omitted_reservation":
        del artifacts["reservation/0001"]
    elif attack == "extra_role":
        artifacts["cas/" + "0" * 64] = b"unreferenced"
    elif attack == "rehashed_finding":
        report = parse(artifacts["finding_report"], limit=8 * 1024 * 1024)
        report["outcome"] = "COUNTEREXAMPLE_FOUND"
        artifacts["finding_report"] = canonical(report)
    elif attack == "rehashed_diagnostics":
        diagnostics = parse(artifacts["diagnostics"], limit=8 * 1024 * 1024)
        diagnostics["baseline_comparison_performed"] = True
        artifacts["diagnostics"] = canonical(diagnostics)
    else:
        artifacts["raw"] += b"\n"
    artifacts["snapshot"] = canonical(snapshot)
    with pytest.raises(SearchEvidenceValidationError):
        verify_search_artifacts(artifacts)


def test_diagnostics_select_adjacent_completed_candidates_without_baseline_or_causal_claims():
    # Declaration-level channel selection; full native paired proofs are covered
    # by the installed acceptance workflow, not this helper's synthetic mapping.
    result = json.loads((Path(__file__).parents[1] / "fixtures" / "evidence-result.json").read_bytes())
    raw = canonical(result)
    bounded = {"execution": {"candidates": [
        {"ordinal": 1, "status": "COMPLETED", "raw_result_audited": True, "run_id": "a" * 64},
        {"ordinal": 3, "status": "COMPLETED", "raw_result_audited": True, "run_id": "b" * 64},
        {"ordinal": 4, "status": "FAILED", "raw_result_audited": False, "run_id": None},
    ]}}
    diagnostics = _diagnostics(bounded, {"candidate/0001/result": raw, "candidate/0003/result": raw})
    assert diagnostics["baseline_comparison_performed"] is False
    assert diagnostics["causal_attribution_issued"] is False
    assert len(diagnostics["pairs"]) == 1
    assert diagnostics["pairs"][0]["left_ordinal"] == 1
    assert diagnostics["pairs"][0]["right_ordinal"] == 3
    assert diagnostics["pairs"][0]["comparison"]["semantically_equal"] is True


def test_explicit_missing_role_differs_from_a_sealed_absence(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    execute(case, plan_id)
    artifacts, _bounded = proof(case, plan_id, authority_id)
    validate_snapshot(artifacts)
    del artifacts["outer_stop"]
    with pytest.raises(SearchEvidenceValidationError, match="outer_stop"):
        validate_snapshot(artifacts)


def test_completed_fee_ambiguity_stays_not_evaluable_after_portable_reaudit(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case, ambiguous=True)
    execute(case, plan_id, engine_factory=ambiguous_engine)
    artifacts, _bounded = proof(case, plan_id, authority_id)
    result = verify_search_artifacts(artifacts)
    assert result["report"]["outcome"] == "NOT_EVALUABLE"
    assert result["report"]["coverage"]["audited_ordinals"] == [1]
    assert result["report"]["coverage"]["unknown_ordinals"] == [1]
    assert result["report"]["planned_predicate_truth"] is None
