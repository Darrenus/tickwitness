"""Pure audit-address/filter regressions; never invoke journalctl or a probe."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "diagnose_restricted_reference.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_reference_diagnostic", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)
BOOT = "a" * 32


def entry(**changes):
    value = {
        "_BOOT_ID": BOOT,
        "__MONOTONIC_TIMESTAMP": "1500",
        "__CURSOR": "s=real;i=123;b=" + BOOT,
        "MESSAGE": 'apparmor="DENIED" operation="capable" profile="unprivileged_userns" '
        'pid=9 comm="bwrap" capability=12 capname="net_admin" name="private-secret"',
    }
    value.update(changes)
    return json.dumps(value).encode()


def test_same_boot_microseconds_and_actual_cursor_are_retained_without_raw_message():
    rows, malformed = diagnostic.select_records(entry(), BOOT, 1_000_000, 2_000_000)
    assert malformed == 0 and len(rows) == 1
    assert rows[0]["cursor"].startswith("s=real;") and rows[0]["monotonic_us"] == 1500
    assert rows[0]["audit_fields"]["capname"] == "net_admin"
    assert "private-secret" not in json.dumps(rows) and "MESSAGE" not in rows[0]


def test_different_boot_outside_window_or_unrelated_message_never_matches():
    raw = b"\n".join(
        (
            entry(_BOOT_ID="b" * 32),
            entry(__MONOTONIC_TIMESTAMP="999"),
            entry(MESSAGE="apparmor unrelated-other-process"),
            entry(MESSAGE='comm="bwrap" ordinary progress'),
        )
    )
    assert diagnostic.select_records(raw, BOOT, 1_000_000, 2_000_000) == ([], 0)


def test_missing_or_invalid_address_is_unknown_not_a_fabricated_cursor():
    raw = b"\n".join((b"broken", b"[]", entry(__CURSOR=""), entry(__MONOTONIC_TIMESTAMP=[1500])))
    rows, malformed = diagnostic.select_records(raw, BOOT, 1_000_000, 2_000_000)
    assert rows == [] and malformed == 4


def test_only_selected_missing_evidence_directory_can_be_created(tmp_path, monkeypatch):
    selected = tmp_path / "selected"
    monkeypatch.setattr(diagnostic, "EXPECTED_EVIDENCE", selected)
    unrelated = tmp_path / "unrelated"
    assert diagnostic.evidence_directory(unrelated) is False
    assert not unrelated.exists()
    assert diagnostic.evidence_directory(selected) is True
    assert selected.is_dir()


def test_evidence_directory_never_follows_a_symlink(tmp_path, monkeypatch):
    original = tmp_path / "original"
    original.mkdir()
    selected = tmp_path / "selected"
    selected.symlink_to(original, target_is_directory=True)
    monkeypatch.setattr(diagnostic, "EXPECTED_EVIDENCE", selected)
    assert diagnostic.evidence_directory(selected) is False
    assert original.is_dir()
