"""Immutable publication and closure checks without domain or SQLite coupling."""

import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import pytest

from tickwitness.infrastructure.local_protocol_registry import (
    LocalProtocolRegistry,
    ProtocolNotFoundError,
    ProtocolRecord,
    ProtocolRegistryError,
)

SOURCE = b"# Original storage fixture; never executed\n"


def document(source: bytes = SOURCE) -> dict[str, object]:
    # This fixture exercises the storage envelope. Domain/application tests
    # separately check claim meaning, claim digest and dataset overlap.
    return {
        "kind": "frozen_research_protocol_v1",
        "schema_version": 1,
        "execution_ready": False,
        "read_policy": "development_only_v1",
        "claim_revision_id": "a" * 64,
        "claim": {"statement": "storage fixture"},
        "datasets": {"development": "b" * 64, "confirmation": "c" * 64},
        "strategy": {"name": "fixture.py", "sha256": hashlib.sha256(source).hexdigest()},
        "parameters": {},
        "configuration": {},
        "budget": {"scenarios": 1},
        "seed": 7,
    }


def canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def seal(registry: LocalProtocolRegistry) -> ProtocolRecord:
    return registry.seal(canonical(document()), SOURCE)


def test_roundtrip_idempotency_and_frozen_record(tmp_path: Path) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    first = seal(registry)
    repeat = seal(registry)
    assert first.created is True
    assert repeat.created is False
    assert first.protocol_id == hashlib.sha256(first.canonical_bytes).hexdigest()
    assert first.strategy_sha256 == hashlib.sha256(SOURCE).hexdigest()
    assert registry.get(first.protocol_id) == repeat
    assert LocalProtocolRegistry(tmp_path, create=False).get(first.protocol_id) == repeat
    with pytest.raises(FrozenInstanceError):
        first.created = False  # type: ignore[misc]


def test_changed_document_is_new_identity_and_never_overwrites_previous(tmp_path: Path) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    first = seal(registry)
    changed = document()
    changed["seed"] = 8
    second = registry.seal(canonical(changed), SOURCE)
    assert second.protocol_id != first.protocol_id
    assert registry.get(first.protocol_id).canonical_bytes == first.canonical_bytes
    assert len(list((tmp_path / "objects" / "sha256").iterdir())) == 1
    assert len(list((tmp_path / "protocols").iterdir())) == 2


@pytest.mark.parametrize("round_id", range(5))
def test_concurrent_fresh_seal_has_one_commit_winner(tmp_path: Path, round_id: int) -> None:
    root = tmp_path / str(round_id) / "nested" / "registry"
    barrier = Barrier(8)

    def together() -> ProtocolRecord:
        barrier.wait(timeout=5)
        return seal(LocalProtocolRegistry(root))

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(together) for _ in range(8)]
        records = [future.result(timeout=10) for future in futures]
    assert len({record.protocol_id for record in records}) == 1
    assert sum(record.created for record in records) == 1
    assert len(list((root / "protocols").iterdir())) == 1


def test_real_publication_failure_leaves_strategy_orphan_but_no_committed_protocol(
    tmp_path: Path,
) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    encoded = canonical(document())
    identity = hashlib.sha256(encoded).hexdigest()
    blocked = tmp_path / "protocols" / f"{identity}.json"
    blocked.mkdir()
    with pytest.raises(ProtocolRegistryError, match="regular"):
        registry.seal(encoded, SOURCE)
    assert (
        tmp_path / "objects" / "sha256" / hashlib.sha256(SOURCE).hexdigest()
    ).read_bytes() == SOURCE
    with pytest.raises(ProtocolRegistryError):
        registry.get(identity)
    blocked.rmdir()
    assert registry.seal(encoded, SOURCE).created is True


@pytest.mark.parametrize("target", ["strategy", "protocol"])
def test_tampering_is_detected_and_never_repaired_by_sealing(tmp_path: Path, target: str) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    record = seal(registry)
    path = (
        tmp_path / "objects" / "sha256" / record.strategy_sha256
        if target == "strategy"
        else tmp_path / "protocols" / f"{record.protocol_id}.json"
    )
    original = path.read_bytes()
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(ProtocolRegistryError, match="hash"):
        registry.get(record.protocol_id)
    with pytest.raises(ProtocolRegistryError, match="hash"):
        seal(registry)
    assert path.read_bytes() != original


def test_missing_strategy_is_corruption_not_an_absent_protocol(tmp_path: Path) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    record = seal(registry)
    (tmp_path / "objects" / "sha256" / record.strategy_sha256).unlink()
    with pytest.raises(ProtocolRegistryError) as caught:
        registry.get(record.protocol_id)
    assert not isinstance(caught.value, ProtocolNotFoundError)


