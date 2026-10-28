"""Opaque search envelope attacks, immutable publication and bounded reads."""

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import pytest

from tickwitness.domain.evidence.search_evidence import (
    MAX_FILES,
    MAX_MANIFEST_BYTES,
    MAX_TOTAL_BYTES,
    REQUIRED_ROLES,
)
from tickwitness.infrastructure import evidence_bundles as legacy
from tickwitness.infrastructure import search_evidence_bundles as bundles
from tickwitness.infrastructure.evidence_bundles import (
    BundleDestinationExistsError,
    BundleDurabilityError,
    BundleError,
    BundleNotFoundError,
)
from tickwitness.infrastructure.search_evidence_bundles import (
    SearchEvidenceBundle,
    SearchEvidenceLimits,
    SearchEvidenceMissingObjectError,
    export_search_evidence_bundle,
    read_search_evidence_bundle,
)


def artifacts():
    # Deliberately opaque: this layer must never pretend these bytes are a
    # semantically valid source/ledger proof. The app tests that separately.
    result = {role: ("opaque-" + role).encode() for role in REQUIRED_ROLES}
    result.update({
        "allocation/0001": b"allocation",
        "candidate/0001/dispatch": b"dispatch",
        "candidate/0001/link": b"link",
        "candidate/0001/result": b"captured-result",
        "reservation/0001": b"reservation",
        "attempt/" + "a" * 64 + "/intent": b"intent",
        "attempt/" + "a" * 64 + "/outcome": b"outcome",
        "cas/" + "b" * 64: b"cas-body",
    })
    return result


def exported(tmp_path, payload=None):
    root = tmp_path / "bundle"
    package = export_search_evidence_bundle(root, artifacts() if payload is None else payload)
    return root, package


def rewrite(root, mutate):
    path = root / "manifest.json"
    document = json.loads(path.read_bytes())
    mutate(document)
    path.write_bytes(legacy._canonical(document))


def test_variable_roles_round_trip_and_detached_views(tmp_path):
    payload = artifacts()
    root, package = exported(tmp_path, payload)
    restored = read_search_evidence_bundle(root)
    assert restored == package and restored.artifacts == payload
    assert restored.bundle_id == legacy._digest(restored.manifest_bytes)
    assert set(root.iterdir()) == {root / "manifest.json", root / "objects"}
    restored.manifest["roles"].clear()
    restored.artifacts["raw"] = b"mutated detached view"
    assert read_search_evidence_bundle(root) == package
    with pytest.raises(FrozenInstanceError):
        restored.manifest_bytes = b"changed"


def test_payload_aliases_are_one_physical_object_with_all_roles(tmp_path):
    payload = artifacts()
    payload["raw"] = payload["normalized"] = b"same-content"
    root, package = exported(tmp_path, payload)
    roles = package.manifest["roles"]
    assert roles["raw"] == roles["normalized"]
    assert len(tuple((root / "objects" / "sha256").iterdir())) == len(set(payload.values()))
    assert read_search_evidence_bundle(root).artifacts == payload


def test_missing_declared_alias_reports_exact_roles_and_sha(tmp_path):
    payload = artifacts()
    payload["raw"] = payload["normalized"] = b"same-content"
    root, package = exported(tmp_path, payload)
    sha = package.manifest["roles"]["raw"]["sha256"]
    (root / "objects" / "sha256" / sha).unlink()
    with pytest.raises(SearchEvidenceMissingObjectError) as caught:
        read_search_evidence_bundle(root)
    assert caught.value.sha256 == sha
    assert set(caught.value.roles) == {"raw", "normalized"}
    assert caught.value.role in caught.value.roles
    assert sha in str(caught.value) and "raw" in str(caught.value)


def test_missing_whole_object_directory_keeps_precise_error(tmp_path):
    root, package = exported(tmp_path)
    shutil.rmtree(root / "objects")
    with pytest.raises(SearchEvidenceMissingObjectError) as caught:
        read_search_evidence_bundle(root)
    expected = package.manifest["roles"][caught.value.role]["sha256"]
    assert caught.value.sha256 == expected


def test_tightening_boundaries_count_unique_objects_and_manifest(tmp_path):
    root, package = exported(tmp_path)
    payload = package.artifacts
    total = len(package.manifest_bytes) + sum(len(raw) for raw in set(payload.values()))
    files = len(set(payload.values())) + 1
    exact = SearchEvidenceLimits(total, files, len(package.manifest_bytes))
    assert read_search_evidence_bundle(root, limits=exact) == package
    for limits in (
        SearchEvidenceLimits(total - 1, files, len(package.manifest_bytes)),
        SearchEvidenceLimits(total, files - 1, len(package.manifest_bytes)),
        SearchEvidenceLimits(total, files, len(package.manifest_bytes) - 1),
    ):
        with pytest.raises(BundleError):
            read_search_evidence_bundle(root, limits=limits)


