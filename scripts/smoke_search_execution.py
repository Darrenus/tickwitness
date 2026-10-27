#!/usr/bin/env python3
"""Verify installed sequential candidate execution and core-only ledger inspection.

Only CI runs this script. The controller uses stdlib and invokes an installed
wheel outside the checkout. Native execution and readonly verification use
separate interpreters; the latter forbids engine, ledger writes and networking.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

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
    raise AssertionError('Readonly search verification requires a core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Search inspection cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args, **kwargs):
    raise AssertionError('Readonly inspection cannot execute, reserve, publish or use network')
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
for name in ('start', 'write_dispatch', 'write_link', 'write_result', 'write_stop'):
    setattr(LocalSearchCampaignStore, name, forbidden)
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
    with TemporaryDirectory(prefix="tickwitness-search-execution-wheel-") as temporary:
        directory = Path(temporary)
        inputs = directory / "inputs"
        inputs.mkdir()
        for name in (
            "replay-partials.jsonl",
            "replay-confirmation.jsonl",
            "stress-experiment-request.json",
            "stress-assumption-request.json",
            "search-execution-grid-request.json",
        ):
            shutil.copyfile(examples / name, inputs / name)
        store, registry, plans, runs = (
            directory / name for name in ("data", "registry", "plans", "runs")
        )

        def run(
            *command: str,
            expected: int = 0,
            readonly: bool = False,
            campaign_report: bool = False,
        ) -> dict:
            executable = verifier if readonly else interpreter
            entry = ["-c", _READONLY_GUARD] if readonly else ["-m", "tickwitness"]
            result = subprocess.run(
                [executable, "-I", *entry, *command],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
                timeout=180,
            )
            use_stdout = expected == 0 or campaign_report
            payload = result.stdout if use_stdout else result.stderr
            unexpected = result.stderr if use_stdout else result.stdout
            if result.returncode != expected or unexpected:
                raise RuntimeError(
                    f"Installed search execution CLI exited {result.returncode}: "
                    f"{result.stdout}\n{result.stderr}"
                )
            return json.loads(payload)

        ids = [
            run("import-events", name, "--input-root", str(inputs), "--store", str(store))[
                "dataset_id"
            ]
            for name in ("replay-partials.jsonl", "replay-confirmation.jsonl")
        ]
        frozen = run(
            "freeze-experiment",
            "stress-experiment-request.json",
            "--input-root",
            str(inputs),
            "--development-dataset",
            ids[0],
            "--confirmation-dataset",
            ids[1],
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        plan = run(
            "freeze-search-plan",
            frozen["protocol_id"],
            "stress-assumption-request.json",
            "search-execution-grid-request.json",
            "--input-root",
            str(inputs),
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--plans",
            str(plans),
        )
        journal = plan["plan"]["journal"]
        assert [row["status"] for row in journal] == [
            "ELIGIBLE",
            "DUPLICATE",
            "ELIGIBLE",
            "REJECTED",
        ]
        sources_before = (_tree(store), _tree(registry), _tree(plans))
        common = (
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--plans",
            str(plans),
            "--runs",
            str(runs),
        )
        replay_common = (
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--runs",
            str(runs),
        )
        missing = directory / "never-created"
        for command in ("run-search-plan", "inspect-search-campaign"):
            denied = run(
                command,
                "invalid-id",
                "--split",
                "confirmation",
                "--plans",
                str(missing / "plans"),
                "--store",
                str(missing / "data"),
                "--registry",
                str(missing / "registry"),
                "--runs",
                str(missing / "runs"),
                expected=5,
                readonly=True,
            )
            assert denied["error"]["code"] == "confirmation_access_denied"
        assert not missing.exists()
        absent = run(
            "inspect-search-campaign",
            plan["plan_id"],
            "--plans",
            str(plans),
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--runs",
            str(missing / "runs"),
            expected=4,
            readonly=True,
        )
        assert absent["error"]["code"] == "research_evidence_not_found"
        assert not missing.exists()
        corrupt_plans = directory / "corrupt-plans"
        shutil.copytree(plans, corrupt_plans)
        corrupt = corrupt_plans / "search-plans" / (plan["plan_id"] + ".json")
        corrupt.write_bytes(b"preserved-invalid-original")
        invalid_runs = directory / "invalid-runs"
        rejected = run(
            "run-search-plan",
            plan["plan_id"],
            "--plans",
            str(corrupt_plans),
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--runs",
            str(invalid_runs),
            expected=3,
        )
        assert rejected["error"]["code"] == "research_store_integrity_or_io_failure"
        assert not invalid_runs.exists()
        assert corrupt.read_bytes() == b"preserved-invalid-original"

        baseline = None
        if arguments.native:
            baseline = run("replay-protocol", frozen["protocol_id"], *replay_common)
        expected_exit = 0 if arguments.native else 6
        executed = run(
            "run-search-plan",
            plan["plan_id"],
            *common,
            expected=expected_exit,
            campaign_report=True,
        )
        assert executed["kind"] == "search_campaign_report_v1"
        assert executed["plan_id"] == plan["plan_id"]
        assert executed["protocol_id"] == frozen["protocol_id"]
        assert executed["scope"] == {
            "phase": "development",
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "calibration_status": "uncalibrated",
            "claim_evaluated": False,
            "finding_issued": False,
            "full_trial_history_certified": False,
        }
        assert executed["verification"] == {
            "plan_recomputed": True,
            "source_revalidated": True,
            "attempt_links_verified": True,
            "outcomes_reaudited": True,
            "native_replayed": False,
            "author_signature_verified": False,
        }
        before_inspect = (_tree(store), _tree(registry), _tree(plans), _tree(runs))
        inspected = run("inspect-search-campaign", plan["plan_id"], *common, readonly=True)
        assert inspected == executed
        repeated = run(
            "run-search-plan",
            plan["plan_id"],
            *common,
            expected=expected_exit,
            readonly=True,
            campaign_report=True,
        )
        assert repeated == inspected
        assert before_inspect == (_tree(store), _tree(registry), _tree(plans), _tree(runs))
        candidates = executed["candidates"]
        assert [row["ordinal"] for row in candidates] == [1, 3]
        attempted = [row for row in candidates if row["attempt_id"] is not None]
        assert len({row["attempt_id"] for row in attempted}) == len(attempted)
        assert len({row["attempt_index"] for row in attempted}) == len(attempted)
        if arguments.native:
            assert executed["status"] == "completed"
            assert executed["stop_reason"] == "planned_candidates_exhausted"
            assert [row["status"] for row in candidates] == ["COMPLETED", "COMPLETED"]
            assert [row["attempt_index"] for row in candidates] == [2, 3]
            assert executed["counts"] == {
                "eligible": 2,
                "dispatched": 2,
                "reserved": 2,
                "completed": 2,
                "failed": 0,
                "incomplete": 0,
                "unfinalized": 0,
            }
            assert all(row["reservation_link_present"] for row in candidates)
            assert all(row["raw_result_sha256"] is not None for row in candidates)
            assert all(row["raw_result_audited"] for row in candidates)
            assert [
                row["evaluation"]["replay_evaluation"]["valuation"]["net_marked_pnl"]
                for row in candidates
            ] == ["-2", "-1"]
            assert baseline["evaluation"]["claim_observation"]["value"] == "-2"
            for row in candidates:
                audited = run(
                    "inspect-scenario-run",
                    row["run_id"],
                    *replay_common,
                    readonly=True,
                )
                assert audited["receipt"]["scope"]["search_performed"] is False
                assert audited["verification"]["accounting_verified"] is True
                assert audited["verification"]["native_replayed"] is False
                assert row["evaluation"] == audited["evaluation"]
            other_request = json.loads((inputs / "search-execution-grid-request.json").read_bytes())
            other_request["search_seed"] += 1
            (inputs / "other-plan.json").write_bytes(_canonical(other_request))
            other = run(
                "freeze-search-plan",
                frozen["protocol_id"],
                "stress-assumption-request.json",
                "other-plan.json",
                "--input-root",
                str(inputs),
                "--store",
                str(store),
                "--registry",
                str(registry),
                "--plans",
                str(plans),
            )
            budget_stop = run(
                "run-search-plan",
                other["plan_id"],
                *common,
                expected=8,
                campaign_report=True,
            )
            assert budget_stop["status"] == "stopped"
            assert budget_stop["stop_reason"] == "attempt_budget_exhausted"
            assert [row["status"] for row in budget_stop["candidates"]] == [
                "BUDGET_EXHAUSTED",
                "NOT_DISPATCHED",
            ]
            assert all(row["attempt_id"] is None for row in budget_stop["candidates"])
            budget_tree = _tree(runs)
            assert (
                run(
                    "inspect-search-campaign",
                    other["plan_id"],
                    *common,
                    readonly=True,
                )
                == budget_stop
            )
            assert _tree(runs) == budget_tree
        else:
            budget_stop = None
            assert executed["status"] == "stopped"
            assert executed["stop_reason"] == "candidate_failed"
            assert [row["status"] for row in candidates] == ["FAILED", "NOT_DISPATCHED"]
            assert candidates[0]["attempt_index"] == 1
            assert candidates[0]["raw_result_audited"] is False
            assert executed["counts"] == {
                "eligible": 2,
                "dispatched": 1,
                "reserved": 1,
                "completed": 0,
                "failed": 1,
                "incomplete": 0,
                "unfinalized": 0,
            }
            failure = run(
                "inspect-scenario-attempt",
                candidates[0]["attempt_id"],
                "--runs",
                str(runs),
                readonly=True,
            )
            assert failure["budget_consumed"] is True
            assert failure["outcome"]["kind"] == "scenario_attempt_failure_v1"
            assert failure["scenario_intent"]["protocol_id"] == frozen["protocol_id"]
        assert sources_before[:2] == (_tree(store), _tree(registry))
        assert sources_before[2].items() <= _tree(plans).items()
        report = {
            "kind": "installed_search_execution_acceptance_v1",
            "accepted": True,
            "synthetic_data": True,
            "native_execution": arguments.native,
            "plan": plan,
            "baseline": baseline,
            "execution": executed,
            "inspection": inspected,
            "budget_stop": budget_stop,
            "same_plan_retry_did_not_execute": True,
            "core_only_readonly_reaudit": True,
            "source_and_original_protocol_unchanged": True,
            "duplicate_and_rejected_proposals_not_executed": True,
            "confirmation_refused_before_io": True,
            "missing_roots_not_created": True,
            "invalid_plan_no_run_publication": True,
        }
        arguments.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        arguments.records_dir.mkdir(parents=True, exist_ok=False)
        for name in ("data", "registry", "plans", "runs"):
            shutil.copytree(directory / name, arguments.records_dir / name)
        manifest = {}
        for path in arguments.records_dir.rglob("*"):
            if path.is_file():
                manifest[str(path.relative_to(arguments.records_dir))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        (arguments.records_dir / "artifact-files.json").write_bytes(_canonical(manifest))
        print(
            "Installed search execution: candidate links, shared budget and readonly audit passed."
        )


if __name__ == "__main__":
    main()
