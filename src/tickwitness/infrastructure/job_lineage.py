"""Shared, append-only dispatch lineage for trusted same-user coordinators.

The family lock is held by the coordinator across original research admission,
native execution, publication and Catalog completion. Pre-upgrade coordinators
must be quiesced; these records are not a hostile-owner authenticity proof.
"""

from __future__ import annotations

import fcntl
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import cast

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.jobs.contracts import (
    MAX_FOLLOWUP_ANCESTRY,
    MAX_JOB_SPEC_BYTES,
    JobSpec,
    execution_origin_spec,
    job_dispatch_nonce,
    load_job_spec,
)
from tickwitness.infrastructure.campaign_resource_guard import charge_managed_write

type Row = dict[str, object]
_NAMESPACE = ".job-followups"
_ORIGIN = "origin.json"
_LOCK = "coordinator.lock"
_MAX_DISPATCHES = MAX_FOLLOWUP_ANCESTRY
_CLAIM_NAME = re.compile(r"[0-9a-f]{64}\.json")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobStoreError(message)


def _spec(spec: JobSpec) -> JobSpec:
    checked = load_job_spec(spec.canonical_bytes)
    _require(checked.spec_id == spec.spec_id, "Family Job identity differs from its exact bytes")
    return checked


def _origin(spec: JobSpec) -> JobSpec:
    checked = _spec(spec)
    _require(
        checked.document["kind"] == "reduction_execution_job_spec_v1",
        "A Job family requires an original native execution specification",
    )
    return checked


def checked_family_specs(origin_spec: JobSpec, specs: tuple[JobSpec, ...]) -> tuple[JobSpec, ...]:
    """Validate one bounded, ordered original-plus-retry dispatch chain."""
    origin = _origin(origin_spec)
    _require(
        type(specs) is tuple and 1 <= len(specs) <= _MAX_DISPATCHES,
        "A Job family requires one to 32 ordered dispatch specifications",
    )
    checked = tuple(_spec(spec) for spec in specs)
    _require(
        checked[0].canonical_bytes == origin.canonical_bytes,
        "Family dispatch chain does not start with its exact original Job",
    )
    identities, nonces = {origin.spec_id}, {job_dispatch_nonce(origin)}
    for parent, child in zip(checked, checked[1:], strict=False):
        request = cast("Row", child.document["request"])
        _require(
            child.document["kind"] == "reduction_followup_job_spec_v1"
            and request["mode"] == "retry_from_origin_v1"
            and request["parent_job_id"] == parent.spec_id
            and execution_origin_spec(child).canonical_bytes == origin.canonical_bytes,
            "Family dispatch is not the exact next retry of its frozen origin",
        )
        _require(child.spec_id not in identities, "Family dispatch lineage contains a cycle")
        nonce = job_dispatch_nonce(child)
        _require(nonce not in nonces, "Family dispatch nonces are not distinct")
        identities.add(child.spec_id)
        nonces.add(nonce)
    return checked


