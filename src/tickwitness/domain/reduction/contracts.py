"""Bounded reduction declarations and byte-preserved full-origin input plans.

The context identity describes planned replay input, never a running strategy,
account, order queue or checkpoint. Every materialization rederives the full
candidate scenario before retaining a contiguous prefix from the source origin.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from tickwitness.domain.assumptions import (
    ValidatedScenario,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.replay._validation import INT64_MAX, integer
from tickwitness.domain.replay._validation import parse as parse_request
from tickwitness.domain.replay.contracts import PreparedReplay, ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay

MAX_TOTAL_BYTES = 16 * 1024 * 1024
_ROLE_LIMITS = {"recipe": 64 * 1024, "materialization": 128 * 1024, "normalized": 8 * 1024 * 1024}
_REFS = {
    "recipe": "recipe.json",
    "materialization": "materialization.json",
    "normalized": "normalized.jsonl",
}
FLAGS: Mapping[str, object] = MappingProxyType(
    {
        "checkpoint_supported": False,
        "checkpoint_used": False,
        "initial_state_materialized": False,
        "requires_full_prefix_replay": True,
        "native_replayed": False,
        "attempt_reserved": False,
        "reduced_predicate_evaluated": False,
        "witness_preservation_verified": False,
        "checkpoint_resume_verified": False,
    }
)
SCOPE: Mapping[str, object] = MappingProxyType(
    {
        "phase": "development",
        "authority": "input_preparation_only_v1",
        "source_claim_authority_extended": False,
        "budget_owner_changed": False,
    }
)
_POLICY: Mapping[str, object] = MappingProxyType(
    {
        "id": "replay_from_original_origin_v1",
        "checkpoint_used": False,
        "prefix_reuse_allowed": False,
    }
)
_REQUEST_FIELDS = {
    "kind",
    "schema_version",
    "witness_ordinal",
    "focus_from_capture_seq",
    "through_capture_seq",
    "additional_delay_ns",
}
_SOURCE_HASHES = {
    "bundle_id",
    "report_id",
    "finding_protocol_id",
    "source_protocol_id",
    "source_claim_revision_id",
    "predicate_id",
    "source_run_id",
    "assumption_id",
    "source_scenario_id",
    "source_dataset_id",
    "source_normalized_sha256",
    "replay_spec_id",
}
_OPERATORS = {"focus_from_capture_seq", "through_capture_seq", "additional_delay_ns"}
type Row = dict[str, object]


class ReductionValidationError(EvidenceValidationError):
    """A declaration or saved preparation cannot reproduce from its source."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReductionValidationError(message)


