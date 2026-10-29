"""Exact transferable envelopes and real controlled publication boundaries."""

import json
import os
import shutil
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from tickwitness.domain.evidence.alpha_scorecard import build_alpha_suite
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure import evidence_bundles as io
from tickwitness.infrastructure.alpha_publication_probe import LocalAlphaPublicationProbe
from tickwitness.infrastructure.alpha_reproduction_kits import (
    MAX_FILES,
    MAX_GUIDE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_RUNNER_BYTES,
    MAX_TOTAL_BYTES,
    MAX_WHEEL_BYTES,
    AlphaKitDestinationExistsError,
    AlphaKitDurabilityError,
    AlphaKitError,
    AlphaKitLimits,
    AlphaKitNotFoundError,
    AlphaReproductionKit,
    _publish_alpha_kit,
    export_alpha_kit,
    publish_alpha_kit,
    read_alpha_kit,
)
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle


@pytest.fixture
def kit(tmp_path: Path) -> AlphaReproductionKit:
    corpus = Path(__file__).parents[2] / "examples" / "alpha"
    counterexample = read_search_evidence_bundle(corpus / "counterexample")
    clean = read_search_evidence_bundle(corpus / "clean-control")
    suite = build_alpha_suite(
        counterexample_bundle_id=counterexample.bundle_id,
        counterexample_report_id=digest(counterexample.artifacts["finding_report"]),
        clean_bundle_id=clean.bundle_id,
        clean_report_id=digest(clean.artifacts["finding_report"]),
    )
    # Opaque test payloads deliberately prove envelope IO does not execute code
    # or claim to authenticate wheel internals. Installed smoke uses a real wheel.
    return export_alpha_kit(
        tmp_path / "kit",
        suite_bytes=suite.canonical_bytes,
        wheel_name="tickwitness-0.2.0.dev0-py3-none-any.whl",
        wheel_bytes=b"opaque wheel test payload",
        guide_bytes=b"Read the separate owner-provided content pin.\n",
        runner_bytes=b"raise AssertionError('kit IO must never execute this runner')\n",
        counterexample=counterexample,
        clean_control=clean,
        producer_version="0.2.0.dev0",
        source_revision="a" * 40,
    )


