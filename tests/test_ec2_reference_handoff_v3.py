"""Actual ready/ACK/cancel/export producers, with inert private files and OS ports."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/ec2_reference_handoff_v3.py"
SPEC = importlib.util.spec_from_file_location("ec2_handoff_v3_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ops = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ops
SPEC.loader.exec_module(ops)
SOURCE = "a" * 40
BOOT = "11111111-2222-3333-4444-555555555555"


class StopWait(Exception):
    pass


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(ops, "ROOT", tmp_path / "reference")
    parent = tmp_path / "operations"
    parent.mkdir(mode=0o700)
    store = ops.Store(
        parent / ops.RUN_ID, owner=os.getuid(), trust_root=tmp_path, archive_base=tmp_path
    )

    class Clock:
        value = 1_000_000_000

        def now(self):
            return self.value

        def sleep(self, seconds):
            self.value += max(1, int(seconds * 1e9))
            raise StopWait

    clock = Clock()

    class Host:
        guard = ops.GuardIdentity(
            "b" * 32,
            ops.ProcessIdentity(10, 100, ops.main_argv(SOURCE), "/system.slice/" + ops.UNIT, 1),
            "actual trusted ExecStart",
            "/system.slice/" + ops.UNIT,
        )
        stop_calls = 0
        live_calls = 0
        live_failure_after = None

        def boot(self):
            return BOOT

        def master(self, source):
            return ops.ProcessIdentity(20, 200, ops.controller_argv(source), self.guard.cgroup, 10)

        def live(self, source, start):
            self.live_calls += 1
            if self.live_failure_after is not None and self.live_calls > self.live_failure_after:
                raise ops.Refused("actual master/guard changed")
            assert source == SOURCE and start["controller_pid"] == 20
            return self.guard

        def stop(self, guard):
            assert guard == self.guard
            self.stop_calls += 1

    host = Host()
    controller = ops.Controller(SOURCE, store, host, None, clock)
    store.create_operation()
    master = host.master(SOURCE)
    controller.start = controller.base("controller-start") | {
        "controller_pid": master.pid,
        "controller_start_ticks": master.start_ticks,
        "controller_argv": master.argv,
        "started_ns": controller.started,
        "outer_deadline_ns": controller.deadline,
    }
    store.record("controller-start", controller.start, SOURCE, BOOT)

    def ready():
        store.write("evidence.tar.gz", b"actual already-published archive bytes")
        with pytest.raises(StopWait):
            controller.wait()
        return store.record_read("handoff-ready", SOURCE, BOOT)

    return SimpleNamespace(
        store=store, host=host, clock=clock, controller=controller, ready=ready, root=tmp_path
    )


def ack_input(ready):
    return {
        key: ready[key]
        for key in (
            "boot_id",
            "invocation_id",
            "main_pid",
            "controller_pid",
            "nonce",
            "bytes",
            "sha256",
        )
    }


def cancel_input(env):
    return {
        "boot_id": BOOT,
        "invocation_id": env.host.guard.invocation_id,
        "main_pid": env.host.guard.main.pid,
        "controller_pid": env.controller.start["controller_pid"],
    }


def original_files(store):
    return {
        path.name: (path.read_bytes(), ops.stat_record(path.stat()))
        for path in store.operation.iterdir()
    }


def overwrite(path, raw):
    path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(0o400)


def test_real_ready_producer_has_exact_fixed_shape_and_single_original_window(environment):
    env = environment
    ready = env.ready()
    assert set(ready) == ops.KEYS["handoff-ready"]
    assert set(ready["archive_stat"]) == ops.STAT_KEYS
    assert ready["controller_pid"] != ready["main_pid"]
    assert ready["controller_argv"] == ops.controller_argv(SOURCE)
    assert ready["main_argv"] == ops.main_argv(SOURCE)
    assert ready["deadline_ns"] == min(
        ready["started_ns"] + ops.HANDOFF_NS, env.controller.deadline
    )
    assert ready["sha256"] == hashlib.sha256(b"actual already-published archive bytes").hexdigest()
    assert ops.hex_string(ready["nonce"], 32)
    with pytest.raises(FileExistsError):
        env.controller.wait()
    assert env.store.record_read("handoff-ready", SOURCE, BOOT) == ready


def test_independent_ack_uses_target_cgroup_without_requiring_callers_membership(environment):
    env = environment
    ready = env.ready()
    # Host.live observes the target master/guard; the SSH helper has no caller-
    # cgroup API. A helper in another session can acknowledge this exact target.
    ops.acknowledge(SOURCE, env.store, env.host, env.clock, ack_input(ready))
    ack = env.store.record_read("handoff-ack", SOURCE, BOOT)
    assert set(ack) == ops.KEYS["handoff-ack"]
    assert {key: ack[key] for key in ack_input(ready)} == ack_input(ready)
    assert env.host.stop_calls == 0
    original = (env.store.operation / "handoff-ack.json").read_bytes()
    with pytest.raises(FileExistsError):
        ops.acknowledge(SOURCE, env.store, env.host, env.clock, ack_input(ready))
    assert (env.store.operation / "handoff-ack.json").read_bytes() == original


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("boot_id", "99999999-2222-3333-4444-555555555555"),
        ("invocation_id", "c" * 32),
        ("main_pid", 11),
        ("controller_pid", 21),
        ("nonce", "d" * 32),
        ("bytes", 1),
        ("sha256", "e" * 64),
        ("main_pid", True),
        ("controller_pid", 20.0),
        ("bytes", True),
        ("nonce", "D" * 32),
        ("sha256", "E" * 64),
    ],
)
def test_wrong_ack_is_zero_protocol_writes_and_zero_signals(environment, field, wrong):
    env = environment
    supplied = ack_input(env.ready())
    supplied[field] = wrong
    before = original_files(env.store)
    with pytest.raises(ops.Refused):
        ops.acknowledge(SOURCE, env.store, env.host, env.clock, supplied)
    assert original_files(env.store) == before
    assert env.host.stop_calls == 0


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("schema_version", True),
        ("schema_version", 3.0),
        ("controller_start_ticks", 201),
        ("main_start_ticks", 101),
        ("guard_exec_start", "different command"),
        ("guard_control_group", "/another-session"),
        ("source_revision", "c" * 40),
        ("run_id", ops.OLD_RUNS[-1]),
        ("controller_argv", ["wrong"]),
        ("main_argv", ["wrong"]),
        ("outer_deadline_ns", 1),
        ("deadline_ns", 2),
        ("unit", "another.service"),
        ("extra", "unknown"),
    ],
)
def test_tampered_ready_is_zero_ack_writes_and_zero_signals(environment, field, wrong):
    env = environment
    ready = env.ready()
    supplied = ack_input(ready)
    ready[field] = wrong
    overwrite(env.store.operation / "handoff-ready.json", ops.canonical(ready))
    before = original_files(env.store)
    with pytest.raises(ops.Refused):
        ops.acknowledge(SOURCE, env.store, env.host, env.clock, supplied)
    assert original_files(env.store) == before
    assert env.host.stop_calls == 0


@pytest.mark.parametrize("fault", ["missing", "partial", "bad_sha", "new_inode", "symlink"])
def test_archive_loss_or_changed_original_bytes_is_not_acknowledged(environment, fault):
    env = environment
    ready = env.ready()
    path = env.store.operation / "evidence.tar.gz"
    if fault == "missing":
        path.unlink()
    elif fault in ("partial", "bad_sha"):
        overwrite(path, b"x" if fault == "partial" else b"x" * ready["bytes"])
    elif fault == "new_inode":
        raw = path.read_bytes()
        path.rename(env.store.operation / "original-archive")
        path.write_bytes(raw)
    else:
        path.unlink()
        path.symlink_to(env.store.operation / "controller-start.json")
    with pytest.raises((ops.Refused, OSError)):
        ops.acknowledge(SOURCE, env.store, env.host, env.clock, ack_input(ready))
    assert not env.store.exists("handoff-ack.json")
    assert env.host.stop_calls == 0


def test_clock_exhaustion_during_hash_verification_has_zero_ack_writes(environment, monkeypatch):
    env = environment
    ready = env.ready()
    original = env.store.archive

    def expensive_verification():
        observed = original()
        env.clock.value = ready["deadline_ns"]
        return observed

    monkeypatch.setattr(env.store, "archive", expensive_verification)
    with pytest.raises(ops.Refused, match="expired"):
        ops.acknowledge(SOURCE, env.store, env.host, env.clock, ack_input(ready))
    assert not env.store.exists("handoff-ack.json")
    assert env.host.stop_calls == 0


@pytest.mark.parametrize(
    "raw",
    [b"{", b"{}", b"{}\n", b'{"x":NaN}\n', b'{"x":Infinity}\n', b'{"x":1,"x":1}\n', b"x" * 65537],
)
def test_strict_decoder_refuses_partial_noncanonical_duplicate_or_oversize(raw):
    if raw == b"{}\n":
        value = ops.decode(raw)
        with pytest.raises(ops.Refused, match="exact fields"):
            ops.validate_record(value, "handoff-ack", SOURCE, BOOT)
    else:
        with pytest.raises(ops.Refused):
            ops.decode(raw)


@pytest.mark.parametrize("fault", ["partial", "fsync"])
def test_partial_or_uncertain_ack_never_gets_overwritten(environment, monkeypatch, fault):
    env = environment
    ready = env.ready()
    if fault == "partial":
        env.store.write("handoff-ack.json", b"{")
        expected = FileExistsError
    else:
        monkeypatch.setattr(
            env.store,
            "fsync_directory",
            lambda _: (_ for _ in ()).throw(OSError("uncertain ACK directory fsync")),
        )
        expected = OSError
    with pytest.raises(expected):
        ops.acknowledge(SOURCE, env.store, env.host, env.clock, ack_input(ready))
    retained = (env.store.operation / "handoff-ack.json").read_bytes()
    with pytest.raises(FileExistsError):
        ops.acknowledge(SOURCE, env.store, env.host, env.clock, ack_input(ready))
    assert (env.store.operation / "handoff-ack.json").read_bytes() == retained


def test_cancel_before_ready_records_once_rechecks_guard_and_stops_original_unit(environment):
    env = environment
    assert not env.store.exists("handoff-ready.json")
    ops.cancel(SOURCE, env.store, env.host, env.clock, cancel_input(env))
    record = env.store.record_read("controller-cancel", SOURCE, BOOT)
    assert set(record) == ops.KEYS["controller-cancel"]
    assert record["controller_start_ticks"] == 200
    assert env.host.stop_calls == 1
    with pytest.raises(FileExistsError):
        ops.cancel(SOURCE, env.store, env.host, env.clock, cancel_input(env))
    assert env.host.stop_calls == 1


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("boot_id", "99999999-2222-3333-4444-555555555555"),
        ("invocation_id", "c" * 32),
        ("main_pid", 11),
        ("controller_pid", 21),
        ("main_pid", True),
        ("controller_pid", 20.0),
        ("extra", 0),
    ],
)
def test_bad_cancel_before_ready_is_zero_write_zero_signal(environment, field, wrong):
    env = environment
    supplied = cancel_input(env)
    supplied[field] = wrong
    before = original_files(env.store)
    with pytest.raises(ops.Refused):
        ops.cancel(SOURCE, env.store, env.host, env.clock, supplied)
    assert original_files(env.store) == before
    assert env.host.stop_calls == 0


def test_pid_reuse_after_cancel_record_keeps_record_but_never_stops_new_guard(environment):
    env = environment
    env.host.live_failure_after = 2
    with pytest.raises(ops.Refused, match="changed"):
        ops.cancel(SOURCE, env.store, env.host, env.clock, cancel_input(env))
    assert env.store.exists("controller-cancel.json")
    assert env.host.stop_calls == 0


@pytest.mark.parametrize("action", ["ack", "cancel"])
@pytest.mark.parametrize("fault", ["expiry", "identity"])
def test_actual_store_metadata_consumes_original_deadline_before_exclusive_open(
    environment, monkeypatch, action, fault
):
    env = environment
    supplied = ack_input(env.ready()) if action == "ack" else cancel_input(env)
    deadline = (
        env.store.record_read("handoff-ready", SOURCE, BOOT)["deadline_ns"]
        if action == "ack"
        else env.controller.deadline
    )
    state = {"publishing": False}
    original_write = env.store.write
    original_ancestry = env.store.ancestry
    original_live = env.host.live

    def ancestry(path):
        original_ancestry(path)
        if state["publishing"] and path == env.store.operation and fault == "expiry":
            env.clock.value = deadline

    def live(source, start):
        if state["publishing"] and fault == "identity":
            raise ops.Refused("target identity changed during Store metadata")
        return original_live(source, start)

    def write(name, raw, mode=0o400, *, before_create=None):
        state["publishing"] = True
        try:
            original_write(name, raw, mode, before_create=before_create)
        finally:
            state["publishing"] = False

    monkeypatch.setattr(env.store, "ancestry", ancestry)
    monkeypatch.setattr(env.store, "write", write)
    monkeypatch.setattr(env.host, "live", live)
    before = original_files(env.store)
    operation = ops.acknowledge if action == "ack" else ops.cancel
    with pytest.raises(ops.Refused):
        operation(SOURCE, env.store, env.host, env.clock, supplied)
    assert original_files(env.store) == before
    assert env.host.stop_calls == 0


def protocol_record(env, name):
    if name == "controller-start":
        return copy.deepcopy(env.controller.start)
    if name == "qualifier-exit":
        return env.controller.base(name) | {"invoked": False, "returncode": None, "report": None}
    if name in ("export-call", "export-consumption"):
        return env.controller.base(name) | {
            "controller_pid": 20,
            "controller_start_ticks": 200,
            "started_ns": env.clock.now(),
        }
    if name == "controller-cancel":
        return (
            env.controller.base(name)
            | cancel_input(env)
            | {
                "controller_start_ticks": 200,
                "requested_ns": env.clock.now(),
            }
        )
    if name == "controller-result":
        return env.controller.base(name) | {
            "preparation_invoked": True,
            "preparation_returncode": 1,
            "qualifier_invoked": False,
            "qualifier_returncode": None,
            "export_invoked": True,
            "export_returncode": 0,
            "handoff_status": "acknowledged",
            "returncode": 74,
        }
    ready = env.ready()
    if name == "handoff-ready":
        return ready
    return env.controller.base(name) | ack_input(ready)


@pytest.mark.parametrize("name", list(ops.KEYS))
def test_every_operational_record_rejects_extra_missing_and_boolean_schema(environment, name):
    env = environment
    valid = protocol_record(env, name)
    ops.validate_record(valid, name, SOURCE, BOOT)
    missing = copy.deepcopy(valid)
    missing.pop("kind")
    for value in (
        valid | {"unexpected": 1},
        valid | {"schema_version": True},
        valid | {"schema_version": 3.0},
        missing,
    ):
        with pytest.raises(ops.Refused):
            ops.validate_record(value, name, SOURCE, BOOT)


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("invoked", 1),
        ("invoked", "false"),
        ("returncode", False),
        ("returncode", 0.0),
        ("returncode", 0),
    ],
)
def test_phase_record_rejects_false_zero_and_boolean_integer_ambiguity(environment, field, wrong):
    env = environment
    value = protocol_record(env, "qualifier-exit")
    value[field] = wrong
    with pytest.raises(ops.Refused):
        ops.validate_record(value, "qualifier-exit", SOURCE, BOOT)


@pytest.mark.parametrize("fault", ["wrong_parent", "wrong_cgroup", "wrong_argv", "future_call"])
def test_internal_export_rejects_non_child_or_wrong_identity_before_consumption(
    environment, monkeypatch, fault
):
    env = environment
    call = protocol_record(env, "export-call")
    if fault == "future_call":
        call["started_ns"] += 1
    env.store.record("export-call", call, SOURCE, BOOT)
    command = [
        "/usr/bin/python3",
        "-I",
        str(ops.STAGE / "ec2_reference_handoff_v3.py"),
        "internal-export",
        "--source-revision",
        SOURCE,
        "--run-id",
        ops.RUN_ID,
    ]
    identity = ops.ProcessIdentity(
        os.getpid(),
        300,
        ["wrong"] if fault == "wrong_argv" else command,
        "/another-session" if fault == "wrong_cgroup" else env.host.guard.cgroup,
        99 if fault == "wrong_parent" else 20,
    )
    monkeypatch.setattr(env.host, "process", lambda _: identity, raising=False)
    calls = []
    monkeypatch.setattr(ops, "export_archive", lambda *args: calls.append(args))
    with pytest.raises(ops.Refused):
        ops.internal_export(SOURCE, env.store, env.host, env.clock)
    assert not env.store.exists("export-consumption.json")
    assert calls == []


def test_internal_export_persists_consumption_before_one_export_and_never_retries(
    environment, monkeypatch
):
    env = environment
    env.store.record("export-call", protocol_record(env, "export-call"), SOURCE, BOOT)
    command = [
        "/usr/bin/python3",
        "-I",
        str(ops.STAGE / "ec2_reference_handoff_v3.py"),
        "internal-export",
        "--source-revision",
        SOURCE,
        "--run-id",
        ops.RUN_ID,
    ]
    identity = ops.ProcessIdentity(os.getpid(), 300, command, env.host.guard.cgroup, 20)
    monkeypatch.setattr(env.host, "process", lambda _: identity, raising=False)
    calls = []

    def exporter(source, store):
        record = store.record_read("export-consumption", source, BOOT)
        assert record["controller_pid"] == 20 and record["controller_start_ticks"] == 200
        calls.append(record)

    monkeypatch.setattr(ops, "export_archive", exporter)
    ops.internal_export(SOURCE, env.store, env.host, env.clock)
    with pytest.raises(FileExistsError):
        ops.internal_export(SOURCE, env.store, env.host, env.clock)
    assert len(calls) == 1


@pytest.mark.parametrize("form", [0, 1])
def test_ready_accepts_only_reviewed_complete_sudo_or_execed_timeout_guard(environment, form):
    env = environment
    command = ops.guard_commands(SOURCE)[form]
    main = ops.ProcessIdentity(10, 100, command, env.host.guard.cgroup, 1)
    env.host.guard = ops.GuardIdentity("b" * 32, main, "actual trusted ExecStart", main.cgroup)
    ready = env.ready()
    assert ready["main_argv"] == command
    ops.acknowledge(SOURCE, env.store, env.host, env.clock, ack_input(ready))


@pytest.mark.parametrize("change", ["atime", "mtime", "inode"])
def test_actual_stop_copy_ignores_only_atime_and_refuses_changed_mtime_or_inode(
    environment, monkeypatch, change
):
    env = environment
    source = env.root / "operator-stop.md"
    raw = b"owner Stop observation\n".ljust(1222, b" ")
    source.write_bytes(raw)
    monkeypatch.setattr(ops, "STOP_SHA", hashlib.sha256(raw).hexdigest())
    target = env.root / "new-authority" / "operator-stop.md"
    if change == "atime":
        # Set an old atime before the read's seal. utime itself also changes
        # ctime, whereas the subsequent real read may update only atime.
        os.utime(source, ns=(1, source.stat().st_mtime_ns))

    class ObservedStore(ops.Store):
        def read(self, path, limit=ops.JSON_LIMIT):
            value, seal = super().read(path, limit)
            if path == source:
                current = source.stat()
                if change == "mtime":
                    os.utime(source, ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000_000))
                elif change == "inode":
                    source.rename(env.root / "original-stop-inode")
                    source.write_bytes(value)
            return value, seal

    store = ObservedStore(
        env.store.operation, owner=os.getuid(), trust_root=env.root, archive_base=env.root
    )
    if change == "atime":
        original_atime = source.stat().st_atime_ns
        before = ops.stat_record(source.stat())
        ops.copy_stop_observation(source, target, store=store)
        assert target.read_bytes() == raw
        assert ops.stat_record(source.stat()) == before
        if source.stat().st_atime_ns != original_atime:
            # noatime mounts need not change it; when the producer does, the
            # original nine identity/content fields must still be unchanged.
            assert source.stat().st_atime_ns > original_atime
            assert ops.stat_record(source.stat()) == before
        assert target.stat().st_nlink == 1
        with pytest.raises(FileExistsError):
            ops.copy_stop_observation(source, target, store=store)
    else:
        with pytest.raises(ops.Refused, match="unstable"):
            ops.copy_stop_observation(source, target, store=store)
        assert not target.exists()


@pytest.mark.parametrize(
    ("form", "main_uid", "master_uid", "accepted"),
    [
        (0, 0, 0, True),
        (0, 1000, 0, True),
        (0, 61184, 0, False),
        (1, 0, 0, True),
        (1, 1000, 0, False),
        (1, 61184, 0, False),
        (0, 1000, 1000, False),
        (1, 0, 1000, False),
    ],
)
def test_actual_host_live_binds_sudo_monitor_owner_and_root_timeout_master(
    environment, monkeypatch, form, main_uid, master_uid, accepted
):
    env = environment
    host = ops.Host(env.store)
    cgroup = "/system.slice/" + ops.UNIT
    main = ops.ProcessIdentity(10, 100, ops.guard_commands(SOURCE)[form], cgroup, 1, main_uid)
    master = ops.ProcessIdentity(20, 200, ops.controller_argv(SOURCE), cgroup, 10, master_uid)
    record = {
        "ActiveState": "active",
        "SubState": "running",
        "InvocationID": "b" * 32,
        "MainPID": "10",
        "ExecStart": "{ path=/usr/bin/sudo ; argv[]="
        + " ".join(ops.main_argv(SOURCE))
        + " ; ignore_errors=no ; }",
        "ControlGroup": cgroup,
        "DropInPaths": "",
        "User": "ubuntu",
    }
    monkeypatch.setattr(host, "boot", lambda: BOOT)
    monkeypatch.setattr(host, "process", lambda pid: {10: main, 20: master}[pid])
    monkeypatch.setattr(host, "show", lambda unit, fields: copy.deepcopy(record))
    monkeypatch.setattr(ops.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1000))
    if accepted:
        guard = host.live(SOURCE, env.controller.start)
        assert guard.main.argv == main.argv and guard.main.effective_uid == main_uid
    else:
        with pytest.raises(ops.Refused):
            host.live(SOURCE, env.controller.start)


@pytest.mark.parametrize(
    "tampered", [None, "batch-source.sh", "preparer-source.sh", "handoff-source.py"]
)
def test_actual_source_binding_checks_retained_operation_copy_as_well_as_live_stage(
    environment, monkeypatch, tampered
):
    env = environment
    seed_history(env)
    stage = env.root / "stage"
    stage.mkdir(mode=0o700)
    selected = env.root / "selected"
    selected.mkdir(mode=0o700)
    monkeypatch.setattr(ops, "STAGE", stage)
    for filename, retained in (
        ("run_ec2_reference_recovery_v3.sh", "batch-source.sh"),
        ("provision_ec2_reference_source.sh", "preparer-source.sh"),
        ("ec2_reference_handoff_v3.py", "handoff-source.py"),
    ):
        raw = ("selected Git bytes: " + filename + "\n").encode()
        (stage / filename).write_bytes(raw)
        (selected / filename).write_bytes(raw)
        env.store.write(
            retained, b"different previously retained bytes" if retained == tampered else raw
        )
    original_read = env.store.read

    def read(path, limit=ops.JSON_LIMIT):
        prefix = Path("/opt/tickwitness-reference") / SOURCE / "scripts"
        if path.parent == prefix:
            return original_read(selected / path.name, limit)
        return original_read(path, limit)

    host = ops.Host(env.store)
    monkeypatch.setattr(env.store, "read", read)
    monkeypatch.setattr(host, "_controls", lambda: None)
    if tampered is None:
        host.after_preparation(SOURCE, env.store)
        assert env.store.exists("source-check.log")
    else:
        with pytest.raises(ops.Refused, match="Stage/operation script"):
            host.after_preparation(SOURCE, env.store)
        assert not env.store.exists("source-check.log")


def seed_history(env):
    for path in ops._history_roots():
        if path.suffix == ".json":
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(b'{"historical":"original raw bytes"}\n')
        else:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            (path / "original.json").write_bytes(b'{"original":1}\n')
    env.store.write("history-before.log", ops.canonical(ops.history_snapshot(env.store)))
    for name in ("qualifier-exit", "export-call", "export-consumption"):
        value = env.controller.base(name)
        if name == "qualifier-exit":
            value.update({"invoked": False, "returncode": None, "report": None})
        else:
            value.update(
                {"controller_pid": 20, "controller_start_ticks": 200, "started_ns": env.clock.now()}
            )
        env.store.record(name, value, SOURCE, BOOT)


def test_single_real_archive_contains_actual_history_and_marks_late_records_outside(environment):
    env = environment
    seed_history(env)
    before = ops.history_snapshot(env.store)
    ops.export_archive(SOURCE, env.store)
    seal, digest = env.store.archive()
    assert seal["nlink"] == 1 and 0 < seal["size"] <= ops.ARCHIVE_LIMIT
    assert not env.store.exists("archive.pending")
    assert ops.history_snapshot(env.store) == before
    raw = (env.store.operation / "evidence.tar.gz").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        inventory_stream = archive.extractfile("export-inventory.json")
        assert inventory_stream is not None
        inventory = json.load(inventory_stream)
        names = archive.getnames()
        assert all(item.isreg() for item in archive.getmembers())
        assert any(name.endswith("export-consumption.json") for name in names)
        assert any(name.endswith("qualifier-exit.json") for name in names)
        assert all(not name.endswith("handoff-ready.json") for name in names)
        assert str(env.store.operation / "controller-result.json") in inventory["inventory_only"]
        assert str(ops.ROOT / "runs" / ops.RUN_ID) in inventory["absent"]
    with pytest.raises(FileExistsError):
        ops.export_archive(SOURCE, env.store)
    assert (env.store.operation / "evidence.tar.gz").read_bytes() == raw


@pytest.mark.parametrize("fault", ["changed_history", "symlink", "hardlink", "partial_pending"])
def test_real_export_refuses_mutated_history_and_never_replaces_uncertain_pending(
    environment, fault
):
    env = environment
    seed_history(env)
    old = ops.ROOT / "host-admission.json"
    if fault == "changed_history":
        old.write_bytes(b"changed old bytes")
    elif fault == "symlink":
        old.unlink()
        old.symlink_to(ops.ROOT / "recovery-plan.json")
    elif fault == "hardlink":
        os.link(old, old.with_name("extra-hardlink"))
    else:
        env.store.write("archive.pending", b"uncertain original pending bytes")
    with pytest.raises((ops.Refused, OSError)):
        ops.export_archive(SOURCE, env.store)
    assert not env.store.exists("evidence.tar.gz")
    if fault == "partial_pending":
        assert (env.store.operation / "archive.pending").read_bytes() == (
            b"uncertain original pending bytes"
        )


@pytest.mark.parametrize("failure", ["fsync", "link"])
def test_export_publication_failure_retains_single_pending_without_retry(
    environment, monkeypatch, failure
):
    env = environment
    seed_history(env)
    if failure == "link":
        monkeypatch.setattr(
            ops.os,
            "link",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("exclusive publication failed")),
        )
    else:
        original = env.store.fsync_directory

        def fsync(path):
            if env.store.exists("archive.pending"):
                raise OSError("uncertain final directory fsync")
            original(path)

        monkeypatch.setattr(env.store, "fsync_directory", fsync)
    with pytest.raises(OSError):
        ops.export_archive(SOURCE, env.store)
    assert env.store.exists("archive.pending")
    retained = (env.store.operation / "archive.pending").read_bytes()
    with pytest.raises(FileExistsError):
        ops.export_archive(SOURCE, env.store)
    assert (env.store.operation / "archive.pending").read_bytes() == retained
