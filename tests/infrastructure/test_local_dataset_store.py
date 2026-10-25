"""Real-filesystem publication, corruption and catalog visibility contracts."""

import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import pytest

from tickwitness.infrastructure.local_dataset_store import (
    DatasetNotFoundError,
    DatasetRecord,
    DatasetStoreError,
    LocalDatasetStore,
)

RAW = b"original capture bytes\n"
NORMALIZED = b'{"event":"synthetic-trade"}\n'
REPORT: dict[str, object] = {"quality_status": "quarantined", "issues": ["missing_clock"]}


def publish(store: LocalDatasetStore) -> DatasetRecord:
    return store.publish(RAW, NORMALIZED, REPORT)


def reference_path(root: Path, manifest: dict[str, object], role: str) -> Path:
    references = manifest["objects"]
    assert isinstance(references, dict)
    reference = references[role]
    assert isinstance(reference, dict)
    path = reference["ref"]
    assert isinstance(path, str)
    return root / path


def forged_manifest(root: Path, manifest: dict[str, object]) -> str:
    """Install a self-hashed but semantically invalid manifest via direct tampering."""
    encoded = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    identity = hashlib.sha256(encoded).hexdigest()
    (root / "manifests" / f"{identity}.json").write_bytes(encoded)
    with sqlite3.connect(root / "catalog.sqlite3") as connection:
        connection.execute("INSERT INTO datasets VALUES (?, ?, 1)", (identity, identity))
    return identity


def test_publication_is_content_bound_idempotent_and_detached(tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = LocalDatasetStore(root)
    report: dict[str, object] = {"quality_status": "quarantined", "nested": {"x": 1, "y": 2}}
    first = store.publish(RAW, NORMALIZED, report)
    repeat = store.publish(
        RAW, NORMALIZED, {"nested": {"y": 2, "x": 1}, "quality_status": "quarantined"}
    )

    assert first.created is True
    assert repeat.created is False
    assert repeat.dataset_id == first.dataset_id
    assert first.report["quality_status"] == "quarantined"
    assert first.manifest["format_id"] == "tickwitness.normalized-events.v1"
    assert str(root) not in json.dumps(first.manifest)
    assert store.list_datasets() == (store.get(first.dataset_id),)
    assert store.get(first.dataset_id).created is False
    assert (
        LocalDatasetStore(tmp_path / "elsewhere").publish(RAW, NORMALIZED, report).dataset_id
        == first.dataset_id
    )

    report["quality_status"] = "changed_after_publication"
    first.report["quality_status"] = "changed_in_record"
    first.manifest["format_id"] = "changed_in_record"
    restored = store.get(first.dataset_id)
    assert restored.report["quality_status"] == "quarantined"
    assert restored.manifest["format_id"] == "tickwitness.normalized-events.v1"
    with pytest.raises(FrozenInstanceError):
        first.created = False  # type: ignore[misc]


@pytest.mark.parametrize("changed", ["raw", "normalized", "report", "format"])
def test_every_semantic_input_changes_dataset_identity(tmp_path: Path, changed: str) -> None:
    store = LocalDatasetStore(tmp_path)
    first = publish(store)
    result = store.publish(
        RAW + b"extra" if changed == "raw" else RAW,
        NORMALIZED + b"extra" if changed == "normalized" else NORMALIZED,
        {**REPORT, "extra": True} if changed == "report" else REPORT,
        format_id="tickwitness.normalized-events.v2"
        if changed == "format"
        else "tickwitness.normalized-events.v1",
    )
    assert result.dataset_id != first.dataset_id
    assert len(store.list_datasets()) == 2
    assert [row.dataset_id for row in store.list_datasets()] == sorted(
        row.dataset_id for row in store.list_datasets()
    )


def test_mid_publication_failure_exposes_nothing_and_retry_succeeds(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    # A real, non-file destination lets raw publication finish but blocks the
    # next object. No mock replaces file writes or SQLite transaction behavior.
    blocked = tmp_path / "objects" / "sha256" / hashlib.sha256(NORMALIZED).hexdigest()
    blocked.mkdir()

    with pytest.raises(DatasetStoreError, match="regular files"):
        publish(store)

    assert (tmp_path / "objects" / "sha256" / hashlib.sha256(RAW).hexdigest()).is_file()
    assert store.list_datasets() == ()
    with sqlite3.connect(tmp_path / "catalog.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM datasets").fetchone() == (0,)

    blocked.rmdir()
    assert publish(store).created is True
    assert publish(store).created is False
    assert len(store.list_datasets()) == 1


def test_manifest_publication_failure_leaves_only_unreachable_objects(tmp_path: Path) -> None:
    expected = publish(LocalDatasetStore(tmp_path / "reference"))
    root = tmp_path / "failing"
    store = LocalDatasetStore(root)
    blocked = root / "manifests" / f"{expected.dataset_id}.json"
    blocked.mkdir()

    with pytest.raises(DatasetStoreError, match="regular files"):
        publish(store)

    assert len(list((root / "objects" / "sha256").iterdir())) == 3
    assert store.list_datasets() == ()
    with pytest.raises(DatasetNotFoundError):
        store.get(expected.dataset_id)
    blocked.rmdir()
    assert publish(store).dataset_id == expected.dataset_id


def test_two_store_instances_publish_one_catalog_identity(tmp_path: Path) -> None:
    first_store = LocalDatasetStore(tmp_path)
    second_store = LocalDatasetStore(tmp_path)
    barrier = Barrier(2)

    def together(store: LocalDatasetStore) -> DatasetRecord:
        barrier.wait(timeout=5)
        return publish(store)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(together, store) for store in (first_store, second_store)]
        results = [future.result(timeout=10) for future in futures]

    assert results[0].dataset_id == results[1].dataset_id
    assert sorted(result.created for result in results) == [False, True]
    assert len(first_store.list_datasets()) == 1
    with sqlite3.connect(tmp_path / "catalog.sqlite3") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)


