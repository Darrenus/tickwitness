"""Declarations for one receive-clock pressure intent; no transformation/execution.

The only accepted intent is an uncalibrated researcher-defined suffix shift.
It cannot certify historical compatibility, calibration, or a native run.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal, Never, cast

from tickwitness.domain.replay.contracts import PreparedReplay, ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.domain.research_contracts.executable import ExecutableProtocol

_LIMIT = 65_536
_INT64_MAX = (1 << 63) - 1
_DELAY_CAP_NS = 60_000_000_000  # Software scope, never an empirical/physical latency bound.
_SCENARIO_KIND = "COUNTERFACTUAL_STRESS"
_TRANSFORM = "replay_receive_suffix_shift_v1"
_ASSUMPTION_REQUEST_FIELDS = {
    "kind",
    "schema_version",
    "scenario_kind",
    "transform",
    "additional_delay",
    "parameter_basis",
}
_SCENARIO_REQUEST_FIELDS = {"kind", "schema_version", "scenario_kind", "additional_delay"}
type Document = dict[str, object]


class AssumptionValidationError(ValueError):
    """A declaration or its actual source bindings violate this limited profile."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssumptionValidationError(message)


def _canonical(document: Document) -> bytes:
    try:
        return json.dumps(
            document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise AssumptionValidationError(
            "Declaration cannot be canonical finite UTF-8 JSON"
        ) from error


def _unique(pairs: list[tuple[str, object]]) -> Document:
    document: Document = {}
    for key, value in pairs:
        _require(key not in document, "Duplicate declaration JSON field")
        document[key] = value
    return document


def _reject_number(_value: str) -> Never:
    raise AssumptionValidationError("Declaration JSON must not contain floating-point numbers")


def _parse(raw: bytes) -> Document:
    _require(
        isinstance(raw, bytes) and 0 < len(raw) <= _LIMIT,
        "Declaration must be immutable nonempty bytes within 64 KiB",
    )
    try:
        document: object = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except AssumptionValidationError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise AssumptionValidationError("Declaration is invalid bounded JSON") from error
    _require(isinstance(document, dict), "Declaration must be a JSON object")
    return cast("Document", document)


def _exact(value: object, keys: set[str], label: str) -> Document:
    _require(
        isinstance(value, dict) and value.keys() == keys, label + " has missing or unknown fields"
    )
    return cast("Document", value)


def _integer(value: object, label: str, low: int = 0, high: int = _INT64_MAX) -> int:
    _require(
        type(value) is int and low <= value <= high,
        f"{label} must be an integer in [{low}, {high}]",
    )
    return cast("int", value)


def _identity(value: object, label: str) -> str:
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        label + " must be a lowercase SHA-256 identity",
    )
    return cast("str", value)


def _equal(left: object, right: object, message: str) -> None:
    _require(_canonical({"value": left}) == _canonical({"value": right}), message)


def _markers(document: Document, kind: str) -> None:
    _equal(document["kind"], kind, "Unsupported declaration kind")
    _integer(document["schema_version"], "schema_version", 1, 1)
    _equal(
        document["scenario_kind"],
        _SCENARIO_KIND,
        "Only COUNTERFACTUAL_STRESS is supported; added delay is not historical interpretation",
    )


def _bounds(value: object) -> tuple[int, int]:
    bounds = _exact(value, {"minimum", "maximum", "unit"}, "additional_delay")
    _equal(bounds["unit"], "ns", "Additional delay requires explicit unit ns")
    minimum = _integer(bounds["minimum"], "minimum", 0, _DELAY_CAP_NS)
    maximum = _integer(bounds["maximum"], "maximum", minimum, _DELAY_CAP_NS)
    return minimum, maximum


def _candidate(value: object) -> int:
    delay = _exact(value, {"value", "unit"}, "additional_delay")
    _equal(delay["unit"], "ns", "Additional delay requires explicit unit ns")
    return _integer(delay["value"], "additional delay value", 0, _DELAY_CAP_NS)


