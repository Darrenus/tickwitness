"""Finding CLI gate order and explicit valid-but-ineligible exit9 semantics."""

import json

import pytest

from tickwitness.cli import main
from tickwitness.domain.evidence.tagged_finding_report import TaggedFindingIneligibleError


@pytest.mark.parametrize(
    "command",
    [
        "freeze-tagged-finding-protocol",
        "inspect-tagged-finding-protocol",
        "issue-tagged-findings",
        "verify-tagged-findings",
    ],
)
def test_confirmation_precedes_id_file_and_registry_access(command, tmp_path, capsys):
    root = tmp_path / "absent"
    if command.startswith("freeze"):
        args = [
            command,
            "bad",
            "missing.json",
            "--input-root",
            str(root),
            "--registry",
            str(root / "registry"),
        ]
    elif command.startswith("inspect"):
        args = [command, "bad", "--registry", str(root / "registry")]
    elif command.startswith("issue"):
        args = [
            command,
            "bad",
            str(root / "pair"),
            "--registry",
            str(root / "registry"),
            "--output",
            str(root / "report"),
            "--expected-bundle-id",
            "bad",
        ]
    else:
        args = [command, str(root / "report"), "--expected-bundle-id", "bad"]
    assert main([*args, "--split", "confirmation"]) == 5
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "confirmation_access_denied"
    assert not root.exists()


def test_ineligible_is_not_invalid_data_or_false_finding(tmp_path, monkeypatch, capsys):
    import tickwitness.cli as cli

    def refuse(arguments):
        raise TaggedFindingIneligibleError("execution_environment_mismatch", "a" * 64)

    monkeypatch.setattr(cli, "execute_tagged_finding_command", refuse)
    result = main(
        [
            "issue-tagged-findings",
            "b" * 64,
            str(tmp_path / "pair"),
            "--registry",
            str(tmp_path / "registry"),
            "--output",
            str(tmp_path / "report"),
            "--expected-bundle-id",
            "a" * 64,
        ]
    )
    assert result == 9
    response = json.loads(capsys.readouterr().err)["error"]
    assert response["code"] == "tagged_finding_ineligible"
    assert response["reason"] == "execution_environment_mismatch"
    assert response["finding_issued"] is False
    assert not (tmp_path / "report").exists()


def test_issuer_requires_explicit_source_identity(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(
            [
                "issue-tagged-findings",
                "a" * 64,
                str(tmp_path),
                "--registry",
                str(tmp_path),
                "--output",
                str(tmp_path / "out"),
            ]
        )
    assert error.value.code == 2
