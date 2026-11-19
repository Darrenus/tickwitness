"""Read bounded host audit evidence; never run a probe or change qualification/policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import selectors
import stat
import subprocess
import sys
import time
from pathlib import Path

COMMAND = ("/usr/bin/journalctl", "-k", "-b0", "-n128", "-r", "--no-pager", "-ojson")
LIMIT = 65_536
PROFILE = r"(?:unconfined|unprivileged_userns|bwrap|unpriv_bwrap|tickwitness-reference-bwrap)"
LABELS = {
    "apparmor": {"DENIED", "ALLOWED", "AUDIT"},
    "operation": {"capable", "userns_create", "change_profile", "exec", "file_perm", "open"},
    "comm": {"bwrap"},
    "capname": {"net_admin", "sys_admin", "setpcap", "setuid", "setgid", "sys_chroot",
                "sys_ptrace", "dac_override", "dac_read_search"},
}


def select_records(raw: bytes, boot: str, start: int, end: int) -> tuple[list[dict], int]:
    """Journal receive timestamps are boot-scoped microseconds, not epoch/nanoseconds."""
    selected, malformed = [], 0
    for line in raw.splitlines()[:128]:
        try:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("Journal record is not an object")
            message, stamp, cursor = (item[key] for key in (
                "MESSAGE", "__MONOTONIC_TIMESTAMP", "__CURSOR"
            ))
            if not all(isinstance(value, str) for value in (message, stamp, cursor)):
                raise ValueError("Non-scalar journal address/message")
            if not re.fullmatch(r"[0-9]{1,20}", stamp) or not re.fullmatch(
                r"[\x21-\x7e]{1,512}", cursor
            ):
                raise ValueError("Invalid journal address")
            if item.get("_BOOT_ID") != boot or not start <= int(stamp) * 1000 <= end:
                continue
            if not re.search(r"apparmor|userns|capabil", message, re.I) or not (
                "bwrap" in message.lower() or re.search(r"\b(?:uid|fsuid)=61184\b", message)
            ):
                continue
            fields = {}
            for key, quoted, plain in re.findall(r'(\w+)=(?:"([^"]*)"|(\S+))', message):
                value = quoted or plain
                if key in {"pid", "uid", "fsuid", "ouid", "error", "capability"}:
                    valid = re.fullmatch(r"-?\d{1,20}", value)
                elif key in LABELS:
                    valid = value in LABELS[key]
                elif key == "profile":
                    valid = re.fullmatch(PROFILE + r"(?:(?://&|//|&)" + PROFILE + r")*", value)
                else:
                    continue
                if valid:
                    fields[key] = value
            selected.append({"boot_id": boot, "monotonic_us": int(stamp), "cursor": cursor,
                             "audit_fields": fields})
        except (ValueError, KeyError, TypeError, RecursionError):
            malformed += 1
    return selected, malformed


def read_journal() -> tuple[bytes, dict]:
    deadline = time.monotonic_ns() + 3_000_000_000
    data = {"stdout": bytearray(), "stderr": bytearray()}
    facts = {"read_status": "UNKNOWN", "exit_code": None, "stop_confirmed": False}
    process = None
    try:
        process = subprocess.Popen(COMMAND, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, close_fds=True,
                                   env={"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"})
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                if stream is None:
                    raise ValueError("Fixed diagnostic pipes unavailable")
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = (deadline - time.monotonic_ns()) / 1e9
                if remaining <= 0:
                    facts["read_status"] = "TIMEOUT"
                    break
                for key, _events in selector.select(timeout=remaining):
                    name = key.data
                    chunk = os.read(key.fd, min(4096, LIMIT - len(data[name]) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    available = LIMIT - len(data[name])
                    data[name].extend(chunk[:available])
                    if len(chunk) > available:
                        facts["read_status"] = name.upper() + "_LIMIT"
                        break
                if facts["read_status"] != "UNKNOWN":
                    break
            else:
                facts["read_status"] = "COMPLETE"
        if facts["read_status"] == "COMPLETE":
            try:
                process.wait(timeout=max(0, (deadline - time.monotonic_ns()) / 1e9))
                if time.monotonic_ns() > deadline:
                    facts["read_status"] = "TIMEOUT"
            except subprocess.TimeoutExpired:
                facts["read_status"] = "TIMEOUT"
    except (OSError, ValueError):
        facts["read_status"] = "UNREADABLE"
    finally:
        if process is not None:
            stop = time.monotonic_ns() + 500_000_000
            try:
                if process.poll() is None:
                    process.kill()  # Only this live owned, fixed --no-pager host command.
                process.wait(timeout=max(0, (stop - time.monotonic_ns()) / 1e9))
                facts["stop_confirmed"] = time.monotonic_ns() <= stop
            except (OSError, subprocess.TimeoutExpired):
                pass
            facts["exit_code"] = process.returncode
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
    facts.update({name + "_bytes": len(value) for name, value in data.items()})
    facts["stderr_sha256"] = hashlib.sha256(data["stderr"]).hexdigest()
    return bytes(data["stdout"]), facts


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    if (sys.platform != "linux" or platform.machine() != "x86_64" or os.geteuid() != 0
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"):
        return 2
    directory = args.evidence_dir.absolute()
    info = directory.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        return 2
    result = {"kind": "restricted_reference_host_diagnostic_v1", "status": "UNKNOWN",
              "qualification_modified": False, "policy_modified": False, "records": []}
    try:
        descriptor = os.open(directory / "report.json", os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                    or info.st_mode & 0o022 or info.st_size > 2_097_152):
                raise ValueError("Existing host report unavailable")
            report = json.loads(stream.read(2_097_153))
        case = next(case for case in report["cases"] if case["admission_submitted"] is True)
        host = case["execution"]["host_facts"]
        start, end = host["original_admission_ns"], host["stop_confirmation_deadline_ns"]
        if (type(start) is not int or type(end) is not int
                or not 0 < start <= end <= start + 12_000_000_000):
            raise ValueError("Original monotonic diagnostic window unavailable")
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")
        raw, facts = read_journal()
        records, malformed = select_records(raw, boot, start, end)
        complete = (facts["read_status"] == "COMPLETE" and facts["exit_code"] == 0
                    and facts["stop_confirmed"] and malformed == 0)
        result.update({"window_ns": {"start": start, "end": end}, "boot_id": boot,
                       "collection": facts, "records": records, "malformed_records": malformed,
                       "status": "MATCHING_RECORDS_OBSERVED" if records and complete else "UNKNOWN",
                       "reason": "Bounded observations only; missing audit never proves no denial"})
    except (OSError, ValueError, KeyError, TypeError, StopIteration, RecursionError) as error:
        result["reason"] = "Existing report/audit unavailable: " + type(error).__name__
    descriptor = os.open(directory / "host-diagnostic.json",
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(json.dumps(result, sort_keys=True, indent=2).encode() + b"\n")
    directory.chmod(0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
