"""Opaque campaign IO never grants execution or replaces committed evidence."""

import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from tickwitness.infrastructure.search_campaign_store import (
    LocalSearchCampaignStore,
    SearchCampaignBusyError,
    SearchCampaignNotFoundError,
    SearchCampaignStoreError,
)

_PLAN = "a" * 64


def root_for(tmp_path):
    return tmp_path / "runs"


def contents(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_namespace_isolated_opaque_and_immutable(tmp_path):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    assert store.get_campaign(_PLAN) is None
    with store.lock(_PLAN):
        store.start(_PLAN, b'{"header":"application validates schema"}')
        store.write_dispatch(_PLAN, 1, b'{"dispatch":1}')
        store.write_link(_PLAN, 1, b'{"link":1}')
        store.write_result(_PLAN, 1, b'{"result":1}')
        store.write_stop(_PLAN, b'{"stop":1}')
    before = contents(root)
    assert sorted(path.name for path in root.iterdir()) == ["search-campaigns"]
    assert store.check_tree(_PLAN) == {"dispatches": (1,), "links": (1,), "results": (1,)}
    readonly = LocalSearchCampaignStore(root)
    assert readonly.get_campaign(_PLAN) == b'{"header":"application validates schema"}'
    assert readonly.get_dispatch(_PLAN, 1) == b'{"dispatch":1}'
    assert readonly.get_link(_PLAN, 1) == b'{"link":1}'
    assert readonly.get_result(_PLAN, 1) == b'{"result":1}'
    assert readonly.get_stop(_PLAN) == b'{"stop":1}'
    assert readonly.get_dispatch(_PLAN, 2) is None
    store.start(_PLAN, b'{"header":"application validates schema"}')
    store.write_dispatch(_PLAN, 1, b'{"dispatch":1}')
    with pytest.raises(SearchCampaignStoreError, match="already differs"):
        store.write_dispatch(_PLAN, 1, b'{"dispatch":2}')
    with pytest.raises(SearchCampaignStoreError, match="read-only"):
        readonly.write_stop(_PLAN, b'{"stop":1}')
    assert contents(root) == before


def test_missing_readonly_root_or_namespace_never_creates_them(tmp_path):
    root = root_for(tmp_path)
    with pytest.raises(SearchCampaignNotFoundError):
        LocalSearchCampaignStore(root)
    assert not root.exists()
    root.mkdir()
    with pytest.raises(SearchCampaignNotFoundError):
        LocalSearchCampaignStore(root)
    assert list(root.iterdir()) == []


def test_missing_plan_reads_and_tree_do_not_create_plan_directory(tmp_path):
    root = root_for(tmp_path)
    LocalSearchCampaignStore(root, create=True)
    store = LocalSearchCampaignStore(root)
    assert store.get_campaign(_PLAN) is None
    assert store.get_dispatch(_PLAN, 1) is None
    assert store.get_link(_PLAN, 1) is None
    assert store.get_result(_PLAN, 1) is None
    assert store.get_stop(_PLAN) is None
    assert store.check_tree(_PLAN) == {"dispatches": (), "links": (), "results": ()}
    assert list((root / "search-campaigns").iterdir()) == []


def test_same_plan_lock_is_nonblocking_but_other_plans_are_independent(tmp_path):
    root = root_for(tmp_path)
    one = LocalSearchCampaignStore(root, create=True)
    two = LocalSearchCampaignStore(root, create=True)
    with one.lock(_PLAN):
        with pytest.raises(SearchCampaignBusyError), two.lock(_PLAN):
            raise AssertionError("Concurrent coordinator must not enter")
        with two.lock("b" * 64):
            two.start("b" * 64, b"different plan")
    with two.lock(_PLAN):
        two.start(_PLAN, b"completed lock cycle")
    assert one.get_campaign(_PLAN) == b"completed lock cycle"
    with pytest.raises(SearchCampaignStoreError, match="read-only"):
        with LocalSearchCampaignStore(root).lock(_PLAN):
            raise AssertionError("Read-only opening cannot construct a lock")


def test_concurrent_same_bytes_publication_is_idempotent(tmp_path):
    root = root_for(tmp_path)
    LocalSearchCampaignStore(root, create=True)

    def write(_index):
        LocalSearchCampaignStore(root, create=True).write_dispatch(_PLAN, 9, b"same dispatch")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(4)))
    store = LocalSearchCampaignStore(root)
    assert store.get_dispatch(_PLAN, 9) == b"same dispatch"
    assert store.check_tree(_PLAN) == {"dispatches": (9,), "links": (), "results": ()}


