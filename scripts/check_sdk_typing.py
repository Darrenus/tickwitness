#!/usr/bin/env python3
"""Qualify downstream SDK typing against a separately installed core wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FILES = ("development_consumer.py", "typing_valid.py", "typing_invalid.py")
EXPECTED_CODES = {"arg-type", "assignment", "attr-defined"}
MARKER = re.compile(r"# expect-error: ([a-z-]+)\s*$")
DIAGNOSTIC = re.compile(r"^(.+):(\d+): error: (.+)  \[([a-z-]+)\]$")

CORE_IDENTITY = r"""
import hashlib
import importlib.abc
import importlib.metadata
import json
import sys
import sysconfig
from pathlib import Path

native = ("nautilus_trader", "tickwitness.infrastructure._nautilus_native",
          "tickwitness.infrastructure._queue_native",
          "tickwitness.infrastructure._tagged_queue_native")
attempts = []
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in native):
            attempts.append(fullname)
            raise ImportError("Native import forbidden during SDK typing qualification")
sys.meta_path.insert(0, NoNative())
from tickwitness import sdk
import tickwitness
package = Path(tickwitness.__file__).resolve().parent
module = Path(sdk.__file__).resolve()
distribution = importlib.metadata.distribution("tickwitness")
site = sorted({str(Path(sysconfig.get_path(name)).resolve())
               for name in ("purelib", "platlib")})
