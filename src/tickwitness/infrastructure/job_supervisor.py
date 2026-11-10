"""Single-coordinator supervision; workers never publish research evidence."""

import os
import secrets
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from tickwitness.application.jobs import JobConflictError, JobRepository, JobStoreError
from tickwitness.domain.evidence.reduction_comparison import load_reduction_comparison_export
from tickwitness.domain.evidence.run_records import canonical, parse
from tickwitness.domain.jobs.contracts import (
    JobSpec,
    build_followup_result,
    execution_origin_spec,
    job_dispatch_nonce,
    load_job_spec,
)
from tickwitness.domain.jobs.native_requests import build_native_worker_request
from tickwitness.domain.replay.contracts import load_replay_result
from tickwitness.infrastructure import job_reduction
from tickwitness.infrastructure.attempt_ledger import AttemptBudgetExceededError
from tickwitness.infrastructure.job_comparison import execute_comparison
from tickwitness.infrastructure.job_control_runtime import (
    JobControlStop,
    JobExecutionControl,
    check_control,
    control_admission,
    control_publication,
    current_control,
    validate_worker_limits,
)
from tickwitness.infrastructure.job_controls import JobControlStore
from tickwitness.infrastructure.job_followups import find_committed_dispatch
from tickwitness.infrastructure.job_lineage import JobFamily
from tickwitness.infrastructure.job_reduction import (
    audit_native_job,
    authorize_native_job,
    prepare_native_job,
    publish_native_job,
)
from tickwitness.infrastructure.job_worker import (
    MAX_JOB_FRAME_BYTES,
    MAX_JOB_REQUEST_BYTES,
    _failure,
)
from tickwitness.infrastructure.nautilus_replay import ReplayDependencyError

type Row = dict[str, object]
MAX_JOB_STDERR_BYTES = 64 * 1024
_COMMON = {
    "kind",
    "schema_version",
    "job_id",
    "coordinator_id",
    "job_attempt_id",
    "lease_token",
    "sequence",
}


class _LeaseExpired(Exception):
    pass


class _WorkerFault(Exception):
    pass


class _NativeDeadlineExpired(Exception):
    pass


@dataclass(slots=True)
class _LeaseWindow:
    deadline_ns: int
    native_deadline_ns: int | None = None


@contextmanager
def _workspace(row: Row, *, prefix: str) -> Iterator[Path]:
    control = current_control()
    if control is not None:
        with control.workspace(row) as path:
            yield path
    else:
        with TemporaryDirectory(prefix=prefix) as directory:
            yield Path(directory)


def _start_worker(command: tuple[str, ...], cwd: Path) -> subprocess.Popen[bytes]:
    with control_admission():
        control = current_control()
        if control is not None:
            return control.spawn(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
                close_fds=True,
            )
        return subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            start_new_session=True,
            close_fds=True,
        )


def _before_control_publication(row: Row) -> None:
    """Private installed-qualification gate; production has no alternate publisher."""


def _resource_stop(exit_code: int | None) -> None:
    if current_control() is not None and exit_code in {-signal.SIGXCPU, -signal.SIGXFSZ}:
        raise JobControlStop("job_resource_limit", "Worker reached its enforced OS limit")


def _signal_group(process: subprocess.Popen[bytes]) -> None:
    # start_new_session establishes pgid == pid. An exited child can race the
    # group signal on Darwin; only a confirmed child exit can excuse EPERM.
    if process.pid <= 0 or process.pid == os.getpgrp():
        raise RuntimeError("Refusing to signal the coordinator's own process group")
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        if process.poll() is None:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                raise error from None


def _terminate(process: subprocess.Popen[bytes]) -> None:
    control = current_control()
    if control is not None:
        control.stop_process(process)
        return
    _signal_group(process)
    process.wait(timeout=5)


