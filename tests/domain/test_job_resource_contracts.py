"""Resource observations cannot create measurements or research authority."""

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import JobValidationError, build_job_spec
from tickwitness.domain.jobs.contracts import (
    MAX_JOB_INTEGER,
    build_execution_job_spec,
    build_followup_job_spec,
    queued_job,
)
from tickwitness.domain.jobs.control import build_job_control_policy
from tickwitness.domain.jobs.resources import (
    MAX_JOB_RESOURCE_BYTES,
    RESOURCE_METRICS,
    RESOURCE_STAGES,
    JobResourceReport,
    build_job_resource_preview,
    build_job_resource_report,
    load_job_compute_usage,
    load_job_resource_report,
    resource_metric,
    resource_stage,
)

JOB = "a" * 64
ATTEMPT = "b" * 64


def declared_usage(**changes):
    return {
        "kind": "job_compute_usage_v1",
        "schema_version": 1,
        "anchor_pid": 100,
        "compute_pid": 101,
        "platform": "linux",
        "user_cpu_us": 1040,
        "system_cpu_us": 37,
        "maxrss_raw": 4096,
        "maxrss_unit": "KiB",
        "compute_wait_status": -9,
        **changes,
    }


def declared_report(**changes):
    """Structural fixture; actual OS provenance is qualified remotely."""
    values = {
        "coordinator_cpu_ns": 111,
        "compute_user_cpu_ns": 1_040_000,
        "compute_system_cpu_ns": 37_000,
        "compute_peak_rss_bytes": 4_194_304,
        "scratch_cleanup_logical_bytes": 1024,
        "job_elapsed_ns": 1000,
        "research_slots_reserved_count": 1,
        "audited_native_results_count": 1,
        "processed_input_record_count": 6,
        "predicate_evaluation_count": None,
    }
    return {
        "kind": "job_resource_report_v1",
        "schema_version": 1,
        "job_id": JOB,
        "job_attempt_id": ATTEMPT,
        "policy_id": build_job_control_policy(JOB).policy_id,
        "catalog_state": "FAILED",
        "catalog_snapshot_sha256": "c" * 64,
        "worker_started": True,
        "worker_usage": declared_usage(),
        "collection_status": "complete",
        "metrics": {
            name: resource_metric(name, value, "not_instrumented" if value is None else None)
            for name, value in values.items()
        },
        "stages": [
            resource_stage("pre_worker_admission", 0, 200),
            resource_stage("owned_worker_lifetime", 200, 500),
            resource_stage("cleanup", 500, 600),
            resource_stage("post_cleanup", 600, 1000),
        ],
        **changes,
    }


def replace(document, path, value):
    result = deepcopy(document)
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return result


def test_report_identity_and_detached_document_preserve_exact_operational_evidence():
    report = build_job_resource_report(declared_report())
    assert report.report_id == digest(report.canonical_bytes)
    assert load_job_resource_report(report.canonical_bytes) == report
    detached = report.document
    detached["metrics"]["compute_peak_rss_bytes"]["value"] = 0
    assert report.document["metrics"]["compute_peak_rss_bytes"]["value"] == 4_194_304
    assert report.document["collection_status"] == "complete"
    assert report.document["catalog_state"] == "FAILED"
    assert report.document["metrics"]["compute_user_cpu_ns"]["scope"] == (
        "terminated_compute_child_os_accounting"
    )
    with pytest.raises(FrozenInstanceError):
        report.report_id = "f" * 64
    with pytest.raises(JobValidationError, match="identity"):
        JobResourceReport("f" * 64, report.canonical_bytes)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("job_attempt_id",), "B" * 64),
        (("job_attempt_id",), None),
        (("worker_started",), 1),
        (("collection_status",), {}),
        (("catalog_state",), None),
        (("metrics", "coordinator_cpu_ns", "value"), True),
        (("metrics", "coordinator_cpu_ns", "value"), -1),
        (("metrics", "coordinator_cpu_ns", "value"), MAX_JOB_INTEGER + 1),
        (("metrics", "coordinator_cpu_ns", "value"), 1.5),
        (("metrics", "compute_peak_rss_bytes", "scope"), "whole_host"),
        (("metrics", "compute_user_cpu_ns", "value"), 1040),
        (("metrics", "compute_system_cpu_ns", "source"), "RUSAGE_CHILDREN_delta"),
        (("metrics", "predicate_evaluation_count", "reason"), []),
        (("metrics", "research_slots_reserved_count", "value"), 2),
        (("metrics", "audited_native_results_count", "value"), 0),
        (("worker_usage", "maxrss_unit"), "bytes"),
        (("stages", 1, "duration_ns"), 999),
        (("stages", 1, "end_offset_ns"), 1001),
        (("stages", 1, "start_offset_ns"), 501),
        (("stages", 1, "name"), "cleanup"),
        (("stages", 1, "reason"), "phase_not_observed"),
        (("stages",), []),
    ],
)
def test_tampered_units_counts_types_clock_and_os_usage_do_not_become_observations(path, value):
    with pytest.raises(JobValidationError):
        build_job_resource_report(replace(declared_report(), path, value))


