"""CLI reduction preparation has no execution or new finding authority."""

import json
import shutil
from pathlib import Path

import pytest

from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical

BUNDLE_ID = "2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4b1a8e9e6c43c78369"
REPORT_ID = "398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb"
CORPUS = Path(__file__).resolve().parents[1] / "examples" / "alpha" / "counterexample"


def _request():
    return {
        "kind": "reduction_request_v1",
        "schema_version": 1,
        "witness_ordinal": 3,
        "focus_from_capture_seq": 4,
        "through_capture_seq": 6,
        "additional_delay_ns": 1_000_000_000,
    }


def _args(tmp_path):
    return [
        "prepare-reduction-input",
        "source",
        "request.json",
        "--input-root",
        str(tmp_path / "inputs"),
        "--expected-bundle-id",
        BUNDLE_ID,
        "--expected-report-id",
        REPORT_ID,
        "--output",
        str(tmp_path / "prepared"),
    ]


@pytest.mark.parametrize("command", ["prepare-reduction-input", "verify-reduction-input"])
def test_confirmation_denied_before_invalid_identity_or_missing_files(tmp_path, capsys, command):
    if command == "prepare-reduction-input":
        args = _args(tmp_path)
    else:
        args = [
            command,
            "missing",
            "--source-evidence",
            "missing",
            "--expected-preparation-id",
            "invalid",
            "--input-root",
            str(tmp_path),
        ]
    assert main([*args, "--split", "confirmation"]) == 5
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_real_prefix_publish_relocation_verify_and_no_overwrite(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    shutil.copytree(CORPUS, inputs / "source")
    (inputs / "request.json").write_bytes(canonical(_request()))
    assert main(_args(tmp_path)) == 0
    emitted = capsys.readouterr()
    assert not emitted.err
    receipt = json.loads(emitted.out)
    assert receipt["status"] == "PREPARED_INPUT_ONLY"
    assert receipt["event_count"] == 6
    assert receipt["warmup_event_count"] == 3
    assert receipt["native_replayed"] is False
    assert receipt["initial_state_materialized"] is False
    assert receipt["attempt_reserved"] is False
    assert receipt["witness_preservation_verified"] is False
    assert len((tmp_path / "prepared" / "normalized.jsonl").read_bytes().splitlines()) == 6
    shutil.move(tmp_path / "prepared", tmp_path / "relocated")
    assert (
        main(
            [
                "verify-reduction-input",
                str(tmp_path / "relocated"),
                "--source-evidence",
                "source",
                "--input-root",
                str(inputs),
                "--expected-preparation-id",
                receipt["preparation_id"],
            ]
        )
        == 0
    )
    checked = capsys.readouterr()
    assert not checked.err
    assert json.loads(checked.out) == {**receipt, "status": "RECOMPUTED_PREPARATION_ONLY"}
    shutil.move(tmp_path / "relocated", tmp_path / "prepared")
    before = {p.name: p.read_bytes() for p in (tmp_path / "prepared").iterdir()}
    assert main(_args(tmp_path)) == 3
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "bundle_destination_exists"
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "prepared").iterdir()}


def test_unsafe_request_is_rejected_before_missing_source(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "request.json").write_bytes(canonical({**_request(), "checkpoint": {}}))
    assert main(_args(tmp_path)) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "missing" not in json.loads(captured.err)["error"]["message"].lower()
    assert not (tmp_path / "prepared").exists()


def test_source_cannot_escape_input_root(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "request.json").write_bytes(canonical(_request()))
    args = _args(tmp_path)
    args[1] = "../outside"
    assert main(args) == 2
    assert "relative path" in capsys.readouterr().err
    assert not (tmp_path / "prepared").exists()


def test_source_parent_alias_cannot_escape_input_root(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (inputs / "request.json").write_bytes(canonical(_request()))
    (inputs / "alias").symlink_to(outside, target_is_directory=True)
    args = _args(tmp_path)
    args[1] = "alias/source"
    assert main(args) == 2
    assert "remain under input-root" in capsys.readouterr().err
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "prepared").exists()
