"""Actual accepted golden witnesses and fresh publication faults form technical evidence."""

import json
import shutil
import socket
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.alpha_scorecard import (
    BoundaryProbeResult,
    evaluate_alpha_kit,
    prepare_alpha_suite,
    verify_alpha_scorecard,
)
from tickwitness.domain.assumptions import AssumptionValidationError
from tickwitness.domain.evidence.alpha_scorecard import AlphaValidationError
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.alpha_publication_probe import LocalAlphaPublicationProbe
from tickwitness.infrastructure.alpha_reproduction_kits import export_alpha_kit
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

CORPUS = Path(__file__).resolve().parents[2] / "examples" / "alpha"


def forbidden(*_args, **_kwargs):
    raise AssertionError(
        "Technical re-audit cannot use original sources, execute, or trust saved flags"
    )


def tree(path):
    return {
        str(item.relative_to(path)): item.read_bytes() for item in path.rglob("*") if item.is_file()
    }


def packages():
    return read_search_evidence_bundle(CORPUS / "counterexample"), read_search_evidence_bundle(
        CORPUS / "clean-control"
    )


@pytest.fixture
def kit(tmp_path):
    # Preserve genuine accepted native bytes; these tests never generate a run.
    inputs = tmp_path / "assembly-inputs"
    shutil.copytree(CORPUS, inputs)
    ce = read_search_evidence_bundle(inputs / "counterexample")
    clean = read_search_evidence_bundle(inputs / "clean-control")
    suite = prepare_alpha_suite(ce, clean)
    value = export_alpha_kit(
        tmp_path / "kit",
        suite_bytes=suite.canonical_bytes,
        wheel_name="tickwitness-0.2.0.dev0-py3-none-any.whl",
        wheel_bytes=b"opaque wheel is not executed by inspection",
        guide_bytes=b"Synthetic technical reproduction instructions\n",
        runner_bytes=b"raise AssertionError('included code must never execute during qualification')\n",
        counterexample=ce,
        clean_control=clean,
        producer_version="test-assembler",
        source_revision="1" * 40,
    )
    shutil.rmtree(inputs)
    return value


def mutate_package(package, role, raw):
    artifacts = package.artifacts
    artifacts[role] = raw
    manifest = canonical(
        {
            "kind": "search_evidence_bundle_v1",
            "schema_version": 1,
            "scope": "development_scoped_search_evidence_v1",
            "roles": {
                name: {
                    "sha256": digest(data),
                    "size_bytes": len(data),
                    "ref": "objects/sha256/" + digest(data),
                }
                for name, data in artifacts.items()
            },
        }
    )
    return SimpleNamespace(bundle_id=digest(manifest), manifest_bytes=manifest, artifacts=artifacts)


def test_actual_golden_cases_and_faults_rebuild_exact_receipt_without_sources(
    tmp_path, kit, monkeypatch
):
    original = tree(tmp_path / "kit")
    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "__init__", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    first = evaluate_alpha_kit(
        kit,
        expected_kit_id=kit.kit_id,
        publication_probe_factory=lambda: LocalAlphaPublicationProbe(tmp_path / "probe-first"),
    )
    assert first["kind"] == "alpha_scorecard_receipt_v1"
    assert first["finalization_status"] == "LOCAL_RECOMPUTED_TECHNICAL_ONLY"
    scorecard = first["scorecard"]
    assert first["scorecard_id"] == digest(canonical(scorecard))
    assert scorecard["cases"]["counterexample"]["outcome"] == "COUNTEREXAMPLE_FOUND"
    assert scorecard["cases"]["clean_control"]["planned_predicate_truth"] is True
    assert scorecard["cases"]["clean_control"]["eligible_ordinals"] == [1, 3]
    assert (
        scorecard["invalid_perturbation"]["challenge_delay_ns"]
        == scorecard["invalid_perturbation"]["frozen_maximum_ns"] + 1
    )
    assert scorecard["gates"] == {
        "technical_checks": "PASS",
        "external_attempts": 0,
        "external_successes": 0,
        "external_attempt_gate": "PENDING",
        "release_decision": "TECHNICAL_ALPHA_ONLY_EXTERNAL_PENDING",
    }
    assert all(value is False for value in scorecard["scope"].values())
    assert not (tmp_path / "probe-first" / "precommit").exists()
    assert (tmp_path / "probe-first" / "postcommit").is_dir()
    assert not (tmp_path / "assembly-inputs").exists()
    fresh = verify_alpha_scorecard(
        kit,
        canonical(first),
        expected_kit_id=kit.kit_id,
        publication_probe_factory=lambda: LocalAlphaPublicationProbe(tmp_path / "probe-second"),
    )
    assert fresh == first
    assert tree(tmp_path / "kit") == original
    assert (tmp_path / "probe-second" / "postcommit").is_dir()


def test_pins_and_case_role_failures_precede_probe_construction(tmp_path, kit):
    with pytest.raises(AlphaValidationError, match="pinned identity"):
        evaluate_alpha_kit(kit, expected_kit_id="0" * 64, publication_probe_factory=forbidden)
    ce, clean = packages()
    for left, right in ((clean, ce), (ce, ce), (clean, clean)):
        with pytest.raises(AlphaValidationError):
            prepare_alpha_suite(left, right)
    wrong = SimpleNamespace(
        kit_id=kit.kit_id,
        manifest_bytes=kit.manifest_bytes,
        suite_bytes=kit.suite_bytes,
        files=kit.files,
        case=lambda _: ce,
    )
    with pytest.raises(AlphaValidationError):
        evaluate_alpha_kit(wrong, expected_kit_id=kit.kit_id, publication_probe_factory=forbidden)


