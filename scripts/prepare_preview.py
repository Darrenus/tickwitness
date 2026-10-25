#!/usr/bin/env python3
"""Check built TickWitness candidates and prepare unsigned, unpublished metadata.

This is a packaging helper, not a publisher or a test/provenance attestation.
Archives are read in place, never extracted or executed. Run from a clean Git
checkout after building the current version into an otherwise empty dist/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import cast

_PROJECT = "tickwitness"
_DERIVED = {"preview-manifest.json", "SHA256SUMS"}
_BUILD_CONTROL = {".gitignore"}  # uv build creates this; it is not a release asset.
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+|\.dev[0-9]+)?\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_METADATA_LIMIT = 256 * 1024
_SOURCE_ROOTS = (
    "src",
    "docs",
    "scripts",
    "research",
    ".github",
    ".python-version",
    "Makefile",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "pyproject.toml",
    "uv.lock",
    "LICENSE",
    "NOTICE",
)


class PreviewError(ValueError):
    """The proposed files cannot be identified as this checkout's preview inputs."""


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise PreviewError(f"Expected a regular non-symlink file: {path.name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit(root: Path) -> str:
    def git(*arguments: str) -> str:
        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", "-C", str(root), *arguments],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise PreviewError("Cannot read the source Git checkout") from error
        if result.returncode:
            raise PreviewError("Cannot identify the source Git checkout")
        return result.stdout.strip()

    commit = git("rev-parse", "--verify", "HEAD")
    if _COMMIT.fullmatch(commit) is None:
        raise PreviewError("Git HEAD is not a complete supported commit identity")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise PreviewError("Source checkout must be clean, including non-ignored untracked files")
    return commit


def _tracked_sources(root: Path) -> dict[str, Path]:
    """Select committed source/support files without including build/import caches."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), "ls-files", "-z", "--", *_SOURCE_ROOTS],
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise PreviewError("Cannot enumerate committed source/support files") from error
    if result.returncode:
        raise PreviewError("Cannot enumerate committed source/support files")
    try:
        names = result.stdout.decode("utf-8").rstrip("\x00").split("\x00")
    except UnicodeError as error:
        raise PreviewError("Tracked source paths must use UTF-8") from error
    sources: dict[str, Path] = {}
    for name in names:
        _archive_path(name)
        source = root / name
        _regular(source)
        sources[name] = source
    required = {
        "src/tickwitness/__init__.py",
        ".python-version",
        "Makefile",
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
        "NOTICE",
    }
    if not required <= sources.keys():
        raise PreviewError("Committed source/support files are incomplete")
    return sources


def _project_version(root: Path) -> tuple[str, bytes, bytes]:
    project_file, lock_file = root / "pyproject.toml", root / "uv.lock"
    _regular(project_file)
    _regular(lock_file)
    project_bytes, lock_bytes = project_file.read_bytes(), lock_file.read_bytes()
    try:
        project = tomllib.loads(project_bytes.decode("utf-8"))["project"]
        lock = tomllib.loads(lock_bytes.decode("utf-8"))
    except (ValueError, UnicodeError, KeyError) as error:
        raise PreviewError("Cannot read project and locked package metadata") from error
    if not isinstance(project, dict) or project.get("name") != _PROJECT:
        raise PreviewError("This helper prepares the TickWitness project only")
    version = project.get("version")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise PreviewError("Project version is outside this helper's supported filename format")
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise PreviewError("uv.lock has no package list")
    own = [value for value in packages if isinstance(value, dict) and value.get("name") == _PROJECT]
    if (
        len(own) != 1
        or own[0].get("version") != version
        or own[0].get("source") != {"editable": "."}
    ):
        raise PreviewError("uv.lock must bind exactly this local project name/version")
    return version, project_bytes, lock_bytes


def _archive_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))
    ):
        raise PreviewError("Archive contains an unsupported member path")
    return path


def _metadata(raw: bytes, version: str) -> None:
    if not raw or len(raw) > _METADATA_LIMIT:
        raise PreviewError("Distribution metadata is empty or oversized")
    message = BytesParser().parsebytes(raw)
    if message.get_all("Name") != [_PROJECT] or message.get_all("Version") != [version]:
        raise PreviewError("Distribution Name/Version metadata differs from pyproject.toml")
    license_files = message.get_all("License-File", [])
    if len(license_files) != 2 or set(license_files) != {"LICENSE", "NOTICE"}:
        raise PreviewError("Distribution must declare exactly LICENSE and NOTICE")


def _wheel(path: Path, root: Path, version: str) -> None:
    expected = f"{_PROJECT}-{version}.dist-info/METADATA"
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            seen: set[str] = set()
            metadata_names: list[str] = []
            for entry in entries:
                _archive_path(entry.filename)
                if entry.filename in seen or stat.S_ISLNK(entry.external_attr >> 16):
                    raise PreviewError("Wheel contains duplicate members or a symbolic link")
                seen.add(entry.filename)
                if entry.filename.endswith(".dist-info/METADATA"):
                    metadata_names.append(entry.filename)
            if metadata_names != [expected]:
                raise PreviewError("Wheel must contain exactly the expected distribution metadata")
            if archive.getinfo(expected).file_size > _METADATA_LIMIT:
                raise PreviewError("Wheel metadata exceeds its size limit")
            _metadata(archive.read(expected), version)
            for filename in ("LICENSE", "NOTICE"):
                source = root / filename
                _regular(source)
                original = source.read_bytes()
                member = f"{_PROJECT}-{version}.dist-info/licenses/{filename}"
                if member not in seen or archive.getinfo(member).file_size != len(original):
                    raise PreviewError(f"Wheel is missing or resizing {filename}")
                if archive.read(member) != original:
                    raise PreviewError(f"Wheel {filename} differs from the checkout")
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise PreviewError("Cannot read the wheel archive") from error


def _examples(root: Path) -> dict[str, Path]:
    directory = root / "examples"
    if directory.is_symlink() or not directory.is_dir():
        raise PreviewError("Source examples directory is missing or is a symlink")
    result: dict[str, Path] = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise PreviewError("Source examples cannot contain symlinks")
        if path.is_dir():
            continue
        _regular(path)
        result[path.relative_to(root).as_posix()] = path
    if not result:
        raise PreviewError("Source examples directory cannot be empty")
    return result


def _sdist(
    path: Path,
    root: Path,
    version: str,
    project_bytes: bytes,
    lock_bytes: bytes,
    sources: dict[str, Path],
) -> None:
    prefix = f"{_PROJECT}-{version}"
    examples = _examples(root)
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            files: dict[str, tarfile.TarInfo] = {}
            seen: set[str] = set()
            for member in archive.getmembers():
                name = _archive_path(member.name)
                if not name.parts or name.parts[0] != prefix:
                    raise PreviewError("Source archive has an unexpected top-level directory")
                normalized = name.as_posix()
                if normalized in seen or not (member.isfile() or member.isdir()):
                    raise PreviewError("Source archive has duplicate, link, or special members")
                seen.add(normalized)
                if member.isfile():
                    files[name.relative_to(prefix).as_posix()] = member

            def read(name: str, limit: int) -> bytes:
                member = files.get(name)
                if member is None or member.size > limit:
                    raise PreviewError(f"Source archive is missing or oversizing {name}")
                stream = archive.extractfile(
                    member
                )  # In-memory member read, never filesystem extraction.
                if stream is None:
                    raise PreviewError(f"Cannot read source archive member {name}")
                with stream:
                    data = stream.read(limit + 1)
                if len(data) != member.size or len(data) > limit:
                    raise PreviewError(f"Source archive member size mismatch: {name}")
                return data

            _metadata(read("PKG-INFO", _METADATA_LIMIT), version)
            if read("pyproject.toml", len(project_bytes)) != project_bytes:
                raise PreviewError("Source archive pyproject.toml differs from the checkout")
            if read("uv.lock", len(lock_bytes)) != lock_bytes:
                raise PreviewError("Source archive uv.lock differs from the checkout")
            for filename in ("LICENSE", "NOTICE"):
                source = root / filename
                _regular(source)
                original = source.read_bytes()
                if read(filename, len(original)) != original:
                    raise PreviewError(f"Source archive {filename} differs from the checkout")
            included_examples = {name for name in files if name.startswith("examples/")}
            if included_examples != set(examples):
                raise PreviewError("Source archive must include exactly the current example files")
            for name, source in sorted(examples.items()):
                expected = source.read_bytes()
                if read(name, len(expected)) != expected:
                    raise PreviewError(f"Source archive example differs from the checkout: {name}")
            for name, source in sorted(sources.items()):
                expected = source.read_bytes()
                if read(name, len(expected)) != expected:
                    raise PreviewError(f"Source archive source/support file differs: {name}")
    except (OSError, tarfile.TarError, EOFError) as error:
        raise PreviewError("Cannot read the source archive") from error


def _write_atomic(path: Path, data: bytes) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".preview-", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def prepare_preview(root: Path, dist: Path | None = None) -> dict[str, object]:
    """Validate exactly one current pure-Python wheel/sdist and write two derived files.

    Source commit identifies the clean metadata/example inputs. It is not a
    claim that every archived source byte was rebuilt or authenticated here.
    CI must separately build/test these exact artifacts before publication.
    """
    root = Path(root).absolute()
    dist = Path(dist).absolute() if dist is not None else root / "dist"
    if dist != root / "dist":
        raise PreviewError("Candidate files and generated metadata must be in the checkout's dist/")
    if dist.is_symlink() or not dist.is_dir():
        raise PreviewError("dist/ must be an existing non-symlink directory")
    version, project_bytes, lock_bytes = _project_version(root)
    commit = _source_commit(root)
    sources = _tracked_sources(root)
    wheel_name = f"{_PROJECT}-{version}-py3-none-any.whl"
    sdist_name = f"{_PROJECT}-{version}.tar.gz"
    expected = {wheel_name, sdist_name}
    found: set[str] = set()
    for path in dist.iterdir():
        _regular(path)
        if path.name not in expected | _DERIVED | _BUILD_CONTROL:
            raise PreviewError(f"dist/ contains an old or unexpected asset: {path.name}")
        if path.name in expected:
            found.add(path.name)
    if found != expected:
        raise PreviewError("dist/ must contain exactly this version's wheel and source archive")
    _wheel(dist / wheel_name, root, version)
    _sdist(dist / sdist_name, root, version, project_bytes, lock_bytes, sources)
    example_manifest = "examples/evidence-demo/manifest.json"
    _regular(root / example_manifest)
    manifest: dict[str, object] = {
        "kind": "tickwitness_preview_manifest_v1",
        "schema_version": 1,
        "name": _PROJECT,
        "version": version,
        "source_commit": commit,
        "uv_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        # Identity only: the separate installed smoke must verify bundle contents.
        "example_bundle": {
            "manifest_path": example_manifest,
            "bundle_id": _sha256(root / example_manifest),
        },
        "artifacts": [
            {
                "filename": name,
                "size_bytes": (dist / name).stat().st_size,
                "sha256": _sha256(dist / name),
            }
            for name in sorted(expected)
        ],
        "claims": {
            "signed": False,
            "published": False,
            "test_results_included": False,
            "source_rebuild_verified": False,
        },
    }
    encoded = (
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()
    sums = {
        row["filename"]: row["sha256"]
        for row in cast("list[dict[str, str]]", manifest["artifacts"])
    }
    sums["preview-manifest.json"] = hashlib.sha256(encoded).hexdigest()
    checksums = "".join(f"{checksum}  {name}\n" for name, checksum in sorted(sums.items())).encode()
    _write_atomic(dist / "preview-manifest.json", encoded)
    _write_atomic(dist / "SHA256SUMS", checksums)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dist", type=Path, help="Must be the selected checkout's dist/ directory")
    arguments = parser.parse_args(argv)
    try:
        manifest = prepare_preview(arguments.root, arguments.dist)
    except (PreviewError, OSError) as error:
        parser.exit(2, f"Preview preparation failed: {error}\n")
    print(
        f"Prepared TickWitness {manifest['version']} preview metadata; unsigned and not published."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
