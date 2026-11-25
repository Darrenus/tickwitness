#!/usr/bin/env python3
"""One manual-only AppArmor add, joined to an already claimed EC2 qualification.

This is a trusted controller entry point, never a guest-selected setup command.
It grants no executable attachment and does not enable product M1.
"""

from __future__ import annotations

import ctypes
import importlib.util
import os
import platform
import stat
import sys
from contextlib import suppress
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SOURCE / "src"))
from tickwitness.infrastructure.restricted_reference_ec2 import Ec2Run  # noqa: E402

_SHARED_PATH = _SOURCE / "scripts/prepare_reference_policy.py"
_SPEC = importlib.util.spec_from_file_location("tickwitness_ec2_policy_shared", _SHARED_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Fixed shared policy loader is unavailable")
shared = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shared)

PROFILE_NAME = "tickwitness-reference-ec2"
POLICY_SHA256 = "62c319e3655d13e4c4f856e3591efb48dda36ce3ba175681688ff49b05592314"
POLICY_SOURCE = _SOURCE / "research/security/reference-ec2.apparmor"
MANUAL_OBSERVATION = {
    "raw": PROFILE_NAME,
    "interpretation": "kernel_profile_name_fallback_no_exec_attachment",
}
SetupRefused = shared.SetupRefused
Row = dict[str, object]


def validate_policy_bytes(raw: bytes) -> None:
    if shared.sha(raw) != POLICY_SHA256:
        raise SetupRefused("Selected EC2 policy differs from its frozen pin")


def refuse_selected_name(before: list[dict[str, str]]) -> None:
    if any(row["name"] == PROFILE_NAME for row in before):
        raise SetupRefused("Selected EC2 profile already exists; no retry or replace")


def loaded_after_is_selected(
    before: list[dict[str, str]],
    after: list[dict[str, str]],
    attachments_before: list[dict[str, str]],
    attachments_after: list[dict[str, str]],
) -> bool:
    """Require one manual profile; retain every foreign opaque observation."""
    expected = sorted(
        [*before, {"name": PROFILE_NAME, "mode": "unconfined"}], key=lambda row: row["name"]
    )
    selected = [row for row in attachments_after if row["name"] == PROFILE_NAME]
    return (
        not any(row["name"] == PROFILE_NAME for row in before)
        and after == expected
        and selected
        == [{"name": PROFILE_NAME, "mode": "unconfined", "attachment": PROFILE_NAME}]
        and [row for row in attachments_after if row["name"] != PROFILE_NAME]
        == attachments_before
    )


def _secure_directory(path: Path) -> None:
    """Check every absolute ancestor without following a symlink."""
    if not path.is_absolute():
        raise SetupRefused("EC2 evidence requires a fixed absolute directory")
    for current in (*reversed(path.parents), path):
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SetupRefused("EC2 evidence ancestor is not a secure root directory")


def _new_directory(path: Path) -> None:
    _secure_directory(path.parent)
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    _secure_directory(path)


def _evidence_directory(root: Path, path: Path) -> None:
    relative = path.relative_to(root)
    _secure_directory(root)
    current = root
    for part in relative.parts:
        current /= part
        with suppress(FileExistsError):
            current.mkdir(mode=0o755)
        _secure_directory(current)
        current.chmod(0o755)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _source_record(path: Path) -> Row:
    raw = shared.bounded_read(path, 65_536)
    return {"path": str(path), "sha256": shared.sha(raw), "bytes": len(raw)}


def _remote_guard(ec2_run: Ec2Run) -> None:
    if type(ec2_run) is not Ec2Run:
        raise SetupRefused("Policy setup requires its actual live EC2 admission")
    if os.geteuid() != 0 or sys.platform != "linux" or platform.machine() != "x86_64":
        raise SetupRefused("Policy setup requires its dedicated root Linux x86_64 host")
    ec2_run.require_phase("CLAIMED")
    shared.check_window(ec2_run.setup_deadline_ns)


