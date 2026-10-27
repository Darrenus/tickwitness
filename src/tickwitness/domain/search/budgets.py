"""Frozen campaign limits and conservative, nonrefundable admission records.

The byte contract covers newly written managed file payloads. It is not an OS
filesystem-block quota, runtime-cache quota, or a statement about research truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError, _parse

CONTROL_RESERVE_BYTES = 32 * 1024 * 1024
CANDIDATE_RESERVE_BYTES = 64 * 1024 * 1024
TERMINAL_RESERVE_BYTES = 64 * 1024
MAX_CAMPAIGN_BUDGET_BYTES = 64 * 1024
_REQUEST_FIELDS = {"kind", "schema_version", "max_evaluations", "max_wall_time_ms", "max_storage_bytes"}
_BUDGET_FIELDS = {
    "kind", "schema_version", "plan_id", "protocol_id", "nonce", "profile", "limits", "accounting", "scope"
}
_ALLOCATION_FIELDS = {
    "kind", "schema_version", "budget_id", "plan_id", "protocol_id", "ordinal", "index",
    "candidate_reserve_bytes", "reserved_storage_bytes",
}
_STOP_FIELDS = {
    "kind", "schema_version", "budget_id", "plan_id", "protocol_id", "reason", "exit_code",
    "elapsed_ns", "message",
}
_REASONS = {
    "completed", "evaluation_limit", "storage_limit", "time_limit", "execution_stopped",
    "execution_unfinalized", "worker_failed", "publication_unconfirmed",
}
_ACCOUNTING: dict[str, object] = {
    "control_reserve_bytes": CONTROL_RESERVE_BYTES,
    "candidate_reserve_bytes": CANDIDATE_RESERVE_BYTES,
    "terminal_reserve_bytes": TERMINAL_RESERVE_BYTES,
    "storage_policy": "managed_new_file_payloads_v1",
    "admission_policy": "nonrefundable_fixed_candidate_envelope_v1",
}
_SCOPE: dict[str, object] = {
    "phase": "development",
    "claim_evaluated": False,
    "findings_issued": False,
    "confirmation_accessed": False,
    "physical_filesystem_blocks_certified": False,
    "full_trial_history_certified": False,
    "clock_authenticity_certified": False,
}


class CampaignBudgetValidationError(EvidenceValidationError):
    """A frozen limit or its immutable admission/termination record is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CampaignBudgetValidationError(message)


def _integer(value: object, minimum: int, maximum: int, label: str) -> int:
    _require(type(value) is int and minimum <= value <= maximum,
             f"{label} must be an integer in [{minimum}, {maximum}]")
    return cast("int", value)


def _exact(value: object, fields: set[str], label: str) -> dict[str, object]:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("dict[str, object]", value)


def _id(value: object) -> str:
    try:
        return identity(value)
    except EvidenceValidationError as error:
        raise CampaignBudgetValidationError(str(error)) from error


def _nonce(value: object) -> str:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None,
             "Budget nonce must be 32 lowercase hexadecimal characters")
    return cast("str", value)


def _markers(value: dict[str, object], kind: str) -> None:
    _require(value["kind"] == kind, "Unsupported campaign budget record kind")
    _integer(value["schema_version"], 1, 1, "schema_version")


def _read(raw: bytes) -> dict[str, object]:
    try:
        return parse(raw, limit=MAX_CAMPAIGN_BUDGET_BYTES)
    except EvidenceValidationError as error:
        raise CampaignBudgetValidationError(str(error)) from error


def _encode(value: dict[str, object]) -> bytes:
    try:
        return canonical(value)
    except EvidenceValidationError as error:
        raise CampaignBudgetValidationError(str(error)) from error


def _limits(value: dict[str, object]) -> dict[str, object]:
    return {
        "max_evaluations": _integer(value["max_evaluations"], 1, 100, "max_evaluations"),
        "max_wall_time_ms": _integer(value["max_wall_time_ms"], 1, 3_600_000, "max_wall_time_ms"),
        "max_storage_bytes": _integer(value["max_storage_bytes"], CONTROL_RESERVE_BYTES,
                                      16 * 1024 * 1024 * 1024, "max_storage_bytes"),
    }


def _document(request: dict[str, object], *, plan_id: str, protocol_id: str, nonce: str) -> dict[str, object]:
    _exact(request, _REQUEST_FIELDS, "Campaign budget request")
    _markers(request, "campaign_budget_request_v1")
    return {
        "kind": "campaign_budget_v1", "schema_version": 1,
        "plan_id": _id(plan_id), "protocol_id": _id(protocol_id), "nonce": _nonce(nonce),
        "profile": "supervised_search_campaign_v1", "limits": _limits(request),
        "accounting": dict(_ACCOUNTING), "scope": dict(_SCOPE),
    }


