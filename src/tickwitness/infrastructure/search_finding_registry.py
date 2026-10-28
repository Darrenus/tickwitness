"""Durable immutable publication in a namespace dedicated to search finding protocols.

Execution registries remain separate and do not grant finding authority. Root
parents are trusted configuration, not a hostile-owner sandbox.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path

from tickwitness.domain.research_contracts.search_finding_protocol import (
    MAX_SEARCH_FINDING_PROTOCOL_BYTES,
    SearchFindingProtocol,
    SearchFindingValidationError,
    load_search_finding_protocol,
)


class SearchFindingStoreError(ValueError):
    """Search finding protocol bytes cannot safely be published or verified."""


class SearchFindingNotFoundError(SearchFindingStoreError):
    """The registry or requested committed search finding protocol does not exist."""


def _identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SearchFindingStoreError(
            "Search finding protocol ID requires 64 lowercase hexadecimal characters"
        )
    return value


def _protocol(raw: bytes) -> SearchFindingProtocol:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SEARCH_FINDING_PROTOCOL_BYTES:
        raise SearchFindingStoreError("Finding authority must be nonempty bounded bytes")
    try:
        return load_search_finding_protocol(raw)
    except SearchFindingValidationError as error:
        raise SearchFindingStoreError(f"Invalid search finding protocol: {error}") from error


class LocalSearchFindingRegistry:
    """Publish finding authority JSON with atomic no-replace hard links and fsync."""

    def __init__(self, root: Path, *, create: bool = False) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise SearchFindingStoreError("Registry requires POSIX no-follow directory operations")
        if type(create) is not bool:
            raise SearchFindingStoreError("create must be a boolean")
        self._root = Path(root).absolute()
        try:
            if create:
                self._create_root()
            elif not self._root.exists():
                if self._root.is_symlink():
                    raise SearchFindingStoreError("Registry root cannot be a symlink")
                raise SearchFindingNotFoundError("Search finding protocol registry does not exist")
            with self._directory(create=create):
                pass
        except OSError as error:
            raise SearchFindingStoreError(
                f"Cannot open search finding protocol registry: {error}"
            ) from error

    def freeze(self, protocol: SearchFindingProtocol) -> bool:
        """Validate an actual value; never replace an existing committed authority."""
        if type(protocol) is not SearchFindingProtocol:
            raise SearchFindingStoreError("Freeze requires an actual SearchFindingProtocol")
        checked = _protocol(protocol.canonical_bytes)
        if checked.protocol_id != protocol.protocol_id:
            raise SearchFindingStoreError("Finding authority identity differs from its bytes")
        try:
            with self._directory() as directory:
                return self._publish(directory, checked.protocol_id, checked.canonical_bytes)
        except OSError as error:
            raise SearchFindingStoreError(
                f"Search finding protocol publication failed: {error}"
            ) from error

    def get(self, protocol_id: str) -> SearchFindingProtocol:
        """Verify a committed protocol without creating directories or repairing evidence."""
        _identity(protocol_id)
        try:
            with self._directory() as directory:
                try:
                    data = self._read(directory, f"{protocol_id}.json", protocol_id)
                except FileNotFoundError as error:
                    raise SearchFindingNotFoundError(
                        f"Search finding protocol is not published: {protocol_id}"
                    ) from error
            return _protocol(data)
        except OSError as error:
            raise SearchFindingStoreError(
                f"Cannot verify search finding protocol evidence: {error}"
            ) from error

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
                    os.mkdir("search-finding-protocols", mode=0o700, dir_fd=root)
                os.fsync(root)
            directory = os.open(
                "search-finding-protocols",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root,
            )
            stack.callback(os.close, directory)
            yield directory

    @staticmethod
    def _read(directory: int, name: str, expected: str, *, durable: bool = False) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise SearchFindingStoreError(
                    "Search finding protocol evidence must be a regular file"
                )
            if info.st_size > MAX_SEARCH_FINDING_PROTOCOL_BYTES:
                raise SearchFindingStoreError(
                    "Search finding protocol evidence exceeds its byte limit"
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(MAX_SEARCH_FINDING_PROTOCOL_BYTES + 1)
            if len(data) > MAX_SEARCH_FINDING_PROTOCOL_BYTES:
                raise SearchFindingStoreError(
                    "Search finding protocol evidence exceeds its byte limit"
                )
            if hashlib.sha256(data).hexdigest() != expected:
                raise SearchFindingStoreError(
                    "Search finding protocol evidence hash does not match identity"
                )
            _protocol(data)
            if durable:
                os.fsync(descriptor)
            return data
        finally:
            os.close(descriptor)

    def _publish(self, directory: int, protocol_id: str, data: bytes) -> bool:
        name = f"{protocol_id}.json"
        try:
            self._read(directory, name, protocol_id, durable=True)
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
                self._read(directory, name, protocol_id, durable=True)
                created = False
            os.fsync(directory)
            return created
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
