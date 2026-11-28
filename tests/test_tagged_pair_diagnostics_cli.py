"""Keep tagged leaf facts command-scoped without changing semantic authority."""

import builtins
import errno
import json
import os
import shutil
import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_evidence_bundles import artifacts as baseline_artifacts
from test_search_evidence_bundles import artifacts as search_artifacts
from test_tagged_evidence_bundles import artifacts as pair_artifacts
from test_tagged_finding_bundles import artifacts as finding_artifacts
from test_tagged_findings import finding_case as finding_case
from test_tagged_pair_diagnostics import PAIR_ROLES, inventory
from test_tagged_pair_package import golden_payload

from tickwitness import cli_tagged_evidence as pair_cli
from tickwitness import cli_tagged_findings as finding_cli
from tickwitness.application.tagged_pair_evidence import verify_tagged_pair_package
from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical
from tickwitness.infrastructure import evidence_bundles as baseline
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_evidence_bundles import export_search_evidence_bundle
from tickwitness.infrastructure.tagged_evidence_bundles import (
    TaggedPairMissingObjectError,
    export_tagged_pair_bundle,
)
from tickwitness.infrastructure.tagged_finding_bundles import export_tagged_finding_bundle
from tickwitness.infrastructure.tagged_finding_registry import LocalTaggedFindingRegistry
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry


def verify_arguments(root, *, command="verify-tagged-queue-pair", expected=None):
    result = [command, str(root)]
    if expected is not None:
        result.extend(["--expected-bundle-id", expected])
    return result


