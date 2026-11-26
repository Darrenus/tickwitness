"""Data-only policy/admission regressions; no root, namespaces or actual attacks."""

import copy
import dataclasses
import hashlib
import json
import os
import stat
import struct
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import restricted_reference as reference
from tickwitness.infrastructure import restricted_reference_bootstrap as bootstrap
from tickwitness.infrastructure import restricted_reference_ec2 as ec2
from tickwitness.infrastructure.restricted_reference_ec2 import Ec2Run, ProbeAdmission


def _filter_result(number, arch=0xC000003E, clone_flags=0):
    """Interpret the generated finite cBPF as data, not as a kernel qualification."""
    program = list(struct.iter_unpack("HBBI", reference.build_seccomp()))
    accumulator, cursor = 0, 0
    fields = {0: number, 4: arch, 16: clone_flags}
    while cursor < len(program):
        operation, yes, no, value = program[cursor]
        if operation == 0x20:
            accumulator = fields[value]
        elif operation == 0x15:
            cursor += yes if accumulator == value else no
        elif operation == 0x45:
            cursor += yes if accumulator & value else no
        elif operation == 0x06:
            return value
        else:
            pytest.fail("Unknown generated policy instruction")
        cursor += 1
    pytest.fail("Policy has no terminal action")


@pytest.mark.parametrize("number", [41, 53, 272, 319, 321, 425, 426, 427, 447])
def test_selected_denials_cannot_become_plain_allow(number):
    assert _filter_result(number) == 0x00050001


def test_abi_and_clone_paths_have_distinct_closed_actions():
    assert _filter_result(39) == 0x7FFF0000  # Ordinary native getpid.
    assert _filter_result(0x40000000 | 39) == 0x00050001  # Distinct from kernel ENOSYS.
    assert _filter_result(39, arch=0x40000003) == 0x80000000  # Compat architecture.
    assert _filter_result(435) == 0x00050026  # libc may fall back; clone3 itself is denied.
    assert _filter_result(56, clone_flags=17) == 0x7FFF0000  # Ordinary fork SIGCHLD.
    for flag in (0x80, 0x20000, 0x10000000, 0x40000000):
        assert _filter_result(56, clone_flags=flag) == 0x00050001


def test_raw_mount_evidence_catches_nonrecursive_writable_child():
    rows = []
    for index, path in enumerate(("/", "/usr", "/proc", "/input", "/scratch"), 1):
        option = "rw" if path == "/scratch" else "ro"
        rows.append(f"{index} 0 0:1 / {path} {option},nosuid - tmpfs tmpfs rw")
    mounts = reference.parse_mounts("\n".join(rows))
    assert reference.validate_mounts(mounts)
    mounts.extend(reference.parse_mounts("8 3 0:2 / /proc/hidden rw - tmpfs tmpfs rw"))
    assert not reference.validate_mounts(mounts)


@pytest.mark.parametrize("raw", ["max 1\nmax 2\n", "max -1\n", "max 1 extra\n"])
def test_ambiguous_or_invalid_controller_counters_are_refused(raw):
    with pytest.raises(ValueError):
        reference.parse_counters(raw)


def _unavailable_runner(tmp_path, monkeypatch):
    runner = object.__new__(reference.ReferenceRunner)
    runner.artifact_dir = tmp_path
    runner.manifest = {"available_for_probe": False}
    runner.manifest_sha256 = "a" * 64
    runner.host_tuple_digest = runner.manifest_sha256
    runner._started_ns = reference.time.monotonic_ns()
    runner._qualification_deadline_ns = runner._started_ns + reference.WINDOW_NS
    runner._ec2_run = None
    runner._admissions = 0
    runner._poisoned = False
    runner._nonces = set()
    runner._owned = {}
    runner._owned_seals = {}

    def never_launch(*_args, **_kwargs):
        pytest.fail("Unavailable profile reached a process or OS control")

    monkeypatch.setattr(reference.subprocess, "Popen", never_launch)
    monkeypatch.setattr(runner, "_prepare_case", never_launch)
    return runner


def test_failed_launch_consumes_original_admission_without_any_worker(tmp_path, monkeypatch):
    runner = _unavailable_runner(tmp_path, monkeypatch)
    for index in range(24):
        result = runner.run_probe("positive", (f"{index:032x}",))
        assert result["failure"] == "setup_refused"
        assert result["started"] is False and result["payload_started"] is False
        assert result["actual_exit_code"] is None
        assert result["host_facts"]["cgroup_before"] is None
    with pytest.raises(ValueError, match="budget exhausted"):
        runner.run_probe("positive", ("f" * 32,))
    assert runner._admissions == 24


