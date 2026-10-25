"""Intent-bound coupled-tape execution records, never baseline claim verdicts."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from tickwitness.domain.assumptions.derivation import (
    CLOCK_PROFILE_ID,
    DerivedReplayView,
    derive_replay_view,
)
from tickwitness.domain.evidence.evaluation import evaluate_replay
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.replay.contracts import ReplayResult

SCENARIO_SCOPE: Mapping[str, object] = MappingProxyType(
    {
        "phase": "development",
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "calibration_status": "uncalibrated",
        "search_performed": False,
        "baseline_claim_evaluated": False,
    }
)
_EVALUATION_LIMIT = 128 * 1024
_INTENT_FIELDS = {
    "kind", "schema_version", "protocol_id", "claim_revision_id", "scope", "bindings",
    "clock_profile_id",
}
_BINDINGS = {
    "development_dataset_id", "source_normalized_sha256", "replay_spec_id", "assumption_id",
    "scenario_id", "derived_view_id", "derived_normalized_sha256",
}
_RECEIPT_FIELDS = {
    "kind", "schema_version", "attempt", "protocol_id", "claim_revision_id",
    "execution_status", "scope", "intent", "bindings",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    _require(isinstance(value, dict) and value.keys() == keys, label + " fields differ")
    return cast("dict[str, object]", value)


def _equal(left: object, right: object, message: str) -> None:
    _require(canonical({"value": left}) == canonical({"value": right}), message)


def _markers(document: dict[str, object], kind: str) -> None:
    _equal(document["kind"], kind, "Unsupported scenario record kind")
    _require(
        type(document["schema_version"]) is int and document["schema_version"] == 1,
        "Unsupported scenario record version",
    )


def _validate_intent(raw: bytes) -> dict[str, object]:
    document = _exact(parse(raw), _INTENT_FIELDS, "Scenario intent")
    _markers(document, "scenario_execution_intent_v1")
    identity(document["protocol_id"])
    identity(document["claim_revision_id"])
    _equal(document["scope"], dict(SCENARIO_SCOPE), "Unsupported scenario scope")
    _equal(document["clock_profile_id"], CLOCK_PROFILE_ID, "Unsupported coupled clock profile")
    bindings = _exact(document["bindings"], _BINDINGS, "Scenario intent bindings")
    for value in bindings.values():
        identity(value)
    return document


@dataclass(frozen=True, slots=True)
class ScenarioIntent:
    intent_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_intent(self.canonical_bytes)
        _require(identity(self.intent_id) == digest(self.canonical_bytes), "Intent identity mismatch")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes)


def _checked_view(view: DerivedReplayView) -> DerivedReplayView:
    _require(isinstance(view, DerivedReplayView), "Intent requires a DerivedReplayView")
    rebuilt = derive_replay_view(view.validated)
    _require(
        rebuilt.canonical_bytes == view.canonical_bytes
        and rebuilt.replay_input == view.replay_input,
        "Scenario view does not reproduce from its source context",
    )
    return rebuilt


def _intent_from_view(view: DerivedReplayView) -> ScenarioIntent:
    validated = view.validated
    source = cast("dict[str, str]", validated.assumptions.document["bindings"])
    _equal(view.document["clock_profile_id"], CLOCK_PROFILE_ID, "View clock profile mismatch")
    document: dict[str, object] = {
        "kind": "scenario_execution_intent_v1",
        "schema_version": 1,
        "protocol_id": validated.protocol.protocol_id,
        "claim_revision_id": validated.protocol.claim_revision_id,
        "scope": dict(SCENARIO_SCOPE),
        "bindings": {
            "development_dataset_id": source["development_dataset_id"],
            "source_normalized_sha256": source["normalized_sha256"],
            "replay_spec_id": source["replay_spec_id"],
            "assumption_id": validated.assumptions.assumption_id,
            "scenario_id": validated.scenario.scenario_id,
            "derived_view_id": view.view_id,
            "derived_normalized_sha256": digest(view.replay_input.normalized_bytes),
        },
        "clock_profile_id": CLOCK_PROFILE_ID,
    }
    raw = canonical(document)
    return ScenarioIntent(digest(raw), raw)


def build_scenario_intent(view: DerivedReplayView) -> ScenarioIntent:
    return _intent_from_view(_checked_view(view))


def load_scenario_intent(raw: bytes) -> ScenarioIntent:
    return ScenarioIntent(digest(raw), raw)


@dataclass(frozen=True, slots=True)
class ScenarioEvaluation:
    view: DerivedReplayView
    result: ReplayResult
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        _require(
            isinstance(self.view, DerivedReplayView) and isinstance(self.result, ReplayResult),
            "Scenario evaluation requires immutable view/result values",
        )
        object.__setattr__(self, "view", _checked_view(self.view))
        intent = _intent_from_view(self.view)
        protocol = self.view.validated.protocol.document
        _equal(self.result.document["engine"], protocol["engine"], "Scenario engine mismatch")
        audited = evaluate_replay(self.view.replay_input, self.result)
        base = audited.document
        _equal(
            base["evaluation_policy"], protocol["evaluation_policy"],
            "Scenario valuation policy mismatch",
        )
        eligible = base["valuation_status"] == "valued"
        value = cast("dict[str, object]", base["valuation"])["net_marked_pnl"] if eligible else None
        raw = canonical(
            {
                "kind": "scenario_evaluation_v1",
                "schema_version": 1,
                "protocol_id": self.view.validated.protocol.protocol_id,
                "claim_revision_id": self.view.validated.protocol.claim_revision_id,
                "intent_id": intent.intent_id,
                "scope": dict(SCENARIO_SCOPE),
                "metric_observation": {
                    "metric": "net_marked_pnl_v1", "unit": "USD",
                    "eligible": eligible, "value": value,
                },
                "replay_evaluation": base,
            }
        )
        parse(raw, limit=_EVALUATION_LIMIT)
        object.__setattr__(self, "canonical_bytes", raw)

    @property
    def evaluation_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=_EVALUATION_LIMIT)


def _attempt_and_intent(document: dict[str, object]) -> tuple[AttemptReservation, ScenarioIntent]:
    attempt = _exact(
        document["attempt"],
        {"kind", "schema_version", "protocol_id", "attempt_index", "nonce",
         "max_wall_seconds", "created_at_utc"},
        "Scenario attempt",
    )
    raw = canonical(attempt)
    reservation = AttemptReservation(digest(raw), raw)
    _require(isinstance(document["intent"], dict), "Scenario record requires a complete intent")
    intent = load_scenario_intent(canonical(cast("dict[str, object]", document["intent"])))
    _equal(document["protocol_id"], reservation.protocol_id, "Scenario attempt protocol mismatch")
    _equal(
        document["protocol_id"], intent.document["protocol_id"], "Scenario intent protocol mismatch"
    )
    return reservation, intent


def _validate_receipt(raw: bytes) -> dict[str, object]:
    document = _exact(parse(raw), _RECEIPT_FIELDS, "Scenario run receipt")
    _markers(document, "scenario_run_receipt_v1")
    _, intent = _attempt_and_intent(document)
    _equal(
        document["claim_revision_id"], intent.document["claim_revision_id"],
        "Scenario claim reference mismatch",
    )
    _equal(document["scope"], intent.document["scope"], "Scenario receipt scope mismatch")
    _require(
        document["execution_status"] in ("completed", "incomplete"),
        "Scenario receipts require audited completed or incomplete execution",
    )
    bindings = _exact(
        document["bindings"], {"replay_result_sha256", "evaluation_sha256"},
        "Scenario receipt bindings",
    )
    for value in bindings.values():
        identity(value)
    return document


@dataclass(frozen=True, slots=True)
class ScenarioRunReceipt:
    run_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_receipt(self.canonical_bytes)
        _require(identity(self.run_id) == digest(self.canonical_bytes), "Scenario receipt ID mismatch")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes)

    @property
    def intent_id(self) -> str:
        return digest(canonical(cast("dict[str, object]", self.document["intent"])))


def build_scenario_run_receipt(document: dict[str, object]) -> ScenarioRunReceipt:
    raw = canonical(document)
    return ScenarioRunReceipt(digest(raw), raw)


def load_scenario_run_receipt(raw: bytes) -> ScenarioRunReceipt:
    return ScenarioRunReceipt(digest(raw), raw)


def load_scenario_failure(raw: bytes) -> dict[str, object]:
    document = _exact(
        parse(raw), {"kind", "schema_version", "attempt", "protocol_id", "intent", "error"},
        "Scenario failure",
    )
    _markers(document, "scenario_attempt_failure_v1")
    _attempt_and_intent(document)
    error = _exact(document["error"], {"code", "message"}, "Scenario failure error")
    for name, maximum in (("code", 128), ("message", 4096)):
        value = error[name]
        _require(
            isinstance(value, str) and 0 < len(value) <= maximum,
            f"Scenario failure {name} is empty or oversized",
        )
    return document


def build_scenario_failure(
    reservation: AttemptReservation, intent: ScenarioIntent, code: str, message: str
) -> bytes:
    _require(
        isinstance(reservation, AttemptReservation) and isinstance(intent, ScenarioIntent),
        "Scenario failure requires immutable reservation and intent",
    )
    raw = canonical(
        {
            "kind": "scenario_attempt_failure_v1",
            "schema_version": 1,
            "attempt": reservation.document,
            "protocol_id": reservation.protocol_id,
            "intent": intent.document,
            "error": {"code": code, "message": message},
        }
    )
    load_scenario_failure(raw)
    return raw
