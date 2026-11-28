"""Bounded installed reads of copies of an already verified tagged-pair bundle."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

_ROLES = {
    "protocol",
    "dataset_manifest",
    "raw",
    "normalized",
    "report",
    "front_result",
    "front_evaluation",
    "front_receipt",
    "back_result",
    "back_evaluation",
    "back_receipt",
    "assessment",
}
_GUARD = """
import importlib.abc
import socket
import sqlite3
import subprocess
import sys
attempted = []
def forbidden(*args, **kwargs):
    attempted.append('repository/publication/reservation/sqlite/network/worker')
    raise AssertionError('Tagged-pair diagnostic verification must remain offline and read-only')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('nautilus_trader', 'tickwitness.infrastructure._nautilus_native',
                                'tickwitness.infrastructure._queue_native',
                                'tickwitness.infrastructure._tagged_queue_native')):
            attempted.append('native:' + fullname)
            raise AssertionError('Tagged-pair diagnostic verification cannot import native')
class NoWorker(subprocess.Popen):
    def __new__(cls, *args, **kwargs):
        return forbidden(*args, **kwargs)
class NoSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        return forbidden(*args, **kwargs)
sys.meta_path.insert(0, NoNative())
sqlite3.connect = forbidden
sqlite3.dbapi2.connect = forbidden
subprocess.Popen = NoWorker
socket.socket = NoSocket
socket.create_connection = forbidden
socket.socketpair = forbidden
try:
    from tickwitness.infrastructure import evidence_bundles, tagged_evidence_bundles
    from tickwitness.infrastructure import tagged_finding_bundles
    from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
    from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
    from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
    from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
    from tickwitness.infrastructure.local_confirmation import (
        LocalConfirmationRegistry, LocalConfirmationExposureLedger,
    )
    from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
    from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry
    from tickwitness.infrastructure.nautilus_replay import NautilusReplayAdapter
    from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore
    from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
    from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
    from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
    from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore
    from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
    from tickwitness.infrastructure.tagged_finding_registry import LocalTaggedFindingRegistry
    from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry
    for repository in (
        LocalAttemptLedger, LocalCampaignBudgetStore, LocalExecutableProtocolRegistry,
        LocalConfirmationRegistry, LocalConfirmationExposureLedger, LocalDatasetStore,
        LocalProtocolRegistry, LocalReductionCampaignStore, LocalSearchCampaignStore,
        LocalSearchFindingRegistry, LocalSearchPlanRegistry, SqliteJobStore,
        LocalTaggedFindingRegistry, LocalTaggedQueueRegistry,
    ):
        repository.__init__ = forbidden
    for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
        setattr(LocalAttemptLedger, name, forbidden)
    for adapter in (BoundedReplayAdapter, NautilusReplayAdapter, SubprocessReplayAdapter):
        adapter.__init__ = forbidden
        adapter.run = forbidden
    evidence_bundles.export_bundle = forbidden
    tagged_evidence_bundles.export_tagged_pair_bundle = forbidden
    tagged_finding_bundles.export_tagged_finding_bundle = forbidden
    from tickwitness.cli import main
    status = main(sys.argv[1:])
finally:
    assert not attempted, attempted
raise SystemExit(status)
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _inventory(root: Path) -> dict:
    """Record all names/types and regular bytes; never follow or read a special file."""
    entries, errors = {}, []

    def failed(name, operation, error):
        errors.append(
            {
                "path": name,
                "operation": operation,
                "errno": error.errno,
                "message": str(error)[:1024],
            }
        )

    def visit(path, parent=None):
        name, target = str(path.relative_to(root)), path if parent is None else path.name
        try:
            info = os.stat(target, dir_fd=parent, follow_symlinks=False)
        except OSError as error:
            failed(name, "lstat", error)
            return
        entry = {"type": stat.S_IFMT(info.st_mode)}
        entries[name] = entry
        descriptor = None
        try:
            if stat.S_ISDIR(info.st_mode):
                descriptor = os.open(
                    target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                with os.scandir(descriptor) as children:
                    names = sorted(child.name for child in children)
                for child in names:
                    visit(path / child, descriptor)
            elif stat.S_ISREG(info.st_mode):
                descriptor = os.open(
                    target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                )
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                    info.st_dev,
                    info.st_ino,
                ):
                    errors.append({"path": name, "operation": "opened_identity_or_type"})
                    return
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    data = stream.read()
                entry.update(size=info.st_size, sha256=_sha(data))
                if len(data) != info.st_size:
                    errors.append({"path": name, "operation": "changed_size"})
        except OSError as error:
            failed(name, "enumerate_or_read", error)
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as error:
                    failed(name, "close", error)

    visit(root)
    return {"entries": entries, "errors": errors}