@pytest.mark.parametrize(
    "name,args", [("shell", ("a" * 32,)), ("positive", ()), ("positive", ("../x",))]
)
def test_unrecognized_command_or_nonce_never_becomes_admission(tmp_path, monkeypatch, name, args):
    runner = _unavailable_runner(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        runner.run_probe(name, args)
    assert runner._admissions == 0 and not list(tmp_path.iterdir())


def test_fixed_original_window_and_uncertain_stop_prevent_new_admission(tmp_path, monkeypatch):
    runner = _unavailable_runner(tmp_path, monkeypatch)
    runner._poisoned = True
    with pytest.raises(ValueError, match="Unconfirmed"):
        runner.run_probe("positive", ("a" * 32,))
    runner._poisoned = False
    monkeypatch.setattr(
        reference.time, "monotonic_ns", lambda: runner._started_ns + reference.WINDOW_NS
    )
    with pytest.raises(ValueError, match="budget exhausted"):
        runner.run_probe("positive", ("b" * 32,))
    assert runner._admissions == 0


def test_changed_frozen_payload_bytes_are_refused_before_copy(tmp_path):
    payload = tmp_path / "payload.py"
    payload.write_bytes(b"fixed\n")
    runner = object.__new__(reference.ReferenceRunner)
    runner.manifest = {
        "binaries": {
            "payload": {"path": str(payload), "sha256": hashlib.sha256(b"fixed\n").hexdigest()}
        }
    }
    assert runner._frozen_bytes("payload") == b"fixed\n"
    payload.write_bytes(b"replacement\n")
    with pytest.raises(ValueError, match="frozen reference TCB"):
        runner._frozen_bytes("payload")


def _file_stat(size, **overrides):
    values = {
        "st_dev": 1,
        "st_ino": 2,
        "st_mode": stat.S_IFREG | 0o600,
        "st_uid": 61184,
        "st_gid": 61184,
        "st_nlink": 1,
        "st_size": size,
        "st_mtime_ns": 10,
        "st_ctime_ns": 11,
        "st_atime_ns": 12,
    }
    return SimpleNamespace(**(values | overrides))


@pytest.mark.parametrize(
    "path",
    [
        "/sys/module/apparmor/parameters/enabled",
        "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
        "/sys/kernel/security/apparmor/profiles",
        "/sys/kernel/security/apparmor/features/domain/version",
        "/sys/kernel/security/apparmor/policy/profiles/profile.1/name",
        "/sys/kernel/security/apparmor/policy/profiles/profile.1/profiles/child.2/attach",
        "/proc/self/attr/current",
        "/proc/self/status",
        "/proc/sys/kernel/random/boot_id",
    ],
)
def test_kernel_policy_size_exception_is_a_fixed_input_closure(path):
    assert reference._kernel_policy_input(reference.Path(path))


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/policy-setup.json",
        "/proc/sys/kernel/hostname",
        "/proc/self/fd/3/policy-setup.json",
        "/sys/kernel/security/apparmor/features",
        "/sys/kernel/security/apparmor/features/../profiles",
        "/sys/kernel/security/apparmor/policy/profiles/profile.1/hash",
        "/sys/kernel/security/apparmor/policy/profiles/profile.1/unexpected/child/name",
        "sys/module/apparmor/parameters/enabled",
    ],
)
def test_kernel_policy_size_exception_rejects_other_locators(path):
    assert not reference._kernel_policy_input(reference.Path(path))


def _stub_policy_read(monkeypatch, stats, raw=b"Y\n"):
    observations, chunks, closed = iter(stats), iter((raw, b"")), []
    monkeypatch.setattr(reference.os, "open", lambda *_args: 17)
    monkeypatch.setattr(reference.os, "fstat", lambda _fd: next(observations))
    monkeypatch.setattr(reference.os, "read", lambda *_args: next(chunks))
    monkeypatch.setattr(reference.os, "close", closed.append)
    monkeypatch.setattr(reference.time, "monotonic_ns", lambda: 1)
    return closed


def test_kernel_policy_read_uses_bounded_bytes_instead_of_virtual_size(monkeypatch):
    info = _file_stat(4096, st_uid=0)
    closed = _stub_policy_read(monkeypatch, (info, info))
    assert (
        reference._policy_read(reference.Path("/sys/module/apparmor/parameters/enabled"), 16, 2)
        == b"Y\n"
    )
    assert closed == [17]


def test_current_proc_label_accepts_kernel_defined_write_mode(monkeypatch):
    info = _file_stat(0, st_uid=0, st_mode=stat.S_IFREG | 0o666)
    closed = _stub_policy_read(monkeypatch, (info, info))
    assert reference._policy_read(reference.Path("/proc/self/attr/current"), 16, 2) == b"Y\n"
    assert closed == [17]


@pytest.mark.parametrize(
    "path",
    ["/tmp/policy-setup.json", "/sys/module/apparmor/parameters/enabled", "/proc/self/status"],
)
def test_other_policy_inputs_still_refuse_write_mode(monkeypatch, path):
    info = _file_stat(0, st_uid=0, st_mode=stat.S_IFREG | 0o666)
    closed = _stub_policy_read(monkeypatch, (info,))
    with pytest.raises(ValueError, match="root-owned regular input"):
        reference._policy_read(reference.Path(path), 16, 2)
    assert closed == [17]


@pytest.mark.parametrize("size", [0, 4096])
def test_disk_policy_read_keeps_exact_size_requirement(monkeypatch, size):
    info = _file_stat(size, st_uid=0)
    closed = _stub_policy_read(monkeypatch, (info, info))
    with pytest.raises(ValueError, match="changed or exceeded"):
        reference._policy_read(reference.Path("/tmp/policy-setup.json"), 16, 2)
    assert closed == [17]


@pytest.mark.parametrize("changed", [{"st_ino": 9}, {"st_size": 99}, {"st_mtime_ns": 20}])
def test_kernel_policy_read_still_rejects_changed_identity(monkeypatch, changed):
    closed = _stub_policy_read(
        monkeypatch, (_file_stat(4096, st_uid=0), _file_stat(4096, st_uid=0, **changed))
    )
    with pytest.raises(ValueError, match="changed or exceeded"):
        reference._policy_read(reference.Path("/sys/module/apparmor/parameters/enabled"), 16, 2)
    assert closed == [17]


def test_kernel_policy_read_still_rejects_excess_actual_bytes(monkeypatch):
    info = _file_stat(4096, st_uid=0)
    closed = _stub_policy_read(monkeypatch, (info, info), b"Y" * 17)
    with pytest.raises(ValueError, match="changed or exceeded"):
        reference._policy_read(reference.Path("/sys/module/apparmor/parameters/enabled"), 16, 2)
    assert closed == [17]


