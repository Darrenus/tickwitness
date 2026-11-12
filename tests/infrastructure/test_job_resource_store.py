"""Real no-follow resource journal behavior without executing project workers."""

import os
from types import SimpleNamespace

import pytest

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import build_job_spec
from tickwitness.domain.jobs.control import build_job_control_policy
from tickwitness.domain.jobs.resources import (
    RESOURCE_STAGES,
    build_job_resource_report,
    resource_metric,
    resource_stage,
)
from tickwitness.infrastructure import job_controls
from tickwitness.infrastructure.job_controls import JobControlStore
from tickwitness.infrastructure.job_resources import JobResourceStore
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.fixture
def resource_case(tmp_path):
    root = tmp_path / "jobs"
    catalog = SqliteJobStore(root, create=True)
    spec = build_job_spec(
        {
            "run_id": "a" * 64, "expected_bundle_id": "b" * 64,
            "expected_report_id": "c" * 64, "input_root": str(tmp_path / "inputs"),
            "runs": str(tmp_path / "runs"), "source_evidence": "source", "split": "development",
        }
    )
    with catalog.coordinator():
        snapshot = catalog.submit(spec, now_ns=100)
    return SimpleNamespace(
        root=root, catalog=catalog, spec=spec, snapshot=snapshot,
        policy=build_job_control_policy(spec.spec_id), controls=JobControlStore(root, spec.spec_id),
        resources=JobResourceStore(root, spec.spec_id),
        directory=root / ".job-resources" / spec.spec_id,
    )


def configure(value):
    with value.catalog.coordinator():
        value.controls.configure(value.policy)


def report_for(value, **changes):
    """Partial structural observation, not a claim of actual worker execution."""
    measurements = {
        "coordinator_cpu_ns": resource_metric("coordinator_cpu_ns", 1),
        "compute_user_cpu_ns": resource_metric("compute_user_cpu_ns", None, "worker_not_started"),
        "compute_system_cpu_ns": resource_metric(
            "compute_system_cpu_ns", None, "worker_not_started"
        ),
        "compute_peak_rss_bytes": resource_metric(
            "compute_peak_rss_bytes", None, "worker_not_started"
        ),
        "scratch_cleanup_logical_bytes": resource_metric("scratch_cleanup_logical_bytes", 0),
        "job_elapsed_ns": resource_metric("job_elapsed_ns", 10),
        "research_slots_reserved_count": resource_metric("research_slots_reserved_count", 0),
        "audited_native_results_count": resource_metric("audited_native_results_count", 0),
        "processed_input_record_count": resource_metric(
            "processed_input_record_count", None, "result_not_audited"
        ),
        "predicate_evaluation_count": resource_metric(
            "predicate_evaluation_count", None, "not_instrumented"
        ),
    }
    return build_job_resource_report(
        {
            "kind": "job_resource_report_v1", "schema_version": 1,
            "job_id": value.spec.spec_id, "job_attempt_id": None,
            "policy_id": value.policy.policy_id, "catalog_state": "QUEUED",
            "catalog_snapshot_sha256": digest(canonical(value.snapshot)),
            "worker_started": False, "worker_usage": None, "collection_status": "partial",
            "metrics": measurements,
            "stages": [resource_stage(name, None, None) for name in RESOURCE_STAGES],
            **changes,
        }
    )


def test_absent_resource_reads_create_nothing_and_use_only_readonly_opens(
    resource_case, monkeypatch
):
    value = resource_case
    before = tree(value.root)
    actual_open = os.open

    def readonly(path, flags, *args, **kwargs):
        assert flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT | os.O_TRUNC) == 0
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", readonly)
    assert value.resources.read() is None
    missing = value.root.parent / "missing"
    assert JobResourceStore(missing, value.spec.spec_id).read() is None
    assert not missing.exists()
    assert tree(value.root) == before
    assert not value.directory.parent.exists()


def test_resource_seal_needs_existing_exact_policy_before_creating_namespace(resource_case):
    value = resource_case
    report = report_for(value)
    original = tree(value.root)
    with pytest.raises(JobConflictError, match="frozen policy"):
        value.resources.seal(report)
    assert tree(value.root) == original
    configure(value)
    wrong = report_for(
        value, policy_id=build_job_control_policy(value.spec.spec_id, max_open_files=256).policy_id
    )
    before = tree(value.root)
    with pytest.raises(JobConflictError, match="frozen policy"):
        value.resources.seal(wrong)
    with pytest.raises(JobConflictError, match="exact Job"):
        value.resources.seal(report_for(value, job_id="f" * 64))
    assert tree(value.root) == before
    assert not value.directory.parent.exists()


def test_report_is_independent_of_schema1_and_the_strict_control_whitelist(resource_case):
    value = resource_case
    configure(value)
    report = report_for(value)
    before = tree(value.root)
    assert value.resources.seal(report) == report
    assert value.resources.read() == report
    for name, raw in before.items():
        assert (value.root / name).read_bytes() == raw
    assert value.catalog.get(value.spec.spec_id) == value.snapshot
    assert len(value.catalog.events(value.spec.spec_id)) == 1
    assert value.controls.policy() == value.policy
    assert value.controls.result() is None
    assert {path.name for path in value.directory.iterdir()} == {"report.json"}
    assert (value.directory / "report.json").read_bytes() == report.canonical_bytes


def test_exact_repeat_is_idempotent_but_changed_report_is_never_overwritten(resource_case):
    value = resource_case
    configure(value)
    report = report_for(value)
    value.resources.seal(report)
    before = tree(value.root)
    assert value.resources.seal(report) == report
    assert tree(value.root) == before
    changed = report_for(value, catalog_snapshot_sha256="d" * 64)
    with pytest.raises(JobConflictError, match="already differs"):
        value.resources.seal(changed)
    assert tree(value.root) == before


