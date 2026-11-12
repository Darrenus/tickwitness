"""Real DatasetStore roots exercise bounded, cooperative orphan maintenance."""

import fcntl
import hashlib
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest

from tickwitness.infrastructure import dataset_retention
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.dataset_retention import LocalDatasetMaintenance
from tickwitness.infrastructure.local_dataset_store import DatasetStoreError, LocalDatasetStore


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def seeded(tmp_path):
    root = tmp_path / "store"
    store = LocalDatasetStore(root)
    record = store.publish(b"raw capture", b"normalized events", {"quality": "fixture"})
    return root, store, record


def orphan(root, payload=b"interrupted publication orphan"):
    sha = hashlib.sha256(payload).hexdigest()
    path = root / "objects" / "sha256" / sha
    path.write_bytes(payload)
    return sha, path


def protected(record):
    return {reference["sha256"] for reference in record.manifest["objects"].values()}


def test_missing_store_is_not_created(tmp_path):
    root = tmp_path / "missing"
    maintenance = LocalDatasetMaintenance(root)
    plan = maintenance.plan(0)
    assert plan.document["status"] == "BLOCKED"
    assert plan.document["diagnostics"] == ["store_unavailable"]
    assert maintenance.apply(plan)["diagnostic"] == "blocked_plan"
    assert not root.exists()


def test_shared_objects_are_retained_for_every_published_dataset(tmp_path):
    root, store, first = seeded(tmp_path)
    second = store.publish(b"raw capture", b"normalized events", {"second": "report"})
    assert len(protected(first) & protected(second)) == 2
    candidate, _ = orphan(root)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert set(plan.document["protected_objects"]) == protected(first) | protected(second)
    assert plan.document["candidates"] == [candidate]
    assert LocalDatasetMaintenance(root).apply(plan)["status"] == "APPLIED"
    assert {record.dataset_id for record in store.list_datasets()} == {
        first.dataset_id,
        second.dataset_id,
    }


def test_plan_exact_apply_and_repeat_keep_all_referenced_bytes(tmp_path):
    root, store, record = seeded(tmp_path)
    first, _ = orphan(root)
    second, _ = orphan(root, b"another orphan")
    maintenance = LocalDatasetMaintenance(root)
    before = tree(root)
    plan = maintenance.plan(0)
    document = plan.document
    assert document["status"] == "READY"
    assert document["candidates"] == sorted([first, second])
    assert set(document["protected_objects"]) == protected(record)
    assert tree(root) == before
    result = maintenance.apply(plan)
    assert result["status"] == "APPLIED"
    assert result["unlinked"] == document["candidates"]
    assert result["already_absent"] == []
    assert result["removed_logical_bytes"] == len(b"interrupted publication orphananother orphan")
    removed = {"objects/sha256/" + sha for sha in result["unlinked"]}
    assert tree(root) == {path: data for path, data in before.items() if path not in removed}
    repeat_before = tree(root)
    repeat = maintenance.apply(plan)
    assert repeat["status"] == "APPLIED"
    assert repeat["unlinked"] == []
    assert repeat["already_absent"] == document["candidates"]
    assert repeat["removed_logical_bytes"] == 0
    assert tree(root) == repeat_before
    assert store.get(record.dataset_id).manifest == record.manifest


