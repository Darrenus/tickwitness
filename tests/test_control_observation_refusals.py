"""Read-only smoke observers distinguish catalog churn from integrity failures."""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.jobs import JobConflictError, JobNotFoundError, JobStoreError
from tickwitness.infrastructure import job_controls, sqlite_job_store


def observation_source(name: str) -> str:
    script = Path(__file__).parents[1] / "scripts/smoke_job_controls.py"
    for node in ast.parse(script.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return str(ast.literal_eval(node.value))
    raise AssertionError("Missing read-only smoke observer")


@pytest.mark.parametrize("observer", ["_CONTROL_VIEW", "_CATALOG_ONLY"])
@pytest.mark.parametrize(
    ("failure", "retry_code"),
    [
        (JobConflictError("busy"), "job_conflict"),
        (JobStoreError("Job catalog path changed while open"), "readonly_snapshot_unstable"),
        (JobStoreError("Job catalog files must be unaliased regular files"), None),
        (JobNotFoundError("Job catalog path changed while open"), None),
    ],
)
def test_only_explicit_read_refusals_are_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    observer: str,
    failure: JobStoreError,
    retry_code: str | None,
) -> None:
    class RefusedStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            assert kwargs == {"create": False}

        def result(self, job_id: str) -> None:
            raise failure

    monkeypatch.setattr(sqlite_job_store, "SqliteJobStore", RefusedStore)
    monkeypatch.setattr(
        job_controls, "JobControlStore", lambda *args: SimpleNamespace(policy=lambda: None)
    )
    stderr = io.StringIO()
    argument = '["job"]' if observer == "_CONTROL_VIEW" else "job"
    namespace = {
        "catalog": tmp_path,
        "json": json,
        "sys": SimpleNamespace(argv=["observer", argument], stderr=stderr),
    }
    source = compile(observation_source(observer), "read-only-control-observer", "exec")
    if retry_code is None:
        with pytest.raises(type(failure), match=str(failure)):
            exec(source, namespace)
        assert stderr.getvalue() == ""
    else:
        with pytest.raises(SystemExit) as exited:
            exec(source, namespace)
        assert exited.value.code == 9
        assert json.loads(stderr.getvalue())["error"]["code"] == retry_code
