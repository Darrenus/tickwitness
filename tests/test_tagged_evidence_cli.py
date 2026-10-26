"""CLI split and safe path boundaries precede tagged evidence IO."""

import json

import pytest

from tickwitness.cli import main


@pytest.mark.parametrize("command", ["export-tagged-queue-pair", "verify-tagged-queue-pair"])
def test_tagged_evidence_confirmation_denied_before_ids_or_files(command, tmp_path, capsys):
    root = tmp_path / "absent"
    if command.startswith("export"):
        args = [command, "bad", "bad", "--store", str(root / "data"),
                "--registry", str(root / "registry"), "--ledger", str(root / "ledger"),
                "--output", str(root / "bundle")]
    else:
        args = [command, str(root / "bundle"), "--expected-bundle-id", "invalid"]
    assert main([*args, "--split", "confirmation"]) == 5
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "confirmation_access_denied"
    assert not root.exists()


def test_verifier_missing_root_does_not_create_it(tmp_path, capsys):
    path = tmp_path / "missing"
    assert main(["verify-tagged-queue-pair", str(path)]) == 4
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "research_evidence_not_found"
    assert not path.exists()


def test_invalid_expected_identity_precedes_filesystem_read(tmp_path, capsys):
    assert main(["verify-tagged-queue-pair", str(tmp_path / "missing"), "--expected-bundle-id", "invalid"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_research_evidence"
