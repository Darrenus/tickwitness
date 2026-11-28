"""Missing twelve-role CAS leaves are IO facts, never semantic replay evidence."""

import builtins
import errno
import hashlib
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_evidence_bundles import artifacts as baseline_artifacts
from test_search_evidence_bundles import artifacts as search_artifacts
from test_tagged_evidence_bundles import ROLES as PAIR_ROLES
from test_tagged_evidence_bundles import artifacts
from test_tagged_finding_bundles import artifacts as finding_artifacts

from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure import evidence_bundles as shared_io
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.evidence_bundles import (
    BundleError,
    BundleLimits,
    BundleMissingObjectError,
    BundleNotFoundError,
    export_bundle,
    read_bundle,
)
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_evidence_bundles import (
    SearchEvidenceMissingObjectError,
    export_search_evidence_bundle,
    read_search_evidence_bundle,
)
from tickwitness.infrastructure.tagged_evidence_bundles import (
    TaggedPairMissingObjectError,
    export_tagged_pair_bundle,
)
from tickwitness.infrastructure.tagged_evidence_bundles import (
    read_tagged_pair_bundle as _read_tagged_pair_bundle,
)
from tickwitness.infrastructure.tagged_finding_bundles import (
    export_tagged_finding_bundle,
    read_tagged_finding_bundle,
)
from tickwitness.infrastructure.tagged_finding_registry import LocalTaggedFindingRegistry
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry


def read_tagged_pair_bundle(root, **kwargs):
    """Guard each actual read after preparation without replacing filesystem IO."""
    attempts = []
    actual_import = builtins.__import__

    def forbidden(*args, **options):
        attempts.append("database/network/worker/repository/publication/reservation")
        raise AssertionError("A pair read cannot construct runtime or write research evidence")

    def import_without_native(name, *args, **options):
        if name.startswith(
            (
                "nautilus_trader",
                "tickwitness.infrastructure._nautilus_native",
                "tickwitness.infrastructure._queue_native",
                "tickwitness.infrastructure._tagged_queue_native",
            )
        ):
            attempts.append("native:" + name)
            raise AssertionError("A pair read cannot import a native engine")
        return actual_import(name, *args, **options)

    class NoWorker(subprocess.Popen):
        def __new__(cls, *args, **options):
            return forbidden(*args, **options)

    class NoSocket(socket.socket):
        def __new__(cls, *args, **options):
            return forbidden(*args, **options)

    with pytest.MonkeyPatch.context() as patch:
        for repository in (
            LocalAttemptLedger,
            LocalExecutableProtocolRegistry,
            LocalDatasetStore,
            LocalTaggedQueueRegistry,
            LocalTaggedFindingRegistry,
        ):
            patch.setattr(repository, "__init__", forbidden)
        for owner, method in (
            (LocalAttemptLedger, "reserve"),
            (LocalAttemptLedger, "reserve_with_nonce"),
            (LocalAttemptLedger, "publish"),
            (LocalAttemptLedger, "bind_intent"),
            (LocalExecutableProtocolRegistry, "seal"),
            (LocalDatasetStore, "publish"),
            (LocalTaggedQueueRegistry, "seal"),
            (LocalTaggedFindingRegistry, "seal"),
        ):
            patch.setattr(owner, method, forbidden)
        patch.setattr(shared_io, "_write_file", forbidden)
        patch.setattr(shared_io, "_rename_exclusive", forbidden)
        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(sqlite3.dbapi2, "connect", forbidden)
        patch.setattr(subprocess, "Popen", NoWorker)
        patch.setattr(socket, "socket", NoSocket)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(socket, "socketpair", forbidden)
        patch.setattr(builtins, "__import__", import_without_native)
        try:
            return _read_tagged_pair_bundle(root, **kwargs)
        finally:
            assert attempts == [], attempts


def inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    """Read every entry without following links; scanning/reading errors propagate."""
    result = {}

    def visit(directory, prefix):
        with os.scandir(directory) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                name = prefix / entry.name
                kind = stat.S_IFMT(info.st_mode)
                payload, size = "", 0
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(
                        entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                    )
                    try:
                        opened = os.fstat(child)
                        assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
                        visit(child, name)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    child = os.open(
                        entry.name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=directory,
                    )
                    try:
                        opened = os.fstat(child)
                        assert stat.S_ISREG(opened.st_mode)
                        assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
                        with os.fdopen(child, "rb", closefd=False) as stream:
                            body = stream.read()
                        after = os.fstat(child)
                        assert (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) == (
                            after.st_size,
                            after.st_mtime_ns,
                            after.st_ctime_ns,
                        )
                        assert len(body) == after.st_size
                        size, payload = len(body), hashlib.sha256(body).hexdigest()
                    finally:
                        os.close(child)
                elif stat.S_ISLNK(info.st_mode):
                    payload = os.readlink(entry.name, dir_fd=directory)
                    size = len(os.fsencode(payload))
                else:
                    size = info.st_size
                result[name.as_posix()] = kind, size, payload

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(descriptor, Path())
    finally:
        os.close(descriptor)
    return result


def pair(root, payload=None):
    package = export_tagged_pair_bundle(root, artifacts() if payload is None else payload)
    return package


def missing_details(error, manifest, sha):
    aliases = tuple(sorted(role for role, ref in manifest["roles"].items() if ref["sha256"] == sha))
    assert isinstance(error, BundleError)
    assert not isinstance(error, BundleMissingObjectError)
    assert error.reason == "tagged_pair_object_missing"
    assert error.role == aliases[0]
    assert error.roles == aliases
    assert error.sha256 == sha


def generic(error):
    assert isinstance(error, BundleError)
    assert not isinstance(error, (TaggedPairMissingObjectError, BundleMissingObjectError))


def scan_fault(
    patch,
    content,
    target=None,
    *,
    reverse=False,
    unlink=False,
    error_number=None,
    error_type=OSError,
):
    """Control native enumeration order; unlink before the real DirEntry.stat."""
    actual_scan = os.scandir
    identity = content.stat()
    observed = {"scans": 0, "removed": False, "stats": 0}

    @contextmanager
    def scan(directory):
        with actual_scan(directory) as entries:
            rows = list(entries)
            current = os.fstat(directory) if isinstance(directory, int) else None
            if current is not None and (current.st_dev, current.st_ino) == (
                identity.st_dev,
                identity.st_ino,
            ):
                observed["scans"] += 1
                rows.sort(key=lambda row: (row.name != target, row.name), reverse=reverse)
                if unlink and not observed["removed"]:
                    (content / target).unlink()
                    observed["removed"] = True
                if error_number is not None:
                    wrapped = []
                    for entry in rows:
                        if entry.name == target:

                            def failed_stat(*, follow_symlinks):
                                assert follow_symlinks is False
                                observed["stats"] += 1
                                raise error_type(error_number, "Declared stat refusal", target)

                            wrapped.append(SimpleNamespace(name=entry.name, stat=failed_stat))
                        else:
                            wrapped.append(entry)
                    rows = wrapped
            yield iter(rows)

    patch.setattr(os, "scandir", scan)
    return observed


def test_inventory_records_names_types_bytes_links_and_special_entries_without_following(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "empty").mkdir()
    (root / "data").write_bytes(b"owned bytes")
    (root / "alias").symlink_to(tmp_path / "absent-outside")
    os.mkfifo(root / "fifo")

    assert inventory(root) == {
        "alias": (
            stat.S_IFLNK,
            len(os.fsencode(str(tmp_path / "absent-outside"))),
            str(tmp_path / "absent-outside"),
        ),
        "data": (stat.S_IFREG, len(b"owned bytes"), digest(b"owned bytes")),
        "empty": (stat.S_IFDIR, 0, ""),
        "fifo": (stat.S_IFIFO, 0, ""),
    }
    assert not (tmp_path / "absent-outside").exists()


@pytest.mark.parametrize("phase", ["scan", "stat"])
def test_inventory_propagates_errors_instead_of_omitting_entries(tmp_path, monkeypatch, phase):
    (tmp_path / "data").write_bytes(b"protected")
    with monkeypatch.context() as patch:
        if phase == "scan":

            def refused_scan(directory):
                raise PermissionError(errno.EACCES, "Declared scan refusal")

            patch.setattr(os, "scandir", refused_scan)
        else:
            scan_fault(patch, tmp_path, "data", error_number=errno.EACCES)
        with pytest.raises(PermissionError):
            inventory(tmp_path)