def test_stopped_named_file_accepts_atime_only_change(tmp_path, monkeypatch):
    raw = b'{"nonce":"fixed"}\n'
    (tmp_path / "heartbeat").write_bytes(raw)
    observations = iter((_file_stat(len(raw)), _file_stat(len(raw), st_atime_ns=99)))
    monkeypatch.setattr(reference.os, "fstat", lambda _fd: next(observations))
    observed = reference._heartbeat(tmp_path)
    assert observed["text"] == raw.decode() and observed["size"] == len(raw)
    assert observed["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("changed", [{"st_ino": 9}, {"st_size": 99}, {"st_mtime_ns": 20}])
def test_stopped_named_file_refuses_identity_size_or_content_change(tmp_path, monkeypatch, changed):
    (tmp_path / "heartbeat").write_bytes(b"stable")
    observations = iter((_file_stat(6), _file_stat(6, **changed)))
    monkeypatch.setattr(reference.os, "fstat", lambda _fd: next(observations))
    observed = reference._heartbeat(tmp_path)
    assert observed["text"] is None and "changed" in observed["read_error"]


def test_named_file_never_follows_a_symlink(tmp_path):
    original = tmp_path / "original"
    original.write_text("protected")
    (tmp_path / "heartbeat").symlink_to(original)
    result = reference._heartbeat(tmp_path)
    assert result["text"] is None and result["read_error"]
    assert original.read_text() == "protected"


def test_public_evidence_mode_is_explicit_under_private_umask(tmp_path):
    previous = os.umask(0o077)
    try:
        target = tmp_path / "receipt.json"
        reference._write(target, b"{}\n")
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    with pytest.raises(FileExistsError):
        reference._write(target, b"replacement")


def _input_runner(tmp_path):
    payload = tmp_path / "frozen-payload.py"
    payload.write_bytes(b"fixed-payload\n")
    runner = object.__new__(reference.ReferenceRunner)
    runner.manifest = {
        "binaries": {
            "payload": {
                "path": str(payload),
                "sha256": hashlib.sha256(b"fixed-payload\n").hexdigest(),
            }
        }
    }
    return runner


def test_actual_case_input_is_guest_readable_under_private_umask(tmp_path):
    runner = _input_runner(tmp_path)
    setup = tmp_path / "owned-setup"
    setup.mkdir()
    setup.chmod(0o711)
    nonce = "a" * 32
    previous = os.umask(0o077)
    try:
        runner._prepare_input(setup, "positive", nonce)
        retained_umask = os.umask(0o077)
    finally:
        os.umask(previous)
    assert retained_umask == 0o077
    assert stat.S_IMODE(setup.stat().st_mode) == 0o711
    inputs = setup / "input"
    assert stat.S_IMODE(inputs.stat().st_mode) == 0o755
    assert inputs.stat().st_uid == setup.stat().st_uid
    assert {path.name for path in inputs.iterdir()} == {
        "payload.py",
        "immutable.txt",
        "probe-context.json",
    }
    for path in inputs.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
        assert path.stat().st_uid == setup.stat().st_uid
    assert (inputs / "payload.py").read_bytes() == b"fixed-payload\n"
    assert (inputs / "immutable.txt").read_bytes() == b"restricted-reference-immutable\n"
    assert json.loads((inputs / "probe-context.json").read_bytes()) == {
        "name": "positive",
        "nonce": nonce,
        "outside_path": str(setup / "outside-readable.txt"),
        "immutable_path": "/input/immutable.txt",
        "secret_env_keys": ["TICKWITNESS_REFERENCE_SECRET"],
        "fd_socket": 200,
        "fd_file": 201,
        "fd_canary_nonce": nonce,
    }


@pytest.mark.parametrize("symlink", [False, True])
def test_case_input_refuses_existing_or_symlink_directory_without_chmod(tmp_path, symlink):
    runner = _input_runner(tmp_path)
    setup = tmp_path / "owned-setup"
    setup.mkdir()
    target = tmp_path / "foreign" if symlink else setup / "input"
    target.mkdir()
    target.chmod(0o700)
    marker = target / "retained"
    marker.write_bytes(b"untouched")
    marker.chmod(0o600)
    if symlink:
        (setup / "input").symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        runner._prepare_input(setup, "positive", "a" * 32)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert marker.read_bytes() == b"untouched"
    assert {path.name for path in target.iterdir()} == {"retained"}
    assert (setup / "input").is_symlink() is symlink


def test_failed_member_diagnostic_does_not_suppress_owned_stop(monkeypatch, tmp_path):
    runner = object.__new__(reference.ReferenceRunner)
    attempted = []

    def broken_observation(*_args):
        raise OSError("controlled observation failure")

    monkeypatch.setattr(runner, "_record_members", broken_observation)
    monkeypatch.setattr(
        runner, "_stop", lambda leaf, process, end: attempted.append((leaf, end)) or True
    )
    facts, result = {}, {"failure": None}
    assert runner._attempt_owned_stop(tmp_path, None, facts, result, 2)
    assert attempted == [(tmp_path, 2)] and result["failure"] == "host_observation_failed"
    assert facts["member_observation_error"]


def test_replaced_cgroup_identity_is_not_killed(monkeypatch, tmp_path):
    runner = object.__new__(reference.ReferenceRunner)
    nonce = "a" * 32
    runner._owned = {nonce: (tmp_path, tmp_path)}
    runner._owned_seals = {nonce: {"cgroup": {"device": 1, "inode": 2}}}
    kill = tmp_path / "cgroup.kill"
    kill.write_text("")
    monkeypatch.setattr(reference, "_path_identity", lambda _path: {"device": 1, "inode": 9})
    with pytest.raises(ValueError, match="no kill was issued"):
        runner._stop(tmp_path, None, 2)
    assert kill.read_text() == ""


def test_unconfirmed_stop_never_unmounts_or_removes_owned_scratch(monkeypatch, tmp_path):
    runner = object.__new__(reference.ReferenceRunner)
    nonce = "a" * 32
    runner._owned = {nonce: (tmp_path, tmp_path)}
    runner._owned_seals = {nonce: {}}
    retained = tmp_path / "retained"
    retained.write_text("original")

    def never_unmount(_path):
        pytest.fail("Unconfirmed stop reached an unmount")

    monkeypatch.setattr(reference, "_unmount", never_unmount)
    with pytest.raises(ValueError, match="confirmed-stop"):
        runner._cleanup(nonce, {"scratch_mounted": True})
    assert retained.read_text() == "original" and nonce in runner._owned


@pytest.mark.parametrize("late_stage", ["counter_read", "wait"])
def test_stop_cannot_confirm_after_original_deadline(monkeypatch, tmp_path, late_stage):
    runner = object.__new__(reference.ReferenceRunner)
    nonce = "a" * 32
    seal = {"device": 1, "inode": 2}
    runner._owned = {nonce: (tmp_path, tmp_path)}
    runner._owned_seals = {nonce: {"cgroup": seal}}
    (tmp_path / "cgroup.kill").write_text("")
    (tmp_path / "cgroup.events").write_text("populated 0\n")
    (tmp_path / "cgroup.procs").write_text("")
    monkeypatch.setattr(reference, "_path_identity", lambda _path: seal)
    clock = iter((1, 11) if late_stage == "counter_read" else (1, 2, 3, 11))
    monkeypatch.setattr(reference.time, "monotonic_ns", lambda: next(clock))
    waits = []
    process = SimpleNamespace(wait=lambda timeout: waits.append(timeout))
    assert runner._stop(tmp_path, process, 10) is False
    assert (tmp_path / "cgroup.kill").read_text() == "1"
    assert bool(waits) is (late_stage == "wait")


def _policy_receipt():
    identities = {}
    for key, path in reference._POLICY_IDENTITIES.items():
        identities[key] = {
            "path": str(path),
            "realpath": str(path),
            "exists": True,
            "sha256": "b" * 64,
            "bytes": 1024,
            "uid": 0,
            "gid": 0,
            "mode": 0o755,
            "device": 1,
            "inode": 2,
            "mtime_ns": 3,
            "ctime_ns": 4,
        }
    config = reference._POLICY_IDENTITIES["parser_config"]
    identities["parser_config"] = {
        "path": str(config),
        "realpath": None,
        "exists": False,
        "sha256": None,
        "bytes": None,
        "reason": "not_present",
    }
    policy = {
        "path": str(reference._STAGED_POLICY),
        "sha256": reference.POLICY_SHA256,
        "bytes": 111,
    }
    files = [
        {
            "path": "/sys/kernel/security/apparmor/features/domain/version",
            "relative_path": "domain/version",
            "sha256": "c" * 64,
            "bytes": 1,
        }
    ]
    features = {"files": files, "canonical_sha256": reference._sha(reference._canonical(files))}
    parser = str(reference._POLICY_IDENTITIES["parser"])
    argv = [parser, "--add", "--skip-cache", "--base=/etc/apparmor.d", policy["path"]]
    commands = []
    for index, command in enumerate(
        (
            [parser, "--skip-cache", "--version"],
            [
                "/usr/bin/dpkg-query",
                "--show",
                "--showformat=${binary:Package}\t${Version}\t${Status}\n",
                "apparmor",
                "libapparmor1",
                "bubblewrap",
            ],
            argv,
        )
    ):
        commands.append(
            {
                "argv": command,
                "started": True,
                "returncode": 0,
                "stop_confirmed": True,
                "timed_out": False,
                "overflow": None,
                "exception": None,
                "started_monotonic_ns": 10 + index,
                "finished_monotonic_ns": 20 + index,
                "original_deadline_ns": 30000000010,
                "stdout_bytes": 0,
                "stderr_bytes": 0,
            }
        )
    selected = {"name": reference.PROFILE_NAME, "mode": "unconfined"}
    loader = {
        **commands[2],
        "commands": commands,
        "original_started_ns": 10,
        "original_deadline_ns": 30000000010,
        "bounds": {"window_ns": 30000000000, "max_commands": 3, "per_stream_bytes": 65536},
        "attachments_before": [],
        "attachments_after": [{**selected, "attachment": "/usr/bin/bwrap"}],
        "parser_configuration_guard": reference.parser_configuration_guard(None),
    }
    report = {
        "kind": "restricted_reference_policy_setup_v1",
        "schema_version": 1,
        "status": "LOADED_REFERENCE_ONLY",
        "profile_name": reference.PROFILE_NAME,
        "attachment": "/usr/bin/bwrap",
        "mode": "unconfined",
        "policy": policy,
        "identities": identities,
        "features": features,
        "loader": loader,
        "loaded_profiles_before": [],
        "loaded_profiles_after": [selected],
        "restrict_before": "1",
        "restrict_after": "1",
        "source_revision": "d" * 40,
        "preload_manifest_sha256": "e" * 64,
    }
    preload = {
        key: copy.deepcopy(report[key])
        for key in (
            "policy",
            "identities",
            "features",
            "source_revision",
            "loaded_profiles_before",
            "restrict_before",
        )
    }
    preload.update(
        {
            "kind": "restricted_reference_policy_preload_v1",
            "schema_version": 1,
            "parser_argv": argv,
            "attachments_before": [],
            "parser_configuration_guard": reference.parser_configuration_guard(None),
        }
    )
    return report, preload


def test_selected_loader_receipt_is_structural_evidence_not_product_admission():
    report, preload = _policy_receipt()
    reference.validate_policy_setup(report, preload)
    assert report["status"] == "LOADED_REFERENCE_ONLY" and report["mode"] == "unconfined"


@pytest.mark.parametrize(
    "change",
    [
        {"status": "UNKNOWN"},
        {"mode": "enforce"},
        {"attachment": "/usr/bin/*"},
        {"restrict_after": "0"},
        {"profile_name": "other"},
        {"unexpected_permission": True},
    ],
)
def test_unknown_or_broadened_policy_receipts_never_authorize_probe(change):
    report, preload = _policy_receipt()
    report.update(change)
    with pytest.raises(ValueError):
        reference.validate_policy_setup(report, preload)


def test_policy_setup_cannot_claim_replacement_or_cache_based_load():
    report, preload = _policy_receipt()
    report["loaded_profiles_before"] = copy.deepcopy(report["loaded_profiles_after"])
    with pytest.raises(ValueError, match="reused/replaced"):
        reference.validate_policy_setup(report, preload)
    report, preload = _policy_receipt()
    report["loader"]["argv"] = ["/usr/sbin/apparmor_parser", "--replace", "/tmp/other"]
    with pytest.raises(ValueError, match="command/window"):
        reference.validate_policy_setup(report, preload)


def test_unknown_or_late_setup_command_cannot_be_hidden_by_success_status():
    report, preload = _policy_receipt()
    report["loader"]["commands"][0]["finished_monotonic_ns"] = 30000000011
    with pytest.raises(ValueError, match="failed, unknown or late"):
        reference.validate_policy_setup(report, preload)


@pytest.mark.parametrize(
    "raw",
    [
        b"Include /tmp/other",
        b"base=/tmp",
        b"namespace other",
        b"features-file=/tmp/a",
        b"write-cache\nwrite-cache\n",
        b"abi=/tmp/other",
        b"\xff",
    ],
)
def test_parser_redirection_and_unknown_configuration_are_refused(raw):
    with pytest.raises(ValueError):
        reference.parser_configuration_guard(raw)


def test_absent_configuration_is_distinct_from_present_empty_configuration():
    absent = reference.parser_configuration_guard(None)
    empty = reference.parser_configuration_guard(b"")
    assert absent["exists"] is False and absent["source_sha256"] is None
    assert empty["exists"] is True and empty["source_sha256"] == hashlib.sha256(b"").hexdigest()
    accepted = reference.parser_configuration_guard(b"# fixed comment\nwrite-cache\n")
    assert accepted["allowed_options"] == ["write-cache"]


def test_current_policy_tuple_change_refuses_before_any_child(monkeypatch):
    runner = object.__new__(reference.ReferenceRunner)
    runner.manifest = {"binaries": {}, "explicit_userns_authorization": {"report_sha256": "a"}}
    monkeypatch.setattr(runner, "_capture_policy", lambda: {"report_sha256": "b"})
    with pytest.raises(ValueError, match="explicit policy/control tuple changed"):
        runner._unchanged_tuple()


def test_unknown_identity_types_do_not_equal_valid_numeric_or_boolean_proof():
    report, preload = _policy_receipt()
    report["identities"]["libapparmor"]["exists"] = 1
    with pytest.raises(ValueError, match="schema differs"):
        reference.validate_policy_setup(report, preload)


@pytest.mark.parametrize("label,nnp", [("unconfined", 1), ("other (enforce)", 0)])
def test_profile_transition_rejects_incompatible_state_before_loading_library(
    monkeypatch, label, nnp
):
    def fake_path(value):
        content = label if str(value).endswith("current") else f"NoNewPrivs:\t{nnp}\n"
        return SimpleNamespace(read_text=lambda: content)

    def never_load(*_args, **_kwargs):
        pytest.fail("Incompatible pre-NNP state reached a library transition")

    monkeypatch.setattr(bootstrap, "Path", fake_path)
    monkeypatch.setattr(bootstrap.ctypes, "CDLL", never_load)
    with pytest.raises(ValueError, match="pre-NNP"):
        bootstrap._enter_profile("a" * 64, 1)


def test_policy_evidence_cannot_select_an_arbitrary_path():
    with pytest.raises(ValueError, match="fixed closure"):
        reference._policy_document("../../other", 1)


def _ec2_policy_receipt():
    report, preload = _policy_receipt()
    run = object.__new__(Ec2Run)
    run.staged_policy = reference.Path(
        "/var/lib/tickwitness-reference-ec2/runs/" + "a" * 32 + "/policy.apparmor"
    )
    run.started_ns = 10
    run.setup_deadline_ns = 30_000_000_010
    run.source_revision = report["source_revision"]
    run.run_id = "a" * 32
    run.boot_id = "11111111-1111-1111-1111-111111111111"
    run.run_dir = run.staged_policy.parent
    run._host = {
        "system": "Linux",
        "release": "fixture-release",
        "version": "fixture-version",
        "architecture": "x86_64",
        "os_release": {"ID": "ubuntu", "VERSION_ID": "24.04"},
        "boot_id": run.boot_id,
        "controller_uid": 0,
        "controller_gid": 0,
        "controller_label": "unconfined",
    }
    records = {}
    run._seals = {}
    for field, path in (
        ("provider_source", ec2.SOURCE_ROOT / ec2.SOURCE_FILES[0]),
        ("source_lock", ec2.ROOT / "sources" / run.source_revision / "source-lock.json"),
        ("identity_document", run.run_dir / "instance-identity-document.json"),
    ):
        item = {"path": str(path), "sha256": "f" * 64, "bytes": 1}
        records[field] = item
        run._seals[str(path)] = (item, (1, 2, 0, 0o600, 1))
    run._state = {
        "provider_context": {
            "kind": "restricted_reference_ec2_host_v1",
            "schema_version": 1,
            "provider": reference.EC2_FAMILY,
            "source_revision": run.source_revision,
            "expected_identity": dict(ec2.EXPECTED_IDENTITY),
            "observed_identity": dict(ec2.EXPECTED_IDENTITY),
            "run_id": run.run_id,
            "boot_id": run.boot_id,
            "host": run._host,
            "gha_metadata": None,
            "gha_metadata_reason": "not_applicable_aws_ec2",
            **records,
        }
    }
    report.update(
        kind="restricted_reference_ec2_policy_setup_v1",
        profile_name=reference.EC2_PROFILE_NAME,
        attachment=None,
        provider_context=copy.deepcopy(run.provider_record),
    )
    preload.update(
        kind="restricted_reference_ec2_policy_preload_v1",
        provider_context=copy.deepcopy(run.provider_record),
    )
    for document in (report, preload):
        document["policy"].update(path=str(run.staged_policy), sha256=reference.EC2_POLICY_SHA256)
    selected = {"name": reference.EC2_PROFILE_NAME, "mode": "unconfined"}
    report["loaded_profiles_after"] = [selected]
    loader = report["loader"]
    loader["argv"][-1] = str(run.staged_policy)
    preload["parser_argv"][-1] = str(run.staged_policy)
    loader["attachments_after"] = [{**selected, "attachment": reference.EC2_PROFILE_NAME}]
    loader["provider_context"] = copy.deepcopy(run.provider_record)
    loader["manual_attachment_observation"] = {
        "raw": reference.EC2_PROFILE_NAME,
        "interpretation": "kernel_profile_name_fallback_no_exec_attachment",
    }
    return report, preload, run


def test_ec2_receipt_is_a_separate_family_and_preserves_opaque_foreign_state():
    report, preload, run = _ec2_policy_receipt()
    foreign = {"name": "opaque-foreign", "mode": "unconfined"}
    attachment = {**foreign, "attachment": "<unknown>"}
    report["loaded_profiles_before"] = [foreign]
    report["loaded_profiles_after"].insert(0, foreign)
    preload["loaded_profiles_before"] = copy.deepcopy(report["loaded_profiles_before"])
    report["loader"]["attachments_before"] = [attachment]
    report["loader"]["attachments_after"].insert(0, attachment)
    preload["attachments_before"] = [attachment]
    reference.validate_policy_setup(report, preload, ec2_run=run)
    assert attachment["attachment"] == "<unknown>"
    with pytest.raises(ValueError):
        reference.validate_policy_setup(report, preload)


@pytest.fixture
def manifest_context(monkeypatch):
    run = object.__new__(Ec2Run)
    context = {
        "kind": "restricted_reference_ec2_recovery_context_v1",
        "schema_version": 1,
        "plan_id": "ec2-recovery-20261126-v1",
        "fixture_scope": "metadata decisions, not recovery authority",
    }
    active_context = [context]
    snapshot = [ec2.BudgetSnapshot(10, 600_000_000_010, 24, 0, 0, 0, False, 0)]
    calls = []
    provider = {"kind": "fixture-provider", "recovery_context": context}
    monkeypatch.setattr(Ec2Run, "provider_record", property(lambda _run: copy.deepcopy(provider)))
    monkeypatch.setattr(
        Ec2Run, "recovery_context", property(lambda _run: copy.deepcopy(active_context[0]))
    )

    def current_snapshot(_run):
        calls.append("snapshot")
        return snapshot[0]

    def accounting(_run, observed):
        assert observed == snapshot[0]
        calls.append("accounting")
        return {
            "kind": "restricted_reference_ec2_recovery_budget_v1",
            "schema_version": 1,
            "prior_charged": 1,
            "current_charged": observed.charged,
            "cumulative_charged": 1 + observed.charged,
        }

    monkeypatch.setattr(Ec2Run, "snapshot", current_snapshot)
    monkeypatch.setattr(Ec2Run, "recovery_accounting", accounting)
    runner = object.__new__(reference.ReferenceRunner)
    runner._ec2_run = run
    runner._started_ns = snapshot[0].started_ns
    runner._qualification_deadline_ns = snapshot[0].deadline_ns
    return SimpleNamespace(
        runner=runner,
        context=context,
        active_context=active_context,
        provider=provider,
        snapshot=snapshot,
        calls=calls,
    )


def test_actual_manifest_context_binds_pre_probe_recovery_counts_without_later_rewrite(
    manifest_context,
):
    fixture = manifest_context
    result = fixture.runner._manifest_context()
    assert result["kind"] == "restricted_reference_ec2_recovery_manifest_v1"
    assert result["schema_version"] == 1
    assert result["provider_context"] == fixture.provider
    assert result["recovery_context"] == fixture.context
    assert result["recovery_accounting_phase"] == "pre_probe_manifest"
    assert result["recovery_accounting"]["current_charged"] == 0
    assert result["recovery_accounting"]["cumulative_charged"] == 1
    assert result["qualification_started_ns"] == fixture.snapshot[0].started_ns
    assert result["qualification_deadline_ns"] == fixture.snapshot[0].deadline_ns
    fixture.snapshot[0] = dataclasses.replace(fixture.snapshot[0], charged=1)
    assert result["recovery_accounting"]["current_charged"] == 0
    with pytest.raises(ValueError, match="pre-probe"):
        fixture.runner._manifest_context()


def test_actual_recovery_manifest_producer_matches_declared_full_top_level_shape(
    manifest_context,
    monkeypatch,
    tmp_path,
):
    """Exercise the real producer with unsupported synthetic metadata, never a probe."""
    fixture = manifest_context
    fixture.runner.payload = tmp_path / "metadata-only-payload.py"
    fixture.runner.payload.write_bytes(b"metadata fixture; never executed\n")
    fixture.runner._ec2_run.source_revision = "a" * 40
    monkeypatch.setattr(reference.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(reference.sys, "platform", "unsupported-metadata-fixture")
    monkeypatch.setattr(reference.platform, "machine", lambda: "metadata-fixture-architecture")
    monkeypatch.setattr(
        reference.platform,
        "uname",
        lambda: SimpleNamespace(_asdict=lambda: {"system": "synthetic-metadata"}),
    )
    monkeypatch.setattr(reference.platform, "libc_ver", lambda: ("fixture-libc", "fixture-version"))
    monkeypatch.setattr(reference, "_BWRAP", tmp_path / "absent-metadata-bwrap")
    monkeypatch.setattr(reference, "_CGROUP_ROOT", tmp_path / "absent-metadata-cgroup")
    monkeypatch.setattr(
        reference,
        "_identity",
        lambda path: {"path": str(path), "sha256": "a" * 64, "bytes": 1},
    )
    monkeypatch.setattr(
        fixture.runner,
        "_capture_policy",
        lambda: {"fixture_scope": "Readonly producer metadata; no policy or host qualification"},
    )

    def forbid_process(*_args, **_kwargs):
        pytest.fail("Manifest schema regression must not execute a process")

    monkeypatch.setattr(reference.subprocess, "run", forbid_process)
    monkeypatch.setattr(reference.subprocess, "Popen", forbid_process)
    manifest = fixture.runner._capture_manifest()
    assert set(manifest) == ec2.RECOVERY_MANIFEST_KEYS
    assert ec2.validate_recovery_manifest_shape(manifest) == manifest
    assert manifest["available_for_probe"] is False
    assert manifest["recovery_accounting"]["current_charged"] == 0
    assert manifest["recovery_accounting"]["cumulative_charged"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"charged": 1},
        {"backend_confirmed": 1},
        {"unconfirmed": 1},
        {"pending_outcomes": 1},
        {"poisoned": True},
    ],
)
def test_recovery_manifest_refuses_a_consumed_or_uncertain_initial_snapshot(
    manifest_context, changes
):
    fixture = manifest_context
    fixture.snapshot[0] = dataclasses.replace(fixture.snapshot[0], **changes)
    with pytest.raises(ValueError, match="pre-probe"):
        fixture.runner._manifest_context()
    assert fixture.calls == ["snapshot"]


