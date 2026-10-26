"""Exercise fixed bundle trees and publication boundaries on the real filesystem."""

import errno
import hashlib
import json
import os
import shutil
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import evidence_bundles as safe_io
from tickwitness.infrastructure.evidence_bundles import (
    BundleDestinationExistsError,
    BundleDurabilityError,
    BundleError,
    BundleLimits,
    BundleNotFoundError,
)
from tickwitness.infrastructure.tagged_finding_bundles import (
    TaggedFindingArtifactBundle,
    export_tagged_finding_bundle,
    read_tagged_finding_bundle,
)

ROLES = (
    "protocol",
    "dataset_manifest",
    "raw",
    "normalized",
    "report",
    "front_result",
    "front_evaluation",
    "front_receipt",
    "back_result",
    "back_evaluation",
    "back_receipt",
    "assessment",
    "finding_protocol",
    "finding_report",
)


def artifacts() -> dict[str, bytes]:
    # Opaque IO fixture: these are deliberately not semantic replay artifacts.
    return {role: json.dumps({"original_fixture_role": role}).encode() for role in ROLES}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def rewrite_manifest(root: Path, document: dict[str, object]) -> None:
    (root / "manifest.json").write_bytes(canonical(document))


def test_round_trip_determinism_and_detached_immutable_payload(tmp_path: Path) -> None:
    payload = artifacts()
    published = export_tagged_finding_bundle(tmp_path / "first", payload)
    second = export_tagged_finding_bundle(tmp_path / "second", payload)
    restored = read_tagged_finding_bundle(tmp_path / "first")

    assert published == restored == second
    assert published.bundle_id == hashlib.sha256(published.manifest_bytes).hexdigest()
    assert published.artifacts == payload
    payload["raw"] = b"changed caller mapping"
    view = published.artifacts
    view["raw"] = b"changed returned mapping"
    manifest = published.manifest
    manifest["roles"]["raw"]["ref"] = "../../outside"
    assert published.artifacts == artifacts()
    assert published.manifest == restored.manifest
    with pytest.raises(FrozenInstanceError):
        published.manifest_bytes = b"{}"
    assert b"created_at" not in published.manifest_bytes
    assert str(tmp_path).encode() not in published.manifest_bytes


def test_moved_directory_remains_independently_readable(tmp_path: Path) -> None:
    original = tmp_path / "original"
    published = export_tagged_finding_bundle(original, artifacts())
    destination = tmp_path / "new-parent" / "moved"
    destination.parent.mkdir()
    shutil.move(str(original), destination)

    assert read_tagged_finding_bundle(destination) == published
    assert not original.exists()


def test_identical_role_content_is_physically_deduplicated(tmp_path: Path) -> None:
    payload = dict.fromkeys(ROLES, b"same immutable bytes")
    destination = tmp_path / "bundle"
    published = export_tagged_finding_bundle(destination, payload)

    assert len(list((destination / "objects" / "sha256").iterdir())) == 1
    assert read_tagged_finding_bundle(destination, limits=BundleLimits(max_files=2)) == published
    with pytest.raises(BundleError, match="max_files"):
        read_tagged_finding_bundle(destination, limits=BundleLimits(max_files=1))


@pytest.mark.parametrize("contents", [None, "regular", "directory", "symlink"])
def test_existing_destination_is_never_overwritten(tmp_path: Path, contents: str | None) -> None:
    destination = tmp_path / "bundle"
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside unchanged")
    if contents == "regular":
        destination.write_bytes(b"user file")
    elif contents == "symlink":
        destination.symlink_to(outside)
    else:
        destination.mkdir()
        if contents == "directory":
            (destination / "user-file").write_bytes(b"user data")
    before = {path.name for path in tmp_path.iterdir()}

    with pytest.raises(BundleDestinationExistsError):
        export_tagged_finding_bundle(destination, artifacts())

    assert {path.name for path in tmp_path.iterdir()} == before
    assert outside.read_bytes() == b"outside unchanged"
    if contents == "regular":
        assert destination.read_bytes() == b"user file"
    elif contents == "directory":
        assert (destination / "user-file").read_bytes() == b"user data"
    elif contents is None:
        assert list(destination.iterdir()) == []
    else:
        assert destination.is_symlink()


