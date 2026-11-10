"""Real journal/locking/IO behavior; process stops are qualified separately."""

import os
from types import SimpleNamespace

import pytest

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import build_job_spec
from tickwitness.domain.jobs.control import build_job_control_policy
from tickwitness.infrastructure.job_controls import JobControlStore
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.fixture
def control_case(tmp_path):
    root = tmp_path / "jobs"
    catalog = SqliteJobStore(root, create=True)
    spec = build_job_spec(
        {
            "run_id": "a" * 64,
            "expected_bundle_id": "b" * 64,
            "expected_report_id": "c" * 64,
            "input_root": str(tmp_path / "inputs"),
            "runs": str(tmp_path / "runs"),
            "source_evidence": "source",
            "split": "development",
        }
    )
    with catalog.coordinator():
        snapshot = catalog.submit(spec, now_ns=100)
    return SimpleNamespace(
        root=root,
        catalog=catalog,
        spec=spec,
        snapshot=snapshot,
        policy=build_job_control_policy(spec.spec_id),
        controls=JobControlStore(root, spec.spec_id),
    )


def configure(value):
    with value.catalog.coordinator():
        return value.controls.configure(value.policy)


def result_for(value, **changes):
    """Structural receipt fixture; not actual runtime/cleanup proof."""
    return {
        "kind": "job_control_result_v1",
        "schema_version": 1,
        "job_id": value.spec.spec_id,
        "policy_id": value.policy.policy_id,
        "job_attempt_id": None,
        "cause": "job_control_error",
        "catalog_state": "QUEUED",
        "catalog_snapshot_sha256": digest(canonical(value.snapshot)),
        "publication_admitted": False,
        "worker_started": False,
        "worker_exit_code": None,
        "worker_group_absent": True,
        "workspace_removed": True,
        "cleanup_confirmed": True,
        "stop_confirmed": False,
        "timing_ns": {
            "elapsed": 0,
            "request_observed": None,
            "worker_reaped": None,
            "cleanup_finished": None,
        },
        "diagnostic": "Declared structural control receipt fixture",
        **changes,
    }


def test_absent_controls_are_readonly_and_do_not_create_namespace(control_case, monkeypatch):
    value = control_case
    before = tree(value.root)
    actual_open = os.open

    def readonly(name, flags, *args, **kwargs):
        assert flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT | os.O_TRUNC) == 0
        return actual_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", readonly)
    assert value.controls.policy() is None
    assert value.controls.cancel_request() is None
    assert value.controls.publication_admission() is None
    assert value.controls.result() is None
    assert tree(value.root) == before


def test_policy_freeze_and_reads_preserve_actual_catalog_bytes(control_case):
    value = control_case
    original = tree(value.root)
    assert configure(value) == value.policy.document
    frozen = tree(value.root)
    assert configure(value) == value.policy.document
    assert tree(value.root) == frozen
    for name, raw in original.items():
        assert (value.root / name).read_bytes() == raw
    assert value.catalog.get(value.spec.spec_id) == value.snapshot
    assert len(value.catalog.events(value.spec.spec_id)) == 1
    changed = build_job_control_policy(value.spec.spec_id, max_open_files=256)
    with pytest.raises(JobConflictError, match="already frozen"):
        value.controls.configure(changed)
    assert tree(value.root) == frozen


def test_cancel_is_idempotent_intent_without_catalog_or_research_write(control_case):
    value = control_case
    configure(value)
    first = value.controls.request_cancel("cancel-1", now_ns=101, snapshot=value.snapshot)
    assert first["status"] == "accepted"
    frozen = tree(value.root)
    repeated = value.controls.request_cancel("cancel-1", now_ns=500, snapshot=value.snapshot)
    assert repeated["status"] == "already_requested"
    assert repeated["request"] == first["request"]
    assert value.catalog.get(value.spec.spec_id) == value.snapshot
    assert len(value.catalog.events(value.spec.spec_id)) == 1
    assert tree(value.root) == frozen
    with pytest.raises(JobConflictError, match="different accepted"):
        value.controls.request_cancel("cancel-2", now_ns=501, snapshot=value.snapshot)
    assert tree(value.root) == frozen
    with value.controls.gate(), pytest.raises(JobConflictError, match="fences"):
        value.controls.admit_publication("d" * 64, now_ns=502)


def test_publication_wins_and_is_visible_while_its_gate_is_still_held(control_case):
    value = control_case
    configure(value)
    peer = JobControlStore(value.root, value.spec.spec_id)
    with pytest.raises(JobConflictError, match="gate owner"):
        value.controls.admit_publication("d" * 64, now_ns=101)
    with value.controls.gate():
        admission = value.controls.admit_publication("d" * 64, now_ns=101)
        assert value.controls.admit_publication("d" * 64, now_ns=999) == admission
        frozen = tree(value.root)
        observed = peer.request_cancel("late", now_ns=102, snapshot=value.snapshot)
        assert observed["status"] == "too_late"
        assert observed["request"] is None and observed["publication_admission"] == admission
        assert tree(value.root) == frozen
        with pytest.raises(JobConflictError, match="another Job attempt"):
            value.controls.admit_publication("e" * 64, now_ns=103)
    assert peer.cancel_request() is None