@pytest.mark.parametrize("plan_id", ["", "a", "A" * 64, "../outside", 1, True])
def test_invalid_plan_ids_fail_before_directory_creation(tmp_path, plan_id):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    with pytest.raises(SearchCampaignStoreError, match="Plan ID"):
        store.start(plan_id, b"header")
    assert list((root / "search-campaigns").iterdir()) == []


@pytest.mark.parametrize("ordinal", [0, -1, 1025, True, "1", None])
def test_invalid_ordinals_fail_before_directory_creation(tmp_path, ordinal):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    with pytest.raises(SearchCampaignStoreError, match="ordinal"):
        store.write_dispatch(_PLAN, ordinal, b"entry")
    assert list((root / "search-campaigns").iterdir()) == []


@pytest.mark.parametrize("attack", ["symlink", "fifo", "directory", "oversize", "empty"])
def test_committed_record_reads_are_bounded_regular_and_never_repair(tmp_path, attack):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    store.start(_PLAN, b"header")
    store.write_dispatch(_PLAN, 1, b"dispatch")
    path = root / "search-campaigns" / _PLAN / "dispatches" / "0001.json"
    path.unlink()
    if attack == "symlink":
        target = tmp_path / "outside"
        target.write_bytes(b"outside")
        path.symlink_to(target)
    elif attack == "fifo":
        os.mkfifo(path)
    elif attack == "directory":
        path.mkdir()
    elif attack == "oversize":
        path.write_bytes(b"x" * (64 * 1024 + 1))
    else:
        path.write_bytes(b"")
    with pytest.raises(SearchCampaignStoreError):
        store.get_dispatch(_PLAN, 1)
    with pytest.raises(SearchCampaignStoreError):
        store.write_dispatch(_PLAN, 1, b"dispatch")
    assert path.exists() or path.is_symlink()


@pytest.mark.parametrize("location", ["root", "namespace", "plan", "category"])
def test_symlink_directories_are_never_followed(tmp_path, location):
    root = root_for(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    if location == "root":
        root.symlink_to(outside, target_is_directory=True)
        with pytest.raises(SearchCampaignStoreError):
            LocalSearchCampaignStore(root, create=True)
    elif location == "namespace":
        root.mkdir()
        (root / "search-campaigns").symlink_to(outside, target_is_directory=True)
        with pytest.raises(SearchCampaignStoreError):
            LocalSearchCampaignStore(root, create=True)
    else:
        store = LocalSearchCampaignStore(root, create=True)
        base = root / "search-campaigns" / _PLAN
        if location == "plan":
            base.symlink_to(outside, target_is_directory=True)
        else:
            base.mkdir()
            (base / "dispatches").symlink_to(outside, target_is_directory=True)
        with pytest.raises(SearchCampaignStoreError):
            store.write_dispatch(_PLAN, 1, b"dispatch")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("name", ["unknown.json", "0000.json", "1025.json", ".pending-INVALID"])
def test_inventory_rejects_unknown_names_and_out_of_range_ordinals(tmp_path, name):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    store.write_dispatch(_PLAN, 1, b"dispatch")
    directory = root / "search-campaigns" / _PLAN / "dispatches"
    (directory / name).write_bytes(b"retained")
    with pytest.raises(SearchCampaignStoreError, match="Unknown"):
        store.check_tree(_PLAN)
    assert (directory / name).read_bytes() == b"retained"


def test_inventory_reports_ordinals_and_preserves_uncommitted_crash_staging(tmp_path):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    store.start(_PLAN, b"header")
    store.write_dispatch(_PLAN, 3, b"dispatch")
    store.write_dispatch(_PLAN, 1, b"earlier dispatch")
    directory = root / "search-campaigns" / _PLAN
    (directory / (".pending-" + "b" * 32)).write_bytes(b"incomplete header")
    (directory / "dispatches" / (".pending-" + "c" * 32)).write_bytes(b"")
    before = contents(root)
    assert store.check_tree(_PLAN) == {"dispatches": (1, 3), "links": (), "results": ()}
    assert contents(root) == before


def test_result_has_independent_larger_byte_bound(tmp_path):
    store = LocalSearchCampaignStore(root_for(tmp_path), create=True)
    raw = b"x" * (64 * 1024 + 1)
    store.write_result(_PLAN, 1, raw)
    assert store.get_result(_PLAN, 1) == raw
    with pytest.raises(SearchCampaignStoreError, match="bounded"):
        store.write_dispatch(_PLAN, 1, raw)
    with pytest.raises(SearchCampaignStoreError, match="bounded"):
        store.write_result(_PLAN, 2, b"x" * (16 * 1024 * 1024 + 1))


def test_link_failure_leaves_no_committed_record_and_cleans_staging(tmp_path, monkeypatch):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)

    def failed(*_args, **_kwargs):
        raise OSError("injected link failure")

    monkeypatch.setattr(os, "link", failed)
    with pytest.raises(SearchCampaignStoreError, match="unconfirmed"):
        store.start(_PLAN, b"header")
    assert store.get_campaign(_PLAN) is None
    assert list((root / "search-campaigns" / _PLAN).iterdir()) == []


