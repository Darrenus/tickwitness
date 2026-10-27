#!/usr/bin/env python3
"""Qualify installed local search conclusions from genuine bounded campaign records."""

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
    raise AssertionError('Search conclusions require an installed core-only verifier')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Search conclusions cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args, **kwargs):
    raise AssertionError('Search conclusions cannot execute, reserve, write or use network')
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
for name in ('start', 'write_dispatch', 'write_link', 'write_result', 'write_stop'):
    setattr(LocalSearchCampaignStore, name, forbidden)
for name in ('start', 'write_allocation', 'write_stop'):
    setattr(LocalCampaignBudgetStore, name, forbidden)
LocalSearchFindingRegistry.freeze = forbidden
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
    parser.add_argument("--budget-report", required=True, type=Path)
    parser.add_argument("--budget-records", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    verifier = str((arguments.verifier_python or arguments.python).absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    source = json.loads(arguments.budget_report.read_bytes())
    assert source["kind"] == "installed_campaign_budget_acceptance_v1"
    assert source["accepted"] is True and source["native_execution"] is arguments.native
    source_records = arguments.budget_records.absolute()
    source_before = _tree(source_records)
    with TemporaryDirectory(prefix="tickwitness-search-findings-wheel-") as temporary:
        directory = Path(temporary)
        inputs, findings = directory / "inputs", directory / "findings"
        inputs.mkdir()
        shutil.copyfile(examples / "search-finding-request.json", inputs / "finding.json")
        cases = []

        def run(*command: str, expected=0, readonly=False, report=False) -> dict:
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
                    f"Installed search-finding CLI exited {completed.returncode}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            return json.loads(payload)

        def common(records: Path, runs: Path) -> tuple[str, ...]:
            return (
                "--plans", str(records / "plans"), "--store", str(records / "data"),
                "--registry", str(records / "registry"), "--runs", str(runs),
            )

        def freeze(plan_id: str, records: Path) -> dict:
            receipt = run(
                "freeze-search-finding-protocol", plan_id, "finding.json", "--input-root",
                str(inputs), "--plans", str(records / "plans"),
                "--finding-registry", str(findings),
            )
            assert receipt["kind"] == "search_finding_protocol_receipt_v1"
            inspected = run(
                "inspect-search-finding-protocol", receipt["protocol_id"],
                "--finding-registry", str(findings), readonly=True,
            )
            assert inspected["protocol"] == receipt["protocol"]
            repeated = run(
                "freeze-search-finding-protocol", plan_id, "finding.json", "--input-root",
                str(inputs), "--plans", str(records / "plans"),
                "--finding-registry", str(findings),
            )
            assert repeated["created"] is False
            assert repeated["protocol_id"] == receipt["protocol_id"]
            return receipt

        def assess(name, authority, records, runs, expected_outcome):
            before = (_tree(records), _tree(findings))
            command = (
                "evaluate-search-findings", authority["protocol_id"],
                *common(records, runs), "--finding-registry", str(findings),
            )
            receipt = run(*command, readonly=True)
            assert receipt == run(*command, readonly=True)
            assert before == (_tree(records), _tree(findings))
            assert receipt["kind"] == "search_finding_receipt_v1"
            assert receipt["finalization_status"] == "LOCAL_REAUDITED"
            report = receipt["report"]
            assert hashlib.sha256(_canonical(report)).hexdigest() == receipt["report_id"]
            assert report["outcome"] == expected_outcome
            assert report["finding_issued"] is (expected_outcome != "NOT_EVALUABLE")
            if expected_outcome == "COUNTEREXAMPLE_FOUND":
                assert report["conclusion_target"] == "frozen_eligible_candidate_robustness_v1"
                assert report["planned_predicate_truth"] is False
            elif expected_outcome == "NOT_EVALUABLE":
                assert report["conclusion_target"] == "conditional_stress_search_not_evaluable_v1"
                assert report["planned_predicate_truth"] is None
            else:
                assert report["conclusion_target"] == "no_false_witness_in_exact_audited_subset_v1"
            for key in ("source_claim_evaluated", "continuous_delay_space_exhausted",
                        "market_probability_inferred", "future_returns_guaranteed",
                        "preregistration_verified", "full_trial_history_certified"):
                assert report["scope"][key] is False
            coverage = report["coverage"]
            assert coverage["eligible_ordinals"] == [1, 3]
            assert coverage["continuous_delay_space_exhausted"] is False
            assert coverage["proposal_counts"] == {
                "proposed": 4, "eligible": 2, "duplicate": 1, "rejected": 1,
            }
            source_claim = authority["protocol"]["bindings"]["source_claim_revision_id"]
            assert report["predicate_id"] != source_claim
            bounded = run(
                "inspect-bounded-search-campaign", authority["protocol"]["bindings"]["plan_id"],
                *common(records, runs), readonly=True,
            )
            snapshot_hash = hashlib.sha256(_canonical(bounded)).hexdigest()
            assert report["source_snapshot_sha256"] == snapshot_hash
            assert report["budget"]["campaign_budget_id"] == bounded["budget_id"]
            assert report["budget"]["campaign_budget"] == bounded["budget"]
            assert report["execution"]["outer_stop_reason"] == bounded["stop_reason"]
            assert bounded["scope"]["claim_evaluated"] is False
            assert bounded["scope"]["finding_issued"] is False
            verified = receipt["verification"]
            for key in ("authority_recomputed", "source_revalidated", "findings_recomputed",
                        "budget_bindings_verified", "quota_reservations_verified"):
                assert verified[key] is True
            for key in ("native_replayed", "attempt_reserved", "portable_evidence_verified",
                        "author_signature_verified", "preregistration_verified",
                        "full_attempt_history_verified"):
                assert verified[key] is False
            cases.append({
                "name": name, "receipt": receipt, "bounded": bounded,
                "core_only_readonly_reaudit": True,
                "same_report_on_repeat": True, "byte_tree_preserved": True,
            })
            return report

        source_plan = source["cases"][0]["execution"]["plan_id"]
        source_authority = freeze(source_plan, source_records)
        for item in source["cases"]:
            expected = (
                "COUNTEREXAMPLE_FOUND"
                if arguments.native and item["name"] in ("normal", "evaluation", "storage-one")
                else "NOT_EVALUABLE"
            )
            result = assess(
                "source-" + item["name"], source_authority, source_records,
                source_records / ("runs-" + item["name"]), expected,
            )
            if expected == "COUNTEREXAMPLE_FOUND":
                assert result["coverage"]["false_ordinals"]
        if arguments.native:
            original = source["original_budget_exhaustion"]
            other_authority = freeze(original["plan_id"], source_records)
            assess("empty-original-budget", other_authority, source_records,
                   source_records / "runs-normal", "NOT_EVALUABLE")

            # Freeze the negative-control numeric criterion before executing it.
            # The finding request cannot substitute a favorable threshold later.
            records = directory / "true-criterion"
            records.mkdir()
            for name in ("replay-partials.jsonl", "replay-confirmation.jsonl",
                         "stress-assumption-request.json", "search-execution-grid-request.json"):
                shutil.copyfile(examples / name, inputs / name)
            request = json.loads((examples / "stress-experiment-request.json").read_bytes())
            request["claim"].update(
                title="Fixed synthetic negative-control criterion",
                hypothesis="Net marked PnL exceeds minus three USD in the declared baseline.",
                threshold="-3",
            )
            (inputs / "true-experiment.json").write_bytes(_canonical(request))
            data = records / "data"
            ids = [
                run("import-events", name, "--input-root", str(inputs), "--store", str(data))[
                    "dataset_id"
                ]
                for name in ("replay-partials.jsonl", "replay-confirmation.jsonl")
            ]
            protocol = run(
                "freeze-experiment", "true-experiment.json", "--input-root", str(inputs),
                "--development-dataset", ids[0], "--confirmation-dataset", ids[1],
                "--store", str(data), "--registry", str(records / "registry"),
            )

            def plan(filename):
                return run(
                    "freeze-search-plan", protocol["protocol_id"],
                    "stress-assumption-request.json", filename, "--input-root", str(inputs),
                    "--store", str(data), "--registry", str(records / "registry"),
                    "--plans", str(records / "plans"),
                )

            planned = plan("search-execution-grid-request.json")
            authority = freeze(planned["plan_id"], records)

            def execute(name, selected_plan, budget, expected):
                filename = f"{name}-budget.json"
                (inputs / filename).write_bytes(_canonical(budget))
                runs = records / ("runs-" + name)
                receipt = run(
                    "run-bounded-search-plan", selected_plan["plan_id"], filename,
                    "--input-root", str(inputs), *common(records, runs),
                    expected=expected, report=True,
                )
                return runs, receipt

            runs, _ = execute("normal", planned, _budget(), 0)
            full = assess("all-true", authority, records, runs, "NO_COUNTEREXAMPLE_FOUND")
            assert full["coverage"]["audited_ordinals"] == [1, 3]
            assert full["coverage"]["coverage_complete_for_plan"] is True
            assert full["planned_predicate_truth"] is True
            for name, limits in (
                ("evaluation", _budget(max_evaluations=1)),
                ("storage", _budget(max_storage_bytes=96 * 1024 * 1024)),
            ):
                limited_runs, _ = execute(name, planned, limits, 8)
                prefix = assess(name + "-true-prefix", authority, records, limited_runs,
                                "NO_COUNTEREXAMPLE_FOUND")
                assert prefix["coverage"]["audited_ordinals"] == [1]
                assert prefix["coverage"]["unevaluated_ordinals"] == [3]
                assert prefix["coverage"]["coverage_complete_for_plan"] is False
                assert prefix["planned_predicate_truth"] is None
            other = json.loads((inputs / "search-execution-grid-request.json").read_bytes())
            other["search_seed"] += 1
            (inputs / "other-plan.json").write_bytes(_canonical(other))
            second_plan = plan("other-plan.json")
            second_authority = freeze(second_plan["plan_id"], records)
            (inputs / "normal-budget.json").write_bytes(_canonical(_budget()))
            exhausted = run(
                "run-bounded-search-plan", second_plan["plan_id"], "normal-budget.json",
                "--input-root", str(inputs), *common(records, runs), expected=8, report=True,
            )
            assert exhausted["execution"]["stop_reason"] == "attempt_budget_exhausted"
            attempts = [row["attempt_index"] for row in exhausted["execution"]["candidates"]]
            assert attempts == [3, None]
            prefix = assess("original-budget-true-prefix", second_authority, records, runs,
                            "NO_COUNTEREXAMPLE_FOUND")
            assert prefix["coverage"]["audited_ordinals"] == [1]
            assert prefix["planned_predicate_truth"] is None

        missing = directory / "absent"
        for command, positional, options in (
            ("freeze-search-finding-protocol", ("invalid", "missing.json"),
             ("--input-root", str(missing), "--plans", str(missing / "plans"))),
            ("inspect-search-finding-protocol", ("invalid",), ()),
            ("evaluate-search-findings", ("invalid",), common(missing, missing / "runs")),
        ):
            denied = run(command, *positional, *options, "--finding-registry",
                         str(missing / "findings"), "--split", "confirmation", expected=5,
                         readonly=True)
            assert denied["error"]["code"] == "confirmation_access_denied"
        assert not missing.exists()
        run("inspect-search-finding-protocol", source_authority["protocol_id"],
            "--finding-registry", str(missing / "findings"), expected=4, readonly=True)
        assert not missing.exists()
        corrupted = directory / "corrupted-data"
        shutil.copytree(source_records / "data", corrupted)
        development = source_authority["protocol"]["bindings"]["development_dataset_id"]
        manifest = json.loads((corrupted / "manifests" / f"{development}.json").read_bytes())
        raw = corrupted / manifest["objects"]["raw"]["ref"]
        raw.write_bytes(raw.read_bytes() + b"\n")
        rejected = run(
            "evaluate-search-findings", source_authority["protocol_id"],
            "--plans", str(source_records / "plans"), "--store", str(corrupted),
            "--registry", str(source_records / "registry"),
            "--runs", str(source_records / "runs-normal"),
            "--finding-registry", str(findings), expected=3, readonly=True,
        )
        assert "error" in rejected and "report" not in rejected
        assert source_before == _tree(source_records)
        report = {
            "kind": "installed_search_finding_acceptance_v1", "accepted": True,
            "synthetic_data": True, "native_execution": arguments.native, "cases": cases,
            "source_records_unchanged": True, "core_only_readonly_reaudit": True,
            "source_claim_scope_unchanged": True, "confirmation_refused_before_io": True,
            "missing_roots_not_created": True, "corrupt_source_is_error_not_not_evaluable": True,
            "criterion_frozen_before_negative_control_execution": arguments.native,
            "reporting_does_not_reserve_attempts": True,
        }
        arguments.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        arguments.records_dir.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source_records, arguments.records_dir / "budget-source")
        for path in directory.iterdir():
            if path.is_dir() and path.name not in ("inputs", "corrupted-data"):
                shutil.copytree(path, arguments.records_dir / path.name)
        files = {
            str(path.relative_to(arguments.records_dir)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in arguments.records_dir.rglob("*") if path.is_file()
        }
        (arguments.records_dir / "artifact-files.json").write_bytes(_canonical(files))
        print(
            "Installed search findings: scoped witnesses, budget coverage "
            "and readonly audit passed."
        )


if __name__ == "__main__":
    main()
