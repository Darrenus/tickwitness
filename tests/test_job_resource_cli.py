"""Resource reads preserve metadata-only admission and historical observations."""

import json
import time

import pytest
from test_job_supervisor import _queued
from test_jobs_cli import _submit

from tickwitness import cli_jobs
from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.jobs import build_execution_job_spec, build_followup_job_spec, queued_job
from tickwitness.domain.jobs.control import build_job_control_policy
from tickwitness.domain.jobs.resources import (
    RESOURCE_STAGES,
    build_job_resource_preview,
    build_job_resource_report,
    resource_metric,
    resource_stage,
)
from tickwitness.infrastructure.job_control_runtime import JobExecutionControl
from tickwitness.infrastructure.job_controls import JobControlStore
from tickwitness.infrastructure.job_resources import JobResourceStore
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("command", ["inspect-job-resources", "preview-job-resources"])
def test_confirmation_refused_before_id_and_catalog_io(tmp_path, capsys, monkeypatch, command):
    def forbidden(*args, **kwargs):
        raise AssertionError("Confirmation must not access metadata")

    monkeypatch.setattr(cli_jobs, "SqliteJobStore", forbidden)
    arguments = [command, "invalid", "--jobs", str(tmp_path / "missing"), "--split", "confirmation"]
    assert main(arguments) == 5
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("command", ["inspect-job-resources", "preview-job-resources"])
def test_missing_catalog_is_not_created(tmp_path, capsys, command):
    assert main([command, "a" * 64, "--jobs", str(tmp_path / "missing")]) == 4
    assert not capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_legacy_and_configured_previews_never_open_missing_research_or_write(tmp_path, capsys):
    assert main(_submit(tmp_path)) == 0
    job = json.loads(capsys.readouterr().out)["job_id"]
    common = [job, "--jobs", str(tmp_path / "jobs")]
    before = tree(tmp_path)
    assert main(["inspect-job-resources", *common]) == 0
    missing = json.loads(capsys.readouterr().out)
    assert missing["status"] == "NOT_RECORDED" and missing["report"] is None
    assert missing["report_id"] is None and missing["report_matches_current_snapshot"] is None
    assert not missing["execution_authorized"]
    assert main(["preview-job-resources", *common]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["configured_limits"] is None
    assert preview["research_slot_requirement"]["value"] == 0
    assert not preview["execution_authorized"]
    assert tree(tmp_path) == before
    assert main(["configure-job-control", *common]) == 0
    policy = json.loads(capsys.readouterr().out)
    before = tree(tmp_path)
    assert main(["preview-job-resources", *common]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["policy_id"] == policy["policy_id"]
    assert preview["configured_limits"] == policy["policy"]["limits"]
    assert all(item["value"] is None for item in preview["estimates"].values())
    assert tree(tmp_path) == before
    assert not (tmp_path / "inputs").exists() and not (tmp_path / "runs").exists()


def test_native_retry_and_ack_preview_are_conditional_metadata_only(tmp_path, capsys):
    request = {
        "input_root": str(tmp_path / "missing-input"),
        "source_evidence": "source",
        "runs": str(tmp_path / "missing-runs"),
        "preparation": str(tmp_path / "missing-preparation"),
        "expected_preparation_id": "a" * 64,
        "expected_bundle_id": "b" * 64,
        "expected_report_id": "c" * 64,
        "split": "development",
        "engine_runtime": "coordinator_interpreter_v1",
        "restart_mode": "frozen_origin_new_attempt_only_v1",
    }
    origin = build_execution_job_spec(request)
    catalog = SqliteJobStore(tmp_path / "jobs", create=True)
    # Domain fixture descriptors only; there is deliberately no source tree.
    with catalog.coordinator():
        catalog.submit(origin, now_ns=time.time_ns())
    before = tree(tmp_path)
    assert main(["preview-job-resources", origin.spec_id, "--jobs", str(catalog.root)]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["research_slot_requirement"]["value"] is None
    assert tree(tmp_path) == before
    # Followup preview's conditional semantics are domain-only; creating a real
    # successor requires terminal parent authority, tested by the existing suite.
    for mode, expected in [("retry_from_origin_v1", None), ("acknowledge_committed_v1", 0)]:
        spec = build_followup_job_spec(origin, origin.spec_id, mode, mode)
        value = build_job_resource_preview(queued_job(spec, now_ns=1), None)
        assert value["research_slot_requirement"]["value"] == expected
        assert not value["execution_authorized"]
    assert tree(tmp_path) == before


def test_queue_stop_report_is_immutable_and_inspect_preview_remain_read_only(tmp_path, capsys):
    assert main(_submit(tmp_path)) == 0
    job = json.loads(capsys.readouterr().out)["job_id"]
    common = [job, "--jobs", str(tmp_path / "jobs")]
    assert main(["configure-job-control", *common]) == 0
    capsys.readouterr()
    assert main(["cancel-job", *common, "--cancel-key", "stop-before-worker"]) == 0
    capsys.readouterr()
    before = tree(tmp_path)
    assert main(["inspect-job-resources", *common]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["report_matches_current_snapshot"] is True
    report = observed["report"]
    assert not report["worker_started"] and report["worker_usage"] is None
    assert report["metrics"]["compute_peak_rss_bytes"]["value"] is None
    assert report["metrics"]["compute_peak_rss_bytes"]["reason"] == "worker_not_started"
    assert report["metrics"]["research_slots_reserved_count"]["value"] == 0
    assert report["metrics"]["predicate_evaluation_count"]["value"] is None
    assert main(["preview-job-resources", *common]) == 0
    capsys.readouterr()
    assert tree(tmp_path) == before
    path = tmp_path / "jobs" / ".job-resources" / job / "report.json"
    tampered = json.loads(path.read_bytes())
    tampered["catalog_snapshot_sha256"] = "f" * 64
    path.write_bytes(canonical(tampered))
    assert main(["inspect-job-resources", *common]) == 3
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "job_store_integrity_or_io_failure"


def test_report_keeps_actual_running_snapshot_after_explicit_orphan_reconciliation(
    tmp_path, capsys
):
    catalog, queued = _queued(tmp_path)
    controls = JobControlStore(catalog.root, queued["job_id"])
    with catalog.coordinator() as owner:
        controls.configure(build_job_control_policy(queued["job_id"]))
        running = catalog.claim(
            queued["job_id"],
            expected_version=1,
            coordinator_id=owner,
            attempt_nonce="a" * 64,
            lease_token="b" * 64,
            now_ns=time.time_ns(),
        )
        guard = JobExecutionControl(controls)
        guard.bind(running)
        # Explicit no-worker collection fixture, not external reproduction.
        guard.finish(running, cause="coordinator_interrupted")
    with catalog.coordinator():
        catalog.reconcile_orphans(now_ns=time.time_ns())
    before = tree(tmp_path)
    assert main(["inspect-job-resources", queued["job_id"], "--jobs", str(catalog.root)]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["status"] == "PARTIAL"
    assert observed["report"]["catalog_state"] == "RUNNING"
    assert observed["report_matches_current_snapshot"] is False
    assert tree(tmp_path) == before
    path = catalog.root / ".job-resources" / queued["job_id"] / "report.json"
    tampered = json.loads(path.read_bytes())
    tampered["catalog_state"] = None
    tampered["catalog_snapshot_sha256"] = None
    tampered["job_attempt_id"] = "f" * 64
    path.write_bytes(canonical(tampered))
    assert main(["inspect-job-resources", queued["job_id"], "--jobs", str(catalog.root)]) == 3
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "job_store_integrity_or_io_failure"


def test_unobserved_snapshot_cannot_claim_an_attempt_in_an_unclaimed_job(tmp_path, capsys):
    catalog, queued = _queued(tmp_path)
    policy = build_job_control_policy(queued["job_id"])
    with catalog.coordinator():
        JobControlStore(catalog.root, queued["job_id"]).configure(policy)
    reasons = {
        "coordinator_cpu_ns": "clock_unavailable",
        "compute_user_cpu_ns": "worker_not_started",
        "compute_system_cpu_ns": "worker_not_started",
        "compute_peak_rss_bytes": "worker_not_started",
        "scratch_cleanup_logical_bytes": "cleanup_incomplete",
        "job_elapsed_ns": "clock_unavailable",
        "research_slots_reserved_count": "reservation_unconfirmed",
        "audited_native_results_count": "not_recorded",
        "processed_input_record_count": "result_not_audited",
        "predicate_evaluation_count": "not_instrumented",
    }
    # Structurally valid partial storage fixture; no real attempt was claimed.
    report = build_job_resource_report(
        {
            "kind": "job_resource_report_v1",
            "schema_version": 1,
            "job_id": queued["job_id"],
            "job_attempt_id": "f" * 64,
            "policy_id": policy.policy_id,
            "catalog_state": None,
            "catalog_snapshot_sha256": None,
            "worker_started": False,
            "worker_usage": None,
            "collection_status": "partial",
            "metrics": {
                name: resource_metric(name, None, reason) for name, reason in reasons.items()
            },
            "stages": [resource_stage(name, None, None) for name in RESOURCE_STAGES],
        }
    )
    JobResourceStore(catalog.root, queued["job_id"]).seal(report)
    assert main(["inspect-job-resources", queued["job_id"], "--jobs", str(catalog.root)]) == 3
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "job_store_integrity_or_io_failure"
