#!/usr/bin/env python3
"""Qualify installed supervised campaign limits and immutable core-only inspection.

CI invokes this stdlib controller against actual installed wheels. No controller
assertion substitutes for deadline/process-group or write-guard unit tests.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

_CONTROL = 32 * 1024 * 1024
_CANDIDATE = 64 * 1024 * 1024
_READONLY_GUARD = """
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
    raise AssertionError('Budget inspection requires an installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Budget inspection cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args, **kwargs):
    raise AssertionError('Readonly budget inspection cannot execute, reserve, write or use network')
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
for name in ('start', 'write_dispatch', 'write_link', 'write_result', 'write_stop'):
    setattr(LocalSearchCampaignStore, name, forbidden)
for name in ('start', 'write_allocation', 'write_stop'):
    setattr(LocalCampaignBudgetStore, name, forbidden)
BoundedReplayAdapter.__init__ = forbidden
SubprocessReplayAdapter.__init__ = forbidden
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


def _inodes(root: Path) -> dict[tuple[int, int], int]:
    result = {}
    for path in root.rglob("*"):
        if path.is_file():
            info = path.stat()
            result[(info.st_dev, info.st_ino)] = info.st_size
    return result


def _budget(**changes: int) -> dict:
    return {
        "kind": "campaign_budget_request_v1",
        "schema_version": 1,
        "max_evaluations": 5,
        "max_wall_time_ms": 120000,
        "max_storage_bytes": 512 * 1024 * 1024,
        **changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--verifier-python", type=Path)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    verifier = str((arguments.verifier_python or arguments.python).absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-budget-wheel-") as temporary:
        directory = Path(temporary)
        inputs = directory / "inputs"
        inputs.mkdir()
        for name in (
            "replay-partials.jsonl", "replay-confirmation.jsonl",
            "stress-experiment-request.json", "stress-assumption-request.json",
            "search-execution-grid-request.json", "campaign-budget-request.json",
        ):
            shutil.copyfile(examples / name, inputs / name)
        data, registry, plans = (directory / name for name in ("data", "registry", "plans"))

        def run(*command: str, expected: int = 0, readonly: bool = False, report=False) -> dict:
            executable = verifier if readonly else interpreter
            entry = ["-c", _READONLY_GUARD] if readonly else ["-m", "tickwitness"]
            completed = subprocess.run(
                [executable, "-I", *entry, *command], cwd=directory,
                text=True, capture_output=True, check=False, timeout=180,
            )
            use_stdout = expected == 0 or report
            payload = completed.stdout if use_stdout else completed.stderr
            unexpected = completed.stderr if use_stdout else completed.stdout
            if completed.returncode != expected or unexpected:
                raise RuntimeError(
                    f"Installed campaign-budget CLI exited {completed.returncode}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            return json.loads(payload)

        ids = [
            run("import-events", name, "--input-root", str(inputs), "--store", str(data))[
                "dataset_id"
            ]
            for name in ("replay-partials.jsonl", "replay-confirmation.jsonl")
        ]
        protocol = run(
            "freeze-experiment", "stress-experiment-request.json", "--input-root", str(inputs),
            "--development-dataset", ids[0], "--confirmation-dataset", ids[1],
            "--store", str(data), "--registry", str(registry),
        )
        plan = run(
            "freeze-search-plan", protocol["protocol_id"],
            "stress-assumption-request.json", "search-execution-grid-request.json",
            "--input-root", str(inputs), "--store", str(data),
            "--registry", str(registry), "--plans", str(plans),
        )
        source_before = (_tree(data), _tree(registry), _tree(plans))
        plan_id = plan["plan_id"]
        case_reports = []

        def common(runs: Path) -> tuple[str, ...]:
            return ("--plans", str(plans), "--store", str(data),
                    "--registry", str(registry), "--runs", str(runs))

        def inspect(runs: Path, identity: str = plan_id, *, expected=0) -> dict:
            return run(
                "inspect-bounded-search-campaign", identity, *common(runs),
                expected=expected, readonly=True,
            )

        def check_report(receipt: dict, budget_request: dict) -> None:
            assert receipt["kind"] == "bounded_search_campaign_report_v1"
            assert receipt["plan_id"] == plan_id
            assert receipt["protocol_id"] == protocol["protocol_id"]
            assert receipt["budget"]["limits"] == {
                key: budget_request[key]
                for key in ("max_evaluations", "max_wall_time_ms", "max_storage_bytes")
            }
            assert receipt["scope"] == {
                "phase": "development", "scenario_kind": "COUNTERFACTUAL_STRESS",
                "calibration_status": "uncalibrated", "claim_evaluated": False,
                "finding_issued": False, "full_trial_history_certified": False,
            }
            resources = receipt["resources"]
            assert resources["admitted_evaluations"] == len(receipt["allocations"])
            assert resources["reserved_storage_bytes"] == (
                _CONTROL + len(receipt["allocations"]) * _CANDIDATE
            )
            assert resources["reserved_storage_bytes"] <= budget_request["max_storage_bytes"]
            assert resources["admitted_evaluations"] <= budget_request["max_evaluations"]
            assert resources["storage_policy"] == "managed_new_file_payloads_v1"
            assert resources["wall_time_scope"] == "coordinator_execution_phase_v1"
            verified = receipt["verification"]
            for key in (
                "plan_recomputed", "source_revalidated", "budget_bindings_verified",
                "quota_reservations_verified",
            ):
                assert verified[key] is True
            assert verified["execution_reaudited"] is (receipt["execution"] is not None)
            for key in (
                "native_replayed", "runtime_limits_reenforced", "author_signature_verified",
                "physical_storage_usage_verified",
            ):
                assert verified[key] is False

        def execute_case(
            name: str, request: dict, expected_exit: int, reason: str, *, baseline=False,
        ):
            runs = directory / f"runs-{name}"
            filename = f"budget-{name}.json"
            (inputs / filename).write_bytes(_canonical(request))
            baseline_report = None
            if baseline:
                baseline_report = run(
                    "replay-protocol", protocol["protocol_id"], "--store", str(data),
                    "--registry", str(registry), "--runs", str(runs),
                )
            before_inodes = _inodes(runs)
            executed = run(
                "run-bounded-search-plan", plan_id, filename, "--input-root", str(inputs),
                *common(runs), expected=expected_exit, report=True,
            )
            check_report(executed, request)
            assert executed["exit_code"] == expected_exit and executed["stop_reason"] == reason
            assert executed["status"] == ("completed" if expected_exit == 0 else "stopped")
            before_read = (_tree(data), _tree(registry), _tree(plans), _tree(runs))
            inspected = inspect(runs)
            assert inspected == executed
            repeated = run(
                "run-bounded-search-plan", plan_id, filename, "--input-root", str(inputs),
                *common(runs), expected=expected_exit, readonly=True, report=True,
            )
            assert repeated == executed
            assert before_read == (_tree(data), _tree(registry), _tree(plans), _tree(runs))
            new_inodes = _inodes(runs)
            new_committed_payload = sum(size for inode, size in new_inodes.items()
                                        if inode not in before_inodes)
            assert new_committed_payload <= executed["resources"]["reserved_storage_bytes"]
            case_reports.append({
                "name": name, "request": request, "execution": executed,
                "inspection": inspected, "baseline": baseline_report,
                "new_observed_file_payload_bytes": new_committed_payload,
                "observed_payload_is_not_peak_or_physical_block_measurement": True,
                "same_plan_repeat_did_not_execute": True,
                "readonly_byte_tree_preserved": True,
            })
            return runs, executed

        missing = directory / "never-created"
        for command in ("run-bounded-search-plan", "inspect-bounded-search-campaign"):
            positionals = (
                ("invalid-id", "absent.json") if command.startswith("run-") else ("invalid-id",)
            )
            extra = ("--input-root", str(missing)) if command.startswith("run-") else ()
            denied = run(
                command, *positionals, *extra, "--split", "confirmation",
                "--plans", str(missing / "plans"), "--store", str(missing / "data"),
                "--registry", str(missing / "registry"), "--runs", str(missing / "runs"),
                expected=5, readonly=True,
            )
            assert denied["error"]["code"] == "confirmation_access_denied"
        assert not missing.exists()
        inspect(missing / "runs", expected=4)
        assert not missing.exists()
        invalid_request = dict(_budget(), max_evaluations=True)
        (inputs / "bad-budget.json").write_bytes(_canonical(invalid_request))
        rejected_runs = directory / "invalid-runs"
        run(
            "run-bounded-search-plan", plan_id, "bad-budget.json", "--input-root", str(inputs),
            *common(rejected_runs), expected=2,
        )
        assert not rejected_runs.exists()

        normal_runs, normal = execute_case(
            "normal", _budget(), 0 if arguments.native else 6,
            "completed" if arguments.native else "execution_stopped", baseline=arguments.native,
        )
        candidates = normal["execution"]["candidates"]
        if arguments.native:
            assert [row["status"] for row in candidates] == ["COMPLETED", "COMPLETED"]
            assert [row["attempt_index"] for row in candidates] == [2, 3]
            assert [row["evaluation"]["metric_observation"]["value"] for row in candidates] == [
                "-2", "-1",
            ]
            assert all(row["raw_result_audited"] for row in candidates)
            _, evaluation = execute_case(
                "evaluation", _budget(max_evaluations=1), 8, "evaluation_limit",
            )
            _, storage = execute_case(
                "storage-one", _budget(max_storage_bytes=_CONTROL + _CANDIDATE),
                8, "storage_limit",
            )
            for limited in (evaluation, storage):
                rows = limited["execution"]["candidates"]
                assert [row["status"] for row in rows] == ["COMPLETED", "NOT_DISPATCHED"]
                assert rows[0]["attempt_index"] == 1
                assert limited["resources"]["admitted_evaluations"] == 1
                assert rows[0]["raw_result_audited"] is True
            other_request = json.loads((inputs / "search-execution-grid-request.json").read_bytes())
            other_request["search_seed"] += 1
            (inputs / "other-plan.json").write_bytes(_canonical(other_request))
            other = run(
                "freeze-search-plan", protocol["protocol_id"], "stress-assumption-request.json",
                "other-plan.json", "--input-root", str(inputs), "--store", str(data),
                "--registry", str(registry), "--plans", str(plans),
            )
            exhausted = run(
                "run-bounded-search-plan", other["plan_id"], "budget-normal.json",
                "--input-root", str(inputs), *common(normal_runs), expected=8, report=True,
            )
            assert exhausted["stop_reason"] == "execution_stopped"
            assert exhausted["execution"]["stop_reason"] == "attempt_budget_exhausted"
            assert exhausted["execution"]["counts"]["reserved"] == 0
            assert inspect(normal_runs, other["plan_id"]) == exhausted
        else:
            assert [row["status"] for row in candidates] == ["FAILED", "NOT_DISPATCHED"]
            assert candidates[0]["attempt_index"] == 1
            assert candidates[0]["budget_consumed"] is True
            assert candidates[0]["raw_result_audited"] is False
            exhausted = None
        _, empty_storage = execute_case(
            "storage-zero", _budget(max_storage_bytes=_CONTROL), 8, "storage_limit",
        )
        assert empty_storage["resources"]["admitted_evaluations"] == 0
        if empty_storage["execution"] is not None:
            assert empty_storage["execution"]["counts"]["reserved"] == 0
        _, timed = execute_case("time", _budget(max_wall_time_ms=1), 8, "time_limit")
        assert timed["status"] != "completed"
        assert timed["resources"]["elapsed_ns"] >= 1_000_000
        if timed["execution"] is not None:
            assert timed["execution"]["counts"]["completed"] == 0
        changed = dict(_budget(), max_evaluations=6)
        (inputs / "changed-budget.json").write_bytes(_canonical(changed))
        before_mismatch = _tree(normal_runs)
        run(
            "run-bounded-search-plan", plan_id, "changed-budget.json", "--input-root", str(inputs),
            *common(normal_runs), expected=2,
        )
        assert _tree(normal_runs) == before_mismatch
        assert source_before[:2] == (_tree(data), _tree(registry))
        assert source_before[2].items() <= _tree(plans).items()
        report = {
            "kind": "installed_campaign_budget_acceptance_v1", "accepted": True,
            "synthetic_data": True, "native_execution": arguments.native,
            "cases": case_reports, "original_budget_exhaustion": exhausted,
            "source_and_original_protocol_unchanged": True,
            "confirmation_refused_before_io": True, "missing_roots_not_created": True,
            "invalid_budget_not_published": True, "changed_budget_not_overwritten": True,
            "core_only_readonly_reaudit": True, "committed_results_preserved": True,
            "observed_payload_within_reserved_envelopes": True,
        }
        arguments.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        arguments.records_dir.mkdir(parents=True, exist_ok=False)
        for path in directory.iterdir():
            if path.is_dir() and path.name != "inputs":
                shutil.copytree(path, arguments.records_dir / path.name)
        files = {
            str(path.relative_to(arguments.records_dir)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in arguments.records_dir.rglob("*") if path.is_file()
        }
        (arguments.records_dir / "artifact-files.json").write_bytes(_canonical(files))
        print(
            "Installed campaign budgets: resource stops, preserved outcomes "
            "and readonly audit passed."
        )


if __name__ == "__main__":
    main()