def _difference(before: dict, after: dict) -> dict:
    initial, final = before["entries"], after["entries"]
    full = {
        "before_keys": sorted(initial),
        "after_keys": sorted(final),
        "added": [
            {"path": name, "value": final[name]} for name in sorted(final.keys() - initial.keys())
        ],
        "removed": [
            {"path": name, "value": initial[name]} for name in sorted(initial.keys() - final.keys())
        ],
        "changed": [
            {"path": name, "before": initial[name], "after": final[name]}
            for name in sorted(initial.keys() & final.keys())
            if initial[name] != final[name]
        ],
        "before_errors": before["errors"],
        "after_errors": after["errors"],
    }
    summary = {
        "unchanged": initial == final and not before["errors"] and not after["errors"],
        "full_difference_sha256": _sha(_canonical(full)),
        "details_complete": all(len(items) <= 32 for items in full.values()),
    }
    for name, items in full.items():
        summary[name] = items[:32]
        summary[name + "_count"] = len(items)
    return summary


def _stream(value: bytes) -> dict:
    return {
        "bytes": len(value),
        "sha256": _sha(value),
        "prefix": value[:4096].decode("utf-8", errors="replace"),
        "prefix_truncated": len(value) > 4096,
    }


def tagged_pair_diagnostics(
    interpreter: str, source: Path, expected_receipt: dict, directory: Path
) -> dict:
    """Reuse the loop's semantic success once; new cases only mutate disposable copies."""
    deadline = time.monotonic() + 90
    original = _inventory(source)
    if original["errors"]:
        raise RuntimeError(
            "Cannot inventory tagged source: " + json.dumps(original, sort_keys=True)
        )
    manifest_bytes = (source / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    roles = manifest["roles"]
    assert set(roles) == _ROLES and expected_receipt["bundle_id"] == _sha(manifest_bytes)
    aliases = {}
    for role, reference in roles.items():
        digest = reference["sha256"]
        assert len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)
        assert reference["ref"] == f"objects/sha256/{digest}"
        aliases.setdefault(digest, []).append(role)
    assert 2 <= len(aliases) <= 12
    expected_stdout = _canonical(expected_receipt) + b"\n"
    directory.mkdir()
    observations = []

    def copied(name):
        case = directory / name
        case.mkdir()
        shutil.copytree(source, case / "bundle")
        return case

    def verify(case, *, expected=3, missing=None, valid=False):
        assert len(observations) < 24
        before, source_before = _inventory(case), _inventory(source)
        remaining = deadline - time.monotonic()
        stdout, stderr = b"", b""
        child = {"state": "not_started", "returncode": None, "expected_returncode": expected}
        command = ["verify-tagged-queue-pair", str(case / "bundle")]
        if valid:
            command.extend(("--expected-bundle-id", expected_receipt["bundle_id"]))
        try:
            if (
                remaining > 0
                and not before["errors"]
                and _difference(original, source_before)["unchanged"]
            ):
                completed = subprocess.run(
                    [interpreter, "-I", "-c", _GUARD, *command],
                    cwd=case,
                    capture_output=True,
                    check=False,
                    timeout=min(15, remaining),
                )
                stdout, stderr = completed.stdout, completed.stderr
                child.update(state="completed", returncode=completed.returncode)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            child.update(state="timeout", timeout_seconds=error.timeout)
        except OSError as error:
            child.update(state="os_error", errno=error.errno, message=str(error)[:1024])
        finally:
            after, source_after = _inventory(case), _inventory(source)
        copy_diff = _difference(before, after)
        source_before_diff, source_after_diff = (
            _difference(original, source_before),
            _difference(original, source_after),
        )
        source_unchanged = source_before_diff["unchanged"] and source_after_diff["unchanged"]
        failures, payload = [], None
        if child["state"] != "completed" or child["returncode"] != expected:
            failures.append("child_did_not_complete_with_expected_exit")
        if not copy_diff["unchanged"] or not source_unchanged:
            failures.append("source_or_copy_inventory_changed_or_unreadable")
        unexpected_stream = stderr if expected == 0 else stdout
        if unexpected_stream:
            failures.append("unexpected_output_stream")
        if child["state"] == "completed":
            try:
                payload = json.loads(stdout if expected == 0 else stderr)
            except ValueError as error:
                failures.append({"json_error": type(error).__name__, "message": str(error)[:512]})
        if valid:
            if stdout != expected_stdout or payload != expected_receipt:
                failures.append("semantic_success_receipt_bytes_differed")
        else:
            error = payload.get("error") if isinstance(payload, dict) else None
            keys = (
                {"code", "message", "reason", "role", "roles", "sha256"}
                if missing
                else {"code", "message"}
            )
            code = (
                "research_evidence_not_found"
                if expected == 4
                else "research_store_integrity_or_io_failure"
            )
            if not (
                isinstance(payload, dict)
                and set(payload) == {"error"}
                and isinstance(error, dict)
                and set(error) == keys
                and error["code"] == code
                and isinstance(error["message"], str)
                and error["message"]
            ):
                failures.append("refusal_envelope_differed")
            elif missing is not None:
                digest, names = missing
                if not (
                    error["reason"] == "tagged_pair_object_missing"
                    and error["roles"] == sorted(names)
                    and error["role"] == sorted(names)[0]
                    and error["sha256"] == digest
                    and str(source) not in error["message"]
                    and str(case) not in error["message"]
                ):
                    failures.append("declared_leaf_identity_or_aliases_differed")
        if failures:
            raise RuntimeError(
                "Installed tagged-pair diagnostic failure: "
                + json.dumps(
                    {
                        "case": case.name,
                        "call_index": len(observations) + 1,
                        "child": child,
                        "failures": failures,
                        "copy": copy_diff,
                        "source_before": source_before_diff,
                        "source_after": source_after_diff,
                        "stdout": _stream(stdout),
                        "stderr": _stream(stderr),
                    },
                    sort_keys=True,
                )
            )
        observation = {
            "kind": "installed_tagged_pair_diagnostic_observation_v1",
            "case": case.name,
            "call_index": len(observations) + 1,
            "child": child,
            "source_unchanged": source_unchanged,
            "copy_unchanged": copy_diff["unchanged"],
            "stdout_bytes": len(stdout),
            "stdout_sha256": _sha(stdout),
            "stderr_bytes": len(stderr),
            "stderr_sha256": _sha(stderr),
            "error": None if valid else payload["error"],
        }
        observations.append(observation)
        print(json.dumps(observation, sort_keys=True))

    verify(copied("valid-golden"), expected=0, valid=True)
    for index, (digest, names) in enumerate(sorted(aliases.items())):
        case = copied(f"missing-unique-{index:02d}")
        (case / "bundle" / "objects" / "sha256" / digest).unlink()
        verify(case, missing=(digest, names))

    aliased = copied("all-twelve-aliases-opaque-absence")
    alias_manifest = json.loads(manifest_bytes)
    reference = min(roles.values(), key=lambda value: (value["size_bytes"], value["sha256"]))
    alias_manifest["roles"] = {role: dict(reference) for role in sorted(roles)}
    (aliased / "bundle" / "manifest.json").write_bytes(_canonical(alias_manifest))
    for digest in aliases:
        (aliased / "bundle" / "objects" / "sha256" / digest).unlink()
    verify(aliased, missing=(reference["sha256"], sorted(roles)))

    multiple = copied("multiple-missing")
    first, second = sorted(aliases)[:2]
    for digest in (second, first):
        (multiple / "bundle" / "objects" / "sha256" / digest).unlink()
    verify(multiple, missing=(first, aliases[first]))

    missing_root = copied("missing-root")
    shutil.rmtree(missing_root / "bundle")
    verify(missing_root, expected=4)
    missing_manifest = copied("missing-manifest")
    (missing_manifest / "bundle" / "manifest.json").unlink()
    verify(missing_manifest)
    for name, relative in (("missing-objects", "objects"), ("missing-sha256", "objects/sha256")):
        case = copied(name)
        shutil.rmtree(case / "bundle" / relative)
        verify(case)
    corrupt = copied("corrupt-object")
    leaf = corrupt / "bundle" / "objects" / "sha256" / first
    data = leaf.read_bytes()
    leaf.write_bytes(bytes((data[0] ^ 1,)) + data[1:])
    verify(corrupt)
    nonregular = copied("fifo-object")
    leaf = nonregular / "bundle" / "objects" / "sha256" / first
    leaf.unlink()
    os.mkfifo(leaf)
    verify(nonregular)
    extra = copied("extra-object")
    (extra / "bundle" / "objects" / "sha256" / ".unexpected").write_bytes(b"extra")
    verify(extra)
    wrong = copied("wrong-profile-marker")
    wrong_manifest = json.loads(manifest_bytes)
    wrong_manifest["kind"] = "tagged_queue_finding_evidence_bundle_v1"
    (wrong / "bundle" / "manifest.json").write_bytes(_canonical(wrong_manifest))
    verify(wrong)
    structural = copied("missing-object-and-unsafe-extra")
    (structural / "bundle" / "objects" / "sha256" / first).unlink()
    os.mkfifo(structural / "bundle" / "objects" / "sha256" / ".unsafe-extra")
    verify(structural)

    assert len(observations) == len(aliases) + 12 <= 24 and time.monotonic() <= deadline
    assert _difference(original, _inventory(source))["unchanged"]
    print(f"Installed tagged pair diagnostics: {len(observations)} bounded verify calls passed.")
    return {
        "kind": "installed_tagged_pair_diagnostic_matrix_v1",
        "call_count": len(observations),
        "unique_source_objects": len(aliases),
        "max_calls": 24,
        "shared_seconds": 90,
        "per_child_seconds": 15,
        "source_bundle_id": expected_receipt["bundle_id"],
        "semantic_receipt_stdout_sha256": _sha(expected_stdout),
        "fresh_native_runs": False,
        "new_research_execution": False,
        "observations": observations,
    }
