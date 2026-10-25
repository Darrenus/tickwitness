"""Public commands use real files and stores and return machine-readable failures."""

import json
from pathlib import Path

import pytest

from tickwitness.cli import main


def test_cli_import_then_inspect(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = {
        "schema_version": 1,
        "type": "snapshot",
        "source": "synthetic",
        "instrument": "TEST-USD",
        "session": "cli-test",
        "capture_seq": 1,
        "event_time_ns": 100,
        "receive_time_ns": None,
        "last_sequence": 10,
        "bids": [[99, 5]],
        "asks": [[101, 5]],
    }
    (tmp_path / "events.jsonl").write_text(json.dumps(raw) + "\n")
    store = str(tmp_path / "store")

    code = main(["import-events", "events.jsonl", "--input-root", str(tmp_path), "--store", store])
    imported = json.loads(capsys.readouterr().out)
    assert code == 0
    assert imported["created"] is True
    assert imported["report"]["unknown_receive_count"] == 1

    code = main(
        [
            "import-events",
            "events.jsonl",
            "--input-root",
            str(tmp_path),
            "--store",
            store,
            "--id-only",
        ]
    )
    assert code == 0
    assert capsys.readouterr().out.strip() == imported["dataset_id"]

    code = main(["inspect-dataset", imported["dataset_id"], "--store", store])
    inspected = json.loads(capsys.readouterr().out)
    assert code == 0
    assert inspected["manifest"] == imported["manifest"]
    assert inspected["report"] == imported["report"]


def test_cli_rejects_traversal_without_creating_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"

    code = main(
        ["import-events", "../outside.jsonl", "--input-root", str(tmp_path), "--store", str(store)]
    )

    assert code == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "unsafe_input"
    assert not store.exists()


def test_cli_unknown_dataset_has_a_distinct_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["inspect-dataset", "0" * 64, "--store", str(tmp_path / "store")])

    assert code == 4
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "dataset_not_found"
    assert not (tmp_path / "store").exists()


def test_invalid_dataset_identity_is_rejected_before_storage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["inspect-dataset", "../bad", "--store", str(tmp_path / "store")])

    assert caught.value.code == 2
    assert "dataset_id" in capsys.readouterr().err
    assert not (tmp_path / "store").exists()