def test_default_ec2_and_gha_manifest_contexts_do_not_gain_recovery_fields(manifest_context):
    fixture = manifest_context
    fixture.active_context[0] = None
    fixture.provider.clear()
    fixture.provider.update(kind="fixture-default-provider")
    assert fixture.runner._manifest_context() == {
        "kind": "restricted_reference_ec2_manifest_v1",
        "schema_version": 1,
        "provider_context": fixture.provider,
        "qualification_started_ns": fixture.snapshot[0].started_ns,
        "qualification_deadline_ns": fixture.snapshot[0].deadline_ns,
    }
    assert fixture.calls == []
    fixture.runner._ec2_run = None
    assert fixture.runner._manifest_context() == {"kind": "restricted_reference_manifest_v1"}


def test_unowned_manifest_metadata_cannot_read_caller_properties():
    class Duck:
        def __getattribute__(self, name):
            pytest.fail("Unowned manifest properties were accessed: " + name)

    runner = object.__new__(reference.ReferenceRunner)
    runner._ec2_run = Duck()
    with pytest.raises(ValueError, match="Actual"):
        runner._manifest_context()


@pytest.mark.parametrize("raw", ["", "<unknown>", "/usr/bin/bwrap", "/usr/*", "other"])
def test_ec2_selected_profile_cannot_hide_opaque_or_executable_attachment(raw):
    report, preload, run = _ec2_policy_receipt()
    report["loader"]["attachments_after"][0]["attachment"] = raw
    with pytest.raises(ValueError, match="attachment"):
        reference.validate_policy_setup(report, preload, ec2_run=run)


