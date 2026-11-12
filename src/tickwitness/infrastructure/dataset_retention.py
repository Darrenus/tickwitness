"""Closed-store, reference-aware orphan retention; no research-payload reader."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import sqlite3
import stat
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tickwitness.domain.data_evidence.retention import (
    MAX_RETENTION_ENTRIES,
    MAX_RETENTION_OBJECT_BYTES,
    MAX_RETENTION_SCAN_BYTES,
    DatasetRetentionPlan,
    build_dataset_retention_plan,
    build_dataset_retention_result,
    load_dataset_retention_plan,
    retention_policy,
    select_candidates,
)
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.local_dataset_store import (
    DatasetStoreError,
    LocalDatasetStore,
    _decode_canonical,
)

type Row = dict[str, object]
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST = re.compile(r"([0-9a-f]{64})\.json\Z")
_SIDECARS = {"catalog.sqlite3-wal", "catalog.sqlite3-shm", "catalog.sqlite3-journal"}
_ROOT_ENTRIES = {"catalog.sqlite3", "objects", "manifests"}
_MAX_INTEGER = 2**63 - 1


class _Blocked(Exception):
    def __init__(self, diagnostic: str) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic)


@dataclass(frozen=True)
class _Opened:
    root: int
    objects_parent: int
    objects: int
    manifests: int
    identity: Row


@dataclass
class _ReadBudget:
    used: int = 0

    def charge(self, size: int) -> None:
        self.used += size
        if self.used > MAX_RETENTION_SCAN_BYTES:
            raise _Blocked("scan_limit")


def _same(left: os.stat_result, right: os.stat_result) -> bool:
    return _metadata(left) == _metadata(right)


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _safe(info: os.stat_result, *, directory: bool) -> None:
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not valid_type
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o022
        or (not directory and info.st_nlink != 1)
        or any(value < 0 or value > _MAX_INTEGER for value in _metadata(info))
    ):
        raise _Blocked("unsafe_entry")


def _identity(info: os.stat_result) -> Row:
    return {"device": info.st_dev, "inode": info.st_ino}


def _names(directory: int, *, limit: int = MAX_RETENTION_ENTRIES) -> list[str]:
    names: list[str] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > limit:
                raise _Blocked("scan_limit")
    return sorted(names)


def _root_entries(directory: int) -> None:
    entries = set(_names(directory, limit=7))
    if entries & _SIDECARS:
        raise _Blocked("sidecar_present")
    if entries - _ROOT_ENTRIES:
        raise _Blocked("unknown_entry")
    if entries != _ROOT_ENTRIES:
        raise _Blocked("store_unavailable")


def _file_row(path: str, sha: str, info: os.stat_result, *, verified: bool) -> Row:
    return {
        "path": path,
        "sha256": sha,
        "size_bytes": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "nlink": info.st_nlink,
        "content_verified": verified,
    }


def _read(
    directory: int,
    name: str,
    expected: str,
    before: os.stat_result,
    budget: _ReadBudget,
    *,
    retain: bool,
) -> bytes:
    if before.st_size + budget.used > MAX_RETENTION_SCAN_BYTES:
        raise _Blocked("scan_limit")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        opened = os.fstat(descriptor)
        _safe(opened, directory=False)
        if not _same(before, opened):
            raise _Blocked("unsafe_entry")
        hasher = hashlib.sha256()
        parts: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise _Blocked("invalid_manifest" if retain else "invalid_object")
            budget.charge(len(chunk))
            remaining -= len(chunk)
            hasher.update(chunk)
            if retain:
                parts.append(chunk)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        _safe(after, directory=False)
        _safe(named, directory=False)
        if not _same(before, after) or not _same(after, named):
            raise _Blocked("unsafe_entry")
        if hasher.hexdigest() != expected:
            raise _Blocked("invalid_manifest" if retain else "invalid_object")
        return b"".join(parts)
    finally:
        os.close(descriptor)


class LocalDatasetMaintenance:
    """Delete only a frozen, revalidated DatasetStore orphan set."""

    def __init__(self, root: Path) -> None:
        # Construction performs no IO: split/identity gates belong to the caller.
        self.root = Path(root).absolute()

    @contextmanager
    def _exclusive(self) -> Iterator[_Opened]:
        with ExitStack() as stack:
            initial = os.stat(self.root, follow_symlinks=False)
            _safe(initial, directory=True)
            root = os.open(self.root, _DIRECTORY_FLAGS)
            stack.callback(os.close, root)
            _safe(os.fstat(root), directory=True)
            if _identity(initial) != _identity(os.fstat(root)):
                raise _Blocked("unsafe_entry")
            try:
                fcntl.flock(root, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise _Blocked("maintenance_busy") from error
            stack.callback(fcntl.flock, root, fcntl.LOCK_UN)
            _root_entries(root)
            directories: dict[str, int] = {"root": root}
            for key, parent, name in (
                ("objects_parent", root, "objects"),
                ("objects", "objects_parent", "sha256"),
                ("manifests", root, "manifests"),
            ):
                parent_fd = directories[parent] if isinstance(parent, str) else parent
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                _safe(before, directory=True)
                descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
                stack.callback(os.close, descriptor)
                _safe(os.fstat(descriptor), directory=True)
                if _identity(before) != _identity(os.fstat(descriptor)):
                    raise _Blocked("unsafe_entry")
                directories[key] = descriptor
            if _names(directories["objects_parent"]) != ["sha256"]:
                raise _Blocked("unknown_entry")
            identity: Row = {
                name: _identity(os.fstat(descriptor)) for name, descriptor in directories.items()
            }
            named_root = os.stat(self.root, follow_symlinks=False)
            if _identity(named_root) != identity["root"]:
                raise _Blocked("unsafe_entry")
            yield _Opened(
                root,
                directories["objects_parent"],
                directories["objects"],
                directories["manifests"],
                identity,
            )

    def _verify_namespaces(self, opened: _Opened) -> None:
        named = os.stat(self.root, follow_symlinks=False)
        _safe(named, directory=True)
        if _identity(named) != opened.identity["root"]:
            raise _Blocked("unsafe_entry")
        for key, parent, name in (
            ("objects_parent", opened.root, "objects"),
            ("objects", opened.objects_parent, "sha256"),
            ("manifests", opened.root, "manifests"),
        ):
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _safe(info, directory=True)
            if _identity(info) != opened.identity[key]:
                raise _Blocked("unsafe_entry")
        _root_entries(opened.root)
        if _names(opened.objects_parent) != ["sha256"]:
            raise _Blocked("unknown_entry")

    def _catalog(self, opened: _Opened) -> list[Row]:
        # Do not independently open the SQLite inode: closing an extra POSIX
        # descriptor can cancel SQLite locks in another thread. All new ordinary
        # readers are excluded by the common root gate before this point.
        before = os.stat("catalog.sqlite3", dir_fd=opened.root, follow_symlinks=False)
        _safe(before, directory=False)
        _root_entries(opened.root)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                (self.root / "catalog.sqlite3").as_uri() + "?mode=ro&immutable=1",
                uri=True,
                isolation_level=None,
                timeout=0,
            )
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("BEGIN")
            LocalDatasetStore._check_schema(connection)
            rows = connection.execute(
                "SELECT dataset_id, manifest_sha256, sealed FROM datasets "
                "ORDER BY dataset_id LIMIT ?",
                (MAX_RETENTION_ENTRIES + 1,),
            ).fetchall()
            if len(rows) > MAX_RETENTION_ENTRIES:
                raise _Blocked("scan_limit")
            result: list[Row] = []
            for row in rows:
                dataset_id = LocalDatasetStore._validate_row(row)
                result.append(
                    {"dataset_id": dataset_id, "manifest_sha256": row[1], "sealed": row[2]}
                )
        except (sqlite3.Error, DatasetStoreError) as error:
            raise _Blocked("invalid_catalog") from error
        finally:
            if connection is not None:
                connection.close()
        after = os.stat("catalog.sqlite3", dir_fd=opened.root, follow_symlinks=False)
        _safe(after, directory=False)
        if not _same(before, after):
            raise _Blocked("invalid_catalog")
        _root_entries(opened.root)
        return result

    @staticmethod
    def _references(raw: bytes) -> dict[str, int]:
        try:
            manifest = _decode_canonical(raw)
            if (
                set(manifest) != {"schema_version", "format_id", "objects"}
                or type(manifest["schema_version"]) is not int
                or manifest["schema_version"] != 1
            ):
                raise _Blocked("invalid_manifest")
            LocalDatasetStore._validate_format(manifest["format_id"])
            roles = manifest["objects"]
            if not isinstance(roles, dict) or set(roles) != {"raw", "normalized", "report"}:
                raise _Blocked("invalid_manifest")
            references: dict[str, int] = {}
            for value in roles.values():
                if not isinstance(value, dict) or set(value) != {"sha256", "size_bytes", "ref"}:
                    raise _Blocked("invalid_manifest")
                sha, size = value["sha256"], value["size_bytes"]
                if (
                    not isinstance(sha, str)
                    or _HASH.fullmatch(sha) is None
                    or type(size) is not int
                    or size < 0
                    or size > _MAX_INTEGER
                    or value["ref"] != "objects/sha256/" + sha
                    or (sha in references and references[sha] != size)
                ):
                    raise _Blocked("invalid_manifest")
                references[sha] = size
            return references
        except DatasetStoreError as error:
            raise _Blocked("invalid_manifest") from error

    def _snapshot(self, opened: _Opened, policy: Row, observed_at_ns: int) -> DatasetRetentionPlan:
        budget = _ReadBudget()
        object_names, manifest_names = _names(opened.objects), _names(opened.manifests)
        if len(object_names) + len(manifest_names) > MAX_RETENTION_ENTRIES:
            raise _Blocked("scan_limit")
        objects: dict[str, os.stat_result] = {}
        for name in object_names:
            if _HASH.fullmatch(name) is None:
                raise _Blocked("unknown_entry")
            info = os.stat(name, dir_fd=opened.objects, follow_symlinks=False)
            _safe(info, directory=False)
            if info.st_size > MAX_RETENTION_OBJECT_BYTES:
                raise _Blocked("scan_limit")
            objects[name] = info
        catalog = self._catalog(opened)
        manifests: list[str] = []
        protected: set[str] = set()
        files: list[Row] = []
        for name in manifest_names:
            match = _MANIFEST.fullmatch(name)
            if match is None:
                raise _Blocked("unknown_entry")
            sha = match.group(1)
            info = os.stat(name, dir_fd=opened.manifests, follow_symlinks=False)
            _safe(info, directory=False)
            if info.st_size > 16_384:
                raise _Blocked("invalid_manifest")
            raw = _read(opened.manifests, name, sha, info, budget, retain=True)
            for object_id, size in self._references(raw).items():
                if object_id not in objects:
                    raise _Blocked("missing_reference")
                if objects[object_id].st_size != size:
                    raise _Blocked("invalid_object")
                protected.add(object_id)
            manifests.append(sha)
            files.append(_file_row("manifests/" + name, sha, info, verified=True))
        manifest_ids = set(manifests)
        if any(row["dataset_id"] not in manifest_ids for row in catalog):
            raise _Blocked("missing_reference")
        for sha, info in objects.items():
            if sha not in protected:
                _read(opened.objects, sha, sha, info, budget, retain=False)
            files.append(
                _file_row("objects/sha256/" + sha, sha, info, verified=sha not in protected)
            )
        files.sort(key=lambda row: cast("str", row["path"]))
        protected_ids = sorted(protected)
        self._verify_namespaces(opened)
        return build_dataset_retention_plan(
            {
                "kind": "dataset_retention_plan_v1",
                "schema_version": 1,
                "status": "READY",
                "policy": policy,
                "observed_at_ns": observed_at_ns,
                "store": opened.identity,
                "reference_sha256": digest(canonical({"catalog": catalog, "manifests": manifests})),
                "files": files,
                "protected_objects": protected_ids,
                "candidates": select_candidates(files, protected_ids, observed_at_ns, policy),
                "diagnostics": [],
            }
        )

    def plan(self, min_age_seconds: int = 86400) -> DatasetRetentionPlan:
        policy = retention_policy(min_age_seconds)
        observed_at_ns = time.time_ns()
        diagnostic: str
        try:
            with self._exclusive() as opened:
                return self._snapshot(opened, policy, observed_at_ns)
        except _Blocked as error:
            diagnostic = error.diagnostic
        except OSError:
            diagnostic = "store_unavailable"
        return build_dataset_retention_plan(
            {
                "kind": "dataset_retention_plan_v1",
                "schema_version": 1,
                "status": "BLOCKED",
                "policy": policy,
                "observed_at_ns": observed_at_ns,
                "store": None,
                "reference_sha256": None,
                "files": [],
                "protected_objects": [],
                "candidates": [],
                "diagnostics": [diagnostic],
            }
        )

    def apply(self, plan: DatasetRetentionPlan) -> Row:
        checked = load_dataset_retention_plan(plan.canonical_bytes)
        if checked.plan_id != plan.plan_id:
            raise ValueError("Retention plan identity differs from its exact canonical bytes")
        document = checked.document
        intended = cast("list[str]", document["candidates"])
        unlinked: list[str] = []
        absent: list[str] = []
        removed = 0

        def result(status: str, diagnostic: str | None) -> Row:
            return build_dataset_retention_result(
                {
                    "kind": "dataset_retention_result_v1",
                    "schema_version": 1,
                    "plan_id": checked.plan_id,
                    "status": status,
                    "intended": intended,
                    "unlinked": unlinked,
                    "already_absent": absent,
                    "removed_logical_bytes": removed,
                    "diagnostic": diagnostic,
                },
                plan=checked,
            )

        if document["status"] != "READY":
            return result("REFUSED", "blocked_plan")
        try:
            with self._exclusive() as opened:
                current = self._snapshot(
                    opened,
                    cast("Row", document["policy"]),
                    cast("int", document["observed_at_ns"]),
                )
                actual = current.document
                present = {cast("str", row["path"]) for row in cast("list[Row]", actual["files"])}
                absent = [sha for sha in intended if "objects/sha256/" + sha not in present]
                absent_paths = {"objects/sha256/" + sha for sha in absent}
                projected = dict(document)
                projected["files"] = [
                    row
                    for row in cast("list[Row]", document["files"])
                    if row["path"] not in absent_paths
                ]
                projected["candidates"] = [sha for sha in intended if sha not in absent]
                expected = build_dataset_retention_plan(projected)
                if current.canonical_bytes != expected.canonical_bytes:
                    absent = []
                    return result("REFUSED", "snapshot_changed")
                sizes = {
                    cast("str", row["sha256"]): cast("int", row["size_bytes"])
                    for row in cast("list[Row]", document["files"])
                    if cast("str", row["path"]).startswith("objects/sha256/")
                }
                failed = False
                for sha in intended:
                    if sha in absent:
                        continue
                    try:
                        os.unlink(sha, dir_fd=opened.objects)
                    except OSError:
                        failed = True
                        break
                    unlinked.append(sha)
                    removed += sizes[sha]
                try:
                    os.fsync(opened.objects)
                except OSError:
                    return result("IO_UNCONFIRMED", "fsync_unconfirmed")
                if failed:
                    return result("PARTIAL", "unlink_failed")
                return result("APPLIED", None)
        except _Blocked as error:
            diagnostic = (
                error.diagnostic if error.diagnostic == "maintenance_busy" else "snapshot_changed"
            )
            return result("REFUSED", diagnostic)
        except OSError:
            return result("IO_UNCONFIRMED" if unlinked else "REFUSED", "store_unavailable")