@pytest.mark.parametrize("target", ["strategy", "protocol"])
def test_symlink_with_matching_external_bytes_is_rejected(tmp_path: Path, target: str) -> None:
    root = tmp_path / "registry"
    registry = LocalProtocolRegistry(root)
    record = seal(registry)
    path = (
        root / "objects" / "sha256" / record.strategy_sha256
        if target == "strategy"
        else root / "protocols" / f"{record.protocol_id}.json"
    )
    outside = tmp_path / "outside"
    original = path.read_bytes()
    outside.write_bytes(original)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ProtocolRegistryError):
        registry.get(record.protocol_id)
    with pytest.raises(ProtocolRegistryError):
        seal(registry)
    assert outside.read_bytes() == original


@pytest.mark.parametrize("component", ["objects", "protocols", "objects/sha256"])
def test_directory_symlinks_are_never_followed(tmp_path: Path, component: str) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    path = root / component
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProtocolRegistryError):
        LocalProtocolRegistry(root)
    assert list(outside.iterdir()) == []


def test_fifo_object_is_rejected_without_a_writer(tmp_path: Path) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    record = seal(registry)
    path = tmp_path / "objects" / "sha256" / record.strategy_sha256
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ProtocolRegistryError, match="regular"):
        registry.get(record.protocol_id)


def test_read_only_open_missing_registry_creates_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ProtocolNotFoundError):
        LocalProtocolRegistry(missing, create=False)
    assert not missing.exists()
    registry = LocalProtocolRegistry(tmp_path / "existing")
    with pytest.raises(ProtocolNotFoundError):
        registry.get("0" * 64)


def test_registry_does_not_open_or_migrate_an_existing_sqlite_database(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with sqlite3.connect(catalog) as connection:
        connection.execute("PRAGMA user_version = 77")
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    original = catalog.read_bytes()
    seal(LocalProtocolRegistry(tmp_path))
    assert catalog.read_bytes() == original
    assert [path.name for path in tmp_path.glob("*.sqlite*")] == ["catalog.sqlite3"]


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63, "/" + "a" * 64])
def test_protocol_id_is_a_digest_not_a_path(tmp_path: Path, identity: str) -> None:
    with pytest.raises(ProtocolRegistryError, match="64 lowercase"):
        LocalProtocolRegistry(tmp_path).get(identity)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("execution_ready", True),
        ("read_policy", "all_data"),
        ("kind", "other"),
        ("claim_revision_id", "../outside"),
        ("datasets", {"development": "b" * 64, "confirmation": "b" * 64}),
        ("datasets", {"development": "b" * 64, "confirmation": "../outside"}),
        ("strategy", {"name": "fixture", "sha256": "../outside"}),
        ("seed", False),
        ("unknown", "field"),
    ],
)
def test_invalid_envelope_is_rejected_before_strategy_publication(
    tmp_path: Path, field: str, value: object
) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    body = document()
    body[field] = value
    with pytest.raises(ProtocolRegistryError):
        registry.seal(canonical(body), SOURCE)
    assert list((tmp_path / "objects" / "sha256").iterdir()) == []


@pytest.mark.parametrize(
    "encoded",
    [
        b"{}",
        b"\xff",
        b"[]",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":"\\ud800"}',
        b"\xef\xbb\xbf{}",
        b"[" * 1100,
    ],
)
def test_malformed_nonfinite_or_duplicate_json_is_rejected(tmp_path: Path, encoded: bytes) -> None:
    with pytest.raises(ProtocolRegistryError):
        LocalProtocolRegistry(tmp_path).seal(encoded, SOURCE)


def test_noncanonical_encoding_and_source_mismatch_are_rejected(tmp_path: Path) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    with pytest.raises(ProtocolRegistryError, match="canonical"):
        registry.seal(json.dumps(document()).encode(), SOURCE)
    with pytest.raises(ProtocolRegistryError, match="match"):
        registry.seal(canonical(document()), b"different")


def test_protocol_and_strategy_bounds_apply_before_publication(tmp_path: Path) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    oversized = document()
    oversized["configuration"] = {"padding": "x" * (128 * 1024)}
    with pytest.raises(ProtocolRegistryError, match="128 KiB"):
        registry.seal(canonical(oversized), SOURCE)
    source = b"x" * (256 * 1024 + 1)
    with pytest.raises(ProtocolRegistryError, match="256 KiB"):
        registry.seal(canonical(document(source)), source)
    assert list((tmp_path / "protocols").iterdir()) == []


def test_source_is_opaque_bounded_bytes_not_executed_or_decoded(tmp_path: Path) -> None:
    source = b"\xff\x00"
    record = LocalProtocolRegistry(tmp_path).seal(canonical(document(source)), source)
    assert record.strategy_sha256 == hashlib.sha256(source).hexdigest()


def test_self_hashed_but_invalid_protocol_is_rejected_on_read(tmp_path: Path) -> None:
    registry = LocalProtocolRegistry(tmp_path)
    record = seal(registry)
    body = document()
    body["execution_ready"] = True
    encoded = canonical(body)
    identity = hashlib.sha256(encoded).hexdigest()
    (tmp_path / "protocols" / f"{identity}.json").write_bytes(encoded)
    with pytest.raises(ProtocolRegistryError, match="markers"):
        registry.get(identity)
    assert registry.get(record.protocol_id).canonical_bytes == record.canonical_bytes
