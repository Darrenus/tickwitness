"""Immutable sequential-search coordination records, separate from scenario receipts.

Records bind a frozen proposal plan to actual attempt identities. They do not
prove physical publication order, authenticate an author, evaluate a claim, or
certify a complete statistical trial history. Application inspection must also
revalidate source and committed ledger evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.scenario_records import ScenarioIntent, load_scenario_intent
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError
from tickwitness.domain.search.plans import SearchPlan, load_search_plan

MAX_CAMPAIGN_BYTES = 4 * 1024 * 1024
MAX_SEARCH_EXECUTION_RECORD_BYTES = 64 * 1024
_EXECUTION_POLICY = "sequential_receive_delay_attempts_v1"
_SCOPE: dict[str, object] = {
    "phase": "development",
    "scenario_kind": "COUNTERFACTUAL_STRESS",
    "calibration_status": "uncalibrated",
    "evaluation_kind": "scenario_metric_observation_v1",
    "claim_evaluated": False,
    "findings_issued": False,
    "confirmation_accessed": False,
    "statistical_trial_history_certified": False,
}
_CAMPAIGN_FIELDS = {
    "kind", "schema_version", "plan_id", "protocol_id", "campaign_nonce", "plan",
    "execution_policy", "scope",
}
_DISPATCH_FIELDS = {
    "kind", "schema_version", "campaign_id", "plan_id", "protocol_id", "ordinal",
    "scenario_id", "reservation_nonce", "intent",
}
_LINK_FIELDS = {
    "kind", "schema_version", "dispatch_id", "campaign_id", "plan_id", "ordinal",
    "scenario_id", "reservation",
}
_STOP_FIELDS = {
    "kind", "schema_version", "campaign_id", "plan_id", "protocol_id", "reason", "ordinal",
    "error_code", "message",
}
_STOP_REASONS = {
    "planned_candidates_exhausted", "no_eligible_candidates", "attempt_budget_exhausted",
    "candidate_failed", "candidate_incomplete", "reservation_unconfirmed",
    "publication_unconfirmed",
}
_NORMAL_REASONS = {"planned_candidates_exhausted", "no_eligible_candidates"}


class SearchExecutionValidationError(EvidenceValidationError):
    """Coordination records or their declared cross-record bindings disagree."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SearchExecutionValidationError(message)


def _encode(value: dict[str, object]) -> bytes:
    try:
        return canonical(value)
    except EvidenceValidationError as error:
        raise SearchExecutionValidationError(str(error)) from error


def _parse(raw: bytes, *, limit: int = MAX_SEARCH_EXECUTION_RECORD_BYTES) -> dict[str, object]:
    try:
        return parse(raw, limit=limit)
    except EvidenceValidationError as error:
        raise SearchExecutionValidationError(str(error)) from error


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    _require(isinstance(value, dict) and value.keys() == keys, label + " fields differ")
    return cast("dict[str, object]", value)


def _markers(value: dict[str, object], kind: str) -> None:
    _require(value["kind"] == kind, "Unsupported search coordination record kind")
    _require(
        type(value["schema_version"]) is int and value["schema_version"] == 1,
        "Unsupported search coordination schema version",
    )


def _identity(value: object) -> str:
    try:
        return identity(value)
    except EvidenceValidationError as error:
        raise SearchExecutionValidationError(str(error)) from error


def _nonce(value: object) -> str:
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None,
        "Coordination nonce must contain exactly 32 lowercase hexadecimal characters",
    )
    return cast("str", value)


def _ordinal(value: object) -> int:
    _require(type(value) is int and 1 <= value <= 1_024, "Candidate ordinal must be in 1..1024")
    return cast("int", value)


def _plan(raw: bytes) -> SearchPlan:
    try:
        return load_search_plan(raw)
    except ProtocolValidationError as error:
        raise SearchExecutionValidationError(str(error)) from error


