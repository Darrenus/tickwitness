"""Queue family publication has its own strict namespace and no-replace durability."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.tagged_queue_protocol import build_tagged_queue_protocol
from tickwitness.infrastructure.executable_registry import (
    ExecutableRegistryError,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.tagged_queue_registry import (
    LocalTaggedQueueRegistry,
    TaggedQueueNotFoundError,
    TaggedQueueRecord,
    TaggedQueueRegistryError,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def family_bytes() -> bytes:
    request = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    source = build_executable_protocol(
        canonical(request), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    actual = ReplayInput(
        "a" * 64,
        normalize_events((EXAMPLES / "queue-observations.jsonl").read_bytes()).normalized_bytes,
        build_replay_spec(canonical(request["replay_spec"])),
    )
    return build_tagged_queue_protocol(
        canonical(
            {
                "kind": "tagged_queue_request_v1",
                "schema_version": 1,
                "claim": {
                    "title": "Tagged inventory",
                    "hypothesis": "Finite marked profit",
                    "metric": "tagged_inventory_net_marked_pnl_v1",
                    "unit": "USD",
                    "comparator": "gt",
                    "threshold": "0",
                },
                "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 1000},
            }
        ),
        source_protocol=source,
        replay_input=actual,
        queue_request=(EXAMPLES / "queue-constraint-request.json").read_bytes(),
    ).canonical_bytes


def test_strict_namespace_idempotency_and_immutable_record(tmp_path: Path) -> None:
    registry = LocalTaggedQueueRegistry(tmp_path, create=True)
    raw = family_bytes()
    first, repeat = registry.seal(raw), registry.seal(raw)
    assert first.created is True and repeat.created is False
    assert first.protocol_id == digest(raw)
    assert registry.get(first.protocol_id) == repeat
    assert LocalTaggedQueueRegistry(tmp_path, create=False).get(first.protocol_id) == repeat
    assert sorted(path.name for path in tmp_path.iterdir()) == ["tagged-queue-protocols"]
    assert list((tmp_path / "tagged-queue-protocols").iterdir()) == [
        tmp_path / "tagged-queue-protocols" / f"{first.protocol_id}.json"
    ]
    with pytest.raises(FrozenInstanceError):
        first.created = False  # type: ignore[misc]
    with pytest.raises(TaggedQueueRegistryError):
        TaggedQueueRecord(first.protocol_id, raw, 1)  # type: ignore[arg-type]
    with pytest.raises(TaggedQueueRegistryError):
        TaggedQueueRecord("0" * 64, raw, False)


def test_v2_and_queue_readers_cannot_publish_each_others_protocol(tmp_path: Path) -> None:
    families = LocalTaggedQueueRegistry(tmp_path, create=True)
    v2 = LocalExecutableProtocolRegistry(tmp_path)
    raw = family_bytes()
    source = canonical(json.loads(raw)["source_protocol"])
    with pytest.raises(TaggedQueueRegistryError):
        families.seal(source)
    with pytest.raises(ExecutableRegistryError):
        v2.seal(raw)
    assert list((tmp_path / "tagged-queue-protocols").iterdir()) == []
    assert list((tmp_path / "protocols").iterdir()) == []


def test_default_open_is_read_only_and_legacy_shadow_reader_rejects_new_protocol(tmp_path) -> None:
    from tickwitness.infrastructure.queue_family_registry import (
        LocalQueueFamilyRegistry,
        QueueFamilyRegistryError,
    )

    missing = tmp_path / "missing"
    with pytest.raises(TaggedQueueNotFoundError):
        LocalTaggedQueueRegistry(missing)
    assert not missing.exists()
    old = LocalQueueFamilyRegistry(tmp_path / "old")
    with pytest.raises(QueueFamilyRegistryError):
        old.seal(family_bytes())
    assert list((tmp_path / "old" / "queue-families").iterdir()) == []


def test_read_only_operations_create_nothing_and_never_repair_corruption(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(TaggedQueueNotFoundError):
        LocalTaggedQueueRegistry(missing, create=False)
    assert not missing.exists()
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(TaggedQueueRegistryError):
        LocalTaggedQueueRegistry(root, create=False)
    assert list(root.iterdir()) == []
    registry = LocalTaggedQueueRegistry(root, create=True)
    with pytest.raises(TaggedQueueNotFoundError):
        registry.get("0" * 64)
    record = registry.seal(family_bytes())
    path = root / "tagged-queue-protocols" / f"{record.protocol_id}.json"
    corrupted = record.canonical_bytes[:-1] + b"!"
    path.write_bytes(corrupted)
    with pytest.raises(TaggedQueueRegistryError, match="hash"):
        registry.get(record.protocol_id)
    with pytest.raises(TaggedQueueRegistryError, match="hash"):
        registry.seal(record.canonical_bytes)
    assert path.read_bytes() == corrupted


def test_concurrent_shared_family_publication_has_exactly_one_winner(tmp_path: Path) -> None:
    raw = family_bytes()
    root = tmp_path / "nested" / "registry"
    barrier = Barrier(8)

    def publish() -> TaggedQueueRecord:
        barrier.wait(timeout=5)
        return LocalTaggedQueueRegistry(root, create=True).seal(raw)

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(lambda _: publish(), range(8)))
    assert len({record.protocol_id for record in records}) == 1
    assert sum(record.created for record in records) == 1
    assert [path.name for path in (root / "tagged-queue-protocols").iterdir()] == [
        f"{records[0].protocol_id}.json"
    ]


def test_matching_hash_does_not_bless_forged_scope_or_budget_ownership(tmp_path: Path) -> None:
    registry = LocalTaggedQueueRegistry(tmp_path, create=True)
    document = json.loads(family_bytes())
    document["scope"]["finding_issued"] = True
    raw = canonical(document)
    family_id = digest(raw)
    (tmp_path / "tagged-queue-protocols" / f"{family_id}.json").write_bytes(raw)
    with pytest.raises(TaggedQueueRegistryError, match="Invalid tagged queue protocol"):
        registry.get(family_id)
    with pytest.raises(TaggedQueueRegistryError):
        registry.seal(raw)


@pytest.mark.parametrize("target", ["root", "tagged-queue-protocols", "file"])
def test_symlinks_are_never_followed_even_for_matching_content(tmp_path: Path, target: str) -> None:
    root = tmp_path / "registry"
    registry = LocalTaggedQueueRegistry(root, create=True)
    record = registry.seal(family_bytes())
    path = root / "tagged-queue-protocols" / f"{record.protocol_id}.json"
    outside = tmp_path / "outside"
    if target == "file":
        path.rename(outside)
        path.symlink_to(outside)
        with pytest.raises(TaggedQueueRegistryError):
            registry.get(record.protocol_id)
        with pytest.raises(TaggedQueueRegistryError):
            registry.seal(record.canonical_bytes)
        assert outside.read_bytes() == record.canonical_bytes
    else:
        source = root if target == "root" else root / "tagged-queue-protocols"
        source.rename(outside)
        source.symlink_to(outside, target_is_directory=True)
        with pytest.raises(TaggedQueueRegistryError):
            LocalTaggedQueueRegistry(root, create=False)
        with pytest.raises(TaggedQueueRegistryError):
            registry.get(record.protocol_id)


@pytest.mark.parametrize("kind", ["fifo", "directory", "oversize"])
def test_nonregular_and_oversize_evidence_is_rejected_without_blocking(
    tmp_path: Path, kind
) -> None:
    registry = LocalTaggedQueueRegistry(tmp_path, create=True)
    record = registry.seal(family_bytes())
    path = tmp_path / "tagged-queue-protocols" / f"{record.protocol_id}.json"
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(TaggedQueueRegistryError):
        registry.get(record.protocol_id)


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63, "/" + "a" * 64])
def test_digest_is_not_a_path(tmp_path: Path, identity: str) -> None:
    with pytest.raises(TaggedQueueRegistryError, match="64 lowercase"):
        LocalTaggedQueueRegistry(tmp_path, create=True).get(identity)


def test_failed_atomic_link_cleans_temporary_and_never_publishes_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = LocalTaggedQueueRegistry(tmp_path, create=True)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("Injected family publication failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(TaggedQueueRegistryError, match="Injected family publication"):
        registry.seal(family_bytes())
    assert list((tmp_path / "tagged-queue-protocols").iterdir()) == []