def test_dry_run_has_no_write_or_retained_payload_open(tmp_path, monkeypatch):
    root, _, record = seeded(tmp_path)
    candidate, _ = orphan(root)
    retained = protected(record)
    before = tree(root)
    actual_open, actual_connect = os.open, sqlite3.connect
    connections = []

    def guarded_open(path, flags, *args, **kwargs):
        assert Path(path).name not in retained
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        return actual_open(path, flags, *args, **kwargs)

    def guarded_connect(database, *args, **kwargs):
        assert "mode=ro" in str(database) and "immutable=1" in str(database)
        assert kwargs["uri"] is True
        connections.append(str(database))
        return actual_connect(database, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("A dry-run must not create or delete metadata")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", guarded_open)
        patch.setattr(sqlite3, "connect", guarded_connect)
        for name in ("mkdir", "unlink", "link", "replace", "rename"):
            patch.setattr(os, name, forbidden)
        plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["status"] == "READY"
    assert plan.document["candidates"] == [candidate]
    assert len(connections) == 1
    assert all(
        row["content_verified"] is (row["sha256"] not in retained)
        for row in plan.document["files"]
        if row["path"].startswith("objects/")
    )
    assert tree(root) == before


def test_unindexed_valid_manifest_is_still_a_reference_root(tmp_path, monkeypatch):
    root, store, _ = seeded(tmp_path)
    before = set((root / "manifests").iterdir())

    @contextmanager
    def fail_catalog(*args, **kwargs):
        raise OSError("Injected before Catalog visibility, after manifest installation")
        yield  # pragma: no cover

    with monkeypatch.context() as patch:
        patch.setattr(store, "_connection", fail_catalog)
        with pytest.raises(DatasetStoreError, match="Catalog visibility"):
            store.publish(b"uncatalogued raw", b"uncatalogued normalized", {"unindexed": True})
    assert len(set((root / "manifests").iterdir()) - before) == 1
    assert len(store.list_datasets()) == 1
    # A normal validated RW lifecycle is explicit fixture preparation after a
    # WAL-mode read; retention itself never checkpoints or removes sidecars.
    LocalDatasetStore(root)
    original = tree(root)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["status"] == "READY" and plan.document["candidates"] == []
    assert len(plan.document["protected_objects"]) == 6
    assert LocalDatasetMaintenance(root).apply(plan)["status"] == "APPLIED"
    assert tree(root) == original


def test_real_interrupted_publish_releases_gate_and_leaves_only_orphan_candidate(
    tmp_path, monkeypatch
):
    root, store, record = seeded(tmp_path)
    actual = store._publish_file
    raw = b"actual first CAS publication before manifest failure"
    raw_id = hashlib.sha256(raw).hexdigest()

    def interrupted(directory, name, data):
        actual(directory, name, data)
        if name == raw_id:
            raise OSError("Injected after durable first CAS insertion")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_publish_file", interrupted)
        with pytest.raises(DatasetStoreError, match="first CAS"):
            store.publish(raw, b"never published normalized", {"unused": True})
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["status"] == "READY" and plan.document["candidates"] == [raw_id]
    assert LocalDatasetMaintenance(root).apply(plan)["unlinked"] == [raw_id]
    assert store.get(record.dataset_id).manifest == record.manifest


@pytest.mark.parametrize("operation", ["publisher", "reader"])
def test_gate_covers_whole_active_publication_or_read(tmp_path, monkeypatch, operation):
    root, store, record = seeded(tmp_path)
    held, release = Event(), Event()
    if operation == "publisher":
        actual = store._publish_file
        first_id = hashlib.sha256(b"active publication").hexdigest()

        def paused(directory, name, data):
            actual(directory, name, data)
            if name == first_id:
                held.set()
                assert release.wait(10)

        monkeypatch.setattr(store, "_publish_file", paused)

        def task():
            return store.publish(b"active publication", b"new normalized", {"live": True})

    else:
        actual_read = store._read_verified_file

        def paused_read(*args, **kwargs):
            held.set()
            assert release.wait(10)
            return actual_read(*args, **kwargs)

        monkeypatch.setattr(store, "_read_verified_file", paused_read)

        def task():
            return store.get(record.dataset_id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(task)
        try:
            assert held.wait(10)
            plan = LocalDatasetMaintenance(root).plan(0)
            assert plan.document["status"] == "BLOCKED"
            assert plan.document["diagnostics"] == ["maintenance_busy"]
            assert plan.document["candidates"] == []
        finally:
            release.set()
        future.result(timeout=10)
    # Releasing the reader gate and satisfying the closed-Catalog prerequisite
    # are separate facts; a normal RW lifecycle prepares the latter explicitly.
    LocalDatasetStore(root)
    assert LocalDatasetMaintenance(root).plan(0).document["status"] == "READY"


def test_exclusive_gate_refuses_constructor_and_every_existing_reader_before_sqlite(
    tmp_path, monkeypatch
):
    root, store, record = seeded(tmp_path)
    plan = LocalDatasetMaintenance(root).plan(0)
    before = tree(root)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)

    def no_sqlite(*args, **kwargs):
        raise AssertionError("Busy reader/constructor must not open SQLite")

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, "connect", no_sqlite)
            operations = (
                lambda: LocalDatasetStore(root, create=False),
                lambda: LocalDatasetStore(root),
                lambda: store.get(record.dataset_id),
                lambda: store.list_datasets(),
                lambda: store.read_normalized(record.dataset_id),
                lambda: store.read_artifacts(record.dataset_id),
                lambda: store.publish(b"no write", b"no normalized", {"no": "write"}),
            )
            for operation in operations:
                with pytest.raises(DatasetStoreError, match="gate is busy"):
                    operation()
        assert LocalDatasetMaintenance(root).apply(plan)["diagnostic"] == "maintenance_busy"
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert tree(root) == before


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_sidecars_refuse_before_sqlite_and_without_touching_any_bytes(
    tmp_path, monkeypatch, sidecar
):
    root, _, _ = seeded(tmp_path)
    orphan(root)
    (root / ("catalog.sqlite3" + sidecar)).write_bytes(b"closed-store precondition not met")
    before = tree(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("Sidecar presence must refuse before SQLite open")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["status"] == "BLOCKED"
    assert plan.document["diagnostics"] == ["sidecar_present"]
    assert plan.document["candidates"] == [] and tree(root) == before


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "pending", "directory", "mixed"])
def test_unknown_unsafe_and_mixed_roots_block_all_candidates(tmp_path, unsafe):
    root, _, _ = seeded(tmp_path)
    orphan(root)
    objects = root / "objects" / "sha256"
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside sentinel")
    if unsafe == "symlink":
        (objects / ("a" * 64)).symlink_to(outside)
    elif unsafe == "hardlink":
        os.link(outside, objects / hashlib.sha256(outside.read_bytes()).hexdigest())
    elif unsafe == "pending":
        (objects / ".pending-interrupted").write_bytes(b"not a canonical orphan")
    elif unsafe == "directory":
        (objects / ("b" * 64)).mkdir()
    else:
        LocalAttemptLedger(root)
    before = tree(root)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["status"] == "BLOCKED" and plan.document["candidates"] == []
    assert plan.document["diagnostics"][0] in {"unknown_entry", "unsafe_entry"}
    assert LocalDatasetMaintenance(root).apply(plan)["diagnostic"] == "blocked_plan"
    assert tree(root) == before and outside.read_bytes() == b"outside sentinel"


