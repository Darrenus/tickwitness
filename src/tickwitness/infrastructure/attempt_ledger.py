"""Append-only per-protocol attempts and atomic outcomes in trusted local storage.

Slots are never returned to the budget. A missing outcome means reserved and
unfinalized, including after interruption; it does not authorize a refund.
Root parents/owner are trusted. This is not a statistical trial-family ledger.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import cast

from tickwitness.domain.evidence.queue_records import (
    MAX_QUEUE_RECORD_BYTES,
    QueueAttemptReservation,
    QueueRunIntent,
    load_queue_failure,
    load_queue_intent,
    load_queue_run_receipt,
)
from tickwitness.domain.evidence.reduction_records import (
    ReductionExecutionIntent,
    load_reduction_failure,
    load_reduction_intent,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    load_run_receipt,
    parse,
)
from tickwitness.domain.evidence.scenario_records import (
    ScenarioIntent,
    load_scenario_failure,
    load_scenario_intent,
    load_scenario_run_receipt,
)
from tickwitness.domain.evidence.tagged_queue_records import (
    MAX_TAGGED_QUEUE_RECORD_BYTES,
    TaggedQueueAttemptReservation,
    TaggedQueueRunIntent,
    load_tagged_queue_failure,
    load_tagged_queue_intent,
    load_tagged_queue_run_receipt,
)
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    load_executable_protocol,
)
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError
from tickwitness.domain.research_contracts.queue_family import (
    QueueFamilyProtocol,
    load_queue_family_protocol,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TaggedQueueProtocol,
    load_tagged_queue_protocol,
)
from tickwitness.infrastructure.campaign_resource_guard import charge_managed_write

_RECORD_LIMIT = 16 * 1024
_ARTIFACT_LIMIT = 16 * 1024 * 1024
_ARTIFACT_COUNT = 16
# Serialize separate ledger instances in this process before acquiring flock.
# The file lock remains necessary for independent processes sharing the root.
_NAMED_RESERVATION_MUTEX = Lock()
type _Owner = ExecutableProtocol | QueueFamilyProtocol | TaggedQueueProtocol
type _Intent = ScenarioIntent | QueueRunIntent | TaggedQueueRunIntent | ReductionExecutionIntent


class AttemptLedgerError(ValueError):
    """Attempt evidence cannot be safely published or verified."""


class AttemptNotFoundError(AttemptLedgerError):
    """The ledger, committed reservation or artifact does not exist."""


class AttemptBudgetExceededError(AttemptLedgerError):
    """All immutable slots in this protocol's attempt budget are occupied."""

    code = "attempt_budget_exhausted"
    exit_code = 8


def _identity(value: object) -> str:
    try:
        return identity(value)
    except EvidenceValidationError as error:
        raise AttemptLedgerError(str(error)) from error


def _reservation(raw: bytes) -> AttemptReservation:
    try:
        kind = parse(raw).get("kind")
        if kind == "tagged_queue_attempt_reservation_v1":
            return TaggedQueueAttemptReservation(digest(raw), raw)
        if kind == "queue_attempt_reservation_v1":
            return QueueAttemptReservation(digest(raw), raw)
        return AttemptReservation(digest(raw), raw)
    except (EvidenceValidationError, TypeError, ValueError) as error:
        raise AttemptLedgerError(f"Invalid attempt reservation: {error}") from error


def _checked_owner(owner: _Owner) -> _Owner:
    """Reconstruct real owners; a forged dataclass or duck type owns no slots."""
    try:
        if type(owner) is ExecutableProtocol:
            rebuilt: _Owner = load_executable_protocol(owner.canonical_bytes)
        elif type(owner) is QueueFamilyProtocol:
            rebuilt = load_queue_family_protocol(owner.canonical_bytes)
        elif type(owner) is TaggedQueueProtocol:
            rebuilt = load_tagged_queue_protocol(owner.canonical_bytes)
        else:
            raise AttemptLedgerError("Expected an actual supported frozen execution protocol")
        if rebuilt.protocol_id != owner.protocol_id:
            raise AttemptLedgerError("Budget owner identity differs from its canonical content")
        return rebuilt
    except (ProtocolValidationError, EvidenceValidationError) as error:
        raise AttemptLedgerError(f"Invalid attempt budget owner: {error}") from error


