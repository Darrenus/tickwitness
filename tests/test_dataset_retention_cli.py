"""Installed-style CLI boundaries without another native run or research slot."""

import json
import os

import pytest

from tickwitness import cli_retention
from tickwitness.application.dataset_retention import apply_dataset_retention
from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def store_fixture(tmp_path):
    root = tmp_path / "data"
    store = LocalDatasetStore(root)
    published = store.publish(b"retained raw", b"retained normalized", {"valid": True})
    contents = b"declared interrupted publication before manifest"
    key = digest(contents)
    (root / "objects" / "sha256" / key).write_bytes(contents)
    return store, published, key, contents


def preview_file(tmp_path, capsys, root):
    assert main(["plan-dataset-retention", "--store", str(root), "--min-age-seconds", "0"]) == 0
    output = capsys.readouterr()
    assert not output.err
    envelope = json.loads(output.out)
    path = tmp_path / "saved-preview"
    path.write_bytes(output.out.encode())
    return path, envelope


@pytest.mark.parametrize("command", ["plan-dataset-retention", "apply-dataset-retention"])
def test_confirmation_denied_before_file_identity_and_store_io(
    tmp_path, capsys, monkeypatch, command
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Confirmation must not inspect a plan or store")

    monkeypatch.setattr(cli_retention, "LocalDatasetMaintenance", forbidden)
    monkeypatch.setattr(cli_retention, "read_regular_file", forbidden)
    arguments = [command, "--store", str(tmp_path / "absent"), "--split", "confirmation"]
    if command == "apply-dataset-retention":
        arguments += ["--plan", str(tmp_path / "never-read"), "--expected-plan-id", "invalid"]
    assert main(arguments) == 5
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"]["code"] == "confirmation_access_denied"
    assert list(tmp_path.iterdir()) == []


def test_absent_store_is_blocked_without_creation(tmp_path, capsys):
    root = tmp_path / "missing"
    assert main(["plan-dataset-retention", "--store", str(root)]) == 0
    output = capsys.readouterr()
    assert not output.err
    envelope = json.loads(output.out)
    assert envelope["plan"]["status"] == "BLOCKED"
    assert envelope["plan"]["candidates"] == []
    assert not envelope["execution_authorized"]
    assert not root.exists()


def test_preview_is_read_only_then_apply_exactly_unlinks_and_repeat_has_no_credit(tmp_path, capsys):
    store, published, orphan, contents = store_fixture(tmp_path)
    before = tree(store._root)
    path, envelope = preview_file(tmp_path, capsys, store._root)
    assert tree(store._root) == before
    assert envelope["plan"]["candidates"] == [orphan]
    assert not envelope["execution_authorized"]
    command = [
        "apply-dataset-retention",
        "--store",
        str(store._root),
        "--plan",
        str(path),
        "--expected-plan-id",
        envelope["plan_id"],
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "APPLIED" and first["unlinked"] == [orphan]
    assert first["already_absent"] == [] and first["removed_logical_bytes"] == len(contents)
    after = tree(store._root)
    assert after == {
        name: data for name, data in before.items() if name != f"objects/sha256/{orphan}"
    }
    assert main(command) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["status"] == "APPLIED" and repeated["unlinked"] == []
    assert repeated["already_absent"] == [orphan] and repeated["removed_logical_bytes"] == 0
    assert tree(store._root) == after
    assert store.get(published.dataset_id).manifest == published.manifest


def test_retained_payloads_are_not_opened_by_planning_or_apply(tmp_path, capsys, monkeypatch):
    store, published, orphan, _ = store_fixture(tmp_path)
    protected = {row["sha256"] for row in published.manifest["objects"].values()}
    actual_open = os.open
    touched = []

    def guarded_open(path, *args, **kwargs):
        name = os.fsdecode(path).rsplit("/", 1)[-1]
        if name in protected:
            touched.append(name)
            raise AssertionError("Maintenance must not open retained raw/normalized/report payload")
        return actual_open(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(os, "open", guarded_open)
        if actual_open in os.supports_dir_fd:
            context.setattr(os, "supports_dir_fd", os.supports_dir_fd | {guarded_open})
        path, envelope = preview_file(tmp_path, capsys, store._root)
        assert (
            main(
                [
                    "apply-dataset-retention",
                    "--store",
                    str(store._root),
                    "--plan",
                    str(path),
                    "--expected-plan-id",
                    envelope["plan_id"],
                ]
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["unlinked"] == [orphan]
    assert touched == []
    assert store.get(published.dataset_id).report == {"valid": True}


def test_expected_identity_mismatch_and_blocked_plans_never_construct_apply_repository(
    tmp_path, capsys, monkeypatch
):
    store, _, _, _ = store_fixture(tmp_path)
    _, envelope = preview_file(tmp_path, capsys, store._root)

    def forbidden():
        raise AssertionError("Refused plan cannot open the apply repository")

    mismatch = apply_dataset_retention(lambda: canonical(envelope), "f" * 64, forbidden)
    assert mismatch["status"] == "REFUSED" and mismatch["diagnostic"] == "plan_mismatch"
    assert main(["plan-dataset-retention", "--store", str(tmp_path / "missing")]) == 0
    blocked = json.loads(capsys.readouterr().out)
    result = apply_dataset_retention(lambda: canonical(blocked), blocked["plan_id"], forbidden)
    assert result["status"] == "REFUSED" and result["diagnostic"] == "blocked_plan"
    monkeypatch.setattr(cli_retention, "LocalDatasetMaintenance", forbidden)
    saved = tmp_path / "blocked.json"
    saved.write_bytes(canonical(blocked) + b"\n")
    assert (
        main(
            [
                "apply-dataset-retention",
                "--store",
                str(tmp_path / "missing"),
                "--plan",
                str(saved),
                "--expected-plan-id",
                blocked["plan_id"],
            ]
        )
        == 9
    )
    output = capsys.readouterr()
    assert not output.err and json.loads(output.out)["status"] == "REFUSED"


@pytest.mark.parametrize("mutation", ["pretty", "extra", "wrong_plan_id", "extra_newline"])
def test_malformed_preview_is_rejected_before_store_access(tmp_path, capsys, monkeypatch, mutation):
    store, _, _, _ = store_fixture(tmp_path)
    saved, envelope = preview_file(tmp_path, capsys, store._root)
    if mutation == "pretty":
        raw = json.dumps(envelope, indent=2).encode()
    elif mutation == "extra":
        raw = canonical({**envelope, "authority": "delete everything"})
    elif mutation == "wrong_plan_id":
        raw = canonical({**envelope, "plan_id": "f" * 64})
    else:
        raw = canonical(envelope) + b"\n\n"
    saved.write_bytes(raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid preview cannot construct a maintenance repository")

    monkeypatch.setattr(cli_retention, "LocalDatasetMaintenance", forbidden)
    before = tree(store._root)
    assert (
        main(
            [
                "apply-dataset-retention",
                "--store",
                str(store._root),
                "--plan",
                str(saved),
                "--expected-plan-id",
                envelope["plan_id"],
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]["code"] == "invalid_research_evidence"
    assert tree(store._root) == before


def test_drift_is_visible_non_success_and_deletes_nothing(tmp_path, capsys):
    store, _, orphan, _ = store_fixture(tmp_path)
    saved, envelope = preview_file(tmp_path, capsys, store._root)
    new_contents = b"appeared after the frozen preview"
    (store._root / "objects" / "sha256" / digest(new_contents)).write_bytes(new_contents)
    before = tree(store._root)
    assert (
        main(
            [
                "apply-dataset-retention",
                "--store",
                str(store._root),
                "--plan",
                str(saved),
                "--expected-plan-id",
                envelope["plan_id"],
            ]
        )
        == 9
    )
    output = capsys.readouterr()
    assert not output.err
    result = json.loads(output.out)
    assert result["status"] == "REFUSED" and result["diagnostic"] == "snapshot_changed"
    assert result["unlinked"] == [] and result["removed_logical_bytes"] == 0
    assert (store._root / "objects" / "sha256" / orphan).exists()
    assert tree(store._root) == before
