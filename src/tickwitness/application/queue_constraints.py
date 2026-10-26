"""Read-only external-queue constraint checks, separate from research execution."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.application.experiments import ExecutableReader
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.assumptions.queue_constraints import (
    QueueConstraintSpec,
    QueueConstraintValidationError,
    QueueFeasibilityPair,
    build_queue_constraint_spec,
    validate_queue_constraints,
)
from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol


@dataclass(frozen=True, slots=True)
class QueueConstraintValidationReceipt:
    constraint: QueueConstraintSpec
    validation: QueueFeasibilityPair

    @property
    def document(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint.constraint_id,
            "validation_id": self.validation.validation_id,
            "constraint": self.constraint.document,
            "validation": self.validation.document,
        }


def validate_queue_contracts(
    protocol_id: str,
    request: bytes,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
) -> QueueConstraintValidationReceipt:
    """Check declarations against real development evidence without opening an engine."""
    if split != "development":
        raise ConfirmationAccessDenied("Queue constraints permit development evidence only")
    if not isinstance(protocol_id, str) or re.fullmatch(r"[0-9a-f]{64}", protocol_id) is None:
        raise QueueConstraintValidationError("protocol_id must be a lowercase SHA-256 identity")
    stored = registry_factory().get(protocol_id)
    protocol = load_executable_protocol(stored.canonical_bytes)
    if stored.protocol_id != protocol_id or protocol.protocol_id != protocol_id:
        raise QueueConstraintValidationError("Queue source protocol identity mismatch")
    document = protocol.document
    dataset_id = cast("dict[str, str]", document["datasets"])["development"]
    try:
        data = read_accepted_events(dataset_id, datasets_factory())
        spec = build_replay_spec(canonical(cast("dict[str, object]", document["replay_spec"])))
        replay_input = ReplayInput(dataset_id, data, spec)
        constraint = build_queue_constraint_spec(
            request, protocol=protocol, replay_input=replay_input
        )
        validation = validate_queue_constraints(
            constraint, protocol=protocol, replay_input=replay_input
        )
    except (DataAccessError, ReplayValidationError) as error:
        raise QueueConstraintValidationError(str(error)) from error
    return QueueConstraintValidationReceipt(constraint, validation)