def _intent(raw: bytes) -> ScenarioIntent:
    try:
        return load_scenario_intent(raw)
    except EvidenceValidationError as error:
        raise SearchExecutionValidationError(str(error)) from error


def _campaign_document(plan: SearchPlan, nonce: str) -> dict[str, object]:
    _require(type(plan) is SearchPlan, "Campaign requires an actual frozen SearchPlan")
    checked = _plan(plan.canonical_bytes)
    _require(checked.plan_id == plan.plan_id, "Search plan identity differs from its content")
    return {
        "kind": "search_campaign_v1",
        "schema_version": 1,
        "plan_id": checked.plan_id,
        "protocol_id": checked.document["protocol_id"],
        "campaign_nonce": _nonce(nonce),
        "plan": checked.document,
        "execution_policy": _EXECUTION_POLICY,
        "scope": dict(_SCOPE),
    }


def _validated_campaign(raw: bytes) -> str:
    value = _exact(_parse(raw, limit=MAX_CAMPAIGN_BYTES), _CAMPAIGN_FIELDS, "Campaign")
    _markers(value, "search_campaign_v1")
    _require(isinstance(value["plan"], dict), "Campaign requires a complete frozen plan")
    plan = _plan(_encode(cast("dict[str, object]", value["plan"])))
    rebuilt = _campaign_document(plan, _nonce(value["campaign_nonce"]))
    _require(_encode(rebuilt) == raw, "Campaign differs from its frozen declarations")
    return digest(raw)


@dataclass(frozen=True, slots=True)
class SearchCampaign:
    campaign_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _require(
            _identity(self.campaign_id) == _validated_campaign(self.canonical_bytes),
            "Campaign identity differs from its canonical content",
        )

    @property
    def document(self) -> dict[str, object]:
        return _parse(self.canonical_bytes, limit=MAX_CAMPAIGN_BYTES)


def build_campaign(plan: SearchPlan, nonce: str) -> SearchCampaign:
    raw = _encode(_campaign_document(plan, nonce))
    return SearchCampaign(digest(raw), raw)


def load_campaign(raw: bytes) -> SearchCampaign:
    return SearchCampaign(_validated_campaign(raw), raw)


def _checked_campaign(campaign: SearchCampaign) -> SearchCampaign:
    _require(type(campaign) is SearchCampaign, "Expected actual SearchCampaign")
    checked = load_campaign(campaign.canonical_bytes)
    _require(checked.campaign_id == campaign.campaign_id, "Forged campaign identity")
    return checked


def _eligible_row(campaign: SearchCampaign, ordinal: object) -> dict[str, object]:
    index = _ordinal(ordinal)
    plan = cast("dict[str, object]", campaign.document["plan"])
    journal = cast("list[dict[str, object]]", plan["journal"])
    _require(index <= len(journal), "Ordinal is outside the frozen proposal journal")
    row = journal[index - 1]
    _require(row["status"] == "ELIGIBLE", "Only unique eligible candidates can be dispatched")
    return row


def _dispatch_document(raw: bytes) -> dict[str, object]:
    value = _exact(_parse(raw), _DISPATCH_FIELDS, "Candidate dispatch")
    _markers(value, "search_candidate_dispatch_v1")
    for key in ("campaign_id", "plan_id", "protocol_id", "scenario_id"):
        _identity(value[key])
    _ordinal(value["ordinal"])
    _nonce(value["reservation_nonce"])
    _require(isinstance(value["intent"], dict), "Dispatch requires a complete ScenarioIntent")
    intent = _intent(_encode(cast("dict[str, object]", value["intent"])))
    _require(
        intent.document["protocol_id"] == value["protocol_id"],
        "Dispatch protocol differs from intent",
    )
    bindings = cast("dict[str, object]", intent.document["bindings"])
    _require(
        bindings["scenario_id"] == value["scenario_id"], "Dispatch scenario differs from intent"
    )
    return value


