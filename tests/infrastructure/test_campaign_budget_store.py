"""Bounded outer control evidence stays immutable and separate from managed results."""

import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    build_allocation,
    build_budget_stop,
    build_campaign_budget,
)
from tickwitness.infrastructure.campaign_budget_store import (
    CampaignBudgetBusyError,
    CampaignBudgetNotFoundError,
    CampaignBudgetStoreError,
    LocalCampaignBudgetStore,
)

_PLAN = "a" * 64


def frozen(**changes):
    return build_campaign_budget(
        canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": 2,
                "max_wall_time_ms": 1000,
                "max_storage_bytes": CONTROL_RESERVE_BYTES + 2 * CANDIDATE_RESERVE_BYTES,
                **changes,
            }
        ),
        plan_id=_PLAN,
        protocol_id="b" * 64,
        nonce="c" * 32,
    )


def prepare(tmp_path):
    root = tmp_path / "runs"
    store = LocalCampaignBudgetStore(root, create=True)
    budget = frozen()
    store.start(_PLAN, budget.canonical_bytes)
    return root, store, budget


def snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_budget_is_idempotent_readonly_and_separate_from_original_ledger(tmp_path):
    root, store, budget = prepare(tmp_path)
    before = snapshot(root)
    store.start(_PLAN, budget.canonical_bytes)
    reader = LocalCampaignBudgetStore(root)
    assert reader.get_budget(_PLAN) == budget.canonical_bytes
    assert reader.get_allocations(_PLAN) == () and reader.get_stop(_PLAN) is None
    assert reader.managed_root(_PLAN) == root / "bounded-search-campaigns" / _PLAN / "managed"
    assert not reader.managed_root(_PLAN).exists()
    assert snapshot(root) == before
    assert list(root.iterdir()) == [root / "bounded-search-campaigns"]
    with pytest.raises(CampaignBudgetStoreError, match="read-only"):
        reader.start(_PLAN, budget.canonical_bytes)
    with pytest.raises(CampaignBudgetStoreError):
        store.start(_PLAN, frozen(max_wall_time_ms=2000).canonical_bytes)
    assert snapshot(root) == before


def test_missing_roots_and_plans_are_not_created_by_inspection(tmp_path):
    missing = tmp_path / "absent"
    with pytest.raises(CampaignBudgetNotFoundError):
        LocalCampaignBudgetStore(missing)
    assert not missing.exists()
    root, store, _ = prepare(tmp_path)
    before = snapshot(root)
    assert store.get_budget("d" * 64) is None
    assert store.check_tree("d" * 64) == {
        "budget": False,
        "stop": False,
        "allocations": (),
        "managed": False,
    }
    assert snapshot(root) == before


def test_allocation_prefix_cannot_reorder_reuse_or_append_after_terminal(tmp_path):
    root, store, budget = prepare(tmp_path)
    first, second = build_allocation(budget, 1, 1), build_allocation(budget, 3, 2)
    with pytest.raises(CampaignBudgetStoreError, match="next index"):
        store.write_allocation(_PLAN, 3, second)
    store.write_allocation(_PLAN, 1, first)
    store.write_allocation(_PLAN, 1, first)
    store.write_allocation(_PLAN, 3, second)
    assert store.get_allocations(_PLAN) == (first, second)
    assert store.check_tree(_PLAN)["allocations"] == (1, 3)
    assert store.control_payload_bytes(_PLAN) == len(budget.canonical_bytes) + len(first) + len(
        second
    )
    stop = build_budget_stop(budget, "evaluation_limit", exit_code=8, elapsed_ns=100)
    store.write_stop(_PLAN, stop)
    assert store.get_stop(_PLAN) == stop
    with pytest.raises(CampaignBudgetStoreError, match="terminated"):
        store.write_allocation(_PLAN, 1, first)
    assert not (root / "slots").exists()


def test_allocation_index_tampering_is_detected_even_with_recomputed_canonical_bytes(tmp_path):
    root, store, budget = prepare(tmp_path)
    first, second = build_allocation(budget, 1, 1), build_allocation(budget, 3, 2)
    store.write_allocation(_PLAN, 1, first)
    directory = root / "bounded-search-campaigns" / _PLAN / "allocations"
    (directory / "0003.json").write_bytes(second)
    assert store.get_allocations(_PLAN) == (first, second)
    (directory / "0003.json").write_bytes(build_allocation(budget, 3, 1))
    with pytest.raises(CampaignBudgetStoreError, match="unique prefix"):
        store.get_allocations(_PLAN)