def test_rehashed_finding_flags_are_not_actual_case_evidence():
    ce, clean = packages()
    report = json.loads(ce.artifacts["finding_report"])
    report["outcome"] = "NO_COUNTEREXAMPLE_FOUND"
    forged = mutate_package(ce, "finding_report", canonical(report))
    with pytest.raises(AlphaValidationError, match="reaudit alpha cases"):
        prepare_alpha_suite(forged, clean)


@pytest.mark.parametrize("mode", ["accepted", "wrong_error"])
def test_invalid_perturbation_must_be_rejected_by_actual_precise_validator(monkeypatch, mode):
    import tickwitness.application.alpha_scorecard as application

    ce, clean = packages()
    actual = application.validate_scenario_spec
    challenged = []

    def altered(scenario, assumptions, **kwargs):
        if (
            scenario.document["additional_delay"]["value"]
            > assumptions.document["additional_delay"]["maximum"]
        ):
            challenged.append(scenario.scenario_id)
            if mode == "wrong_error":
                raise AssumptionValidationError("unrelated binding failure")
            return None
        return actual(scenario, assumptions, **kwargs)

    monkeypatch.setattr(application, "validate_scenario_spec", altered)
    with pytest.raises(AlphaValidationError):
        prepare_alpha_suite(ce, clean)
    assert len(challenged) == 1


def test_postcommit_static_flags_do_not_replace_reaudit_of_actual_retained_cases(tmp_path, kit):
    ce = kit.case("counterexample")
    corrupted = mutate_package(
        ce,
        "normalized",
        ce.artifacts["normalized"].replace(b'"price_ticks":100', b'"price_ticks":101', 1) + b" ",
    )

    class WrongRetained:
        def run(self, supplied):
            actual = LocalAlphaPublicationProbe(tmp_path / "probe-retained").run(supplied)
            retained = actual.postcommit_kit
            substituted = SimpleNamespace(
                kit_id=retained.kit_id,
                manifest_bytes=retained.manifest_bytes,
                suite_bytes=retained.suite_bytes,
                files=retained.files,
                case=lambda name: corrupted if name == "counterexample" else retained.case(name),
            )
            return BoundaryProbeResult(document=actual.document, postcommit_kit=substituted)

    with pytest.raises(AlphaValidationError):
        evaluate_alpha_kit(kit, expected_kit_id=kit.kit_id, publication_probe_factory=WrongRetained)
    assert (tmp_path / "probe-retained" / "postcommit").exists()


def test_valid_saved_shape_still_requires_fresh_probe_and_semantic_equality(tmp_path, kit):
    first = evaluate_alpha_kit(
        kit,
        expected_kit_id=kit.kit_id,
        publication_probe_factory=lambda: LocalAlphaPublicationProbe(tmp_path / "first"),
    )
    first["scorecard"]["cases"]["counterexample"]["source_protocol_id"] = "0" * 64
    first["scorecard_id"] = digest(canonical(first["scorecard"]))
    with pytest.raises(AlphaValidationError, match="does not reproduce"):
        verify_alpha_scorecard(
            kit,
            canonical(first),
            expected_kit_id=kit.kit_id,
            publication_probe_factory=lambda: LocalAlphaPublicationProbe(tmp_path / "fresh"),
        )
    assert (tmp_path / "fresh" / "postcommit").exists()


def test_saved_external_success_is_rejected_without_running_probe(tmp_path, kit):
    first = evaluate_alpha_kit(
        kit,
        expected_kit_id=kit.kit_id,
        publication_probe_factory=lambda: LocalAlphaPublicationProbe(tmp_path / "first"),
    )
    first["scorecard"]["gates"]["external_attempts"] = 1
    first["scorecard_id"] = digest(canonical(first["scorecard"]))
    with pytest.raises(AlphaValidationError, match="External attempts"):
        verify_alpha_scorecard(
            kit, canonical(first), expected_kit_id=kit.kit_id, publication_probe_factory=forbidden
        )


def test_probe_failure_never_gets_a_successful_scorecard(tmp_path, kit):
    class FailedProbe:
        def run(self, _kit):
            raise OSError("controlled probe could not complete")

    with pytest.raises(OSError, match="could not complete"):
        evaluate_alpha_kit(kit, expected_kit_id=kit.kit_id, publication_probe_factory=FailedProbe)


def test_claimed_success_after_a_failed_publication_is_rejected(tmp_path, kit):
    class SuccessAfterFault:
        def run(self, supplied):
            actual = LocalAlphaPublicationProbe(tmp_path / "false-success").run(supplied)
            actual.document["postcommit_parent_sync_failure"]["success_returned"] = True
            return actual

    with pytest.raises(AlphaValidationError, match="Publication boundary"):
        evaluate_alpha_kit(
            kit, expected_kit_id=kit.kit_id, publication_probe_factory=SuccessAfterFault
        )
