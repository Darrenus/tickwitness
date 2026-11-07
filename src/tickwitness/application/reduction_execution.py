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
    ReductionExecutionIntent,
    ReductionRunReceipt,
    ReductionStateAudit,
    build_reduction_failure,
    build_reduction_intent,
    build_reduction_run_receipt,
    load_reduction_failure,
    load_reduction_intent,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.reduction_recovery import (
    build_reduction_attempt_recovery,
    load_reduction_attempt_recovery,
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
from tickwitness.domain.replay.contracts import ReplayInput, ReplayPort, load_replay_result
from tickwitness.domain.research_contracts.executable import ExecutableProtocol

type Row = dict[str, object]


class ReductionLedger(AttemptLedger, Protocol):
    def reserve_with_nonce(
        self, protocol: ExecutableProtocol, nonce: str
    ) -> AttemptReservation: ...

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


@dataclass(frozen=True, slots=True)
class PreparedReductionExecution:
    """Frozen source/preparation bytes, without a reservation or execution grant."""

    _source: _Source
    _preparation: _Preparation
    _prepared: PreparedReduction

    @property
    def protocol(self) -> ExecutableProtocol:
        return self._prepared.materialization.source.validation.protocol

    @property
    def replay_input(self) -> ReplayInput:
        return self._prepared.materialization.replay_input

    @property
    def intent(self) -> ReductionExecutionIntent:
        return build_reduction_intent(self._prepared.materialization)

    @property
    def artifacts(self) -> tuple[bytes, ...]:
        return _preparation_artifacts(self._prepared)

    @property
    def source(self) -> SearchEvidencePackage:
        return self._source

    @property
    def preparation(self) -> ReductionPackage:
        return self._preparation

    @property
    def preparation_id(self) -> str:
        return self._prepared.preparation_id


@dataclass(frozen=True, slots=True)
class AuditedReductionExecution:
    """Computed receipt and immutable artifacts; publication must re-audit them."""

    receipt: ReductionRunReceipt
    result_bytes: bytes
    audit_bytes: bytes

    @property
    def submission(self) -> ReductionSubmission:
        result = load_replay_result(self.result_bytes)
        attempt_raw = canonical(cast("Row", self.receipt.document["attempt"]))
        return ReductionSubmission(
            self.receipt.run_id,
            digest(attempt_raw),
            self.receipt.intent_id,
            cast("str", result.document["execution_status"]),
            parse(self.audit_bytes, limit=MAX_REDUCTION_STATE_AUDIT_BYTES),
        )


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Reduction execution permits development evidence only")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _snapshot(source: SearchEvidencePackage) -> _Source:
    return _Source(source.bundle_id, source.manifest_bytes, tuple(sorted(source.artifacts.items())))


def _pinned_source(
    source: SearchEvidencePackage, bundle_id: str, report_id: str, *, label: str
) -> _Source:
    snapshot = _snapshot(source)
    report_raw = snapshot.artifacts.get("finding_report")
    _require(
        snapshot.bundle_id == bundle_id
        and isinstance(report_raw, bytes)
        and digest(report_raw) == report_id,
        label + " differs from the expected pinned bundle or report",
    )
    return snapshot


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


def _check_event_budget(prepared: PreparedReduction) -> None:
    protocol = prepared.materialization.source.validation.protocol
    budget = cast("dict[str, int]", protocol.document["budget"])
    descriptor = prepared.materialization.document
    _require(
        cast("int", cast("Row", descriptor["candidate"])["full_event_count"])
        <= budget["max_events"]
        and cast("int", cast("Row", descriptor["retained"])["event_count"]) <= budget["max_events"],
        "Reduction source or retained prefix exceeds the original event budget",
    )


def prepare_reduction_execution(
    preparation: ReductionPackage,
    source: SearchEvidencePackage,
    *,
    expected_preparation_id: str,
    expected_bundle_id: str,
    expected_report_id: str,
    split: str,
) -> PreparedReductionExecution:
    """Rebuild frozen execution inputs without ledger or engine access."""
    _development(split)
    expected = identity(expected_preparation_id)
    bundle_id, report_id = identity(expected_bundle_id), identity(expected_report_id)
    snapshot = _pinned_source(source, bundle_id, report_id, label="Execution source")
    checked_preparation = _Preparation(
        preparation.preparation_id,
        preparation.manifest_bytes,
        tuple(sorted(preparation.artifacts.items())),
    )
    prepared, _ = _prepare(checked_preparation, snapshot, expected)
    bindings = prepared.materialization.source
    _require(
        bindings.bundle_id == bundle_id and bindings.report_id == report_id,
        "Execution preparation differs from the expected source identities",
    )
    _check_event_budget(prepared)
    return PreparedReductionExecution(snapshot, checked_preparation, prepared)


def _checked_execution(execution: PreparedReductionExecution) -> PreparedReductionExecution:
    _require(
        type(execution) is PreparedReductionExecution,
        "Execution phases require an actual frozen reduction execution",
    )
    source = execution._prepared.materialization.source
    return prepare_reduction_execution(
        execution.preparation,
        execution.source,
        expected_preparation_id=execution.preparation_id,
        expected_bundle_id=source.bundle_id,
        expected_report_id=source.report_id,
        split="development",
    )


def _dispatch_nonce(nonce: str) -> str:
    _require(
        isinstance(nonce, str) and re.fullmatch(r"[0-9a-f]{32}", nonce) is not None,
        "Reduction dispatch nonce requires 32 lowercase hex characters",
    )
    return nonce


def _nonce_reservation(
    reservations: tuple[AttemptReservation, ...], nonce: str
) -> AttemptReservation | None:
    matches = tuple(row for row in reservations if row.document["nonce"] == nonce)
    _require(len(matches) <= 1, "Dispatch nonce matches more than one original reservation")
    return matches[0] if matches else None


def find_reduction_execution_reservation(
    execution: PreparedReductionExecution, *, ledger: ReductionLedger, nonce: str
) -> AttemptReservation | None:
    """Observe the original nonce association without repairing or resuming it."""
    checked_nonce = _dispatch_nonce(nonce)
    checked = _checked_execution(execution)
    return _nonce_reservation(
        _checked_prefix(checked._source, checked.protocol, ledger), checked_nonce
    )


def _execution_reservation(
    prepared: PreparedReduction, reservation: AttemptReservation
) -> AttemptReservation:
    _require(type(reservation) is AttemptReservation, "Execution requires an original reservation")
    checked = AttemptReservation(reservation.attempt_id, reservation.canonical_bytes)
    protocol = prepared.materialization.source.validation.protocol
    budget = cast("dict[str, int]", protocol.document["budget"])
    _require(
        checked.protocol_id == protocol.protocol_id
        and checked.attempt_index <= budget["max_attempts"]
        and checked.document["max_wall_seconds"] == budget["max_wall_seconds"],
        "Execution reservation differs from the frozen original owner and budget",
    )
    return checked


def _bound_preparation(
    execution: PreparedReductionExecution,
    reservation: AttemptReservation,
    ledger: ReductionLedger,
) -> None:
    intent = execution.intent
    _require(
        ledger.get_intent(reservation.attempt_id) == intent.canonical_bytes,
        "Execution intent differs from the exact durable preparation",
    )
    for raw in (intent.canonical_bytes, *execution.artifacts):
        _require(
            ledger.read_artifact(digest(raw), max_bytes=16 * 1024 * 1024) == raw,
            "Execution intent or preparation CAS is not durably available",
        )


def authorize_reduction_execution(
    execution: PreparedReductionExecution,
    *,
    ledger: ReductionLedger,
    reservation_nonce: str,
    fence: Callable[[], None],
) -> AttemptReservation:
    """Consume one named original slot and bind its intent before native execution.

    Any existing nonce requires observation or explicit later recovery. It never
    authorizes replay using an already consumed slot, even after a lost reply.
    """
    nonce = _dispatch_nonce(reservation_nonce)
    checked = _checked_execution(execution)
    prefix = _checked_prefix(checked._source, checked.protocol, ledger)
    _require(
        _nonce_reservation(prefix, nonce) is None,
        "Original dispatch nonce is already consumed; no execution or retry is authorized",
    )
    fence()
    reservation = ledger.reserve_with_nonce(checked.protocol, nonce)
    reservation = _execution_reservation(checked._prepared, reservation)
    _require(
        reservation.document["nonce"] == nonce
        and reservation.attempt_index > len(prefix)
        and ledger.get_reservation(reservation.attempt_id) == reservation
        and reservation in _checked_prefix(checked._source, checked.protocol, ledger),
        "Named execution reservation differs from its actual original slot",
    )
    _require(
        ledger.get_outcome(reservation.attempt_id) is None,
        "New execution reservation already has a terminal outcome",
    )
    intent = checked.intent
    artifacts = checked.artifacts
    fence()
    committed = ledger.bind_intent(reservation, intent.canonical_bytes, artifacts=artifacts)
    _require(committed == intent.intent_id, "Ledger returned a conflicting execution intent")
    _bound_preparation(checked, reservation, ledger)
    return reservation


def _audit_prepared_result(
    prepared: PreparedReduction, reservation: AttemptReservation, result_raw: bytes
) -> AuditedReductionExecution:
    reservation = _execution_reservation(prepared, reservation)
    protocol = prepared.materialization.source.validation.protocol
    intent = build_reduction_intent(prepared.materialization)
    result = load_replay_result(result_raw)
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
    return AuditedReductionExecution(receipt, result.canonical_bytes, audit.canonical_bytes)


def audit_reduction_execution(
    execution: PreparedReductionExecution, reservation: AttemptReservation, result_raw: bytes
) -> AuditedReductionExecution:
    """Recompute result accounting and the final receipt without any publication."""
    checked = _checked_execution(execution)
    return _audit_prepared_result(checked._prepared, reservation, result_raw)


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


def publish_reduction_execution(
    execution: PreparedReductionExecution,
    reservation: AttemptReservation,
    audited: AuditedReductionExecution,
    *,
    ledger: ReductionLedger,
    fence: Callable[[], None],
) -> ReductionSubmission:
    """Re-audit frozen and actual facts before one currently fenced publication.

    The research ledger and Job Catalog do not share an atomic transaction.
    Publication/readback errors remain unconfirmed and never publish a second
    terminal or authorize re-execution of the already consumed reservation.
    """
    checked = _checked_execution(execution)
    actual = _execution_reservation(checked._prepared, reservation)
    _require(
        actual in _checked_prefix(checked._source, checked.protocol, ledger)
        and ledger.get_reservation(actual.attempt_id) == actual,
        "Publication reservation differs from the actual original slot",
    )
    _bound_preparation(checked, actual, ledger)
    _require(
        type(audited) is AuditedReductionExecution,
        "Publication requires actual audited reduction bytes",
    )
    rebuilt = _audit_prepared_result(checked._prepared, actual, audited.result_bytes)
    _require(
        rebuilt.receipt.canonical_bytes == audited.receipt.canonical_bytes
        and rebuilt.result_bytes == audited.result_bytes
        and rebuilt.audit_bytes == audited.audit_bytes,
        "Publication artifacts differ from independent result and receipt recomputation",
    )
    _require(
        ledger.get_outcome(actual.attempt_id) is None,
        "Original attempt already has an outcome; explicit recovery is required",
    )
    fence()
    # Keep all uncertain publication/readback outside execution-failure handling.
    # A committed outcome must never be replaced by a compensating failure.
    try:
        _confirmed_publication(
            ledger,
            actual,
            rebuilt.receipt.canonical_bytes,
            (rebuilt.result_bytes, rebuilt.audit_bytes),
        )
        for raw in (
            rebuilt.receipt.canonical_bytes,
            rebuilt.result_bytes,
            rebuilt.audit_bytes,
        ):
            _require(
                ledger.read_artifact(digest(raw), max_bytes=16 * 1024 * 1024) == raw,
                "Published reduction receipt or artifact could not be read back exactly",
            )
    except ProtocolRunError:
        raise
    except Exception as error:
        raise ProtocolRunError(
            "attempt_outcome_unconfirmed",
            "Attempt remains consumed; reduction publication readback could not be confirmed",
            actual.attempt_id,
            3,
        ) from error
    return rebuilt.submission


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
    _check_event_budget(prepared)
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
        audited = _audit_prepared_result(prepared, reservation, returned.canonical_bytes)
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
        audited.receipt.canonical_bytes,
        (audited.result_bytes, audited.audit_bytes),
    )
    return audited.submission


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


