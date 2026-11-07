"""Greedy local reduction using original slots and immutable cooperative control.

The elapsed cap gates new candidates; it is not a hard wall deadline. A cancel
request waits for the current bounded run and assessment. Existing execution
journals are inspected, never resumed, repaired or refunded.
"""

import re
import secrets
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import partial
from typing import Protocol, cast

from tickwitness.application.experiments import ProtocolRunError
from tickwitness.application.reduction_execution import (
    ReductionLedger,
    _checked_prefix,
    _Preparation,
    _snapshot,
    _Source,
    inspect_reduction_run,
    run_reduction_input,
)
from tickwitness.application.reductions import PreparedReduction, prepare_reduction_input
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_evidence import SearchEvidencePackage, verify_search_package
from tickwitness.domain.evidence.reduction_preservation import ReductionPreservationAssessment
from tickwitness.domain.evidence.reduction_records import (
    build_reduction_intent,
    load_reduction_failure,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.reduction.campaign import (
    ReductionCampaignValidationError,
    ReductionDispatch,
    build_cancel,
    build_dispatch,
    build_link,
    build_stop,
    load_cancel,
    load_dispatch,
    load_link,
    load_stop,
)
from tickwitness.domain.reduction.contracts import build_reduction_manifest
from tickwitness.domain.reduction.search import (
    ReductionSearchPlan,
    build_reduction_search_plan,
    initial_point,
    load_reduction_search_plan,
    load_reduction_search_request,
    point_cost,
    reduction_neighbors,
    reduction_request,
)
from tickwitness.domain.replay.contracts import ReplayPort, load_replay_result
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    load_executable_protocol,
)
from tickwitness.domain.research_contracts.search_finding_protocol import (
    SearchFindingProtocol,
    load_search_finding_protocol,
)

type Row = dict[str, object]


class ReductionSearchPublicationError(RuntimeError):
    """A control publication cannot be confirmed; no retry or success is implied."""

    code = "reduction_search_publication_unconfirmed"
    exit_code = 3


class ReductionSearchLedger(ReductionLedger, Protocol):
    def reserve_with_nonce(
        self, protocol: ExecutableProtocol, nonce: str
    ) -> AttemptReservation: ...


class ReductionCampaignReader(Protocol):
    def get_campaign(self, plan_id: str) -> bytes | None: ...
    def get_dispatch(self, plan_id: str, ordinal: int) -> bytes | None: ...
    def get_link(self, plan_id: str, ordinal: int) -> bytes | None: ...
    def get_result(self, plan_id: str, ordinal: int) -> bytes | None: ...
    def get_stop(self, plan_id: str) -> bytes | None: ...
    def get_cancel(self, plan_id: str) -> bytes | None: ...
    def check_tree(self, plan_id: str) -> dict[str, tuple[int, ...]]: ...