@pytest.mark.parametrize("failure", ["manifest", "missing_reference", "wrong_size", "orphan_hash"])
def test_invalid_reference_graphs_and_orphan_bytes_never_form_partial_authority(tmp_path, failure):
    root, _, record = seeded(tmp_path)
    _, path = orphan(root)
    raw_id = record.manifest["objects"]["raw"]["sha256"]
    if failure == "manifest":
        manifest = root / "manifests" / (record.dataset_id + ".json")
        manifest.write_bytes(manifest.read_bytes() + b" ")
    elif failure == "missing_reference":
        (root / "objects" / "sha256" / raw_id).unlink()
    elif failure == "wrong_size":
        (root / "objects" / "sha256" / raw_id).write_bytes(b"different declared size")
    else:
        path.write_bytes(b"invalid CAS bytes")
    before = tree(root)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["status"] == "BLOCKED" and plan.document["candidates"] == []
    assert tree(root) == before


def test_retained_same_size_payload_is_not_opened_or_claimed_content_verified(tmp_path):
    root, store, record = seeded(tmp_path)
    raw_id = record.manifest["objects"]["raw"]["sha256"]
    path = root / "objects" / "sha256" / raw_id
    path.write_bytes(b"x" * len(path.read_bytes()))
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["status"] == "READY" and plan.document["candidates"] == []
    raw_row = next(row for row in plan.document["files"] if row["sha256"] == raw_id)
    assert raw_row["content_verified"] is False
    with pytest.raises(DatasetStoreError, match="hash"):
        store.get(record.dataset_id)


def test_fixed_age_uses_both_mtime_and_ctime_and_keeps_future_entries(tmp_path):
    root, _, _ = seeded(tmp_path)
    sha, path = orphan(root)
    os.utime(path, ns=(0, 0))
    old_mtime = LocalDatasetMaintenance(root).plan()
    assert old_mtime.document["status"] == "READY" and old_mtime.document["candidates"] == []
    assert LocalDatasetMaintenance(root).plan(0).document["candidates"] == [sha]
    future = time.time_ns() + 1_000_000_000_000
    os.utime(path, ns=(future, future))
    assert LocalDatasetMaintenance(root).plan(0).document["candidates"] == []


@pytest.mark.parametrize("drift", ["new_object", "new_reference", "retained_metadata", "recreated"])
def test_apply_revalidates_every_original_fact_before_first_unlink(tmp_path, drift):
    root, store, record = seeded(tmp_path)
    sha, path = orphan(root)
    maintenance = LocalDatasetMaintenance(root)
    plan = maintenance.plan(0)
    if drift == "new_object":
        orphan(root, b"new unrelated object after frozen plan")
    elif drift == "new_reference":
        store.publish(b"new raw", b"new normalized", {"new": "reference"})
    elif drift == "retained_metadata":
        raw_id = record.manifest["objects"]["raw"]["sha256"]
        os.chmod(root / "objects" / "sha256" / raw_id, 0o400)
    else:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(path.read_bytes())
        assert replacement.stat().st_ino != path.stat().st_ino
        os.replace(replacement, path)
    before = tree(root)
    refused = maintenance.apply(plan)
    assert refused["status"] == "REFUSED" and refused["diagnostic"] == "snapshot_changed"
    assert refused["unlinked"] == [] and refused["removed_logical_bytes"] == 0
    assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha
    assert tree(root) == before


