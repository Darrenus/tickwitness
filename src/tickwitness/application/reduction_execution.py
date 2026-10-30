"""Execute full-origin prefixes against the original durable attempt budget.

Portable evidence supplies reproducible source bytes, never replacement slots.
Terminal projections are audited after the existing adapter returns; they do
not establish a focus checkpoint or preservation of the source counterexample.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.experiments import AttemptLedger, ProtocolRunError
from tickwitness.application.reductions import (
    PreparedReduction,
    ReductionPackage,
    prepare_reduction_input,
    verify_reduction_input,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_evidence import SearchEvidencePackage
from tickwitness.domain.evidence.reduction_records import (
    MAX_REDUCTION_RECORD_BYTES,
    MAX_REDUCTION_STATE_AUDIT_BYTES,
    ReductionStateAudit,
    build_reduction_failure,
    build_reduction_intent,
    build_reduction_run_receipt,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.reduction.contracts import (
    build_reduction_manifest,
    load_reduction_recipe,
    role_limit,
)
from tickwitness.domain.replay.contracts import ReplayPort, load_replay_result
from tickwitness.domain.research_contracts.executable import ExecutableProtocol

type Row = dict[str, object]


class ReductionLedger(AttemptLedger, Protocol):
    def list_reservations(self, protocol: ExecutableProtocol) -> tuple[AttemptReservation, ...]: ...

    def bind_intent(
        self,
        reservation: AttemptReservation,
        intent_bytes: bytes,
        *,
        artifacts: tuple[bytes, ...] = (),
    ) -> str: ...

    def get_intent(self, attempt_id: str) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class ReductionSubmission:
    run_id: str
    attempt_id: str
    intent_id: str
    execution_status: str
    state_audit: Row


@dataclass(frozen=True, slots=True)
class _Source:
    bundle_id: str
    manifest_bytes: bytes
    _artifacts: tuple[tuple[str, bytes], ...]

    @property
    def artifacts(self) -> dict[str, bytes]:
        return dict(self._artifacts)


@dataclass(frozen=True, slots=True)
class _Preparation:
    preparation_id: str
    manifest_bytes: bytes
    _artifacts: tuple[tuple[str, bytes], ...]

    @property
    def artifacts(self) -> dict[str, bytes]:
        return dict(self._artifacts)


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Reduction execution permits development evidence only")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _snapshot(source: SearchEvidencePackage) -> _Source:
    return _Source(source.bundle_id, source.manifest_bytes, tuple(sorted(source.artifacts.items())))


def _prepare(
    preparation: ReductionPackage, source: _Source, expected: str
) -> tuple[PreparedReduction, Row]:
    checked = _Preparation(
        preparation.preparation_id,
        preparation.manifest_bytes,
        tuple(sorted(preparation.artifacts.items())),
    )
    receipt = verify_reduction_input(
        checked, source=source, expected_preparation_id=expected, split="development"
    )
    recipe = load_reduction_recipe(checked.artifacts["recipe"]).document
    bindings = cast("Row", recipe["source"])
    request = canonical(
        {
            "kind": "reduction_request_v1",
            "schema_version": 1,
            "witness_ordinal": bindings["witness_ordinal"],
            **cast("Row", recipe["operators"]),
        }
    )
    prepared = prepare_reduction_input(
        source,
        request,
        expected_bundle_id=cast("str", bindings["bundle_id"]),
        expected_report_id=cast("str", bindings["report_id"]),
        split="development",
    )
    _require(prepared.artifacts == checked.artifacts, "Reduction preparation changed during audit")
    return prepared, receipt


def _checked_prefix(
    source: _Source, protocol: ExecutableProtocol, ledger: ReductionLedger
) -> tuple[AttemptReservation, ...]:
    """Match observed portable facts to existing live evidence, without importing it."""
    artifacts = source.artifacts
    snapshot = parse(artifacts["snapshot"], limit=2 * 1024 * 1024)
    _require(
        snapshot["ledger_prefix_observed"] is True,
        "Reduction execution requires an observed original ledger prefix",
    )
    budget = cast("dict[str, int]", protocol.document["budget"])
    reservations = ledger.list_reservations(protocol)
    _require(
        type(reservations) is tuple and len(reservations) <= budget["max_attempts"],
        "Live reservation prefix exceeds the original protocol budget",
    )
    seen: set[str] = set()
    for index, record in enumerate(reservations, start=1):
        _require(type(record) is AttemptReservation, "Reduction requires original protocol slots")
        rebuilt = AttemptReservation(record.attempt_id, record.canonical_bytes)
        _require(
            rebuilt.protocol_id == protocol.protocol_id
            and rebuilt.attempt_index == index
            and rebuilt.document["max_wall_seconds"] == budget["max_wall_seconds"]
            and rebuilt.attempt_id not in seen
            and ledger.get_reservation(rebuilt.attempt_id) == rebuilt,
            "Live reservation differs from the original owner and slot",
        )
        seen.add(rebuilt.attempt_id)
    observed = cast("list[Row]", snapshot["reservations"])
    _require(
        len(reservations) >= len(observed),
        "Live ledger is shorter than the observed source prefix; portable slots cannot be restored",
    )
    for row, record in zip(observed, reservations, strict=False):
        index = cast("int", row["index"])
        _require(
            row["attempt_id"] == record.attempt_id
            and artifacts[f"reservation/{index:04}"] == record.canonical_bytes,
            "Observed source reservation differs from the existing live prefix",
        )
    for row in cast("list[Row]", snapshot["attempts"]):
        attempt_id = cast("str", row["attempt_id"])
        # False records an unobserved object, not an assertion of live absence.
        for key, getter in (("intent", ledger.get_intent), ("outcome", ledger.get_outcome)):
            if row[key] is True:
                _require(
                    getter(attempt_id) == artifacts[f"attempt/{attempt_id}/{key}"],
                    "Observed source attempt object differs from the existing live ledger",
                )
    for sha in cast("list[str]", snapshot["cas"]):
        _require(
            ledger.read_artifact(sha, max_bytes=16 * 1024 * 1024) == artifacts[f"cas/{sha}"],
            "Observed source CAS differs from the existing live ledger",
        )
    return reservations


def _preparation_artifacts(prepared: PreparedReduction) -> tuple[bytes, ...]:
    artifacts = prepared.artifacts
    return (
        build_reduction_manifest(artifacts),
        artifacts["recipe"],
        artifacts["materialization"],
        artifacts["normalized"],
    )


def _confirmed_publication(
    ledger: ReductionLedger,
    reservation: AttemptReservation,
    raw: bytes,
    artifacts: tuple[bytes, ...],
) -> None:
    """A late publication failure never authorizes replacing the committed terminal."""
    try:
        committed = ledger.publish(reservation, raw, artifacts=artifacts)
        _require(committed == digest(raw), "Ledger returned a conflicting reduction outcome")
        _require(
            ledger.get_outcome(reservation.attempt_id) == raw,
            "Reduction outcome could not be read back from its committed attempt",
        )
    except Exception as error:
        raise ProtocolRunError(
            "attempt_outcome_unconfirmed",
            "Attempt remains consumed; reduction outcome publication could not be confirmed",
            reservation.attempt_id,
            3,
        ) from error


def run_reduction_input(
    preparation: ReductionPackage,
    source: SearchEvidencePackage,
    *,
    expected_preparation_id: str,
    split: str,
    ledger_factory: Callable[[], ReductionLedger],
    engine_factory: Callable[[int], ReplayPort],
) -> ReductionSubmission:
    _development(split)
    expected = identity(expected_preparation_id)
    snapshot = _snapshot(source)
    prepared, _ = _prepare(preparation, snapshot, expected)
    protocol = prepared.materialization.source.validation.protocol
    intent = build_reduction_intent(prepared.materialization)
    budget = cast("dict[str, int]", protocol.document["budget"])
    descriptor = prepared.materialization.document
    _require(
        cast("int", cast("Row", descriptor["candidate"])["full_event_count"])
        <= budget["max_events"]
        and cast("int", cast("Row", descriptor["retained"])["event_count"]) <= budget["max_events"],
        "Reduction source or retained prefix exceeds the original event budget",
    )
    ledger = ledger_factory()
    prefix = _checked_prefix(snapshot, protocol, ledger)
    reservation = ledger.reserve(protocol)
    try:
        _require(
            type(reservation) is AttemptReservation
            and reservation.protocol_id == protocol.protocol_id
            and len(prefix) < reservation.attempt_index <= budget["max_attempts"]
            and reservation.document["max_wall_seconds"] == budget["max_wall_seconds"]
            and ledger.get_reservation(reservation.attempt_id) == reservation,
            "Reduction reservation differs from the frozen original budget",
        )
        after_reserve = _checked_prefix(snapshot, protocol, ledger)
        _require(
            reservation in after_reserve,
            "New reduction reservation is not in the verified contiguous live prefix",
        )
        artifacts = _preparation_artifacts(prepared)
        committed = ledger.bind_intent(reservation, intent.canonical_bytes, artifacts=artifacts)
        _require(committed == intent.intent_id, "Ledger returned a conflicting reduction intent")
        _require(
            ledger.get_intent(reservation.attempt_id) == intent.canonical_bytes,
            "Reduction intent is not the exact durable execution intent",
        )
        for raw in artifacts:
            _require(
                ledger.read_artifact(digest(raw), max_bytes=16 * 1024 * 1024) == raw,
                "Reduction preparation CAS is not durably available before execution",
            )
        returned = engine_factory(budget["max_wall_seconds"]).run(
            prepared.materialization.replay_input
        )
        result = load_replay_result(returned.canonical_bytes)
        audit = ReductionStateAudit(prepared.materialization, result)
        receipt = build_reduction_run_receipt(
            {
                "kind": "reduction_run_receipt_v1",
                "schema_version": 1,
                "attempt": reservation.document,
                "protocol_id": protocol.protocol_id,
                "claim_revision_id": protocol.claim_revision_id,
                "scope": intent.document["scope"],
                "intent": intent.document,
                "execution_status": result.document["execution_status"],
                "bindings": {
                    "replay_result_sha256": digest(result.canonical_bytes),
                    "state_audit_sha256": audit.audit_id,
                },
            }
        )
    except Exception as error:
        raw_code, raw_exit = (
            getattr(error, "code", "reduction_run_failed"),
            getattr(error, "exit_code", 7),
        )
        code = (
            raw_code
            if isinstance(raw_code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", raw_code)
            else "reduction_run_failed"
        )
        exit_code = raw_exit if type(raw_exit) is int and raw_exit in (2, 3, 4, 6, 7) else 7
        message = (
            (str(error) or type(error).__name__)
            .encode("utf-8", errors="backslashreplace")[:4096]
            .decode("utf-8", errors="ignore")
        )
        try:
            # Bound the complete escaped record, not just UTF-8 diagnostic bytes.
            # Control characters can expand sixfold during canonical JSON output.
            while True:
                try:
                    failure = build_reduction_failure(reservation, intent, code, message)
                    break
                except EvidenceValidationError:
                    if len(message) <= 1:
                        raise
                    message = message[: max(1, len(message) // 2)]
        except Exception as publication_error:
            raise ProtocolRunError(
                "attempt_outcome_unconfirmed",
                "Attempt remains consumed; reduction failure record could not be constructed",
                reservation.attempt_id,
                3,
            ) from publication_error
        _confirmed_publication(ledger, reservation, failure, ())
        raise ProtocolRunError(code, message, reservation.attempt_id, exit_code) from error
    # Keep terminal publication outside the execution catch: a committed receipt
    # must never be overwritten with a failure after uncertain return/readback.
    _confirmed_publication(
        ledger,
        reservation,
        receipt.canonical_bytes,
        (result.canonical_bytes, audit.canonical_bytes),
    )
    return ReductionSubmission(
        receipt.run_id,
        reservation.attempt_id,
        intent.intent_id,
        cast("str", result.document["execution_status"]),
        audit.document,
    )


def inspect_reduction_run(
    run_id: str,
    *,
    source: SearchEvidencePackage,
    split: str,
    ledger_factory: Callable[[], ReductionLedger],
) -> Row:
    """Rebuild stored input and terminal accounting without running or repairing it."""
    _development(split)
    identity(run_id)
    snapshot = _snapshot(source)
    ledger = ledger_factory()
    raw = ledger.read_artifact(run_id, max_bytes=MAX_REDUCTION_RECORD_BYTES)
    receipt = load_reduction_run_receipt(raw)
    _require(receipt.run_id == run_id, "Reduction run identity differs from requested evidence")
    document = receipt.document
    attempt_raw = canonical(cast("Row", document["attempt"]))
    reservation = AttemptReservation(digest(attempt_raw), attempt_raw)
    _require(
        ledger.get_reservation(reservation.attempt_id) == reservation
        and ledger.get_outcome(reservation.attempt_id) == raw,
        "Reduction receipt is not the committed original attempt outcome",
    )
    intent_raw = canonical(cast("Row", document["intent"]))
    _require(
        ledger.get_intent(reservation.attempt_id) == intent_raw,
        "Reduction intent differs from committed evidence",
    )
    bindings = cast("dict[str, str]", cast("Row", document["intent"])["bindings"])
    artifacts = {
        "recipe": ledger.read_artifact(bindings["recipe_id"], max_bytes=role_limit("recipe")),
        "materialization": ledger.read_artifact(
            bindings["materialization_sha256"], max_bytes=role_limit("materialization")
        ),
        "normalized": ledger.read_artifact(
            bindings["normalized_sha256"], max_bytes=role_limit("normalized")
        ),
    }
    preparation = _Preparation(
        bindings["preparation_id"],
        ledger.read_artifact(bindings["preparation_manifest_sha256"], max_bytes=64 * 1024),
        tuple(sorted(artifacts.items())),
    )
    prepared, preparation_receipt = _prepare(preparation, snapshot, bindings["preparation_id"])
    protocol = prepared.materialization.source.validation.protocol
    _checked_prefix(snapshot, protocol, ledger)
    rebuilt_intent = build_reduction_intent(prepared.materialization)
    _require(
        rebuilt_intent.canonical_bytes == intent_raw,
        "Reduction intent differs from independently reconstructed source and preparation",
    )
    budget = cast("dict[str, int]", protocol.document["budget"])
    _require(
        reservation.protocol_id == protocol.protocol_id
        and reservation.attempt_index <= budget["max_attempts"]
        and reservation.document["max_wall_seconds"] == budget["max_wall_seconds"],
        "Reduction receipt exceeds the original protocol budget",
    )
    result_bindings = cast("dict[str, str]", document["bindings"])
    result = load_replay_result(ledger.read_artifact(result_bindings["replay_result_sha256"]))
    _require(
        digest(result.canonical_bytes) == result_bindings["replay_result_sha256"],
        "Reduction result identity differs from its committed binding",
    )
    audit = ReductionStateAudit(prepared.materialization, result)
    _require(
        audit.audit_id == result_bindings["state_audit_sha256"]
        and ledger.read_artifact(audit.audit_id, max_bytes=MAX_REDUCTION_STATE_AUDIT_BYTES)
        == audit.canonical_bytes,
        "Stored reduction state audit differs from independent recomputation",
    )
    _require(
        document["execution_status"] == result.document["execution_status"],
        "Reduction execution status differs from the audited native result",
    )
    return {
        "run_id": receipt.run_id,
        "attempt_id": reservation.attempt_id,
        "intent_id": receipt.intent_id,
        "protocol_id": protocol.protocol_id,
        "receipt": document,
        "state_audit": audit.document,
        "preparation": preparation_receipt,
        "budget": {
            "protocol_id": protocol.protocol_id,
            "attempt_index": reservation.attempt_index,
            **budget,
        },
        "verification": {
            "integrity_verified": True,
            "bindings_verified": True,
            "source_package_reaudited": True,
            "observed_source_prefix_matched": True,
            "preparation_recomputed": True,
            "state_audit_recomputed": True,
            "native_replayed": False,
            "attempt_reserved": False,
            "checkpoint_resume_verified": False,
            "witness_preservation_verified": False,
            "full_attempt_history_verified": False,
            "global_ledger_authenticity_verified": False,
            "source_claim_authority_extended": False,
        },
    }