def test_accepted_cancel_is_visible_while_another_gate_holder_is_present(control_case):
    value = control_case
    configure(value)
    accepted = value.controls.request_cancel("same", now_ns=101, snapshot=value.snapshot)
    peer = JobControlStore(value.root, value.spec.spec_id)
    with value.controls.gate():
        repeated = peer.request_cancel("same", now_ns=102, snapshot=value.snapshot)
        assert repeated["status"] == "already_requested"
        assert repeated["request"] == accepted["request"]


def test_busy_unmarked_gate_is_a_visible_conflict_without_cancellation_acceptance(control_case):
    value = control_case
    configure(value)
    peer = JobControlStore(value.root, value.spec.spec_id)
    with value.controls.gate():
        before = tree(value.root)
        with pytest.raises(JobConflictError, match="gate"):
            peer.request_cancel("not-accepted", now_ns=101, snapshot=value.snapshot)
        with pytest.raises(JobConflictError, match="busy"):
            peer.policy()
        assert tree(value.root) == before
    assert peer.cancel_request() is None


def test_current_gate_owner_pid_and_inode_are_required_for_publication(control_case, monkeypatch):
    value = control_case
    configure(value)
    directory = value.controls.directory
    with value.controls.gate():
        original_pid = os.getpid()
        monkeypatch.setattr(os, "getpid", lambda: original_pid + 1)
        with pytest.raises(JobConflictError, match="gate owner"):
            value.controls.admit_publication("d" * 64, now_ns=101)
        monkeypatch.setattr(os, "getpid", lambda: original_pid)
        (directory / "gate.lock").rename(value.root / "retired-gate")
        (directory / "gate.lock").touch(mode=0o600)
        with pytest.raises(JobStoreError, match="gate was replaced"):
            value.controls.admit_publication("d" * 64, now_ns=101)


def test_result_is_strict_immutable_and_blocks_later_admission(control_case):
    value = control_case
    configure(value)
    result = result_for(value)
    assert value.controls.write_result(result) == result
    frozen = tree(value.root)
    assert value.controls.write_result(result) == result
    assert value.controls.result() == result
    assert tree(value.root) == frozen
    with pytest.raises(JobConflictError, match="Immutable"):
        value.controls.write_result({**result, "diagnostic": "Changed fact"})
    with value.controls.gate(), pytest.raises(JobConflictError, match="completed control"):
        value.controls.admit_publication("d" * 64, now_ns=101)
    assert tree(value.root) == frozen


@pytest.mark.parametrize(
    "change",
    [
        {"policy_id": "f" * 64},
        {"job_id": "f" * 64},
        {"publication_admitted": True},
        {"cause": "job_cancelled"},
    ],
)
def test_result_must_bind_actual_journal_policy_and_publication(control_case, change):
    value = control_case
    configure(value)
    frozen = tree(value.root)
    with pytest.raises(JobStoreError):
        value.controls.write_result(result_for(value, **change))
    assert tree(value.root) == frozen and value.controls.result() is None


def test_post_cancel_publication_error_retains_accepted_immutable_intent(control_case, monkeypatch):
    value = control_case
    configure(value)
    original_publish = JobControlStore._publish

    def lost_response(directory, name, raw):
        original_publish(directory, name, raw)
        if name == "cancel.json":
            raise JobStoreError("Controlled response loss after real cancellation publication")

    monkeypatch.setattr(JobControlStore, "_publish", staticmethod(lost_response))
    with pytest.raises(JobStoreError, match="after real cancellation"):
        value.controls.request_cancel("same", now_ns=101, snapshot=value.snapshot)
    retained = value.controls.cancel_request()
    frozen = tree(value.root)
    repeated = value.controls.request_cancel("same", now_ns=200, snapshot=value.snapshot)
    assert repeated["status"] == "already_requested" and repeated["request"] == retained
    assert tree(value.root) == frozen


@pytest.mark.parametrize("name", ["policy.json", "gate.lock", "workspaces"])
def test_symlink_control_paths_fail_without_following_or_repair(control_case, tmp_path, name):
    value = control_case
    configure(value)
    directory = value.controls.directory
    outside = tmp_path / "outside"
    outside.write_bytes(b"external bytes")
    target = directory / name
    if target.exists():
        target.unlink()
    target.symlink_to(outside)
    frozen = tree(value.root)
    with pytest.raises(JobStoreError):
        value.controls.policy()
    assert outside.read_bytes() == b"external bytes"
    assert tree(value.root) == frozen