def guard_reads(monkeypatch, *, authority_root=None, authority_events=None):
    """Install after preparation; issuer alone may read its existing authority."""
    attempts = []
    real_import = builtins.__import__
    real_finding_init = LocalTaggedFindingRegistry.__init__

    def forbidden(*args, **kwargs):
        attempts.append("execution_or_publication")
        raise AssertionError("Offline diagnostics cannot execute, reserve or publish")

    def import_without_native(name, *args, **kwargs):
        if name == "nautilus_trader" or name.startswith("nautilus_trader."):
            attempts.append("native_import")
            raise AssertionError("Offline diagnostics cannot import a native engine")
        return real_import(name, *args, **kwargs)

    def readonly_authority(self, root, *, create=False):
        if authority_root is None:
            forbidden()
        assert Path(root).absolute() == authority_root and create is False
        if authority_events is not None:
            authority_events.append("authority_constructor")
        real_finding_init(self, root, create=False)

    class NoWorker(subprocess.Popen):
        def __new__(cls, *args, **kwargs):
            return forbidden(*args, **kwargs)

    class NoSocket(socket.socket):
        def __new__(cls, *args, **kwargs):
            return forbidden(*args, **kwargs)

    for repository in (
        LocalAttemptLedger,
        LocalExecutableProtocolRegistry,
        LocalDatasetStore,
        LocalTaggedQueueRegistry,
    ):
        monkeypatch.setattr(repository, "__init__", forbidden)
    for owner, method in (
        (LocalAttemptLedger, "reserve"),
        (LocalAttemptLedger, "reserve_with_nonce"),
        (LocalAttemptLedger, "publish"),
        (LocalAttemptLedger, "bind_intent"),
        (LocalExecutableProtocolRegistry, "seal"),
        (LocalDatasetStore, "publish"),
        (LocalTaggedQueueRegistry, "seal"),
        (LocalTaggedFindingRegistry, "seal"),
    ):
        monkeypatch.setattr(owner, method, forbidden)
    monkeypatch.setattr(LocalTaggedFindingRegistry, "__init__", readonly_authority)
    monkeypatch.setattr(pair_cli, "export_tagged_pair_bundle", forbidden)
    monkeypatch.setattr(finding_cli, "export_tagged_finding_bundle", forbidden)
    monkeypatch.setattr(finding_cli, "freeze_finding_protocol", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", NoWorker)
    monkeypatch.setattr(socket, "socket", NoSocket)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socketpair", forbidden)
    monkeypatch.setattr(builtins, "__import__", import_without_native)
    return attempts


def error_output(argv, capsys, exit_code=3):
    assert main(argv) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    envelope = json.loads(captured.err)
    assert set(envelope) == {"error"}
    assert isinstance(envelope["error"]["message"], str) and envelope["error"]["message"]
    return envelope["error"]


def generic(error, code="research_store_integrity_or_io_failure"):
    assert set(error) == {"code", "message"}
    assert error["code"] == code


def missing_context(error, package, sha256):
    roles = sorted(
        name
        for name, reference in package.manifest["roles"].items()
        if reference["sha256"] == sha256
    )
    assert error == {
        "code": "research_store_integrity_or_io_failure",
        "message": error["message"],
        "reason": "tagged_pair_object_missing",
        "role": roles[0],
        "roles": roles,
        "sha256": sha256,
    }


@pytest.fixture
def semantic_pair(tmp_path):
    source = tmp_path / "source"
    package = export_tagged_pair_bundle(source, golden_payload())
    return source, package


@pytest.mark.parametrize("mark", [100, 102])
def test_real_relocated_semantic_receipt_keeps_its_original_bytes(
    tmp_path, capsys, monkeypatch, mark
):
    source = tmp_path / "source"
    package = export_tagged_pair_bundle(source, golden_payload(mark))
    relocated = tmp_path / "relocated"
    shutil.copytree(source, relocated)
    expected = verify_tagged_pair_package(package, expected_bundle_id=package.bundle_id)
    assert expected["assessment"]["comparison"]["truths"] == (
        [False, False] if mark == 100 else [True, False]
    )
    for field in (
        "native_replayed",
        "author_signature_verified",
        "confirmation_reference_checked",
        "full_attempt_ledger_checked",
        "ledger_commitment_checked",
    ):
        assert expected[field] is False
    assert expected["assessment"]["findings"] == []
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    assert main(verify_arguments(relocated, expected=package.bundle_id)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.encode() == canonical(expected) + b"\n"
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize("role", PAIR_ROLES)
def test_each_declared_semantic_role_reports_all_actual_aliases_without_mutation(
    semantic_pair, tmp_path, capsys, monkeypatch, role
):
    source, package = semantic_pair
    copied = tmp_path / "missing-object"
    shutil.copytree(source, copied)
    reference = package.manifest["roles"][role]
    (copied / reference["ref"]).unlink()
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    error = error_output(verify_arguments(copied, expected=package.bundle_id), capsys)
    missing_context(error, package, reference["sha256"])
    assert str(tmp_path) not in error["message"]
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize("case", ["partial-alias", "all-aliases", "multiple-missing"])
def test_opaque_alias_and_multiple_leaf_errors_are_only_file_facts(
    tmp_path, capsys, monkeypatch, case
):
    # These fixtures are intentionally opaque, never semantic success receipts.
    payload = pair_artifacts()
    if case == "partial-alias":
        payload["raw"] = payload["normalized"] = b"shared opaque role content"
    elif case == "all-aliases":
        payload = dict.fromkeys(PAIR_ROLES, b"one opaque object for all roles")
    source = tmp_path / "source"
    package = export_tagged_pair_bundle(source, payload)
    copied = tmp_path / "damaged"
    shutil.copytree(source, copied)
    if case == "multiple-missing":
        missing = {
            package.manifest["roles"][role]["sha256"]
            for role in ("protocol", "raw", "front_receipt")
        }
    else:
        missing = {package.manifest["roles"]["raw"]["sha256"]}
    for sha256 in sorted(missing, reverse=True):
        (copied / "objects" / "sha256" / sha256).unlink()
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    error = error_output(verify_arguments(copied), capsys)
    missing_context(error, package, min(missing))
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize("missing", ["root", "manifest.json", "objects", "objects/sha256"])
def test_missing_root_manifest_and_containers_preserve_their_original_envelopes(
    semantic_pair, tmp_path, capsys, monkeypatch, missing
):
    source, _ = semantic_pair
    copied = tmp_path / "damaged"
    if missing != "root":
        shutil.copytree(source, copied)
        victim = copied / missing
        if victim.is_dir():
            shutil.rmtree(victim)
        else:
            victim.unlink()
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    error = error_output(verify_arguments(copied), capsys, 4 if missing == "root" else 3)
    expected_code = (
        "research_evidence_not_found"
        if missing == "root"
        else "research_store_integrity_or_io_failure"
    )
    generic(error, expected_code)
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize("bad_input", ["noncanonical", "corrupt-object", "rehash-assessment"])
def test_invalid_or_rehashed_semantic_evidence_never_gains_missing_context(
    semantic_pair, tmp_path, capsys, monkeypatch, bad_input
):
    source, package = semantic_pair
    copied = tmp_path / "damaged"
    if bad_input == "rehash-assessment":
        payload = package.artifacts
        payload["assessment"] = b'{"self_attested":true}'
        export_tagged_pair_bundle(copied, payload)
    else:
        shutil.copytree(source, copied)
        if bad_input == "noncanonical":
            manifest = copied / "manifest.json"
            manifest.write_bytes(manifest.read_bytes() + b"\n")
        else:
            victim = copied / package.manifest["roles"]["raw"]["ref"]
            original = victim.read_bytes()
            victim.write_bytes(b"!" + original[1:])
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    semantic_failure = bad_input == "rehash-assessment"
    error = error_output(verify_arguments(copied), capsys, 2 if semantic_failure else 3)
    expected_code = (
        "invalid_research_evidence"
        if semantic_failure
        else "research_store_integrity_or_io_failure"
    )
    generic(error, expected_code)
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_leaf_open_permission_and_io_refusals_cannot_be_classified_from_text(
    semantic_pair, tmp_path, capsys, monkeypatch, error_number
):
    source, package = semantic_pair
    sha256 = package.manifest["roles"]["raw"]["sha256"]
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    real_open = os.open
    observed = []

    def denied(path, flags, *args, **kwargs):
        if path == sha256 and kwargs.get("dir_fd") is not None:
            observed.append(path)
            raise OSError(error_number, "Missing tagged pair evidence object for role(s): raw")
        return real_open(path, flags, *args, **kwargs)

    # Keep the fault outside inventory's own no-follow syscalls.
    with monkeypatch.context() as fault:
        fault.setattr(os, "open", denied)
        error = error_output(verify_arguments(source), capsys)
    generic(error)
    assert observed and inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize("gate", ["confirmation", "malformed-pin"])
def test_early_refusal_precedes_any_pair_read(tmp_path, capsys, monkeypatch, gate):
    def forbidden(*args, **kwargs):
        raise AssertionError("The gate must precede reading or creating a pair")

    monkeypatch.setattr(pair_cli, "read_tagged_pair_bundle", forbidden)
    attempts = guard_reads(monkeypatch)
    arguments = verify_arguments(tmp_path / "absent", expected="invalid")
    if gate == "confirmation":
        arguments.extend(["--split", "confirmation"])
    error = error_output(arguments, capsys, 5 if gate == "confirmation" else 2)
    expected_code = (
        "confirmation_access_denied" if gate == "confirmation" else "invalid_research_evidence"
    )
    generic(error, expected_code)
    assert inventory(tmp_path) == {} and attempts == []


@pytest.mark.parametrize("missing_leaf", [False, True])
def test_well_formed_wrong_pin_is_checked_only_after_the_original_full_read(
    semantic_pair, tmp_path, capsys, monkeypatch, missing_leaf
):
    source, package = semantic_pair
    reference = package.manifest["roles"]["raw"]
    if missing_leaf:
        (source / reference["ref"]).unlink()
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    error = error_output(
        verify_arguments(source, expected="0" * 64), capsys, 3 if missing_leaf else 2
    )
    if missing_leaf:
        missing_context(error, package, reference["sha256"])
    else:
        generic(error, "invalid_research_evidence")
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize(
    ("source_profile", "command"),
    [
        ("baseline", "verify-tagged-queue-pair"),
        ("finding", "verify-tagged-queue-pair"),
        ("search", "verify-tagged-queue-pair"),
        ("pair", "verify-evidence"),
        ("pair", "verify-tagged-findings"),
        ("pair", "verify-search-evidence"),
    ],
)
def test_wrong_profiles_never_acquire_twelve_role_missing_context(
    tmp_path, capsys, monkeypatch, source_profile, command
):
    root = tmp_path / "wrong-profile"
    exporter, payload = {
        "baseline": (baseline.export_bundle, baseline_artifacts),
        "finding": (export_tagged_finding_bundle, finding_artifacts),
        "search": (export_search_evidence_bundle, search_artifacts),
        "pair": (export_tagged_pair_bundle, pair_artifacts),
    }[source_profile]
    package = exporter(root, payload())
    (root / package.manifest["roles"]["raw"]["ref"]).unlink()
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    error = error_output(verify_arguments(root, command=command), capsys)
    generic(error)
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize(
    "case", ["baseline-leaf", "search-leaf", "search-container", "finding-leaf"]
)
def test_other_profile_diagnostics_keep_their_original_classification(
    tmp_path, capsys, monkeypatch, case
):
    root = tmp_path / "other-profile"
    if case == "baseline-leaf":
        package = baseline.export_bundle(root, baseline_artifacts())
        command = "verify-evidence"
    elif case == "finding-leaf":
        package = export_tagged_finding_bundle(root, finding_artifacts())
        command = "verify-tagged-findings"
    else:
        package = export_search_evidence_bundle(root, search_artifacts())
        command = "verify-search-evidence"
    references = package.manifest["roles"]
    if case == "search-container":
        sha256 = min(reference["sha256"] for reference in references.values())
        shutil.rmtree(root / "objects")
    else:
        sha256 = references["raw"]["sha256"]
        (root / references["raw"]["ref"]).unlink()
    roles = sorted(name for name, ref in references.items() if ref["sha256"] == sha256)
    before = inventory(tmp_path)
    attempts = guard_reads(monkeypatch)
    error = error_output(verify_arguments(root, command=command), capsys)
    if case == "finding-leaf":
        generic(error)
    else:
        expected = {
            "code": "research_store_integrity_or_io_failure"
            if case == "baseline-leaf"
            else "search_evidence_object_missing",
            "message": error["message"],
            "role": roles[0],
            "roles": roles,
            "sha256": sha256,
        }
        if case == "baseline-leaf":
            expected["reason"] = "bundle_object_missing"
            assert error["message"] == "Missing baseline evidence object for role(s) raw: " + sha256
        assert error == expected
    assert inventory(tmp_path) == before and attempts == []


@pytest.mark.parametrize(
    "gate",
    [
        "missing-leaf",
        "wrong-pin-and-missing-leaf",
        "wrong-pin",
        "missing-authority-and-leaf",
        "invalid-authority-id",
        "malformed-pin",
        "confirmation",
    ],
)
def test_actual_finding_issuer_keeps_authority_order_and_generic_source_errors(
    finding_case, capsys, monkeypatch, gate
):
    case = finding_case
    source = case.root / "pair"
    if gate in {"missing-leaf", "wrong-pin-and-missing-leaf", "missing-authority-and-leaf"}:
        (source / case.source.manifest["roles"]["raw"]["ref"]).unlink()
    requested = "0" * 64 if gate == "missing-authority-and-leaf" else case.finding_id
    if gate in {"invalid-authority-id", "confirmation"}:
        requested = "invalid"
    expected = (
        "0" * 64 if gate in {"wrong-pin", "wrong-pin-and-missing-leaf"} else case.source.bundle_id
    )
    if gate in {"malformed-pin", "confirmation"}:
        expected = "invalid"
    output = case.root / "must-not-be-published"
    arguments = [
        "issue-tagged-findings",
        requested,
        str(source),
        "--expected-bundle-id",
        expected,
        "--registry",
        str(case.root / "registry"),
        "--output",
        str(output),
    ]
    if gate == "confirmation":
        arguments.extend(["--split", "confirmation"])
    events, typed_failures = [], []
    real_get = LocalTaggedFindingRegistry.get
    real_read_pair = finding_cli.read_tagged_pair_bundle

    def authority_get(registry, protocol_id):
        events.append("authority_get")
        return real_get(registry, protocol_id)

    def source_read(path):
        events.append("source")
        try:
            return real_read_pair(path)
        except TaggedPairMissingObjectError as error:
            typed_failures.append(error)
            raise

    monkeypatch.setattr(LocalTaggedFindingRegistry, "get", authority_get)
    monkeypatch.setattr(finding_cli, "read_tagged_pair_bundle", source_read)
    before = inventory(case.root)
    attempts = guard_reads(
        monkeypatch, authority_root=case.root / "registry", authority_events=events
    )
    code, exit_code, expected_events = {
        "missing-leaf": (
            "research_store_integrity_or_io_failure",
            3,
            ["authority_constructor", "authority_get", "source"],
        ),
        "wrong-pin-and-missing-leaf": (
            "research_store_integrity_or_io_failure",
            3,
            ["authority_constructor", "authority_get", "source"],
        ),
        "wrong-pin": (
            "invalid_research_evidence",
            2,
            ["authority_constructor", "authority_get", "source"],
        ),
        "missing-authority-and-leaf": (
            "research_evidence_not_found",
            4,
            ["authority_constructor", "authority_get"],
        ),
        "invalid-authority-id": ("invalid_research_evidence", 2, []),
        "malformed-pin": ("invalid_research_evidence", 2, []),
        "confirmation": ("confirmation_access_denied", 5, []),
    }[gate]
    error = error_output(arguments, capsys, exit_code)
    generic(error, code)
    assert events == expected_events
    if gate in {"missing-leaf", "wrong-pin-and-missing-leaf"}:
        assert len(typed_failures) == 1
        assert error["message"] == str(typed_failures[0])
    else:
        assert typed_failures == []
    assert not output.exists() and inventory(case.root) == before and attempts == []
