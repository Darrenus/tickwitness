#!/usr/bin/env python3
"""Fixed synthetic payloads; run only inside the selected remote reference launcher."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import resource
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

CONTEXT = Path("/input/probe-context.json")
START_KIND = "restricted_reference_started_v1"
RESULT_KIND = "restricted_reference_payload_v1"
PROBE_NAMES = (
    "positive",
    "filesystem",
    "readonly",
    "environment",
    "identity",
    "network_ipv4",
    "network_ipv6",
    "network_dns",
    "network_loopback",
    "inherited_fds",
    "memory",
    "pids",
    "disk_bytes",
    "inodes",
    "fds",
    "file_size",
    "cpu",
    "output_flood",
    "detached",
    "namespace_denial",
    "privileged_syscalls",
    "malformed_output",
    "stdio_closed",
    "abi_denial",
)
_CONTEXT_KEYS = {
    "name",
    "nonce",
    "outside_path",
    "immutable_path",
    "secret_env_keys",
    "fd_socket",
    "fd_file",
    "fd_canary_nonce",
}


def emit(document: object) -> None:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if len(raw) > 16_384:
        raise ValueError("Fixed payload record exceeded its bound")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def status_fields() -> dict[str, str]:
    return {
        key: value.strip()
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def require_guest_gate() -> dict[str, object]:
    if sys.platform != "linux" or os.getuid() != 61184 or os.geteuid() != 61184:
        raise ValueError("Selected guest identity is absent")
    status = status_fields()
    if (
        os.getgid() != 61184
        or os.getegid() != 61184
        or os.getgroups()
        or status.get("NoNewPrivs") != "1"
        or status.get("Seccomp") != "2"
        or int(status.get("CapEff", "-1"), 16) != 0
    ):
        raise ValueError("Selected guest privilege controls are absent")
    for symbol, value in (
        (resource.RLIMIT_NOFILE, 64),
        (resource.RLIMIT_FSIZE, 8_388_608),
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_RTPRIO, 0),
    ):
        if resource.getrlimit(symbol) != (value, value):
            raise ValueError("Selected guest hard and soft limits are absent")
    if os.environ.get("TICKWITNESS_REFERENCE") != "restricted_reference_v1":
        raise ValueError("Selected guest environment is absent")
    return {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "groups": os.getgroups(),
        "no_new_privs": 1,
        "seccomp": 2,
        "cap_eff": status["CapEff"],
    }


def read_context(name: str, nonce: str) -> dict[str, object]:
    raw = CONTEXT.read_bytes()
    if len(raw) > 8192:
        raise ValueError("Probe context exceeded its bound")
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) != _CONTEXT_KEYS:
        raise ValueError("Probe context fields differ")
    if document["name"] != name or document["nonce"] != nonce:
        raise ValueError("Probe context identity differs")
    if document["immutable_path"] != "/input/immutable.txt":
        raise ValueError("Probe immutable locator differs")
    if (
        not isinstance(document["outside_path"], str)
        or not document["outside_path"].startswith("/")
    ):
        raise ValueError("Probe outside canary locator differs")
    if document["fd_socket"] != 200 or document["fd_file"] != 201:
        raise ValueError("Probe inherited descriptor locators differ")
    keys = document["secret_env_keys"]
    if not isinstance(keys, list) or not keys or any(not isinstance(key, str) for key in keys):
        raise ValueError("Probe secret-key canaries differ")
    if not isinstance(document["fd_canary_nonce"], str):
        raise ValueError("Probe descriptor canary differs")
    return document


def denied_operation(label: str, operation: Callable[[], object]) -> dict[str, object]:
    try:
        operation()
    except OSError as error:
        return {"operation": label, "result": -1, "errno": error.errno}
    return {"operation": label, "result": 0, "errno": 0}


def open_and_close(path: str, flags: int) -> None:
    descriptor = os.open(path, flags)
    os.close(descriptor)


def filesystem(context: dict[str, object]) -> dict[str, object]:
    outside = str(context["outside_path"])
    attempts = []
    for path in (outside, "/proc/1/root" + outside, "/proc/self/root" + outside):
        attempts.append(
            denied_operation(
                "outside_read:" + path, lambda path=path: open_and_close(path, os.O_RDONLY)
            )
        )
    attempts.append(
        denied_operation("outside_write", lambda: open_and_close(outside, os.O_WRONLY))
    )
    link = "/scratch/outside-link"
    os.symlink(outside, link)
    attempts.append(denied_operation("symlink_read", lambda: open_and_close(link, os.O_RDONLY)))
    attempts.append(denied_operation("hardlink", lambda: os.link(outside, "/scratch/hardlink")))
    attempts.append(denied_operation("rename", lambda: os.rename(outside, "/scratch/renamed")))
    attempts.append(
        denied_operation("host_etc_read", lambda: open_and_close("/etc/passwd", os.O_RDONLY))
    )
    race_denials = 0
    for index in range(128):
        candidate = Path("/scratch/race-link")
        candidate.unlink(missing_ok=True)
        candidate.symlink_to(outside if index % 2 else "/proc/1/root" + outside)
        row = denied_operation(
            "link_replacement",
            lambda candidate=candidate: open_and_close(str(candidate), os.O_RDONLY),
        )
        race_denials += int(row["result"] == -1)
    return {
        "attempts": attempts,
        "link_replacement_attempts": 128,
        "link_replacement_denials": race_denials,
    }


def readonly(context: dict[str, object]) -> dict[str, object]:
    immutable = Path(str(context["immutable_path"]))
    before = hashlib.sha256(immutable.read_bytes()).hexdigest()
    attempts = [
        denied_operation("input_write", lambda: open_and_close(str(immutable), os.O_WRONLY)),
        denied_operation("input_replace", lambda: os.rename(str(immutable), "/scratch/input")),
        denied_operation("runtime_write", lambda: open_and_close("/usr/bin/python3", os.O_WRONLY)),
        denied_operation(
            "root_create", lambda: open_and_close("/created", os.O_CREAT | os.O_WRONLY)
        ),
    ]
    return {
        "attempts": attempts,
        "input_sha256_before": before,
        "input_sha256_after": hashlib.sha256(immutable.read_bytes()).hexdigest(),
    }


def network(name: str) -> dict[str, object]:
    configurations = {
        "network_ipv4": ((socket.AF_INET, socket.SOCK_STREAM, "ipv4_tcp"),),
        "network_ipv6": ((socket.AF_INET6, socket.SOCK_STREAM, "ipv6_tcp"),),
        "network_dns": (
            (socket.AF_INET, socket.SOCK_DGRAM, "dns_ipv4_udp_transport"),
            (socket.AF_INET6, socket.SOCK_DGRAM, "dns_ipv6_udp_transport"),
        ),
        "network_loopback": (
            (socket.AF_INET, socket.SOCK_STREAM, "ipv4_loopback_transport"),
            (socket.AF_INET6, socket.SOCK_STREAM, "ipv6_loopback_transport"),
            (socket.AF_UNIX, socket.SOCK_STREAM, "unix_socket_transport"),
        ),
    }
    attempts = []
    for family, kind, label in configurations[name]:
        def create(family: int = family, kind: int = kind) -> None:
            value = socket.socket(family, kind)
            value.close()
        attempts.append(denied_operation(label, create))
    if name == "network_loopback":
        def create_pair() -> None:
            left, right = socket.socketpair()
            left.close()
            right.close()
        attempts.append(denied_operation("unix_socketpair", create_pair))
    return {
        "attempts": attempts,
        "denial_stage": "socket_creation_before_connect_send_or_resolver_transport",
        "external_packets_requested": False,
    }


def inherited_fds(context: dict[str, object]) -> dict[str, object]:
    nonce = str(context["fd_canary_nonce"]).encode()
    return {
        "attempts": [
            denied_operation("inherited_socket_fstat", lambda: os.fstat(200)),
            denied_operation("inherited_socket_write", lambda: os.write(200, nonce)),
            denied_operation("inherited_file_fstat", lambda: os.fstat(201)),
            denied_operation("inherited_file_write", lambda: os.pwrite(201, nonce, 0)),
        ]
    }


def memory() -> dict[str, object]:
    allocated = []
    try:
        for _ in range(256):
            allocated.append(bytearray(b"m" * (2 * 1024 * 1024)))
    except MemoryError:
        return {"allocation_failed": True, "allocated_chunks": len(allocated)}
    return {"allocation_failed": False, "allocated_chunks": len(allocated)}


def pids() -> dict[str, object]:
    release = threading.Event()
    threads = []
    thread_limit = False
    for _ in range(64):
        value = threading.Thread(target=release.wait, daemon=True)
        try:
            value.start()
        except RuntimeError:
            thread_limit = True
            break
        threads.append(value)
    release.set()
    for value in threads:
        value.join(timeout=0.5)
    released = all(not value.is_alive() for value in threads)
    if not released:
        raise ValueError("Bounded thread phase did not finish")
    children = []
    failure = 0
    for _ in range(64):
        try:
            child = os.fork()
        except OSError as error:
            failure = error.errno
            break
        if child == 0:
            time.sleep(20)
            os._exit(0)
        children.append(child)
    return {
        "threads_created": len(threads),
        "thread_limit_observed": thread_limit,
        "thread_release_confirmed": released,
        "children_created": len(children),
        "fork_errno": failure,
    }

def exhaust_files(*, inodes: bool) -> dict[str, object]:
    created = 0
    written = 0
    failure = 0
    data = b"d" * 1_048_576
    try:
        for index in range(1024 if inodes else 32):
            with open(f"/scratch/exhaust-{index}", "xb", buffering=0) as output:
                created += 1
                if not inodes:
                    written += output.write(data)
    except OSError as error:
        failure = error.errno
    return {"files_created": created, "bytes_written": written, "write_errno": failure}


def fds() -> dict[str, object]:
    descriptors = []
    failure = 0
    try:
        for _ in range(128):
            descriptors.append(os.open("/input/immutable.txt", os.O_RDONLY))
    except OSError as error:
        failure = error.errno
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    return {"opened_descriptors": len(descriptors), "open_errno": failure}


def file_size() -> dict[str, object]:
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    written = 0
    failure = 0
    try:
        with open("/scratch/oversized", "xb", buffering=0) as output:
            for _ in range(16):
                written += output.write(b"s" * 1_048_576)
    except OSError as error:
        failure = error.errno
    return {"bytes_written": written, "write_errno": failure}


def cpu() -> dict[str, object]:
    for _ in range(2):
        if os.fork() == 0:
            until = time.monotonic() + 20
            while time.monotonic() < until:
                pass
            os._exit(0)
    until = time.monotonic() + 20
    while time.monotonic() < until:
        pass
    return {"unexpected_completed": True}


def output_flood() -> dict[str, object]:
    for _ in range(128):
        os.write(1, b"o" * 4096)
        os.write(2, b"e" * 4096)
    return {"unexpected_completed": True}


def detached(context: dict[str, object]) -> dict[str, object]:
    ready_read, ready_write = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(ready_read)
        os.setsid()
        if os.fork() > 0:
            os.close(ready_write)
            os._exit(0)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        descriptor = os.open(
            "/scratch/heartbeat", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        heartbeat = {
            "nonce": context["nonce"],
            "guest_pid": os.getpid(),
            "guest_sid": os.getsid(0),
            "sigign": status_fields()["SigIgn"],
            "ticks": "00000000000000000000",
        }
        os.pwrite(descriptor, json.dumps(heartbeat, sort_keys=True).encode(), 0)
        evidence = {
            "descendant_pid": os.getpid(),
            "descendant_sid": os.getsid(0),
            "sigterm_ignored": signal.getsignal(signal.SIGTERM) == signal.SIG_IGN,
            "heartbeat_nonce": context["nonce"],
            "double_fork": True,
        }
        os.write(ready_write, json.dumps(evidence).encode())
        os.close(ready_write)
        until = time.monotonic() + 20
        ticks = 0
        while time.monotonic() < until:
            ticks += 1
            heartbeat["ticks"] = f"{ticks:020d}"
            os.pwrite(descriptor, json.dumps(heartbeat, sort_keys=True).encode(), 0)
            time.sleep(0.025)
        os.close(descriptor)
        os._exit(0)
    os.close(ready_write)
    os.waitpid(child, 0)
    raw = os.read(ready_read, 1025)
    os.close(ready_read)
    if not raw or len(raw) > 1024:
        raise ValueError("Detached child did not deliver its bounded readiness")
    evidence = json.loads(raw)
    emit({
        "kind": RESULT_KIND,
        "name": context["name"],
        "nonce": context["nonce"],
        "facts": evidence,
    })
    time.sleep(20)
    return {"unexpected_completed": True}

def syscall(number: int, *arguments: object) -> dict[str, object]:
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    converted = [ctypes.c_long(value) if isinstance(value, int) else value for value in arguments]
    result = library.syscall(ctypes.c_long(number), *converted)
    actual_errno = ctypes.get_errno()
    if result >= 3 and number in {319, 447}:
        os.close(result)
    return {"syscall_number": number, "result": result, "errno": actual_errno}


def syscall_probe(name: str) -> dict[str, object]:
    if name == "abi_denial":
        return {"attempts": [syscall(0x40000000 | 39)], "tested_abi_route": "x32_getpid"}
    if name == "namespace_denial":
        values = (
            (272, (0x10000000,)),
            (308, (-1, 0)),
            (165, (None, b"/scratch", None, 4096, None)),
            (435, (None, 0)),
        )
    else:
        parameter = ctypes.c_int(1)
        values = (
            (319, (b"reference", 0)),
            (447, (0,)),
            (425, (0, None)),
            (426, (-1, 0, 0, 0, None, 0)),
            (427, (-1, 0, None, 0)),
            (29, (0, 4096, 0o1600)),
            (64, (0, 1, 0o1600)),
            (68, (0, 0o1600)),
            (101, (0, 0, None, None)),
            (321, (0, None, 0)),
            (144, (0, 1, ctypes.byref(parameter))),
        )
    return {"attempts": [syscall(number, *arguments) for number, arguments in values]}


def run_probe(
    name: str, context: dict[str, object], identity: dict[str, object]
) -> dict[str, object]:
    if name == "positive":
        data = Path(str(context["immutable_path"])).read_bytes()
        target = Path("/scratch/positive")
        target.write_bytes(b"selected reference positive")
        return {
            "input_read": bool(data),
            "scratch_roundtrip": target.read_bytes() == b"selected reference positive",
        }
    if name == "filesystem":
        return filesystem(context)
    if name == "readonly":
        return readonly(context)
    if name == "environment":
        allowed = {
            "PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE",
            "TICKWITNESS_REFERENCE", "PWD",
        }
        return {
            "environment_keys": sorted(os.environ),
            "unexpected_keys": sorted(set(os.environ) - allowed),
            "secret_canaries_absent": all(
                key not in os.environ for key in context["secret_env_keys"]
            ),
            "home": os.environ.get("HOME"),
            "tmpdir": os.environ.get("TMPDIR"),
        }
    if name == "identity":
        return identity
    if name.startswith("network_"):
        return network(name)
    if name == "inherited_fds":
        return inherited_fds(context)
    if name == "memory":
        return memory()
    if name == "pids":
        return pids()
    if name in {"disk_bytes", "inodes"}:
        return exhaust_files(inodes=name == "inodes")
    if name == "fds":
        return fds()
    if name == "file_size":
        return file_size()
    if name == "cpu":
        return cpu()
    if name == "output_flood":
        return output_flood()
    if name == "detached":
        return detached(context)
    if name in {"namespace_denial", "privileged_syscalls", "abi_denial"}:
        return syscall_probe(name)
    if name == "malformed_output":
        os.write(1, b'{"kind":"forged_host_receipt","qualified":true}\n{not-json\n')
        return {}
    if name == "stdio_closed":
        for descriptor in (0, 1, 2):
            os.close(descriptor)
        os._exit(0)
    raise ValueError("Unsupported fixed probe")


def main() -> int:
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in PROBE_NAMES:
            raise ValueError("Only fixed probe arguments are supported")
        name, nonce = sys.argv[1:]
        if re.fullmatch(r"[a-f0-9]{32}", nonce) is None:
            raise ValueError("Probe nonce differs")
        identity = require_guest_gate()
        context = read_context(name, nonce)
        emit({"kind": START_KIND, "name": name, "nonce": nonce})
        if sys.stdin.buffer.readline(80) != ("GO " + nonce + "\n").encode("ascii"):
            raise ValueError("Host observation gate was not opened")
        facts = run_probe(name, context, identity)
        if name != "malformed_output":
            emit({"kind": RESULT_KIND, "name": name, "nonce": nonce, "facts": facts})
        return 0
    except Exception as error:
        sys.stderr.write("restricted_reference_payload_refused: " + type(error).__name__ + "\n")
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
