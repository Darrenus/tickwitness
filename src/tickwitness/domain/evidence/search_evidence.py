"""Strict closed role inventory for portable scoped-search evidence.

The snapshot describes supplied committed-record content and explicit absence.
It does not authenticate a producer, publication time or an exhaustive history.
"""

import re
from collections.abc import Mapping
from typing import cast

from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.scenario_records import (
    load_scenario_failure,
    load_scenario_intent,
    load_scenario_run_receipt,
)
from tickwitness.domain.research_contracts.search_finding_protocol import load_search_finding_protocol
from tickwitness.domain.search.budgets import load_allocation, load_budget_stop, load_campaign_budget
from tickwitness.domain.search.execution import load_campaign, load_dispatch, load_link, load_stop

MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 4096
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
FIXED_ROLE_LIMITS = {
    "finding_protocol": 3 * 1024 * 1024,
    "snapshot": MAX_SNAPSHOT_BYTES,
    "dataset_manifest": 64 * 1024,
    "raw": 8 * 1024 * 1024,
    "normalized": 8 * 1024 * 1024,
    "report": 4 * 1024 * 1024,
    "budget": 64 * 1024,
    "finding_report": 8 * 1024 * 1024,
    "diagnostics": 8 * 1024 * 1024,
}
REQUIRED_ROLES = frozenset(FIXED_ROLE_LIMITS)
_OPTIONAL_LIMITS = {"outer_stop": 64 * 1024, "campaign": 4 * 1024 * 1024, "inner_stop": 64 * 1024}
_NUMBERED = re.compile(r"(allocation|reservation)/([0-9]{4})\Z")
_CANDIDATE = re.compile(r"candidate/([0-9]{4})/(dispatch|link|result)\Z")
_ATTEMPT = re.compile(r"attempt/([0-9a-f]{64})/(intent|outcome)\Z")
_CAS = re.compile(r"cas/([0-9a-f]{64})\Z")
_FIELDS = {
    "kind", "schema_version", "finding_protocol_id", "plan_id", "protocol_id", "dataset_id",
    "budget_id", "producer_version", "allocations", "outer_stop", "inner_campaign", "inner_stop",
    "ledger_prefix_observed", "reservations", "candidates", "attempts", "cas",
}
type Row = dict[str, object]


