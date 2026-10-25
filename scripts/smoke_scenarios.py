#!/usr/bin/env python3
"""Run installed-wheel stress workflows remotely, outside the source directory."""

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-scenario-wheel-") as temporary:
        directory = Path(temporary)
        store, registry, runs = (directory / name for name in ("data", "registry", "runs"))

        def run(*command: str, expected: int = 0):
            result = subprocess.run(
                [interpreter, "-I", "-m", "tickwitness", *command],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
                timeout=180,
            )
            if result.returncode != expected or (expected and result.stdout):
                raise RuntimeError(f"Installed scenario CLI failed: {result.stdout}\n{result.stderr}")
            return json.loads(result.stdout if expected == 0 else result.stderr)

        ids = [
            run("import-events", name, "--input-root", str(examples), "--store", str(store))[
                "dataset_id"
            ]
            for name in ("replay-partials.jsonl", "replay-confirmation.jsonl")
        ]
        original = run("inspect-dataset", ids[0], "--store", str(store))
        frozen = run(
            "freeze-experiment",
            "stress-experiment-request.json",
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
        common = (
            "--store", str(store), "--registry", str(registry), "--runs", str(runs)
        )

        def scenario(name, expected=0):
            return run(
                "run-scenario", frozen["protocol_id"], "stress-assumption-request.json",
                f"stress-{name}-request.json", "--input-root", str(examples), *common,
                expected=expected
            )

        missing = directory / "never-created"
        denied = run(
            "run-scenario", "invalid-id", "absent.json", "absent.json", "--split", "confirmation",
            "--input-root", str(missing), "--store", str(missing / "data"),
            "--registry", str(missing / "registry"), "--runs", str(missing / "runs"), expected=5
        )
        assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
        if not arguments.native:
            failed = scenario("suffix", expected=6)["error"]
            assert failed["budget_consumed"] is True
            attempt = run(
                "inspect-scenario-attempt", failed["attempt_id"], "--runs", str(runs)
            )
            assert attempt["state"] == "finalized"
            assert attempt["outcome"]["kind"] == "scenario_attempt_failure_v1"
            assert attempt["scenario_intent"]["protocol_id"] == frozen["protocol_id"]
            assert run("inspect-dataset", ids[0], "--store", str(store)) == original
            print("Installed core scenario workflow: persistent failure intent and source preserved.")
            return
        baseline = run("replay-protocol", frozen["protocol_id"], *common)
        zero, suffix = scenario("zero"), scenario("suffix")
        audited = [run("inspect-scenario-run", item["run_id"], *common) for item in (zero, suffix)]
        for item in audited:
            assert item["verification"]["derivation_recomputed"] is True
            assert item["verification"]["accounting_verified"] is True
            assert item["verification"]["native_replayed"] is False
            assert item["receipt"]["execution_status"] == "completed"
        base_audit = baseline["evaluation"]["replay_evaluation"]
        zero_audit = zero["evaluation"]["replay_evaluation"]
        assert {key: value for key, value in base_audit.items() if key != "bindings"} == {
            key: value for key, value in zero_audit.items() if key != "bindings"
        }
        assert suffix["evaluation"]["replay_evaluation"]["valuation"]["net_marked_pnl"] == "-1"
        assert baseline["evaluation"]["claim_observation"]["value"] == "-2"
        assert "claim_observation" not in suffix["evaluation"]
        assert scenario("suffix", expected=8)["error"]["code"] == "attempt_budget_exhausted"
        destination = directory / "unsupported-baseline-export"
        rejected = run("export-evidence", suffix["run_id"], str(destination), *common, expected=2)
        assert rejected["error"]["code"] == "invalid_research_evidence" and not destination.exists()
        assert run("inspect-dataset", ids[0], "--store", str(store)) == original
        report = {
            "kind": "installed_scenario_execution_smoke_v1",
            "synthetic_data": True,
            "baseline": baseline,
            "zero": audited[0],
            "suffix": audited[1],
            "shared_budget_exhaustion_verified": True,
            "source_unchanged_verified": True,
            "baseline_bundle_rejection_verified": True,
        }
        if arguments.report is not None:
            arguments.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print("Installed native scenario workflow: zero control, nonzero stress, audits and budget passed.")


if __name__ == "__main__":
    main()