def test_aliased_gate_is_refused_without_modifying_its_other_name(control_case, tmp_path):
    value = control_case
    configure(value)
    directory = value.controls.directory
    alias = tmp_path / "gate-alias"
    os.link(directory / "gate.lock", alias)
    before = tree(value.root)
    with pytest.raises(JobStoreError, match="unaliased"):
        value.controls.policy()
    assert alias.read_bytes() == b"" and tree(value.root) == before


def test_partial_or_unknown_journal_is_retained_and_not_reset(control_case):
    value = control_case
    directory = value.root / ".job-controls" / value.spec.spec_id
    directory.mkdir(mode=0o700, parents=True)
    (directory / "gate.lock").touch(mode=0o600)
    frozen = tree(value.root)
    with pytest.raises(JobStoreError):
        value.controls.policy()
    with pytest.raises(JobStoreError):
        configure(value)
    assert tree(value.root) == frozen


def test_unknown_entry_and_corrupt_binding_fail_closed_without_new_request(control_case):
    value = control_case
    configure(value)
    directory = value.controls.directory
    (directory / "unknown").write_bytes(b"retain diagnostic")
    frozen = tree(value.root)
    with pytest.raises(JobStoreError, match="unknown entry"):
        value.controls.request_cancel("blocked", now_ns=101, snapshot=value.snapshot)
    assert tree(value.root) == frozen
    (directory / "unknown").unlink()
    accepted = value.controls.request_cancel("valid", now_ns=101, snapshot=value.snapshot)
    malformed = {**accepted["request"], "policy_id": "f" * 64}
    (directory / "cancel.json").write_bytes(canonical(malformed))
    frozen = tree(value.root)
    with pytest.raises(JobStoreError, match="binding"):
        value.controls.cancel_request()
    assert tree(value.root) == frozen


def test_known_workspace_directory_is_allowed_but_not_created_by_reads(control_case):
    value = control_case
    configure(value)
    directory = value.controls.directory
    before = tree(value.root)
    assert value.controls.policy() == value.policy
    assert not (directory / "workspaces").exists()
    assert tree(value.root) == before
    (directory / "workspaces").mkdir(mode=0o700)
    assert value.controls.policy() == value.policy


def test_terminal_job_without_prior_request_returns_already_terminal_without_write(control_case):
    value = control_case
    configure(value)
    with value.catalog.coordinator() as owner:
        claimed = value.catalog.claim(
            value.spec.spec_id,
            expected_version=1,
            coordinator_id=owner,
            attempt_nonce="d" * 64,
            lease_token="e" * 64,
            now_ns=101,
        )
        attempt = claimed["attempt"]
        terminal = value.catalog.fail(
            value.spec.spec_id,
            {"code": "declared_failure", "message": "Fixture terminal", "worker_exit_code": None},
            expected_version=2,
            coordinator_id=owner,
            job_attempt_id=attempt["job_attempt_id"],
            lease_token=attempt["lease_token"],
            now_ns=102,
        )
    frozen = tree(value.root)
    observed = value.controls.request_cancel("no-new-request", now_ns=103, snapshot=terminal)
    assert observed["status"] == "already_terminal" and observed["request"] is None
    assert value.controls.cancel_request() is None and tree(value.root) == frozen


def test_configured_readers_never_open_write_handles(control_case, monkeypatch):
    value = control_case
    configure(value)
    before = tree(value.root)
    actual_open = os.open

    def readonly(name, flags, *args, **kwargs):
        assert flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT | os.O_TRUNC) == 0
        return actual_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", readonly)
    assert value.controls.policy() == value.policy
    assert value.controls.cancel_request() is None
    assert value.controls.publication_admission() is None
    assert value.controls.result() is None
    assert tree(value.root) == before


def test_policy_cannot_be_configured_for_another_job_before_namespace_creation(control_case):
    value = control_case
    before = tree(value.root)
    with pytest.raises(ValueError, match="bind this exact Job"):
        value.controls.configure(build_job_control_policy("f" * 64))
    assert tree(value.root) == before


def test_same_descriptor_in_another_catalog_has_independent_control_scope(control_case, tmp_path):
    value = control_case
    configure(value)
    other_root = tmp_path / "other-jobs"
    other_catalog = SqliteJobStore(other_root, create=True)
    with other_catalog.coordinator():
        other_catalog.submit(value.spec, now_ns=100)
        other = JobControlStore(other_root, value.spec.spec_id)
        other.configure(value.policy)
    value.controls.request_cancel("local-only", now_ns=101, snapshot=value.snapshot)
    assert other.cancel_request() is None
    assert other.policy() == value.policy
    with other.gate():
        assert other.admit_publication("d" * 64, now_ns=102)["job_attempt_id"] == "d" * 64
    assert value.controls.publication_admission() is None