def _checked_frame(raw: bytes, row: Row) -> Row:
    frame = parse(raw, limit=MAX_JOB_FRAME_BYTES)
    kind = frame.get("kind")
    native = cast("Row", row["spec"])["operation"] in {
        "execute_reduction_input_v1",
        "resolve_reduction_job_v1",
    }
    result_kind = "job_native_result_v1" if native else "job_result_v1"
    extra = (
        {"replay_result"}
        if kind == "job_native_result_v1"
        else {"export"}
        if kind == "job_result_v1"
        else {"failure"}
        if kind == "job_failure_v1"
        else set()
    )
    attempt = cast("Row", row["attempt"])
    if (
        not isinstance(kind, str)
        or kind not in {"job_heartbeat_v1", result_kind, "job_failure_v1"}
        or set(frame) != _COMMON | extra
        or type(frame["schema_version"]) is not int
        or frame["schema_version"] != 1
        or frame["job_id"] != row["job_id"]
        or any(
            frame[key] != attempt[key]
            for key in ("coordinator_id", "job_attempt_id", "lease_token")
        )
        or type(frame["sequence"]) is not int
        or frame["sequence"] != cast("int", attempt["heartbeat_sequence"]) + 1
    ):
        raise _WorkerFault("Worker IPC identity, schema or sequence differs")
    if kind == "job_result_v1":
        load_reduction_comparison_export(canonical(cast("Row", frame["export"])))
    elif kind == "job_native_result_v1":
        load_replay_result(canonical(cast("Row", frame["replay_result"])))
    elif kind == "job_failure_v1":
        failure = frame["failure"]
        if (
            not isinstance(failure, dict)
            or set(failure) != {"code", "message", "worker_exit_code"}
            or not isinstance(failure["code"], str)
            or not 1 <= len(failure["code"]) <= 128
            or not isinstance(failure["message"], str)
            or len(failure["message"]) > 2048
            or type(failure["worker_exit_code"]) is not int
            or not 1 <= failure["worker_exit_code"] <= 255
        ):
            raise _WorkerFault("Worker failure diagnostic differs from its schema")
    return frame


