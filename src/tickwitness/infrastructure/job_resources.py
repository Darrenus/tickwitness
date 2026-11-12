"""Same-user no-follow immutable resource observations outside the control journal."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import cast

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.evidence.run_records import identity
from tickwitness.domain.jobs.control import JobControlPolicy
from tickwitness.domain.jobs.resources import JobResourceReport, load_job_resource_report
from tickwitness.infrastructure.job_controls import JobControlStore

_NAMESPACE = ".job-resources"
_REPORT = "report.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobStoreError(message)


class JobResourceStore:
    """One immutable report, serialized with the original frozen control gate."""

    def __init__(self, catalog_root: Path, job_id: str) -> None:
        self._root = Path(catalog_root).absolute()
        self._job_id = identity(job_id)
        self._controls = JobControlStore(self._root, self._job_id)

    @contextmanager
    def _job_directory(self, *, create: bool = False) -> Iterator[tuple[int, bool] | None]:
        try:
            with ExitStack() as stack:
                try:
                    root = stack.enter_context(JobControlStore._directory(self._root))
                except FileNotFoundError:
                    if create:
                        raise
                    yield None
                    return
                if create:
                    JobControlStore._mkdir(root, _NAMESPACE)
                try:
                    namespace = stack.enter_context(JobControlStore._directory(root, _NAMESPACE))
                except FileNotFoundError:
                    if create:
                        raise
                    yield None
                    return
                created = JobControlStore._mkdir(namespace, self._job_id) if create else False
                try:
                    directory = stack.enter_context(
                        JobControlStore._directory(namespace, self._job_id)
                    )
                except FileNotFoundError:
                    if create:
                        raise
                    yield None
                    return
                yield directory, created
        except OSError as error:
            raise JobStoreError("Cannot access Job resource namespace: " + str(error)) from error

    def _record(self, directory: int, policy: JobControlPolicy) -> JobResourceReport:
        found = False
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                _require(
                    index == 0 and entry.name == _REPORT,
                    "Resource publication has unknown entries",
                )
                found = True
        _require(found, "Resource publication is incomplete")
        report = load_job_resource_report(JobControlStore._read(directory, _REPORT))
        document = report.document
        _require(
            document["job_id"] == self._job_id and document["policy_id"] == policy.policy_id,
            "Resource report differs from its immutable Job/policy binding",
        )
        return report

    def read(self) -> JobResourceReport | None:
        try:
            with self._job_directory() as found:
                if found is None:
                    return None
                with self._controls._reader() as controlled:
                    _require(controlled is not None, "Resource report requires a frozen policy")
                    policy = cast("tuple[int, JobControlPolicy]", controlled)[1]
                    return self._record(found[0], policy)
        except (OSError, ValueError) as error:
            if isinstance(error, JobStoreError):
                raise
            raise JobStoreError("Cannot read Job resource report: " + str(error)) from error

    def seal(self, report: JobResourceReport) -> JobResourceReport:
        checked = load_job_resource_report(report.canonical_bytes)
        if checked.report_id != report.report_id or checked.document["job_id"] != self._job_id:
            raise JobConflictError("Resource report must bind this exact Job")
        policy = self._controls.policy()
        if policy is None or checked.document["policy_id"] != policy.policy_id:
            raise JobConflictError("Resource report requires its exact frozen policy")
        try:
            with self._controls.gate():
                admitted = self._controls.policy()
                _require(admitted is not None, "Resource policy disappeared before publication")
                policy = cast("JobControlPolicy", admitted)
                _require(
                    policy.policy_id == checked.document["policy_id"], "Resource policy changed"
                )
                with self._job_directory(create=True) as found:
                    _require(found is not None, "Cannot create resource publication namespace")
                    directory, created = cast("tuple[int, bool]", found)
                    if not created:
                        previous = self._record(directory, policy)
                        if previous.canonical_bytes != checked.canonical_bytes:
                            raise JobConflictError("Immutable Job resource report already differs")
                        return previous
                    JobControlStore._publish(directory, _REPORT, checked.canonical_bytes)
                    with self._job_directory() as current:
                        _require(current is not None, "Resource publication namespace disappeared")
                        original = os.fstat(directory)
                        live = os.fstat(cast("tuple[int, bool]", current)[0])
                        _require(
                            (original.st_dev, original.st_ino) == (live.st_dev, live.st_ino),
                            "Resource publication directory was replaced",
                        )
                    stored = self._record(directory, policy)
                    _require(stored == checked, "Resource report readback differs")
                    return stored
        except (OSError, ValueError) as error:
            if isinstance(error, JobStoreError):
                raise
            raise JobStoreError("Cannot publish Job resource report: " + str(error)) from error
