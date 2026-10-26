"""Optional queue execution and a bounded, separate subprocess IPC transport."""

import json
import os
import subprocess
import sys
import time
from decimal import ROUND_HALF_EVEN, Context, localcontext
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import cast

from tickwitness.domain.replay._validation import ReplayValidationError, canonical
from tickwitness.domain.replay.queue_contracts import (
    ENGINE,
    QueueReplayInput,
    QueueReplayResult,
    build_queue_replay_result,
    load_queue_replay_result,
)
from tickwitness.infrastructure.nautilus_replay import ReplayDependencyError, ReplayEngineError
from tickwitness.infrastructure.subprocess_replay import (
    MAX_REQUEST_BYTES,
    MAX_RESULT_BYTES,
    MAX_STDERR_BYTES,
    ReplayProcessError,
    SubprocessReplayAdapter,
    _kill,
    _size,
)


class NautilusQueueReplayAdapter:
    """Execute a revalidated family member through pinned, public native hooks."""

    def run(self, replay_input: QueueReplayInput) -> QueueReplayResult:
        if not isinstance(replay_input, QueueReplayInput):
            raise ReplayValidationError("Queue execution requires QueueReplayInput")
        checked = QueueReplayInput(
            replay_input.family, replay_input.normalized_bytes, replay_input.policy_id
        )
        try:
            installed = metadata.version("nautilus_trader")
        except metadata.PackageNotFoundError as error:
            raise ReplayDependencyError(
                "missing_dependency", "Install the optional nautilus extra for queue execution"
            ) from error
        if installed != ENGINE["version"]:
            raise ReplayDependencyError(
                "version_mismatch", "Queue execution requires Nautilus 1.231.0"
            )
        try:
            from tickwitness.infrastructure._queue_native import run_native

            with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
                return build_queue_replay_result(run_native(checked))
        except ImportError as error:
            raise ReplayDependencyError(
                "native_import_failed", "The pinned Nautilus runtime cannot be imported"
            ) from error
        except Exception as error:
            raise ReplayEngineError(
                "native_execution_failed",
                f"Native queue execution failed: {type(error).__name__}: {error}",
            ) from error


class QueueSubprocessReplayAdapter:
    """One family member per disposable worker; wall time and output remain bounded."""

    def __init__(self, *, timeout_seconds: int = 60, python_executable: Path | None = None) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
            raise ReplayValidationError("Queue wall timeout must be an integer in [1, 60]")
        self.timeout_seconds = timeout_seconds
        # Preserve a venv launcher symlink; resolving it changes interpreter package scope.
        self.python_executable = (python_executable or Path(sys.executable)).absolute()

    def run(self, replay_input: QueueReplayInput) -> QueueReplayResult:
        if not isinstance(replay_input, QueueReplayInput):
            raise ReplayValidationError("Queue worker requires QueueReplayInput")
        checked = QueueReplayInput(
            replay_input.family, replay_input.normalized_bytes, replay_input.policy_id
        )
        request = json.dumps(
            {
                "kind": "queue_replay_worker_request_v1",
                "schema_version": 1,
                "family": checked.family.canonical_bytes.decode("utf-8"),
                "normalized": checked.normalized_bytes.decode("utf-8"),
                "policy_id": checked.policy_id,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(request) > MAX_REQUEST_BYTES:
            raise ReplayValidationError("Queue worker request exceeds its byte bound")
        if os.name != "posix":
            raise ReplayProcessError(
                "engine_unavailable", "Queue worker requires POSIX supervision", 6
            )
        budget = cast("dict[str, int]", checked.family.document["budget"])
        timeout = min(self.timeout_seconds, budget["max_wall_seconds"])
        with (
            TemporaryDirectory(prefix="tickwitness-queue-") as directory,
            TemporaryFile() as stdin,
            TemporaryFile() as stdout,
            TemporaryFile() as stderr,
        ):
            stdin.write(request)
            stdin.seek(0)
            try:
                process = subprocess.Popen(
                    [
                        str(self.python_executable),
                        "-I",
                        "-m",
                        "tickwitness.infrastructure._queue_worker",
                    ],
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    cwd=directory,
                    start_new_session=True,
                )
            except OSError as error:
                raise ReplayProcessError(
                    "engine_unavailable", "Queue worker interpreter could not start", 6
                ) from error
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if _size(stdout) > MAX_RESULT_BYTES or _size(stderr) > MAX_STDERR_BYTES:
                        raise ReplayProcessError(
                            "engine_output_limit", "Queue worker output exceeded its byte bound"
                        )
                    if time.monotonic() >= deadline:
                        raise ReplayProcessError(
                            "engine_timeout", "Queue worker exceeded the frozen wall time"
                        )
                    time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
                if _size(stdout) > MAX_RESULT_BYTES or _size(stderr) > MAX_STDERR_BYTES:
                    raise ReplayProcessError(
                        "engine_output_limit", "Queue worker output exceeded its byte bound"
                    )
                if process.returncode != 0:
                    stderr.seek(0)
                    SubprocessReplayAdapter._raise_worker_error(
                        process.returncode, stderr.read(MAX_STDERR_BYTES + 1)
                    )
                stdout.seek(0)
                raw = stdout.read(MAX_RESULT_BYTES + 1)
            finally:
                _kill(process)
        try:
            result = load_queue_replay_result(raw)
        except ReplayValidationError as error:
            raise ReplayProcessError(
                "engine_invalid_result", "Queue worker returned invalid bounded evidence"
            ) from error
        document = result.document
        if canonical(cast("dict[str, object]", document["bindings"])) != canonical(
            cast("dict[str, object]", checked.bindings)
        ):
            raise ReplayProcessError(
                "engine_invalid_result", "Queue worker evidence bindings differ from its request"
            )
        return result
