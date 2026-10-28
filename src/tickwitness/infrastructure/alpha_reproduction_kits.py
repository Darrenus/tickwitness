"""Bounded transferable alpha kits; included code is opaque and never executed.

Parents are trusted configuration. File descriptors, exact trees and no-follow
opens protect the envelope. Pins describe content integrity, not authorship.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from collections.abc import Callable, Mapping
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from tickwitness.domain.evidence.alpha_scorecard import load_alpha_suite
from tickwitness.domain.evidence.run_records import canonical, digest, identity, parse
from tickwitness.infrastructure import evidence_bundles as _io
from tickwitness.infrastructure.search_evidence_bundles import SearchEvidenceBundle

MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILES = 512
MAX_MANIFEST_BYTES = 256 * 1024
MAX_WHEEL_BYTES = 4 * 1024 * 1024
MAX_GUIDE_BYTES = 64 * 1024
MAX_RUNNER_BYTES = 64 * 1024
_WHEEL = re.compile(r"tickwitness-[0-9][A-Za-z0-9._+]*-py3-none-any\.whl\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_CASE_PATH = re.compile(
    r"cases/(?:counterexample|clean-control)/(?:manifest\.json|objects/sha256/[0-9a-f]{64})\Z"
)
_CASE_NAMES = {"counterexample": "counterexample", "clean_control": "clean-control"}


class AlphaKitError(ValueError):
    """The kit envelope, resource profile, IO or content pin is invalid."""


class AlphaKitNotFoundError(AlphaKitError):
    """The requested kit root does not exist; nothing was created."""


class AlphaKitDestinationExistsError(AlphaKitError):
    """Publication refused an existing destination without changing it."""


class AlphaKitDurabilityError(AlphaKitError):
    """A complete kit remains published, with crash durability unconfirmed."""


class _SearchPackage(Protocol):
    @property
    def manifest_bytes(self) -> bytes: ...
    @property
    def bundle_id(self) -> str: ...
    @property
    def artifacts(self) -> dict[str, bytes]: ...


@dataclass(frozen=True, slots=True)
class AlphaKitLimits:
    max_total_bytes: int = MAX_TOTAL_BYTES
    max_files: int = MAX_FILES
    max_manifest_bytes: int = MAX_MANIFEST_BYTES
    max_wheel_bytes: int = MAX_WHEEL_BYTES
    max_guide_bytes: int = MAX_GUIDE_BYTES
    max_runner_bytes: int = MAX_RUNNER_BYTES

    def __post_init__(self) -> None:
        for name, maximum in (
            ("max_total_bytes", MAX_TOTAL_BYTES),
            ("max_files", MAX_FILES),
            ("max_manifest_bytes", MAX_MANIFEST_BYTES),
            ("max_wheel_bytes", MAX_WHEEL_BYTES),
            ("max_guide_bytes", MAX_GUIDE_BYTES),
            ("max_runner_bytes", MAX_RUNNER_BYTES),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise AlphaKitError(name + " must only tighten its positive alpha profile limit")


_DEFAULT_LIMITS = AlphaKitLimits()


def _limits(limits: AlphaKitLimits) -> AlphaKitLimits:
    if type(limits) is not AlphaKitLimits:
        raise AlphaKitError("limits must be AlphaKitLimits")
    return AlphaKitLimits(
        limits.max_total_bytes,
        limits.max_files,
        limits.max_manifest_bytes,
        limits.max_wheel_bytes,
        limits.max_guide_bytes,
        limits.max_runner_bytes,
    )


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= 64
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise AlphaKitError("Producer version must be clean nonempty text within 64 characters")
    value.encode("utf-8", errors="strict")
    return value


def _manifest(raw: bytes, limits: AlphaKitLimits) -> dict[str, object]:
    try:
        value = parse(raw, limit=limits.max_manifest_bytes)
        if (
            value.keys()
            != {"kind", "schema_version", "scope", "producer", "suite", "wheel_path", "files"}
            or value["kind"] != "alpha_reproduction_kit_v1"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["scope"] != "development_technical_alpha_v1"
        ):
            raise AlphaKitError("Unsupported alpha kit markers or fields")
        producer = value["producer"]
        if not isinstance(producer, dict) or producer.keys() != {"version", "source_revision"}:
            raise AlphaKitError("Alpha producer has missing or unknown fields")
        _text(producer["version"])
        revision = producer["source_revision"]
        if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
            raise AlphaKitError("Source revision must be 40 lowercase hexadecimal characters")
        if not isinstance(value["suite"], dict):
            raise AlphaKitError("Alpha kit requires a complete suite document")
        load_alpha_suite(canonical(cast("dict[str, object]", value["suite"])))
        wheel = value["wheel_path"]
        if (
            not isinstance(wheel, str)
            or not wheel.startswith("distribution/")
            or _WHEEL.fullmatch(wheel.removeprefix("distribution/")) is None
            or len(wheel) > 240
        ):
            raise AlphaKitError("Alpha kit requires one TickWitness universal wheel basename")
        files = value["files"]
        if (
            not isinstance(files, dict)
            or not {
                "README.md",
                "reproduce.py",
                wheel,
                "cases/counterexample/manifest.json",
                "cases/clean-control/manifest.json",
            }
            <= files.keys()
        ):
            raise AlphaKitError("Alpha kit is missing a fixed required file")
        if len(files) + 1 > limits.max_files:
            raise AlphaKitError("Alpha kit exceeds max_files")
        total = len(raw)
        for path, reference in files.items():
            if path not in {"README.md", "reproduce.py", wheel} and (
                not isinstance(path, str) or _CASE_PATH.fullmatch(path) is None
            ):
                raise AlphaKitError("Unknown or unsafe alpha kit path")
            if not isinstance(reference, dict) or reference.keys() != {"sha256", "size_bytes"}:
                raise AlphaKitError("Alpha file reference has missing or unknown fields")
            identity(reference["sha256"])
            size = reference["size_bytes"]
            maximum = {
                "README.md": limits.max_guide_bytes,
                "reproduce.py": limits.max_runner_bytes,
                wheel: limits.max_wheel_bytes,
            }.get(path, limits.max_total_bytes)
            if type(size) is not int or not 0 < size <= maximum:
                raise AlphaKitError("Alpha file exceeds its nonempty byte limit: " + path)
            total += size
        if total > limits.max_total_bytes:
            raise AlphaKitError("Alpha kit exceeds max_total_bytes")
        return value
    except AlphaKitError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise AlphaKitError("Invalid alpha kit manifest: " + str(error)) from error


def _case(files: Mapping[str, bytes], name: str) -> SearchEvidenceBundle:
    if name not in _CASE_NAMES:
        raise AlphaKitError("Unknown alpha case name")
    prefix = "cases/" + _CASE_NAMES[name] + "/"
    try:
        raw = files[prefix + "manifest.json"]
        document = parse(raw, limit=2 * 1024 * 1024)
        roles = document["roles"]
        if not isinstance(roles, dict):
            raise AlphaKitError("Nested search bundle roles must be an object")
        expected = {prefix + "manifest.json"}
        contents: list[tuple[str, bytes]] = []
        for role, reference in roles.items():
            if not isinstance(reference, dict) or not isinstance(reference.get("ref"), str):
                raise AlphaKitError("Invalid nested search bundle reference")
            path = prefix + reference["ref"]
            expected.add(path)
            contents.append((role, files[path]))
        if {path for path in files if path.startswith(prefix)} != expected:
            raise AlphaKitError("Nested search bundle has missing or extra files")
        return SearchEvidenceBundle(raw, tuple(sorted(contents)))
    except AlphaKitError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise AlphaKitError("Invalid nested alpha search bundle: " + str(error)) from error


@dataclass(frozen=True, slots=True)
class AlphaReproductionKit:
    manifest_bytes: bytes
    _files: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        document = _manifest(self.manifest_bytes, _DEFAULT_LIMITS)
        if type(self._files) is not tuple or any(
            type(pair) is not tuple or len(pair) != 2 for pair in self._files
        ):
            raise AlphaKitError("Alpha kit files require immutable path/bytes pairs")
        try:
            files = dict(self._files)
        except (TypeError, ValueError) as error:
            raise AlphaKitError("Invalid immutable alpha file inventory") from error
        references = cast("dict[str, dict[str, object]]", document["files"])
        if len(files) != len(self._files) or files.keys() != references.keys():
            raise AlphaKitError("Alpha payload does not match the exact file inventory")
        for path, data in files.items():
            if (
                type(data) is not bytes
                or len(data) != references[path]["size_bytes"]
                or digest(data) != references[path]["sha256"]
            ):
                raise AlphaKitError("Alpha file does not match its content reference: " + path)
        suite = load_alpha_suite(canonical(cast("dict[str, object]", document["suite"])))
        cases = cast("dict[str, dict[str, object]]", suite.document["cases"])
        for name in _CASE_NAMES:
            if _case(files, name).bundle_id != cases[name]["bundle_id"]:
                raise AlphaKitError("Alpha nested bundle differs from its suite pin")

    @property
    def kit_id(self) -> str:
        return digest(self.manifest_bytes)

    @property
    def manifest(self) -> dict[str, object]:
        return cast("dict[str, object]", json.loads(self.manifest_bytes))

    @property
    def files(self) -> dict[str, bytes]:
        return dict(self._files)

    @property
    def suite_bytes(self) -> bytes:
        return canonical(cast("dict[str, object]", self.manifest["suite"]))

    def case(self, name: str) -> SearchEvidenceBundle:
        return _case(self.files, name)


def _package_files(package: _SearchPackage, name: str) -> dict[str, bytes]:
    checked = SearchEvidenceBundle(package.manifest_bytes, tuple(sorted(package.artifacts.items())))
    if checked.bundle_id != package.bundle_id:
        raise AlphaKitError("Supplied search package identity differs")
    prefix = "cases/" + _CASE_NAMES[name] + "/"
    files = {prefix + "manifest.json": checked.manifest_bytes}
    for data in checked.artifacts.values():
        files[prefix + "objects/sha256/" + digest(data)] = data
    return files


def export_alpha_kit(
    destination: Path,
    *,
    suite_bytes: bytes,
    wheel_name: str,
    wheel_bytes: bytes,
    guide_bytes: bytes,
    runner_bytes: bytes,
    counterexample: _SearchPackage,
    clean_control: _SearchPackage,
    producer_version: str,
    source_revision: str,
) -> AlphaReproductionKit:
    """Build the exact opaque closure, then publish under an existing parent."""
    try:
        suite = load_alpha_suite(suite_bytes)
        files = {
            "README.md": guide_bytes,
            "reproduce.py": runner_bytes,
            "distribution/" + wheel_name: wheel_bytes,
            **_package_files(counterexample, "counterexample"),
            **_package_files(clean_control, "clean_control"),
        }
        raw = canonical(
            {
                "kind": "alpha_reproduction_kit_v1",
                "schema_version": 1,
                "scope": "development_technical_alpha_v1",
                "producer": {"version": producer_version, "source_revision": source_revision},
                "suite": suite.document,
                "wheel_path": "distribution/" + wheel_name,
                "files": {
                    path: {"sha256": digest(data), "size_bytes": len(data)}
                    for path, data in files.items()
                },
            }
        )
        kit = AlphaReproductionKit(raw, tuple(sorted(files.items())))
        return publish_alpha_kit(destination, kit)
    except AlphaKitError:
        raise
    except (ValueError, TypeError, AttributeError) as error:
        raise AlphaKitError("Invalid alpha kit assembly: " + str(error)) from error


def _tree(paths: Mapping[str, object]) -> dict[str, object]:
    tree: dict[str, object] = {}
    for path in paths:
        current = tree
        segments = path.split("/")
        for segment in segments[:-1]:
            current = cast("dict[str, object]", current.setdefault(segment, {}))
        current[segments[-1]] = None
    return tree


def _read_tree(
    directory: int,
    tree: dict[str, object],
    references: dict[str, dict[str, object]],
    prefix: str,
    files: dict[str, bytes],
) -> None:
    _io._tree_entries(directory, {name: isinstance(child, dict) for name, child in tree.items()})
    for name, child in sorted(tree.items()):
        path = prefix + name
        if isinstance(child, dict):
            descriptor = _io._directory(directory, name)
            try:
                _read_tree(descriptor, child, references, path + "/", files)
            finally:
                os.close(descriptor)
        elif path != "manifest.json":
            reference = references[path]
            size = cast("int", reference["size_bytes"])
            raw = _io._read_file(directory, name, size, size=size)
            if digest(raw) != reference["sha256"]:
                raise AlphaKitError("Alpha file hash differs from its manifest: " + path)
            files[path] = raw


def read_alpha_kit(
    root: Path,
    *,
    expected_kit_id: str | None = None,
    limits: AlphaKitLimits = _DEFAULT_LIMITS,
) -> AlphaReproductionKit:
    """Read the exact bounded closure without executing code or changing files."""
    try:
        limits = _limits(limits)
        if expected_kit_id is not None:
            identity(expected_kit_id)
        _io._posix()
        with ExitStack() as stack:
            try:
                directory = os.open(
                    Path(root).absolute(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
            except FileNotFoundError as error:
                raise AlphaKitNotFoundError("Alpha kit root does not exist") from error
            stack.callback(os.close, directory)
            raw = _io._read_file(directory, "manifest.json", limits.max_manifest_bytes)
            if expected_kit_id is not None and digest(raw) != expected_kit_id:
                raise AlphaKitError("Alpha kit differs from the expected pinned identity")
            manifest = _manifest(raw, limits)
            references = cast("dict[str, dict[str, object]]", manifest["files"])
            files: dict[str, bytes] = {}
            _read_tree(
                directory, _tree({"manifest.json": None, **references}), references, "", files
            )
            return AlphaReproductionKit(raw, tuple(sorted(files.items())))
    except AlphaKitError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise AlphaKitError("Cannot safely read alpha kit: " + str(error)) from error


def _sync(directory: int, _phase: str) -> None:
    os.fsync(directory)


def _write_tree(
    directory: int,
    tree: dict[str, object],
    files: dict[str, bytes],
    prefix: str,
    writer: Callable[[int, str, bytes], None],
    sync: Callable[[int, str], None],
) -> None:
    for name, child in sorted(tree.items()):
        path = prefix + name
        if isinstance(child, dict):
            os.mkdir(name, 0o700, dir_fd=directory)
            descriptor = _io._directory(directory, name)
            try:
                _write_tree(descriptor, child, files, path + "/", writer, sync)
            finally:
                os.close(descriptor)
        else:
            writer(directory, name, files[path])
    sync(directory, "stage")


def _publish_alpha_kit(
    destination: Path,
    kit: AlphaReproductionKit,
    *,
    writer: Callable[[int, str, bytes], None] = _io._write_file,
    sync: Callable[[int, str], None] = _sync,
) -> AlphaReproductionKit:
    """Private per-call hooks support controlled scratch probes, never kit inputs."""
    published = False
    try:
        if type(kit) is not AlphaReproductionKit:
            raise AlphaKitError("Publisher requires an immutable AlphaReproductionKit")
        kit = AlphaReproductionKit(kit.manifest_bytes, kit._files)
        _io._posix()
        _io._rename_operation()
        destination = Path(destination).absolute()
        if not destination.name or destination.name in {".", ".."}:
            raise AlphaKitError("Alpha output must name a new directory")
        with ExitStack() as stack:
            parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, parent)
            try:
                os.stat(destination.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise AlphaKitDestinationExistsError("Alpha kit destination already exists")
            stage = ".tickwitness-alpha-kit-" + secrets.token_hex(16)
            os.mkdir(stage, 0o700, dir_fd=parent)
            try:
                directory = _io._directory(parent, stage)
                stack.callback(os.close, directory)
                files = {"manifest.json": kit.manifest_bytes, **kit.files}
                _write_tree(directory, _tree(files), files, "", writer, sync)
                try:
                    _io._rename_exclusive(parent, stage, destination.name)
                except _io.BundleDestinationExistsError as error:
                    raise AlphaKitDestinationExistsError(str(error)) from error
                published = True
                try:
                    sync(parent, "parent")
                except OSError as error:
                    raise AlphaKitDurabilityError(
                        "Complete alpha kit is published; parent sync failed. Preserve and "
                        "verify the artifact; crash durability is unconfirmed."
                    ) from error
            finally:
                if not published:
                    with suppress(OSError):
                        shutil.rmtree(stage, dir_fd=parent)
        # A receipt only follows exact readback, never a saved success flag.
        return read_alpha_kit(destination, expected_kit_id=kit.kit_id)
    except AlphaKitError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise AlphaKitError("Alpha kit publication failed: " + str(error)) from error


def publish_alpha_kit(destination: Path, kit: AlphaReproductionKit) -> AlphaReproductionKit:
    """Atomically publish without replacing any existing path or following links."""
    return _publish_alpha_kit(destination, kit)
