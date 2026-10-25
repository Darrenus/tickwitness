"""Append-only per-protocol attempts and atomic outcomes in trusted local storage.

Slots are never returned to the budget. A missing outcome means reserved and
unfinalized, including after interruption; it does not authorize a refund.
Root parents/owner are trusted. This is not a statistical trial-family ledger.
"""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    load_run_receipt,
    parse,
)
from tickwitness.domain.research_contracts.executable import ExecutableProtocol

_RECORD_LIMIT = 16 * 1024
_ARTIFACT_LIMIT = 16 * 1024 * 1024
_ARTIFACT_COUNT = 16


class AttemptLedgerError(ValueError):
    """Attempt evidence cannot be safely published or verified."""


class AttemptNotFoundError(AttemptLedgerError):
    """The ledger, committed reservation or artifact does not exist."""


class AttemptBudgetExceededError(AttemptLedgerError):
    """All immutable slots in this protocol's attempt budget are occupied."""


def _identity(value: object) -> str:
    try:
        return identity(value)
    except EvidenceValidationError as error:
        raise AttemptLedgerError(str(error)) from error


def _reservation(raw: bytes) -> AttemptReservation:
    try:
        return AttemptReservation(digest(raw), raw)
    except (EvidenceValidationError, TypeError, ValueError) as error:
        raise AttemptLedgerError(f"Invalid attempt reservation: {error}") from error


def _outcome(raw: bytes, reservation: AttemptReservation) -> None:
    try:
        document = parse(raw, limit=_RECORD_LIMIT)
        if document.get("kind") == "research_run_receipt_v1":
            load_run_receipt(raw)
        elif document.get("kind") == "replay_attempt_failure_v1":
            if (
                set(document) != {"kind", "schema_version", "attempt", "protocol_id", "error"}
                or type(document["schema_version"]) is not int
                or document["schema_version"] != 1
            ):
                raise EvidenceValidationError("Failure outcome fields or version are invalid")
            details = document["error"]
            if not isinstance(details, dict) or set(details) != {"code", "message"}:
                raise EvidenceValidationError("Failure outcome requires code and message")
            for key, maximum in (("code", 128), ("message", 4096)):
                value = details[key]
                if not isinstance(value, str) or not value or len(value) > maximum:
                    raise EvidenceValidationError(f"Failure {key} is empty or oversized")
        else:
            raise EvidenceValidationError("Unsupported attempt outcome kind")
        attempt = document.get("attempt")
        if not isinstance(attempt, dict) or canonical(attempt) != reservation.canonical_bytes:
            raise EvidenceValidationError("Outcome does not bind the complete reserved attempt")
        if document.get("protocol_id") != reservation.protocol_id:
            raise EvidenceValidationError("Outcome belongs to a different protocol")
    except (EvidenceValidationError, TypeError, ValueError, RecursionError) as error:
        raise AttemptLedgerError(f"Invalid attempt outcome: {error}") from error