@pytest.mark.parametrize("document", ["report", "preload", "loader"])
def test_ec2_policy_provider_bindings_cannot_change_between_receipts(document):
    report, preload, run = _ec2_policy_receipt()
    selected = {"report": report, "preload": preload, "loader": report["loader"]}[document]
    selected["provider_context"]["run_id"] = "b" * 32
    with pytest.raises(ValueError, match="provider bindings"):
        reference.validate_policy_setup(report, preload, ec2_run=run)


def test_ec2_setup_cannot_receive_a_fresh_window_after_claim():
    report, preload, run = _ec2_policy_receipt()
    run.started_ns -= 1
    run.setup_deadline_ns -= 1
    with pytest.raises(ValueError, match="original claimed window"):
        reference.validate_policy_setup(report, preload, ec2_run=run)


@pytest.mark.parametrize("family", ["other", "tickwitness-reference-ec2", {}, False, 1])
def test_bootstrap_family_cannot_select_an_arbitrary_profile_or_pin(family):
    with pytest.raises(ValueError, match="fixed reference policy family"):
        bootstrap._policy_selection(family)


def test_bootstrap_has_only_two_source_pinned_reference_selections():
    assert bootstrap._policy_selection() == (
        reference.PROFILE_NAME.encode(),
        reference.EXPECTED_LABEL,
        reference.POLICY_SHA256,
    )
    assert bootstrap._policy_selection(reference.EC2_FAMILY) == (
        reference.EC2_PROFILE_NAME.encode(),
        reference.EC2_PROFILE_NAME + " (unconfined)",
        reference.EC2_POLICY_SHA256,
    )


