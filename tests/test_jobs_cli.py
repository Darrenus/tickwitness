"""Public Job commands preserve refusal, visibility and read-only boundaries."""

import json

import pytest

from tickwitness import cli_jobs
from tickwitness.cli import main


def _submit(tmp_path, *, split="development", jobs=None):
    return [
        "submit-comparison-job",
        "0" * 64,
        "--input-root",
        str(tmp_path / "inputs"),
        "--source-evidence",
        "portable/source",
        "--runs",
        str(tmp_path / "runs"),
        "--expected-bundle-id",
        "1" * 64,
        "--expected-report-id",
        "2" * 64,
        "--jobs",
        str(jobs or tmp_path / "jobs"),
        "--split",
        split,
    ]


def test_confirmation_refused_before_identifiers_paths_or_catalog(tmp_path, capsys, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Confirmation must not access the catalog")

    monkeypatch.setattr(cli_jobs, "SqliteJobStore", forbidden)
    arguments = _submit(tmp_path, split="confirmation")
    arguments[1] = "invalid"
    assert main(arguments) == 5
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert not (tmp_path / "jobs").exists()


@pytest.mark.parametrize("command", ["inspect-job", "run-job", "read-job-result", "reconcile-jobs"])
def test_missing_catalog_is_not_created_by_queries_or_execution(tmp_path, capsys, command):
    arguments = [command]
    if command != "reconcile-jobs":
        arguments.append("0" * 64)
    arguments.extend(["--jobs", str(tmp_path / "absent")])
    assert main(arguments) == 4
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]["code"] == "job_not_found"
    assert not (tmp_path / "absent").exists()


def test_queued_public_view_event_metadata_and_terminal_failure_are_honest(tmp_path, capsys):
    assert main(_submit(tmp_path)) == 0
    created = json.loads(capsys.readouterr().out)
    job_id = created["job_id"]
    assert created["stored_state"] == created["state"] == "QUEUED"
    assert created["attempt"] is None and created["scope"]["native_replayed"] is False
    assert main(_submit(tmp_path)) == 0
    assert json.loads(capsys.readouterr().out) == created

    common = [job_id, "--jobs", str(tmp_path / "jobs")]
    assert main(["inspect-job", *common, "--events"]) == 0
    output = capsys.readouterr()
    inspected = json.loads(output.out)
    assert len(inspected["events"]) == 1
    assert inspected["events"][0]["aggregate_version"] == 1
    assert inspected["events"][0]["event_type"] == "JobSubmitted"
    assert inspected["complete_history_claimed"] is False
    assert "snapshot" not in inspected["events"][0]

    assert main(["read-job-result", *common]) == 9
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]["code"] == "job_conflict"

    # Missing real source is an execution failure, not a fake positive Job.
    assert main(["run-job", *common]) == 0
    output = capsys.readouterr()
    failed = json.loads(output.out)
    assert not output.err and failed["state"] == failed["stored_state"] == "FAILED"
    assert failed["failure"]["worker_exit_code"] == 4
    assert "lease_token" not in output.out and "nonce" not in output.out
    attempt_id = failed["attempt"]["job_attempt_id"]
    assert main(["run-job", *common]) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated == failed and repeated["attempt"]["job_attempt_id"] == attempt_id
    assert main(["reconcile-jobs", "--jobs", str(tmp_path / "jobs")]) == 0
    assert json.loads(capsys.readouterr().out)["jobs"] == []


def test_catalog_cannot_be_placed_in_observed_source_tree(tmp_path, capsys):
    jobs = tmp_path / "inputs" / "catalog"
    assert main(_submit(tmp_path, jobs=jobs)) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]["code"] == "invalid_job"
    assert not jobs.exists()