def _outcome(raw: bytes, reservation: AttemptReservation) -> _Intent | None:
    try:
        document = parse(raw, limit=MAX_TAGGED_QUEUE_RECORD_BYTES)
        intent: _Intent | None = None
        tagged_kind = document.get("kind") in (
            "tagged_queue_run_receipt_v1",
            "tagged_queue_attempt_failure_v1",
        )
        if tagged_kind != (type(reservation) is TaggedQueueAttemptReservation):
            raise EvidenceValidationError("Outcome kind differs from the reserved execution owner")
        queue_kind = document.get("kind") in ("queue_run_receipt_v1", "queue_attempt_failure_v1")
        if queue_kind != (type(reservation) is QueueAttemptReservation):
            raise EvidenceValidationError("Outcome kind differs from the reserved execution owner")
        if tagged_kind:
            if document["kind"] == "tagged_queue_run_receipt_v1":
                load_tagged_queue_run_receipt(raw)
            else:
                load_tagged_queue_failure(raw)
            intent = load_tagged_queue_intent(
                canonical(cast("dict[str, object]", document["intent"]))
            )
        elif queue_kind:
            if document["kind"] == "queue_run_receipt_v1":
                load_queue_run_receipt(raw)
            else:
                load_queue_failure(raw)
            intent = load_queue_intent(canonical(cast("dict[str, object]", document["intent"])))
        elif document.get("kind") == "research_run_receipt_v1":
            load_run_receipt(raw)
        elif document.get("kind") in ("scenario_run_receipt_v1", "scenario_attempt_failure_v1"):
            if document["kind"] == "scenario_run_receipt_v1":
                load_scenario_run_receipt(raw)
            else:
                load_scenario_failure(raw)
            intent = load_scenario_intent(canonical(cast("dict[str, object]", document["intent"])))
        elif document.get("kind") in ("reduction_run_receipt_v1", "reduction_attempt_failure_v1"):
            if document["kind"] == "reduction_run_receipt_v1":
                load_reduction_run_receipt(raw)
            else:
                load_reduction_failure(raw)
            intent = load_reduction_intent(canonical(cast("dict[str, object]", document["intent"])))
        elif document.get("kind") == "replay_attempt_failure_v1":
            parse(raw, limit=_RECORD_LIMIT)
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
        return intent
    except (EvidenceValidationError, TypeError, ValueError, RecursionError) as error:
        raise AttemptLedgerError(f"Invalid attempt outcome: {error}") from error


def _reservation_class(owner: _Owner) -> type[AttemptReservation]:
    if type(owner) is TaggedQueueProtocol:
        return TaggedQueueAttemptReservation
    if type(owner) is QueueFamilyProtocol:
        return QueueAttemptReservation
    return AttemptReservation


