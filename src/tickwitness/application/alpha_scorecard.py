"""Rebuild technical-alpha checks from real sealed content and fresh IO probes.

No saved acceptance flag, external-user declaration or failed publication grants
success. This use case never executes a strategy or consumes a research slot.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.search_evidence import SearchEvidencePackage, verify_search_package
from tickwitness.domain.assumptions import (
    AssumptionValidationError,
    build_scenario_spec,
    load_assumption_spec,
    load_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.evidence.alpha_scorecard import (
    GATES,
    INVALID_POLICY,
    MAX_ALPHA_SCORECARD_BYTES,
    PROFILE,
    SCOPE,
    AlphaScorecard,
    AlphaSuite,
    AlphaValidationError,
    build_alpha_scorecard,
    build_alpha_suite,
    load_alpha_scorecard,
    load_alpha_suite,
)
from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import load_search_finding_protocol

MAX_ALPHA_RECEIPT_BYTES = MAX_ALPHA_SCORECARD_BYTES + 4096
_VERIFICATION: dict[str, object] = {
    "case_contents_reaudited": True,
    "invalid_validator_reexecuted": True,
    "publication_boundaries_reexecuted": True,
    "postcommit_case_contents_reaudited": True,
    "saved_flags_trusted": False,
}
type Row = dict[str, object]


class AlphaKit(Protocol):
    @property
    def kit_id(self) -> str: ...
    @property
    def manifest_bytes(self) -> bytes: ...
    @property
    def suite_bytes(self) -> bytes: ...
    @property
    def files(self) -> dict[str, bytes]: ...
    def case(self, name: str) -> SearchEvidencePackage: ...


@dataclass(frozen=True, slots=True)
class BoundaryProbeResult:
    document: Row
    postcommit_kit: AlphaKit


class PublicationBoundaryProbe(Protocol):
    """Run fixed per-call faults in new scratch and return retained actual content."""

    def run(self, kit: AlphaKit) -> BoundaryProbeResult: ...


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AlphaValidationError(message)


def _same(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _kit(kit: AlphaKit, expected_kit_id: str) -> AlphaSuite:
    try:
        expected_id = identity(expected_kit_id)
        _require(identity(kit.kit_id) == expected_id, "Alpha kit differs from its expected pinned identity")
        manifest = parse(kit.manifest_bytes, limit=256 * 1024)
        _require(digest(kit.manifest_bytes) == expected_id, "Alpha kit manifest identity differs")
        _require(manifest.keys() == {"kind", "schema_version", "scope", "producer", "suite", "wheel_path", "files"}, "Alpha kit manifest fields differ")
        _same([manifest["kind"], manifest["schema_version"], manifest["scope"]], ["alpha_reproduction_kit_v1", 1, PROFILE], "Alpha kit profile differs")
        producer = manifest["producer"]
        _require(isinstance(producer, dict) and producer.keys() == {"version", "source_revision"}, "Alpha kit producer declaration fields differ")
        producer = cast("Row", producer)
        version, revision = producer["version"], producer["source_revision"]
        _require(isinstance(version, str) and 0 < len(version) <= 64 and version == version.strip() and not any(ord(char) < 32 or ord(char) == 127 for char in version), "Alpha kit declared version differs")
        _require(isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "Alpha kit source revision differs")
        suite = load_alpha_suite(kit.suite_bytes)
        _require(canonical(cast("Row", manifest["suite"])) == suite.canonical_bytes, "Alpha kit embedded suite differs")
        files, refs = kit.files, manifest["files"]
        _require(type(files) is dict and isinstance(refs, dict) and files.keys() == refs.keys(), "Alpha kit file closure differs")
        references = cast("dict[str, object]", refs)
        _require(1 <= len(files) <= 511, "Alpha kit file inventory exceeds its profile")
        total = len(kit.manifest_bytes)
        for name, raw in files.items():
            _require(type(raw) is bytes and bool(raw), "Alpha kit file must be nonempty immutable bytes")
            total += len(raw)
            _same(references[name], {"sha256": digest(raw), "size_bytes": len(raw)}, "Alpha kit file reference differs: " + name)
        _require(total <= 32 * 1024 * 1024, "Alpha kit exceeds its aggregate profile")
        return suite
    except AlphaValidationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise AlphaValidationError("Invalid alpha kit content: " + str(error)) from error


def _summary(receipt: Row, *, clean: bool) -> Row:
    report = cast("Row", receipt["report"])
    coverage, execution = cast("Row", report["coverage"]), cast("Row", report["execution"])
    witnesses = cast("list[Row]", report["witnesses"])
    if clean:
        _same([report["outcome"], report["planned_predicate_truth"], coverage["coverage_complete_for_plan"]], ["NO_COUNTEREXAMPLE_FOUND", True, True], "Clean control requires the full all-true finding")
        eligible = cast("list[int]", coverage["eligible_ordinals"])
        _require(bool(eligible), "Clean control cannot be empty")
        _same([coverage["audited_ordinals"], coverage["true_ordinals"], [row["ordinal"] for row in witnesses]], [eligible] * 3, "Clean control is not the complete audited true set")
        _same([coverage["false_ordinals"], coverage["unknown_ordinals"], coverage["unevaluated_ordinals"]], [[], [], []], "Clean control contains false or unknown candidates")
        _same([execution[name] for name in ("outer_status", "outer_stop_reason", "inner_status", "inner_stop_reason")], ["completed", "completed", "completed", "planned_candidates_exhausted"], "Clean control stopped before a clean completion")
    else:
        _same([report["outcome"], report["planned_predicate_truth"]], ["COUNTEREXAMPLE_FOUND", False], "Counterexample case lacks its frozen false finding")
        _require(bool(witnesses), "Counterexample case has no actual witness")
        _require(all(row["truth"] is False and row["status"] == "COMPLETED" and row["raw_result_audited"] is True for row in witnesses), "Counterexample witnesses are not completed audited false results")
    summary: Row = {key: report[key] for key in ("finding_protocol_id", "source_protocol_id", "predicate_id", "outcome", "planned_predicate_truth")}
    summary.update(bundle_id=receipt["bundle_id"], report_id=receipt["report_id"], witness_ordinals=[row["ordinal"] for row in witnesses])
    for name in ("eligible_ordinals", "audited_ordinals", "true_ordinals", "false_ordinals", "unknown_ordinals", "unevaluated_ordinals", "coverage_complete_for_plan"):
        summary[name] = coverage[name]
    for name in ("outer_status", "outer_stop_reason", "inner_status", "inner_stop_reason"):
        summary[name] = execution[name]
    return summary


def _cases(counterexample: SearchEvidencePackage, clean_control: SearchEvidencePackage) -> tuple[AlphaSuite, Row]:
    try:
        ce, clean = verify_search_package(counterexample), verify_search_package(clean_control)
        summaries: Row = {"counterexample": _summary(ce, clean=False), "clean_control": _summary(clean, clean=True)}
        suite = build_alpha_suite(counterexample_bundle_id=cast("str", ce["bundle_id"]), counterexample_report_id=cast("str", ce["report_id"]), clean_bundle_id=cast("str", clean["bundle_id"]), clean_report_id=cast("str", clean["report_id"]))
        return suite, summaries
    except AlphaValidationError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise AlphaValidationError("Cannot reaudit alpha cases: " + str(error)) from error


def _invalid(counterexample: SearchEvidencePackage) -> Row:
    try:
        artifacts = counterexample.artifacts
        authority = load_search_finding_protocol(artifacts["finding_protocol"])
        plan = authority.plan.document
        protocol = load_executable_protocol(canonical(cast("Row", plan["protocol"])))
        assumptions = load_assumption_spec(canonical(cast("Row", plan["assumptions"])))
        source_id = cast("str", cast("Row", protocol.document["datasets"])["development"])
        replay_input = ReplayInput(source_id, artifacts["normalized"], build_replay_spec(canonical(cast("Row", protocol.document["replay_spec"]))))
        eligible = next(row for row in cast("list[Row]", plan["journal"]) if row["status"] == "ELIGIBLE")
        anchor = build_scenario_spec(canonical({"kind": "scenario_request_v1", "schema_version": 1, "scenario_kind": "COUNTERFACTUAL_STRESS", "additional_delay": {"value": eligible["delay_ns"], "unit": "ns"}}), assumptions=assumptions)
        validate_scenario_spec(anchor, assumptions, protocol=protocol, replay_input=replay_input)
        maximum = cast("int", cast("Row", assumptions.document["additional_delay"])["maximum"])
        _require(0 <= maximum < 60_000_000_000, "Frozen delay upper+1 is outside the alpha challenge profile")
        scenario = load_scenario_spec(canonical({"kind": "scenario_spec_v1", "schema_version": 1, "scenario_kind": "COUNTERFACTUAL_STRESS", "additional_delay": {"value": maximum + 1, "unit": "ns"}, "assumption_id": assumptions.assumption_id}))
        try:
            validate_scenario_spec(scenario, assumptions, protocol=protocol, replay_input=replay_input)
        except AssumptionValidationError as error:
            _require(str(error) == "Scenario delay is outside its frozen assumption range", "Invalid perturbation failed for a different reason")
        else:
            raise AlphaValidationError("Invalid perturbation was accepted by the actual validator")
        return {"kind": "alpha_invalid_perturbation_check_v1", "schema_version": 1, "source_case": "counterexample", "source_bundle_id": counterexample.bundle_id, "assumption_id": assumptions.assumption_id, "scenario_id": scenario.scenario_id, "policy": INVALID_POLICY, "validator": "validate_scenario_spec_v1", "frozen_maximum_ns": maximum, "challenge_delay_ns": maximum + 1, "outcome": "REJECTED", "reason_code": "scenario_delay_outside_frozen_assumption_range"}
    except AlphaValidationError:
        raise
    except (ValueError, KeyError, TypeError, StopIteration, AttributeError) as error:
        raise AlphaValidationError("Cannot recompute invalid perturbation: " + str(error)) from error


def prepare_alpha_suite(counterexample: SearchEvidencePackage, clean_control: SearchEvidencePackage) -> AlphaSuite:
    """Preflight actual cases and negative validator challenge before publication."""
    suite, _summaries = _cases(counterexample, clean_control)
    _invalid(counterexample)
    return suite


def _receipt(scorecard: AlphaScorecard) -> Row:
    document = scorecard.document
    return {
        "kind": "alpha_scorecard_receipt_v1", "schema_version": 1,
        "kit_id": document["kit_id"], "suite_id": document["suite_id"],
        "scorecard_id": scorecard.scorecard_id, "scorecard": document,
        "finalization_status": "LOCAL_RECOMPUTED_TECHNICAL_ONLY", "verification": dict(_VERIFICATION),
    }


def evaluate_alpha_kit(kit: AlphaKit, *, expected_kit_id: str, publication_probe_factory: Callable[[], PublicationBoundaryProbe]) -> Row:
    """Run actual content, validator and controlled publication checks afresh."""
    declared = _kit(kit, expected_kit_id)
    counterexample, clean_control = kit.case("counterexample"), kit.case("clean_control")
    suite, summaries = _cases(counterexample, clean_control)
    _require(suite.canonical_bytes == declared.canonical_bytes, "Actual alpha cases differ from the pinned suite")
    invalid = _invalid(counterexample)
    result = publication_probe_factory().run(kit)
    _require(type(result) is BoundaryProbeResult, "Publication probe returned an invalid result type")
    retained = result.postcommit_kit
    retained_suite = _kit(retained, expected_kit_id)
    _require(retained.manifest_bytes == kit.manifest_bytes and retained.files == kit.files and retained_suite.canonical_bytes == declared.canonical_bytes, "Postcommit retained alpha kit differs")
    retained_pins, retained_summaries = _cases(retained.case("counterexample"), retained.case("clean_control"))
    _require(retained_pins.canonical_bytes == suite.canonical_bytes, "Postcommit retained case pins differ")
    _same(retained_summaries, summaries, "Postcommit retained semantic cases differ")
    scorecard = build_alpha_scorecard({"kind": "alpha_scorecard_v1", "schema_version": 1, "profile": PROFILE, "kit_id": expected_kit_id, "suite_id": suite.suite_id, "suite": suite.document, "cases": summaries, "invalid_perturbation": invalid, "publication_probe": result.document, "gates": dict(GATES), "scope": dict(SCOPE)})
    return _receipt(scorecard)


def verify_alpha_scorecard(kit: AlphaKit, saved: bytes, *, expected_kit_id: str, publication_probe_factory: Callable[[], PublicationBoundaryProbe]) -> Row:
    """Load a complete saved receipt, rerun every check, then compare exact bytes."""
    try:
        document = parse(saved, limit=MAX_ALPHA_RECEIPT_BYTES)
        _require(document.keys() == {"kind", "schema_version", "kit_id", "suite_id", "scorecard_id", "scorecard", "finalization_status", "verification"}, "Saved alpha receipt fields differ")
        scorecard = load_alpha_scorecard(canonical(cast("Row", document["scorecard"])))
        _require(canonical(_receipt(scorecard)) == saved, "Saved alpha receipt differs from its exact scorecard bindings")
    except AlphaValidationError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise AlphaValidationError("Invalid saved alpha receipt: " + str(error)) from error
    fresh = evaluate_alpha_kit(kit, expected_kit_id=expected_kit_id, publication_probe_factory=publication_probe_factory)
    _require(canonical(fresh) == saved, "Saved alpha scorecard does not reproduce from fresh checks")
    return fresh
