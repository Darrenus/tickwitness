"""Freeze and durably execute two models under one development-only protocol budget."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.application.experiments import ExecutableReader, ExecutableRecord, ProtocolRunError
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.tagged_queue_evaluation import (
    TaggedQueueReplayEvaluation,
    evaluate_tagged_queue_replay,
    load_tagged_queue_evaluation,
)
from tickwitness.domain.evidence.tagged_queue_records import (
    MAX_TAGGED_QUEUE_RECORD_BYTES,
    TaggedQueueAttemptReservation,
    TaggedQueueRunReceipt,
    build_tagged_queue_failure,
    build_tagged_queue_intent,
    build_tagged_queue_run_receipt,
    load_tagged_queue_intent,
    load_tagged_queue_run_receipt,
)
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import load_replay_spec
from tickwitness.domain.replay.tagged_queue_contracts import (
    TaggedQueueReplayInput,
    TaggedQueueReplayPort,
    TaggedQueueReplayResult,
    load_tagged_queue_replay_result,
)
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TAGGED_POLICY_IDS,
    TaggedQueueProtocol,
    TaggedQueueValidationError,
    build_tagged_queue_protocol,
    load_tagged_queue_protocol,
    validate_tagged_queue_input,
)


class TaggedQueueReader(Protocol):
    def get(self, protocol_id: str) -> ExecutableRecord: ...


class TaggedQueueRepository(TaggedQueueReader, Protocol):
    def seal(self, canonical_bytes: bytes) -> ExecutableRecord: ...


class TaggedQueueLedger(Protocol):
    def reserve(self, protocol: TaggedQueueProtocol) -> AttemptReservation: ...
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
    def list_reservations(self, owner: TaggedQueueProtocol) -> tuple[AttemptReservation, ...]: ...
    def read_artifact(self, content_hash: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes: ...


class TaggedQueueReservationUnconfirmed(RuntimeError):
    """A reserve error cannot establish whether publication consumed a slot."""

    code = "tagged_queue_reservation_unconfirmed"
    exit_code = 3
    budget_consumed: None = None

    def __init__(self, protocol_id: str) -> None:
        self.protocol_id = protocol_id
        super().__init__(
            "Tagged attempt reservation could not be confirmed; budget consumption is unknown. "
            "Inspect the protocol's committed attempt ledger before retrying."
        )


@dataclass(frozen=True, slots=True)
class TaggedQueueFreezeReceipt:
    protocol: TaggedQueueProtocol
    created: bool

    @property
    def protocol_id(self) -> str:
        return self.protocol.protocol_id

    @property
    def document(self) -> dict[str, object]:
        return {
            "protocol_id": self.protocol_id,
            "created": self.created,
            "protocol": self.protocol.document,
        }


@dataclass(frozen=True, slots=True)
class TaggedQueueModelSubmission:
    run_id: str
    attempt_id: str
    intent_id: str
    protocol_id: str
    policy_id: str
    execution_status: str
    execution_environment: dict[str, object]
    evaluation: dict[str, object]

    @property
    def document(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "intent_id": self.intent_id,
            "protocol_id": self.protocol_id,
            "policy_id": self.policy_id,
            "execution_status": self.execution_status,
            "execution_environment": self.execution_environment,
            "evaluation": self.evaluation,
        }


@dataclass(frozen=True, slots=True)
class TaggedQueueRunEvidence:
    receipt: TaggedQueueRunReceipt
    replay_input: TaggedQueueReplayInput
    result: TaggedQueueReplayResult
    evaluation: TaggedQueueReplayEvaluation


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Queue protocols permit development execution only")


def _load_protocol(protocol_id: str, repository: TaggedQueueReader) -> TaggedQueueProtocol:
    identity(protocol_id)
    stored = repository.get(protocol_id)
    protocol = load_tagged_queue_protocol(stored.canonical_bytes)
    if stored.protocol_id != protocol_id or protocol.protocol_id != protocol_id:
        raise TaggedQueueValidationError("Registry returned a conflicting queue protocol")
    return protocol


def _actual_input(protocol: TaggedQueueProtocol, datasets: DatasetReader) -> ReplayInput:
    bindings = cast("dict[str, str]", protocol.document["bindings"])
    try:
        data = read_accepted_events(bindings["development_dataset_id"], datasets)
    except DataAccessError as error:
        raise TaggedQueueValidationError(str(error)) from error
    source = protocol.source_protocol.document
    spec = load_replay_spec(canonical(cast("dict[str, object]", source["replay_spec"])))
    actual = ReplayInput(bindings["development_dataset_id"], data, spec)
    validate_tagged_queue_input(protocol, actual)
    return actual


def freeze_tagged_queue(
    source_protocol_id: str,
    request: bytes,
    queue_request: bytes,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    protocols_factory: Callable[[], TaggedQueueRepository],
) -> TaggedQueueFreezeReceipt:
    _development(split)
    identity(source_protocol_id)
    stored_source = registry_factory().get(source_protocol_id)
    source = load_executable_protocol(stored_source.canonical_bytes)
    if source.protocol_id != source_protocol_id or stored_source.protocol_id != source_protocol_id:
        raise TaggedQueueValidationError("Registry returned a conflicting source protocol")
    document = source.document
    dataset_id = cast("dict[str, str]", document["datasets"])["development"]
    try:
        data = read_accepted_events(dataset_id, datasets_factory())
    except DataAccessError as error:
        raise TaggedQueueValidationError(str(error)) from error
    spec = load_replay_spec(canonical(cast("dict[str, object]", document["replay_spec"])))
    actual = ReplayInput(dataset_id, data, spec)
    protocol = build_tagged_queue_protocol(
        request, source_protocol=source, replay_input=actual, queue_request=queue_request
    )
    stored = protocols_factory().seal(protocol.canonical_bytes)
    if (
        stored.protocol_id != protocol.protocol_id
        or stored.canonical_bytes != protocol.canonical_bytes
    ):
        raise TaggedQueueValidationError("Registry returned conflicting queue protocol evidence")
    return TaggedQueueFreezeReceipt(protocol, stored.created)


def inspect_tagged_queue(
    protocol_id: str,
    *,
    split: str = "development",
    protocols_factory: Callable[[], TaggedQueueReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], TaggedQueueLedger],
) -> dict[str, object]:
    _development(split)
    identity(protocol_id)
    protocol = _load_protocol(protocol_id, protocols_factory())
    actual = _actual_input(protocol, datasets_factory())
    validation = validate_tagged_queue_input(protocol, actual)
    ledger = ledger_factory()
    attempts: list[dict[str, object]] = []
    for reservation in ledger.list_reservations(protocol):
        _reservation_budget(reservation, protocol)
        intent_raw = ledger.get_intent(reservation.attempt_id)
        intent = None if intent_raw is None else load_tagged_queue_intent(intent_raw)
        if intent is not None and intent.protocol.canonical_bytes != protocol.canonical_bytes:
            raise EvidenceValidationError("Attempt intent differs from the inspected protocol")
        outcome_raw = ledger.get_outcome(reservation.attempt_id)
        outcome = (
            None if outcome_raw is None else parse(outcome_raw, limit=MAX_TAGGED_QUEUE_RECORD_BYTES)
        )
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
    budget = cast("dict[str, int]", protocol.document["budget"])
    return {
        "protocol_id": protocol.protocol_id,
        "protocol": protocol.document,
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


def _artifacts(replay_input: TaggedQueueReplayInput) -> tuple[bytes, ...]:
    return (
        replay_input.protocol.canonical_bytes,
        replay_input.protocol.source_protocol.canonical_bytes,
        replay_input.protocol.constraint.canonical_bytes,
        replay_input.normalized_bytes,
        replay_input.witnesses.canonical_bytes,
    )


def _reservation_budget(reservation: AttemptReservation, protocol: TaggedQueueProtocol) -> None:
    budget = cast("dict[str, int]", protocol.document["budget"])
    if (
        type(reservation) is not TaggedQueueAttemptReservation
        or reservation.protocol_id != protocol.protocol_id
        or reservation.attempt_index > budget["max_attempts"]
        or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
    ):
        raise EvidenceValidationError("Queue reservation differs from the frozen shared budget")


def _failure_details(error: Exception) -> tuple[str, str, int]:
    if type(error).__name__ == "AttemptBudgetExceededError":
        return "attempt_budget_exhausted", str(error) or "Shared protocol budget is exhausted", 8
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


def run_tagged_queue_model(
    protocol_id: str,
    policy_id: str,
    *,
    split: str,
    protocols_factory: Callable[[], TaggedQueueReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], TaggedQueueLedger],
    replay_factory: Callable[[int], TaggedQueueReplayPort],
) -> TaggedQueueModelSubmission:
    _development(split)
    identity(protocol_id)
    protocol = _load_protocol(protocol_id, protocols_factory())
    intent = build_tagged_queue_intent(protocol, policy_id)
    actual = _actual_input(protocol, datasets_factory())
    replay_input = TaggedQueueReplayInput(protocol, actual.normalized_bytes, policy_id)
    ledger = ledger_factory()
    try:
        reservation = ledger.reserve(protocol)
    except Exception as error:
        # Reserve can fail after its slot link was published, for example during fsync.
        # Only explicit exhaustion proves that this call did not consume another slot.
        if type(error).__name__ == "AttemptBudgetExceededError":
            raise
        raise TaggedQueueReservationUnconfirmed(protocol.protocol_id) from error
    budget = cast("dict[str, int]", protocol.document["budget"])
    diagnostic_artifacts: tuple[bytes, ...] = ()
    try:
        _reservation_budget(reservation, protocol)
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
        evaluation = evaluate_tagged_queue_replay(replay_input, result)
        diagnostic_artifacts += (evaluation.canonical_bytes,)
        receipt = build_tagged_queue_run_receipt(
            {
                "kind": "tagged_queue_run_receipt_v1",
                "schema_version": 1,
                "attempt": reservation.document,
                "protocol_id": protocol.protocol_id,
                "claim_revision_id": protocol.claim_revision_id,
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
        return TaggedQueueModelSubmission(
            receipt.run_id,
            reservation.attempt_id,
            intent.intent_id,
            protocol.protocol_id,
            policy_id,
            cast("str", result.document["execution_status"]),
            cast("dict[str, object]", result.document["environment"]),
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
                build_tagged_queue_failure(reservation, intent, code, message),
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


def run_tagged_queue_pair(
    protocol_id: str,
    *,
    split: str,
    protocols_factory: Callable[[], TaggedQueueReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], TaggedQueueLedger],
    replay_factory: Callable[[int], TaggedQueueReplayPort],
) -> dict[str, object]:
    """Run each frozen policy once; stop after failure and preserve partial submissions."""
    _development(split)
    identity(protocol_id)
    protocol = _load_protocol(protocol_id, protocols_factory())
    _actual_input(protocol, datasets_factory())
    runs: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    attempted: list[str] = []
    for policy in TAGGED_POLICY_IDS:
        try:
            consumed = ledger_factory().list_reservations(protocol)
            budget = cast("dict[str, int]", protocol.document["budget"])
            if len(consumed) >= budget["max_attempts"]:
                failures.append(
                    {
                        "policy_id": policy,
                        "attempt_id": None,
                        "budget_consumed": False,
                        "code": "attempt_budget_exhausted",
                        "message": "All shared protocol attempt slots are already consumed",
                        "exit_code": 8,
                    }
                )
                break
            attempted.append(policy)
            submission = run_tagged_queue_model(
                protocol_id,
                policy,
                split=split,
                protocols_factory=protocols_factory,
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
                    "budget_consumed": (
                        True
                        if attempt_id is not None
                        else False
                        if code == "attempt_budget_exhausted"
                        else None
                    ),
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
    truths = [
        cast("dict[str, object]", cast("dict[str, object]", run["evaluation"])["claim_evaluation"])[
            "truth"
        ]
        for run in runs
    ]
    same_environment = (
        completed
        and canonical(cast("dict[str, object]", runs[0]["execution_environment"]))
        == canonical(cast("dict[str, object]", runs[1]["execution_environment"]))
    )
    eligible_truths = len(truths) == 2 and all(type(value) is bool for value in truths)
    relation = (
        ("opposite_truth_values" if truths[0] != truths[1] else "same_truth_value")
        if completed and same_environment and eligible_truths
        else "ineligible"
    )
    ineligible_reason = (
        "execution_incomplete"
        if not completed
        else "execution_environment_mismatch"
        if not same_environment
        else "claim_evaluation_ineligible"
        if not eligible_truths
        else None
    )
    return {
        "protocol_id": protocol_id,
        "status": "completed" if completed else "partial" if runs else "failed",
        "runs": runs,
        "failures": failures,
        "failed_policy_ids": [failure["policy_id"] for failure in failures],
        "pending_policy_ids": [policy for policy in TAGGED_POLICY_IDS if policy not in attempted],
        "scope": protocol.document["scope"],
        "claim_comparison": {
            "claim_revision_id": protocol.claim_revision_id,
            "relation": relation,
            "ineligible_reason": ineligible_reason,
            "same_execution_environment": same_environment,
            "truths": truths,
            "scope": "frozen_conditional_tagged_pair_only",
            "source_claim_evaluated": False,
        },
        "findings": [],
    }


def tagged_queue_run_evidence(
    run_id: str,
    *,
    ledger: TaggedQueueLedger,
    protocols: TaggedQueueReader,
    datasets: DatasetReader,
) -> TaggedQueueRunEvidence:
    """Independently rebuild source and audit durable execution without a native worker."""
    identity(run_id)
    raw = ledger.read_artifact(run_id, max_bytes=MAX_TAGGED_QUEUE_RECORD_BYTES)
    receipt = load_tagged_queue_run_receipt(raw)
    if receipt.run_id != run_id:
        raise EvidenceValidationError("Queue run identity differs from requested receipt")
    document = receipt.document
    attempt_raw = canonical(cast("dict[str, object]", document["attempt"]))
    reservation = TaggedQueueAttemptReservation(digest(attempt_raw), attempt_raw)
    if ledger.get_reservation(reservation.attempt_id) != reservation:
        raise EvidenceValidationError("Queue reservation differs from committed evidence")
    if ledger.get_outcome(reservation.attempt_id) != raw:
        raise EvidenceValidationError("Queue receipt is not the committed attempt outcome")
    intent_raw = canonical(cast("dict[str, object]", document["intent"]))
    if ledger.get_intent(reservation.attempt_id) != intent_raw:
        raise EvidenceValidationError("Queue intent differs from committed evidence")
    protocol = _load_protocol(cast("str", document["protocol_id"]), protocols)
    _reservation_budget(reservation, protocol)
    intent_document = cast("dict[str, object]", document["intent"])
    policy = cast("str", intent_document["policy_id"])
    intent = build_tagged_queue_intent(protocol, policy)
    if intent.canonical_bytes != intent_raw:
        raise EvidenceValidationError("Queue intent differs from independently frozen protocol")
    actual = _actual_input(protocol, datasets)
    replay_input = TaggedQueueReplayInput(protocol, actual.normalized_bytes, policy)
    for artifact in _artifacts(replay_input):
        if ledger.read_artifact(digest(artifact)) != artifact:
            raise EvidenceValidationError("Queue input artifacts differ from independent source")
    bindings = cast("dict[str, str]", document["bindings"])
    result = load_tagged_queue_replay_result(ledger.read_artifact(bindings["replay_result_sha256"]))
    if digest(result.canonical_bytes) != bindings["replay_result_sha256"]:
        raise EvidenceValidationError("Queue result identity differs from receipt")
    evaluation = evaluate_tagged_queue_replay(replay_input, result)
    stored_evaluation = load_tagged_queue_evaluation(
        ledger.read_artifact(bindings["evaluation_sha256"])
    )
    if (
        evaluation.evaluation_id != bindings["evaluation_sha256"]
        or stored_evaluation.canonical_bytes != evaluation.canonical_bytes
    ):
        raise EvidenceValidationError("Queue evaluation differs from independently audited result")
    if document["execution_status"] != result.document["execution_status"]:
        raise EvidenceValidationError("Queue receipt status differs from audited result")
    return TaggedQueueRunEvidence(receipt, replay_input, result, evaluation)


def inspect_tagged_queue_run(
    run_id: str,
    *,
    split: str = "development",
    protocols_factory: Callable[[], TaggedQueueReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], TaggedQueueLedger],
) -> dict[str, object]:
    _development(split)
    identity(run_id)
    evidence = tagged_queue_run_evidence(
        run_id,
        ledger=ledger_factory(),
        protocols=protocols_factory(),
        datasets=datasets_factory(),
    )
    return {
        "run_id": evidence.receipt.run_id,
        "receipt": evidence.receipt.document,
        "protocol": evidence.replay_input.protocol.document,
        "result": evidence.result.document,
        "evaluation": evidence.evaluation.document,
        "verification": {
            "kind": "tagged_queue_ledger_verification_v1",
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