def test_missing_usage_requires_honest_partial_and_no_fabricated_zero():
    document = declared_report(worker_usage=None, collection_status="partial")
    for name in ("compute_user_cpu_ns", "compute_system_cpu_ns", "compute_peak_rss_bytes"):
        document["metrics"][name] = resource_metric(name, None, "usage_unavailable")
    assert build_job_resource_report(document).document["worker_usage"] is None
    document["collection_status"] = "complete"
    with pytest.raises(JobValidationError, match="Complete collection"):
        build_job_resource_report(document)
    document["collection_status"] = "partial"
    document["metrics"]["compute_peak_rss_bytes"] = resource_metric("compute_peak_rss_bytes", 0)
    with pytest.raises(JobValidationError, match="Absent compute usage"):
        build_job_resource_report(document)


def test_never_started_worker_has_no_memory_measurement_even_in_complete_collection():
    document = declared_report(worker_started=False, worker_usage=None)
    for name in ("compute_user_cpu_ns", "compute_system_cpu_ns", "compute_peak_rss_bytes"):
        document["metrics"][name] = resource_metric(name, None, "worker_not_started")
    document["metrics"]["research_slots_reserved_count"] = resource_metric(
        "research_slots_reserved_count", 0
    )
    document["metrics"]["audited_native_results_count"] = resource_metric(
        "audited_native_results_count", 0
    )
    document["metrics"]["processed_input_record_count"] = resource_metric(
        "processed_input_record_count", None, "result_not_audited"
    )
    document["metrics"]["scratch_cleanup_logical_bytes"] = resource_metric(
        "scratch_cleanup_logical_bytes", 0
    )
    document["stages"] = [resource_stage(name, None, None) for name in RESOURCE_STAGES]
    assert build_job_resource_report(document).document["collection_status"] == "complete"


def test_unknown_clock_or_catalog_does_not_create_complete_collection():
    document = declared_report(
        catalog_state=None,
        catalog_snapshot_sha256=None,
        collection_status="partial",
    )
    document["metrics"]["job_elapsed_ns"] = resource_metric(
        "job_elapsed_ns", None, "clock_unavailable"
    )
    document["stages"] = [resource_stage(name, None, None) for name in RESOURCE_STAGES]
    assert build_job_resource_report(document).document["catalog_state"] is None
    document["collection_status"] = "complete"
    with pytest.raises(JobValidationError, match="Complete collection"):
        build_job_resource_report(document)