def test_corrupted_budget_is_not_repaired(tmp_path):
    root, store, budget = prepare(tmp_path)
    path = root / "bounded-search-campaigns" / _PLAN / "budget.json"
    path.write_bytes(b"{}")
    with pytest.raises(CampaignBudgetStoreError):
        store.get_budget(_PLAN)
    with pytest.raises(CampaignBudgetStoreError):
        store.start(_PLAN, budget.canonical_bytes)
    assert path.read_bytes() == b"{}"


@pytest.mark.parametrize("attack", ["symlink", "fifo", "directory", "oversize", "unknown"])
def test_unsafe_control_entries_are_rejected_without_blocking(tmp_path, attack):
    root, store, _ = prepare(tmp_path)
    directory = root / "bounded-search-campaigns" / _PLAN
    if attack == "unknown":
        (directory / "unexpected.json").write_bytes(b"preserved")
    else:
        path = directory / "stop.json"
        if attack == "symlink":
            outside = tmp_path / "outside.json"
            outside.write_bytes(b"{}")
            path.symlink_to(outside)
        elif attack == "fifo":
            os.mkfifo(path)
        elif attack == "directory":
            path.mkdir()
        else:
            path.write_bytes(b" " * 65_537)
    with pytest.raises(CampaignBudgetStoreError):
        store.check_tree(_PLAN)


def test_managed_symlink_cannot_redirect_execution(tmp_path):
    _root, store, _ = prepare(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    store.managed_root(_PLAN).symlink_to(outside, target_is_directory=True)
    with pytest.raises(CampaignBudgetStoreError):
        store.check_tree(_PLAN)
    assert list(outside.iterdir()) == []


def test_orphan_control_payload_is_measured_without_constructing_a_budget(tmp_path):
    root = tmp_path / "runs"
    store = LocalCampaignBudgetStore(root, create=True)
    directory = root / "bounded-search-campaigns" / _PLAN
    (directory / "allocations").mkdir(parents=True)
    (directory / "allocations" / "0001.json").write_bytes(b"uncommitted orphan")
    pending = directory / (".pending-" + "a" * 32)
    pending.write_bytes(b"stage")
    assert store.get_budget(_PLAN) is None
    assert store.check_tree(_PLAN)["allocations"] == (1,)
    assert store.control_payload_bytes(_PLAN) == len(b"uncommitted orphanstage")


def test_plan_lock_is_nonblocking_and_readonly_never_constructs_it(tmp_path):
    root, one, _ = prepare(tmp_path)
    two = LocalCampaignBudgetStore(root, create=True)
    with one.lock(_PLAN), pytest.raises(CampaignBudgetBusyError), two.lock(_PLAN):
        raise AssertionError("Concurrent coordinator must not enter")
    with two.lock(_PLAN):
        pass
    with (
        pytest.raises(CampaignBudgetStoreError, match="read-only"),
        LocalCampaignBudgetStore(root).lock(_PLAN),
    ):
        raise AssertionError("Read-only opening cannot create locks")


def test_same_budget_publication_is_idempotent_under_concurrency(tmp_path):
    root, _, budget = prepare(tmp_path)

    def publish(_index):
        LocalCampaignBudgetStore(root, create=True).start(_PLAN, budget.canonical_bytes)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(publish, range(8)))
    assert LocalCampaignBudgetStore(root).get_budget(_PLAN) == budget.canonical_bytes


def test_postlink_fsync_error_preserves_committed_budget(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    store = LocalCampaignBudgetStore(root, create=True)
    budget = frozen()
    original_link, original_fsync = os.link, os.fsync
    linked = []

    def link(source, target, **kwargs):
        result = original_link(source, target, **kwargs)
        if target == "budget.json":
            linked.append(True)
        return result

    def fsync(descriptor):
        if linked and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("injected post-commit sync uncertainty")
        return original_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", link)
        patch.setattr(os, "fsync", fsync)
        with pytest.raises(CampaignBudgetStoreError, match="unconfirmed"):
            store.start(_PLAN, budget.canonical_bytes)
    assert linked
    assert LocalCampaignBudgetStore(root).get_budget(_PLAN) == budget.canonical_bytes
