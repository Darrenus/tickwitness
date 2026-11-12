"""Bounded immutable control journal for one trusted local Catalog Job.

Only configuration needs caller-owned Catalog admission. Requests use a distinct
short gate, never the Catalog/family lock, and do not open SQLite or research.
"""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import cast

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.evidence.run_records import canonical, identity
from tickwitness.domain.jobs import JobValidationError, load_job_snapshot
from tickwitness.domain.jobs.control import (
    MAX_JOB_CONTROL_BYTES,
    JobControlPolicy,
    build_job_cancel_request,
    build_job_control_result,
    build_job_publication_admission,
    control_key,
    load_job_cancel_request,
    load_job_control_policy,
    load_job_control_result,
    load_job_publication_admission,
)
from tickwitness.infrastructure.campaign_resource_guard import charge_managed_write

type Row = dict[str, object]
_NAMESPACE = ".job-controls"
_POLICY = "policy.json"
_GATE = "gate.lock"
_CANCEL = "cancel.json"
_PUBLICATION = "publication.json"
_RESULT = "result.json"
_FILES = {_POLICY, _GATE, _CANCEL, _PUBLICATION, _RESULT}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobStoreError(message)


class JobControlStore:
    """A no-follow append-only journal, not a budget or research authority."""

    def __init__(self, catalog_root: Path, job_id: str) -> None:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise JobStoreError("Job controls require POSIX no-follow IO")
        self._root = Path(catalog_root).absolute()
        self._job_id = identity(job_id)
        self._owner_pid: int | None = None
        self._owner_fd: int | None = None
        self._owner_directory: int | None = None

    @staticmethod
    def _owner(info: os.stat_result, *, directory: bool) -> None:
        _require(
            (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == os.geteuid()
            and info.st_mode & 0o022 == 0
            and (directory or info.st_nlink == 1),
            "Job controls require same-user safe directories and unaliased regular files",
        )

    @staticmethod
    @contextmanager
    def _directory(parent: int | Path, name: str | None = None) -> Iterator[int]:
        descriptor = os.open(
            parent if isinstance(parent, Path) else cast("str", name),
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=None if isinstance(parent, Path) else parent,
        )
        try:
            JobControlStore._owner(os.fstat(descriptor), directory=True)
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _mkdir(parent: int, name: str) -> bool:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            return False
        os.fsync(parent)
        return True

    @contextmanager
    def _job_directory(self, *, create: bool = False) -> Iterator[tuple[int, bool] | None]:
        try:
            with ExitStack() as stack:
                root = stack.enter_context(self._directory(self._root))
                if create:
                    self._mkdir(root, _NAMESPACE)
                try:
                    namespace = stack.enter_context(self._directory(root, _NAMESPACE))
                except FileNotFoundError:
                    if create:
                        raise
                    yield None
                    return
                created = self._mkdir(namespace, self._job_id) if create else False
                try:
                    directory = stack.enter_context(self._directory(namespace, self._job_id))
                except FileNotFoundError:
                    if create:
                        raise
                    yield None
                    return
                yield directory, created
        except OSError as error:
            raise JobStoreError("Cannot access Job control namespace: " + str(error)) from error

    @staticmethod
    @contextmanager
    def _regular(directory: int, name: str, *, write: bool = False) -> Iterator[int]:
        descriptor = os.open(
            name,
            (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        try:
            JobControlStore._owner(os.fstat(descriptor), directory=False)
            os.set_inheritable(descriptor, False)
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _read(directory: int, name: str) -> bytes:
        with JobControlStore._regular(directory, name) as descriptor:
            size = os.fstat(descriptor).st_size
            _require(0 < size <= MAX_JOB_CONTROL_BYTES, "Control record is empty or oversized")
            chunks: list[bytes] = []
            remaining = MAX_JOB_CONTROL_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            _require(len(raw) == size, "Control record changed or exceeded its read bound")
            return raw

    @staticmethod
    def _optional(directory: int, name: str) -> bytes | None:
        try:
            return JobControlStore._read(directory, name)
        except FileNotFoundError:
            return None

    @staticmethod
    def _publish(directory: int, name: str, raw: bytes) -> None:
        _require(0 < len(raw) <= MAX_JOB_CONTROL_BYTES, "Control record exceeds its bound")
        existing = JobControlStore._optional(directory, name)
        if existing is not None:
            if existing != raw:
                raise JobConflictError("Immutable Job control record already differs")
            return
        charge_managed_write(len(raw))
        temporary = ".pending-" + secrets.token_hex(16)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(
                temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False
            )
            os.fsync(directory)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)

    def _bound(self, document: Row, policy: JobControlPolicy) -> Row:
        _require(
            document["job_id"] == self._job_id and document["policy_id"] == policy.policy_id,
            "Control record differs from its immutable Job/policy binding",
        )
        return document

    def _load_policy(self, directory: int) -> JobControlPolicy:
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    _require(index < 6, "Control journal has too many entries")
                    _require(
                        entry.name in _FILES | {"workspaces"},
                        "Control journal contains an unknown entry",
                    )
                    if entry.name == "workspaces":
                        with self._directory(directory, entry.name):
                            pass
                    else:
                        with self._regular(directory, entry.name) as descriptor:
                            if entry.name == _GATE:
                                _require(
                                    os.fstat(descriptor).st_size == 0, "Control gate is not empty"
                                )
            policy = load_job_control_policy(self._read(directory, _POLICY))
            _require(policy.document["job_id"] == self._job_id, "Policy belongs to another Job")
            cancellation = self._optional(directory, _CANCEL)
            admission = self._optional(directory, _PUBLICATION)
            _require(
                cancellation is None or admission is None, "Cancellation and publication conflict"
            )
            if cancellation is not None:
                self._bound(load_job_cancel_request(cancellation), policy)
            publication = None
            if admission is not None:
                publication = self._bound(load_job_publication_admission(admission), policy)
            result = self._optional(directory, _RESULT)
            if result is not None:
                checked = self._bound(load_job_control_result(result), policy)
                _require(
                    checked["publication_admitted"] == (admission is not None),
                    "Control result admission differs",
                )
                if publication is not None:
                    _require(
                        checked["job_attempt_id"] == publication["job_attempt_id"],
                        "Control result belongs to another attempt",
                    )
                if checked["cause"] == "job_cancelled":
                    _require(
                        cancellation is not None, "Cancellation result lacks an accepted request"
                    )
            return policy
        except (ValueError, KeyError) as error:
            if isinstance(error, JobStoreError):
                raise
            raise JobStoreError("Control journal is invalid: " + str(error)) from error

    def _owned(self) -> int:
        if (
            self._owner_pid != os.getpid()
            or self._owner_fd is None
            or self._owner_directory is None
        ):
            raise JobConflictError("Job control write requires its current gate owner")
        try:
            held = os.fstat(self._owner_fd)
            with self._job_directory() as found:
                _require(found is not None, "Owned control namespace disappeared")
                directory = cast("tuple[int, bool]", found)[0]
                previous = os.fstat(self._owner_directory)
                current = os.fstat(directory)
                _require(
                    (previous.st_dev, previous.st_ino) == (current.st_dev, current.st_ino),
                    "Control directory was replaced",
                )
                with self._regular(directory, _GATE) as descriptor:
                    current = os.fstat(descriptor)
                    _require(
                        (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino),
                        "Control gate was replaced",
                    )
            return self._owner_directory
        except OSError as error:
            raise JobStoreError("Cannot verify control gate ownership: " + str(error)) from error

    @contextmanager
    def _reader(self) -> Iterator[tuple[int, JobControlPolicy] | None]:
        if self._owner_pid is not None:
            directory = self._owned()
            yield directory, self._load_policy(directory)
            return
        try:
            with self._job_directory() as found:
                if found is None:
                    yield None
                    return
                directory = found[0]
                with self._regular(directory, _GATE) as descriptor:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise JobConflictError(
                            "Job control publication is busy; retry the read"
                        ) from error
                    try:
                        yield directory, self._load_policy(directory)
                    finally:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as error:
            raise JobStoreError("Cannot read Job control journal: " + str(error)) from error

    @property
    def directory(self) -> Path:
        with self._reader() as found:
            if found is None:
                raise JobConflictError("Job control policy is not configured")
        return self._root / _NAMESPACE / self._job_id

    def policy(self) -> JobControlPolicy | None:
        with self._reader() as found:
            return None if found is None else found[1]

    def configure(self, policy: JobControlPolicy) -> Row:
        checked = load_job_control_policy(policy.canonical_bytes)
        if checked.policy_id != policy.policy_id or checked.document["job_id"] != self._job_id:
            raise JobValidationError("Configured policy must bind this exact Job")
        try:
            with self._job_directory(create=True) as found:
                _require(found is not None, "Cannot create control namespace")
                directory, created = cast("tuple[int, bool]", found)
                if created:
                    descriptor = os.open(
                        _GATE,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=directory,
                    )
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                    os.fsync(directory)
                with self._regular(directory, _GATE, write=True) as descriptor:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise JobConflictError(
                            "Another writer owns the Job control gate"
                        ) from error
                    try:
                        if not created:
                            existing = self._load_policy(directory)
                            if existing.canonical_bytes != checked.canonical_bytes:
                                raise JobConflictError(
                                    "Job control policy is already frozen differently"
                                )
                            return existing.document
                        self._publish(directory, _POLICY, checked.canonical_bytes)
                        return self._load_policy(directory).document
                    finally:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as error:
            raise JobStoreError("Cannot configure Job control policy: " + str(error)) from error

    @contextmanager
    def gate(self) -> Iterator[None]:
        if self._owner_pid is not None:
            raise JobConflictError("This control store already owns a gate")
        try:
            with self._job_directory() as found:
                if found is None:
                    raise JobConflictError("Job control policy is not configured")
                directory = found[0]
                with self._regular(directory, _GATE, write=True) as descriptor:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise JobConflictError(
                            "Another writer owns the Job control gate"
                        ) from error
                    self._owner_pid, self._owner_fd, self._owner_directory = (
                        os.getpid(),
                        descriptor,
                        directory,
                    )
                    try:
                        self._load_policy(directory)
                        yield
                    finally:
                        self._owner_pid = self._owner_fd = self._owner_directory = None
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as error:
            raise JobStoreError("Cannot access Job control gate: " + str(error)) from error

    def _record(self, name: str, loader: Callable[[bytes], Row]) -> Row | None:
        with self._reader() as found:
            if found is None:
                return None
            raw = self._optional(found[0], name)
            return None if raw is None else self._bound(loader(raw), found[1])

    def cancel_request(self) -> Row | None:
        return self._record(_CANCEL, load_job_cancel_request)

    def publication_admission(self) -> Row | None:
        return self._record(_PUBLICATION, load_job_publication_admission)

    def result(self) -> Row | None:
        return self._record(_RESULT, load_job_control_result)

    def _cancel_observation(
        self,
        policy: JobControlPolicy,
        *,
        status: str,
        request: Row | None,
        admission: Row | None,
    ) -> Row:
        return {
            "kind": "job_cancel_observation_v1",
            "schema_version": 1,
            "job_id": self._job_id,
            "policy_id": policy.policy_id,
            "status": status,
            "request": request,
            "publication_admission": admission,
        }

    def _cancel_fastpath(self, key: str, *, now_ns: int, snapshot: Row) -> Row | None:
        """Observe immutable positive records even while publication owns the gate.

        No absence is certified here. A partial read falls through to exclusive
        admission, where a live writer is a visible conflict and a broken free
        journal fails integrity validation. This never accepts a new request.
        """
        try:
            with self._job_directory() as found:
                if found is None:
                    return None
                directory = found[0]
                with self._regular(directory, _GATE) as descriptor:
                    _require(os.fstat(descriptor).st_size == 0, "Control gate is not empty")
                policy = load_job_control_policy(self._read(directory, _POLICY))
                _require(policy.document["job_id"] == self._job_id, "Policy belongs to another Job")
                build_job_cancel_request(policy, key=key, now_ns=now_ns)
                previous_raw = self._optional(directory, _CANCEL)
                admission_raw = self._optional(directory, _PUBLICATION)
                _require(
                    previous_raw is None or admission_raw is None,
                    "Cancellation and publication conflict",
                )
                previous = (
                    None
                    if previous_raw is None
                    else self._bound(load_job_cancel_request(previous_raw), policy)
                )
                admission = (
                    None
                    if admission_raw is None
                    else self._bound(load_job_publication_admission(admission_raw), policy)
                )
        except (OSError, ValueError):
            return None
        if previous is not None:
            if previous["idempotency_key"] != key:
                raise JobConflictError("Job already has a different accepted cancellation key")
            return self._cancel_observation(
                policy, status="already_requested", request=previous, admission=admission
            )
        if snapshot["state"] in {"SUCCEEDED", "FAILED", "LOST"}:
            return self._cancel_observation(
                policy, status="already_terminal", request=None, admission=admission
            )
        if admission is not None:
            return self._cancel_observation(
                policy, status="too_late", request=None, admission=admission
            )
        return None

    def request_cancel(self, key: str, *, now_ns: int, snapshot: Row) -> Row:
        selected_key = control_key(key)
        checked = load_job_snapshot(canonical(snapshot))
        if checked["job_id"] != self._job_id:
            raise JobValidationError("Cancellation snapshot belongs to another Job")
        observed = self._cancel_fastpath(selected_key, now_ns=now_ns, snapshot=checked)
        if observed is not None:
            return observed
        with self.gate():
            directory = self._owned()
            policy = self._load_policy(directory)
            candidate = build_job_cancel_request(policy, key=selected_key, now_ns=now_ns)
            request: Row | None
            previous = self.cancel_request()
            admission = self.publication_admission()
            if previous is not None:
                if previous["idempotency_key"] != selected_key:
                    raise JobConflictError("Job already has a different accepted cancellation key")
                request, status = previous, "already_requested"
            elif checked["state"] in {"SUCCEEDED", "FAILED", "LOST"}:
                request, status = None, "already_terminal"
            elif admission is not None:
                request, status = None, "too_late"
            else:
                self._publish(directory, _CANCEL, canonical(candidate))
                request, status = candidate, "accepted"
            return self._cancel_observation(
                policy, status=status, request=request, admission=admission
            )

    def admit_publication(self, job_attempt_id: str, *, now_ns: int) -> Row:
        directory = self._owned()
        policy = self._load_policy(directory)
        if self.cancel_request() is not None:
            raise JobConflictError("Accepted cancellation fences successful publication")
        if self.result() is not None:
            raise JobConflictError("A completed control result cannot admit another publication")
        admission = build_job_publication_admission(policy, job_attempt_id, now_ns=now_ns)
        previous = self.publication_admission()
        if previous is not None:
            if previous["job_attempt_id"] != job_attempt_id:
                raise JobConflictError("Publication admission belongs to another Job attempt")
            return previous
        self._publish(directory, _PUBLICATION, canonical(admission))
        return admission

    def write_result(self, document: Row) -> Row:
        checked = build_job_control_result(document)
        if self._owner_pid is None:
            with self.gate():
                return self._write_result_owned(checked)
        return self._write_result_owned(checked)

    def _write_result_owned(self, checked: Row) -> Row:
        """Perform one admitted write without redispatching the public port."""
        directory = self._owned()
        policy = self._load_policy(directory)
        self._bound(checked, policy)
        admission = self.publication_admission()
        _require(
            checked["publication_admitted"] == (admission is not None),
            "Result admission does not match the actual journal",
        )
        if admission is not None:
            _require(
                checked["job_attempt_id"] == admission["job_attempt_id"],
                "Result attempt differs from publication admission",
            )
        if checked["cause"] == "job_cancelled":
            _require(
                self.cancel_request() is not None,
                "Cancellation result requires an accepted request",
            )
        self._publish(directory, _RESULT, canonical(checked))
        return checked
