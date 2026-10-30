"""Original-owner prefix executions and independently audited terminal projections.

These records describe the existing adapter's after-run, before-dispose boundary.
They never export a focus state, checkpoint, complete simulator serialization,
source claim verdict or proof that a reduced input preserves a counterexample.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from tickwitness.domain.evidence.evaluation import evaluate_replay
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.reduction.contracts import (
    MaterializedReduction,
    build_reduction_manifest,
    materialize_reduction,
)
from tickwitness.domain.replay.contracts import ReplayResult
from tickwitness.domain.research_contracts.executable import (
    ENGINE_ID,
    ENGINE_SEMANTIC_ID,
    ENGINE_VERSION,
)

MAX_REDUCTION_RECORD_BYTES = 16 * 1024
MAX_REDUCTION_STATE_AUDIT_BYTES = 128 * 1024
STATE_BOUNDARY = "after_native_run_before_dispose_v1"
REDUCTION_SCOPE: Mapping[str, object] = MappingProxyType(
    {
        "phase": "development",
        "authority": "reduction_prefix_state_audit_only_v1",
        "source_claim_authority_extended": False,
        "budget_owner_changed": False,
    }
)
STATE_AUDIT_FLAGS: Mapping[str, object] = MappingProxyType(
    {
        "from_origin_prefix_replayed": True,
        "state_projection_audited": True,
        "focus_state_captured": False,
        "pre_engine_end_state_captured": False,
        "initial_state_materialized": False,
        "checkpoint_used": False,
        "checkpoint_resume_verified": False,
        "reduced_predicate_evaluated": False,
        "witness_preservation_verified": False,
        "margin_lock_algorithm_certified": False,
    }
)
INTENT_FLAGS: Mapping[str, object] = MappingProxyType(
    {name: False for name in STATE_AUDIT_FLAGS}
)
_INTENT_FIELDS = {
    "kind", "schema_version", "protocol_id", "claim_revision_id", "scope",
    "bindings", "engine", "state_boundary", "flags",
}
_INTENT_BINDINGS = {
    "source_bundle_id", "source_report_id", "source_run_id", "source_finding_protocol_id",
    "preparation_id", "recipe_id", "materialization_sha256", "prefix_context_id",
    "normalized_sha256", "replay_spec_id", "candidate_scenario_id",
    "preparation_manifest_sha256",
}
_RECEIPT_FIELDS = {
    "kind", "schema_version", "attempt", "protocol_id", "claim_revision_id", "scope",
    "intent", "execution_status", "bindings",
}
type Row = dict[str, object]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _same(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _markers(document: Row, kind: str) -> None:
    _same([document["kind"], document["schema_version"]], [kind, 1], "Unsupported reduction record")


def _checked_materialization(materialized: MaterializedReduction) -> MaterializedReduction:
    _require(type(materialized) is MaterializedReduction, "Reduction intent needs an actual materialization")
    rebuilt = materialize_reduction(materialized.recipe, source=materialized.source)
    _require(
        rebuilt.canonical_bytes == materialized.canonical_bytes
        and rebuilt.replay_input == materialized.replay_input
        and rebuilt.prepared == materialized.prepared,
        "Reduction materialization does not reproduce from its full source",
    )
    return rebuilt


def _intent_document(materialized: MaterializedReduction) -> Row:
    recipe, descriptor = materialized.recipe.document, materialized.document
    source = cast("Row", recipe["source"])
    candidate = cast("Row", descriptor["candidate"])
    protocol = materialized.source.validation.protocol
    manifest = build_reduction_manifest(
        {
            "recipe": materialized.recipe.canonical_bytes,
            "materialization": materialized.canonical_bytes,
            "normalized": materialized.replay_input.normalized_bytes,
        }
    )
    preparation_id = digest(manifest)
    return {
        "kind": "reduction_execution_intent_v1", "schema_version": 1,
        "protocol_id": protocol.protocol_id, "claim_revision_id": protocol.claim_revision_id,
        "scope": dict(REDUCTION_SCOPE),
        "bindings": {
            "source_bundle_id": source["bundle_id"], "source_report_id": source["report_id"],
            "source_run_id": source["source_run_id"],
            "source_finding_protocol_id": source["finding_protocol_id"],
            "preparation_id": preparation_id, "recipe_id": materialized.recipe.recipe_id,
            "materialization_sha256": digest(materialized.canonical_bytes),
            "prefix_context_id": descriptor["prefix_context_id"],
            "normalized_sha256": digest(materialized.replay_input.normalized_bytes),
            "replay_spec_id": materialized.replay_input.spec.spec_id,
            "candidate_scenario_id": candidate["scenario_id"],
            "preparation_manifest_sha256": preparation_id,
        },
        "engine": protocol.document["engine"], "state_boundary": STATE_BOUNDARY,
        "flags": dict(INTENT_FLAGS),
    }


def _validate_intent(raw: bytes) -> Row:
    document = _exact(parse(raw, limit=MAX_REDUCTION_RECORD_BYTES), _INTENT_FIELDS, "Reduction intent")
    _markers(document, "reduction_execution_intent_v1")
    identity(document["protocol_id"])
    identity(document["claim_revision_id"])
    bindings = _exact(document["bindings"], _INTENT_BINDINGS, "Reduction intent bindings")
    for value in bindings.values():
        identity(value)
    _same(bindings["preparation_id"], bindings["preparation_manifest_sha256"], "Preparation manifest identity differs")
    _same(document["scope"], dict(REDUCTION_SCOPE), "Reduction intent cannot extend source authority")
    _same(document["flags"], dict(INTENT_FLAGS), "Intent cannot assert a completed execution or state audit")
    _same(document["state_boundary"], STATE_BOUNDARY, "Unsupported reduction state boundary")
    _same(document["engine"], {"id": ENGINE_ID, "version": ENGINE_VERSION, "semantic_id": ENGINE_SEMANTIC_ID}, "Reduction engine differs from the supported original profile")
    return document


@dataclass(frozen=True, slots=True)
class ReductionExecutionIntent:
    intent_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_intent(self.canonical_bytes)
        _require(identity(self.intent_id) == digest(self.canonical_bytes), "Reduction intent identity differs")

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_REDUCTION_RECORD_BYTES)


def build_reduction_intent(materialized: MaterializedReduction) -> ReductionExecutionIntent:
    try:
        raw = canonical(_intent_document(_checked_materialization(materialized)))
        return ReductionExecutionIntent(digest(raw), raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise EvidenceValidationError("Cannot bind reduction intent: " + str(error)) from error


def load_reduction_intent(raw: bytes) -> ReductionExecutionIntent:
    return ReductionExecutionIntent(digest(raw), raw)


@dataclass(frozen=True, slots=True)
class ReductionStateAudit:
    materialized: MaterializedReduction
    result: ReplayResult
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        try:
            materialized = _checked_materialization(self.materialized)
            _require(type(self.result) is ReplayResult, "Reduction audit needs an actual replay result")
            result = ReplayResult(self.result.canonical_bytes)
            raw_result = result.document
            _require(raw_result["execution_status"] in ("completed", "incomplete"), "Failed replay cannot issue a successful reduction state audit")
            completeness = cast("Row", raw_result["completeness"])
            count = len(materialized.prepared.events)
            _same([completeness["input_records"], completeness["processed_records"]], [count, count], "State audit requires every retained prefix event to be processed")
            intent = load_reduction_intent(canonical(_intent_document(materialized)))
            _same(raw_result["engine"], intent.document["engine"], "Reduction result engine differs from original owner")
            evaluation = evaluate_replay(materialized.replay_input, result)
            accounts = cast("list[Row]", raw_result["account_trace"])
            _require(bool(accounts) and accounts[0]["kind"] == "initial_account_snapshot" and accounts[-1]["kind"] == "final_account_snapshot", "Reduction state audit lacks actual initial or terminal accounts")
            descriptor = materialized.document
            retained = cast("Row", descriptor["retained"])
            candidate = cast("Row", descriptor["candidate"])
            bindings = cast("Row", intent.document["bindings"])
            document: Row = {
                "kind": "reduction_state_audit_v1", "schema_version": 1,
                "protocol_id": intent.document["protocol_id"],
                "claim_revision_id": intent.document["claim_revision_id"],
                "intent_id": intent.intent_id, "scope": dict(REDUCTION_SCOPE),
                "state_boundary": STATE_BOUNDARY, "audit_status": "verified",
                "execution_status": raw_result["execution_status"],
                "bindings": {
                    "preparation_id": bindings["preparation_id"],
                    "recipe_id": bindings["recipe_id"],
                    "prefix_context_id": bindings["prefix_context_id"],
                    "normalized_sha256": bindings["normalized_sha256"],
                    "replay_spec_id": bindings["replay_spec_id"],
                    "replay_result_sha256": digest(result.canonical_bytes),
                },
                "coverage": {
                    "source_event_count": candidate["full_event_count"],
                    "retained_event_count": retained["event_count"],
                    "processed_records": completeness["processed_records"],
                    "warmup_event_count": retained["warmup_event_count"],
                    "origin_ref": retained["origin_ref"], "focus_ref": retained["focus_ref"],
                    "through_ref": retained["through_ref"],
                },
                "initial_account": accounts[0],
                "terminal_state": {
                    "account": accounts[-1], "open_orders": completeness["open_orders"],
                    "pending_commands": completeness["pending_commands"],
                    "stop_reason": completeness["stop_reason"],
                },
                "cash_lock_verification": "nonnegative_and_total_equals_free_plus_locked_v1",
                "replay_evaluation": evaluation.document, "flags": dict(STATE_AUDIT_FLAGS),
            }
            raw = canonical(document)
            parse(raw, limit=MAX_REDUCTION_STATE_AUDIT_BYTES)
            object.__setattr__(self, "materialized", materialized)
            object.__setattr__(self, "result", result)
            object.__setattr__(self, "canonical_bytes", raw)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise EvidenceValidationError("Cannot audit reduction terminal state: " + str(error)) from error

    @property
    def audit_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_REDUCTION_STATE_AUDIT_BYTES)


def _attempt_and_intent(document: Row) -> tuple[AttemptReservation, ReductionExecutionIntent]:
    _require(isinstance(document["attempt"], dict) and isinstance(document["intent"], dict), "Reduction outcome requires complete reservation and intent objects")
    raw_attempt = canonical(cast("Row", document["attempt"]))
    reservation = AttemptReservation(digest(raw_attempt), raw_attempt)
    intent = load_reduction_intent(canonical(cast("Row", document["intent"])))
    _same([document["protocol_id"], intent.document["protocol_id"]], [reservation.protocol_id] * 2, "Reduction outcome belongs to another original owner")
    return reservation, intent


def _validate_receipt(raw: bytes) -> Row:
    document = _exact(parse(raw, limit=MAX_REDUCTION_RECORD_BYTES), _RECEIPT_FIELDS, "Reduction run receipt")
    _markers(document, "reduction_run_receipt_v1")
    _reservation, intent = _attempt_and_intent(document)
    _same(document["claim_revision_id"], intent.document["claim_revision_id"], "Reduction receipt claim lineage differs")
    _same(document["scope"], intent.document["scope"], "Reduction receipt scope differs")
    _require(document["execution_status"] in ("completed", "incomplete"), "Reduction receipts require an audited completed or incomplete run")
    bindings = _exact(document["bindings"], {"replay_result_sha256", "state_audit_sha256"}, "Reduction receipt bindings")
    for value in bindings.values():
        identity(value)
    return document


@dataclass(frozen=True, slots=True)
class ReductionRunReceipt:
    run_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _validate_receipt(self.canonical_bytes)
        _require(identity(self.run_id) == digest(self.canonical_bytes), "Reduction run identity differs")

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_REDUCTION_RECORD_BYTES)

    @property
    def intent_id(self) -> str:
        return digest(canonical(cast("Row", self.document["intent"])))


def build_reduction_run_receipt(document: Row) -> ReductionRunReceipt:
    raw = canonical(document)
    return ReductionRunReceipt(digest(raw), raw)


def load_reduction_run_receipt(raw: bytes) -> ReductionRunReceipt:
    return ReductionRunReceipt(digest(raw), raw)


def load_reduction_failure(raw: bytes) -> Row:
    document = _exact(parse(raw, limit=MAX_REDUCTION_RECORD_BYTES), {"kind", "schema_version", "attempt", "protocol_id", "intent", "error"}, "Reduction failure")
    _markers(document, "reduction_attempt_failure_v1")
    _attempt_and_intent(document)
    error = _exact(document["error"], {"code", "message"}, "Reduction error")
    code, message = error["code"], error["message"]
    _require(isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is not None, "Reduction failure code is not a bounded identifier")
    _require(isinstance(message, str) and 0 < len(message) <= 4096, "Reduction failure message is empty or oversized")
    return document


def build_reduction_failure(reservation: AttemptReservation, intent: ReductionExecutionIntent, code: str, message: str) -> bytes:
    _require(type(reservation) is AttemptReservation and type(intent) is ReductionExecutionIntent, "Reduction failure requires original reservation and immutable intent")
    raw = canonical({"kind": "reduction_attempt_failure_v1", "schema_version": 1, "attempt": reservation.document, "protocol_id": reservation.protocol_id, "intent": intent.document, "error": {"code": code, "message": message}})
    load_reduction_failure(raw)
    return raw
