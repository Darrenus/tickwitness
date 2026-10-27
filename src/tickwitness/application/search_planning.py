"""Freeze source-checked proposal journals without executing or spending attempts."""

from collections.abc import Callable
from typing import Protocol, cast

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.application.experiments import ExecutableReader
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.assumptions.specs import (
    AssumptionSpec,
    AssumptionValidationError,
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.evidence.run_records import canonical, identity
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    load_executable_protocol,
)
from tickwitness.domain.search.plans import (
    SearchPlan,
    SearchPlanValidationError,
    build_search_plan,
    load_search_plan,
)

MAX_DERIVED_EVENT_CHECKS = 1_000_000


class SearchPlanRecord(Protocol):
    @property
    def plan_id(self) -> str: ...
    @property
    def canonical_bytes(self) -> bytes: ...
    @property
    def created(self) -> bool: ...


class SearchPlanReader(Protocol):
    def get(self, plan_id: str) -> SearchPlanRecord: ...


class SearchPlanRepository(SearchPlanReader, Protocol):
    def seal(self, canonical_bytes: bytes) -> SearchPlanRecord: ...


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Search planning permits development evidence only")


def _context(
    protocol_id: str,
    assumption_request: bytes,
    *,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
) -> tuple[ExecutableProtocol, AssumptionSpec, ReplayInput]:
    identity(protocol_id)
    record = registry_factory().get(protocol_id)
    protocol = load_executable_protocol(record.canonical_bytes)
    if record.protocol_id != protocol_id or protocol.protocol_id != protocol_id:
        raise SearchPlanValidationError("Search subject registry returned conflicting evidence")
    document = protocol.document
    dataset_id = cast("dict[str, str]", document["datasets"])["development"]
    try:
        data = read_accepted_events(dataset_id, datasets_factory())
        spec = build_replay_spec(canonical(cast("dict[str, object]", document["replay_spec"])))
        replay_input = ReplayInput(dataset_id, data, spec)
        assumptions = build_assumption_spec(
            assumption_request, protocol=protocol, replay_input=replay_input
        )
    except (DataAccessError, ReplayValidationError, AssumptionValidationError) as error:
        raise SearchPlanValidationError("Search source validation failed: " + str(error)) from error
    return protocol, assumptions, replay_input


def _check_derived_candidates(
    plan: SearchPlan,
    protocol: ExecutableProtocol,
    assumptions: AssumptionSpec,
    replay_input: ReplayInput,
) -> None:
    journal = cast("list[dict[str, object]]", plan.document["journal"])
    eligible = [row for row in journal if row["status"] == "ELIGIBLE"]
    # This is a planning work bound, not an execution or statistical trial budget.
    if len(replay_input.normalized_bytes.splitlines()) * len(eligible) > MAX_DERIVED_EVENT_CHECKS:
        raise SearchPlanValidationError("Plan exceeds the derived-event validation work limit")
    try:
        for row in eligible:
            scenario = build_scenario_spec(
                canonical(
                    {
                        "kind": "scenario_request_v1",
                        "schema_version": 1,
                        "scenario_kind": "COUNTERFACTUAL_STRESS",
                        "additional_delay": {"value": row["delay_ns"], "unit": "ns"},
                    }
                ),
                assumptions=assumptions,
            )
            if scenario.scenario_id != row["scenario_id"]:
                raise SearchPlanValidationError("Candidate scenario identity differs from journal")
            derive_replay_view(
                validate_scenario_spec(
                    scenario, assumptions, protocol=protocol, replay_input=replay_input
                )
            )
    except (AssumptionValidationError, ReplayValidationError) as error:
        # A source/derivation defect invalidates the entire plan, never a research finding.
        raise SearchPlanValidationError("Candidate preflight failed: " + str(error)) from error


def _receipt(plan: SearchPlan, *, created: bool) -> dict[str, object]:
    if type(created) is not bool:
        raise SearchPlanValidationError("Plan repository returned an invalid created marker")
    return {
        "kind": "search_plan_receipt_v1",
        "schema_version": 1,
        "plan_id": plan.plan_id,
        "created": created,
        "plan": plan.document,
        "validation_policy": "bounded_derived_event_checks_v1",
        "derived_event_check_limit": MAX_DERIVED_EVENT_CHECKS,
        "verification": {
            "plan_recomputed": True,
            "source_revalidated": True,
            "derived_candidates_checked": True,
            "native_replayed": False,
        },
        "scope": {
            "execution_started": False,
            "attempt_reserved": False,
            "search_performed": False,
            "finding_issued": False,
        },
    }


def freeze_search_plan(
    protocol_id: str,
    assumption_request: bytes,
    search_request: bytes,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    plans_factory: Callable[[], SearchPlanRepository],
) -> dict[str, object]:
    _development(split)
    protocol, assumptions, replay_input = _context(
        protocol_id,
        assumption_request,
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    plan = build_search_plan(search_request, protocol=protocol, assumptions=assumptions)
    _check_derived_candidates(plan, protocol, assumptions, replay_input)
    stored = plans_factory().seal(plan.canonical_bytes)
    if stored.plan_id != plan.plan_id or stored.canonical_bytes != plan.canonical_bytes:
        raise SearchPlanValidationError("Plan repository returned conflicting frozen evidence")
    return _receipt(plan, created=stored.created)


def inspect_search_plan(
    plan_id: str,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    plans_factory: Callable[[], SearchPlanReader],
) -> dict[str, object]:
    _development(split)
    identity(plan_id)
    stored = plans_factory().get(plan_id)
    plan = load_search_plan(stored.canonical_bytes)
    if stored.plan_id != plan_id or plan.plan_id != plan_id:
        raise SearchPlanValidationError("Plan repository returned a conflicting identity")
    document = plan.document
    assumptions_document = cast("dict[str, object]", document["assumptions"])
    assumption_request = {
        key: value for key, value in assumptions_document.items() if key != "bindings"
    }
    assumption_request["kind"] = "assumption_request_v1"
    protocol, assumptions, replay_input = _context(
        cast("str", document["protocol_id"]),
        canonical(assumption_request),
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    rebuilt = build_search_plan(
        canonical(cast("dict[str, object]", document["request"])),
        protocol=protocol,
        assumptions=assumptions,
    )
    if rebuilt.canonical_bytes != plan.canonical_bytes:
        raise SearchPlanValidationError("Stored plan differs from the actual source contract")
    _check_derived_candidates(rebuilt, protocol, assumptions, replay_input)
    return _receipt(rebuilt, created=False)
