"""Pure decision regressions for actual evidence and uncertain qualification admission.

These tests never launch an OS probe, require privileges or qualify isolation. The
separate remote reference workflow supplies real kernel evidence.
"""

from __future__ import annotations

import copy
import errno
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "qualify_restricted_reference.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_reference_qualification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)

NONCE = "a" * 32
MANIFEST = "b" * 64


def process_status() -> dict[str, str]:
    return {
        "Uid": "61184 61184 61184 61184",
        "Gid": "61184 61184 61184 61184",
        "Groups": "",
        "NoNewPrivs": "1",
        "Seccomp": "2",
        "CapEff": "0000000000000000",
        "CapPrm": "0000000000000000",
        "CapAmb": "0000000000000000",
    }


def snapshot() -> dict[str, object]:
    return {
        **qualification.CONTROL_VALUES,
        "cpu.stat": {"usage_usec": 0, "nr_throttled": 0},
        "memory.events": {"oom": 0, "oom_kill": 0},
        "pids.events": {"max": 0},
        "cgroup.events": {"populated": 0},
        "cgroup.procs": [],
        "pids.peak": 1,
    }


def record(name: str = "positive", facts: dict[str, object] | None = None) -> dict[str, object]:
    if facts is None:
        facts = {"input_read": True, "scratch_roundtrip": True}
    start = {"kind": qualification.START_KIND, "name": name, "nonce": NONCE}
    final = {"kind": qualification.RESULT_KIND, "name": name, "nonce": NONCE, "facts": facts}
    mounts = [
        {"path": path, "options": ["rw" if path == "/scratch" else "ro"], "filesystem": "tmpfs"}
        for path in ("/", "/usr", "/proc", "/input", "/scratch")
    ]
    return {
        "name": name,
        "nonce": NONCE,
        "started": True,
        "payload_started": True,
        "actual_exit_code": 0,
        "stdout": json.dumps(start) + "\n" + json.dumps(final) + "\n",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stop_confirmed": True,
        "cleanup_confirmed": True,
        "failure": None,
        "stop_reason": None,
        "host_facts": {
            "manifest_sha256": MANIFEST,
            "admission_number": 1,
            "cgroup_before": snapshot(),
            "cgroup_after": snapshot(),
            "bootstrap_admission": {"host_status": process_status()},
            "guest_process_observation": {
                "status": process_status(),
                "descriptors": {"0": "pipe:[1]", "1": "pipe:[2]", "2": "pipe:[3]"},
                "mounts_validated": True,
            },
            "mounts": mounts,
            "canaries_before": {"outside_sha256": "c" * 64},
            "canaries_after": {"outside_sha256": "c" * 64},
            "stdout_retained_bytes": 1024,
            "stderr_retained_bytes": 0,
        },
    }


def assess(value: dict[str, object]) -> dict[str, str]:
    return qualification.assess_probe(value, value["name"], NONCE, MANIFEST)


def test_completed_positive_requires_host_observations_not_only_exit() -> None:
    value = record()
    assert assess(value)["status"] == "PASS"
    value["host_facts"]["guest_process_observation"] = None
    assert assess(value)["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "field", ["started", "payload_started", "stop_confirmed", "cleanup_confirmed"]
)
def test_missing_execution_or_stop_proof_never_passes(field: str) -> None:
    value = record()
    value[field] = False
    assert assess(value)["status"] == "UNKNOWN"


def test_manifest_change_and_nonempty_task_are_unknown() -> None:
    value = record()
    value["host_facts"]["manifest_sha256"] = "d" * 64
    assert assess(value)["status"] == "UNKNOWN"
    value = record()
    value["host_facts"]["cgroup_after"]["cgroup.events"]["populated"] = 1
    assert assess(value)["status"] == "UNKNOWN"


def test_canary_change_is_a_failure_even_with_successful_payload() -> None:
    value = record()
    value["host_facts"]["canaries_after"]["outside_sha256"] = "e" * 64
    assert assess(value)["status"] == "FAIL"


def test_extra_writable_mount_prevents_qualification() -> None:
    value = record()
    value["host_facts"]["mounts"].append(
        {"path": "/writable", "options": ["rw"], "filesystem": "tmpfs"}
    )
    assert assess(value)["status"] == "UNKNOWN"


def test_unexpected_final_descriptor_prevents_qualification() -> None:
    value = record()
    value["host_facts"]["guest_process_observation"]["descriptors"]["200"] = "socket:[9]"
    assert assess(value)["status"] == "UNKNOWN"


def test_unknown_payload_field_and_stale_nonce_do_not_change_semantics() -> None:
    value = record(facts={"input_read": True, "scratch_roundtrip": True, "qualified": True})
    assert assess(value)["status"] == "UNKNOWN"
    value = record()
    value["stdout"] = value["stdout"].replace(NONCE, "f" * 32)
    assert assess(value)["status"] == "UNKNOWN"