@pytest.mark.parametrize("entry", [None, ".pending-uncertain", "unexpected"])
def test_unknown_or_empty_old_directory_is_not_repaired_or_treated_as_missing(resource_case, entry):
    value = resource_case
    configure(value)
    value.directory.mkdir(parents=True, mode=0o700)
    if entry is not None:
        (value.directory / entry).write_bytes(b"uncertain publication")
    before = tree(value.root)
    with pytest.raises(JobStoreError, match="incomplete|unknown"):
        value.resources.read()
    with pytest.raises(JobStoreError, match="incomplete|unknown"):
        value.resources.seal(report_for(value))
    assert tree(value.root) == before


def test_existing_report_plus_unknown_entry_is_refused(resource_case):
    value = resource_case
    configure(value)
    value.resources.seal(report_for(value))
    (value.directory / ".pending-uncertain").write_bytes(b"unknown")
    with pytest.raises(JobStoreError, match="unknown"):
        value.resources.read()


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_report_file_aliases_are_never_followed_or_accepted(resource_case, tmp_path, alias):
    value = resource_case
    configure(value)
    report = report_for(value)
    value.resources.seal(report)
    path = value.directory / "report.json"
    outside = tmp_path / "outside.json"
    if alias == "symlink":
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    else:
        outside.hardlink_to(path)
    with pytest.raises(JobStoreError):
        value.resources.read()
    assert outside.read_bytes() == report.canonical_bytes


def test_symlinked_resource_namespace_and_unsafe_directory_modes_fail(resource_case, tmp_path):
    value = resource_case
    configure(value)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    namespace = value.directory.parent
    namespace.symlink_to(outside, target_is_directory=True)
    with pytest.raises(JobStoreError):
        value.resources.read()
    with pytest.raises(JobStoreError):
        value.resources.seal(report_for(value))
    assert not list(outside.iterdir())
    namespace.unlink()
    namespace.mkdir(mode=0o777)
    namespace.chmod(0o777)
    with pytest.raises(JobStoreError, match="same-user safe"):
        value.resources.seal(report_for(value))


def test_report_policy_binding_is_checked_on_every_read(resource_case):
    value = resource_case
    configure(value)
    value.resources.seal(report_for(value))
    path = value.directory / "report.json"
    foreign = report_for(value, policy_id="f" * 64)
    path.write_bytes(foreign.canonical_bytes)
    with pytest.raises(JobStoreError, match="binding"):
        value.resources.read()


def test_busy_original_control_gate_prevents_resource_publication(resource_case):
    value = resource_case
    configure(value)
    with value.controls.gate():
        with pytest.raises(JobConflictError, match="busy|owns"):
            value.resources.seal(report_for(value))
    assert not value.directory.parent.exists()


def test_uncertain_linked_report_is_not_redispatched_or_rolled_back(resource_case, monkeypatch):
    value = resource_case
    configure(value)
    report = report_for(value)
    actual_publish = JobControlStore._publish
    calls = []

    def uncertain(directory, name, raw):
        calls.append((name, raw))
        actual_publish(directory, name, raw)
        raise OSError("Injected post-link acknowledgment failure")

    monkeypatch.setattr(JobControlStore, "_publish", staticmethod(uncertain))
    with pytest.raises(JobStoreError, match="acknowledgment failure"):
        value.resources.seal(report)
    assert calls == [("report.json", report.canonical_bytes)]
    assert value.resources.read() == report
    assert value.catalog.get(value.spec.spec_id) == value.snapshot
    assert len(value.catalog.events(value.spec.spec_id)) == 1
    assert value.controls.result() is None


def test_failed_managed_charge_leaves_explicit_uncertainty_not_an_automatic_retry(
    resource_case, monkeypatch
):
    value = resource_case
    configure(value)
    calls = []

    def exhausted(amount):
        calls.append(amount)
        raise JobStoreError("Declared operational storage budget exhausted")

    monkeypatch.setattr(job_controls, "charge_managed_write", exhausted)
    with pytest.raises(JobStoreError, match="storage budget exhausted"):
        value.resources.seal(report_for(value))
    assert calls == [len(report_for(value).canonical_bytes)]
    before = tree(value.root)
    with pytest.raises(JobStoreError, match="incomplete"):
        value.resources.seal(report_for(value))
    with pytest.raises(JobStoreError, match="incomplete"):
        value.resources.read()
    assert len(calls) == 1
    assert tree(value.root) == before


def test_later_catalog_state_does_not_rewrite_the_sealed_historical_observation(resource_case):
    value = resource_case
    configure(value)
    report = report_for(value)
    value.resources.seal(report)
    raw = (value.directory / "report.json").read_bytes()
    with value.catalog.coordinator() as coordinator:
        running = value.catalog.claim(
            value.spec.spec_id, expected_version=1, coordinator_id=coordinator,
            attempt_nonce="d" * 64, lease_token="e" * 64, now_ns=200,
        )
        value.catalog.mark_lost(
            value.spec.spec_id, expected_version=running["version"], reason="lease_expired",
            now_ns=running["attempt"]["lease_expires_at_ns"],
        )
    assert value.catalog.get(value.spec.spec_id)["state"] == "LOST"
    assert value.resources.read() == report
    assert value.resources.read().document["catalog_state"] == "QUEUED"
    assert (value.directory / "report.json").read_bytes() == raw
