"""Exclusive v2 plan preparation against two synthetic durable failures."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

# Share filesystem scenarios with the provider tests, including their real v1 histories.
sys.path.insert(0, str(Path(__file__).parent / "infrastructure"))
from test_restricted_reference_ec2_recovery_v2 import CURRENT, assert_preserved  # noqa: E402
from test_restricted_reference_ec2_recovery_v2 import host as host  # noqa: E402
from test_restricted_reference_ec2_recovery_v2 import recovery as recovery  # noqa: E402
from test_restricted_reference_ec2_recovery_v2 import v2_history as v2_history  # noqa: E402

SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_ec2_reference_recovery_v2.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_recovery_v2_preparation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preparation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparation)


@pytest.fixture
def prepared_host(v2_history, monkeypatch):
    monkeypatch.setattr(preparation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(preparation.sys, "platform", "linux")
    monkeypatch.setattr(preparation.platform, "machine", lambda: "x86_64")
    return v2_history


def prepare():
    return preparation.prepare_plan(source_revision=CURRENT, plan_id=ec2.RECOVERY_V2_PLAN_ID)


def test_prepare_publishes_only_v2_plan_without_clocks_metadata_or_budget(
    prepared_host, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Preparation cannot allocate qualification clocks or access metadata")

    monkeypatch.setattr(ec2.time, "monotonic_ns", forbidden)
    monkeypatch.setattr(ec2, "_metadata", forbidden)
    record = prepare()
    plan = json.loads(prepared_host.plan_path.read_bytes())
    assert len(plan) == 12 and plan["schema_version"] == 2
    assert plan["history"] == prepared_host.history
    assert record["sha256"] == ec2._sha(prepared_host.plan_path.read_bytes())
    assert not prepared_host.consumption.exists() and not prepared_host.new_dir.exists()
    assert_preserved(prepared_host)


@pytest.mark.parametrize("existing", ["plan", "consumption", "partial_plan", "plan_symlink"])
def test_existing_new_artifacts_are_preserved_and_never_replaced(prepared_host, existing):
    path = prepared_host.consumption if existing == "consumption" else prepared_host.plan_path
    if existing == "plan_symlink":
        path.symlink_to(prepared_host.paths["state_sha256"])
        original = path.readlink()
    else:
        path.write_bytes(b"" if existing == "partial_plan" else b"USED\n")
        original = path.read_bytes()
    inode = path.lstat().st_ino
    with pytest.raises(ValueError, match="Existing v2"):
        prepare()
    assert path.lstat().st_ino == inode
    assert (path.readlink() if path.is_symlink() else path.read_bytes()) == original


def test_same_global_readonly_host_mutex_serializes_preparation(prepared_host):
    path = prepared_host.host.root / "host-admission.json"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            prepare()
    finally:
        os.close(fd)
    assert not prepared_host.plan_path.exists()
    prepare()


@pytest.mark.parametrize("target", ["state_sha256", "consumption_sha256", "stop", "helper"])
def test_second_history_or_source_change_cannot_publish_plan(prepared_host, target):
    path = (
        prepared_host.paths[target] if target in prepared_host.paths
        else getattr(prepared_host, target)
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        prepare()
    assert not prepared_host.plan_path.exists() and not prepared_host.consumption.exists()


@pytest.mark.parametrize("target", ["state_sha256", "source_lock", "host_claim"])
def test_history_inode_replacement_during_validation_is_detected(
    prepared_host, monkeypatch, target
):
    original = ec2._recovery_v2_plan

    def replaced(**arguments):
        result = original(**arguments)
        if target == "host_claim":
            path = prepared_host.host.root / "host-admission.json"
        elif target == "source_lock":
            path = prepared_host.source_lock
        else:
            path = prepared_host.paths[target]
        raw = path.read_bytes()
        replacement = path.with_name(path.name + ".replacement")
        replacement.write_bytes(raw)
        os.replace(replacement, path)
        return result

    monkeypatch.setattr(ec2, "_recovery_v2_plan", replaced)
    with pytest.raises(ValueError, match=r"mutex|record changed"):
        prepare()
    assert not prepared_host.plan_path.exists()


def test_partial_or_uncertain_plan_publication_does_not_grant_a_window(prepared_host, monkeypatch):
    original = ec2._fsync_dir

    def uncertain(path):
        if path == prepared_host.plan_path.parent and prepared_host.plan_path.exists():
            raise OSError("injected uncertain plan parent fsync")
        original(path)

    monkeypatch.setattr(ec2, "_fsync_dir", uncertain)
    with pytest.raises(OSError, match="uncertain"):
        prepare()
    retained = prepared_host.plan_path.read_bytes()
    with pytest.raises(ValueError, match="Existing v2"):
        prepare()
    assert prepared_host.plan_path.read_bytes() == retained
    assert not prepared_host.consumption.exists() and not prepared_host.new_dir.exists()


@pytest.mark.parametrize("change", ["nonroot", "architecture", "platform"])
def test_unsupported_preparer_context_refuses_before_publication(
    prepared_host, monkeypatch, change
):
    if change == "nonroot":
        monkeypatch.setattr(preparation.os, "geteuid", lambda: 1000)
    elif change == "architecture":
        monkeypatch.setattr(preparation.platform, "machine", lambda: "aarch64")
    else:
        monkeypatch.setattr(preparation.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="root Linux"):
        prepare()
    assert not prepared_host.plan_path.exists()


@pytest.mark.parametrize("plan", [ec2.RECOVERY_PLAN_ID, "../plan", "ec2-recovery-20261127-v3"])
def test_no_arbitrary_or_old_plan_can_select_third_allowance(prepared_host, plan):
    with pytest.raises(ValueError, match="fixed v2 plan"):
        preparation.prepare_plan(source_revision=CURRENT, plan_id=plan)
    assert not prepared_host.plan_path.exists()


def test_unknown_cli_and_abbreviations_do_not_reach_preparation(monkeypatch):
    def forbidden(**_arguments):
        raise AssertionError("Invalid arguments cannot reach preparation")

    monkeypatch.setattr(preparation, "prepare_plan", forbidden)
    with pytest.raises(SystemExit) as exited:
        preparation.main(["--source", CURRENT, "--plan-id", ec2.RECOVERY_V2_PLAN_ID])
    assert exited.value.code == 2


def test_cli_reports_prepared_only_without_claiming_m1(prepared_host, capsys):
    assert preparation.main([
        "--source-revision", CURRENT, "--plan-id", ec2.RECOVERY_V2_PLAN_ID
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PREPARED_ONLY"
    assert result["qualification_started"] is False and result["production_m1"] == "DISABLED"