@pytest.mark.parametrize("round_index", range(20))
def test_fresh_root_concurrent_initialization_and_publication(
    tmp_path: Path, round_index: int
) -> None:
    root = tmp_path / f"round-{round_index}" / "new" / "store"
    barrier = Barrier(8)

    def start_fresh() -> DatasetRecord:
        barrier.wait(timeout=5)
        return publish(LocalDatasetStore(root))

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(start_fresh) for _ in range(8)]
        records = [future.result(timeout=15) for future in futures]

    assert len({record.dataset_id for record in records}) == 1
    assert sum(record.created for record in records) == 1
    assert len(LocalDatasetStore(root, create=False).list_datasets()) == 1


@pytest.mark.parametrize("create", [False, True])
@pytest.mark.parametrize("foreign_kind", ["different_owner", "unknown_version", "unversioned"])
def test_foreign_catalog_tree_is_unchanged_when_open_is_rejected(
    tmp_path: Path, create: bool, foreign_kind: str
) -> None:
    root = tmp_path / "foreign"
    root.mkdir()
    (root / "owner-data.txt").write_bytes(b"preserve unrelated owner data")
    with sqlite3.connect(root / "catalog.sqlite3") as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('preserve me')")
        if foreign_kind == "different_owner":
            connection.execute("PRAGMA user_version = 1")
            connection.execute("PRAGMA application_id = 17")
        elif foreign_kind == "unknown_version":
            connection.execute("PRAGMA user_version = 99")

    def snapshot() -> dict[str, tuple[int, int, bytes | None]]:
        result: dict[str, tuple[int, int, bytes | None]] = {}
        for path in [root, *sorted(root.rglob("*"))]:
            info = path.lstat()
            result[str(path.relative_to(root))] = (
                info.st_mode,
                info.st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
        return result

    before = snapshot()
    with pytest.raises(DatasetStoreError):
        LocalDatasetStore(root, create=create)
    assert snapshot() == before
    with sqlite3.connect(root / "catalog.sqlite3") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)


