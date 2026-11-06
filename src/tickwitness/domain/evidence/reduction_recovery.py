"""Bounded observations of original attempt recovery, without execution authority.

The application reaudits source bytes and the live ledger. This pure document
checks the reported bindings and scope; it cannot authenticate those stores or
turn an observed absence into a durable guarantee that no outcome exists.
"""

from typing import cast

from tickwitness.domain.evidence.reduction_records import load_reduction_run_receipt
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)

MAX_REDUCTION_RECOVERY_BYTES = 128 * 1024
_FIELDS = {
    "kind",
    "schema_version",
    "source",
    "preparation_id",
    "attempt",
    "status",
    "recovery",
    "bindings",
    "final_manifest",
    "verification",
}
_DISPOSITIONS = {
    "reserved_without_intent": "owner_review_required",
    "reserved_unfinalized": "new_original_attempt_required_for_execution",
    "committed_failure": "failure_reverified",
    "committed_result": "result_reverified_without_execution",
}
_VERIFIED = {
    "source_reaudited",
    "preparation_recomputed",
    "observed_source_prefix_matched",
    "reservation_verified",
    "observation_only",
}
_NOT_AUTHORIZED = {
    "attempt_reserved",
    "native_replayed",
    "research_published",
    "job_state_changed",
    "checkpoint_restored",
    "retry_performed",
    "budget_refunded",
    "global_absence_verified",
    "global_ledger_authenticity_verified",
}
type Row = dict[str, object]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _same(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _validate(raw: bytes) -> Row:
    document = _exact(parse(raw, limit=MAX_REDUCTION_RECOVERY_BYTES), _FIELDS, "Recovery report")
    _same(
        [document["kind"], document["schema_version"]],
        ["reduction_attempt_recovery_v1", 1],
        "Unsupported reduction attempt recovery report",
    )
    source = _exact(
        document["source"], {"bundle_id", "report_id", "protocol_id"}, "Recovery source"
    )
    for value in source.values():
        identity(value)
    preparation_id = identity(document["preparation_id"])
    _require(isinstance(document["attempt"], dict), "Recovery requires an original reservation")
    reservation_raw = canonical(cast("Row", document["attempt"]))
    reservation = AttemptReservation(digest(reservation_raw), reservation_raw)
    _require(
        source["protocol_id"] == reservation.protocol_id,
        "Recovery reservation belongs to a different original protocol",
    )
    status = document["status"]
    _require(
        isinstance(status, str) and status in _DISPOSITIONS,
        "Unsupported reduction attempt recovery status",
    )
    checked_status = cast("str", status)
    bound = checked_status != "reserved_without_intent"
    committed = checked_status in {"committed_failure", "committed_result"}
    _same(
        document["recovery"],
        {
            "disposition": _DISPOSITIONS[checked_status],
            "restart_mode": "frozen_origin_new_attempt_only_v1",
            "checkpoint_supported": False,
            "execution_authorized": False,
        },
        "Recovery disposition or authority differs from the observed status",
    )
    bindings = _exact(
        document["bindings"], {"intent_id", "outcome_id", "run_id"}, "Recovery bindings"
    )
    for name, present in (
        ("intent_id", bound),
        ("outcome_id", committed),
        ("run_id", checked_status == "committed_result"),
    ):
        if present:
            identity(bindings[name])
        else:
            _require(bindings[name] is None, "Recovery binding must remain null: " + name)
    if checked_status == "committed_result":
        _require(
            isinstance(document["final_manifest"], dict),
            "Committed recovery result requires its exact final research receipt",
        )
        receipt = load_reduction_run_receipt(canonical(cast("Row", document["final_manifest"])))
        _same(
            receipt.document["attempt"],
            reservation.document,
            "Recovery final manifest belongs to another original attempt",
        )
        _same(
            [bindings["intent_id"], bindings["outcome_id"], bindings["run_id"]],
            [receipt.intent_id, receipt.run_id, receipt.run_id],
            "Recovery result identities differ from its exact final manifest",
        )
        intent = cast("Row", receipt.document["intent"])
        intent_bindings = cast("Row", intent["bindings"])
        _same(
            [
                receipt.document["protocol_id"],
                intent_bindings["source_bundle_id"],
                intent_bindings["source_report_id"],
                intent_bindings["preparation_id"],
            ],
            [source["protocol_id"], source["bundle_id"], source["report_id"], preparation_id],
            "Recovery result source or preparation differs from its frozen intent",
        )
    else:
        _require(
            document["final_manifest"] is None,
            "Only committed results may carry a successful final manifest",
        )
    _same(
        document["verification"],
        {
            **dict.fromkeys(_VERIFIED, True),
            "preparation_binding_verified": bound,
            "preparation_cas_verified": bound,
            "terminal_reverified": committed,
            **dict.fromkeys(_NOT_AUTHORIZED, False),
        },
        "Recovery verification scope differs from its observed status",
    )
    return document


def load_reduction_attempt_recovery(raw: bytes) -> Row:
    """Validate canonical observations without executing, repairing or retrying."""
    try:
        return _validate(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise EvidenceValidationError(
            "Cannot load reduction attempt recovery: " + str(error)
        ) from error


def build_reduction_attempt_recovery(document: Row) -> bytes:
    """Freeze a strictly scoped report; this does not reverify its source stores."""
    raw = canonical(document)
    load_reduction_attempt_recovery(raw)
    return raw
