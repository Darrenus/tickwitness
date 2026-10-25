"""Supervise trusted native replay with wall time and output bounds.

The worker executes a built-in strategy only. A separate process is a crash and
timeout boundary, not a sandbox for malicious code or a memory quota.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import BinaryIO

from tickwitness.domain.replay.capabilities import EngineCapabilities
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult, load_replay_result
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.infrastructure.nautilus_replay import (
    CAPABILITIES,
    ENGINE_ID,
    ENGINE_VERSION,
    SEMANTIC_ID,
)

MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024


class ReplayProcessError(RuntimeError):
    """An unavailable worker, timeout, output breach or native failure."""

    def __init__(self, code: str, message: str, exit_code: int = 7) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(message)


def _kill(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _size(stream: BinaryIO) -> int:
    return os.fstat(stream.fileno()).st_size


class SubprocessReplayAdapter:
    """Launch an installed TickWitness worker via an explicitly trusted interpreter."""

    def __init__(self, *, timeout_seconds: int = 60, python_executable: Path | None = None) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
            raise ReplayValidationError("timeout_seconds must be an integer from 1 to 60")
        self._timeout = timeout_seconds
        # Preserve a venv symlink: resolve() would select the base interpreter.
        self._python = str((python_executable or Path(sys.executable)).absolute())

    @property
    def capabilities(self) -> EngineCapabilities:
        return CAPABILITIES

    def run(self, replay_input: ReplayInput) -> ReplayResult:
        preflight_replay(replay_input)
        payload = json.dumps(
            {
                "schema_version": 1,
                "dataset_id": replay_input.dataset_id,
                "normalized": replay_input.normalized_bytes.decode("utf-8"),
                "spec": replay_input.spec.canonical_bytes.decode("utf-8"),
            },
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            raise ReplayValidationError("Worker request exceeds its byte bound")
        if os.name != "posix":
            raise ReplayProcessError("engine_unavailable", "Replay supervision requires POSIX", 6)
        try:
            with (
                TemporaryDirectory(prefix="tickwitness-replay-") as directory,
                TemporaryFile() as request,
                TemporaryFile() as output,
                TemporaryFile() as errors,
            ):
                request.write(payload)
                request.seek(0)
                process = subprocess.Popen(
                    [self._python, "-I", "-m", "tickwitness.infrastructure.replay_worker"],
                    stdin=request,
                    stdout=output,
                    stderr=errors,
                    cwd=directory,
                    start_new_session=True,
                )
                deadline = time.monotonic() + self._timeout
                try:
                    while process.poll() is None:
                        if _size(output) > MAX_RESULT_BYTES or _size(errors) > MAX_STDERR_BYTES:
                            raise ReplayProcessError(
                                "engine_output_limit", "Worker output exceeded its limit"
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ReplayProcessError(
                                "engine_timeout", "Worker exceeded its wall time budget"
                            )
                        with suppress(subprocess.TimeoutExpired):
                            process.wait(timeout=min(0.05, remaining))
                finally:
                    _kill(process)
                if _size(output) > MAX_RESULT_BYTES or _size(errors) > MAX_STDERR_BYTES:
                    raise ReplayProcessError(
                        "engine_output_limit", "Worker output exceeded its limit"
                    )
                output.seek(0)
                errors.seek(0)
                if process.returncode != 0:
                    self._raise_worker_error(process.returncode, errors.read(MAX_STDERR_BYTES))
                raw = output.read(MAX_RESULT_BYTES + 1)
        except OSError as error:
            raise ReplayProcessError(
                "engine_unavailable",
                "Cannot launch the installed replay worker "
                f"(errno {error.errno}: {error.strerror})",
                6,
            ) from error
        try:
            result = load_replay_result(raw)
        except ReplayValidationError as error:
            raise ReplayProcessError(
                "engine_invalid_result", "Worker returned an invalid result"
            ) from error
        document = result.document
        if (
            document["dataset_id"] != replay_input.dataset_id
            or document["spec_id"] != replay_input.spec.spec_id
            or document["data_sha256"] != hashlib.sha256(replay_input.normalized_bytes).hexdigest()
            or document["engine"]
            != {
                "id": ENGINE_ID,
                "version": ENGINE_VERSION,
                "semantic_id": SEMANTIC_ID,
            }
        ):
            raise ReplayProcessError(
                "engine_invalid_result", "Worker result identity does not match its request"
            )
        return result

    @staticmethod
    def _raise_worker_error(returncode: int, stderr: bytes) -> None:
        try:
            parsed: object = json.loads(stderr)
        except (ValueError, UnicodeError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            error = parsed["error"]
            message = error.get("message")
            code = error.get("code")
            allowed = {2: "invalid_replay", 6: "engine_unavailable", 7: "engine_failure"}
            if allowed.get(returncode) == code and isinstance(message, str):
                raise ReplayProcessError(code, message[:2048], returncode)
        raise ReplayProcessError("engine_failure", f"Replay worker exited with status {returncode}")