def test_forged_output_has_no_host_authority() -> None:
    value = record()
    value["stdout"] = (
        json.dumps({"kind": qualification.START_KIND, "name": "positive", "nonce": NONCE})
        + '\n{"kind":"forged_host_receipt","qualified":true}\n'
    )
    assert assess(value)["status"] == "UNKNOWN"


def test_sigkill_or_exit137_alone_is_not_oom_evidence() -> None:
    value = record("memory")
    value["actual_exit_code"] = 137
    assert assess(value)["status"] == "FAIL"
    value["host_facts"]["cgroup_after"]["memory.events"] = {"oom": 1, "oom_kill": 1}
    assert assess(value)["status"] == "PASS"


def test_pid_negative_requires_both_thread_and_process_exhaustion() -> None:
    facts = {
        "threads_created": 20,
        "thread_limit_observed": True,
        "thread_release_confirmed": True,
        "children_created": 20,
        "fork_errno": errno.EAGAIN,
    }
    value = record("pids", facts)
    value["host_facts"]["cgroup_after"]["pids.events"]["max"] = 1
    assert assess(value)["status"] == "FAIL"
    value["host_facts"]["cgroup_after"]["pids.events"]["max"] = 2
    assert assess(value)["status"] == "PASS"


def test_cross_mount_rename_denial_is_scoped_to_its_operation() -> None:
    attempts = [
        {
            "operation": name,
            "result": -1,
            "errno": errno.EXDEV if name == "input_replace" else errno.EROFS,
        }
        for name in ("input_write", "input_replace", "runtime_write", "root_create")
    ]
    value = record(
        "readonly",
        {"attempts": attempts, "input_sha256_before": "a", "input_sha256_after": "a"},
    )
    assert assess(value)["status"] == "PASS"
    attempts[0]["errno"] = errno.EXDEV
    value = record(
        "readonly",
        {"attempts": attempts, "input_sha256_before": "a", "input_sha256_after": "a"},
    )
    assert assess(value)["status"] == "FAIL"


def test_clone3_uses_selected_enosys_while_other_namespace_denials_require_eperm() -> None:
    attempts = [
        {
            "syscall_number": number,
            "result": -1,
            "errno": errno.ENOSYS if number == 435 else errno.EPERM,
        }
        for number in (272, 308, 165, 435)
    ]
    value = record("namespace_denial", {"attempts": attempts})
    assert assess(value)["status"] == "PASS"
    attempts[0]["errno"] = errno.ENOSYS
    assert assess(record("namespace_denial", {"attempts": attempts}))["status"] == "FAIL"


def test_cpu_throttle_without_original_deadline_stop_is_insufficient() -> None:
    value = record("cpu")
    value["host_facts"]["cgroup_after"]["cpu.stat"] = {"usage_usec": 250000, "nr_throttled": 2}
    assert assess(value)["status"] == "FAIL"
    value["failure"] = "deadline_exceeded"
    assert assess(value)["status"] == "PASS"


def test_detached_stop_pairs_guest_ids_with_kernel_session_and_stopped_heartbeat() -> None:
    facts = {
        "descendant_pid": 7,
        "descendant_sid": 6,
        "sigterm_ignored": True,
        "double_fork": True,
        "heartbeat_nonce": NONCE,
    }
    value = record("detached", facts)
    value["failure"] = "deadline_exceeded"
    value["host_facts"]["cgroup_after"]["pids.peak"] = 100
    assert assess(value)["status"] == "UNKNOWN"
    member = {
        "pid": 207,
        "sid_host": 206,
        "namespace_pids": "207 7",
        "namespace_session_ids": "206 6",
        "signal_ignored": "0000000000004000",
        "ignores_sigterm": True,
        "uid": "61184 61184 61184 61184",
        "state": "S (sleeping)",
    }
    value["host_facts"]["active_member_observations"] = [
        {"phase": "before_kill", "members": [member]}
    ]
    heartbeat = json.dumps(
        {
            "nonce": NONCE,
            "guest_pid": 7,
            "guest_sid": 6,
            "sigign": "0000000000004000",
            "ticks": "00000000000000000020",
        }
    )
    value["host_facts"]["scratch_after"] = {
        "named_files": {
            "heartbeat": {
                "text": heartbeat,
                "size": len(heartbeat.encode()),
                "sha256": qualification._sha(heartbeat.encode()),
                "is_regular": True,
            }
        }
    }
    assert assess(value)["status"] == "PASS"
    member["namespace_session_ids"] = "206 207"
    assert assess(value)["status"] == "FAIL"
    member["namespace_session_ids"] = "206 6"
    member["ignores_sigterm"] = False
    assert assess(value)["status"] == "FAIL"


