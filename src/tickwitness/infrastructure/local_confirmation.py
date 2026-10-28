"""One managed store's immutable declarations and irreversible exposure history.

The fixed root anchor detects accidental loss of the whole state directory.
Exposure publication keeps an uncertainty marker until the complete append-only
logical document is durable. Any abandoned marker fails closed; this module has
no repair, refund or reset operation. Trusted owners can still replace a store
or falsify origin labels; this is not global history certification.
"""

from __future__ import annotations

import fcntl
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import cast

from tickwitness.domain.evidence.run_records import canonical, parse
from tickwitness.domain.research_contracts.confirmation import (
    MAX_CONFIRMATION_EXPOSURE_BYTES,
    MAX_CONFIRMATION_PROTOCOL_BYTES,
    ConfirmationAlreadyExposed,
    ConfirmationExposure,
    ConfirmationProtocol,
    OriginFootprint,
    build_confirmation_exposure,
    footprints_overlap,
    load_confirmation_exposure,
    load_confirmation_protocol,
    load_origin_footprint,
)
from tickwitness.infrastructure.evidence_bundles import (
    BundleError,
    _directory,
    _read_file,
    _rename_exclusive,
    _rename_operation,
    _write_file,
)

MAX_EXPOSURE_RECORDS = 256
MAX_EXPOSURE_LEDGER_BYTES = 32 * 1024 * 1024
_MUTEX = RLock()
_STATE = "confirmation-state"
_ANCHOR_NAME = ".confirmation-state-initialized"
_ANCHOR = canonical({"kind": "confirmation_state_anchor_v1", "schema_version": 1})
_PENDING = ".pending-exposure"
_NEXT = ".exposure-next"
_INITIALIZING = ".initializing"
_UNCERTAIN = b"confirmation state publication is incomplete or uncertain\n"


class ConfirmationStoreError(ValueError):
    """Managed confirmation history is unsafe, corrupt or unavailable."""


class ConfirmationNotFoundError(ConfirmationStoreError):
    """A confirmation declaration, or the never-initialized store, is absent."""


def _identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ConfirmationStoreError("Protocol ID requires 64 lowercase hexadecimal characters")
    return value


def _protocol(raw: bytes) -> ConfirmationProtocol:
    try:
        return load_confirmation_protocol(raw)
    except ValueError as error:
        raise ConfirmationStoreError(f"Invalid confirmation protocol: {error}") from error


def _footprint(exposure: ConfirmationExposure | ConfirmationProtocol) -> OriginFootprint:
    return load_origin_footprint(
        canonical(cast("dict[str, object]", exposure.document["origin_footprint"]))
    )


def _log_bytes(entries: tuple[ConfirmationExposure, ...]) -> bytes:
    return canonical(
        {
            "kind": "confirmation_exposure_ledger_v1",
            "schema_version": 1,
            "exposures": [entry.document for entry in entries],
        }
    )


def _load_log(raw: bytes) -> tuple[ConfirmationExposure, ...]:
    document = parse(raw, limit=MAX_EXPOSURE_LEDGER_BYTES)
    if (
        set(document) != {"kind", "schema_version", "exposures"}
        or document["kind"] != "confirmation_exposure_ledger_v1"
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
    ):
        raise ConfirmationStoreError("Unsupported confirmation exposure ledger document")
    values = document["exposures"]
    if type(values) is not list or len(values) > MAX_EXPOSURE_RECORDS:
        raise ConfirmationStoreError("Exposure ledger exceeds its 256 record limit")
    entries: list[ConfirmationExposure] = []
    for value in cast("list[object]", values):
        if not isinstance(value, dict):
            raise ConfirmationStoreError("Exposure ledger requires complete exposure objects")
        data = canonical(cast("dict[str, object]", value))
        if len(data) > MAX_CONFIRMATION_EXPOSURE_BYTES:
            raise ConfirmationStoreError("Exposure record exceeds its byte limit")
        entries.append(load_confirmation_exposure(data))
    identities = [entry.exposure_id for entry in entries]
    if identities != sorted(set(identities)):
        raise ConfirmationStoreError("Exposure records must have sorted unique identities")
    _verify_history(tuple(entries))
    return tuple(entries)