def _same(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _exact(value: object, keys: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == keys, label + " fields differ")
    return cast("Row", value)


def role_limit(role: str) -> int:
    if not isinstance(role, str) or role not in _ROLE_LIMITS:
        raise ReductionValidationError("Unknown reduction preparation role: " + str(role))
    return _ROLE_LIMITS[role]


def load_reduction_request(raw: bytes) -> Row:
    try:
        request = _exact(parse_request(raw, 64 * 1024), _REQUEST_FIELDS, "Reduction request")
        _same(
            [request["kind"], request["schema_version"]],
            ["reduction_request_v1", 1],
            "Unsupported reduction request",
        )
        integer(request["witness_ordinal"], "witness_ordinal", 1, 1024)
        for name in _OPERATORS:
            integer(request[name], name, 0 if name == "additional_delay_ns" else 1, INT64_MAX)
        return request
    except (ValueError, TypeError, KeyError) as error:
        raise ReductionValidationError(str(error)) from error


def build_reduction_manifest(artifacts: Mapping[str, bytes]) -> bytes:
    try:
        _require(
            isinstance(artifacts, Mapping) and artifacts.keys() == _ROLE_LIMITS.keys(),
            "Reduction preparation requires exactly three artifact roles",
        )
        for role, raw in artifacts.items():
            _require(
                type(raw) is bytes and 0 < len(raw) <= role_limit(role),
                "Reduction artifact exceeds its nonempty byte limit: " + role,
            )
            if role != "normalized":
                parse(raw, limit=role_limit(role))
        manifest = canonical(
            {
                "kind": "reduction_preparation_bundle_v1",
                "schema_version": 1,
                "scope": "development_input_preparation_only_v1",
                "roles": {
                    role: {"sha256": digest(raw), "size_bytes": len(raw), "ref": _REFS[role]}
                    for role, raw in artifacts.items()
                },
            }
        )
        _require(
            len(manifest) + sum(len(raw) for raw in artifacts.values()) <= MAX_TOTAL_BYTES,
            "Reduction preparation exceeds its total byte limit",
        )
        return manifest
    except (ValueError, TypeError, KeyError) as error:
        raise ReductionValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class ReductionSource:
    """Application-selected actual false witness and its full validated source."""

    bundle_id: str
    report_id: str
    finding_protocol_id: str
    predicate_id: str
    source_run_id: str
    witness_ordinal: int
    validation: ValidatedScenario

    def __post_init__(self) -> None:
        try:
            for value in (
                self.bundle_id,
                self.report_id,
                self.finding_protocol_id,
                self.predicate_id,
                self.source_run_id,
            ):
                identity(value)
            integer(self.witness_ordinal, "witness_ordinal", 1, 1024)
            _require(
                type(self.validation) is ValidatedScenario,
                "Reduction source needs a validated original scenario",
            )
        except (ValueError, TypeError) as error:
            raise ReductionValidationError(str(error)) from error


def _source_document(source: ReductionSource) -> Row:
    # Rebuild all frozen declarations, actual input and original scenario rather
    # than treating a previously returned validation flag as a certificate.
    validated = derive_replay_view(source.validation).validated
    protocol = validated.protocol
    return {
        "bundle_id": source.bundle_id,
        "report_id": source.report_id,
        "finding_protocol_id": source.finding_protocol_id,
        "source_protocol_id": protocol.protocol_id,
        "source_claim_revision_id": protocol.claim_revision_id,
        "predicate_id": source.predicate_id,
        "source_run_id": source.source_run_id,
        "assumption_id": validated.assumptions.assumption_id,
        "source_scenario_id": validated.scenario.scenario_id,
        "source_dataset_id": validated.replay_input.dataset_id,
        "source_normalized_sha256": digest(validated.replay_input.normalized_bytes),
        "replay_spec_id": validated.replay_input.spec.spec_id,
        "witness_ordinal": source.witness_ordinal,
    }


def _validated_recipe(raw: bytes) -> Row:
    row = _exact(
        parse(raw, limit=role_limit("recipe")),
        {"kind", "schema_version", "source", "operators", "execution_policy", "scope", "flags"},
        "Reduction recipe",
    )
    _same(
        [row["kind"], row["schema_version"]],
        ["reduction_recipe_v1", 1],
        "Unsupported reduction recipe",
    )
    source = _exact(
        row["source"], _SOURCE_HASHES | {"witness_ordinal"}, "Reduction source bindings"
    )
    for name in _SOURCE_HASHES:
        identity(source[name])
    operators = _exact(row["operators"], _OPERATORS, "Reduction operators")
    load_reduction_request(
        canonical(
            {
                "kind": "reduction_request_v1",
                "schema_version": 1,
                "witness_ordinal": source["witness_ordinal"],
                **operators,
            }
        )
    )
    _same(row["execution_policy"], dict(_POLICY), "Checkpoint or prefix reuse is not supported")
    _same(
        row["scope"], dict(SCOPE), "Reduction preparation cannot extend source authority or budget"
    )
    _same(
        row["flags"], dict(FLAGS), "Reduction recipe cannot assert execution or materialized state"
    )
    return row


@dataclass(frozen=True, slots=True)
class ReductionRecipe:
    recipe_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated_recipe(self.canonical_bytes)
            _require(
                identity(self.recipe_id) == digest(self.canonical_bytes),
                "Reduction recipe identity differs",
            )
        except (ValueError, TypeError, KeyError) as error:
            raise ReductionValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=role_limit("recipe"))


