"""Small immutable protocol registry, independent of the dataset catalog.

Only the protocol file is the publication commit point. This is trusted local
storage, not confirmation-data access control or a malicious-owner sandbox.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Never

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PROTOCOL_LIMIT = 128 * 1024
_STRATEGY_LIMIT = 256 * 1024
_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "execution_ready",
        "read_policy",
        "claim_revision_id",
        "claim",
        "datasets",
        "strategy",
        "parameters",
        "configuration",
        "budget",
        "seed",
    }
)


class ProtocolRegistryError(ValueError):
    """Protocol evidence cannot safely be stored or verified."""


class ProtocolNotFoundError(ProtocolRegistryError):
    """The registry or requested committed protocol is absent."""


@dataclass(frozen=True, slots=True)
class ProtocolRecord:
    """Immutable verified bytes, without mutable trial or execution state."""

    protocol_id: str
    canonical_bytes: bytes
    strategy_sha256: str
    created: bool


def _hash(value: object) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ProtocolRegistryError("References require 64 lowercase hexadecimal characters")
    return value


def _reject_constant(_value: str) -> Never:
    raise ProtocolRegistryError("Protocol JSON must contain finite values")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolRegistryError("Duplicate protocol JSON key")
        result[key] = value
    return result


def _finite_json(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, dict):
        for item in value.values():
            _finite_json(item)
        return
    if isinstance(value, list):
        for item in value:
            _finite_json(item)
        return
    raise ProtocolRegistryError("Protocol JSON must contain finite values")


def _document(data: bytes) -> tuple[dict[str, object], str]:
    if not isinstance(data, bytes) or not data or len(data) > _PROTOCOL_LIMIT:
        raise ProtocolRegistryError("Protocol bytes must be nonempty and within 128 KiB")
    try:
        value: object = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(value, dict):
            raise ProtocolRegistryError("Protocol JSON must be an object")
        _finite_json(value)
        encoded = json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ProtocolRegistryError):
            raise
        raise ProtocolRegistryError("Invalid UTF-8 or protocol JSON") from exc
    if encoded != data:
        raise ProtocolRegistryError("Protocol bytes must use canonical JSON encoding")
    if set(value) != _FIELDS:
        raise ProtocolRegistryError("Missing or unknown protocol top-level fields")
    if (
        value["kind"] != "frozen_research_protocol_v1"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["execution_ready"] is not False
        or value["read_policy"] != "development_only_v1"
    ):
        raise ProtocolRegistryError("Unsupported frozen protocol markers")
    _hash(value["claim_revision_id"])
    datasets = value["datasets"]
    if not isinstance(datasets, dict) or set(datasets) != {"development", "confirmation"}:
        raise ProtocolRegistryError("Protocol must reference development and confirmation datasets")
    development = _hash(datasets["development"])
    if _hash(datasets["confirmation"]) == development:
        raise ProtocolRegistryError("Development and confirmation dataset identities must differ")
    strategy = value["strategy"]
    if not isinstance(strategy, dict) or set(strategy) != {"name", "sha256"}:
        raise ProtocolRegistryError("Protocol strategy must contain name and sha256")
    name = strategy["name"]
    if not isinstance(name, str) or not name or len(name) > 256:
        raise ProtocolRegistryError("Strategy name must be a bounded nonempty string")
    for field in ("claim", "parameters", "configuration", "budget"):
        if not isinstance(value[field], dict):
            raise ProtocolRegistryError(f"Protocol {field} must be a JSON object")
    if type(value["seed"]) is not int:
        raise ProtocolRegistryError("Protocol seed must be an integer")
    return value, _hash(strategy["sha256"])


class LocalProtocolRegistry:
    """Publish strategy CAS first and a canonical protocol file last.

    Root/parents are trusted owner configuration. No SQLite or dataset migration
    is performed. Domain/application code verifies claim and policy semantics.
    """

    def __init__(self, root: Path, *, create: bool = True) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ProtocolRegistryError("Registry requires POSIX no-follow directory operations")
        if type(create) is not bool:
            raise ProtocolRegistryError("create must be a boolean")
        self._root = Path(root).absolute()
        try:
            if create:
                self._create_root()
            elif not self._root.exists():
                # A dangling symlink must be rejected as unsafe, not followed.
                if self._root.is_symlink():
                    raise ProtocolRegistryError("Registry root cannot be a symlink")
                raise ProtocolNotFoundError("Protocol registry does not exist")
            with self._directories(create=create):
                pass
        except FileNotFoundError as exc:
            raise ProtocolRegistryError("Protocol registry directories are incomplete") from exc
        except OSError as exc:
            raise ProtocolRegistryError(f"Cannot open protocol registry: {exc}") from exc

    def seal(self, protocol_bytes: bytes, strategy_bytes: bytes) -> ProtocolRecord:
        """Persist prevalidated canonical metadata and its exact strategy bytes."""
        _, strategy_hash = _document(protocol_bytes)
        if not isinstance(strategy_bytes, bytes) or len(strategy_bytes) > _STRATEGY_LIMIT:
            raise ProtocolRegistryError("Strategy bytes exceed the 256 KiB bound or are not bytes")
        if hashlib.sha256(strategy_bytes).hexdigest() != strategy_hash:
            raise ProtocolRegistryError("Strategy bytes do not match the protocol strategy hash")
        protocol_id = hashlib.sha256(protocol_bytes).hexdigest()
        try:
            with self._directories() as (objects, protocols):
                self._publish(objects, strategy_hash, strategy_bytes, _STRATEGY_LIMIT)
                # Verify the strategy closure before the protocol becomes visible.
                self._read(objects, strategy_hash, strategy_hash, _STRATEGY_LIMIT, durable=True)
                created = self._publish(
                    protocols, f"{protocol_id}.json", protocol_bytes, _PROTOCOL_LIMIT
                )
            return ProtocolRecord(protocol_id, protocol_bytes, strategy_hash, created)
        except OSError as exc:
            raise ProtocolRegistryError(f"Protocol publication failed: {exc}") from exc

    def get(self, protocol_id: str) -> ProtocolRecord:
        """Verify the committed document and complete strategy hash closure."""
        _hash(protocol_id)
        try:
            with self._directories() as (objects, protocols):
                try:
                    data = self._read(
                        protocols, f"{protocol_id}.json", protocol_id, _PROTOCOL_LIMIT
                    )
                except FileNotFoundError as exc:
                    raise ProtocolNotFoundError(
                        f"Protocol is not published: {protocol_id}"
                    ) from exc
                _, strategy_hash = _document(data)
                self._read(objects, strategy_hash, strategy_hash, _STRATEGY_LIMIT)
                return ProtocolRecord(protocol_id, data, strategy_hash, False)
        except OSError as exc:
            raise ProtocolRegistryError(f"Cannot verify protocol evidence: {exc}") from exc

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
    def _directory(parent: int, name: str, create: bool) -> int:
        if create:
            with suppress(FileExistsError):
                os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)

    @contextmanager
    def _directories(self, *, create: bool = False) -> Iterator[tuple[int, int]]:
        with ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            parent = self._directory(root, "objects", create)
            stack.callback(os.close, parent)
            objects = self._directory(parent, "sha256", create)
            stack.callback(os.close, objects)
            protocols = self._directory(root, "protocols", create)
            stack.callback(os.close, protocols)
            yield objects, protocols

    @staticmethod
    def _read(
        directory: int, name: str, expected: str, limit: int, *, durable: bool = False
    ) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ProtocolRegistryError("Registry evidence must be a regular file")
            if info.st_size > limit:
                raise ProtocolRegistryError("Registry evidence exceeds its byte bound")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise ProtocolRegistryError("Registry evidence exceeds its byte bound")
            if hashlib.sha256(data).hexdigest() != expected:
                raise ProtocolRegistryError("Registry evidence hash does not match its identity")
            if durable:
                os.fsync(descriptor)
            return data
        finally:
            os.close(descriptor)

    def _publish(self, directory: int, name: str, data: bytes, limit: int) -> bool:
        digest = hashlib.sha256(data).hexdigest()
        try:
            self._read(directory, name, digest, limit, durable=True)
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
                self._read(directory, name, digest, limit, durable=True)
                created = False
            os.fsync(directory)
            return created
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
