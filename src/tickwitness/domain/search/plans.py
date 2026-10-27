"""Freeze a reproducible receive-delay proposal journal without evaluating it.

The independent search seed never changes the frozen native replay seed. The
embedded assumptions bind a declared source; only the application can validate
those declarations against actual development input.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast

from tickwitness.domain.assumptions.specs import (
    AssumptionSpec,
    AssumptionValidationError,
    build_scenario_spec,
    load_assumption_spec,
)
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    load_executable_protocol,
)
from tickwitness.domain.research_contracts.protocols import (
    ProtocolValidationError,
    _canonical,
    _digest,
    _integer,
    _object,
    _parse,
)

MAX_SEARCH_PLAN_BYTES = 2 * 1024 * 1024
_DELAY_CAP_NS = 60_000_000_000
_MAX_PROPOSALS = 1_024
_MAX_RANDOM_DRAWS = _MAX_PROPOSALS * 1_024
_RANDOM_DOMAIN = b"TickWitness/search-delay/sha256-counter-rejection/v1\0"
_GENERATION_POLICY = "bounded_receive_delay_proposals_v1"
_RANDOM_POLICY = "sha256_counter_rejection_v1"
_REQUEST_FIELDS = frozenset({"kind", "schema_version", "search_seed", "max_proposals", "generator"})
_PLAN_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "protocol_id",
        "protocol",
        "assumption_id",
        "assumptions",
        "request",
        "generation_policy",
        "random_policy",
        "journal",
        "counts",
        "generation_stop",
        "scope",
        "limitations",
    }
)
_SCOPE: dict[str, object] = {
    "phase": "development",
    "scenario_kind": "COUNTERFACTUAL_STRESS",
    "calibration_status": "uncalibrated",
    "source_validated": False,
    "execution_performed": False,
    "attempt_budget_reserved": False,
    "claim_evaluated": False,
    "findings_issued": False,
}
_LIMITATIONS = (
    "declared_bindings_do_not_validate_actual_source",
    "proposal_seed_is_distinct_from_frozen_replay_seed",
    "proposal_limit_counts_duplicates_and_rejections_without_refill",
    "finite_proposals_do_not_exhaust_continuous_delay_space",
    "candidate_journal_is_not_an_execution_or_statistical_trial_ledger",
    "no_execution_authority_budget_reservation_or_research_verdict",
)


class SearchPlanValidationError(ProtocolValidationError):
    """A bounded candidate declaration or frozen plan is inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SearchPlanValidationError(message)


def _encode(document: dict[str, object]) -> bytes:
    try:
        return _canonical(document)
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise SearchPlanValidationError("Search plan cannot be canonical UTF-8 JSON") from error


def _request(document: dict[str, object]) -> dict[str, object]:
    _object(document, _REQUEST_FIELDS, "search plan request")
    _require(document["kind"] == "search_plan_request_v1", "Unsupported search plan request kind")
    _integer(document["schema_version"], "schema_version", 1, 1)
    _integer(document["search_seed"], "search_seed", 0, (1 << 63) - 1)
    _integer(document["max_proposals"], "max_proposals", 1, _MAX_PROPOSALS)
    generator = document["generator"]
    _require(isinstance(generator, dict), "generator must be an exact supported object")
    generator = cast("dict[str, object]", generator)
    kind = generator.get("kind")
    if kind == "grid":
        _object(generator, frozenset({"kind", "values_ns"}), "grid generator")
        values = generator["values_ns"]
        _require(
            isinstance(values, list) and 1 <= len(values) <= _MAX_PROPOSALS,
            "grid values_ns must contain 1..1024 integer delay proposals",
        )
        for value in cast("list[object]", values):
            _integer(value, "grid delay_ns", 0, _DELAY_CAP_NS)
    elif kind == "random_integer_with_replacement":
        _object(
            generator,
            frozenset({"kind", "minimum_ns", "maximum_ns"}),
            "random generator",
        )
        minimum = _integer(generator["minimum_ns"], "minimum_ns", 0, _DELAY_CAP_NS)
        _integer(generator["maximum_ns"], "maximum_ns", minimum, _DELAY_CAP_NS)
    else:
        raise SearchPlanValidationError("Unsupported candidate generator kind")
    return document


