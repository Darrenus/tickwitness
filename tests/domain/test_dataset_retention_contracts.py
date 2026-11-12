"""Pure retention contracts do not establish filesystem deletion or reachability."""

import json
from copy import deepcopy

import pytest

from tickwitness.domain.data_evidence.retention import (
    MAX_RETENTION_ENTRIES,
    MAX_RETENTION_OBJECT_BYTES,
    MAX_RETENTION_PLAN_BYTES,
    build_dataset_retention_plan,
    build_dataset_retention_result,
    load_dataset_retention_plan,
    load_retention_preview,
    retention_policy,
    retention_preview,
    select_candidates,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest


def file_row(key, *, manifest=False, protected=False, mtime=10, ctime=20, size=7):
    return {
        "path": f"manifests/{key}.json" if manifest else f"objects/sha256/{key}",
        "sha256": key,
        "size_bytes": size,
        "device": 1,
        "inode": 2,
        "mtime_ns": mtime,
        "ctime_ns": ctime,
        "nlink": 1,
        "content_verified": not protected,
    }


def plan_document():
    protected, orphan, young, manifest = [
        digest(value) for value in (b"protected", b"orphan", b"young", b"manifest")
    ]
    files = sorted(
        [
            file_row(protected, protected=True),
            file_row(orphan),
            file_row(young, mtime=300),
            file_row(manifest, manifest=True),
        ],
        key=lambda row: row["path"],
    )
    return {
        "kind": "dataset_retention_plan_v1",
        "schema_version": 1,
        "status": "READY",
        "policy": retention_policy(0),
        "observed_at_ns": 200,
        "store": {
            name: {"device": 1, "inode": index}
            for index, name in enumerate(("root", "objects_parent", "objects", "manifests"), 1)
        },
        "reference_sha256": digest(b"references"),
        "files": files,
        "protected_objects": [protected],
        "candidates": [orphan],
        "diagnostics": [],
    }


def test_roundtrip_exact_identity_and_detached_document():
    document = plan_document()
    plan = build_dataset_retention_plan(document)
    assert plan.plan_id == digest(canonical(document))
    assert load_dataset_retention_plan(plan.canonical_bytes) == plan
    detached = plan.document
    detached["candidates"].clear()
    assert plan.document == document
    assert select_candidates(
        document["files"], document["protected_objects"], 200, document["policy"]
    ) == [digest(b"orphan")]


def test_filesystem_entry_age_uses_both_timestamps_and_keeps_references():
    document = plan_document()
    orphan = next(row for row in document["files"] if row["sha256"] == digest(b"orphan"))
    orphan["ctime_ns"] = 201
    assert select_candidates(
        document["files"], document["protected_objects"], 200, document["policy"]
    ) == []
    document["candidates"] = []
    build_dataset_retention_plan(document)


@pytest.mark.parametrize("minimum", [-1, True, 1.0, 315360001])
def test_policy_rejects_invalid_age(minimum):
    with pytest.raises(EvidenceValidationError):
        retention_policy(minimum)


@pytest.mark.parametrize(
    "field,value", [("max_entries", 4097), ("max_object_bytes", True), ("max_scan_bytes", 0)]
)
def test_policy_bounds_cannot_be_changed(field, value):
    document = plan_document()
    document["policy"][field] = value
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_plan(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "objects/sha256/../victim"),
        ("sha256", "f" * 64),
        ("nlink", 2),
        ("nlink", True),
        ("mtime_ns", -1),
        ("ctime_ns", False),
        ("size_bytes", MAX_RETENTION_OBJECT_BYTES + 1),
        ("content_verified", "yes"),
    ],
)
def test_unsafe_file_observations_are_not_authority(field, value):
    document = plan_document()
    document["files"][0][field] = value
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_plan(document)


@pytest.mark.parametrize(
    "change", ["referenced", "young", "omitted", "unverified", "absent", "unordered", "extra"]
)
def test_candidate_set_is_exact_complete_eligible_classification(change):
    document = plan_document()
    if change == "referenced":
        document["candidates"] = document["protected_objects"]
    elif change == "young":
        document["candidates"] = [digest(b"young")]
    elif change == "omitted":
        document["candidates"] = []
    elif change == "unverified":
        orphan = next(row for row in document["files"] if row["sha256"] == digest(b"orphan"))
        orphan["content_verified"] = False
    elif change == "absent":
        document["protected_objects"] = ["f" * 64]
    elif change == "unordered":
        document["files"].reverse()
    else:
        document["unknown"] = "ignored?"
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_plan(document)


