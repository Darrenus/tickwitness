"""Conditional stress authority storage stays distinct and immutable."""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

import pytest

from tickwitness.application.scenarios import validate_scenario_contracts
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.research_contracts.search_finding_protocol import (
    MAX_SEARCH_FINDING_PROTOCOL_BYTES,
    build_search_finding_protocol,
)
from tickwitness.domain.search.plans import build_search_plan
from tickwitness.infrastructure.executable_registry import (
    ExecutableRegistryError,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.search_finding_registry import (
    LocalSearchFindingRegistry,
    SearchFindingNotFoundError,
    SearchFindingStoreError,
)
from tickwitness.infrastructure.search_plan_registry import (
    LocalSearchPlanRegistry,
    SearchPlanRegistryError,
)


def protocol(case):
    assumption = canonical(
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
    )
    checked = validate_scenario_contracts(
        case.frozen.protocol_id,
        assumption,
        canonical(
            {
                "kind": "scenario_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "additional_delay": {"value": 0, "unit": "ns"},
            }
        ),
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
    )
    plan = build_search_plan(
        canonical(
            {
                "kind": "search_plan_request_v1",
                "schema_version": 1,
                "search_seed": 7,
                "max_proposals": 1,
                "generator": {"kind": "grid", "values_ns": [0]},
            }
        ),
        protocol=checked.validation.protocol,
        assumptions=checked.validation.assumptions,
    )
    return build_search_finding_protocol(
        canonical(
            {
                "kind": "search_finding_request_v1",
                "schema_version": 1,
                "title": "Declared receive-delay predicate",
                "authority": "conditional_stress_search_findings_v1",
            }
        ),
        plan=plan,
    )


def test_atomic_idempotent_publication_and_detached_frozen_value(experiment_case):
    root = experiment_case.root / "findings"
    registry = LocalSearchFindingRegistry(root, create=True)
    authority = protocol(experiment_case)
    assert registry.freeze(authority) is True
    assert registry.freeze(authority) is False
    assert registry.get(authority.protocol_id) == authority
    assert LocalSearchFindingRegistry(root).get(authority.protocol_id) == authority
    assert sorted(path.name for path in root.iterdir()) == ["search-finding-protocols"]
    assert [path.name for path in (root / "search-finding-protocols").iterdir()] == [
        f"{authority.protocol_id}.json"
    ]
    detached = registry.get(authority.protocol_id).document
    detached["authority"]["budget_owner_changed"] = True
    assert (
        registry.get(authority.protocol_id).document["authority"]["budget_owner_changed"] is False
    )
    with pytest.raises(FrozenInstanceError):
        authority.protocol_id = "f" * 64


def test_finding_plan_and_execution_namespaces_reject_cross_format(experiment_case):
    root = experiment_case.root / "isolated"
    findings = LocalSearchFindingRegistry(root, create=True)
    plans = LocalSearchPlanRegistry(root, create=True)
    executable = LocalExecutableProtocolRegistry(root)
    authority = protocol(experiment_case)
    with pytest.raises(SearchFindingStoreError, match="actual"):
        findings.freeze(authority.plan)
    with pytest.raises(SearchPlanRegistryError):
        plans.seal(authority.canonical_bytes)
    with pytest.raises(ExecutableRegistryError):
        executable.seal(authority.canonical_bytes)
    assert list((root / "search-finding-protocols").iterdir()) == []
    assert list((root / "search-plans").iterdir()) == []
    assert list((root / "protocols").iterdir()) == []


def test_readonly_open_and_missing_get_never_create_or_repair(tmp_path):
    missing = tmp_path / "absent"
    with pytest.raises(SearchFindingNotFoundError):
        LocalSearchFindingRegistry(missing)
    assert not missing.exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SearchFindingStoreError):
        LocalSearchFindingRegistry(empty)
    assert list(empty.iterdir()) == []
    registry = LocalSearchFindingRegistry(empty, create=True)
    with pytest.raises(SearchFindingNotFoundError):
        registry.get("f" * 64)
    assert list((empty / "search-finding-protocols").iterdir()) == []


def test_corrupt_and_rehashed_authority_remain_rejected_and_untouched(experiment_case):
    root = experiment_case.root / "findings"
    registry = LocalSearchFindingRegistry(root, create=True)
    authority = protocol(experiment_case)
    registry.freeze(authority)
    path = root / "search-finding-protocols" / f"{authority.protocol_id}.json"
    corrupt = authority.canonical_bytes[:-1] + b"!"
    path.write_bytes(corrupt)
    for operation in (
        lambda: registry.get(authority.protocol_id),
        lambda: registry.freeze(authority),
    ):
        with pytest.raises(SearchFindingStoreError, match="hash"):
            operation()
    assert path.read_bytes() == corrupt
    document = json.loads(authority.canonical_bytes)
    document["scope"]["source_claim_evaluated"] = True
    forged = canonical(document)
    forged_id = digest(forged)
    (path.parent / f"{forged_id}.json").write_bytes(forged)
    with pytest.raises(SearchFindingStoreError, match="Invalid search finding"):
        registry.get(forged_id)