def _context(
    protocol: ExecutableProtocol, assumptions: AssumptionSpec
) -> tuple[ExecutableProtocol, AssumptionSpec]:
    _require(type(protocol) is ExecutableProtocol, "Search plans require ExecutableProtocol v2")
    _require(type(assumptions) is AssumptionSpec, "Search plans require AssumptionSpec v1")
    checked_protocol = load_executable_protocol(protocol.canonical_bytes)
    checked_assumptions = load_assumption_spec(assumptions.canonical_bytes)
    _require(
        checked_protocol.protocol_id == protocol.protocol_id
        and checked_protocol.claim_revision_id == protocol.claim_revision_id,
        "Search subject identity differs from its canonical content",
    )
    _require(
        checked_assumptions.assumption_id == assumptions.assumption_id,
        "Search assumption identity differs from its canonical content",
    )
    bindings = cast("dict[str, str]", checked_assumptions.document["bindings"])
    subject = checked_protocol.document
    datasets = cast("dict[str, str]", subject["datasets"])
    _require(
        bindings["protocol_id"] == checked_protocol.protocol_id
        and bindings["development_dataset_id"] == datasets["development"]
        and bindings["replay_spec_id"] == subject["replay_spec_id"],
        "Search assumption bindings differ from the frozen development subject",
    )
    return checked_protocol, checked_assumptions


def _random_values(seed: int, count: int, minimum: int, maximum: int) -> list[int]:
    """Version-one SHA-256 counter stream with unbiased integer rejection.

    Each draw hashes domain || seed_u64be || counter_u64be. Counter begins at
    zero and advances on every draw, including rejected digests. Interpret the
    digest as an unsigned big-endian integer x; reject x >= 2^256-(2^256 mod n),
    otherwise emit minimum+(x mod n), where n=maximum-minimum+1. The stream does
    not depend on count or bounds; accepted proposals do depend on the bounds.
    At most 1,048,576 raw draws are allowed; failure produces no frozen plan.
    """
    span = maximum - minimum + 1
    cutoff = (1 << 256) - ((1 << 256) % span)
    prefix = _RANDOM_DOMAIN + seed.to_bytes(8, "big")
    values: list[int] = []
    for counter in range(_MAX_RANDOM_DRAWS):
        sample = int.from_bytes(hashlib.sha256(prefix + counter.to_bytes(8, "big")).digest(), "big")
        if sample < cutoff:
            values.append(minimum + sample % span)
            if len(values) == count:
                return values
    raise SearchPlanValidationError("Random rejection stream exceeded its raw-draw safety limit")


