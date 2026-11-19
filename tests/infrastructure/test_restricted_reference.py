"""Data-only policy/admission regressions; no root, namespaces or actual attacks."""

import hashlib
import os
import stat
import struct
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import restricted_reference as reference


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
