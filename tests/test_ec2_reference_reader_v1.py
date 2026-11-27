"""Readonly production descriptors/wire over synthetic files, never AWS qualification."""

from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/ec2_reference_reader_v1.py"
SPEC = importlib.util.spec_from_file_location("ec2_reader_v1_tests", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)
BOOT = "66666666-6666-4666-8666-666666666666"


class Clock:
    def __init__(self):
        self.value = 1000

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += int(seconds * 1_000_000_000)


class Host:
    def __init__(self, clock):
        self.clock, self.boot_id = clock, BOOT
        self.changed_invocation = False
        self.reused_master = False
        self.inactive = False
        self.root_sleep = False

    def boot(self):
        return self.boot_id

    def lifecycle(self, _files):
        return None

    def no_project_process(self):
        return None

    def process(self, pid):
        if pid == 500:
            return {
                "pid": 500,
                "start_ticks": 100,
                "ppid": 1,
                "effective_uid": 0 if self.root_sleep else 1000,
                "argv": ["/usr/bin/sleep", "300"],
                "cgroup": "/system.slice/" + reader.UNIT,
            }
        if pid == 100:
            return {
                "pid": 100,
                "start_ticks": 200,
                "ppid": 1,
                "effective_uid": 0,
                "argv": [
                    "/usr/bin/timeout",
                    "--signal=TERM",
                    "--kill-after=2s",
                    "1500s",
                    *self.process(200)["argv"],
                ],
                "cgroup": "/system.slice/" + reader.UNIT,
            }
        return {
            "pid": pid,
            "start_ticks": 201 if self.reused_master else 200,
            "ppid": 100,
            "effective_uid": 0,
            "argv": [
                "/usr/bin/python3",
                "-I",
                reader.STAGE + "/ec2_reference_handoff_v3.py",
                "run",
                "--source-revision",
                reader.SOURCE,
                "--run-id",
                reader.RUN_ID,
            ],
            "cgroup": "/system.slice/" + reader.UNIT,
        }

    def guard(self):
        live = self.boot_id == reader.ORIGINAL_BOOT
        command = (
            [
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=2s",
                "1500s",
                *self.process(200)["argv"],
            ]
            if live
            else ["/usr/bin/sleep", "300"]
        )
        return {
            "active_state": "inactive" if self.inactive else "active",
            "sub_state": "dead" if self.inactive else "running",
            "invocation_id": "9" * 32
            if self.changed_invocation
            else (reader.ORIGINAL_INVOCATION if live else "7" * 32),
            "main_pid": 100 if live else 500,
            "main_start_ticks": 200 if live else 100,
            "main_argv": command,
            "exec_start": (
                "{ path=/usr/bin/sleep ; argv[]=/usr/bin/sleep 300 ; }"
                if not live
                else "fixed guard"
            ),
            "control_group": "/system.slice/" + reader.UNIT,
            "user": "ubuntu",
        }


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / "host"
    root.mkdir(mode=0o700)
    files = reader.SafeFiles(root, owner=os.getuid())

    def put(logical, raw):
        path = files.path(logical)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    archive = b"Original synthetic archive bytes, never regenerated.\n"
    put(reader.ARCHIVE, archive)
    monkeypatch.setattr(reader, "ARCHIVE_SHA", reader.sha(archive))
    monkeypatch.setattr(reader, "ARCHIVE_BYTES", len(archive))
    clock, host = Clock(), None
    host = Host(clock)
    host.boot_id = reader.ORIGINAL_BOOT
    guard, master = host.guard(), host.process(200)
    ready = {
        "kind": "restricted_reference_ec2_handoff_ready_v3",
        "schema_version": 3,
        "source_revision": reader.SOURCE,
        "run_id": reader.RUN_ID,
        "boot_id": reader.ORIGINAL_BOOT,
        "unit": reader.UNIT,
        "invocation_id": reader.ORIGINAL_INVOCATION,
        "main_pid": 100,
        "main_start_ticks": 200,
        "main_argv": guard["main_argv"],
        "guard_exec_start": guard["exec_start"],
        "guard_control_group": guard["control_group"],
        "controller_pid": 200,
        "controller_start_ticks": 200,
        "controller_argv": master["argv"],
        "nonce": "3" * 32,
        "bytes": len(archive),
        "sha256": reader.sha(archive),
        "archive_stat": {
            key: int(value)
            for key, value in reader.stat_record(files.path(reader.ARCHIVE).stat()).items()
        },
        "started_ns": 1,
        "deadline_ns": 120_000_000_001,
        "outer_deadline_ns": 1500_000_000_001,
    }
    ready_raw = reader.canonical(ready)
    put(reader.READY, ready_raw)
    monkeypatch.setattr(reader, "READY_SHA", reader.sha(ready_raw))
    start = {
        "kind": "restricted_reference_ec2_controller_start_v3",
        "schema_version": 3,
        "source_revision": reader.SOURCE,
        "run_id": reader.RUN_ID,
        "boot_id": reader.ORIGINAL_BOOT,
        "controller_pid": 200,
        "controller_start_ticks": 200,
        "controller_argv": master["argv"],
        "started_ns": 1,
        "outer_deadline_ns": ready["outer_deadline_ns"],
    }
    put(reader.OPERATION + "/controller-start.json", reader.canonical(start))
    for path in reader.STAGE_PATHS:
        put(path, b"Synthetic operation source; not executed.\n")
    source_rows = []
    for path in sorted(reader.SOURCE_PATHS):
        raw = ("Synthetic source observation: " + path).encode()
        put(path, raw)
        source_rows.append({"path": path, "bytes": len(raw), "sha256": reader.sha(raw)})
    pin_rows = []
    for path in sorted(
        {
            reader.READY,
            reader.ARCHIVE,
            reader.OPERATION + "/controller-start.json",
            *reader.STAGE_PATHS,
        }
    ):
        raw = files.path(path).read_bytes()
        pin_rows.append(
            {
                "path": path,
                "bytes": len(raw),
                "sha256": reader.sha(raw),
                "stat": reader.stat_record(files.path(path).stat()),
            }
        )
    data = {
        "kind": "ec2_transport_pin_set_v1",
        "schema_version": 1,
        "observation_id": reader.OBSERVATION_ID,
        "source_revision": reader.SOURCE,
        "run_id": reader.RUN_ID,
        "original_boot_id": reader.ORIGINAL_BOOT,
        "original_invocation_id": reader.ORIGINAL_INVOCATION,
        "original_archive_sha256": reader.ARCHIVE_SHA,
        "original_archive_bytes": len(archive),
        "original_ready_sha256": reader.READY_SHA,
        "origin_audit_index_sha256": reader.AUDIT_SHA,
        "files": pin_rows,
        "source_files": source_rows,
    }
    pins = reader.PinSet(reader.canonical(data), owner=os.getuid())
    host.boot_id = BOOT
    return SimpleNamespace(
        root=root,
        files=files,
        put=put,
        data=data,
        pins=pins,
        host=host,
        clock=clock,
        ready=ready,
        archive=archive,
        reader=reader.Reader(pins, files, host, clock),
    )