class JobFamily:
    """No-follow family journal beneath an already-existing original ledger."""

    def __init__(self, origin_spec: JobSpec) -> None:
        self._origin_spec = _origin(origin_spec)
        request = cast("Row", self.origin_spec.document["request"])
        self._root = Path(cast("str", request["runs"]))
        self._owner_pid: int | None = None
        self._owner_fd: int | None = None
        self._directory_fd: int | None = None

    @property
    def origin_spec(self) -> JobSpec:
        return self._origin_spec

    @staticmethod
    def _owner(info: os.stat_result, *, directory: bool) -> None:
        _require(
            (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == os.geteuid()
            and info.st_mode & 0o022 == 0
            and (directory or info.st_nlink == 1),
            "Family paths require same-user, unaliased regular files and safe directories",
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
            JobFamily._owner(os.fstat(descriptor), directory=True)
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _mkdir(parent: int, name: str) -> bool:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            return False
        os.fsync(parent)
        return True

    @contextmanager
    def _family_directory(self, *, create: bool) -> Iterator[tuple[int, bool] | None]:
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
            created = self._mkdir(namespace, self.origin_spec.spec_id) if create else False
            try:
                directory = stack.enter_context(
                    self._directory(namespace, self.origin_spec.spec_id)
                )
            except FileNotFoundError:
                if create:
                    raise
                yield None
                return
            yield directory, created

    @staticmethod
    @contextmanager
    def _regular(directory: int, name: str, *, write: bool = False) -> Iterator[int]:
        descriptor = os.open(
            name,
            (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        try:
            JobFamily._owner(os.fstat(descriptor), directory=False)
            os.set_inheritable(descriptor, False)
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _read(directory: int, name: str) -> bytes:
        with JobFamily._regular(directory, name) as descriptor:
            size = os.fstat(descriptor).st_size
            _require(0 < size <= MAX_JOB_SPEC_BYTES, "Family specification is empty or oversized")
            chunks: list[bytes] = []
            remaining = MAX_JOB_SPEC_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            _require(len(raw) == size, "Family specification changed or exceeded its read bound")
            return raw

    @staticmethod
    def _publish(directory: int, name: str, raw: bytes) -> None:
        _require(0 < len(raw) <= MAX_JOB_SPEC_BYTES, "Family specification exceeds its bound")
        try:
            existing = JobFamily._read(directory, name)
        except FileNotFoundError:
            pass
        else:
            _require(existing == raw, "Immutable family specification already differs")
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
                temporary,
                name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            os.fsync(directory)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)

    def _specs(self, directory: int) -> tuple[JobSpec, ...]:
        _require(
            self._read(directory, _ORIGIN) == self.origin_spec.canonical_bytes,
            "Family root seal differs from the exact original Job",
        )
        with self._regular(directory, _LOCK):
            pass
        claims: dict[str, JobSpec] = {}
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                _require(index < _MAX_DISPATCHES + 1, "Family journal has too many entries")
                name = entry.name
                if name in {_ORIGIN, _LOCK}:
                    continue
                _require(
                    _CLAIM_NAME.fullmatch(name) is not None,
                    "Family journal has an unknown entry",
                )
                try:
                    child = load_job_spec(self._read(directory, name))
                except ValueError as error:
                    raise JobStoreError(
                        "Family claim contains an invalid Job specification"
                    ) from error
                request = cast("Row", child.document["request"])
                _require(
                    child.document["kind"] == "reduction_followup_job_spec_v1"
                    and request["mode"] == "retry_from_origin_v1"
                    and request["parent_job_id"] == name[:-5],
                    "Family claim does not bind its exact parent filename",
                )
                claims[name[:-5]] = child
        chain = [self.origin_spec]
        while chain[-1].spec_id in claims:
            _require(len(chain) < _MAX_DISPATCHES, "Family dispatch chain exceeds 32 entries")
            chain.append(claims.pop(chain[-1].spec_id))
        _require(not claims, "Family journal contains an unreachable or conflicting claim")
        return checked_family_specs(self.origin_spec, tuple(chain))

    def specs(self) -> tuple[JobSpec, ...]:
        """Read origin and registered retries without creating metadata or locks."""
        try:
            with self._family_directory(create=False) as opened:
                return (self.origin_spec,) if opened is None else self._specs(opened[0])
        except OSError as error:
            raise JobStoreError("Cannot read original Job family: " + str(error)) from error

    def _ownership(self) -> int:
        if (
            self._owner_pid != os.getpid()
            or self._owner_fd is None
            or self._directory_fd is None
        ):
            raise JobConflictError("Retry claim requires current family coordinator ownership")
        held = os.fstat(self._owner_fd)
        with self._regular(self._directory_fd, _LOCK) as descriptor:
            current = os.fstat(descriptor)
            _require(
                (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino),
                "Family coordinator lock path was replaced",
            )
        return self._directory_fd

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Seal and own the shared family only after full original-source verification."""
        if self._owner_fd is not None:
            raise JobConflictError("This family already owns a coordinator context")
        # Delayed import avoids coupling the read-only journal to runtime composition.
        from tickwitness.infrastructure.job_reduction import prepare_native_job

        prepare_native_job(self.origin_spec)
        try:
            with self._family_directory(create=True) as opened:
                _require(opened is not None, "Family directory disappeared during creation")
                directory, created = cast("tuple[int, bool]", opened)
                if created:
                    descriptor = os.open(
                        _LOCK,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=directory,
                    )
                    os.fsync(descriptor)
                    os.close(descriptor)
                    os.fsync(directory)
                with self._regular(directory, _LOCK, write=True) as descriptor:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise JobConflictError(
                            "Another coordinator owns this original Job family"
                        ) from error
                    self._owner_pid, self._owner_fd, self._directory_fd = (
                        os.getpid(),
                        descriptor,
                        directory,
                    )
                    try:
                        if created:
                            self._publish(directory, _ORIGIN, self.origin_spec.canonical_bytes)
                        self._specs(directory)
                        yield
                    finally:
                        self._owner_pid = self._owner_fd = self._directory_fd = None
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as error:
            raise JobStoreError(
                "Family publication or ownership is unconfirmed: " + str(error)
            ) from error

    def claim_retry(self, spec: JobSpec) -> None:
        """Durably register one exact current-leaf retry before its research reserve."""
        try:
            directory = self._ownership()
            checked = _spec(spec)
            request = cast("Row", checked.document["request"])
            _require(
                checked.document["kind"] == "reduction_followup_job_spec_v1"
                and request["mode"] == "retry_from_origin_v1"
                and execution_origin_spec(checked).canonical_bytes
                == self.origin_spec.canonical_bytes,
                "A retry claim requires the exact original family and retry mode",
            )
            chain = self._specs(directory)
            for item in chain[1:]:
                item_request = cast("Row", item.document["request"])
                if item_request["parent_job_id"] == request["parent_job_id"]:
                    if item.canonical_bytes == checked.canonical_bytes:
                        return
                    raise JobConflictError(
                        "Original family parent already has another retry successor"
                    )
            if request["parent_job_id"] != chain[-1].spec_id:
                raise JobConflictError("Retry parent is not the current original-family leaf")
            checked_family_specs(self.origin_spec, (*chain, checked))
            self._publish(
                directory,
                cast("str", request["parent_job_id"]) + ".json",
                checked.canonical_bytes,
            )
            _require(
                self._specs(directory)[-1].canonical_bytes == checked.canonical_bytes,
                "Retry claim readback differs from its exact immutable child",
            )
        except OSError as error:
            raise JobStoreError("Retry claim publication is unconfirmed: " + str(error)) from error