def prepare_policy(*, ec2_run: Ec2Run) -> Row:
    """Join this invocation's CLAIMED record; never create or renew an admission."""
    _remote_guard(ec2_run)
    created = False
    load_submitted = False
    commands: list[Row] = []
    observations: Row = {}
    phase = "claimed_guard"
    started = ec2_run.started_ns
    deadline = ec2_run.setup_deadline_ns
    evidence = ec2_run.policy_evidence_dir
    staged = ec2_run.staged_policy
    provider_context: Row | None = None
    try:
        if (
            evidence != ec2_run.run_dir / "policy-evidence"
            or staged != ec2_run.run_dir / "policy.apparmor"
        ):
            raise SetupRefused("Policy evidence paths differ from the owned admission")
        _new_directory(evidence)
        created = True
        if os.path.lexists(staged):
            raise SetupRefused("Staged policy already exists; no overwrite is permitted")
        phase = "provider_preflight"
        provider_context = ec2_run.prepare_host()
        if provider_context != ec2_run.provider_record:
            raise SetupRefused("Provider host observation differs from its owned cache")
        shared.check_window(deadline)
        phase = "preflight"
        restrict_before = shared.bounded_read(shared.RESTRICT, 16).decode().strip()
        enabled = shared.bounded_read(shared.AA_ENABLED, 16).decode().strip()
        controller_label = shared.bounded_read(shared.CONTROLLER_LABEL, 4096).decode().strip()
        if restrict_before != "1" or enabled != "Y" or controller_label != "unconfined":
            raise SetupRefused("Required unchanged AppArmor host state is unavailable")
        release_raw = shared.bounded_read(
            Path("/etc/os-release").resolve(strict=True), 65_536
        ).decode()
        release = {
            key: value.strip('"')
            for line in release_raw.splitlines()
            if "=" in line
            for key, value in [line.split("=", 1)]
        }
        if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
            raise SetupRefused("Observed OS is outside the selected Ubuntu24.04 family")
        status_fields = {
            key: value.strip()
            for line in shared.bounded_read(shared.CONTROLLER_STATUS, 65_536).decode().splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        if status_fields.get("NoNewPrivs") != "0":
            raise SetupRefused("Controller already has incompatible no-new-privileges state")
        before = shared.parse_profiles(
            shared.bounded_read(shared.PROFILE_TABLE, shared.DOCUMENT_LIMIT)
        )
        attachments_before = shared.capture_attachments(shared.PROFILE_ROOT, before, deadline)
        observations.update(
            loaded_profiles_before=before,
            attachments_before=attachments_before,
            restrict_before=restrict_before,
            apparmor_enabled=enabled,
            controller_label=controller_label,
        )
        refuse_selected_name(before)
        # Foreign <unknown> remains an opaque observation, never a non-conflict proof.
        source = shared.bounded_read(POLICY_SOURCE, 65_536)
        validate_policy_bytes(source)
        identities = {
            "bwrap": shared.file_identity(Path("/usr/bin/bwrap"), deadline),
            "parser": shared.file_identity(shared.PARSER, deadline),
            "abi": shared.file_identity(shared.ABI, deadline),
            "parser_config": shared.file_identity(shared.PARSER_CONFIG, deadline, optional=True),
            "libapparmor": shared.file_identity(shared.LIBAPPARMOR, deadline),
        }
        if identities["bwrap"]["mode"] & 0o6000 or identities["parser"]["mode"] & 0o6000:
            raise SetupRefused("Selected bwrap/parser has privilege-bearing mode bits")
        if identities["abi"]["bytes"] > 65_536 or (
            identities["parser_config"]["exists"] and identities["parser_config"]["bytes"] > 65_536
        ):
            raise SetupRefused("ABI or parser configuration exceeds its bound")
        config_raw = (
            shared.bounded_read(shared.PARSER_CONFIG, 65_536)
            if identities["parser_config"]["exists"]
            else None
        )
        configuration_guard = shared.validate_parser_config(config_raw)
        if (
            config_raw is not None
            and shared.sha(config_raw) != identities["parser_config"]["sha256"]
        ):
            raise SetupRefused("Observed parser configuration bytes changed")
        library = ctypes.CDLL(str(identities["libapparmor"]["realpath"]), use_errno=True)
        if not getattr(library, "aa_change_profile", None):
            raise SetupRefused("Bound libapparmor lacks the required transition symbol")
        dpkg_identity = shared.file_identity(shared.DPKG, deadline)
        features, feature_bytes = shared.capture_features(shared.FEATURE_ROOT, deadline)
        phase = "readonly_commands"
        if (
            shared.file_identity(shared.PARSER_CONFIG, deadline, optional=True)
            != identities["parser_config"]
        ):
            raise SetupRefused("Parser configuration changed before version observation")
        version = shared.bounded_command(
            (str(shared.PARSER), "--skip-cache", "--version"),
            deadline, capture_number=1, evidence_dir=evidence,
        )
        commands.append(version)
        shared.require_command(version)
        if version["stdout_preview_truncated"] or not version["stdout"].strip():
            raise SetupRefused("Observed parser version output is empty")
        packages = shared.bounded_command(
            (
                str(shared.DPKG), "--show",
                "--showformat=${binary:Package}\t${Version}\t${Status}\n",
                "apparmor", "libapparmor1", "bubblewrap",
            ),
            deadline, capture_number=2, evidence_dir=evidence,
        )
        commands.append(packages)
        shared.require_command(packages)
        if packages["stdout_preview_truncated"]:
            raise SetupRefused("Observed package response exceeded its semantic bound")
        package_versions = shared.parse_packages(packages["stdout"])
        phase = "stage_and_freeze"
        shared.write_exclusive(staged, source, limit=65_536)
        _fsync_directory(ec2_run.run_dir)
        policy = {"path": str(staged), "sha256": shared.sha(source), "bytes": len(source)}
        staged_identity = shared.file_identity(staged, deadline)
        host = {
            "system": platform.system(), "release": platform.release(),
            "version": platform.version(), "architecture": platform.machine(),
            "os_release": release_raw,
            "boot_id": shared.bounded_read(shared.BOOT_ID, 128).decode().strip(),
            "runner_image_os": None, "runner_image_version": None,
            "run_id": ec2_run.run_id, "run_attempt": None,
            "controller_uid": os.geteuid(), "controller_gid": os.getegid(),
            "controller_label": controller_label,
        }
        if host["boot_id"] != ec2_run.boot_id:
            raise SetupRefused("Observed boot differs from the owned admission")
        loader_source = _source_record(Path(__file__).resolve())
        shared_loader_source = _source_record(_SHARED_PATH)
        argv = (str(shared.PARSER), "--add", "--skip-cache", "--base=/etc/apparmor.d", str(staged))
        preload = {
            "kind": "restricted_reference_ec2_policy_preload_v1", "schema_version": 1,
            "profile_name": PROFILE_NAME, "attachment": None, "mode": "unconfined",
            "policy": policy, "staged_identity": staged_identity,
            "policy_source": {
                "path": str(POLICY_SOURCE), "sha256": shared.sha(source), "bytes": len(source)
            },
            "identities": identities, "features": features, "host": host,
            "provider_context": provider_context,
            "loaded_profiles_before": before, "attachments_before": attachments_before,
            "restrict_before": restrict_before, "source_revision": ec2_run.source_revision,
            "parser_argv": list(argv), "parser_version": version, "packages": package_versions,
            "parser_configuration_guard": configuration_guard, "dpkg_identity": dpkg_identity,
            "loader_source": loader_source, "shared_loader_source": shared_loader_source,
            "original_started_ns": started, "original_deadline_ns": deadline,
            "max_commands": 3, "per_stream_bytes": shared.STREAM_LIMIT,
        }
        preload_raw = shared.canonical(preload)
        shared.write_exclusive(evidence / "preload-manifest.json", preload_raw)
        preload_sha = shared.sha(preload_raw)
        shared.write_exclusive(evidence / "preload-manifest.sha256", (preload_sha + "\n").encode())
        _evidence_directory(evidence, evidence / "inputs")
        shared.write_exclusive(evidence / "inputs/policy", source, limit=65_536)
        for key, original in (("abi", shared.ABI), ("parser_config", shared.PARSER_CONFIG)):
            if identities[key]["exists"]:
                shared.write_exclusive(
                    evidence / "inputs" / key, shared.bounded_read(original, 65_536), limit=65_536
                )
        _evidence_directory(evidence, evidence / "kernel-features")
        for relative, content in feature_bytes.items():
            target = evidence / "kernel-features" / relative
            _evidence_directory(evidence, target.parent)
            shared.write_exclusive(target, content, limit=4096)
        _fsync_directory(evidence)

        def revalidate_tcb() -> None:
            for key, path in (
                ("bwrap", Path("/usr/bin/bwrap")), ("parser", shared.PARSER),
                ("abi", shared.ABI), ("parser_config", shared.PARSER_CONFIG),
                ("libapparmor", shared.LIBAPPARMOR),
            ):
                if (
                    shared.file_identity(path, deadline, optional=key == "parser_config")
                    != identities[key]
                ):
                    raise SetupRefused("Selected binary/configuration identity changed")
            if shared.file_identity(shared.DPKG, deadline) != dpkg_identity:
                raise SetupRefused("Bound package-query identity changed")
            if shared.file_identity(staged, deadline) != staged_identity:
                raise SetupRefused("Exclusive staged policy identity changed")
            if shared.capture_features(shared.FEATURE_ROOT, deadline)[0] != features:
                raise SetupRefused("Kernel feature closure changed")
            if (
                _source_record(Path(__file__).resolve()) != loader_source
                or _source_record(_SHARED_PATH) != shared_loader_source
            ):
                raise SetupRefused("Trusted loader source changed")
            if _source_record(POLICY_SOURCE) != preload["policy_source"]:
                raise SetupRefused("Selected policy source changed")
            if ec2_run.revalidate(deadline_ns=deadline) != provider_context:
                raise SetupRefused("Provider identity changed within the original setup window")

        revalidate_tcb()
        current = shared.parse_profiles(
            shared.bounded_read(shared.PROFILE_TABLE, shared.DOCUMENT_LIMIT)
        )
        current_attachments = shared.capture_attachments(shared.PROFILE_ROOT, current, deadline)
        if current != before or current_attachments != attachments_before:
            raise SetupRefused("Loaded policy state changed before the one authorized add")
        if shared.bounded_read(shared.RESTRICT, 16).decode().strip() != "1":
            raise SetupRefused("Global userns restriction changed before add")
        phase = "one_add"
        shared.check_window(deadline)
        load_submitted = True
        loaded = shared.bounded_command(argv, deadline, capture_number=3, evidence_dir=evidence)
        commands.append(loaded)
        phase = "post_load_readback"
        after = shared.parse_profiles(
            shared.bounded_read(shared.PROFILE_TABLE, shared.DOCUMENT_LIMIT)
        )
        attachments_after = shared.capture_attachments(shared.PROFILE_ROOT, after, deadline)
        restrict_after = shared.bounded_read(shared.RESTRICT, 16).decode().strip()
        observations.update(
            loaded_profiles_after=after,
            attachments_after=attachments_after,
            restrict_after=restrict_after,
        )
        shared.require_command(loaded)
        if restrict_after != "1" or not loaded_after_is_selected(
            before, after, attachments_before, attachments_after
        ):
            raise SetupRefused(
                "Manual profile or unchanged foreign policy/restriction was not established"
            )
        revalidate_tcb()
        shared.check_window(deadline)
        loader = {
            **loaded, "version": version["stdout"], "packages": package_versions,
            "commands": commands, "original_started_ns": started, "original_deadline_ns": deadline,
            "host": host, "provider_context": provider_context,
            "policy_source": preload["policy_source"], "loader_source": loader_source,
            "shared_loader_source": shared_loader_source,
            "staged_identity": staged_identity, "dpkg_identity": dpkg_identity,
            "attachments_before": attachments_before, "attachments_after": attachments_after,
            "manual_attachment_observation": dict(MANUAL_OBSERVATION),
            "parser_configuration_guard": configuration_guard,
            "bounds": {
                "window_ns": shared.WINDOW_NS,
                "max_commands": 3,
                "per_stream_bytes": shared.STREAM_LIMIT,
            },
        }
        report = {
            "kind": "restricted_reference_ec2_policy_setup_v1", "schema_version": 1,
            "status": "LOADED_REFERENCE_ONLY", "profile_name": PROFILE_NAME,
            "attachment": None, "mode": "unconfined", "policy": policy,
            "identities": identities, "features": features, "loader": loader,
            "provider_context": provider_context,
            "loaded_profiles_before": before, "loaded_profiles_after": after,
            "restrict_before": restrict_before, "restrict_after": restrict_after,
            "source_revision": ec2_run.source_revision, "preload_manifest_sha256": preload_sha,
        }
        if set(report) != shared.SUCCESS_FIELDS | {"provider_context"}:
            raise SetupRefused("Internal EC2 success receipt schema differs")
        report_raw = shared.canonical(report) + b"\n"
        shared.write_exclusive(evidence / "policy-setup.json", report_raw)
        _fsync_directory(evidence)
        ec2_run.policy_ready(preload_sha256=preload_sha, report_sha256=shared.sha(report_raw))
        return report
    except Exception as error:
        failure: Row = {
            "kind": "restricted_reference_ec2_policy_setup_failure_v1", "schema_version": 1,
            "status": "UNKNOWN" if load_submitted else "REFUSED", "phase": phase,
            "reason": (type(error).__name__ + ": " + str(error))[:2048],
            "load_submitted": load_submitted, "commands": commands,
            "original_started_ns": started, "original_deadline_ns": deadline,
            "source_revision": ec2_run.source_revision, "provider_context": provider_context,
            "product_m1": "DISABLED", "retry_performed": False, "observations": observations,
        }
        if len(shared.canonical(failure)) + 1 > shared.DOCUMENT_LIMIT:
            failure["observations"] = {
                "retained": False, "reason": "report_bound_exceeded",
                "canonical_sha256": shared.sha(shared.canonical(observations)),
            }
        if created:
            target = evidence / "policy-setup.json"
            if os.path.lexists(target):
                target = evidence / "policy-setup-failure.json"
            shared.write_exclusive(target, shared.canonical(failure) + b"\n")
            _fsync_directory(evidence)
        raise


if __name__ == "__main__":
    sys.stderr.write("Use the trusted same-process EC2 qualification driver with its live claim.\n")
    raise SystemExit(1)
