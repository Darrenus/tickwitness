"""Strict declared scorecard consistency never grants external acceptance."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from tickwitness.domain.evidence.alpha_scorecard import (
    GATES,
    INVALID_POLICY,
    PROFILE,
    PUBLICATION_PROBE,
    SCOPE,
    AlphaValidationError,
    build_alpha_scorecard,
    build_alpha_suite,
    load_alpha_scorecard,
    load_alpha_suite,
)
from tickwitness.domain.evidence.run_records import canonical, digest


def probe_document(kit_id):
    """A declared unit fixture; application tests require actual IO execution."""
    return {
        "kind": "alpha_kit_publication_probe_v1",
        "schema_version": 1,
        "profile": PUBLICATION_PROBE,
        "kit_id": kit_id,
        "normal_publication": {
            "published_kit_id": kit_id,
            "readback_kit_id": kit_id,
            "success_returned": True,
        },
        "existing_destination": {
            "exception_type": "AlphaKitDestinationExistsError",
            "success_returned": False,
            "original_tree_unchanged": True,
        },
        "precommit_sync_failure": {
            "fault_injected": True,
            "exception_type": "AlphaKitError",
            "success_returned": False,
            "target_exists": False,
            "staging_entries_remaining": 0,
        },
        "postcommit_parent_sync_failure": {
            "fault_injected": True,
            "exception_type": "AlphaKitDurabilityError",
            "success_returned": False,
            "target_exists": True,
            "retained_kit_id": kit_id,
        },
    }


def declared_document():
    suite = build_alpha_suite(
        counterexample_bundle_id="a" * 64,
        counterexample_report_id="b" * 64,
        clean_bundle_id="c" * 64,
        clean_report_id="d" * 64,
    )
    cases = {}
    for role, clean in (("counterexample", False), ("clean_control", True)):
        cases[role] = {
            **suite.document["cases"][role],
            "finding_protocol_id": "1" * 64,
            "source_protocol_id": "2" * 64,
            "predicate_id": "3" * 64,
            "outcome": "NO_COUNTEREXAMPLE_FOUND" if clean else "COUNTEREXAMPLE_FOUND",
            "planned_predicate_truth": clean,
            "eligible_ordinals": [1, 3],
            "audited_ordinals": [1, 3],
            "true_ordinals": [1, 3] if clean else [1],
            "false_ordinals": [] if clean else [3],
            "unknown_ordinals": [],
            "unevaluated_ordinals": [],
            "witness_ordinals": [1, 3] if clean else [3],
            "coverage_complete_for_plan": True,
            "outer_status": "completed",
            "outer_stop_reason": "completed",
            "inner_status": "completed",
            "inner_stop_reason": "planned_candidates_exhausted",
        }
    assumption_id, maximum = "4" * 64, 20_000_000
    scenario_id = digest(
        canonical(
            {
                "kind": "scenario_spec_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "additional_delay": {"value": maximum + 1, "unit": "ns"},
                "assumption_id": assumption_id,
            }
        )
    )
    return {
        "kind": "alpha_scorecard_v1",
        "schema_version": 1,
        "profile": PROFILE,
        "kit_id": "e" * 64,
        "suite_id": suite.suite_id,
        "suite": suite.document,
        "cases": cases,
        "invalid_perturbation": {
            "kind": "alpha_invalid_perturbation_check_v1",
            "schema_version": 1,
            "source_case": "counterexample",
            "source_bundle_id": "a" * 64,
            "assumption_id": assumption_id,
            "scenario_id": scenario_id,
            "policy": INVALID_POLICY,
            "validator": "validate_scenario_spec_v1",
            "frozen_maximum_ns": maximum,
            "challenge_delay_ns": maximum + 1,
            "outcome": "REJECTED",
            "reason_code": "scenario_delay_outside_frozen_assumption_range",
        },
        "publication_probe": probe_document("e" * 64),
        "gates": dict(GATES),
        "scope": dict(SCOPE),
    }


def test_exact_suite_and_scorecard_are_detached_content_values():
    document = declared_document()
    suite = load_alpha_suite(canonical(document["suite"]))
    scorecard = build_alpha_scorecard(document)
    assert load_alpha_scorecard(scorecard.canonical_bytes) == scorecard
    assert scorecard.scorecard_id == digest(scorecard.canonical_bytes)
    assert suite.suite_id == document["suite_id"]
    view = scorecard.document
    view["gates"]["external_attempts"] = 1
    assert scorecard.document["gates"] == GATES
    with pytest.raises(AlphaValidationError):
        replace(scorecard, scorecard_id="0" * 64)
    with pytest.raises(AlphaValidationError):
        replace(suite, suite_id="0" * 64)


@pytest.mark.parametrize(
    "path,value",
    [
        (("gates", "external_attempts"), 1),
        (("gates", "external_attempts"), False),
        (("gates", "external_successes"), 1),
        (("gates", "external_attempt_gate"), "PASS"),
        (("gates", "release_decision"), "READY"),
        (("scope", "external_identity_authenticated"), True),
        (("scope", "new_research_attempts"), 0),
        (("schema_version",), True),
        (("invalid_perturbation", "scenario_id"), "0" * 64),
        (("invalid_perturbation", "challenge_delay_ns"), 20_000_000),
        (("publication_probe", "precommit_sync_failure", "target_exists"), True),
        (("publication_probe", "postcommit_parent_sync_failure", "success_returned"), True),
        (("publication_probe", "postcommit_parent_sync_failure", "retained_kit_id"), "0" * 64),
        (("publication_probe", "existing_destination", "original_tree_unchanged"), False),
        (("cases", "clean_control", "coverage_complete_for_plan"), False),
        (("cases", "clean_control", "outer_stop_reason"), "evaluation_limit"),
        (("cases", "clean_control", "true_ordinals"), [1]),
        (("cases", "counterexample", "false_ordinals"), []),
        (("cases", "counterexample", "witness_ordinals"), [1]),
    ],
)
def test_rehashed_declarations_cannot_expand_gates_or_weaken_oracles(path, value):
    document = declared_document()
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(AlphaValidationError):
        load_alpha_scorecard(canonical(document))


@pytest.mark.parametrize("change", ["unknown", "float", "duplicate", "pretty", "oversize"])
def test_strict_json_and_bounds_reject_nonprofile_scorecards(change, monkeypatch):
    document = declared_document()
    if change == "unknown":
        document["owner_approved"] = True
    elif change == "float":
        document["schema_version"] = 1.0
    raw = canonical(document)
    if change == "duplicate":
        raw = raw.replace(
            b'"kind":"alpha_scorecard_v1"',
            b'"kind":"alpha_scorecard_v1","kind":"alpha_scorecard_v1"',
            1,
        )
    elif change == "pretty":
        raw = json.dumps(document, indent=2).encode()
    elif change == "oversize":
        monkeypatch.setattr(
            "tickwitness.domain.evidence.alpha_scorecard.MAX_ALPHA_SCORECARD_BYTES", len(raw) - 1
        )
    with pytest.raises(AlphaValidationError):
        load_alpha_scorecard(raw)


def test_suite_pins_and_fixed_policies_cannot_be_rewritten():
    document = declared_document()["suite"]
    for key, value in (
        ("publication_probe", "saved_probe_is_true"),
        ("external_gate", "ci_counts_as_external"),
        ("schema_version", True),
    ):
        changed = deepcopy(document)
        changed[key] = value
        with pytest.raises(AlphaValidationError):
            load_alpha_suite(canonical(changed))
    with pytest.raises(AlphaValidationError):
        build_alpha_suite(
            counterexample_bundle_id="a" * 64,
            counterexample_report_id="b" * 64,
            clean_bundle_id="a" * 64,
            clean_report_id="b" * 64,
        )
