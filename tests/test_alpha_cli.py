"""Installed-style CLI composition uses real corpus and preserves redirected receipts."""

import json
import shutil
from pathlib import Path

import pytest

from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical

CORPUS = Path(__file__).resolve().parents[1] / "examples" / "alpha"


def export_arguments(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    shutil.copytree(CORPUS, inputs / "cases")
    wheel = inputs / "tickwitness-0.2.0.dev0-py3-none-any.whl"
    wheel.write_bytes(b"opaque IO fixture; never installed by these tests")
    guide = inputs / "guide.md"
    guide.write_bytes(b"Read the separately supplied owner content pin.\n")
    runner = inputs / "reproduce.py"
    runner.write_bytes(b"raise AssertionError('qualification must not execute included code')\n")
    output = tmp_path / "kit"
    return output, [
        "export-alpha-kit",
        "--counterexample",
        str(inputs / "cases" / "counterexample"),
        "--clean-control",
        str(inputs / "cases" / "clean-control"),
        "--wheel",
        str(wheel),
        "--guide",
        str(guide),
        "--runner",
        str(runner),
        "--source-revision",
        "1" * 40,
        "--output",
        str(output),
    ]


def export_kit(tmp_path, capsys):
    output, arguments = export_arguments(tmp_path)
    assert main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    receipt = json.loads(captured.out)
    assert receipt["kind"] == "alpha_kit_export_receipt_v1"
    assert receipt["technical_qualification_performed"] is False
    assert receipt["external_attempts"] == 0
    assert receipt["release_authorized"] is False
    return output, receipt["kit_id"]


def qualify_arguments(kit, kit_id, probe):
    return ["qualify-alpha-kit", str(kit), "--expected-kit-id", kit_id, "--probe-root", str(probe)]


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_export_qualify_and_redirected_single_lf_receipt_reproduce(tmp_path, capsys):
    kit, kit_id = export_kit(tmp_path, capsys)
    before = tree(kit)
    assert main(qualify_arguments(kit, kit_id, tmp_path / "probe-first")) == 0
    emitted = capsys.readouterr()
    assert emitted.err == ""
    assert emitted.out.endswith("\n") and not emitted.out.endswith("\n\n")
    receipt = json.loads(emitted.out)
    assert receipt["kind"] == "alpha_scorecard_receipt_v1"
    assert receipt["scorecard"]["gates"]["external_attempt_gate"] == "PENDING"
    (tmp_path / "receipt.json").write_bytes(emitted.out.encode())
    assert (
        main(
            [
                "verify-alpha-scorecard",
                str(kit),
                "receipt.json",
                "--input-root",
                str(tmp_path),
                "--expected-kit-id",
                kit_id,
                "--probe-root",
                str(tmp_path / "probe-second"),
            ]
        )
        == 0
    )
    verified = capsys.readouterr()
    assert verified.err == "" and json.loads(verified.out) == receipt
    assert tree(kit) == before
    assert not (tmp_path / "probe-first" / "precommit").exists()
    assert (tmp_path / "probe-second" / "postcommit").is_dir()


def test_bad_pin_and_probe_inside_kit_refuse_without_writing(tmp_path, capsys):
    kit, kit_id = export_kit(tmp_path, capsys)
    before = tree(kit)
    probe = tmp_path / "bad-pin-probe"
    assert main(qualify_arguments(kit, "0" * 64, probe)) == 3
    error = capsys.readouterr()
    assert error.out == ""
    assert json.loads(error.err)["error"]["code"] == "alpha_kit_integrity_or_io_failure"
    assert not probe.exists()
    inside = kit / "new-probe"
    assert main(qualify_arguments(kit, kit_id, inside)) == 2
    error = capsys.readouterr()
    assert error.out == ""
    assert json.loads(error.err)["error"]["code"] == "invalid_alpha_evidence"
    assert not inside.exists() and tree(kit) == before


@pytest.mark.parametrize("attack", ["forged_gate", "second_lf"])
def test_saved_forgery_or_extra_framing_is_rejected_before_probe(tmp_path, capsys, attack):
    kit, kit_id = export_kit(tmp_path, capsys)
    assert main(qualify_arguments(kit, kit_id, tmp_path / "first")) == 0
    emitted = capsys.readouterr().out
    if attack == "forged_gate":
        receipt = json.loads(emitted)
        receipt["scorecard"]["gates"]["external_attempts"] = 1
        saved = canonical(receipt) + b"\n"
    else:
        saved = emitted.encode() + b"\n"
    (tmp_path / "saved.json").write_bytes(saved)
    probe = tmp_path / "must-not-run"
    assert (
        main(
            [
                "verify-alpha-scorecard",
                str(kit),
                "saved.json",
                "--input-root",
                str(tmp_path),
                "--expected-kit-id",
                kit_id,
                "--probe-root",
                str(probe),
            ]
        )
        == 2
    )
    result = capsys.readouterr()
    assert result.out == ""
    assert json.loads(result.err)["error"]["code"] == "invalid_alpha_evidence"
    assert not probe.exists()


def test_export_destination_inside_original_case_is_rejected_without_changes(tmp_path, capsys):
    _kit, arguments = export_arguments(tmp_path)
    source = tmp_path / "inputs" / "cases" / "counterexample"
    before = tree(source)
    arguments[-1] = str(source / "nested-kit")
    assert main(arguments) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert json.loads(result.err)["error"]["code"] == "invalid_alpha_evidence"
    assert tree(source) == before and not (source / "nested-kit").exists()


@pytest.mark.parametrize("command", ["qualify-alpha-kit", "verify-alpha-scorecard"])
def test_missing_kit_does_not_create_kit_or_probe_root(tmp_path, capsys, command):
    missing, probe = tmp_path / "missing", tmp_path / "probe"
    arguments = [command, str(missing)]
    if command == "verify-alpha-scorecard":
        arguments.extend(["saved.json", "--input-root", str(tmp_path)])
    arguments.extend(["--expected-kit-id", "a" * 64, "--probe-root", str(probe)])
    assert main(arguments) == 4
    result = capsys.readouterr()
    assert result.out == ""
    assert json.loads(result.err)["error"]["code"] == "alpha_kit_not_found"
    assert not missing.exists() and not probe.exists()