def _ec2_unavailable_runner(tmp_path, monkeypatch):
    runner = _unavailable_runner(tmp_path, monkeypatch)
    admitted = runner._started_ns + 1
    ticket = ProbeAdmission(
        "a" * 32,
        "b" * 36,
        "c" * 40,
        1,
        "positive",
        "d" * 32,
        admitted,
        admitted + reference.WALL_NS,
    )
    accepted, outcomes = [], []
    runner._ec2_run = SimpleNamespace(
        run_id=ticket.run_id,
        boot_id=ticket.boot_id,
        source_revision=ticket.source_revision,
        admit_probe=accepted.append,
        finish_probe=lambda admission, **outcome: outcomes.append((admission, outcome)),
    )
    return runner, ticket, accepted, outcomes


def test_ec2_backend_uses_durable_original_ticket_without_a_second_charge(tmp_path, monkeypatch):
    runner, ticket, accepted, outcomes = _ec2_unavailable_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(reference.time, "monotonic_ns", lambda: ticket.admitted_ns + 2_000_000_000)
    result = runner.run_probe("positive", (ticket.nonce,), ec2_admission=ticket)
    assert accepted == [ticket] and runner._admissions == 1
    assert result["host_facts"]["original_admission_ns"] == ticket.admitted_ns
    assert result["host_facts"]["original_deadline_ns"] == ticket.deadline_ns
    raw = (tmp_path / ("positive-" + ticket.nonce + ".json")).read_bytes()
    assert outcomes == [
        (
            ticket,
            {
                "result_sha256": hashlib.sha256(raw).hexdigest(),
                "stop_confirmed": False,
                "cleanup_confirmed": False,
                "failure": "setup_refused",
            },
        )
    ]
    assert runner._poisoned is True