def test_empty_destination_created_at_commit_cannot_be_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    rename = safe_io._rename_exclusive

    def insert_user_directory(parent: int, source: str, target: str) -> None:
        os.mkdir(target, dir_fd=parent)
        rename(parent, source, target)

    monkeypatch.setattr(safe_io, "_rename_exclusive", insert_user_directory)
    with pytest.raises(BundleDestinationExistsError):
        export_tagged_finding_bundle(destination, artifacts())
    assert destination.is_dir()
    assert list(destination.iterdir()) == []


def test_two_concurrent_exports_have_one_winner_without_overwrite(tmp_path: Path) -> None:
    for iteration in range(8):
        destination = tmp_path / f"bundle-{iteration}"
        barrier = Barrier(2)

        def publish(
            target: Path = destination, synchronization: Barrier = barrier
        ) -> TaggedFindingArtifactBundle | BundleDestinationExistsError:
            synchronization.wait()
            try:
                return export_tagged_finding_bundle(target, artifacts())
            except BundleDestinationExistsError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: publish(), range(2)))
        assert sum(isinstance(item, TaggedFindingArtifactBundle) for item in outcomes) == 1
        assert sum(isinstance(item, BundleDestinationExistsError) for item in outcomes) == 1
        assert read_tagged_finding_bundle(destination).artifacts == artifacts()
        assert not any(path.name.startswith(".tickwitness") for path in tmp_path.iterdir())


@pytest.mark.parametrize("fail_at", [2, 9])
def test_precommit_disk_full_leaves_no_target_and_retry_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    destination = tmp_path / "bundle"
    original_fsync = os.fsync
    regular_fsyncs = 0

    def disk_full(descriptor: int) -> None:
        nonlocal regular_fsyncs
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            regular_fsyncs += 1
            if regular_fsyncs == fail_at:
                raise OSError(errno.ENOSPC, "simulated full disk")
        original_fsync(descriptor)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", disk_full)
        with pytest.raises(BundleError, match="publication failed"):
            export_tagged_finding_bundle(destination, artifacts())
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
    assert export_tagged_finding_bundle(destination, artifacts()) == read_tagged_finding_bundle(
        destination
    )


def test_postcommit_parent_fsync_error_preserves_complete_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    parent_inode = tmp_path.stat().st_ino
    original_fsync = os.fsync

    def unconfirmed(descriptor: int) -> None:
        info = os.fstat(descriptor)
        if stat.S_ISDIR(info.st_mode) and info.st_ino == parent_inode:
            raise OSError(errno.EIO, "parent durability unconfirmed")
        original_fsync(descriptor)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", unconfirmed)
        with pytest.raises(BundleDurabilityError, match="Complete bundle is published"):
            export_tagged_finding_bundle(destination, artifacts())
    assert read_tagged_finding_bundle(destination).artifacts == artifacts()
    with pytest.raises(BundleDestinationExistsError):
        export_tagged_finding_bundle(destination, artifacts())


@pytest.mark.parametrize("invalid", [{}, {**artifacts(), "confirmation": b"secret"}])
def test_bad_roles_do_not_create_target_or_parent(
    tmp_path: Path, invalid: dict[str, bytes]
) -> None:
    destination = tmp_path / "absent-parent" / "bundle"
    with pytest.raises(BundleError, match="fourteen fixed"):
        export_tagged_finding_bundle(destination, invalid)
    assert not destination.parent.exists()


@pytest.mark.parametrize("invalid", [b"", bytearray(b"mutable"), "text", None])
def test_bad_payload_types_are_rejected_before_staging(tmp_path: Path, invalid: object) -> None:
    payload = artifacts()
    payload["raw"] = invalid
    with pytest.raises(BundleError, match="immutable nonempty bytes"):
        export_tagged_finding_bundle(tmp_path / "bundle", payload)
    assert list(tmp_path.iterdir()) == []