@dataclass(frozen=True, slots=True)
class SearchDispatch:
    """Structural identity; load_dispatch also checks its required campaign context."""

    dispatch_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _dispatch_document(self.canonical_bytes)
        _require(
            _identity(self.dispatch_id) == digest(self.canonical_bytes),
            "Dispatch identity differs from its canonical content",
        )

    @property
    def document(self) -> dict[str, object]:
        return _dispatch_document(self.canonical_bytes)


def load_dispatch(raw: bytes, *, campaign: SearchCampaign) -> SearchDispatch:
    checked = _checked_campaign(campaign)
    value = _dispatch_document(raw)
    row = _eligible_row(checked, value["ordinal"])
    campaign_doc = checked.document
    _require(
        value["campaign_id"] == checked.campaign_id
        and value["plan_id"] == campaign_doc["plan_id"]
        and value["protocol_id"] == campaign_doc["protocol_id"]
        and value["scenario_id"] == row["scenario_id"],
        "Dispatch differs from the frozen campaign candidate",
    )
    plan = cast("dict[str, object]", campaign_doc["plan"])
    protocol = cast("dict[str, object]", plan["protocol"])
    assumptions = cast("dict[str, object]", plan["assumptions"])
    source = cast("dict[str, object]", assumptions["bindings"])
    intent = cast("dict[str, object]", value["intent"])
    bindings = cast("dict[str, object]", intent["bindings"])
    _require(
        intent["claim_revision_id"] == protocol["claim_revision_id"]
        and bindings["assumption_id"] == plan["assumption_id"]
        and bindings["development_dataset_id"] == source["development_dataset_id"]
        and bindings["source_normalized_sha256"] == source["normalized_sha256"]
        and bindings["replay_spec_id"] == source["replay_spec_id"],
        "Dispatch intent differs from the frozen source contract",
    )
    return SearchDispatch(digest(raw), raw)


def build_dispatch(
    campaign: SearchCampaign, ordinal: int, nonce: str, intent: ScenarioIntent
) -> SearchDispatch:
    campaign = _checked_campaign(campaign)
    _require(type(intent) is ScenarioIntent, "Dispatch requires an actual ScenarioIntent")
    checked_intent = _intent(intent.canonical_bytes)
    _require(checked_intent.intent_id == intent.intent_id, "Forged scenario intent identity")
    row = _eligible_row(campaign, ordinal)
    raw = _encode(
        {
            "kind": "search_candidate_dispatch_v1",
            "schema_version": 1,
            "campaign_id": campaign.campaign_id,
            "plan_id": campaign.document["plan_id"],
            "protocol_id": campaign.document["protocol_id"],
            "ordinal": _ordinal(ordinal),
            "scenario_id": row["scenario_id"],
            "reservation_nonce": _nonce(nonce),
            "intent": checked_intent.document,
        }
    )
    return load_dispatch(raw, campaign=campaign)


def _checked_dispatch(dispatch: SearchDispatch) -> SearchDispatch:
    _require(type(dispatch) is SearchDispatch, "Expected actual SearchDispatch")
    checked = SearchDispatch(digest(dispatch.canonical_bytes), dispatch.canonical_bytes)
    _require(checked.dispatch_id == dispatch.dispatch_id, "Forged dispatch identity")
    return checked


def _reservation(raw: bytes) -> AttemptReservation:
    try:
        return AttemptReservation(digest(raw), raw)
    except EvidenceValidationError as error:
        raise SearchExecutionValidationError(str(error)) from error


