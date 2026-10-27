"""Report authority publication is immutable and isolated from execution protocols."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import pytest

from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.research_contracts.tagged_finding_protocol import (
    build_tagged_finding_protocol,
    load_tagged_finding_protocol,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import load_tagged_queue_protocol
from tickwitness.infrastructure.executable_registry import (
    ExecutableRegistryError,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.tagged_finding_registry import (
    LocalTaggedFindingRegistry,
    TaggedFindingNotFoundError,
    TaggedFindingRecord,
    TaggedFindingRegistryError,
)
from tickwitness.infrastructure.tagged_queue_registry import (
    LocalTaggedQueueRegistry,
    TaggedQueueRegistryError,
)

ROOT = Path(__file__).resolve().parents[2]


def finding_bytes():
    golden = json.loads((ROOT / "tests/fixtures/tagged-pair-native-golden.json").read_bytes())
    subject = load_tagged_queue_protocol(canonical(golden["cases"][0]["protocol"]))
    request = canonical(
        {
            "kind": "tagged_finding_request_v1",
            "schema_version": 1,
            "title": "Conditional tagged findings",
            "authority": "conditional_tagged_findings_v1",
        }
    )
    return build_tagged_finding_protocol(request, subject_protocol=subject).canonical_bytes


def test_strict_namespace_idempotency_and_immutable_record(tmp_path):
    registry = LocalTaggedFindingRegistry(tmp_path, create=True)
    raw = finding_bytes()
    first, repeat = registry.seal(raw), registry.seal(raw)
    assert first.created is True and repeat.created is False
    assert first.protocol_id == digest(raw)
    assert registry.get(first.protocol_id) == repeat
    assert LocalTaggedFindingRegistry(tmp_path).get(first.protocol_id) == repeat
    assert sorted(path.name for path in tmp_path.iterdir()) == ["tagged-finding-protocols"]
    assert list((tmp_path / "tagged-finding-protocols").iterdir()) == [
        tmp_path / "tagged-finding-protocols" / f"{first.protocol_id}.json"
    ]
    with pytest.raises(FrozenInstanceError):
        first.created = False
    with pytest.raises(TaggedFindingRegistryError):
        TaggedFindingRecord(first.protocol_id, raw, 1)
    with pytest.raises(TaggedFindingRegistryError):
        TaggedFindingRecord("0" * 64, raw, False)


def test_finding_and_execution_readers_reject_each_others_contract(tmp_path):
    finding = LocalTaggedFindingRegistry(tmp_path, create=True)
    tagged = LocalTaggedQueueRegistry(tmp_path, create=True)
    legacy = LocalExecutableProtocolRegistry(tmp_path)
    raw = finding_bytes()
    source = load_tagged_finding_protocol(raw).subject_protocol.canonical_bytes
    with pytest.raises(TaggedFindingRegistryError):
        finding.seal(source)
    with pytest.raises(TaggedQueueRegistryError):
        tagged.seal(raw)
    with pytest.raises(ExecutableRegistryError):
        legacy.seal(raw)
    assert list((tmp_path / "tagged-finding-protocols").iterdir()) == []
    assert list((tmp_path / "tagged-queue-protocols").iterdir()) == []
    assert list((tmp_path / "protocols").iterdir()) == []


def test_default_open_is_readonly_and_does_not_create_missing_root(tmp_path):
    missing = tmp_path / "absent"
    with pytest.raises(TaggedFindingNotFoundError):
        LocalTaggedFindingRegistry(missing)
    assert not missing.exists()
    existing = tmp_path / "empty"
    existing.mkdir()
    with pytest.raises(TaggedFindingRegistryError):
        LocalTaggedFindingRegistry(existing)
    assert list(existing.iterdir()) == []


def test_readonly_does_not_repair_rehashed_or_corrupted_protocol(tmp_path):
    registry = LocalTaggedFindingRegistry(tmp_path, create=True)
    record = registry.seal(finding_bytes())
    path = tmp_path / "tagged-finding-protocols" / f"{record.protocol_id}.json"
    corrupt = record.canonical_bytes[:-1] + b"!"
    path.write_bytes(corrupt)
    for operation in (
        lambda: registry.get(record.protocol_id),
        lambda: registry.seal(record.canonical_bytes),
    ):
        with pytest.raises(TaggedFindingRegistryError, match="hash"):
            operation()
    assert path.read_bytes() == corrupt
    document = json.loads(record.canonical_bytes)
    document["unapproved_finding_authority"] = True
    forged = canonical(document)
    forged_id = digest(forged)
    (path.parent / f"{forged_id}.json").write_bytes(forged)
    with pytest.raises(TaggedFindingRegistryError, match="Invalid tagged finding protocol"):
        registry.get(forged_id)
    with pytest.raises(TaggedFindingRegistryError):
        registry.seal(forged)


def test_concurrent_publication_has_one_created_record(tmp_path):
    raw = finding_bytes()
    root = tmp_path / "nested" / "registry"
    barrier = Barrier(8)

    def publish():
        barrier.wait(timeout=5)
        return LocalTaggedFindingRegistry(root, create=True).seal(raw)

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(lambda _: publish(), range(8)))
    assert len({record.protocol_id for record in records}) == 1
    assert sum(record.created for record in records) == 1
    assert [p.name for p in (root / "tagged-finding-protocols").iterdir()] == [
        f"{records[0].protocol_id}.json"
    ]


@pytest.mark.parametrize("target", ["root", "namespace", "file"])
def test_symlinks_are_rejected_even_for_matching_bytes(tmp_path, target):
    root = tmp_path / "registry"
    registry = LocalTaggedFindingRegistry(root, create=True)
    record = registry.seal(finding_bytes())
    path = root / "tagged-finding-protocols" / f"{record.protocol_id}.json"
    outside = tmp_path / "outside"
    if target == "file":
        path.rename(outside)
        path.symlink_to(outside)
        with pytest.raises(TaggedFindingRegistryError):
            registry.get(record.protocol_id)
        with pytest.raises(TaggedFindingRegistryError):
            registry.seal(record.canonical_bytes)
        assert outside.read_bytes() == record.canonical_bytes
    else:
        source = root if target == "root" else path.parent
        source.rename(outside)
        source.symlink_to(outside, target_is_directory=True)
        with pytest.raises(TaggedFindingRegistryError):
            LocalTaggedFindingRegistry(root)
        with pytest.raises(TaggedFindingRegistryError):
            registry.get(record.protocol_id)


@pytest.mark.parametrize("kind", ["fifo", "directory", "oversize"])
def test_nonregular_or_oversize_evidence_is_rejected_without_waiting(tmp_path, kind):
    registry = LocalTaggedFindingRegistry(tmp_path, create=True)
    record = registry.seal(finding_bytes())
    path = tmp_path / "tagged-finding-protocols" / f"{record.protocol_id}.json"
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * (512 * 1024 + 1))
    with pytest.raises(TaggedFindingRegistryError):
        registry.get(record.protocol_id)


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63, "/" + "a" * 64])
def test_digest_is_not_a_path(tmp_path, identity):
    registry = LocalTaggedFindingRegistry(tmp_path, create=True)
    with pytest.raises(TaggedFindingRegistryError, match="64 lowercase"):
        registry.get(identity)


def test_failed_link_cleans_stage_without_partial_publication(tmp_path, monkeypatch):
    registry = LocalTaggedFindingRegistry(tmp_path, create=True)

    def fail(*args, **kwargs):
        raise OSError("Injected authority publication failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(TaggedFindingRegistryError, match="Injected authority publication"):
        registry.seal(finding_bytes())
    assert list((tmp_path / "tagged-finding-protocols").iterdir()) == []


@pytest.mark.parametrize("create", [1, None, "yes"])
def test_create_flag_is_a_genuine_bool(tmp_path, create):
    with pytest.raises(TaggedFindingRegistryError, match="boolean"):
        LocalTaggedFindingRegistry(tmp_path, create=create)
