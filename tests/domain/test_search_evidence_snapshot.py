"""Closed portable-role grammar and the immutable bounded profile."""

import pytest

from tickwitness.domain.evidence.search_evidence import (
    MAX_FILES,
    MAX_MANIFEST_BYTES,
    MAX_TOTAL_BYTES,
    REQUIRED_ROLES,
    SearchEvidenceValidationError,
    role_limit,
)


@pytest.mark.parametrize("role,limit", [
    ("finding_protocol", 3 * 1024 * 1024), ("snapshot", 2 * 1024 * 1024),
    ("allocation/0001", 64 * 1024), ("reservation/0100", 16 * 1024),
    ("candidate/1024/result", 16 * 1024 * 1024),
    ("attempt/" + "a" * 64 + "/outcome", 16 * 1024),
    ("cas/" + "0" * 64, 16 * 1024 * 1024),
])
def test_fixed_role_caps(role, limit):
    assert role_limit(role) == limit


@pytest.mark.parametrize("role", [
    "../snapshot", "allocation/0000", "reservation/1025", "candidate/1/result",
    "candidate/0001/unknown", "attempt/" + "A" * 64 + "/intent", "cas/" + "a" * 63,
    "cas/" + "a" * 64 + "/extra", "raw/extra", "unknown", True, 1, None,
])
def test_unknown_or_pathlike_roles_are_never_allowed(role):
    with pytest.raises(SearchEvidenceValidationError):
        role_limit(role)


def test_profile_caps_and_mandatory_roles_are_explicit():
    assert MAX_TOTAL_BYTES == 256 * 1024 * 1024
    assert MAX_FILES == 4096
    assert MAX_MANIFEST_BYTES == 2 * 1024 * 1024
    assert REQUIRED_ROLES == frozenset({"finding_protocol", "snapshot", "dataset_manifest", "raw",
        "normalized", "report", "budget", "finding_report", "diagnostics"})
