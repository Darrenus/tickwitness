"""Prepare and independently rebuild legal full-origin reduction inputs.

Source selection consumes actual portable search evidence. No original store,
ledger, native runtime, running-state restoration or reduction verdict is used.
"""

from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_evidence import SearchEvidencePackage, verify_search_package
from tickwitness.domain.assumptions import build_scenario_spec, load_assumption_spec, validate_scenario_spec
from tickwitness.domain.evidence.run_records import canonical, digest, identity
from tickwitness.domain.reduction.contracts import (
    FLAGS,
    MaterializedReduction,
    ReductionRecipe,
    ReductionSource,
    ReductionValidationError,
    build_reduction_manifest,
    build_reduction_recipe,
    load_reduction_recipe,
    load_reduction_request,
    materialize_reduction,
)
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import load_search_finding_protocol

type Row = dict[str, object]


class ReductionPackage(Protocol):
    @property
    def preparation_id(self) -> str: ...
    @property
    def manifest_bytes(self) -> bytes: ...
    @property
    def artifacts(self) -> dict[str, bytes]: ...


@dataclass(frozen=True, slots=True)
class _SourcePackage:
    bundle_id: str
    manifest_bytes: bytes
    _artifacts: tuple[tuple[str, bytes], ...]

    @property
    def artifacts(self) -> dict[str, bytes]:
        return dict(self._artifacts)


@dataclass(frozen=True, slots=True)
class PreparedReduction:
    recipe: ReductionRecipe
    materialization: MaterializedReduction

    def __post_init__(self) -> None:
        if self.recipe != self.materialization.recipe:
            raise ReductionValidationError("Prepared recipe differs from its materialized input")
        build_reduction_manifest(self.artifacts)

    @property
    def artifacts(self) -> dict[str, bytes]:
        return {"recipe": self.recipe.canonical_bytes, "materialization": self.materialization.canonical_bytes, "normalized": self.materialization.replay_input.normalized_bytes}

    @property
    def preparation_id(self) -> str:
        return digest(build_reduction_manifest(self.artifacts))


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Reduction input preparation permits development evidence only")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReductionValidationError(message)


def _source_context(package: SearchEvidencePackage, request: Row, bundle_id: str, report_id: str) -> ReductionSource:
    snapshot = _SourcePackage(package.bundle_id, package.manifest_bytes, tuple(sorted(package.artifacts.items())))
    receipt = verify_search_package(snapshot, expected_bundle_id=bundle_id)
    _require(receipt["report_id"] == report_id, "Source report differs from the expected pinned identity")
    report = cast("Row", receipt["report"])
    _require(report["outcome"] == "COUNTEREXAMPLE_FOUND" and report["planned_predicate_truth"] is False, "Reduction requires an actual scoped counterexample finding")
    ordinal = cast("int", request["witness_ordinal"])
    selected = [row for row in cast("list[Row]", report["witnesses"]) if row["ordinal"] == ordinal]
    _require(len(selected) == 1, "Reduction ordinal must select an actual false witness")
    witness = selected[0]
    _require(witness["status"] == "COMPLETED" and witness["raw_result_audited"] is True and witness["truth"] is False, "Selected witness must be completed, audited and false")
    artifacts = snapshot.artifacts
    authority = load_search_finding_protocol(artifacts["finding_protocol"])
    plan = authority.plan.document
    protocol = load_executable_protocol(canonical(cast("Row", plan["protocol"])))
    assumptions = load_assumption_spec(canonical(cast("Row", plan["assumptions"])))
    proposal = next(row for row in cast("list[Row]", plan["journal"]) if row["ordinal"] == ordinal)
    _require(proposal["status"] == "ELIGIBLE", "Selected witness has no eligible original proposal")
    scenario = build_scenario_spec(canonical({"kind": "scenario_request_v1", "schema_version": 1, "scenario_kind": "COUNTERFACTUAL_STRESS", "additional_delay": {"value": proposal["delay_ns"], "unit": "ns"}}), assumptions=assumptions)
    _require(scenario.scenario_id == witness["scenario_id"], "Actual witness scenario identity differs")
    dataset_id = cast("str", cast("Row", protocol.document["datasets"])["development"])
    replay_input = ReplayInput(dataset_id, artifacts["normalized"], build_replay_spec(canonical(cast("Row", protocol.document["replay_spec"]))))
    validation = validate_scenario_spec(scenario, assumptions, protocol=protocol, replay_input=replay_input)
    return ReductionSource(bundle_id=bundle_id, report_id=report_id, finding_protocol_id=authority.protocol_id, predicate_id=cast("str", report["predicate_id"]), source_run_id=identity(witness["run_id"]), witness_ordinal=ordinal, validation=validation)


