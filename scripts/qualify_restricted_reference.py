#!/usr/bin/env python3
"""Qualify the fixed restricted reference on its authorized remote CPU family."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import platform
import secrets
import sys
import time
from pathlib import Path

# This file and this checkout are trusted TCB, never supplied through a guest argument.
_SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SOURCE / "src"))
from tickwitness.infrastructure.restricted_reference import (  # noqa: E402
    CONTROL_VALUES,
    PROBE_NAMES,
    ReferenceRunner,
    validate_mounts,
)

START_KIND = "restricted_reference_started_v1"
RESULT_KIND = "restricted_reference_payload_v1"
_FIELDS = {
    "positive": {"input_read", "scratch_roundtrip"},
    "filesystem": {"attempts", "link_replacement_attempts", "link_replacement_denials"},
    "readonly": {"attempts", "input_sha256_before", "input_sha256_after"},
    "environment": {
        "environment_keys", "unexpected_keys", "secret_canaries_absent", "home", "tmpdir",
    },
    "identity": {"uid", "gid", "groups", "no_new_privs", "seccomp", "cap_eff"},
    "network_ipv4": {"attempts", "denial_stage", "external_packets_requested"},
    "network_ipv6": {"attempts", "denial_stage", "external_packets_requested"},
    "network_dns": {"attempts", "denial_stage", "external_packets_requested"},
    "network_loopback": {"attempts", "denial_stage", "external_packets_requested"},
    "inherited_fds": {"attempts"},
    "memory": {"allocation_failed", "allocated_chunks"},
    "pids": {
        "threads_created", "thread_limit_observed", "thread_release_confirmed",
        "children_created", "fork_errno",
    },
    "disk_bytes": {"files_created", "bytes_written", "write_errno"},
    "inodes": {"files_created", "bytes_written", "write_errno"},
    "fds": {"opened_descriptors", "open_errno"},
    "file_size": {"bytes_written", "write_errno"},
    "detached": {
        "descendant_pid", "descendant_sid", "sigterm_ignored", "heartbeat_nonce", "double_fork",
    },
    "namespace_denial": {"attempts"},
    "privileged_syscalls": {"attempts"},
    "abi_denial": {"attempts", "tested_abi_route"},
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Missing actual " + label)
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError("Missing actual integer " + label)
    return value


def _counter(snapshot: dict[str, object], file: str, key: str) -> int:
    return _integer(_mapping(snapshot.get(file), file).get(key), file + ":" + key)


def _delta(before: dict[str, object], after: dict[str, object], file: str, key: str) -> int:
    value = _counter(after, file, key) - _counter(before, file, key)
    if value < 0:
        raise ValueError("Actual controller counter regressed")
    return value


def _identity(status: object) -> bool:
    value = _mapping(status, "host process status")
    return (
        str(value.get("Uid", "")).split() == ["61184"] * 4
        and str(value.get("Gid", "")).split() == ["61184"] * 4
        and str(value.get("Groups", "")).split() == []
        and value.get("NoNewPrivs") == "1"
        and all(int(str(value.get(key, "-1")), 16) == 0 for key in ("CapEff", "CapPrm", "CapAmb"))
    )


def payload_facts(result: dict[str, object], name: str, nonce: str) -> dict[str, object]:
    output = result.get("stdout")
    if not isinstance(output, str) or len(output.encode("utf-8")) > 196_608:
        raise ValueError("Missing bounded actual payload output")
    lines = output.splitlines()
    if len(lines) != 2:
        raise ValueError("Payload result line count differs")
    start = json.loads(lines[0])
    if start != {"kind": START_KIND, "name": name, "nonce": nonce}:
        raise ValueError("Payload readiness identity differs")
    document = _mapping(json.loads(lines[1]), "payload result")
    if set(document) != {"kind", "name", "nonce", "facts"} or (
        document["kind"] != RESULT_KIND or document["name"] != name or document["nonce"] != nonce
    ):
        raise ValueError("Payload result identity or fields differ")
    facts = _mapping(document["facts"], "payload facts")
    if name not in _FIELDS or set(facts) != _FIELDS[name]:
        raise ValueError("Payload facts contain missing or unknown fields")
    return facts


def _all_denied(value: object, *, allowed: set[int], count: int) -> bool:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError("Actual denial case count differs")
    identifiers = []
    for item in value:
        record = _mapping(item, "denial observation")
        if set(record) not in (
            {"operation", "result", "errno"}, {"syscall_number", "result", "errno"}
        ):
            raise ValueError("Actual denial fields differ")
        identifier = record.get("operation", record.get("syscall_number"))
        if not isinstance(identifier, (str, int)) or isinstance(identifier, bool):
            raise ValueError("Actual denial identifier differs")
        identifiers.append(identifier)
        if (
            _integer(record["result"], "denial result") != -1
            or _integer(record["errno"], "denial errno") not in allowed
        ):
            return False
    if len(set(identifiers)) != count:
        raise ValueError("Duplicate actual denial identifiers")
    return True


def _readonly_denials(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Readonly denial count differs")
    expected = {"input_write", "input_replace", "runtime_write", "root_create"}
    rows = [_mapping(item, "readonly denial") for item in value]
    if {row.get("operation") for row in rows} != expected:
        raise ValueError("Readonly operations differ")
    for row in rows:
        allowed = {errno.EROFS, errno.EPERM, errno.EACCES}
        if row["operation"] == "input_replace":
            allowed.add(errno.EXDEV)
        if not _all_denied([row], allowed=allowed, count=1):
            return False
    return True


def _syscall_denials(value: object, *, name: str, count: int) -> bool:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError("Syscall denial count differs")
    expected = {
        "namespace_denial": {272, 308, 165, 435},
        "privileged_syscalls": {319, 447, 425, 426, 427, 29, 64, 68, 101, 321, 144},
        "abi_denial": {0x40000000 | 39},
    }
    rows = [_mapping(item, "syscall denial") for item in value]
    if {row.get("syscall_number") for row in rows} != expected[name]:
        raise ValueError("Actual fixed syscall set differs")
    for row in rows:
        allowed = {errno.ENOSYS} if row["syscall_number"] == 435 else {errno.EPERM}
        if not _all_denied([row], allowed=allowed, count=1):
            return False
    return True


def _namespace_ids(value: object, label: str) -> list[int]:
    if not isinstance(value, str):
        raise ValueError("Missing actual namespace " + label)
    fields = value.split()
    if len(fields) < 2 or any(not item.isdecimal() for item in fields):
        raise ValueError("Missing separate host and guest namespace IDs")
    return [int(item) for item in fields]


def _detached_proof(host: dict[str, object], facts: dict[str, object], nonce: str) -> bool:
    pid = _integer(facts["descendant_pid"], "detached guest PID")
    sid = _integer(facts["descendant_sid"], "detached guest SID")
    if (
        pid <= 1 or sid <= 1 or pid == sid
        or facts["double_fork"] is not True or facts["sigterm_ignored"] is not True
        or facts["heartbeat_nonce"] != nonce
    ):
        return False
    snapshots = host.get("active_member_observations")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("Detached task membership was not independently observed")
    last = [
        _mapping(row, "membership sample")
        for row in snapshots
        if isinstance(row, dict) and row.get("phase") == "before_kill"
    ]
    if len(last) != 1 or not isinstance(last[0].get("members"), list):
        raise ValueError("Unique before-kill task observation is unavailable")
    matching = []
    for raw in last[0]["members"]:
        member = _mapping(raw, "live task member")
        if member.get("observation", True) is None:
            continue
        namespace_pids = _namespace_ids(member.get("namespace_pids"), "PIDs")
        if namespace_pids[-1] == pid:
            matching.append(member)
    if len(matching) != 1:
        raise ValueError("Detached guest PID was not uniquely observed before kill")
    member = matching[0]
    namespace_pids = _namespace_ids(member["namespace_pids"], "PIDs")
    namespace_sids = _namespace_ids(member.get("namespace_session_ids"), "SIDs")
    ignored = str(member.get("signal_ignored", ""))
    live = str(member.get("state", "")).split()
    if (
        namespace_pids[0] != member.get("pid") or namespace_sids[0] != member.get("sid_host")
        or namespace_sids[-1] != sid or not int(ignored, 16) & (1 << 14)
        or member.get("ignores_sigterm") is not True or not live or live[0] in {"Z", "X"}
        or str(member.get("uid", "")).split() != ["61184"] * 4
    ):
        return False
    scratch = _mapping(host.get("scratch_after"), "scratch")
    named = _mapping(scratch.get("named_files"), "named scratch observations")
    heartbeat = _mapping(named.get("heartbeat"), "stopped heartbeat file")
    raw = heartbeat.get("text")
    if not isinstance(raw, str) or len(raw.encode()) > 1024:
        raise ValueError("Actual stopped heartbeat bytes are unavailable")
    if heartbeat.get("is_regular") is not True:
        raise ValueError("Stopped heartbeat is not an observed regular file")
    if heartbeat.get("size") != len(raw.encode()) or heartbeat.get("sha256") != _sha(raw.encode()):
        raise ValueError("Actual stopped heartbeat byte binding differs")
    document = _mapping(json.loads(raw), "stopped heartbeat JSON")
    if set(document) != {"nonce", "guest_pid", "guest_sid", "sigign", "ticks"}:
        raise ValueError("Stopped heartbeat fields differ")
    ticks = document["ticks"]
    return (
        document["nonce"] == nonce and document["guest_pid"] == pid and document["guest_sid"] == sid
        and document["sigign"] == ignored and isinstance(ticks, str) and len(ticks) == 20
        and ticks.isdecimal() and int(ticks) > 0
    )


def _common(
    result: dict[str, object], name: str, nonce: str, manifest_sha256: str
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    if result.get("name") != name or result.get("nonce") != nonce:
        raise ValueError("Actual execution identity differs")
    if result.get("started") is not True or result.get("payload_started") is not True:
        raise ValueError("Fixed payload did not pass its actual host observation gate")
    if result.get("stop_confirmed") is not True or result.get("cleanup_confirmed") is not True:
        raise ValueError("Actual complete stop or cleanup remains unconfirmed")
    if result.get("failure") in {
        "setup_refused", "host_observation_failed", "stop_unconfirmed", "cleanup_unconfirmed"
    }:
        raise ValueError("Required actual host control or observation failed")
    if result.get("failure") not in {None, "deadline_exceeded", "stdout_limit", "stderr_limit"}:
        raise ValueError("Unknown execution failure code")
    _integer(result.get("actual_exit_code"), "exit code")
    host = _mapping(result.get("host_facts"), "host facts")
    if host.get("manifest_sha256") != manifest_sha256:
        raise ValueError("Actual execution is not bound to the original host tuple")
    before = _mapping(host.get("cgroup_before"), "pre-probe cgroup")
    after = _mapping(host.get("cgroup_after"), "post-stop cgroup")
    if any(
        before.get(key) != value or after.get(key) != value
        for key, value in CONTROL_VALUES.items()
    ):
        raise ValueError("Actual original resource readback differs")
    if _counter(after, "cgroup.events", "populated") != 0 or after.get("cgroup.procs") != []:
        raise ValueError("Owned cgroup is not independently confirmed empty")
    bootstrap = _mapping(host.get("bootstrap_admission"), "bootstrap admission")
    if not _identity(bootstrap.get("host_status")):
        raise ValueError("Actual pre-exec host identity differs")
    guest = _mapping(host.get("guest_process_observation"), "guest process observation")
    if (
        not _identity(guest.get("status"))
        or _mapping(guest.get("status"), "status").get("Seccomp") != "2"
    ):
        raise ValueError("Actual final task identity or seccomp observation differs")
    descriptors = _mapping(guest.get("descriptors"), "final descriptors")
    if set(descriptors) != {"0", "1", "2"} or any(
        not isinstance(value, str) or not value.startswith("pipe:[")
        for value in descriptors.values()
    ):
        raise ValueError("Actual task inherited unexpected descriptors")
    mounts = host.get("mounts")
    if (
        not isinstance(mounts, list)
        or guest.get("mounts_validated") is not True
        or not validate_mounts(mounts)
    ):
        raise ValueError("Actual mount isolation is missing or differs")
    protected = _mapping(host.get("canaries_before"), "protected pre-probe canaries")
    if not protected or protected != _mapping(
        host.get("canaries_after"), "protected post-probe canaries"
    ):
        raise RuntimeError("Protected host or immutable input canary changed")
    for stream in ("stdout", "stderr"):
        retained = _integer(host.get(stream + "_retained_bytes"), stream + " retained bytes")
        if not 0 <= retained <= 65_536:
            raise RuntimeError("Host retained output exceeded its frozen bound")
    return host, before, after


def _assess_normal(
    name: str, facts: dict[str, object], host: dict[str, object],
    before: dict[str, object], after: dict[str, object]
) -> bool:
    if name == "positive":
        return facts["input_read"] is True and facts["scratch_roundtrip"] is True
    if name == "filesystem":
        return (
            _all_denied(
                facts["attempts"],
                allowed={errno.EPERM, errno.EACCES, errno.ENOENT, errno.ELOOP}, count=8,
            )
            and facts["link_replacement_attempts"] == 128
            and facts["link_replacement_denials"] == 128
        )
    if name == "readonly":
        return (
            _readonly_denials(facts["attempts"])
            and facts["input_sha256_before"] == facts["input_sha256_after"]
        )
    if name == "environment":
        return (
            host.get("launcher_secret_present") is True
            and facts["secret_canaries_absent"] is True
            and facts["unexpected_keys"] == []
            and facts["home"] == "/nonexistent"
            and facts["tmpdir"] == "/tmp"
        )
    if name == "identity":
        return (
            facts["uid"] == 61184 and facts["gid"] == 61184 and facts["groups"] == []
            and facts["no_new_privs"] == 1 and facts["seccomp"] == 2
            and int(str(facts["cap_eff"]), 16) == 0
        )
    if name.startswith("network_"):
        counts = {"network_ipv4": 1, "network_ipv6": 1, "network_dns": 2, "network_loopback": 4}
        return (
            _all_denied(facts["attempts"], allowed={errno.EPERM}, count=counts[name])
            and facts["denial_stage"] == "socket_creation_before_connect_send_or_resolver_transport"
            and facts["external_packets_requested"] is False
        )
    if name == "inherited_fds":
        observed = _mapping(host.get("fd_canary_observation"), "host descriptor canaries")
        return (
            observed.get("socket_fd") == 200 and observed.get("file_fd") == 201
            and observed.get("preconnected_inheritable") is True
            and all(observed.get(key) is True for key in (
                "socket_preconnected", "socket_inheritable", "file_inheritable",
                "socket_is_socket", "file_is_regular", "file_unchanged",
            ))
            and observed.get("unexpected_socket_bytes") == 0
            and observed.get("socket_received_bytes") == 0
            and _all_denied(facts["attempts"], allowed={errno.EBADF}, count=4)
        )
    if name == "pids":
        return (
            facts["fork_errno"] == errno.EAGAIN
            and _integer(facts["children_created"], "created children") > 0
            and _integer(facts["threads_created"], "created threads") > 0
            and facts["thread_limit_observed"] is True
            and facts["thread_release_confirmed"] is True
            and _delta(before, after, "pids.events", "max") >= 2
        )
    if name in {"disk_bytes", "inodes"}:
        scratch = _mapping(host.get("scratch_after"), "actual scratch capacity")
        return (
            facts["write_errno"] == errno.ENOSPC
            and _integer(facts["files_created"], "created files") > 1
            and scratch.get("bytes_total") == 16_777_216
            and scratch.get("inodes_total") == 512
            and (
                _integer(facts["bytes_written"], "written bytes") > 8_388_608
                and _integer(scratch.get("bytes_available"), "remaining scratch bytes") < 1_048_576
                if name == "disk_bytes"
                else facts["bytes_written"] == 0 and scratch.get("inodes_available") == 0
            )
        )
    if name == "fds":
        return (
            facts["open_errno"] == errno.EMFILE
            and _integer(facts["opened_descriptors"], "opened descriptors") > 0
        )
    if name == "file_size":
        return facts["write_errno"] == errno.EFBIG and facts["bytes_written"] == 8_388_608
    if name in {"namespace_denial", "privileged_syscalls", "abi_denial"}:
        counts = {"namespace_denial": 4, "privileged_syscalls": 11, "abi_denial": 1}
        passed = _syscall_denials(facts["attempts"], name=name, count=counts[name])
        if name == "abi_denial":
            return passed and facts["tested_abi_route"] == "x32_getpid"
        return passed
    raise ValueError("Unknown normal fixed-case assessment")


def assess_probe(
    result: dict[str, object], name: str, nonce: str, manifest_sha256: str
) -> dict[str, str]:
    """Interpret a real execution without turning missing evidence into a pass."""
    try:
        if name not in PROBE_NAMES:
            raise ValueError("Unknown fixed probe")
        host, before, after = _common(result, name, nonce, manifest_sha256)
        if name == "memory":
            observed_oom = _delta(before, after, "memory.events", "oom") > 0
            observed_kill = _delta(before, after, "memory.events", "oom_kill") > 0
            passed = observed_oom and observed_kill and result["actual_exit_code"] in {-9, 137}
        elif name == "cpu":
            passed = (
                result.get("failure") == "deadline_exceeded"
                and _delta(before, after, "cpu.stat", "usage_usec") > 0
                and _delta(before, after, "cpu.stat", "nr_throttled") > 0
            )
        elif name == "detached":
            facts = payload_facts(result, name, nonce)
            passed = (
                result.get("failure") == "deadline_exceeded"
                and _detached_proof(host, facts, nonce)
            )
        elif name == "output_flood":
            passed = (
                result.get("failure") in {"stdout_limit", "stderr_limit"}
                and (
                    result.get("stdout_truncated") is True
                    or result.get("stderr_truncated") is True
                )
            )
        elif name == "stdio_closed":
            passed = result["actual_exit_code"] == 0 and result.get("failure") is None
        elif name == "malformed_output":
            if result["actual_exit_code"] != 0 or result.get("failure") is not None:
                raise ValueError(
                    "Malformed output probe did not finish inside the observed controls"
                )
            try:
                payload_facts(result, name, nonce)
            except (ValueError, TypeError):
                passed = True
            else:
                passed = False
        else:
            if result["actual_exit_code"] != 0 or result.get("failure") is not None:
                raise ValueError("No completed actual fixed payload result")
            facts = payload_facts(result, name, nonce)
            passed = _assess_normal(name, facts, host, before, after)
        return {
            "status": "PASS" if passed else "FAIL",
            "reason": (
                "actual_scoped_control_evidence" if passed else "actual_control_expectation_not_met"
            ),
        }
    except RuntimeError as error:
        return {"status": "FAIL", "reason": str(error)}
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return {"status": "UNKNOWN", "reason": str(error)}


def remote_guard() -> None:
    if (
        sys.platform != "linux" or platform.machine() != "x86_64" or os.geteuid() != 0
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise ValueError(
            "Qualification requires its explicit root GitHub-hosted Linux remote profile"
        )


def admission_accounting(cases: list[dict[str, object]]) -> dict[str, object]:
    charged = sum(case.get("admission_submitted") is True for case in cases)
    confirmed = 0
    observed_starts = 0
    for case in cases:
        execution = case.get("execution")
        if not isinstance(execution, dict):
            continue
        observed_starts += int(execution.get("payload_started") is True)
        facts = execution.get("host_facts")
        number = facts.get("admission_number") if isinstance(facts, dict) else None
        confirmed += int(type(number) is int and 1 <= number <= 24)
    return {
        "admissions_charged": charged,
        "confirmed_backend_admissions": confirmed,
        "unconfirmed_admission_outcomes": charged - confirmed,
        "observed_payload_starts": observed_starts,
        "admission_accounting_scope": (
            "Submitted fixed-launcher calls charged once; unknown outcomes not refunded. "
            "Observed payload starts are separate from submissions or confirmed admission."
        ),
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    cases = report.get("cases")
    if isinstance(cases, list):
        report.update(admission_accounting(cases))
    raw = json.dumps(report, sort_keys=True, indent=2).encode() + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    path.chmod(0o644)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        remote_guard()
    except ValueError as error:
        sys.stderr.write(str(error) + "\n")
        return 2
    evidence = args.evidence_dir.absolute()
    started = time.monotonic_ns()
    deadline = started + 600_000_000_000
    cases: list[dict[str, object]] = []
    report: dict[str, object] = {
        "kind": "restricted_reference_qualification_v1",
        "controls_status": "NOT_QUALIFIED",
        "production_m1": "DISABLED",
        "independent_human_security_review": "NOT_PERFORMED",
        "external_human_reproduction": "0/0/PENDING",
        "research_reservations": 0,
        "replay_engine_invocations": 0,
        "driver_sha256": _sha(Path(__file__).read_bytes()),
        "payload_sha256": _sha(
            Path(__file__).with_name("restricted_reference_payload.py").read_bytes()
        ),
        "original_qualification_budget": {"max_admissions": 24, "window_ns": 600_000_000_000},
        "cases": cases,
        "scope": (
            "Fixed synthetic reference controls only; no product isolation admission, research "
            "finding, arbitrary strategy support or independent human approval"
        ),
    }
    try:
        runner = ReferenceRunner(
            evidence, Path(__file__).with_name("restricted_reference_payload.py")
        )
        if runner.manifest.get("fixed_cases") != list(PROBE_NAMES):
            raise ValueError("Frozen manifest fixed-case catalog differs")
        if len(PROBE_NAMES) > 24 or len(set(PROBE_NAMES)) != len(PROBE_NAMES):
            raise ValueError("Fixed-case admission catalog differs")
        report["manifest_sha256"] = runner.manifest_sha256
        write_report(evidence / "report.json", report)
        stopped = False
        for name in PROBE_NAMES:
            if stopped or time.monotonic_ns() >= deadline:
                cases.append({
                    "name": name, "admission_submitted": False, "status": "UNKNOWN",
                    "reason": "not_admitted_after_original_window_or_uncertainty",
                })
                continue
            nonce = secrets.token_hex(16)
            case: dict[str, object] = {
                "name": name, "nonce": nonce, "admission_submitted": True,
                "status": "UNKNOWN", "reason": "execution_outcome_unavailable",
            }
            cases.append(case)
            write_report(evidence / "report.json", report)
            result = runner.run_probe(name, arguments=(nonce,))
            assessment = assess_probe(result, name, nonce, runner.manifest_sha256)
            case.update({**assessment, "execution": result})
            write_report(evidence / "report.json", report)
            if assessment["status"] != "PASS":
                stopped = True
        all_passed = (
            len(cases) == len(PROBE_NAMES) and all(case["status"] == "PASS" for case in cases)
        )
        report["controls_status"] = "QUALIFIED_REFERENCE_ONLY" if all_passed else "NOT_QUALIFIED"
        report.update(admission_accounting(cases))
        report["completed_at_monotonic_ns"] = time.monotonic_ns()
        write_report(evidence / "report.json", report)
        sys.stdout.write(json.dumps({
            "controls_status": report["controls_status"], "production_m1": "DISABLED",
            "admissions_charged": report["admissions_charged"],
            "observed_payload_starts": report["observed_payload_starts"],
            "manifest_sha256": runner.manifest_sha256,
        }) + "\n")
        return 0 if all_passed else 1
    except Exception as error:
        admitted_names = {case["name"] for case in cases}
        for name in PROBE_NAMES:
            if name not in admitted_names:
                cases.append({
                    "name": name, "admission_submitted": False, "status": "UNKNOWN",
                    "reason": "not_admitted_after_harness_failure",
                })
        report["failure"] = {"type": type(error).__name__, "reason": str(error)[:2048]}
        report.update(admission_accounting(cases))
        if evidence.is_dir() and not evidence.is_symlink():
            write_report(evidence / "report.json", report)
        sys.stderr.write("restricted_reference_not_qualified: " + type(error).__name__ + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