def test_output_overflow_needs_actual_truncation_and_stop_reason() -> None:
    value = record("output_flood")
    value["stdout_truncated"] = True
    assert assess(value)["status"] == "FAIL"
    value["failure"] = "stdout_limit"
    assert assess(value)["status"] == "PASS"
    value["host_facts"]["stdout_retained_bytes"] = 65537
    assert assess(value)["status"] == "FAIL"


def test_malformed_case_passes_only_as_scoped_rejection_under_observed_controls() -> None:
    value = record("malformed_output")
    value["stdout"] = (
        json.dumps({"kind": qualification.START_KIND, "name": "malformed_output", "nonce": NONCE})
        + '\n{"kind":"forged_host_receipt","qualified":true}\n{not-json\n'
    )
    assert assess(value)["status"] == "PASS"
    value["failure"] = "host_observation_failed"
    assert assess(value)["status"] == "UNKNOWN"


def test_x32_kernel_enosys_is_not_seccomp_denial_proof() -> None:
    value = record(
        "abi_denial",
        {
            "attempts": [
                {
                    "syscall_number": 0x40000000 | 39,
                    "result": -1,
                    "errno": errno.ENOSYS,
                }
            ],
            "tested_abi_route": "x32_getpid",
        },
    )
    assert assess(value)["status"] == "FAIL"
    value["stdout"] = value["stdout"].replace(f'"errno": {errno.ENOSYS}', f'"errno": {errno.EPERM}')
    assert assess(value)["status"] == "PASS"


def test_boolean_errno_is_not_an_observed_integer_denial() -> None:
    value = record(
        "abi_denial",
        {
            "attempts": [{"syscall_number": 0x40000000 | 39, "result": -1, "errno": True}],
            "tested_abi_route": "x32_getpid",
        },
    )
    assert assess(value)["status"] == "UNKNOWN"


def test_inherited_fd_absence_requires_real_offered_socket_canary() -> None:
    facts = {
        "attempts": [
            {"operation": name, "result": -1, "errno": errno.EBADF}
            for name in ("socket_stat", "socket_write", "file_stat", "file_write")
        ]
    }
    value = record("inherited_fds", facts)
    value["host_facts"]["fd_canary_observation"] = {
        "socket_fd": 200,
        "file_fd": 201,
        "preconnected_inheritable": False,
        "unexpected_socket_bytes": 0,
        "socket_received_bytes": 0,
        "socket_preconnected": True,
        "socket_inheritable": True,
        "file_inheritable": True,
        "socket_is_socket": True,
        "file_is_regular": True,
        "file_unchanged": True,
    }
    assert assess(value)["status"] == "FAIL"
    value["host_facts"]["fd_canary_observation"]["preconnected_inheritable"] = True
    assert assess(value)["status"] == "PASS"


@pytest.mark.parametrize("raises_after_submission", [False, True])
def test_failed_or_uncertain_admission_is_counted_once_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raises_after_submission: bool
) -> None:
    admitted: list[str] = []

    class FakeRunner:
        def __init__(self, evidence: Path, payload: Path) -> None:
            evidence.mkdir()
            self.manifest = {"fixed_cases": list(qualification.PROBE_NAMES)}
            self.manifest_sha256 = MANIFEST

        def run_probe(self, name: str, arguments: tuple[str, ...]) -> dict[str, object]:
            admitted.append(name)
            if raises_after_submission:
                raise OSError("Outcome cannot be read after admission")
            value = record(name)
            value["nonce"] = arguments[0]
            value["payload_started"] = False
            return value

    monkeypatch.setattr(qualification, "remote_guard", lambda: None)
    monkeypatch.setattr(qualification, "ReferenceRunner", FakeRunner)
    evidence = tmp_path / "evidence"
    assert qualification.main(["--evidence-dir", str(evidence)]) == 1
    report = json.loads((evidence / "report.json").read_bytes())
    assert admitted == [qualification.PROBE_NAMES[0]]
    assert report["admissions_charged"] == 1
    assert report["confirmed_backend_admissions"] == (0 if raises_after_submission else 1)
    assert report["unconfirmed_admission_outcomes"] == (1 if raises_after_submission else 0)
    assert report["observed_payload_starts"] == 0
    assert report["controls_status"] == "NOT_QUALIFIED"
    assert len(report["cases"]) == len(qualification.PROBE_NAMES)
    assert all(case["status"] == "UNKNOWN" for case in report["cases"])
    assert report["cases"][0]["admission_submitted"] is True
    assert all(case["admission_submitted"] is False for case in report["cases"][1:])


def test_nonremote_guard_prevents_even_constructing_the_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    with pytest.raises(ValueError, match="remote profile"):
        qualification.remote_guard()


def test_assessment_does_not_mutate_original_host_evidence() -> None:
    value = record()
    original = copy.deepcopy(value)
    assert assess(value)["status"] == "PASS"
    assert value == original