def _record_limit(reservation: AttemptReservation) -> int:
    if type(reservation) is TaggedQueueAttemptReservation:
        return MAX_TAGGED_QUEUE_RECORD_BYTES
    if type(reservation) is QueueAttemptReservation:
        return MAX_QUEUE_RECORD_BYTES
    return _RECORD_LIMIT


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

    def reserve(self, protocol: _Owner) -> AttemptReservation:
        """Atomically consume the first available slot, before execution starts."""
        return self._reserve(protocol)

    def reserve_with_nonce(self, protocol: ExecutableProtocol, nonce: str) -> AttemptReservation:
        """Consume an original v2 slot using a nonce already sealed in a dispatch.

        Named calls serialize so the same dispatch nonce cannot consume two
        slots. A committed nonce is rejected, never returned for free replay.
        Ordinary reservations still compete for the same immutable slots.
        An exception after slot publication does not establish non-consumption.
        """
        if type(protocol) is not ExecutableProtocol:
            raise AttemptLedgerError("Named search reservations require ExecutableProtocol v2")
        if not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
            raise AttemptLedgerError(
                "Search reservation nonce requires 32 lowercase hex characters"
            )
        checked = _checked_owner(protocol)
        try:
            with self._named_reservation_lock():
                if any(item.document["nonce"] == nonce for item in self.list_reservations(checked)):
                    raise AttemptLedgerError("Search reservation nonce is already committed")
                return self._reserve(checked, nonce=nonce)
        except OSError as error:
            raise AttemptLedgerError(f"Cannot reserve named search attempt: {error}") from error

    def _reserve(self, protocol: _Owner, *, nonce: str | None = None) -> AttemptReservation:
        protocol = _checked_owner(protocol)
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
                            "kind": (
                                "tagged_queue_attempt_reservation_v1"
                                if type(protocol) is TaggedQueueProtocol
                                else (
                                    "queue_attempt_reservation_v1"
                                    if type(protocol) is QueueFamilyProtocol
                                    else "replay_attempt_reservation_v1"
                                )
                            ),
                            "schema_version": 1,
                            "protocol_id": protocol.protocol_id,
                            "attempt_index": index,
                            "nonce": nonce if nonce is not None else secrets.token_hex(16),
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

    @contextmanager
    def _named_reservation_lock(self) -> Iterator[None]:
        import fcntl

        with _NAMED_RESERVATION_MUTEX, ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            descriptor = os.open(
                ".search-reservation.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                mode=0o600,
                dir_fd=root,
            )
            stack.callback(os.close, descriptor)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise AttemptLedgerError("Search reservation lock must be a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                os.fsync(descriptor)
                os.fsync(root)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)

    def list_reservations(self, owner: _Owner) -> tuple[AttemptReservation, ...]:
        """Read the committed slot prefix without creating any owner namespace.

        Concurrent writers may append after this view's first absent slot. The
        result is a verified prefix, not a promise that no later attempt exists.
        """
        owner = _checked_owner(owner)
        budget = cast("dict[str, int]", owner.document["budget"])
        reservations: list[AttemptReservation] = []
        try:
            with self._directories() as (objects, slots, _):
                try:
                    with self._protocol_slots(slots, owner.protocol_id) as directory:
                        for index in range(1, budget["max_attempts"] + 1):
                            try:
                                reservation = self._existing_slot(
                                    objects, directory, f"{index:04}.json", owner, index
                                )
                            except FileNotFoundError:
                                break
                            reservations.append(reservation)
                except FileNotFoundError:
                    return ()
            return tuple(reservations)
        except OSError as error:
            raise AttemptLedgerError(f"Cannot list attempt reservations: {error}") from error

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
        intended = _outcome(outcome, reservation)
        self._artifacts(artifacts)
        try:
            with (
                self._locked_attempt(reservation),
                self._directories() as (objects, _, outcomes),
            ):
                self._match_intent(intended, self.get_intent(reservation.attempt_id))
                for artifact in artifacts:
                    self._cas(objects, artifact)
                outcome_id = self._cas(objects, outcome)
                self._publish_bytes(
                    outcomes,
                    f"{reservation.attempt_id}.json",
                    outcome,
                    _record_limit(reservation),
                )
                return outcome_id
        except OSError as error:
            raise AttemptLedgerError(f"Cannot publish attempt outcome: {error}") from error

    def bind_intent(
        self,
        reservation: AttemptReservation,
        intent_bytes: bytes,
        *,
        artifacts: tuple[bytes, ...] = (),
    ) -> str:
        """Commit an immutable execution intent before constructing a native engine.

        A failure cannot refund the already occupied reservation. Artifact objects
        become durable before the intent name; no execution is authorized here.
        """
        if not isinstance(reservation, AttemptReservation):
            raise AttemptLedgerError("bind_intent requires an actual AttemptReservation")
        intent = self._intent(intent_bytes, reservation)
        self._artifacts(artifacts)
        try:
            with self._locked_attempt(reservation):
                existing = self.get_intent(reservation.attempt_id)
                if existing is not None and existing != intent_bytes:
                    raise AttemptLedgerError("Attempt already binds a different immutable intent")
                if self.get_outcome(reservation.attempt_id) is not None and existing is None:
                    raise AttemptLedgerError("Cannot bind intent after an outcome was finalized")
                with self._directories() as (objects, _, _):
                    for artifact in artifacts:
                        self._cas(objects, artifact)
                    self._cas(objects, intent_bytes)
                with self._intents(create=True) as directory:
                    assert directory is not None
                    self._publish_bytes(
                        directory,
                        f"{reservation.attempt_id}.json",
                        intent_bytes,
                        _record_limit(reservation),
                    )
                return intent.intent_id
        except OSError as error:
            raise AttemptLedgerError(f"Cannot bind execution intent: {error}") from error

    def get_intent(self, attempt_id: str) -> bytes | None:
        """Read optional durable intent and CAS closure without upgrading old roots."""
        reservation = self.get_reservation(attempt_id)
        try:
            with self._intents() as directory:
                if directory is None:
                    return None
                try:
                    raw = self._read(directory, f"{attempt_id}.json", _record_limit(reservation))
                except FileNotFoundError:
                    return None
            intent = self._intent(raw, reservation)
            try:
                closure = self.read_artifact(intent.intent_id, max_bytes=_record_limit(reservation))
            except AttemptNotFoundError as error:
                raise AttemptLedgerError("Scenario intent CAS closure is missing") from error
            if closure != raw:
                raise AttemptLedgerError("Scenario intent CAS closure differs")
            return raw
        except OSError as error:
            raise AttemptLedgerError(f"Cannot verify scenario intent: {error}") from error

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
                    raw = self._read(outcomes, f"{attempt_id}.json", _record_limit(reservation))
                except FileNotFoundError:
                    return None
                # A scenario terminal is committed after its immutable intent.
                # Reading intent first could retain a stale None while a writer
                # commits both records before this reader opens the outcome.
                self._match_intent(_outcome(raw, reservation), self.get_intent(attempt_id))
                try:
                    closure = self._read(
                        objects, digest(raw), _record_limit(reservation), expected=digest(raw)
                    )
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
    def _artifacts(artifacts: tuple[bytes, ...]) -> None:
        if type(artifacts) is not tuple or len(artifacts) > _ARTIFACT_COUNT:
            raise AttemptLedgerError(
                "artifacts must be a tuple of at most 16 immutable byte values"
            )
        for artifact in artifacts:
            LocalAttemptLedger._bounded(artifact, _ARTIFACT_LIMIT)

    @staticmethod
    def _intent(raw: bytes, reservation: AttemptReservation) -> _Intent:
        try:
            intent: _Intent
            if type(reservation) is TaggedQueueAttemptReservation:
                intent = load_tagged_queue_intent(raw)
            elif type(reservation) is QueueAttemptReservation:
                intent = load_queue_intent(raw)
            elif parse(raw, limit=_RECORD_LIMIT).get("kind") == "reduction_execution_intent_v1":
                intent = load_reduction_intent(raw)
            else:
                intent = load_scenario_intent(raw)
            if intent.document["protocol_id"] != reservation.protocol_id:
                raise EvidenceValidationError("Intent belongs to a different reserved protocol")
            if isinstance(intent, QueueRunIntent):
                budget = cast("dict[str, int]", intent.family.document["budget"])
                if (
                    reservation.attempt_index > budget["max_attempts"]
                    or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
                ):
                    raise EvidenceValidationError("Queue intent reservation exceeds family budget")
            elif isinstance(intent, TaggedQueueRunIntent):
                budget = cast("dict[str, int]", intent.protocol.document["budget"])
                if (
                    reservation.attempt_index > budget["max_attempts"]
                    or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
                ):
                    raise EvidenceValidationError("Tagged intent reservation exceeds shared budget")
            return intent
        except EvidenceValidationError as error:
            raise AttemptLedgerError(f"Invalid execution intent: {error}") from error

    @staticmethod
    def _match_intent(intended: _Intent | None, persisted: bytes | None) -> None:
        if intended is None:
            if persisted is not None:
                raise AttemptLedgerError("Scenario-bound attempts cannot publish baseline outcomes")
        elif persisted != intended.canonical_bytes:
            raise AttemptLedgerError("Execution outcome requires its exact durable intent")

    @contextmanager
    def _locked_attempt(self, reservation: AttemptReservation) -> Iterator[None]:
        # Lock the immutable reservation inode, not a new mutable lock-file namespace.
        # No native runtime or non-stdlib dependency is imported at this IO boundary.
        import fcntl

        with self._directories() as (objects, _, _):
            try:
                descriptor = os.open(
                    reservation.attempt_id,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=objects,
                )
            except FileNotFoundError as error:
                raise AttemptNotFoundError("Attempt reservation CAS does not exist") from error
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise AttemptLedgerError("Attempt reservation lock requires a regular file")
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                try:
                    if self.get_reservation(reservation.attempt_id).canonical_bytes != (
                        reservation.canonical_bytes
                    ):
                        raise AttemptLedgerError("Reservation differs from its committed slot")
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    @staticmethod
    def _existing_slot(
        objects: int, directory: int, name: str, protocol: _Owner, index: int
    ) -> AttemptReservation:
        raw = LocalAttemptLedger._read(directory, name, _RECORD_LIMIT)
        reservation = _reservation(raw)
        budget = cast("dict[str, int]", protocol.document["budget"])
        if (
            reservation.protocol_id != protocol.protocol_id
            or reservation.attempt_index != index
            or reservation.document["max_wall_seconds"] != budget["max_wall_seconds"]
            or type(reservation) is not _reservation_class(protocol)
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

    @contextmanager
    def _intents(self, *, create: bool = False) -> Iterator[int | None]:
        with ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            try:
                directory = self._directory(stack, root, "intents", create)
            except FileNotFoundError:
                if create:
                    raise
                yield None
                return
            yield directory

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
        charge_managed_write(len(raw))
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
