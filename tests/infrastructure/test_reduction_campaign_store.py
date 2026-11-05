"""Reduction cancellation is isolated and keeps the existing immutable IO rules."""

import os
import stat

import pytest

from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore
from tickwitness.infrastructure.search_campaign_store import (
    LocalSearchCampaignStore,
    SearchCampaignStoreError,
)

PLAN = "a" * 64


def test_reduction_namespace_does_not_relax_original_search_inventory(tmp_path):
    root = tmp_path / "runs"
    search = LocalSearchCampaignStore(root, create=True)
    reduction = LocalReductionCampaignStore(root, create=True)
    search.start(PLAN, b"original search")
    reduction.start(PLAN, b"independent reduction plan")
    reduction.write_cancel(PLAN, b"cooperative cancellation")
    assert search.get_campaign(PLAN) == b"original search"
    assert reduction.get_campaign(PLAN) == b"independent reduction plan"
    assert reduction.get_cancel(PLAN) == b"cooperative cancellation"
    assert sorted(path.name for path in root.iterdir()) == [
        "reduction-campaigns",
        "search-campaigns",
    ]
    assert reduction.check_tree(PLAN) == {"dispatches": (), "links": (), "results": ()}
    (root / "search-campaigns" / PLAN / "cancel.json").write_bytes(b"not a search path")
    with pytest.raises(SearchCampaignStoreError, match="Unknown"):
        search.check_tree(PLAN)


def test_cancellation_can_publish_while_coordinator_holds_its_lock(tmp_path):
    root = tmp_path / "runs"
    coordinator = LocalReductionCampaignStore(root, create=True)
    requester = LocalReductionCampaignStore(root, create=True)
    with coordinator.lock(PLAN):
        coordinator.start(PLAN, b"frozen plan")
        requester.write_cancel(PLAN, b"one immutable request")
        assert coordinator.get_cancel(PLAN) == b"one immutable request"
        requester.write_cancel(PLAN, b"one immutable request")
        with pytest.raises(SearchCampaignStoreError, match="already differs"):
            requester.write_cancel(PLAN, b"replacement request")
    reader = LocalReductionCampaignStore(root, create=False)
    with pytest.raises(SearchCampaignStoreError, match="read-only"):
        reader.write_cancel(PLAN, b"one immutable request")
    assert reader.get_cancel(PLAN) == b"one immutable request"


def test_assessment_bound_is_independent_from_legacy_raw_result_bound(tmp_path):
    root = tmp_path / "runs"
    reduction = LocalReductionCampaignStore(root, create=True)
    assessment = b"x" * (128 * 1024)
    reduction.write_result(PLAN, 1, assessment)
    assert reduction.get_result(PLAN, 1) == assessment
    with pytest.raises(SearchCampaignStoreError, match="bounded"):
        reduction.write_result(PLAN, 2, assessment + b"x")
    search = LocalSearchCampaignStore(root, create=True)
    search.write_result(PLAN, 1, assessment + b"x")
    assert search.get_result(PLAN, 1) == assessment + b"x"


@pytest.mark.parametrize("attack", ["symlink", "fifo", "directory", "empty", "oversized"])
def test_cancel_reads_reject_unsafe_bytes_without_repair(tmp_path, attack):
    root = tmp_path / "runs"
    store = LocalReductionCampaignStore(root, create=True)
    store.start(PLAN, b"frozen plan")
    path = root / "reduction-campaigns" / PLAN / "cancel.json"
    if attack == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside")
        path.symlink_to(outside)
    elif attack == "fifo":
        os.mkfifo(path)
    elif attack == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"" if attack == "empty" else b"x" * (64 * 1024 + 1))
    with pytest.raises(SearchCampaignStoreError):
        store.get_cancel(PLAN)
    with pytest.raises(SearchCampaignStoreError):
        store.write_cancel(PLAN, b"do not repair")
    assert path.exists() or path.is_symlink()


def test_reduction_inventory_accepts_only_its_one_extra_control_name(tmp_path):
    root = tmp_path / "runs"
    store = LocalReductionCampaignStore(root, create=True)
    store.start(PLAN, b"frozen")
    store.write_cancel(PLAN, b"known")
    (root / "reduction-campaigns" / PLAN / "other.json").write_bytes(b"unknown")
    with pytest.raises(SearchCampaignStoreError, match="Unknown"):
        store.check_tree(PLAN)


def test_cancel_postcommit_sync_error_retains_the_exact_request(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    store = LocalReductionCampaignStore(root, create=True)
    store.start(PLAN, b"frozen")
    original_link, original_sync = os.link, os.fsync
    committed = [False]

    def link(source, destination, **kwargs):
        original_link(source, destination, **kwargs)
        if destination == "cancel.json":
            committed[0] = True

    def sync(descriptor):
        if committed[0] and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            committed[0] = False
            raise OSError("uncertain cancellation directory sync")
        original_sync(descriptor)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(SearchCampaignStoreError, match="unconfirmed"):
        store.write_cancel(PLAN, b"committed cancellation")
    assert store.get_cancel(PLAN) == b"committed cancellation"
    with pytest.raises(SearchCampaignStoreError, match="already differs"):
        store.write_cancel(PLAN, b"must not replace")
