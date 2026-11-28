"""Inspection context preserves real lookup priority and consumed-attempt evidence."""

import builtins
import errno
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import tickwitness.cli_experiments as experiments_cli
import tickwitness.sdk as sdk
from tickwitness.application.experiments import inspect_attempt, inspect_experiment
from tickwitness.cli import main
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.infrastructure.attempt_ledger import AttemptNotFoundError, LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import (
    ExecutableProtocolNotFoundError,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore


def arguments(root: Path, command: str, requested_id: str) -> list[str]:
    result = [command, requested_id]
    if command == "inspect-experiment":
        result.extend(["--registry", str(root / "registry"), "--store", str(root / "data")])
    else:
        result.extend(["--runs", str(root / "runs")])
    return result


def inventory(root: Path) -> dict[str, tuple[int, str]]:
    """Compare persistent evidence; SQLite runtime sidecars and metadata may change."""
    sidecars = {root / "data" / f"catalog.sqlite3-{suffix}" for suffix in ("wal", "shm")}
    result = {}
    for path in root.rglob("*"):
        if path in sidecars:
            continue
        kind = stat.S_IFMT(path.lstat().st_mode)
        if kind == stat.S_IFREG:
            payload = hashlib.sha256(path.read_bytes()).hexdigest()
        elif kind == stat.S_IFLNK:
            payload = os.readlink(path)
        else:
            payload = ""
        result[str(path.relative_to(root))] = kind, payload
    return result


def guard_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Install after fixture preparation; existing read-only SQLite stays allowed."""
    connections = []
    real_connect = sqlite3.connect
    real_import = builtins.__import__

    def forbidden(*args, **kwargs):
        raise AssertionError("Inspection must not execute, publish or allocate research")

    def readonly_connect(database, *args, **kwargs):
        assert kwargs.get("uri") is True
        assert isinstance(database, str) and database.endswith("?mode=ro")
        connections.append(database)
        return real_connect(database, *args, **kwargs)

    def import_without_native(name, *args, **kwargs):
        if name == "nautilus_trader" or name.startswith("nautilus_trader."):
            raise AssertionError("Inspection must not import a native engine")
        return real_import(name, *args, **kwargs)

    for owner, method in (
        (LocalAttemptLedger, "reserve"),
        (LocalAttemptLedger, "reserve_with_nonce"),
        (LocalAttemptLedger, "publish"),
        (LocalAttemptLedger, "bind_intent"),
        (LocalExecutableProtocolRegistry, "seal"),
        (LocalDatasetStore, "publish"),
    ):
        monkeypatch.setattr(owner, method, forbidden)
    monkeypatch.setattr(experiments_cli, "freeze_experiment", forbidden)
    monkeypatch.setattr(experiments_cli, "run_experiment", forbidden)
    monkeypatch.setattr(experiments_cli, "SubprocessReplayAdapter", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socketpair", forbidden)
    monkeypatch.setattr(sqlite3, "connect", readonly_connect)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", readonly_connect)
    monkeypatch.setattr(builtins, "__import__", import_without_native)
    return connections


def failure(argv: list[str], capsys: pytest.CaptureFixture[str], exit_code: int = 4) -> dict:
    assert main(argv) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    envelope = json.loads(captured.err)
    assert set(envelope) == {"error"}
    assert isinstance(envelope["error"]["message"], str) and envelope["error"]["message"]
    return envelope["error"]


def context(
    error: dict,
    *,
    command: str,
    requested_id: str,
    lookup: str,
    code: str = "research_evidence_not_found",
    resource_id: str | None = None,
) -> None:
    expected = {
        "code": code,
        "message": error["message"],
        "reason": "inspection_evidence_not_found",
        "command": command,
        "requested_id": requested_id,
        "lookup": lookup,
    }
    if resource_id is not None:
        expected["resource_id"] = resource_id
    assert error == expected


def remove_dataset(case, dataset_id: str) -> None:
    connection = sqlite3.connect(case.root / "data" / "catalog.sqlite3")
    try:
        removed = connection.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))
        assert removed.rowcount == 1
        connection.commit()
    finally:
        connection.close()


def attempt(case, *, finalized: bool = False):
    protocol = load_executable_protocol(case.registry.get(case.frozen.protocol_id).canonical_bytes)
    ledger = case.ledger_factory()
    reservation = ledger.reserve(protocol)
    outcome = canonical(
        {
            "kind": "replay_attempt_failure_v1",
            "schema_version": 1,
            "attempt": reservation.document,
            "protocol_id": reservation.protocol_id,
            "error": {"code": "native_timeout", "message": "Original synthetic failure"},
        }
    )
    if finalized:
        ledger.publish(reservation, outcome)
    return ledger, reservation, outcome


@pytest.mark.parametrize(
    "lookup",
    [
        "executable_registry",
        "dataset_store",
        "executable_protocol",
        "development",
        "confirmation",
        "attempt_ledger",
        "committed_attempt",
    ],
)
def test_real_absence_has_exact_lookup_and_only_known_resource_identity(
    experiment_case,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    lookup: str,
) -> None:
    case = experiment_case
    requested, command = case.frozen.protocol_id, "inspect-experiment"
    code, resource = "research_evidence_not_found", None
    if lookup == "executable_registry":
        shutil.rmtree(case.root / "registry")
    elif lookup == "dataset_store":
        shutil.rmtree(case.root / "data")
        code = "dataset_not_found"
    elif lookup == "executable_protocol":
        (case.root / "registry" / "protocols" / f"{requested}.json").unlink()
        resource = requested
    elif lookup in {"development", "confirmation"}:
        resource = getattr(case, lookup)
        remove_dataset(case, resource)
        lookup, code = "referenced_dataset", "dataset_not_found"
    else:
        command, requested = "inspect-attempt", "0" * 64
        if lookup == "committed_attempt":
            case.ledger_factory()
            resource = requested
    before = inventory(case.root)
    guard_reads(monkeypatch)

    error = failure(arguments(case.root, command, requested), capsys)

    context(
        error,
        command=command,
        requested_id=requested,
        lookup=lookup,
        code=code,
        resource_id=resource,
    )
    assert inventory(case.root) == before


def test_missing_catalog_uses_store_context_without_a_guessed_dataset(
    experiment_case, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    (case.root / "data" / "catalog.sqlite3").unlink()
    before = inventory(case.root)
    guard_reads(monkeypatch)
    error = failure(arguments(case.root, "inspect-experiment", case.frozen.protocol_id), capsys)
    context(
        error,
        command="inspect-experiment",
        requested_id=case.frozen.protocol_id,
        lookup="dataset_store",
        code="dataset_not_found",
    )
    assert inventory(case.root) == before


@pytest.mark.parametrize(
    "faults", ["registry_and_store", "protocol_and_store", "protocol_and_data"]
)
def test_dual_faults_preserve_eager_constructor_and_get_priority(
    experiment_case,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    faults: str,
) -> None:
    case = experiment_case
    protocol_id = case.frozen.protocol_id
    resource = None
    if faults == "registry_and_store":
        shutil.rmtree(case.root / "registry")
        shutil.rmtree(case.root / "data")
        lookup, code = "executable_registry", "research_evidence_not_found"
    else:
        (case.root / "registry" / "protocols" / f"{protocol_id}.json").unlink()
        if faults == "protocol_and_store":
            shutil.rmtree(case.root / "data")
            lookup, code = "dataset_store", "dataset_not_found"
        else:
            remove_dataset(case, case.development)
            lookup, code = "executable_protocol", "research_evidence_not_found"
            resource = protocol_id
    before = inventory(case.root)
    guard_reads(monkeypatch)
    error = failure(arguments(case.root, "inspect-experiment", protocol_id), capsys)
    context(
        error,
        command="inspect-experiment",
        requested_id=protocol_id,
        lookup=lookup,
        code=code,
        resource_id=resource,
    )
    assert inventory(case.root) == before


@pytest.mark.parametrize("command", ["inspect-experiment", "inspect-attempt"])
@pytest.mark.parametrize("requested", ["../escape", "A" * 64, "a" * 63])
def test_invalid_identity_refuses_before_any_factory_or_io(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    requested: str,
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid identity must fail before constructing a reader")

    for name in ("LocalExecutableProtocolRegistry", "LocalDatasetStore", "LocalAttemptLedger"):
        monkeypatch.setattr(experiments_cli, name, forbidden)
    with pytest.raises(SystemExit) as caught:
        main(arguments(tmp_path, command, requested))
    assert caught.value.code == 2
    assert capsys.readouterr().out == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("state", ["experiment", "reserved_unfinalized", "finalized_failure"])
def test_valid_projections_are_unchanged_without_new_execution_or_publication(
    experiment_case, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    case = experiment_case
    if state == "experiment":
        command, requested = "inspect-experiment", case.frozen.protocol_id
        expected = asdict(inspect_experiment(requested, case.registry, case.data))
    else:
        ledger, reservation, _ = attempt(case, finalized=state == "finalized_failure")
        command, requested = "inspect-attempt", reservation.attempt_id
        expected = inspect_attempt(requested, ledger)
        assert expected["budget_consumed"] is True
        assert expected["state"] == ("finalized" if state == "finalized_failure" else state)
        if state == "reserved_unfinalized":
            assert expected["outcome"] is None
    before = inventory(case.root)
    connections = guard_reads(monkeypatch)

    assert main(arguments(case.root, command, requested)) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    serialized = json.dumps(
        expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    assert captured.out == serialized + "\n"
    assert bool(connections) is (state == "experiment")
    assert inventory(case.root) == before


@pytest.mark.parametrize(
    "target",
    ["registry_root", "dataset_root", "ledger_root", "protocol", "dataset", "reservation"],
)
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_actual_open_errors_keep_generic_routes_without_absence_context(
    experiment_case,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    error_number: int,
) -> None:
    case = experiment_case
    command, requested = "inspect-experiment", case.frozen.protocol_id
    if target in {"ledger_root", "reservation"}:
        _, reservation, _ = attempt(case)
        command, requested = "inspect-attempt", reservation.attempt_id
    victim = {
        "registry_root": case.root / "registry",
        "dataset_root": case.root / "data",
        "ledger_root": case.root / "runs",
        "protocol": f"{case.frozen.protocol_id}.json",
        "dataset": f"{case.development}.json",
        "reservation": requested,
    }[target]
    real_open = os.open
    observed = []

    def blocked(path, flags, *args, **kwargs):
        if path == victim:
            observed.append(path)
            raise OSError(error_number, "not found is human text, not an absence classification")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", blocked)
    before = inventory(case.root)
    guard_reads(monkeypatch)
    error = failure(arguments(case.root, command, requested), capsys, 3)
    code = (
        "store_integrity_or_publication_failure"
        if target in {"dataset_root", "dataset"}
        else "research_store_integrity_or_io_failure"
    )
    assert error["code"] == code and set(error) == {"code", "message"}
    assert observed
    assert inventory(case.root) == before


@pytest.mark.parametrize("target", ["protocol", "dataset", "reservation", "outcome"])
@pytest.mark.parametrize("damage", ["corrupt", "symlink", "fifo", "directory"])
def test_unsafe_and_corrupt_real_evidence_is_not_absence(
    experiment_case,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    damage: str,
) -> None:
    case = experiment_case
    command, requested = "inspect-experiment", case.frozen.protocol_id
    if target in {"reservation", "outcome"}:
        _, reservation, _ = attempt(case, finalized=True)
        command, requested = "inspect-attempt", reservation.attempt_id
    victim = {
        "protocol": case.root / "registry" / "protocols" / f"{case.frozen.protocol_id}.json",
        "dataset": case.root / "data" / "manifests" / f"{case.development}.json",
        "reservation": case.root / "runs" / "objects" / "sha256" / requested,
        "outcome": case.root / "runs" / "outcomes" / f"{requested}.json",
    }[target]
    original = victim.read_bytes()
    if damage == "corrupt":
        victim.write_bytes(b"{}")
    else:
        victim.unlink()
        if damage == "symlink":
            outside = case.root / "outside"
            outside.write_bytes(original)
            victim.symlink_to(outside)
        elif damage == "fifo":
            os.mkfifo(victim)
        else:
            victim.mkdir()
    before = inventory(case.root)
    guard_reads(monkeypatch)
    error = failure(arguments(case.root, command, requested), capsys, 3)
    code = (
        "store_integrity_or_publication_failure"
        if target == "dataset"
        else "research_store_integrity_or_io_failure"
    )
    assert error["code"] == code and set(error) == {"code", "message"}
    assert inventory(case.root) == before


@pytest.mark.parametrize(
    "missing",
    [
        "registry/protocols",
        "data/manifests",
        "data/objects/sha256",
        "runs/objects/sha256",
        "runs/slots",
        "runs/outcomes",
    ],
)
def test_required_structural_directories_keep_their_non_not_found_route(
    experiment_case,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    case = experiment_case
    command, requested = "inspect-experiment", case.frozen.protocol_id
    if missing.startswith("runs/"):
        _, reservation, _ = attempt(case)
        command, requested = "inspect-attempt", reservation.attempt_id
    shutil.rmtree(case.root / missing)
    before = inventory(case.root)
    guard_reads(monkeypatch)
    error = failure(arguments(case.root, command, requested), capsys, 3)
    code = (
        "store_integrity_or_publication_failure"
        if missing.startswith("data/")
        else "research_store_integrity_or_io_failure"
    )
    assert error["code"] == code and set(error) == {"code", "message"}
    assert inventory(case.root) == before


@pytest.mark.parametrize(
    "missing", ["cas_orphan", "slot_namespace", "reservation_cas", "outcome_pointer", "outcome_cas"]
)
def test_committed_closure_and_unknown_outcome_keep_existing_accounting(
    experiment_case,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    case = experiment_case
    _, reservation, outcome = attempt(case, finalized=missing.startswith("outcome_"))
    root = case.root / "runs"
    slot_directory = root / "slots" / reservation.protocol_id
    if missing == "cas_orphan":
        (slot_directory / f"{reservation.attempt_index:04}.json").unlink()
    elif missing == "slot_namespace":
        shutil.rmtree(slot_directory)
    elif missing == "reservation_cas":
        (root / "objects" / "sha256" / reservation.attempt_id).unlink()
    elif missing == "outcome_pointer":
        (root / "outcomes" / f"{reservation.attempt_id}.json").unlink()
    else:
        (root / "objects" / "sha256" / digest(outcome)).unlink()
    before = inventory(case.root)
    guard_reads(monkeypatch)
    argv = arguments(case.root, "inspect-attempt", reservation.attempt_id)
    if missing == "outcome_pointer":
        assert main(argv) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "attempt_id": reservation.attempt_id,
            "reservation": reservation.document,
            "budget_consumed": True,
            "state": "reserved_unfinalized",
            "outcome": None,
        }
    elif missing == "outcome_cas":
        error = failure(argv, capsys, 3)
        assert error["code"] == "research_store_integrity_or_io_failure"
        assert set(error) == {"code", "message"}
    else:
        error = failure(argv, capsys)
        context(
            error,
            command="inspect-attempt",
            requested_id=reservation.attempt_id,
            lookup="committed_attempt",
            resource_id=reservation.attempt_id,
        )
    assert inventory(case.root) == before


@pytest.mark.parametrize("mismatch", ["protocol_identity", "dataset_identity", "protocol_policy"])
def test_identity_and_valid_hash_policy_refusals_do_not_gain_absence_context(
    experiment_case,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    case = experiment_case
    requested, exit_code, code = case.frozen.protocol_id, 2, "invalid_protocol"
    if mismatch == "protocol_identity":
        real_get = LocalExecutableProtocolRegistry.get

        def wrong_protocol(self, protocol_id):
            record = real_get(self, protocol_id)
            return SimpleNamespace(
                protocol_id="f" * 64,
                canonical_bytes=record.canonical_bytes,
                created=record.created,
            )

        monkeypatch.setattr(LocalExecutableProtocolRegistry, "get", wrong_protocol)
    elif mismatch == "dataset_identity":
        real_get = LocalDatasetStore.get

        def wrong_dataset(self, dataset_id):
            return replace(real_get(self, dataset_id), dataset_id="f" * 64)

        monkeypatch.setattr(LocalDatasetStore, "get", wrong_dataset)
    else:
        document = case.frozen.document
        document["read_policy"] = "confirmation_open"
        raw = canonical(document)
        requested = digest(raw)
        (case.root / "registry" / "protocols" / f"{requested}.json").write_bytes(raw)
        exit_code, code = 3, "research_store_integrity_or_io_failure"
    before = inventory(case.root)
    guard_reads(monkeypatch)
    error = failure(arguments(case.root, "inspect-experiment", requested), capsys, exit_code)
    assert error["code"] == code and set(error) == {"code", "message"}
    assert inventory(case.root) == before


@pytest.mark.parametrize("command", ["inspect-experiment", "inspect-attempt"])
def test_adapter_context_keeps_original_exception_cause_and_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    guard_reads(monkeypatch)
    values = SimpleNamespace(
        command=command,
        protocol_id="0" * 64,
        attempt_id="0" * 64,
        registry=tmp_path / "registry",
        store=tmp_path / "data",
        runs=tmp_path / "runs",
    )
    with pytest.raises(experiments_cli.InspectionNotFoundError) as caught:
        experiments_cli.execute(values)
    expected = (
        ExecutableProtocolNotFoundError if command == "inspect-experiment" else AttemptNotFoundError
    )
    assert isinstance(caught.value.__cause__, expected)
    assert str(caught.value) == str(caught.value.__cause__)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("command", ["inspect-run", "verify-evidence"])
def test_other_research_cli_routes_keep_the_previous_error_envelope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    guard_reads(monkeypatch)
    if command == "verify-evidence":
        argv = [command, str(tmp_path / "bundle")]
    else:
        argv = [
            command,
            "0" * 64,
            "--runs",
            str(tmp_path / "runs"),
            "--registry",
            str(tmp_path / "registry"),
            "--store",
            str(tmp_path / "data"),
        ]
    error = failure(argv, capsys)
    assert error["code"] == "research_evidence_not_found"
    assert set(error) == {"code", "message"}
    assert list(tmp_path.iterdir()) == []


def test_sdk_error_and_surface_do_not_acquire_executable_inspection_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard_reads(monkeypatch)
    client = sdk.Client(store=tmp_path / "data", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        client.inspect_dataset("0" * 64)
    assert (caught.value.code, caught.value.exit_code) == ("dataset_not_found", 4)
    assert set(caught.value.as_dict()["error"]) == {"code", "message"}
    assert not hasattr(caught.value, "lookup")
    assert not hasattr(client, "inspect_experiment") and not hasattr(client, "inspect_attempt")
    assert sdk.SDK_CONTRACT_VERSION == 1 and len(sdk.__all__) == 7
    assert list(tmp_path.iterdir()) == []
