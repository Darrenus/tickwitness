"""Stable missing-object detail must not grant offline verification new authority."""

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

from tickwitness.cli import main
from tickwitness.infrastructure.evidence_bundles import export_bundle

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "evidence-demo"
ROLES = (
    "attempt",
    "dataset_manifest",
    "evaluation",
    "normalized",
    "protocol",
    "raw",
    "replay_result",
    "report",
)


@pytest.fixture
def portable(tmp_path: Path) -> Path:
    return Path(shutil.copytree(EXAMPLE, tmp_path / "portable"))


def inventory(root: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in root.rglob("*"):
        kind = stat.S_IFMT(path.lstat().st_mode)
        if kind == stat.S_IFREG:
            payload = hashlib.sha256(path.read_bytes()).hexdigest()
        elif kind == stat.S_IFLNK:
            payload = os.readlink(path)
        else:
            payload = ""
        result[str(path.relative_to(root))] = kind, payload
    return result


def fail(root: Path, capsys: pytest.CaptureFixture[str], expected: int = 3) -> dict:
    assert main(["verify-evidence", str(root)]) == expected
    captured = capsys.readouterr()
    assert captured.out == ""
    return json.loads(captured.err)["error"]


@pytest.mark.parametrize("role", ROLES)
def test_deleted_declared_leaf_has_stable_context_without_writes(
    portable: Path, capsys: pytest.CaptureFixture[str], role: str
) -> None:
    manifest = json.loads((portable / "manifest.json").read_bytes())
    reference = manifest["roles"][role]
    (portable / reference["ref"]).unlink()
    before = inventory(portable)

    error = fail(portable, capsys)

    aliases = sorted(
        name for name, item in manifest["roles"].items() if item["sha256"] == reference["sha256"]
    )
    assert set(error) == {"code", "message", "reason", "role", "roles", "sha256"}
    assert error["code"] == "research_store_integrity_or_io_failure"
    assert error["reason"] == "bundle_object_missing"
    assert error["role"] == aliases[0] and error["roles"] == aliases
    assert error["sha256"] == reference["sha256"]
    assert str(portable) not in error["message"]
    assert inventory(portable) == before


def test_shared_leaf_keeps_all_aliases_and_deterministic_first_sha(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # These bytes intentionally test only the IO failure path, not semantic validity.
    payload = {role: role.encode() for role in ROLES}
    payload["normalized"] = payload["raw"]
    root = tmp_path / "aliases"
    bundle = export_bundle(root, payload)
    references = bundle.manifest["roles"]
    shared = references["raw"]["sha256"]
    (root / references["raw"]["ref"]).unlink()
    error = fail(root, capsys)
    assert error["role"] == "normalized"
    assert error["roles"] == ["normalized", "raw"] and error["sha256"] == shared

    other = references["protocol"]["sha256"]
    (root / references["protocol"]["ref"]).unlink()
    before = inventory(root)
    error = fail(root, capsys)
    selected = min(shared, other)
    aliases = sorted(name for name, ref in references.items() if ref["sha256"] == selected)
    assert error["sha256"] == selected and error["roles"] == aliases
    assert inventory(root) == before


@pytest.mark.parametrize("missing", ["manifest.json", "objects", "objects/sha256"])
def test_missing_manifest_or_container_does_not_invent_object_context(
    portable: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    path = portable / missing
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    before = inventory(portable)
    error = fail(portable, capsys)
    assert error["code"] == "research_store_integrity_or_io_failure"
    assert set(error) == {"code", "message"}
    assert inventory(portable) == before


def test_missing_root_retains_exit_four_without_creating_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "absent" / "bundle"
    error = fail(root, capsys, expected=4)
    assert error["code"] == "research_evidence_not_found"
    assert set(error) == {"code", "message"}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("damage", ["manifest", "bytes", "size", "symlink", "fifo", "extra"])
def test_integrity_and_unsafe_inputs_do_not_become_missing_objects(
    portable: Path, capsys: pytest.CaptureFixture[str], damage: str
) -> None:
    manifest = json.loads((portable / "manifest.json").read_bytes())
    victim = portable / manifest["roles"]["raw"]["ref"]
    if damage == "manifest":
        (portable / "manifest.json").write_bytes(b"{}")
    elif damage == "bytes":
        data = victim.read_bytes()
        victim.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    elif damage == "size":
        victim.write_bytes(b"short")
    elif damage == "extra":
        (victim.parent / "unexpected").write_bytes(b"extra")
    else:
        victim.unlink()
        if damage == "symlink":
            victim.symlink_to(portable / "manifest.json")
        else:
            os.mkfifo(victim)
    before = inventory(portable)
    error = fail(portable, capsys)
    assert error["code"] == "research_store_integrity_or_io_failure"
    assert set(error) == {"code", "message"}
    assert inventory(portable) == before


def test_valid_and_missing_offline_reads_need_no_database_worker_or_network(
    portable: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline diagnostics must not open a database, worker or network")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    before = inventory(portable)
    assert main(["verify-evidence", str(portable)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    receipt = json.loads(captured.out)
    assert receipt["native_replayed"] is False and receipt["accounting_verified"] is True
    assert inventory(portable) == before
    manifest = json.loads((portable / "manifest.json").read_bytes())
    (portable / manifest["roles"]["attempt"]["ref"]).unlink()
    remaining = inventory(portable)
    assert fail(portable, capsys)["reason"] == "bundle_object_missing"
    assert inventory(portable) == remaining
