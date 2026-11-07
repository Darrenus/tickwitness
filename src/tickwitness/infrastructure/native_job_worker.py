"""One trusted native process, path-free input and no research write authority."""

import signal
import sys
import time
from threading import Thread
from typing import cast

from tickwitness.domain.evidence.run_records import EvidenceValidationError
from tickwitness.domain.jobs.native_requests import (
    MAX_NATIVE_JOB_REQUEST_BYTES,
    load_native_worker_request,
)
from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.infrastructure.job_worker import _Emitter
from tickwitness.infrastructure.nautilus_replay import (
    NautilusReplayAdapter,
    ReplayDependencyError,
    ReplayEngineError,
)

type Row = dict[str, object]


def arm_native_deadline(deadline_ns: int) -> None:
    """Default OS termination, without a Python callback waiting for the GIL.

    This private one-process native worker owns SIGALRM. Its absolute monotonic
    deadline comes from the live coordinator, never persisted across boots.
    """
    if type(deadline_ns) is not int:
        raise EvidenceValidationError("Native deadline must be an integer")
    if deadline_ns <= time.monotonic_ns():
        raise EvidenceValidationError("Original native deadline expired before execution")
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM})
    remaining = deadline_ns - time.monotonic_ns()
    if remaining <= 0:
        raise EvidenceValidationError("Original native deadline expired during alarm setup")
    signal.setitimer(signal.ITIMER_REAL, remaining / 1_000_000_000)
    if time.monotonic_ns() >= deadline_ns:
        raise EvidenceValidationError("Original native deadline expired before alarm admission")


def _failure(error: Exception) -> Row:
    if isinstance(error, ReplayDependencyError):
        code, exit_code = "engine_unavailable", 6
    elif isinstance(error, (ReplayValidationError, EvidenceValidationError)):
        code, exit_code = "invalid_research_evidence", 2
    elif isinstance(error, ReplayEngineError):
        code, exit_code = "engine_failure", 7
    else:
        code, exit_code = "native_job_worker_failed", 7
    return {"code": code, "message": str(error)[:2048], "worker_exit_code": exit_code}


def main() -> int:
    emitter: _Emitter | None = None
    thread: Thread | None = None
    try:
        raw = sys.stdin.buffer.readline(MAX_NATIVE_JOB_REQUEST_BYTES + 2)
        if not raw.endswith(b"\n") or len(raw) > MAX_NATIVE_JOB_REQUEST_BYTES + 1:
            return 2
        request, replay_input, reservation, _intent = load_native_worker_request(raw[:-1])
        bindings = {
            key: request[key]
            for key in ("job_id", "coordinator_id", "job_attempt_id", "lease_token")
        }
        payload = cast("Row", request["payload"])
        deadline = cast("int", payload["native_deadline_ns"])
        # The coordinator's original budget includes startup and delivery.
        if (
            deadline - time.monotonic_ns()
            > cast("int", reservation.document["max_wall_seconds"]) * 1_000_000_000
        ):
            raise EvidenceValidationError("Native deadline exceeds its original reservation")
        arm_native_deadline(deadline)
        emitter = _Emitter(bindings)
        emitter.emit("job_heartbeat_v1")
        # A fixed short heartbeat is independent of the research wall deadline.
        # A one-second Job lease is supported without granting more wall time.
        thread = Thread(target=emitter.pulse, args=(0.2,), daemon=True)
        thread.start()
        failure: Row | None = None
        result = None
        try:
            result = NautilusReplayAdapter().run(replay_input)
        except Exception as error:
            failure = _failure(error)
        finally:
            emitter.stop.set()
            thread.join()
        if emitter.broken.is_set():
            return 3
        if failure is not None:
            emitter.emit("job_failure_v1", failure=failure)
            return cast("int", failure["worker_exit_code"])
        if result is None:
            return 7
        emitter.emit("job_native_result_v1", replay_result=result.document)
        return 0
    except (EvidenceValidationError, ReplayValidationError):
        return 2
    except Exception:
        return 3
    finally:
        if emitter is not None:
            emitter.stop.set()
        if thread is not None:
            thread.join()


if __name__ == "__main__":
    raise SystemExit(main())
