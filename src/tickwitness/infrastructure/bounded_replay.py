"""Native replay using bounded RAM pipes inside a campaign's supervised group.

Unlike the legacy adapter this worker does not create a new session. It must be
called by the trusted supervised coordinator, so an outer timeout can terminate
both it and the coordinator together. This is not a public hostile-code sandbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

from tickwitness.domain.replay.capabilities import EngineCapabilities
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult, load_replay_result
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.infrastructure.campaign_supervisor import (
    _close_pipes,
    _PipeDeadlineExceeded,
    _PipeOutputExceeded,
    _pipe_exchange,
)
from tickwitness.infrastructure.nautilus_replay import (
    CAPABILITIES,
    ENGINE_ID,
    ENGINE_VERSION,
    SEMANTIC_ID,
)
from tickwitness.infrastructure.subprocess_replay import (
    MAX_REQUEST_BYTES,
    MAX_RESULT_BYTES,
    MAX_STDERR_BYTES,
    ReplayProcessError,
    SubprocessReplayAdapter,
)


def _terminate_worker(process: subprocess.Popen[bytes]) -> None:
    # The worker inherits its coordinator's process group. Killing that group
    # here would kill the coordinator itself; only the outer supervisor does so.
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.kill()
    process.wait()


class BoundedReplayAdapter:
    """Apply both original per-attempt time and one nonrenewable campaign deadline."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 60,
        deadline_ns: int,
        python_executable: Path | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
            raise ReplayValidationError("timeout_seconds must be an integer from 1 to 60")
        if type(deadline_ns) is not int or not 1 <= deadline_ns < 1 << 63:
            raise ReplayValidationError("deadline_ns must be a positive int64 monotonic deadline")
        self._timeout, self._deadline, self._clock = timeout_seconds, deadline_ns, clock_ns
        # Do not resolve virtualenv interpreter symlinks to their base Python.
        self._python = str((python_executable or Path(sys.executable)).absolute())

    @property
    def capabilities(self) -> EngineCapabilities:
        return CAPABILITIES

    def _check(self, effective_deadline: int) -> None:
        now = self._clock()
        if now >= effective_deadline:
            if now >= self._deadline:
                raise ReplayProcessError(
                    "campaign_time_limit", "Campaign execution deadline reached", 8
                )
            raise ReplayProcessError("engine_timeout", "Worker exceeded original attempt time", 7)

    def run(self, replay_input: ReplayInput) -> ReplayResult:
        effective = min(self._deadline, self._clock() + self._timeout * 1_000_000_000)
        self._check(effective)
        preflight_replay(replay_input)
        payload = json.dumps(
            {
                "schema_version": 1,
                "dataset_id": replay_input.dataset_id,
                "normalized": replay_input.normalized_bytes.decode("utf-8"),
                "spec": replay_input.spec.canonical_bytes.decode("utf-8"),
            },
            separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            raise ReplayValidationError("Worker request exceeds its byte bound")
        self._check(effective)
        if os.name != "posix":
            raise ReplayProcessError("engine_unavailable", "Replay supervision requires POSIX", 6)
        process: subprocess.Popen[bytes] | None = None
        try:
            with TemporaryDirectory(prefix="tickwitness-bounded-replay-") as directory:
                self._check(effective)
                process = subprocess.Popen(
                    [self._python, "-I", "-m", "tickwitness.infrastructure.replay_worker"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=directory, start_new_session=False,
                )
                try:
                    output, errors = _pipe_exchange(
                        process, payload, deadline_ns=effective,
                        stdout_limit=MAX_RESULT_BYTES, stderr_limit=MAX_STDERR_BYTES,
                        clock_ns=self._clock,
                    )
                except _PipeDeadlineExceeded:
                    self._check(effective)
                    raise ReplayProcessError(
                        "engine_timeout", "Worker deadline reached", 7
                    ) from None
                except _PipeOutputExceeded as error:
                    raise ReplayProcessError(
                        "engine_output_limit", "Worker exceeded bounded pipe output", 7
                    ) from error
                finally:
                    _terminate_worker(process)
                    _close_pipes(process)
                self._check(effective)
                if process.returncode != 0:
                    SubprocessReplayAdapter._raise_worker_error(process.returncode or 7, errors)
        except OSError as error:
            raise ReplayProcessError(
                "engine_unavailable", f"Cannot launch replay worker (errno {error.errno})", 6
            ) from error
        self._check(effective)
        try:
            result = load_replay_result(output)
        except ReplayValidationError as error:
            raise ReplayProcessError(
                "engine_invalid_result", "Worker returned invalid result", 7
            ) from error
        self._check(effective)
        document = result.document
        if (
            document["dataset_id"] != replay_input.dataset_id
            or document["spec_id"] != replay_input.spec.spec_id
            or document["data_sha256"] != hashlib.sha256(replay_input.normalized_bytes).hexdigest()
            or document["engine"] != {
                "id": ENGINE_ID, "version": ENGINE_VERSION, "semantic_id": SEMANTIC_ID,
            }
        ):
            raise ReplayProcessError("engine_invalid_result", "Worker result binding differs", 7)
        self._check(effective)
        return result