@pytest.mark.parametrize("role", PAIR_ROLES)
def test_each_declared_role_has_precise_absence_and_unchanged_source_and_copy(tmp_path, role):
    source, copied = tmp_path / "source", tmp_path / "copy"
    package = pair(source)
    original = inventory(source)
    shutil.copytree(source, copied)
    ref = package.manifest["roles"][role]
    (copied / ref["ref"]).unlink()
    before = inventory(copied)

    with pytest.raises(TaggedPairMissingObjectError) as caught:
        read_tagged_pair_bundle(copied)

    missing_details(caught.value, package.manifest, ref["sha256"])
    assert inventory(copied) == before
    assert inventory(source) == original


@pytest.mark.parametrize("aliases", ["all", "partial"])
def test_one_missing_object_reports_every_sorted_alias_once(tmp_path, aliases):
    payload = artifacts()
    selected = PAIR_ROLES if aliases == "all" else ("raw", "normalized", "report")
    payload.update(dict.fromkeys(selected, b"shared opaque IO bytes"))
    root = tmp_path / "bundle"
    package = pair(root, payload)
    assert read_tagged_pair_bundle(root) == package  # IO closure, not semantic verification.
    ref = package.manifest["roles"][selected[0]]
    (root / ref["ref"]).unlink()
    before = inventory(root)

    with pytest.raises(TaggedPairMissingObjectError) as caught:
        read_tagged_pair_bundle(root)

    missing_details(caught.value, package.manifest, ref["sha256"])
    assert caught.value.roles == tuple(sorted(selected))
    assert inventory(root) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_completed_scan_selects_smallest_missing_sha_independent_of_enumeration(
    tmp_path, monkeypatch, reverse
):
    root = tmp_path / "bundle"
    package = pair(root)
    roles = package.manifest["roles"]
    missing = {roles[role]["sha256"] for role in ("raw", "protocol", "assessment")}
    for sha in missing:
        (root / "objects" / "sha256" / sha).unlink()
    before = inventory(root)
    with monkeypatch.context() as patch:
        observed = scan_fault(patch, root / "objects" / "sha256", reverse=reverse)
        with pytest.raises(TaggedPairMissingObjectError) as caught:
            read_tagged_pair_bundle(root)
    assert observed["scans"] == 1
    missing_details(caught.value, package.manifest, min(missing))
    assert inventory(root) == before


