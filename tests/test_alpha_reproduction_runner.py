"""The stdlib participant runner records real CLI-shaped outcomes without certification."""

import json
import runpy
import sys
from pathlib import Path

import pytest
from test_alpha_cli import export_kit, qualify_arguments

from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical, digest

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "reproduce_alpha.py"


def load_runner():
    return runpy.run_path(str(RUNNER))["main"]


def arguments(kit, kit_id, output, role="automation"):
    return ["--kit", str(kit), "--expected-kit-id", kit_id, "--participant-id", "remote-reproduction", "--participant-role", role, "--output", str(output)]


def submission(output):
    document = json.loads((output / "submission.json").read_bytes())
    assert document["submission_id"] == digest(canonical(document["submission"]))
    return document["submission"]


def test_success_preserves_actual_technical_receipt_and_unreviewed_automation_identity(tmp_path, capsys, monkeypatch):
    kit, kit_id = export_kit(tmp_path, capsys)
    assert main(qualify_arguments(kit, kit_id, tmp_path / "actual-probe")) == 0
    actual = capsys.readouterr()
    assert actual.err == ""
    receipt = json.loads(actual.out)
    calls = []
    run = load_runner()
    capture_result = run.__globals__["CaptureResult"]

    def completed(command):
        calls.append(command)
        assert command[1:3] == ["-I", "-c"]
        return capture_result(stdout=actual.out.encode(), exit_code=0, stdout_complete=True, stderr_complete=True, stdout_observed_bytes=len(actual.out.encode()))

    monkeypatch.setitem(run.__globals__, "_capture", completed)
    output = tmp_path / "submission-success"
    assert run(arguments(kit, kit_id, output)) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["outcome"] == "VERIFIED" and written["external_gate_updated"] is False
    record = submission(output)
    assert len(calls) == 1
    assert record["participant"] == {"id": "remote-reproduction", "role_declared": "automation"}
    assert record["review_status"] == "SELF_REPORTED_UNREVIEWED"
    assert record["participant_identity_authenticated"] is False
    assert record["external_gate_updated"] is False
    assert record["process_exit_code"] == 0
    assert record["elapsed_ns_observed"] >= 0
    assert record["stdout"] is None
    assert json.loads((output / "scorecard.json").read_bytes()) == receipt
    assert receipt["scorecard"]["gates"]["external_attempts"] == 0


def test_actual_cli_failure_is_preserved_with_exit_three_and_no_scorecard(tmp_path, capsys, monkeypatch):
    kit, kit_id = export_kit(tmp_path, capsys)
    assert main(qualify_arguments(kit, "0" * 64, tmp_path / "unused-probe")) == 3
    failed = capsys.readouterr()
    assert failed.out == ""
    run = load_runner()
    capture_result = run.__globals__["CaptureResult"]

    def completed(_command):
        return capture_result(stderr=failed.err.encode(), exit_code=3, stdout_complete=True, stderr_complete=True, stderr_observed_bytes=len(failed.err.encode()))

    monkeypatch.setitem(run.__globals__, "_capture", completed)
    output = tmp_path / "failed-submission"
    assert run(arguments(kit, kit_id, output, role="external_user")) == 10
    assert json.loads(capsys.readouterr().out)["outcome"] == "FAILED"
    record = submission(output)
    assert record["process_exit_code"] == 3
    assert record["stderr"]["text"] == failed.err
    assert record["scorecard_id"] is None
    assert record["participant"]["role_declared"] == "external_user"
    assert record["participant_identity_authenticated"] is False
    assert record["external_gate_updated"] is False
    assert not (output / "scorecard.json").exists()


