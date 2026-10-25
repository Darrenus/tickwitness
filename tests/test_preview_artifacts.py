"""Packaging-only checks use original tiny archives, without executing their contents."""

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_preview.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_preview_test_helper", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)
VERSION = "0.1.0a1"
COMMIT = "a" * 40
SOURCE_COMMIT = preview._source_commit
TRACKED_SOURCES = preview._tracked_sources
SOURCE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "LICENSE",
    "NOTICE",
    ".python-version",
    "Makefile",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "src/tickwitness/__init__.py",
    "docs/support.md",
    "scripts/smoke_evidence.py",
    "research/original.json",
    ".github/workflows/engineering.yml",
)


def metadata(version: str = VERSION, name: str = "tickwitness") -> bytes:
    return (
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
        "License-File: LICENSE\nLicense-File: NOTICE\n\nOriginal fixture.\n"
    ).encode()


def wheel(
    root: Path,
    *,
    version: str = VERSION,
    name: str = "tickwitness",
    missing: str | None = None,
    changed: str | None = None,
) -> Path:
    path = root / "dist" / f"tickwitness-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"tickwitness-{VERSION}.dist-info/METADATA", metadata(version, name))
        archive.writestr("tickwitness/__init__.py", "raise RuntimeError('must never execute')\n")
        for filename in ("LICENSE", "NOTICE"):
            if filename != missing:
                data = (
                    b"changed license fixture"
                    if filename == changed
                    else (root / filename).read_bytes()
                )
                archive.writestr(f"tickwitness-{VERSION}.dist-info/licenses/{filename}", data)
    return path


def sdist(
    root: Path,
    *,
    version: str = VERSION,
    missing: str | None = None,
    changed: str | None = None,
    extra: str | None = None,
) -> Path:
    path = root / "dist" / f"tickwitness-{VERSION}.tar.gz"
    files = {
        **{name: (root / name).read_bytes() for name in SOURCE_FILES},
        "PKG-INFO": metadata(version),
        "examples/replay.jsonl": (root / "examples" / "replay.jsonl").read_bytes(),
        "examples/evidence-demo/manifest.json": (
            root / "examples" / "evidence-demo" / "manifest.json"
        ).read_bytes(),
    }
    if missing is not None:
        del files[missing]
    if changed is not None:
        files[changed] = b"changed fixture bytes"
    if extra is not None:
        files[extra] = b"unexpected"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(f"tickwitness-{VERSION}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


@pytest.fixture
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "dist").mkdir()
    (tmp_path / "examples" / "evidence-demo").mkdir(parents=True)
    (tmp_path / "examples" / "replay.jsonl").write_bytes(b'{"original":"tiny-example"}\n')
    (tmp_path / "examples" / "evidence-demo" / "manifest.json").write_bytes(b'{"original":"demo"}')
    (tmp_path / "LICENSE").write_bytes(b"Original license fixture, not a third-party license.\n")
    (tmp_path / "NOTICE").write_bytes(b"Original notice fixture.\n")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname="tickwitness"\nversion="{VERSION}"\n'
    )
    (tmp_path / "uv.lock").write_text(
        f'version=1\n[[package]]\nname="tickwitness"\nversion="{VERSION}"\n'
        'source={editable="."}\n'
    )
    for name in SOURCE_FILES:
        path = tmp_path / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Original source/support fixture, never executed.\n")
    monkeypatch.setattr(preview, "_source_commit", lambda _root: COMMIT)
    monkeypatch.setattr(
        preview, "_tracked_sources", lambda root: {name: root / name for name in SOURCE_FILES}
    )
    wheel(tmp_path)
    sdist(tmp_path)
    return tmp_path


