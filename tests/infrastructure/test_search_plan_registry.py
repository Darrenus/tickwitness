"""Proposal evidence is immutable, bounded, and separate from execution state."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

import pytest

from tickwitness.application.data_access import read_accepted_events
from tickwitness.domain.assumptions.specs import build_assumption_spec
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.search.plans import MAX_SEARCH_PLAN_BYTES, build_search_plan
from tickwitness.infrastructure.executable_registry import (
    ExecutableRegistryError,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.search_plan_registry import (
    LocalSearchPlanRegistry,
    SearchPlanNotFoundError,
    SearchPlanRecord,
    SearchPlanRegistryError,
)


def plan_bytes(case, *, seed=0):
    protocol = load_executable_protocol(case.registry.get(case.frozen.protocol_id).canonical_bytes)
    source = ReplayInput(
        case.development,
        read_accepted_events(case.development, case.data),
        build_replay_spec(canonical(protocol.document["replay_spec"])),
    )
    assumptions = build_assumption_spec(
        canonical(
            {
                "kind": "assumption_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "transform": {
                    "semantic_id": "replay_receive_suffix_shift_v1",
                    "from_capture_seq": 2,
                },
                "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
                "parameter_basis": {
                    "kind": "researcher_defined",
                    "calibration_status": "uncalibrated",
                    "calibration_evidence_refs": [],
                },
            }
        ),
        protocol=protocol,
        replay_input=source,
    )
    return build_search_plan(
        canonical(
            {
                "kind": "search_plan_request_v1",
                "schema_version": 1,
                "search_seed": seed,
                "max_proposals": 4,
                "generator": {"kind": "grid", "values_ns": [0, 0, 10_000_000, 30_000_000]},
            }
        ),
        protocol=protocol,
        assumptions=assumptions,
    ).canonical_bytes


def test_plan_namespace_idempotency_and_detached_record(tmp_path, experiment_case):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    raw = plan_bytes(experiment_case)
    first = registry.seal(raw)
    repeat = registry.seal(raw)
    assert first.created is True and repeat.created is False
    assert first.plan_id == digest(raw)
    assert registry.get(first.plan_id) == repeat
    assert LocalSearchPlanRegistry(root).get(first.plan_id) == repeat
    assert sorted(path.name for path in root.iterdir()) == ["search-plans"]
    assert list((root / "search-plans").iterdir()) == [
        root / "search-plans" / f"{first.plan_id}.json"
    ]
    with pytest.raises(FrozenInstanceError):
        first.created = False
    with pytest.raises(SearchPlanRegistryError):
        SearchPlanRecord(first.plan_id, raw, 1)
    with pytest.raises(SearchPlanRegistryError):
        SearchPlanRecord("0" * 64, raw, False)


def test_new_seed_publishes_new_identity_without_replacing_previous(tmp_path, experiment_case):
    registry = LocalSearchPlanRegistry(tmp_path / "plans", create=True)
    first = registry.seal(plan_bytes(experiment_case))
    second = registry.seal(plan_bytes(experiment_case, seed=1))
    assert second.plan_id != first.plan_id
    assert registry.get(first.plan_id).canonical_bytes == first.canonical_bytes
    assert len(list((tmp_path / "plans" / "search-plans").iterdir())) == 2


def test_plan_cannot_be_used_as_executable_protocol(tmp_path, experiment_case):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    executable = LocalExecutableProtocolRegistry(root)
    raw = plan_bytes(experiment_case)
    protocol = experiment_case.registry.get(experiment_case.frozen.protocol_id).canonical_bytes
    with pytest.raises(SearchPlanRegistryError):
        registry.seal(protocol)
    with pytest.raises(ExecutableRegistryError):
        executable.seal(raw)
    assert list((root / "search-plans").iterdir()) == []
    assert list((root / "protocols").iterdir()) == []


def test_default_open_does_not_create_or_repair_missing_root(tmp_path):
    missing = tmp_path / "absent"
    with pytest.raises(SearchPlanNotFoundError):
        LocalSearchPlanRegistry(missing)
    assert not missing.exists()
    existing = tmp_path / "empty"
    existing.mkdir()
    with pytest.raises(SearchPlanRegistryError):
        LocalSearchPlanRegistry(existing)
    assert list(existing.iterdir()) == []


def test_absent_record_is_a_not_found_error_without_mutation(tmp_path):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    with pytest.raises(SearchPlanNotFoundError):
        registry.get("0" * 64)
    assert list((root / "search-plans").iterdir()) == []


def test_reading_and_resealing_do_not_repair_corrupt_committed_bytes(tmp_path, experiment_case):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    record = registry.seal(plan_bytes(experiment_case))
    path = root / "search-plans" / f"{record.plan_id}.json"
    damaged = record.canonical_bytes[:-1] + b"!"
    path.write_bytes(damaged)
    for operation in (
        lambda: registry.get(record.plan_id),
        lambda: registry.seal(record.canonical_bytes),
    ):
        with pytest.raises(SearchPlanRegistryError, match="hash"):
            operation()
        assert path.read_bytes() == damaged


def test_matching_hash_does_not_bless_forged_journal(tmp_path, experiment_case):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    document = json.loads(plan_bytes(experiment_case))
    document["execution_approved"] = True
    forged = canonical(document)
    forged_id = digest(forged)
    path = root / "search-plans" / f"{forged_id}.json"
    path.write_bytes(forged)
    with pytest.raises(SearchPlanRegistryError, match="Invalid search plan"):
        registry.get(forged_id)
    with pytest.raises(SearchPlanRegistryError):
        registry.seal(forged)
    assert path.read_bytes() == forged


def test_concurrent_publication_has_one_created_record(tmp_path, experiment_case):
    raw = plan_bytes(experiment_case)
    root = tmp_path / "nested" / "plans"
    barrier = Barrier(8)

    def publish():
        barrier.wait(timeout=10)
        return LocalSearchPlanRegistry(root, create=True).seal(raw)

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(lambda _: publish(), range(8)))
    assert len({record.plan_id for record in records}) == 1
    assert sum(record.created for record in records) == 1
    assert [path.name for path in (root / "search-plans").iterdir()] == [
        f"{records[0].plan_id}.json"
    ]


@pytest.mark.parametrize("target", ["root", "namespace", "file"])
def test_symlinks_are_rejected_even_when_external_bytes_match(tmp_path, experiment_case, target):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    record = registry.seal(plan_bytes(experiment_case))
    path = root / "search-plans" / f"{record.plan_id}.json"
    outside = tmp_path / "outside"
    if target == "file":
        path.rename(outside)
        path.symlink_to(outside)
        with pytest.raises(SearchPlanRegistryError):
            registry.get(record.plan_id)
        with pytest.raises(SearchPlanRegistryError):
            registry.seal(record.canonical_bytes)
        assert outside.read_bytes() == record.canonical_bytes
    else:
        source = root if target == "root" else path.parent
        source.rename(outside)
        source.symlink_to(outside, target_is_directory=True)
        with pytest.raises(SearchPlanRegistryError):
            LocalSearchPlanRegistry(root)
        with pytest.raises(SearchPlanRegistryError):
            registry.get(record.plan_id)


@pytest.mark.parametrize("kind", ["fifo", "directory", "oversize"])
def test_nonregular_or_oversize_evidence_fails_without_waiting(tmp_path, experiment_case, kind):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    record = registry.seal(plan_bytes(experiment_case))
    path = root / "search-plans" / f"{record.plan_id}.json"
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * (MAX_SEARCH_PLAN_BYTES + 1))
    with pytest.raises(SearchPlanRegistryError):
        registry.get(record.plan_id)


@pytest.mark.parametrize("plan_id", ["../outside", "A" * 64, "a" * 63, "/" + "a" * 64])
def test_identity_is_not_a_path(tmp_path, plan_id):
    registry = LocalSearchPlanRegistry(tmp_path / "plans", create=True)
    with pytest.raises(SearchPlanRegistryError, match="64 lowercase"):
        registry.get(plan_id)


def test_link_failure_cleans_staging_without_committing(tmp_path, experiment_case, monkeypatch):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)

    def fail(*args, **kwargs):
        raise OSError("Injected no-replace link failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(SearchPlanRegistryError, match="Injected no-replace"):
        registry.seal(plan_bytes(experiment_case))
    assert list((root / "search-plans").iterdir()) == []


def test_post_link_fsync_failure_preserves_uncertain_committed_evidence(
    tmp_path, experiment_case, monkeypatch
):
    root = tmp_path / "plans"
    registry = LocalSearchPlanRegistry(root, create=True)
    raw = plan_bytes(experiment_case)
    real_link, real_fsync = os.link, os.fsync
    committed, failed = False, False

    def link(*args, **kwargs):
        nonlocal committed
        real_link(*args, **kwargs)
        committed = True

    def fsync(descriptor):
        nonlocal failed
        if committed and not failed:
            failed = True
            raise OSError("Injected post-link durability uncertainty")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(SearchPlanRegistryError, match="inspect committed identity"):
        registry.seal(raw)
    path = root / "search-plans" / f"{digest(raw)}.json"
    assert failed and path.read_bytes() == raw
    assert [item.name for item in path.parent.iterdir()] == [path.name]
    assert registry.get(digest(raw)).canonical_bytes == raw
    assert registry.seal(raw).created is False


@pytest.mark.parametrize("create", [1, None, "yes"])
def test_create_requires_genuine_boolean(tmp_path, create):
    with pytest.raises(SearchPlanRegistryError, match="boolean"):
        LocalSearchPlanRegistry(tmp_path / "plans", create=create)
