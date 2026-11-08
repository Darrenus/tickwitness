"""Original-ledger lineage admission, without executing a native engine."""

import os
from pathlib import Path

import pytest
from test_native_job_supervisor import queued
from test_reduction_execution import forbidden
from test_reduction_execution import reduction_case as reduction_case
from test_search_findings import tree

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.jobs.contracts import (
    build_execution_job_spec,
    build_followup_job_spec,
)
from tickwitness.infrastructure import job_reduction
from tickwitness.infrastructure.job_lineage import JobFamily, checked_family_specs


@pytest.fixture
def family_case(reduction_case, tmp_path_factory):
    origin, _, _ = queued(reduction_case, tmp_path_factory.mktemp("job-family"))
    return reduction_case, origin


def retry(origin, parent=None, key="retry-a"):
    return build_followup_job_spec(
        origin, origin.spec_id if parent is None else parent.spec_id, "retry_from_origin_v1", key
    )


def family_root(origin):
    return Path(origin.document["request"]["runs"]) / ".job-followups" / origin.spec_id


def test_missing_family_is_readonly_and_does_not_create_metadata(family_case, monkeypatch):
    value, origin = family_case
    before = tree(value.case.root)
    actual_open = os.open

    def readonly_open(name, flags, *args, **kwargs):
        assert flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT | os.O_TRUNC) == 0
        return actual_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", readonly_open)
    family = JobFamily(origin)
    assert family.specs() == (origin,)
    assert not family_root(origin).exists()
    assert tree(value.case.root) == before


def test_original_source_validation_precedes_all_family_metadata(family_case, monkeypatch):
    value, origin = family_case
    before = tree(value.case.root)
    monkeypatch.setattr(job_reduction, "prepare_native_job", forbidden)
    with pytest.raises(AssertionError), JobFamily(origin).locked():
        pytest.fail("Invalid source must never acquire family ownership")
    assert not family_root(origin).exists()
    assert tree(value.case.root) == before


def test_seal_and_retry_chain_are_immutable_without_research_writes(family_case):
    value, origin = family_case
    before = tree(value.case.root / "runs")
    family, child = JobFamily(origin), retry(origin)
    with family.locked():
        assert family.specs() == (origin,)
        family.claim_retry(child)
        first = tree(family_root(origin))
        family.claim_retry(child)
        assert tree(family_root(origin)) == first
        grandchild = retry(origin, child, "retry-b")
        family.claim_retry(grandchild)
        # Reobserving an exact older registration does not authorize execution.
        family.claim_retry(child)
    root = family_root(origin)
    assert (root / "origin.json").read_bytes() == origin.canonical_bytes
    assert (root / (origin.spec_id + ".json")).read_bytes() == child.canonical_bytes
    assert (root / (child.spec_id + ".json")).read_bytes() == grandchild.canonical_bytes
    assert JobFamily(origin).specs() == (origin, child, grandchild)
    original_only = {
        name: raw
        for name, raw in tree(value.case.root / "runs").items()
        if not name.startswith(".job-followups/")
    }
    assert original_only == before


def test_same_original_lock_conflicts_across_coordinator_instances(family_case):
    _, origin = family_case
    first, second = JobFamily(origin), JobFamily(origin)
    with (
        first.locked(),
        pytest.raises(JobConflictError, match="Another coordinator"),
        second.locked(),
    ):
        pytest.fail("The second coordinator must not enter")
    with second.locked():
        assert second.specs() == (origin,)


def test_claim_requires_current_process_family_ownership(family_case, monkeypatch):
    _, origin = family_case
    family, child = JobFamily(origin), retry(origin)
    with pytest.raises(JobConflictError, match="ownership"):
        family.claim_retry(child)
    with family.locked():
        actual_pid = os.getpid()
        monkeypatch.setattr(os, "getpid", lambda: actual_pid + 1)
        with pytest.raises(JobConflictError, match="ownership"):
            family.claim_retry(child)


def test_another_retry_key_cannot_branch_the_shared_parent(family_case):
    _, origin = family_case
    family, child = JobFamily(origin), retry(origin)
    with family.locked():
        family.claim_retry(child)
        with pytest.raises(JobConflictError, match="another retry successor"):
            family.claim_retry(retry(origin, key="another-key"))
        missing_parent = retry(origin, retry(origin, key="unregistered"), "orphan")
        with pytest.raises(JobConflictError, match=r"current.*leaf"):
            family.claim_retry(missing_parent)
    assert family.specs() == (origin, child)