def build_link(dispatch: SearchDispatch, reservation: AttemptReservation) -> bytes:
    dispatch = _checked_dispatch(dispatch)
    _require(type(reservation) is AttemptReservation, "Link requires an original protocol attempt")
    checked = _reservation(reservation.canonical_bytes)
    _require(checked.attempt_id == reservation.attempt_id, "Forged reservation identity")
    source = dispatch.document
    _require(
        checked.protocol_id == source["protocol_id"]
        and checked.document["nonce"] == source["reservation_nonce"],
        "Reservation protocol or nonce differs from dispatch",
    )
    return _encode(
        {
            "kind": "search_candidate_attempt_link_v1",
            "schema_version": 1,
            "dispatch_id": dispatch.dispatch_id,
            "campaign_id": source["campaign_id"],
            "plan_id": source["plan_id"],
            "ordinal": source["ordinal"],
            "scenario_id": source["scenario_id"],
            "reservation": checked.document,
        }
    )


def load_link(raw: bytes, *, dispatch: SearchDispatch) -> AttemptReservation:
    dispatch = _checked_dispatch(dispatch)
    value = _exact(_parse(raw), _LINK_FIELDS, "Candidate attempt link")
    _markers(value, "search_candidate_attempt_link_v1")
    _require(isinstance(value["reservation"], dict), "Link requires a complete reservation")
    reservation = _reservation(_encode(cast("dict[str, object]", value["reservation"])))
    _require(build_link(dispatch, reservation) == raw, "Link differs from its dispatch/reservation")
    return reservation


def _error_code(value: object) -> str | None:
    if value is None:
        return None
    _require(
        isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", value) is not None,
        "Stop error_code must be a bounded lowercase machine code",
    )
    return cast("str", value)


def _message(value: object) -> str | None:
    if value is None:
        return None
    _require(
        isinstance(value, str)
        and 0 < len(value) <= 4_096
        and not any(ord(character) < 32 or ord(character) == 127 for character in value),
        "Stop message must be a nonempty bounded string without control characters",
    )
    try:
        cast("str", value).encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise SearchExecutionValidationError("Stop message requires valid Unicode") from error
    return cast("str", value)


def build_stop(
    campaign: SearchCampaign,
    reason: str,
    *,
    ordinal: int | None = None,
    error_code: str | None = None,
    message: str | None = None,
) -> bytes:
    campaign = _checked_campaign(campaign)
    _require(
        isinstance(reason, str) and reason in _STOP_REASONS, "Unsupported campaign stop reason"
    )
    code, detail = _error_code(error_code), _message(message)
    if reason in _NORMAL_REASONS:
        _require(ordinal is None, "Exhaustion stop cannot identify a failed candidate")
        _require(code is None and detail is None, "Exhaustion stop cannot contain failure details")
        plan = cast("dict[str, object]", campaign.document["plan"])
        counts = cast("dict[str, int]", plan["counts"])
        if reason == "no_eligible_candidates":
            _require(counts["eligible"] == 0, "Plan contains eligible candidates")
        else:
            _require(counts["eligible"] > 0, "Empty eligible set requires no_eligible_candidates")
    elif ordinal is not None:
        _eligible_row(campaign, ordinal)
    else:
        _require(
            reason == "publication_unconfirmed", "Candidate stop requires an eligible ordinal"
        )
    return _encode(
        {
            "kind": "search_campaign_stop_v1",
            "schema_version": 1,
            "campaign_id": campaign.campaign_id,
            "plan_id": campaign.document["plan_id"],
            "protocol_id": campaign.document["protocol_id"],
            "reason": reason,
            "ordinal": ordinal,
            "error_code": code,
            "message": detail,
        }
    )


def load_stop(raw: bytes, *, campaign: SearchCampaign) -> dict[str, object]:
    value = _exact(_parse(raw), _STOP_FIELDS, "Campaign stop")
    _markers(value, "search_campaign_stop_v1")
    rebuilt = build_stop(
        campaign,
        cast("str", value["reason"]),
        ordinal=cast("int | None", value["ordinal"]),
        error_code=cast("str | None", value["error_code"]),
        message=cast("str | None", value["message"]),
    )
    _require(rebuilt == raw, "Stop differs from its campaign declarations")
    return value
