"""Budgeted receive-clock stress runs, distinct from baseline claim evaluation."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.application.experiments import AttemptLedger, ExecutableReader, ProtocolRunError
from tickwitness.application.scenarios import validate_scenario_contracts
from tickwitness.domain.assumptions.derivation import DerivedReplayView, derive_replay_view
from tickwitness.domain.assumptions.specs import (
    load_assumption_spec,
    load_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.scenario_records import (
    ScenarioEvaluation,
    build_scenario_failure,
    build_scenario_intent,
    build_scenario_run_receipt,
    load_scenario_run_receipt,
)
from tickwitness.domain.replay.contracts import ReplayInput, ReplayPort, load_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol


class ScenarioLedger(AttemptLedger, Protocol):
    def bind_intent(
        self, reservation: AttemptReservation, intent: bytes, *, artifacts: tuple[bytes, ...] = ()
    ) -> str: ...

    def get_intent(self, attempt_id: str) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class ScenarioSubmission:
    run_id: str
    attempt_id: str
    intent_id: str
    derived_view_id: str
    execution_status: str
    evaluation: dict[str, object]


def _artifacts(view: DerivedReplayView) -> tuple[bytes, ...]:
    return (
        view.validated.assumptions.canonical_bytes,
        view.validated.scenario.canonical_bytes,
        view.canonical_bytes,
        view.replay_input.normalized_bytes,
    )


def run_scenario(
    protocol_id: str,
    assumption_request: bytes,
    scenario_request: bytes,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
    ledger_factory: Callable[[], ScenarioLedger],
    engine_factory: Callable[[int], ReplayPort],
) -> ScenarioSubmission:
    checked = validate_scenario_contracts(
        protocol_id,
        assumption_request,
        scenario_request,
        split=split,
        registry_factory=registry_factory,
        datasets_factory=datasets_factory,
    )
    view = derive_replay_view(checked.validation)
    intent = build_scenario_intent(view)
    # The original protocol owns every slot, including all candidates and failures.
    protocol = checked.validation.protocol
    ledger = ledger_factory()
    reservation = ledger.reserve(protocol)
    budget = cast("dict[str, int]", protocol.document["budget"])
    try:
        if (
            reservation.protocol_id != protocol.protocol_id
            or reservation.attempt_index > budget["max_attempts"]
            or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
        ):
            raise EvidenceValidationError("Scenario reservation differs from the frozen budget")
        committed = ledger.bind_intent(reservation, intent.canonical_bytes, artifacts=_artifacts(view))
        if committed != intent.intent_id:
            raise EvidenceValidationError("Ledger returned a conflicting scenario intent")
        result = engine_factory(budget["max_wall_seconds"]).run(view.replay_input)
        evaluation = ScenarioEvaluation(view, result)
        receipt = build_scenario_run_receipt(
            {
                "kind": "scenario_run_receipt_v1",
                "schema_version": 1,
                "attempt": reservation.document,
                "protocol_id": protocol.protocol_id,
                "claim_revision_id": protocol.claim_revision_id,
                "scope": intent.document["scope"],
                "intent": intent.document,
                "execution_status": result.document["execution_status"],
                "bindings": {
                    "replay_result_sha256": digest(result.canonical_bytes),
                    "evaluation_sha256": evaluation.evaluation_id,
                },
            }
        )
        outcome_id = ledger.publish(
            reservation,
            receipt.canonical_bytes,
            artifacts=(result.canonical_bytes, evaluation.canonical_bytes),
        )
        if outcome_id != receipt.run_id:
            raise EvidenceValidationError("Ledger returned a conflicting scenario outcome")
        return ScenarioSubmission(
            receipt.run_id,
            reservation.attempt_id,
            intent.intent_id,
            view.view_id,
            cast("str", result.document["execution_status"]),
            evaluation.document,
        )
    except Exception as error:
        raw_code, raw_exit = getattr(error, "code", "scenario_run_failed"), getattr(
            error, "exit_code", 7
        )
        code = (
            raw_code
            if isinstance(raw_code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", raw_code)
            else "scenario_run_failed"
        )
        exit_code = raw_exit if type(raw_exit) is int and raw_exit in (2, 3, 4, 6, 7) else 7
        message = (
            (str(error) or type(error).__name__)
            .encode("utf-8", errors="backslashreplace")[:4096]
            .decode("utf-8", errors="ignore")
        )
        try:
            ledger.publish(
                reservation, build_scenario_failure(reservation, intent, code, message)
            )
        except Exception as publication_error:
            raise ProtocolRunError(
                "attempt_outcome_unconfirmed",
                "Attempt remains consumed; scenario outcome publication could not be confirmed",
                reservation.attempt_id,
                3,
            ) from publication_error
        raise ProtocolRunError(code, message, reservation.attempt_id, exit_code) from error


def inspect_scenario_run(
    run_id: str,
    *,
    ledger: ScenarioLedger,
    registry: ExecutableReader,
    datasets: DatasetReader,
) -> dict[str, object]:
    """Recompute the view and accounting from committed evidence, without native replay."""
    identity(run_id)
    raw = ledger.read_artifact(run_id, max_bytes=16 * 1024)
    receipt = load_scenario_run_receipt(raw)
    if receipt.run_id != run_id:
        raise EvidenceValidationError("Scenario run identity differs from requested evidence")
    document = receipt.document
    attempt_raw = canonical(cast("dict[str, object]", document["attempt"]))
    reservation = AttemptReservation(digest(attempt_raw), attempt_raw)
    if ledger.get_reservation(reservation.attempt_id) != reservation:
        raise EvidenceValidationError("Scenario reservation differs from committed evidence")
    if ledger.get_outcome(reservation.attempt_id) != raw:
        raise EvidenceValidationError("Scenario outcome is not the committed attempt outcome")
    intent_raw = canonical(cast("dict[str, object]", document["intent"]))
    if ledger.get_intent(reservation.attempt_id) != intent_raw:
        raise EvidenceValidationError("Scenario intent differs from committed evidence")
    protocol_id = cast("str", document["protocol_id"])
    stored = registry.get(protocol_id)
    protocol = load_executable_protocol(stored.canonical_bytes)
    if stored.protocol_id != protocol_id or protocol.protocol_id != protocol_id:
        raise EvidenceValidationError("Scenario protocol identity mismatch")
    budget = cast("dict[str, int]", protocol.document["budget"])
    if (
        reservation.attempt_index > budget["max_attempts"]
        or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
    ):
        raise EvidenceValidationError("Scenario reservation differs from the frozen budget")
    source_id = cast("dict[str, str]", protocol.document["datasets"])["development"]
    try:
        data = read_accepted_events(source_id, datasets)
    except DataAccessError as error:
        raise EvidenceValidationError(str(error)) from error
    spec = build_replay_spec(canonical(cast("dict[str, object]", protocol.document["replay_spec"])))
    source = ReplayInput(source_id, data, spec)
    intent_doc = cast("dict[str, object]", document["intent"])
    bindings = cast("dict[str, str]", intent_doc["bindings"])
    assumptions = load_assumption_spec(
        ledger.read_artifact(bindings["assumption_id"], max_bytes=64 * 1024)
    )
    scenario = load_scenario_spec(
        ledger.read_artifact(bindings["scenario_id"], max_bytes=64 * 1024)
    )
    view = derive_replay_view(
        validate_scenario_spec(scenario, assumptions, protocol=protocol, replay_input=source)
    )
    rebuilt_intent = build_scenario_intent(view)
    if rebuilt_intent.canonical_bytes != intent_raw:
        raise EvidenceValidationError("Scenario intent differs from independently derived evidence")
    if ledger.read_artifact(view.view_id, max_bytes=64 * 1024) != view.canonical_bytes:
        raise EvidenceValidationError("Stored derived-view descriptor differs from recomputation")
    if (
        ledger.read_artifact(digest(view.replay_input.normalized_bytes), max_bytes=8 * 1024 * 1024)
        != view.replay_input.normalized_bytes
    ):
        raise EvidenceValidationError("Stored derived tape differs from recomputation")
    result_bindings = cast("dict[str, str]", document["bindings"])
    result = load_replay_result(ledger.read_artifact(result_bindings["replay_result_sha256"]))
    if digest(result.canonical_bytes) != result_bindings["replay_result_sha256"]:
        raise EvidenceValidationError("Scenario result identity mismatch")
    evaluation = ScenarioEvaluation(view, result)
    if (
        evaluation.evaluation_id != result_bindings["evaluation_sha256"]
        or
        ledger.read_artifact(result_bindings["evaluation_sha256"], max_bytes=4 * 1024 * 1024)
        != evaluation.canonical_bytes
    ):
        raise EvidenceValidationError("Scenario accounting differs from recomputation")
    if document["execution_status"] != result.document["execution_status"]:
        raise EvidenceValidationError("Scenario execution status differs from audited result")
    return {
        "run_id": receipt.run_id,
        "receipt": document,
        "derivation": view.document,
        "evaluation": evaluation.document,
        "verification": {
            "kind": "scenario_ledger_verification_v1",
            "integrity_verified": True,
            "bindings_verified": True,
            "derivation_recomputed": True,
            "accounting_verified": True,
            "native_replayed": False,
            "confirmation_reference_checked": False,
            "full_attempt_ledger_checked": False,
            "author_signature_verified": False,
        },
    }