class LocalAttemptLedger:
    """Fixed POSIX namespaces with no-follow reads and no-replace publication."""

    def __init__(self, root: Path, *, create: bool = True) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise AttemptLedgerError("Attempt ledger requires POSIX no-follow directories")
        if type(create) is not bool:
            raise AttemptLedgerError("create must be a boolean")
        self._root = Path(root).absolute()
        try:
            if create:
                self._create_root()
            elif not self._root.exists():
                if self._root.is_symlink():
                    raise AttemptLedgerError("Ledger root cannot be a symlink")
                raise AttemptNotFoundError("Attempt ledger does not exist")
            with self._directories(create=create):
                pass
        except OSError as error:
            raise AttemptLedgerError(f"Cannot open attempt ledger: {error}") from error

    def reserve(self, protocol: ExecutableProtocol) -> AttemptReservation:
        """Atomically consume the first available slot, before execution starts."""
        if not isinstance(protocol, ExecutableProtocol):
            raise AttemptLedgerError("reserve requires an actual ExecutableProtocol")
        budget = cast("dict[str, int]", protocol.document["budget"])
        try:
            with (
                self._directories() as (objects, slots, _),
                self._protocol_slots(slots, protocol.protocol_id, create=True) as directory,
            ):
                for index in range(1, budget["max_attempts"] + 1):
                    name = f"{index:04}.json"
                    try:
                        self._existing_slot(objects, directory, name, protocol, index)
                        continue
                    except FileNotFoundError:
                        pass
                    raw = canonical(
                        {
                            "kind": "replay_attempt_reservation_v1",
                            "schema_version": 1,
                            "protocol_id": protocol.protocol_id,
                            "attempt_index": index,
                            "nonce": secrets.token_hex(16),
                            "max_wall_seconds": budget["max_wall_seconds"],
                            "created_at_utc": datetime.now(UTC).isoformat(timespec="microseconds"),
                        }
                    )
                    reservation = _reservation(raw)
                    self._cas(objects, raw)
                    try:
                        os.link(
                            reservation.attempt_id,
                            name,
                            src_dir_fd=objects,
                            dst_dir_fd=directory,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        self._existing_slot(objects, directory, name, protocol, index)
                        continue
                    os.fsync(directory)
                    return reservation
            raise AttemptBudgetExceededError(
                "This protocol's immutable attempt budget is exhausted"
            )
        except OSError as error:
            raise AttemptLedgerError(f"Cannot reserve attempt: {error}") from error

    def publish(
        self,
        reservation: AttemptReservation,
        outcome: bytes,
        *,
        artifacts: tuple[bytes, ...] = (),
    ) -> str:
        """Persist opaque artifact CAS first, then one immutable outcome commit."""
        if not isinstance(reservation, AttemptReservation):
            raise AttemptLedgerError("publish requires an actual AttemptReservation")
        committed = self.get_reservation(reservation.attempt_id)
        if committed.canonical_bytes != reservation.canonical_bytes:
            raise AttemptLedgerError("Reservation differs from its committed slot")
        _outcome(outcome, reservation)
        if type(artifacts) is not tuple or len(artifacts) > _ARTIFACT_COUNT:
            raise AttemptLedgerError(
                "artifacts must be a tuple of at most 16 immutable byte values"
            )
        for artifact in artifacts:
            self._bounded(artifact, _ARTIFACT_LIMIT)
        try:
            with self._directories() as (objects, _, outcomes):
                for artifact in artifacts:
                    self._cas(objects, artifact)
                outcome_id = self._cas(objects, outcome)
                self._publish_bytes(
                    outcomes, f"{reservation.attempt_id}.json", outcome, _RECORD_LIMIT
                )
                return outcome_id
        except OSError as error:
            raise AttemptLedgerError(f"Cannot publish attempt outcome: {error}") from error

    def get_reservation(self, attempt_id: str) -> AttemptReservation:
        """Require reservation CAS and the exact protocol slot closure."""
        _identity(attempt_id)
        try:
            with self._directories() as (objects, slots, _):
                try:
                    raw = self._read(objects, attempt_id, _RECORD_LIMIT, expected=attempt_id)
                    reservation = _reservation(raw)
                    with self._protocol_slots(slots, reservation.protocol_id) as directory:
                        slot = self._read(
                            directory,
                            f"{reservation.attempt_index:04}.json",
                            _RECORD_LIMIT,
                            expected=attempt_id,
                        )
                except FileNotFoundError as error:
                    raise AttemptNotFoundError(
                        "Attempt has no committed reservation closure"
                    ) from error
                if slot != raw:
                    raise AttemptLedgerError("Reservation CAS and slot differ")
                return reservation
        except OSError as error:
            raise AttemptLedgerError(f"Cannot verify attempt reservation: {error}") from error

    def get_outcome(self, attempt_id: str) -> bytes | None:
        """None means reserved_unfinalized; it never refunds the consumed slot."""
        reservation = self.get_reservation(attempt_id)
        try:
            with self._directories() as (objects, _, outcomes):
                try:
                    raw = self._read(outcomes, f"{attempt_id}.json", _RECORD_LIMIT)
                except FileNotFoundError:
                    return None
                _outcome(raw, reservation)
                try:
                    closure = self._read(objects, digest(raw), _RECORD_LIMIT, expected=digest(raw))
                except FileNotFoundError as error:
                    raise AttemptLedgerError("Outcome CAS closure is missing") from error
                if closure != raw:
                    raise AttemptLedgerError("Outcome CAS closure differs")
                return raw
        except OSError as error:
            raise AttemptLedgerError(f"Cannot verify attempt outcome: {error}") from error

    def read_artifact(self, sha: str, *, max_bytes: int = _ARTIFACT_LIMIT) -> bytes:
        _identity(sha)
        if type(max_bytes) is not int or not 1 <= max_bytes <= _ARTIFACT_LIMIT:
            raise AttemptLedgerError("Artifact read limit must be an integer in 1..16 MiB")
        try:
            with self._directories() as (objects, _, _):
                try:
                    return self._read(objects, sha, max_bytes, expected=sha)
                except FileNotFoundError as error:
                    raise AttemptNotFoundError("Artifact CAS object does not exist") from error
        except OSError as error:
            raise AttemptLedgerError(f"Cannot read attempt artifact: {error}") from error

    @staticmethod
    def _bounded(raw: bytes, limit: int) -> None:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
            raise AttemptLedgerError(f"Evidence requires nonempty immutable bytes within {limit}")

    @staticmethod
    def _existing_slot(
        objects: int, directory: int, name: str, protocol: ExecutableProtocol, index: int
    ) -> AttemptReservation:
        raw = LocalAttemptLedger._read(directory, name, _RECORD_LIMIT)
        reservation = _reservation(raw)
        budget = cast("dict[str, int]", protocol.document["budget"])
        if (
            reservation.protocol_id != protocol.protocol_id
            or reservation.attempt_index != index
            or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
        ):
            raise AttemptLedgerError("Occupied slot does not match protocol, index or wall budget")
        try:
            LocalAttemptLedger._read(
                objects, reservation.attempt_id, _RECORD_LIMIT, expected=reservation.attempt_id
            )
        except FileNotFoundError as error:
            raise AttemptLedgerError("Occupied reservation CAS closure is missing") from error
        return reservation

    def _create_root(self) -> None:
        missing: list[Path] = []
        current = self._root
        while not current.exists():
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            with suppress(FileExistsError):
                path.mkdir(mode=0o700)
            with ExitStack() as stack:
                child = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, child)
                parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                stack.callback(os.close, parent)
                os.fsync(child)
                os.fsync(parent)

    @staticmethod
    def _directory(stack: ExitStack, parent: int, name: str, create: bool) -> int:
        if create:
            with suppress(FileExistsError):
                os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        stack.callback(os.close, descriptor)
        return descriptor

    @contextmanager
    def _directories(self, *, create: bool = False) -> Iterator[tuple[int, int, int]]:
        with ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            parent = self._directory(stack, root, "objects", create)
            objects = self._directory(stack, parent, "sha256", create)
            slots = self._directory(stack, root, "slots", create)
            outcomes = self._directory(stack, root, "outcomes", create)
            yield objects, slots, outcomes

    @contextmanager
    def _protocol_slots(
        self, slots: int, protocol_id: str, *, create: bool = False
    ) -> Iterator[int]:
        _identity(protocol_id)
        with ExitStack() as stack:
            yield self._directory(stack, slots, protocol_id, create)

    @staticmethod
    def _read(
        directory: int,
        name: str,
        limit: int,
        *,
        expected: str | None = None,
        durable: bool = False,
    ) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise AttemptLedgerError("Attempt evidence must be a regular file")
            if info.st_size > limit:
                raise AttemptLedgerError("Attempt evidence exceeds its byte limit")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise AttemptLedgerError("Attempt evidence exceeds its byte limit")
            if expected is not None and digest(raw) != expected:
                raise AttemptLedgerError("Attempt evidence hash does not match its identity")
            if durable:
                os.fsync(descriptor)
            return raw
        finally:
            os.close(descriptor)

    def _cas(self, directory: int, raw: bytes) -> str:
        self._bounded(raw, _ARTIFACT_LIMIT)
        sha = digest(raw)
        self._publish_bytes(directory, sha, raw, _ARTIFACT_LIMIT)
        return sha

    def _publish_bytes(self, directory: int, name: str, raw: bytes, limit: int) -> None:
        try:
            existing = self._read(directory, name, limit, durable=True)
            if existing != raw:
                raise AttemptLedgerError("Immutable evidence already exists with different content")
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
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                if self._read(directory, name, limit, durable=True) != raw:
                    raise AttemptLedgerError(
                        "Immutable evidence already exists with different content"
                    ) from error
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
