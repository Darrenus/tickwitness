"""The real manifest producer retains its exact shape and schema3/prior21 distinction."""

import dataclasses
from types import SimpleNamespace

import pytest
from test_restricted_reference_ec2_manifest_v2 import _manifest_case

from tickwitness.infrastructure import restricted_reference as reference
from tickwitness.infrastructure import restricted_reference_ec2 as ec2


def metadata_case(monkeypatch):
    case = _manifest_case(monkeypatch, version=3)

    def accounting(_run, snapshot):
        assert snapshot == case.snapshot
        case.calls.append("accounting")
        return {
            "kind": "restricted_reference_ec2_recovery_budget_v3",
            "schema_version": 3,
            "plan_id": ec2.RECOVERY_V3_PLAN_ID,
            "historical_run_ids": [value["run_id"] for value in ec2.RECOVERY_V3_HISTORY.values()],
            "prior_charged": 21,
            "prior_backend_confirmed": 21,
            "current_charged": snapshot.charged,
            "current_backend_confirmed": snapshot.backend_confirmed,
            "current_unconfirmed": snapshot.unconfirmed,
            "current_pending_outcomes": snapshot.pending_outcomes,
            "cumulative_charged": 21 + snapshot.charged,
            "cumulative_backend_confirmed": 21 + snapshot.backend_confirmed,
            "max_current_admissions": 24,
            "max_cumulative_admissions": 45,
        }

    monkeypatch.setattr(ec2.Ec2Run, "recovery_accounting", accounting)
    return case


def test_v3_context_has_eight_keys_but_initial_cumulative_count_is_twenty_one(monkeypatch):
    case = metadata_case(monkeypatch)
    manifest = case.runner._manifest_context()
    assert len(manifest) == 8
    assert manifest["kind"] == "restricted_reference_ec2_recovery_manifest_v3"
    assert manifest["schema_version"] == 3
    assert manifest["recovery_accounting_phase"] == "pre_probe_manifest"
    assert manifest["recovery_accounting"]["prior_charged"] == 21
    assert manifest["recovery_accounting"]["current_charged"] == 0
    assert manifest["recovery_accounting"]["cumulative_charged"] == 21
    assert case.calls == ["snapshot", "accounting"]


@pytest.mark.parametrize(
    "change", [None, {"schema_version": 2}, {"schema_version": True}, {"kind": "other"}]
)
def test_v3_kind_and_context_are_explicit_never_selected_by_truthiness(monkeypatch, change):
    case = metadata_case(monkeypatch)
    case.context = None if change is None else case.context | change
    with pytest.raises(ValueError, match="version and established context"):
        case.runner._manifest_context()
    assert case.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"charged": 1},
        {"backend_confirmed": 1},
        {"unconfirmed": 1},
        {"pending_outcomes": 1},
        {"poisoned": True},
    ],
)
def test_v3_manifest_stays_an_immutable_preprobe_snapshot(monkeypatch, change):
    case = metadata_case(monkeypatch)
    initial = case.runner._manifest_context()
    case.snapshot = dataclasses.replace(case.snapshot, **change)
    with pytest.raises(ValueError, match="pre-probe"):
        case.runner._manifest_context()
    assert initial["recovery_accounting"]["current_charged"] == 0
    assert initial["recovery_accounting"]["cumulative_charged"] == 21


def test_actual_full_v3_producer_matches_all_41_keys_without_processes(monkeypatch, tmp_path):
    case = metadata_case(monkeypatch)
    case.runner.payload = tmp_path / "inert-payload.py"
    case.runner.payload.write_bytes(b"not executed\n")
    monkeypatch.setattr(reference.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(reference.sys, "platform", "unsupported-metadata-fixture")
    monkeypatch.setattr(reference.platform, "machine", lambda: "metadata-fixture")
    monkeypatch.setattr(
        reference.platform, "uname", lambda: SimpleNamespace(_asdict=lambda: {"system": "fixture"})
    )
    monkeypatch.setattr(reference.platform, "libc_ver", lambda: ("fixture", "version"))
    monkeypatch.setattr(reference, "_BWRAP", tmp_path / "absent-bwrap")
    monkeypatch.setattr(reference, "_CGROUP_ROOT", tmp_path / "absent-cgroup")
    monkeypatch.setattr(
        reference, "_identity", lambda path: {"path": str(path), "sha256": "a" * 64, "bytes": 1}
    )
    monkeypatch.setattr(
        case.runner, "_capture_policy", lambda: {"verified": False, "reason": "metadata-only"}
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("Manifest metadata regression cannot launch any process")

    monkeypatch.setattr(reference.subprocess, "run", forbidden)
    monkeypatch.setattr(reference.subprocess, "Popen", forbidden)
    manifest = case.runner._capture_manifest()
    assert len(manifest) == 41 and set(manifest) == ec2.RECOVERY_MANIFEST_KEYS
    assert manifest["available_for_probe"] is False
    assert manifest["recovery_accounting"]["cumulative_charged"] == 21
    assert ec2.validate_recovery_manifest_shape(manifest, version=3) == manifest
    for version in (1, 2, 4, True):
        with pytest.raises(ValueError):
            ec2.validate_recovery_manifest_shape(manifest, version=version)


@pytest.mark.parametrize("fault", ["unknown", "missing"])
def test_v3_top_level_manifest_schema_never_becomes_extensible_observation_metadata(fault):
    manifest = dict.fromkeys(ec2.RECOVERY_MANIFEST_KEYS)
    manifest.update(kind="restricted_reference_ec2_recovery_manifest_v3", schema_version=3)
    if fault == "unknown":
        manifest["fixture_scope"] = "not a permitted authority envelope key"
    else:
        del manifest["os_release"]
    with pytest.raises(ValueError, match="manifest"):
        ec2.validate_recovery_manifest_shape(manifest, version=3)