def test_concurrent_freeze_has_one_publication(experiment_case):
    root = experiment_case.root / "nested" / "findings"
    authority = protocol(experiment_case)
    barrier = Barrier(8)

    def publish(_index):
        barrier.wait(timeout=5)
        return LocalSearchFindingRegistry(root, create=True).freeze(authority)

    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(publish, range(8)))
    assert sum(created) == 1
    assert all(type(item) is bool for item in created)
    assert [path.name for path in (root / "search-finding-protocols").iterdir()] == [
        f"{authority.protocol_id}.json"
    ]
    assert LocalSearchFindingRegistry(root).get(authority.protocol_id) == authority


@pytest.mark.parametrize("target", ["root", "namespace", "file"])
def test_no_follow_root_namespace_and_file(experiment_case, target):
    root = experiment_case.root / "findings"
    registry = LocalSearchFindingRegistry(root, create=True)
    authority = protocol(experiment_case)
    registry.freeze(authority)
    path = root / "search-finding-protocols" / f"{authority.protocol_id}.json"
    outside = experiment_case.root / "outside"
    source = root if target == "root" else path.parent if target == "namespace" else path
    source.rename(outside)
    source.symlink_to(outside, target_is_directory=target != "file")
    with pytest.raises(SearchFindingStoreError):
        registry.get(authority.protocol_id)
    with pytest.raises(SearchFindingStoreError):
        registry.freeze(authority)
    if target == "file":
        assert outside.read_bytes() == authority.canonical_bytes
    else:
        with pytest.raises(SearchFindingStoreError):
            LocalSearchFindingRegistry(root)


@pytest.mark.parametrize("kind", ["fifo", "directory", "oversize"])
def test_unsafe_evidence_cannot_block_or_overread(experiment_case, kind):
    root = experiment_case.root / "findings"
    registry = LocalSearchFindingRegistry(root, create=True)
    authority = protocol(experiment_case)
    registry.freeze(authority)
    path = root / "search-finding-protocols" / f"{authority.protocol_id}.json"
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * (MAX_SEARCH_FINDING_PROTOCOL_BYTES + 1))
    with pytest.raises(SearchFindingStoreError):
        registry.get(authority.protocol_id)
    with pytest.raises(SearchFindingStoreError):
        registry.freeze(authority)


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63, "/" + "a" * 64, True])
def test_digest_cannot_be_a_path(tmp_path, identity):
    registry = LocalSearchFindingRegistry(tmp_path, create=True)
    with pytest.raises(SearchFindingStoreError, match="64 lowercase"):
        registry.get(identity)


def test_precommit_failure_leaves_no_committed_or_staged_authority(experiment_case, monkeypatch):
    root = experiment_case.root / "findings"
    registry = LocalSearchFindingRegistry(root, create=True)
    authority = protocol(experiment_case)

    def fail(*_args, **_kwargs):
        raise OSError("Injected authority publication failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(SearchFindingStoreError, match="Injected authority"):
        registry.freeze(authority)
    assert list((root / "search-finding-protocols").iterdir()) == []


def test_postcommit_sync_failure_preserves_authority_for_reinspection(experiment_case, monkeypatch):
    root = experiment_case.root / "findings"
    registry = LocalSearchFindingRegistry(root, create=True)
    authority = protocol(experiment_case)
    original_link, original_sync = os.link, os.fsync
    committed = False

    def link(source, destination, **kwargs):
        nonlocal committed
        original_link(source, destination, **kwargs)
        committed = True

    def sync(descriptor):
        nonlocal committed
        if committed and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            committed = False
            raise OSError("Injected post-publication synchronization failure")
        original_sync(descriptor)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(SearchFindingStoreError, match="post-publication"):
        registry.freeze(authority)
    assert registry.get(authority.protocol_id) == authority
    assert registry.freeze(authority) is False


@pytest.mark.parametrize("create", [1, None, "yes"])
def test_create_flag_requires_boolean(tmp_path, create):
    with pytest.raises(SearchFindingStoreError, match="boolean"):
        LocalSearchFindingRegistry(tmp_path, create=create)


@pytest.mark.parametrize("value", [None, b"{}", {}, 1])
def test_freeze_requires_a_real_frozen_protocol(tmp_path, value):
    registry = LocalSearchFindingRegistry(tmp_path, create=True)
    with pytest.raises(SearchFindingStoreError, match="actual"):
        registry.freeze(value)
    assert list((tmp_path / "search-finding-protocols").iterdir()) == []
