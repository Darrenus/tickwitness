"""Bounded immutable input preparations, without execution or ledger authority.

The source root is a publication exclusion boundary, not a restriction on where
a relocated preparation may be read. Root ancestors remain trusted owner
configuration; files inside the fixed tree are opened without following links.
"""

from __future__ import annotations

import os
import secrets
import shutil
from collections.abc import Callable, Mapping
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from tickwitness.domain.evidence.run_records import digest, identity, parse
from tickwitness.domain.reduction.contracts import (
    MAX_TOTAL_BYTES,
    build_reduction_manifest,
    role_limit,
)
from tickwitness.infrastructure import evidence_bundles as _io
from tickwitness.infrastructure.evidence_bundles import (
    BundleDurabilityError,
    BundleError,
    BundleNotFoundError,
)

_MANIFEST_LIMIT = 64 * 1024
_FILES = {
    "recipe": "recipe.json",
    "materialization": "materialization.json",
    "normalized": "normalized.jsonl",
}


class _PreparedReduction(Protocol):
    @property
    def preparation_id(self) -> str: ...
    @property
    def artifacts(self) -> dict[str, bytes]: ...


def _role_limit(role: str) -> int:
    try:
        return role_limit(role)
    except (TypeError, ValueError) as error:
        raise BundleError("Invalid reduction role: " + str(role)) from error


def _manifest(raw: bytes) -> dict[str, object]:
    try:
        value = parse(raw, limit=_MANIFEST_LIMIT)
        if (
            value.keys() != {"kind", "schema_version", "scope", "roles"}
            or value["kind"] != "reduction_preparation_bundle_v1"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["scope"] != "development_input_preparation_only_v1"
        ):
            raise BundleError("Unsupported reduction manifest fields or markers")
        roles = value["roles"]
        if not isinstance(roles, dict) or roles.keys() != _FILES.keys():
            raise BundleError("Reduction manifest requires exactly three fixed roles")
        total = len(raw)
        for role, filename in _FILES.items():
            reference = roles[role]
            if not isinstance(reference, dict) or reference.keys() != {
                "sha256",
                "size_bytes",
                "ref",
            }:
                raise BundleError("Reduction reference has missing or unknown fields")
            identity(reference["sha256"])
            size = reference["size_bytes"]
            if type(size) is not int or not 0 < size <= _role_limit(role):
                raise BundleError("Reduction artifact exceeds its nonempty byte budget: " + role)
            if reference["ref"] != filename:
                raise BundleError("Reduction artifact reference differs from its fixed filename")
            total += size
        if total > MAX_TOTAL_BYTES:
            raise BundleError("Reduction preparation exceeds its total byte budget")
        return value
    except BundleError:
        raise
    except (ValueError, TypeError) as error:
        raise BundleError("Invalid canonical reduction manifest: " + str(error)) from error


