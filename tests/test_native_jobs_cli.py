"""Native Job admission freezes intent without pretending submission executed it."""

import json

from tickwitness.cli import main


def test_followup_confirmation_is_denied_before_ids_and_catalog_io(tmp_path, capsys):
    for command, key in (
        ("retry-reduction-job", "--retry-key"),
        ("recover-reduction-job", "--recovery-key"),
    ):
        assert (
            main(
                [
                    command,
                    "invalid",
                    key,
                    "invalid key",
                    "--jobs",
                    str(tmp_path / "missing"),
                    "--split",
                    "confirmation",
                ]
            )
            == 5
        )
        captured = capsys.readouterr()
        assert not captured.out
        assert json.loads(captured.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def submit_args(root, *, split="development", bad=False):
    identity = "invalid" if bad else "a" * 64
    return [
        "submit-reduction-job",
        str(root / "preparation"),
        "--expected-preparation-id",
        identity,
        "--expected-bundle-id",
        identity,
        "--expected-report-id",
        identity,
        "--input-root",
        str(root / "input"),
        "--source-evidence",
        "missing-source",
        "--runs",
        str(root / "runs"),
        "--jobs",
        str(root / "jobs"),
        "--split",
        split,
    ]


def test_native_confirmation_rejected_before_identifiers_or_any_catalog_io(tmp_path, capsys):
    assert main(submit_args(tmp_path, split="confirmation", bad=True)) == 5
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_native_invalid_identity_or_catalog_overlap_cannot_create_a_store(tmp_path, capsys):
    assert main(submit_args(tmp_path, bad=True)) == 2
    assert not capsys.readouterr().out
    args = submit_args(tmp_path)
    args[args.index("--jobs") + 1] = str(tmp_path / "input")
    assert main(args) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"]["code"] == "invalid_job"
    assert list(tmp_path.iterdir()) == []


def test_native_submit_and_catalog_inspection_do_not_claim_research_execution(tmp_path, capsys):
    args = submit_args(tmp_path)
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["state"] == "QUEUED"
    assert first["scope"]["operation"] == "execute_reduction_input_v1"
    assert first["scope"]["research_attempt_reserved"] is None
    assert first["scope"]["native_replayed"] is None
    assert not (tmp_path / "runs").exists() and not (tmp_path / "input").exists()
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert main(["inspect-job", first["job_id"], "--jobs", str(tmp_path / "jobs")]) == 0
    assert json.loads(capsys.readouterr().out) == first
