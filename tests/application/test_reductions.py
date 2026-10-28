"""Actual sealed CE witnesses prepare legal inputs without executing any research."""

import json
import socket
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.reductions import prepare_reduction_input, verify_reduction_input
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.assumptions import build_scenario_spec, validate_scenario_spec
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.reduction.contracts import (
    FLAGS,
    ReductionValidationError,
    build_reduction_manifest,
)
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

CORPUS = Path(__file__).resolve().parents[2] / "examples" / "alpha"


def request(*, focus=4, through=6, delay=1_000_000_000, ordinal=3):
    return canonical(
        {
            "kind": "reduction_request_v1",
            "schema_version": 1,
            "witness_ordinal": ordinal,
            "focus_from_capture_seq": focus,
            "through_capture_seq": through,
            "additional_delay_ns": delay,
        }
    )


def options(source):
    return {
        "expected_bundle_id": source.bundle_id,
        "expected_report_id": digest(source.artifacts["finding_report"]),
    }


def package(artifacts):
    manifest = build_reduction_manifest(artifacts)
    return SimpleNamespace(
        artifacts=artifacts, manifest_bytes=manifest, preparation_id=digest(manifest)
    )


def forbidden(*_args, **_kwargs):
    raise AssertionError("Preparation cannot execute or open original data/ledger state")


class Unreadable:
    def __getattribute__(self, _name):
        raise AssertionError("Validation must precede any package property")


def test_genuine_source_prefix_recomputation_uses_no_native_or_original_workspace(monkeypatch):
    source = read_search_evidence_bundle(CORPUS / "counterexample")
    pins = options(source)
    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "__init__", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    prepared = prepare_reduction_input(source, request(), **pins)
    document = prepared.materialization.document
    assert document["retained"]["event_count"] == 6
    assert document["retained"]["warmup_event_count"] == 3
    assert [event.capture_seq for event in prepared.materialization.prepared.events] == list(
        range(1, 7)
    )
    assert document["flags"] == dict(FLAGS)
    assert document["changes"] == {
        "strictly_shorter_input": True,
        "parameter_contracted": True,
        "focus_window_narrowed": True,
    }
    receipt = verify_reduction_input(
        package(prepared.artifacts), source=source, expected_preparation_id=prepared.preparation_id
    )
    assert receipt["status"] == "RECOMPUTED_PREPARATION_ONLY"
    assert receipt["source_bundle_id"] == source.bundle_id
    assert receipt["source_report_id"] == pins["expected_report_id"]
    assert receipt["event_count"] == 6 and receipt["warmup_event_count"] == 3
    for flag, value in FLAGS.items():
        assert receipt[flag] is value
    detached = prepared.artifacts
    detached["normalized"] = b"tampered"
    assert prepared.artifacts["normalized"] != b"tampered"


def test_noop_and_changed_delay_rederive_the_full_original_scenario_before_cut():
    source = read_search_evidence_bundle(CORPUS / "counterexample")
    noop = prepare_reduction_input(
        source, request(focus=1, through=7, delay=2_000_000_000), **options(source)
    )
    original = derive_replay_view(noop.materialization.source.validation)
    assert noop.artifacts["normalized"] == original.replay_input.normalized_bytes
    assert noop.materialization.document["changes"] == {
        "strictly_shorter_input": False,
        "parameter_contracted": False,
        "focus_window_narrowed": False,
    }
    contracted = prepare_reduction_input(source, request(), **options(source))
    context = contracted.materialization.source.validation
    scenario = build_scenario_spec(
        canonical(
            {
                "kind": "scenario_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "additional_delay": {"value": 1_000_000_000, "unit": "ns"},
            }
        ),
        assumptions=context.assumptions,
    )
    full = derive_replay_view(
        validate_scenario_spec(
            scenario,
            context.assumptions,
            protocol=context.protocol,
            replay_input=context.replay_input,
        )
    )
    assert contracted.artifacts["normalized"] == b"".join(
        full.replay_input.normalized_bytes.splitlines(keepends=True)[:6]
    )
    assert (
        contracted.materialization.document["prefix_context_id"]
        != noop.materialization.document["prefix_context_id"]
    )


@pytest.mark.parametrize("attack", ["middle_delete", "context", "fake_state", "recipe_binding"])
def test_rehashing_saved_outer_identity_cannot_hide_invalid_preparation(attack):
    source = read_search_evidence_bundle(CORPUS / "counterexample")
    prepared = prepare_reduction_input(source, request(), **options(source))
    artifacts = prepared.artifacts
    if attack == "middle_delete":
        lines = artifacts["normalized"].splitlines(keepends=True)
        artifacts["normalized"] = b"".join(lines[:2] + lines[3:])
    elif attack == "recipe_binding":
        recipe = json.loads(artifacts["recipe"])
        recipe["source"]["source_run_id"] = "0" * 64
        artifacts["recipe"] = canonical(recipe)
    else:
        descriptor = json.loads(artifacts["materialization"])
        if attack == "fake_state":
            descriptor["flags"]["initial_state_materialized"] = True
        else:
            descriptor["prefix_context"]["engine"]["semantic_id"] = "snapshot_resume_v1"
            descriptor["prefix_context_id"] = digest(canonical(descriptor["prefix_context"]))
        artifacts["materialization"] = canonical(descriptor)
    changed = package(artifacts)
    with pytest.raises(ReductionValidationError):
        verify_reduction_input(
            changed, source=source, expected_preparation_id=changed.preparation_id
        )


def test_full_source_and_both_pins_are_required_before_any_cut():
    source = read_search_evidence_bundle(CORPUS / "counterexample")
    for name in ("expected_bundle_id", "expected_report_id"):
        with pytest.raises(ReductionValidationError):
            prepare_reduction_input(source, request(), **{**options(source), name: "0" * 64})
    clean = read_search_evidence_bundle(CORPUS / "clean-control")
    with pytest.raises(ReductionValidationError, match="counterexample"):
        prepare_reduction_input(clean, request(), **options(clean))
    artifacts = source.artifacts
    artifacts["raw"] = artifacts["raw"][:-1] + b" "
    broken = SimpleNamespace(
        bundle_id=source.bundle_id, manifest_bytes=source.manifest_bytes, artifacts=artifacts
    )
    with pytest.raises(ReductionValidationError):
        prepare_reduction_input(broken, request(through=4), **options(source))


@pytest.mark.parametrize(
    "raw",
    [
        b"{broken",
        b'{"kind":"x","kind":"x"}',
        canonical({"checkpoint": True}),
        request(ordinal=True),
        request(delay=-1),
    ],
)
def test_malformed_request_rejects_before_package_properties(raw):
    with pytest.raises(ReductionValidationError):
        prepare_reduction_input(
            Unreadable(), raw, expected_bundle_id="invalid", expected_report_id="invalid"
        )


def test_confirmation_denial_precedes_ids_requests_and_packages():
    with pytest.raises(ConfirmationAccessDenied):
        prepare_reduction_input(
            Unreadable(),
            b"broken",
            expected_bundle_id="invalid",
            expected_report_id="invalid",
            split="confirmation",
        )
    with pytest.raises(ConfirmationAccessDenied):
        verify_reduction_input(
            Unreadable(),
            source=Unreadable(),
            expected_preparation_id="invalid",
            split="confirmation",
        )