def _paths(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _changed(kit: AlphaReproductionKit, change) -> bytes:
    document = kit.manifest
    change(document)
    return canonical(document)


def test_immutable_roundtrip_relocation_and_exact_readonly_tree(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    root = tmp_path / "kit"
    assert digest(kit.manifest_bytes) == kit.kit_id
    assert read_alpha_kit(root, expected_kit_id=kit.kit_id) == kit
    before = {path: path.stat().st_mtime_ns for path in root.rglob("*")}
    assert read_alpha_kit(root) == kit
    assert {path: path.stat().st_mtime_ns for path in root.rglob("*")} == before
    detached = kit.files
    detached["README.md"] = b"changed"
    manifest = kit.manifest
    manifest["scope"] = "changed"
    assert kit.files["README.md"] != b"changed"
    assert kit.manifest["scope"] == "development_technical_alpha_v1"
    assert kit.case("counterexample").bundle_id != kit.case("clean_control").bundle_id
    with pytest.raises(AlphaKitError):
        kit.case("clean-control")
    with pytest.raises(FrozenInstanceError):
        kit.manifest_bytes = b"{}"  # type: ignore[misc]
    relocated = tmp_path / "relocated"
    root.rename(relocated)
    assert read_alpha_kit(relocated, expected_kit_id=kit.kit_id) == kit
    assert _paths(relocated) == {"manifest.json": kit.manifest_bytes, **kit.files}


def test_no_overwrite_preserves_existing_complete_directory(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    before = _paths(tmp_path / "kit")
    with pytest.raises(AlphaKitDestinationExistsError):
        publish_alpha_kit(tmp_path / "kit", kit)
    assert _paths(tmp_path / "kit") == before
    assert {path.name for path in tmp_path.iterdir()} == {"kit"}


def test_missing_root_wrong_pin_and_invalid_pin_never_create_files(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    missing = tmp_path / "absent"
    with pytest.raises(AlphaKitNotFoundError):
        read_alpha_kit(missing)
    assert not missing.exists()
    for pin in ("0" * 64, "../outside", "A" * 64, "1"):
        with pytest.raises(AlphaKitError):
            read_alpha_kit(tmp_path / "kit", expected_kit_id=pin)


@pytest.mark.parametrize(
    "name,maximum",
    [
        ("max_total_bytes", MAX_TOTAL_BYTES),
        ("max_files", MAX_FILES),
        ("max_manifest_bytes", MAX_MANIFEST_BYTES),
        ("max_wheel_bytes", MAX_WHEEL_BYTES),
        ("max_guide_bytes", MAX_GUIDE_BYTES),
        ("max_runner_bytes", MAX_RUNNER_BYTES),
    ],
)
@pytest.mark.parametrize("invalid", ["zero", "negative", "boolean", "float", "larger"])
def test_limits_only_tighten(name: str, maximum: int, invalid: str) -> None:
    value = {"zero": 0, "negative": -1, "boolean": True, "float": 1.0, "larger": maximum + 1}[
        invalid
    ]
    with pytest.raises(AlphaKitError):
        AlphaKitLimits(**{name: value})


def test_exact_limits_pass_and_one_byte_or_file_less_fails(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    sizes = {path: len(raw) for path, raw in kit.files.items()}
    limits = AlphaKitLimits(
        max_total_bytes=len(kit.manifest_bytes) + sum(sizes.values()),
        max_files=len(sizes) + 1,
        max_manifest_bytes=len(kit.manifest_bytes),
        max_wheel_bytes=sizes[kit.manifest["wheel_path"]],
        max_guide_bytes=sizes["README.md"],
        max_runner_bytes=sizes["reproduce.py"],
    )
    assert read_alpha_kit(tmp_path / "kit", limits=limits) == kit
    for name in (
        "max_total_bytes",
        "max_files",
        "max_manifest_bytes",
        "max_wheel_bytes",
        "max_guide_bytes",
        "max_runner_bytes",
    ):
        with pytest.raises(AlphaKitError):
            read_alpha_kit(
                tmp_path / "kit", limits=replace(limits, **{name: getattr(limits, name) - 1})
            )


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/absolute",
        "cases/counterexample/../README.md",
        "cases/counterexample/objects/sha256/" + "A" * 64,
        "cases/counterexample/objects/sha256/" + "a" * 63,
        "cases/counterexample/objects/sha256/" + "a/" * 32,
        "cases\\counterexample\\manifest.json",
        ".hidden",
        "distribution/another-1-py3-none-any.whl",
        "distribution/tickwitness-1-cp313-cp313-any.whl",
    ],
)
def test_manifest_paths_are_fixed_not_arbitrary(kit: AlphaReproductionKit, path: str) -> None:
    files = kit.files
    files[path] = b"extra"
    document = kit.manifest
    document["files"][path] = {"sha256": digest(b"extra"), "size_bytes": 5}
    with pytest.raises(AlphaKitError):
        AlphaReproductionKit(canonical(document), tuple(sorted(files.items())))


@pytest.mark.parametrize("change", ["scope", "schema", "producer", "version", "suite", "wheel"])
def test_rehashed_wrong_manifest_markers_never_become_valid(
    kit: AlphaReproductionKit, change: str
) -> None:
    document = kit.manifest
    if change == "scope":
        document["scope"] = "release_approved"
    elif change == "schema":
        document["schema_version"] = True
    elif change == "producer":
        document["producer"]["source_revision"] = "A" * 40
    elif change == "version":
        document["producer"]["version"] = "bad\nversion"
    elif change == "suite":
        document["suite"]["external_gate"] = "ci_counts_as_external"
    else:
        document["wheel_path"] = "distribution/tickwitness-1-cp313-cp313-any.whl"
    with pytest.raises(AlphaKitError):
        AlphaReproductionKit(canonical(document), kit._files)


def test_payload_must_be_exact_immutable_and_close_both_bundle_pins(
    kit: AlphaReproductionKit,
) -> None:
    for contents in (
        list(kit._files),
        (*kit._files, kit._files[0]),
        kit._files[1:],
        (([], b"unhashable"),),
    ):
        with pytest.raises(AlphaKitError):
            AlphaReproductionKit(kit.manifest_bytes, contents)
    files = kit.files
    files["README.md"] = bytearray(files["README.md"])
    with pytest.raises(AlphaKitError):
        AlphaReproductionKit(kit.manifest_bytes, tuple(files.items()))
    document = kit.manifest
    document["suite"]["cases"]["counterexample"]["bundle_id"] = "0" * 64
    with pytest.raises(AlphaKitError, match="suite pin"):
        AlphaReproductionKit(canonical(document), kit._files)
    extra = "cases/counterexample/objects/sha256/" + digest(b"unrelated")
    document = kit.manifest
    document["files"][extra] = {"sha256": digest(b"unrelated"), "size_bytes": 9}
    files = {**kit.files, extra: b"unrelated"}
    with pytest.raises(AlphaKitError, match="extra files"):
        AlphaReproductionKit(canonical(document), tuple(files.items()))


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"\xff", b'{"x":1,"x":2}', b" "])
def test_other_formats_and_noncanonical_manifests_are_rejected(
    tmp_path: Path, kit: AlphaReproductionKit, raw: bytes
) -> None:
    (tmp_path / "kit" / "manifest.json").write_bytes(raw)
    with pytest.raises(AlphaKitError):
        read_alpha_kit(tmp_path / "kit")
    with pytest.raises(AlphaKitError):
        AlphaReproductionKit(json.dumps(kit.manifest, indent=2).encode(), kit._files)


@pytest.mark.parametrize("entry", [".hidden", "empty", "cases/counterexample/unknown"])
def test_unknown_files_and_empty_directories_are_not_ignored(
    tmp_path: Path, kit: AlphaReproductionKit, entry: str
) -> None:
    path = tmp_path / "kit" / entry
    if entry == "empty":
        path.mkdir()
    else:
        path.write_bytes(b"extra")
    with pytest.raises(AlphaKitError):
        read_alpha_kit(tmp_path / "kit")


@pytest.mark.parametrize("target", ["root", "manifest", "guide", "wheel", "cases", "object"])
def test_every_fixed_path_is_nofollow(
    tmp_path: Path, kit: AlphaReproductionKit, target: str
) -> None:
    root = tmp_path / "kit"
    paths = {
        "root": root,
        "manifest": root / "manifest.json",
        "guide": root / "README.md",
        "wheel": root / kit.manifest["wheel_path"],
        "cases": root / "cases",
        "object": next((root / "cases" / "counterexample" / "objects" / "sha256").iterdir()),
    }
    path = paths[target]
    outside = tmp_path / "outside"
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=outside.is_dir())
    with pytest.raises(AlphaKitError):
        read_alpha_kit(root)
    assert outside.exists()


