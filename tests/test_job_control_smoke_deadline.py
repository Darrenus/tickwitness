"""Smoke evidence can prove a deadline without claiming native completion.

These are metadata decisions using the helpers called by the installed smoke.
They launch no worker, extend no deadline and allocate no research reservation.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

JOB = "a" * 64
COORDINATOR = "b" * 64
ATTEMPT = "c" * 64
LEASE = "d" * 64
DATASET = "e" * 64


@pytest.fixture(scope="module")
def smoke():
    script = Path(__file__).parents[1] / "scripts" / "smoke_job_controls.py"
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.syspath_prepend(str(script.parent))
        spec = importlib.util.spec_from_file_location("tickwitness_control_smoke", script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def bind(smoke, observed):
    """Rebind hashes after a mutation so a different invariant must reject it."""
    control = observed["control"]
    control["policy_id"] = smoke._sha(smoke._canonical(control["policy"]))
    control["result"]["policy_id"] = control["policy_id"]
    control["result"]["catalog_snapshot_sha256"] = smoke._sha(
        smoke._canonical(observed["snapshot"])
    )


@pytest.fixture
def evidence(smoke):
    request = {
        "kind": "job_native_worker_request_v1",
        "schema_version": 1,
        "job_id": JOB,
        "coordinator_id": COORDINATOR,
        "job_attempt_id": ATTEMPT,
        "lease_token": LEASE,
        "payload": {
            "dataset_id": DATASET,
            "research_attempt": {
                "kind": "replay_attempt_reservation_v1",
                "schema_version": 1,
                "protocol_id": "f" * 64,
                "nonce": "1" * 32,
                "created_at_utc": "2026-11-26T18:39:06.440287+00:00",
                "attempt_index": 5,
                "max_wall_seconds": 60,
            },
            "native_deadline_ns": 261_161_481_958,
            "intent": {},
            "normalized": "",
            "replay_spec": {},
        },
    }
    identity = {"pid": 202, "parent_pid": 201, "process_group": 201, "session_id": 201}
    ready = {
        "kind": "actual_native_adapter_entered_while_heartbeat_emitter_live_v1",
        **identity,
        "job_id": JOB,
        "request_sha256": smoke._sha(smoke._canonical(request) + b"\n"),
        "workspace": "/owned/job-workspace/scratch",
        "limits": {"cpu": [60, 60], "file": [8_388_608, 8_388_608], "files": [128, 128]},
        "workspace_at_ready": {
            "exists": True,
            "is_symlink": False,
            "device": 10,
            "inode": 20,
        },
        "mode": "deadline",
        "native_completed": False,
        "native_completion_status": "NOT_OBSERVED",
    }
    calls = [
        {
            "kind": "actual_native_adapter_invoked_v1",
            **identity,
            "job_id": JOB,
            "dataset_id": DATASET,
        }
    ]
    frames = [
        {
            "kind": "job_heartbeat_v1",
            "schema_version": 1,
            "job_id": JOB,
            "coordinator_id": COORDINATOR,
            "job_attempt_id": ATTEMPT,
            "lease_token": LEASE,
            "sequence": sequence,
        }
        for sequence in range(1, 17)
    ]
    # The real failed smoke had 16 delivered frames and 15 processed heartbeats.
    # Its original total-clock observation is retained without a timing replay.
    snapshot = {
        "kind": "job_snapshot_v1",
        "schema_version": 1,
        "job_id": JOB,
        "spec": {"lease_duration_ns": 30_000_000_000},
        "state": "FAILED",
        "version": 18,
        "created_at_ns": 1_795_718_332_826_122_000,
        "updated_at_ns": 1_795_718_351_014_480_000,
        "attempt": {
            "job_attempt_id": ATTEMPT,
            "attempt_number": 1,
            "nonce": "2" * 64,
            "coordinator_id": COORDINATOR,
            "lease_token": LEASE,
            "heartbeat_sequence": 15,
            "heartbeat_at_ns": 1_795_718_350_702_543_000,
            "lease_expires_at_ns": 1_795_718_380_702_543_000,
        },
        "result_sha256": None,
        "failure": {
            "code": "job_deadline_exceeded",
            "message": "Fixed Job total admission deadline expired",
            "worker_exit_code": -9,
        },
    }
    observed = {
        "snapshot": snapshot,
        "events": [],
        "result": None,
        "control": {
            "policy": {
                "kind": "job_control_policy_v1",
                "schema_version": 1,
                "job_id": JOB,
                "limits": {
                    "max_wall_ns": 15_000_000_000,
                    "worker_cpu_seconds": 60,
                    "max_file_bytes": 8_388_608,
                    "max_open_files": 128,
                    "cleanup_grace_ns": 5_000_000_000,
                },
            },
            "policy_id": None,
            "cancel": None,
            "publication": None,
            "result": {
                "kind": "job_control_result_v1",
                "schema_version": 1,
                "job_id": JOB,
                "job_attempt_id": ATTEMPT,
                "policy_id": None,
                "cause": "job_deadline_exceeded",
                "catalog_state": "FAILED",
                "catalog_snapshot_sha256": None,
                "publication_admitted": False,
                "worker_started": True,
                "worker_exit_code": -9,
                "worker_group_absent": True,
                "workspace_removed": True,
                "cleanup_confirmed": True,
                "stop_confirmed": True,
                "timing_ns": {
                    "elapsed": 15_071_925_875,
                    "request_observed": None,
                    "worker_reaped": 15_047_038_750,
                    "cleanup_finished": 15_060_759_667,
                },
                "diagnostic": "Fixed Job total admission deadline expired",
            },
        },
    }
    bind(smoke, observed)
    return {
        "request": request,
        "ready": ready,
        "calls": calls,
        "frames": frames,
        "observed": observed,
    }


def native_result(smoke, evidence):
    return smoke._canonical(
        {
            "kind": "replay_qualification_result_v1",
            "schema_version": 1,
            "dataset_id": evidence["request"]["payload"]["dataset_id"],
            "execution_status": "completed",
        }
    )


def gate(smoke, evidence, *, mode="deadline", result=None):
    return smoke._validate_native_gate(
        mode, evidence["ready"], evidence["request"], evidence["calls"], result
    )


def test_deadline_entry_and_live_lease_prove_stop_without_native_completion(smoke, evidence):
    original = copy.deepcopy(evidence)
    assert gate(smoke, evidence) == {
        "kind": "native_control_gate_evidence_v1",
        "gate_phase": "adapter_entry",
        "adapter_entered": True,
        "native_completed": False,
        "native_completion_status": "NOT_OBSERVED",
        "native_result_sha256": None,
    }
    smoke._validate_native_deadline_outcome(
        evidence["observed"], evidence["request"], evidence["frames"]
    )
    assert evidence == original


def test_later_result_observation_does_not_rewrite_the_original_entry(smoke, evidence):
    raw = native_result(smoke, evidence)
    outcome = gate(smoke, evidence, result=raw)
    assert outcome["gate_phase"] == "adapter_entry"
    assert outcome["native_completed"] is True
    assert outcome["native_completion_status"] == "OBSERVED"
    assert outcome["native_result_sha256"] == smoke._sha(raw)
    assert evidence["ready"]["native_completed"] is False
    assert evidence["ready"]["native_completion_status"] == "NOT_OBSERVED"


@pytest.mark.parametrize("mode", ["cancel", "resource", "cancel_publication", "publication_wins"])
def test_other_native_modes_still_require_a_completed_gate_and_actual_result(smoke, evidence, mode):
    ready = evidence["ready"]
    ready["kind"] = "actual_native_completed_while_heartbeat_emitter_live_v1"
    ready["mode"] = mode if mode in {"cancel", "resource"} else "normal"
    for key in ("request_sha256", "native_completed", "native_completion_status"):
        del ready[key]
    if mode == "resource":
        ready["limits"]["file"] = [65_536, 65_536]
    with pytest.raises(AssertionError):
        gate(smoke, evidence, mode=mode)
    outcome = gate(smoke, evidence, mode=mode, result=native_result(smoke, evidence))
    assert outcome["gate_phase"] == "native_completed"
    assert outcome["native_completed"] is True


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("kind",), "actual_native_completed_while_heartbeat_emitter_live_v1"),
        (("native_completed",), True),
        (("native_completion_status",), "OBSERVED"),
        (("request_sha256",), "0" * 64),
        (("job_id",), "0" * 64),
        (("pid",), 203),
        (("mode",), "normal"),
        (("limits", "cpu"), [61, 61]),
        (("limits", "cpu"), [60, 61]),
        (("limits", "file"), [8_388_609, 8_388_609]),
        (("limits", "files"), [129, 129]),
        (("workspace_at_ready", "exists"), False),
        (("workspace_at_ready", "is_symlink"), True),
    ],
)
def test_deadline_gate_refuses_false_entry_or_wrong_observed_identity(smoke, evidence, path, value):
    target = evidence["ready"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(AssertionError):
        gate(smoke, evidence)


@pytest.mark.parametrize("field", ["kind", "request_sha256", "native_completed"])
def test_deadline_without_the_entry_evidence_is_not_accepted(smoke, evidence, field):
    del evidence["ready"][field]
    with pytest.raises(KeyError):
        gate(smoke, evidence)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_pid", "wrong_dataset"])
def test_native_adapter_call_must_be_present_once_and_bound_to_entry(smoke, evidence, fault):
    calls = evidence["calls"]
    if fault == "missing":
        calls.clear()
    elif fault == "duplicate":
        calls.append(copy.deepcopy(calls[0]))
    elif fault == "wrong_pid":
        calls[0]["pid"] = 203
    else:
        calls[0]["dataset_id"] = "0" * 64
    with pytest.raises(AssertionError):
        gate(smoke, evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "not_a_native_result"),
        ("dataset_id", "0" * 64),
        ("execution_status", "failed"),
    ],
)
def test_present_but_incompatible_result_cannot_claim_completion(smoke, evidence, field, value):
    result = {
        "kind": "replay_qualification_result_v1",
        "schema_version": 1,
        "dataset_id": DATASET,
        "execution_status": "completed",
    }
    result[field] = value
    with pytest.raises(AssertionError):
        gate(smoke, evidence, result=smoke._canonical(result))


def test_os_timer_may_reap_before_controller_deadline_observation(smoke, evidence):
    timing = evidence["observed"]["control"]["result"]["timing_ns"]
    timing["worker_reaped"] = 14_999_999_999
    smoke._validate_native_deadline_outcome(
        evidence["observed"], evidence["request"], evidence["frames"]
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("snapshot", "state"), "RUNNING"),
        (("snapshot", "failure", "code"), "job_lease_expired"),
        (("snapshot", "attempt", "lease_expires_at_ns"), 1_795_718_351_014_480_000),
        (("snapshot", "attempt", "job_attempt_id"), "0" * 64),
        (("snapshot", "attempt", "coordinator_id"), "0" * 64),
        (("snapshot", "attempt", "lease_token"), "0" * 64),
        (("snapshot", "attempt", "heartbeat_sequence"), 2),
        (("snapshot", "attempt", "heartbeat_sequence"), 17),
        (("snapshot", "attempt", "heartbeat_sequence"), True),
        (("snapshot", "result_sha256"), "0" * 64),
        (("result",), {"action": "replayed_from_origin"}),
        (("control", "result", "cause"), "job_cancelled"),
        (("control", "result", "job_attempt_id"), "0" * 64),
        (("control", "result", "worker_started"), False),
        (("control", "result", "worker_group_absent"), False),
        (("control", "result", "workspace_removed"), False),
        (("control", "result", "cleanup_confirmed"), False),
        (("control", "result", "stop_confirmed"), False),
        (("control", "result", "publication_admitted"), True),
        (("control", "publication"), {"kind": "publication_already_admitted"}),
        (("control", "result", "worker_exit_code"), None),
        (("control", "result", "timing_ns", "elapsed"), 14_999_999_999),
        (("control", "result", "timing_ns", "elapsed"), True),
        (("control", "result", "timing_ns", "worker_reaped"), -1),
        (("control", "result", "timing_ns", "cleanup_finished"), 15_047_038_749),
        (("control", "result", "timing_ns", "cleanup_finished"), 15_071_925_876),
        (("control", "policy", "limits", "max_wall_ns"), 16_000_000_000),
        (("control", "policy", "limits", "worker_cpu_seconds"), 61),
    ],
)
def test_deadline_terminal_requires_the_original_bound_policy_and_confirmed_stop(
    smoke, evidence, path, value
):
    observed = evidence["observed"]
    target = observed
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    bind(smoke, observed)
    with pytest.raises(AssertionError):
        smoke._validate_native_deadline_outcome(observed, evidence["request"], evidence["frames"])


@pytest.mark.parametrize("fault", ["few", "gap", "duplicate", "bool", "kind", "binding", "schema"])
def test_deadline_requires_continuous_authentic_heartbeat_frames(smoke, evidence, fault):
    frames = evidence["frames"]
    if fault == "few":
        del frames[2:]
    elif fault == "gap":
        frames[1]["sequence"] = 3
    elif fault == "duplicate":
        frames[1]["sequence"] = 1
    elif fault == "bool":
        frames[0]["sequence"] = True
    elif fault == "kind":
        frames[0]["kind"] = "job_result_v1"
    elif fault == "schema":
        frames[0]["schema_version"] = 2
    else:
        frames[0]["lease_token"] = "0" * 64
    with pytest.raises(AssertionError):
        smoke._validate_native_deadline_outcome(evidence["observed"], evidence["request"], frames)


@pytest.mark.parametrize("field", ["policy_id", "catalog_snapshot_sha256"])
def test_deadline_receipt_cannot_refer_to_different_persisted_authority(smoke, evidence, field):
    evidence["observed"]["control"]["result"][field] = "0" * 64
    with pytest.raises(AssertionError):
        smoke._validate_native_deadline_outcome(
            evidence["observed"], evidence["request"], evidence["frames"]
        )


@pytest.mark.parametrize(("field", "value"), [("attempt_index", 6), ("max_wall_seconds", 61)])
def test_deadline_stays_within_original_slot_five_and_native_sixty_seconds(
    smoke, evidence, field, value
):
    evidence["request"]["payload"]["research_attempt"][field] = value
    with pytest.raises(AssertionError):
        smoke._validate_native_deadline_outcome(
            evidence["observed"], evidence["request"], evidence["frames"]
        )


GATE_BUSY = {
    "error": {"code": "job_conflict", "message": "Another writer owns the Job control gate"}
}


@pytest.fixture
def cancellation_harness(smoke, monkeypatch, tmp_path):
    class Clock:
        now = 100.0

        def __init__(self):
            self.sleeps = []

        def monotonic(self):
            return self.now

        def wait(self, seconds):
            assert 0 < seconds <= 0.02
            self.sleeps.append(seconds)
            self.now += seconds

    clock = Clock()
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    harness = SimpleNamespace(
        clock=clock,
        responses=[],
        costs=[],
        runs=[],
        records=[],
        transcripts=transcripts,
        on_run=None,
    )

    def run(argv, **kwargs):
        harness.runs.append((tuple(argv), dict(kwargs)))
        assert kwargs["timeout"] > 0
        if harness.on_run is not None:
            harness.on_run()
        if harness.costs:
            clock.now += harness.costs.pop(0)
        response = harness.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return subprocess.CompletedProcess(argv, *response)

    def invoke(entry=None, command=None):
        selected_command = (
            [
                "readonly",
                "/owned/jobs",
                "cancel-job",
                JOB,
                "--cancel-key",
                "original-key",
                "--jobs",
                "/owned/jobs",
            ]
            if command is None
            else command
        )
        return smoke._invoke_cancellation(
            "/installed/core-python",
            ["-c", "original-guard"] if entry is None else entry,
            selected_command,
            cwd=tmp_path,
            calls=harness.records,
            transcripts=transcripts,
        )

    harness.invoke = invoke
    monkeypatch.setattr(smoke, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(smoke, "Event", lambda: SimpleNamespace(wait=clock.wait))
    monkeypatch.setattr(smoke, "subprocess", SimpleNamespace(run=run))
    return harness


def busy_response():
    return 9, "", json.dumps(GATE_BUSY) + "\n"


def test_cancel_gate_refusal_keeps_fixed_argv_original_window_and_raw_transcripts(
    cancellation_harness,
):
    harness = cancellation_harness
    entry = ["-c", "original-guard"]
    command = [
        "readonly",
        "/owned/jobs",
        "cancel-job",
        JOB,
        "--cancel-key",
        "original-key",
        "--jobs",
        "/owned/jobs",
    ]
    expected_argv = ("/installed/core-python", "-I", *entry, *command)
    response = {"status": "accepted", "job_id": JOB, "policy_id": "f" * 64}
    harness.responses[:] = [busy_response(), (0, json.dumps(response), "")]
    harness.costs[:] = [1.5, 0.25]

    def mutate_original_arguments():
        entry[:] = ["-c", "changed-guard"]
        command[:] = ["cancel-job", "0" * 64, "--cancel-key", "changed-key"]

    harness.on_run = mutate_original_arguments
    assert harness.invoke(entry, command) == response
    assert [argv for argv, _ in harness.runs] == [expected_argv, expected_argv]
    assert [kwargs["timeout"] for _, kwargs in harness.runs] == pytest.approx([10, 8.48])
    assert harness.clock.sleeps == [0.02]
    assert harness.clock.now == pytest.approx(101.77)
    assert [row["expected_exit_code"] for row in harness.records] == [9, 0]
    stored = [json.loads(path.read_bytes()) for path in sorted(harness.transcripts.glob("*.json"))]
    assert stored == harness.records
    assert json.loads(stored[0]["stderr"]) == GATE_BUSY


@pytest.mark.parametrize(
    "status", ["accepted", "already_requested", "too_late", "already_terminal"]
)
def test_cancel_response_status_is_returned_once_without_promoting_it_to_acceptance(
    cancellation_harness, status
):
    harness = cancellation_harness
    response = {"status": status, "job_id": JOB}
    harness.responses.append((0, json.dumps(response), ""))
    assert harness.invoke() == response
    assert len(harness.runs) == 1 and harness.clock.sleeps == []


@pytest.mark.parametrize("change", ["command", "catalog"])
def test_cancel_retry_is_not_available_to_other_mutations_or_catalogs(cancellation_harness, change):
    harness = cancellation_harness
    command = [
        "readonly",
        "/owned/jobs",
        "cancel-job",
        JOB,
        "--cancel-key",
        "original-key",
        "--jobs",
        "/owned/jobs",
    ]
    if change == "command":
        command[2] = "configure-job-control"
    else:
        command[-1] = "/different/jobs"
    with pytest.raises(AssertionError):
        harness.invoke(command=command)
    assert harness.runs == [] and harness.records == []


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [
        (9, "", json.dumps({"error": {"code": "job_conflict", "message": "Other writer"}})),
        (9, "", json.dumps({"error": {"code": "readonly_snapshot_unstable", "message": "busy"}})),
        (
            9,
            "",
            json.dumps(
                {
                    "error": {
                        "code": "job_conflict",
                        "message": "Job already has a different accepted cancellation key",
                    }
                }
            ),
        ),
        (9, "", json.dumps({**GATE_BUSY, "unknown": True})),
        (9, "", "not-json"),
        (9, "", json.dumps(GATE_BUSY) + "\n{}"),
        (9, "partial-output", json.dumps(GATE_BUSY)),
        (8, "", json.dumps(GATE_BUSY)),
        (-9, "", ""),
    ],
)
def test_cancel_repeats_no_other_conflict_partial_output_or_unknown_failure(
    cancellation_harness, returncode, stdout, stderr
):
    harness = cancellation_harness
    harness.responses.append((returncode, stdout, stderr))
    with pytest.raises((AssertionError, RuntimeError, ValueError)):
        harness.invoke()
    assert len(harness.runs) == 1 and harness.clock.sleeps == []


@pytest.mark.parametrize(
    "stderr",
    [
        '{"error":{"code":"job_conflict","code":"job_conflict",'
        '"message":"Another writer owns the Job control gate"}}',
        '{"error":{"code":"job_conflict","message":"Another writer owns the Job control gate"},'
        '"error":{"code":"job_conflict","message":"Another writer owns the Job control gate"}}',
        '{"error":{"code":"job_conflict","message":NaN}}',
        '{"error":{"code":"job_conflict","message":Infinity}}',
    ],
)
def test_cancel_ambiguous_or_non_json_constants_are_not_prewrite_refusal_proof(
    cancellation_harness, stderr
):
    harness = cancellation_harness
    harness.responses.append((9, "", stderr))
    with pytest.raises(ValueError):
        harness.invoke()
    assert len(harness.runs) == len(harness.records) == 1
    assert harness.clock.sleeps == []
    assert harness.records[0]["stderr"] == stderr


def test_cancel_subprocess_timeout_is_unknown_and_is_never_repeated(cancellation_harness):
    harness = cancellation_harness
    failure = subprocess.TimeoutExpired("cancel-job", 10, output="partial")
    harness.responses.append(failure)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        harness.invoke()
    assert caught.value is failure
    assert len(harness.runs) == 1 and harness.clock.sleeps == []


def test_cancel_io_error_is_not_a_known_prewrite_gate_refusal(cancellation_harness):
    harness = cancellation_harness
    failure = OSError("Cancellation command outcome is unconfirmed")
    harness.responses.append(failure)
    with pytest.raises(OSError) as caught:
        harness.invoke()
    assert caught.value is failure
    assert len(harness.runs) == 1 and harness.clock.sleeps == []


def test_cancel_gate_refusal_has_one_absolute_ten_second_limit(cancellation_harness):
    harness = cancellation_harness
    harness.responses[:] = [busy_response()] * 2
    harness.costs[:] = [9.99]
    with pytest.raises(AssertionError):
        harness.invoke()
    assert len(harness.runs) == 1
    assert harness.clock.now == pytest.approx(110.0)
    assert harness.clock.sleeps == pytest.approx([0.01])
    assert len(harness.records) == 1


def test_cancel_gate_refusal_cannot_create_a_seventeenth_attempt(cancellation_harness):
    harness = cancellation_harness
    harness.responses[:] = [busy_response()] * 17
    with pytest.raises(AssertionError):
        harness.invoke()
    assert len(harness.runs) == len(harness.records) == 16
    assert len(harness.responses) == 1
    assert harness.clock.now < 110
    assert all(row["expected_exit_code"] == 9 for row in harness.records)
