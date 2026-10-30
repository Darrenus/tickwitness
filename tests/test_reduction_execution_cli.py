"""Execution CLI cannot create a replacement ledger or expose confirmation data."""

import json
from pathlib import Path

import pytest

from tickwitness.application.reductions import prepare_reduction_input
from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.reduction_bundles import LocalReductionBundles
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

CORPUS = Path(__file__).resolve().parents[1] / "examples" / "alpha"


@pytest.mark.parametrize("command", ["run-reduction-input", "inspect-reduction-run"])
def test_confirmation_denied_before_ids_source_preparation_or_ledger(tmp_path, capsys, command):
    args = [
        command,
        "invalid",
        "--source-evidence",
        "missing",
        "--input-root",
        str(tmp_path),
        "--runs",
        str(tmp_path / "runs"),
        "--split",
        "confirmation",
    ]
    if command == "run-reduction-input":
        args += ["--expected-preparation-id", "invalid"]
    assert main(args) == 5
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_portable_source_cannot_create_a_new_budget_ledger(tmp_path, capsys):
    source = read_search_evidence_bundle(CORPUS / "counterexample")
    prepared = prepare_reduction_input(
        source,
        canonical(
            {
                "kind": "reduction_request_v1",
                "schema_version": 1,
                "witness_ordinal": 3,
                "focus_from_capture_seq": 4,
                "through_capture_seq": 4,
                "additional_delay_ns": 1_000_000_000,
            }
        ),
        expected_bundle_id=source.bundle_id,
        expected_report_id=digest(source.artifacts["finding_report"]),
    )
    preparation = tmp_path / "prepared"
    LocalReductionBundles(CORPUS).publish(prepared, preparation)
    missing = tmp_path / "never-created-ledger"
    assert (
        main(
            [
                "run-reduction-input",
                str(preparation),
                "--expected-preparation-id",
                prepared.preparation_id,
                "--source-evidence",
                "counterexample",
                "--input-root",
                str(CORPUS),
                "--runs",
                str(missing),
            ]
        )
        == 4
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"]["code"] == "research_evidence_not_found"
    assert not missing.exists()
