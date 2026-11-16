"""Coordinator-owned transactional jobs, separate from research evidence stores.

The worker receives no catalog handle. Paths and their parents are trusted owner
configuration; no-follow checks do not sandbox another process with owner rights.
SQLite rollback journaling avoids creating WAL/shm files during read-only queries.
"""

from __future__ import annotations

import errno
import fcntl
import os
import re
import secrets
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import cast
from urllib.parse import quote

from tickwitness.application.jobs import JobConflictError, JobNotFoundError, JobStoreError
from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse
from tickwitness.domain.jobs import (
    MAX_JOB_SNAPSHOT_BYTES,
    JobSpec,
    JobValidationError,
    assert_active_job,
    check_job_result,
    claim_job,
    finish_job,
    heartbeat_job,
    load_job_snapshot,
    load_job_spec,
    lose_job,
    queued_job,
)
from tickwitness.domain.jobs import (
    validate_followup_context as validate_job_followup_context,
)

type Row = dict[str, object]
_APPLICATION_ID = 0x54574A42
_SCHEMA_VERSION = 1
_CATALOG = "catalog.sqlite3"
_LOCK = "coordinator.lock"
_BUSY_TIMEOUT_SECONDS = 5.0
_EVENT_LIMIT = MAX_JOB_SNAPSHOT_BYTES + 16 * 1024
_TABLES = {
    "jobs": """CREATE TABLE jobs (
        job_id TEXT PRIMARY KEY NOT NULL,
        state TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version >= 1),
        snapshot_sha256 TEXT NOT NULL,
        snapshot BLOB NOT NULL,
        result BLOB
    )""",
    "job_events": """CREATE TABLE job_events (
        job_id TEXT NOT NULL REFERENCES jobs(job_id),
        version INTEGER NOT NULL CHECK (version >= 1),
        event_id TEXT NOT NULL UNIQUE,
        event BLOB NOT NULL,
        PRIMARY KEY (job_id, version)
    )""",
}
_INDEXES = {
    "one_running_job": "CREATE UNIQUE INDEX one_running_job ON jobs(state) WHERE state='RUNNING'"
}
_EVENT_STATES = {
    "JobSubmitted": "QUEUED",
    "JobClaimed": "RUNNING",
    "JobHeartbeatRecorded": "RUNNING",
    "JobSucceeded": "SUCCEEDED",
    "JobFailed": "FAILED",
    "JobLost": "LOST",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobStoreError(message)


def _sql(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().rstrip(";")


def _bytes(value: object, label: str) -> bytes:
    _require(type(value) is bytes, label + " must be a BLOB")
    return cast("bytes", value)


def _snapshot(raw: bytes) -> Row:
    try:
        return load_job_snapshot(raw)
    except ValueError as error:
        raise JobStoreError("Stored job snapshot is invalid: " + str(error)) from error


def _event(snapshot: Row, event_type: str, causation_id: str) -> Row:
    payload: Row = {
        "kind": "job_event_v1",
        "schema_version": 1,
        "event_type": event_type,
        "aggregate_id": snapshot["job_id"],
        "aggregate_version": snapshot["version"],
        "occurred_at_ns": snapshot["updated_at_ns"],
        "correlation_id": snapshot["job_id"],
        "causation_id": causation_id,
        "snapshot_sha256": digest(canonical(snapshot)),
        "snapshot": snapshot,
    }
    return {"event_id": digest(canonical(payload)), **payload}


def _load_event(raw: bytes) -> Row:
    try:
        value = parse(raw, limit=_EVENT_LIMIT)
        _require(
            value.keys()
            == {
                "event_id",
                "kind",
                "schema_version",
                "event_type",
                "aggregate_id",
                "aggregate_version",
                "occurred_at_ns",
                "correlation_id",
                "causation_id",
                "snapshot_sha256",
                "snapshot",
            },
            "Stored job event fields differ",
        )
        snapshot = _snapshot(canonical(cast("Row", value["snapshot"])))
        event_type = value["event_type"]
        _require(isinstance(event_type, str), "Stored event type must be text")
        event_type = cast("str", event_type)
        _require(event_type in _EVENT_STATES, "Stored event type is unsupported")
        _require(
            value["kind"] == "job_event_v1"
            and type(value["schema_version"]) is int
            and value["schema_version"] == 1
            and _EVENT_STATES[event_type] == snapshot["state"]
            and value["aggregate_id"] == value["correlation_id"] == snapshot["job_id"]
            and type(value["aggregate_version"]) is int
            and value["aggregate_version"] == snapshot["version"]
            and type(value["occurred_at_ns"]) is int
            and value["occurred_at_ns"] == snapshot["updated_at_ns"]
            and value["snapshot_sha256"] == digest(canonical(snapshot)),
            "Stored event does not bind its exact snapshot",
        )
        payload = dict(value)
        event_id = identity(payload.pop("event_id"))
        identity(value["causation_id"])
        _require(digest(canonical(payload)) == event_id, "Stored event identity differs")
        if event_type == "JobSubmitted":
            _require(value["aggregate_version"] == 1, "Submission event has a later version")
        elif event_type in {"JobClaimed", "JobHeartbeatRecorded"}:
            sequence = cast("Row", snapshot["attempt"])["heartbeat_sequence"]
            _require(
                (event_type == "JobClaimed") is (sequence == 0),
                "Stored running event has the wrong heartbeat boundary",
            )
        return value
    except (ValueError, TypeError, KeyError) as error:
        if isinstance(error, JobStoreError):
            raise
        raise JobStoreError("Stored job event is invalid: " + str(error)) from error


def _check_result(snapshot: Row, raw: bytes) -> str:
    try:
        spec = load_job_spec(canonical(cast("Row", snapshot["spec"])))
        return check_job_result(spec, raw)
    except (ValueError, TypeError, KeyError) as error:
        if isinstance(error, JobStoreError):
            raise
        if isinstance(error, JobValidationError):
            raise JobStoreError(str(error)) from error
        raise JobStoreError("Job result export is invalid: " + str(error)) from error


class SqliteJobStore:
    """Only an exclusive coordinator may mutate this local schema-v1 catalog."""

    @property
    def root(self) -> Path:
        """Locate optional controls without changing the Catalog's schema or identity."""
        return self._root

    def __init__(self, root: Path, *, create: bool = False) -> None:
        if type(create) is not bool or not hasattr(os, "O_NOFOLLOW"):
            raise JobStoreError("Job catalog requires a boolean create flag and POSIX no-follow IO")
        self._root = Path(root).absolute()
        self._owner: str | None = None
        self._owner_pid: int | None = None
        self._owner_fd: int | None = None
        if create:
            self._create_root()
        try:
            with self._root_fd() as root_fd:
                database = self._exists(root_fd, _CATALOG)
                lock = self._exists(root_fd, _LOCK)
                if create and not database and not lock:
                    descriptor = os.open(
                        _LOCK,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=root_fd,
                    )
                    os.fsync(descriptor)
                    os.close(descriptor)
                    os.fsync(root_fd)
                    with self.coordinator():
                        descriptor = os.open(
                            _CATALOG,
                            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600,
                            dir_fd=root_fd,
                        )
                        os.close(descriptor)
                        with self._connection(write=True, initializing=True) as connection:
                            connection.execute("BEGIN IMMEDIATE")
                            for statement in (*_TABLES.values(), *_INDEXES.values()):
                                connection.execute(statement)
                            connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                            self._commit(connection)
                        os.fsync(root_fd)
                elif not database:
                    if create and lock:
                        raise JobStoreError("Partial job catalog cannot be reset implicitly")
                    raise JobNotFoundError("Job catalog does not exist")
                elif not lock:
                    raise JobStoreError("Job catalog coordinator lock is missing")
                else:
                    with self._regular(root_fd, _LOCK):
                        pass
                    with self._regular(root_fd, _CATALOG) as descriptor:
                        self._check_header(descriptor)
        except OSError as error:
            raise JobStoreError("Cannot open job catalog: " + str(error)) from error

    def _create_root(self) -> None:
        missing: list[Path] = []
        current = self._root
        while not current.exists():
            missing.append(current)
            current = current.parent
        try:
            for path in reversed(missing):
                with suppress(FileExistsError):
                    path.mkdir(mode=0o700)
                descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError as error:
            raise JobStoreError("Cannot create job catalog root: " + str(error)) from error

    @contextmanager
    def _root_fd(self) -> Iterator[int]:
        try:
            descriptor = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError as error:
            raise JobNotFoundError("Job catalog root does not exist") from error
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _exists(root_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    @contextmanager
    def _regular(root_fd: int, name: str, *, write: bool = False) -> Iterator[int]:
        descriptor = os.open(
            name,
            (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=root_fd,
        )
        try:
            info = os.fstat(descriptor)
            _require(
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                "Job catalog files must be unaliased regular files",
            )
            yield descriptor
            after = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            _require(
                (info.st_dev, info.st_ino) == (after.st_dev, after.st_ino)
                and stat.S_ISREG(after.st_mode)
                and after.st_nlink == 1,
                "Job catalog path changed while open",
            )
        finally:
            os.close(descriptor)

    @staticmethod
    def _check_header(descriptor: int) -> None:
        header = os.pread(descriptor, 100, 0)
        _require(
            len(header) == 100 and header[:16] == b"SQLite format 3\x00",
            "Job catalog SQLite header is invalid",
        )
        _require(header[18:20] == b"\x01\x01", "WAL-mode job catalogs are unsupported")
        _require(
            int.from_bytes(header[60:64], "big") == _SCHEMA_VERSION,
            "Unsupported job catalog schema version",
        )
        _require(
            int.from_bytes(header[68:72], "big") == _APPLICATION_ID,
            "Catalog belongs to another application",
        )

    @staticmethod
    def _check_schema(connection: sqlite3.Connection) -> None:
        _require(
            connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION,
            "Unsupported job catalog schema version",
        )
        _require(
            connection.execute("PRAGMA application_id").fetchone()[0] == _APPLICATION_ID,
            "Catalog belongs to another application",
        )
        expected = {**_TABLES, **_INDEXES}
        actual = {
            name: statement
            for name, statement in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            )
        }
        _require(
            actual.keys() == expected.keys()
            and all(
                isinstance(actual[name], str) and _sql(actual[name]) == _sql(statement)
                for name, statement in expected.items()
            ),
            "Job catalog schema differs from version 1",
        )
        _require(
            connection.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok",
            "Job catalog integrity check failed",
        )
        _require(
            not connection.execute("PRAGMA foreign_key_check").fetchall(),
            "Job catalog references are inconsistent",
        )

    @contextmanager
    def _connection(
        self, *, write: bool = False, initializing: bool = False
    ) -> Iterator[sqlite3.Connection]:
        if write:
            self._ownership()
        try:
            with self._root_fd() as root_fd, self._regular(root_fd, _CATALOG) as descriptor:
                if not initializing:
                    self._check_header(descriptor)
                for suffix in ("-wal", "-shm"):
                    _require(
                        not self._exists(root_fd, _CATALOG + suffix),
                        "Unexpected job catalog WAL sidecar",
                    )
                if self._exists(root_fd, _CATALOG + "-journal"):
                    try:
                        with self._regular(root_fd, _CATALOG + "-journal"):
                            pass
                    except FileNotFoundError as error:
                        if not write and error.errno == errno.ENOENT:
                            raise JobConflictError(
                                "Job catalog read is busy; retry read"
                            ) from error
                        raise
                uri = "file:" + quote(str(self._root / _CATALOG), safe="/")
                connection = sqlite3.connect(
                    uri + ("?mode=rw" if write else "?mode=ro"),
                    uri=True,
                    isolation_level=None,
                    timeout=_BUSY_TIMEOUT_SECONDS,
                )
                try:
                    connection.execute("PRAGMA foreign_keys=ON")
                    connection.execute("PRAGMA trusted_schema=OFF")
                    if write:
                        connection.execute("PRAGMA synchronous=FULL")
                    if not initializing:
                        self._check_schema(connection)
                    yield connection
                finally:
                    connection.close()
        except (sqlite3.Error, OSError) as error:
            code = getattr(error, "sqlite_errorcode", None)
            if (
                not write
                and isinstance(error, sqlite3.Error)
                and isinstance(code, int)
                and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
            ):
                raise JobConflictError("Job catalog read is busy; retry read") from error
            raise JobStoreError(
                "Job catalog IO or publication is unconfirmed: " + str(error)
            ) from error

    @contextmanager
    def coordinator(self) -> Iterator[str]:
        if self._owner is not None:
            raise JobConflictError("This store already owns a coordinator context")
        try:
            with (
                self._root_fd() as root_fd,
                self._regular(root_fd, _LOCK, write=True) as descriptor,
            ):
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise JobConflictError("Another coordinator owns this catalog") from error
                os.set_inheritable(descriptor, False)
                self._owner, self._owner_pid, self._owner_fd = (
                    secrets.token_hex(32),
                    os.getpid(),
                    descriptor,
                )
                try:
                    yield self._owner
                finally:
                    self._owner = self._owner_pid = self._owner_fd = None
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as error:
            raise JobStoreError("Cannot access coordinator ownership: " + str(error)) from error

    def _ownership(self, coordinator_id: str | None = None) -> str:
        if self._owner is None or self._owner_pid != os.getpid() or self._owner_fd is None:
            raise JobConflictError("Job mutation requires current exclusive coordinator ownership")
        if coordinator_id is not None and coordinator_id != self._owner:
            raise JobConflictError("Coordinator epoch differs from the current owner")
        try:
            held = os.fstat(self._owner_fd)
            with self._root_fd() as root_fd, self._regular(root_fd, _LOCK) as descriptor:
                current = os.fstat(descriptor)
                _require(
                    (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino),
                    "Coordinator lock path was replaced",
                )
        except OSError as error:
            raise JobStoreError("Coordinator descriptor is invalid: " + str(error)) from error
        return self._owner

    def coordinator_active(self) -> bool:
        if self._owner is not None and self._owner_pid == os.getpid():
            self._ownership()
            return True
        try:
            with self._root_fd() as root_fd, self._regular(root_fd, _LOCK) as descriptor:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                return False
        except OSError as error:
            raise JobStoreError("Cannot inspect coordinator ownership: " + str(error)) from error

    @staticmethod
    def _stored_event(connection: sqlite3.Connection, job_id: str, version: int) -> Row:
        record = connection.execute(
            "SELECT event_id, event FROM job_events WHERE job_id=? AND version=?", (job_id, version)
        ).fetchone()
        _require(record is not None, "Job event history has a missing committed version")
        event = _load_event(_bytes(record[1], "Event"))
        _require(
            event["event_id"] == record[0]
            and event["aggregate_id"] == job_id
            and event["aggregate_version"] == version,
            "Event index differs from its bytes",
        )
        return event

    def _fetch(self, connection: sqlite3.Connection, job_id: str) -> tuple[Row, bytes | None, Row]:
        record = connection.execute(
            "SELECT state, version, snapshot_sha256, snapshot, result FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if record is None:
            raise JobNotFoundError("Managed job does not exist: " + job_id)
        raw = _bytes(record[3], "Snapshot")
        snapshot = _snapshot(raw)
        _require(
            snapshot["job_id"] == job_id
            and snapshot["state"] == record[0]
            and snapshot["version"] == record[1]
            and digest(raw) == record[2],
            "Job index differs from its exact snapshot",
        )
        result = None if record[4] is None else _bytes(record[4], "Result")
        if snapshot["state"] == "SUCCEEDED":
            _require(result is not None, "Successful job is missing its result BLOB")
            _require(
                _check_result(snapshot, cast("bytes", result)) == snapshot["result_sha256"],
                "Stored job result hash differs",
            )
        else:
            _require(result is None, "Unsuccessful job contains an unexpected result BLOB")
        version = cast("int", snapshot["version"])
        _require(
            connection.execute(
                "SELECT max(version) FROM job_events WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            == version,
            "Job event index has an unexpected later version",
        )
        event = self._stored_event(connection, job_id, version)
        _require(
            canonical(cast("Row", event["snapshot"])) == raw,
            "Latest event differs from the current snapshot",
        )
        previous_id = (
            job_id
            if version == 1
            else self._stored_event(connection, job_id, version - 1)["event_id"]
        )
        _require(event["causation_id"] == previous_id, "Latest event causation differs")
        return snapshot, result, event

    def get(self, job_id: str) -> Row:
        key = identity(job_id)
        with self._connection() as connection:
            connection.execute("BEGIN")
            return self._fetch(connection, key)[0]

    def result(self, job_id: str) -> bytes | None:
        key = identity(job_id)
        with self._connection() as connection:
            connection.execute("BEGIN")
            return self._fetch(connection, key)[1]

    def _resource_metadata(self, connection: sqlite3.Connection, job_id: str) -> Row:
        record = connection.execute(
            "SELECT state, version, snapshot_sha256, snapshot FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if record is None:
            raise JobNotFoundError("Managed job does not exist: " + job_id)
        raw = _bytes(record[3], "Snapshot")
        snapshot = _snapshot(raw)
        _require(
            snapshot["job_id"] == job_id
            and snapshot["state"] == record[0]
            and snapshot["version"] == record[1]
            and digest(raw) == record[2],
            "Job index differs from its exact snapshot",
        )
        version = cast("int", snapshot["version"])
        _require(
            connection.execute(
                "SELECT max(version) FROM job_events WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            == version,
            "Job event index has an unexpected later version",
        )
        event = self._stored_event(connection, job_id, version)
        _require(
            canonical(cast("Row", event["snapshot"])) == raw,
            "Latest event differs from the current snapshot",
        )
        previous_id = (
            job_id
            if version == 1
            else self._stored_event(connection, job_id, version - 1)["event_id"]
        )
        _require(event["causation_id"] == previous_id, "Latest event causation differs")
        return snapshot

    def resource_descriptor(self, job_id: str) -> Row:
        """Read checked Job metadata without selecting or parsing its result BLOB."""
        key = identity(job_id)
        with self._connection() as connection:
            connection.execute("BEGIN")
            return self._resource_metadata(connection, key)

    def resource_snapshot(self, job_id: str, snapshot_sha256: str) -> Row | None:
        """Resolve a report's historical binding without reconciling or new tables."""
        key, expected = identity(job_id), identity(snapshot_sha256)
        with self._connection() as connection:
            connection.execute("BEGIN")
            current = self._resource_metadata(connection, key)
            if digest(canonical(current)) == expected:
                return current
            versions = connection.execute(
                "SELECT version FROM job_events WHERE job_id=? AND "
                "json_extract(CAST(event AS TEXT),'$.snapshot_sha256')=? LIMIT 2",
                (key, expected),
            ).fetchall()
            if not versions:
                return None
            _require(len(versions) == 1, "Resource snapshot has ambiguous historical bindings")
            event = self._stored_event(connection, key, versions[0][0])
            snapshot = cast("Row", event["snapshot"])
            _require(
                digest(canonical(snapshot)) == expected,
                "Resource historical snapshot differs from its recorded hash",
            )
            return snapshot

    def events(self, job_id: str, *, limit: int = 100) -> list[Row]:
        key = identity(job_id)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise JobStoreError("Event query limit must be an integer in 1..1000")
        with self._connection() as connection:
            connection.execute("BEGIN")
            snapshot, _, _ = self._fetch(connection, key)
            versions = [
                record[0]
                for record in connection.execute(
                    "SELECT version FROM job_events WHERE job_id=? ORDER BY version DESC LIMIT ?",
                    (key, limit),
                )
            ]
            versions.reverse()
            latest = cast("int", snapshot["version"])
            _require(
                bool(versions)
                and versions[0] == latest - len(versions) + 1
                and all(version == versions[0] + index for index, version in enumerate(versions)),
                "Bounded event suffix is not contiguous",
            )
            output = [self._stored_event(connection, key, version) for version in versions]
            previous = (
                key
                if versions[0] == 1
                else self._stored_event(connection, key, versions[0] - 1)["event_id"]
            )
            for event in output:
                _require(event["causation_id"] == previous, "Event causation chain differs")
                previous = event["event_id"]
            return output

    @staticmethod
    def _commit(connection: sqlite3.Connection) -> None:
        connection.commit()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection(write=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                self._commit(connection)
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, event: Row) -> None:
        connection.execute(
            "INSERT INTO job_events(job_id,version,event_id,event) VALUES(?,?,?,?)",
            (
                event["aggregate_id"],
                event["aggregate_version"],
                event["event_id"],
                canonical(event),
            ),
        )

    def submit(self, spec: JobSpec, *, now_ns: int) -> Row:
        self._ownership()
        checked = load_job_spec(spec.canonical_bytes)
        if checked.spec_id != spec.spec_id:
            raise JobValidationError("Job specification identity differs")
        snapshot = queued_job(checked, now_ns=now_ns)
        with self._transaction() as connection:
            if spec.document["operation"] == "resolve_reduction_job_v1":
                try:
                    validate_job_followup_context(
                        spec, lambda job_id: self._fetch(connection, job_id)[0]
                    )
                except JobValidationError as error:
                    raise JobConflictError(str(error)) from error
                request = cast("Row", spec.document["request"])
                if request["mode"] == "retry_from_origin_v1":
                    # The current owner lock and this short transaction make
                    # parent-successor admission atomic within this Catalog.
                    # Shared-ledger family claims fence other Catalog copies.
                    siblings = connection.execute(
                        "SELECT job_id FROM jobs WHERE "
                        "json_extract(CAST(snapshot AS TEXT),'$.spec.operation')=? AND "
                        "json_extract(CAST(snapshot AS TEXT),'$.spec.request.mode')=? AND "
                        "json_extract(CAST(snapshot AS TEXT),'$.spec.request.parent_job_id')=? "
                        "LIMIT 2",
                        (
                            "resolve_reduction_job_v1",
                            "retry_from_origin_v1",
                            request["parent_job_id"],
                        ),
                    ).fetchall()
                    if len(siblings) > 1:
                        raise JobStoreError("Parent has conflicting retry successors in Catalog")
                    for sibling in siblings:
                        existing_child = self._fetch(connection, sibling[0])[0]
                        if (
                            existing_child["job_id"] != spec.spec_id
                            or canonical(cast("Row", existing_child["spec"]))
                            != spec.canonical_bytes
                        ):
                            raise JobConflictError("Parent already has a different retry successor")
            found = connection.execute(
                "SELECT job_id FROM jobs WHERE job_id=?", (spec.spec_id,)
            ).fetchone()
            if found is not None:
                existing = self._fetch(connection, spec.spec_id)[0]
                _require(
                    canonical(cast("Row", existing["spec"])) == spec.canonical_bytes,
                    "Existing job belongs to a different specification",
                )
                return existing
            raw = canonical(snapshot)
            connection.execute(
                "INSERT INTO jobs(job_id,state,version,snapshot_sha256,snapshot,result) "
                "VALUES(?,?,?,?,?,NULL)",
                (spec.spec_id, snapshot["state"], snapshot["version"], digest(raw), raw),
            )
            self._insert_event(connection, _event(snapshot, "JobSubmitted", spec.spec_id))
        return snapshot

    def validate_followup_context(self, job_id: str) -> tuple[Row, ...]:
        """Read child and complete bounded ancestry from one consistent Catalog view."""
        key = identity(job_id)
        with self._connection() as connection:
            connection.execute("BEGIN")
            child = self._fetch(connection, key)[0]
            spec = load_job_spec(canonical(cast("Row", child["spec"])))
            try:
                return validate_job_followup_context(
                    spec, lambda parent_id: self._fetch(connection, parent_id)[0]
                )
            except JobValidationError as error:
                raise JobConflictError(str(error)) from error

    def _change(
        self,
        job_id: str,
        expected_version: int,
        event_type: str,
        transform: Callable[[Row], Row],
        *,
        result: bytes | None = None,
    ) -> Row:
        self._ownership()
        key = identity(job_id)
        if type(expected_version) is not int or expected_version < 1:
            raise JobConflictError("Expected job version must be a positive integer")
        with self._transaction() as connection:
            snapshot, _, previous = self._fetch(connection, key)
            if snapshot["version"] != expected_version:
                raise JobConflictError("Job version changed before mutation")
            if (
                event_type == "JobClaimed"
                and connection.execute(
                    "SELECT job_id FROM jobs WHERE state='RUNNING' AND job_id<>? LIMIT 1", (key,)
                ).fetchone()
                is not None
            ):
                raise JobConflictError("Single-worker catalog already has a running job")
            try:
                updated = transform(snapshot)
            except JobValidationError as error:
                raise JobConflictError(str(error)) from error
            raw = canonical(updated)
            cursor = connection.execute(
                "UPDATE jobs SET state=?,version=?,snapshot_sha256=?,snapshot=?,result=? "
                "WHERE job_id=? AND version=?",
                (
                    updated["state"],
                    updated["version"],
                    digest(raw),
                    raw,
                    result,
                    key,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise JobConflictError("Job compare-and-swap did not update exactly one version")
            self._insert_event(
                connection, _event(updated, event_type, cast("str", previous["event_id"]))
            )
        return updated

    def claim(
        self,
        job_id: str,
        *,
        expected_version: int,
        coordinator_id: str,
        attempt_nonce: str,
        lease_token: str,
        now_ns: int,
    ) -> Row:
        self._ownership(coordinator_id)
        return self._change(
            job_id,
            expected_version,
            "JobClaimed",
            lambda row: claim_job(
                row,
                coordinator_id=coordinator_id,
                attempt_nonce=attempt_nonce,
                lease_token=lease_token,
                now_ns=now_ns,
            ),
        )

    def assert_active(
        self,
        job_id: str,
        *,
        expected_version: int,
        coordinator_id: str,
        job_attempt_id: str,
        lease_token: str,
        now_ns: int,
    ) -> Row:
        """Admit an external write under the held owner lock without renewing its lease."""
        self._ownership(coordinator_id)
        if type(expected_version) is not int or expected_version < 1:
            raise JobConflictError("Expected job version must be a positive integer")
        row = self.get(job_id)
        if row["version"] != expected_version:
            raise JobConflictError("Job version changed before external write admission")
        try:
            checked = assert_active_job(
                row,
                coordinator_id=coordinator_id,
                job_attempt_id=job_attempt_id,
                lease_token=lease_token,
                now_ns=now_ns,
            )
        except JobValidationError as error:
            raise JobConflictError(str(error)) from error
        # The read above can wait on SQLite. Never carry authority through a
        # lost/replaced owner descriptor or epoch merely because it was valid
        # before that wait; the caller separately rechecks its live clocks.
        self._ownership(coordinator_id)
        return checked

    def heartbeat(
        self,
        job_id: str,
        *,
        expected_version: int,
        coordinator_id: str,
        job_attempt_id: str,
        lease_token: str,
        sequence: int,
        now_ns: int,
    ) -> Row:
        self._ownership(coordinator_id)
        return self._change(
            job_id,
            expected_version,
            "JobHeartbeatRecorded",
            lambda row: heartbeat_job(
                row,
                coordinator_id=coordinator_id,
                job_attempt_id=job_attempt_id,
                lease_token=lease_token,
                sequence=sequence,
                now_ns=now_ns,
            ),
        )

    def complete(
        self,
        job_id: str,
        raw: bytes,
        *,
        expected_version: int,
        coordinator_id: str,
        job_attempt_id: str,
        lease_token: str,
        now_ns: int,
    ) -> Row:
        self._ownership(coordinator_id)
        # Parsing/hash/pin validation happens before the short write transaction.
        checked = self.get(job_id)
        result_sha = _check_result(checked, raw)
        return self._change(
            job_id,
            expected_version,
            "JobSucceeded",
            lambda row: finish_job(
                row,
                coordinator_id=coordinator_id,
                job_attempt_id=job_attempt_id,
                lease_token=lease_token,
                result_sha256=result_sha,
                failure=None,
                now_ns=now_ns,
            ),
            result=raw,
        )

    def fail(
        self,
        job_id: str,
        failure: Row,
        *,
        expected_version: int,
        coordinator_id: str,
        job_attempt_id: str,
        lease_token: str,
        now_ns: int,
    ) -> Row:
        self._ownership(coordinator_id)
        return self._change(
            job_id,
            expected_version,
            "JobFailed",
            lambda row: finish_job(
                row,
                coordinator_id=coordinator_id,
                job_attempt_id=job_attempt_id,
                lease_token=lease_token,
                result_sha256=None,
                failure=failure,
                now_ns=now_ns,
            ),
        )

    def mark_lost(
        self,
        job_id: str,
        *,
        expected_version: int,
        reason: str,
        now_ns: int,
    ) -> Row:
        owner = self._ownership()

        def lost(row: Row) -> Row:
            attempt = row["attempt"]
            if (
                reason == "coordinator_lost"
                and isinstance(attempt, dict)
                and attempt["coordinator_id"] == owner
            ):
                raise JobConflictError("Active owner cannot classify itself as coordinator-lost")
            return lose_job(row, reason=reason, now_ns=now_ns)

        return self._change(job_id, expected_version, "JobLost", lost)

    def reconcile_orphans(self, *, now_ns: int) -> list[Row]:
        owner = self._ownership()
        # A new exclusive owner may let SQLite recover its own rollback journal.
        # Standalone queries remain mode=ro and never repair a crashed write.
        with self._connection(write=True) as connection:
            keys = [
                record[0]
                for record in connection.execute(
                    "SELECT job_id FROM jobs WHERE state='RUNNING' ORDER BY job_id"
                )
            ]
        output = []
        for job_id in keys:
            row = self.get(job_id)
            if cast("Row", row["attempt"])["coordinator_id"] != owner:
                output.append(
                    self.mark_lost(
                        job_id,
                        expected_version=cast("int", row["version"]),
                        reason="coordinator_lost",
                        now_ns=now_ns,
                    )
                )
        return output
