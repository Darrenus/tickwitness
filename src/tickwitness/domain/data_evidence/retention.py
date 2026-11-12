"""Bounded DatasetStore retention observations and explicit deletion contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)

type Row = dict[str, object]
MAX_RETENTION_PLAN_BYTES = 4 * 1024 * 1024
MAX_RETENTION_PREVIEW_BYTES = MAX_RETENTION_PLAN_BYTES + 512
MAX_RETENTION_ENTRIES = 4096
MAX_RETENTION_OBJECT_BYTES = 64 * 1024 * 1024
MAX_RETENTION_SCAN_BYTES = 256 * 1024 * 1024
DEFAULT_MIN_AGE_SECONDS = 86400
MAX_MIN_AGE_SECONDS = 315360000
_MAX_INTEGER = 2**63 - 1
_PLAN_FIELDS = {
    "kind",
    "schema_version",
    "status",
    "policy",
    "observed_at_ns",
    "store",
    "reference_sha256",
    "files",
    "protected_objects",
    "candidates",
    "diagnostics",
}
_FILE_FIELDS = {
    "path",
    "sha256",
    "size_bytes",
    "device",
    "inode",
    "mtime_ns",
    "ctime_ns",
    "nlink",
    "content_verified",
}
_FILE_PATH = re.compile(r"(?:objects/sha256/([0-9a-f]{64})|manifests/([0-9a-f]{64})\.json)\Z")
RETENTION_DIAGNOSTICS = frozenset(
    {
        "maintenance_busy",
        "store_unavailable",
        "unknown_entry",
        "unsafe_entry",
        "invalid_catalog",
        "invalid_manifest",
        "missing_reference",
        "invalid_object",
        "sidecar_present",
        "scan_limit",
    }
)
_RESULT_DIAGNOSTICS = frozenset(
    {
        "blocked_plan",
        "plan_mismatch",
        "snapshot_changed",
        "unlink_failed",
        "fsync_unconfirmed",
        "maintenance_busy",
        "store_unavailable",
    }
)


class RetentionValidationError(EvidenceValidationError):
    """A maintenance observation has invalid shape, identity or authority bounds."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RetentionValidationError(message)


def _integer(value: object, label: str, maximum: int = _MAX_INTEGER) -> int:
    _require(type(value) is int and 0 <= value <= maximum, label + " is outside its bounds")
    return cast("int", value)


def _row(value: object, fields: set[str], label: str) -> Row:
    _require(isinstance(value, dict) and value.keys() == fields, label + " fields differ")
    return cast("Row", value)


def _identity(value: object) -> str:
    try:
        return identity(value)
    except ValueError as error:
        raise RetentionValidationError("Invalid retention identity: " + str(error)) from error


def _identities(value: object, label: str) -> list[str]:
    _require(
        type(value) is list and len(value) <= MAX_RETENTION_ENTRIES,
        label + " must be a bounded list",
    )
    result = [_identity(item) for item in cast("list[object]", value)]
    _require(result == sorted(set(result)), label + " must be sorted and unique")
    return result


def retention_policy(min_age_seconds: int = DEFAULT_MIN_AGE_SECONDS) -> Row:
    """Age narrows orphan eligibility; it never expires a referenced object."""
    return {
        "min_age_seconds": _integer(min_age_seconds, "Minimum age", MAX_MIN_AGE_SECONDS),
        "max_entries": MAX_RETENTION_ENTRIES,
        "max_object_bytes": MAX_RETENTION_OBJECT_BYTES,
        "max_scan_bytes": MAX_RETENTION_SCAN_BYTES,
    }


def _policy(value: object) -> Row:
    policy = _row(
        value, {"min_age_seconds", "max_entries", "max_object_bytes", "max_scan_bytes"}, "Policy"
    )
    expected = retention_policy(cast("int", policy["min_age_seconds"]))
    for name, number in expected.items():
        _require(type(policy[name]) is int and policy[name] == number, "Retention bounds differ")
    return policy


