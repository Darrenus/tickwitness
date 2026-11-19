"""Pure policy-setup decisions; never load policy or invoke an external command.

Actual loading, transition and kernel qualification belong only to the dedicated
remote workflow. These regressions supply no security qualification evidence.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/prepare_reference_policy.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_reference_policy", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def deadline() -> int:
    return time.monotonic_ns() + 30_000_000_000


def profile_directory(root: Path, name: str, mode: str, attachment: str) -> None:
    root.mkdir(parents=True)
    for field, value in (("name", name), ("mode", mode), ("attach", attachment)):
        (root / field).write_text(value + "\n")


def test_loaded_table_refuses_truncation_duplicates_and_missing_mode() -> None:
    for value in (
        b"truncated", b"alpha (enforce)\nalpha (complain)\n",
        b"alpha ()\n", b"alpha (unknown-mode)\n",
    ):
        with pytest.raises(policy.SetupRefused):
            policy.parse_profiles(value)
    assert policy.parse_profiles(b"beta (enforce)\nalpha (unconfined)\n") == [
        {"name": "alpha", "mode": "unconfined"},
        {"name": "beta", "mode": "enforce"},
    ]


@pytest.mark.parametrize(
    "attachment",
    ["/usr/bin/bwrap", "/bin/bwrap", "/usr/bin/*", "/{,usr/}bin/bwrap", "/**"],
)
def test_literal_or_ambiguous_target_attachment_conflicts(attachment: str) -> None:
    assert policy.attachment_may_conflict(attachment)


@pytest.mark.parametrize(
    "attachment", ["/usr/bin/firefox{,-beta}", "/snap/bin/*", "/usr/sbin/service", "named-profile"]
)
def test_only_definitely_nonmatching_literal_prefix_can_be_excluded(attachment: str) -> None:
    assert not policy.attachment_may_conflict(attachment)


def test_bounded_literal_braces_can_prove_explicit_nonmatches() -> None:
    assert not policy.attachment_may_conflict("/{usr/,}sbin/dhclient")
    assert not policy.attachment_may_conflict("/usr/bin/{foo,bar}")
    assert policy.attachment_may_conflict("/usr/bin/{foo,{bwrap,bar}}")
    with pytest.raises(policy.SetupRefused, match="bound"):
        policy.expand_fixed_braces("{" + ",".join(str(index) for index in range(65)) + "}")
    with pytest.raises(policy.SetupRefused):
        policy.attachment_may_conflict("/usr/bin/{unknown}")


def test_unknown_source_policy_cannot_add_an_extra_capability_or_profile() -> None:
    frozen = policy.POLICY_SOURCE.read_bytes()
    policy.validate_policy_bytes(frozen)
    with pytest.raises(policy.SetupRefused, match="frozen pin"):
        policy.validate_policy_bytes(frozen.replace(b"userns,", b"userns, capability,"))
    with pytest.raises(policy.SetupRefused):
        policy.validate_policy_bytes(frozen + b"profile unexpected { }\n")


def test_unknown_kernel_attachment_cannot_be_assumed_safe() -> None:
    with pytest.raises(policy.SetupRefused, match="unknown"):
        policy.attachment_may_conflict("<unknown>")


def test_existing_selected_name_cannot_be_reused_even_if_mode_matches() -> None:
    with pytest.raises(policy.SetupRefused, match="already exists"):
        policy.refuse_conflicts(
            [{"name": policy.PROFILE_NAME, "mode": "unconfined"}], []
        )


def test_attachment_introspection_must_cover_the_actual_loaded_table(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    profile_directory(root / "other.1", "other", "enforce", "/usr/bin/other")
    before = [{"name": "other", "mode": "enforce"}]
    assert policy.capture_attachments(root, before, deadline()) == [
        {"name": "other", "mode": "enforce", "attachment": "/usr/bin/other"}
    ]
    with pytest.raises(policy.SetupRefused, match="disagree"):
        policy.capture_attachments(
            root, before + [{"name": "missing", "mode": "enforce"}], deadline()
        )


def test_nested_profile_introspection_uses_full_names(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    profile_directory(root / "parent.1", "parent", "enforce", "/usr/bin/parent")
    profile_directory(root / "parent.1/profiles/hat.2", "hat", "complain", "hat")
    before = [
        {"name": "parent", "mode": "enforce"},
        {"name": "parent//hat", "mode": "complain"},
    ]
    rows = policy.capture_attachments(root, before, deadline())
    assert [row["name"] for row in rows] == ["parent", "parent//hat"]


def test_loaded_readback_requires_only_one_named_unconfined_addition() -> None:
    before = [{"name": "other", "mode": "enforce"}]
    after = before + [{"name": policy.PROFILE_NAME, "mode": "unconfined"}]
    attachments = [
        {"name": policy.PROFILE_NAME, "mode": "unconfined", "attachment": "/usr/bin/bwrap"}
    ]
    assert policy.loaded_after_is_selected(before, after, attachments)
    assert not policy.loaded_after_is_selected(
        before, [{"name": "other", "mode": "complain"}, after[-1]], attachments
    )
    assert not policy.loaded_after_is_selected(
        before, before + [{"name": policy.PROFILE_NAME, "mode": "enforce"}], attachments
    )
    assert not policy.loaded_after_is_selected(before, after, [
        {"name": policy.PROFILE_NAME, "mode": "unconfined", "attachment": "/usr/bin/*"}
    ])


def test_optional_absence_is_explicit_not_a_hash_of_empty_bytes(tmp_path: Path) -> None:
    path = tmp_path / "absent-config"
    identity = policy.file_identity(path, deadline(), optional=True)
    assert identity["exists"] is False
    assert identity["sha256"] is None and identity["bytes"] is None
    assert identity["reason"] == "not_present"
    path.symlink_to(tmp_path / "missing-target")
    with pytest.raises(policy.SetupRefused):
        policy.file_identity(path, deadline(), optional=True)


def test_feature_capture_binds_bytes_and_refuses_oversized_or_symlink_input(tmp_path: Path) -> None:
    root = tmp_path / "features"
    (root / "domain").mkdir(parents=True)
    (root / "domain/change_profile").write_bytes(b"yes\n")
    evidence, contents = policy.capture_features(root, deadline())
    assert contents == {"domain/change_profile": b"yes\n"}
    assert evidence["canonical_sha256"] == policy.sha(policy.canonical(evidence["files"]))
    assert evidence["files"][0]["sha256"] == policy.sha(b"yes\n")
    (root / "domain/change_profile").write_bytes(b"x" * 4097)
    with pytest.raises(policy.SetupRefused):
        policy.capture_features(root, deadline())
    (root / "domain/change_profile").unlink()
    (root / "domain/change_profile").symlink_to(tmp_path / "outside")
    with pytest.raises(policy.SetupRefused):
        policy.capture_features(root, deadline())


def test_feature_file_count_is_bounded_before_a_policy_can_be_loaded(tmp_path: Path) -> None:
    root = tmp_path / "features"
    root.mkdir()
    for index in range(257):
        (root / f"feature-{index:03d}").write_bytes(b"1\n")
    with pytest.raises(policy.SetupRefused, match="count"):
        policy.capture_features(root, deadline())


def test_selected_package_closure_requires_all_three_installed_packages() -> None:
    raw = (
        "apparmor\t4.0.1-0ubuntu1\tinstall ok installed\n"
        "libapparmor1:amd64\t4.0.1-0ubuntu1\tinstall ok installed\n"
        "bubblewrap\t0.9.0-1ubuntu0.3\tinstall ok installed\n"
    )
    versions = policy.parse_packages(raw)
    assert versions["libapparmor1"] == "4.0.1-0ubuntu1"
    with pytest.raises(policy.SetupRefused):
        policy.parse_packages(raw.replace("bubblewrap", "unexpected-package"))
    with pytest.raises(policy.SetupRefused):
        policy.parse_packages(raw.replace("install ok installed", "deinstall ok config-files"))
    with pytest.raises(policy.SetupRefused):
        policy.parse_packages(raw + raw.splitlines()[0] + "\n")


@pytest.mark.parametrize(
    "change",
    [
        {"returncode": 1}, {"returncode": None}, {"timed_out": True},
        {"overflow": "stderr"}, {"exception": {"type": "TimeoutExpired"}},
        {"started": False}, {"stop_confirmed": False},
    ],
)
def test_nonzero_overflow_timeout_or_unknown_command_never_authorizes_load(
    change: dict[str, object],
) -> None:
    record = {
        "started": True, "stop_confirmed": True, "returncode": 0,
        "timed_out": False, "overflow": None, "exception": None,
    }
    policy.require_command(record)
    with pytest.raises(policy.SetupRefused):
        policy.require_command({**record, **change})


def test_original_window_is_not_renewed_by_later_commands() -> None:
    with pytest.raises(TimeoutError):
        policy.check_window(time.monotonic_ns() - 1)


def test_existing_owned_policy_or_evidence_file_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "selected-policy"
    path.write_bytes(b"original evidence")
    with pytest.raises(FileExistsError):
        policy.write_exclusive(path, b"replacement")
    assert path.read_bytes() == b"original evidence"


def test_nonremote_refusal_precedes_any_command_or_filesystem_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(policy, "EVIDENCE", evidence)
    monkeypatch.setattr(policy.sys, "argv", ["prepare_reference_policy.py"])

    def refuse() -> None:
        raise policy.SetupRefused("not the authorized remote family")

    def no_command(*args: object, **kwargs: object) -> object:
        raise AssertionError("A nonremote refusal must not invoke an external command")

    monkeypatch.setattr(policy, "remote_guard", refuse)
    monkeypatch.setattr(policy.subprocess, "Popen", no_command)
    assert policy.main() == 1
    assert not evidence.exists()


def test_preload_canonical_digest_binds_the_exact_persisted_bytes(tmp_path: Path) -> None:
    value = {"policy": {"sha256": "a" * 64}, "observed": None}
    raw = policy.canonical(value)
    path = tmp_path / "preload-manifest.json"
    policy.write_exclusive(path, raw)
    assert policy.sha(path.read_bytes()) == policy.sha(raw)
    assert json.loads(path.read_bytes()) == value


def test_private_umask_does_not_hide_any_frozen_evidence_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(policy, "EVIDENCE", evidence)
    original = os.umask(0o077)
    try:
        evidence.mkdir(mode=0o755)
        policy.evidence_directory(evidence / "inputs")
        target = evidence / "kernel-features/domain/change_profile"
        policy.evidence_directory(target.parent)
        policy.write_exclusive(target, b"yes\n")
    finally:
        os.umask(original)
    for directory in (
        evidence, evidence / "inputs", evidence / "kernel-features",
        evidence / "kernel-features/domain",
    ):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o755
        assert directory.stat().st_uid == os.geteuid()
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    with pytest.raises(ValueError):
        policy.evidence_directory(tmp_path / "outside-evidence")


@pytest.mark.parametrize(
    "raw, expected",
    [(None, []), (b"", []), (b"# comment\n \n", []), (b"# cache\nwrite-cache\n", ["write-cache"])],
)
def test_only_empty_comments_or_overridden_known_cache_config_is_allowed(
    raw: bytes | None, expected: list[str],
) -> None:
    guard = policy.validate_parser_config(raw)
    assert guard["allowed_options"] == expected
    assert guard["exists"] is (raw is not None)
    assert guard["source_sha256"] == (policy.sha(raw) if raw is not None else None)
    assert guard["input_redirection_options_permitted"] is False


@pytest.mark.parametrize(
    "raw",
    [
        b"Include=/tmp/other\n", b"base=/tmp/other\n",
        b"override-policy-abi=/tmp/other\n", b"kernel-features=/tmp/features\n",
        b"namespace=other\n", b"unknown-option\n", b"write-cache\nwrite-cache\n",
        b"write-cache # unparsed inline option\n", b"\xff",
    ],
)
def test_unsafe_or_unknown_default_config_is_refused_before_popen(
    raw: bytes, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def no_process(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("Unknown parser configuration reached Popen")

    monkeypatch.setattr(policy.subprocess, "Popen", no_process)
    with pytest.raises(policy.SetupRefused):
        policy.checked_parser_version(raw, deadline())
    assert calls == []


def test_known_cache_config_is_overridden_even_for_readonly_version_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    def captured(argv: tuple[str, ...], limit: int, *, capture_number: int) -> dict[str, object]:
        observed.append(argv)
        return {
            "started": True, "stop_confirmed": True, "returncode": 0,
            "timed_out": False, "overflow": None, "exception": None,
        }

    monkeypatch.setattr(policy, "bounded_command", captured)
    guard, _record = policy.checked_parser_version(b"write-cache\n", deadline())
    assert guard["allowed_options"] == ["write-cache"]
    assert observed == [(str(policy.PARSER), "--skip-cache", "--version")]