def _exchange(
    process: subprocess.Popen[bytes],
    raw: bytes,
    store: JobRepository,
    row: Row,
    window: _LeaseWindow,
) -> tuple[Row, Row | None, bytes]:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise _WorkerFault("Worker pipes are unavailable")
    job_id = cast("str", row["job_id"])
    spec = cast("Row", row["spec"])
    lease_ns = cast("int", spec["lease_duration_ns"])
    pending = memoryview(raw + b"\n")
    buffer = bytearray()
    errors = bytearray()
    terminal: Row | None = None
    exit_seen = False
    with selectors.DefaultSelector() as selector:
        for stream, events, name in (
            (process.stdin, selectors.EVENT_WRITE, "stdin"),
            (process.stdout, selectors.EVENT_READ, "stdout"),
            (process.stderr, selectors.EVENT_READ, "stderr"),
        ):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, events, name)
        controlled = current_control() is not None
        while selector.get_map() or (not controlled and process.poll() is None):
            check_control()
            if (
                window.native_deadline_ns is not None
                and time.monotonic_ns() >= window.native_deadline_ns
            ):
                raise _NativeDeadlineExpired
            if time.monotonic_ns() >= window.deadline_ns:
                raise _LeaseExpired
            if not controlled and not exit_seen and process.poll() is not None:
                exit_seen = True
                # An orphan descendant must not keep either pipe alive forever.
                _signal_group(process)
            deadline = (
                min(window.deadline_ns, window.native_deadline_ns)
                if window.native_deadline_ns is not None
                else window.deadline_ns
            )
            timeout = min(0.1, max(0, deadline - time.monotonic_ns()) / 1_000_000_000)
            for key, _ in selector.select(timeout):
                ready_stream = key.fileobj
                descriptor = key.fd
                if key.data == "stdin":
                    try:
                        pending = pending[os.write(descriptor, pending) :]
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        pending = pending[:0]
                    if not pending:
                        selector.unregister(ready_stream)
                        process.stdin.close()
                    continue
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    selector.unregister(ready_stream)
                    if key.data == "stdout" and buffer:
                        raise _WorkerFault("Worker output ended inside an IPC frame")
                    continue
                if key.data == "stderr":
                    errors.extend(chunk)
                    if len(errors) > MAX_JOB_STDERR_BYTES:
                        raise _WorkerFault("Worker stderr exceeds 64 KiB")
                    continue
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, tail = buffer.partition(b"\n")
                    buffer = bytearray(tail)
                    if terminal is not None:
                        raise _WorkerFault("Worker emitted output after its terminal frame")
                    frame = _checked_frame(bytes(line), row)
                    pulse_clock = time.monotonic_ns()
                    if (
                        window.native_deadline_ns is not None
                        and pulse_clock >= window.native_deadline_ns
                    ):
                        raise _NativeDeadlineExpired
                    if pulse_clock >= window.deadline_ns:
                        raise _LeaseExpired
                    check_control()
                    attempt = cast("Row", row["attempt"])
                    row = store.heartbeat(
                        job_id,
                        expected_version=cast("int", row["version"]),
                        coordinator_id=cast("str", attempt["coordinator_id"]),
                        job_attempt_id=cast("str", attempt["job_attempt_id"]),
                        lease_token=cast("str", attempt["lease_token"]),
                        sequence=cast("int", frame["sequence"]),
                        now_ns=time.time_ns(),
                    )
                    window.deadline_ns = pulse_clock + lease_ns
                    if frame["kind"] != "job_heartbeat_v1":
                        terminal = frame
                if len(buffer) > MAX_JOB_FRAME_BYTES:
                    raise _WorkerFault("Worker stdout frame exceeds its byte limit")
        if (
            window.native_deadline_ns is not None
            and time.monotonic_ns() >= window.native_deadline_ns
        ):
            raise _NativeDeadlineExpired
        return row, terminal, bytes(errors)


def _lost_lease(store: JobRepository, row: Row, *, now_ns: int) -> Row:
    if now_ns < cast("int", cast("Row", row["attempt"])["lease_expires_at_ns"]):
        raise JobConflictError(
            "Monotonic lease expired but UTC cannot confirm it; inspect or reconcile"
        )
    return store.mark_lost(
        cast("str", row["job_id"]),
        expected_version=cast("int", row["version"]),
        reason="lease_expired",
        now_ns=now_ns,
    )


def _finish_failure(store: JobRepository, row: Row, failure: Row, window: _LeaseWindow) -> Row:
    check_control()
    if current_control() is not None and failure["code"] == "job_resource_limit":
        raise JobControlStop("job_resource_limit", cast("str", failure["message"]))
    now = time.time_ns()
    attempt = cast("Row", row["attempt"])
    if time.monotonic_ns() >= window.deadline_ns or now >= cast(
        "int", attempt["lease_expires_at_ns"]
    ):
        return _lost_lease(store, row, now_ns=now)
    return store.fail(
        cast("str", row["job_id"]),
        failure,
        expected_version=cast("int", row["version"]),
        coordinator_id=cast("str", attempt["coordinator_id"]),
        job_attempt_id=cast("str", attempt["job_attempt_id"]),
        lease_token=cast("str", attempt["lease_token"]),
        now_ns=now,
    )


def _native_failure(error: Exception, *, worker_exit_code: int | None = None) -> Row:
    if isinstance(error, ReplayDependencyError):
        return {
            "code": "engine_unavailable",
            "message": str(error)[:2048],
            "worker_exit_code": worker_exit_code,
        }
    diagnostic = _failure(error)
    code = getattr(error, "code", None)
    if isinstance(code, str) and 0 < len(code) <= 128:
        diagnostic["code"] = code
    diagnostic["worker_exit_code"] = worker_exit_code
    return diagnostic