def test_real_file_descriptors_source_and_stage_pins_do_not_write_or_recreate_anything(case):
    before = {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in case.root.rglob("*")
        if path.is_file()
    }
    inventory = case.reader.inventory(BOOT)
    assert inventory["files_verified"] == 6 and inventory["source_files_verified"] == 10
    snapshot = case.reader.snapshot(BOOT)
    assert reader.decode_frame(reader.canonical(snapshot)) == snapshot
    assert snapshot["live"] is False and snapshot["master"] is None
    output, metadata = io.BytesIO(), io.BytesIO()
    case.reader.archive(BOOT, output, metadata)
    assert output.getvalue() == case.archive
    records = [reader.decode_frame(line) for line in metadata.getvalue().splitlines()]
    assert [row["phase"] for row in records] == ["before", "after"]
    assert records[0]["stat"] == records[1]["stat"]
    assert before == {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in case.root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("fault", ["extra", "duplicate_path", "bool", "leading_zero", "float_ns"])
def test_pinset_rejects_ambiguous_or_lossy_authority(case, fault):
    data = copy.deepcopy(case.data)
    if fault == "extra":
        data["unknown"] = True
    elif fault == "duplicate_path":
        data["files"].append(copy.deepcopy(data["files"][0]))
    elif fault == "bool":
        data["files"][0]["bytes"] = True
    elif fault == "leading_zero":
        data["files"][0]["stat"]["inode"] = "01"
    else:
        data["files"][0]["stat"]["mtime_ns"] = 1.8e18
    with pytest.raises(reader.Refused):
        reader.PinSet(reader.canonical(data), owner=os.getuid())


@pytest.mark.parametrize("suffix", ["/./state.json", "//state.json", "/state.json/"])
def test_pin_paths_cannot_use_textual_aliases(suffix):
    assert not reader.allowed_path(reader.ROOT + "/runs/" + reader.RUN_ID + suffix)


@pytest.mark.parametrize("fault", ["symlink", "hardlink", "parent_mode", "inode"])
def test_real_filesystem_faults_never_become_absence_or_a_matching_pin(case, fault):
    path = case.files.path(reader.READY)
    if fault == "symlink":
        path.unlink()
        path.symlink_to(case.files.path(reader.ARCHIVE))
    elif fault == "hardlink":
        os.link(path, path.with_name("unrelated-link"))
    elif fault == "parent_mode":
        path.parent.chmod(0o777)
    else:
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
    with pytest.raises(reader.Refused):
        case.reader.verified(reader.READY)
    assert case.reader.observed(reader.READY)["status"] != "ABSENT"


def test_parent_swap_to_symlink_with_identical_leaf_inode_is_detected_after_read(case, monkeypatch):
    path = case.files.path(reader.READY)
    actual_read = reader.os.read
    swapped = False

    def read_and_swap(fd, count):
        nonlocal swapped
        raw = actual_read(fd, count)
        if not swapped and os.fstat(fd).st_ino == path.stat().st_ino:
            swapped = True
            parent = path.parent
            retained = parent.with_name(parent.name + "-retained")
            parent.rename(retained)
            parent.symlink_to(retained, target_is_directory=True)
        return raw

    monkeypatch.setattr(reader.os, "read", read_and_swap)
    with pytest.raises(reader.ReadError, match="CHANGED"):
        case.files.read(reader.READY, reader.JSON_LIMIT)


def test_postrecords_keep_real_absence_empty_and_malformed_bytes_distinct(case):
    case.put(reader.OPERATION + "/export.stderr", b"")
    malformed = b'{"not-complete":'
    case.put(reader.OPERATION + "/controller-result.json", malformed)
    frames = list(case.reader.post_records(BOOT))
    assert len(frames) == 14 and frames[-1]["complete"] is True
    rows = {Path(frame["record"]["path"]).name: frame["record"] for frame in frames[1:-1]}
    assert rows["handoff-ack.json"]["status"] == "ABSENT"
    assert rows["export.stderr"]["status"] == "PRESENT_EMPTY"
    assert base64.b64decode(rows["controller-result.json"]["raw_b64"]) == malformed
    assert all(reader.decode_frame(reader.canonical(frame)) == frame for frame in frames)
    body = b"".join(reader.canonical(frame) for frame in frames[1:-1])
    assert frames[-1]["sha256"] == reader.sha(body)


def test_unsafe_postrecord_retains_error_and_never_claims_complete(case):
    path = case.put(reader.OPERATION + "/controller-result.json", b"{}")
    path.chmod(0o666)
    frames = list(case.reader.post_records(BOOT))
    assert frames[-1]["complete"] is False and frames[-1]["reason"] == "error"
    assert frames[1]["record"]["status"] == "UNSAFE"


def test_oversized_postrecord_preserves_known_prefix_without_complete_claim(case):
    raw = b"x" * (reader.JSON_LIMIT + 5)
    case.put(reader.OPERATION + "/controller-result.json", raw)
    frames = list(case.reader.post_records(BOOT))
    row = frames[1]["record"]
    assert (
        row["status"] == "TOO_LARGE"
        and base64.b64decode(row["raw_b64"]) == raw[: reader.JSON_LIMIT]
    )
    assert frames[-1]["complete"] is False
    assert reader.decode_frame(reader.canonical(frames[1])) == frames[1]


def test_historical_wait_flag_cannot_reopen_an_old_clock_with_smaller_new_boot_uptime(case):
    case.clock.value = 1
    with pytest.raises(reader.Refused):
        next(case.reader.post_records(BOOT, wait_existing_terminal=True))
    assert not case.files.path(reader.OPERATION + "/handoff-ack.json").exists()


@pytest.mark.parametrize("fault", ["invocation", "master_pid"])
def test_live_waiter_refuses_replacement_even_when_same_name_unit_is_inactive(case, fault):
    case.host.boot_id = reader.ORIGINAL_BOOT
    case.put(reader.OPERATION + "/controller-result.json", b"{}")
    stream = case.reader.post_records(reader.ORIGINAL_BOOT, wait_existing_terminal=True)
    assert next(stream)["kind"] == "ec2_reader_post_begin_v1"
    if fault == "invocation":
        case.host.inactive = case.host.changed_invocation = True
    else:
        case.host.reused_master = True
    with pytest.raises(reader.Refused):
        list(stream)


def test_sleep_guard_requires_actual_uid_and_identity_cannot_be_renewed(case):
    case.host.root_sleep = True
    with pytest.raises(reader.Refused):
        case.reader.snapshot(BOOT)
    case.host.root_sleep = False
    case.reader.snapshot(BOOT)
    case.host.changed_invocation = True
    with pytest.raises(reader.Refused):
        case.reader.snapshot(BOOT)


def test_source_original_inode_is_unknown_but_replacement_during_readback_is_not_ignored(case):
    case.reader.inventory(BOOT)
    path = case.files.path(sorted(reader.SOURCE_PATHS)[0])
    replacement = path.with_suffix(".new")
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    with pytest.raises(reader.Refused, match="inode changed"):
        case.reader.inventory(BOOT)


@pytest.mark.parametrize("raw", [b'{"kind":1,"kind":1}', b'{"clock":NaN}', b'{"clock":Infinity}'])
def test_duplicate_or_non_json_wire_values_are_not_valid_proof(raw):
    with pytest.raises(reader.Refused):
        reader.strict_json(raw)


def test_wire_field_order_can_vary_without_rewriting_original_payload(case):
    frame = case.reader.snapshot(BOOT)
    reordered = json.dumps(dict(reversed(list(frame.items()))), indent=1).encode()
    assert reader.decode_frame(reordered) == frame
    frame["server_now_ns"] = True
    with pytest.raises(reader.Refused):
        reader.decode_frame(reader.canonical(frame))


@pytest.mark.skipif(sys.platform != "linux", reason="Production waitid/WNOWAIT requires Linux")
@pytest.mark.parametrize(
    "program,expected,code",
    [
        ("print('one raw journal observation')", True, 0),
        ("pass", False, 0),
        ("import sys;print('partial');sys.stderr.write('error');sys.exit(7)", False, 7),
    ],
)
def test_actual_journal_subprocess_is_bounded_and_does_not_accept_empty_or_error(
    case, monkeypatch, program, expected, code
):
    actual_popen = subprocess.Popen
    case.reader.clock = reader.Clock()

    def producer(_command, **options):
        return actual_popen([sys.executable, "-c", program], **options)

    monkeypatch.setattr(reader.subprocess, "Popen", producer)
    output = io.BytesIO()
    frame = case.reader.journal("journal-unit", BOOT, output)
    assert frame["complete"] is expected and frame["producer_exit_code"] == code
    assert frame["sha256"] == reader.sha(output.getvalue())
    assert "_BOOT_ID=" + reader.ORIGINAL_BOOT.replace("-", "") in frame["query"]
    assert reader.decode_frame(reader.canonical(frame)) == frame


@pytest.mark.skipif(sys.platform != "linux", reason="Production waitid/WNOWAIT requires Linux")
def test_actual_journal_flood_is_stopped_without_unbounded_capture(case, monkeypatch):
    actual_popen = subprocess.Popen
    case.reader.clock = reader.Clock()
    child = []

    def producer(_command, **options):
        process = actual_popen(
            [sys.executable, "-c", "import os;os.write(1,b'x'*10000)"], **options
        )
        child.append(process)
        return process

    monkeypatch.setattr(reader.subprocess, "Popen", producer)
    monkeypatch.setattr(reader, "STREAM_LIMIT", 1024)
    output = io.BytesIO()
    with pytest.raises(reader.Refused, match="bound"):
        case.reader.journal("journal-boot", BOOT, output)
    assert len(output.getvalue()) <= 1024 and child[0].poll() is not None


@pytest.mark.skipif(
    sys.platform != "linux", reason="Real procfs/fork/group ownership requires Linux"
)
@pytest.mark.parametrize("cleanup_signal", [None, signal.SIGALRM, signal.SIGTERM])
def test_journal_timeout_kills_pipe_holder_even_after_the_owned_leader_exited(
    case, monkeypatch, cleanup_signal
):
    actual_popen = subprocess.Popen
    children = []
    marker = case.root.parent / "pipe-holder-ready"

    def producer(_command, **options):
        program = (
            "import os,signal,time,sys\nfrom pathlib import Path\n"
            "child=os.fork()\n"
            "if child==0:\n"
            " signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            " os.write(1,(str(os.getpid())+'\\n').encode())\n"
            " Path(sys.argv[1]).write_text('ready')\n"
            " time.sleep(60)\n"
            "else: os._exit(0)\n"
        )
        process = actual_popen([sys.executable, "-c", program, str(marker)], **options)
        children.append(process)
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not marker.exists():
            os.killpg(process.pid, 9)
            process.wait(timeout=2)
            pytest.fail("Real forked pipe-holder never signalled readiness")
        return process

    class AdvancingClock(Clock):
        def now(self):
            self.value += 10_000_000_000
            return self.value

    case.reader.clock = AdvancingClock()
    monkeypatch.setattr(reader.subprocess, "Popen", producer)
    actual_killpg = os.killpg
    actual_stopped = reader.owned_group_stopped
    pending = []

    def killpg(pgid, signum):
        actual_killpg(pgid, signum)
        if signum == signal.SIGTERM:
            if cleanup_signal == signal.SIGALRM:
                signal.setitimer(signal.ITIMER_REAL, 0.02)
            elif cleanup_signal == signal.SIGTERM:
                os.kill(os.getpid(), signal.SIGTERM)

    def stopped(pgid, deadline):
        pending.append(cleanup_signal in signal.sigpending())
        return actual_stopped(pgid, deadline)

    monkeypatch.setattr(reader.os, "killpg", killpg)
    monkeypatch.setattr(reader, "owned_group_stopped", stopped)
    previous = signal.signal(signal.SIGALRM, reader._alarm)
    previous_term = signal.signal(signal.SIGTERM, reader._alarm)
    output = io.BytesIO()
    started = time.monotonic()
    try:
        with pytest.raises(reader.Refused, match="deadline"):
            case.reader.journal("journal-boot", BOOT, output)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        signal.signal(signal.SIGTERM, previous_term)
    assert time.monotonic() - started < 2.5
    if cleanup_signal is not None:
        assert any(pending), "The real deadline signal must arrive between TERM and KILL"
    pid = int(output.getvalue().strip())
    assert children[0].poll() == 0
    state = Path(f"/proc/{pid}/stat")
    if state.exists():
        tail = state.read_bytes().rsplit(b")", 1)[1].split()
        assert tail[0] in {b"Z", b"X"}


def test_journal_cannot_renew_the_original_cli_deadline_after_its_prelude(case, monkeypatch):
    case.reader.command_deadline_ns = case.reader.clock.now()

    def forbidden(*_args, **_kwargs):
        pytest.fail("An exhausted command deadline must refuse before spawning journalctl")

    monkeypatch.setattr(reader.subprocess, "Popen", forbidden)
    with pytest.raises(reader.Refused, match="before spawn"):
        case.reader.journal("journal-boot", BOOT, io.BytesIO())


@pytest.mark.parametrize("command_seconds_left", [3, 120])
def test_live_waiter_clips_output_alarm_to_original_window_without_extending_cli_deadline(
    case, monkeypatch, command_seconds_left
):
    case.host.boot_id = reader.ORIGINAL_BOOT
    case.clock.value = case.ready["deadline_ns"] - 10_000_000_000
    initial = case.clock.now() + command_seconds_left * 1_000_000_000
    case.reader.command_deadline_ns = initial
    armed = []
    monkeypatch.setattr(reader.signal, "setitimer", lambda *args: armed.append(args))
    stream = case.reader.post_records(reader.ORIGINAL_BOOT, wait_existing_terminal=True)
    first = next(stream)
    expected = min(initial, case.ready["deadline_ns"], case.ready["outer_deadline_ns"])
    assert first["kind"] == "ec2_reader_post_begin_v1"
    assert case.reader.command_deadline_ns == expected
    assert armed == [(signal.ITIMER_REAL, (expected - case.clock.now()) / 1e9)]
    next(stream)
    assert len(armed) == 1, "Data frames must not renew the original output alarm"
    stream.close()


def test_expired_live_waiter_cli_deadline_cannot_emit_a_positive_header(case, monkeypatch):
    case.host.boot_id = reader.ORIGINAL_BOOT
    case.reader.command_deadline_ns = case.clock.now()
    armed = []
    monkeypatch.setattr(reader.signal, "setitimer", lambda *args: armed.append(args))
    stream = case.reader.post_records(reader.ORIGINAL_BOOT, wait_existing_terminal=True)
    with pytest.raises(reader.ReaderAlarm, match="before output"):
        next(stream)
    assert armed == []


@pytest.mark.parametrize(
    "code,field,value",
    [
        (0, None, None),
        (1, None, None),
        (4, None, None),
        (4, "InvocationID", "1" * 32),
        (4, "User", "ubuntu"),
        (4, "ActiveState", "active"),
        (4, "ExecStart", "/usr/bin/sleep 300"),
        (5, None, None),
    ],
)
def test_missing_transient_guard_requires_positive_exact_empty_identity(
    monkeypatch, code, field, value
):
    data = dict(reader.MISSING_GUARD)
    if field is not None:
        data[field] = value

    def show(command, **_options):
        assert command[:4] == ["/usr/bin/systemctl", "show", reader.UNIT, "--all"]
        raw = "".join(key + "=" + item + "\n" for key, item in data.items()).encode()
        return subprocess.CompletedProcess(command, code, raw, b"")

    monkeypatch.setattr(reader.subprocess, "run", show)
    if field is None and code in {0, 1, 4}:
        guard = reader.Host().guard()
        assert guard["active_state"] == "inactive" and guard["sub_state"] == "dead"
        assert guard["main_pid"] == 0 and guard["main_argv"] == []
        assert guard["invocation_id"] == "" and guard["exec_start"] == ""
    else:
        with pytest.raises(reader.Refused):
            reader.Host().guard()


@pytest.mark.parametrize(
    "omitted,code",
    [("ExecStart", 0), ("ExecStart", 4), ("MainPID", 0), ("User", 0), ("InvocationID", 0)],
)
def test_unloaded_guard_preserves_observed_eight_fields_without_filling_other_missing_fields(
    monkeypatch, omitted, code
):
    data = {key: value for key, value in reader.MISSING_GUARD.items() if key != omitted}

    def show(command, **_options):
        raw = "".join(key + "=" + item + "\n" for key, item in data.items()).encode()
        return subprocess.CompletedProcess(command, code, raw, b"")

    monkeypatch.setattr(reader.subprocess, "run", show)
    host = reader.Host()
    if omitted == "ExecStart":
        observed = host.show(reader.UNIT, tuple(reader.MISSING_GUARD))
        assert observed == data and "ExecStart" not in observed
        guard = host.guard()
        assert guard["exec_start"] == reader.UNOBSERVED_EXEC_START
        assert guard["active_state"] == "inactive" and guard["main_pid"] == 0
    else:
        with pytest.raises(reader.Refused, match="Missing manager identity"):
            host.guard()
    with pytest.raises(reader.Refused, match="Missing manager identity"):
        host.show("tickwitness-boot-deadline.service", tuple(reader.MISSING_GUARD))


def test_active_manager_cannot_use_the_unloaded_guard_missing_property_exception(monkeypatch):
    data = reader.UNLOADED_GUARD | {"LoadState": "loaded", "ActiveState": "active"}

    def show(command, **_options):
        raw = "".join(key + "=" + item + "\n" for key, item in data.items()).encode()
        return subprocess.CompletedProcess(command, 0, raw, b"")

    monkeypatch.setattr(reader.subprocess, "run", show)
    with pytest.raises(reader.Refused, match="Missing manager identity"):
        reader.Host().guard()


@pytest.mark.skipif(sys.platform != "linux", reason="Actual systemd observation requires Linux")
def test_actual_remote_systemctl_missing_transient_guard_is_only_an_inactive_observation():
    if not Path("/run/systemd/system").exists():
        pytest.skip("This remote fixture is not booted with a systemd system manager")
    names = tuple(reader.MISSING_GUARD)
    command = [
        "/usr/bin/systemctl",
        "show",
        reader.UNIT,
        "--all",
        "--no-pager",
        "--property=" + ",".join(names),
    ]
    result = subprocess.run(command, capture_output=True, timeout=3, check=False)
    print(
        "Actual readonly missing-unit observation:",
        result.returncode,
        result.stdout,
        result.stderr,
    )
    details = (result.returncode, result.stdout, result.stderr)
    assert result.returncode in {0, 1, 4}, details
    observed = reader.Host().show(reader.UNIT, names)
    raw_values = dict(line.split("=", 1) for line in result.stdout.decode().splitlines())
    assert observed == raw_values, details
    assert observed in (reader.MISSING_GUARD, reader.UNLOADED_GUARD), details
    guard = reader.Host().guard()
    assert guard["active_state"] == "inactive" and guard["main_pid"] == 0, details
    assert guard["exec_start"] == (
        "" if "ExecStart" in observed else reader.UNOBSERVED_EXEC_START
    ), details


@pytest.mark.parametrize(
    "fault", [None, "timer_dropin", "timer_path", "period", "service_dropin", "service_path"]
)
def test_real_lifecycle_method_checks_stop_service_and_timer_without_running_systemd(
    case, monkeypatch, fault
):
    hashes = {}
    for path in reader.LIFECYCLE_SHA:
        raw = ("Synthetic original lifecycle bytes: " + path).encode()
        case.put(path, raw)
        hashes[path] = reader.sha(raw)
    monkeypatch.setattr(reader, "LIFECYCLE_SHA", hashes)
    host = reader.Host()

    def show(unit, _names):
        if unit.endswith(".timer"):
            return {
                "ActiveState": "active",
                "UnitFileState": "enabled",
                "DropInPaths": "/override" if fault == "timer_dropin" else "",
                "FragmentPath": "/other"
                if fault == "timer_path"
                else "/etc/systemd/system/tickwitness-boot-deadline.timer",
                "TimersMonotonic": "changed"
                if fault == "period"
                else "{ OnBootUSec=4h ; next_elapse=4h }",
            }
        return {
            "DropInPaths": "/override" if fault == "service_dropin" else "",
            "FragmentPath": "/other"
            if fault == "service_path"
            else "/etc/systemd/system/tickwitness-boot-deadline.service",
        }

    monkeypatch.setattr(host, "show", show)
    if fault is None:
        host.lifecycle(case.files)
    else:
        with pytest.raises(reader.Refused):
            host.lifecycle(case.files)


@pytest.mark.skipif(os.name != "posix", reason="Production readonly CLI requires POSIX")
@pytest.mark.parametrize("unsafe", [False, True])
def test_actual_cli_subprocess_frames_real_reader_and_never_calls_an_old_operation(case, unsafe):
    if unsafe:
        case.put(reader.OPERATION + "/controller-result.json", b"{}").chmod(0o666)
    pin_path = case.root.parent / "pins.json"
    pin_path.write_bytes(reader.canonical(case.data))
    # Only constructor ports/observations are substituted, not main, Reader,
    # descriptor reads, record production or stream completeness decisions.
    program = r"""
import base64,json,os,runpy,sys
from pathlib import Path
namespace=runpy.run_path(sys.argv[1])
module=namespace['reader']
raw=Path(sys.argv[2]).read_bytes()
pins=json.loads(raw)
module.ARCHIVE_SHA=pins['original_archive_sha256']
module.ARCHIVE_BYTES=pins['original_archive_bytes']
module.READY_SHA=pins['original_ready_sha256']
module.PIN_SET_B64=base64.b64encode(raw).decode()
actual_pins,actual_reader=module.PinSet,module.Reader
module.PinSet=lambda value:actual_pins(value,owner=os.getuid())
clock=namespace['Clock']()
host=namespace['Host'](clock)
module.Reader=lambda value:actual_reader(
 value,module.SafeFiles(Path(sys.argv[3]),owner=os.getuid()),host,clock)
module.os.geteuid=lambda:0
module.platform.machine=lambda:'x86_64'
module.platform.freedesktop_os_release=lambda:{'ID':'ubuntu','VERSION_ID':'24.04'}
module.sys.platform='linux'
raise SystemExit(module.main(['post-records',namespace['BOOT']]))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(Path(__file__)), str(pin_path), str(case.root)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == (74 if unsafe else 0) and result.stderr == b""
    frames = [reader.decode_frame(line) for line in result.stdout.splitlines()]
    assert frames[0]["kind"] == "ec2_reader_post_begin_v1"
    assert frames[-1]["complete"] is (not unsafe)
    assert frames[-1]["records"] == 12
    assert not case.files.path(reader.OPERATION + "/handoff-ack.json").exists()