def _files(value: object) -> list[Row]:
    _require(
        type(value) is list and len(value) <= MAX_RETENTION_ENTRIES,
        "File inventory exceeds its bound",
    )
    result: list[Row] = []
    for item in cast("list[object]", value):
        row = _row(item, _FILE_FIELDS, "File")
        path = row["path"]
        _require(isinstance(path, str), "Retention file path must be a string")
        matched = _FILE_PATH.fullmatch(cast("str", path))
        _require(matched is not None, "Retention file path is outside the fixed namespace")
        assert matched is not None
        _require(
            _identity(row["sha256"]) == (matched[1] or matched[2]),
            "File identity differs from path",
        )
        _integer(row["size_bytes"], "Object size", MAX_RETENTION_OBJECT_BYTES)
        for name in ("device", "inode", "mtime_ns", "ctime_ns"):
            _integer(row[name], "File " + name)
        _require(
            type(row["nlink"]) is int and row["nlink"] == 1,
            "Retention files must be unaliased",
        )
        _require(type(row["content_verified"]) is bool, "Content verification must be explicit")
        if matched[2] is not None:
            _require(row["content_verified"] is True, "Manifest content must be verified")
        result.append(row)
    paths = [cast("str", row["path"]) for row in result]
    _require(paths == sorted(set(paths)), "File inventory must be sorted and unique")
    _require(
        sum(cast("int", row["size_bytes"]) for row in result if row["content_verified"])
        <= MAX_RETENTION_SCAN_BYTES,
        "Verified content exceeds the scan byte budget",
    )
    return result


def select_candidates(
    files: list[Row], protected_objects: list[str], observed_at_ns: int, policy: Row
) -> list[str]:
    """Classify one fixed snapshot without reading a clock or filesystem."""
    checked_files = _files(files)
    protected = set(_identities(protected_objects, "Protected objects"))
    observed = _integer(observed_at_ns, "Observation time")
    checked_policy = _policy(policy)
    cutoff = max(0, observed - cast("int", checked_policy["min_age_seconds"]) * 1_000_000_000)
    return sorted(
        cast("str", row["sha256"])
        for row in checked_files
        if cast("str", row["path"]).startswith("objects/sha256/")
        and row["sha256"] not in protected
        and row["content_verified"] is True
        and max(cast("int", row["mtime_ns"]), cast("int", row["ctime_ns"])) <= cutoff
    )


def _plan(document: Row) -> Row:
    row = _row(document, _PLAN_FIELDS, "Retention plan")
    _require(
        row["kind"] == "dataset_retention_plan_v1"
        and type(row["schema_version"]) is int
        and row["schema_version"] == 1,
        "Unsupported retention plan",
    )
    _require(
        isinstance(row["status"], str) and row["status"] in {"READY", "BLOCKED"},
        "Unsupported retention status",
    )
    policy = _policy(row["policy"])
    observed = _integer(row["observed_at_ns"], "Observation time")
    store = row["store"]
    if store is not None:
        locations = _row(store, {"root", "objects_parent", "objects", "manifests"}, "Store")
        for location in locations.values():
            for name, number in _row(location, {"device", "inode"}, "Directory identity").items():
                _integer(number, "Directory " + name)
    if row["reference_sha256"] is not None:
        _identity(row["reference_sha256"])
    files = _files(row["files"])
    protected = _identities(row["protected_objects"], "Protected objects")
    candidates = _identities(row["candidates"], "Candidates")
    diagnostics = row["diagnostics"]
    _require(type(diagnostics) is list, "Diagnostics must be a list")
    codes = cast("list[object]", diagnostics)
    _require(
        all(isinstance(code, str) and code in RETENTION_DIAGNOSTICS for code in codes),
        "Unknown diagnostic",
    )
    _require(
        codes == sorted(set(cast("list[str]", codes))), "Diagnostics must be sorted and unique"
    )
    if row["status"] == "BLOCKED":
        _require(
            not candidates and bool(codes), "Blocked plans require diagnostics and no candidates"
        )
        return row
    _require(
        store is not None and row["reference_sha256"] is not None and not codes,
        "Ready snapshot is incomplete",
    )
    object_rows = {
        cast("str", item["sha256"]): item
        for item in files
        if cast("str", item["path"]).startswith("objects/sha256/")
    }
    _require(set(protected).issubset(object_rows), "Protected object is absent from inventory")
    for key, item in object_rows.items():
        _require(
            item["content_verified"] == (key not in protected),
            "Retained payload verification scope differs",
        )
    eligible = select_candidates(files, protected, observed, policy)
    _require(candidates == eligible, "Candidates differ from complete eligible classification")
    return row


@dataclass(frozen=True, slots=True)
class DatasetRetentionPlan:
    plan_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _identity(self.plan_id)
        _plan(parse(self.canonical_bytes, limit=MAX_RETENTION_PLAN_BYTES))
        _require(
            digest(self.canonical_bytes) == self.plan_id, "Plan identity differs from exact bytes"
        )

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_RETENTION_PLAN_BYTES)