def _assert_publication_authority(store: JobRepository, row: Row, window: _LeaseWindow) -> None:
    check_control()
    attempt = cast("Row", row["attempt"])
    now = time.time_ns()
    if time.monotonic_ns() >= window.deadline_ns or now >= cast(
        "int", attempt["lease_expires_at_ns"]
    ):
        raise _LeaseExpired
    store.assert_active(
        cast("str", row["job_id"]),
        expected_version=cast("int", row["version"]),
        coordinator_id=cast("str", attempt["coordinator_id"]),
        job_attempt_id=cast("str", attempt["job_attempt_id"]),
        lease_token=cast("str", attempt["lease_token"]),
        now_ns=now,
    )
    checked_at = time.time_ns()
    if checked_at < now:
        raise JobConflictError("Coordinator UTC moved backwards during admission")
    check_control()
    if time.monotonic_ns() >= window.deadline_ns or checked_at >= cast(
        "int", attempt["lease_expires_at_ns"]
    ):
        raise _LeaseExpired


@contextmanager
def _success_admission(store: JobRepository, row: Row, window: _LeaseWindow) -> Iterator[None]:
    if current_control() is None:
        yield
        return
    # Both Catalog authority and the fixed total deadline must be fresh under
    # the same gate BEFORE the irreversible admission marker is committed.
    with control_admission():
        _assert_publication_authority(store, row, window)
        with control_publication():
            yield


def _complete_followup(
    store: JobRepository,
    row: Row,
    spec: JobSpec,
    dispatch: JobSpec,
    outcome: bytes,
    action: str,
    window: _LeaseWindow,
) -> Row:
    """Publish a separate acknowledgment; an uncertain commit is never retried here."""
    raw = build_followup_result(spec, dispatch, outcome, action)
    with _success_admission(store, row, window):
        _assert_publication_authority(store, row, window)
        attempt = cast("Row", row["attempt"])
        return store.complete(
            spec.spec_id,
            raw,
            expected_version=cast("int", row["version"]),
            coordinator_id=cast("str", attempt["coordinator_id"]),
            job_attempt_id=cast("str", attempt["job_attempt_id"]),
            lease_token=cast("str", attempt["lease_token"]),
            now_ns=time.time_ns(),
        )


def _run_native_claimed(
    store: JobRepository,
    row: Row,
    window: _LeaseWindow,
    *,
    _worker_command: tuple[str, ...] | None,
) -> Row:
    spec = load_job_spec(canonical(cast("Row", row["spec"])))
    origin = execution_origin_spec(spec)
    followup = spec.document["operation"] == "resolve_reduction_job_v1"
    try:
        if followup:
            store.validate_followup_context(spec.spec_id)
        # Validate actual source/preparation and original live prefix first.
        prepared = prepare_native_job(origin)
        _assert_publication_authority(store, row, window)
    except _LeaseExpired:
        return _lost_lease(store, store.get(spec.spec_id), now_ns=time.time_ns())
    except JobStoreError:
        raise
    except Exception as error:
        return _finish_failure(store, row, _native_failure(error), window)

    family = JobFamily(origin)
    if followup and cast("Row", spec.document["request"])["mode"] == "acknowledge_committed_v1":
        # No lockfile/journal creation, optional-runtime check or research write.
        committed = find_committed_dispatch(origin, family.specs())
        if committed is None:
            return _finish_failure(
                store,
                row,
                {
                    "code": "research_outcome_not_committed",
                    "message": "No verified committed outcome was observed in this lineage",
                    "worker_exit_code": None,
                },
                window,
            )
        dispatch, outcome = committed
        try:
            return _complete_followup(
                store, row, spec, dispatch, outcome, "acknowledged_committed", window
            )
        except _LeaseExpired:
            return _lost_lease(store, store.get(spec.spec_id), now_ns=time.time_ns())

    if not followup:
        try:
            job_reduction.require_native_runtime()
            # Immutable exhausted slots cannot become available again. Refuse
            # a known-full original budget before creating operational family
            # metadata, while preserving the existing duplicate-nonce path.
            slots = prepared.ledger.list_reservations(prepared.execution.protocol)
            budget = cast("dict[str, int]", prepared.execution.protocol.document["budget"])
            if len(slots) >= budget["max_attempts"] and all(
                item.document["nonce"] != job_dispatch_nonce(spec) for item in slots
            ):
                raise AttemptBudgetExceededError(
                    "This protocol's immutable attempt budget is exhausted"
                )
        except Exception as error:
            return _finish_failure(store, row, _native_failure(error), window)
    # Every current native publisher for this original Job shares this lock,
    # including original execution, across Catalogs and their stale backups.
    with family.locked():
        try:
            _assert_publication_authority(store, row, window)
        except _LeaseExpired:
            return _lost_lease(store, store.get(spec.spec_id), now_ns=time.time_ns())
        if followup:
            committed = find_committed_dispatch(origin, family.specs())
            if committed is not None:
                dispatch, outcome = committed
                try:
                    return _complete_followup(
                        store, row, spec, dispatch, outcome, "acknowledged_committed", window
                    )
                except _LeaseExpired:
                    return _lost_lease(store, store.get(spec.spec_id), now_ns=time.time_ns())
            try:
                _assert_publication_authority(store, row, window)
            except _LeaseExpired:
                return _lost_lease(store, store.get(spec.spec_id), now_ns=time.time_ns())
            family.claim_retry(spec)
        return _execute_native_claimed(store, row, window, _worker_command=_worker_command)