def test_claim_rejects_an_ack_descriptor_under_owned_lock(family_case):
    _, origin = family_case
    family = JobFamily(origin)
    ack = build_followup_job_spec(origin, origin.spec_id, "acknowledge_committed_v1", "ack")
    with family.locked(), pytest.raises(JobStoreError, match="retry mode"):
        family.claim_retry(ack)


def test_a_durable_claim_with_lost_reply_is_not_removed_or_replaced(family_case, monkeypatch):
    _, origin = family_case
    family, child = JobFamily(origin), retry(origin)
    actual_publish = JobFamily._publish

    def lose_reply(directory, name, raw):
        actual_publish(directory, name, raw)
        if name == origin.spec_id + ".json":
            raise OSError("Controlled lost claim reply")

    with family.locked():
        monkeypatch.setattr(JobFamily, "_publish", staticmethod(lose_reply))
        with pytest.raises(JobStoreError, match="unconfirmed"):
            family.claim_retry(child)
    assert JobFamily(origin).specs() == (origin, child)


@pytest.mark.parametrize("entry", ["origin.json", "coordinator.lock", "unknown.json"])
def test_partial_or_unrecognized_journal_is_not_repaired(family_case, entry):
    _, origin = family_case
    root = family_root(origin)
    root.mkdir(parents=True, mode=0o700)
    (root / entry).write_bytes(origin.canonical_bytes)
    before = tree(root)
    with pytest.raises(JobStoreError):
        JobFamily(origin).specs()
    with pytest.raises(JobStoreError), JobFamily(origin).locked():
        pytest.fail("Partial metadata must not be repaired")
    assert tree(root) == before


@pytest.mark.parametrize("entry", ["origin.json", "coordinator.lock", "unexpected"])
def test_symlink_or_unknown_entry_fails_closed(family_case, tmp_path, entry):
    _, origin = family_case
    family = JobFamily(origin)
    with family.locked():
        pass
    root = family_root(origin)
    target = tmp_path / "outside"
    target.write_bytes(origin.canonical_bytes)
    if (root / entry).exists():
        (root / entry).unlink()
    (root / entry).symlink_to(target)
    with pytest.raises(JobStoreError):
        family.specs()
    assert target.read_bytes() == origin.canonical_bytes


def test_replaced_lock_path_cannot_authorize_a_claim(family_case):
    _, origin = family_case
    family = JobFamily(origin)
    with family.locked():
        lock = family_root(origin) / "coordinator.lock"
        lock.unlink()
        lock.write_bytes(b"")
        with pytest.raises(JobStoreError, match="replaced"):
            family.claim_retry(retry(origin))


def test_valid_but_different_root_seal_is_refused(family_case):
    _, origin = family_case
    family = JobFamily(origin)
    with family.locked():
        pass
    changed = build_execution_job_spec(origin.document["request"], lease_duration_ns=31_000_000_000)
    (family_root(origin) / "origin.json").write_bytes(changed.canonical_bytes)
    with pytest.raises(JobStoreError, match="root seal"):
        family.specs()


@pytest.mark.parametrize("level", ["namespace", "family"])
def test_metadata_directories_cannot_follow_symlinks(family_case, tmp_path, level):
    _, origin = family_case
    root = family_root(origin)
    target = tmp_path / "outside-directory"
    target.mkdir()
    if level == "namespace":
        root.parent.symlink_to(target, target_is_directory=True)
    else:
        root.parent.mkdir(mode=0o700)
        root.symlink_to(target, target_is_directory=True)
    with pytest.raises(JobStoreError):
        JobFamily(origin).specs()
    with pytest.raises(JobStoreError), JobFamily(origin).locked():
        pytest.fail("A symlink directory must never grant family ownership")
    assert list(target.iterdir()) == []


def test_unreachable_claim_and_chain_limit_are_refused(family_case):
    _, origin = family_case
    family = JobFamily(origin)
    with family.locked():
        pass
    orphan = retry(origin, retry(origin), "orphan")
    parent_id = orphan.document["request"]["parent_job_id"]
    (family_root(origin) / (parent_id + ".json")).write_bytes(orphan.canonical_bytes)
    with pytest.raises(JobStoreError, match="unreachable"):
        family.specs()
    chain = [origin]
    for index in range(32):
        chain.append(retry(origin, chain[-1], "key-" + str(index)))
    assert checked_family_specs(origin, tuple(chain[:32])) == tuple(chain[:32])
    with pytest.raises(JobStoreError, match="one to 32"):
        checked_family_specs(origin, tuple(chain))