def inspect_reduction_attempt(
    attempt_id: str,
    preparation: ReductionPackage,
    source: SearchEvidencePackage,
    *,
    expected_preparation_id: str,
    expected_bundle_id: str,
    expected_report_id: str,
    split: str,
    ledger_factory: Callable[[], ReductionLedger],
) -> Row:
    """Observe an original attempt without authorizing execution or repairing it.

    Absence is an observation of these reads, not a sealed global absence.
    Recovery dispositions describe the required boundary for later work; this
    inspector never consumes a slot, restores engine state or retries a run.
    """
    _development(split)
    requested = identity(attempt_id)
    expected = identity(expected_preparation_id)
    bundle_id, report_id = identity(expected_bundle_id), identity(expected_report_id)
    snapshot = _pinned_source(source, bundle_id, report_id, label="Recovery source")
    prepared, _ = _prepare(preparation, snapshot, expected)
    source_context = prepared.materialization.source
    _require(
        source_context.bundle_id == bundle_id and source_context.report_id == report_id,
        "Recovery preparation differs from the expected source identities",
    )
    protocol = source_context.validation.protocol
    expected_intent = build_reduction_intent(prepared.materialization)
    ledger = ledger_factory()
    reservations = _checked_prefix(snapshot, protocol, ledger)
    reservation = ledger.get_reservation(requested)
    _require(type(reservation) is AttemptReservation, "Recovery requires an original attempt")
    reservation = AttemptReservation(reservation.attempt_id, reservation.canonical_bytes)
    budget = cast("dict[str, int]", protocol.document["budget"])
    _require(
        reservation.attempt_id == requested
        and reservation.protocol_id == protocol.protocol_id
        and reservation in reservations
        and reservation.attempt_index <= budget["max_attempts"]
        and reservation.document["max_wall_seconds"] == budget["max_wall_seconds"],
        "Recovery reservation differs from the verified original owner and budget",
    )
    intent_raw = ledger.get_intent(requested)
    outcome = ledger.get_outcome(requested)
    if intent_raw is None and outcome is not None:
        # An independent writer may bind and finalize between these reads.
        # Reobserve once; a terminal still requires its exact durable intent.
        intent_raw = ledger.get_intent(requested)
    status, disposition = "reserved_without_intent", "owner_review_required"
    intent_id: str | None = None
    outcome_id: str | None = None
    run_id: str | None = None
    final_manifest: object = None
    bound = intent_raw is not None
    terminal = outcome is not None
    if not bound:
        _require(outcome is None, "Recovery outcome has no observed immutable reduction intent")
    else:
        intent = load_reduction_intent(cast("bytes", intent_raw))
        _require(
            intent.canonical_bytes == expected_intent.canonical_bytes,
            "Recovery intent differs from the exact frozen preparation",
        )
        intent_id = intent.intent_id
        _require(
            ledger.read_artifact(intent_id, max_bytes=MAX_REDUCTION_RECORD_BYTES)
            == intent.canonical_bytes,
            "Recovery intent CAS differs from the committed immutable intent",
        )
        for raw in _preparation_artifacts(prepared):
            _require(
                ledger.read_artifact(digest(raw), max_bytes=16 * 1024 * 1024) == raw,
                "Recovery preparation CAS differs from the exact frozen artifacts",
            )
        status, disposition = (
            "reserved_unfinalized",
            "new_original_attempt_required_for_execution",
        )
        if outcome is not None:
            outcome_id = digest(outcome)
            _require(
                ledger.read_artifact(outcome_id, max_bytes=MAX_REDUCTION_RECORD_BYTES) == outcome,
                "Recovery outcome CAS differs from the committed terminal",
            )
            document = parse(outcome, limit=MAX_REDUCTION_RECORD_BYTES)
            _require(
                isinstance(document.get("attempt"), dict)
                and canonical(cast("Row", document["attempt"])) == reservation.canonical_bytes,
                "Recovery terminal belongs to another original reservation",
            )
            if document.get("kind") == "reduction_attempt_failure_v1":
                failure = load_reduction_failure(outcome)
                _require(
                    canonical(cast("Row", failure["intent"])) == intent.canonical_bytes,
                    "Recovery failure differs from the exact committed intent",
                )
                status, disposition = "committed_failure", "failure_reverified"
            else:
                _require(
                    document.get("kind") == "reduction_run_receipt_v1",
                    "Recovery terminal is not a reduction result or failure",
                )
                inspected = inspect_reduction_run(
                    outcome_id,
                    source=snapshot,
                    split="development",
                    ledger_factory=lambda: ledger,
                )
                _require(
                    canonical(cast("Row", inspected["receipt"])) == outcome
                    and cast("Row", inspected["preparation"])["preparation_id"] == expected,
                    "Recovery reverified result differs from the requested preparation",
                )
                run_id, final_manifest = outcome_id, inspected["receipt"]
                status, disposition = (
                    "committed_result",
                    "result_reverified_without_execution",
                )
    report: Row = {
        "kind": "reduction_attempt_recovery_v1",
        "schema_version": 1,
        "source": {
            "bundle_id": bundle_id,
            "report_id": report_id,
            "protocol_id": protocol.protocol_id,
        },
        "preparation_id": expected,
        "attempt": reservation.document,
        "status": status,
        "recovery": {
            "disposition": disposition,
            "restart_mode": "frozen_origin_new_attempt_only_v1",
            "checkpoint_supported": False,
            "execution_authorized": False,
        },
        "bindings": {"intent_id": intent_id, "outcome_id": outcome_id, "run_id": run_id},
        "final_manifest": final_manifest,
        "verification": {
            "source_reaudited": True,
            "preparation_recomputed": True,
            "observed_source_prefix_matched": True,
            "reservation_verified": True,
            "preparation_binding_verified": bound,
            "preparation_cas_verified": bound,
            "terminal_reverified": terminal,
            "observation_only": True,
            "attempt_reserved": False,
            "native_replayed": False,
            "research_published": False,
            "job_state_changed": False,
            "checkpoint_restored": False,
            "retry_performed": False,
            "budget_refunded": False,
            "global_absence_verified": False,
            "global_ledger_authenticity_verified": False,
        },
    }
    return load_reduction_attempt_recovery(build_reduction_attempt_recovery(report))