def _verify_history(entries: tuple[ConfirmationExposure, ...]) -> None:
    """Check API nonoverlap in one bounded inventory, without quadratic reparsing."""
    trades: set[tuple[str, str, str, str]] = set()
    books: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    for entry in entries:
        footprint = cast("dict[str, object]", entry.document["origin_footprint"])
        for row in cast("list[dict[str, object]]", footprint["streams"]):
            stream = (
                cast("str", row["source"]),
                cast("str", row["instrument"]),
                cast("str", row["session"]),
            )
            for trade in cast("list[str]", row["trade_ids"]):
                identity = (*stream, trade)
                if identity in trades:
                    raise ConfirmationStoreError("Committed exposure origins overlap")
                trades.add(identity)
            books.setdefault(stream, []).extend(
                (first, last) for first, last in cast("list[list[int]]", row["book_intervals"])
            )
    for intervals in books.values():
        previous_last = -1
        for first, last in sorted(intervals):
            if first <= previous_last:
                raise ConfirmationStoreError("Committed exposure origins overlap")
            previous_last = last


def _exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _same_file(directory: int, name: str, descriptor: int) -> None:
    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
    opened = os.fstat(descriptor)
    if (current.st_dev, current.st_ino, current.st_mode) != (
        opened.st_dev,
        opened.st_ino,
        opened.st_mode,
    ):
        raise ConfirmationStoreError("Managed confirmation path changed while open")


def _check_state(directory: int) -> None:
    expected = {"protocols": True, "exposures.json": False, ".lock": False}
    seen: set[str] = set()
    with os.scandir(directory) as children:
        for child in children:
            if child.name in {_PENDING, _NEXT, _INITIALIZING}:
                raise ConfirmationStoreError("Confirmation commit is incomplete or uncertain")
            if child.name not in expected:
                raise ConfirmationStoreError("Unknown confirmation state entry")
            info = child.stat(follow_symlinks=False)
            if (
                stat.S_ISLNK(info.st_mode)
                or stat.S_ISDIR(info.st_mode) != expected[child.name]
                or (not expected[child.name] and not stat.S_ISREG(info.st_mode))
            ):
                raise ConfirmationStoreError("Confirmation state entry has an unsafe file type")
            seen.add(child.name)
    if seen != set(expected):
        raise ConfirmationStoreError("Confirmation state is missing a required entry")


def _retain_uncertainty(directory: int, name: str) -> None:
    """Best effort after IO failure, never remove a committed ledger or anchor."""
    with suppress(OSError, BundleError):
        if not _exists(directory, name):
            _write_file(directory, name, _UNCERTAIN)
        os.fsync(directory)


def _initialize(dataset: int) -> None:
    # The anchor is exclusive and precedes every state write. Another process
    # observing it during initialization refuses instead of creating fresh state.
    _rename_operation()
    _write_file(dataset, _ANCHOR_NAME, _ANCHOR)
    os.fsync(dataset)
    stage = f".confirmation-state-{secrets.token_hex(16)}"
    os.mkdir(stage, 0o700, dir_fd=dataset)
    with ExitStack() as stack:
        directory = _directory(dataset, stage)
        stack.callback(os.close, directory)
        try:
            _write_file(directory, _INITIALIZING, _UNCERTAIN)
            os.mkdir("protocols", 0o700, dir_fd=directory)
            protocols = _directory(directory, "protocols")
            stack.callback(os.close, protocols)
            os.fsync(protocols)
            _write_file(directory, ".lock", b"")
            _write_file(directory, "exposures.json", _log_bytes(()))
            os.fsync(directory)
            _rename_exclusive(dataset, stage, _STATE)
            os.fsync(dataset)
            os.unlink(_INITIALIZING, dir_fd=directory)
            os.fsync(directory)
        except (OSError, BundleError):
            _retain_uncertainty(directory, _INITIALIZING)
            raise


