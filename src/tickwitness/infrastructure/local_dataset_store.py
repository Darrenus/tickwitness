"""Publish immutable dataset evidence before exposing it in a local catalog.

The root is trusted owner configuration, not an arbitrary user-supplied path.
Files within it are checked without following symbolic links. This does not
provide isolation from a hostile owner concurrently replacing the store itself.
Only application-side processes should receive access to the catalog.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

_SCHEMA_VERSION = 1
_APPLICATION_ID = 0x54574453
_CATALOG = "catalog.sqlite3"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FORMAT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_ROLES = frozenset({"raw", "normalized", "report"})
_CREATE_TABLE = """CREATE TABLE datasets (
    dataset_id TEXT PRIMARY KEY NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    sealed INTEGER NOT NULL CHECK (sealed = 1)
)"""


class DatasetStoreError(ValueError):
    """Evidence, catalog, or filesystem state cannot safely be used."""


class DatasetNotFoundError(DatasetStoreError):
    """The catalog contains no sealed dataset with the requested identity."""


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    """Detached verified metadata; sealed does not mean replay-ready.

    The dictionaries are fresh decoded copies. Changing one cannot modify the
    stored evidence. ``created`` records catalog insertion, not CAS insertion.
    """

    dataset_id: str
    manifest: dict[str, object]
    created: bool
    report: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Directories:
    root: int
    objects: int
    manifests: int


def _require_hash(value: object) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise DatasetStoreError("Content identities must be 64 lowercase hexadecimal characters")
    return value


def _validate_json(value: object, ancestors: frozenset[int] = frozenset()) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            raise DatasetStoreError("JSON evidence cannot contain cycles")
        next_ancestors = ancestors | {id(value)}
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise DatasetStoreError("JSON object keys must be strings")
                _validate_json(item, next_ancestors)
        else:
            for item in value:
                _validate_json(item, next_ancestors)
        return
    raise DatasetStoreError("Evidence must contain only finite JSON values")


def _canonical(value: dict[str, object]) -> bytes:
    try:
        _validate_json(value)
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, UnicodeError, RecursionError) as exc:
        raise DatasetStoreError("Evidence cannot be encoded as canonical JSON") from exc


def _decode_canonical(data: bytes) -> dict[str, object]:
    try:
        value: object = json.loads(data)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DatasetStoreError("Stored evidence is not valid JSON") from exc
    if not isinstance(value, dict) or _canonical(value) != data:
        raise DatasetStoreError("Stored evidence must be a canonical JSON object")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalDatasetStore:
    """Content-addressed files plus a transactional, single-machine catalog.

    Successful publication means the entire hash-verified evidence closure was
    committed. A quality report can still mark that evidence as quarantined.
    Interrupted publications may leave unreachable objects for later cleanup.
    """

    def __init__(self, root: Path, *, create: bool = True) -> None:
        """Open an owned store, optionally initializing an absent one.

        ``create=False`` does not create a root, catalog or CAS directories. It
        controls initialization, rather than making later publication read-only.
        """
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise DatasetStoreError("This store requires no-follow directory file operations")
        if type(create) is not bool:
            raise DatasetStoreError("create must be a boolean")
        self._root = Path(root).absolute()
        try:
            if create:
                self._create_root_durably()
            with ExitStack() as stack:
                try:
                    root_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                except FileNotFoundError as exc:
                    if not create:
                        raise DatasetNotFoundError("Dataset store does not exist") from exc
                    raise
                stack.callback(os.close, root_fd)
                if not create:
                    try:
                        info = os.stat(_CATALOG, dir_fd=root_fd, follow_symlinks=False)
                    except FileNotFoundError as exc:
                        raise DatasetNotFoundError("Dataset catalog does not exist") from exc
                    if not stat.S_ISREG(info.st_mode):
                        raise DatasetStoreError("Catalog must be a regular, non-symlink file")
                # Validate ownership before creating CAS directories or changing
                # journal mode. Initialization metadata is checked in one transaction.
                with (
                    self._connection(root_fd, initialize=create, read_only=not create),
                    self._directories(create=create),
                ):
                    pass
        except (OSError, sqlite3.Error) as exc:
            raise DatasetStoreError(f"Cannot initialize dataset store: {exc}") from exc

    def _create_root_durably(self) -> None:
        """Sync new root/ancestor entries; this is not a power-loss experiment."""
        missing: list[Path] = []
        candidate = self._root
        while not candidate.exists():
            missing.append(candidate)
            candidate = candidate.parent
        for directory in reversed(missing):
            with suppress(FileExistsError):
                directory.mkdir(mode=0o700)
            with ExitStack() as stack:
                child = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, child)
                # Configured root parents are trusted, including intentional
                # parent aliases such as /tmp on macOS.
                parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
                stack.callback(os.close, parent)
                os.fsync(child)
                os.fsync(parent)

    def publish(
        self,
        raw: bytes,
        normalized: bytes,
        report: dict[str, object],
        *,
        format_id: str = "tickwitness.normalized-events.v1",
    ) -> DatasetRecord:
        """Seal bytes and a finite JSON report, then atomically expose one identity."""
        if not isinstance(raw, bytes) or not isinstance(normalized, bytes):
            raise DatasetStoreError("Raw and normalized evidence must be bytes")
        if not isinstance(report, dict):
            raise DatasetStoreError("The quality report must be a JSON object")
        self._validate_format(format_id)
        contents = {"raw": raw, "normalized": normalized, "report": _canonical(report)}
        references: dict[str, object] = {}
        for role, data in contents.items():
            content_hash = _sha256(data)
            references[role] = {
                "sha256": content_hash,
                "size_bytes": len(data),
                "ref": f"objects/sha256/{content_hash}",
            }
        manifest: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "format_id": format_id,
            "objects": references,
        }
        manifest_bytes = _canonical(manifest)
        dataset_id = _sha256(manifest_bytes)
        try:
            with self._directories() as directories:
                for data in contents.values():
                    self._publish_file(directories.objects, _sha256(data), data)
                self._publish_file(directories.manifests, f"{dataset_id}.json", manifest_bytes)
                # Re-read closure before catalog visibility, including files another
                # publisher may have installed concurrently.
                record = self._read_record(directories, dataset_id, created=False)
                with (
                    self._connection(directories.root) as connection,
                    self._transaction(connection),
                ):
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO datasets VALUES (?, ?, 1)",
                        (dataset_id, dataset_id),
                    )
                    created = cursor.rowcount == 1
                    row = connection.execute(
                        "SELECT dataset_id, manifest_sha256, sealed FROM datasets "
                        "WHERE dataset_id = ?",
                        (dataset_id,),
                    ).fetchone()
                    self._validate_row(row)
                return DatasetRecord(dataset_id, record.manifest, created, record.report)
        except (OSError, sqlite3.Error) as exc:
            raise DatasetStoreError(f"Dataset publication failed: {exc}") from exc

    def get(self, dataset_id: str) -> DatasetRecord:
        """Read only a sealed catalog entry, verifying every referenced object."""
        _require_hash(dataset_id)
        try:
            with self._directories() as directories:
                with self._connection(directories.root, read_only=True) as connection:
                    row = connection.execute(
                        "SELECT dataset_id, manifest_sha256, sealed FROM datasets "
                        "WHERE dataset_id = ?",
                        (dataset_id,),
                    ).fetchone()
                    if row is None:
                        raise DatasetNotFoundError(f"Dataset is not published: {dataset_id}")
                    self._validate_row(row)
                return self._read_record(directories, dataset_id, created=False)
        except (OSError, sqlite3.Error) as exc:
            raise DatasetStoreError(f"Cannot read dataset evidence: {exc}") from exc

    def list_datasets(self) -> tuple[DatasetRecord, ...]:
        """Return a stable identity order; fail instead of returning corrupted entries."""
        try:
            with self._directories() as directories:
                with self._connection(directories.root, read_only=True) as connection:
                    rows = connection.execute(
                        "SELECT dataset_id, manifest_sha256, sealed FROM datasets "
                        "ORDER BY dataset_id"
                    ).fetchall()
                    identities = [self._validate_row(row) for row in rows]
                return tuple(
                    self._read_record(directories, identity, created=False)
                    for identity in identities
                )
        except (OSError, sqlite3.Error) as exc:
            raise DatasetStoreError(f"Cannot list dataset evidence: {exc}") from exc

    def read_normalized(self, dataset_id: str, *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
        """Read bounded normalized-v1 bytes through a sealed, verified dataset.

        This is a content read, not replay certification. Callers enforce the
        development/confirmation policy before invoking this trusted repository.
        """
        _require_hash(dataset_id)
        if type(max_bytes) is not int or max_bytes <= 0:
            raise DatasetStoreError("max_bytes must be a positive integer")
        try:
            with self._directories() as directories:
                with self._connection(directories.root, read_only=True) as connection:
                    row = connection.execute(
                        "SELECT dataset_id, manifest_sha256, sealed FROM datasets "
                        "WHERE dataset_id = ?",
                        (dataset_id,),
                    ).fetchone()
                    if row is None:
                        raise DatasetNotFoundError(f"Dataset is not published: {dataset_id}")
                    self._validate_row(row)
                record = self._read_record(
                    directories,
                    dataset_id,
                    created=False,
                    normalized_limit=max_bytes,
                    normalized_v1=True,
                )
                references = record.manifest["objects"]
                if not isinstance(references, dict):
                    raise DatasetStoreError("Invalid normalized content references")
                reference = references["normalized"]
                if not isinstance(reference, dict) or type(reference["size_bytes"]) is not int:
                    raise DatasetStoreError("Invalid normalized content reference")
                content_hash = _require_hash(reference["sha256"])
                return self._read_verified_file(
                    directories.objects,
                    content_hash,
                    content_hash,
                    size=reference["size_bytes"],
                    max_size=max_bytes,
                )
        except (OSError, sqlite3.Error) as exc:
            raise DatasetStoreError(f"Cannot read normalized dataset evidence: {exc}") from exc

    @staticmethod
    def _validate_format(format_id: object) -> None:
        if not isinstance(format_id, str) or _FORMAT_ID.fullmatch(format_id) is None:
            raise DatasetStoreError(
                "format_id must be a non-path identifier of at most 256 characters"
            )

    @staticmethod
    def _validate_row(row: tuple[object, ...] | None) -> str:
        if row is None or len(row) != 3:
            raise DatasetStoreError("Invalid sealed catalog record")
        identity = _require_hash(row[0])
        if row[1] != identity or type(row[2]) is not int or row[2] != 1:
            raise DatasetStoreError("Catalog manifest identity or sealed state is invalid")
        return identity

    def _read_record(
        self,
        directories: _Directories,
        identity: str,
        *,
        created: bool,
        normalized_limit: int | None = None,
        normalized_v1: bool = False,
    ) -> DatasetRecord:
        manifest_bytes = self._read_verified_file(
            directories.manifests, f"{identity}.json", identity, max_size=16_384
        )
        manifest = _decode_canonical(manifest_bytes)
        if set(manifest) != {"schema_version", "format_id", "objects"}:
            raise DatasetStoreError("Unknown dataset manifest fields")
        if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
            raise DatasetStoreError("Unsupported dataset manifest schema version")
        self._validate_format(manifest["format_id"])
        if normalized_v1 and manifest["format_id"] != "tickwitness.normalized-events.v1":
            raise DatasetStoreError("Normalized reads require tickwitness.normalized-events.v1")
        references = manifest["objects"]
        if not isinstance(references, dict) or set(references) != _ROLES:
            raise DatasetStoreError("Manifest must bind raw, normalized, and report evidence")
        report: dict[str, object] = {}
        for role in sorted(_ROLES):
            reference = references[role]
            if not isinstance(reference, dict) or set(reference) != {"sha256", "size_bytes", "ref"}:
                raise DatasetStoreError("Invalid content reference fields")
            content_hash = _require_hash(reference["sha256"])
            size = reference["size_bytes"]
            if type(size) is not int or size < 0:
                raise DatasetStoreError("Content size must be a nonnegative integer")
            if role == "normalized" and normalized_limit is not None and size > normalized_limit:
                raise DatasetStoreError("Normalized evidence exceeds max_bytes")
            if reference["ref"] != f"objects/sha256/{content_hash}":
                raise DatasetStoreError(
                    "Content reference must point to its restricted CAS identity"
                )
            data = self._read_verified_file(
                directories.objects, content_hash, content_hash, size=size, retain=role == "report"
            )
            if role == "report":
                report = _decode_canonical(data)
        return DatasetRecord(identity, manifest, created, report)

    @contextmanager
    def _directories(self, *, create: bool = False) -> Iterator[_Directories]:
        with ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            objects_parent = self._open_directory(root, "objects", create=create)
            stack.callback(os.close, objects_parent)
            objects = self._open_directory(objects_parent, "sha256", create=create)
            stack.callback(os.close, objects)
            manifests = self._open_directory(root, "manifests", create=create)
            stack.callback(os.close, manifests)
            yield _Directories(root, objects, manifests)

    @staticmethod
    def _open_directory(parent: int, name: str, *, create: bool) -> int:
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            else:
                os.fsync(parent)
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)

    @staticmethod
    def _read_verified_file(
        directory: int,
        name: str,
        expected_hash: str,
        *,
        size: int | None = None,
        max_size: int | None = None,
        retain: bool = True,
        durable: bool = False,
    ) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise DatasetStoreError("Evidence objects must be regular files")
            if size is not None and info.st_size != size:
                raise DatasetStoreError("Evidence object size does not match its manifest")
            if max_size is not None and info.st_size > max_size:
                raise DatasetStoreError("Dataset manifest exceeds its schema size bound")
            hasher = hashlib.sha256()
            chunks: list[bytes] = []
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                while chunk := stream.read(1024 * 1024):
                    hasher.update(chunk)
                    if retain:
                        chunks.append(chunk)
            if hasher.hexdigest() != expected_hash:
                raise DatasetStoreError("Evidence object hash does not match its identity")
            if durable:
                os.fsync(descriptor)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _publish_file(self, directory: int, name: str, data: bytes) -> None:
        expected_hash = _sha256(data)
        try:
            self._read_verified_file(
                directory, name, expected_hash, size=len(data), retain=False, durable=True
            )
            os.fsync(directory)
            return
        except FileNotFoundError:
            pass
        temporary = f".pending-{secrets.token_hex(16)}"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode=0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Hard-link insertion is atomic and does not overwrite an existing
                # immutable object. A concurrent winner must contain identical bytes.
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            except FileExistsError:
                self._read_verified_file(
                    directory, name, expected_hash, size=len(data), retain=False, durable=True
                )
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)

    @staticmethod
    def _check_catalog_files(root: int) -> None:
        for name in (_CATALOG, f"{_CATALOG}-wal", f"{_CATALOG}-shm", f"{_CATALOG}-journal"):
            try:
                info = os.stat(name, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                raise DatasetStoreError("Catalog and sidecars must be regular, non-symlink files")

    @contextmanager
    def _connection(
        self, root: int, *, initialize: bool = False, read_only: bool = False
    ) -> Iterator[sqlite3.Connection]:
        self._check_catalog_files(root)
        try:
            before = os.stat(_CATALOG, dir_fd=root, follow_symlinks=False)
        except FileNotFoundError:
            if not initialize:
                raise
            before = None
        connection: sqlite3.Connection | None = None
        try:
            # Do not independently open/close the catalog inode: closing an
            # external descriptor can cancel another thread's SQLite POSIX locks.
            # SQLite owns all database descriptors; lstat checks reject static
            # symlinks within the trusted-owner root boundary.
            # https://sqlite.org/howtocorrupt.html#_posix_advisory_locks_canceled_by_a_separate_thread_doing_close_
            mode = "rwc" if initialize else "ro" if read_only else "rw"
            connection = sqlite3.connect(
                f"{(self._root / _CATALOG).as_uri()}?mode={mode}",
                uri=True,
                timeout=5,
                isolation_level=None,
            )
            self._check_catalog_files(root)
            after = os.stat(_CATALOG, dir_fd=root, follow_symlinks=False)
            if before is not None and (before.st_dev, before.st_ino) != (
                after.st_dev,
                after.st_ino,
            ):
                raise DatasetStoreError("Catalog identity changed during open")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA trusted_schema = OFF")
            if initialize:
                with self._transaction(connection):
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    if version == 0:
                        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
                        existing = connection.execute(
                            "SELECT 1 FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                        ).fetchone()
                        if application_id != 0 or existing is not None:
                            raise DatasetStoreError("Unversioned catalog is not an empty store")
                        # New SQLite connections default to FULL. Refuse a build
                        # with weaker defaults before the first schema write;
                        # synchronous cannot be changed inside a transaction.
                        if connection.execute("PRAGMA synchronous").fetchone()[0] < 2:
                            raise DatasetStoreError("Catalog initialization requires FULL sync")
                        connection.execute(_CREATE_TABLE)
                        connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                        connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                    self._check_schema(connection)
                self._enable_wal(connection)
                connection.execute("PRAGMA synchronous = FULL")
                os.fsync(root)
            else:
                # One read snapshot avoids mixing metadata versions. Read-only
                # opens never repair an alien catalog or switch its journal mode.
                connection.execute("BEGIN")
                try:
                    self._check_schema(connection)
                    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                        raise DatasetStoreError("Catalog requires WAL journal mode")
                finally:
                    connection.rollback()
                if not read_only:
                    connection.execute("PRAGMA synchronous = FULL")
            yield connection
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _enable_wal(connection: sqlite3.Connection) -> None:
        """Bound retries to transient WAL-switch contention, never foreign errors."""
        deadline = time.monotonic() + 5
        while True:
            try:
                if connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] != "wal":
                    raise DatasetStoreError("Catalog requires WAL journal mode")
                return
            except sqlite3.OperationalError as exc:
                primary_code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                remaining = deadline - time.monotonic()
                if (
                    primary_code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                    or remaining <= 0
                ):
                    raise
                time.sleep(min(0.01, remaining))

    @staticmethod
    def _check_schema(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
            raise DatasetStoreError("Unsupported catalog schema version")
        if connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID:
            raise DatasetStoreError("Catalog belongs to a different application")
        objects = connection.execute(
            "SELECT name, type FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        if objects != [("datasets", "table")]:
            raise DatasetStoreError("Unexpected catalog schema objects")
        columns = connection.execute("PRAGMA table_info(datasets)").fetchall()
        expected = [
            ("dataset_id", "TEXT", 1, 1),
            ("manifest_sha256", "TEXT", 1, 0),
            ("sealed", "INTEGER", 1, 0),
        ]
        if [(row[1], row[2], row[3], row[5]) for row in columns] != expected:
            raise DatasetStoreError("Unsupported catalog table schema")

    @staticmethod
    @contextmanager
    def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
