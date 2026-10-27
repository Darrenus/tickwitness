"""Scoped conclusions from compact declarations of a locally audited campaign.

The application must supply its real source/ledger reinspection. Standalone
loading checks only this report's declarations and never authenticates that
inspection, physical limits, an author or a portable evidence closure.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.research_contracts.search_finding_protocol import (
    FINDING_LIMITATIONS,
    FINDING_REPORT_POLICY,
    FINDING_SCOPE,
    SearchFindingProtocol,
    load_search_finding_protocol,
)
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    load_allocation,
    load_budget_stop,
    load_campaign_budget,
)

MAX_SEARCH_FINDING_REPORT_BYTES = 8 * 1024 * 1024
MAX_SOURCE_CAMPAIGN_BYTES = 32 * 1024 * 1024
type Row = dict[str, object]
_CANDIDATE_FIELDS = {
    "ordinal",
    "scenario_id",
    "status",
    "attempt_id",
    "attempt_index",
    "outcome_id",
    "run_id",
    "intent_id",
    "evaluation_sha256",
    "raw_result_sha256",
    "budget_consumed",
    "reservation_link_present",
    "raw_result_audited",
    "metric_observation",
    "truth",
    "error",
}
_BUDGET_FIELDS = {
    "original_protocol_limits",
    "campaign_budget_id",
    "campaign_budget",
    "allocations",
    "resources",
}
_EXECUTION_FIELDS = {
    "outer_status",
    "outer_stop_reason",
    "outer_exit_code",
    "outer_stop",
    "inner_campaign_id",
    "inner_status",
    "inner_stop_reason",
    "inner_exit_code",
    "inner_stop",
}
_REPORT_FIELDS = {
    "kind",
    "schema_version",
    "report_policy",
    "finding_protocol",
    "finding_protocol_id",
    "plan_id",
    "source_protocol_id",
    "source_claim_revision_id",
    "predicate_id",
    "source_snapshot_sha256",
    "scope",
    "audit",
    "proposal_journal",
    "candidate_assessments",
    "budget",
    "execution",
    "outcome",
    "finding_issued",
    "reasons",
    "witnesses",
    "coverage",
    "limitations",
    "conclusion_target",
    "planned_predicate_truth",
}
_STATES = {
    "COMPLETED",
    "INCOMPLETE",
    "FAILED",
    "RESERVED_UNFINALIZED",
    "RESERVATION_UNCONFIRMED",
    "BUDGET_EXHAUSTED",
    "NOT_DISPATCHED",
}


class SearchFindingReportValidationError(EvidenceValidationError):
    """A finding declaration, criterion or campaign projection is inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SearchFindingReportValidationError(message)


def _exact(value: object, keys: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == keys, label + " fields differ")
    return cast("Row", value)


def _equal(left: object, right: object, message: str) -> None:
    _require(canonical({"v": left}) == canonical({"v": right}), message)


def _integer(value: object, low: int, high: int, label: str) -> int:
    _require(type(value) is int and low <= value <= high, label + " is outside its integer bound")
    return cast("int", value)


def _text(value: object, maximum: int, label: str) -> str:
    _require(isinstance(value, str) and 0 < len(value) <= maximum, label + " must be bounded text")
    value = cast("str", value)
    _require(
        not any(ord(char) < 32 or ord(char) == 127 for char in value), label + " contains controls"
    )
    return value


def _checked(authority: SearchFindingProtocol) -> SearchFindingProtocol:
    _require(
        type(authority) is SearchFindingProtocol, "Findings require an actual frozen authority"
    )
    checked = load_search_finding_protocol(authority.canonical_bytes)
    _require(checked.protocol_id == authority.protocol_id, "Finding authority identity differs")
    return checked


