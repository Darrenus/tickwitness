"""Real immutable preparation IO, isolated from native execution and budgets."""

import os
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.reductions import prepare_reduction_input, verify_reduction_input
from tickwitness.domain.evidence.run_records import canonical, digest, parse
from tickwitness.domain.reduction.contracts import (
    ReductionValidationError,
    build_reduction_manifest,
    role_limit,
)
from tickwitness.infrastructure import evidence_bundles as io
from tickwitness.infrastructure.evidence_bundles import (
    BundleDestinationExistsError,
    BundleDurabilityError,
    BundleError,
    BundleNotFoundError,
)
from tickwitness.infrastructure.reduction_bundles import (
    LocalReductionBundles,
    ReductionInputBundle,
)
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle


@pytest.fixture
def prepared():
    corpus = Path(__file__).parents[2] / "examples" / "alpha" / "counterexample"
    source = read_search_evidence_bundle(corpus)
    return prepare_reduction_input(
        source,
        canonical(
            {
                "kind": "reduction_request_v1",
                "schema_version": 1,
                "witness_ordinal": 3,
                "focus_from_capture_seq": 4,
                "through_capture_seq": 6,
                "additional_delay_ns": 1_000_000_000,
            }
        ),
        expected_bundle_id=source.bundle_id,
        expected_report_id=digest(source.artifacts["finding_report"]),
    )