def _assumption_document(document: Document, *, request: bool) -> None:
    fields = _ASSUMPTION_REQUEST_FIELDS if request else _ASSUMPTION_REQUEST_FIELDS | {"bindings"}
    _exact(document, fields, "Assumption request" if request else "AssumptionSpec")
    _markers(document, "assumption_request_v1" if request else "assumption_spec_v1")
    transform = _exact(document["transform"], {"semantic_id", "from_capture_seq"}, "transform")
    _equal(transform["semantic_id"], _TRANSFORM, "Unsupported typed receive-delay intent")
    _integer(transform["from_capture_seq"], "from_capture_seq", 1)
    _bounds(document["additional_delay"])
    basis = _exact(
        document["parameter_basis"],
        {"kind", "calibration_status", "calibration_evidence_refs"},
        "parameter_basis",
    )
    _equal(
        basis,
        {
            "kind": "researcher_defined",
            "calibration_status": "uncalibrated",
            "calibration_evidence_refs": [],
        },
        "Pressure parameters require researcher_defined, uncalibrated, and empty evidence refs",
    )
    if not request:
        bindings = _exact(
            document["bindings"],
            {"protocol_id", "development_dataset_id", "normalized_sha256", "replay_spec_id"},
            "assumption bindings",
        )
        for label, value in bindings.items():
            _identity(value, label)


def _scenario_document(document: Document, *, request: bool) -> None:
    fields = _SCENARIO_REQUEST_FIELDS if request else _SCENARIO_REQUEST_FIELDS | {"assumption_id"}
    _exact(document, fields, "Scenario request" if request else "ScenarioSpec")
    _markers(document, "scenario_request_v1" if request else "scenario_spec_v1")
    _candidate(document["additional_delay"])
    if not request:
        _identity(document["assumption_id"], "assumption_id")