def _validated(raw: bytes) -> str:
    value = _exact(_read(raw), _BUDGET_FIELDS, "Frozen campaign budget")
    _markers(value, "campaign_budget_v1")
    limits = _exact(value["limits"], {"max_evaluations", "max_wall_time_ms", "max_storage_bytes"}, "Limits")
    request = {"kind": "campaign_budget_request_v1", "schema_version": 1, **limits}
    expected = _document(request, plan_id=_id(value["plan_id"]), protocol_id=_id(value["protocol_id"]),
                         nonce=_nonce(value["nonce"]))
    _require(_encode(expected) == raw, "Campaign budget does not reproduce from its declarations")
    return digest(raw)


@dataclass(frozen=True, slots=True)
class CampaignBudget:
    budget_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _require(_id(self.budget_id) == _validated(self.canonical_bytes), "Budget identity mismatch")

    @property
    def document(self) -> dict[str, object]:
        return _read(self.canonical_bytes)


def build_campaign_budget(raw: bytes, *, plan_id: str, protocol_id: str, nonce: str) -> CampaignBudget:
    try:
        request = _parse(raw)
    except ProtocolValidationError as error:
        raise CampaignBudgetValidationError(str(error)) from error
    encoded = _encode(_document(request, plan_id=plan_id, protocol_id=protocol_id, nonce=nonce))
    return CampaignBudget(digest(encoded), encoded)


def load_campaign_budget(raw: bytes) -> CampaignBudget:
    return CampaignBudget(_validated(raw), raw)


def _checked(budget: CampaignBudget) -> CampaignBudget:
    _require(type(budget) is CampaignBudget, "Expected an actual CampaignBudget")
    checked = load_campaign_budget(budget.canonical_bytes)
    _require(checked.budget_id == budget.budget_id, "Forged campaign budget identity")
    return checked


def build_allocation(budget: CampaignBudget, ordinal: int, index: int) -> bytes:
    budget = _checked(budget)
    document = budget.document
    limits = cast("dict[str, int]", document["limits"])
    _integer(ordinal, 1, 1_024, "ordinal")
    _integer(index, 1, limits["max_evaluations"], "allocation index")
    reserved = CONTROL_RESERVE_BYTES + index * CANDIDATE_RESERVE_BYTES
    _require(reserved <= limits["max_storage_bytes"], "Allocation exceeds frozen storage admission")
    return _encode({
        "kind": "campaign_allocation_v1", "schema_version": 1,
        "budget_id": budget.budget_id, "plan_id": document["plan_id"],
        "protocol_id": document["protocol_id"], "ordinal": ordinal, "index": index,
        "candidate_reserve_bytes": CANDIDATE_RESERVE_BYTES, "reserved_storage_bytes": reserved,
    })


def load_allocation(raw: bytes, *, budget: CampaignBudget) -> dict[str, object]:
    document = _exact(_read(raw), _ALLOCATION_FIELDS, "Campaign allocation")
    _markers(document, "campaign_allocation_v1")
    expected = build_allocation(budget, cast("int", document["ordinal"]), cast("int", document["index"]))
    _require(expected == raw, "Allocation differs from the frozen budget")
    return document


def build_budget_stop(
    budget: CampaignBudget, reason: str, *, exit_code: int, elapsed_ns: int, message: str | None = None,
) -> bytes:
    budget = _checked(budget)
    _require(isinstance(reason, str) and reason in _REASONS, "Unsupported campaign budget stop reason")
    _integer(exit_code, 0, 255, "exit_code")
    _integer(elapsed_ns, 0, (1 << 63) - 1, "elapsed_ns")
    if reason == "completed":
        _require(exit_code == 0, "Completed stop requires exit zero")
    elif reason in ("evaluation_limit", "storage_limit", "time_limit"):
        _require(exit_code == 8, "A resource limit requires exit eight")
    elif reason in ("publication_unconfirmed", "execution_unfinalized"):
        _require(exit_code == 3, "Uncertain publication or finalization requires exit three")
    elif reason == "worker_failed":
        _require(exit_code == 7, "Worker failure requires exit seven")
    else:
        _require(exit_code in (3, 6, 7, 8), "Execution stop requires a supported inner exit")
    if message is not None:
        _require(isinstance(message, str) and 0 < len(message) <= 4_096,
                 "Stop message must be a nonempty bounded string")
        _require(not any(ord(character) < 32 or ord(character) == 127 for character in message),
                 "Stop message cannot contain control characters")
    return _encode({
        "kind": "campaign_budget_stop_v1", "schema_version": 1,
        "budget_id": budget.budget_id, "plan_id": budget.document["plan_id"],
        "protocol_id": budget.document["protocol_id"], "reason": reason,
        "exit_code": exit_code, "elapsed_ns": elapsed_ns, "message": message,
    })


def load_budget_stop(raw: bytes, *, budget: CampaignBudget) -> dict[str, object]:
    document = _exact(_read(raw), _STOP_FIELDS, "Campaign budget stop")
    _markers(document, "campaign_budget_stop_v1")
    expected = build_budget_stop(
        budget, cast("str", document["reason"]), exit_code=cast("int", document["exit_code"]),
        elapsed_ns=cast("int", document["elapsed_ns"]), message=cast("str | None", document["message"]),
    )
    _require(expected == raw, "Budget stop differs from its frozen campaign")
    return document
