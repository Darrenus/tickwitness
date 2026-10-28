"""One-time observation access uses real frozen v2 sources and persistent state."""

import json

import pytest

from tickwitness.cli import main


def _request(root, title="Confirm the frozen declaration", max_events=100):
    path = root / "confirmation-request.json"
    path.write_text(
        json.dumps(
            {
                "kind": "confirmation_request_v1",
                "schema_version": 1,
                "title": title,
                "max_events": max_events,
            }
        )
    )
    return path.name


def _common(case):
    return ["--store", str(case.root / "data"), "--registry", str(case.root / "registry")]


def _freeze(case):
    return [
        "freeze-confirmation-protocol",
        case.frozen.protocol_id,
        "confirmation-request.json",
        "--input-root",
        str(case.root),
        *_common(case),
    ]


def test_real_v2_confirmation_open_repeat_and_new_name(experiment_case, capsys):
    case = experiment_case
    _request(case.root)
    assert main(_freeze(case)) == 0
    first = json.loads(capsys.readouterr().out)
    protocol_id = first["protocol_id"]
    assert first["created"] is True
    assert first["exposure_status"] == "NO_MATCHING_EXPOSURE_IN_LEDGER"
    assert "observations" not in first
    assert main(_freeze(case)) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["protocol_id"] == protocol_id
    assert repeated["created"] is False

    opening = ["open-confirmation-protocol", protocol_id, *_common(case)]
    assert main(opening) == 0
    released = json.loads(capsys.readouterr().out)
    assert released["kind"] == "confirmation_observation_release_v1"
    assert released["dataset_id"] == case.confirmation
    assert released["total_records"] == len(released["observations"]) == 1
    assert released["truncated"] is False
    assert released["scope"]["confirmation_finding_issued"] is False
    assert released["scope"]["historical_unseen_certified"] is False

    assert main(opening) == 5
    denied = capsys.readouterr()
    assert denied.out == ""
    error = json.loads(denied.err)["error"]
    assert error["code"] == "confirmation_already_exposed"
    assert error["related_exposure_ids"] == [released["exposure_id"]]
    assert main(["inspect-confirmation-protocol", protocol_id, *_common(case)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["exposure_status"] == "ALREADY_EXPOSED_IN_LEDGER"
    assert inspected["related_exposure_ids"] == [released["exposure_id"]]
    assert "observations" not in inspected

    _request(case.root, title="A new experiment name cannot restore freshness")
    assert main(_freeze(case)) == 0
    renamed = json.loads(capsys.readouterr().out)
    assert renamed["protocol_id"] != protocol_id
    assert renamed["exposure_status"] == "ALREADY_EXPOSED_IN_LEDGER"
    assert main(["open-confirmation-protocol", renamed["protocol_id"], *_common(case)]) == 5
    assert capsys.readouterr().out == ""
    assert not (case.root / "runs").exists()


@pytest.mark.parametrize("failure", ["bad_json", "symlink", "bool_budget", "over_limit"])
def test_invalid_confirmation_request_does_not_initialize_state(experiment_case, capsys, failure):
    case = experiment_case
    name = _request(case.root)
    path = case.root / name
    if failure == "bad_json":
        path.write_text("{broken")
    elif failure == "symlink":
        path.unlink()
        path.symlink_to(case.root / "missing.json")
    elif failure == "bool_budget":
        _request(case.root, max_events=True)
    else:
        _request(case.root, max_events=1001)
    assert main(_freeze(case)) == 2
    assert capsys.readouterr().out == ""
    assert not (case.root / "data" / "confirmation-state").exists()
    assert not (case.root / "data" / ".confirmation-state-initialized").exists()


@pytest.mark.parametrize("command", ["inspect-confirmation-protocol", "open-confirmation-protocol"])
def test_missing_confirmation_does_not_create_storage(tmp_path, capsys, command):
    assert (
        main(
            [
                command,
                "a" * 64,
                "--store",
                str(tmp_path / "data"),
                "--registry",
                str(tmp_path / "registry"),
            ]
        )
        == 4
    )
    failure = capsys.readouterr()
    assert failure.out == ""
    assert json.loads(failure.err)["error"]["code"] == "confirmation_protocol_not_found"
    assert list(tmp_path.iterdir()) == []