def test_real_declared_unlink_before_stat_is_absence(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    package = pair(root)
    ref = package.manifest["roles"]["raw"]
    expected = inventory(root)
    del expected[ref["ref"]]
    with monkeypatch.context() as patch:
        observed = scan_fault(patch, root / "objects" / "sha256", ref["sha256"], unlink=True)
        with pytest.raises(TaggedPairMissingObjectError) as caught:
            read_tagged_pair_bundle(root)
    assert observed["removed"]
    missing_details(caught.value, package.manifest, ref["sha256"])
    assert inventory(root) == expected


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("unsafe", ["extra", "directory", "symlink", "fifo", "declared-directory"])
def test_stat_disappearance_cannot_hide_structural_faults(tmp_path, monkeypatch, reverse, unsafe):
    root = tmp_path / "bundle"
    package = pair(root)
    content = root / "objects" / "sha256"
    bad = content / ".unexpected"
    if unsafe == "declared-directory":
        bad = root / package.manifest["roles"]["protocol"]["ref"]
        bad.unlink()
        bad.mkdir()
    elif unsafe == "extra":
        bad.write_bytes(b"extra")
    elif unsafe == "directory":
        bad.mkdir()
    elif unsafe == "symlink":
        bad.symlink_to(tmp_path / "absent-outside")
    else:
        os.mkfifo(bad)
    ref = package.manifest["roles"]["raw"]
    expected = inventory(root)
    del expected[ref["ref"]]
    with monkeypatch.context() as patch:
        observed = scan_fault(patch, content, ref["sha256"], reverse=reverse, unlink=True)
        with pytest.raises(BundleError) as caught:
            read_tagged_pair_bundle(root)
    assert observed["removed"]
    generic(caught.value)
    assert inventory(root) == expected
    assert not (tmp_path / "absent-outside").exists()


def test_unknown_entry_stat_enoent_is_not_declared_leaf_absence(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    pair(root)
    content = root / "objects" / "sha256"
    (content / ".unexpected").write_bytes(b"extra")
    expected = inventory(root)
    del expected["objects/sha256/.unexpected"]
    with monkeypatch.context() as patch:
        observed = scan_fault(patch, content, ".unexpected", unlink=True)
        with pytest.raises(BundleError) as caught:
            read_tagged_pair_bundle(root)
    assert observed["removed"]
    generic(caught.value)
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert caught.value.__cause__.errno == errno.ENOENT
    assert inventory(root) == expected


def test_real_unlink_after_scan_before_open_reports_only_that_leaf(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    package = pair(root)
    ref = package.manifest["roles"]["raw"]
    expected = inventory(root)
    del expected[ref["ref"]]
    actual_open = os.open
    removed = []

    def opened(path, flags, *args, **kwargs):
        if path == ref["sha256"] and kwargs.get("dir_fd") is not None:
            assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
            (root / ref["ref"]).unlink()
            removed.append(path)
        return actual_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        with pytest.raises(TaggedPairMissingObjectError) as caught:
            read_tagged_pair_bundle(root)
    assert removed == [ref["sha256"]]
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert caught.value.__cause__.errno == errno.ENOENT
    missing_details(caught.value, package.manifest, ref["sha256"])
    assert inventory(root) == expected


@pytest.mark.parametrize("phase", ["stat", "open"])
@pytest.mark.parametrize(
    "error_number", [errno.EACCES, errno.EPERM, errno.EIO, errno.ELOOP, errno.ENOTDIR]
)
def test_other_stat_and_open_errors_remain_generic(tmp_path, monkeypatch, phase, error_number):
    root = tmp_path / "bundle"
    package = pair(root)
    ref = package.manifest["roles"]["raw"]
    before = inventory(root)
    actual_open = os.open
    observed = []

    def refused(path, flags, *args, **kwargs):
        if path == ref["sha256"] and kwargs.get("dir_fd") is not None:
            observed.append(path)
            raise OSError(error_number, "Declared leaf-open refusal")
        return actual_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        if phase == "stat":
            scanned = scan_fault(
                patch, root / "objects" / "sha256", ref["sha256"], error_number=error_number
            )
        else:
            patch.setattr(os, "open", refused)
        with pytest.raises(BundleError) as caught:
            read_tagged_pair_bundle(root)
    if phase == "stat":
        assert scanned["stats"] == 1
    else:
        assert observed == [ref["sha256"]]
    generic(caught.value)
    assert isinstance(caught.value.__cause__, OSError)
    assert caught.value.__cause__.errno == error_number
    assert inventory(root) == before


@pytest.mark.parametrize("phase", ["fstat", "read"])
def test_post_open_enoent_remains_generic_and_closes_the_actual_descriptor(
    tmp_path, monkeypatch, phase
):
    root = tmp_path / "bundle"
    package = pair(root)
    sha = package.manifest["roles"]["raw"]["sha256"]
    before = inventory(root)
    actual_open, actual_fstat, actual_fdopen = os.open, os.fstat, os.fdopen
    descriptors, injected = [], []

    def opened(path, flags, *args, **kwargs):
        descriptor = actual_open(path, flags, *args, **kwargs)
        if path == sha and kwargs.get("dir_fd") is not None:
            descriptors.append(descriptor)
        return descriptor

    def failed_read(limit):
        injected.append("read")
        raise FileNotFoundError(errno.ENOENT, "Declared failure after successful open")

    def checked_fstat(descriptor):
        if phase == "fstat" and descriptor in descriptors:
            injected.append("fstat")
            raise FileNotFoundError(errno.ENOENT, "Declared failure after successful open")
        return actual_fstat(descriptor)

    @contextmanager
    def stream(descriptor, *args, **kwargs):
        with actual_fdopen(descriptor, *args, **kwargs) as opened_stream:
            yield SimpleNamespace(read=failed_read) if descriptor in descriptors else opened_stream

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        patch.setattr(os, "fstat", checked_fstat)
        if phase == "read":
            patch.setattr(os, "fdopen", stream)
        with pytest.raises(BundleError) as caught:
            read_tagged_pair_bundle(root)
    assert injected == [phase] and len(descriptors) == 1
    generic(caught.value)
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    with pytest.raises(OSError) as closed:
        actual_fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF
    assert inventory(root) == before


@pytest.mark.parametrize("phase", ["stat", "open"])
def test_file_not_found_exception_without_enoent_stays_generic(tmp_path, monkeypatch, phase):
    root = tmp_path / "bundle"
    package = pair(root)
    sha = package.manifest["roles"]["raw"]["sha256"]
    before = inventory(root)
    actual_open = os.open
    observed = []

    def refused(path, flags, *args, **kwargs):
        if path == sha and kwargs.get("dir_fd") is not None:
            observed.append(path)
            raise FileNotFoundError(errno.EIO, "ENOENT is required, not just the exception class")
        return actual_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        if phase == "stat":
            scanned = scan_fault(
                patch,
                root / "objects" / "sha256",
                sha,
                error_number=errno.EIO,
                error_type=FileNotFoundError,
            )
        else:
            patch.setattr(os, "open", refused)
        with pytest.raises(BundleError) as caught:
            read_tagged_pair_bundle(root)
    if phase == "stat":
        assert scanned["stats"] == 1
    else:
        assert observed == [sha]
    generic(caught.value)
    assert caught.value.__cause__.errno == errno.EIO
    assert inventory(root) == before


def test_changed_read_is_generic_even_when_size_and_hash_checks_would_follow(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    package = pair(root)
    ref = package.manifest["roles"]["raw"]
    target = root / ref["ref"]
    identity = target.stat()
    changed_body = b"!" + target.read_bytes()[1:]
    expected = inventory(root)
    expected[ref["ref"]] = stat.S_IFREG, len(changed_body), digest(changed_body)
    actual_fstat = os.fstat
    changed = []

    def checked(descriptor):
        info = actual_fstat(descriptor)
        if not changed and (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
            changed.append(descriptor)
            target.write_bytes(changed_body)
            os.utime(target, ns=(identity.st_atime_ns, identity.st_mtime_ns + 1_000_000))
        return info

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", checked)
        with pytest.raises(BundleError, match="changed while being read") as caught:
            read_tagged_pair_bundle(root)
    assert changed
    generic(caught.value)
    assert inventory(root) == expected


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_unreadable_object_directory_is_not_an_absent_leaf(tmp_path, monkeypatch, error_number):
    root = tmp_path / "bundle"
    pair(root)
    identity = (root / "objects" / "sha256").stat()
    before = inventory(root)
    actual_scan = os.scandir
    observed = []

    def refused_scan(directory):
        current = os.fstat(directory)
        if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            observed.append(directory)
            raise OSError(error_number, "Declared directory scan refusal")
        return actual_scan(directory)

    with monkeypatch.context() as patch:
        patch.setattr(os, "scandir", refused_scan)
        with pytest.raises(BundleError) as caught:
            read_tagged_pair_bundle(root)
    assert len(observed) == 1
    generic(caught.value)
    assert caught.value.__cause__.errno == error_number
    assert inventory(root) == before


def test_missing_root_keeps_its_original_class_and_creates_nothing(tmp_path):
    root = tmp_path / "absent" / "bundle"
    with pytest.raises(BundleNotFoundError) as caught:
        read_tagged_pair_bundle(root)
    generic(caught.value)
    assert inventory(tmp_path) == {}


@pytest.mark.parametrize("missing", ["manifest.json", "objects", "objects/sha256"])
def test_missing_manifest_and_containers_never_authorize_role_context(tmp_path, missing):
    root = tmp_path / "bundle"
    pair(root)
    target = root / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    before = inventory(root)
    with pytest.raises(BundleError) as caught:
        read_tagged_pair_bundle(root)
    generic(caught.value)
    assert not isinstance(caught.value, BundleNotFoundError)
    assert inventory(root) == before


@pytest.mark.parametrize("damage", ["hash", "size", "symlink", "fifo", "directory"])
def test_present_damaged_or_unsafe_declared_leaf_never_reports_absence(tmp_path, damage):
    root = tmp_path / "bundle"
    package = pair(root)
    target = root / package.manifest["roles"]["raw"]["ref"]
    body = target.read_bytes()
    if damage == "hash":
        target.write_bytes(b"!" + body[1:])
    elif damage == "size":
        target.write_bytes(body + b"extra")
    else:
        target.unlink()
        if damage == "symlink":
            target.symlink_to(tmp_path / "absent-outside")
        elif damage == "fifo":
            os.mkfifo(target)
        else:
            target.mkdir()
    before = inventory(root)
    with pytest.raises(BundleError) as caught:
        read_tagged_pair_bundle(root)
    generic(caught.value)
    assert inventory(root) == before
    assert not (tmp_path / "absent-outside").exists()


@pytest.mark.parametrize(
    "damage",
    [
        "kind",
        "scope",
        "version",
        "ref",
        "bool-size",
        "alias-size",
        "unknown-role",
        "missing-role",
        "extra-field",
        "newline",
        "malformed",
        "duplicate",
        "bom",
        "role-limit",
        "manifest-limit",
        "total-limit",
        "file-limit",
    ],
)
def test_invalid_manifest_and_limits_preempt_missing_leaf_details(tmp_path, damage):
    root = tmp_path / "bundle"
    package = pair(root)
    manifest = package.manifest
    (root / manifest["roles"]["raw"]["ref"]).unlink()
    limits = BundleLimits()
    if damage == "kind":
        manifest["kind"] = "tagged_finding_evidence_bundle_v1"
    elif damage == "scope":
        manifest["scope"] = "confirmation"
    elif damage == "version":
        manifest["schema_version"] = True
    elif damage == "ref":
        manifest["roles"]["raw"]["ref"] = "../../outside"
    elif damage == "bool-size":
        manifest["roles"]["raw"]["size_bytes"] = True
    elif damage == "alias-size":
        manifest["roles"]["normalized"] = {
            **manifest["roles"]["raw"],
            "size_bytes": manifest["roles"]["raw"]["size_bytes"] + 1,
        }
    elif damage == "unknown-role":
        manifest["roles"]["finding_report"] = manifest["roles"]["raw"]
    elif damage == "missing-role":
        del manifest["roles"]["raw"]
    elif damage == "extra-field":
        manifest["authenticated"] = True
    elif damage == "role-limit":
        manifest["roles"]["raw"]["size_bytes"] = 8 * 1024 * 1024 + 1
    elif damage == "manifest-limit":
        limits = BundleLimits(max_manifest_bytes=len(package.manifest_bytes) - 1)
    elif damage == "total-limit":
        total = len(package.manifest_bytes) + sum(map(len, artifacts().values()))
        limits = BundleLimits(max_total_bytes=total - 1)
    elif damage == "file-limit":
        limits = BundleLimits(max_files=len(PAIR_ROLES))
    raw = canonical(manifest)
    if damage == "newline":
        raw += b"\n"
    elif damage == "malformed":
        raw = b"not-json"
    elif damage == "duplicate":
        raw = b'{"kind":1,"kind":2}'
    elif damage == "bom":
        raw = b"\xef\xbb\xbf" + raw
    (root / "manifest.json").write_bytes(raw)
    before = inventory(root)
    with pytest.raises(BundleError) as caught:
        read_tagged_pair_bundle(root, limits=limits)
    generic(caught.value)
    assert inventory(root) == before


@pytest.mark.parametrize("profile", ["baseline", "finding", "search"])
def test_profile_errors_remain_independent_in_both_reader_directions(tmp_path, profile):
    source, other = tmp_path / "pair", tmp_path / profile
    pair_package = pair(source)
    export, read, payload = {
        "baseline": (export_bundle, read_bundle, baseline_artifacts),
        "finding": (export_tagged_finding_bundle, read_tagged_finding_bundle, finding_artifacts),
        "search": (export_search_evidence_bundle, read_search_evidence_bundle, search_artifacts),
    }[profile]
    other_package = export(other, payload())
    before = inventory(tmp_path)
    with pytest.raises(BundleError) as wrong_pair:
        read_tagged_pair_bundle(other)
    generic(wrong_pair.value)
    with pytest.raises(BundleError) as wrong_other:
        read(source)
    generic(wrong_other.value)
    assert inventory(tmp_path) == before

    ref = other_package.manifest["roles"]["raw"]
    (other / ref["ref"]).unlink()
    before = inventory(tmp_path)
    expected = {
        "baseline": BundleMissingObjectError,
        "finding": BundleError,
        "search": SearchEvidenceMissingObjectError,
    }[profile]
    with pytest.raises(expected) as caught:
        read(other)
    assert not isinstance(caught.value, TaggedPairMissingObjectError)
    if profile == "baseline":
        assert caught.value.reason == "bundle_object_missing"
        assert str(caught.value) == (
            "Missing baseline evidence object for role(s) raw: " + ref["sha256"]
        )
        assert caught.value.roles == ("raw",)
    elif profile == "finding":
        generic(caught.value)
    else:
        assert caught.value.sha256 == ref["sha256"]
    assert inventory(tmp_path) == before
    assert read_tagged_pair_bundle(source) == pair_package


def test_generic_tree_checker_retains_its_untyped_missing_entry_error(tmp_path):
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(BundleError, match="missing a required entry") as caught:
            shared_io._tree_entries(descriptor, {"required": False})
    finally:
        os.close(descriptor)
    generic(caught.value)
