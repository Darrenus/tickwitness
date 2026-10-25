"""Bounded immutable directory bundles; semantic verification belongs to the app.

The existing parent/root ancestors are trusted owner configuration. Directory
handles and no-follow opens protect the fixed tree; this is not an owner sandbox.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
from collections.abc import Mapping
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Never, Protocol, cast

_MIB = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ROLE_LIMITS = {
    "protocol": 128 * 1024,
    "dataset_manifest": 64 * 1024,
    "raw": 8 * _MIB,
    "normalized": 8 * _MIB,
    "report": 4 * _MIB,
    "replay_result": 16 * _MIB,
    "evaluation": 4 * _MIB,
    "attempt": 256 * 1024,
}


class BundleError(ValueError):
    """Bundle shape, integrity, IO, limits or platform validation failed."""


class BundleNotFoundError(BundleError):
    """The requested root does not exist; no directory was created."""


class BundleDestinationExistsError(BundleError):
    """Publication refused an existing destination without changing it."""


class BundleDurabilityError(BundleError):
    """A complete directory is published but parent fsync did not confirm durability."""


@dataclass(frozen=True, slots=True)
class BundleLimits:
    max_total_bytes: int = 64 * _MIB
    max_files: int = 32
    max_manifest_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for value in (self.max_total_bytes, self.max_files, self.max_manifest_bytes):
            if type(value) is not int or value <= 0:
                raise BundleError("Bundle limits must be positive integers")


_DEFAULT_LIMITS = BundleLimits()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise BundleError("Duplicate manifest JSON key")
        value[key] = item
    return value


def _reject_number(_value: str) -> Never:
    raise BundleError("Manifest numbers must be finite integers")


def _manifest(raw: bytes, limits: BundleLimits) -> dict[str, object]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limits.max_manifest_bytes:
        raise BundleError("Manifest exceeds its nonempty byte budget")
    try:
        value: object = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        if not isinstance(value, dict) or set(value) != {
            "kind",
            "schema_version",
            "scope",
            "roles",
        }:
            raise BundleError("Manifest has missing or unknown fields")
        if (
            value["kind"] != "evidence_bundle_v1"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["scope"] != "development_replay_v1"
        ):
            raise BundleError("Unsupported evidence bundle markers")
        roles = value["roles"]
        if not isinstance(roles, dict) or set(roles) != set(_ROLE_LIMITS):
            raise BundleError("Bundle requires exactly the eight fixed artifact roles")
        sizes: dict[str, int] = {}
        for role, reference in roles.items():
            if not isinstance(reference, dict) or set(reference) != {"sha256", "size_bytes", "ref"}:
                raise BundleError("Artifact reference has missing or unknown fields")
            digest, size = reference["sha256"], reference["size_bytes"]
            if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
                raise BundleError("Artifact hash must be 64 lowercase hexadecimal characters")
            if type(size) is not int or not 0 < size <= _ROLE_LIMITS[role]:
                raise BundleError(f"Artifact {role} exceeds its nonempty byte budget")
            if reference["ref"] != f"objects/sha256/{digest}":
                raise BundleError("Artifact reference is not its fixed content address")
            if digest in sizes and sizes[digest] != size:
                raise BundleError("The same object hash has conflicting declared sizes")
            sizes[digest] = size
        if len(sizes) + 1 > limits.max_files:
            raise BundleError("Bundle exceeds max_files")
        if len(raw) + sum(sizes.values()) > limits.max_total_bytes:
            raise BundleError("Bundle exceeds max_total_bytes")
        if _canonical(value) != raw:
            raise BundleError("Manifest must use exact canonical JSON encoding")
    except BundleError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise BundleError("Invalid UTF-8 or manifest JSON") from error
    return cast("dict[str, object]", value)


def _artifacts(artifacts: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(_ROLE_LIMITS):
        raise BundleError("Bundle requires exactly the eight fixed artifact roles")
    result: dict[str, bytes] = {}
    for role, limit in _ROLE_LIMITS.items():
        data = artifacts[role]
        if not isinstance(data, bytes) or not 0 < len(data) <= limit:
            raise BundleError(f"Artifact {role} must be immutable nonempty bytes within {limit}")
        result[role] = data
    return result


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    """Verified opaque immutable bytes, with fresh mutable views for callers."""

    manifest_bytes: bytes
    _contents: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        document = _manifest(self.manifest_bytes, BundleLimits())
        if type(self._contents) is not tuple or any(
            type(item) is not tuple or len(item) != 2 for item in self._contents
        ):
            raise BundleError("Bundle payload must be an immutable tuple of role/bytes pairs")
        try:
            contents = _artifacts(dict(self._contents))
        except (TypeError, ValueError) as error:
            raise BundleError("Invalid immutable artifact payload") from error
        if len(contents) != len(self._contents):
            raise BundleError("Duplicate bundle payload role")
        roles = cast("dict[str, dict[str, object]]", document["roles"])
        for role, data in contents.items():
            if _digest(data) != roles[role]["sha256"] or len(data) != roles[role]["size_bytes"]:
                raise BundleError("Bundle payload does not close its manifest references")

    @property
    def bundle_id(self) -> str:
        return _digest(self.manifest_bytes)

    @property
    def manifest(self) -> dict[str, object]:
        return cast("dict[str, object]", json.loads(self.manifest_bytes))

    @property
    def artifacts(self) -> dict[str, bytes]:
        return dict(self._contents)


def _prepare(artifacts: Mapping[str, bytes]) -> ArtifactBundle:
    payload = _artifacts(artifacts)
    roles = {
        role: {
            "sha256": _digest(data),
            "size_bytes": len(data),
            "ref": f"objects/sha256/{_digest(data)}",
        }
        for role, data in payload.items()
    }
    manifest = _canonical(
        {
            "kind": "evidence_bundle_v1",
            "schema_version": 1,
            "scope": "development_replay_v1",
            "roles": roles,
        }
    )
    return ArtifactBundle(manifest, tuple(sorted(payload.items())))


def _posix() -> None:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise BundleError("Bundle IO requires POSIX no-follow directory operations")


def _directory(parent: int, name: str) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _read_file(directory: int, name: str, limit: int, *, size: int | None = None) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BundleError("Bundle evidence must be a regular file")
        if before.st_size > limit or (size is not None and before.st_size != size):
            raise BundleError("Bundle evidence size does not match its budget/reference")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(descriptor)
        if len(data) > limit or (size is not None and len(data) != size):
            raise BundleError("Bundle evidence exceeds its budget/reference")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BundleError("Bundle evidence changed while being read")
        return data
    finally:
        os.close(descriptor)


def _tree_entries(directory: int, expected: Mapping[str, bool]) -> None:
    seen: set[str] = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise BundleError("Bundle symlink entries are forbidden, including hidden extras")
            if entry.name not in expected:
                raise BundleError("Bundle contains an unknown or extra entry")
            is_directory = stat.S_ISDIR(info.st_mode)
            if is_directory != expected[entry.name] or (
                not is_directory and not stat.S_ISREG(info.st_mode)
            ):
                raise BundleError("Bundle entry has an invalid file type")
            seen.add(entry.name)
    if seen != set(expected):
        raise BundleError("Bundle is missing a required entry")


class _RenameOperation(Protocol):
    argtypes: object
    restype: object

    def __call__(self, old_fd: int, old: bytes, new_fd: int, new: bytes, flags: int) -> int: ...


def _rename_operation() -> tuple[_RenameOperation, int]:
    # Only these two OS APIs have been selected; never fall back to replacing rename.
    if sys.platform == "darwin":
        symbol, flags = "renameatx_np", 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        symbol, flags = "renameat2", 1  # RENAME_NOREPLACE
    else:
        raise BundleError("Atomic no-replace bundle publication is unsupported on this platform")
    try:
        operation = cast("_RenameOperation", getattr(ctypes.CDLL(None, use_errno=True), symbol))
    except (AttributeError, OSError) as error:
        raise BundleError("Atomic no-replace bundle publication is unavailable in libc") from error
    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    return operation, flags


def _rename_exclusive(parent: int, source: str, target: str) -> None:
    operation, flags = _rename_operation()
    ctypes.set_errno(0)
    if operation(parent, os.fsencode(source), parent, os.fsencode(target), flags) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise BundleDestinationExistsError("Bundle destination already exists")
        if code in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
            raise BundleError(
                f"Filesystem does not support atomic no-replace publication (errno {code})"
            )
        raise OSError(code, os.strerror(code))


def _write_file(directory: int, name: str, data: bytes) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if _read_file(directory, name, len(data), size=len(data)) != data:
        raise BundleError("Written bundle evidence failed verification")


def export_bundle(destination: Path, artifacts: Mapping[str, bytes]) -> ArtifactBundle:
    """Publish below an existing trusted parent; never replace any destination."""
    bundle = _prepare(artifacts)  # Complete payload validation precedes filesystem changes.
    _posix()
    _rename_operation()  # Unsupported platforms fail before staging.
    destination = Path(destination).absolute()
    name = destination.name
    if not name or name in (".", ".."):
        raise BundleError("Destination must name a new directory under an existing parent")
    stage: str | None = None
    published = False
    try:
        with ExitStack() as stack:
            parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, parent)
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise BundleDestinationExistsError("Bundle destination already exists")
            stage = f".tickwitness-bundle-{secrets.token_hex(16)}"
            os.mkdir(stage, 0o700, dir_fd=parent)
            try:
                stage_fd = _directory(parent, stage)
                stack.callback(os.close, stage_fd)
                os.mkdir("objects", 0o700, dir_fd=stage_fd)
                objects = _directory(stage_fd, "objects")
                stack.callback(os.close, objects)
                os.mkdir("sha256", 0o700, dir_fd=objects)
                content = _directory(objects, "sha256")
                stack.callback(os.close, content)
                unique = {_digest(data): data for data in bundle.artifacts.values()}
                for digest, data in sorted(unique.items()):
                    _write_file(content, digest, data)
                os.fsync(content)
                os.fsync(objects)
                _write_file(stage_fd, "manifest.json", bundle.manifest_bytes)
                os.fsync(stage_fd)
                _rename_exclusive(parent, stage, name)
                published = True
                try:
                    os.fsync(parent)
                except OSError as error:
                    raise BundleDurabilityError(
                        "Complete bundle is published; parent fsync failed and crash durability "
                        "is unconfirmed. Preserve the directory and read/verify it."
                    ) from error
            finally:
                if not published:
                    with suppress(OSError):
                        shutil.rmtree(stage, dir_fd=parent)
            return bundle
    except BundleError:
        raise
    except OSError as error:
        raise BundleError(f"Bundle publication failed: {error.strerror}") from error


def read_bundle(root: Path, *, limits: BundleLimits = _DEFAULT_LIMITS) -> ArtifactBundle:
    """Read the exact fixed tree without writing, loading native code, or querying SQLite."""
    if not isinstance(limits, BundleLimits):
        raise BundleError("limits must be BundleLimits")
    _posix()
    try:
        with ExitStack() as stack:
            try:
                directory = os.open(
                    Path(root).absolute(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
            except FileNotFoundError as error:
                raise BundleNotFoundError("Bundle root does not exist") from error
            stack.callback(os.close, directory)
            _tree_entries(directory, {"manifest.json": False, "objects": True})
            raw = _read_file(directory, "manifest.json", limits.max_manifest_bytes)
            manifest = _manifest(raw, limits)
            roles = cast("dict[str, dict[str, object]]", manifest["roles"])
            object_sizes = {
                cast("str", reference["sha256"]): cast("int", reference["size_bytes"])
                for reference in roles.values()
            }
            objects = _directory(directory, "objects")
            stack.callback(os.close, objects)
            _tree_entries(objects, {"sha256": True})
            content = _directory(objects, "sha256")
            stack.callback(os.close, content)
            _tree_entries(content, {digest: False for digest in object_sizes})
            verified: dict[str, bytes] = {}
            for digest, size in sorted(object_sizes.items()):
                data = _read_file(content, digest, size, size=size)
                if _digest(data) != digest:
                    raise BundleError("Bundle object hash does not match its identity")
                verified[digest] = data
            payload = tuple(
                (role, verified[cast("str", roles[role]["sha256"])]) for role in sorted(roles)
            )
            return ArtifactBundle(raw, payload)
    except BundleError:
        raise
    except OSError as error:
        raise BundleError(f"Cannot safely read bundle: {error.strerror}") from error
