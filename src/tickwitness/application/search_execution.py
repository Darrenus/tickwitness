"""Sequential plan execution linked to the original immutable attempt budget.

Dispatch nonces are committed before reservation. Existing campaigns are inspected,
never resumed or replayed. This coordinator produces execution facts, not findings.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol, cast

from tickwitness.application.data_access import DatasetReader
from tickwitness.application.experiments import ExecutableReader, ProtocolRunError
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.scenario_execution import (
    ScenarioLedger,
    run_scenario,
    scenario_run_evidence,
)
from tickwitness.application.scenarios import validate_scenario_contracts
from tickwitness.application.search_planning import SearchPlanReader, inspect_search_plan
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.scenario_records import (
    build_scenario_intent,
    load_scenario_failure,
    load_scenario_intent,
)
from tickwitness.domain.replay.contracts import (
    ReplayInput,
    ReplayPort,
    ReplayResult,
    load_replay_result,
)
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    load_executable_protocol,
)
from tickwitness.domain.search.execution import (
    SearchCampaign,
    SearchDispatch,
    SearchExecutionValidationError,
    build_campaign,
    build_dispatch,
    build_link,
    build_stop,
    load_campaign,
    load_dispatch,
    load_link,
    load_stop,
)
from tickwitness.domain.search.plans import SearchPlan, load_search_plan


class SearchLedger(ScenarioLedger, Protocol):
    def reserve_with_nonce(
        self, protocol: ExecutableProtocol, nonce: str
    ) -> AttemptReservation: ...
    def list_reservations(self, owner: ExecutableProtocol) -> tuple[AttemptReservation, ...]: ...


class CampaignReader(Protocol):
    def get_campaign(self, plan_id: str) -> bytes | None: ...
    def get_dispatch(self, plan_id: str, ordinal: int) -> bytes | None: ...
    def get_link(self, plan_id: str, ordinal: int) -> bytes | None: ...
    def get_result(self, plan_id: str, ordinal: int) -> bytes | None: ...
    def get_stop(self, plan_id: str) -> bytes | None: ...
    def check_tree(self, plan_id: str) -> dict[str, tuple[int, ...]]: ...


class CampaignStore(CampaignReader, Protocol):
    def lock(self, plan_id: str) -> AbstractContextManager[object]: ...
    def start(self, plan_id: str, raw: bytes) -> None: ...
    def write_dispatch(self, plan_id: str, ordinal: int, raw: bytes) -> None: ...
    def write_link(self, plan_id: str, ordinal: int, raw: bytes) -> None: ...
    def write_result(self, plan_id: str, ordinal: int, raw: bytes) -> None: ...
    def write_stop(self, plan_id: str, raw: bytes) -> None: ...


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Search execution permits development evidence only")


def _plan(
    plan_id: str,
    *,
    plans_factory: Callable[[], SearchPlanReader],
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
) -> SearchPlan:
    receipt = inspect_search_plan(
        plan_id,
        split="development",
        plans_factory=plans_factory,
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    plan = load_search_plan(canonical(cast("dict[str, object]", receipt["plan"])))
    if plan.plan_id != plan_id:
        raise SearchExecutionValidationError("Search plan identity differs from requested plan")
    return plan


def _subject(plan: SearchPlan) -> ExecutableProtocol:
    return load_executable_protocol(canonical(cast("dict[str, object]", plan.document["protocol"])))


def _eligible(plan: SearchPlan) -> list[dict[str, object]]:
    return [
        row
        for row in cast("list[dict[str, object]]", plan.document["journal"])
        if row["status"] == "ELIGIBLE"
    ]


def _requests(plan: SearchPlan, row: dict[str, object]) -> tuple[bytes, bytes]:
    assumption = cast("dict[str, object]", plan.document["assumptions"])
    request = {key: value for key, value in assumption.items() if key != "bindings"}
    request["kind"] = "assumption_request_v1"
    return canonical(request), canonical(
        {
            "kind": "scenario_request_v1",
            "schema_version": 1,
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "additional_delay": {"value": row["delay_ns"], "unit": "ns"},
        }
    )


def _expected_intent(
    plan: SearchPlan,
    row: dict[str, object],
    *,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
) -> bytes:
    checked = validate_scenario_contracts(
        _subject(plan).protocol_id,
        *_requests(plan, row),
        split="development",
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    return build_scenario_intent(derive_replay_view(checked.validation)).canonical_bytes


def _checked_campaign(plan: SearchPlan, raw: bytes) -> SearchCampaign:
    campaign = load_campaign(raw)
    if canonical(cast("dict[str, object]", campaign.document["plan"])) != plan.canonical_bytes:
        raise SearchExecutionValidationError("Campaign differs from the source-checked frozen plan")
    return campaign


def _checked_reservations(
    protocol: ExecutableProtocol,
    ledger: SearchLedger,
) -> tuple[AttemptReservation, ...]:
    reservations = ledger.list_reservations(protocol)
    budget = cast("dict[str, int]", protocol.document["budget"])
    if len(reservations) > budget["max_attempts"]:
        raise SearchExecutionValidationError("Ledger prefix exceeds original protocol budget")
    seen: set[str] = set()
    for index, reservation in enumerate(reservations, start=1):
        rebuilt = AttemptReservation(reservation.attempt_id, reservation.canonical_bytes)
        if (
            rebuilt.protocol_id != protocol.protocol_id
            or rebuilt.attempt_index != index
            or rebuilt.document["max_wall_seconds"] != budget["max_wall_seconds"]
            or rebuilt.attempt_id in seen
            or ledger.get_reservation(rebuilt.attempt_id) != rebuilt
        ):
            raise SearchExecutionValidationError(
                "Search reservation differs from verified owner slots"
            )
        seen.add(rebuilt.attempt_id)
    return reservations


def _candidate_state(
    row: dict[str, object],
    dispatch: SearchDispatch | None,
    *,
    plan: SearchPlan,
    ledger: SearchLedger,
    store: CampaignReader,
    reservations: tuple[AttemptReservation, ...],
    stop: dict[str, object] | None,
    registry: ExecutableReader,
    datasets: DatasetReader,
) -> dict[str, object]:
    ordinal = cast("int", row["ordinal"])
    state: dict[str, object] = {
        "ordinal": ordinal,
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
    if dispatch is None:
        return state
    matches = [
        item
        for item in reservations
        if item.document["nonce"] == dispatch.document["reservation_nonce"]
    ]
    if len(matches) > 1:
        raise SearchExecutionValidationError("Dispatch nonce matches multiple committed slots")
    link = store.get_link(plan.plan_id, ordinal)
    raw_result = store.get_result(plan.plan_id, ordinal)
    if not matches:
        if link is not None or raw_result is not None:
            raise SearchExecutionValidationError("Candidate artifacts have no original reservation")
        known_exhausted = (
            stop is not None
            and stop["reason"] == "attempt_budget_exhausted"
            and stop["ordinal"] == ordinal
            and len(reservations)
            == cast("dict[str, int]", _subject(plan).document["budget"])["max_attempts"]
        )
        state.update(
            status="BUDGET_EXHAUSTED" if known_exhausted else "RESERVATION_UNCONFIRMED",
            budget_consumed=False if known_exhausted else None,
        )
        return state
    reservation = matches[0]
    state.update(
        attempt_id=reservation.attempt_id,
        attempt_index=reservation.attempt_index,
        budget_consumed=True,
        status="RESERVED_UNFINALIZED",
    )
    if link is not None:
        if load_link(link, dispatch=dispatch) != reservation:
            raise SearchExecutionValidationError("Candidate link differs from original slot")
        state["reservation_link_present"] = True
    expected_intent = canonical(cast("dict[str, object]", dispatch.document["intent"]))
    committed_intent = ledger.get_intent(reservation.attempt_id)
    if committed_intent is not None and committed_intent != expected_intent:
        raise SearchExecutionValidationError(
            "Candidate intent differs from original attempt intent"
        )
    if raw_result is not None:
        if link is None:
            raise SearchExecutionValidationError("Captured result lacks its pre-execution link")
        load_replay_result(raw_result)
        state["raw_result_sha256"] = digest(raw_result)
    outcome = ledger.get_outcome(reservation.attempt_id)
    if outcome is None:
        return state
    if committed_intent != expected_intent:
        raise SearchExecutionValidationError(
            "Finalized candidate lacks its committed dispatch intent"
        )
    if link is None:
        raise SearchExecutionValidationError("Finalized candidate lacks its pre-execution link")
    document = parse(outcome)
    state["outcome_id"] = digest(outcome)
    if document.get("kind") == "scenario_attempt_failure_v1":
        failure = load_scenario_failure(outcome)
        if (
            canonical(cast("dict[str, object]", failure["attempt"])) != reservation.canonical_bytes
            or canonical(cast("dict[str, object]", failure["intent"])) != expected_intent
        ):
            raise SearchExecutionValidationError("Candidate failure differs from dispatch and slot")
        state.update(status="FAILED", error=failure["error"])
        return state
    evidence = scenario_run_evidence(
        digest(outcome), ledger=ledger, registry=registry, datasets=datasets
    )
    if evidence.receipt.document["intent"] != dispatch.document["intent"]:
        raise SearchExecutionValidationError("Audited outcome differs from dispatched scenario")
    if raw_result != evidence.result.canonical_bytes:
        raise SearchExecutionValidationError("Captured raw result differs from audited receipt")
    state.update(
        status="COMPLETED"
        if evidence.result.document["execution_status"] == "completed"
        else "INCOMPLETE",
        run_id=evidence.receipt.run_id,
        evaluation=evidence.evaluation.document,
        raw_result_audited=True,
    )
    return state


def _report(
    plan: SearchPlan,
    *,
    store: CampaignReader,
    ledger: SearchLedger,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
) -> dict[str, object]:
    raw = store.get_campaign(plan.plan_id)
    if raw is None:
        raise SearchExecutionValidationError("Search campaign has not been started")
    campaign = _checked_campaign(plan, raw)
    # A terminal marker observed only after scanning could falsely close a mixed snapshot.
    terminal_raw = store.get_stop(plan.plan_id)
    stop = load_stop(terminal_raw, campaign=campaign) if terminal_raw is not None else None
    inventory = store.check_tree(plan.plan_id)
    rows = _eligible(plan)
    allowed = {cast("int", row["ordinal"]) for row in rows}
    dispatched = set(inventory["dispatches"])
    if (
        not dispatched <= allowed
        or not set(inventory["links"]) <= dispatched
        or not set(inventory["results"]) <= dispatched
    ):
        raise SearchExecutionValidationError("Campaign has extra or orphaned candidate records")
    reservations = _checked_reservations(_subject(plan), ledger)
    states: list[dict[str, object]] = []
    encountered_missing = False
    used_attempts: set[str] = set()
    used_nonces: set[str] = set()
    observed_dispatches: set[int] = set()
    registry, datasets = registry_factory(), datasets_factory()
    for row in rows:
        ordinal = cast("int", row["ordinal"])
        dispatch_raw = store.get_dispatch(plan.plan_id, ordinal)
        dispatch = (
            load_dispatch(dispatch_raw, campaign=campaign) if dispatch_raw is not None else None
        )
        if dispatch is not None:
            observed_dispatches.add(ordinal)
            if encountered_missing:
                raise SearchExecutionValidationError(
                    "Dispatched candidates do not form a plan prefix"
                )
            expected = _expected_intent(
                plan, row, registry_factory=registry_factory, datasets_factory=datasets_factory
            )
            if canonical(cast("dict[str, object]", dispatch.document["intent"])) != expected:
                raise SearchExecutionValidationError("Dispatch intent differs from actual source")
            nonce = cast("str", dispatch.document["reservation_nonce"])
            if nonce in used_nonces:
                raise SearchExecutionValidationError(
                    "Candidates reuse a dispatch reservation nonce"
                )
            used_nonces.add(nonce)
        else:
            encountered_missing = True
        state = _candidate_state(
            row,
            dispatch,
            plan=plan,
            ledger=ledger,
            store=store,
            reservations=reservations,
            stop=stop,
            registry=registry,
            datasets=datasets,
        )
        attempt = state["attempt_id"]
        if isinstance(attempt, str):
            if attempt in used_attempts:
                raise SearchExecutionValidationError(
                    "Candidates share an original execution attempt"
                )
            used_attempts.add(attempt)
        if states and dispatch is not None and states[-1]["status"] != "COMPLETED":
            raise SearchExecutionValidationError(
                "Campaign continued after a noncompleted candidate"
            )
        states.append(state)
    if observed_dispatches != dispatched:
        raise SearchExecutionValidationError("Campaign changed during inspection; retry the read")
    if store.check_tree(plan.plan_id) != inventory:
        raise SearchExecutionValidationError("Campaign changed during inspection; retry the read")
    complete = all(item["status"] == "COMPLETED" for item in states)
    status, reason, exit_code = "unfinalized", "terminal_record_absent", 3
    if stop is not None:
        reason = cast("str", stop["reason"])
        if reason in ("planned_candidates_exhausted", "no_eligible_candidates"):
            if not complete or (reason == "no_eligible_candidates") != (len(states) == 0):
                raise SearchExecutionValidationError(
                    "Campaign completion contradicts original outcomes"
                )
            status, exit_code = "completed", 0
        else:
            status = "stopped"
            exit_code = 8 if reason == "attempt_budget_exhausted" else 7
            if reason in ("reservation_unconfirmed", "publication_unconfirmed"):
                exit_code = 3
            stop_ordinal = cast("int | None", stop["ordinal"])
            target = next((item for item in states if item["ordinal"] == stop_ordinal), None)
            if target is not None and stop_ordinal is not None:
                if any(
                    cast("int", item["ordinal"]) > stop_ordinal
                    and item["status"] != "NOT_DISPATCHED"
                    for item in states
                ):
                    raise SearchExecutionValidationError("Stop marker precedes a later dispatch")
                if reason == "attempt_budget_exhausted" and target["status"] != "BUDGET_EXHAUSTED":
                    raise SearchExecutionValidationError(
                        "Budget stop is not supported by original slots"
                    )
                if reason == "candidate_failed" and target["status"] != "FAILED":
                    raise SearchExecutionValidationError("Failure stop lacks a committed failure")
                if (
                    reason == "candidate_failed"
                    and cast("dict[str, object]", target["error"])["code"] != stop["error_code"]
                ):
                    raise SearchExecutionValidationError("Stop error differs from original failure")
                if reason == "candidate_incomplete" and target["status"] != "INCOMPLETE":
                    raise SearchExecutionValidationError(
                        "Incomplete stop lacks an audited incomplete run"
                    )
                if reason == "candidate_failed" and stop["error_code"] == "engine_unavailable":
                    exit_code = 6
    counts = {
        "eligible": len(states),
        "dispatched": len(dispatched),
        "reserved": len(used_attempts),
        "completed": sum(item["status"] == "COMPLETED" for item in states),
        "failed": sum(item["status"] == "FAILED" for item in states),
        "incomplete": sum(item["status"] == "INCOMPLETE" for item in states),
        "unfinalized": sum(
            item["status"] in ("RESERVED_UNFINALIZED", "RESERVATION_UNCONFIRMED") for item in states
        ),
    }
    return {
        "kind": "search_campaign_report_v1",
        "schema_version": 1,
        "campaign_id": campaign.campaign_id,
        "plan_id": plan.plan_id,
        "protocol_id": _subject(plan).protocol_id,
        "status": status,
        "stop_reason": reason,
        "exit_code": exit_code,
        "counts": counts,
        "candidates": states,
        "proposal_journal": plan.document["journal"],
        "stop": stop,
        "scope": {
            "phase": "development",
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "calibration_status": "uncalibrated",
            "claim_evaluated": False,
            "finding_issued": False,
            "full_trial_history_certified": False,
        },
        "verification": {
            "plan_recomputed": True,
            "source_revalidated": True,
            "attempt_links_verified": all(
                item["status"] in ("NOT_DISPATCHED", "BUDGET_EXHAUSTED")
                or item["reservation_link_present"] is True
                for item in states
            ),
            "outcomes_reaudited": True,
            "native_replayed": False,
            "author_signature_verified": False,
        },
    }


class _DispatchLedger:
    def __init__(
        self, ledger: SearchLedger, store: CampaignStore, plan: SearchPlan, dispatch: SearchDispatch
    ) -> None:
        self.ledger, self.store, self.plan, self.dispatch = ledger, store, plan, dispatch
        self.reservation: AttemptReservation | None = None

    def reserve(self, protocol: ExecutableProtocol) -> AttemptReservation:
        if protocol.canonical_bytes != _subject(self.plan).canonical_bytes:
            raise SearchExecutionValidationError("Scenario changed the original budget owner")
        reservation = self.ledger.reserve_with_nonce(
            protocol, cast("str", self.dispatch.document["reservation_nonce"])
        )
        budget = cast("dict[str, int]", protocol.document["budget"])
        if (
            reservation.attempt_index > budget["max_attempts"]
            or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
        ):
            raise SearchExecutionValidationError("Named reservation differs from original budget")
        raw = build_link(self.dispatch, reservation)
        if self.ledger.get_reservation(reservation.attempt_id) != reservation:
            raise SearchExecutionValidationError(
                "Named reservation is not committed to original ledger"
            )
        self.store.write_link(
            self.plan.plan_id, cast("int", self.dispatch.document["ordinal"]), raw
        )
        self.reservation = reservation
        return reservation

    def bind_intent(
        self,
        reservation: AttemptReservation,
        intent_bytes: bytes,
        *,
        artifacts: tuple[bytes, ...] = (),
    ) -> str:
        if reservation != self.reservation or intent_bytes != canonical(
            cast("dict[str, object]", self.dispatch.document["intent"])
        ):
            raise SearchExecutionValidationError("Scenario intent differs from durable dispatch")
        return self.ledger.bind_intent(reservation, intent_bytes, artifacts=artifacts)

    def publish(
        self, reservation: AttemptReservation, outcome: bytes, *, artifacts: tuple[bytes, ...] = ()
    ) -> str:
        if reservation != self.reservation:
            raise SearchExecutionValidationError("Scenario outcome changed the linked attempt")
        return self.ledger.publish(reservation, outcome, artifacts=artifacts)

    def read_artifact(self, content_hash: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes:
        return self.ledger.read_artifact(content_hash, max_bytes=max_bytes)

    def get_intent(self, attempt_id: str) -> bytes | None:
        return self.ledger.get_intent(attempt_id)

    def get_outcome(self, attempt_id: str) -> bytes | None:
        return self.ledger.get_outcome(attempt_id)

    def get_reservation(self, attempt_id: str) -> AttemptReservation:
        return self.ledger.get_reservation(attempt_id)

    def engine(self, timeout: int, factory: Callable[[int], ReplayPort]) -> ReplayPort:
        ordinal = cast("int", self.dispatch.document["ordinal"])
        reservation = self.reservation
        link = self.store.get_link(self.plan.plan_id, ordinal)
        if (
            reservation is None
            or link is None
            or load_link(link, dispatch=self.dispatch) != reservation
            or self.ledger.get_intent(reservation.attempt_id)
            != canonical(cast("dict[str, object]", self.dispatch.document["intent"]))
            or self.ledger.get_outcome(reservation.attempt_id) is not None
        ):
            raise SearchExecutionValidationError(
                "Worker requires durable dispatch, slot, link and intent"
            )
        underlying = factory(timeout)
        store, plan_id = self.store, self.plan.plan_id

        class RecordingReplay:
            def run(self, replay_input: ReplayInput) -> ReplayResult:
                result = underlying.run(replay_input)
                checked = load_replay_result(result.canonical_bytes)
                store.write_result(plan_id, ordinal, checked.canonical_bytes)
                if store.get_result(plan_id, ordinal) != checked.canonical_bytes:
                    raise SearchExecutionValidationError(
                        "Raw result capture differs from actual result"
                    )
                return checked

        return RecordingReplay()


def inspect_search_campaign(
    plan_id: str,
    *,
    split: str,
    plans_factory: Callable[[], SearchPlanReader],
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], SearchLedger],
    campaigns_factory: Callable[[], CampaignReader],
) -> dict[str, object]:
    _development(split)
    identity(plan_id)
    plan = _plan(
        plan_id,
        plans_factory=plans_factory,
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    return _report(
        plan,
        store=campaigns_factory(),
        ledger=ledger_factory(),
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )


def run_search_plan(
    plan_id: str,
    *,
    split: str,
    plans_factory: Callable[[], SearchPlanReader],
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], SearchLedger],
    ledger_reader_factory: Callable[[], SearchLedger],
    campaigns_factory: Callable[[], CampaignStore],
    engine_factory: Callable[[int], ReplayPort],
    nonce_factory: Callable[[], str],
) -> dict[str, object]:
    _development(split)
    identity(plan_id)
    plan = _plan(
        plan_id,
        plans_factory=plans_factory,
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    store = campaigns_factory()
    with store.lock(plan_id):
        existing = store.get_campaign(plan_id)
        if existing is not None:
            ledger = ledger_reader_factory()
            return _report(
                plan,
                store=store,
                ledger=ledger,
                registry_factory=registry_factory,
                datasets_factory=datasets_factory,
            )
        if any(store.check_tree(plan_id).values()) or store.get_stop(plan_id) is not None:
            raise SearchExecutionValidationError("Unstarted campaign contains orphaned records")
        ledger = ledger_factory()
        campaign = build_campaign(plan, nonce_factory())
        store.start(plan_id, campaign.canonical_bytes)
        if store.get_campaign(plan_id) != campaign.canonical_bytes:
            raise SearchExecutionValidationError("Campaign store returned conflicting header")
        rows = _eligible(plan)
        for row in rows:
            ordinal = cast("int", row["ordinal"])
            expected = _expected_intent(
                plan, row, registry_factory=registry_factory, datasets_factory=datasets_factory
            )
            dispatch = build_dispatch(
                campaign, ordinal, nonce_factory(), load_scenario_intent(expected)
            )
            reason, code, message = None, None, None
            phase = "dispatch_publication"
            try:
                store.write_dispatch(plan_id, ordinal, dispatch.canonical_bytes)
                if store.get_dispatch(plan_id, ordinal) != dispatch.canonical_bytes:
                    raise SearchExecutionValidationError("Campaign dispatch publication differs")
                wrapper = _DispatchLedger(ledger, store, plan, dispatch)
                phase = "reservation"
                submission = run_scenario(
                    _subject(plan).protocol_id,
                    *_requests(plan, row),
                    split="development",
                    registry_factory=registry_factory,
                    datasets_factory=datasets_factory,
                    ledger_factory=lambda: wrapper,
                    engine_factory=lambda timeout: wrapper.engine(timeout, engine_factory),
                )
                if submission.execution_status != "completed":
                    reason, code, message = (
                        "candidate_incomplete",
                        "candidate_incomplete",
                        "Candidate did not complete",
                    )
            except ProtocolRunError as error:
                reason = (
                    "publication_unconfirmed"
                    if error.code == "attempt_outcome_unconfirmed"
                    else "candidate_failed"
                )
                code, message = error.code, str(error)
            except Exception as error:
                # Reserve can commit before raising. The precommitted nonce enables inspection.
                reason = (
                    "publication_unconfirmed"
                    if phase == "dispatch_publication"
                    else "attempt_budget_exhausted"
                    if getattr(error, "code", None) == "attempt_budget_exhausted"
                    else "reservation_unconfirmed"
                )
                code = reason
                message = (str(error) or type(error).__name__)[:4096]
            if reason is not None:
                if message is not None:
                    message = (
                        "".join(
                            character if ord(character) >= 32 and ord(character) != 127 else " "
                            for character in message
                        )
                        .encode("utf-8", errors="backslashreplace")
                        .decode("utf-8")[:4096]
                    )
                store.write_stop(
                    plan_id,
                    build_stop(campaign, reason, ordinal=ordinal, error_code=code, message=message),
                )
                break
        else:
            reason = "planned_candidates_exhausted" if rows else "no_eligible_candidates"
            store.write_stop(plan_id, build_stop(campaign, reason))
        return _report(
            plan,
            store=store,
            ledger=ledger,
            registry_factory=registry_factory,
            datasets_factory=datasets_factory,
        )
