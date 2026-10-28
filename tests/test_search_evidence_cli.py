"""Portable search CLI rejects confirmation and missing roots without side effects."""

import json

import pytest

from tickwitness.cli import main


@pytest.mark.parametrize("command", ["export-search-evidence", "verify-search-evidence"])
def test_confirmation_denied_before_files_or_ids(tmp_path, capsys, command):
    missing = tmp_path / "missing"
    args = [command, "invalid"]
    if command.startswith("export"):
        args += ["--expected-report-id", "invalid"]
        for option in ("plans", "store", "registry", "runs", "finding-registry", "output"):
            args += [f"--{option}", str(missing / option)]
    assert main([*args, "--split", "confirmation"]) == 5
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "confirmation_access_denied"
    assert not missing.exists()


def test_missing_bundle_does_not_create_root(tmp_path, capsys):
    missing = tmp_path / "missing"
    assert main(["verify-search-evidence", str(missing)]) == 4
    assert not capsys.readouterr().out
    assert not missing.exists()


def test_export_cannot_add_unknown_entries_to_original_stores(tmp_path, capsys):
    args = ["export-search-evidence", "a" * 64, "--expected-report-id", "b" * 64]
    for option in ("plans", "store", "registry", "runs", "finding-registry"):
        args += [f"--{option}", str(tmp_path / option)]
    args += ["--output", str(tmp_path / "runs" / "new-evidence")]
    assert main(args) == 2
    assert "outside all original source roots" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()
