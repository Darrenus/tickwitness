"""Immutable proposal-plan publication, separate from execution and trial ledgers.

Root parents are trusted local configuration. Content closure does not prove
source availability, execution, global trial history, or author authentication.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from tickwitness.domain.search.plans import (
    MAX_SEARCH_PLAN_BYTES,
    SearchPlan,
    SearchPlanValidationError,
    load_search_plan,
)


class SearchPlanRegistryError(ValueError):
    """A plan cannot safely be read or published; publication may be uncertain."""


class SearchPlanNotFoundError(SearchPlanRegistryError):
    """The registry root or requested committed plan does not exist."""


def _identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SearchPlanRegistryError("Plan ID requires 64 lowercase hexadecimal characters")
    return value


def _plan(raw: bytes) -> SearchPlan:
    try:
        return load_search_plan(raw)
    except SearchPlanValidationError as error:
        raise SearchPlanRegistryError(f"Invalid search plan: {error}") from error


@dataclass(frozen=True, slots=True)
class SearchPlanRecord:
    plan_id: str
    canonical_bytes: bytes
    created: bool

    def __post_init__(self) -> None:
        if type(self.created) is not bool or _plan(self.canonical_bytes).plan_id != _identity(
            self.plan_id
        ):
            raise SearchPlanRegistryError("Record identity or created flag is invalid")


class LocalSearchPlanRegistry:
    """Commit a canonical plan with atomic no-replace hard links and fsync.

    Default opening and get never create or repair files. The committed filename
    is the visibility point; a later fsync error does not imply it is absent.
    """

    def __init__(self, root: Path, *, create: bool = False) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise SearchPlanRegistryError("Registry requires POSIX no-follow directory operations")
        if type(create) is not bool:
            raise SearchPlanRegistryError("create must be a boolean")
        self._root = Path(root).absolute()
        try:
            if create:
                self._create_root()
            elif not self._root.exists():
                if self._root.is_symlink():
                    raise SearchPlanRegistryError("Registry root cannot be a symlink")
                raise SearchPlanNotFoundError("Search plan registry does not exist")
            with self._directory(create=create):
                pass
        except OSError as error:
            raise SearchPlanRegistryError(f"Cannot open search plan registry: {error}") from error

    def seal(self, canonical_bytes: bytes) -> SearchPlanRecord:
        """Rebuild the journal before publication; verify an existing same-ID record."""
        plan = _plan(canonical_bytes)
        try:
            with self._directory() as directory:
                created = self._publish(directory, plan.plan_id, canonical_bytes)
            return SearchPlanRecord(plan.plan_id, canonical_bytes, created)
        except OSError as error:
            raise SearchPlanRegistryError(
                f"Search plan publication failed; inspect committed identity before retry: {error}"
            ) from error

    def get(self, plan_id: str) -> SearchPlanRecord:
        """Rebuild a committed journal without writing or repairing any evidence."""
        _identity(plan_id)
        try:
            with self._directory() as directory:
                try:
                    data = self._read(directory, f"{plan_id}.json", plan_id)
                except FileNotFoundError as error:
                    raise SearchPlanNotFoundError(
                        f"Search plan is not published: {plan_id}"
                    ) from error
            return SearchPlanRecord(plan_id, data, False)
        except OSError as error:
            raise SearchPlanRegistryError(f"Cannot verify search plan evidence: {error}") from error

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

    @contextmanager
    def _directory(self, *, create: bool = False) -> Iterator[int]:
        with ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            if create:
                with suppress(FileExistsError):
                    os.mkdir("search-plans", mode=0o700, dir_fd=root)
                os.fsync(root)
            directory = os.open(
                "search-plans", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root
            )
            stack.callback(os.close, directory)
            yield directory

    @staticmethod
    def _read(directory: int, name: str, expected: str, *, durable: bool = False) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise SearchPlanRegistryError("Search plan evidence must be a regular file")
            if info.st_size > MAX_SEARCH_PLAN_BYTES:
                raise SearchPlanRegistryError("Search plan evidence exceeds 2 MiB")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(MAX_SEARCH_PLAN_BYTES + 1)
            if len(data) > MAX_SEARCH_PLAN_BYTES:
                raise SearchPlanRegistryError("Search plan evidence exceeds 2 MiB")
            if hashlib.sha256(data).hexdigest() != expected:
                raise SearchPlanRegistryError("Search plan evidence hash does not match identity")
            _plan(data)
            if durable:
                os.fsync(descriptor)
            return data
        finally:
            os.close(descriptor)

    def _publish(self, directory: int, plan_id: str, data: bytes) -> bool:
        name = f"{plan_id}.json"
        try:
            self._read(directory, name, plan_id, durable=True)
            os.fsync(directory)
            return False
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
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                created = True
            except FileExistsError:
                self._read(directory, name, plan_id, durable=True)
                created = False
            os.fsync(directory)
            return created
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
