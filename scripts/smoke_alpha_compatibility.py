#!/usr/bin/env python3
"""Qualify real unsupported-Python bootstrap without running qualification."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory

_ERROR = {
    "error": {
        "code": "unsupported_python_version",
        "message": "TickWitness alpha reproduction requires Python 3.12–3.14.",
    }
}
_RUNTIME_QUERY = """
import json
import sys
from importlib import metadata
versions = {}
for name in ('tickwitness', 'nautilus_trader'):
    try:
        versions[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        versions[name] = None
print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix,
                  'base_prefix': sys.base_prefix,
                  'version_info': list(sys.version_info[:3]),
                  'distributions': versions}, sort_keys=True))
"""
_BOOTSTRAP_GUARD = """
import builtins
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
runner = Path(sys.argv[1])
guard_report = Path(sys.argv[2])
code = compile(runner.read_bytes(), str(runner), 'exec')
arguments = [str(runner), *sys.argv[3:]]
observed_imports = []
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    observed_imports.append(name)
    if name not in {'sys', '__future__'}:
        raise AssertionError('Unsupported bootstrap attempted import: ' + name)
    return original_import(name, *args, **kwargs)
def forbidden(*args, **kwargs):
    raise AssertionError('Unsupported bootstrap attempted file IO, a worker or network')
saved = [(builtins, 'open', builtins.open), (io, 'open', io.open),
         (os, 'open', os.open), (os, 'mkdir', os.mkdir),
         (os, 'makedirs', os.makedirs),
         (subprocess, 'Popen', subprocess.Popen),
         (socket, 'socket', socket.socket),
         (socket, 'create_connection', socket.create_connection)]
for module, name, original in saved:
    setattr(module, name, forbidden)
builtins.__import__ = guarded_import
sys.argv = arguments
exit_code = None
try:
    try:
        exec(code, {'__name__': '__main__', '__file__': str(runner)})
    except SystemExit as error:
        exit_code = error.code
finally:
    builtins.__import__ = original_import
    for module, name, original in saved:
        setattr(module, name, original)
    guard_report.write_text(json.dumps({'observed_imports': observed_imports,
                                       'exit_code': exit_code,
                                       'actual_version_info': list(sys.version_info[:3]),
                                       'file_io_worker_and_network_tripwires': True},
                                      sort_keys=True), encoding='utf-8')
if exit_code is None:
    raise AssertionError('Unsupported runner returned without SystemExit')
raise SystemExit(exit_code)
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): "directory" if path.is_dir() else _sha(path.read_bytes())
        for path in root.rglob("*")
    }


@contextmanager
def _preserved_workspace(records: Path, report: Path) -> Iterator[Path]:
    with TemporaryDirectory(prefix="tickwitness-alpha-compatibility-") as temporary:
        root = Path(temporary)
        failure = None
        try:
            yield root
        except BaseException as error:
            failure = error
            for accepted_report in (
                report,
                root / "alpha-compatibility-smoke" / "report.json",
                records / "alpha-compatibility-smoke" / "report.json",
            ):
                with suppress(OSError):
                    accepted_report.unlink(missing_ok=True)
            raise
        finally:
            if not records.exists():
                try:
                    shutil.copytree(root, records)
                    (records / "diagnostic-capture.json").write_bytes(
                        _canonical(
                            {
                                "kind": "alpha_compatibility_workspace_diagnostics_v1",
                                "accepted": False,
                                "exception_type": (
                                    type(failure).__name__ if failure is not None else None
                                ),
                                "message": str(failure) if failure is not None else None,
                            }
                        )
                    )
                except Exception as diagnostic_error:
                    if failure is None:
                        raise
                    print(
                        "Failed to preserve alpha compatibility diagnostics: "
                        + str(diagnostic_error),
                        file=sys.stderr,
                    )


