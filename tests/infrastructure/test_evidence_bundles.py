"""Exercise fixed bundle trees and publication boundaries on the real filesystem."""

import errno
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import evidence_bundles as bundles
from tickwitness.infrastructure.evidence_bundles import (
    ArtifactBundle,
    BundleDestinationExistsError,
    BundleDurabilityError,
    BundleError,
    BundleLimits,
    BundleMissingObjectError,
    BundleNotFoundError,
    export_bundle,
    read_bundle,
)

ROLES = (
    "protocol",
    "dataset_manifest",
    "raw",
    "normalized",
    "report",
    "replay_result",
    "evaluation",
    "attempt",
)


def artifacts() -> dict[str, bytes]:
    # Opaque IO fixture: these are deliberately not semantic replay artifacts.
    return {role: json.dumps({"original_fixture_role": role}).encode() for role in ROLES}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def rewrite_manifest(root: Path, document: dict[str, object]) -> None:
    (root / "manifest.json").write_bytes(canonical(document))


def bundle_bytes(root: Path) -> dict[str, bytes]:
    """Snapshot the regular files of these owned synthetic fixtures only."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if not path.is_symlink() and path.is_file()
    }


def disappear_first_during_scan(
    monkeypatch: pytest.MonkeyPatch, content: Path, sha256: str
) -> None:
    original_scandir = os.scandir
    identity = content.stat()
    disappeared = False

    @contextmanager
    def scan(directory: int | str | os.PathLike[str]) -> Iterator[Iterator[os.DirEntry[str]]]:
        nonlocal disappeared
        with original_scandir(directory) as entries:
            observed = list(entries)
            current = os.fstat(directory) if isinstance(directory, int) else None
            if current is not None and (current.st_dev, current.st_ino) == (
                identity.st_dev,
                identity.st_ino,
            ):
                observed.sort(key=lambda entry: (entry.name != sha256, entry.name))
                if not disappeared:
                    (content / sha256).unlink()
                    disappeared = True
            yield iter(observed)

    monkeypatch.setattr(bundles.os, "scandir", scan)


def test_round_trip_determinism_and_detached_immutable_payload(tmp_path: Path) -> None:
    payload = artifacts()
    published = export_bundle(tmp_path / "first", payload)
    second = export_bundle(tmp_path / "second", payload)
    restored = read_bundle(tmp_path / "first")

    assert published == restored == second
    assert published.bundle_id == hashlib.sha256(published.manifest_bytes).hexdigest()
    assert published.artifacts == payload
    payload["raw"] = b"changed caller mapping"
    view = published.artifacts
    view["raw"] = b"changed returned mapping"
    manifest = published.manifest
    manifest["roles"]["raw"]["ref"] = "../../outside"
    assert published.artifacts == artifacts()
    assert published.manifest == restored.manifest
    with pytest.raises(FrozenInstanceError):
        published.manifest_bytes = b"{}"
    assert b"created_at" not in published.manifest_bytes
    assert str(tmp_path).encode() not in published.manifest_bytes


def test_moved_directory_remains_independently_readable(tmp_path: Path) -> None:
    original = tmp_path / "original"
    published = export_bundle(original, artifacts())
    destination = tmp_path / "new-parent" / "moved"
    destination.parent.mkdir()
    shutil.move(str(original), destination)

    assert read_bundle(destination) == published
    assert not original.exists()


def test_identical_role_content_is_physically_deduplicated(tmp_path: Path) -> None:
    payload = dict.fromkeys(ROLES, b"same immutable bytes")
    destination = tmp_path / "bundle"
    published = export_bundle(destination, payload)

    assert len(list((destination / "objects" / "sha256").iterdir())) == 1
    assert read_bundle(destination, limits=BundleLimits(max_files=2)) == published
    with pytest.raises(BundleError, match="max_files"):
        read_bundle(destination, limits=BundleLimits(max_files=1))


@pytest.mark.parametrize("contents", [None, "regular", "directory", "symlink"])
def test_existing_destination_is_never_overwritten(tmp_path: Path, contents: str | None) -> None:
    destination = tmp_path / "bundle"
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside unchanged")
    if contents == "regular":
        destination.write_bytes(b"user file")
    elif contents == "symlink":
        destination.symlink_to(outside)
    else:
        destination.mkdir()
        if contents == "directory":
            (destination / "user-file").write_bytes(b"user data")
    before = {path.name for path in tmp_path.iterdir()}

    with pytest.raises(BundleDestinationExistsError):
        export_bundle(destination, artifacts())

    assert {path.name for path in tmp_path.iterdir()} == before
    assert outside.read_bytes() == b"outside unchanged"
    if contents == "regular":
        assert destination.read_bytes() == b"user file"
    elif contents == "directory":
        assert (destination / "user-file").read_bytes() == b"user data"
    elif contents is None:
        assert list(destination.iterdir()) == []
    else:
        assert destination.is_symlink()


def test_empty_destination_created_at_commit_cannot_be_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    rename = bundles._rename_exclusive

    def insert_user_directory(parent: int, source: str, target: str) -> None:
        os.mkdir(target, dir_fd=parent)
        rename(parent, source, target)

    monkeypatch.setattr(bundles, "_rename_exclusive", insert_user_directory)
    with pytest.raises(BundleDestinationExistsError):
        export_bundle(destination, artifacts())
    assert destination.is_dir()
    assert list(destination.iterdir()) == []


def test_two_concurrent_exports_have_one_winner_without_overwrite(tmp_path: Path) -> None:
    for iteration in range(8):
        destination = tmp_path / f"bundle-{iteration}"
        barrier = Barrier(2)

        def publish(
            target: Path = destination, synchronization: Barrier = barrier
        ) -> ArtifactBundle | BundleDestinationExistsError:
            synchronization.wait()
            try:
                return export_bundle(target, artifacts())
            except BundleDestinationExistsError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: publish(), range(2)))
        assert sum(isinstance(item, ArtifactBundle) for item in outcomes) == 1
        assert sum(isinstance(item, BundleDestinationExistsError) for item in outcomes) == 1
        assert read_bundle(destination).artifacts == artifacts()
        assert not any(path.name.startswith(".tickwitness") for path in tmp_path.iterdir())


@pytest.mark.parametrize("fail_at", [2, 9])
def test_precommit_disk_full_leaves_no_target_and_retry_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    destination = tmp_path / "bundle"
    original_fsync = os.fsync
    regular_fsyncs = 0

    def disk_full(descriptor: int) -> None:
        nonlocal regular_fsyncs
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            regular_fsyncs += 1
            if regular_fsyncs == fail_at:
                raise OSError(errno.ENOSPC, "simulated full disk")
        original_fsync(descriptor)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", disk_full)
        with pytest.raises(BundleError, match="publication failed"):
            export_bundle(destination, artifacts())
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
    assert export_bundle(destination, artifacts()) == read_bundle(destination)


def test_postcommit_parent_fsync_error_preserves_complete_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    parent_inode = tmp_path.stat().st_ino
    original_fsync = os.fsync

    def unconfirmed(descriptor: int) -> None:
        info = os.fstat(descriptor)
        if stat.S_ISDIR(info.st_mode) and info.st_ino == parent_inode:
            raise OSError(errno.EIO, "parent durability unconfirmed")
        original_fsync(descriptor)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", unconfirmed)
        with pytest.raises(BundleDurabilityError, match="Complete bundle is published"):
            export_bundle(destination, artifacts())
    assert read_bundle(destination).artifacts == artifacts()
    with pytest.raises(BundleDestinationExistsError):
        export_bundle(destination, artifacts())


@pytest.mark.parametrize("invalid", [{}, {**artifacts(), "confirmation": b"secret"}])
def test_bad_roles_do_not_create_target_or_parent(
    tmp_path: Path, invalid: dict[str, bytes]
) -> None:
    destination = tmp_path / "absent-parent" / "bundle"
    with pytest.raises(BundleError, match="eight fixed"):
        export_bundle(destination, invalid)
    assert not destination.parent.exists()


@pytest.mark.parametrize("invalid", [b"", bytearray(b"mutable"), "text", None])
def test_bad_payload_types_are_rejected_before_staging(tmp_path: Path, invalid: object) -> None:
    payload = artifacts()
    payload["raw"] = invalid
    with pytest.raises(BundleError, match="immutable nonempty bytes"):
        export_bundle(tmp_path / "bundle", payload)
    assert list(tmp_path.iterdir()) == []


def test_public_bundle_constructor_cannot_wrap_mutable_or_mismatched_bytes(tmp_path: Path) -> None:
    published = export_bundle(tmp_path / "bundle", artifacts())
    with pytest.raises(BundleError):
        ArtifactBundle(bytearray(published.manifest_bytes), tuple(artifacts().items()))
    with pytest.raises(BundleError):
        ArtifactBundle(published.manifest_bytes, list(artifacts().items()))
    changed = artifacts()
    changed["raw"] = b"different"
    with pytest.raises(BundleError, match="close its manifest"):
        ArtifactBundle(published.manifest_bytes, tuple(changed.items()))
    with pytest.raises(BundleError):
        ArtifactBundle(
            published.manifest_bytes, (*tuple(artifacts().items()), ("raw", b"duplicate"))
        )


def test_missing_parent_is_not_created(tmp_path: Path) -> None:
    destination = tmp_path / "absent" / "bundle"
    with pytest.raises(BundleError, match="publication failed"):
        export_bundle(destination, artifacts())
    assert list(tmp_path.iterdir()) == []


def test_export_rejects_symlink_parent_without_writing_outside(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(BundleError):
        export_bundle(alias / "bundle", artifacts())
    assert list(outside.iterdir()) == []


def test_unsupported_rename_platform_fails_before_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bundles.sys, "platform", "unsupported-os")
    with pytest.raises(BundleError, match="unsupported"):
        export_bundle(tmp_path / "bundle", artifacts())
    assert list(tmp_path.iterdir()) == []


def test_missing_no_replace_libc_entry_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bundles.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace())
    with pytest.raises(BundleError, match="unavailable in libc"):
        export_bundle(tmp_path / "bundle", artifacts())
    assert list(tmp_path.iterdir()) == []


def test_read_missing_root_has_no_side_effect(tmp_path: Path) -> None:
    destination = tmp_path / "absent" / "bundle"
    with pytest.raises(BundleNotFoundError) as failure:
        read_bundle(destination)
    assert not isinstance(failure.value, BundleMissingObjectError)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entry", ["manifest", "object"])
def test_missing_required_entry_is_corruption_not_missing_root(tmp_path: Path, entry: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    path = destination / (
        "manifest.json" if entry == "manifest" else bundle.manifest["roles"]["raw"]["ref"]
    )
    path.unlink()
    with pytest.raises(BundleError) as failure:
        read_bundle(destination)
    assert not isinstance(failure.value, BundleNotFoundError)
    assert isinstance(failure.value, BundleMissingObjectError) == (entry == "object")


@pytest.mark.parametrize("role", ROLES)
def test_missing_declared_object_reports_manifest_role_and_preserves_fixture_copies(
    tmp_path: Path, role: str
) -> None:
    original = tmp_path / "original"
    package = export_bundle(original, artifacts())
    destination = tmp_path / "copy"
    shutil.copytree(original, destination)
    reference = package.manifest["roles"][role]
    (destination / reference["ref"]).unlink()
    original_before, copy_before = bundle_bytes(original), bundle_bytes(destination)

    with pytest.raises(BundleMissingObjectError) as failure:
        read_bundle(destination)

    assert failure.value.reason == "bundle_object_missing"
    assert failure.value.role == role
    assert failure.value.roles == (role,)
    assert failure.value.sha256 == reference["sha256"]
    assert str(destination) not in str(failure.value)
    assert bundle_bytes(original) == original_before
    assert bundle_bytes(destination) == copy_before


def test_missing_shared_object_keeps_all_fixed_aliases_sorted(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, dict.fromkeys(ROLES, b"same immutable bytes"))
    reference = package.manifest["roles"]["raw"]
    (destination / reference["ref"]).unlink()

    with pytest.raises(BundleMissingObjectError) as failure:
        read_bundle(destination)

    assert failure.value.roles == tuple(sorted(ROLES))
    assert failure.value.role == sorted(ROLES)[0]
    assert failure.value.sha256 == reference["sha256"]


def test_multiple_missing_objects_report_first_sha_not_first_role(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    roles = package.manifest["roles"]
    missing = {roles[role]["sha256"] for role in ("protocol", "raw", "evaluation")}
    for sha256 in sorted(missing, reverse=True):
        (destination / "objects" / "sha256" / sha256).unlink()

    with pytest.raises(BundleMissingObjectError) as failure:
        read_bundle(destination)

    first = min(missing)
    aliases = tuple(sorted(role for role, ref in roles.items() if ref["sha256"] == first))
    assert failure.value.sha256 == first
    assert failure.value.roles == aliases
    assert failure.value.role == aliases[0]


def test_declared_leaf_disappearing_before_stat_is_observed_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    reference = package.manifest["roles"]["raw"]
    disappear_first_during_scan(
        monkeypatch, destination / "objects" / "sha256", reference["sha256"]
    )

    with pytest.raises(BundleMissingObjectError) as failure:
        read_bundle(destination)

    assert failure.value.sha256 == reference["sha256"]
    assert failure.value.roles == ("raw",)


@pytest.mark.parametrize("unsafe", ["extra", "directory", "symlink", "fifo", "declared-directory"])
def test_scan_disappearance_cannot_hide_later_structural_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    content = destination / "objects" / "sha256"
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside unchanged")
    bad = content / ".unexpected"
    if unsafe == "extra":
        bad.write_bytes(b"extra")
    elif unsafe == "directory":
        bad.mkdir()
    elif unsafe == "symlink":
        bad.symlink_to(outside)
    elif unsafe == "fifo":
        os.mkfifo(bad)
    else:
        bad = destination / package.manifest["roles"]["protocol"]["ref"]
        bad.unlink()
        bad.mkdir()
    reference = package.manifest["roles"]["raw"]
    disappear_first_during_scan(monkeypatch, content, reference["sha256"])

    with pytest.raises(BundleError) as failure:
        read_bundle(destination)

    assert not isinstance(failure.value, BundleMissingObjectError)
    assert outside.read_bytes() == b"outside unchanged"


def test_real_unlink_between_completed_scan_and_open_reports_that_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    reference = package.manifest["roles"]["raw"]
    original_open = os.open
    removed = False

    def open_after_unlink(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal removed
        if path == reference["sha256"] and dir_fd is not None and not removed:
            (destination / reference["ref"]).unlink()
            removed = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(bundles.os, "open", open_after_unlink)
    with pytest.raises(BundleMissingObjectError) as failure:
        read_bundle(destination)

    assert removed
    assert isinstance(failure.value.__cause__, FileNotFoundError)
    assert failure.value.sha256 == reference["sha256"]
    assert failure.value.roles == ("raw",)


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EPERM, errno.ELOOP, errno.ENOTDIR])
def test_declared_object_open_errors_are_not_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    reference = package.manifest["roles"]["raw"]
    before = bundle_bytes(destination)
    original_open = os.open

    def refused_open(path, flags, mode=0o777, *, dir_fd=None):
        if path == reference["sha256"] and dir_fd is not None:
            raise OSError(error_number, "injected object-open refusal")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(bundles.os, "open", refused_open)
    with pytest.raises(BundleError) as failure:
        read_bundle(destination)

    assert not isinstance(failure.value, BundleMissingObjectError)
    assert isinstance(failure.value.__cause__, OSError)
    assert failure.value.__cause__.errno == error_number
    assert bundle_bytes(destination) == before


def test_post_open_enoent_is_not_a_missing_leaf_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    reference = package.manifest["roles"]["raw"]
    identity = (destination / reference["ref"]).stat()
    original_fstat = os.fstat

    def failed_fstat(descriptor):
        observed = original_fstat(descriptor)
        if (observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino):
            raise FileNotFoundError(errno.ENOENT, "injected failure after successful open")
        return observed

    monkeypatch.setattr(bundles.os, "fstat", failed_fstat)
    with pytest.raises(BundleError) as failure:
        read_bundle(destination)

    assert not isinstance(failure.value, BundleMissingObjectError)
    assert isinstance(failure.value.__cause__, FileNotFoundError)


def test_declared_object_changing_after_open_remains_generic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    target = destination / package.manifest["roles"]["raw"]["ref"]
    identity = target.stat()
    original_fstat = os.fstat
    changed = False

    def change_after_first_stat(descriptor):
        nonlocal changed
        observed = original_fstat(descriptor)
        if not changed and (observed.st_dev, observed.st_ino) == (
            identity.st_dev,
            identity.st_ino,
        ):
            target.write_bytes(b"changed during the read")
            os.utime(target, ns=(identity.st_atime_ns, identity.st_mtime_ns + 1_000_000))
            changed = True
        return observed

    monkeypatch.setattr(bundles.os, "fstat", change_after_first_stat)
    with pytest.raises(BundleError) as failure:
        read_bundle(destination)

    assert changed
    assert not isinstance(failure.value, BundleMissingObjectError)


@pytest.mark.parametrize("missing", ["manifest.json", "objects", "objects/sha256"])
def test_missing_manifest_or_container_never_supplies_a_declared_role(
    tmp_path: Path, missing: str
) -> None:
    destination = tmp_path / "bundle"
    export_bundle(destination, artifacts())
    target = destination / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    before = bundle_bytes(destination)

    with pytest.raises(BundleError) as failure:
        read_bundle(destination)

    assert not isinstance(failure.value, (BundleMissingObjectError, BundleNotFoundError))
    assert bundle_bytes(destination) == before


def test_invalid_manifest_cannot_authorize_missing_object_details(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    package = export_bundle(destination, artifacts())
    (destination / package.manifest["roles"]["raw"]["ref"]).unlink()
    manifest = package.manifest
    manifest["schema_version"] = 2
    rewrite_manifest(destination, manifest)

    with pytest.raises(BundleError) as failure:
        read_bundle(destination)

    assert not isinstance(failure.value, BundleMissingObjectError)


def test_generic_tree_checker_keeps_its_existing_missing_entry_failure(tmp_path: Path) -> None:
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(BundleError, match="missing a required entry") as failure:
            bundles._tree_entries(descriptor, {"missing": False})
    finally:
        os.close(descriptor)

    assert not isinstance(failure.value, BundleMissingObjectError)


@pytest.mark.parametrize("level", ["root", "objects", "sha256"])
@pytest.mark.parametrize("extra", ["file", "directory", "hidden-symlink", "fifo"])
def test_unknown_entries_of_every_type_are_rejected_without_following(
    tmp_path: Path, level: str, extra: str
) -> None:
    destination = tmp_path / "bundle"
    export_bundle(destination, artifacts())
    directory = {
        "root": destination,
        "objects": destination / "objects",
        "sha256": destination / "objects" / "sha256",
    }[level]
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    path = directory / ".unexpected"
    if extra == "file":
        path.write_bytes(b"extra")
    elif extra == "directory":
        path.mkdir()
    elif extra == "hidden-symlink":
        path.symlink_to(outside)
    else:
        os.mkfifo(path)

    with pytest.raises(BundleError) as failure:
        read_bundle(destination)
    assert not isinstance(failure.value, BundleMissingObjectError)
    assert outside.read_bytes() == b"unchanged"


@pytest.mark.parametrize("entry", ["root", "objects", "sha256", "manifest", "object"])
def test_required_symlinks_are_rejected(tmp_path: Path, entry: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    role = bundle.manifest["roles"]["raw"]
    target = {
        "root": destination,
        "objects": destination / "objects",
        "sha256": destination / "objects" / "sha256",
        "manifest": destination / "manifest.json",
        "object": destination / role["ref"],
    }[entry]
    outside = tmp_path / "external-entry"
    shutil.move(str(target), outside)
    target.symlink_to(outside, target_is_directory=outside.is_dir())

    with pytest.raises(BundleError) as failure:
        read_bundle(destination)
    assert not isinstance(failure.value, BundleMissingObjectError)


@pytest.mark.parametrize("entry", ["manifest", "object"])
def test_required_fifo_is_rejected_without_waiting_for_writer(tmp_path: Path, entry: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    path = destination / (
        "manifest.json" if entry == "manifest" else bundle.manifest["roles"]["raw"]["ref"]
    )
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(BundleError) as failure:
        read_bundle(destination)
    assert not isinstance(failure.value, BundleMissingObjectError)


@pytest.mark.parametrize("role", ROLES)
def test_tampered_role_bytes_fail_complete_closure(tmp_path: Path, role: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    path = destination / bundle.manifest["roles"][role]["ref"]
    data = path.read_bytes()
    path.write_bytes(b"!" + data[1:])
    with pytest.raises(BundleError, match="hash does not match") as failure:
        read_bundle(destination)
    assert not isinstance(failure.value, BundleMissingObjectError)


@pytest.mark.parametrize(
    "change",
    ["path", "hash", "size", "missing-role", "extra-role", "extra-field", "version", "scope"],
)
def test_manifest_injection_and_unknown_schema_are_rejected(tmp_path: Path, change: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    manifest = bundle.manifest
    if change == "path":
        manifest["roles"]["raw"]["ref"] = "../../outside"
    elif change == "hash":
        manifest["roles"]["raw"]["sha256"] = "../" + "a" * 61
    elif change == "size":
        manifest["roles"]["raw"]["size_bytes"] = True
    elif change == "missing-role":
        del manifest["roles"]["raw"]
    elif change == "extra-role":
        manifest["roles"]["confirmation"] = manifest["roles"]["raw"]
    elif change == "extra-field":
        manifest["trusted_author"] = "not a supported claim"
    elif change == "version":
        manifest["schema_version"] = True
    else:
        manifest["scope"] = "confirmation_replay"
    rewrite_manifest(destination, manifest)
    with pytest.raises(BundleError):
        read_bundle(destination)


@pytest.mark.parametrize(
    "invalid", [b"\xff", b"{}", b'{"kind":1,"kind":2}', b"\xef\xbb\xbf{}", b'{"x":NaN}']
)
def test_malformed_manifest_json_is_rejected(tmp_path: Path, invalid: bytes) -> None:
    destination = tmp_path / "bundle"
    export_bundle(destination, artifacts())
    (destination / "manifest.json").write_bytes(invalid)
    with pytest.raises(BundleError):
        read_bundle(destination)


def test_manifest_trailing_newline_is_not_canonical(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    (destination / "manifest.json").write_bytes(bundle.manifest_bytes + b"\n")
    with pytest.raises(BundleError, match="canonical"):
        read_bundle(destination)


def test_size_filecount_manifest_and_total_budgets(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    total = len(bundle.manifest_bytes) + sum(len(data) for data in artifacts().values())
    assert read_bundle(destination, limits=BundleLimits(max_total_bytes=total)) == bundle
    for limits in (
        BundleLimits(max_total_bytes=total - 1),
        BundleLimits(max_files=8),
        BundleLimits(max_manifest_bytes=len(bundle.manifest_bytes) - 1),
    ):
        with pytest.raises(BundleError):
            read_bundle(destination, limits=limits)
    raw = destination / bundle.manifest["roles"]["raw"]["ref"]
    raw.write_bytes(raw.read_bytes() + b"extra")
    with pytest.raises(BundleError, match="size"):
        read_bundle(destination)


def test_role_limit_is_applied_before_target_creation(tmp_path: Path) -> None:
    payload = artifacts()
    payload["protocol"] = b"x" * (128 * 1024 + 1)
    with pytest.raises(BundleError, match="protocol"):
        export_bundle(tmp_path / "bundle", payload)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("role", "maximum"), [("normalized", 8 * 1024 * 1024), ("replay_result", 16 * 1024 * 1024)]
)
def test_declared_role_limit_is_rejected_before_object_loading(
    tmp_path: Path, role: str, maximum: int
) -> None:
    destination = tmp_path / "bundle"
    bundle = export_bundle(destination, artifacts())
    manifest = bundle.manifest
    manifest["roles"][role]["size_bytes"] = maximum + 1
    rewrite_manifest(destination, manifest)
    with pytest.raises(BundleError, match=f"Artifact {role} exceeds"):
        read_bundle(destination)


@pytest.mark.parametrize("invalid", [0, -1, True, "64"])
def test_limits_require_positive_real_integers(invalid: object) -> None:
    with pytest.raises(BundleError):
        BundleLimits(max_total_bytes=invalid)
