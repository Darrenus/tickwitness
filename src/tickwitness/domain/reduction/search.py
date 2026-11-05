"""Finite local reduction policy bound to one original false source witness.

Plans authorize no new execution budget. They fix a review focus and two
strictly decreasing operators; the application rederives them from complete
source evidence before executing or inspecting their durable journal.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType
from typing import cast

from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse
from tickwitness.domain.reduction.contracts import (
    MaterializedReduction,
    ReductionValidationError,
    materialize_reduction,
)
from tickwitness.domain.replay._validation import INT64_MAX, integer
from tickwitness.domain.replay._validation import parse as parse_request

MAX_REDUCTION_SEARCH_PLAN_BYTES = 4 * 1024 * 1024
REDUCTION_SEARCH_POLICY_ID = "halve_delay_then_trim_one_tail_event_v1"
SEARCH_SCOPE: Mapping[str, object] = MappingProxyType(
    {
        "phase": "development",
        "authority": "bounded_reduction_search_v1",
        "source_claim_evaluated": False,
        "baseline_truth_evaluated": False,
        "original_predicate_domain_extended": False,
        "budget_owner_changed": False,
        "global_minimum_verified": False,
        "local_minimum_verified": False,
        "checkpoint_resume_verified": False,
        "confirmation_accessed": False,
    }
)
_REQUEST_FIELDS = {
    "kind",
    "schema_version",
    "witness_ordinal",
    "focus_from_capture_seq",
    "max_steps",
    "max_wall_time_ms",
}
_SOURCE_IDS = {
    "bundle_id",
    "report_id",
    "finding_protocol_id",
    "source_protocol_id",
    "source_claim_revision_id",
    "predicate_id",
    "source_run_id",
    "assumption_id",
    "source_scenario_id",
    "source_dataset_id",
    "source_normalized_sha256",
    "replay_spec_id",
}
_PLAN_FIELDS = {
    "kind",
    "schema_version",
    "source",
    "request",
    "source_capture_seqs",
    "minimum_through_capture_seq",
    "minimum_delay_ns",
    "initial",
    "original_budget",
    "policy",
    "scope",
}
type Row = dict[str, object]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReductionValidationError(message)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _same(value: object, expected: object, message: str) -> None:
    _require(canonical({"v": value}) == canonical({"v": expected}), message)


def _policy() -> Row:
    return {
        "id": REDUCTION_SEARCH_POLICY_ID,
        "operator_order": ["halve_delay", "trim_last_event"],
        "cost_order": ["retained_event_count", "additional_delay_ns"],
        "acceptance": "strict_cost_decrease_and_false_numeric_criterion_v1",
        "initial_best": "source_witness_not_a_new_execution_v1",
        "unknown_neighbor": "unknown_never_a_minimum_certificate_v1",
        "existing_execution": "inspect_only_never_resume_v1",
        "cancellation": "between_candidates_after_current_bounded_attempt_v1",
        "elapsed_limit": "between_candidate_admission_not_hard_total_deadline_v1",
        "storage_limit": "bounded_records_not_a_total_managed_storage_quota_v1",
    }


def load_reduction_search_request(raw: bytes) -> Row:
    try:
        request = _exact(parse_request(raw, 16 * 1024), _REQUEST_FIELDS, "Reduction search request")
        _same(
            [request["kind"], request["schema_version"]],
            ["reduction_search_request_v1", 1],
            "Unsupported reduction search request",
        )
        integer(request["witness_ordinal"], "witness_ordinal", 1, 1024)
        integer(request["focus_from_capture_seq"], "focus_from_capture_seq", 1, INT64_MAX)
        integer(request["max_steps"], "max_steps", 1, 100)
        integer(request["max_wall_time_ms"], "max_wall_time_ms", 1, 86_400_000)
        return request
    except (ValueError, TypeError, KeyError) as error:
        raise ReductionValidationError(str(error)) from error


def _point(document: Row, value: object) -> Row:
    point = _exact(value, {"through_capture_seq", "additional_delay_ns"}, "Reduction point")
    through = integer(point["through_capture_seq"], "through_capture_seq", 1, INT64_MAX)
    initial = cast("Row", document["initial"])
    delay = integer(
        point["additional_delay_ns"],
        "additional_delay_ns",
        cast("int", document["minimum_delay_ns"]),
        cast("int", initial["additional_delay_ns"]),
    )
    captures = cast("list[int]", document["source_capture_seqs"])
    _require(
        through in captures and through >= cast("int", document["minimum_through_capture_seq"]),
        "Reduction point must retain a legal actual prefix endpoint",
    )
    return {"through_capture_seq": through, "additional_delay_ns": delay}


def _validated(raw: bytes) -> Row:
    document = _exact(
        parse(raw, limit=MAX_REDUCTION_SEARCH_PLAN_BYTES), _PLAN_FIELDS, "Reduction search plan"
    )
    _same(
        [document["kind"], document["schema_version"]],
        ["reduction_search_plan_v1", 1],
        "Unsupported reduction search plan",
    )
    request = load_reduction_search_request(canonical(cast("Row", document["request"])))
    source = _exact(document["source"], _SOURCE_IDS | {"witness_ordinal"}, "Source bindings")
    for name in _SOURCE_IDS:
        identity(source[name])
    integer(source["witness_ordinal"], "source witness_ordinal", 1, 1024)
    _same(source["witness_ordinal"], request["witness_ordinal"], "Plan selects another witness")
    budget = _exact(
        document["original_budget"],
        {"max_attempts", "max_events", "max_wall_seconds"},
        "Original execution budget",
    )
    for name, maximum in (("max_attempts", 100), ("max_events", 10_000), ("max_wall_seconds", 60)):
        integer(budget[name], name, 1, maximum)
    captures_value = document["source_capture_seqs"]
    _require(isinstance(captures_value, list), "Source captures must be a finite list")
    captures = cast("list[object]", captures_value)
    _require(
        0 < len(captures) <= cast("int", budget["max_events"]),
        "Source capture count exceeds the original event budget",
    )
    checked = [integer(value, "source capture_seq", 1, INT64_MAX) for value in captures]
    _require(all(left < right for left, right in pairwise(checked)), "Captures not ordered")
    focus = cast("int", request["focus_from_capture_seq"])
    minimum = integer(document["minimum_through_capture_seq"], "minimum through", focus, INT64_MAX)
    _require(focus in checked and minimum in checked, "Focus and minimum must be actual captures")
    minimum_delay = integer(document["minimum_delay_ns"], "minimum delay", 0, INT64_MAX)
    initial = _exact(document["initial"], {"through_capture_seq", "additional_delay_ns"}, "Initial")
    integer(initial["additional_delay_ns"], "initial delay", minimum_delay, INT64_MAX)
    integer(initial["through_capture_seq"], "initial through", 1, INT64_MAX)
    _same(initial["through_capture_seq"], checked[-1], "Initial point must be the complete witness")
    _point(document, initial)
    _same(document["policy"], _policy(), "Reduction policy or cancellation boundary differs")
    _same(document["scope"], dict(SEARCH_SCOPE), "Reduction search scope cannot extend authority")
    _require(canonical(document) == raw, "Reduction search plan must be exact canonical bytes")
    return document


@dataclass(frozen=True, slots=True)
class ReductionSearchPlan:
    plan_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated(self.canonical_bytes)
            _require(
                identity(self.plan_id) == digest(self.canonical_bytes), "Plan identity differs"
            )
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ReductionValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_REDUCTION_SEARCH_PLAN_BYTES)


def load_reduction_search_plan(raw: bytes) -> ReductionSearchPlan:
    try:
        return ReductionSearchPlan(digest(raw), raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReductionValidationError(str(error)) from error


def build_reduction_search_plan(
    request_raw: bytes, *, materialization: MaterializedReduction
) -> ReductionSearchPlan:
    try:
        request = load_reduction_search_request(request_raw)
        _require(
            type(materialization) is MaterializedReduction, "Plan requires real materialization"
        )
        rebuilt = materialize_reduction(materialization.recipe, source=materialization.source)
        _require(
            rebuilt.canonical_bytes == materialization.canonical_bytes
            and rebuilt.replay_input == materialization.replay_input,
            "Plan materialization differs from independently derived bytes",
        )
        recipe, descriptor = rebuilt.recipe.document, rebuilt.document
        source = cast("Row", recipe["source"])
        operators = cast("Row", recipe["operators"])
        validation = rebuilt.source.validation
        source_delay = cast("Row", validation.scenario.document["additional_delay"])["value"]
        captures = [event.capture_seq for event in rebuilt.prepared.events]
        _same(source["witness_ordinal"], request["witness_ordinal"], "Plan witness differs")
        _same(
            operators["focus_from_capture_seq"],
            request["focus_from_capture_seq"],
            "Plan focus differs from full-witness preparation",
        )
        _same(operators["additional_delay_ns"], source_delay, "Initial delay is already reduced")
        _same(
            cast("Row", descriptor["retained"])["event_count"],
            cast("Row", descriptor["candidate"])["full_event_count"],
            "Plan requires the complete original witness, not an already shortened input",
        )
        assumption = validation.assumptions.document
        protocol = validation.protocol.document
        strategy = cast("Row", cast("Row", protocol["replay_spec"])["strategy"])
        minimum = max(
            cast("int", request["focus_from_capture_seq"]),
            cast("int", strategy["submit_capture_seq"]),
            cast("int", cast("Row", assumption["transform"])["from_capture_seq"]),
        )
        return load_reduction_search_plan(
            canonical(
                {
                    "kind": "reduction_search_plan_v1",
                    "schema_version": 1,
                    "source": source,
                    "request": request,
                    "source_capture_seqs": captures,
                    "minimum_through_capture_seq": minimum,
                    "minimum_delay_ns": cast("Row", assumption["additional_delay"])["minimum"],
                    "initial": {
                        "through_capture_seq": captures[-1],
                        "additional_delay_ns": source_delay,
                    },
                    "original_budget": protocol["budget"],
                    "policy": _policy(),
                    "scope": dict(SEARCH_SCOPE),
                }
            )
        )
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
        raise ReductionValidationError("Cannot freeze reduction search: " + str(error)) from error


def _checked(plan: ReductionSearchPlan) -> Row:
    _require(type(plan) is ReductionSearchPlan, "Expected an actual immutable reduction plan")
    rebuilt = load_reduction_search_plan(plan.canonical_bytes)
    _require(rebuilt.plan_id == plan.plan_id, "Reduction plan identity differs from its bytes")
    return rebuilt.document


def initial_point(plan: ReductionSearchPlan) -> Row:
    return cast("Row", _checked(plan)["initial"])


def point_cost(plan: ReductionSearchPlan, point: Row) -> tuple[int, int]:
    document = _checked(plan)
    point = _point(document, point)
    return (
        cast("list[int]", document["source_capture_seqs"]).index(
            cast("int", point["through_capture_seq"])
        )
        + 1,
        cast("int", point["additional_delay_ns"]),
    )


def reduction_neighbors(plan: ReductionSearchPlan, point: Row) -> tuple[Row, ...]:
    document = _checked(plan)
    point = _point(document, point)
    through = cast("int", point["through_capture_seq"])
    delay = cast("int", point["additional_delay_ns"])
    candidates: list[Row] = []
    contracted = delay // 2
    if contracted < delay and contracted >= cast("int", document["minimum_delay_ns"]):
        candidates.append({"through_capture_seq": through, "additional_delay_ns": contracted})
    captures = cast("list[int]", document["source_capture_seqs"])
    index = captures.index(through)
    if index > 0 and captures[index - 1] >= cast("int", document["minimum_through_capture_seq"]):
        candidates.append(
            {"through_capture_seq": captures[index - 1], "additional_delay_ns": delay}
        )
    return tuple(candidates)


def reduction_request(plan: ReductionSearchPlan, point: Row) -> bytes:
    document = _checked(plan)
    point = _point(document, point)
    request = cast("Row", document["request"])
    return canonical(
        {
            "kind": "reduction_request_v1",
            "schema_version": 1,
            "witness_ordinal": request["witness_ordinal"],
            "focus_from_capture_seq": request["focus_from_capture_seq"],
            **point,
        }
    )