@dataclass(frozen=True, slots=True)
class AssumptionSpec:
    assumption_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        document = _parse(self.canonical_bytes)
        _assumption_document(document, request=False)
        _require(_canonical(document) == self.canonical_bytes, "AssumptionSpec must be canonical")
        _equal(
            _identity(self.assumption_id, "assumption_id"),
            hashlib.sha256(self.canonical_bytes).hexdigest(),
            "AssumptionSpec identity mismatch",
        )

    @property
    def document(self) -> Document:
        return _parse(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    scenario_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        document = _parse(self.canonical_bytes)
        _scenario_document(document, request=False)
        _require(_canonical(document) == self.canonical_bytes, "ScenarioSpec must be canonical")
        _equal(
            _identity(self.scenario_id, "scenario_id"),
            hashlib.sha256(self.canonical_bytes).hexdigest(),
            "ScenarioSpec identity mismatch",
        )

    @property
    def document(self) -> Document:
        return _parse(self.canonical_bytes)


def _bindings(protocol: ExecutableProtocol, replay_input: ReplayInput) -> Document:
    _require(
        isinstance(protocol, ExecutableProtocol), "Assumptions require an ExecutableProtocol v2"
    )
    _require(isinstance(replay_input, ReplayInput), "Assumptions require a validated ReplayInput")
    document = protocol.document
    datasets = cast("dict[str, str]", document["datasets"])
    _equal(
        replay_input.dataset_id,
        datasets["development"],
        "Scenario input must be the protocol's development dataset, never confirmation",
    )
    _equal(
        replay_input.spec.spec_id,
        document["replay_spec_id"],
        "Scenario replay spec binding mismatch",
    )
    _equal(
        replay_input.spec.document, document["replay_spec"], "Scenario replay spec content mismatch"
    )
    return {
        "protocol_id": protocol.protocol_id,
        "development_dataset_id": replay_input.dataset_id,
        "normalized_sha256": hashlib.sha256(replay_input.normalized_bytes).hexdigest(),
        "replay_spec_id": replay_input.spec.spec_id,
    }


def _input_constraints(
    assumptions: AssumptionSpec, *, protocol: ExecutableProtocol, replay_input: ReplayInput
) -> PreparedReplay:
    _require(isinstance(assumptions, AssumptionSpec), "Expected AssumptionSpec")
    document = assumptions.document
    _equal(
        document["bindings"],
        _bindings(protocol, replay_input),
        "Assumption actual source bindings mismatch",
    )
    try:
        prepared = preflight_replay(replay_input)
    except ReplayValidationError as error:
        raise AssumptionValidationError(
            "Assumption input preflight failed: " + str(error)
        ) from error
    budget = cast("dict[str, int]", protocol.document["budget"])
    _require(
        len(prepared.events) <= budget["max_events"], "Source input exceeds the frozen event budget"
    )
    anchor = cast("Document", document["transform"])["from_capture_seq"]
    _require(
        anchor in {event.capture_seq for event in prepared.events},
        "from_capture_seq must identify an actual development input",
    )
    _, maximum = _bounds(document["additional_delay"])
    _horizon(prepared, maximum)
    return prepared


def _horizon(prepared: PreparedReplay, delay: int) -> None:
    execution = cast("dict[str, int]", prepared.spec.document["execution"])
    last = prepared.events[-1].receive_time_ns
    _require(
        last + delay + execution["insert_latency_ns"] + execution["cancel_latency_ns"]
        <= _INT64_MAX,
        "Additional receive delay plus the frozen native latency horizon exceeds int64",
    )


def _scenario_bindings(scenario: ScenarioSpec, assumptions: AssumptionSpec) -> int:
    _require(isinstance(scenario, ScenarioSpec), "Expected ScenarioSpec")
    _require(isinstance(assumptions, AssumptionSpec), "Expected AssumptionSpec")
    document = scenario.document
    _equal(
        document["assumption_id"],
        assumptions.assumption_id,
        "Scenario assumption identity mismatch",
    )
    delay = _candidate(document["additional_delay"])
    minimum, maximum = _bounds(assumptions.document["additional_delay"])
    _require(minimum <= delay <= maximum, "Scenario delay is outside its frozen assumption range")
    return delay


def build_assumption_spec(
    raw: bytes, *, protocol: ExecutableProtocol, replay_input: ReplayInput
) -> AssumptionSpec:
    request = _parse(raw)
    _assumption_document(request, request=True)
    document = {
        **request,
        "kind": "assumption_spec_v1",
        "bindings": _bindings(protocol, replay_input),
    }
    encoded = _canonical(document)
    assumptions = AssumptionSpec(hashlib.sha256(encoded).hexdigest(), encoded)
    _input_constraints(assumptions, protocol=protocol, replay_input=replay_input)
    return assumptions


def load_assumption_spec(raw: bytes) -> AssumptionSpec:
    """Check canonical structure/identity only; external source bindings remain unverified."""
    _parse(raw)
    return AssumptionSpec(hashlib.sha256(raw).hexdigest(), raw)


def build_scenario_spec(raw: bytes, *, assumptions: AssumptionSpec) -> ScenarioSpec:
    _require(isinstance(assumptions, AssumptionSpec), "Expected AssumptionSpec")
    request = _parse(raw)
    _scenario_document(request, request=True)
    document = {**request, "kind": "scenario_spec_v1", "assumption_id": assumptions.assumption_id}
    encoded = _canonical(document)
    scenario = ScenarioSpec(hashlib.sha256(encoded).hexdigest(), encoded)
    _scenario_bindings(scenario, assumptions)
    return scenario


def load_scenario_spec(raw: bytes) -> ScenarioSpec:
    """Check canonical structure/identity only, without choosing or executing a model."""
    _parse(raw)
    return ScenarioSpec(hashlib.sha256(raw).hexdigest(), raw)


@dataclass(frozen=True, slots=True)
class ValidatedScenario:
    scenario: ScenarioSpec
    assumptions: AssumptionSpec
    protocol: ExecutableProtocol
    replay_input: ReplayInput
    source_bindings_verified: Literal[True] = field(default=True, init=False)
    input_constraints_verified: Literal[True] = field(default=True, init=False)
    calibration_status: Literal["uncalibrated"] = field(default="uncalibrated", init=False)
    execution_approved: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        delay = _scenario_bindings(self.scenario, self.assumptions)
        prepared = _input_constraints(
            self.assumptions, protocol=self.protocol, replay_input=self.replay_input
        )
        _horizon(prepared, delay)

    @property
    def document(self) -> Document:
        assumptions, scenario = self.assumptions.document, self.scenario.document
        return {
            "kind": "validated_scenario_constraints_v1",
            "schema_version": 1,
            "scenario_id": self.scenario.scenario_id,
            "assumption_id": self.assumptions.assumption_id,
            "bindings": assumptions["bindings"],
            "scenario_kind": _SCENARIO_KIND,
            "transform": assumptions["transform"],
            "additional_delay": scenario["additional_delay"],
            "source_bindings_verified": True,
            "input_constraints_verified": True,
            "calibration_status": "uncalibrated",
            "execution_approved": False,
        }


def validate_scenario_spec(
    scenario: ScenarioSpec,
    assumptions: AssumptionSpec,
    *,
    protocol: ExecutableProtocol,
    replay_input: ReplayInput,
) -> ValidatedScenario:
    """Validate declarations against actual development input; never transform or replay it."""
    return ValidatedScenario(scenario, assumptions, protocol, replay_input)
