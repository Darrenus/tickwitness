"""Command authorization rejects confirmation before touching the configured paths."""

import json

import pytest

from tickwitness.cli import main


@pytest.mark.parametrize(
    "command,positionals",
    [
        ("freeze-tagged-queue", ["a" * 64, "missing.json", "gross.json"]),
        ("inspect-tagged-queue", ["a" * 64]),
        ("inspect-tagged-queue-run", ["a" * 64]),
        ("run-tagged-queue-pair", ["a" * 64]),
        ("run-tagged-queue-model", ["a" * 64, "protected_tag_front_cancel_v1"]),
    ],
)
def test_tagged_cli_confirmation_denial_has_no_filesystem_side_effect(
    command, positionals, tmp_path, capsys
):
    root = tmp_path / "absent"
    flags = [
        "--store",
        str(root / "data"),
        "--registry",
        str(root / "registry"),
        "--split",
        "confirmation",
    ]
    flags += (
        ["--input-root", str(root)]
        if command == "freeze-tagged-queue"
        else ["--ledger", str(root / "ledger")]
    )
    assert main([command, *positionals, *flags]) == 5
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "confirmation_access_denied"
    assert not root.exists()
