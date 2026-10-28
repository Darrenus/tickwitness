"""Bounded technical-alpha declarations, without external or historical authority.

Loading checks declared content consistency. Only the application can freshly
reaudit cases, rerun the validator and exercise actual publication boundaries.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.assumptions import load_scenario_spec
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)

MAX_ALPHA_SUITE_BYTES = 65_536
MAX_ALPHA_SCORECARD_BYTES = 1024 * 1024
PROFILE = "development_technical_alpha_v1"
PUBLICATION_PROBE = "alpha_kit_precommit_sync_postcommit_parent_sync_v1"
INVALID_POLICY = "frozen_delay_upper_bound_plus_one_v1"
SCOPE: dict[str, object] = {
    "native_replayed": False,
    "new_research_attempts": False,
    "confirmation_accessed": False,
    "source_claim_authority_extended": False,
    "global_history_authenticated": False,
    "external_identity_authenticated": False,
    "power_loss_durability_certified": False,
    "s10_recovery_qualified": False,
}
GATES: dict[str, object] = {
    "technical_checks": "PASS",
    "external_attempts": 0,
    "external_successes": 0,
    "external_attempt_gate": "PENDING",
    "release_decision": "TECHNICAL_ALPHA_ONLY_EXTERNAL_PENDING",
}
_SUITE_FIELDS = {"kind", "schema_version", "profile", "cases", "invalid_perturbation", "publication_probe", "external_gate"}
_SCORECARD_FIELDS = {"kind", "schema_version", "profile", "kit_id", "suite_id", "suite", "cases", "invalid_perturbation", "publication_probe", "gates", "scope"}
_CASE_FIELDS = {"bundle_id", "report_id", "finding_protocol_id", "source_protocol_id", "predicate_id", "outcome", "planned_predicate_truth", "eligible_ordinals", "audited_ordinals", "true_ordinals", "false_ordinals", "unknown_ordinals", "unevaluated_ordinals", "witness_ordinals", "coverage_complete_for_plan", "outer_status", "outer_stop_reason", "inner_status", "inner_stop_reason"}
type Row = dict[str, object]


class AlphaValidationError(EvidenceValidationError):
    """An alpha suite or scorecard violates its exact technical-only contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AlphaValidationError(message)