typed = package / "py.typed"
assert sys.prefix != sys.base_prefix, "An independent installed-core environment is required"
assert package == Path(distribution.locate_file("tickwitness")).resolve()
assert any(package.is_relative_to(Path(value)) for value in site)
assert module == package / "sdk.py" and typed.is_file()
assert not attempts and not any(name in sys.modules for name in native)
assert sdk.SDK_CONTRACT_VERSION == 1
print(json.dumps({
    "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
    "python_version": list(sys.version_info[:3]), "version": distribution.version,
    "package_origin": str(package), "sdk_origin": str(module), "site_packages": site,
    "sdk_source": module.read_text(encoding="utf-8"),
    "sdk_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
    "py_typed": str(typed), "py_typed_sha256": hashlib.sha256(typed.read_bytes()).hexdigest(),
    "exports": list(sdk.__all__), "contract_version": sdk.SDK_CONTRACT_VERSION,
    "native_import_guard": True, "native_import_attempts": attempts, "sys_path": sys.path,
}, sort_keys=True))
"""

TYPE_IDENTITY = r"""
import importlib.metadata
import importlib.util
import json
import sys
spec = importlib.util.find_spec("mypy")
assert spec is not None and spec.origin is not None
print(json.dumps({"executable": sys.executable, "prefix": sys.prefix,
                  "base_prefix": sys.base_prefix, "origin": spec.origin,
                  "version": importlib.metadata.version("mypy")}, sort_keys=True))
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--type-python", required=True, type=Path)
    parser.add_argument("--consumer-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    parser.add_argument("--prior-report", type=Path)
    arguments = parser.parse_args()
    # Preserve virtual-environment entry-point symlinks rather than resolving them.
    core_python = arguments.python.absolute()
    type_python = arguments.type_python.absolute()
    records = arguments.records_dir.absolute()
    report_path = arguments.report.absolute()
    records.mkdir(parents=True, exist_ok=False)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + 180
    prior_children = 0
    child_limit = 4
    commands: list[dict[str, object]] = []
    budget: dict[str, object] = {
        "max_children": 4,
        "stage_max_children": 4,
        "ordinary_wait_seconds": 30,
        "admission_wait_seconds": 180,
        "started_monotonic_seconds": started,
        "stage_started_monotonic_seconds": started,
        "deadline_monotonic_seconds": deadline,
        "shared_with_prior_qualification": False,
        "count_scope": "direct_supervised_invocations_not_os_descendant_count",
    }
    report: dict[str, object] = {
        "kind": "installed_sdk_downstream_typing_v1",
        "accepted": False,
        "source_driver_sha256": digest(Path(__file__).read_bytes()),
        "consumer_source_directory": str(arguments.consumer_dir.absolute()),
        "commands": commands,
        "budget": budget,
        "scope": {"negative_fixture_executed": False, "research_execution": False},
    }
    write_json(report_path, report)
    environment = os.environ.copy()
    stripped = [name for name in ("PYTHONPATH", "MYPYPATH") if name in environment]
    for name in ("PYTHONPATH", "MYPYPATH"):
        environment.pop(name, None)

    def run(label: str, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        remaining = deadline - time.monotonic()
        if len(commands) >= child_limit or prior_children + len(commands) >= 32 or remaining <= 0:
            raise RuntimeError("SDK typing admission/wait budget exhausted")
        record: dict[str, object] = {
            "label": label,
            "argv": command,
            "cwd": str(cwd),
            "removed_environment_keys": stripped,
            "excluded_environment_keys": ["PYTHONPATH", "MYPYPATH"],
            "timeout_seconds": min(30, remaining),
        }
        commands.append(record)
        before = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=min(30, remaining),
            )
            record.update(
                stdout=completed.stdout, stderr=completed.stderr, exit_code=completed.returncode
            )
            return completed
        except Exception as error:
            record["failure"] = {"type": type(error).__name__, "message": str(error)}
            if isinstance(error, subprocess.TimeoutExpired):
                for name in ("stdout", "stderr"):
                    output = getattr(error, name)
                    record[name] = (
                        output.decode("utf-8", errors="replace")
                        if isinstance(output, bytes)
                        else output
                    )
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - before
            write_json(records / f"{len(commands):02d}-{label}.json", record)

    try:
        if arguments.prior_report is not None:
            prior_bytes = arguments.prior_report.read_bytes()
            (records / "prior-report.json").write_bytes(prior_bytes)
            report["prior_report"] = {
                "path": str(arguments.prior_report.absolute()),
                "sha256": digest(prior_bytes),
                "preserved_copy": "prior-report.json",
            }
            prior = json.loads(prior_bytes)
            if (
                not isinstance(prior, dict)
                or prior.get("kind") != "installed_python_sdk_consumer_acceptance_v1"
                or prior.get("accepted") is not True
                or not isinstance(prior.get("budget"), dict)
            ):
                raise RuntimeError("Prior SDK consumer report is not an accepted qualification")
            previous = prior["budget"]
            previous_start = previous.get("started_monotonic_seconds")
            previous_deadline = previous.get("deadline_monotonic_seconds")
            for value in (previous_start, previous_deadline):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise RuntimeError("Prior SDK budget requires finite monotonic timestamps")
            if previous_start > started or previous_deadline != previous_start + 180:
                raise RuntimeError("Prior SDK budget does not match the original monotonic window")
            count = previous.get("actual_children")
            if (
                type(count) is not int
                or not 0 <= count <= 28
                or type(previous.get("child_invocations")) is not int
                or previous["child_invocations"] != count
            ):
                raise RuntimeError("Prior SDK child count must be a real integer from zero to28")
            for name, expected_limit in (
                ("max_child_invocations", 32),
                ("functional_max_child_invocations", 28),
                ("reserved_typing_child_invocations", 4),
                ("max_child_seconds", 30),
                ("max_supervisor_seconds", 180),
            ):
                if type(previous.get(name)) is not int or previous[name] != expected_limit:
                    raise RuntimeError("Prior SDK qualification has incompatible limit: " + name)
            prior_children = count
            child_limit = min(4, 32 - prior_children)
            deadline = min(deadline, previous_deadline)
            budget.update(
                max_children=32,
                prior_actual_children=prior_children,
                prior_started_monotonic_seconds=previous_start,
                started_monotonic_seconds=previous_start,
                deadline_monotonic_seconds=deadline,
                remaining_stage_child_admissions=child_limit,
                shared_with_prior_qualification=True,
            )
            report["prior_budget"] = previous
            if deadline <= started:
                raise RuntimeError("Original SDK admission/wait budget exhausted before typing")
        with tempfile.TemporaryDirectory(prefix="tickwitness-sdk-types-") as temporary:
            work = Path(temporary)
            source_records = records / "sources"
            source_records.mkdir()
            sources: dict[str, str] = {}
            for name in FILES:
                data = (arguments.consumer_dir / name).read_bytes()
                data.decode("utf-8")
                (work / name).write_bytes(data)
                (source_records / name).write_bytes(data)
                sources[name] = digest(data)
            report["sources"] = sources
            report["independent_cwd"] = str(work)
            core = run(
                "installed-core-identity", [str(core_python), "-I", "-c", CORE_IDENTITY], work
            )
            if core.returncode != 0:
                raise RuntimeError("Installed SDK identity/import qualification failed")
            identity = json.loads(core.stdout)
            report["installed_core"] = identity
            sdk_source = identity["sdk_source"].encode("utf-8")
            if digest(sdk_source) != identity["sdk_sha256"]:
                raise RuntimeError("Installed SDK source and digest disagree")
            (source_records / "installed-sdk.py").write_bytes(sdk_source)
            typed = run("type-tool-identity", [str(type_python), "-I", "-c", TYPE_IDENTITY], work)
            if typed.returncode != 0:
                raise RuntimeError("Installed mypy identity qualification failed")
            report["type_tool"] = json.loads(typed.stdout)
            configuration = work / "mypy.ini"
            configuration.write_text("[mypy]\n", encoding="utf-8")
            (records / "mypy.ini").write_bytes(configuration.read_bytes())
            command = [
                str(type_python),
                "-I",
                "-m",
                "mypy",
                "--config-file",
                str(configuration),
                "--python-executable",
                str(core_python),
                "--no-incremental",
                "--strict",
                "--show-error-codes",
                "--no-pretty",
                "--no-error-summary",
                "--no-color-output",
                "--cache-dir",
                str(work / ".mypy_cache"),
            ]
            positive = run(
                "positive-consumer", [*command, "development_consumer.py", "typing_valid.py"], work
            )
            if positive.returncode != 0:
                raise RuntimeError("Actual consumer or positive SDK typing failed")
            expected = []
            for number, line in enumerate((work / "typing_invalid.py").read_text().splitlines(), 1):
                marker = MARKER.search(line)
                if marker is not None:
                    expected.append(
                        {"file": "typing_invalid.py", "line": number, "code": marker[1]}
                    )
            if len(expected) != 3 or {row["code"] for row in expected} != EXPECTED_CODES:
                raise RuntimeError(
                    "Negative fixture must name exactly the three frozen diagnostics"
                )
            report["expected_negative_diagnostics"] = expected
            negative = run("negative-fixture", [*command, "typing_invalid.py"], work)
            actual = []
            for line in negative.stdout.splitlines():
                if ": error:" not in line:
                    continue
                match = DIAGNOSTIC.fullmatch(line)
                if match is None:
                    raise RuntimeError("Unrecognized negative diagnostic: " + line)
                actual.append({"file": match[1], "line": int(match[2]), "code": match[4]})
            report["actual_negative_diagnostics"] = actual
            if negative.returncode != 1 or negative.stderr or actual != expected:
                raise RuntimeError(
                    "Negative typing failed for a different reason or diagnostic set"
                )
            report["accepted"] = True
    except Exception as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        report["actual_children"] = len(commands)
        budget["stage_actual_children"] = len(commands)
        budget["total_supervised_child_invocations"] = prior_children + len(commands)
        write_json(report_path, report)
    print(json.dumps({"accepted": report["accepted"], "report": str(report_path)}, sort_keys=True))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
