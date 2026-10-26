"""Command authorization rejects confirmation before touching the configured paths."""

import json

import pytest

import tickwitness.cli as cli
from tickwitness.application.tagged_queue_execution import TaggedQueueReservationUnconfirmed
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


def test_tagged_single_cli_preserves_unknown_reservation_consumption(monkeypatch, tmp_path, capsys):
    protocol_id = "a" * 64

    def uncertain(_arguments):
        raise TaggedQueueReservationUnconfirmed(protocol_id)

    monkeypatch.setattr(cli, "execute_tagged_queue_command", uncertain)
    assert (
        main(
            [
                "run-tagged-queue-model",
                protocol_id,
                "protected_tag_front_cancel_v1",
                "--store",
                str(tmp_path / "data"),
                "--registry",
                str(tmp_path / "registry"),
                "--ledger",
                str(tmp_path / "ledger"),
            ]
        )
        == 3
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["code"] == "tagged_queue_reservation_unconfirmed"
    assert error["protocol_id"] == protocol_id
    assert error["budget_consumed"] is None
    assert "Inspect" in error["message"]