def load_reduction_recipe(raw: bytes) -> ReductionRecipe:
    try:
        _validated_recipe(raw)
        return ReductionRecipe(digest(raw), raw)
    except (ValueError, TypeError, KeyError) as error:
        raise ReductionValidationError(str(error)) from error


def build_reduction_recipe(request_raw: bytes, *, source: ReductionSource) -> ReductionRecipe:
    try:
        request = load_reduction_request(request_raw)
        _same(
            request["witness_ordinal"],
            source.witness_ordinal,
            "Reduction request selects another witness",
        )
        original = derive_replay_view(source.validation)
        validated = original.validated
        original_delay = cast(
            "int", cast("Row", validated.scenario.document["additional_delay"])["value"]
        )
        delay = cast("int", request["additional_delay_ns"])
        _require(delay <= original_delay, "Reduction cannot increase the selected witness delay")
        candidate = build_scenario_spec(
            canonical(
                {
                    "kind": "scenario_request_v1",
                    "schema_version": 1,
                    "scenario_kind": "COUNTERFACTUAL_STRESS",
                    "additional_delay": {"value": delay, "unit": "ns"},
                }
            ),
            assumptions=validated.assumptions,
        )
        validate_scenario_spec(
            candidate,
            validated.assumptions,
            protocol=validated.protocol,
            replay_input=validated.replay_input,
        )
        prepared = preflight_replay(validated.replay_input)
        captures = [event.capture_seq for event in prepared.events]
        focus, through = (
            cast("int", request["focus_from_capture_seq"]),
            cast("int", request["through_capture_seq"]),
        )
        _require(
            focus in captures and through in captures and captures[0] <= focus <= through,
            "Reduction endpoints must identify an ordered actual source window",
        )
        strategy = cast("Row", validated.protocol.document["replay_spec"])["strategy"]
        submit = cast("int", cast("Row", strategy)["submit_capture_seq"])
        anchor = cast(
            "int", cast("Row", validated.assumptions.document["transform"])["from_capture_seq"]
        )
        _require(
            through >= submit and through >= anchor,
            "Reduction prefix must retain the strategy submission and stress anchor",
        )
        document: Row = {
            "kind": "reduction_recipe_v1",
            "schema_version": 1,
            "source": _source_document(source),
            "operators": {name: request[name] for name in _OPERATORS},
            "execution_policy": dict(_POLICY),
            "scope": dict(SCOPE),
            "flags": dict(FLAGS),
        }
        return load_reduction_recipe(canonical(document))
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReductionValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class MaterializedReduction:
    source: ReductionSource
    recipe: ReductionRecipe
    canonical_bytes: bytes = field(init=False)
    replay_input: ReplayInput = field(init=False)
    prepared: PreparedReplay = field(init=False)

    def __post_init__(self) -> None:
        try:
            document = self.recipe.document
            operators = cast("Row", document["operators"])
            rebuilt = build_reduction_recipe(
                canonical(
                    {
                        "kind": "reduction_request_v1",
                        "schema_version": 1,
                        "witness_ordinal": cast("Row", document["source"])["witness_ordinal"],
                        **operators,
                    }
                ),
                source=self.source,
            )
            _require(
                rebuilt.recipe_id == self.recipe.recipe_id
                and rebuilt.canonical_bytes == self.recipe.canonical_bytes,
                "Reduction recipe does not reproduce from its actual witness",
            )
            original = derive_replay_view(self.source.validation)
            validated = original.validated
            scenario = build_scenario_spec(
                canonical(
                    {
                        "kind": "scenario_request_v1",
                        "schema_version": 1,
                        "scenario_kind": "COUNTERFACTUAL_STRESS",
                        "additional_delay": {
                            "value": operators["additional_delay_ns"],
                            "unit": "ns",
                        },
                    }
                ),
                assumptions=validated.assumptions,
            )
            candidate = derive_replay_view(
                validate_scenario_spec(
                    scenario,
                    validated.assumptions,
                    protocol=validated.protocol,
                    replay_input=validated.replay_input,
                )
            )
            source_events = preflight_replay(validated.replay_input).events
            captures = [event.capture_seq for event in source_events]
            focus_index = captures.index(cast("int", operators["focus_from_capture_seq"]))
            through_index = captures.index(cast("int", operators["through_capture_seq"]))
            lines = candidate.replay_input.normalized_bytes.splitlines(keepends=True)
            prefix, warmup = b"".join(lines[: through_index + 1]), b"".join(lines[:focus_index])
            retained: Row = {
                "normalized_sha256": digest(prefix),
                "warmup_normalized_sha256": digest(warmup),
                "event_count": through_index + 1,
                "warmup_event_count": focus_index,
                "origin_ref": source_events[0].source_ref,
                "focus_ref": source_events[focus_index].source_ref,
                "through_ref": source_events[through_index].source_ref,
            }
            bindings = cast("Row", document["source"])
            context: Row = {
                "kind": "reduction_prefix_context_v1",
                "schema_version": 1,
                "policy": "replay_from_original_origin_before_focus_v1",
                "recipe_id": self.recipe.recipe_id,
                "source_bundle_id": self.source.bundle_id,
                "source_report_id": self.source.report_id,
                "source_protocol_id": validated.protocol.protocol_id,
                "source_normalized_sha256": bindings["source_normalized_sha256"],
                "assumption_id": validated.assumptions.assumption_id,
                "candidate_scenario_id": scenario.scenario_id,
                "candidate_full_view_id": candidate.view_id,
                "replay_spec_id": validated.replay_input.spec.spec_id,
                "engine": validated.protocol.document["engine"],
                **retained,
            }
            context_id = digest(canonical(context))
            _require(
                context_id
                not in (validated.replay_input.dataset_id, candidate.view_id, original.view_id),
                "Reduction input identity cannot alias the original dataset or scenario view",
            )
            replay_input = ReplayInput(context_id, prefix, validated.replay_input.spec)
            prepared = preflight_replay(replay_input)
            _require(
                [event.source_ref for event in prepared.events]
                == [event.source_ref for event in source_events[: through_index + 1]],
                "Reduction prefix lost original source references",
            )
            descriptor: Row = {
                "kind": "materialized_reduction_input_v1",
                "schema_version": 1,
                "recipe_id": self.recipe.recipe_id,
                "prefix_context_id": context_id,
                "prefix_context": context,
                "candidate": {
                    "scenario_id": scenario.scenario_id,
                    "scenario": scenario.document,
                    "full_view_id": candidate.view_id,
                    "full_normalized_sha256": digest(candidate.replay_input.normalized_bytes),
                    "full_event_count": len(source_events),
                    "additional_delay_ns": operators["additional_delay_ns"],
                },
                "retained": retained,
                "changes": {
                    "strictly_shorter_input": through_index + 1 < len(source_events),
                    "parameter_contracted": cast("int", operators["additional_delay_ns"])
                    < cast(
                        "int", cast("Row", validated.scenario.document["additional_delay"])["value"]
                    ),
                    "focus_window_narrowed": focus_index > 0,
                },
                "scope": dict(SCOPE),
                "flags": dict(FLAGS),
            }
            encoded = canonical(descriptor)
            parse(encoded, limit=role_limit("materialization"))
            object.__setattr__(self, "canonical_bytes", encoded)
            object.__setattr__(self, "replay_input", replay_input)
            object.__setattr__(self, "prepared", prepared)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ReductionValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=role_limit("materialization"))


def materialize_reduction(
    recipe: ReductionRecipe, *, source: ReductionSource
) -> MaterializedReduction:
    return MaterializedReduction(source, recipe)