def prepare_reduction_input(
    package: SearchEvidencePackage,
    request_raw: bytes,
    *,
    expected_bundle_id: str,
    expected_report_id: str,
    split: str = "development",
) -> PreparedReduction:
    """Validate the complete original evidence before materializing any prefix."""
    _development(split)
    request = load_reduction_request(request_raw)
    try:
        bundle_id, report_id = identity(expected_bundle_id), identity(expected_report_id)
        source = _source_context(package, request, bundle_id, report_id)
        recipe = build_reduction_recipe(canonical(request), source=source)
        return PreparedReduction(recipe, materialize_reduction(recipe, source=source))
    except ReductionValidationError:
        raise
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as error:
        raise ReductionValidationError("Cannot prepare reduction input: " + str(error)) from error


def _receipt(prepared: PreparedReduction) -> Row:
    recipe, descriptor = prepared.recipe.document, prepared.materialization.document
    source, operators = cast("Row", recipe["source"]), cast("Row", recipe["operators"])
    candidate, retained = cast("Row", descriptor["candidate"]), cast("Row", descriptor["retained"])
    return {
        "kind": "reduction_input_receipt_v1", "schema_version": 1,
        "scope": "development_input_preparation_only_v1", "status": "RECOMPUTED_PREPARATION_ONLY",
        "preparation_id": prepared.preparation_id, "source_bundle_id": source["bundle_id"],
        "source_report_id": source["report_id"], "source_protocol_id": source["source_protocol_id"],
        "recipe_id": prepared.recipe.recipe_id, "prefix_context_id": descriptor["prefix_context_id"],
        "candidate_scenario_id": candidate["scenario_id"], "source_event_count": candidate["full_event_count"],
        "event_count": retained["event_count"], "warmup_event_count": retained["warmup_event_count"],
        **operators, **cast("Row", descriptor["changes"]), **dict(FLAGS),
    }


def verify_reduction_input(
    package: ReductionPackage,
    *,
    source: SearchEvidencePackage,
    expected_preparation_id: str,
    split: str = "development",
) -> Row:
    """Rebuild recipe, context and actual normalized bytes, ignoring saved claims."""
    _development(split)
    try:
        expected = identity(expected_preparation_id)
        artifacts = package.artifacts
        manifest = build_reduction_manifest(artifacts)
        _require(type(package.manifest_bytes) is bytes and package.manifest_bytes == manifest, "Reduction manifest differs from its exact content closure")
        _require(identity(package.preparation_id) == expected == digest(manifest), "Reduction preparation differs from the expected pinned identity")
        recipe = load_reduction_recipe(artifacts["recipe"])
        document = recipe.document
        bindings = cast("Row", document["source"])
        request = canonical({"kind": "reduction_request_v1", "schema_version": 1, "witness_ordinal": bindings["witness_ordinal"], **cast("Row", document["operators"])})
        rebuilt = prepare_reduction_input(source, request, expected_bundle_id=cast("str", bindings["bundle_id"]), expected_report_id=cast("str", bindings["report_id"]))
        _require(rebuilt.artifacts == artifacts, "Saved reduction recipe, prefix context or normalized bytes do not reproduce")
        _require(rebuilt.preparation_id == expected, "Rebuilt reduction preparation identity differs")
        return _receipt(rebuilt)
    except ReductionValidationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReductionValidationError("Invalid reduction preparation: " + str(error)) from error