def _identity(interpreter: Path, runtime: dict) -> dict:
    expected_prefix = str(interpreter.absolute().parent.parent.resolve())
    assert str(Path(runtime["prefix"]).resolve()) == expected_prefix, (
        f"Requested interpreter {str(interpreter)!r} uses prefix {runtime['prefix']!r}; "
        f"expected virtual environment {expected_prefix!r}"
    )
    assert Path(runtime["prefix"]).resolve() != Path(runtime["base_prefix"]).resolve(), runtime
    assert runtime["distributions"]["nautilus_trader"] is None, runtime
    return {
        "requested_executable": str(interpreter.absolute()),
        "requested_venv_prefix_resolved": expected_prefix,
        "runtime": runtime,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "unsupported-python", "runner", "guide", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    arguments = parser.parse_args()
    originals = {
        "runner": (arguments.runner, _sha(arguments.runner.read_bytes())),
        "guide": (arguments.guide, _sha(arguments.guide.read_bytes())),
    }
    with _preserved_workspace(arguments.records_dir, arguments.report) as root:
        copied, transcripts, cwd = (root / name for name in ("source-inputs", "transcripts", "cwd"))
        for directory in (copied, transcripts, cwd):
            directory.mkdir()
        runner = copied / "reproduce.py"
        guide = copied / "README.md"
        shutil.copyfile(arguments.runner, runner)
        shutil.copyfile(arguments.guide, guide)
        for tool in ("shasum -a 256 -c -", "sha256sum -c -"):
            command = (
                "printf '%s  %s\\n' 'OWNER_CONFIRMED_ARCHIVE_SHA256' "
                "'alpha-reproduction-kit.tar.gz' | " + tool
            )
            assert command in guide.read_text(encoding="utf-8"), command
        assert "unsupported_python_version" in guide.read_text(encoding="utf-8")
        invocations = []

        def invoke(command: list[str], *, expected: int = 0) -> dict:
            completed = subprocess.run(
                command, cwd=cwd, capture_output=True, text=True, check=False, timeout=30
            )
            result = {
                "command": command,
                "expected_exit_code": expected,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            invocations.append(result)
            (transcripts / f"{len(invocations):04d}.json").write_bytes(_canonical(result))
            assert completed.returncode == expected, result
            return result

        supported_process = invoke([str(arguments.python.absolute()), "-I", "-c", _RUNTIME_QUERY])
        unsupported_process = invoke(
            [str(arguments.unsupported_python.absolute()), "-I", "-c", _RUNTIME_QUERY]
        )
        assert supported_process["stderr"] == unsupported_process["stderr"] == ""
        supported = _identity(arguments.python, json.loads(supported_process["stdout"]))
        unsupported = _identity(
            arguments.unsupported_python, json.loads(unsupported_process["stdout"])
        )
        assert [3, 12] <= supported["runtime"]["version_info"][:2] < [3, 15]
        assert supported["runtime"]["distributions"]["tickwitness"]
        assert unsupported["runtime"]["version_info"][:2] == [3, 9], unsupported
        assert unsupported["runtime"]["distributions"]["tickwitness"] is None, unsupported
        identities = {"supported": supported, "unsupported": unsupported}
        (root / "interpreter-identities.json").write_bytes(_canonical(identities))
        help_process = invoke([str(arguments.python.absolute()), "-I", str(runner), "--help"])
        assert help_process["stderr"] == ""
        assert "--participant-role" in help_process["stdout"]
        assert "--expected-kit-id" in help_process["stdout"]
        occupied = cwd / "existing-submission"
        occupied.mkdir()
        (occupied / "submission.json").write_bytes(b"Preserve this existing submission exactly.\n")
        occupied_before = _tree(occupied)
        kit = cwd / "must-not-read-kit"
        assert not kit.exists()
        cases = []
        for guarded in (False, True):
            for existing in (False, True):
                name = ("guarded-" if guarded else "direct-") + (
                    "existing-output" if existing else "new-output"
                )
                output = occupied if existing else cwd / (name + "-submission")
                runner_arguments = [
                    "--kit", str(kit), "--expected-kit-id", "0" * 64,
                    "--participant-id", "automation-compatibility",
                    "--participant-role", "automation", "--output", str(output),
                ]
                guard_path = root / (name + "-guard.json")
                if guarded:
                    command = [
                        str(arguments.unsupported_python.absolute()), "-I", "-c",
                        _BOOTSTRAP_GUARD, str(runner), str(guard_path), *runner_arguments,
                    ]
                else:
                    command = [
                        str(arguments.unsupported_python.absolute()), "-I", str(runner),
                        *runner_arguments,
                    ]
                process = invoke(command, expected=2)
                assert process["stdout"] == "" and "Traceback" not in process["stderr"]
                assert process["stderr"].endswith("\n")
                assert len(process["stderr"].splitlines()) == 1
                assert json.loads(process["stderr"]) == _ERROR, process
                assert not kit.exists() and _tree(occupied) == occupied_before
                assert output.exists() is existing
                guard = None
                if guarded:
                    guard = json.loads(guard_path.read_bytes())
                    assert guard["exit_code"] == 2
                    assert guard["actual_version_info"][:2] == [3, 9]
                    assert "sys" in guard["observed_imports"]
                    assert set(guard["observed_imports"]) <= {"__future__", "sys"}
                    assert guard["file_io_worker_and_network_tripwires"] is True
                cases.append(
                    {
                        "name": name,
                        "runner_exit_code": process["exit_code"],
                        "error": json.loads(process["stderr"]),
                        "new_submission_created": False,
                        "existing_submission_unchanged": True,
                        "guard": guard,
                    }
                )
        for key, (path, before) in originals.items():
            assert _sha(path.read_bytes()) == before
            assert _sha((runner if key == "runner" else guide).read_bytes()) == before
        report = {
            "kind": "installed_alpha_compatibility_acceptance_v1",
            "accepted": True,
            "source_inputs": {key: value[1] for key, value in originals.items()},
            "interpreter_identities": identities,
            "supported_runner_help_succeeded": True,
            "cases": cases,
            "actual_python_39_executed": True,
            "unsupported_bootstrap_only_imported_future_and_sys": True,
            "direct_runner_unmodified": True,
            "guarded_runner_source_bytes_unmodified": True,
            "source_byte_trees_unchanged": True,
            "new_research_attempts": False,
            "native_replayed": False,
            "external_attempts": 0,
            "external_attempt_gate": "PENDING",
        }
        report_path = root / "alpha-compatibility-smoke" / "report.json"
        report_path.parent.mkdir()
        report_path.write_bytes(_canonical(report))
        shutil.copytree(root, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(
                {
                    str(path.relative_to(arguments.records_dir)): _sha(path.read_bytes())
                    for path in arguments.records_dir.rglob("*")
                    if path.is_file()
                }
            )
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
