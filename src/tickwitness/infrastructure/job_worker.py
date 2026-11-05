"""Built-in Job worker: bounded JSONL IPC, heartbeats, no Catalog capability.

This is trusted same-user code, not an isolation boundary for hostile plugins.
The coordinator, rather than this process, records all durable job transitions.
"""

import os
import sys
from threading import Event, Lock, Thread
from typing import cast

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.reduction_comparison import (
    MAX_REDUCTION_COMPARISON_EXPORT_BYTES,
)
from tickwitness.domain.evidence.run_records import canonical, identity, parse
from tickwitness.domain.jobs.contracts import load_job_spec
from tickwitness.infrastructure.attempt_ledger import AttemptNotFoundError
from tickwitness.infrastructure.evidence_bundles import BundleNotFoundError
from tickwitness.infrastructure.job_comparison import execute_comparison
from tickwitness.infrastructure.safe_input import InputReadError

MAX_JOB_REQUEST_BYTES = 64 * 1024
MAX_JOB_FRAME_BYTES = MAX_REDUCTION_COMPARISON_EXPORT_BYTES + 64 * 1024
_COMMON = {"job_id", "coordinator_id", "job_attempt_id", "lease_token"}
type Row = dict[str, object]


class _Emitter:
    def __init__(self, bindings: Row) -> None:
        self.bindings = bindings
        self.sequence = 0
        self.lock = Lock()
        self.stop = Event()
        self.broken = Event()

    def emit(self, kind: str, **payload: object) -> None:
        with self.lock:
            self.sequence += 1
            raw = canonical(
                {
                    "kind": kind,
                    "schema_version": 1,
                    **self.bindings,
                    "sequence": self.sequence,
                    **payload,
                }
            )
            if len(raw) > MAX_JOB_FRAME_BYTES:
                raise ValueError("Job IPC result exceeds its frame limit")
            sys.stdout.buffer.write(raw + b"\n")
            sys.stdout.buffer.flush()

    def pulse(self, interval: float) -> None:
        while not self.stop.wait(interval):
            try:
                self.emit("job_heartbeat_v1")
            except (OSError, ValueError):
                self.broken.set()
                # This built-in operation has no writable Catalog or research
                # output. Stop its computation when owner-channel loss is
                # observed, rather than leave a read-only orphan running.
                os._exit(3)


def _failure(error: Exception) -> Row:
    from tickwitness.domain.evidence.run_records import EvidenceValidationError
    from tickwitness.domain.jobs.contracts import JobValidationError

    if isinstance(error, ConfirmationAccessDenied):
        code, exit_code = "confirmation_access_denied", 5
    elif isinstance(error, (AttemptNotFoundError, BundleNotFoundError)):
        code, exit_code = "research_evidence_not_found", 4
    elif isinstance(error, (EvidenceValidationError, JobValidationError, InputReadError)):
        code, exit_code = "invalid_research_evidence", 2
    else:
        code, exit_code = "research_store_integrity_or_io_failure", 3
    return {"code": code, "message": str(error)[:2048], "worker_exit_code": exit_code}


def main() -> int:
    raw = sys.stdin.buffer.readline(MAX_JOB_REQUEST_BYTES + 2)
    if not raw.endswith(b"\n") or len(raw) > MAX_JOB_REQUEST_BYTES + 1:
        return 2
    emitter: _Emitter | None = None
    thread: Thread | None = None
    try:
        request = parse(raw[:-1], limit=MAX_JOB_REQUEST_BYTES)
        if (
            set(request) != _COMMON | {"kind", "schema_version", "spec"}
            or request["kind"] != "job_worker_request_v1"
            or type(request["schema_version"]) is not int
            or request["schema_version"] != 1
        ):
            return 2
        spec = load_job_spec(canonical(cast("Row", request["spec"])))
        bindings = {key: identity(request[key]) for key in _COMMON}
        if spec.spec_id != bindings["job_id"]:
            return 2
        emitter = _Emitter(cast("Row", bindings))
        emitter.emit("job_heartbeat_v1")
        interval = min(1.0, cast("int", spec.document["lease_duration_ns"]) / 4_000_000_000)
        thread = Thread(target=emitter.pulse, args=(interval,), daemon=True)
        thread.start()
        failure: Row | None = None
        output: bytes | None = None
        try:
            output = execute_comparison(spec)
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
        if output is None:
            return 3
        emitter.emit(
            "job_result_v1", export=parse(output, limit=MAX_REDUCTION_COMPARISON_EXPORT_BYTES)
        )
        return 0
    except Exception:
        return 3
    finally:
        if emitter is not None:
            emitter.stop.set()
        if thread is not None:
            thread.join()


if __name__ == "__main__":
    raise SystemExit(main())