def test_darwin_raw_bytes_are_not_multiplied_as_linux_kibibytes():
    document = declared_report()
    document["worker_usage"] = declared_usage(platform="darwin", maxrss_unit="bytes")
    document["metrics"]["compute_peak_rss_bytes"] = resource_metric("compute_peak_rss_bytes", 4096)
    assert (
        build_job_resource_report(document).document["metrics"]["compute_peak_rss_bytes"]["value"]
        == 4096
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("anchor_pid", 101),
        ("compute_pid", 0),
        ("user_cpu_us", True),
        ("user_cpu_us", MAX_JOB_INTEGER // 1000 + 1),
        ("maxrss_raw", MAX_JOB_INTEGER // 1024 + 1),
        ("compute_wait_status", -256),
        ("platform", "unsupported"),
        ("schema_version", True),
        ("maxrss_unit", "kilobytes"),
    ],
)
def test_private_compute_frame_rejects_identity_unit_and_conversion_overflow(field, value):
    with pytest.raises(JobValidationError):
        load_job_compute_usage(canonical(declared_usage(**{field: value})))


def test_private_frame_and_report_require_bounded_canonical_unique_documents():
    raw = canonical(declared_usage())
    assert load_job_compute_usage(raw)["compute_wait_status"] == -9
    for invalid in (raw + b"\n", b'{"kind":"x","kind":"y"}', b" " * 512):
        with pytest.raises(JobValidationError):
            load_job_compute_usage(invalid)
    report = canonical(declared_report())
    for invalid in (
        report + b"\n",
        report.replace(b'"schema_version":1', b'"schema_version":1.0'),
        b" " * (MAX_JOB_RESOURCE_BYTES + 1),
    ):
        with pytest.raises(JobValidationError):
            load_job_resource_report(invalid)
    extra = declared_report(lease_token="private")
    with pytest.raises(JobValidationError, match="fields differ"):
        build_job_resource_report(extra)
    with pytest.raises(JobValidationError):
        resource_metric("predicate_evaluation_count", 1)
    with pytest.raises(JobValidationError):
        resource_stage("owned_worker_lifetime", 10, 1)
    assert resource_stage("cleanup", 1, None)["start_offset_ns"] is None


def preview_spec():
    return build_job_spec(
        {
            "run_id": "1" * 64,
            "expected_bundle_id": "2" * 64,
            "expected_report_id": "3" * 64,
            "input_root": "/unopened/inputs",
            "runs": "/unopened/runs",
            "source_evidence": "source",
            "split": "development",
        }
    )


def native_spec():
    return build_execution_job_spec(
        {
            "preparation": "/unopened/preparation",
            "expected_preparation_id": "4" * 64,
            "expected_bundle_id": "2" * 64,
            "expected_report_id": "3" * 64,
            "input_root": "/unopened/inputs",
            "source_evidence": "source",
            "runs": "/unopened/runs",
            "split": "development",
            "engine_runtime": "coordinator_interpreter_v1",
            "restart_mode": "frozen_origin_new_attempt_only_v1",
        }
    )


def test_preview_uses_only_supplied_metadata_and_never_claims_calibrated_cost(monkeypatch):
    import os

    spec = preview_spec()
    snapshot = queued_job(spec, now_ns=100)
    policy = build_job_control_policy(spec.spec_id)

    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata-only preview cannot open input or create a ledger")

    monkeypatch.setattr(os, "open", forbidden)
    preview = build_job_resource_preview(snapshot, policy)
    assert preview["execution_authorized"] is False
    assert preview["configured_limits"] == policy.document["limits"]
    assert preview["research_slot_requirement"] == {
        "availability": "measured",
        "value": 0,
        "reason": "structurally_read_only",
    }
    assert set(preview["estimates"]) == {"cpu_ns", "peak_rss_bytes", "elapsed_ns", "disk_bytes"}
    assert all(
        item == {"availability": "unavailable", "value": None, "reason": "not_calibrated"}
        for item in preview["estimates"].values()
    )
    assert b"/unopened" not in canonical(preview)
    assert build_job_resource_preview(snapshot, None)["configured_limits"] is None
    with pytest.raises(JobValidationError, match="another Job"):
        build_job_resource_preview(snapshot, build_job_control_policy("f" * 64))


@pytest.mark.parametrize("mode", ["native", "retry_from_origin_v1", "acknowledge_committed_v1"])
def test_preview_distinguishes_structural_ack_from_conditional_execution(mode):
    origin = native_spec()
    spec = origin if mode == "native" else build_followup_job_spec(origin, "e" * 64, mode, "key")
    preview = build_job_resource_preview(queued_job(spec, now_ns=100), None)
    requirement = preview["research_slot_requirement"]
    if mode == "acknowledge_committed_v1":
        assert requirement == {
            "availability": "measured",
            "value": 0,
            "reason": "structurally_read_only",
        }
    else:
        assert requirement == {
            "availability": "unavailable",
            "value": None,
            "reason": "conditional_execution",
        }
    assert preview["execution_authorized"] is False


def test_resource_metric_set_is_frozen_and_does_not_include_host_or_research_verdict():
    assert set(RESOURCE_METRICS) == {
        "coordinator_cpu_ns",
        "compute_user_cpu_ns",
        "compute_system_cpu_ns",
        "compute_peak_rss_bytes",
        "scratch_cleanup_logical_bytes",
        "job_elapsed_ns",
        "research_slots_reserved_count",
        "audited_native_results_count",
        "processed_input_record_count",
        "predicate_evaluation_count",
    }