def test_scan_limits_and_canonical_encoding_are_enforced():
    document = plan_document()
    document["files"] = [document["files"][0]] * (MAX_RETENTION_ENTRIES + 1)
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_plan(document)
    document = plan_document()
    document["files"] = sorted(
        [
            file_row(digest(str(index).encode()), size=MAX_RETENTION_OBJECT_BYTES)
            for index in range(5)
        ],
        key=lambda row: row["path"],
    )
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_plan(document)
    plan = build_dataset_retention_plan(plan_document())
    for raw in (
        plan.canonical_bytes + b"\n",
        json.dumps(plan.document).encode(),
        b" " * (MAX_RETENTION_PLAN_BYTES + 1),
    ):
        with pytest.raises(EvidenceValidationError):
            load_dataset_retention_plan(raw)


def test_preview_accepts_only_the_single_stdout_newline():
    plan = build_dataset_retention_plan(plan_document())
    preview = retention_preview(plan)
    assert load_retention_preview(canonical(preview)) == plan
    assert load_retention_preview(canonical(preview) + b"\n") == plan
    for raw in (canonical(preview) + b"\n\n", json.dumps(preview, indent=2).encode()):
        with pytest.raises(EvidenceValidationError):
            load_retention_preview(raw)
    for field, value in (
        ("plan_id", "f" * 64), ("execution_authorized", True), ("schema_version", True)
    ):
        changed = deepcopy(preview)
        changed[field] = value
        with pytest.raises(EvidenceValidationError):
            load_retention_preview(canonical(changed))


def result_document(plan, *, repeat=False):
    return {
        "kind": "dataset_retention_result_v1",
        "schema_version": 1,
        "plan_id": plan.plan_id,
        "status": "APPLIED",
        "intended": plan.document["candidates"],
        "unlinked": [] if repeat else plan.document["candidates"],
        "already_absent": plan.document["candidates"] if repeat else [],
        "removed_logical_bytes": 0 if repeat else 7,
        "diagnostic": None,
    }


def test_fresh_and_explicit_repeat_have_distinct_removal_credit():
    plan = build_dataset_retention_plan(plan_document())
    first = build_dataset_retention_result(result_document(plan), plan=plan)
    repeated = build_dataset_retention_result(result_document(plan, repeat=True), plan=plan)
    assert first["removed_logical_bytes"] == 7
    assert repeated["removed_logical_bytes"] == 0
    dishonest = result_document(plan, repeat=True)
    dishonest["removed_logical_bytes"] = 7
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_result(dishonest, plan=plan)


@pytest.mark.parametrize(
    "change", ["foreign", "overlap", "wrong_bytes", "missing", "refused_delete", "diagnostic"]
)
def test_result_cannot_invent_success_or_unlink_credit(change):
    plan = build_dataset_retention_plan(plan_document())
    result = result_document(plan)
    if change == "foreign":
        result["plan_id"] = "f" * 64
    elif change == "overlap":
        result["already_absent"] = result["unlinked"]
    elif change == "wrong_bytes":
        result["removed_logical_bytes"] = 8
    elif change == "missing":
        result["unlinked"] = []
        result["removed_logical_bytes"] = 0
    elif change == "refused_delete":
        result["status"] = "REFUSED"
        result["diagnostic"] = "snapshot_changed"
    else:
        result["diagnostic"] = "fsync_unconfirmed"
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_result(result, plan=plan)


def test_blocked_snapshot_has_no_partial_deletion_authority():
    document = plan_document()
    document.update(
        status="BLOCKED", store=None, reference_sha256=None, files=[],
        protected_objects=[], candidates=[], diagnostics=["sidecar_present"],
    )
    blocked = build_dataset_retention_plan(document)
    assert blocked.document["candidates"] == []
    document["candidates"] = [digest(b"orphan")]
    with pytest.raises(EvidenceValidationError):
        build_dataset_retention_plan(document)
