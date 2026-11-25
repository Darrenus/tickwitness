"""Pure EC2 policy decisions; these tests never load policy or run a command.

Only a dedicated remote qualification can supply actual security evidence.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/prepare_reference_policy_ec2.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_ec2_reference_policy", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def selected(attachment: str = policy.PROFILE_NAME, mode: str = "unconfined") -> dict[str, str]:
    return {"name": policy.PROFILE_NAME, "mode": mode, "attachment": attachment}


def foreign() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    return (
        [{"name": "foreign", "mode": "enforce"}],
        [{"name": "foreign", "mode": "enforce", "attachment": "<unknown>"}],
    )


def test_frozen_manual_policy_has_no_executable_attachment() -> None:
    raw = policy.POLICY_SOURCE.read_bytes()
    policy.validate_policy_bytes(raw)
    assert raw == (
        b"abi <abi/4.0>,\n\n"
        b"profile tickwitness-reference-ec2 flags=(unconfined) {\n  userns,\n}\n"
    )
    assert policy.shared.sha(raw) == policy.POLICY_SHA256
    for changed in (raw.replace(b"userns,", b"userns, capability,"), raw + b"\n"):
        with pytest.raises(policy.SetupRefused, match="frozen pin"):
            policy.validate_policy_bytes(changed)


def test_existing_selected_name_refuses_even_with_matching_policy_mode() -> None:
    with pytest.raises(policy.SetupRefused, match="already exists"):
        policy.refuse_selected_name([{"name": policy.PROFILE_NAME, "mode": "unconfined"}])


def test_opaque_foreign_observations_are_retained_without_global_closure_claim() -> None:
    before, attachments = foreign()
    policy.refuse_selected_name(before)
    after = sorted(
        [*before, {"name": policy.PROFILE_NAME, "mode": "unconfined"}],
        key=lambda row: row["name"],
    )
    actual = sorted([*attachments, selected()], key=lambda row: row["name"])
    assert policy.loaded_after_is_selected(before, after, attachments, actual)
    assert attachments[0]["attachment"] == "<unknown>"
    # The previous GHA attachment-based entry keeps its stricter refusal.
    with pytest.raises(policy.shared.SetupRefused, match="unknown"):
        policy.shared.attachment_may_conflict("<unknown>")


@pytest.mark.parametrize("raw", ["", "<unknown>", "/usr/bin/bwrap", "/**", "another-profile"])
def test_manual_profile_requires_exact_kernel_profile_name_fallback(raw: str) -> None:
    after = [{"name": policy.PROFILE_NAME, "mode": "unconfined"}]
    assert not policy.loaded_after_is_selected([], after, [], [selected(raw)])


@pytest.mark.parametrize("mode", ["complain", "enforce", "kill"])
def test_selected_mode_must_be_actual_unconfined(mode: str) -> None:
    after = [{"name": policy.PROFILE_NAME, "mode": mode}]
    assert not policy.loaded_after_is_selected([], after, [], [selected(mode=mode)])


def test_duplicate_selected_observation_and_foreign_change_refuse() -> None:
    before, attachments = foreign()
    after = sorted(
        [*before, {"name": policy.PROFILE_NAME, "mode": "unconfined"}],
        key=lambda row: row["name"],
    )
    assert not policy.loaded_after_is_selected(
        before, after, attachments, [*attachments, selected(), selected()]
    )
    changed = [{**attachments[0], "attachment": "foreign"}, selected()]
    assert not policy.loaded_after_is_selected(before, after, attachments, changed)
    assert not policy.loaded_after_is_selected(
        after, after, attachments, [*attachments, selected()]
    )


def test_unowned_caller_cannot_obtain_policy_authority() -> None:
    with pytest.raises(policy.SetupRefused, match="actual live EC2 admission"):
        policy._remote_guard(SimpleNamespace())


@pytest.mark.parametrize("caller_kind", ["duck", "subclass"])
def test_unowned_entry_refuses_before_any_property_or_host_operation(
    monkeypatch: pytest.MonkeyPatch, caller_kind: str,
) -> None:
    calls: list[str] = []

    class Duck:
        def __getattribute__(self, name: str) -> object:
            calls.append("attribute:" + name)
            raise AssertionError("Unowned caller properties must never be read")

    class Subclass(policy.Ec2Run):
        def __getattribute__(self, name: str) -> object:
            calls.append("attribute:" + name)
            raise AssertionError("Subclass properties must never be read")

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append("host_operation")
        raise AssertionError("No filesystem, phase or host operation may precede authority")

    caller = Duck() if caller_kind == "duck" else object.__new__(Subclass)
    monkeypatch.setattr(policy, "_new_directory", forbidden)
    monkeypatch.setattr(policy.os, "geteuid", forbidden)
    monkeypatch.setattr(policy.platform, "machine", forbidden)
    monkeypatch.setattr(policy.shared, "bounded_command", forbidden)
    with pytest.raises(policy.SetupRefused, match="actual live EC2 admission"):
        policy.prepare_policy(ec2_run=caller)
    assert calls == []


def test_claim_failure_precedes_any_filesystem_or_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    class FakeRun:
        started_ns = 123
        setup_deadline_ns = started_ns + policy.shared.WINDOW_NS
        run_dir = Path("/var/lib/tickwitness-reference-ec2/runs/" + "a" * 32)
        staged_policy = run_dir / "policy.apparmor"
        policy_evidence_dir = run_dir / "policy-evidence"
        source_revision = "b" * 40

        def require_phase(self, phase: str) -> None:
            calls.append(phase)
            raise policy.SetupRefused("Claim is not this invocation's CLAIMED state")

    monkeypatch.setattr(policy, "Ec2Run", FakeRun)
    monkeypatch.setattr(policy.os, "geteuid", lambda: 0)
    monkeypatch.setattr(policy.sys, "platform", "linux")
    monkeypatch.setattr(policy.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(policy, "_new_directory", lambda path: calls.append(path))
    monkeypatch.setattr(
        policy.shared, "bounded_command", lambda *args, **kwargs: calls.append("command")
    )
    with pytest.raises(policy.SetupRefused, match="CLAIMED"):
        policy.prepare_policy(ec2_run=FakeRun())
    assert calls == ["CLAIMED"]


def test_failed_provider_keeps_original_anchor_and_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    writes: dict[Path, bytes] = {}

    class FakeRun:
        started_ns = 123
        setup_deadline_ns = started_ns + policy.shared.WINDOW_NS
        run_dir = Path("/var/lib/tickwitness-reference-ec2/runs/" + "a" * 32)
        staged_policy = run_dir / "policy.apparmor"
        policy_evidence_dir = run_dir / "policy-evidence"
        source_revision = "b" * 40

        def prepare_host(self) -> dict[str, object]:
            calls.append("prepare_host")
            raise policy.SetupRefused("IMDS observation failed within original setup window")

        def policy_ready(self, **kwargs: object) -> None:
            calls.append("policy_ready")

    monkeypatch.setattr(policy, "_remote_guard", lambda run: calls.append("CLAIMED"))
    monkeypatch.setattr(policy, "_new_directory", lambda path: calls.append("exclusive_evidence"))
    monkeypatch.setattr(policy, "_fsync_directory", lambda path: None)
    monkeypatch.setattr(policy.os.path, "lexists", lambda path: False)
    monkeypatch.setattr(
        policy.shared, "write_exclusive", lambda path, raw: writes.__setitem__(path, raw)
    )
    monkeypatch.setattr(
        policy.shared, "bounded_command", lambda *args, **kwargs: calls.append("command")
    )
    with pytest.raises(policy.SetupRefused, match="IMDS"):
        policy.prepare_policy(ec2_run=FakeRun())
    receipt = json.loads(writes[FakeRun.policy_evidence_dir / "policy-setup.json"])
    assert calls == ["CLAIMED", "exclusive_evidence", "prepare_host"]
    assert receipt["status"] == "REFUSED"
    assert receipt["original_started_ns"] == FakeRun.started_ns
    assert receipt["original_deadline_ns"] == FakeRun.setup_deadline_ns
    assert receipt["commands"] == []
    assert receipt["retry_performed"] is False
    assert receipt["product_m1"] == "DISABLED"


def test_exclusive_directory_reuse_refuses_without_normalizing_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = tmp_path / "policy-evidence"
    existing.mkdir(mode=0o700)
    marker = existing / "retained"
    marker.write_bytes(b"original")
    monkeypatch.setattr(policy, "_secure_directory", lambda path: None)
    with pytest.raises(FileExistsError):
        policy._new_directory(existing)
    assert marker.read_bytes() == b"original"
    assert existing.stat().st_mode & 0o777 == 0o700