def _truth(metric: object, *, status: str, authority: SearchFindingProtocol) -> bool | None:
    if metric is None:
        _require(status not in ("COMPLETED", "INCOMPLETE"), "Audited candidate lacks its metric")
        return None
    observation = _exact(metric, {"metric", "unit", "eligible", "value"}, "Metric observation")
    _require(status in ("COMPLETED", "INCOMPLETE"), "Non-audited candidate has a metric")
    _require(
        observation["metric"] == "net_marked_pnl_v1" and observation["unit"] == "USD",
        "Metric profile differs",
    )
    _require(type(observation["eligible"]) is bool, "Metric eligibility must be boolean")
    if observation["eligible"] is False:
        _require(observation["value"] is None, "Ineligible metric cannot contain a value")
        return None
    value = observation["value"]
    _require(
        isinstance(value, str)
        and len(value) <= 256
        and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is not None,
        "Eligible metric must be bounded plain decimal text",
    )
    if status != "COMPLETED":
        return None
    predicate = cast("Row", authority.document["predicate"])
    criterion = cast("Row", predicate["criterion"])
    actual, threshold = Decimal(cast("str", value)), Decimal(cast("str", criterion["threshold"]))
    return {
        "gt": actual > threshold,
        "ge": actual >= threshold,
        "lt": actual < threshold,
        "le": actual <= threshold,
    }[cast("str", criterion["comparator"])]


def _candidate(value: object, *, expected: Row, authority: SearchFindingProtocol) -> Row:
    row = _exact(value, _CANDIDATE_FIELDS, "Candidate assessment")
    _equal(row["ordinal"], expected["ordinal"], "Candidate ordinal differs from the plan")
    _equal(row["scenario_id"], expected["scenario_id"], "Candidate scenario differs from the plan")
    status = row["status"]
    _require(isinstance(status, str) and status in _STATES, "Unsupported candidate status")
    status = cast("str", status)
    for name in ("reservation_link_present", "raw_result_audited"):
        _require(type(row[name]) is bool, "Candidate audit flags must be boolean")
    _require(
        row["budget_consumed"] is None or type(row["budget_consumed"]) is bool,
        "Candidate consumption must be boolean or unknown",
    )
    id_fields = (
        "attempt_id",
        "outcome_id",
        "run_id",
        "intent_id",
        "evaluation_sha256",
        "raw_result_sha256",
    )
    for name in id_fields:
        if row[name] is not None:
            identity(row[name])
    known_attempt = status in ("COMPLETED", "INCOMPLETE", "FAILED", "RESERVED_UNFINALIZED")
    if known_attempt:
        identity(row["attempt_id"])
        limits = cast("Row", cast("Row", authority.plan.document["protocol"])["budget"])
        _integer(row["attempt_index"], 1, cast("int", limits["max_attempts"]), "attempt index")
        _require(row["budget_consumed"] is True, "Known attempt must remain consumed")
    else:
        _require(
            all(row[name] is None for name in id_fields) and row["attempt_index"] is None,
            "Unreserved candidate has execution identities",
        )
        _require(
            row["reservation_link_present"] is False and row["raw_result_audited"] is False,
            "Unreserved candidate has audit flags",
        )
        _require(
            row["budget_consumed"] is (None if status == "RESERVATION_UNCONFIRMED" else False),
            "Unreserved consumption differs",
        )
    if status in ("COMPLETED", "INCOMPLETE"):
        _require(
            all(row[name] is not None for name in id_fields),
            "Audited result lacks evidence references",
        )
        _require(
            row["run_id"] == row["outcome_id"]
            and row["reservation_link_present"] is True
            and row["raw_result_audited"] is True,
            "Audited result lacks its committed run/link",
        )
    elif status == "FAILED":
        identity(row["outcome_id"])
        _require(
            row["run_id"] is None
            and row["raw_result_audited"] is False
            and row["reservation_link_present"] is True,
            "Failure cannot be an audited successful run",
        )
    else:
        _require(
            row["run_id"] is None
            and row["outcome_id"] is None
            and row["raw_result_audited"] is False,
            "Unfinalized candidate contains a finalized result",
        )
    if status == "FAILED":
        error = _exact(row["error"], {"code", "message"}, "Candidate error")
        # The committed scenario-failure contract permits multiline diagnostics.
        # Preserve those exact bounded strings; JSON encoding escapes controls.
        for name, maximum in (("code", 128), ("message", 4096)):
            detail = error[name]
            _require(
                isinstance(detail, str) and 0 < len(detail) <= maximum,
                "Candidate failure " + name + " is empty or oversized",
            )
    else:
        _require(row["error"] is None, "Nonfailed candidate contains failure data")
    _equal(
        row["truth"],
        _truth(row["metric_observation"], status=status, authority=authority),
        "Candidate truth differs from its exact metric",
    )
    return row