def _prepared(artifacts):
    return SimpleNamespace(
        artifacts=artifacts,
        preparation_id=digest(build_reduction_manifest(artifacts)),
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def _json_bytes(size: int) -> bytes:
    overhead = len(canonical({"padding": ""}))
    return canonical({"padding": "x" * (size - overhead)})


def test_exact_four_files_roundtrip_and_detached_content(tmp_path: Path, prepared) -> None:
    source = tmp_path / "source"
    source.mkdir()
    publisher = LocalReductionBundles(source)
    output = tmp_path / "preparation"
    saved = publisher.publish(prepared, output)
    assert saved.preparation_id == prepared.preparation_id == digest(saved.manifest_bytes)
    assert saved.artifacts == prepared.artifacts
    assert set(_tree(output)) == {
        "manifest.json",
        "recipe.json",
        "materialization.json",
        "normalized.jsonl",
    }
    assert _tree(output) == {
        "manifest.json": saved.manifest_bytes,
        "recipe.json": prepared.artifacts["recipe"],
        "materialization.json": prepared.artifacts["materialization"],
        "normalized.jsonl": prepared.artifacts["normalized"],
    }
    before = {path: path.stat().st_mtime_ns for path in output.iterdir()}
    assert publisher.read(output) == saved
    assert {path: path.stat().st_mtime_ns for path in output.iterdir()} == before
    detached = saved.artifacts
    detached["normalized"] = b"changed"
    assert saved.artifacts == prepared.artifacts
    with pytest.raises(FrozenInstanceError):
        saved.manifest_bytes = b"{}"  # type: ignore[misc]


def test_reader_is_independent_of_original_input_root_and_allows_relocation(
    tmp_path: Path, prepared
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "preparation"
    saved = LocalReductionBundles(source).publish(prepared, output)
    relocated = tmp_path / "relocated"
    output.rename(relocated)
    shutil.rmtree(source)
    assert LocalReductionBundles(tmp_path / "never-created-source").read(relocated) == saved
    assert not source.exists()
    assert not (tmp_path / "never-created-source").exists()


def test_publish_refuses_source_root_descendants_and_aliases_before_writing(
    tmp_path: Path, prepared
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    publisher = LocalReductionBundles(source)
    for output in (source, source / "nested", alias / "nested"):
        with pytest.raises(BundleError, match="outside"):
            publisher.publish(prepared, output)
    assert list(source.iterdir()) == []
    with pytest.raises(BundleError, match="outside"):
        LocalReductionBundles(alias).publish(prepared, source / "nested")
    assert list(source.iterdir()) == []


def test_existing_destination_and_atomic_creation_race_preserve_winner(
    tmp_path: Path, prepared
) -> None:
    publisher = LocalReductionBundles(tmp_path / "source")
    output = tmp_path / "saved"
    saved = publisher.publish(prepared, output)
    original = _tree(output)
    with pytest.raises(BundleDestinationExistsError):
        publisher.publish(prepared, output)
    assert _tree(output) == original
    assert publisher.read(output) == saved
    raced = tmp_path / "raced"
    created = False

    def writer(directory: int, name: str, raw: bytes) -> None:
        nonlocal created
        if not created:
            created = True
            raced.mkdir()
            (raced / "winner").write_bytes(b"preserve")
        io._write_file(directory, name, raw)

    with pytest.raises(BundleDestinationExistsError):
        LocalReductionBundles(tmp_path / "source", writer=writer).publish(prepared, raced)
    assert _tree(raced) == {"winner": b"preserve"}
    assert not any(path.name.startswith(".tickwitness-reduction-") for path in tmp_path.iterdir())


@pytest.mark.parametrize("point", ["writer", "stage_sync"])
def test_precommit_failure_cleans_stage_and_returns_no_package(
    tmp_path: Path, prepared, point: str
) -> None:
    def writer(directory: int, name: str, raw: bytes) -> None:
        if point == "writer":
            raise OSError("Injected reduction write failure")
        io._write_file(directory, name, raw)

    def sync(_directory: int, phase: str) -> None:
        assert point == "stage_sync" and phase == "stage"
        raise OSError("Injected reduction stage sync failure")

    publisher = LocalReductionBundles(tmp_path / "source", writer=writer, sync=sync)
    output = tmp_path / "failed"
    with pytest.raises(BundleError, match="Injected"):
        publisher.publish(prepared, output)
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_postcommit_sync_uncertainty_preserves_complete_target_without_success(
    tmp_path: Path, prepared
) -> None:
    def sync(directory: int, phase: str) -> None:
        if phase == "parent":
            raise OSError("Injected reduction durability uncertainty")
        os.fsync(directory)

    output = tmp_path / "unconfirmed"
    publisher = LocalReductionBundles(tmp_path / "source", sync=sync)
    with pytest.raises(BundleDurabilityError, match="unconfirmed"):
        publisher.publish(prepared, output)
    readback = publisher.read(output)
    assert readback.preparation_id == prepared.preparation_id
    assert readback.artifacts == prepared.artifacts
    assert set(_tree(output)) == {
        "manifest.json",
        "recipe.json",
        "materialization.json",
        "normalized.jsonl",
    }
    with pytest.raises(BundleDestinationExistsError):
        publisher.publish(prepared, output)


def test_wrong_prepared_identity_or_invalid_artifacts_publish_nothing(
    tmp_path: Path, prepared
) -> None:
    publisher = LocalReductionBundles(tmp_path / "source")
    variants = [
        SimpleNamespace(artifacts=prepared.artifacts, preparation_id="0" * 64),
        SimpleNamespace(artifacts={**prepared.artifacts, "extra": b"x"}, preparation_id="0" * 64),
        SimpleNamespace(artifacts={"recipe": b"{}"}, preparation_id="0" * 64),
        SimpleNamespace(artifacts={**prepared.artifacts, "recipe": b"[]"}, preparation_id="0" * 64),
    ]
    for value in variants:
        with pytest.raises(BundleError):
            publisher.publish(value, tmp_path / "invalid")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("role", ["recipe", "materialization", "normalized"])
def test_role_byte_boundaries_accept_exact_limit_and_reject_overflow(
    tmp_path: Path, prepared, role: str
) -> None:
    maximum = role_limit(role)
    exact = b"x" * maximum if role == "normalized" else _json_bytes(maximum)
    assert len(exact) == maximum
    artifacts = {**prepared.artifacts, role: exact}
    publisher = LocalReductionBundles(tmp_path / "source")
    saved = publisher.publish(_prepared(artifacts), tmp_path / "exact")
    assert saved.artifacts[role] == exact
    oversized = b"x" * (maximum + 1) if role == "normalized" else _json_bytes(maximum + 1)
    with pytest.raises(BundleError):
        publisher.publish(
            SimpleNamespace(
                artifacts={**prepared.artifacts, role: oversized}, preparation_id="0" * 64
            ),
            tmp_path / "oversize",
        )
    assert not (tmp_path / "oversize").exists()


def test_bundle_constructor_rejects_mutable_duplicate_missing_and_rehashed_references(prepared):
    raw = build_reduction_manifest(prepared.artifacts)
    pairs = tuple(sorted(prepared.artifacts.items()))
    for invalid in (list(pairs), (*pairs, pairs[0]), pairs[:-1], (([], b"unhashable"),)):
        with pytest.raises(BundleError):
            ReductionInputBundle(raw, invalid)
    artifacts = {**prepared.artifacts, "normalized": bytearray(prepared.artifacts["normalized"])}
    with pytest.raises(BundleError):
        ReductionInputBundle(raw, tuple(artifacts.items()))
    document = parse(raw)
    document["roles"]["recipe"]["sha256"] = "0" * 64
    with pytest.raises(BundleError, match="references"):
        ReductionInputBundle(canonical(document), pairs)


@pytest.mark.parametrize(
    "change", ["marker", "bool", "unknown", "float", "path", "size", "missing", "noncanonical"]
)
def test_manifest_is_exact_canonical_bounded_and_has_only_fixed_refs(
    tmp_path: Path, prepared, change: str
) -> None:
    output = tmp_path / "saved"
    publisher = LocalReductionBundles(tmp_path / "source")
    saved = publisher.publish(prepared, output)
    document = parse(saved.manifest_bytes)
    if change == "marker":
        document["scope"] = "execution_approved"
    elif change == "bool":
        document["schema_version"] = True
    elif change == "unknown":
        document["checkpoint"] = True
    elif change == "float":
        document["roles"]["recipe"]["size_bytes"] = 1.0
    elif change == "path":
        document["roles"]["recipe"]["ref"] = "../outside.json"
    elif change == "size":
        document["roles"]["normalized"]["size_bytes"] = role_limit("normalized") + 1
    elif change == "missing":
        del document["roles"]["recipe"]
    raw = canonical(document)
    if change == "noncanonical":
        raw += b"\n"
    (output / "manifest.json").write_bytes(raw)
    with pytest.raises(BundleError):
        publisher.read(output)


@pytest.mark.parametrize(
    "target", ["root", "manifest.json", "recipe.json", "materialization.json", "normalized.jsonl"]
)
def test_fixed_roots_and_files_cannot_be_symlinks(tmp_path: Path, prepared, target: str) -> None:
    publisher = LocalReductionBundles(tmp_path / "source")
    output = tmp_path / "saved"
    publisher.publish(prepared, output)
    path = output if target == "root" else output / target
    outside = tmp_path / "outside"
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=outside.is_dir())
    with pytest.raises(BundleError):
        publisher.read(output)
    assert outside.exists()


@pytest.mark.parametrize(
    "filename", ["manifest.json", "recipe.json", "materialization.json", "normalized.jsonl"]
)
@pytest.mark.parametrize("kind", ["missing", "fifo", "directory", "oversize", "changed"])
def test_files_are_required_regular_nonblocking_and_size_hash_checked(
    tmp_path: Path, prepared, filename: str, kind: str
) -> None:
    publisher = LocalReductionBundles(tmp_path / "source")
    output = tmp_path / "saved"
    publisher.publish(prepared, output)
    path = output / filename
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "oversize":
        with path.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
    elif kind == "changed":
        path.write_bytes(b"changed")
    with pytest.raises(BundleError):
        publisher.read(output)


@pytest.mark.parametrize("name", ["extra.json", ".hidden", "empty"])
def test_unknown_files_hidden_entries_and_empty_directories_are_rejected(
    tmp_path: Path, prepared, name: str
) -> None:
    publisher = LocalReductionBundles(tmp_path / "source")
    output = tmp_path / "saved"
    publisher.publish(prepared, output)
    if name == "empty":
        (output / name).mkdir()
    else:
        (output / name).write_bytes(b"extra")
    with pytest.raises(BundleError):
        publisher.read(output)


def test_missing_preparation_does_not_create_input_or_output_state(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(BundleNotFoundError):
        LocalReductionBundles(tmp_path / "source").read(missing)
    assert list(tmp_path.iterdir()) == []


def test_constructor_does_no_source_io_or_writes(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Constructing the IO adapter cannot open source or output files")

    monkeypatch.setattr(os, "open", forbidden)
    LocalReductionBundles(tmp_path / "not-created")
    assert list(tmp_path.iterdir()) == []


def test_rehashed_saved_flags_close_the_envelope_but_never_pass_semantic_recomputation(
    tmp_path: Path, prepared
) -> None:
    source = read_search_evidence_bundle(
        Path(__file__).parents[2] / "examples" / "alpha" / "counterexample"
    )
    artifacts = prepared.artifacts
    document = parse(artifacts["materialization"], limit=role_limit("materialization"))
    document["flags"]["initial_state_materialized"] = True
    document["flags"]["native_replayed"] = True
    artifacts["materialization"] = canonical(document)
    forged = _prepared(artifacts)
    publisher = LocalReductionBundles(tmp_path / "source")
    saved = publisher.publish(forged, tmp_path / "forged")
    assert saved.preparation_id == forged.preparation_id
    with pytest.raises(ReductionValidationError):
        verify_reduction_input(saved, source=source, expected_preparation_id=saved.preparation_id)
