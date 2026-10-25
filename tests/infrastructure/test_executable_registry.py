"""Real filesystem publication, corruption and concurrent immutable v2 writes."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import pytest

from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.infrastructure.executable_registry import (
    ExecutableProtocolNotFoundError,
    ExecutableProtocolRecord,
    ExecutableRegistryError,
    LocalExecutableProtocolRegistry,
)


def protocol_bytes() -> bytes:
    request = {
        "schema_version": 2,
        "claim": {
            "title": "Original local registry fixture",
            "hypothesis": "Synthetic net marked PnL is positive under the bound model.",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "0",
            "unit": "USD",
        },
        "replay_spec": {
            "schema_version": 1,
            "clock_policy_id": "receive_order_v1",
            "instrument": {
                "base_currency": "EUR",
                "quote_currency": "USD",
                "price_increment": "1",
                "size_increment": "1",
            },
            "account": {"starting_cash": "10000"},
            "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
            "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
            "strategy": {
                "kind": "single_limit_buy_v1",
                "submit_capture_seq": 1,
                "limit_price_ticks": 100,
                "quantity_lots": 2,
                "cancel_after_first_fill": False,
            },
            "seed": 7,
        },
        "budget": {"max_attempts": 3, "max_wall_seconds": 30, "max_events": 1_000},
    }
    return build_executable_protocol(
        json.dumps(request).encode(),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
    ).canonical_bytes


def test_roundtrip_idempotency_immutable_record_and_no_source_objects(tmp_path: Path) -> None:
    registry = LocalExecutableProtocolRegistry(tmp_path)
    raw = protocol_bytes()
    first, repeat = registry.seal(raw), registry.seal(raw)
    assert first.created is True and repeat.created is False
    assert first.protocol_id == hashlib.sha256(raw).hexdigest()
    assert registry.get(first.protocol_id) == repeat
    assert LocalExecutableProtocolRegistry(tmp_path, create=False).get(first.protocol_id) == repeat
    assert sorted(path.name for path in tmp_path.iterdir()) == ["protocols"]
    assert len(list((tmp_path / "protocols").iterdir())) == 1
    with pytest.raises(FrozenInstanceError):
        first.created = False  # type: ignore[misc]
    with pytest.raises(ExecutableRegistryError):
        ExecutableProtocolRecord(first.protocol_id, bytearray(raw), False)  # type: ignore[arg-type]


def test_read_only_missing_root_and_missing_id_create_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ExecutableProtocolNotFoundError):
        LocalExecutableProtocolRegistry(missing, create=False)
    assert not missing.exists()
    root = tmp_path / "empty-root"
    root.mkdir()
    with pytest.raises(ExecutableRegistryError):
        LocalExecutableProtocolRegistry(root, create=False)
    assert list(root.iterdir()) == []
    registry = LocalExecutableProtocolRegistry(root)
    before = {path: path.stat().st_mtime_ns for path in root.rglob("*")}
    with pytest.raises(ExecutableProtocolNotFoundError):
        registry.get("0" * 64)
    assert {path: path.stat().st_mtime_ns for path in root.rglob("*")} == before


@pytest.mark.parametrize("round_id", range(3))
def test_concurrent_fresh_publication_has_one_winner(tmp_path: Path, round_id: int) -> None:
    root = tmp_path / str(round_id) / "nested"
    raw = protocol_bytes()
    barrier = Barrier(8)

    def together() -> ExecutableProtocolRecord:
        barrier.wait(timeout=5)
        return LocalExecutableProtocolRegistry(root).seal(raw)

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(lambda _: together(), range(8)))
    assert len({record.protocol_id for record in records}) == 1
    assert sum(record.created for record in records) == 1
    assert [path.name for path in (root / "protocols").iterdir()] == [
        f"{records[0].protocol_id}.json"
    ]


def test_tampering_is_detected_and_seal_never_repairs_it(tmp_path: Path) -> None:
    registry = LocalExecutableProtocolRegistry(tmp_path)
    record = registry.seal(protocol_bytes())
    path = tmp_path / "protocols" / f"{record.protocol_id}.json"
    original = path.read_bytes()
    altered = original[:-1] + b"!"
    path.write_bytes(altered)
    with pytest.raises(ExecutableRegistryError, match="hash"):
        registry.get(record.protocol_id)
    with pytest.raises(ExecutableRegistryError, match="hash"):
        registry.seal(original)
    assert path.read_bytes() == altered


def test_matching_hash_does_not_bless_forged_policies_or_v1(tmp_path: Path) -> None:
    registry = LocalExecutableProtocolRegistry(tmp_path)
    value = json.loads(protocol_bytes())
    value["read_policy"] = "confirmation_unsealed"
    forged = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    identity = hashlib.sha256(forged).hexdigest()
    (tmp_path / "protocols" / f"{identity}.json").write_bytes(forged)
    with pytest.raises(ExecutableRegistryError, match="Invalid executable"):
        registry.get(identity)
    with pytest.raises(ExecutableRegistryError):
        registry.seal(forged)


@pytest.mark.parametrize("target", ["root", "protocols", "file"])
def test_symlinks_are_not_followed_even_with_matching_bytes(tmp_path: Path, target: str) -> None:
    root = tmp_path / "registry"
    registry = LocalExecutableProtocolRegistry(root)
    record = registry.seal(protocol_bytes())
    path = root / "protocols" / f"{record.protocol_id}.json"
    outside = tmp_path / "outside"
    if target == "file":
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        with pytest.raises(ExecutableRegistryError):
            registry.get(record.protocol_id)
        with pytest.raises(ExecutableRegistryError):
            registry.seal(record.canonical_bytes)
        assert outside.read_bytes() == record.canonical_bytes
    else:
        source = root if target == "root" else root / "protocols"
        source.rename(outside)
        source.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ExecutableRegistryError):
            LocalExecutableProtocolRegistry(root, create=False)
        with pytest.raises(ExecutableRegistryError):
            registry.get(record.protocol_id)


def test_dangling_root_symlink_is_unsafe_not_absent(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    root.symlink_to(tmp_path / "absent", target_is_directory=True)
    with pytest.raises(ExecutableRegistryError) as caught:
        LocalExecutableProtocolRegistry(root, create=False)
    assert not isinstance(caught.value, ExecutableProtocolNotFoundError)
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("kind", ["fifo", "directory", "oversize"])
def test_nonregular_or_oversize_committed_object_is_rejected(tmp_path: Path, kind: str) -> None:
    registry = LocalExecutableProtocolRegistry(tmp_path)
    record = registry.seal(protocol_bytes())
    path = tmp_path / "protocols" / f"{record.protocol_id}.json"
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(ExecutableRegistryError):
        registry.get(record.protocol_id)


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63, "/" + "a" * 64])
def test_ids_are_digests_not_paths(tmp_path: Path, identity: str) -> None:
    with pytest.raises(ExecutableRegistryError, match="64 lowercase"):
        LocalExecutableProtocolRegistry(tmp_path).get(identity)


@pytest.mark.parametrize("raw", [b"{}", b"\xff", b'{"x":1,"x":2}', b" " * (128 * 1024 + 1)])
def test_invalid_input_publishes_no_file(tmp_path: Path, raw: bytes) -> None:
    registry = LocalExecutableProtocolRegistry(tmp_path)
    with pytest.raises(ExecutableRegistryError):
        registry.seal(raw)
    assert list((tmp_path / "protocols").iterdir()) == []


def test_failed_atomic_link_publishes_no_partial_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = LocalExecutableProtocolRegistry(tmp_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("Injected publication failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(ExecutableRegistryError, match="Injected publication"):
        registry.seal(protocol_bytes())
    assert list((tmp_path / "protocols").iterdir()) == []
