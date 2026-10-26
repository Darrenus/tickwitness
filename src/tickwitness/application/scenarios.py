"""Check proposed stress contracts against one immutable development baseline.

This use case reads input evidence, but never evaluates a strategy, reserves an
attempt, writes a transformed dataset, or authorizes native scenario execution.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.application.experiments import ExecutableReader
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.assumptions.specs import (
    AssumptionSpec,
    AssumptionValidationError,
    ScenarioSpec,
    ValidatedScenario,
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol


@dataclass(frozen=True, slots=True)
class ScenarioValidationReceipt:
    assumption: AssumptionSpec
    scenario: ScenarioSpec
    validation: ValidatedScenario

    @property
    def assumption_id(self) -> str:
        return self.assumption.assumption_id

    @property
    def scenario_id(self) -> str:
        return self.scenario.scenario_id

    @property
    def document(self) -> dict[str, object]:
        return {
            "assumption": self.assumption.document,
            "scenario": self.scenario.document,
            "validation": self.validation.document,
        }


def validate_scenario_contracts(
    protocol_id: str,
    assumption_request: bytes,
    scenario_request: bytes,
    *,
    split: str,
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetReader],
) -> ScenarioValidationReceipt:
    if split != "development":
        raise ConfirmationAccessDenied("Scenario contracts permit development evidence only")
    if not isinstance(protocol_id, str) or re.fullmatch(r"[0-9a-f]{64}", protocol_id) is None:
        raise AssumptionValidationError("protocol_id must be a lowercase SHA-256 identity")
    stored = registry_factory().get(protocol_id)
    protocol = load_executable_protocol(stored.canonical_bytes)
    if stored.protocol_id != protocol_id or protocol.protocol_id != protocol_id:
        raise AssumptionValidationError("Registry returned a conflicting executable protocol")
    document = protocol.document
    dataset_id = cast("dict[str, str]", document["datasets"])["development"]
    try:
        data = read_accepted_events(dataset_id, datasets_factory())
        replay_spec = build_replay_spec(
            json.dumps(document["replay_spec"], allow_nan=False).encode("utf-8")
        )
        replay_input = ReplayInput(dataset_id, data, replay_spec)
        assumptions = build_assumption_spec(
            assumption_request, protocol=protocol, replay_input=replay_input
        )
        scenario = build_scenario_spec(scenario_request, assumptions=assumptions)
        validated = validate_scenario_spec(
            scenario, assumptions, protocol=protocol, replay_input=replay_input
        )
    except (DataAccessError, ReplayValidationError) as error:
        raise AssumptionValidationError(str(error)) from error
    return ScenarioValidationReceipt(assumptions, scenario, validated)
