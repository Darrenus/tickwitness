#!/usr/bin/env python3
"""Exercise versioned experiments with an installed wheel, never source-path imports."""

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from smoke_inspection_diagnostics import inspection_diagnostics

_OFFLINE_GUARD = """
import importlib.abc
import socket
import sqlite3
import subprocess
import sys

attempted = []
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            attempted.append('native:' + fullname)
            raise AssertionError('Offline baseline verification cannot import native')

def forbidden(*args, **kwargs):
    attempted.append('database/network/worker')
    raise AssertionError('Offline baseline verification cannot use database, network or worker')

class NoWorker(subprocess.Popen):
    def __new__(cls, *args, **kwargs):
        return forbidden(*args, **kwargs)

class NoSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        return forbidden(*args, **kwargs)

sys.meta_path.insert(0, NoNative())
sqlite3.connect = forbidden
sqlite3.dbapi2.connect = forbidden
socket.socket = NoSocket
socket.create_connection = forbidden
socket.socketpair = forbidden
subprocess.Popen = NoWorker
try:
    from tickwitness.cli import main
    status = main(sys.argv[1:])
finally:
    assert not attempted, attempted
raise SystemExit(status)
"""


def _inventory(root: Path) -> dict[str, tuple[object, ...]]:
    """Compare fixture names, bytes and stable metadata, deliberately excluding atime."""
    result: dict[str, tuple[object, ...]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        content: str | None
        if stat.S_ISREG(info.st_mode):
            content = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            assert stat.S_ISDIR(info.st_mode), "Offline fixtures require regular files/directories"
            content = None
        result[str(path.relative_to(root))] = (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_uid,
            info.st_gid,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
            content,
        )
    return result


def _offline_diagnostics(interpreter: str, sample: Path, directory: Path) -> None:
    """Use only disposable copies of the existing sample, never new research authority."""
    deadline = time.monotonic() + 90
    original = _inventory(sample)
    manifest_bytes = (sample / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    roles = manifest["roles"]
    assert len(roles) == 8
    object_roles: dict[str, list[str]] = {}
    for role, reference in roles.items():
        digest = reference["sha256"]
        assert len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)
        assert reference["ref"] == f"objects/sha256/{digest}"
        object_roles.setdefault(digest, []).append(role)
    assert 2 <= len(object_roles) <= 8
    directory.mkdir()
    calls = 0

    def verify(bundle: Path, *, expected: int = 0):
        nonlocal calls
        calls += 1
        assert calls <= len(object_roles) + 9
        before = _inventory(directory)
        assert _inventory(sample) == original
        remaining = deadline - time.monotonic()
        assert remaining > 0, "Installed offline diagnostic deadline exhausted"
        result = subprocess.run(
            [interpreter, "-I", "-c", _OFFLINE_GUARD, "verify-evidence", str(bundle)],
            cwd=directory,
            text=True,
            capture_output=True,
            check=False,
            timeout=min(15, remaining),
        )
        assert _inventory(directory) == before, "Offline CLI changed disposable fixture evidence"
        assert _inventory(sample) == original, "Offline CLI changed the original sample"
        if result.returncode != expected or (expected and result.stdout):
            raise RuntimeError(
                f"Guarded installed baseline CLI exited {result.returncode}: "
                f"{result.stdout}\n{result.stderr}"
            )
        return json.loads(result.stdout if expected == 0 else result.stderr)

    def missing(bundle: Path, digest: str, aliases: list[str]) -> None:
        error = verify(bundle, expected=3)["error"]
        assert set(error) == {"code", "message", "reason", "role", "roles", "sha256"}
        assert error["code"] == "research_store_integrity_or_io_failure"
        assert error["reason"] == "bundle_object_missing"
        assert error["roles"] == sorted(aliases) and error["role"] == sorted(aliases)[0]
        assert error["sha256"] == digest

    expected = verify(sample)
    assert expected["bundle_id"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert expected["accounting_verified"] is True and expected["native_replayed"] is False
    relocated = directory / "relocated"
    shutil.copytree(sample, relocated)
    assert verify(relocated) == expected
    for number, (digest, aliases) in enumerate(sorted(object_roles.items())):
        copied = directory / f"missing-object-{number:02}"
        shutil.copytree(sample, copied)
        (copied / "objects" / "sha256" / digest).unlink()
        missing(copied, digest, aliases)

    multiple = directory / "multiple-missing"
    shutil.copytree(sample, multiple)
    first, second = sorted(object_roles)[:2]
    for digest in (second, first):
        (multiple / "objects" / "sha256" / digest).unlink()
    missing(multiple, first, object_roles[first])

    aliased = directory / "missing-aliases"
    shutil.copytree(sample, aliased)
    alias_manifest = json.loads((aliased / "manifest.json").read_bytes())
    alias_roles = alias_manifest["roles"]
    old_digest = alias_roles["normalized"]["sha256"]
    digest = alias_roles["raw"]["sha256"]
    assert old_digest != digest
    alias_roles["normalized"] = dict(alias_roles["raw"])
    (aliased / "manifest.json").write_bytes(
        json.dumps(
            alias_manifest,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if not any(reference["sha256"] == old_digest for reference in alias_roles.values()):
        (aliased / "objects" / "sha256" / old_digest).unlink()
    (aliased / "objects" / "sha256" / digest).unlink()
    aliases = [role for role, reference in alias_roles.items() if reference["sha256"] == digest]
    # Only structural absence is tested; this rewritten manifest is never a valid research receipt.
    missing(aliased, digest, aliases)

    absent = directory / "never-created-root"
    error = verify(absent, expected=4)["error"]
    assert error["code"] == "research_evidence_not_found" and set(error) == {"code", "message"}
    assert not absent.exists()
    for name, relative in (
        ("manifest", "manifest.json"),
        ("invalid-manifest", "manifest.json"),
        ("objects", "objects"),
        ("sha256-container", "objects/sha256"),
    ):
        copied = directory / f"generic-{name}"
        shutil.copytree(sample, copied)
        target = copied / relative
        if name == "invalid-manifest":
            target.write_bytes(b"{}")
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        error = verify(copied, expected=3)["error"]
        assert error["code"] == "research_store_integrity_or_io_failure"
        assert set(error) == {"code", "message"}, "Structural failure invented object context"
    assert calls == len(object_roles) + 9
    assert _inventory(sample) == original
    assert time.monotonic() <= deadline, "Installed offline diagnostic deadline exhausted"
    print(
        "Installed baseline diagnostics: guarded relocated verification, declared missing "
        "objects/aliases and unchanged generic refusals passed without new research."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--save-sample", type=Path)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-evidence-wheel-") as temporary:
        directory = Path(temporary)
        store, registry, runs = (directory / name for name in ("data", "registry", "runs"))

        def run(*command: str, expected: int = 0):
            result = subprocess.run(
                [interpreter, "-I", "-m", "tickwitness", *command],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != expected or (expected and result.stdout):
                raise RuntimeError(
                    f"Installed evidence CLI failed: {result.stdout}\n{result.stderr}"
                )
            return json.loads(result.stdout if expected == 0 else result.stderr)

        ids = []
        for name in ("replay-partials.jsonl", "replay-confirmation.jsonl"):
            receipt = run(
                "import-events", name, "--input-root", str(examples), "--store", str(store)
            )
            ids.append(receipt["dataset_id"])
        frozen = run(
            "freeze-experiment",
            "experiment-request.json",
            "--input-root",
            str(examples),
            "--development-dataset",
            ids[0],
            "--confirmation-dataset",
            ids[1],
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        repeated = run(
            "freeze-experiment",
            "experiment-request.json",
            "--input-root",
            str(examples),
            "--development-dataset",
            ids[0],
            "--confirmation-dataset",
            ids[1],
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        assert repeated["protocol_id"] == frozen["protocol_id"] and repeated["created"] is False
        protocol_id = frozen["protocol_id"]
        scenario_command = (
            "validate-scenario",
            protocol_id,
            "assumption-request.json",
            "scenario-request.json",
            "--input-root",
            str(examples),
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        scenario = run(*scenario_command)
        assert run(*scenario_command) == scenario
        assert scenario["validation"]["source_bindings_verified"] is True
        assert scenario["validation"]["input_constraints_verified"] is True
        assert scenario["validation"]["execution_approved"] is False
        assert scenario["validation"]["calibration_status"] == "uncalibrated"
        assert scenario["validation"]["bindings"]["protocol_id"] == protocol_id
        assert scenario["validation"]["additional_delay"] == {"unit": "ns", "value": 20_000_000}
        assert not runs.exists()
        missing = directory / "never-created"
        scenario_denied = run(
            "validate-scenario",
            protocol_id,
            "absent-assumptions.json",
            "absent-scenario.json",
            "--input-root",
            str(missing / "inputs"),
            "--split",
            "confirmation",
            "--store",
            str(missing / "data"),
            "--registry",
            str(missing / "registry"),
            expected=5,
        )
        assert scenario_denied["error"]["code"] == "confirmation_access_denied"
        assert not missing.exists()
        denied = run(
            "replay-protocol",
            protocol_id,
            "--split",
            "confirmation",
            "--store",
            str(missing / "data"),
            "--registry",
            str(missing / "registry"),
            "--runs",
            str(missing / "runs"),
            expected=5,
        )
        assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
        command = (
            "replay-protocol",
            protocol_id,
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--runs",
            str(runs),
        )
        result = run(*command, expected=0 if arguments.native else 6)
        inspection_diagnostics(
            interpreter,
            store,
            registry,
            runs,
            protocol_id,
            result["attempt_id"] if arguments.native else result["error"]["attempt_id"],
            directory / "inspection-copies",
        )
        if arguments.native:
            observation = result["evaluation"]["claim_observation"]
            assert observation["eligible"] is True and observation["value"] == "-2"
            assert observation["satisfied"] is False
            destination = directory / "exported"
            exported = run(
                "export-evidence",
                result["run_id"],
                str(destination),
                "--store",
                str(store),
                "--registry",
                str(registry),
                "--runs",
                str(runs),
            )
            assert exported["native_replayed"] is False and exported["accounting_verified"] is True
            relocated = directory / "relocated"
            destination.rename(relocated)
            for path in (store, registry, runs):
                shutil.rmtree(path)
            verified = run("verify-evidence", str(relocated))
            assert verified == exported
            if arguments.save_sample is not None:
                if arguments.save_sample.exists():
                    raise RuntimeError("Sample destination already exists")
                shutil.copytree(relocated, arguments.save_sample)
            manifest = json.loads((relocated / "manifest.json").read_bytes())
            victim = relocated / manifest["roles"]["replay_result"]["ref"]
            victim.write_bytes(b"tampered")
            assert (
                run("verify-evidence", str(relocated), expected=3)["error"]["code"]
                == "research_store_integrity_or_io_failure"
            )
        else:
            failure = result["error"]
            assert failure["budget_consumed"] is True
            attempt = run("inspect-attempt", failure["attempt_id"], "--runs", str(runs))
            assert (
                attempt["state"] == "finalized"
                and attempt["outcome"]["kind"] == "replay_attempt_failure_v1"
            )
            sample = examples / "evidence-demo"
            verified = run("verify-evidence", str(sample))
            assert verified["accounting_verified"] is True and verified["native_replayed"] is False
        _offline_diagnostics(interpreter, examples / "evidence-demo", directory / "offline-copies")
    print(
        "Installed evidence workflow: versioned freeze, read-only stress-contract checks, "
        "budgeted replay, portable offline verification passed."
    )


if __name__ == "__main__":
    main()