def _basis(
    authority: SearchFindingProtocol,
    budget_value: object,
    execution_value: object,
    candidates_value: object,
) -> tuple[Row, Row, list[Row]]:
    plan = authority.plan
    pdoc = plan.document
    source = cast("Row", pdoc["protocol"])
    budget = _exact(budget_value, _BUDGET_FIELDS, "Finding budget")
    _equal(budget["original_protocol_limits"], source["budget"], "Original protocol budget differs")
    frozen = load_campaign_budget(canonical(cast("Row", budget["campaign_budget"])))
    _require(
        frozen.budget_id == budget["campaign_budget_id"]
        and frozen.document["plan_id"] == plan.plan_id
        and frozen.document["protocol_id"] == pdoc["protocol_id"],
        "Campaign budget differs from the authority",
    )
    journal = cast("list[Row]", pdoc["journal"])
    eligible = [row for row in journal if row["status"] == "ELIGIBLE"]
    _require(
        isinstance(candidates_value, list) and len(candidates_value) == len(eligible),
        "Candidate assessments must cover the complete eligible list",
    )
    candidates = [
        _candidate(row, expected=expected, authority=authority)
        for row, expected in zip(cast("list[object]", candidates_value), eligible, strict=True)
    ]
    raw_allocations = budget["allocations"]
    _require(
        isinstance(raw_allocations, list) and len(raw_allocations) <= len(eligible),
        "Invalid admission list",
    )
    allocations = [
        load_allocation(canonical(cast("Row", item)), budget=frozen)
        for item in cast("list[object]", raw_allocations)
    ]
    for index, row in enumerate(allocations):
        _equal(row["index"], index + 1, "Admissions are not a contiguous prefix")
        _equal(row["ordinal"], eligible[index]["ordinal"], "Admissions differ from eligible prefix")
    admitted = {row["ordinal"] for row in allocations}
    encountered_noncomplete = False
    seen_attempts: set[str] = set()
    last_index = 0
    for row in candidates:
        if row["status"] != "NOT_DISPATCHED":
            _require(
                row["ordinal"] in admitted and not encountered_noncomplete,
                "Dispatch lacks admission or follows a noncompleted candidate",
            )
        if row["status"] != "COMPLETED":
            encountered_noncomplete = True
        attempt = row["attempt_id"]
        if isinstance(attempt, str):
            _require(
                attempt not in seen_attempts and cast("int", row["attempt_index"]) > last_index,
                "Candidate attempts are reused or out of order",
            )
            seen_attempts.add(attempt)
            last_index = cast("int", row["attempt_index"])
    execution = _exact(execution_value, _EXECUTION_FIELDS, "Finding execution")
    resources = _exact(
        budget["resources"],
        {
            "admitted_evaluations",
            "reserved_storage_bytes",
            "max_storage_bytes",
            "elapsed_ns",
            "storage_policy",
            "wall_time_scope",
        },
        "Resource summary",
    )
    limits = cast("Row", frozen.document["limits"])
    _equal(resources["admitted_evaluations"], len(allocations), "Admission summary differs")
    _equal(
        resources["reserved_storage_bytes"],
        CONTROL_RESERVE_BYTES + len(allocations) * CANDIDATE_RESERVE_BYTES,
        "Storage reservation summary differs",
    )
    _equal(resources["max_storage_bytes"], limits["max_storage_bytes"], "Storage capacity differs")
    _equal(resources["storage_policy"], "managed_new_file_payloads_v1", "Storage unit differs")
    _equal(
        resources["wall_time_scope"], "coordinator_execution_phase_v1", "Wall-time scope differs"
    )
    stop_value = execution["outer_stop"]
    if stop_value is None:
        _require(
            execution["outer_status"] == "unfinalized"
            and execution["outer_stop_reason"] == "terminal_record_absent"
            and execution["outer_exit_code"] == 3
            and resources["elapsed_ns"] is None,
            "Missing outer terminal was reported as finalized",
        )
    else:
        stop = load_budget_stop(canonical(cast("Row", stop_value)), budget=frozen)
        _equal(execution["outer_stop_reason"], stop["reason"], "Outer stop reason differs")
        _equal(execution["outer_exit_code"], stop["exit_code"], "Outer stop exit differs")
        _equal(resources["elapsed_ns"], stop["elapsed_ns"], "Elapsed time differs from stop")
        _equal(
            execution["outer_status"],
            "completed" if stop["reason"] == "completed" else "stopped",
            "Outer completion status differs",
        )
        if stop["reason"] == "completed":
            _require(
                execution["inner_status"] == "completed"
                and len(allocations) == len(eligible)
                and all(row["status"] == "COMPLETED" for row in candidates)
                and cast("int", stop["elapsed_ns"])
                < cast("int", limits["max_wall_time_ms"]) * 1_000_000,
                "Completed stop lacks complete in-deadline evidence",
            )
        if stop["reason"] == "time_limit":
            _require(
                cast("int", stop["elapsed_ns"])
                >= cast("int", limits["max_wall_time_ms"]) * 1_000_000,
                "Time stop precedes its deadline",
            )
        if stop["reason"] == "evaluation_limit":
            _require(
                len(allocations) == limits["max_evaluations"] and len(allocations) < len(eligible),
                "Evaluation limit lacks exhausted admissions",
            )
        if stop["reason"] == "execution_stopped":
            _require(
                execution["inner_status"] in ("stopped", "unfinalized")
                and execution["inner_exit_code"] == stop["exit_code"],
                "Execution stop differs from inner facts",
            )
    if execution["inner_campaign_id"] is None:
        _require(
            all(
                execution[name] is None
                for name in ("inner_status", "inner_stop_reason", "inner_exit_code", "inner_stop")
            )
            and not allocations
            and all(row["status"] == "NOT_DISPATCHED" for row in candidates),
            "Missing inner campaign contains execution evidence",
        )
    else:
        identity(execution["inner_campaign_id"])
        _require(
            execution["inner_status"] in ("completed", "stopped", "unfinalized"),
            "Unknown inner status",
        )
        _integer(execution["inner_exit_code"], 0, 255, "inner exit code")
        _text(execution["inner_stop_reason"], 128, "inner stop reason")
        inner_stop = execution["inner_stop"]
        if inner_stop is None:
            _require(
                execution["inner_status"] == "unfinalized"
                and execution["inner_stop_reason"] == "terminal_record_absent"
                and execution["inner_exit_code"] == 3,
                "Missing inner terminal was reported as finalized",
            )
        else:
            inner_stop = _exact(
                inner_stop,
                {
                    "kind",
                    "schema_version",
                    "campaign_id",
                    "plan_id",
                    "protocol_id",
                    "reason",
                    "ordinal",
                    "error_code",
                    "message",
                },
                "Inner stop",
            )
            _equal(inner_stop["kind"], "search_campaign_stop_v1", "Inner stop kind differs")
            _equal(inner_stop["schema_version"], 1, "Inner stop version differs")
            _equal(
                inner_stop["campaign_id"],
                execution["inner_campaign_id"],
                "Inner stop campaign differs",
            )
            _equal(inner_stop["plan_id"], plan.plan_id, "Inner stop plan differs")
            _equal(inner_stop["protocol_id"], pdoc["protocol_id"], "Inner stop owner differs")
            _equal(
                inner_stop["reason"], execution["inner_stop_reason"], "Inner stop reason differs"
            )
            if inner_stop["ordinal"] is not None:
                _require(
                    type(inner_stop["ordinal"]) is int
                    and inner_stop["ordinal"] in {row["ordinal"] for row in candidates},
                    "Inner stop ordinal differs from the candidate set",
                )
            for name, maximum in (("error_code", 128), ("message", 4096)):
                if inner_stop[name] is not None:
                    _text(inner_stop[name], maximum, "inner stop " + name)
            if execution["inner_status"] == "completed":
                _require(
                    inner_stop["reason"]
                    in ("planned_candidates_exhausted", "no_eligible_candidates")
                    and execution["inner_exit_code"] == 0
                    and all(row["status"] == "COMPLETED" for row in candidates),
                    "Inner completion lacks completed candidates",
                )
            else:
                _require(
                    execution["inner_status"] == "stopped"
                    and inner_stop["reason"]
                    in (
                        "attempt_budget_exhausted",
                        "candidate_failed",
                        "candidate_incomplete",
                        "reservation_unconfirmed",
                        "publication_unconfirmed",
                    ),
                    "Unknown terminal inner stop",
                )
                if inner_stop["reason"] == "attempt_budget_exhausted":
                    target = next(
                        (row for row in candidates if row["ordinal"] == inner_stop["ordinal"]), None
                    )
                    _require(
                        target is not None
                        and target["status"] == "BUDGET_EXHAUSTED"
                        and execution["inner_exit_code"] == 8,
                        "Original budget stop lacks its unreserved candidate",
                    )
    return budget, execution, candidates


