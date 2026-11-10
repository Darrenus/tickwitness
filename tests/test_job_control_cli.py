"""New control commands preserve confirmation and read-only admission boundaries."""

import json

import pytest
from test_jobs_cli import _submit

from tickwitness import cli_jobs
from tickwitness.cli import main


@pytest.mark.parametrize(
    "command",
    [
        "configure-job-control",
        "cancel-job",
        "inspect-job-control",
        "reclaim-job-workspaces",
    ],
)
def test_controls_confirmation_is_denied_before_identity_or_catalog(
    tmp_path, capsys, monkeypatch, command
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Confirmation must not access the Catalog")

    monkeypatch.setattr(cli_jobs, "SqliteJobStore", forbidden)
    arguments = [command, "invalid", "--jobs", str(tmp_path / "missing"), "--split", "confirmation"]
    if command == "cancel-job":
        arguments.extend(["--cancel-key", "invalid key"])
    assert main(arguments) == 5
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_public_queue_policy_cancel_and_reclaim_never_start_research(tmp_path, capsys):
    assert main(_submit(tmp_path)) == 0
    submitted = json.loads(capsys.readouterr().out)
    common = [submitted["job_id"], "--jobs", str(tmp_path / "jobs")]
    assert main(["inspect-job-control", *common]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "UNCONFIGURED"
    assert not (tmp_path / "jobs" / ".job-controls").exists()
    assert main(["configure-job-control", *common]) == 0
    frozen = json.loads(capsys.readouterr().out)
    assert frozen["policy"]["job_id"] == submitted["job_id"]
    assert main(["configure-job-control", *common, "--wall-seconds", "60"]) == 9
    assert not capsys.readouterr().out
    assert main(["cancel-job", *common, "--cancel-key", "queue-stop"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "accepted"
    assert main(["inspect-job-control", *common]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["status"] == "STOP_CONFIRMED"
    assert inspected["job"]["stored_state"] == "FAILED"
    assert inspected["control_result"]["cause"] == "job_cancelled"
    assert not inspected["control_result"]["worker_started"]
    assert main(["configure-job-control", *common]) == 0
    assert json.loads(capsys.readouterr().out) == frozen
    assert main(["cancel-job", *common, "--cancel-key", "queue-stop"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_requested"
    assert main(["reclaim-job-workspaces", *common]) == 0
    assert json.loads(capsys.readouterr().out)["pid_signalled"] is False
    assert not (tmp_path / "runs").exists()
