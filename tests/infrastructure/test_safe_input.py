"""Exercise real filesystem boundaries, not a mocked path-resolution algorithm."""

import os
from pathlib import Path

import pytest

from tickwitness.infrastructure.safe_input import InputReadError, read_jsonl


def test_reads_nested_regular_file_without_changing_bytes(tmp_path: Path) -> None:
    directory = tmp_path / "nested"
    directory.mkdir()
    raw = b'{"example":1}\r\n'
    (directory / "events.jsonl").write_bytes(raw)

    assert read_jsonl(tmp_path, "nested/events.jsonl", max_bytes=len(raw)) == raw


@pytest.mark.parametrize(
    "path", ["../outside.jsonl", "/absolute.jsonl", "nested/../events.jsonl", "x\\y.jsonl", "x.pkl"]
)
def test_rejects_traversal_and_unsupported_formats(tmp_path: Path, path: str) -> None:
    with pytest.raises(InputReadError):
        read_jsonl(tmp_path, path, max_bytes=128)


@pytest.mark.parametrize("parent_symlink", [False, True])
def test_rejects_file_and_parent_symlinks(tmp_path: Path, parent_symlink: bool) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "events.jsonl").write_text("{}\n")
    if parent_symlink:
        (root / "nested").symlink_to(outside, target_is_directory=True)
        candidate = "nested/events.jsonl"
    else:
        (root / "events.jsonl").symlink_to(outside / "events.jsonl")
        candidate = "events.jsonl"

    with pytest.raises(InputReadError):
        read_jsonl(root, candidate, max_bytes=128)


def test_rejects_large_files_before_publication(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_bytes(b"x" * 129)

    with pytest.raises(InputReadError, match="max_bytes"):
        read_jsonl(tmp_path, "events.jsonl", max_bytes=128)


def test_rejects_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "events.jsonl")

    with pytest.raises(InputReadError, match="regular file"):
        read_jsonl(tmp_path, "events.jsonl", max_bytes=128)


def test_root_itself_cannot_be_a_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "actual"
    directory.mkdir()
    (directory / "events.jsonl").write_text("{}\n")
    root = tmp_path / "alias"
    root.symlink_to(directory, target_is_directory=True)

    with pytest.raises(InputReadError):
        read_jsonl(root, "events.jsonl", max_bytes=128)