def _document(
    authority: SearchFindingProtocol,
    *,
    budget_value: object,
    execution_value: object,
    candidates_value: object,
    snapshot: object,
) -> Row:
    authority = _checked(authority)
    budget, execution, candidates = _basis(
        authority, budget_value, execution_value, candidates_value
    )
    snapshot_id = identity(snapshot)
    plan = authority.plan.document
    true_rows = [row for row in candidates if row["truth"] is True]
    false_rows = [row for row in candidates if row["truth"] is False]
    audited = [
        row
        for row in candidates
        if row["status"] == "COMPLETED" and row["raw_result_audited"] is True
    ]
    evaluated = [row for row in candidates if type(row["truth"]) is bool]
    unknown = [
        row
        for row in candidates
        if row["status"] in ("COMPLETED", "INCOMPLETE") and row["truth"] is None
    ]
    admitted = {row["ordinal"] for row in cast("list[Row]", budget["allocations"])}
    admitted_rows = [row for row in candidates if row["ordinal"] in admitted]
    terminal = execution["outer_stop"] is not None
    original_stop = (
        execution["outer_stop_reason"] == "execution_stopped"
        and execution["inner_stop_reason"] == "attempt_budget_exhausted"
    )
    clean_stop = (
        execution["outer_stop_reason"]
        in ("completed", "evaluation_limit", "storage_limit", "time_limit")
        or original_stop
    )
    clean_admissions = all(
        row["status"] == "COMPLETED"
        or (
            original_stop
            and row["status"] == "BUDGET_EXHAUSTED"
            and row["budget_consumed"] is False
        )
        for row in admitted_rows
    )
    reasons: list[str] = []
    if not terminal:
        reasons.append("outer_terminal_absent")
    if not evaluated:
        reasons.append("no_evaluable_completed_candidate")
    if unknown:
        reasons.append("candidate_metric_unknown_or_execution_incomplete")
    if not clean_stop:
        reasons.append("campaign_did_not_end_with_completion_or_clean_budget_stop")
    if not clean_admissions:
        reasons.append("admitted_candidate_is_failed_unfinalized_or_undispatched")
    if terminal and false_rows:
        outcome, witnesses, reasons = (
            "COUNTEREXAMPLE_FOUND",
            false_rows,
            ["audited_false_conditional_witness"],
        )
    elif terminal and true_rows and not unknown and clean_stop and clean_admissions:
        outcome, witnesses, reasons = (
            "NO_COUNTEREXAMPLE_FOUND",
            true_rows,
            ["no_false_witness_in_nonempty_clean_audited_subset"],
        )
    else:
        outcome, witnesses = "NOT_EVALUABLE", []
    complete_for_plan = bool(candidates) and len(evaluated) == len(candidates)
    conclusion_target = {
        "COUNTEREXAMPLE_FOUND": "frozen_eligible_candidate_robustness_v1",
        "NO_COUNTEREXAMPLE_FOUND": "no_false_witness_in_exact_audited_subset_v1",
        "NOT_EVALUABLE": "conditional_stress_search_not_evaluable_v1",
    }[outcome]
    planned_truth = (
        False
        if outcome == "COUNTEREXAMPLE_FOUND"
        else (True if outcome == "NO_COUNTEREXAMPLE_FOUND" and complete_for_plan else None)
    )
    bindings = cast("Row", authority.document["bindings"])
    return {
        "kind": "search_finding_report_v1",
        "schema_version": 1,
        "report_policy": FINDING_REPORT_POLICY,
        "finding_protocol": authority.document,
        "finding_protocol_id": authority.protocol_id,
        "plan_id": authority.plan.plan_id,
        "source_protocol_id": bindings["source_protocol_id"],
        "source_claim_revision_id": bindings["source_claim_revision_id"],
        "predicate_id": authority.document["predicate_id"],
        "source_snapshot_sha256": snapshot_id,
        "scope": {
            **FINDING_SCOPE,
            "finding_protocol_id": authority.protocol_id,
            "plan_id": authority.plan.plan_id,
            "source_protocol_id": bindings["source_protocol_id"],
            "source_claim_revision_id": bindings["source_claim_revision_id"],
            "predicate_id": authority.document["predicate_id"],
            "campaign_budget_id": budget["campaign_budget_id"],
            "eligible_candidates": [
                {"ordinal": row["ordinal"], "scenario_id": row["scenario_id"]} for row in candidates
            ],
            "evaluated_candidates": [
                {"ordinal": row["ordinal"], "scenario_id": row["scenario_id"]} for row in evaluated
            ],
        },
        "audit": {
            "state": "UNASSERTED",
            "source_ledger_reaudit_asserted": False,
            "source_snapshot_identity_only": True,
        },
        "proposal_journal": plan["journal"],
        "candidate_assessments": candidates,
        "budget": budget,
        "execution": execution,
        "outcome": outcome,
        "finding_issued": outcome != "NOT_EVALUABLE",
        "reasons": reasons,
        "conclusion_target": conclusion_target,
        "planned_predicate_truth": planned_truth,
        "witnesses": witnesses,
        "coverage": {
            "eligible_ordinals": [row["ordinal"] for row in candidates],
            "audited_ordinals": [row["ordinal"] for row in audited],
            "unevaluated_ordinals": [row["ordinal"] for row in candidates if row["truth"] is None],
            "true_ordinals": [row["ordinal"] for row in true_rows],
            "false_ordinals": [row["ordinal"] for row in false_rows],
            "unknown_ordinals": [row["ordinal"] for row in unknown],
            "coverage_complete_for_plan": complete_for_plan,
            "continuous_delay_space_exhausted": False,
            "proposal_counts": plan["counts"],
            "generation_stop": plan["generation_stop"],
        },
        "limitations": list(FINDING_LIMITATIONS),
    }