def build_dataset_retention_plan(document: Row) -> DatasetRetentionPlan:
    raw = canonical(_plan(document))
    return DatasetRetentionPlan(digest(raw), raw)


def load_dataset_retention_plan(raw: bytes) -> DatasetRetentionPlan:
    _plan(parse(raw, limit=MAX_RETENTION_PLAN_BYTES))
    return DatasetRetentionPlan(digest(raw), raw)


def retention_preview(plan: DatasetRetentionPlan) -> Row:
    checked = load_dataset_retention_plan(plan.canonical_bytes)
    _require(checked.plan_id == plan.plan_id, "Preview plan identity differs")
    return {
        "kind": "dataset_retention_preview_v1",
        "schema_version": 1,
        "plan_id": checked.plan_id,
        "plan": checked.document,
        "execution_authorized": False,
    }


def load_retention_preview(raw: bytes) -> DatasetRetentionPlan:
    """Accept canonical stdout with at most its one CLI newline, never pretty JSON."""
    if isinstance(raw, bytes) and raw.endswith(b"\n"):
        raw = raw[:-1]
    row = _row(
        parse(raw, limit=MAX_RETENTION_PREVIEW_BYTES),
        {"kind", "schema_version", "plan_id", "plan", "execution_authorized"},
        "Retention preview",
    )
    _require(
        row["kind"] == "dataset_retention_preview_v1"
        and type(row["schema_version"]) is int
        and row["schema_version"] == 1
        and row["execution_authorized"] is False,
        "Unsupported retention preview",
    )
    _require(isinstance(row["plan"], dict), "Preview requires a plan object")
    plan = build_dataset_retention_plan(cast("Row", row["plan"]))
    _require(_identity(row["plan_id"]) == plan.plan_id, "Preview identity differs from its plan")
    return plan


def build_dataset_retention_result(
    document: Row, *, plan: DatasetRetentionPlan | None = None
) -> Row:
    row = _row(
        document,
        {
            "kind",
            "schema_version",
            "plan_id",
            "status",
            "intended",
            "unlinked",
            "already_absent",
            "removed_logical_bytes",
            "diagnostic",
        },
        "Retention result",
    )
    _require(
        row["kind"] == "dataset_retention_result_v1"
        and type(row["schema_version"]) is int
        and row["schema_version"] == 1,
        "Unsupported retention result",
    )
    _identity(row["plan_id"])
    _require(
        isinstance(row["status"], str)
        and row["status"] in {"APPLIED", "REFUSED", "PARTIAL", "IO_UNCONFIRMED"},
        "Unsupported apply status",
    )
    intended = _identities(row["intended"], "Intended objects")
    unlinked = _identities(row["unlinked"], "Unlinked objects")
    absent = _identities(row["already_absent"], "Already absent objects")
    removed = _integer(row["removed_logical_bytes"], "Removed logical bytes")
    _require(set(unlinked).isdisjoint(absent), "Unlinked and already absent observations overlap")
    _require(set(unlinked + absent).issubset(intended), "Result exceeds original candidates")
    _require(bool(unlinked) or removed == 0, "Missing objects receive no removal credit")
    if row["status"] == "APPLIED":
        _require(
            row["diagnostic"] is None and set(unlinked + absent) == set(intended),
            "Applied result is incomplete",
        )
    else:
        _require(
            isinstance(row["diagnostic"], str) and row["diagnostic"] in _RESULT_DIAGNOSTICS,
            "Non-success requires a fixed diagnostic",
        )
        if row["status"] == "REFUSED":
            _require(not unlinked and removed == 0, "Refused maintenance cannot report deletion")
    if plan is not None:
        checked = load_dataset_retention_plan(plan.canonical_bytes)
        _require(
            row["plan_id"] == checked.plan_id and intended == checked.document["candidates"],
            "Result differs from planned candidates",
        )
        _require(
            row["status"] != "APPLIED" or checked.document["status"] == "READY",
            "Blocked plans cannot be applied",
        )
        sizes = {
            item["sha256"]: item["size_bytes"]
            for item in cast("list[Row]", checked.document["files"])
            if cast("str", item["path"]).startswith("objects/sha256/")
        }
        _require(
            removed == sum(cast("int", sizes[key]) for key in unlinked),
            "Removal credit differs from actual unlinked entries",
        )
    return parse(canonical(row), limit=MAX_RETENTION_PLAN_BYTES)