@pytest.mark.parametrize("field,maximum", [
    ("max_total_bytes", MAX_TOTAL_BYTES),
    ("max_files", MAX_FILES),
    ("max_manifest_bytes", MAX_MANIFEST_BYTES),
])
@pytest.mark.parametrize("kind", ["zero", "negative", "bool", "float", "broaden"])
def test_limits_only_allow_positive_integers_tightening_profile(field, maximum, kind):
    value = {"zero": 0, "negative": -1, "bool": True, "float": 1.0, "broaden": maximum + 1}[kind]
    with pytest.raises(BundleError):
        SearchEvidenceLimits(**{field: value})


def test_reader_rechecks_forged_or_foreign_limit_object(tmp_path):
    root, _ = exported(tmp_path)
    forged = SearchEvidenceLimits()
    object.__setattr__(forged, "max_files", MAX_FILES + 1)
    for limits in (forged, legacy.BundleLimits(), None):
        with pytest.raises(BundleError):
            read_search_evidence_bundle(root, limits=limits)


@pytest.mark.parametrize("role", [
    "../raw", "cas/not-a-hash", "candidate/0000/result", "candidate/1025/result",
    "candidate/0001/unknown", "allocation/1", "reservation/0000", "unknown",
])
def test_invalid_role_rejected_before_filesystem_changes(tmp_path, role):
    payload = artifacts()
    payload[role] = b"invalid"
    with pytest.raises(BundleError):
        export_search_evidence_bundle(tmp_path / "rejected", payload)
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize("attack", ["empty", "mutable", "missing", "oversized"])
def test_invalid_payload_rejected_before_publication(tmp_path, attack):
    payload = artifacts()
    if attack == "empty":
        payload["raw"] = b""
    elif attack == "mutable":
        payload["raw"] = bytearray(b"mutable")
    elif attack == "missing":
        del payload["snapshot"]
    else:
        payload["budget"] = b"x" * (64 * 1024 + 1)
    with pytest.raises(BundleError):
        export_search_evidence_bundle(tmp_path / "rejected", payload)
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize("attack", [
    "kind", "scope", "bool_version", "unknown", "role", "hash", "size_bool", "ref", "alias_size",
])
def test_manifest_declarations_are_strict_even_when_reencoded(tmp_path, attack):
    root, _ = exported(tmp_path)

    def mutate(document):
        reference = document["roles"]["raw"]
        if attack == "kind":
            document["kind"] = "evidence_bundle_v1"
        elif attack == "scope":
            document["scope"] = "confirmation"
        elif attack == "bool_version":
            document["schema_version"] = True
        elif attack == "unknown":
            document["surprise"] = None
        elif attack == "role":
            document["roles"]["surprise"] = reference
        elif attack == "hash":
            reference["sha256"] = "A" * 64
        elif attack == "size_bool":
            reference["size_bytes"] = True
        elif attack == "ref":
            reference["ref"] = "../outside"
        else:
            document["roles"]["normalized"] = dict(
                reference, size_bytes=reference["size_bytes"] + 1
            )

    rewrite(root, mutate)
    with pytest.raises(BundleError):
        read_search_evidence_bundle(root)


@pytest.mark.parametrize("attack", ["whitespace", "duplicate", "float", "nonfinite"])
def test_noncanonical_duplicate_and_noninteger_manifest_json_rejected(tmp_path, attack):
    root, package = exported(tmp_path)
    raw = package.manifest_bytes
    changed = {
        "whitespace": raw + b"\n",
        "duplicate": raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
        "float": raw.replace(b'"schema_version":1', b'"schema_version":1.0'),
        "nonfinite": raw.replace(b'"schema_version":1', b'"schema_version":NaN'),
    }[attack]
    assert changed != raw
    (root / "manifest.json").write_bytes(changed)
    with pytest.raises(BundleError):
        read_search_evidence_bundle(root)


@pytest.mark.parametrize("attack", ["symlink", "fifo", "directory", "hash"])
def test_declared_objects_cannot_redirect_block_or_change_content(tmp_path, attack):
    root, package = exported(tmp_path)
    sha = package.manifest["roles"]["raw"]["sha256"]
    path = root / "objects" / "sha256" / sha
    original = path.read_bytes()
    path.unlink()
    if attack == "symlink":
        target = tmp_path / "outside"
        target.write_bytes(original)
        path.symlink_to(target)
    elif attack == "fifo":
        os.mkfifo(path)
    elif attack == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"!" + original[1:])
    with pytest.raises(BundleError):
        read_search_evidence_bundle(root)