class _ManagedConfirmationState:
    def __init__(self, dataset_root: Path, *, create: bool = False) -> None:
        if type(create) is not bool:
            raise ConfirmationStoreError("create must be a boolean")
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ConfirmationStoreError("Confirmation state requires POSIX no-follow IO")
        self._dataset_root = Path(dataset_root).absolute()
        try:
            with _MUTEX, ExitStack() as stack:
                try:
                    dataset = os.open(
                        self._dataset_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    )
                except FileNotFoundError as error:
                    if create:
                        raise ConfirmationStoreError("Managed dataset root must already exist")
                    raise ConfirmationNotFoundError(
                        "Managed dataset root does not exist"
                    ) from error
                stack.callback(os.close, dataset)
                anchored = _exists(dataset, _ANCHOR_NAME)
                present = _exists(dataset, _STATE)
                if not anchored and not present:
                    if not create:
                        raise ConfirmationNotFoundError("Confirmation state is not initialized")
                    _initialize(dataset)
                elif not anchored or not present:
                    raise ConfirmationStoreError(
                        "Confirmation anchor or state directory is missing"
                    )
            with self._locked():
                pass
        except ConfirmationStoreError:
            raise
        except (OSError, ValueError) as error:
            raise ConfirmationStoreError(
                f"Cannot initialize confirmation state: {error}"
            ) from error

    @contextmanager
    def _locked(self) -> Iterator[tuple[int, int, tuple[ConfirmationExposure, ...]]]:
        try:
            with _MUTEX, ExitStack() as stack:
                dataset = os.open(
                    self._dataset_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
                stack.callback(os.close, dataset)
                if _read_file(dataset, _ANCHOR_NAME, len(_ANCHOR)) != _ANCHOR:
                    raise ConfirmationStoreError("Invalid managed confirmation anchor")
                directory = _directory(dataset, _STATE)
                stack.callback(os.close, directory)
                lock = os.open(
                    ".lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
                stack.callback(os.close, lock)
                info = os.fstat(lock)
                if not stat.S_ISREG(info.st_mode) or info.st_size != 0:
                    raise ConfirmationStoreError("Confirmation lock must be an empty regular file")
                fcntl.flock(lock, fcntl.LOCK_EX)
                stack.callback(fcntl.flock, lock, fcntl.LOCK_UN)
                _same_file(dataset, _STATE, directory)
                _same_file(directory, ".lock", lock)
                _check_state(directory)
                entries = _load_log(
                    _read_file(directory, "exposures.json", MAX_EXPOSURE_LEDGER_BYTES)
                )
                yield dataset, directory, entries
                _same_file(dataset, _STATE, directory)
                _same_file(directory, ".lock", lock)
        except ConfirmationAlreadyExposed:
            # PermissionError is an OSError; preserve the semantic race loser.
            raise
        except ConfirmationStoreError:
            raise
        except (OSError, ValueError) as error:
            raise ConfirmationStoreError(f"Cannot verify confirmation state: {error}") from error


@dataclass(frozen=True, slots=True)
class ConfirmationProtocolRecord:
    protocol_id: str
    canonical_bytes: bytes
    created: bool

    def __post_init__(self) -> None:
        if (
            type(self.created) is not bool
            or _protocol(self.canonical_bytes).protocol_id != self.protocol_id
        ):
            raise ConfirmationStoreError("Invalid confirmation protocol record")


class LocalConfirmationRegistry(_ManagedConfirmationState):
    """Immutable exact confirmation declarations below the fixed managed root."""

    def get(self, protocol_id: str) -> ConfirmationProtocolRecord:
        _identity(protocol_id)
        with self._locked() as (_dataset, state, _entries), ExitStack() as stack:
            directory = _directory(state, "protocols")
            stack.callback(os.close, directory)
            try:
                data = self._read_protocol(directory, protocol_id)
            except FileNotFoundError as error:
                raise ConfirmationNotFoundError(
                    f"Confirmation protocol is not published: {protocol_id}"
                ) from error
        return ConfirmationProtocolRecord(protocol_id, data, False)

    def seal(self, canonical_bytes: bytes) -> ConfirmationProtocolRecord:
        value = _protocol(canonical_bytes)
        with self._locked() as (_dataset, state, _entries), ExitStack() as stack:
            directory = _directory(state, "protocols")
            stack.callback(os.close, directory)
            created = self._publish(directory, value)
        return ConfirmationProtocolRecord(value.protocol_id, value.canonical_bytes, created)

    @staticmethod
    def _read_protocol(directory: int, protocol_id: str) -> bytes:
        data = _read_file(directory, f"{protocol_id}.json", MAX_CONFIRMATION_PROTOCOL_BYTES)
        if _protocol(data).protocol_id != protocol_id:
            raise ConfirmationStoreError("Confirmation protocol hash does not match identity")
        return data

    def _publish(self, directory: int, value: ConfirmationProtocol) -> bool:
        name = f"{value.protocol_id}.json"
        try:
            data = self._read_protocol(directory, value.protocol_id)
            if data != value.canonical_bytes:
                raise ConfirmationStoreError("Existing confirmation declaration differs")
            os.fsync(directory)
            return False
        except FileNotFoundError:
            pass
        temporary = f".pending-{secrets.token_hex(16)}"
        _write_file(directory, temporary, value.canonical_bytes)
        try:
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                created = True
            except FileExistsError:
                if self._read_protocol(directory, value.protocol_id) != value.canonical_bytes:
                    raise ConfirmationStoreError("Concurrent confirmation declaration differs")
                created = False
            os.fsync(directory)
            return created
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)


class LocalConfirmationExposureLedger(_ManagedConfirmationState):
    """Serialize conflict detection and durable whole-document consumption."""

    def entries(self) -> tuple[ConfirmationExposure, ...]:
        with self._locked() as (_dataset, _directory, entries):
            return entries

    def find_conflicts(self, footprint: OriginFootprint) -> tuple[ConfirmationExposure, ...]:
        try:
            checked = load_origin_footprint(footprint.canonical_bytes)
            if checked.footprint_id != footprint.footprint_id:
                raise ConfirmationStoreError("Origin footprint identity differs")
            with self._locked() as (_dataset, _directory, entries):
                return self._conflicts(checked, entries)
        except (ValueError, AttributeError) as error:
            if isinstance(error, ConfirmationStoreError):
                raise
            raise ConfirmationStoreError(f"Invalid exposure footprint: {error}") from error

    def expose(self, protocol: ConfirmationProtocol) -> ConfirmationExposure:
        try:
            checked = _protocol(protocol.canonical_bytes)
            if checked.protocol_id != protocol.protocol_id:
                raise ConfirmationStoreError("Confirmation protocol identity differs")
            exposure = build_confirmation_exposure(checked)
            footprint = _footprint(exposure)
            with self._locked() as (dataset, directory, entries):
                conflicts = self._conflicts(footprint, entries)
                if conflicts:
                    raise ConfirmationAlreadyExposed(conflicts)
                if len(entries) >= MAX_EXPOSURE_RECORDS:
                    raise ConfirmationStoreError("Exposure ledger reached its 256 record limit")
                complete = tuple(sorted((*entries, exposure), key=lambda item: item.exposure_id))
                data = _log_bytes(complete)
                if len(data) > MAX_EXPOSURE_LEDGER_BYTES:
                    raise ConfirmationStoreError("Exposure ledger exceeds its 32 MiB byte limit")
                _same_file(dataset, _STATE, directory)
                self._commit(directory, data, exposure)
            return exposure
        except (ValueError, AttributeError) as error:
            if isinstance(error, ConfirmationStoreError):
                raise
            raise ConfirmationStoreError(f"Invalid exposure declaration: {error}") from error

    @staticmethod
    def _conflicts(
        footprint: OriginFootprint, entries: tuple[ConfirmationExposure, ...]
    ) -> tuple[ConfirmationExposure, ...]:
        return tuple(entry for entry in entries if footprints_overlap(footprint, _footprint(entry)))

    @staticmethod
    def _commit(directory: int, data: bytes, exposure: ConfirmationExposure) -> None:
        try:
            # Persist the conservative claim before staging/replacing history.
            # Any failure leaves a marker, even if atomic replace already worked.
            _write_file(directory, _PENDING, exposure.canonical_bytes)
            os.fsync(directory)
            _write_file(directory, _NEXT, data)
            os.replace(_NEXT, "exposures.json", src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            os.unlink(_PENDING, dir_fd=directory)
            os.fsync(directory)
        except (OSError, BundleError):
            _retain_uncertainty(directory, _PENDING)
            raise
