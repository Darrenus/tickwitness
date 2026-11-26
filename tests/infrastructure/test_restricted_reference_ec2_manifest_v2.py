"""Manifest metadata regressions; no policy, process, probe or host qualification."""

import copy
import dataclasses
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import restricted_reference as reference
from tickwitness.infrastructure import restricted_reference_ec2 as ec2


def _manifest_case(monkeypatch, *, version=2):
    """Stub already-verified provider metadata, keeping the real manifest producer."""
    context = (
        None
        if version is None
        else {
            "kind": f"restricted_reference_ec2_recovery_context_v{version}",
            "schema_version": version,
            "plan_id": "metadata-only-unusable-authority",
        }
    )
    case = SimpleNamespace(
        version=version,
        context=context,
        snapshot=ec2.BudgetSnapshot(10, 600_000_000_010, 24, 0, 0, 0, False, 0),
        calls=[],
        accounting_available=True,
    )
    run = object.__new__(ec2.Ec2Run)
    run.source_revision = "a" * 40
    provider = {"kind": "metadata-only-provider", "recovery_context": context}
    monkeypatch.setattr(
        ec2.Ec2Run, "provider_record", property(lambda _run: copy.deepcopy(provider))
    )
    monkeypatch.setattr(
        ec2.Ec2Run, "recovery_schema_version", property(lambda _run: case.version), raising=False
    )
    monkeypatch.setattr(
        ec2.Ec2Run, "recovery_context", property(lambda _run: copy.deepcopy(case.context))
    )

    def snapshot(_run):
        case.calls.append("snapshot")
        return case.snapshot

    def accounting(_run, observed):
        assert observed == case.snapshot
        case.calls.append("accounting")
        if not case.accounting_available:
            return None
        prior = 1 if case.version == 1 else 2
        return {
            "kind": f"restricted_reference_ec2_recovery_budget_v{case.version}",
            "schema_version": case.version,
            "prior_charged": prior,
            "current_charged": observed.charged,
            "cumulative_charged": prior + observed.charged,
        }

    monkeypatch.setattr(ec2.Ec2Run, "snapshot", snapshot)
    monkeypatch.setattr(ec2.Ec2Run, "recovery_accounting", accounting)
    runner = object.__new__(reference.ReferenceRunner)
    runner._ec2_run = run
    runner._started_ns = case.snapshot.started_ns
    runner._qualification_deadline_ns = case.snapshot.deadline_ns
    case.runner, case.provider = runner, provider
    return case


@pytest.mark.parametrize("version", [None, 1, 2])
def test_checked_recovery_version_selects_only_its_manifest_envelope(monkeypatch, version):
    case = _manifest_case(monkeypatch, version=version)
    manifest = case.runner._manifest_context()
    if version is None:
        assert manifest == {
            "kind": "restricted_reference_ec2_manifest_v1",
            "schema_version": 1,
            "provider_context": case.provider,
            "qualification_started_ns": case.snapshot.started_ns,
            "qualification_deadline_ns": case.snapshot.deadline_ns,
        }
        assert case.calls == []
    else:
        assert len(manifest) == 8
        assert manifest["kind"] == f"restricted_reference_ec2_recovery_manifest_v{version}"
        assert manifest["schema_version"] == version
        assert manifest["provider_context"] == case.provider
        assert manifest["recovery_context"] == case.context
        assert manifest["recovery_accounting_phase"] == "pre_probe_manifest"
        assert manifest["recovery_accounting"]["current_charged"] == 0
        assert manifest["recovery_accounting"]["cumulative_charged"] == version
        assert case.calls == ["snapshot", "accounting"]
    case.runner._ec2_run = None
    assert case.runner._manifest_context() == {"kind": "restricted_reference_manifest_v1"}


@pytest.mark.parametrize("version", [True, False, 0, 3, "2", 2.0])
def test_unknown_or_boolean_version_cannot_select_a_recovery_manifest(monkeypatch, version):
    case = _manifest_case(monkeypatch)
    case.version = version
    with pytest.raises(ValueError, match="exact recovery manifest version"):
        case.runner._manifest_context()
    assert case.calls == []


