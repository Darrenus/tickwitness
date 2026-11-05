"""Canonical CLI exports bind actual records; offline fixtures are not new native runs."""

import json

import pytest
from test_reduction_execution import reduction_case as reduction_case
from test_reduction_execution import run
from test_search_findings import tree

from tickwitness.cli import main
from tickwitness.cli_reduction_comparison import VERIFICATION
from tickwitness.domain.evidence.reduction_comparison import (
    MAX_REDUCTION_COMPARISON_EXPORT_BYTES,
)
from tickwitness.domain.evidence.run_records import canonical, digest, parse


def _arguments(command, run_id, root, *, bundle="a" * 64, report="b" * 64):
    positional = [command, run_id]
    if command == "verify-reduction-comparison":
        positional += ["comparison.json", "--expected-comparison-id", "c" * 64]
    return [
        *positional,
        "--source-evidence",
        "portable-source",
        "--input-root",
        str(root),
        "--runs",
        str(root / "runs"),
        "--expected-bundle-id",
        bundle,
        "--expected-report-id",
        report,
    ]


@pytest.mark.parametrize("command", ["compare-reduction-run", "verify-reduction-comparison"])
def test_confirmation_precedes_ids_paths_and_all_factories(tmp_path, capsys, command):
    arguments = _arguments(command, "invalid", tmp_path / "missing", bundle="bad", report="bad")
    assert main([*arguments, "--split", "confirmation"]) == 5
    streams = capsys.readouterr()
    assert not streams.out
    assert json.loads(streams.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("command", ["compare-reduction-run", "verify-reduction-comparison"])
@pytest.mark.parametrize("field", ["run", "bundle", "report"])
def test_invalid_identities_precede_source_and_ledger_io(tmp_path, capsys, command, field):
    arguments = _arguments(
        command,
        "bad" if field == "run" else "d" * 64,
        tmp_path / "missing",
        bundle="bad" if field == "bundle" else "a" * 64,
        report="bad" if field == "report" else "b" * 64,
    )
    assert main(arguments) == 2
    streams = capsys.readouterr()
    assert not streams.out
    assert json.loads(streams.err)["error"]["code"] == "invalid_research_evidence"
    assert list(tmp_path.iterdir()) == []


def test_unsafe_export_is_rejected_before_source_or_ledger(tmp_path, capsys):
    arguments = _arguments("verify-reduction-comparison", "d" * 64, tmp_path)
    arguments[2] = "../comparison.json"
    assert main(arguments) == 2
    streams = capsys.readouterr()
    assert not streams.out
    assert json.loads(streams.err)["error"]["code"] == "unsafe_input"
    assert list(tmp_path.iterdir()) == []


def test_export_compare_verify_and_markdown_use_same_readonly_evidence(reduction_case, capsys):
    value = reduction_case
    submitted = run(value)
    root = value.case.root
    source_before = tree(root / "portable-source")
    runs_before = tree(root / "runs")
    arguments = _arguments(
        "compare-reduction-run",
        submitted.run_id,
        root,
        bundle=value.source.bundle_id,
        report=digest(value.source.artifacts["finding_report"]),
    )
    assert main(arguments) == 0
    streams = capsys.readouterr()
    assert not streams.err
    raw = streams.out.encode("utf-8")
    exported = parse(raw, limit=MAX_REDUCTION_COMPARISON_EXPORT_BYTES)
    assert not raw.endswith(b"\n")
    assert exported["comparison_id"] == digest(canonical(exported["report"]))
    assert exported["report"]["both_false_witnesses"] is True
    assert exported["report"]["input_difference"]["removed_event_count"] == 0
    (root / "comparison.json").write_bytes(raw)
    verify = _arguments(
        "verify-reduction-comparison",
        submitted.run_id,
        root,
        bundle=value.source.bundle_id,
        report=digest(value.source.artifacts["finding_report"]),
    )
    verify[4] = exported["comparison_id"]
    assert main(verify) == 0
    streams = capsys.readouterr()
    assert not streams.err
    receipt = parse(streams.out.encode("utf-8"), limit=MAX_REDUCTION_COMPARISON_EXPORT_BYTES)
    assert receipt["kind"] == "reduction_comparison_verification_receipt_v1"
    assert receipt["report"] == exported["report"]
    assert receipt["comparison_id"] == exported["comparison_id"]
    assert receipt["verification"] == dict(VERIFICATION)
    assert main([*arguments, "--format", "markdown"]) == 0
    streams = capsys.readouterr()
    assert not streams.err
    assert exported["comparison_id"] in streams.out
    assert "## Removed trailing events" in streams.out
    assert "PRESERVED" in streams.out
    assert "global earliest event or a causal effect" in streams.out
    assert tree(root / "portable-source") == source_before
    assert tree(root / "runs") == runs_before


def test_rehashed_saved_comparison_cannot_override_actual_run(reduction_case, capsys):
    value = reduction_case
    submitted = run(value)
    root = value.case.root
    common = {
        "bundle": value.source.bundle_id,
        "report": digest(value.source.artifacts["finding_report"]),
    }
    assert main(_arguments("compare-reduction-run", submitted.run_id, root, **common)) == 0
    streams = capsys.readouterr()
    exported = json.loads(streams.out)
    exported["report"]["input_difference"]["removed_event_count"] = 1
    exported["comparison_id"] = digest(canonical(exported["report"]))
    (root / "comparison.json").write_bytes(canonical(exported))
    before = tree(root / "runs")
    arguments = _arguments("verify-reduction-comparison", submitted.run_id, root, **common)
    arguments[4] = exported["comparison_id"]
    assert main(arguments) == 2
    streams = capsys.readouterr()
    assert not streams.out
    assert json.loads(streams.err)["error"]["code"] == "invalid_research_evidence"
    assert tree(root / "runs") == before