@pytest.mark.parametrize(
    "change",
    [
        {"name": "identity"},
        {"nonce": "e" * 32},
        {"run_id": "e" * 32},
        {"boot_id": "e" * 36},
        {"source_revision": "e" * 40},
        {"admission_number": 2},
        {"deadline_ns": 1},
    ],
)
def test_ec2_backend_rejects_mismatched_or_renewed_ticket_before_acceptance(
    tmp_path, monkeypatch, change
):
    runner, ticket, accepted, outcomes = _ec2_unavailable_runner(tmp_path, monkeypatch)
    altered = dataclasses.replace(ticket, **change)
    with pytest.raises(ValueError, match="durable EC2 admission"):
        runner.run_probe("positive", (ticket.nonce,), ec2_admission=altered)
    assert accepted == [] and outcomes == [] and runner._admissions == 0
    assert not list(tmp_path.iterdir())


def test_ec2_backend_requires_ticket_and_gha_cannot_accept_it(tmp_path, monkeypatch):
    runner, ticket, accepted, outcomes = _ec2_unavailable_runner(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="durable EC2 admission"):
        runner.run_probe("positive", (ticket.nonce,))
    runner._ec2_run = None
    with pytest.raises(ValueError, match="GHA reference family"):
        runner.run_probe("positive", (ticket.nonce,), ec2_admission=ticket)
    assert accepted == [] and outcomes == [] and runner._admissions == 0