def test_timeout_is_retained_and_existing_submission_is_never_reused(tmp_path, capsys, monkeypatch):
    kit = tmp_path / "kit"
    kit.mkdir()

    output = tmp_path / "timed-out-submission"
    run = load_runner()
    capture_result = run.__globals__["CaptureResult"]

    def timeout(_command):
        return capture_result(stdout=b"partial output", stderr=b"timeout diagnostic", timed_out=True, stdout_observed_bytes=len(b"partial output"), stderr_observed_bytes=len(b"timeout diagnostic"), stage="process_timeout")

    monkeypatch.setitem(run.__globals__, "_capture", timeout)
    assert run(arguments(kit, "a" * 64, output)) == 11
    assert json.loads(capsys.readouterr().out)["outcome"] == "TIMED_OUT"
    record = submission(output)
    assert record["process_exit_code"] is None
    assert record["stdout"]["text"] == "partial output"
    assert record["stderr"]["text"] == "timeout diagnostic"
    assert not (output / "scorecard.json").exists()
    before = (output / "submission.json").read_bytes()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("An existing output must refuse before launching another CLI")

    monkeypatch.setitem(run.__globals__, "_capture", forbidden)
    assert run(arguments(kit, "a" * 64, output)) == 3
    refusal = capsys.readouterr()
    assert refusal.out == ""
    assert json.loads(refusal.err)["error"]["code"] == "alpha_submission_io_failure"
    assert (output / "submission.json").read_bytes() == before


def test_output_inside_the_kit_is_rejected_before_process_or_files(tmp_path, monkeypatch):
    kit = tmp_path / "kit"
    kit.mkdir()
    output = kit / "submission"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("A submission cannot mutate its immutable source kit")

    run = load_runner()
    monkeypatch.setitem(run.__globals__, "_capture", forbidden)
    with pytest.raises(SystemExit) as caught:
        run(arguments(kit, "a" * 64, output))
    assert caught.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_actual_child_output_overflow_is_bounded_and_preserved_as_failed_submission(tmp_path, capsys, monkeypatch, stream):
    kit = tmp_path / "kit"
    kit.mkdir()
    run = load_runner()
    namespace = run.__globals__
    limit = namespace["_MAX_RECEIPT" if stream == "stdout" else "_MAX_DIAGNOSTIC"]
    descriptor = 1 if stream == "stdout" else 2
    # The real bounded subprocess layer executes only this short diagnostic
    # child. It produces no financial result and invokes no project use case.
    noisy = f"import os; os.write({descriptor}, b'x' * {limit + 8192})"
    monkeypatch.setitem(namespace, "_ENTRYPOINT", noisy)
    monkeypatch.setitem(namespace, "_TIMEOUT", 10)
    output = tmp_path / (stream + "-overflow")
    assert run(arguments(kit, "a" * 64, output)) == 10
    assert json.loads(capsys.readouterr().out)["outcome"] == "FAILED"
    record = submission(output)
    assert record["stage"] == "process_output_limit"
    assert record["capture"][stream + "_overflow"] is True
    assert record["capture"][stream + "_observed_bytes"] > limit
    assert record["capture"][stream + "_limit_bytes"] == limit
    assert record[stream]["capture_overflow"] is True
    assert record[stream]["truncated"] is True
    assert len(record[stream]["text"].encode()) <= 32 * 1024
    assert record["scorecard_id"] is None
    assert not (output / "scorecard.json").exists()


def test_actual_process_start_error_still_writes_a_failed_submission(tmp_path, capsys, monkeypatch):
    kit = tmp_path / "kit"
    kit.mkdir()
    run = load_runner()
    missing_executable = tmp_path / "python-that-does-not-exist"
    monkeypatch.setattr(sys, "executable", str(missing_executable))
    output = tmp_path / "launch-failure"
    assert run(arguments(kit, "a" * 64, output)) == 10
    assert json.loads(capsys.readouterr().out)["outcome"] == "FAILED"
    record = submission(output)
    assert record["stage"] == "process_start"
    assert record["process_exit_code"] is None
    assert record["process_start_error"]["type"] == "FileNotFoundError"
    assert record["process_start_error"]["errno"] == 2
    assert str(missing_executable) in record["process_start_error"]["message"]
    assert record["command"][0] == str(missing_executable)
    assert record["external_gate_updated"] is False
    assert record["scorecard_id"] is None
    assert not (output / "scorecard.json").exists()