class SearchEvidenceValidationError(EvidenceValidationError):
    """A portable search inventory or referenced committed-record closure differs."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SearchEvidenceValidationError(message)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _same(actual: object, expected: object, label: str) -> None:
    if isinstance(actual, bytes) or isinstance(expected, bytes):
        _require(type(actual) is bytes and type(expected) is bytes and actual == expected, label)
        return
    _require(canonical({"v": actual}) == canonical({"v": expected}), label)


def _ordinal(value: object, label: str) -> int:
    _require(type(value) is int and 1 <= value <= 1024, label + " must be an integer in 1..1024")
    return cast("int", value)


def role_limit(role: str) -> int:
    """Return the fixed profile cap; no caller-defined path or role is accepted."""
    _require(type(role) is str, "Search evidence role must be text")
    if role in FIXED_ROLE_LIMITS:
        return FIXED_ROLE_LIMITS[role]
    if role in _OPTIONAL_LIMITS:
        return _OPTIONAL_LIMITS[role]
    numbered = _NUMBERED.fullmatch(role)
    if numbered is not None and 1 <= int(numbered[2]) <= 1024:
        return (16 if numbered[1] == "reservation" else 64) * 1024
    candidate = _CANDIDATE.fullmatch(role)
    if candidate is not None and 1 <= int(candidate[1]) <= 1024:
        return 16 * 1024 * 1024 if candidate[2] == "result" else 64 * 1024
    if _ATTEMPT.fullmatch(role):
        return 16 * 1024
    if _CAS.fullmatch(role):
        return 16 * 1024 * 1024
    raise SearchEvidenceValidationError("Unsupported search evidence role: " + role)


def _payload(artifacts: Mapping[str, bytes], *, require_derived: bool) -> dict[str, bytes]:
    _require(isinstance(artifacts, Mapping), "Search artifacts must be a mapping")
    contents = dict(artifacts)
    required = REQUIRED_ROLES if require_derived else REQUIRED_ROLES - {"finding_report", "diagnostics"}
    missing = required - contents.keys()
    _require(not missing, "Missing sealed role: " + ", ".join(sorted(missing)))
    unique: dict[str, int] = {}
    references: Row = {}
    for role, raw in contents.items():
        limit = role_limit(role)
        _require(type(raw) is bytes and 0 < len(raw) <= limit, "Empty or oversized sealed role: " + role)
        sha = digest(raw)
        unique[sha] = len(raw)
        references[role] = {"sha256": sha, "size_bytes": len(raw), "ref": "objects/sha256/" + sha}
    manifest = canonical({"kind": "search_evidence_bundle_v1", "schema_version": 1,
                          "scope": "development_scoped_search_evidence_v1", "roles": references})
    _require(len(manifest) <= MAX_MANIFEST_BYTES, "Search manifest exceeds its byte bound")
    _require(len(unique) + 1 <= MAX_FILES, "Search evidence exceeds its file bound")
    _require(len(manifest) + sum(unique.values()) <= MAX_TOTAL_BYTES, "Search evidence exceeds aggregate byte bound")
    return contents


def validate_snapshot(artifacts: Mapping[str, bytes], *, require_derived: bool = True) -> Row:
    """Check exact supplied record roles, references, and explicit absence flags.

    Source-derived intent/economics and findings are independently reaudited by
    application/search_evidence_verification through readonly memory ports.
    """
    try:
        contents = _payload(artifacts, require_derived=require_derived)
        snapshot = _exact(parse(contents["snapshot"], limit=MAX_SNAPSHOT_BYTES), _FIELDS, "Search snapshot")
        _same(snapshot["kind"], "search_evidence_snapshot_v1", "Unsupported search snapshot")
        _same(snapshot["schema_version"], 1, "Unsupported search snapshot schema")
        _require(canonical(snapshot) == contents["snapshot"], "Search snapshot is not canonical JSON")
        authority = load_search_finding_protocol(contents["finding_protocol"])
        plan = authority.plan
        pdoc = plan.document
        protocol = cast("Row", pdoc["protocol"])
        dataset_id = cast("Row", protocol["datasets"])["development"]
        budget = load_campaign_budget(contents["budget"])
        for name, expected in (("finding_protocol_id", authority.protocol_id), ("plan_id", plan.plan_id),
                               ("protocol_id", pdoc["protocol_id"]), ("dataset_id", dataset_id),
                               ("budget_id", budget.budget_id)):
            identity(snapshot[name])
            _same(snapshot[name], expected, "Search snapshot binding differs: " + name)
        _same([budget.document["plan_id"], budget.document["protocol_id"]],
              [plan.plan_id, pdoc["protocol_id"]], "Budget differs from the search subject")
        version = snapshot["producer_version"]
        _require(isinstance(version, str) and 0 < len(version) <= 64
                 and not any(ord(char) < 32 or ord(char) == 127 for char in version), "Invalid declared producer version")
        for name in ("outer_stop", "inner_campaign", "inner_stop", "ledger_prefix_observed"):
            _require(type(snapshot[name]) is bool, "Snapshot presence flags must be boolean")
        _require(snapshot["inner_campaign"] is snapshot["ledger_prefix_observed"], "Inner campaign requires its observed reservation prefix")
        _require(not snapshot["inner_stop"] or snapshot["inner_campaign"] is True, "Inner stop has no campaign")
        expected_roles = set(REQUIRED_ROLES)
        if not require_derived:
            expected_roles -= {"finding_report", "diagnostics"} - contents.keys()
        for flag, role in (("outer_stop", "outer_stop"), ("inner_campaign", "campaign"), ("inner_stop", "inner_stop")):
            if snapshot[flag]:
                expected_roles.add(role)
        if snapshot["outer_stop"]:
            load_budget_stop(contents["outer_stop"], budget=budget)
        campaign = load_campaign(contents["campaign"]) if snapshot["inner_campaign"] else None
        if campaign is not None:
            _same(canonical(cast("Row", campaign.document["plan"])), plan.canonical_bytes, "Inner campaign has another plan")
            if snapshot["inner_stop"]:
                load_stop(contents["inner_stop"], campaign=campaign)
        eligible = [row for row in cast("list[Row]", pdoc["journal"]) if row["status"] == "ELIGIBLE"]
        allocation_value = snapshot["allocations"]
        _require(type(allocation_value) is list and len(allocation_value) <= 100, "Invalid allocation inventory")
        allocations = cast("list[object]", allocation_value)
        _require(len(allocations) <= len(eligible), "Admissions exceed eligible candidates")
        for index, value in enumerate(allocations, 1):
            ordinal = _ordinal(value, "Allocation ordinal")
            _same(ordinal, eligible[index - 1]["ordinal"], "Admissions are not the eligible prefix")
            role = f"allocation/{ordinal:04}"
            expected_roles.add(role)
            record = load_allocation(contents[role], budget=budget)
            _same([record["index"], record["ordinal"]], [index, ordinal], "Allocation identity differs")
        reservations_value = snapshot["reservations"]
        _require(type(reservations_value) is list and len(reservations_value) <= 100, "Invalid reservation inventory")
        reservation_rows = cast("list[object]", reservations_value)
        reservations: dict[str, AttemptReservation] = {}
        ordered_reservations: list[AttemptReservation] = []
        necessary_cas: set[str] = set()
        limits = cast("Row", protocol["budget"])
        _require(len(reservation_rows) <= cast("int", limits["max_attempts"]), "Reservation prefix exceeds original budget")
        for index, value in enumerate(reservation_rows, 1):
            row = _exact(value, {"index", "attempt_id"}, "Reservation inventory entry")
            _same(row["index"], index, "Reservation indexes are not a complete prefix")
            attempt_id = identity(row["attempt_id"])
            role = f"reservation/{index:04}"
            expected_roles.add(role)
            reservation = AttemptReservation(attempt_id, contents[role])
            _same([reservation.protocol_id, reservation.attempt_index, reservation.document["max_wall_seconds"]],
                  [pdoc["protocol_id"], index, limits["max_wall_seconds"]], "Reservation differs from original owner/slot/budget")
            _require(attempt_id not in reservations, "Duplicate reservation identity")
            reservations[attempt_id] = reservation
            ordered_reservations.append(reservation)
            necessary_cas.add(attempt_id)
        candidate_value = snapshot["candidates"]
        _require(type(candidate_value) is list and len(candidate_value) == len(eligible), "Snapshot must list every eligible candidate")
        matched: set[str] = set()
        candidates = cast("list[object]", candidate_value)
        for value, proposal in zip(candidates, eligible, strict=True):
            row = _exact(value, {"ordinal", "dispatch", "link", "result"}, "Candidate inventory entry")
            ordinal = _ordinal(row["ordinal"], "Candidate ordinal")
            _same(ordinal, proposal["ordinal"], "Candidate inventory differs from the complete plan")
            for name in ("dispatch", "link", "result"):
                _require(type(row[name]) is bool, "Candidate presence flags must be boolean")
                if row[name]:
                    expected_roles.add(f"candidate/{ordinal:04}/{name}")
            _require(not row["link"] or row["dispatch"] is True, "Candidate link has no dispatch")
            _require(not row["result"] or row["link"] is True, "Captured result has no link")
            if row["dispatch"]:
                if campaign is None:
                    raise SearchEvidenceValidationError("Dispatch has no inner campaign")
                dispatch = load_dispatch(contents[f"candidate/{ordinal:04}/dispatch"], campaign=campaign)
                _same(dispatch.document["ordinal"], ordinal, "Dispatch ordinal differs")
                nonce_matches = [item for item in ordered_reservations if item.document["nonce"] == dispatch.document["reservation_nonce"]]
                _require(len(nonce_matches) <= 1, "Dispatch nonce matches multiple original slots")
                if nonce_matches:
                    matched.add(nonce_matches[0].attempt_id)
                if row["link"]:
                    link = load_link(contents[f"candidate/{ordinal:04}/link"], dispatch=dispatch)
                    _require(bool(nonce_matches) and link == nonce_matches[0], "Candidate link differs from actual selected slot")
        attempts_value = snapshot["attempts"]
        _require(type(attempts_value) is list, "Attempt inventory must be a list")
        selected = [item for item in ordered_reservations if item.attempt_id in matched]
        _require(len(attempts_value) == len(selected), "Attempt inventory differs from selected dispatches")
        for value, reservation in zip(cast("list[object]", attempts_value), selected, strict=True):
            row = _exact(value, {"attempt_id", "intent", "outcome"}, "Attempt inventory entry")
            attempt_id = reservation.attempt_id
            _same(row["attempt_id"], attempt_id, "Attempt inventory is not ordered by original slot")
            for name in ("intent", "outcome"):
                _require(type(row[name]) is bool, "Attempt presence flags must be boolean")
            _require(not row["outcome"] or row["intent"] is True, "Committed outcome lacks committed intent")
            if row["intent"]:
                role = f"attempt/{attempt_id}/intent"
                expected_roles.add(role)
                intent = load_scenario_intent(contents[role])
                necessary_cas.add(intent.intent_id)
                _same(intent.document["protocol_id"], pdoc["protocol_id"], "Selected intent has another owner")
                bindings = cast("Row", intent.document["bindings"])
                for name in ("assumption_id", "scenario_id", "derived_view_id", "derived_normalized_sha256"):
                    necessary_cas.add(identity(bindings[name]))
            if row["outcome"]:
                role = f"attempt/{attempt_id}/outcome"
                expected_roles.add(role)
                raw = contents[role]
                document = parse(raw)
                if document.get("kind") == "scenario_attempt_failure_v1":
                    outcome = load_scenario_failure(raw)
                else:
                    receipt = load_scenario_run_receipt(raw)
                    outcome = receipt.document
                    bindings = cast("Row", outcome["bindings"])
                    necessary_cas.add(identity(bindings["replay_result_sha256"]))
                    necessary_cas.add(identity(bindings["evaluation_sha256"]))
                _same(canonical(cast("Row", outcome["attempt"])), reservation.canonical_bytes, "Outcome has another reservation")
                _same(canonical(cast("Row", outcome["intent"])), contents[f"attempt/{attempt_id}/intent"], "Outcome differs from committed intent")
                necessary_cas.add(digest(raw))
        cas_value = snapshot["cas"]
        _require(type(cas_value) is list and all(type(item) is str for item in cas_value), "CAS inventory must be a list of identities")
        _same(cas_value, sorted(necessary_cas), "CAS inventory omits necessary closure or contains unrelated objects")
        for sha in necessary_cas:
            role = "cas/" + sha
            expected_roles.add(role)
            _require(digest(contents[role]) == sha, "CAS content address differs: " + role)
        for index, reservation in enumerate(ordered_reservations, 1):
            _same(contents[f"reservation/{index:04}"], contents["cas/" + reservation.attempt_id], "Reservation CAS closure differs")
        for value in cast("list[Row]", attempts_value):
            for name in ("intent", "outcome"):
                if value[name]:
                    role = f"attempt/{value['attempt_id']}/{name}"
                    _same(contents[role], contents["cas/" + digest(contents[role])], "Selected " + name + " CAS closure differs")
        if not snapshot["inner_campaign"]:
            _require(not allocations and not reservations_value and not attempts_value and not cas_value,
                     "Absent inner campaign cannot claim an observed execution ledger")
            _require(all(not any(cast("Row", item)[name] for name in ("dispatch", "link", "result")) for item in candidates), "Absent inner campaign contains candidate evidence")
        _require(contents.keys() == expected_roles, "Search evidence roles differ from the exact snapshot closure")
        return snapshot
    except SearchEvidenceValidationError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise SearchEvidenceValidationError("Invalid sealed search snapshot: " + str(error)) from error
