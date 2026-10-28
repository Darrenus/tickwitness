"""Bounded immutable variable-role search evidence directories.

This module verifies an opaque directory envelope. Actual source, candidate,
ledger and finding semantics are independently rebuilt by the application.
Parents are trusted configuration; no hostile-owner or authorship claim is made.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
from collections.abc import Mapping
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tickwitness.domain.evidence.search_evidence import (
    MAX_FILES,
    MAX_MANIFEST_BYTES,
    MAX_TOTAL_BYTES,
    REQUIRED_ROLES,
    role_limit,
)
from tickwitness.infrastructure import evidence_bundles as _io
from tickwitness.infrastructure.evidence_bundles import (
    BundleDestinationExistsError,
    BundleDurabilityError,
    BundleError,
    BundleNotFoundError,
)

_HASH = re.compile(r"[0-9a-f]{64}\Z")


class SearchEvidenceMissingObjectError(BundleError):
    """A manifest-declared object is absent, rather than a sealed absence."""

    code = "search_evidence_object_missing"

    def __init__(self, role: str, sha256: str, *, roles: tuple[str, ...] | None = None) -> None:
        self.role, self.sha256 = role, sha256
        self.roles = roles if roles is not None else (role,)
        super().__init__(
            "Missing search evidence object for role(s) " + ", ".join(self.roles) + ": " + sha256
        )


@dataclass(frozen=True, slots=True)
class SearchEvidenceLimits:
    """Profile-wide maxima can be tightened, never silently increased."""

    max_total_bytes: int = MAX_TOTAL_BYTES
    max_files: int = MAX_FILES
    max_manifest_bytes: int = MAX_MANIFEST_BYTES

    def __post_init__(self) -> None:
        for name, maximum in (
            ("max_total_bytes", MAX_TOTAL_BYTES),
            ("max_files", MAX_FILES),
            ("max_manifest_bytes", MAX_MANIFEST_BYTES),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise BundleError(name + " must be a positive integer within the search profile")


_DEFAULT_LIMITS = SearchEvidenceLimits()


def _checked_limits(limits: SearchEvidenceLimits) -> SearchEvidenceLimits:
    if type(limits) is not SearchEvidenceLimits:
        raise BundleError("limits must be SearchEvidenceLimits")
    return SearchEvidenceLimits(limits.max_total_bytes, limits.max_files, limits.max_manifest_bytes)


def _role_limit(role: object) -> int:
    try:
        return role_limit(cast("str", role))
    except (ValueError, TypeError) as error:
        raise BundleError("Unsupported search evidence role: " + str(role)) from error


def _manifest(raw: bytes, limits: SearchEvidenceLimits) -> dict[str, object]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limits.max_manifest_bytes:
        raise BundleError("Search evidence manifest exceeds its nonempty byte budget")
    try:
        value: object = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_io._unique,
            parse_float=_io._reject_number,
            parse_constant=_io._reject_number,
        )
        if not isinstance(value, dict) or value.keys() != {
            "kind",
            "schema_version",
            "scope",
            "roles",
        }:
            raise BundleError("Search evidence manifest has missing or unknown fields")
        if (
            value["kind"] != "search_evidence_bundle_v1"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["scope"] != "development_scoped_search_evidence_v1"
        ):
            raise BundleError("Unsupported search evidence bundle markers")
        roles = value["roles"]
        if not isinstance(roles, dict) or not roles.keys() >= REQUIRED_ROLES:
            raise BundleError("Search evidence manifest lacks mandatory roles")
        object_sizes: dict[str, int] = {}
        for role, reference in roles.items():
            maximum = _role_limit(role)
            if not isinstance(reference, dict) or reference.keys() != {
                "sha256",
                "size_bytes",
                "ref",
            }:
                raise BundleError("Search artifact reference has missing or unknown fields")
            sha, size = reference["sha256"], reference["size_bytes"]
            if not isinstance(sha, str) or _HASH.fullmatch(sha) is None:
                raise BundleError("Search object hash must be lowercase SHA-256 text")
            if type(size) is not int or not 0 < size <= maximum:
                raise BundleError("Search artifact " + role + " exceeds its nonempty byte budget")
            if reference["ref"] != "objects/sha256/" + sha:
                raise BundleError("Search object reference differs from its content address")
            if sha in object_sizes and object_sizes[sha] != size:
                raise BundleError("The same search object hash has conflicting declared sizes")
            object_sizes[sha] = size
        if len(object_sizes) + 1 > limits.max_files:
            raise BundleError("Search evidence exceeds max_files")
        if len(raw) + sum(object_sizes.values()) > limits.max_total_bytes:
            raise BundleError("Search evidence exceeds max_total_bytes")
        if _io._canonical(value) != raw:
            raise BundleError("Search evidence manifest must use exact canonical JSON")
    except BundleError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise BundleError("Invalid search evidence manifest UTF-8 or JSON") from error
    return cast("dict[str, object]", value)


def _artifacts(artifacts: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(artifacts, Mapping) or not artifacts.keys() >= REQUIRED_ROLES:
        raise BundleError("Search evidence requires every mandatory artifact role")
    result: dict[str, bytes] = {}
    for role, raw in artifacts.items():
        maximum = _role_limit(role)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= maximum:
            raise BundleError(
                "Search artifact " + role + " must be nonempty immutable bounded bytes"
            )
        result[role] = raw
    return result


@dataclass(frozen=True, slots=True)
class SearchEvidenceBundle:
    manifest_bytes: bytes
    _contents: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        document = _manifest(self.manifest_bytes, _DEFAULT_LIMITS)
        if type(self._contents) is not tuple or any(
            type(item) is not tuple or len(item) != 2 for item in self._contents
        ):
            raise BundleError("Search evidence payload must be immutable role/bytes pairs")
        try:
            payload = _artifacts(dict(self._contents))
        except (ValueError, TypeError) as error:
            raise BundleError("Invalid immutable search evidence payload") from error
        if len(payload) != len(self._contents):
            raise BundleError("Duplicate search evidence payload role")
        roles = cast("dict[str, dict[str, object]]", document["roles"])
        if payload.keys() != roles.keys():
            raise BundleError("Search evidence payload roles differ from its manifest")
        for role, data in payload.items():
            if _io._digest(data) != roles[role]["sha256"] or len(data) != roles[role]["size_bytes"]:
                raise BundleError("Search evidence payload does not close role " + role)

    @property
    def bundle_id(self) -> str:
        return _io._digest(self.manifest_bytes)

    @property
    def manifest(self) -> dict[str, object]:
        return cast("dict[str, object]", json.loads(self.manifest_bytes))

    @property
    def artifacts(self) -> dict[str, bytes]:
        return dict(self._contents)


def _prepare(artifacts: Mapping[str, bytes]) -> SearchEvidenceBundle:
    payload = _artifacts(artifacts)
    roles = {
        role: {
            "sha256": _io._digest(raw),
            "size_bytes": len(raw),
            "ref": "objects/sha256/" + _io._digest(raw),
        }
        for role, raw in payload.items()
    }
    manifest = _io._canonical(
        {
            "kind": "search_evidence_bundle_v1",
            "schema_version": 1,
            "scope": "development_scoped_search_evidence_v1",
            "roles": roles,
        }
    )
    return SearchEvidenceBundle(manifest, tuple(sorted(payload.items())))


def export_search_evidence_bundle(
    destination: Path, artifacts: Mapping[str, bytes]
) -> SearchEvidenceBundle:
    """Publish under an existing trusted parent; preserve any existing destination."""
    bundle = _prepare(artifacts)
    _io._posix()
    _io._rename_operation()
    destination = Path(destination).absolute()
    name = destination.name
    if not name or name in (".", ".."):
        raise BundleError("Destination must name a new search evidence directory")
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
                raise BundleDestinationExistsError("Search evidence destination already exists")
            stage = ".tickwitness-search-evidence-" + secrets.token_hex(16)
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
                unique = {_io._digest(raw): raw for raw in bundle.artifacts.values()}
                for sha, raw in sorted(unique.items()):
                    _io._write_file(content, sha, raw)
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
                        "Complete search evidence is published; parent fsync failed. "
                        "Preserve the directory and verify its content; "
                        "crash durability is unconfirmed."
                    ) from error
            finally:
                if not published:
                    with suppress(OSError):
                        shutil.rmtree(stage, dir_fd=parent)
            return bundle
    except BundleError:
        raise
    except OSError as error:
        raise BundleError("Search evidence publication failed: " + str(error)) from error


def _missing(sha: str, roles: Mapping[str, dict[str, object]]) -> SearchEvidenceMissingObjectError:
    names = tuple(sorted(name for name, ref in roles.items() if ref["sha256"] == sha))
    return SearchEvidenceMissingObjectError(names[0], sha, roles=names)


def _object_tree(content: int, roles: Mapping[str, dict[str, object]]) -> None:
    expected = {cast("str", reference["sha256"]) for reference in roles.values()}
    seen: set[str] = set()
    with os.scandir(content) as entries:
        for entry in entries:
            if entry.name not in expected:
                raise BundleError("Search evidence contains an unknown or extra object")
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError as error:
                raise _missing(entry.name, roles) from error
            if not stat.S_ISREG(info.st_mode):
                raise BundleError("Search evidence object must be a regular non-symlink file")
            seen.add(entry.name)
    missing = expected - seen
    if missing:
        raise _missing(sorted(missing)[0], roles)


def read_search_evidence_bundle(
    root: Path, *, limits: SearchEvidenceLimits = _DEFAULT_LIMITS
) -> SearchEvidenceBundle:
    """Read a bounded fixed directory tree without execution, SQLite or writes."""
    limits = _checked_limits(limits)
    _io._posix()
    try:
        with ExitStack() as stack:
            try:
                directory = os.open(
                    Path(root).absolute(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
            except FileNotFoundError as error:
                raise BundleNotFoundError("Search evidence root does not exist") from error
            stack.callback(os.close, directory)
            raw = _io._read_file(directory, "manifest.json", limits.max_manifest_bytes)
            manifest = _manifest(raw, limits)
            roles = cast("dict[str, dict[str, object]]", manifest["roles"])
            sizes = {
                cast("str", ref["sha256"]): cast("int", ref["size_bytes"]) for ref in roles.values()
            }
            try:
                objects = _io._directory(directory, "objects")
                stack.callback(os.close, objects)
                content = _io._directory(objects, "sha256")
                stack.callback(os.close, content)
            except FileNotFoundError as error:
                raise _missing(sorted(sizes)[0], roles) from error
            verified: dict[str, bytes] = {}
            for sha, size in sorted(sizes.items()):
                try:
                    data = _io._read_file(content, sha, size, size=size)
                except FileNotFoundError as error:
                    raise _missing(sha, roles) from error
                if _io._digest(data) != sha:
                    raise BundleError("Search evidence object hash differs from its identity")
                verified[sha] = data
            _object_tree(content, roles)
            _io._tree_entries(objects, {"sha256": True})
            _io._tree_entries(directory, {"manifest.json": False, "objects": True})
            payload = tuple(
                (role, verified[cast("str", roles[role]["sha256"])]) for role in sorted(roles)
            )
            return SearchEvidenceBundle(raw, payload)
    except BundleError:
        raise
    except OSError as error:
        raise BundleError("Cannot safely read search evidence: " + str(error)) from error