def _execute_native_claimed(
    store: JobRepository,
    row: Row,
    window: _LeaseWindow,
    *,
    _worker_command: tuple[str, ...] | None,
) -> Row:
    job_id = cast("str", row["job_id"])
    spec = load_job_spec(canonical(cast("Row", row["spec"])))

    def fence() -> None:
        _assert_publication_authority(store, row, window)

    try:
        prepared = prepare_native_job(spec)
        with control_admission():
            reservation = authorize_native_job(prepared, fence=fence)
    except _LeaseExpired:
        return _lost_lease(store, store.get(job_id), now_ns=time.time_ns())
    except JobStoreError:
        raise
    except Exception as error:
        return _finish_failure(store, store.get(job_id), _native_failure(error), window)

    # Research execution time never renews with a Job heartbeat. Startup,
    # request encoding/delivery, native computation and final IPC share it.
    native_started = time.monotonic_ns()
    window.native_deadline_ns = (
        native_started + cast("int", reservation.document["max_wall_seconds"]) * 1_000_000_000
    )
    attempt = cast("Row", row["attempt"])
    try:
        raw = build_native_worker_request(
            job_id=job_id,
            coordinator_id=cast("str", attempt["coordinator_id"]),
            job_attempt_id=cast("str", attempt["job_attempt_id"]),
            lease_token=cast("str", attempt["lease_token"]),
            research_attempt=reservation,
            intent=prepared.execution.intent,
            replay_input=prepared.execution.replay_input,
            native_deadline_ns=window.native_deadline_ns,
        )
        fence()
    except _LeaseExpired:
        return _lost_lease(store, store.get(job_id), now_ns=time.time_ns())
    except JobStoreError:
        raise
    except Exception as error:
        return _finish_failure(store, store.get(job_id), _native_failure(error), window)

    command = _worker_command or (
        str(Path(sys.executable).absolute()),
        "-I",
        "-B",
        "-m",
        "tickwitness.infrastructure.native_job_worker",
    )
    process: subprocess.Popen[bytes] | None = None
    terminal: Row | None = None
    errors = b""
    fault: Exception | None = None
    expired, wall_expired = False, False
    with _workspace(row, prefix="tickwitness-native-job-") as cwd:
        try:
            process = _start_worker(command, cwd)
            row, terminal, errors = _exchange(process, raw, store, row, window)
        except _NativeDeadlineExpired:
            wall_expired = True
        except _LeaseExpired:
            expired = True
        except (OSError, _WorkerFault, ValueError) as error:
            if isinstance(error, JobStoreError):
                raise
            fault = error
        finally:
            if process is not None:
                try:
                    _terminate(process)
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            with suppress(OSError):
                                stream.close()
    check_control()
    row = store.get(job_id)
    _resource_stop(process.returncode if process is not None else None)
    if expired or time.monotonic_ns() >= window.deadline_ns:
        return _lost_lease(store, row, now_ns=time.time_ns())
    exit_code = process.returncode if process is not None else None
    if wall_expired or exit_code == -signal.SIGALRM:
        return _finish_failure(
            store,
            row,
            {
                "code": "research_wall_time_limit",
                "message": "Original native attempt wall limit expired; its slot remains consumed",
                "worker_exit_code": exit_code,
            },
            window,
        )
    # Only actual exit before the immutable native deadline can be admitted.
    # Subsequent independent audit/publication has its own current Job lease.
    window.native_deadline_ns = None
    if (
        fault is not None
        or terminal is None
        or (terminal["kind"] == "job_native_result_v1" and exit_code != 0)
    ):
        message = str(fault) if fault is not None else "Native worker exited without a valid result"
        if errors:
            message += ": " + errors.decode("utf-8", errors="replace")
        return _finish_failure(
            store,
            row,
            {
                "code": "job_worker_failed",
                "message": message[:2048],
                "worker_exit_code": exit_code,
            },
            window,
        )
    if terminal["kind"] == "job_failure_v1":
        diagnostic = cast("Row", terminal["failure"])
        if diagnostic["worker_exit_code"] != exit_code:
            diagnostic = {
                "code": "job_worker_protocol_error",
                "message": "Native failure frame and actual exit differ",
                "worker_exit_code": exit_code,
            }
        return _finish_failure(store, row, diagnostic, window)
    try:
        reopened, audited = audit_native_job(
            prepared,
            reservation,
            canonical(cast("Row", terminal["replay_result"])),
        )
    except Exception as error:
        return _finish_failure(
            store, row, _native_failure(error, worker_exit_code=exit_code), window
        )
    try:
        check_control()
        _before_control_publication(row)
        with _success_admission(store, row, window):
            # Never turn publication/confirmation uncertainty into another research
            # outcome or a new execution. The receipt may already be committed.
            try:
                output = publish_native_job(reopened, reservation, audited, fence=fence)
            except _LeaseExpired:
                return _lost_lease(store, store.get(job_id), now_ns=time.time_ns())
            try:
                fence()
            except _LeaseExpired:
                return _lost_lease(store, store.get(job_id), now_ns=time.time_ns())
            if spec.document["operation"] == "resolve_reduction_job_v1":
                try:
                    return _complete_followup(
                        store, row, spec, spec, output, "replayed_from_origin", window
                    )
                except _LeaseExpired:
                    return _lost_lease(store, store.get(job_id), now_ns=time.time_ns())
            attempt = cast("Row", row["attempt"])
            return store.complete(
                job_id,
                output,
                expected_version=cast("int", row["version"]),
                coordinator_id=cast("str", attempt["coordinator_id"]),
                job_attempt_id=cast("str", attempt["job_attempt_id"]),
                lease_token=cast("str", attempt["lease_token"]),
                now_ns=time.time_ns(),
            )

    except _LeaseExpired:
        return _lost_lease(store, store.get(job_id), now_ns=time.time_ns())