def test_partial_unlink_requires_explicit_repeat_and_gives_only_new_credit(tmp_path, monkeypatch):
    root, _, _ = seeded(tmp_path)
    first, first_path = orphan(root, b"first candidate")
    second, second_path = orphan(root, b"second candidate")
    maintenance = LocalDatasetMaintenance(root)
    plan = maintenance.plan(0)
    ordered = sorted([first, second])
    actual_unlink = os.unlink

    def fail_second(path, *args, **kwargs):
        if str(path) == ordered[1]:
            raise OSError("Injected second unlink failure")
        return actual_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", fail_second)
        partial = maintenance.apply(plan)
    assert partial["status"] == "PARTIAL" and partial["diagnostic"] == "unlink_failed"
    assert partial["unlinked"] == [ordered[0]] and partial["already_absent"] == []
    remaining = first_path if first_path.exists() else second_path
    remaining_size = remaining.stat().st_size
    completed = maintenance.apply(plan)
    assert completed["status"] == "APPLIED"
    assert completed["already_absent"] == [ordered[0]] and completed["unlinked"] == [ordered[1]]
    assert completed["removed_logical_bytes"] == remaining_size


def test_fsync_failure_reports_known_unlinks_as_unconfirmed_and_repeat_observes_absence(
    tmp_path, monkeypatch
):
    root, _, _ = seeded(tmp_path)
    sha, path = orphan(root)
    size = path.stat().st_size
    maintenance = LocalDatasetMaintenance(root)
    plan = maintenance.plan(0)

    def failed(*args, **kwargs):
        raise OSError("Injected objects directory fsync failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", failed)
        uncertain = maintenance.apply(plan)
    assert uncertain["status"] == "IO_UNCONFIRMED"
    assert uncertain["diagnostic"] == "fsync_unconfirmed" and uncertain["unlinked"] == [sha]
    assert uncertain["removed_logical_bytes"] == size and not path.exists()
    repeated = maintenance.apply(plan)
    assert repeated["status"] == "APPLIED"
    assert repeated["already_absent"] == [sha]
    assert repeated["unlinked"] == [] and repeated["removed_logical_bytes"] == 0


def test_limits_never_return_a_deletable_truncated_subset(tmp_path, monkeypatch):
    root, _, _ = seeded(tmp_path)
    orphan(root)
    before = tree(root)
    monkeypatch.setattr(dataset_retention, "MAX_RETENTION_ENTRIES", 3)
    blocked = LocalDatasetMaintenance(root).plan(0)
    assert blocked.document["diagnostics"] == ["scan_limit"]
    assert blocked.document["candidates"] == [] and tree(root) == before


def test_actual_manifest_and_orphan_read_budget_never_samples_beyond_ceiling(tmp_path, monkeypatch):
    root, _, _ = seeded(tmp_path)
    orphan(root, b"first orphan payload")
    orphan(root, b"second orphan payload")
    manifest_size = sum(path.stat().st_size for path in (root / "manifests").iterdir())
    ceiling = manifest_size + 25
    actual_read = os.read
    observed = []

    def counted(descriptor, amount):
        data = actual_read(descriptor, amount)
        observed.append(len(data))
        return data

    monkeypatch.setattr(dataset_retention, "MAX_RETENTION_SCAN_BYTES", ceiling)
    monkeypatch.setattr(os, "read", counted)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["diagnostics"] == ["scan_limit"]
    assert plan.document["candidates"] == [] and sum(observed) <= ceiling


def test_oversized_object_blocks_before_any_object_content_read(tmp_path, monkeypatch):
    root, _, _ = seeded(tmp_path)
    retained_candidate, candidate_path = orphan(root)
    oversized = root / "objects" / "sha256" / ("0" * 64)
    with oversized.open("wb") as stream:
        stream.truncate(dataset_retention.MAX_RETENTION_OBJECT_BYTES + 1)

    def no_content(*args, **kwargs):
        raise AssertionError("Oversize stat must block before the content scan")

    monkeypatch.setattr(os, "read", no_content)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["diagnostics"] == ["scan_limit"]
    assert plan.document["candidates"] == []
    assert candidate_path.exists() and candidate_path.name == retained_candidate
    assert oversized.stat().st_size == dataset_retention.MAX_RETENTION_OBJECT_BYTES + 1


def test_invalid_catalog_is_preserved_with_no_deletion_authority(tmp_path):
    root, _, _ = seeded(tmp_path)
    _, candidate_path = orphan(root)
    catalog = root / "catalog.sqlite3"
    catalog.write_bytes(b"invalid closed Catalog fixture")
    before = tree(root)
    plan = LocalDatasetMaintenance(root).plan(0)
    assert plan.document["diagnostics"] == ["invalid_catalog"]
    assert plan.document["candidates"] == [] and candidate_path.exists()
    assert tree(root) == before