def _artifacts(value: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(value, Mapping) or value.keys() != _FILES.keys():
        raise BundleError("Reduction preparation requires exactly three fixed artifacts")
    contents: dict[str, bytes] = {}
    for role in _FILES:
        raw = value[role]
        if type(raw) is not bytes or not 0 < len(raw) <= _role_limit(role):
            raise BundleError(
                "Reduction artifact must be immutable nonempty bounded bytes: " + role
            )
        if role != "normalized":
            try:
                parse(raw, limit=_role_limit(role))
            except ValueError as error:
                raise BundleError("Reduction JSON artifact must be canonical: " + role) from error
        contents[role] = raw
    return contents


@dataclass(frozen=True, slots=True)
class ReductionInputBundle:
    manifest_bytes: bytes
    _contents: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        _manifest(self.manifest_bytes)
        if type(self._contents) is not tuple or any(
            type(pair) is not tuple or len(pair) != 2 for pair in self._contents
        ):
            raise BundleError("Reduction payload requires immutable role/bytes pairs")
        try:
            artifacts = _artifacts(dict(self._contents))
        except (ValueError, TypeError) as error:
            raise BundleError("Invalid immutable reduction payload") from error
        if len(artifacts) != len(self._contents):
            raise BundleError("Reduction payload contains a duplicate role")
        try:
            expected = build_reduction_manifest(artifacts)
        except (ValueError, TypeError) as error:
            raise BundleError("Invalid reduction artifact envelope: " + str(error)) from error
        if expected != self.manifest_bytes:
            raise BundleError("Reduction payload does not close its exact manifest references")

    @property
    def preparation_id(self) -> str:
        return digest(self.manifest_bytes)

    @property
    def artifacts(self) -> dict[str, bytes]:
        return dict(self._contents)


def _sync(directory: int, _phase: str) -> None:
    os.fsync(directory)


class LocalReductionBundles:
    """Exact four-file immutable publications outside the original input root."""

    def __init__(
        self,
        input_root: Path,
        *,
        writer: Callable[[int, str, bytes], None] = _io._write_file,
        sync: Callable[[int, str], None] = _sync,
    ) -> None:
        self._input_root = Path(input_root).absolute()
        self._writer, self._sync = writer, sync

    def read(self, path: Path) -> ReductionInputBundle:
        """Read any relocated preparation without creating or reading source state."""
        try:
            _io._posix()
            with ExitStack() as stack:
                try:
                    directory = os.open(
                        Path(path).absolute(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    )
                except FileNotFoundError as error:
                    raise BundleNotFoundError(
                        "Reduction preparation root does not exist"
                    ) from error
                stack.callback(os.close, directory)
                _io._tree_entries(
                    directory, {"manifest.json": False, **dict.fromkeys(_FILES.values(), False)}
                )
                raw = _io._read_file(directory, "manifest.json", _MANIFEST_LIMIT)
                manifest = _manifest(raw)
                references = cast("dict[str, dict[str, object]]", manifest["roles"])
                artifacts: dict[str, bytes] = {}
                for role, filename in _FILES.items():
                    size = cast("int", references[role]["size_bytes"])
                    data = _io._read_file(directory, filename, _role_limit(role), size=size)
                    if digest(data) != references[role]["sha256"]:
                        raise BundleError(
                            "Reduction artifact hash differs from its reference: " + role
                        )
                    artifacts[role] = data
                return ReductionInputBundle(raw, tuple(sorted(artifacts.items())))
        except BundleError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise BundleError("Cannot safely read reduction preparation: " + str(error)) from error

    def _outside_source(self, output: Path) -> None:
        try:
            if output.is_relative_to(self._input_root) or output.resolve().is_relative_to(
                self._input_root.resolve()
            ):
                raise BundleError("Reduction output must be outside the original input/source root")
        except (OSError, RuntimeError) as error:
            raise BundleError("Cannot validate reduction publication boundary") from error

    def publish(self, prepared: _PreparedReduction, output: Path) -> ReductionInputBundle:
        """Validate first, atomically publish, then verify the complete readback."""
        try:
            contents = _artifacts(prepared.artifacts)
            raw = build_reduction_manifest(contents)
            bundle = ReductionInputBundle(raw, tuple(sorted(contents.items())))
            if identity(prepared.preparation_id) != bundle.preparation_id:
                raise BundleError("Prepared reduction identity differs from its actual artifacts")
        except BundleError:
            raise
        except (ValueError, TypeError, AttributeError) as error:
            raise BundleError("Invalid prepared reduction publication: " + str(error)) from error
        _io._posix()
        _io._rename_operation()
        output = Path(output).absolute()
        self._outside_source(output)
        if not output.name or output.name in {".", ".."}:
            raise BundleError("Reduction output must name a new directory")
        published = False
        try:
            with ExitStack() as stack:
                parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, parent)
                try:
                    os.stat(output.name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise _io.BundleDestinationExistsError("Reduction output already exists")
                stage = ".tickwitness-reduction-" + secrets.token_hex(16)
                os.mkdir(stage, 0o700, dir_fd=parent)
                try:
                    directory = _io._directory(parent, stage)
                    stack.callback(os.close, directory)
                    for role, filename in _FILES.items():
                        self._writer(directory, filename, contents[role])
                    self._writer(directory, "manifest.json", bundle.manifest_bytes)
                    self._sync(directory, "stage")
                    self._outside_source(output)
                    _io._rename_exclusive(parent, stage, output.name)
                    published = True
                    try:
                        self._sync(parent, "parent")
                    except OSError as error:
                        raise BundleDurabilityError(
                            "Complete reduction preparation is published; parent sync failed. "
                            "Preserve and verify it; crash durability is unconfirmed."
                        ) from error
                finally:
                    if not published:
                        with suppress(OSError):
                            shutil.rmtree(stage, dir_fd=parent)
            readback = self.read(output)
            if readback != bundle:
                raise BundleError("Reduction preparation changed before publication readback")
            return readback
        except BundleError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise BundleError("Reduction preparation publication failed: " + str(error)) from error