def test_public_bundle_constructor_cannot_wrap_mutable_or_mismatched_bytes(tmp_path: Path) -> None:
    published = export_tagged_finding_bundle(tmp_path / "bundle", artifacts())
    with pytest.raises(BundleError):
        TaggedFindingArtifactBundle(bytearray(published.manifest_bytes), tuple(artifacts().items()))
    with pytest.raises(BundleError):
        TaggedFindingArtifactBundle(published.manifest_bytes, list(artifacts().items()))
    changed = artifacts()
    changed["raw"] = b"different"
    with pytest.raises(BundleError, match="close its manifest"):
        TaggedFindingArtifactBundle(published.manifest_bytes, tuple(changed.items()))
    with pytest.raises(BundleError):
        TaggedFindingArtifactBundle(
            published.manifest_bytes, (*tuple(artifacts().items()), ("raw", b"duplicate"))
        )


def test_missing_parent_is_not_created(tmp_path: Path) -> None:
    destination = tmp_path / "absent" / "bundle"
    with pytest.raises(BundleError, match="publication failed"):
        export_tagged_finding_bundle(destination, artifacts())
    assert list(tmp_path.iterdir()) == []


def test_export_rejects_symlink_parent_without_writing_outside(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(BundleError):
        export_tagged_finding_bundle(alias / "bundle", artifacts())
    assert list(outside.iterdir()) == []


def test_unsupported_rename_platform_fails_before_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(safe_io.sys, "platform", "unsupported-os")
    with pytest.raises(BundleError, match="unsupported"):
        export_tagged_finding_bundle(tmp_path / "bundle", artifacts())
    assert list(tmp_path.iterdir()) == []


def test_missing_no_replace_libc_entry_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(safe_io.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace())
    with pytest.raises(BundleError, match="unavailable in libc"):
        export_tagged_finding_bundle(tmp_path / "bundle", artifacts())
    assert list(tmp_path.iterdir()) == []


def test_read_missing_root_has_no_side_effect(tmp_path: Path) -> None:
    destination = tmp_path / "absent" / "bundle"
    with pytest.raises(BundleNotFoundError):
        read_tagged_finding_bundle(destination)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entry", ["manifest", "object"])
def test_missing_required_entry_is_corruption_not_missing_root(tmp_path: Path, entry: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    path = destination / (
        "manifest.json" if entry == "manifest" else bundle.manifest["roles"]["raw"]["ref"]
    )
    path.unlink()
    with pytest.raises(BundleError) as failure:
        read_tagged_finding_bundle(destination)
    assert not isinstance(failure.value, BundleNotFoundError)


@pytest.mark.parametrize("level", ["root", "objects", "sha256"])
@pytest.mark.parametrize("extra", ["file", "directory", "hidden-symlink", "fifo"])
def test_unknown_entries_of_every_type_are_rejected_without_following(
    tmp_path: Path, level: str, extra: str
) -> None:
    destination = tmp_path / "bundle"
    export_tagged_finding_bundle(destination, artifacts())
    directory = {
        "root": destination,
        "objects": destination / "objects",
        "sha256": destination / "objects" / "sha256",
    }[level]
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    path = directory / ".unexpected"
    if extra == "file":
        path.write_bytes(b"extra")
    elif extra == "directory":
        path.mkdir()
    elif extra == "hidden-symlink":
        path.symlink_to(outside)
    else:
        os.mkfifo(path)

    with pytest.raises(BundleError):
        read_tagged_finding_bundle(destination)
    assert outside.read_bytes() == b"unchanged"


@pytest.mark.parametrize("entry", ["root", "objects", "sha256", "manifest", "object"])
def test_required_symlinks_are_rejected(tmp_path: Path, entry: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    role = bundle.manifest["roles"]["raw"]
    target = {
        "root": destination,
        "objects": destination / "objects",
        "sha256": destination / "objects" / "sha256",
        "manifest": destination / "manifest.json",
        "object": destination / role["ref"],
    }[entry]
    outside = tmp_path / "external-entry"
    shutil.move(str(target), outside)
    target.symlink_to(outside, target_is_directory=outside.is_dir())

    with pytest.raises(BundleError):
        read_tagged_finding_bundle(destination)


@pytest.mark.parametrize("entry", ["manifest", "object"])
def test_required_fifo_is_rejected_without_waiting_for_writer(tmp_path: Path, entry: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    path = destination / (
        "manifest.json" if entry == "manifest" else bundle.manifest["roles"]["raw"]["ref"]
    )
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(BundleError):
        read_tagged_finding_bundle(destination)


@pytest.mark.parametrize("role", ROLES)
def test_tampered_role_bytes_fail_complete_closure(tmp_path: Path, role: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    path = destination / bundle.manifest["roles"][role]["ref"]
    data = path.read_bytes()
    path.write_bytes(b"!" + data[1:])
    with pytest.raises(BundleError, match="hash does not match"):
        read_tagged_finding_bundle(destination)


@pytest.mark.parametrize(
    "change",
    [
        "path",
        "hash",
        "size",
        "missing-role",
        "extra-role",
        "extra-field",
        "version",
        "scope",
        "kind",
    ],
)
def test_manifest_injection_and_unknown_schema_are_rejected(tmp_path: Path, change: str) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    manifest = bundle.manifest
    if change == "path":
        manifest["roles"]["raw"]["ref"] = "../../outside"
    elif change == "hash":
        manifest["roles"]["raw"]["sha256"] = "../" + "a" * 61
    elif change == "size":
        manifest["roles"]["raw"]["size_bytes"] = True
    elif change == "missing-role":
        del manifest["roles"]["raw"]
    elif change == "extra-role":
        manifest["roles"]["confirmation"] = manifest["roles"]["raw"]
    elif change == "extra-field":
        manifest["trusted_author"] = "not a supported claim"
    elif change == "version":
        manifest["schema_version"] = True
    elif change == "scope":
        manifest["scope"] = "confirmation_replay"
    else:
        manifest["kind"] = "evidence_bundle_v1"
    rewrite_manifest(destination, manifest)
    with pytest.raises(BundleError):
        read_tagged_finding_bundle(destination)


@pytest.mark.parametrize(
    "invalid", [b"\xff", b"{}", b'{"kind":1,"kind":2}', b"\xef\xbb\xbf{}", b'{"x":NaN}']
)
def test_malformed_manifest_json_is_rejected(tmp_path: Path, invalid: bytes) -> None:
    destination = tmp_path / "bundle"
    export_tagged_finding_bundle(destination, artifacts())
    (destination / "manifest.json").write_bytes(invalid)
    with pytest.raises(BundleError):
        read_tagged_finding_bundle(destination)


def test_manifest_trailing_newline_is_not_canonical(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    (destination / "manifest.json").write_bytes(bundle.manifest_bytes + b"\n")
    with pytest.raises(BundleError, match="canonical"):
        read_tagged_finding_bundle(destination)


def test_size_filecount_manifest_and_total_budgets(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    total = len(bundle.manifest_bytes) + sum(len(data) for data in artifacts().values())
    assert (
        read_tagged_finding_bundle(destination, limits=BundleLimits(max_total_bytes=total)) == bundle
    )
    for limits in (
        BundleLimits(max_total_bytes=total - 1),
        BundleLimits(max_files=8),
        BundleLimits(max_manifest_bytes=len(bundle.manifest_bytes) - 1),
    ):
        with pytest.raises(BundleError):
            read_tagged_finding_bundle(destination, limits=limits)
    raw = destination / bundle.manifest["roles"]["raw"]["ref"]
    raw.write_bytes(raw.read_bytes() + b"extra")
    with pytest.raises(BundleError, match="size"):
        read_tagged_finding_bundle(destination)


def test_role_limit_is_applied_before_target_creation(tmp_path: Path) -> None:
    payload = artifacts()
    payload["protocol"] = b"x" * (256 * 1024 + 1)
    with pytest.raises(BundleError, match="protocol"):
        export_tagged_finding_bundle(tmp_path / "bundle", payload)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("role", "maximum"),
    [
        ("protocol", 256 * 1024),
        ("dataset_manifest", 64 * 1024),
        ("raw", 8 * 1024 * 1024),
        ("normalized", 8 * 1024 * 1024),
        ("report", 4 * 1024 * 1024),
        ("front_result", 16 * 1024 * 1024),
        ("front_evaluation", 64 * 1024),
        ("front_receipt", 1024 * 1024),
        ("back_result", 16 * 1024 * 1024),
        ("back_evaluation", 64 * 1024),
        ("back_receipt", 1024 * 1024),
        ("assessment", 256 * 1024),
        ("finding_protocol", 512 * 1024),
        ("finding_report", 512 * 1024),
    ],
)
def test_declared_role_limit_is_rejected_before_object_loading(
    tmp_path: Path, role: str, maximum: int
) -> None:
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, artifacts())
    manifest = bundle.manifest
    manifest["roles"][role]["size_bytes"] = maximum + 1
    rewrite_manifest(destination, manifest)
    with pytest.raises(BundleError, match=f"Artifact {role} exceeds"):
        read_tagged_finding_bundle(destination)


@pytest.mark.parametrize("invalid", [0, -1, True, "64"])
def test_limits_require_positive_real_integers(invalid: object) -> None:
    with pytest.raises(BundleError):
        BundleLimits(max_total_bytes=invalid)


def test_distinct_contract_cannot_be_read_as_legacy_and_does_not_accept_legacy(tmp_path):
    tagged = tmp_path / "tagged"
    legacy = tmp_path / "legacy"
    published = export_tagged_finding_bundle(tagged, artifacts())
    assert published.manifest["kind"] == "tagged_finding_evidence_bundle_v1"
    assert published.manifest["scope"] == "development_conditional_tagged_findings_v1"
    assert set(published.manifest["roles"]) == set(ROLES)
    with pytest.raises(BundleError, match="markers"):
        safe_io.read_bundle(tagged)
    legacy_artifacts = {
        name: name.encode()
        for name in (
            "protocol",
            "dataset_manifest",
            "raw",
            "normalized",
            "report",
            "replay_result",
            "evaluation",
            "attempt",
        )
    }
    safe_io.export_bundle(legacy, legacy_artifacts)
    with pytest.raises(BundleError, match="markers"):
        read_tagged_finding_bundle(legacy)
    assert safe_io.read_bundle(legacy).artifacts == legacy_artifacts


def test_rehashed_opaque_artifacts_remain_io_only(tmp_path):
    original = artifacts()
    first = export_tagged_finding_bundle(tmp_path / "first", original)
    changed = dict(original, assessment=b'{"self_attested":true}')
    second = export_tagged_finding_bundle(tmp_path / "second", changed)
    assert first.bundle_id != second.bundle_id
    assert read_tagged_finding_bundle(tmp_path / "second").artifacts == changed
    # The IO layer makes no semantic claim from an artifact called assessment.
    assert set(second.manifest) == {"kind", "schema_version", "scope", "roles"}


def test_finding_and_pair_envelopes_are_mutually_exclusive(tmp_path):
    from tickwitness.infrastructure.tagged_evidence_bundles import (
        export_tagged_pair_bundle,
        read_tagged_pair_bundle,
    )

    finding_root, pair_root = tmp_path / "finding", tmp_path / "pair"
    finding = export_tagged_finding_bundle(finding_root, artifacts())
    pair_payload = {
        role: data for role, data in artifacts().items()
        if role not in {"finding_protocol", "finding_report"}
    }
    pair = export_tagged_pair_bundle(pair_root, pair_payload)
    with pytest.raises(BundleError, match="markers"):
        read_tagged_pair_bundle(finding_root)
    with pytest.raises(BundleError, match="markers"):
        read_tagged_finding_bundle(pair_root)
    assert read_tagged_finding_bundle(finding_root) == finding
    assert read_tagged_pair_bundle(pair_root) == pair


def test_declared_alias_cannot_reuse_hash_with_a_different_size(tmp_path):
    destination = tmp_path / "bundle"
    bundle = export_tagged_finding_bundle(destination, dict.fromkeys(ROLES, b"same"))
    document = bundle.manifest
    document["roles"]["back_receipt"]["size_bytes"] += 1
    rewrite_manifest(destination, document)
    with pytest.raises(BundleError, match="conflicting"):
        read_tagged_finding_bundle(destination)
