"""Live Job control admission, owned processes and independently recorded stop facts."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from typing import cast

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.jobs import load_job_snapshot
from tickwitness.domain.jobs.control import JobControlPolicy, load_job_control_result
from tickwitness.infrastructure.job_control_bootstrap import checked_limits
from tickwitness.infrastructure.job_control_workspace import OwnedJobWorkspace, reclaim_workspace
from tickwitness.infrastructure.job_controls import JobControlStore

type Row = dict[str, object]
_ACTIVE_CONTROL: ContextVar[JobExecutionControl | None] = ContextVar(
    "active_job_execution_control", default=None
)


class JobControlStop(BaseException):
    """A non-success stop bypassing legacy exception-to-research-failure paths."""

    def __init__(self, code: str, diagnostic: str = "") -> None:
        if code not in {"job_cancelled", "job_deadline_exceeded", "job_resource_limit"}:
            raise ValueError("Unsupported Job control stop reason")
        self.code = code
        super().__init__(diagnostic or code)


def validate_worker_limits(policy: JobControlPolicy) -> None:
    try:
        checked_limits(policy.document)
    except (OSError, ValueError) as error:
        raise JobConflictError(
            "Requested Job worker limits cannot be enforced: " + str(error)
        ) from error


class JobExecutionControl:
    """One nonresumable live coordinator control context, never a research budget."""

    def __init__(self, control: JobControlStore) -> None:
        policy = control.policy()
        if policy is None:
            raise JobConflictError("An execution control requires a configured policy")
        self.control, self.policy = control, policy
        self._limits = cast("dict[str, int]", policy.document["limits"])
        self._started_ns = time.monotonic_ns()
        self.deadline_ns = self._started_ns + self._limits["max_wall_ns"]
        self._pid = os.getpid()
        self._row: Row | None = None
        self._admission_depth = 0
        self._publication_depth = 0
        self._publication_seen = False
        self._request_observed: int | None = None
        self._worker_reaped: int | None = None
        self._cleanup_finished: int | None = None
        self._workspace: OwnedJobWorkspace | None = None
        self._owned_process: subprocess.Popen[bytes] | None = None
        self._worker_started = False
        self._worker_exit_code: int | None = None
        self._worker_group_absent = True
        self._stop_attempted = False
        self._cleanup_deadline_ns: int | None = None
        self._finish_attempted = False
        self._finished: Row | None = None

    @property
    def worker_exit_code(self) -> int | None:
        return self._worker_exit_code

    def _elapsed(self) -> int:
        elapsed = time.monotonic_ns() - self._started_ns
        if elapsed < 0:
            raise JobStoreError("Job monotonic control clock regressed")
        return elapsed

    def _current(self) -> None:
        if os.getpid() != self._pid:
            raise JobConflictError("Job control cannot be inherited by a different coordinator")

    @contextmanager
    def activate(self) -> Iterator[None]:
        self._current()
        existing = current_control()
        if existing is not None and existing is not self:
            raise JobConflictError("Another Job control is already active in this context")
        token = _ACTIVE_CONTROL.set(self)
        try:
            yield
        finally:
            _ACTIVE_CONTROL.reset(token)

    def bind(self, row: Row) -> None:
        self._current()
        checked = load_job_snapshot(canonical(row))
        if checked["job_id"] != self.policy.document["job_id"] or checked["attempt"] is None:
            raise JobStoreError("Job control must bind its actual claimed Job attempt")
        if self._row is not None and self._row["attempt"] != checked["attempt"]:
            raise JobConflictError("Job control cannot be rebound to a different attempt")
        self._row = checked

    def check(self) -> None:
        self._current()
        if self._publication_depth:
            return
        if time.monotonic_ns() >= self.deadline_ns:
            raise JobControlStop(
                "job_deadline_exceeded", "Fixed Job total admission deadline expired"
            )
        try:
            requested = self.control.cancel_request()
        except JobConflictError:
            # An immutable request can be inside its short publication transaction.
            # No irreversible action bypasses the separate exclusive admission gate.
            return
        if requested is not None:
            if self._request_observed is None:
                self._request_observed = self._elapsed()
            raise JobControlStop("job_cancelled", "Durable explicit cancellation was observed")

    @contextmanager
    def admission(self) -> Iterator[None]:
        self._current()
        if self._admission_depth:
            self.check()
            yield
            return
        # Only an unentered read/control gate is retried. No uncertain write,
        # worker computation or research admission is replayed here.
        gate_deadline = min(
            self.deadline_ns,
            time.monotonic_ns() + min(1_000_000_000, self._limits["cleanup_grace_ns"]),
        )
        with ExitStack() as stack:
            for retry in range(101):
                try:
                    stack.enter_context(self.control.gate())
                    break
                except JobConflictError:
                    self.check()
                    if retry == 100 or time.monotonic_ns() >= gate_deadline:
                        raise
                    time.sleep(0.01)
            self.check()
            self._admission_depth = 1
            try:
                yield
            finally:
                self._admission_depth = 0

    @contextmanager
    def publication(self) -> Iterator[None]:
        if self._publication_depth:
            yield
            return
        if self._publication_seen:
            raise JobStoreError("An irreversible publication admission cannot be resumed")
        if self._row is None:
            raise JobStoreError("Job control publication requires an actual claimed attempt")
        attempt = cast("Row", self._row["attempt"])
        with self.admission():
            self.control.admit_publication(
                cast("str", attempt["job_attempt_id"]), now_ns=time.time_ns()
            )
            self._publication_seen = True
            self._publication_depth = 1
            try:
                yield
            finally:
                self._publication_depth = 0

    @contextmanager
    def workspace(self, row: Row) -> Iterator[Path]:
        self._current()
        if self._workspace is not None or self._row is None:
            raise JobConflictError("A controlled attempt may create exactly one owned workspace")
        if (
            cast("Row", row["attempt"])["job_attempt_id"]
            != cast("Row", self._row["attempt"])["job_attempt_id"]
        ):
            raise JobStoreError("Workspace attempt differs from the bound control")
        self.check()
        workspace = OwnedJobWorkspace(self.control.directory, self.policy.policy_id, row)
        self._workspace = workspace
        body_error: BaseException | None = None
        try:
            workspace.create()
            yield workspace.scratch
        except BaseException as error:
            body_error = error
            raise
        finally:
            try:
                if self._owned_process is not None and not self._stop_attempted:
                    self.stop_process(self._owned_process)
                workspace.close_parent_lifetime()
                if self._worker_started and not self._worker_group_absent:
                    if body_error is not None:
                        raise body_error
                    raise JobStoreError("Worker group stop is unconfirmed; owned scratch retained")
                if self._cleanup_deadline_ns is None:
                    self._cleanup_deadline_ns = (
                        time.monotonic_ns() + self._limits["cleanup_grace_ns"]
                    )
                workspace.cleanup(
                    group_absent=self._worker_group_absent, deadline_ns=self._cleanup_deadline_ns
                )
                self._cleanup_finished = self._elapsed()
            except OSError as error:
                raise JobStoreError(
                    "Owned workspace cleanup is unconfirmed: " + str(error)
                ) from error
            finally:
                workspace.close()

    def spawn(
        self,
        command: tuple[str, ...],
        *,
        stdin: int = subprocess.PIPE,
        stdout: int = subprocess.PIPE,
        stderr: int = subprocess.PIPE,
        cwd: str | Path | None = None,
        start_new_session: bool = True,
        close_fds: bool = True,
    ) -> subprocess.Popen[bytes]:
        self._current()
        workspace = self._workspace
        if workspace is None or workspace.lifetime_fd is None or self._worker_started:
            raise JobStoreError("Worker startup requires its one owned lifetime workspace")
        if (
            not start_new_session
            or not close_fds
            or (cwd is not None and Path(cwd) != workspace.scratch)
        ):
            raise JobStoreError("Controlled workers require owned scratch and a fresh session")
        with self.admission():
            workspace.verify()
            bootstrap = Path(__file__).with_name("job_control_bootstrap.py").absolute()
            wrapped = (
                str(Path(sys.executable).absolute()),
                "-I",
                "-B",
                str(bootstrap),
                self.policy.canonical_bytes.decode("utf-8"),
                self.policy.policy_id,
                str(self.deadline_ns),
                str(workspace.lifetime_fd),
                "--",
                *command,
            )
            process = subprocess.Popen(
                wrapped,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                cwd=workspace.scratch,
                start_new_session=True,
                close_fds=True,
                pass_fds=(workspace.lifetime_fd,),
            )
            self._owned_process = process
            self._worker_started = True
            self._worker_group_absent = False
            workspace.close_parent_lifetime()
            return process

    def stop_process(self, process: subprocess.Popen[bytes]) -> None:
        self._current()
        if process is not self._owned_process or self._stop_attempted:
            raise JobStoreError("Worker cleanup requires its current unreaped child identity once")
        self._stop_attempted = True
        self._cleanup_deadline_ns = time.monotonic_ns() + self._limits["cleanup_grace_ns"]
        if process.pid <= 0 or process.pid == os.getpgrp() or process.returncode is not None:
            raise JobStoreError("Worker leader was reaped or its process-group identity is unsafe")
        try:
            # Natural exit can race the request. Only bounded wait plus strict
            # group observation below can establish confirmed cleanup.
            with suppress(ProcessLookupError, PermissionError):
                os.kill(process.pid, signal.SIGTERM)
            remaining = min(
                0.5,
                max(0, self._cleanup_deadline_ns - time.monotonic_ns()) / 1_000_000_000,
            )
            try:
                self._worker_exit_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                if process.returncode is not None:
                    raise JobStoreError(
                        "Anchor identity was reaped during stop admission"
                    ) from None
                # This sole fallback precedes reaping. A timeout has not made
                # the live owned leader PID reusable; never repeat it later.
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                remaining = max(0, self._cleanup_deadline_ns - time.monotonic_ns()) / 1_000_000_000
                self._worker_exit_code = process.wait(timeout=remaining)
            self._worker_reaped = self._elapsed()
            while True:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    self._worker_group_absent = True
                    return
                if time.monotonic_ns() >= self._cleanup_deadline_ns:
                    raise JobStoreError("Worker process group remains; cleanup is unconfirmed")
                time.sleep(0.01)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise JobStoreError("Owned worker termination is unconfirmed: " + str(error)) from error

    def finish(self, snapshot: Row | None, *, cause: str = "finished", diagnostic: str = "") -> Row:
        self._current()
        if self._finish_attempted:
            if self._finished is None:
                raise JobStoreError("Control result publication is unconfirmed; never auto-retry")
            return load_job_control_result(canonical(self._finished))
        self._finish_attempted = True
        checked = None if snapshot is None else load_job_snapshot(canonical(snapshot))
        if checked is not None and checked["job_id"] != self.policy.document["job_id"]:
            raise JobStoreError("Control result snapshot belongs to another Job")
        admitted = self.control.publication_admission() is not None
        removed = self._workspace is None or self._workspace.removed
        cleanup = self._worker_group_absent and removed
        if cleanup and self._cleanup_finished is None:
            self._cleanup_finished = self._elapsed()
        attempt = None if self._row is None else cast("Row", self._row["attempt"])
        document: Row = {
            "kind": "job_control_result_v1",
            "schema_version": 1,
            "job_id": self.policy.document["job_id"],
            "policy_id": self.policy.policy_id,
            "job_attempt_id": None if attempt is None else attempt["job_attempt_id"],
            "cause": cause,
            "catalog_state": None if checked is None else checked["state"],
            "catalog_snapshot_sha256": None if checked is None else digest(canonical(checked)),
            "publication_admitted": admitted,
            "worker_started": self._worker_started,
            "worker_exit_code": self._worker_exit_code,
            "worker_group_absent": self._worker_group_absent,
            "workspace_removed": removed,
            "cleanup_confirmed": cleanup,
            "stop_confirmed": cause
            in {"job_cancelled", "job_deadline_exceeded", "job_resource_limit"}
            and cleanup
            and (not self._worker_started or self._worker_exit_code is not None),
            "timing_ns": {
                "elapsed": self._elapsed(),
                "request_observed": self._request_observed,
                "worker_reaped": self._worker_reaped,
                "cleanup_finished": self._cleanup_finished,
            },
            "diagnostic": diagnostic[:2048],
        }
        self._finished = self.control.write_result(document)
        return load_job_control_result(canonical(self._finished))


def current_control() -> JobExecutionControl | None:
    return _ACTIVE_CONTROL.get()


def check_control() -> None:
    control = current_control()
    if control is not None:
        control.check()


@contextmanager
def control_admission() -> Iterator[None]:
    control = current_control()
    if control is None:
        yield
    else:
        with control.admission():
            yield


@contextmanager
def control_publication() -> Iterator[None]:
    control = current_control()
    if control is None:
        yield
    else:
        with control.publication():
            yield


def reclaim_workspaces(control: JobControlStore, snapshot: Row) -> Row:
    snapshot = load_job_snapshot(canonical(snapshot))
    policy = control.policy()
    if policy is None or snapshot["job_id"] != policy.document["job_id"]:
        raise JobConflictError("Workspace reclamation requires this Job's configured policy")
    try:
        outcome = reclaim_workspace(
            control.directory,
            policy.policy_id,
            snapshot,
            grace_ns=cast("dict[str, int]", policy.document["limits"])["cleanup_grace_ns"],
        )
    except OSError as error:
        raise JobStoreError("Workspace reclamation is unconfirmed: " + str(error)) from error
    return {
        "kind": "job_workspace_reclamation_v1",
        "schema_version": 1,
        "job_id": snapshot["job_id"],
        "policy_id": policy.policy_id,
        **outcome,
        "pid_signalled": False,
    }