def test_ec2_result_write_failure_preserves_accepted_pending_charge(tmp_path, monkeypatch):
    runner, ticket, accepted, outcomes = _ec2_unavailable_runner(tmp_path, monkeypatch)
    original_write = reference._write

    def fail_final_receipt(path, raw, *, durable=False):
        if path.suffix == ".json":
            raise OSError("injected final receipt write failure")
        original_write(path, raw, durable=durable)

    monkeypatch.setattr(reference, "_write", fail_final_receipt)
    with pytest.raises(OSError, match="final receipt"):
        runner.run_probe("positive", (ticket.nonce,), ec2_admission=ticket)
    assert accepted == [ticket] and runner._admissions == 1
    assert outcomes == []
    assert not (tmp_path / ("positive-" + ticket.nonce + ".json")).exists()


def test_ec2_per_probe_tuple_readback_keeps_original_ticket_deadline(monkeypatch):
    runner = object.__new__(reference.ReferenceRunner)
    expected = {"report_sha256": "a"}
    runner.manifest = {"binaries": {}, "explicit_userns_authorization": expected}
    deadlines = []

    def capture(*, deadline_ns=None):
        deadlines.append(deadline_ns)
        return expected

    monkeypatch.setattr(runner, "_capture_policy", capture)
    runner._unchanged_tuple(deadline_ns=123)
    assert deadlines == [123]


def test_ec2_constructor_rejects_duck_authority_before_access_or_creation(tmp_path):
    class FakeRun:
        def __getattr__(self, _name):
            pytest.fail("Unrecognized authority was inspected or acquired")

    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="Actual closed EC2 run authority"):
        reference.ReferenceRunner(output, tmp_path / "payload.py", ec2_run=FakeRun())
    assert not output.exists()
    with pytest.raises(ValueError, match="Actual closed EC2 run authority"):
        reference.validate_policy_setup({}, {}, ec2_run=FakeRun())
