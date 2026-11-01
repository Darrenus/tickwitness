"""Bounded immutable reduction coordination records, separate from execution facts.

Canonical records bind one frozen plan to original reservation nonces. Their
publication order and historical clock authenticity require separate evidence;
the application must reconstruct the actual ledger and greedy traversal.
"""

import re
from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.reduction_records import (
    ReductionExecutionIntent,
    load_reduction_intent,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.reduction.search import (
    ReductionSearchPlan,
    load_reduction_search_plan,
    point_cost,
)

MAX_REDUCTION_CONTROL_BYTES = 64 * 1024
type Row = dict[str, object]
_DISPATCH_FIELDS = {
    "kind", "schema_version", "plan_id", "index", "point", "parent_point",
    "parent_run_id", "neighbor_index", "reservation_nonce", "intent",
}
_LINK_FIELDS = {"kind", "schema_version", "plan_id", "index", "dispatch_id", "reservation"}
_CANCEL_FIELDS = {"kind", "schema_version", "plan_id", "policy", "hard_kill_requested"}
_STOP_FIELDS = {
    "kind", "schema_version", "plan_id", "reason", "steps", "elapsed_ns",
    "blocked_point", "error", "cancel_id", "exit_code",
}
STOP_REASONS = frozenset({
    "neighborhood_checked", "step_limit", "admission_deadline", "cancelled",
    "original_attempt_budget_exhausted", "operational_failure",
})


class ReductionCampaignValidationError(EvidenceValidationError):
    """A saved coordination record disagrees with its declared immutable context."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReductionCampaignValidationError(message)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _integer(value: object, minimum: int, maximum: int, label: str) -> int:
    _require(type(value) is int and minimum <= value <= maximum, label + " is outside bounds")
    return cast("int", value)


def _checked(plan: ReductionSearchPlan) -> ReductionSearchPlan:
    _require(type(plan) is ReductionSearchPlan, "Expected actual frozen reduction plan")
    checked = load_reduction_search_plan(plan.canonical_bytes)
    _require(checked.plan_id == plan.plan_id, "Plan identity differs from canonical declarations")
    return checked


def _point(plan: ReductionSearchPlan, value: object) -> Row:
    point = _exact(value, {"through_capture_seq", "additional_delay_ns"}, "Reduction point")
    point_cost(plan, point)
    return point


def _read(raw: bytes, fields: set[str], kind: str, plan: ReductionSearchPlan) -> Row:
    value = _exact(parse(raw, limit=MAX_REDUCTION_CONTROL_BYTES), fields, "Control record")
    _require(
        value["kind"] == kind and type(value["schema_version"]) is int
        and value["schema_version"] == 1,
        "Unsupported reduction coordination markers",
    )
    _require(identity(value["plan_id"]) == _checked(plan).plan_id, "Record belongs to another plan")
    _require(canonical(value) == raw, "Reduction coordination record is not exact canonical bytes")
    return value


def _bounded(value: Row) -> bytes:
    raw = canonical(value)
    _require(len(raw) <= MAX_REDUCTION_CONTROL_BYTES, "Reduction control record exceeds byte bound")
    return raw


@dataclass(frozen=True, slots=True)
class ReductionDispatch:
    dispatch_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        value = _exact(
            parse(self.canonical_bytes, limit=MAX_REDUCTION_CONTROL_BYTES),
            _DISPATCH_FIELDS, "Reduction dispatch",
        )
        _require(
            value["kind"] == "reduction_search_dispatch_v1"
            and type(value["schema_version"]) is int and value["schema_version"] == 1,
            "Unsupported reduction dispatch markers",
        )
        _require(canonical(value) == self.canonical_bytes
                 and identity(self.dispatch_id) == digest(self.canonical_bytes),
                 "Dispatch identity differs from exact canonical bytes")

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_REDUCTION_CONTROL_BYTES)


def load_dispatch(raw: bytes, *, plan: ReductionSearchPlan) -> ReductionDispatch:
    plan = _checked(plan)
    value = _read(raw, _DISPATCH_FIELDS, "reduction_search_dispatch_v1", plan)
    maximum = cast("int", cast("Row", plan.document["request"])["max_steps"])
    _integer(value["index"], 1, maximum, "Dispatch index")
    _integer(value["neighbor_index"], 0, 1, "Neighbor index")
    _point(plan, value["point"])
    _point(plan, value["parent_point"])
    identity(value["parent_run_id"])
    _require(
        isinstance(value["reservation_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", value["reservation_nonce"]) is not None,
        "Dispatch nonce requires 32 lowercase hexadecimal characters",
    )
    intent = load_reduction_intent(canonical(cast("Row", value["intent"])))
    source = cast("Row", plan.document["source"])
    _require(
        intent.document["protocol_id"] == source["source_protocol_id"]
        and intent.document["claim_revision_id"] == source["source_claim_revision_id"],
        "Dispatch changed the original protocol or claim",
    )
    bindings = cast("Row", intent.document["bindings"])
    for key, source_key in (
        ("source_bundle_id", "bundle_id"), ("source_report_id", "report_id"),
        ("source_run_id", "source_run_id"), ("source_finding_protocol_id", "finding_protocol_id"),
        ("replay_spec_id", "replay_spec_id"),
    ):
        _require(bindings[key] == source[source_key], "Dispatch differs from original source")
    return ReductionDispatch(digest(raw), raw)


def build_dispatch(
    plan: ReductionSearchPlan, *, index: int, point: Row, parent_point: Row,
    parent_run_id: str, neighbor_index: int, nonce: str, intent: ReductionExecutionIntent,
) -> ReductionDispatch:
    _require(type(intent) is ReductionExecutionIntent, "Dispatch requires actual reduction intent")
    checked = load_reduction_intent(intent.canonical_bytes)
    _require(checked.intent_id == intent.intent_id, "Reduction intent identity differs")
    raw = _bounded({
        "kind": "reduction_search_dispatch_v1", "schema_version": 1,
        "plan_id": plan.plan_id, "index": index, "point": point,
        "parent_point": parent_point, "parent_run_id": parent_run_id,
        "neighbor_index": neighbor_index, "reservation_nonce": nonce, "intent": checked.document,
    })
    return load_dispatch(raw, plan=plan)


def build_link(
    dispatch: ReductionDispatch, reservation: AttemptReservation, *, plan: ReductionSearchPlan,
) -> bytes:
    checked = load_dispatch(dispatch.canonical_bytes, plan=plan)
    _require(checked.dispatch_id == dispatch.dispatch_id, "Dispatch identity differs")
    _require(type(reservation) is AttemptReservation, "Link requires actual original reservation")
    actual = AttemptReservation(digest(reservation.canonical_bytes), reservation.canonical_bytes)
    _require(actual.attempt_id == reservation.attempt_id, "Reservation identity differs")
    source = cast("Row", plan.document["source"])
    budget = cast("Row", plan.document["original_budget"])
    _require(
        actual.protocol_id == source["source_protocol_id"]
        and actual.document["nonce"] == checked.document["reservation_nonce"]
        and actual.document["max_wall_seconds"] == budget["max_wall_seconds"]
        and actual.attempt_index <= cast("int", budget["max_attempts"]),
        "Reservation differs from the dispatched original budget slot",
    )
    return _bounded({
        "kind": "reduction_search_attempt_link_v1", "schema_version": 1,
        "plan_id": plan.plan_id, "index": checked.document["index"],
        "dispatch_id": checked.dispatch_id, "reservation": actual.document,
    })


def load_link(
    raw: bytes, *, dispatch: ReductionDispatch, plan: ReductionSearchPlan,
) -> AttemptReservation:
    value = _read(raw, _LINK_FIELDS, "reduction_search_attempt_link_v1", plan)
    reservation_raw = canonical(cast("Row", value["reservation"]))
    reservation = AttemptReservation(digest(reservation_raw), reservation_raw)
    _require(build_link(dispatch, reservation, plan=plan) == raw, "Link differs from actual dispatch")
    return reservation


def build_cancel(plan: ReductionSearchPlan) -> bytes:
    return _bounded({
        "kind": "reduction_search_cancel_request_v1", "schema_version": 1,
        "plan_id": _checked(plan).plan_id,
        "policy": "between_candidates_after_current_bounded_attempt_v1",
        "hard_kill_requested": False,
    })


def load_cancel(raw: bytes, *, plan: ReductionSearchPlan) -> Row:
    value = _read(raw, _CANCEL_FIELDS, "reduction_search_cancel_request_v1", plan)
    _require(build_cancel(plan) == raw, "Cancellation policy or plan differs")
    return value


def _error(value: object) -> Row | None:
    if value is None:
        return None
    error = _exact(value, {"code", "message", "exit_code"}, "Operational error")
    _require(
        isinstance(error["code"], str)
        and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", error["code"]) is not None,
        "Error code is not a bounded machine code",
    )
    message = error["message"]
    _require(
        isinstance(message, str) and 0 < len(message) <= 4096
        and not any(ord(character) < 32 or ord(character) == 127 for character in message),
        "Error message must be bounded printable Unicode",
    )
    cast("str", message).encode("utf-8", errors="strict")
    _require(type(error["exit_code"]) is int and error["exit_code"] in (2, 3, 4, 6, 7, 8),
             "Operational exit code is not supported")
    return error


def build_stop(
    plan: ReductionSearchPlan, reason: str, *, steps: int, elapsed_ns: int,
    blocked_point: Row | None = None, error: Row | None = None, cancel_id: str | None = None,
) -> bytes:
    plan = _checked(plan)
    _require(reason in STOP_REASONS, "Unsupported reduction stop reason")
    maximum = cast("int", cast("Row", plan.document["request"])["max_steps"])
    _integer(steps, 0, maximum, "Stop step count")
    _integer(elapsed_ns, 0, (1 << 63) - 1, "Observed monotonic elapsed time")
    if blocked_point is not None:
        _point(plan, blocked_point)
    error = _error(error)
    if reason == "operational_failure":
        _require(error is not None, "Operational stop requires its observed error")
    elif reason == "original_attempt_budget_exhausted":
        _require(error is not None and error["code"] == "attempt_budget_exhausted",
                 "Budget stop requires original budget exhaustion")
    else:
        _require(error is None, "Intentional stop cannot fabricate execution failure")
    if reason == "neighborhood_checked":
        _require(blocked_point is None, "Checked neighborhood cannot name an unchecked point")
    elif reason != "cancelled":
        _require(blocked_point is not None, "Stop requires its actual blocked point")
    if reason == "cancelled":
        identity(cancel_id)
    else:
        _require(cancel_id is None, "Only effective cancellation binds a cancel request")
    if reason == "admission_deadline":
        limit = cast("int", cast("Row", plan.document["request"])["max_wall_time_ms"])
        _require(elapsed_ns >= limit * 1_000_000, "Admission stop precedes its elapsed cap")
    exit_code = (8 if reason == "original_attempt_budget_exhausted"
                 else cast("int", error["exit_code"]) if error is not None else 0)
    return _bounded({
        "kind": "reduction_search_stop_v1", "schema_version": 1, "plan_id": plan.plan_id,
        "reason": reason, "steps": steps, "elapsed_ns": elapsed_ns,
        "blocked_point": blocked_point, "error": error, "cancel_id": cancel_id,
        "exit_code": exit_code,
    })


def load_stop(raw: bytes, *, plan: ReductionSearchPlan) -> Row:
    value = _read(raw, _STOP_FIELDS, "reduction_search_stop_v1", plan)
    rebuilt = build_stop(
        plan, cast("str", value["reason"]), steps=cast("int", value["steps"]),
        elapsed_ns=cast("int", value["elapsed_ns"]),
        blocked_point=cast("Row | None", value["blocked_point"]),
        error=cast("Row | None", value["error"]), cancel_id=cast("str | None", value["cancel_id"]),
    )
    _require(rebuilt == raw, "Reduction stop differs from its immutable declarations")
    return value
