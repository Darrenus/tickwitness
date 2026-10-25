"""Freeze, reserve, execute and verify one explicitly scoped development baseline."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.data_access import (
    DataAccessError,
    DatasetReader,
    assert_forward_disjoint,
    read_accepted_events,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.protocol_evaluation import SCOPE, ProtocolEvaluation
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    build_run_receipt,
    canonical,
    digest,
    identity,
    load_run_receipt,
    parse,
)
from tickwitness.domain.evidence.verification import verify_artifacts
from tickwitness.domain.replay.contracts import ReplayInput, ReplayPort
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    ProtocolValidationError,
    build_executable_protocol,
    load_executable_protocol,
)


class ExecutableRecord(Protocol):
    @property
    def protocol_id(self) -> str: ...
    @property
    def canonical_bytes(self) -> bytes: ...
    @property
    def created(self) -> bool: ...


class ExecutableReader(Protocol):
    def get(self, protocol_id: str) -> ExecutableRecord: ...


class ExecutableRepository(ExecutableReader, Protocol):
    def seal(self, canonical_bytes: bytes) -> ExecutableRecord: ...


class AttemptLedger(Protocol):
    def reserve(self, protocol: ExecutableProtocol) -> AttemptReservation: ...
    def publish(
        self, reservation: AttemptReservation, outcome: bytes, *, artifacts: tuple[bytes, ...] = ()
    ) -> str: ...
    def read_artifact(self, content_hash: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes: ...
    def get_reservation(self, attempt_id: str) -> AttemptReservation: ...
    def get_outcome(self, attempt_id: str) -> bytes | None: ...


class DatasetEvidenceReader(DatasetReader, Protocol):
    def read_artifacts(self, dataset_id: str) -> dict[str, bytes]: ...


class EvidencePackage(Protocol):
    @property
    def bundle_id(self) -> str: ...
    @property
    def artifacts(self) -> dict[str, bytes]: ...


@dataclass(frozen=True, slots=True)
class ExperimentReceipt:
    protocol_id: str
    claim_revision_id: str
    created: bool
    document: dict[str, object]


@dataclass(frozen=True, slots=True)
class RunSubmission:
    run_id: str
    attempt_id: str
    execution_status: str
    evaluation: dict[str, object]


class ProtocolRunError(RuntimeError):
    """A reserved attempt failed; the reservation remains consumed."""

    def __init__(self, code: str, message: str, attempt_id: str, exit_code: int = 7) -> None:
        self.code, self.attempt_id, self.exit_code = code, attempt_id, exit_code
        super().__init__(message)


def _load(protocol_id: str, registry: ExecutableReader) -> ExecutableProtocol:
    stored = registry.get(protocol_id)
    protocol = load_executable_protocol(stored.canonical_bytes)
    if stored.protocol_id != protocol_id or protocol.protocol_id != protocol_id:
        raise ProtocolValidationError("Executable protocol identity mismatch")
    return protocol


def _input(protocol: ExecutableProtocol, data: bytes) -> ReplayInput:
    document = protocol.document
    datasets = cast("dict[str, str]", document["datasets"])
    spec = build_replay_spec(canonical(cast("dict[str, object]", document["replay_spec"])))
    replay_input = ReplayInput(datasets["development"], data, spec)
    prepared = preflight_replay(replay_input)
    if len(prepared.events) > cast("dict[str, int]", document["budget"])["max_events"]:
        raise ProtocolValidationError("Development data exceeds the frozen event budget")
    return replay_input


def freeze_experiment(
    request: bytes,
    *,
    development_dataset_id: str,
    confirmation_dataset_id: str,
    datasets_factory: Callable[[], DatasetReader],
    registry_factory: Callable[[], ExecutableRepository],
) -> ExperimentReceipt:
    protocol = build_executable_protocol(
        request,
        development_dataset_id=development_dataset_id,
        confirmation_dataset_id=confirmation_dataset_id,
    )
    data = datasets_factory()
    try:
        development = read_accepted_events(development_dataset_id, data)
        confirmation = read_accepted_events(confirmation_dataset_id, data)
    except DataAccessError as error:
        raise ProtocolValidationError(str(error)) from error
    partitions = [
        tuple(cast("dict[str, object]", json.loads(line)) for line in value.splitlines())
        for value in (development, confirmation)
    ]
    assert_forward_disjoint(*partitions)
    _input(protocol, development)
    stored = registry_factory().seal(protocol.canonical_bytes)
    if (
        stored.protocol_id != protocol.protocol_id
        or stored.canonical_bytes != protocol.canonical_bytes
    ):
        raise ProtocolValidationError("Registry returned conflicting executable evidence")
    return ExperimentReceipt(
        protocol.protocol_id, protocol.claim_revision_id, stored.created, protocol.document
    )


def inspect_experiment(
    protocol_id: str, registry: ExecutableReader, datasets: DatasetReader
) -> ExperimentReceipt:
    protocol = _load(protocol_id, registry)
    for dataset_id in cast("dict[str, str]", protocol.document["datasets"]).values():
        if datasets.get(dataset_id).dataset_id != dataset_id:
            raise ProtocolValidationError("Executable data reference mismatch")
    return ExperimentReceipt(
        protocol.protocol_id, protocol.claim_revision_id, False, protocol.document
    )


def run_experiment(
    protocol_id: str,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], AttemptLedger],
    engine_factory: Callable[[int], ReplayPort],
) -> RunSubmission:
    if split != "development":
        raise ConfirmationAccessDenied("Executable protocols permit development replay only")
    protocol = _load(protocol_id, registry_factory())
    dataset_id = cast("dict[str, str]", protocol.document["datasets"])["development"]
    try:
        data = read_accepted_events(dataset_id, datasets_factory())
    except DataAccessError as error:
        raise ProtocolValidationError(str(error)) from error
    replay_input = _input(protocol, data)
    ledger = ledger_factory()
    reservation = ledger.reserve(protocol)
    budget = cast("dict[str, int]", protocol.document["budget"])
    try:
        result = engine_factory(budget["max_wall_seconds"]).run(replay_input)
        evaluation = ProtocolEvaluation(protocol, replay_input, result)
        receipt = build_run_receipt(
            {
                "kind": "research_run_receipt_v1",
                "schema_version": 1,
                "attempt": reservation.document,
                "protocol_id": protocol.protocol_id,
                "claim_revision_id": protocol.claim_revision_id,
                "execution_status": result.document["execution_status"],
                "scope": dict(SCOPE),
                "bindings": {
                    "dataset_id": dataset_id,
                    "data_sha256": digest(data),
                    "replay_spec_id": replay_input.spec.spec_id,
                    "replay_result_sha256": digest(result.canonical_bytes),
                    "evaluation_sha256": evaluation.evaluation_id,
                },
            }
        )
        stored = ledger.publish(
            reservation,
            receipt.canonical_bytes,
            artifacts=(result.canonical_bytes, evaluation.canonical_bytes),
        )
        if stored != receipt.run_id:
            raise EvidenceValidationError("Attempt ledger returned a conflicting outcome identity")
        return RunSubmission(
            receipt.run_id,
            reservation.attempt_id,
            cast("str", result.document["execution_status"]),
            evaluation.document,
        )
    except Exception as error:
        raw_code, raw_exit = (
            getattr(error, "code", "research_run_failed"),
            getattr(error, "exit_code", 7),
        )
        code = (
            raw_code
            if isinstance(raw_code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", raw_code)
            else "research_run_failed"
        )
        exit_code = raw_exit if type(raw_exit) is int and raw_exit in (2, 3, 4, 6, 7) else 7
        message = (
            (str(error) or type(error).__name__)
            .encode("utf-8", errors="backslashreplace")[:4096]
            .decode("utf-8", errors="ignore")
        )
        failure = canonical(
            {
                "kind": "replay_attempt_failure_v1",
                "schema_version": 1,
                "attempt": reservation.document,
                "protocol_id": protocol.protocol_id,
                "error": {"code": code, "message": message},
            }
        )
        try:
            ledger.publish(reservation, failure)
        except Exception as publication_error:
            raise ProtocolRunError(
                "attempt_outcome_unconfirmed",
                "Attempt remains consumed; outcome publication could not be confirmed",
                reservation.attempt_id,
                3,
            ) from publication_error
        raise ProtocolRunError(code, message, reservation.attempt_id, exit_code) from error


def inspect_attempt(attempt_id: str, ledger: AttemptLedger) -> dict[str, object]:
    reservation = ledger.get_reservation(attempt_id)
    outcome = ledger.get_outcome(attempt_id)
    return {
        "attempt_id": attempt_id,
        "reservation": reservation.document,
        "budget_consumed": True,
        "state": "reserved_unfinalized" if outcome is None else "finalized",
        "outcome": None if outcome is None else parse(outcome),
    }


def run_artifacts(
    run_id: str,
    *,
    ledger: AttemptLedger,
    registry: ExecutableReader,
    datasets: DatasetEvidenceReader,
) -> dict[str, bytes]:
    receipt = load_run_receipt(ledger.read_artifact(identity(run_id), max_bytes=16_384))
    if receipt.run_id != run_id:
        raise EvidenceValidationError("Run identity does not match its receipt")
    run = receipt.document
    reservation_bytes = canonical(cast("dict[str, object]", run["attempt"]))
    attempt_id = digest(reservation_bytes)
    if (
        ledger.get_reservation(attempt_id).canonical_bytes != reservation_bytes
        or ledger.get_outcome(attempt_id) != receipt.canonical_bytes
    ):
        raise EvidenceValidationError("Run is not the committed outcome of its reservation")
    protocol = _load(cast("str", run["protocol_id"]), registry)
    bindings = cast("dict[str, str]", run["bindings"])
    development = cast("dict[str, str]", protocol.document["datasets"])["development"]
    if (
        bindings["dataset_id"] != development
        or run["claim_revision_id"] != protocol.claim_revision_id
        or bindings["replay_spec_id"] != protocol.document["replay_spec_id"]
    ):
        raise EvidenceValidationError("Run does not bind the protocol's development inputs")
    artifacts = datasets.read_artifacts(development)
    artifacts.update(
        {
            "protocol": protocol.canonical_bytes,
            "attempt": receipt.canonical_bytes,
            "replay_result": ledger.read_artifact(bindings["replay_result_sha256"]),
            "evaluation": ledger.read_artifact(
                bindings["evaluation_sha256"], max_bytes=4 * 1024 * 1024
            ),
        }
    )
    verify_artifacts(artifacts)
    return artifacts


def export_run(
    run_id: str,
    *,
    ledger: AttemptLedger,
    registry: ExecutableReader,
    datasets: DatasetEvidenceReader,
    exporter: Callable[[dict[str, bytes]], EvidencePackage],
) -> dict[str, object]:
    artifacts = run_artifacts(run_id, ledger=ledger, registry=registry, datasets=datasets)
    return verify_package(exporter(artifacts))


def verify_package(package: EvidencePackage) -> dict[str, object]:
    result = verify_artifacts(package.artifacts)
    return {"bundle_id": identity(package.bundle_id), **result}
