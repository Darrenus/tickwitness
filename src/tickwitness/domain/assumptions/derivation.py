"""Pure receive-clock views derived from revalidated development declarations.

A view identity is the hash of this derivation document, not a dataset catalog
manifest. Its ReplayInput deliberately uses that separate identity. The view
does not certify an independent feed delay or authorize native execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import cast

from tickwitness.domain.assumptions.specs import (
    AssumptionSpec,
    AssumptionValidationError,
    ScenarioSpec,
    ValidatedScenario,
    validate_scenario_spec,
)
from tickwitness.domain.replay.contracts import PreparedReplay, ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplaySpec, ReplayValidationError
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    ProtocolValidationError,
)

CLOCK_PROFILE_ID = "coupled_receive_suffix_clock_v1"
MAX_DERIVATION_BYTES = 65_536


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(document: dict[str, object]) -> bytes:
    return json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _revalidate(validated: ValidatedScenario) -> ValidatedScenario:
    if not isinstance(validated, ValidatedScenario) or not (
        isinstance(validated.assumptions, AssumptionSpec)
        and isinstance(validated.scenario, ScenarioSpec)
        and isinstance(validated.protocol, ExecutableProtocol)
        and isinstance(validated.replay_input, ReplayInput)
        and isinstance(validated.replay_input.spec, ReplaySpec)
    ):
        raise AssumptionValidationError("Derivation requires a complete ValidatedScenario")
    source = validated.replay_input
    try:
        # Reconstruct every immutable value so neither previously set markers nor
        # a forged frozen instance can bypass canonical/identity/source checks.
        protocol = ExecutableProtocol(
            validated.protocol.protocol_id,
            validated.protocol.claim_revision_id,
            validated.protocol.canonical_bytes,
        )
        spec = ReplaySpec(source.spec.spec_id, source.spec.canonical_bytes)
        replay_input = ReplayInput(source.dataset_id, source.normalized_bytes, spec)
        assumptions = AssumptionSpec(
            validated.assumptions.assumption_id, validated.assumptions.canonical_bytes
        )
        scenario = ScenarioSpec(validated.scenario.scenario_id, validated.scenario.canonical_bytes)
        return validate_scenario_spec(
            scenario, assumptions, protocol=protocol, replay_input=replay_input
        )
    except (ProtocolValidationError, ReplayValidationError) as error:
        raise AssumptionValidationError(
            "Derivation source revalidation failed: " + str(error)
        ) from error


def _shift(source: PreparedReplay, anchor: int, delay: int) -> bytes:
    if delay == 0:
        return source.replay_input.normalized_bytes
    output: list[bytes] = []
    for line, event in zip(
        source.replay_input.normalized_bytes.splitlines(keepends=True), source.events, strict=True
    ):
        if event.capture_seq >= anchor:
            # The source is already canonical JSONL. Replace this one numeric
            # token, retaining every other byte, including the line terminator.
            before = f'"receive_time_ns":{event.receive_time_ns},'.encode("ascii")
            after = f'"receive_time_ns":{event.receive_time_ns + delay},'.encode("ascii")
            if line.count(before) != 1:
                raise AssumptionValidationError("Canonical source receive token is not unique")
            line = line.replace(before, after, 1)
        output.append(line)
    return b"".join(output)


@dataclass(frozen=True, slots=True)
class DerivedReplayView:
    """Recomputed immutable view; supplied hashes or transformed bytes are not accepted."""

    validated: ValidatedScenario
    canonical_bytes: bytes = field(init=False)
    replay_input: ReplayInput = field(init=False)

    def __post_init__(self) -> None:
        checked = _revalidate(self.validated)
        source = preflight_replay(checked.replay_input)
        assumption, scenario = checked.assumptions.document, checked.scenario.document
        transform = cast("dict[str, object]", assumption["transform"])
        delay_document = cast("dict[str, object]", scenario["additional_delay"])
        anchor = cast("int", transform["from_capture_seq"])
        delay = cast("int", delay_document["value"])
        derived_bytes = _shift(source, anchor, delay)
        document: dict[str, object] = {
            "kind": "derived_replay_view_v1",
            "schema_version": 1,
            "clock_profile_id": CLOCK_PROFILE_ID,
            "identity_semantics": "derived_view_not_catalog_manifest_v1",
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "calibration_status": "uncalibrated",
            "source_bindings": assumption["bindings"],
            "assumption_id": checked.assumptions.assumption_id,
            "scenario_id": checked.scenario.scenario_id,
            "transform": transform,
            "additional_delay": delay_document,
            "derived": {
                "normalized_sha256": _digest(derived_bytes),
                "record_count": len(source.events),
            },
            "execution_approved": False,
        }
        encoded = _canonical(document)
        try:
            derived_input = ReplayInput(_digest(encoded), derived_bytes, source.spec)
            prepared = preflight_replay(derived_input)
        except ReplayValidationError as error:
            raise AssumptionValidationError(
                "Derived input preflight failed: " + str(error)
            ) from error
        for original, derived in zip(source.events, prepared.events, strict=True):
            receive = original.receive_time_ns + (delay if original.capture_seq >= anchor else 0)
            if derived != replace(original, receive_time_ns=receive):
                raise AssumptionValidationError(
                    "Derivation changed fields beyond suffix receive time"
                )
        if derived_input.dataset_id == source.dataset_id:
            raise AssumptionValidationError("Derived view identity cannot alias its source dataset")
        object.__setattr__(self, "validated", checked)
        object.__setattr__(self, "canonical_bytes", encoded)
        object.__setattr__(self, "replay_input", derived_input)

    @property
    def view_id(self) -> str:
        return _digest(self.canonical_bytes)

    @property
    def derived_input(self) -> ReplayInput:
        return self.replay_input

    @property
    def document(self) -> dict[str, object]:
        return cast("dict[str, object]", json.loads(self.canonical_bytes))


def derive_replay_view(validated: ValidatedScenario) -> DerivedReplayView:
    """Derive a coupled receive-clock view, with no engine, ledger, or storage access."""
    return DerivedReplayView(validated)


def load_derived_replay_view(raw: bytes, *, validated: ValidatedScenario) -> DerivedReplayView:
    """Recompute from source; a self-consistent hash or declaration alone is insufficient."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_DERIVATION_BYTES:
        raise AssumptionValidationError("Derived view requires immutable bytes within 64 KiB")
    rebuilt = derive_replay_view(validated)
    if raw != rebuilt.canonical_bytes:
        raise AssumptionValidationError("Derived view does not reproduce from its source context")
    return rebuilt