def _settle_control_stop(
    store: JobRepository, row: Row, control: JobExecutionControl, stopped: JobControlStop
) -> Row:
    """Record non-success without renewing or weakening an expired worker lease."""
    if row["state"] != "RUNNING":
        return row
    now = time.time_ns()
    attempt = cast("Row", row["attempt"])
    if now >= cast("int", attempt["lease_expires_at_ns"]):
        return store.mark_lost(
            cast("str", row["job_id"]),
            expected_version=cast("int", row["version"]),
            reason="lease_expired",
            now_ns=now,
        )
    return store.fail(
        cast("str", row["job_id"]),
        {
            "code": stopped.code,
            "message": str(stopped)[:2048],
            "worker_exit_code": control.worker_exit_code,
        },
        expected_version=cast("int", row["version"]),
        coordinator_id=cast("str", attempt["coordinator_id"]),
        job_attempt_id=cast("str", attempt["job_attempt_id"]),
        lease_token=cast("str", attempt["lease_token"]),
        now_ns=now,
    )


def run_job(
    store: JobRepository, job_id: str, *, _worker_command: tuple[str, ...] | None = None
) -> Row:
    """Run one allowlisted Job, enforcing its separately frozen policy when present."""
    if os.name != "posix":
        raise JobConflictError("Managed Job supervision requires POSIX")
    with store.coordinator() as coordinator_id:
        store.reconcile_orphans(now_ns=time.time_ns())
        row = store.get(job_id)
        if row["state"] in {"SUCCEEDED", "FAILED", "LOST"}:
            return row
        if row["state"] != "QUEUED":
            raise JobConflictError("Only a queued Job may start a worker")
        root = getattr(store, "root", None)
        controls = JobControlStore(root, job_id) if isinstance(root, Path) else None
        policy = controls.policy() if controls is not None else None
        if policy is None or controls is None:
            return _run_queued_job(
                store, row, coordinator_id, _worker_command=_worker_command
            )
        validate_worker_limits(policy)
        control = JobExecutionControl(controls)
        with control.activate():
            try:
                result = _run_queued_job(
                    store, row, coordinator_id, _worker_command=_worker_command
                )
            except JobControlStop as stopped:
                result = _settle_control_stop(store, store.get(job_id), control, stopped)
                control.finish(result, cause=stopped.code, diagnostic=str(stopped))
                return result
            except BaseException as error:
                control.finish(
                    store.get(job_id),
                    cause="coordinator_interrupted"
                    if isinstance(error, (KeyboardInterrupt, SystemExit))
                    else "job_control_error",
                    diagnostic=str(error)[:2048],
                )
                raise
            else:
                control.finish(result)
                return result