@pytest.mark.parametrize(
    "change", [None, {"schema_version": 1}, {"schema_version": True}, {"kind": "other"}]
)
def test_v2_manifest_requires_the_context_established_for_its_exact_version(monkeypatch, change):
    case = _manifest_case(monkeypatch)
    case.context = None if change is None else case.context | change
    with pytest.raises(ValueError, match="version and established context"):
        case.runner._manifest_context()
    assert case.calls == []


def test_nonempty_context_cannot_make_default_authority_a_recovery_manifest(monkeypatch):
    case = _manifest_case(monkeypatch)
    case.version = None
    with pytest.raises(ValueError, match="cannot discard recovery authority"):
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
def test_v2_manifest_rejects_any_consumed_or_uncertain_initial_snapshot(monkeypatch, change):
    case = _manifest_case(monkeypatch)
    case.snapshot = dataclasses.replace(case.snapshot, **change)
    with pytest.raises(ValueError, match="pre-probe"):
        case.runner._manifest_context()
    assert case.calls == ["snapshot"]


def test_v2_initial_accounting_is_required_and_never_rewritten_after_charge(monkeypatch):
    case = _manifest_case(monkeypatch)
    initial = case.runner._manifest_context()
    case.snapshot = dataclasses.replace(case.snapshot, charged=1, backend_confirmed=1)
    with pytest.raises(ValueError, match="pre-probe"):
        case.runner._manifest_context()
    assert initial["recovery_accounting"]["current_charged"] == 0
    assert initial["recovery_accounting"]["cumulative_charged"] == 2
    case.snapshot = dataclasses.replace(case.snapshot, charged=0, backend_confirmed=0)
    case.accounting_available = False
    with pytest.raises(ValueError, match="cumulative accounting"):
        case.runner._manifest_context()


@pytest.mark.parametrize("version", [1, 2])
def test_actual_producer_keeps_all_41_manifest_keys_for_each_recovery_version(
    monkeypatch, tmp_path, version
):
    case = _manifest_case(monkeypatch, version=version)
    case.runner.payload = tmp_path / "metadata-only-payload.py"
    case.runner.payload.write_bytes(b"inert bytes; never executed\n")
    monkeypatch.setattr(reference.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(reference.sys, "platform", "unsupported-metadata-fixture")
    monkeypatch.setattr(reference.platform, "machine", lambda: "metadata-fixture-architecture")
    monkeypatch.setattr(
        reference.platform,
        "uname",
        lambda: SimpleNamespace(_asdict=lambda: {"system": "synthetic-metadata"}),
    )
    monkeypatch.setattr(reference.platform, "libc_ver", lambda: ("fixture-libc", "fixture-version"))
    monkeypatch.setattr(reference, "_BWRAP", tmp_path / "absent-bwrap")
    monkeypatch.setattr(reference, "_CGROUP_ROOT", tmp_path / "absent-cgroup")
    monkeypatch.setattr(
        reference, "_identity", lambda path: {"path": str(path), "sha256": "a" * 64, "bytes": 1}
    )
    monkeypatch.setattr(
        case.runner, "_capture_policy", lambda: {"verified": False, "reason": "metadata fixture"}
    )

    def no_process(*_args, **_kwargs):
        pytest.fail("Manifest regression attempted to launch a process")

    monkeypatch.setattr(reference.subprocess, "run", no_process)
    monkeypatch.setattr(reference.subprocess, "Popen", no_process)
    manifest = case.runner._capture_manifest()
    assert len(manifest) == 41
    assert set(manifest) == ec2.RECOVERY_MANIFEST_KEYS
    assert ec2.validate_recovery_manifest_shape(manifest, version=version) == manifest
    assert manifest["schema_version"] == version
    assert manifest["available_for_probe"] is False
    assert manifest["recovery_accounting"]["cumulative_charged"] == version
    with pytest.raises(ValueError, match="manifest"):
        ec2.validate_recovery_manifest_shape(manifest, version=3 - version)