def test_open_existing_does_not_create_missing_root_or_catalog(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(DatasetNotFoundError):
        LocalDatasetStore(missing, create=False)
    assert not missing.exists()

    ordinary = tmp_path / "ordinary-directory"
    ordinary.mkdir()
    (ordinary / "sentinel").write_bytes(b"leave this directory alone")
    with pytest.raises(DatasetNotFoundError):
        LocalDatasetStore(ordinary, create=False)
    assert [path.name for path in ordinary.iterdir()] == ["sentinel"]


def test_open_existing_verifies_evidence_and_distinguishes_damage(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    original = publish(store)
    reopened = LocalDatasetStore(tmp_path, create=False)
    assert reopened.get(original.dataset_id).report == original.report
    with pytest.raises(DatasetNotFoundError):
        reopened.get("0" * 64)

    reference_path(tmp_path, original.manifest, "raw").unlink()
    with pytest.raises(DatasetStoreError) as caught:
        reopened.get(original.dataset_id)
    assert not isinstance(caught.value, DatasetNotFoundError)


def test_open_existing_does_not_repair_missing_store_directories(tmp_path: Path) -> None:
    LocalDatasetStore(tmp_path)
    (tmp_path / "manifests").rmdir()
    with pytest.raises(DatasetStoreError) as caught:
        LocalDatasetStore(tmp_path, create=False)
    assert not isinstance(caught.value, DatasetNotFoundError)
    assert not (tmp_path / "manifests").exists()


@pytest.mark.parametrize("report_bytes", [b"null", b'{"value":NaN}', b'{"x":1,"x":2}'])
def test_self_hashed_report_still_requires_canonical_json_object(
    tmp_path: Path, report_bytes: bytes
) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    manifest = record.manifest
    references = manifest["objects"]
    assert isinstance(references, dict)
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    references["report"] = {
        "sha256": report_hash,
        "size_bytes": len(report_bytes),
        "ref": f"objects/sha256/{report_hash}",
    }
    (tmp_path / "objects" / "sha256" / report_hash).write_bytes(report_bytes)
    identity = forged_manifest(tmp_path, manifest)
    with pytest.raises(DatasetStoreError, match="JSON"):
        store.get(identity)


@pytest.mark.parametrize("role", ["raw", "normalized", "report"])
def test_tampered_content_fails_get_list_and_republication(tmp_path: Path, role: str) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    path = reference_path(tmp_path, record.manifest, role)
    contents = path.read_bytes()
    path.write_bytes(bytes([contents[0] ^ 1]) + contents[1:])

    with pytest.raises(DatasetStoreError, match="hash"):
        store.get(record.dataset_id)
    with pytest.raises(DatasetStoreError, match="hash"):
        store.list_datasets()
    with pytest.raises(DatasetStoreError, match="hash"):
        publish(store)
    assert path.read_bytes() != contents  # Publication cannot silently repair history.


def test_missing_object_invalidates_the_entire_list(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    reference_path(tmp_path, record.manifest, "normalized").unlink()
    with pytest.raises(DatasetStoreError):
        store.get(record.dataset_id)
    with pytest.raises(DatasetStoreError):
        store.list_datasets()


def test_tampered_manifest_is_rejected_even_when_json_is_valid(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    path = tmp_path / "manifests" / f"{record.dataset_id}.json"
    path.write_text('{"schema_version":1}')
    with pytest.raises(DatasetStoreError, match="hash"):
        store.get(record.dataset_id)


@pytest.mark.parametrize("tamper", ["path", "hash", "size", "schema", "roles"])
def test_self_hashed_manifest_still_requires_a_valid_closed_schema(
    tmp_path: Path, tamper: str
) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    manifest = record.manifest
    references = manifest["objects"]
    assert isinstance(references, dict)
    raw_ref = references["raw"]
    assert isinstance(raw_ref, dict)
    if tamper == "path":
        raw_ref["ref"] = "../../outside"
    elif tamper == "hash":
        raw_ref["sha256"] = "../" + "a" * 64
    elif tamper == "size":
        raw_ref["size_bytes"] = True
    elif tamper == "schema":
        manifest["schema_version"] = 2
    else:
        references.pop("normalized")
    identity = forged_manifest(tmp_path, manifest)

    with pytest.raises(DatasetStoreError):
        store.get(identity)
    with pytest.raises(DatasetStoreError):
        store.list_datasets()


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "g" * 64, "a" * 63, "/" + "a" * 64])
def test_dataset_ids_never_become_arbitrary_paths(tmp_path: Path, identity: str) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(DatasetStoreError, match="64 lowercase hexadecimal"):
        store.get(identity)


def test_unpublished_orphan_is_not_a_dataset(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    content_hash = hashlib.sha256(RAW).hexdigest()
    (tmp_path / "objects" / "sha256" / content_hash).write_bytes(RAW)
    with pytest.raises(DatasetNotFoundError):
        store.get(content_hash)
    assert store.list_datasets() == ()


@pytest.mark.parametrize("target", ["raw", "manifest"])
def test_symlink_evidence_is_rejected_even_if_external_bytes_match(
    tmp_path: Path, target: str
) -> None:
    root = tmp_path / "store"
    store = LocalDatasetStore(root)
    record = publish(store)
    path = (
        reference_path(root, record.manifest, "raw")
        if target == "raw"
        else (root / "manifests" / f"{record.dataset_id}.json")
    )
    outside = tmp_path / "outside"
    outside.write_bytes(path.read_bytes())
    original = outside.read_bytes()
    path.unlink()
    path.symlink_to(outside)

    with pytest.raises(DatasetStoreError):
        store.get(record.dataset_id)
    with pytest.raises(DatasetStoreError):
        store.list_datasets()
    assert outside.read_bytes() == original


@pytest.mark.parametrize("part", ["objects", "manifests", "catalog.sqlite3"])
def test_symlink_store_components_are_rejected_at_initialization(tmp_path: Path, part: str) -> None:
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    if part == "catalog.sqlite3":
        outside.write_bytes(b"do not modify")
    else:
        outside.mkdir()
    (root / part).symlink_to(outside, target_is_directory=outside.is_dir())

    with pytest.raises(DatasetStoreError):
        LocalDatasetStore(root)
    if outside.is_file():
        assert outside.read_bytes() == b"do not modify"
    else:
        assert list(outside.iterdir()) == []


def test_catalog_sidecar_symlink_is_never_given_to_sqlite(tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = LocalDatasetStore(root)
    outside = tmp_path / "outside"
    outside.write_bytes(b"do not modify")
    (root / "catalog.sqlite3-wal").symlink_to(outside)
    with pytest.raises(DatasetStoreError, match="non-symlink"):
        store.list_datasets()
    assert outside.read_bytes() == b"do not modify"


def test_fifo_object_is_rejected_without_waiting_for_a_writer(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    raw = reference_path(tmp_path, record.manifest, "raw")
    raw.unlink()
    os.mkfifo(raw)
    with pytest.raises(DatasetStoreError, match="regular files"):
        store.get(record.dataset_id)


def test_unknown_catalog_schema_is_rejected_without_initializing_over_it(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    with sqlite3.connect(tmp_path / "catalog.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(DatasetStoreError, match="schema version"):
        LocalDatasetStore(tmp_path)
    with pytest.raises(DatasetStoreError, match="schema version"):
        store.get(record.dataset_id)
    with pytest.raises(DatasetStoreError, match="schema version"):
        store.list_datasets()
    with sqlite3.connect(tmp_path / "catalog.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (99,)
        assert connection.execute("SELECT count(*) FROM datasets").fetchone() == (1,)


def test_catalog_reference_tampering_cannot_redirect_manifest_lookup(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    with sqlite3.connect(tmp_path / "catalog.sqlite3") as connection:
        connection.execute("UPDATE datasets SET manifest_sha256 = ?", ("../outside",))
    with pytest.raises(DatasetStoreError, match="identity"):
        store.get(record.dataset_id)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), b"bytes", {1, 2}, (1, 2)])
def test_non_json_reports_are_rejected_before_publication(tmp_path: Path, bad: object) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(DatasetStoreError, match="JSON"):
        store.publish(RAW, NORMALIZED, {"bad": bad})
    assert store.list_datasets() == ()


def test_cycles_and_non_string_report_keys_are_rejected(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(DatasetStoreError, match="cycles"):
        store.publish(RAW, NORMALIZED, cyclic)
    with pytest.raises(DatasetStoreError, match="keys"):
        store.publish(RAW, NORMALIZED, {1: "bad"})  # type: ignore[dict-item]


def test_format_id_cannot_inject_a_filesystem_path(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(DatasetStoreError, match="non-path"):
        store.publish(RAW, NORMALIZED, REPORT, format_id="../../outside")
    assert store.list_datasets() == ()


def test_read_normalized_returns_verified_bounded_bytes_even_when_quarantined(
    tmp_path: Path,
) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    assert store.read_normalized(record.dataset_id, max_bytes=len(NORMALIZED)) == NORMALIZED
    with pytest.raises(DatasetStoreError, match="max_bytes"):
        store.read_normalized(record.dataset_id, max_bytes=len(NORMALIZED) - 1)
    assert record.report["quality_status"] == "quarantined"


@pytest.mark.parametrize("budget", [0, -1, True])
def test_read_normalized_requires_a_positive_real_byte_budget(tmp_path: Path, budget: int) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(DatasetStoreError, match="positive integer"):
        store.read_normalized(publish(store).dataset_id, max_bytes=budget)


def test_read_normalized_requires_the_fixed_v1_format(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    record = store.publish(RAW, NORMALIZED, REPORT, format_id="tickwitness.other-format.v1")
    with pytest.raises(DatasetStoreError, match=r"normalized-events\.v1"):
        store.read_normalized(record.dataset_id)


@pytest.mark.parametrize("role", ["raw", "normalized", "report"])
def test_read_normalized_rechecks_the_entire_sealed_closure(tmp_path: Path, role: str) -> None:
    store = LocalDatasetStore(tmp_path)
    record = publish(store)
    path = reference_path(tmp_path, record.manifest, role)
    path.write_bytes(b"damaged")
    with pytest.raises(DatasetStoreError):
        store.read_normalized(record.dataset_id)


def test_read_normalized_cannot_read_arbitrary_cas_paths(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(DatasetStoreError, match="64 lowercase"):
        store.read_normalized("../outside")
    with pytest.raises(DatasetNotFoundError):
        store.read_normalized("0" * 64)