def _build_document(
    declaration: dict[str, object],
    *,
    protocol: ExecutableProtocol,
    assumptions: AssumptionSpec,
) -> dict[str, object]:
    request = _request(declaration)
    protocol, assumptions = _context(protocol, assumptions)
    generator = cast("dict[str, object]", request["generator"])
    limit = cast("int", request["max_proposals"])
    if generator["kind"] == "grid":
        grid = cast("list[int]", generator["values_ns"])
        values = grid[:limit]
        stop = "grid_exhausted" if len(grid) <= limit else "proposal_limit"
    else:
        values = _random_values(
            cast("int", request["search_seed"]),
            limit,
            cast("int", generator["minimum_ns"]),
            cast("int", generator["maximum_ns"]),
        )
        stop = "proposal_limit"
    bounds = cast("dict[str, object]", assumptions.document["additional_delay"])
    minimum, maximum = cast("int", bounds["minimum"]), cast("int", bounds["maximum"])
    journal: list[dict[str, object]] = []
    first_proposals: dict[int, int] = {}
    scenario_ids: dict[int, str | None] = {}
    counts = {"proposed": len(values), "eligible": 0, "duplicate": 0, "rejected": 0}
    for ordinal, delay in enumerate(values, start=1):
        duplicate_of = first_proposals.get(delay)
        scenario_id: str | None = scenario_ids.get(delay)
        reason: str | None
        if duplicate_of is not None:
            status, reason = "DUPLICATE", "duplicate_proposal"
        elif not minimum <= delay <= maximum:
            status, reason = "REJECTED", "outside_assumption_range"
        else:
            status, reason = "ELIGIBLE", None
            scenario = build_scenario_spec(
                _encode(
                    {
                        "kind": "scenario_request_v1",
                        "schema_version": 1,
                        "scenario_kind": "COUNTERFACTUAL_STRESS",
                        "additional_delay": {"value": delay, "unit": "ns"},
                    }
                ),
                assumptions=assumptions,
            )
            scenario_id = scenario.scenario_id
        if duplicate_of is None:
            first_proposals[delay] = ordinal
            scenario_ids[delay] = scenario_id
        counts[status.lower()] += 1
        journal.append(
            {
                "ordinal": ordinal,
                "delay_ns": delay,
                "scenario_id": scenario_id,
                "status": status,
                "duplicate_of": duplicate_of,
                "reason": reason,
            }
        )
    return {
        "kind": "search_plan_v1",
        "schema_version": 1,
        "protocol_id": protocol.protocol_id,
        "protocol": protocol.document,
        "assumption_id": assumptions.assumption_id,
        "assumptions": assumptions.document,
        "request": request,
        "generation_policy": _GENERATION_POLICY,
        "random_policy": _RANDOM_POLICY,
        "journal": journal,
        "counts": counts,
        "generation_stop": stop,
        "scope": dict(_SCOPE),
        "limitations": list(_LIMITATIONS),
    }


def _validated(raw: bytes) -> str:
    document = _object(
        _parse(raw, max_bytes=MAX_SEARCH_PLAN_BYTES), _PLAN_FIELDS, "frozen search plan"
    )
    _require(document["kind"] == "search_plan_v1", "Unsupported frozen search plan kind")
    _integer(document["schema_version"], "schema_version", 1, 1)
    _require(isinstance(document["protocol"], dict), "Search subject must be an object")
    _require(isinstance(document["assumptions"], dict), "Search assumptions must be an object")
    _require(isinstance(document["request"], dict), "Search request must be an object")
    protocol = load_executable_protocol(_encode(cast("dict[str, object]", document["protocol"])))
    assumptions = load_assumption_spec(_encode(cast("dict[str, object]", document["assumptions"])))
    rebuilt = _build_document(
        cast("dict[str, object]", document["request"]),
        protocol=protocol,
        assumptions=assumptions,
    )
    _require(_encode(rebuilt) == raw, "Frozen search plan does not reproduce from its declarations")
    return _digest(raw)


@dataclass(frozen=True, slots=True)
class SearchPlan:
    """Immutable canonical plan with detached documents and no execution authority."""

    plan_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            expected = _validated(self.canonical_bytes)
            _require(
                self.plan_id == expected, "Search plan identity differs from canonical content"
            )
        except SearchPlanValidationError:
            raise
        except (ProtocolValidationError, AssumptionValidationError) as error:
            raise SearchPlanValidationError(str(error)) from error

    @property
    def document(self) -> dict[str, object]:
        return _parse(self.canonical_bytes, max_bytes=MAX_SEARCH_PLAN_BYTES)


def build_search_plan(
    raw: bytes, *, protocol: ExecutableProtocol, assumptions: AssumptionSpec
) -> SearchPlan:
    """Freeze proposals from declarations; never inspect source, reserve or execute."""
    try:
        document = _build_document(_parse(raw), protocol=protocol, assumptions=assumptions)
        encoded = _encode(document)
        return SearchPlan(_digest(encoded), encoded)
    except SearchPlanValidationError:
        raise
    except (ProtocolValidationError, AssumptionValidationError) as error:
        raise SearchPlanValidationError(str(error)) from error


def load_search_plan(raw: bytes) -> SearchPlan:
    """Recompute every proposal/status from embedded declarations, without source IO."""
    try:
        return SearchPlan(_validated(raw), raw)
    except SearchPlanValidationError:
        raise
    except (ProtocolValidationError, AssumptionValidationError) as error:
        raise SearchPlanValidationError(str(error)) from error