class ReductionCampaignStore(ReductionCampaignReader, Protocol):
    def lock(self, plan_id: str) -> AbstractContextManager[object]: ...
    def start(self, plan_id: str, raw: bytes) -> None: ...
    def write_dispatch(self, plan_id: str, ordinal: int, raw: bytes) -> None: ...
    def write_link(self, plan_id: str, ordinal: int, raw: bytes) -> None: ...
    def write_result(self, plan_id: str, ordinal: int, raw: bytes) -> None: ...
    def write_stop(self, plan_id: str, raw: bytes) -> None: ...
    def write_cancel(self, plan_id: str, raw: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class _Context:
    source: _Source
    plan: ReductionSearchPlan
    full: PreparedReduction
    authority: SearchFindingProtocol

    @property
    def protocol(self) -> ExecutableProtocol:
        return self.full.materialization.source.validation.protocol


@dataclass(frozen=True, slots=True)
class _Traversal:
    report: Row
    best: Row
    cursor: int
    next_point: Row | None
    all_assessed: bool


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Reduction search permits development evidence only")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReductionCampaignValidationError(message)


def _publish(write: Callable[[], None], read: Callable[[], bytes | None], raw: bytes) -> None:
    try:
        write()
        _require(read() == raw, "Published reduction control differs from its requested bytes")
    except Exception as error:
        raise ReductionSearchPublicationError(
            "Reduction control publication is unconfirmed; inspect without resuming or refunding"
        ) from error


def _source_and_ledger(
    source: SearchEvidencePackage, ledger_factory: Callable[[], ReductionSearchLedger]
) -> tuple[_Source, ReductionSearchLedger]:
    snapshot = _snapshot(source)
    verify_search_package(snapshot, expected_bundle_id=identity(snapshot.bundle_id))
    authority = load_search_finding_protocol(snapshot.artifacts["finding_protocol"])
    protocol = load_executable_protocol(canonical(cast("Row", authority.plan.document["protocol"])))
    ledger = ledger_factory()
    _checked_prefix(snapshot, protocol, ledger)
    return snapshot, ledger


def _build(source: _Source, request_raw: bytes, bundle_id: str, report_id: str) -> _Context:
    request = load_reduction_search_request(request_raw)
    receipt = verify_search_package(source, expected_bundle_id=identity(bundle_id))
    _require(receipt["report_id"] == identity(report_id), "Original source report pin differs")
    authority = load_search_finding_protocol(source.artifacts["finding_protocol"])
    ordinal = cast("int", request["witness_ordinal"])
    proposals = cast("list[Row]", authority.plan.document["journal"])
    rows = [row for row in proposals if row["ordinal"] == ordinal]
    _require(len(rows) == 1, "Witness ordinal has no unique original proposal")
    lines = source.artifacts["normalized"].splitlines()
    _require(bool(lines), "Original normalized source is empty")
    last = parse(lines[-1], limit=8 * 1024 * 1024)
    full = prepare_reduction_input(
        source,
        canonical(
            {
                "kind": "reduction_request_v1",
                "schema_version": 1,
                "witness_ordinal": ordinal,
                "focus_from_capture_seq": request["focus_from_capture_seq"],
                "through_capture_seq": last["capture_seq"],
                "additional_delay_ns": rows[0]["delay_ns"],
            }
        ),
        expected_bundle_id=bundle_id,
        expected_report_id=report_id,
        split="development",
    )
    plan = build_reduction_search_plan(request_raw, materialization=full.materialization)
    return _Context(source, plan, full, authority)


def _context(
    plan_id: str, source: _Source, ledger: ReductionSearchLedger, store: ReductionCampaignReader
) -> _Context:
    raw = store.get_campaign(plan_id)
    _require(raw is not None, "Reduction search plan has not been frozen")
    plan = load_reduction_search_plan(cast("bytes", raw))
    _require(plan.plan_id == plan_id, "Stored reduction plan identity differs")
    document = plan.document
    bindings = cast("Row", document["source"])
    context = _build(
        source,
        canonical(cast("Row", document["request"])),
        cast("str", bindings["bundle_id"]),
        cast("str", bindings["report_id"]),
    )
    _require(context.plan.canonical_bytes == raw, "Plan does not reproduce from actual full source")
    _checked_prefix(source, context.protocol, ledger)
    return context


def _prepared(context: _Context, point: Row) -> PreparedReduction:
    bindings = cast("Row", context.plan.document["source"])
    return prepare_reduction_input(
        context.source,
        reduction_request(context.plan, point),
        expected_bundle_id=cast("str", bindings["bundle_id"]),
        expected_report_id=cast("str", bindings["report_id"]),
        split="development",
    )


def _package(prepared: PreparedReduction) -> _Preparation:
    return _Preparation(
        prepared.preparation_id,
        build_reduction_manifest(prepared.artifacts),
        tuple(sorted(prepared.artifacts.items())),
    )


def _assessment(
    context: _Context, prepared: PreparedReduction, run_id: str, ledger: ReductionSearchLedger
) -> ReductionPreservationAssessment:
    inspected = inspect_reduction_run(
        run_id, source=context.source, split="development", ledger_factory=lambda: ledger
    )
    receipt = load_reduction_run_receipt(ledger.read_artifact(run_id, max_bytes=16 * 1024))
    result_id = cast("str", cast("Row", receipt.document["bindings"])["replay_result_sha256"])
    result = load_replay_result(ledger.read_artifact(result_id))
    _require(
        cast("Row", inspected["preparation"])["preparation_id"] == prepared.preparation_id,
        "Actual run differs from the dispatched reduction preparation",
    )
    return ReductionPreservationAssessment(
        context.authority, prepared.materialization, receipt, result
    )


def freeze_reduction_search(
    source: SearchEvidencePackage,
    request_raw: bytes,
    *,
    expected_bundle_id: str,
    expected_report_id: str,
    split: str,
    ledger_factory: Callable[[], ReductionSearchLedger],
    store_factory: Callable[[], ReductionCampaignStore],
) -> Row:
    _development(split)
    load_reduction_search_request(request_raw)
    bundle_id, report_id = identity(expected_bundle_id), identity(expected_report_id)
    snapshot = _snapshot(source)
    context = _build(snapshot, request_raw, bundle_id, report_id)
    ledger = ledger_factory()
    _checked_prefix(snapshot, context.protocol, ledger)
    store = store_factory()
    plan = context.plan
    with store.lock(plan.plan_id):
        existing = store.get_campaign(plan.plan_id)
        if existing is None:
            _require(
                not any(store.check_tree(plan.plan_id).values())
                and store.get_stop(plan.plan_id) is None
                and store.get_cancel(plan.plan_id) is None,
                "Unfrozen reduction search contains orphaned records",
            )
            _publish(
                lambda: store.start(plan.plan_id, plan.canonical_bytes),
                lambda: store.get_campaign(plan.plan_id),
                plan.canonical_bytes,
            )
        else:
            _require(existing == plan.canonical_bytes, "Frozen reduction search already differs")
    return {
        "plan_id": plan.plan_id,
        "plan": plan.document,
        "status": "FROZEN",
        "existing_campaign": existing is not None,
        "attempt_reserved": False,
        "native_replayed": False,
        "reduced_predicate_evaluated": False,
        "witness_preservation_verified": False,
        "scope": plan.document["scope"],
    }


def _initial_best(plan: ReductionSearchPlan) -> Row:
    source = cast("Row", plan.document["source"])
    point = initial_point(plan)
    return {
        "origin": "SOURCE_WITNESS",
        "point": point,
        "cost": list(point_cost(plan, point)),
        "run_id": source["source_run_id"],
        "assessment_id": None,
    }


def _step(
    context: _Context,
    store: ReductionCampaignReader,
    ledger: ReductionSearchLedger,
    dispatch: ReductionDispatch,
    prepared: PreparedReduction,
    reservations: tuple[AttemptReservation, ...],
) -> Row:
    plan, document = context.plan, dispatch.document
    index = cast("int", document["index"])
    matches = [
        row for row in reservations if row.document["nonce"] == document["reservation_nonce"]
    ]
    _require(len(matches) <= 1, "Reduction dispatch nonce matches more than one original slot")
    link = store.get_link(plan.plan_id, index)
    saved = store.get_result(plan.plan_id, index)
    state: Row = {
        "index": index,
        "point": document["point"],
        "dispatch": document,
        "dispatch_id": dispatch.dispatch_id,
        "attempt_id": None,
        "attempt_index": None,
        "run_id": None,
        "assessment": None,
        "assessment_id": None,
        "execution_error": None,
        "execution_status": None,
        "status": "RESERVATION_UNCONFIRMED",
        "budget_consumed": None,
        "reservation_link_present": False,
    }
    if not matches:
        _require(link is None and saved is None, "Journal artifacts have no original reservation")
        return state
    reservation = matches[0]
    state.update(
        attempt_id=reservation.attempt_id,
        attempt_index=reservation.attempt_index,
        status="RESERVED_UNFINALIZED",
        budget_consumed=True,
    )
    if link is not None:
        _require(
            load_link(link, dispatch=dispatch, plan=plan) == reservation,
            "Reduction link differs from original nonce reservation",
        )
        state["reservation_link_present"] = True
    intent_raw = canonical(cast("Row", document["intent"]))
    intent = ledger.get_intent(reservation.attempt_id)
    _require(intent is None or intent == intent_raw, "Actual intent differs from dispatched intent")
    outcome = ledger.get_outcome(reservation.attempt_id)
    if outcome is None:
        _require(saved is None, "Assessment has no actual committed outcome")
        return state
    _require(
        link is not None and intent == intent_raw,
        "Committed outcome lacks exact pre-execution link and intent",
    )
    outcome_doc = parse(outcome)
    _require(
        canonical(cast("Row", outcome_doc["attempt"])) == reservation.canonical_bytes,
        "Committed outcome belongs to another original reservation",
    )
    if outcome_doc.get("kind") == "reduction_attempt_failure_v1":
        failure = load_reduction_failure(outcome)
        _require(
            canonical(cast("Row", failure["intent"])) == intent_raw,
            "Reduction failure changed its original execution intent",
        )
        _require(saved is None, "Failed execution cannot have a preservation assessment")
        state.update(status="FAILED", execution_error=failure["error"])
        return state
    _require(
        outcome_doc.get("kind") == "reduction_run_receipt_v1",
        "Reduction dispatch was finalized by another outcome kind",
    )
    run_id = digest(outcome)
    assessment = _assessment(context, prepared, run_id, ledger)
    state.update(
        run_id=run_id,
        execution_status=outcome_doc["execution_status"],
        status="ASSESSMENT_UNFINALIZED",
    )
    if saved is not None:
        _require(
            saved == assessment.canonical_bytes,
            "Saved preservation assessment differs from independent actual-result audit",
        )
        state.update(
            status="ASSESSED",
            assessment=assessment.document,
            assessment_id=assessment.assessment_id,
        )
    return state


def _traversal(
    context: _Context, store: ReductionCampaignReader, ledger: ReductionSearchLedger
) -> _Traversal:
    plan, plan_id = context.plan, context.plan.plan_id
    stop_raw = store.get_stop(plan_id)
    stop = load_stop(stop_raw, plan=plan) if stop_raw is not None else None
    cancel_raw = store.get_cancel(plan_id)
    cancellation = load_cancel(cancel_raw, plan=plan) if cancel_raw is not None else None
    inventory = store.check_tree(plan_id)
    dispatched = inventory["dispatches"]
    maximum = cast("int", cast("Row", plan.document["request"])["max_steps"])
    _require(
        dispatched == tuple(range(1, len(dispatched) + 1)) and len(dispatched) <= maximum,
        "Reduction dispatches are not a bounded contiguous prefix",
    )
    _require(
        set(inventory["links"]) <= set(dispatched) and set(inventory["results"]) <= set(dispatched),
        "Orphaned reduction journal records",
    )
    reservations = _checked_prefix(context.source, context.protocol, ledger)
    best, cursor = _initial_best(plan), 0
    steps: list[Row] = []
    used_nonces: set[str] = set()
    used_attempts: set[str] = set()
    all_assessed = True
    for index in dispatched:
        _require(all_assessed, "Reduction continued after an unfinalized or failed candidate")
        neighbors = reduction_neighbors(plan, cast("Row", best["point"]))
        _require(cursor < len(neighbors), "Reduction dispatched beyond its greedy neighborhood")
        raw = store.get_dispatch(plan_id, index)
        _require(raw is not None, "Dispatched reduction record disappeared")
        dispatch = load_dispatch(cast("bytes", raw), plan=plan)
        document, point = dispatch.document, neighbors[cursor]
        _require(
            document["index"] == index
            and document["point"] == point
            and document["parent_point"] == best["point"]
            and document["parent_run_id"] == best["run_id"]
            and document["neighbor_index"] == cursor,
            "Reduction journal differs from the exact frozen greedy traversal",
        )
        nonce = cast("str", document["reservation_nonce"])
        _require(nonce not in used_nonces, "Reduction dispatches reuse a reservation nonce")
        used_nonces.add(nonce)
        prepared = _prepared(context, point)
        intent = build_reduction_intent(prepared.materialization)
        _require(document["intent"] == intent.document, "Dispatch differs from actual source input")
        state = _step(context, store, ledger, dispatch, prepared, reservations)
        attempt_id = state["attempt_id"]
        if isinstance(attempt_id, str):
            _require(attempt_id not in used_attempts, "Reduction steps share one original attempt")
            used_attempts.add(attempt_id)
        assessment = cast("Row | None", state["assessment"])
        all_assessed = assessment is not None
        if assessment is not None:
            if assessment["outcome"] == "PRESERVED":
                _require(
                    point_cost(plan, point) < tuple(cast("list[int]", best["cost"])),
                    "Preservation does not strictly reduce the declared cost",
                )
                best = {
                    "origin": "REDUCTION_RUN",
                    "point": point,
                    "cost": list(point_cost(plan, point)),
                    "run_id": state["run_id"],
                    "assessment_id": state["assessment_id"],
                }
                cursor = 0
            else:
                cursor += 1
        steps.append(state)
    neighbors = reduction_neighbors(plan, cast("Row", best["point"]))
    next_point = neighbors[cursor] if cursor < len(neighbors) else None
    if stop is not None:
        _require(stop["steps"] == len(steps), "Terminal step count differs from actual dispatches")
        reason = stop["reason"]
        if reason in ("neighborhood_checked", "step_limit", "admission_deadline", "cancelled"):
            _require(all_assessed, "Intentional stop hides an unassessed or failed candidate")
            _require(
                stop["blocked_point"] == next_point,
                "Intentional stop differs from the next frozen candidate",
            )
            if reason == "neighborhood_checked":
                _require(next_point is None, "Neighborhood stop leaves a legal unchecked neighbor")
            elif reason == "step_limit":
                _require(
                    len(steps) == maximum and next_point is not None,
                    "Step stop lacks exhausted admissions or an actual next candidate",
                )
            elif reason == "cancelled":
                _require(
                    cancel_raw is not None and stop["cancel_id"] == digest(cancel_raw),
                    "Cancellation stop lacks its exact durable request",
                )
        elif reason == "original_attempt_budget_exhausted":
            _require(
                bool(steps) and steps[-1]["attempt_id"] is None,
                "Original-budget stop has an already consumed candidate slot",
            )
            _require(
                len(reservations) == cast("Row", plan.document["original_budget"])["max_attempts"],
                "Original-budget stop is not supported by the actual full ledger",
            )
            _require(
                stop["blocked_point"] == steps[-1]["point"], "Budget stop changed its candidate"
            )
            steps[-1].update(
                status="BUDGET_EXHAUSTED", budget_consumed=False, execution_error=stop["error"]
            )
        else:
            _require(stop["reason"] == "operational_failure", "Unknown reduction stop")
            _require(
                bool(steps) and not all_assessed,
                "Operational stop lacks an actual failed or unfinalized dispatch",
            )
            _require(
                stop["blocked_point"] == steps[-1]["point"],
                "Operational stop changed its actual dispatched candidate",
            )
            error = cast("Row", stop["error"])
            if steps and steps[-1]["execution_error"] is not None:
                actual = cast("Row", steps[-1]["execution_error"])
                _require(
                    actual["code"] == error["code"], "Stop differs from actual committed failure"
                )
            if steps and steps[-1]["execution_error"] is None and not all_assessed:
                steps[-1]["execution_error"] = error
    _require(store.check_tree(plan_id) == inventory, "Reduction journal changed during inspection")
    _require(
        store.get_campaign(plan_id) == plan.canonical_bytes,
        "Frozen reduction header changed during inspection",
    )
    if stop_raw is not None:
        _require(
            store.get_stop(plan_id) == stop_raw, "Reduction terminal changed during inspection"
        )
    status, reason, exit_code = "UNFINALIZED", "terminal_record_absent", 3
    if stop is None and not steps:
        status, reason, exit_code = "FROZEN", "not_started", 0
    elif stop is not None:
        reason = cast("str", stop["reason"])
        status = "COMPLETED" if reason == "neighborhood_checked" else "STOPPED"
        exit_code = cast("int", stop["exit_code"])

    def assessed_as(item: Row, outcome: str) -> bool:
        observed = item["assessment"]
        return isinstance(observed, dict) and observed.get("outcome") == outcome

    counts = {
        "dispatched": len(steps),
        "assessed": sum(item["assessment"] is not None for item in steps),
        "preserved": sum(assessed_as(item, "PRESERVED") for item in steps),
        "not_preserved": sum(assessed_as(item, "NOT_PRESERVED") for item in steps),
        "not_evaluable": sum(assessed_as(item, "NOT_EVALUABLE") for item in steps),
        "failed": sum(item["status"] == "FAILED" for item in steps),
        "unfinalized": sum(
            item["status"]
            in ("RESERVATION_UNCONFIRMED", "RESERVED_UNFINALIZED", "ASSESSMENT_UNFINALIZED")
            for item in steps
        ),
    }
    report: Row = {
        "kind": "reduction_search_report_v1",
        "schema_version": 1,
        "plan_id": plan_id,
        "plan": plan.document,
        "source": plan.document["source"],
        "steps": steps,
        "best": best,
        "stop": stop,
        "status": status,
        "stop_reason": reason,
        "exit_code": exit_code,
        "counts": counts,
        "cancellation": {"request": cancellation, "effective": reason == "cancelled"},
        "scope": plan.document["scope"],
        "verification": {
            "source_package_reaudited": True,
            "plan_recomputed": True,
            "observed_original_prefix_matched": True,
            "greedy_traversal_recomputed": True,
            "committed_outcomes_reaudited": True,
            "saved_assessments_recomputed": True,
            "native_replayed": False,
            "attempt_reserved": False,
            "source_claim_evaluated": False,
            "baseline_truth_evaluated": False,
            "original_predicate_domain_extended": False,
            "local_minimum_verified": False,
            "global_minimum_verified": False,
            "checkpoint_resume_verified": False,
            "global_ledger_authenticity_verified": False,
            "full_attempt_history_verified": False,
            "author_signature_verified": False,
            "monotonic_clock_authenticity_verified": False,
            "physical_storage_usage_verified": False,
            "hard_total_deadline_enforced": False,
            "total_storage_quota_enforced": False,
            "hard_cancel_enforced": False,
        },
    }
    return _Traversal(report, best, cursor, next_point, all_assessed)


def inspect_reduction_search(
    plan_id: str,
    *,
    source: SearchEvidencePackage,
    split: str,
    ledger_factory: Callable[[], ReductionSearchLedger],
    store_factory: Callable[[], ReductionCampaignReader],
) -> Row:
    _development(split)
    identity(plan_id)
    snapshot, ledger = _source_and_ledger(source, ledger_factory)
    store = store_factory()
    context = _context(plan_id, snapshot, ledger, store)
    return _traversal(context, store, ledger).report


def cancel_reduction_search(
    plan_id: str,
    *,
    source: SearchEvidencePackage,
    split: str,
    ledger_factory: Callable[[], ReductionSearchLedger],
    store_factory: Callable[[], ReductionCampaignStore],
) -> Row:
    _development(split)
    identity(plan_id)
    snapshot, ledger = _source_and_ledger(source, ledger_factory)
    store = store_factory()
    context = _context(plan_id, snapshot, ledger, store)
    stop_raw = store.get_stop(plan_id)
    stop = load_stop(stop_raw, plan=context.plan) if stop_raw is not None else None
    raw = store.get_cancel(plan_id)
    if raw is not None:
        load_cancel(raw, plan=context.plan)
    if stop is not None:
        _traversal(context, store, ledger)
    if stop is None and raw is None:
        raw = build_cancel(context.plan)
        _publish(
            partial(store.write_cancel, plan_id, raw),
            partial(store.get_cancel, plan_id),
            raw,
        )
    cancellation = load_cancel(raw, plan=context.plan) if raw is not None else None
    return {
        "plan_id": plan_id,
        "status": "ALREADY_TERMINAL" if stop is not None else "CANCEL_REQUESTED",
        "cancel_id": digest(raw) if raw is not None else None,
        "cancellation": cancellation,
        "stop": stop,
        "cooperative_between_candidates": True,
        "attempt_reserved": False,
        "native_replayed": False,
    }


class _DispatchLedger:
    def __init__(
        self,
        context: _Context,
        ledger: ReductionSearchLedger,
        store: ReductionCampaignStore,
        dispatch: ReductionDispatch,
        engine_factory: Callable[[int], ReplayPort],
    ) -> None:
        self.context, self.ledger, self.store, self.dispatch = context, ledger, store, dispatch
        self.engine_factory = engine_factory
        self.reservation: AttemptReservation | None = None

    def as_ledger(self) -> ReductionLedger:
        return self

    def reserve_with_nonce(self, protocol: ExecutableProtocol, nonce: str) -> AttemptReservation:
        _require(
            nonce == self.dispatch.document["reservation_nonce"],
            "Named reduction reservation differs from its frozen dispatch nonce",
        )
        return self.reserve(protocol)

    def reserve(self, protocol: ExecutableProtocol) -> AttemptReservation:
        _require(
            protocol.canonical_bytes == self.context.protocol.canonical_bytes,
            "Reduction dispatch changed the original budget owner",
        )
        _require(self.reservation is None, "A dispatched reduction cannot reserve twice")
        reservation = self.ledger.reserve_with_nonce(
            protocol, cast("str", self.dispatch.document["reservation_nonce"])
        )
        self.reservation = reservation
        raw = build_link(self.dispatch, reservation, plan=self.context.plan)
        index = cast("int", self.dispatch.document["index"])
        _publish(
            lambda: self.store.write_link(self.context.plan.plan_id, index, raw),
            lambda: self.store.get_link(self.context.plan.plan_id, index),
            raw,
        )
        return reservation

    def list_reservations(self, protocol: ExecutableProtocol) -> tuple[AttemptReservation, ...]:
        return self.ledger.list_reservations(protocol)

    def get_reservation(self, attempt_id: str) -> AttemptReservation:
        return self.ledger.get_reservation(attempt_id)

    def get_intent(self, attempt_id: str) -> bytes | None:
        return self.ledger.get_intent(attempt_id)

    def get_outcome(self, attempt_id: str) -> bytes | None:
        return self.ledger.get_outcome(attempt_id)

    def read_artifact(self, content_hash: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes:
        return self.ledger.read_artifact(content_hash, max_bytes=max_bytes)

    def bind_intent(
        self,
        reservation: AttemptReservation,
        intent_bytes: bytes,
        *,
        artifacts: tuple[bytes, ...] = (),
    ) -> str:
        _require(
            reservation == self.reservation
            and intent_bytes == canonical(cast("Row", self.dispatch.document["intent"])),
            "Reduction intent differs from the durable dispatched intent",
        )
        return self.ledger.bind_intent(reservation, intent_bytes, artifacts=artifacts)

    def publish(
        self,
        reservation: AttemptReservation,
        outcome: bytes,
        *,
        artifacts: tuple[bytes, ...] = (),
    ) -> str:
        _require(reservation == self.reservation, "Reduction outcome changed the linked attempt")
        return self.ledger.publish(reservation, outcome, artifacts=artifacts)

    def engine(self, timeout: int) -> ReplayPort:
        reservation = self.reservation
        index = cast("int", self.dispatch.document["index"])
        link = self.store.get_link(self.context.plan.plan_id, index)
        _require(
            reservation is not None and link is not None,
            "Native construction requires a committed original reservation link",
        )
        actual = cast("AttemptReservation", reservation)
        _require(
            load_link(cast("bytes", link), dispatch=self.dispatch, plan=self.context.plan) == actual
            and self.ledger.get_intent(actual.attempt_id)
            == canonical(cast("Row", self.dispatch.document["intent"]))
            and self.ledger.get_outcome(actual.attempt_id) is None,
            "Native construction requires exact durable link and intent without outcome",
        )
        return self.engine_factory(timeout)


def _error(error: Exception, *, default_code: str, default_exit: int) -> Row:
    raw_code = getattr(error, "code", default_code)
    code = (
        raw_code
        if isinstance(raw_code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", raw_code)
        else default_code
    )
    raw_exit = getattr(error, "exit_code", default_exit)
    exit_code = (
        raw_exit if type(raw_exit) is int and raw_exit in (2, 3, 4, 6, 7, 8) else default_exit
    )
    message = "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " "
        for character in (str(error) or type(error).__name__)
    )
    message = message.encode("utf-8", errors="backslashreplace")[:2048].decode(
        "utf-8", errors="ignore"
    )
    return {"code": code, "message": message or "Unknown execution error", "exit_code": exit_code}


def run_reduction_search(
    plan_id: str,
    *,
    source: SearchEvidencePackage,
    split: str,
    ledger_factory: Callable[[], ReductionSearchLedger],
    store_factory: Callable[[], ReductionCampaignStore],
    engine_factory: Callable[[int], ReplayPort],
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> Row:
    _development(split)
    identity(plan_id)
    snapshot, ledger = _source_and_ledger(source, ledger_factory)
    store = store_factory()
    context = _context(plan_id, snapshot, ledger, store)
    plan = context.plan
    request = cast("Row", plan.document["request"])
    maximum, cap = cast("int", request["max_steps"]), cast("int", request["max_wall_time_ms"])
    with store.lock(plan_id):
        state = _traversal(context, store, ledger)
        if any(store.check_tree(plan_id).values()) or state.report["stop"] is not None:
            return state.report
        started = monotonic_ns()
        _require(type(started) is int and 0 <= started < (1 << 63), "Invalid monotonic start value")
        previous = started

        def elapsed() -> int:
            nonlocal previous
            now = monotonic_ns()
            _require(type(now) is int and previous <= now < (1 << 63), "Regressing monotonic clock")
            previous = now
            return now - started

        def stop(reason: str, *, error: Row | None = None, cancel_id: str | None = None) -> Row:
            current = _traversal(context, store, ledger)
            steps = cast("list[Row]", current.report["steps"])
            blocked = current.next_point
            if reason == "original_attempt_budget_exhausted":
                blocked = cast("Row", steps[-1]["point"])
            raw = build_stop(
                plan,
                reason,
                steps=len(steps),
                elapsed_ns=elapsed(),
                blocked_point=blocked,
                error=error,
                cancel_id=cancel_id,
            )
            _publish(lambda: store.write_stop(plan_id, raw), lambda: store.get_stop(plan_id), raw)
            return _traversal(context, store, ledger).report

        while True:
            state = _traversal(context, store, ledger)
            point = state.next_point
            if point is None:
                return stop("neighborhood_checked")
            cancellation = store.get_cancel(plan_id)
            if cancellation is not None:
                load_cancel(cancellation, plan=plan)
                return stop("cancelled", cancel_id=digest(cancellation))
            index = len(cast("list[Row]", state.report["steps"])) + 1
            if index > maximum:
                return stop("step_limit")
            if elapsed() >= cap * 1_000_000:
                return stop("admission_deadline")
            prepared = _prepared(context, point)
            dispatch = build_dispatch(
                plan,
                index=index,
                point=point,
                parent_point=cast("Row", state.best["point"]),
                parent_run_id=cast("str", state.best["run_id"]),
                neighbor_index=state.cursor,
                nonce=secrets.token_hex(16),
                intent=build_reduction_intent(prepared.materialization),
            )
            # Materialization can be expensive. Recheck at the admission boundary
            # immediately before durable dispatch; the admitted attempt then
            # retains its original independent timeout without mid-run killing.
            cancellation = store.get_cancel(plan_id)
            if cancellation is not None:
                load_cancel(cancellation, plan=plan)
                return stop("cancelled", cancel_id=digest(cancellation))
            if elapsed() >= cap * 1_000_000:
                return stop("admission_deadline")
            _publish(
                partial(store.write_dispatch, plan_id, index, dispatch.canonical_bytes),
                partial(store.get_dispatch, plan_id, index),
                dispatch.canonical_bytes,
            )
            wrapper = _DispatchLedger(context, ledger, store, dispatch, engine_factory)
            try:
                submission = run_reduction_input(
                    _package(prepared),
                    context.source,
                    expected_preparation_id=prepared.preparation_id,
                    split="development",
                    ledger_factory=wrapper.as_ledger,
                    engine_factory=wrapper.engine,
                )
            except ReductionSearchPublicationError:
                raise
            except ProtocolRunError as error:
                return stop(
                    "operational_failure",
                    error=_error(error, default_code="reduction_execution_failed", default_exit=7),
                )
            except Exception as error:
                exhausted = getattr(error, "code", None) == "attempt_budget_exhausted"
                return stop(
                    "original_attempt_budget_exhausted" if exhausted else "operational_failure",
                    error=_error(
                        error,
                        default_code="reservation_unconfirmed",
                        default_exit=8 if exhausted else 3,
                    ),
                )
            assessment = _assessment(context, prepared, submission.run_id, ledger)
            _publish(
                partial(store.write_result, plan_id, index, assessment.canonical_bytes),
                partial(store.get_result, plan_id, index),
                assessment.canonical_bytes,
            )
