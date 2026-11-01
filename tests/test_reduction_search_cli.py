"""Reduction coordination keeps confirmation, budget and exit-stream boundaries."""

import json
import shutil
from pathlib import Path

import pytest

from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

CORPUS = Path(__file__).resolve().parents[1] / "examples" / "alpha"


@pytest.mark.parametrize(
    "command",
    [
        "freeze-reduction-search",
        "run-reduction-search",
        "inspect-reduction-search",
        "cancel-reduction-search",
    ],
)
def test_confirmation_denial_precedes_invalid_ids_packages_and_factories(tmp_path, capsys, command):
    args = [command, "invalid"]
    if command == "freeze-reduction-search":
        args += [
            "missing.json", "--expected-bundle-id", "invalid", "--expected-report-id", "invalid"
        ]
    else:
        args += ["--source-evidence", "missing-source"]
    args += [
        "--input-root",
        str(tmp_path / "missing-input-root"),
        "--runs",
        str(tmp_path / "missing-runs"),
        "--split",
        "confirmation",
    ]
    assert main(args) == 5
    streams = capsys.readouterr()
    assert not streams.out
    assert json.loads(streams.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "command", ["run-reduction-search", "inspect-reduction-search", "cancel-reduction-search"]
)
def test_invalid_plan_identity_is_rejected_before_source_or_root_io(tmp_path, capsys, command):
    assert (
        main(
            [
                command,
                "invalid",
                "--source-evidence",
                "missing-source",
                "--input-root",
                str(tmp_path / "missing-input-root"),
                "--runs",
                str(tmp_path / "missing-runs"),
            ]
        )
        == 2
    )
    streams = capsys.readouterr()
    assert not streams.out
    assert json.loads(streams.err)["error"]["code"] == "invalid_research_evidence"
    assert list(tmp_path.iterdir()) == []


def _freeze_args(tmp_path, runs):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    shutil.copytree(CORPUS / "counterexample", inputs / "source")
    source = read_search_evidence_bundle(inputs / "source")
    (inputs / "request.json").write_bytes(
        canonical(
            {
                "kind": "reduction_search_request_v1",
                "schema_version": 1,
                "witness_ordinal": 3,
                "focus_from_capture_seq": 4,
                "max_steps": 7,
                "max_wall_time_ms": 120_000,
            }
        )
    )
    return [
        "freeze-reduction-search",
        "source",
        "request.json",
        "--input-root",
        str(inputs),
        "--expected-bundle-id",
        source.bundle_id,
        "--expected-report-id",
        digest(source.artifacts["finding_report"]),
        "--runs",
        str(runs),
    ]


@pytest.mark.parametrize("existing", [False, True])
def test_old_portable_source_cannot_create_or_restore_original_slots(tmp_path, capsys, existing):
    runs = tmp_path / "runs"
    if existing:
        LocalAttemptLedger(runs)
    before = {
        str(path.relative_to(runs)): path.read_bytes()
        for path in runs.rglob("*")
        if path.is_file()
    }
    assert main(_freeze_args(tmp_path, runs)) == (2 if existing else 4)
    streams = capsys.readouterr()
    assert not streams.out
    assert json.loads(streams.err)["error"]["code"] == (
        "invalid_research_evidence" if existing else "research_evidence_not_found"
    )
    assert not (runs / "reduction-campaigns").exists()
    after = {
        str(path.relative_to(runs)): path.read_bytes()
        for path in runs.rglob("*")
        if path.is_file()
    }
    assert after == before
    if not existing:
        assert not runs.exists()


def test_budget_stop_keeps_structured_stdout_report(tmp_path, capsys, monkeypatch):
    from tickwitness import cli_reduction_search

    report = {
        "plan_id": "0" * 64,
        "status": "STOPPED",
        "stop_reason": "original_attempt_budget_exhausted",
        "exit_code": 8,
    }
    monkeypatch.setattr(
        cli_reduction_search, "run_reduction_search", lambda *args, **kwargs: report
    )
    assert (
        main(
            [
                "run-reduction-search",
                "0" * 64,
                "--source-evidence",
                "counterexample",
                "--input-root",
                str(CORPUS),
                "--runs",
                str(tmp_path / "missing-runs"),
            ]
        )
        == 8
    )
    streams = capsys.readouterr()
    assert not streams.err
    assert json.loads(streams.out) == report
    assert list(tmp_path.iterdir()) == []
