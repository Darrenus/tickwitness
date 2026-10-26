"""Freeze and durably execute two models under one development-only family budget."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.application.experiments import ExecutableReader, ExecutableRecord, ProtocolRunError
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.queue_evaluation import (
    QueueReplayEvaluation,
    evaluate_queue_replay,
    load_queue_evaluation,
)
from tickwitness.domain.evidence.queue_records import (
    MAX_QUEUE_RECORD_BYTES,
    QueueAttemptReservation,
    QueueRunReceipt,
    build_queue_failure,
    build_queue_intent,
    build_queue_run_receipt,
    load_queue_intent,
    load_queue_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.queue_contracts import (
    QueueReplayInput,
    QueueReplayPort,
    QueueReplayResult,
    load_queue_replay_result,
)
from tickwitness.domain.replay.specs import load_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.queue_family import (
    QUEUE_POLICY_IDS,
    QueueFamilyProtocol,
    QueueFamilyValidationError,
    build_queue_family_protocol,
    load_queue_family_protocol,
    validate_queue_family_input,
)


class QueueFamilyReader(Protocol):
    def get(self, protocol_id: str) -> ExecutableRecord: ...


class QueueFamilyRepository(QueueFamilyReader, Protocol):
    def seal(self, canonical_bytes: bytes) -> ExecutableRecord: ...


class QueueLedger(Protocol):
    def reserve(self, protocol: QueueFamilyProtocol) -> AttemptReservation: ...
    def bind_intent(
        self,
        reservation: AttemptReservation,
        intent_bytes: bytes,
        *,
        artifacts: tuple[bytes, ...] = (),
    ) -> str: ...
    def publish(
        self, reservation: AttemptReservation, outcome: bytes, *, artifacts: tuple[bytes, ...] = ()
    ) -> str: ...
    def get_reservation(self, attempt_id: str) -> AttemptReservation: ...
    def get_intent(self, attempt_id: str) -> bytes | None: ...
    def get_outcome(self, attempt_id: str) -> bytes | None: ...
    def list_reservations(self, owner: QueueFamilyProtocol) -> tuple[AttemptReservation, ...]: ...
    def read_artifact(self, content_hash: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes: ...


@dataclass(frozen=True, slots=True)
class QueueFamilyFreezeReceipt:
    family: QueueFamilyProtocol
    created: bool

    @property
    def family_id(self) -> str:
        return self.family.family_id

    @property
    def protocol_id(self) -> str:
        return self.family_id

    @property
    def document(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "created": self.created,
            "family": self.family.document,
        }


@dataclass(frozen=True, slots=True)
class QueueModelSubmission:
    run_id: str
    attempt_id: str
    intent_id: str
    family_id: str
    policy_id: str
    execution_status: str
    evaluation: dict[str, object]

    @property
    def document(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "intent_id": self.intent_id,
            "family_id": self.family_id,
            "policy_id": self.policy_id,
            "execution_status": self.execution_status,
            "evaluation": self.evaluation,
        }


@dataclass(frozen=True, slots=True)
class QueueRunEvidence:
    receipt: QueueRunReceipt
    replay_input: QueueReplayInput
    result: QueueReplayResult
    evaluation: QueueReplayEvaluation


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Queue families permit development execution only")


def _load_family(family_id: str, repository: QueueFamilyReader) -> QueueFamilyProtocol:
    identity(family_id)
    stored = repository.get(family_id)
    family = load_queue_family_protocol(stored.canonical_bytes)
    if stored.protocol_id != family_id or family.family_id != family_id:
        raise QueueFamilyValidationError("Registry returned a conflicting queue family")
    return family


def _actual_input(family: QueueFamilyProtocol, datasets: DatasetReader) -> ReplayInput:
    bindings = cast("dict[str, str]", family.document["bindings"])
    try:
        data = read_accepted_events(bindings["development_dataset_id"], datasets)
    except DataAccessError as error:
        raise QueueFamilyValidationError(str(error)) from error
    source = family.source_protocol.document
    spec = load_replay_spec(canonical(cast("dict[str, object]", source["replay_spec"])))
    actual = ReplayInput(bindings["development_dataset_id"], data, spec)
    validate_queue_family_input(family, actual)
    return actual


def freeze_queue_family(
    source_protocol_id: str,
    family_request: bytes,
    queue_request: bytes,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    families_factory: Callable[[], QueueFamilyRepository],
) -> QueueFamilyFreezeReceipt:
    _development(split)
    identity(source_protocol_id)
    stored_source = registry_factory().get(source_protocol_id)
    source = load_executable_protocol(stored_source.canonical_bytes)
    if source.protocol_id != source_protocol_id or stored_source.protocol_id != source_protocol_id:
        raise QueueFamilyValidationError("Registry returned a conflicting source protocol")
    document = source.document
    dataset_id = cast("dict[str, str]", document["datasets"])["development"]
    try:
        data = read_accepted_events(dataset_id, datasets_factory())
    except DataAccessError as error:
        raise QueueFamilyValidationError(str(error)) from error
    spec = load_replay_spec(canonical(cast("dict[str, object]", document["replay_spec"])))
    actual = ReplayInput(dataset_id, data, spec)
    family = build_queue_family_protocol(
        family_request, source_protocol=source, replay_input=actual, queue_request=queue_request
    )
    stored = families_factory().seal(family.canonical_bytes)
    if stored.protocol_id != family.family_id or stored.canonical_bytes != family.canonical_bytes:
        raise QueueFamilyValidationError("Registry returned conflicting queue family evidence")
    return QueueFamilyFreezeReceipt(family, stored.created)


def inspect_queue_family(
    family_id: str,
    *,
    split: str = "development",
    families_factory: Callable[[], QueueFamilyReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], QueueLedger],
) -> dict[str, object]:
    _development(split)
    identity(family_id)
    family = _load_family(family_id, families_factory())
    actual = _actual_input(family, datasets_factory())
    validation = validate_queue_family_input(family, actual)
    ledger = ledger_factory()
    attempts: list[dict[str, object]] = []
    for reservation in ledger.list_reservations(family):
        _reservation_budget(reservation, family)
        intent_raw = ledger.get_intent(reservation.attempt_id)
        intent = None if intent_raw is None else load_queue_intent(intent_raw)
        if intent is not None and intent.family.canonical_bytes != family.canonical_bytes:
            raise EvidenceValidationError("Attempt intent differs from the inspected family")
        outcome_raw = ledger.get_outcome(reservation.attempt_id)
        outcome = None if outcome_raw is None else parse(outcome_raw, limit=MAX_QUEUE_RECORD_BYTES)
        attempts.append(
            {
                "attempt_id": reservation.attempt_id,
                "reservation": reservation.document,
                "budget_consumed": True,
                "state": "reserved_unfinalized" if outcome is None else "finalized",
                "intent_id": None if intent is None else intent.intent_id,
                "policy_id": None if intent is None else intent.policy_id,
                "outcome_id": None if outcome_raw is None else digest(outcome_raw),
                "outcome_kind": None if outcome is None else outcome["kind"],
                "execution_status": None if outcome is None else outcome.get("execution_status"),
                "error": None if outcome is None else outcome.get("error"),
            }
        )
    budget = cast("dict[str, int]", family.document["budget"])
    return {
        "family_id": family.family_id,
        "family": family.document,
        "validation": validation.document,
        "budget": {
            **budget,
            "consumed_attempts": len(attempts),
            "remaining_attempts": budget["max_attempts"] - len(attempts),
        },
        "attempts": attempts,
        "verification": {
            "family_rebuilt": True,
            "source_bindings_verified": True,
            "flow_conservation_verified": True,
            "native_replayed": False,
            "confirmation_reference_checked": False,
            "attempt_ledger_checked": True,
        },
    }


def _artifacts(replay_input: QueueReplayInput) -> tuple[bytes, ...]:
    return (
        replay_input.family.canonical_bytes,
        replay_input.family.source_protocol.canonical_bytes,
        replay_input.family.constraint.canonical_bytes,
        replay_input.normalized_bytes,
        replay_input.feasibility.canonical_bytes,
    )


def _reservation_budget(reservation: AttemptReservation, family: QueueFamilyProtocol) -> None:
    budget = cast("dict[str, int]", family.document["budget"])
    if (
        type(reservation) is not QueueAttemptReservation
        or reservation.protocol_id != family.family_id
        or reservation.attempt_index > budget["max_attempts"]
        or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
    ):
        raise EvidenceValidationError("Queue reservation differs from the frozen shared budget")


def _failure_details(error: Exception) -> tuple[str, str, int]:
    if type(error).__name__ == "AttemptBudgetExceededError":
        return "attempt_budget_exhausted", str(error) or "Shared family budget is exhausted", 8
    raw_code, raw_exit = getattr(error, "code", "queue_run_failed"), getattr(error, "exit_code", 7)
    code = (
        raw_code
        if isinstance(raw_code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", raw_code)
        else "queue_run_failed"
    )
    exit_code = raw_exit if type(raw_exit) is int and raw_exit in (2, 3, 4, 6, 7, 8) else 7
    message = (
        (str(error) or type(error).__name__)
        .encode("utf-8", errors="backslashreplace")[:4096]
        .decode("utf-8", errors="ignore")
    )
    return code, message, exit_code


def run_queue_model(
    family_id: str,
    policy_id: str,
    *,
    split: str,
    families_factory: Callable[[], QueueFamilyReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], QueueLedger],
    replay_factory: Callable[[int], QueueReplayPort],
) -> QueueModelSubmission:
    _development(split)
    identity(family_id)
    family = _load_family(family_id, families_factory())
    intent = build_queue_intent(family, policy_id)
    actual = _actual_input(family, datasets_factory())
    replay_input = QueueReplayInput(family, actual.normalized_bytes, policy_id)
    ledger = ledger_factory()
    reservation = ledger.reserve(family)
    budget = cast("dict[str, int]", family.document["budget"])
    diagnostic_artifacts: tuple[bytes, ...] = ()
    try:
        _reservation_budget(reservation, family)
        intent_id = ledger.bind_intent(
            reservation, intent.canonical_bytes, artifacts=_artifacts(replay_input)
        )
        if intent_id != intent.intent_id:
            raise EvidenceValidationError("Ledger returned a conflicting queue intent")
        result = replay_factory(budget["max_wall_seconds"]).run(replay_input)
        diagnostic_artifacts = (result.canonical_bytes,)
        # Preserve the raw callbacks before auditing so a rejected result remains reviewable.
        if (
            ledger.bind_intent(reservation, intent.canonical_bytes, artifacts=diagnostic_artifacts)
            != intent.intent_id
        ):
            raise EvidenceValidationError("Ledger returned a conflicting queue diagnostic binding")
        evaluation = evaluate_queue_replay(replay_input, result)
        diagnostic_artifacts += (evaluation.canonical_bytes,)
        receipt = build_queue_run_receipt(
            {
                "kind": "queue_run_receipt_v1",
                "schema_version": 1,
                "attempt": reservation.document,
                "protocol_id": family.family_id,
                "intent": intent.document,
                "execution_status": result.document["execution_status"],
                "bindings": {
                    "replay_result_sha256": digest(result.canonical_bytes),
                    "evaluation_sha256": evaluation.evaluation_id,
                },
            }
        )
        outcome = ledger.publish(
            reservation,
            receipt.canonical_bytes,
            artifacts=(result.canonical_bytes, evaluation.canonical_bytes),
        )
        if outcome != receipt.run_id:
            raise EvidenceValidationError("Ledger returned a conflicting queue outcome")
        return QueueModelSubmission(
            receipt.run_id,
            reservation.attempt_id,
            intent.intent_id,
            family.family_id,
            policy_id,
            cast("str", result.document["execution_status"]),
            evaluation.document,
        )
    except Exception as error:
        code, message, exit_code = _failure_details(error)
        if diagnostic_artifacts:
            message = (
                message[:3900]
                + " Diagnostic replay_result_sha256="
                + digest(diagnostic_artifacts[0])
            )
        try:
            ledger.publish(
                reservation,
                build_queue_failure(reservation, intent, code, message),
                artifacts=diagnostic_artifacts,
            )
        except Exception as publication_error:
            raise ProtocolRunError(
                "attempt_outcome_unconfirmed",
                "Attempt remains consumed; queue outcome publication could not be confirmed",
                reservation.attempt_id,
                3,
            ) from publication_error
        raise ProtocolRunError(code, message, reservation.attempt_id, exit_code) from error


def run_queue_family(
    family_id: str,
    *,
    split: str,
    families_factory: Callable[[], QueueFamilyReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], QueueLedger],
    replay_factory: Callable[[int], QueueReplayPort],
) -> dict[str, object]:
    """Run each frozen policy once; stop after failure and preserve partial submissions."""
    _development(split)
    identity(family_id)
    family = _load_family(family_id, families_factory())
    _actual_input(family, datasets_factory())
    runs: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    attempted: list[str] = []
    for policy in QUEUE_POLICY_IDS:
        try:
            consumed = ledger_factory().list_reservations(family)
            budget = cast("dict[str, int]", family.document["budget"])
            if len(consumed) >= budget["max_attempts"]:
                failures.append(
                    {
                        "policy_id": policy,
                        "attempt_id": None,
                        "budget_consumed": False,
                        "code": "attempt_budget_exhausted",
                        "message": "All shared family attempt slots are already consumed",
                        "exit_code": 8,
                    }
                )
                break
            attempted.append(policy)
            submission = run_queue_model(
                family_id,
                policy,
                split=split,
                families_factory=families_factory,
                datasets_factory=datasets_factory,
                ledger_factory=ledger_factory,
                replay_factory=replay_factory,
            )
            runs.append(submission.document)
        except Exception as error:
            code, message, exit_code = _failure_details(error)
            attempt_id = getattr(error, "attempt_id", None)
            failures.append(
                {
                    "policy_id": policy,
                    "attempt_id": attempt_id,
                    "budget_consumed": attempt_id is not None,
                    "code": code,
                    "message": message,
                    "exit_code": exit_code,
                }
            )
            break
    completed = (
        not failures
        and len(runs) == 2
        and all(run["execution_status"] == "completed" for run in runs)
    )
    return {
        "family_id": family_id,
        "status": "completed" if completed else "partial" if runs else "failed",
        "runs": runs,
        "failures": failures,
        "failed_policy_ids": [failure["policy_id"] for failure in failures],
        "pending_policy_ids": [policy for policy in QUEUE_POLICY_IDS if policy not in attempted],
        "scope": family.document["scope"],
    }


def queue_run_evidence(
    run_id: str,
    *,
    ledger: QueueLedger,
    families: QueueFamilyReader,
    datasets: DatasetReader,
) -> QueueRunEvidence:
    """Independently rebuild source and audit durable execution without a native worker."""
    identity(run_id)
    raw = ledger.read_artifact(run_id, max_bytes=MAX_QUEUE_RECORD_BYTES)
    receipt = load_queue_run_receipt(raw)
    if receipt.run_id != run_id:
        raise EvidenceValidationError("Queue run identity differs from requested receipt")
    document = receipt.document
    attempt_raw = canonical(cast("dict[str, object]", document["attempt"]))
    reservation = QueueAttemptReservation(digest(attempt_raw), attempt_raw)
    if ledger.get_reservation(reservation.attempt_id) != reservation:
        raise EvidenceValidationError("Queue reservation differs from committed evidence")
    if ledger.get_outcome(reservation.attempt_id) != raw:
        raise EvidenceValidationError("Queue receipt is not the committed attempt outcome")
    intent_raw = canonical(cast("dict[str, object]", document["intent"]))
    if ledger.get_intent(reservation.attempt_id) != intent_raw:
        raise EvidenceValidationError("Queue intent differs from committed evidence")
    family = _load_family(cast("str", document["protocol_id"]), families)
    _reservation_budget(reservation, family)
    intent_document = cast("dict[str, object]", document["intent"])
    policy = cast("str", intent_document["policy_id"])
    intent = build_queue_intent(family, policy)
    if intent.canonical_bytes != intent_raw:
        raise EvidenceValidationError("Queue intent differs from independently frozen family")
    actual = _actual_input(family, datasets)
    replay_input = QueueReplayInput(family, actual.normalized_bytes, policy)
    for artifact in _artifacts(replay_input):
        if ledger.read_artifact(digest(artifact)) != artifact:
            raise EvidenceValidationError("Queue input artifacts differ from independent source")
    bindings = cast("dict[str, str]", document["bindings"])
    result = load_queue_replay_result(ledger.read_artifact(bindings["replay_result_sha256"]))
    if digest(result.canonical_bytes) != bindings["replay_result_sha256"]:
        raise EvidenceValidationError("Queue result identity differs from receipt")
    evaluation = evaluate_queue_replay(replay_input, result)
    stored_evaluation = load_queue_evaluation(ledger.read_artifact(bindings["evaluation_sha256"]))
    if (
        evaluation.evaluation_id != bindings["evaluation_sha256"]
        or stored_evaluation.canonical_bytes != evaluation.canonical_bytes
    ):
        raise EvidenceValidationError("Queue evaluation differs from independently audited result")
    if document["execution_status"] != result.document["execution_status"]:
        raise EvidenceValidationError("Queue receipt status differs from audited result")
    return QueueRunEvidence(receipt, replay_input, result, evaluation)


def inspect_queue_run(
    run_id: str,
    *,
    split: str = "development",
    families_factory: Callable[[], QueueFamilyReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], QueueLedger],
) -> dict[str, object]:
    _development(split)
    identity(run_id)
    evidence = queue_run_evidence(
        run_id,
        ledger=ledger_factory(),
        families=families_factory(),
        datasets=datasets_factory(),
    )
    return {
        "run_id": evidence.receipt.run_id,
        "receipt": evidence.receipt.document,
        "family": evidence.replay_input.family.document,
        "result": evidence.result.document,
        "evaluation": evidence.evaluation.document,
        "verification": {
            "kind": "queue_ledger_verification_v1",
            "integrity_verified": True,
            "bindings_verified": True,
            "source_revalidated": True,
            "queue_execution_audited": True,
            "native_replayed": False,
            "confirmation_reference_checked": False,
            "full_attempt_ledger_checked": False,
            "author_signature_verified": False,
        },
    }
