"""Fixed, immutable tagged-pair evidence directories with independent markers.

The opaque IO envelope does not certify a claim, execute native code, or access
an original catalog/ledger. Semantic closure belongs to the domain verifier.
The legacy eight-role bundle contract is unchanged. Both formats share only the
POSIX no-follow, bounded regular-file and no-replace publication primitives.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from collections.abc import Mapping
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tickwitness.infrastructure import evidence_bundles as _io
from tickwitness.infrastructure.evidence_bundles import (
    BundleDestinationExistsError,
    BundleDurabilityError,
    BundleError,
    BundleLimits,
    BundleNotFoundError,
)

_MIB = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ROLE_LIMITS = {
    "protocol": 256 * 1024,
    "dataset_manifest": 64 * 1024,
    "raw": 8 * _MIB,
    "normalized": 8 * _MIB,
    "report": 4 * _MIB,
    "front_result": 16 * _MIB,
    "front_evaluation": 64 * 1024,
    "front_receipt": _MIB,
    "back_result": 16 * _MIB,
    "back_evaluation": 64 * 1024,
    "back_receipt": _MIB,
    "assessment": 256 * 1024,
}
_DEFAULT_LIMITS = BundleLimits()


def _manifest(raw: bytes, limits: BundleLimits) -> dict[str, object]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limits.max_manifest_bytes:
        raise BundleError("Manifest exceeds its nonempty byte budget")
    try:
        value: object = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_io._unique,
            parse_float=_io._reject_number,
            parse_constant=_io._reject_number,
        )
        if not isinstance(value, dict) or set(value) != {
            "kind",
            "schema_version",
            "scope",
            "roles",
        }:
            raise BundleError("Manifest has missing or unknown fields")
        if (
            value["kind"] != "tagged_queue_pair_evidence_bundle_v1"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["scope"] != "development_tagged_queue_pair_v1"
        ):
            raise BundleError("Unsupported evidence bundle markers")
        roles = value["roles"]
        if not isinstance(roles, dict) or set(roles) != set(_ROLE_LIMITS):
            raise BundleError("Bundle requires exactly the twelve fixed artifact roles")
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
        if _io._canonical(value) != raw:
            raise BundleError("Manifest must use exact canonical JSON encoding")
    except BundleError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise BundleError("Invalid UTF-8 or manifest JSON") from error
    return cast("dict[str, object]", value)


def _artifacts(artifacts: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(_ROLE_LIMITS):
        raise BundleError("Bundle requires exactly the twelve fixed artifact roles")
    result: dict[str, bytes] = {}
    for role, limit in _ROLE_LIMITS.items():
        data = artifacts[role]
        if not isinstance(data, bytes) or not 0 < len(data) <= limit:
            raise BundleError(f"Artifact {role} must be immutable nonempty bytes within {limit}")
        result[role] = data
    return result


@dataclass(frozen=True, slots=True)
class TaggedPairArtifactBundle:
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
            if _io._digest(data) != roles[role]["sha256"] or len(data) != roles[role]["size_bytes"]:
                raise BundleError("Bundle payload does not close its manifest references")

    @property
    def bundle_id(self) -> str:
        return _io._digest(self.manifest_bytes)

    @property
    def manifest(self) -> dict[str, object]:
        return cast("dict[str, object]", json.loads(self.manifest_bytes))

    @property
    def artifacts(self) -> dict[str, bytes]:
        return dict(self._contents)


def _prepare(artifacts: Mapping[str, bytes]) -> TaggedPairArtifactBundle:
    payload = _artifacts(artifacts)
    roles = {
        role: {
            "sha256": _io._digest(data),
            "size_bytes": len(data),
            "ref": f"objects/sha256/{_io._digest(data)}",
        }
        for role, data in payload.items()
    }
    manifest = _io._canonical(
        {
            "kind": "tagged_queue_pair_evidence_bundle_v1",
            "schema_version": 1,
            "scope": "development_tagged_queue_pair_v1",
            "roles": roles,
        }
    )
    return TaggedPairArtifactBundle(manifest, tuple(sorted(payload.items())))


def export_tagged_pair_bundle(
    destination: Path, artifacts: Mapping[str, bytes]
) -> TaggedPairArtifactBundle:
    """Publish below an existing trusted parent; never replace any destination."""
    bundle = _prepare(artifacts)  # Complete payload validation precedes filesystem changes.
    _io._posix()
    _io._rename_operation()  # Unsupported platforms fail before staging.
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
            stage = f".tickwitness-tagged-pair-{secrets.token_hex(16)}"
            os.mkdir(stage, 0o700, dir_fd=parent)
            try:
                stage_fd = _io._directory(parent, stage)
                stack.callback(os.close, stage_fd)
                os.mkdir("objects", 0o700, dir_fd=stage_fd)
                objects = _io._directory(stage_fd, "objects")
                stack.callback(os.close, objects)
                os.mkdir("sha256", 0o700, dir_fd=objects)
                content = _io._directory(objects, "sha256")
                stack.callback(os.close, content)
                unique = {_io._digest(data): data for data in bundle.artifacts.values()}
                for digest, data in sorted(unique.items()):
                    _io._write_file(content, digest, data)
                os.fsync(content)
                os.fsync(objects)
                _io._write_file(stage_fd, "manifest.json", bundle.manifest_bytes)
                os.fsync(stage_fd)
                _io._rename_exclusive(parent, stage, name)
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


def read_tagged_pair_bundle(
    root: Path, *, limits: BundleLimits = _DEFAULT_LIMITS
) -> TaggedPairArtifactBundle:
    """Read the exact fixed tree without writing, loading native code, or querying SQLite."""
    if not isinstance(limits, BundleLimits):
        raise BundleError("limits must be BundleLimits")
    _io._posix()
    try:
        with ExitStack() as stack:
            try:
                directory = os.open(
                    Path(root).absolute(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
            except FileNotFoundError as error:
                raise BundleNotFoundError("Bundle root does not exist") from error
            stack.callback(os.close, directory)
            _io._tree_entries(directory, {"manifest.json": False, "objects": True})
            raw = _io._read_file(directory, "manifest.json", limits.max_manifest_bytes)
            manifest = _manifest(raw, limits)
            roles = cast("dict[str, dict[str, object]]", manifest["roles"])
            object_sizes = {
                cast("str", reference["sha256"]): cast("int", reference["size_bytes"])
                for reference in roles.values()
            }
            objects = _io._directory(directory, "objects")
            stack.callback(os.close, objects)
            _io._tree_entries(objects, {"sha256": True})
            content = _io._directory(objects, "sha256")
            stack.callback(os.close, content)
            _io._tree_entries(content, {digest: False for digest in object_sizes})
            verified: dict[str, bytes] = {}
            for digest, size in sorted(object_sizes.items()):
                data = _io._read_file(content, digest, size, size=size)
                if _io._digest(data) != digest:
                    raise BundleError("Bundle object hash does not match its identity")
                verified[digest] = data
            payload = tuple(
                (role, verified[cast("str", roles[role]["sha256"])]) for role in sorted(roles)
            )
            return TaggedPairArtifactBundle(raw, payload)
    except BundleError:
        raise
    except OSError as error:
        raise BundleError(f"Cannot safely read bundle: {error.strerror}") from error
