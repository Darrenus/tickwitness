#!/usr/bin/env python3
"""Capture a real, unreviewed reproduction submission using only the standard library.

Install the owner's pinned core wheel in a fresh virtual environment first.
This script never uploads a result or certifies the participant's identity.
"""

from __future__ import annotations

import sys

# Bootstrap before version-dependent imports or declarations. Unsupported
# interpreters must not inspect a kit, launch qualification, or reserve output.
if (3, 12) <= sys.version_info[:2] < (3, 15):
    import argparse
    import hashlib
    import json
    import os
    import platform
    import re
    import secrets
    import selectors
    import signal
    import subprocess
    import time
    from contextlib import suppress
    from dataclasses import dataclass
    from datetime import UTC, datetime
    from importlib import metadata
    from pathlib import Path
else:
    sys.stderr.write(
        '{"error":{"code":"unsupported_python_version",'
        '"message":"TickWitness alpha reproduction requires Python 3.12\\u20133.14."}}\n'
    )
    raise SystemExit(2)

_MAX_RECEIPT = 1024 * 1024 + 4096
_MAX_DIAGNOSTIC = 32 * 1024
_TIMEOUT = 180
_ENTRYPOINT = "from tickwitness.cli import main; raise SystemExit(main())"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _hash(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("Expected kit ID must be 64 lowercase hexadecimal digits")
    return value


def _participant(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise argparse.ArgumentTypeError(
            "Use a bounded pseudonym, without names or directory paths"
        )
    return value


def _diagnostic(
    raw: bytes | str | None,
    *,
    observed_bytes: int | None = None,
    complete: bool = True,
    overflow: bool = False,
) -> dict[str, object]:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw or b""
    return {
        "text": data[:_MAX_DIAGNOSTIC].decode("utf-8", errors="replace"),
        "truncated": len(data) > _MAX_DIAGNOSTIC or overflow or not complete,
        "captured_prefix_size_bytes": len(data),
        "observed_size_bytes": len(data) if observed_bytes is None else observed_bytes,
        "total_size_known": complete,
        "capture_overflow": overflow,
    }


@dataclass(frozen=True, slots=True)
class CaptureResult:
    stdout: bytes = b""
    stderr: bytes = b""
    exit_code: int | None = None
    timed_out: bool = False
    stdout_overflow: bool = False
    stderr_overflow: bool = False
    process_start_error: dict[str, object] | None = None
    capture_error: str | None = None
    stdout_complete: bool = False
    stderr_complete: bool = False
    stdout_observed_bytes: int = 0
    stderr_observed_bytes: int = 0
    stage: str = "qualification"


def _capture(command: list[str]) -> CaptureResult:
    """Retain bounded prefixes and stop only this attempt's POSIX process group.

    At most one additional byte is observed per pipe to detect overflow. An
    interrupted prefix is not described as the child's unknown total output.
    """
    deadline = time.monotonic() + _TIMEOUT
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return CaptureResult(
            process_start_error={
                "type": type(error).__name__,
                "errno": error.errno,
                "message": str(error),
            },
            stage="process_start",
        )
    prefixes = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": _MAX_RECEIPT, "stderr": _MAX_DIAGNOSTIC}
    observed = {"stdout": 0, "stderr": 0}
    complete = {"stdout": False, "stderr": False}
    overflow = {"stdout": False, "stderr": False}
    timed_out = False
    capture_error = None
    stage = "qualification"
    finished = False
    try:
        with selectors.DefaultSelector() as selector:
            if process.stdout is None or process.stderr is None:
                raise OSError("Qualification subprocess did not provide capture pipes")
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() and not any(overflow.values()):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    stage = "process_timeout"
                    break
                for key, _events in selector.select(timeout=remaining):
                    name = key.data
                    space = limits[name] - len(prefixes[name])
                    try:
                        chunk = os.read(key.fd, min(65_536, space + 1))
                    except BlockingIOError:
                        continue
                    observed[name] += len(chunk)
                    if not chunk:
                        complete[name] = True
                        selector.unregister(key.fileobj)
                        continue
                    prefixes[name].extend(chunk[:space])
                    if len(chunk) > space:
                        overflow[name] = True
                        stage = "process_output_limit"
                        break
            if not timed_out and not any(overflow.values()):
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    stage = "process_timeout"
            finished = True
    except (OSError, ValueError) as error:
        capture_error = str(error)
        stage = "process_capture"
    finally:
        if not finished or timed_out or any(overflow.values()) or capture_error is not None:
            # start_new_session gives this attempt a separate pgid, including
            # descendants keeping a pipe open after the immediate child exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as error:
                capture_error = "Could not terminate attempt process group: " + str(error)
            try:
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as error:
                capture_error = "Could not confirm attempt process termination: " + str(error)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with suppress(OSError):
                    stream.close()
    return CaptureResult(
        stdout=bytes(prefixes["stdout"]),
        stderr=bytes(prefixes["stderr"]),
        exit_code=process.returncode,
        timed_out=timed_out,
        stdout_overflow=overflow["stdout"],
        stderr_overflow=overflow["stderr"],
        capture_error=capture_error,
        stdout_complete=complete["stdout"],
        stderr_complete=complete["stderr"],
        stdout_observed_bytes=observed["stdout"],
        stderr_observed_bytes=observed["stderr"],
        stage=stage,
    )


def _receipt(raw: bytes, expected: str) -> dict[str, object]:
    if not 0 < len(raw) <= _MAX_RECEIPT:
        raise ValueError("CLI receipt is empty or exceeds its bounded profile")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("CLI did not return a receipt object")
    scorecard = value.get("scorecard")
    if (
        value.get("kind") != "alpha_scorecard_receipt_v1"
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("finalization_status") != "LOCAL_RECOMPUTED_TECHNICAL_ONLY"
        or value.get("kit_id") != expected
        or not isinstance(scorecard, dict)
        or scorecard.get("kit_id") != expected
        or scorecard.get("kind") != "alpha_scorecard_v1"
        or value.get("scorecard_id") != hashlib.sha256(_canonical(scorecard)).hexdigest()
    ):
        raise ValueError("CLI returned a conflicting or unrecognized technical receipt")
    gates = scorecard.get("gates")
    if (
        not isinstance(gates, dict)
        or gates
        != {
            "technical_checks": "PASS",
            "external_attempts": 0,
            "external_successes": 0,
            "external_attempt_gate": "PENDING",
            "release_decision": "TECHNICAL_ALPHA_ONLY_EXTERNAL_PENDING",
        }
        or type(gates.get("external_attempts")) is not int
        or type(gates.get("external_successes")) is not int
    ):
        raise ValueError("Receipt must preserve the unreviewed external gate")
    return value


def _publish(directory: Path, name: str, payload: bytes) -> None:
    temporary = directory / (".pending-" + secrets.token_hex(16))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, directory / name, follow_symlinks=False)
    temporary.unlink()
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--expected-kit-id", required=True, type=_hash)
    parser.add_argument("--participant-id", required=True, type=_participant)
    parser.add_argument(
        "--participant-role", required=True, choices=("external_user", "maintainer", "automation")
    )
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    output = arguments.output.absolute()
    if output.resolve().is_relative_to(arguments.kit.resolve()):
        parser.error("Submission output must be outside the immutable kit")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        parser.error("This qualified profile requires POSIX Linux or macOS")
    try:
        # Reserve a new directory; never overwrite a prior submission or run.
        output.mkdir(mode=0o700)
        command = [
            sys.executable,
            "-I",
            "-c",
            _ENTRYPOINT,
            "qualify-alpha-kit",
            str(arguments.kit.absolute()),
            "--expected-kit-id",
            arguments.expected_kit_id,
            "--probe-root",
            str(output / "publication-probe"),
        ]
        started = datetime.now(UTC).isoformat()
        began = time.monotonic_ns()
        captured = _capture(command)
        stdout, stderr = captured.stdout, captured.stderr
        exit_code, timed_out = captured.exit_code, captured.timed_out
        elapsed_ns = time.monotonic_ns() - began
        finished = datetime.now(UTC).isoformat()
        checked = None
        receipt_error = None
        if (
            exit_code == 0
            and not timed_out
            and not stderr
            and not captured.stdout_overflow
            and not captured.stderr_overflow
            and captured.process_start_error is None
            and captured.capture_error is None
            and captured.stdout_complete
            and captured.stderr_complete
        ):
            try:
                checked = _receipt(stdout, arguments.expected_kit_id)
            except (ValueError, UnicodeError, RecursionError) as error:
                receipt_error = str(error)
        if checked is not None:
            _publish(output, "scorecard.json", _canonical(checked))
        try:
            installed = metadata.version("tickwitness")
        except metadata.PackageNotFoundError:
            installed = None
        outcome = "TIMED_OUT" if timed_out else "VERIFIED" if checked is not None else "FAILED"
        submission = {
            "kind": "alpha_reproduction_submission_v1",
            "schema_version": 1,
            "attempt_id": secrets.token_hex(16),
            "participant": {
                "id": arguments.participant_id,
                "role_declared": arguments.participant_role,
            },
            "review_status": "SELF_REPORTED_UNREVIEWED",
            "participant_identity_authenticated": False,
            "expected_kit_id": arguments.expected_kit_id,
            "outcome": outcome,
            "stage": captured.stage,
            "started_at_utc_declared": started,
            "finished_at_utc_declared": finished,
            "elapsed_ns_observed": elapsed_ns,
            "environment": {
                "os": platform.system(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "tickwitness": installed,
            },
            "command": command,
            "process_exit_code": exit_code,
            "process_start_error": captured.process_start_error,
            "capture_error": captured.capture_error,
            "timeout_seconds": _TIMEOUT,
            "capture": {
                "stdout_limit_bytes": _MAX_RECEIPT,
                "stderr_limit_bytes": _MAX_DIAGNOSTIC,
                "stdout_overflow": captured.stdout_overflow,
                "stderr_overflow": captured.stderr_overflow,
                "stdout_complete": captured.stdout_complete,
                "stderr_complete": captured.stderr_complete,
                "stdout_observed_bytes": captured.stdout_observed_bytes,
                "stderr_observed_bytes": captured.stderr_observed_bytes,
            },
            "stdout": (
                _diagnostic(
                    stdout,
                    observed_bytes=captured.stdout_observed_bytes,
                    complete=captured.stdout_complete,
                    overflow=captured.stdout_overflow,
                )
                if checked is None
                else None
            ),
            "stderr": _diagnostic(
                stderr,
                observed_bytes=captured.stderr_observed_bytes,
                complete=captured.stderr_complete,
                overflow=captured.stderr_overflow,
            ),
            "receipt_error": receipt_error,
            "scorecard_id": checked["scorecard_id"] if checked is not None else None,
            "external_gate_updated": False,
        }
        encoded = _canonical(submission)
        submission_id = hashlib.sha256(encoded).hexdigest()
        _publish(
            output,
            "submission.json",
            _canonical({"submission_id": submission_id, "submission": submission}),
        )
        print(
            json.dumps(
                {
                    "kind": "alpha_submission_written_v1",
                    "submission_id": submission_id,
                    "outcome": outcome,
                    "review_status": "SELF_REPORTED_UNREVIEWED",
                    "external_gate_updated": False,
                },
                sort_keys=True,
            )
        )
        return 0 if checked is not None else 11 if timed_out else 10
    except OSError as error:
        print(
            json.dumps({"error": {"code": "alpha_submission_io_failure", "message": str(error)}}),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