@pytest.mark.parametrize("location", ["root", "objects", "content"])
def test_hidden_or_extra_entries_are_not_ignored(tmp_path, location):
    root, _ = exported(tmp_path)
    selected = {
        "root": root,
        "objects": root / "objects",
        "content": root / "objects" / "sha256",
    }[location]
    (selected / ".hidden-extra").write_bytes(b"unexpected")
    with pytest.raises(BundleError):
        read_search_evidence_bundle(root)


def test_existing_destination_is_never_changed(tmp_path):
    root, package = exported(tmp_path)
    before = (root / "manifest.json").read_bytes()
    with pytest.raises(BundleDestinationExistsError):
        export_search_evidence_bundle(root, package.artifacts)
    assert (root / "manifest.json").read_bytes() == before
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(BundleDestinationExistsError):
        export_search_evidence_bundle(empty, artifacts())
    assert tuple(empty.iterdir()) == ()


def test_parent_and_root_symlinks_are_not_followed(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(parent, target_is_directory=True)
    with pytest.raises(BundleError):
        export_search_evidence_bundle(link / "rejected", artifacts())
    assert not (parent / "rejected").exists()
    root, _ = exported(tmp_path)
    root_alias = tmp_path / "bundle-alias"
    root_alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(BundleError):
        read_search_evidence_bundle(root_alias)


def test_missing_roots_and_parents_are_not_created(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(BundleNotFoundError):
        read_search_evidence_bundle(missing)
    with pytest.raises(BundleError):
        export_search_evidence_bundle(missing / "new", artifacts())
    assert not missing.exists()


def test_old_and_search_bundle_formats_reject_each_other(tmp_path):
    new_root, _ = exported(tmp_path)
    old = tmp_path / "old"
    legacy.export_bundle(old, {role: role.encode() for role in legacy._ROLE_LIMITS})
    with pytest.raises(BundleError):
        legacy.read_bundle(new_root)
    with pytest.raises(BundleError):
        read_search_evidence_bundle(old)


def test_concurrent_publication_has_one_complete_winner(tmp_path):
    destination = tmp_path / "bundle"
    barrier = Barrier(4)

    def publish(_index):
        barrier.wait()
        try:
            return export_search_evidence_bundle(destination, artifacts())
        except BundleDestinationExistsError as error:
            return error

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(publish, range(4)))
    assert sum(isinstance(item, SearchEvidenceBundle) for item in results) == 1
    assert sum(isinstance(item, BundleDestinationExistsError) for item in results) == 3
    assert read_search_evidence_bundle(destination).artifacts == artifacts()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["bundle"]


def test_precommit_failure_removes_staging_without_publishing(tmp_path, monkeypatch):
    def failed_write(*_args, **_kwargs):
        raise OSError("injected before publication")

    monkeypatch.setattr(legacy, "_write_file", failed_write)
    with pytest.raises(BundleError, match="injected before publication"):
        export_search_evidence_bundle(tmp_path / "bundle", artifacts())
    assert tuple(tmp_path.iterdir()) == ()


def test_postcommit_sync_failure_retains_complete_published_bundle(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    original_rename, original_sync = legacy._rename_exclusive, os.fsync
    committed = False

    def rename(parent, source, target):
        nonlocal committed
        original_rename(parent, source, target)
        committed = True

    def sync(descriptor):
        if committed:
            raise OSError("injected parent sync uncertainty")
        original_sync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(legacy, "_rename_exclusive", rename)
        patch.setattr(os, "fsync", sync)
        with pytest.raises(BundleDurabilityError):
            export_search_evidence_bundle(root, artifacts())
    assert read_search_evidence_bundle(root).artifacts == artifacts()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["bundle"]


def test_immutable_bundle_rejects_duplicate_and_incomplete_payload(tmp_path):
    _root, package = exported(tmp_path)
    contents = package._contents
    for malformed in (contents + (contents[0],), contents[1:], list(contents)):
        with pytest.raises(BundleError):
            SearchEvidenceBundle(package.manifest_bytes, malformed)


def test_unsupported_atomic_publish_fails_before_staging(tmp_path, monkeypatch):
    def unavailable():
        raise BundleError("atomic no-replace is unavailable")

    monkeypatch.setattr(legacy, "_rename_operation", unavailable)
    with pytest.raises(BundleError, match="unavailable"):
        export_search_evidence_bundle(tmp_path / "bundle", artifacts())
    assert tuple(tmp_path.iterdir()) == ()