def _exact(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _same(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _integer(value: object, low: int, high: int, label: str) -> int:
    _require(type(value) is int and low <= value <= high, label + " is outside its integer bound")
    return cast("int", value)


def _text(value: object, label: str) -> str:
    _require(isinstance(value, str) and 0 < len(value) <= 128, label + " must be bounded text")
    text = cast("str", value)
    _require(not any(ord(char) < 32 or ord(char) == 127 for char in text), label + " contains controls")
    return text


def _suite_document(ce_bundle: str, ce_report: str, clean_bundle: str, clean_report: str) -> Row:
    for value in (ce_bundle, ce_report, clean_bundle, clean_report):
        identity(value)
    _require(ce_bundle != clean_bundle and ce_report != clean_report, "Alpha cases require distinct frozen findings")
    return {
        "kind": "alpha_reproduction_suite_v1", "schema_version": 1, "profile": PROFILE,
        "cases": {"counterexample": {"bundle_id": ce_bundle, "report_id": ce_report}, "clean_control": {"bundle_id": clean_bundle, "report_id": clean_report}},
        "invalid_perturbation": {"source_case": "counterexample", "policy": INVALID_POLICY},
        "publication_probe": PUBLICATION_PROBE,
        "external_gate": "human_confirmed_external_attempt_required_v1",
    }


def _validated_suite(raw: bytes) -> Row:
    document = _exact(parse(raw, limit=MAX_ALPHA_SUITE_BYTES), _SUITE_FIELDS, "Alpha suite")
    cases = _exact(document["cases"], {"counterexample", "clean_control"}, "Alpha suite cases")
    ce = _exact(cases["counterexample"], {"bundle_id", "report_id"}, "Counterexample pin")
    clean = _exact(cases["clean_control"], {"bundle_id", "report_id"}, "Clean-control pin")
    expected = _suite_document(identity(ce["bundle_id"]), identity(ce["report_id"]), identity(clean["bundle_id"]), identity(clean["report_id"]))
    _require(canonical(expected) == raw, "Alpha suite policies, pins or encoding differ")
    return expected


@dataclass(frozen=True, slots=True)
class AlphaSuite:
    suite_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated_suite(self.canonical_bytes)
            _require(identity(self.suite_id) == digest(self.canonical_bytes), "Alpha suite identity differs")
        except (ValueError, KeyError, TypeError) as error:
            raise AlphaValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_ALPHA_SUITE_BYTES)


def build_alpha_suite(*, counterexample_bundle_id: str, counterexample_report_id: str, clean_bundle_id: str, clean_report_id: str) -> AlphaSuite:
    try:
        document = _suite_document(counterexample_bundle_id, counterexample_report_id, clean_bundle_id, clean_report_id)
        return load_alpha_suite(canonical(document))
    except (ValueError, KeyError, TypeError) as error:
        raise AlphaValidationError(str(error)) from error


def load_alpha_suite(raw: bytes) -> AlphaSuite:
    try:
        _validated_suite(raw)
        return AlphaSuite(digest(raw), raw)
    except (ValueError, KeyError, TypeError) as error:
        raise AlphaValidationError(str(error)) from error


def _ordinals(value: object, label: str) -> list[int]:
    _require(type(value) is list and len(value) <= 100, label + " must be a bounded list")
    values = [_integer(item, 1, 1024, label) for item in cast("list[object]", value)]
    _require(values == sorted(set(values)), label + " must be sorted and unique")
    return values


def _case(value: object, *, clean: bool, pin: Row) -> Row:
    row = _exact(value, _CASE_FIELDS, "Alpha case")
    for field in ("bundle_id", "report_id", "finding_protocol_id", "source_protocol_id", "predicate_id"):
        identity(row[field])
    _same([row["bundle_id"], row["report_id"]], [pin["bundle_id"], pin["report_id"]], "Alpha case differs from its suite pins")
    inventories = {name: _ordinals(row[name + "_ordinals"], name) for name in ("eligible", "audited", "true", "false", "unknown", "unevaluated", "witness")}
    eligible = set(inventories["eligible"])
    _require(bool(eligible), "Alpha case must have eligible candidates")
    for items in inventories.values():
        _require(set(items) <= eligible, "Alpha case inventory exceeds its frozen candidate set")
    true, false = set(inventories["true"]), set(inventories["false"])
    _require(not true & false and true | false <= set(inventories["audited"]), "Alpha case truth lacks completed audited witnesses")
    _same(inventories["unevaluated"], sorted(eligible - (true | false)), "Alpha unevaluated coverage differs")
    _require(set(inventories["unknown"]) <= set(inventories["unevaluated"]), "Alpha unknown coverage differs")
    _same(row["coverage_complete_for_plan"], not inventories["unevaluated"], "Alpha complete-coverage claim differs")
    for field in ("outer_status", "outer_stop_reason", "inner_status", "inner_stop_reason"):
        _text(row[field], field)
    _same(row["outcome"], "NO_COUNTEREXAMPLE_FOUND" if clean else "COUNTEREXAMPLE_FOUND", "Alpha case finding differs from its role")
    _same(row["planned_predicate_truth"], clean, "Alpha case predicate truth differs from its role")
    if clean:
        _same([inventories[name] for name in ("audited", "true", "witness")], [inventories["eligible"]] * 3, "Clean control is not the complete all-true set")
        _require(not any(inventories[name] for name in ("false", "unknown", "unevaluated")), "Clean control contains false or unknown candidates")
        _same([row[name] for name in ("outer_status", "outer_stop_reason", "inner_status", "inner_stop_reason")], ["completed", "completed", "completed", "planned_candidates_exhausted"], "Clean control did not complete cleanly")
    else:
        _require(bool(false), "Counterexample case lacks a false witness")
        _same(inventories["witness"], inventories["false"], "Counterexample witness inventory differs")
    return row


def _invalid(value: object, *, source_bundle_id: object) -> None:
    row = _exact(value, {"kind", "schema_version", "source_case", "source_bundle_id", "assumption_id", "scenario_id", "policy", "validator", "frozen_maximum_ns", "challenge_delay_ns", "outcome", "reason_code"}, "Invalid perturbation check")
    assumption_id, scenario_id = identity(row["assumption_id"]), identity(row["scenario_id"])
    maximum = _integer(row["frozen_maximum_ns"], 0, 59_999_999_999, "Frozen delay maximum")
    delay = _integer(row["challenge_delay_ns"], maximum + 1, maximum + 1, "Invalid challenge delay")
    challenge = load_scenario_spec(canonical({"kind": "scenario_spec_v1", "schema_version": 1, "scenario_kind": "COUNTERFACTUAL_STRESS", "additional_delay": {"value": delay, "unit": "ns"}, "assumption_id": assumption_id}))
    expected = {"kind": "alpha_invalid_perturbation_check_v1", "schema_version": 1, "source_case": "counterexample", "source_bundle_id": source_bundle_id, "assumption_id": assumption_id, "scenario_id": challenge.scenario_id, "policy": INVALID_POLICY, "validator": "validate_scenario_spec_v1", "frozen_maximum_ns": maximum, "challenge_delay_ns": delay, "outcome": "REJECTED", "reason_code": "scenario_delay_outside_frozen_assumption_range"}
    _require(scenario_id == challenge.scenario_id, "Invalid challenge scenario identity differs")
    _same(row, expected, "Invalid perturbation check policies or bindings differ")


def _probe(value: object, *, kit_id: str) -> None:
    expected: Row = {
        "kind": "alpha_kit_publication_probe_v1", "schema_version": 1, "profile": PUBLICATION_PROBE, "kit_id": kit_id,
        "normal_publication": {"published_kit_id": kit_id, "readback_kit_id": kit_id, "success_returned": True},
        "existing_destination": {"exception_type": "AlphaKitDestinationExistsError", "success_returned": False, "original_tree_unchanged": True},
        "precommit_sync_failure": {"fault_injected": True, "exception_type": "AlphaKitError", "success_returned": False, "target_exists": False, "staging_entries_remaining": 0},
        "postcommit_parent_sync_failure": {"fault_injected": True, "exception_type": "AlphaKitDurabilityError", "success_returned": False, "target_exists": True, "retained_kit_id": kit_id},
    }
    _same(value, expected, "Publication boundary check does not establish the fixed controlled-fault behavior")


def _validated_scorecard(raw: bytes) -> Row:
    row = _exact(parse(raw, limit=MAX_ALPHA_SCORECARD_BYTES), _SCORECARD_FIELDS, "Alpha scorecard")
    suite = load_alpha_suite(canonical(cast("Row", row["suite"])))
    kit_id = identity(row["kit_id"])
    _require(identity(row["suite_id"]) == suite.suite_id, "Scorecard suite identity differs")
    _same([row["kind"], row["schema_version"], row["profile"]], ["alpha_scorecard_v1", 1, PROFILE], "Unsupported alpha scorecard")
    cases = _exact(row["cases"], {"counterexample", "clean_control"}, "Scorecard cases")
    pins = cast("dict[str, Row]", suite.document["cases"])
    ce = _case(cases["counterexample"], clean=False, pin=pins["counterexample"])
    _case(cases["clean_control"], clean=True, pin=pins["clean_control"])
    _invalid(row["invalid_perturbation"], source_bundle_id=ce["bundle_id"])
    _probe(row["publication_probe"], kit_id=kit_id)
    _same(row["gates"], GATES, "External attempts and release gates cannot be overridden")
    _same(row["scope"], SCOPE, "Alpha scorecard authority cannot be extended")
    return row


@dataclass(frozen=True, slots=True)
class AlphaScorecard:
    scorecard_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated_scorecard(self.canonical_bytes)
            _require(identity(self.scorecard_id) == digest(self.canonical_bytes), "Alpha scorecard identity differs")
        except (ValueError, KeyError, TypeError) as error:
            raise AlphaValidationError(str(error)) from error

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_ALPHA_SCORECARD_BYTES)


def build_alpha_scorecard(document: Row) -> AlphaScorecard:
    return load_alpha_scorecard(canonical(document))


def load_alpha_scorecard(raw: bytes) -> AlphaScorecard:
    try:
        _validated_scorecard(raw)
        return AlphaScorecard(digest(raw), raw)
    except (ValueError, KeyError, TypeError) as error:
        raise AlphaValidationError(str(error)) from error