def test_manifest_and_checksums_bind_exact_actual_bytes_and_repeat_deterministically(
    candidate: Path,
) -> None:
    manifest = preview.prepare_preview(candidate)
    manifest_bytes = (candidate / "dist" / "preview-manifest.json").read_bytes()
    checksums = (candidate / "dist" / "SHA256SUMS").read_bytes()
    assert json.loads(manifest_bytes) == manifest
    assert manifest["version"] == VERSION and manifest["source_commit"] == COMMIT
    assert (
        manifest["uv_lock_sha256"]
        == hashlib.sha256((candidate / "uv.lock").read_bytes()).hexdigest()
    )
    assert manifest["claims"] == {
        "signed": False,
        "published": False,
        "test_results_included": False,
        "source_rebuild_verified": False,
    }
    assert manifest["example_bundle"] == {
        "manifest_path": "examples/evidence-demo/manifest.json",
        "bundle_id": hashlib.sha256(
            (candidate / "examples" / "evidence-demo" / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    for artifact in manifest["artifacts"]:
        data = (candidate / "dist" / artifact["filename"]).read_bytes()
        assert artifact["size_bytes"] == len(data)
        assert artifact["sha256"] == hashlib.sha256(data).hexdigest()
    lines = dict(line.split("  ", 1)[::-1] for line in checksums.decode().splitlines())
    assert set(lines) == {
        "preview-manifest.json",
        *(artifact["filename"] for artifact in manifest["artifacts"]),
    }
    for name, checksum in lines.items():
        assert hashlib.sha256((candidate / "dist" / name).read_bytes()).hexdigest() == checksum
    assert preview.prepare_preview(candidate) == manifest
    assert (candidate / "dist" / "preview-manifest.json").read_bytes() == manifest_bytes
    assert (candidate / "dist" / "SHA256SUMS").read_bytes() == checksums


def test_source_commit_change_changes_manifest_without_inventing_test_results(
    candidate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = preview.prepare_preview(candidate)
    first_checksums = (candidate / "dist" / "SHA256SUMS").read_bytes()
    monkeypatch.setattr(preview, "_source_commit", lambda _root: "b" * 40)
    second = preview.prepare_preview(candidate)
    assert second["source_commit"] == "b" * 40
    assert first["artifacts"] == second["artifacts"]
    assert first["claims"] == second["claims"]
    assert (candidate / "dist" / "SHA256SUMS").read_bytes() != first_checksums


@pytest.mark.parametrize("dirty", [" M pyproject.toml\n", "?? examples/untracked.json\n"])
def test_source_identity_reader_refuses_uncommitted_inputs_without_invoking_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dirty: str
) -> None:
    observed = []

    def fake_git(command, **_kwargs):
        observed.append(command)
        return SimpleNamespace(returncode=0, stdout=COMMIT if "rev-parse" in command else dirty)

    monkeypatch.setattr(preview.subprocess, "run", fake_git)
    with pytest.raises(preview.PreviewError, match="Source checkout must be clean"):
        SOURCE_COMMIT(tmp_path)
    assert len(observed) == 2
    assert all(command[:2] == ["git", "--no-optional-locks"] for command in observed)


def test_tracked_source_selection_uses_nul_separated_git_listing_without_running_git(
    candidate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = []

    def fake_git(command, **_kwargs):
        observed.append(command)
        return SimpleNamespace(returncode=0, stdout=("\x00".join(SOURCE_FILES) + "\x00").encode())

    monkeypatch.setattr(preview.subprocess, "run", fake_git)
    assert TRACKED_SOURCES(candidate) == {name: candidate / name for name in SOURCE_FILES}
    assert len(observed) == 1
    assert "ls-files" in observed[0] and "-z" in observed[0]


@pytest.mark.parametrize("archive", ["wheel", "sdist"])
def test_metadata_version_mismatch_is_rejected(candidate: Path, archive: str) -> None:
    (wheel if archive == "wheel" else sdist)(candidate, version="0.0.2.dev0")
    with pytest.raises(preview.PreviewError, match="Name/Version"):
        preview.prepare_preview(candidate)
    assert not (candidate / "dist" / "preview-manifest.json").exists()


def test_metadata_name_mismatch_is_rejected(candidate: Path) -> None:
    wheel(candidate, name="another-project")
    with pytest.raises(preview.PreviewError, match="Name/Version"):
        preview.prepare_preview(candidate)


@pytest.mark.parametrize(
    "filename", [f"tickwitness-{VERSION}-py3-none-any.whl", f"tickwitness-{VERSION}.tar.gz"]
)
def test_missing_distribution_is_rejected(candidate: Path, filename: str) -> None:
    (candidate / "dist" / filename).unlink()
    with pytest.raises(preview.PreviewError, match="exactly this version"):
        preview.prepare_preview(candidate)


@pytest.mark.parametrize("filename", ["tickwitness-0.0.2.dev0-py3-none-any.whl", "build.log"])
def test_old_or_extra_assets_are_rejected(candidate: Path, filename: str) -> None:
    (candidate / "dist" / filename).write_bytes(b"old fixture")
    with pytest.raises(preview.PreviewError, match="old or unexpected"):
        preview.prepare_preview(candidate)


@pytest.mark.parametrize(
    "missing",
    [
        "uv.lock",
        "examples/replay.jsonl",
        "examples/evidence-demo/manifest.json",
        "LICENSE",
        "NOTICE",
    ],
)
def test_source_archive_requires_lock_and_complete_examples(candidate: Path, missing: str) -> None:
    sdist(candidate, missing=missing)
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(candidate)


@pytest.mark.parametrize(
    "changed", ["pyproject.toml", "uv.lock", "examples/replay.jsonl", "LICENSE", "NOTICE"]
)
def test_source_archive_must_match_current_input_bytes(candidate: Path, changed: str) -> None:
    sdist(candidate, changed=changed)
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(candidate)


def test_source_archive_rejects_historical_extra_example(candidate: Path) -> None:
    sdist(candidate, extra="examples/old-example.json")
    with pytest.raises(preview.PreviewError, match="exactly the current example"):
        preview.prepare_preview(candidate)


@pytest.mark.parametrize(
    "missing", ["src/tickwitness/__init__.py", "Makefile", "docs/support.md", ".python-version"]
)
def test_source_archive_cannot_pass_with_only_metadata_and_examples(
    candidate: Path, missing: str
) -> None:
    sdist(candidate, missing=missing)
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(candidate)


def test_wheel_rejects_noncanonical_alias_member_path(candidate: Path) -> None:
    path = candidate / "dist" / f"tickwitness-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("tickwitness//__init__.py", "must not alias an existing path\n")
    with pytest.raises(preview.PreviewError, match="unsupported member path"):
        preview.prepare_preview(candidate)


@pytest.mark.parametrize("filename", ["LICENSE", "NOTICE"])
@pytest.mark.parametrize("problem", ["missing", "changed"])
def test_wheel_license_and_notice_are_complete_and_identical_to_source(
    candidate: Path, filename: str, problem: str
) -> None:
    wheel(candidate, **{problem: filename})
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(candidate)


def test_lock_project_version_must_match_metadata(candidate: Path) -> None:
    path = candidate / "uv.lock"
    path.write_text(path.read_text().replace(VERSION, "0.0.2.dev0"))
    with pytest.raises(preview.PreviewError, match="uv.lock must bind"):
        preview.prepare_preview(candidate)


def test_derived_files_cannot_be_redirected_outside_dist(candidate: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    (candidate / "dist" / "SHA256SUMS").symlink_to(outside)
    with pytest.raises(preview.PreviewError, match="non-symlink"):
        preview.prepare_preview(candidate)
    assert outside.read_bytes() == b"unchanged"


def test_output_directory_is_fixed_to_checkout_dist(candidate: Path) -> None:
    with pytest.raises(preview.PreviewError, match="checkout's dist"):
        preview.prepare_preview(candidate, candidate / "elsewhere")


def test_help_needs_no_git_checkout_or_distributions(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--root" in result.stdout and "--dist" in result.stdout
    assert list(tmp_path.iterdir()) == []