@pytest.mark.parametrize("kind", ["fifo", "directory", "oversize", "missing", "tamper"])
@pytest.mark.parametrize("target", ["manifest.json", "README.md", "reproduce.py"])
def test_files_are_regular_bounded_hash_checked_and_required(
    tmp_path: Path, kit: AlphaReproductionKit, kind: str, target: str
) -> None:
    path = tmp_path / "kit" / target
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "oversize":
        with path.open("wb") as stream:
            stream.truncate(MAX_TOTAL_BYTES + 1)
    elif kind == "tamper":
        path.write_bytes(b"tampered")
    with pytest.raises(AlphaKitError):
        read_alpha_kit(tmp_path / "kit")


def test_private_writer_failure_and_precommit_sync_clean_stage_without_success(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    def fail_write(_directory: int, _name: str, _raw: bytes) -> None:
        raise OSError("Injected private writer failure")

    def fail_sync(_directory: int, phase: str) -> None:
        assert phase == "stage"
        raise OSError("Injected private stage sync failure")

    cases = (("writer-fault", {"writer": fail_write}), ("sync-fault", {"sync": fail_sync}))
    for name, options in cases:
        target = tmp_path / name
        with pytest.raises(AlphaKitError):
            _publish_alpha_kit(target, kit, **options)
        assert not target.exists()
        assert {path.name for path in tmp_path.iterdir()} == {"kit"}


def test_postcommit_sync_failure_retains_complete_kit_without_success_receipt(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    def fail_parent(directory: int, phase: str) -> None:
        if phase == "parent":
            raise OSError("Injected private postcommit sync uncertainty")
        os.fsync(directory)

    target = tmp_path / "postcommit"
    with pytest.raises(AlphaKitDurabilityError, match="unconfirmed"):
        _publish_alpha_kit(target, kit, sync=fail_parent)
    assert read_alpha_kit(target, expected_kit_id=kit.kit_id) == kit
    assert _paths(target) == {"manifest.json": kit.manifest_bytes, **kit.files}
    with pytest.raises(AlphaKitDestinationExistsError):
        publish_alpha_kit(target, kit)


def test_creation_race_never_replaces_the_winners_directory(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    target = tmp_path / "raced"
    created = False

    def race(directory: int, name: str, data: bytes) -> None:
        nonlocal created
        if not created:
            created = True
            target.mkdir()
            (target / "winner").write_bytes(b"preserve")
        io._write_file(directory, name, data)

    with pytest.raises(AlphaKitDestinationExistsError):
        _publish_alpha_kit(target, kit, writer=race)
    assert _paths(target) == {"winner": b"preserve"}
    assert {path.name for path in tmp_path.iterdir()} == {"kit", "raced"}


@pytest.mark.parametrize("existing", [False, True])
def test_missing_libc_api_refuses_before_staging_without_replacing_or_mutating_content(
    tmp_path: Path,
    kit: AlphaReproductionKit,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    target = tmp_path / "unavailable"
    if existing:
        target.mkdir()
        (target / "owner-file").write_bytes(b"preserve this existing destination")
    before_target = _paths(target) if existing else None
    before_kit = _paths(tmp_path / "kit")
    before_entries = {path.name for path in tmp_path.iterdir()}
    requested: list[str] = []
    expected_symbol = "renameatx_np" if io.sys.platform == "darwin" else "renameat2"

    class MissingLibcAPI:
        def __getattr__(self, symbol: str) -> object:
            requested.append(symbol)
            raise AttributeError("Controlled missing libc symbol: " + symbol)

    def missing_library(name: object, *, use_errno: bool) -> MissingLibcAPI:
        assert name is None and use_errno is True
        return MissingLibcAPI()

    def forbidden(*_args: object) -> None:
        raise AssertionError("Missing libc API must be detected before stage writes or sync")

    # Exercise the real helper's dynamic symbol lookup. The missing-entry
    # condition is independent of a particular libc family or version.
    monkeypatch.setattr(io.ctypes, "CDLL", missing_library)
    with pytest.raises(AlphaKitError) as caught:
        _publish_alpha_kit(target, kit, writer=forbidden, sync=forbidden)
    assert str(caught.value) == (
        "Alpha kit publication failed: Atomic no-replace bundle publication is unavailable in libc"
    )
    assert isinstance(caught.value.__cause__, io.BundleError)
    assert isinstance(caught.value.__cause__.__cause__, AttributeError)
    assert requested == [expected_symbol]
    assert {path.name for path in tmp_path.iterdir()} == before_entries
    assert _paths(tmp_path / "kit") == before_kit
    assert read_alpha_kit(tmp_path / "kit", expected_kit_id=kit.kit_id) == kit
    if existing:
        assert _paths(target) == before_target
    else:
        assert not target.exists()


def test_fresh_probe_uses_real_publisher_faults_and_retains_actual_artifact(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    root = tmp_path / "probe"
    result = LocalAlphaPublicationProbe(root).run(kit)
    assert result.postcommit_kit == kit
    assert read_alpha_kit(root / "postcommit", expected_kit_id=kit.kit_id) == kit
    assert {path.name for path in root.iterdir()} == {"normal", "postcommit"}
    document = result.document
    assert document["kit_id"] == kit.kit_id
    assert document["normal_publication"]["success_returned"] is True
    assert document["existing_destination"]["original_tree_unchanged"] is True
    assert document["precommit_sync_failure"] == {
        "fault_injected": True,
        "exception_type": "AlphaKitError",
        "success_returned": False,
        "target_exists": False,
        "staging_entries_remaining": 0,
    }
    assert document["postcommit_parent_sync_failure"] == {
        "fault_injected": True,
        "exception_type": "AlphaKitDurabilityError",
        "success_returned": False,
        "target_exists": True,
        "retained_kit_id": kit.kit_id,
    }
    before = {path.relative_to(root): path.stat().st_mtime_ns for path in root.rglob("*")}
    with pytest.raises(AlphaKitDestinationExistsError):
        LocalAlphaPublicationProbe(root).run(kit)
    assert {path.relative_to(root): path.stat().st_mtime_ns for path in root.rglob("*")} == before


def test_probe_results_do_not_depend_on_absolute_location(
    tmp_path: Path, kit: AlphaReproductionKit
) -> None:
    first = LocalAlphaPublicationProbe(tmp_path / "first").run(kit)
    other_parent = tmp_path / "another-parent"
    other_parent.mkdir()
    second = LocalAlphaPublicationProbe(other_parent / "second").run(kit)
    assert first.document == second.document
    assert first.postcommit_kit == second.postcommit_kit
    shutil.rmtree(tmp_path / "kit")
    expected_bundle = kit.case("counterexample").bundle_id
    assert first.postcommit_kit.case("counterexample").bundle_id == expected_bundle
