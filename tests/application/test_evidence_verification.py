"""Rehashed portable artifacts still have to reproduce their declared semantics."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tickwitness.application.experiments import run_artifacts, run_experiment
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    build_run_receipt,
    canonical,
    digest,
    load_run_receipt,
)
from tickwitness.domain.evidence.verification import verify_artifacts
from tickwitness.infrastructure.evidence_bundles import export_bundle


def artifacts(case):
    submission = run_experiment(
        case.frozen.protocol_id,
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )
    return run_artifacts(
        submission.run_id, ledger=case.ledger_factory(), registry=case.registry, datasets=case.data
    )


def test_rehashing_a_false_claim_observation_does_not_make_it_valid(experiment_case) -> None:
    evidence = artifacts(experiment_case)
    evaluation = json.loads(evidence["evaluation"])
    evaluation["claim_observation"]["satisfied"] = False
    evidence["evaluation"] = canonical(evaluation)
    receipt = load_run_receipt(evidence["attempt"]).document
    receipt["bindings"]["evaluation_sha256"] = digest(evidence["evaluation"])
    evidence["attempt"] = build_run_receipt(receipt).canonical_bytes

    with pytest.raises(EvidenceValidationError, match="does not reproduce"):
        verify_artifacts(evidence)


@pytest.mark.parametrize("change", ["index", "wall", "status"])
def test_portable_run_cannot_change_frozen_budget_or_execution(
    change: str, experiment_case
) -> None:
    evidence = artifacts(experiment_case)
    receipt = load_run_receipt(evidence["attempt"]).document
    if change == "index":
        receipt["attempt"]["attempt_index"] = 3
    elif change == "wall":
        receipt["attempt"]["max_wall_seconds"] = 30
    else:
        receipt["execution_status"] = "incomplete"
    evidence["attempt"] = build_run_receipt(receipt).canonical_bytes

    with pytest.raises(EvidenceValidationError):
        verify_artifacts(evidence)


def test_offline_cli_does_not_connect_sqlite_or_import_native(
    experiment_case, tmp_path: Path
) -> None:
    destination = tmp_path / "portable"
    export_bundle(destination, artifacts(experiment_case))
    script = """
import importlib.abc
import sqlite3
import sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Offline verification must not import native')
sys.meta_path.insert(0, NoNative())
def forbidden(*args, **kwargs):
    raise AssertionError('Offline verification must not connect SQLite')
sqlite3.connect = forbidden
from tickwitness.cli import main
raise SystemExit(main(['verify-evidence', sys.argv[1]]))
"""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(destination)],
        cwd=empty,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["native_replayed"] is False
    assert receipt["accounting_verified"] is True
