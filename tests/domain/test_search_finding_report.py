"""Fixed declaration-level oracles; actual ledger audits belong to app tests."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import localcontext

import pytest
from test_search_finding_protocol import authority

from tickwitness.domain.evidence.run_records import canonical, digest, parse
from tickwitness.domain.evidence.search_finding_report import (
    SearchFindingReport,
    SearchFindingReportValidationError,
    build_search_finding_report,
    load_search_finding_report,
)
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    build_allocation,
    build_budget_stop,
    build_campaign_budget,
)
from tickwitness.domain.search.execution import build_campaign, build_stop


def reference(label):
    return digest(canonical({"fixture_reference": label}))


def campaign(
    protocol, *, values=None, states=None, admissions=None, reason="completed", terminal=True
):
    """Construct a self-consistent declaration, never claim a real source audit."""
    plan = protocol.plan
    eligible = [row for row in plan.document["journal"] if row["status"] == "ELIGIBLE"]
    values = ["1"] * len(eligible) if values is None else values
    states = ["COMPLETED"] * len(eligible) if states is None else states
    if admissions is None:
        admissions = sum(state != "NOT_DISPATCHED" for state in states)
    budget = build_campaign_budget(
        canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": max(1, admissions) if reason == "evaluation_limit" else 2,
                "max_wall_time_ms": 1000,
                "max_storage_bytes": CONTROL_RESERVE_BYTES
                + (admissions if reason == "storage_limit" else 2) * CANDIDATE_RESERVE_BYTES,
            }
        ),
        plan_id=plan.plan_id,
        protocol_id=plan.document["protocol_id"],
        nonce="a" * 32,
    )
    legacy = build_campaign(plan, "b" * 32)
    rows = []
    for index, (proposal, status, value) in enumerate(
        zip(eligible, states, values, strict=True), 1
    ):
        known = status in ("COMPLETED", "INCOMPLETE", "FAILED", "RESERVED_UNFINALIZED")
        audited = status in ("COMPLETED", "INCOMPLETE")
        outcome = reference(f"outcome-{index}") if audited or status == "FAILED" else None
        evaluation = None
        if audited:
            evaluation = {
                "kind": "scenario_evaluation_v1",
                "schema_version": 1,
                "protocol_id": plan.document["protocol_id"],
                "claim_revision_id": protocol.document["bindings"]["source_claim_revision_id"],
                "intent_id": reference(f"intent-{index}"),
                "scope": {
                    "phase": "development",
                    "scenario_kind": "COUNTERFACTUAL_STRESS",
                    "calibration_status": "uncalibrated",
                    "search_performed": False,
                    "baseline_claim_evaluated": False,
                },
                "metric_observation": {
                    "metric": "net_marked_pnl_v1",
                    "unit": "USD",
                    "eligible": value is not None,
                    "value": value,
                },
                "replay_evaluation": {"fixture_declaration_only": True},
            }
        rows.append(
            {
                "ordinal": proposal["ordinal"],
                "scenario_id": proposal["scenario_id"],
                "status": status,
                "attempt_id": reference(f"attempt-{index}") if known else None,
                "attempt_index": index if known else None,
                "outcome_id": outcome,
                "run_id": outcome if audited else None,
                "evaluation": evaluation,
                "budget_consumed": True
                if known
                else (None if status == "RESERVATION_UNCONFIRMED" else False),
                "reservation_link_present": known,
                "raw_result_sha256": reference(f"result-{index}") if audited else None,
                "raw_result_audited": audited,
                "error": {"code": "engine_failure", "message": "Fixture failure"}
                if status == "FAILED"
                else None,
            }
        )
    inner_stop = None
    inner_status, inner_reason, inner_code = "unfinalized", "terminal_record_absent", 3
    if all(status == "COMPLETED" for status in states):
        inner_status, inner_code = "completed", 0
        inner_reason = "planned_candidates_exhausted" if eligible else "no_eligible_candidates"
        inner_stop = parse(build_stop(legacy, inner_reason))
    else:
        target = next(
            (row for row in rows if row["status"] in ("FAILED", "INCOMPLETE", "BUDGET_EXHAUSTED")),
            None,
        )
        if target is not None:
            inner_reason = {
                "FAILED": "candidate_failed",
                "INCOMPLETE": "candidate_incomplete",
                "BUDGET_EXHAUSTED": "attempt_budget_exhausted",
            }[target["status"]]
            inner_status, inner_code = "stopped", 8 if target["status"] == "BUDGET_EXHAUSTED" else 7
            inner_stop = parse(
                build_stop(
                    legacy,
                    inner_reason,
                    ordinal=target["ordinal"],
                    error_code="engine_failure" if target["status"] == "FAILED" else None,
                )
            )
    scope = {
        "phase": "development",
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "calibration_status": "uncalibrated",
        "claim_evaluated": False,
        "finding_issued": False,
        "full_trial_history_certified": False,
    }
    inner = {
        "kind": "search_campaign_report_v1",
        "schema_version": 1,
        "campaign_id": legacy.campaign_id,
        "plan_id": plan.plan_id,
        "protocol_id": plan.document["protocol_id"],
        "status": inner_status,
        "stop_reason": inner_reason,
        "exit_code": inner_code,
        "counts": {
            "eligible": len(rows),
            "dispatched": sum(row["status"] != "NOT_DISPATCHED" for row in rows),
            "reserved": sum(row["attempt_id"] is not None for row in rows),
            "completed": sum(row["status"] == "COMPLETED" for row in rows),
            "failed": sum(row["status"] == "FAILED" for row in rows),
            "incomplete": sum(row["status"] == "INCOMPLETE" for row in rows),
            "unfinalized": sum(
                row["status"] in ("RESERVED_UNFINALIZED", "RESERVATION_UNCONFIRMED") for row in rows
            ),
        },
        "candidates": rows,
        "proposal_journal": plan.document["journal"],
        "stop": inner_stop,
        "scope": dict(scope),
        "verification": {
            "plan_recomputed": True,
            "source_revalidated": True,
            "attempt_links_verified": all(
                row["status"] in ("NOT_DISPATCHED", "BUDGET_EXHAUSTED")
                or row["reservation_link_present"] is True
                for row in rows
            ),
            "outcomes_reaudited": True,
            "native_replayed": False,
            "author_signature_verified": False,
        },
    }
    exit_code = (
        0
        if reason == "completed"
        else (
            inner_code if reason == "execution_stopped" else 7 if reason == "worker_failed" else 8
        )
    )
    elapsed = 1_000_000_000 if reason == "time_limit" else 1
    outer_stop = (
        parse(build_budget_stop(budget, reason, exit_code=exit_code, elapsed_ns=elapsed))
        if terminal
        else None
    )
    return {
        "kind": "bounded_search_campaign_report_v1",
        "schema_version": 1,
        "plan_id": plan.plan_id,
        "protocol_id": plan.document["protocol_id"],
        "budget_id": budget.budget_id,
        "budget": budget.document,
        "status": ("completed" if reason == "completed" else "stopped")
        if terminal
        else "unfinalized",
        "stop_reason": reason if terminal else "terminal_record_absent",
        "exit_code": exit_code if terminal else 3,
        "allocations": [
            parse(build_allocation(budget, row["ordinal"], index))
            for index, row in enumerate(eligible[:admissions], 1)
        ],
        "execution": inner,
        "stop": outer_stop,
        "proposal_journal": plan.document["journal"],
        "resources": {
            "admitted_evaluations": admissions,
            "reserved_storage_bytes": CONTROL_RESERVE_BYTES + admissions * CANDIDATE_RESERVE_BYTES,
            "max_storage_bytes": budget.document["limits"]["max_storage_bytes"],
            "elapsed_ns": elapsed if terminal else None,
            "storage_policy": "managed_new_file_payloads_v1",
            "wall_time_scope": "coordinator_execution_phase_v1",
        },
        "scope": scope,
        "verification": {
            "plan_recomputed": True,
            "source_revalidated": True,
            "budget_bindings_verified": True,
            "quota_reservations_verified": True,
            "execution_reaudited": True,
            "native_replayed": False,
            "runtime_limits_reenforced": False,
            "author_signature_verified": False,
            "physical_storage_usage_verified": False,
        },
    }


@pytest.mark.parametrize(
    ("values", "outcome", "truth", "witnesses"),
    [
        (["-1", "-2"], "COUNTEREXAMPLE_FOUND", False, [1, 2]),
        (["1", "-2"], "COUNTEREXAMPLE_FOUND", False, [2]),
        (["-1", "2"], "COUNTEREXAMPLE_FOUND", False, [1]),
        (["1", "2"], "NO_COUNTEREXAMPLE_FOUND", True, [1, 2]),
    ],
)
def test_fixed_truth_table_and_distinct_full_predicate_target(values, outcome, truth, witnesses):
    protocol = authority()
    source = campaign(protocol, values=values)
    report = build_search_finding_report(protocol, campaign=source)
    doc = report.document
    assert doc["outcome"] == outcome and doc["finding_issued"] is True
    assert doc["planned_predicate_truth"] is truth
    assert [row["ordinal"] for row in doc["witnesses"]] == witnesses
    assert doc["coverage"]["coverage_complete_for_plan"] is True
    assert doc["source_snapshot_sha256"] == digest(canonical(source))
    assert doc["audit"]["state"] == "UNASSERTED"
    assert doc["audit"]["source_ledger_reaudit_asserted"] is False
    assert doc["scope"]["source_claim_evaluated"] is False
    assert doc["predicate_id"] != doc["source_claim_revision_id"]


@pytest.mark.parametrize(
    ("comparator", "values", "truths"),
    [
        ("gt", ["0", "0.000000000000000001"], [False, True]),
        ("ge", ["0", "-0.000000000000000001"], [True, False]),
        ("lt", ["0", "-0.000000000000000001"], [False, True]),
        ("le", ["0", "0.000000000000000001"], [True, False]),
    ],
)
def test_decimal_comparators_preserve_equality_and_small_values_under_host_context(
    comparator, values, truths
):
    protocol = authority(comparator=comparator)
    with localcontext() as arithmetic:
        arithmetic.prec = 1
        report = build_search_finding_report(protocol, campaign=campaign(protocol, values=values))
    assert [row["truth"] for row in report.document["candidate_assessments"]] == truths


@pytest.mark.parametrize("reason", ["evaluation_limit", "storage_limit", "time_limit"])
def test_clean_budget_prefix_no_counterexample_is_not_full_set_truth(reason):
    protocol = authority(values=[0, 0, 1, 20_000_001])
    source = campaign(
        protocol,
        values=["1", None],
        states=["COMPLETED", "NOT_DISPATCHED"],
        admissions=1,
        reason=reason,
    )
    doc = build_search_finding_report(protocol, campaign=source).document
    assert doc["outcome"] == "NO_COUNTEREXAMPLE_FOUND"
    assert doc["conclusion_target"] == "no_false_witness_in_exact_audited_subset_v1"
    assert doc["planned_predicate_truth"] is None
    assert doc["coverage"]["eligible_ordinals"] == [1, 3]
    assert doc["coverage"]["audited_ordinals"] == [1]
    assert doc["coverage"]["unevaluated_ordinals"] == [3]
    assert doc["coverage"]["proposal_counts"] == {
        "proposed": 4,
        "eligible": 2,
        "duplicate": 1,
        "rejected": 1,
    }
    assert doc["coverage"]["coverage_complete_for_plan"] is False
    assert doc["coverage"]["continuous_delay_space_exhausted"] is False
    assert doc["budget"]["original_protocol_limits"] == protocol.plan.document["protocol"]["budget"]
    scope = doc["scope"]
    for key in (
        "finding_protocol_id",
        "plan_id",
        "source_protocol_id",
        "source_claim_revision_id",
        "predicate_id",
    ):
        assert scope[key] == doc[key]
    assert scope["campaign_budget_id"] == doc["budget"]["campaign_budget_id"]
    eligible = [row for row in protocol.plan.document["journal"] if row["status"] == "ELIGIBLE"]
    pairs = [{"ordinal": row["ordinal"], "scenario_id": row["scenario_id"]} for row in eligible]
    assert scope["eligible_candidates"] == pairs
    assert scope["evaluated_candidates"] == pairs[:1]


def test_original_budget_exhaustion_can_close_only_the_previously_audited_subset():
    protocol = authority()
    source = campaign(
        protocol,
        values=["1", None],
        states=["COMPLETED", "BUDGET_EXHAUSTED"],
        reason="execution_stopped",
    )
    doc = build_search_finding_report(protocol, campaign=source).document
    assert doc["outcome"] == "NO_COUNTEREXAMPLE_FOUND"
    assert doc["planned_predicate_truth"] is None
    assert doc["candidate_assessments"][1]["budget_consumed"] is False
    assert doc["execution"]["inner_stop_reason"] == "attempt_budget_exhausted"
    assert "remaining_attempts" not in doc["budget"]


@pytest.mark.parametrize(
    "state",
    ["FAILED", "INCOMPLETE", "RESERVED_UNFINALIZED", "RESERVATION_UNCONFIRMED", "NOT_DISPATCHED"],
)
def test_failed_unknown_or_admitted_but_undispatched_suffix_never_becomes_no_counterexample(state):
    protocol = authority()
    source = campaign(
        protocol, values=["1", None], states=["COMPLETED", state], admissions=2, reason="time_limit"
    )
    doc = build_search_finding_report(protocol, campaign=source).document
    assert doc["outcome"] == "NOT_EVALUABLE"
    assert doc["finding_issued"] is False and doc["planned_predicate_truth"] is None
    assert doc["witnesses"] == []


def test_false_committed_witness_survives_later_failure_without_renaming_search_success():
    protocol = authority()
    source = campaign(
        protocol, values=["-1", None], states=["COMPLETED", "FAILED"], reason="worker_failed"
    )
    before = deepcopy(source)
    doc = build_search_finding_report(protocol, campaign=source).document
    assert doc["outcome"] == "COUNTEREXAMPLE_FOUND"
    assert [row["ordinal"] for row in doc["witnesses"]] == [1]
    assert doc["execution"]["outer_status"] == "stopped"
    assert doc["execution"]["outer_exit_code"] == 7
    assert doc["candidate_assessments"][1]["status"] == "FAILED"
    assert source == before


def test_no_outer_terminal_suppresses_issuance_even_with_a_false_witness():
    protocol = authority()
    doc = build_search_finding_report(
        protocol, campaign=campaign(protocol, values=["-1", "2"], terminal=False)
    ).document
    assert doc["outcome"] == "NOT_EVALUABLE"
    assert "outer_terminal_absent" in doc["reasons"]
    assert doc["planned_predicate_truth"] is None


def test_unknown_valuation_and_empty_eligible_set_are_not_vacuous_success():
    protocol = authority()
    doc = build_search_finding_report(
        protocol, campaign=campaign(protocol, values=[None, "2"])
    ).document
    assert doc["outcome"] == "NOT_EVALUABLE"
    assert doc["coverage"]["unknown_ordinals"] == [1]
    empty = authority(values=[20_000_001])
    doc = build_search_finding_report(empty, campaign=campaign(empty)).document
    assert doc["outcome"] == "NOT_EVALUABLE"
    assert doc["coverage"]["coverage_complete_for_plan"] is False


def test_timeout_before_inner_header_does_not_invent_an_execution_or_empty_success():
    protocol = authority()
    source = campaign(
        protocol,
        values=[None, None],
        states=["NOT_DISPATCHED", "NOT_DISPATCHED"],
        admissions=0,
        reason="time_limit",
    )
    source["execution"] = None
    source["verification"]["execution_reaudited"] = False
    doc = build_search_finding_report(protocol, campaign=source).document
    assert doc["outcome"] == "NOT_EVALUABLE"
    assert doc["execution"]["inner_campaign_id"] is None
    assert doc["coverage"]["audited_ordinals"] == []
    assert doc["coverage"]["unevaluated_ordinals"] == [1, 2]


@pytest.mark.parametrize("value", [True, 1, "NaN", "Infinity", "1e-3", " 1", "1" * 257])
def test_invalid_eligible_metric_is_a_validation_error_instead_of_unknown(value):
    protocol = authority()
    source = campaign(protocol)
    source["execution"]["candidates"][0]["evaluation"]["metric_observation"]["value"] = value
    with pytest.raises(SearchFindingReportValidationError):
        build_search_finding_report(protocol, campaign=source)


@pytest.mark.parametrize(
    "attack",
    [
        "outcome",
        "coverage",
        "witness",
        "planned_truth",
        "scope",
        "audit",
        "predicate",
        "snapshot",
        "budget",
        "metric_bool",
        "scope_budget",
        "scope_candidate_pair",
    ],
)
def test_rehashed_report_cannot_change_derived_conclusion_or_upgrade_evidence(attack):
    protocol = authority()
    source = campaign(
        protocol,
        values=["1", None],
        states=["COMPLETED", "NOT_DISPATCHED"],
        admissions=1,
        reason="evaluation_limit",
    )
    doc = build_search_finding_report(protocol, campaign=source).document
    if attack == "outcome":
        doc["outcome"] = "COUNTEREXAMPLE_FOUND"
    elif attack == "coverage":
        doc["coverage"]["coverage_complete_for_plan"] = True
    elif attack == "witness":
        doc["witnesses"][0]["truth"] = False
    elif attack == "planned_truth":
        doc["planned_predicate_truth"] = True
    elif attack == "scope":
        doc["scope"]["source_claim_evaluated"] = True
    elif attack == "audit":
        doc["audit"]["state"] = "LOCAL_REAUDITED"
    elif attack == "predicate":
        doc["predicate_id"] = doc["source_claim_revision_id"]
    elif attack == "snapshot":
        doc["source_snapshot_sha256"] = "not-a-hash"
    elif attack == "budget":
        doc["budget"]["original_protocol_limits"]["max_attempts"] += 1
    elif attack == "scope_budget":
        doc["scope"]["campaign_budget_id"] = doc["source_protocol_id"]
    elif attack == "scope_candidate_pair":
        doc["scope"]["evaluated_candidates"][0]["scenario_id"] = doc["scope"][
            "eligible_candidates"
        ][1]["scenario_id"]
    else:
        doc["candidate_assessments"][0]["metric_observation"]["eligible"] = 1
    with pytest.raises(SearchFindingReportValidationError):
        SearchFindingReport(canonical(doc))


def test_report_roundtrip_is_immutable_and_does_not_represent_portable_verification():
    protocol = authority()
    report = build_search_finding_report(protocol, campaign=campaign(protocol))
    assert load_search_finding_report(report.canonical_bytes) == report
    assert report.report_id == digest(report.canonical_bytes)
    doc = report.document
    doc["candidate_assessments"][0]["truth"] = False
    assert report.document["candidate_assessments"][0]["truth"] is True
    with pytest.raises(FrozenInstanceError):
        report.canonical_bytes = b"{}"
    assert report.document["audit"]["source_ledger_reaudit_asserted"] is False


def test_bad_campaign_identity_counts_or_legacy_scope_are_validation_errors():
    protocol = authority()
    for mutation in ("identity", "counts", "scope"):
        source = campaign(protocol)
        if mutation == "identity":
            source["protocol_id"] = "a" * 64
        elif mutation == "counts":
            source["execution"]["counts"]["completed"] = 0
        else:
            source["scope"]["finding_issued"] = True
        with pytest.raises(SearchFindingReportValidationError):
            build_search_finding_report(protocol, campaign=source)


def test_inner_inspection_declarations_must_match_the_actual_candidate_projection():
    protocol = authority()
    source = campaign(protocol)
    source["execution"]["verification"]["attempt_links_verified"] = False
    with pytest.raises(SearchFindingReportValidationError, match="Inner inspection declarations"):
        build_search_finding_report(protocol, campaign=source)
