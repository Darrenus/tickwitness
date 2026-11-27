"""Exclusive v3 plan preparation over three real durable synthetic histories."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

sys.path.insert(0, str(Path(__file__).parent / "infrastructure"))
from test_restricted_reference_ec2_recovery_v3 import CURRENT, assert_preserved
from test_restricted_reference_ec2_recovery_v3 import base_host as base_host
from test_restricted_reference_ec2_recovery_v3 import host as host
from test_restricted_reference_ec2_recovery_v3 import recovery as recovery
from test_restricted_reference_ec2_recovery_v3 import v2 as v2
from test_restricted_reference_ec2_recovery_v3 import v2_history as v2_history
from test_restricted_reference_ec2_recovery_v3 import v3_history as v3_history

SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_ec2_reference_recovery_v3.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_recovery_v3_preparation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preparation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparation)


@pytest.fixture
def prepared_host(v3_history, monkeypatch):
    monkeypatch.setattr(preparation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(preparation.sys, "platform", "linux")
    monkeypatch.setattr(preparation.platform, "machine", lambda: "x86_64")
    return v3_history


def prepare():
    return preparation.prepare_plan(source_revision=CURRENT, plan_id=ec2.RECOVERY_V3_PLAN_ID)


def test_plan_is_readonly_preparation_not_a_window_metadata_request_or_research_call(
    prepared_host, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Preparation cannot allocate clocks or access IMDS")

    monkeypatch.setattr(ec2.time, "monotonic_ns", forbidden)
    monkeypatch.setattr(ec2, "_metadata", forbidden)
    result = prepare()
    plan = json.loads(prepared_host.plan_path.read_bytes())
    assert len(plan) == 12 and plan["schema_version"] == 3
    assert plan["history"] == prepared_host.history
    assert plan["history"]["recovery_v2"]["charged"] == 19
    assert plan["allowance"]["max_cumulative_admissions"] == 45
    assert result["sha256"] == ec2._sha(prepared_host.plan_path.read_bytes())
    assert not prepared_host.consumption.exists() and not prepared_host.new_dir.exists()
    assert len(prepared_host.host.requests) == 3
    assert_preserved(prepared_host)


@pytest.mark.parametrize("existing", ["plan", "consumption", "partial_plan", "plan_symlink"])
def test_existing_or_partial_new_records_are_not_replaced(prepared_host, existing):
    path = prepared_host.consumption if existing == "consumption" else prepared_host.plan_path
    if existing == "plan_symlink":
        path.symlink_to(prepared_host.paths["state_sha256"])
        original = path.readlink()
    else:
        path.write_bytes(b"" if existing == "partial_plan" else b"USED\n")
        original = path.read_bytes()
    inode = path.lstat().st_ino
    with pytest.raises(ValueError):
        prepare()
    assert path.lstat().st_ino == inode
    assert (path.readlink() if path.is_symlink() else path.read_bytes()) == original


def test_preparation_holds_the_same_readonly_old_host_mutex(prepared_host):
    fd = os.open(prepared_host.host.root / "host-admission.json", os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            prepare()
    finally:
        os.close(fd)
    assert not prepared_host.plan_path.exists()
    prepare()


@pytest.mark.parametrize(
    "target", ["state_sha256", "consumption_sha256", "stop", "helper", "case-19.json"]
)
def test_changed_third_history_or_source_cannot_publish_a_plan(prepared_host, target):
    path = (
        prepared_host.paths.get(target)
        or prepared_host.case_paths.get(target)
        or getattr(prepared_host, target)
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        prepare()
    assert not prepared_host.plan_path.exists() and not prepared_host.consumption.exists()


@pytest.mark.parametrize("target", ["state_sha256", "source_lock", "host_claim", "case-19.json"])
def test_same_bytes_new_inode_after_builder_never_becomes_a_prepared_plan(
    prepared_host, monkeypatch, target
):
    original = ec2._recovery_v3_plan

    def replaced(**arguments):
        plan = original(**arguments)
        if target == "host_claim":
            path = prepared_host.host.root / "host-admission.json"
        else:
            path = (
                prepared_host.paths.get(target)
                or prepared_host.case_paths.get(target)
                or getattr(prepared_host, target)
            )
        replacement = path.with_name(path.name + ".replacement")
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        return plan

    monkeypatch.setattr(ec2, "_recovery_v3_plan", replaced)
    with pytest.raises(ValueError):
        prepare()
    assert not prepared_host.plan_path.exists()


def test_uncertain_plan_fsync_keeps_original_bytes_and_grants_no_claim(prepared_host, monkeypatch):
    original = ec2._fsync_dir

    def uncertain(path):
        if path == prepared_host.plan_path.parent and prepared_host.plan_path.exists():
            raise OSError("uncertain v3 plan parent fsync")
        original(path)

    monkeypatch.setattr(ec2, "_fsync_dir", uncertain)
    with pytest.raises(OSError):
        prepare()
    raw = prepared_host.plan_path.read_bytes()
    with pytest.raises(ValueError):
        prepare()
    assert prepared_host.plan_path.read_bytes() == raw
    assert not prepared_host.consumption.exists() and not prepared_host.new_dir.exists()


@pytest.mark.parametrize("change", ["nonroot", "architecture", "platform"])
def test_unsupported_preparation_context_refuses_before_publication(
    prepared_host, monkeypatch, change
):
    if change == "nonroot":
        monkeypatch.setattr(preparation.os, "geteuid", lambda: 1000)
    elif change == "architecture":
        monkeypatch.setattr(preparation.platform, "machine", lambda: "aarch64")
    else:
        monkeypatch.setattr(preparation.sys, "platform", "darwin")
    with pytest.raises(ValueError):
        prepare()
    assert not prepared_host.plan_path.exists()


@pytest.mark.parametrize(
    "plan", [ec2.RECOVERY_PLAN_ID, ec2.RECOVERY_V2_PLAN_ID, "../plan", "other"]
)
def test_old_or_arbitrary_selection_does_not_open_the_fourth_allowance(prepared_host, plan):
    with pytest.raises(ValueError):
        preparation.prepare_plan(source_revision=CURRENT, plan_id=plan)
    assert not prepared_host.plan_path.exists()


def test_preparer_cli_has_no_abbreviations_and_reports_prepared_only(prepared_host, capsys):
    with pytest.raises(SystemExit) as exited:
        preparation.main(["--source", CURRENT, "--plan-id", ec2.RECOVERY_V3_PLAN_ID])
    assert exited.value.code == 2 and not prepared_host.plan_path.exists()
    capsys.readouterr()
    assert (
        preparation.main(["--source-revision", CURRENT, "--plan-id", ec2.RECOVERY_V3_PLAN_ID]) == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PREPARED_ONLY" and result["qualification_started"] is False
    assert result["production_m1"] == "DISABLED" and not prepared_host.consumption.exists()