@dataclass(frozen=True, slots=True)
class SearchFindingReport:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            doc = _exact(
                parse(self.canonical_bytes, limit=MAX_SEARCH_FINDING_REPORT_BYTES),
                _REPORT_FIELDS,
                "Search finding report",
            )
            authority = load_search_finding_protocol(
                canonical(cast("Row", doc["finding_protocol"]))
            )
            rebuilt = _document(
                authority,
                budget_value=doc["budget"],
                execution_value=doc["execution"],
                candidates_value=doc["candidate_assessments"],
                snapshot=doc["source_snapshot_sha256"],
            )
            _require(
                canonical(rebuilt) == self.canonical_bytes,
                "Finding outcome, coverage, scope, predicate or bindings differ",
            )
        except (ValueError, KeyError, TypeError) as error:
            raise SearchFindingReportValidationError(str(error)) from error

    @property
    def report_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_SEARCH_FINDING_REPORT_BYTES)


def load_search_finding_report(raw: bytes) -> SearchFindingReport:
    return SearchFindingReport(raw)


def build_search_finding_report(
    authority: SearchFindingProtocol, *, campaign: Row
) -> SearchFindingReport:
    try:
        authority = _checked(authority)
        snapshot = canonical(campaign)
        source = _exact(
            parse(snapshot, limit=MAX_SOURCE_CAMPAIGN_BYTES),
            {
                "kind",
                "schema_version",
                "plan_id",
                "protocol_id",
                "budget_id",
                "budget",
                "status",
                "stop_reason",
                "exit_code",
                "allocations",
                "execution",
                "stop",
                "proposal_journal",
                "resources",
                "scope",
                "verification",
            },
            "Bounded campaign report",
        )
        _require(
            source.get("kind") == "bounded_search_campaign_report_v1"
            and type(source.get("schema_version")) is int
            and source["schema_version"] == 1,
            "Finding requires the actual bounded campaign profile",
        )
        _equal(
            source["plan_id"],
            authority.plan.plan_id,
            "Campaign differs from the frozen finding plan",
        )
        _equal(
            source["protocol_id"],
            authority.plan.document["protocol_id"],
            "Campaign budget owner differs",
        )
        _equal(
            source["proposal_journal"],
            authority.plan.document["journal"],
            "Campaign proposal journal differs",
        )
        _equal(
            source["scope"],
            {
                "phase": "development",
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "calibration_status": "uncalibrated",
                "claim_evaluated": False,
                "finding_issued": False,
                "full_trial_history_certified": False,
            },
            "Legacy campaign scope differs",
        )
        inner = source["execution"]
        candidates: list[Row] = []
        rows = [
            row
            for row in cast("list[Row]", authority.plan.document["journal"])
            if row["status"] == "ELIGIBLE"
        ]
        if inner is None:
            originals = [
                {
                    "ordinal": row["ordinal"],
                    "scenario_id": row["scenario_id"],
                    "status": "NOT_DISPATCHED",
                    "attempt_id": None,
                    "attempt_index": None,
                    "outcome_id": None,
                    "run_id": None,
                    "evaluation": None,
                    "budget_consumed": False,
                    "reservation_link_present": False,
                    "raw_result_sha256": None,
                    "error": None,
                    "raw_result_audited": False,
                }
                for row in rows
            ]
        else:
            _require(isinstance(inner, dict), "Inner campaign must be an object")
            inner = cast("Row", inner)
            _exact(
                inner,
                {
                    "kind",
                    "schema_version",
                    "campaign_id",
                    "plan_id",
                    "protocol_id",
                    "status",
                    "stop_reason",
                    "exit_code",
                    "counts",
                    "candidates",
                    "proposal_journal",
                    "stop",
                    "scope",
                    "verification",
                },
                "Inner campaign report",
            )
            _require(
                inner.get("kind") == "search_campaign_report_v1"
                and type(inner.get("schema_version")) is int
                and inner["schema_version"] == 1,
                "Inner campaign profile differs",
            )
            _equal(inner["plan_id"], source["plan_id"], "Inner plan differs")
            _equal(inner["protocol_id"], source["protocol_id"], "Inner protocol differs")
            _equal(inner["proposal_journal"], source["proposal_journal"], "Inner journal differs")
            _equal(inner["scope"], source["scope"], "Inner legacy scope differs")
            _require(isinstance(inner["candidates"], list), "Inner candidate list is missing")
            originals = cast("list[Row]", inner["candidates"])
        for original in originals:
            _exact(
                original,
                (
                    _CANDIDATE_FIELDS
                    - {"intent_id", "evaluation_sha256", "metric_observation", "truth"}
                )
                | {"evaluation"},
                "Inner candidate",
            )
            evaluation = original["evaluation"]
            row = {
                key: original[key]
                for key in _CANDIDATE_FIELDS
                - {"intent_id", "evaluation_sha256", "metric_observation", "truth"}
            }
            if evaluation is None:
                row.update(
                    intent_id=None, evaluation_sha256=None, metric_observation=None, truth=None
                )
            else:
                _require(isinstance(evaluation, dict), "Evaluation must be an audited object")
                evaluation = cast("Row", evaluation)
                _exact(
                    evaluation,
                    {
                        "kind",
                        "schema_version",
                        "protocol_id",
                        "claim_revision_id",
                        "intent_id",
                        "scope",
                        "metric_observation",
                        "replay_evaluation",
                    },
                    "Scenario evaluation",
                )
                _require(
                    evaluation.get("kind") == "scenario_evaluation_v1"
                    and type(evaluation.get("schema_version")) is int
                    and evaluation["schema_version"] == 1,
                    "Evaluation profile differs",
                )
                _equal(evaluation["protocol_id"], source["protocol_id"], "Evaluation owner differs")
                _equal(
                    evaluation["claim_revision_id"],
                    cast("Row", authority.document["bindings"])["source_claim_revision_id"],
                    "Evaluation source criterion differs",
                )
                _equal(
                    evaluation["scope"],
                    {
                        "phase": "development",
                        "scenario_kind": "COUNTERFACTUAL_STRESS",
                        "calibration_status": "uncalibrated",
                        "search_performed": False,
                        "baseline_claim_evaluated": False,
                    },
                    "Scenario evaluation scope differs",
                )
                metric = evaluation["metric_observation"]
                row.update(
                    intent_id=evaluation["intent_id"],
                    evaluation_sha256=digest(canonical(evaluation)),
                    metric_observation=metric,
                    truth=_truth(metric, status=cast("str", row["status"]), authority=authority),
                )
            candidates.append(row)
        _equal(
            source["verification"],
            {
                "plan_recomputed": True,
                "source_revalidated": True,
                "budget_bindings_verified": True,
                "quota_reservations_verified": True,
                "execution_reaudited": inner is not None,
                "native_replayed": False,
                "runtime_limits_reenforced": False,
                "author_signature_verified": False,
                "physical_storage_usage_verified": False,
            },
            "Bounded inspection declarations differ",
        )
        if inner is not None:
            _equal(
                inner["counts"],
                {
                    "eligible": len(candidates),
                    "dispatched": sum(row["status"] != "NOT_DISPATCHED" for row in candidates),
                    "reserved": sum(row["attempt_id"] is not None for row in candidates),
                    "completed": sum(row["status"] == "COMPLETED" for row in candidates),
                    "failed": sum(row["status"] == "FAILED" for row in candidates),
                    "incomplete": sum(row["status"] == "INCOMPLETE" for row in candidates),
                    "unfinalized": sum(
                        row["status"] in ("RESERVED_UNFINALIZED", "RESERVATION_UNCONFIRMED")
                        for row in candidates
                    ),
                },
                "Inner counts differ from actual candidate declarations",
            )
            _equal(
                inner["verification"],
                {
                    "plan_recomputed": True,
                    "source_revalidated": True,
                    "attempt_links_verified": all(
                        row["status"] in ("NOT_DISPATCHED", "BUDGET_EXHAUSTED")
                        or row["reservation_link_present"] is True
                        for row in candidates
                    ),
                    "outcomes_reaudited": True,
                    "native_replayed": False,
                    "author_signature_verified": False,
                },
                "Inner inspection declarations differ",
            )
        budget_value: Row = {
            "original_protocol_limits": cast("Row", authority.plan.document["protocol"])["budget"],
            "campaign_budget_id": source["budget_id"],
            "campaign_budget": source["budget"],
            "allocations": source["allocations"],
            "resources": source["resources"],
        }
        execution_value: Row = {
            "outer_status": source["status"],
            "outer_stop_reason": source["stop_reason"],
            "outer_exit_code": source["exit_code"],
            "outer_stop": source["stop"],
            "inner_campaign_id": None if inner is None else inner["campaign_id"],
            "inner_status": None if inner is None else inner["status"],
            "inner_stop_reason": None if inner is None else inner["stop_reason"],
            "inner_exit_code": None if inner is None else inner["exit_code"],
            "inner_stop": None if inner is None else inner["stop"],
        }
        encoded = canonical(
            _document(
                authority,
                budget_value=budget_value,
                execution_value=execution_value,
                candidates_value=candidates,
                snapshot=digest(snapshot),
            )
        )
        return SearchFindingReport(encoded)
    except (ValueError, KeyError, TypeError) as error:
        raise SearchFindingReportValidationError(str(error)) from error
