#!/usr/bin/env python3
"""Exercise source-bound candidate planning using an isolated installed core wheel.

This control process uses only stdlib. The product actions run remotely in an
installed interpreter, outside the checkout, with workers and networking denied.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

_GUARD = """
import importlib.abc
from importlib import metadata
import socket
import subprocess
import sys
try:
    metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Search planning smoke requires an installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Search planning cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
def forbidden(*args, **kwargs):
    raise AssertionError('Search planning cannot reserve attempts, use network or start workers')
LocalAttemptLedger.__init__ = forbidden
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
raise SystemExit(main(sys.argv[1:]))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-search-plan-wheel-") as temporary:
        directory = Path(temporary)
        inputs = directory / "inputs"
        inputs.mkdir()
        for name in (
            "replay-partials.jsonl",
            "replay-confirmation.jsonl",
            "stress-experiment-request.json",
            "stress-assumption-request.json",
            "search-grid-request.json",
            "search-random-request.json",
        ):
            shutil.copyfile(examples / name, inputs / name)
        store, registry, plans = (directory / name for name in ("data", "registry", "plans"))

        def run(*command: str, expected: int = 0, guarded: bool = True) -> dict:
            entry = ["-c", _GUARD] if guarded else ["-m", "tickwitness"]
            result = subprocess.run(
                [interpreter, "-I", *entry, *command],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
                timeout=180,
            )
            if result.returncode != expected or (expected and result.stdout):
                raise RuntimeError(
                    f"Installed planning CLI exited {result.returncode}: "
                    f"{result.stdout}\n{result.stderr}"
                )
            return json.loads(result.stdout if expected == 0 else result.stderr)

        ids = [
            run(
                "import-events", name, "--input-root", str(inputs), "--store", str(store),
                guarded=False,
            )["dataset_id"]
            for name in ("replay-partials.jsonl", "replay-confirmation.jsonl")
        ]
        frozen = run(
            "freeze-experiment",
            "stress-experiment-request.json",
            "--input-root", str(inputs),
            "--development-dataset", ids[0],
            "--confirmation-dataset", ids[1],
            "--store", str(store), "--registry", str(registry),
            guarded=False,
        )
        sources_before = (_tree(store), _tree(registry))
        def freeze(name: str, *, expected: int = 0, root: Path = plans) -> dict:
            return run(
                "freeze-search-plan", frozen["protocol_id"],
                "stress-assumption-request.json", name,
                "--input-root", str(inputs),
                "--store", str(store), "--registry", str(registry), "--plans", str(root),
                expected=expected,
            )

        def inspect(plan_id: str, *, expected: int = 0, root: Path = plans) -> dict:
            return run(
                "inspect-search-plan", plan_id,
                "--store", str(store), "--registry", str(registry), "--plans", str(root),
                expected=expected,
            )

        def check_receipt(receipt: dict) -> None:
            assert receipt["kind"] == "search_plan_receipt_v1"
            assert receipt["verification"]["plan_recomputed"] is True
            assert receipt["verification"]["source_revalidated"] is True
            assert receipt["verification"]["derived_candidates_checked"] is True
            assert receipt["verification"]["native_replayed"] is False
            assert receipt["scope"] == {
                "execution_started": False,
                "attempt_reserved": False,
                "search_performed": False,
                "finding_issued": False,
            }
            assert receipt["plan"]["scope"]["source_validated"] is False

        cases = []
        for name in ("search-grid-request.json", "search-random-request.json"):
            first = freeze(name)
            check_receipt(first)
            assert first["created"] is True
            before = (_tree(store), _tree(registry), _tree(plans))
            second = freeze(name)
            audited = inspect(first["plan_id"])
            assert second == audited == dict(first, created=False)
            assert before == (_tree(store), _tree(registry), _tree(plans))
            cases.append({"request": name, "receipt": first, "verification": audited})
        grid = cases[0]["receipt"]["plan"]
        assert [item["status"] for item in grid["journal"]] == [
            "ELIGIBLE", "DUPLICATE", "ELIGIBLE", "REJECTED",
        ]
        assert grid["journal"][1]["duplicate_of"] == 1
        assert grid["journal"][3]["reason"] == "outside_assumption_range"
        assert grid["counts"] == {"proposed": 4, "eligible": 2, "duplicate": 1, "rejected": 1}
        assert grid["generation_stop"] == "grid_exhausted"

        random_request = json.loads((inputs / "search-random-request.json").read_bytes())
        short_request = dict(random_request, max_proposals=3)
        (inputs / "short.json").write_bytes(_canonical(short_request))
        short = freeze("short.json")
        assert short["plan"]["journal"] == cases[1]["receipt"]["plan"]["journal"][:3]
        assert short["plan"]["generation_stop"] == "proposal_limit"
        singleton_request = dict(
            random_request,
            max_proposals=4,
            generator={
                "kind": "random_integer_with_replacement",
                "minimum_ns": 3000000000,
                "maximum_ns": 3000000000,
            },
        )
        (inputs / "singleton.json").write_bytes(_canonical(singleton_request))
        singleton = freeze("singleton.json")
        assert [item["status"] for item in singleton["plan"]["journal"]] == [
            "REJECTED", "DUPLICATE", "DUPLICATE", "DUPLICATE",
        ]
        assert singleton["plan"]["counts"] == {
            "proposed": 4, "eligible": 0, "duplicate": 3, "rejected": 1,
        }
        golden_vectors = []
        for seed in (0, 1, (1 << 63) - 1):
            golden_request = dict(
                random_request,
                search_seed=seed,
                generator={
                    "kind": "random_integer_with_replacement",
                    "minimum_ns": 0,
                    "maximum_ns": 60000000000,
                },
            )
            filename = f"golden-{seed}.json"
            (inputs / filename).write_bytes(_canonical(golden_request))
            golden = freeze(filename)
            check_receipt(golden)
            golden_vectors.append({
                "search_seed": seed,
                "minimum_ns": 0,
                "maximum_ns": 60000000000,
                "delays_ns": [item["delay_ns"] for item in golden["plan"]["journal"]],
                "receipt": golden,
            })

        missing = directory / "never-created"
        for command in ("freeze-search-plan", "inspect-search-plan"):
            positionals = (
                ("invalid-id", "absent.json", "absent.json")
                if command == "freeze-search-plan" else ("invalid-id",)
            )
            extra = ("--input-root", str(missing)) if command == "freeze-search-plan" else ()
            denied = run(
                command, *positionals, *extra, "--split", "confirmation",
                "--store", str(missing / "data"), "--registry", str(missing / "registry"),
                "--plans", str(missing / "plans"), expected=5,
            )
            assert denied["error"]["code"] == "confirmation_access_denied"
        absent = inspect("0" * 64, root=missing / "plans", expected=4)
        assert absent["error"]["code"] == "research_evidence_not_found"
        assert not missing.exists()
        invalid_request = dict(random_request, unexpected="not allowed")
        (inputs / "unknown.json").write_bytes(_canonical(invalid_request))
        invalid_output = directory / "invalid-output"
        freeze("unknown.json", root=invalid_output, expected=2)
        assert not invalid_output.exists()

        corrupt = directory / "corrupt-plans"
        shutil.copytree(plans, corrupt)
        grid_id = cases[0]["receipt"]["plan_id"]
        published = corrupt / "search-plans" / f"{grid_id}.json"
        published.write_bytes(b"corrupt-original-evidence")
        inspect(grid_id, root=corrupt, expected=3)
        freeze("search-grid-request.json", root=corrupt, expected=3)
        assert published.read_bytes() == b"corrupt-original-evidence"

        forged = json.loads(_canonical(grid))
        forged["journal"][0]["delay_ns"] = 1
        forged_bytes = _canonical(forged)
        forged_id = hashlib.sha256(forged_bytes).hexdigest()
        forged_path = plans / "search-plans" / f"{forged_id}.json"
        forged_path.write_bytes(forged_bytes)
        inspect(forged_id, expected=3)
        assert forged_path.read_bytes() == forged_bytes
        assert sources_before == (_tree(store), _tree(registry))
        assert not (directory / "runs").exists()
        assert not any(path.name == "attempts" for path in directory.rglob("*"))
        report = {
            "kind": "installed_search_plan_acceptance_v1",
            "accepted": True,
            "synthetic_data": True,
            "cases": cases,
            "short_random": short,
            "rejected_singleton": singleton,
            "golden_vectors": golden_vectors,
            "same_identity_and_readonly_verified": True,
            "raw_proposal_budget_and_prefix_verified": True,
            "confirmation_refused_before_io": True,
            "missing_roots_not_created": True,
            "invalid_request_not_published": True,
            "no_overwrite_verified": True,
            "fully_rehashed_journal_attack_rejected": True,
            "source_and_execution_registry_unchanged": True,
            "core_only_no_workers_or_attempts_verified": True,
        }
        arguments.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(
            "Installed search planning: deterministic journals, source rechecks and refusal passed."
        )


if __name__ == "__main__":
    main()