def _run_queued_job(
    store: JobRepository,
    row: Row,
    coordinator_id: str,
    *,
    _worker_command: tuple[str, ...] | None,
) -> Row:
    job_id = cast("str", row["job_id"])
    claim_clock = time.monotonic_ns()
    row = store.claim(
        job_id,
        expected_version=cast("int", row["version"]),
        coordinator_id=coordinator_id,
        attempt_nonce=secrets.token_hex(32),
        lease_token=secrets.token_hex(32),
        now_ns=time.time_ns(),
    )
    control = current_control()
    if control is not None:
        control.bind(row)
    check_control()
    window = _LeaseWindow(
        claim_clock + cast("int", cast("Row", row["spec"])["lease_duration_ns"])
    )
    if cast("Row", row["spec"])["operation"] in {
        "execute_reduction_input_v1",
        "resolve_reduction_job_v1",
    }:
        return _run_native_claimed(store, row, window, _worker_command=_worker_command)
    attempt = cast("Row", row["attempt"])
    raw = canonical(
        {
            "kind": "job_worker_request_v1",
            "schema_version": 1,
            "spec": row["spec"],
            "job_id": job_id,
            **{
                key: attempt[key] for key in ("coordinator_id", "job_attempt_id", "lease_token")
            },
        }
    )
    if len(raw) > MAX_JOB_REQUEST_BYTES:
        return _finish_failure(
            store,
            row,
            {
                "code": "job_request_too_large",
                "message": "Job IPC request exceeds 64 KiB",
                "worker_exit_code": None,
            },
            window,
        )
    command = _worker_command or (
        str(Path(sys.executable).absolute()),
        "-I",
        "-B",
        "-m",
        "tickwitness.infrastructure.job_worker",
    )
    process: subprocess.Popen[bytes] | None = None
    terminal: Row | None = None
    errors = b""
    fault: Exception | None = None
    expired = False
    with _workspace(row, prefix="tickwitness-job-") as cwd:
        try:
            process = _start_worker(command, cwd)
            row, terminal, errors = _exchange(process, raw, store, row, window)
        except _LeaseExpired:
            expired = True
        except (OSError, _WorkerFault, ValueError) as error:
            # Store/conflict errors must not be rewritten as worker failures.
            if isinstance(error, JobStoreError):
                raise
            fault = error
        finally:
            if process is not None:
                try:
                    _terminate(process)
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            with suppress(OSError):
                                stream.close()
    # Heartbeats may have committed before an interrupted exchange. Never
    # finish against an old version or turn an uncertain DB write into FAILED.
    check_control()
    row = store.get(job_id)
    _resource_stop(process.returncode if process is not None else None)
    if expired or time.monotonic_ns() >= window.deadline_ns:
        return _lost_lease(store, row, now_ns=time.time_ns())
    exit_code = process.returncode if process is not None else None
    if (
        fault is not None
        or terminal is None
        or (terminal["kind"] == "job_result_v1" and exit_code != 0)
    ):
        message = (
            str(fault)
            if fault is not None
            else "Worker exited without a valid successful result"
        )
        if errors:
            message += ": " + errors.decode("utf-8", errors="replace")
        return _finish_failure(
            store,
            row,
            {
                "code": "job_worker_failed",
                "message": message[:2048],
                "worker_exit_code": exit_code,
            },
            window,
        )
    if terminal["kind"] == "job_failure_v1":
        diagnostic = cast("Row", terminal["failure"])
        if diagnostic["worker_exit_code"] != exit_code:
            diagnostic = {
                "code": "job_worker_protocol_error",
                "message": "Failure frame and actual process exit differ",
                "worker_exit_code": exit_code,
            }
        return _finish_failure(store, row, diagnostic, window)
    output = canonical(cast("Row", terminal["export"]))
    spec = load_job_spec(canonical(cast("Row", row["spec"])))
    attempt = cast("Row", row["attempt"])
    validation_started = time.time_ns()
    if validation_started < cast("int", row["updated_at_ns"]):
        raise JobConflictError("Coordinator UTC moved backwards; lease validity is uncertain")
    try:
        independently_verified = execute_comparison(spec, saved=output)
        if independently_verified != output:
            raise _WorkerFault("Coordinator re-audit differs from worker output")
    except Exception as error:
        diagnostic = _failure(error)
        diagnostic["message"] = ("Coordinator re-audit rejected result: " + str(error))[:2048]
        diagnostic["worker_exit_code"] = exit_code
        return _finish_failure(store, row, diagnostic, window)
    try:
        check_control()
        with _success_admission(store, row, window):
            attempt = cast("Row", row["attempt"])
            now = time.time_ns()
            if time.monotonic_ns() >= window.deadline_ns or now >= cast(
                "int", attempt["lease_expires_at_ns"]
            ):
                return _lost_lease(store, row, now_ns=now)
            # Deliberately outside error->failure handling: a commit failure may have
            # published SUCCEEDED. Only later independent inspection may resolve it.
            return store.complete(
                job_id,
                output,
                expected_version=cast("int", row["version"]),
                coordinator_id=cast("str", attempt["coordinator_id"]),
                job_attempt_id=cast("str", attempt["job_attempt_id"]),
                lease_token=cast("str", attempt["lease_token"]),
                now_ns=now,
            )

    except _LeaseExpired:
        return _lost_lease(store, store.get(job_id), now_ns=time.time_ns())