def test_postcommit_fsync_uncertainty_preserves_committed_record(tmp_path, monkeypatch):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    original_link, original_sync = os.link, os.fsync
    committed = False

    def link(source, destination, **kwargs):
        nonlocal committed
        original_link(source, destination, **kwargs)
        if destination == "campaign.json":
            committed = True

    def fsync(descriptor):
        nonlocal committed
        if committed and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            committed = False
            raise OSError("injected postcommit fsync failure")
        original_sync(descriptor)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(SearchCampaignStoreError, match="unconfirmed"):
        store.start(_PLAN, b"header")
    assert store.get_campaign(_PLAN) == b"header"
    assert store.check_tree(_PLAN) == {"dispatches": (), "links": (), "results": ()}
    with pytest.raises(SearchCampaignStoreError, match="already differs"):
        store.start(_PLAN, b"replacement")


@pytest.mark.parametrize("location", ["plan", "category"])
def test_disappearing_staging_does_not_skip_later_unknown_entries(tmp_path, monkeypatch, location):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    store.start(_PLAN, b"header")
    store.write_dispatch(_PLAN, 1, b"dispatch")
    directory = root / "search-campaigns" / _PLAN
    if location == "category":
        directory /= "dispatches"
    pending_name = ".pending-" + "d" * 32
    (directory / pending_name).write_bytes(b"temporary")
    unknown = directory / "unknown.json"
    unknown.write_bytes(b"retained unknown evidence")
    original_list, original_check = os.listdir, store._check_regular

    def list_pending_first(descriptor):
        names = original_list(descriptor)
        if pending_name in names:
            return [
                pending_name,
                "unknown.json",
                *(name for name in names if name not in (pending_name, "unknown.json")),
            ]
        return names

    def disappear(descriptor, name, limit):
        if name == pending_name:
            os.unlink(name, dir_fd=descriptor)
            raise FileNotFoundError("staging removed after enumeration")
        return original_check(descriptor, name, limit)

    monkeypatch.setattr(os, "listdir", list_pending_first)
    monkeypatch.setattr(store, "_check_regular", disappear)
    with pytest.raises(SearchCampaignStoreError, match="Unknown"):
        store.check_tree(_PLAN)
    assert not (directory / pending_name).exists()
    assert unknown.read_bytes() == b"retained unknown evidence"


def test_disappearing_committed_entry_is_an_integrity_error(tmp_path, monkeypatch):
    root = root_for(tmp_path)
    store = LocalSearchCampaignStore(root, create=True)
    store.write_dispatch(_PLAN, 1, b"dispatch")
    original_check = store._check_regular

    def disappear(descriptor, name, limit):
        if name == "0001.json":
            os.unlink(name, dir_fd=descriptor)
            raise FileNotFoundError("committed entry disappeared after enumeration")
        return original_check(descriptor, name, limit)

    monkeypatch.setattr(store, "_check_regular", disappear)
    with pytest.raises(SearchCampaignStoreError, match="committed entry disappeared"):
        store.check_tree(_PLAN)
