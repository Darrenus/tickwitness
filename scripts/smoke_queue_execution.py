#!/usr/bin/env python3
"""Exercise installed persistent queue execution outside the source checkout.

Run only in the remote verification environment. The control process imports
stdlib only; every product operation uses the installed CLI in isolated mode.
"""

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
    args = parser.parse_args()
    interpreter = str(args.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    report = {
        "kind": "installed_queue_execution_acceptance_v1",
        "native": args.native,
        "fixture_kind": "original_synthetic",
        "claim_verdict_issued": False,
    }
    with TemporaryDirectory(prefix="tickwitness-queue-execution-") as temporary:
        root = Path(temporary)
        store, registry, families, runs = [
            root / name for name in ("data", "registry", "families", "runs")
        ]

        def run(*command: str, expected: int = 0):
            result = subprocess.run(
                [interpreter, "-I", "-m", "tickwitness", *command],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=150,
            )
            if result.returncode != expected:
                raise RuntimeError(
                    f"Installed queue CLI exited {result.returncode}: "
                    f"{result.stdout}\n{result.stderr}"
                )
            # Partial dual-model output is intentionally structured stdout with a nonzero exit.
            return json.loads(result.stdout if result.stdout else result.stderr)

        ids = [
            run("import-events", name, "--input-root", str(examples), "--store", str(store))[
                "dataset_id"
            ]
            for name in ("queue-observations.jsonl", "replay-confirmation.jsonl")
        ]
        source = run(
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
        frozen = run(
            "freeze-queue-family",
            source["protocol_id"],
            "queue-family-request.json",
            "queue-constraint-request.json",
            "--input-root",
            str(examples),
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--families",
            str(families),
        )
        family_id = frozen["family_id"]
        assert frozen["family"]["policies"] == ["cancel_front_first_v1", "cancel_back_first_v1"]
        assert frozen["family"]["budget"]["max_attempts"] == 2 and not runs.exists()
        common = ("--families", str(families), "--store", str(store), "--runs", str(runs))
        missing = root / "never-created"
        for name, identity in (
            ("run-queue-family", "bad-id"),
            ("inspect-queue-family", "bad-id"),
            ("inspect-queue-run", "bad-id"),
        ):
            denied = run(
                name,
                identity,
                "--families",
                str(missing / "families"),
                "--store",
                str(missing / "data"),
                "--runs",
                str(missing / "runs"),
                "--split",
                "confirmation",
                expected=5,
            )
            assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
        submission = run("run-queue-family", family_id, *common, expected=0 if args.native else 6)
        report.update(
            {
                "source_protocol_id": source["protocol_id"],
                "family": frozen,
                "submission": submission,
            }
        )
        if args.native:
            assert submission["status"] == "completed" and not submission["failures"]
            front, back = submission["runs"]
            assert front["family_id"] == back["family_id"] == family_id
            assert front["attempt_id"] != back["attempt_id"]
            assert front["evaluation"]["filled_quantity_lots"] == 1
            assert back["evaluation"]["filled_quantity_lots"] == 0
            assert front["evaluation"]["actual_commission"] == "1"
            assert back["evaluation"]["actual_commission"] == "0"
            inspected = [
                run("inspect-queue-run", item["run_id"], *common) for item in (front, back)
            ]
            for item in inspected:
                assert item["verification"]["queue_execution_audited"] is True
                assert item["verification"]["native_replayed"] is False
                assert item["evaluation"]["scope"]["valuation_issued"] is False
                assert item["result"]["execution_status"] == "completed"
                assert item["result"]["order_trace"][-1]["kind"] == "OrderCanceled"
                assert item["result"]["bindings"]["family_id"] == family_id
            report["inspected_runs"] = inspected
            before = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            ledger = run("inspect-queue-family", family_id, *common)
            assert (
                ledger["budget"]["consumed_attempts"] == 2
                and ledger["budget"]["remaining_attempts"] == 0
            )
            assert {row["policy_id"] for row in ledger["attempts"]} == set(
                frozen["family"]["policies"]
            )
            exhausted = run("run-queue-family", family_id, *common, expected=8)
            assert (
                exhausted["status"] == "failed"
                and exhausted["failures"][0]["budget_consumed"] is False
            )
            assert exhausted["failures"][0]["code"] == "attempt_budget_exhausted"
            for item in (front, back):
                run("inspect-queue-run", item["run_id"], *common)
            after = {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            assert before == after, (
                "Read-only audit or exhausted execution mutated committed storage"
            )
            report.update(
                {"budget": ledger, "exhaustion": exhausted, "read_only_tree_verified": True}
            )
        else:
            assert submission["status"] == "failed" and len(submission["failures"]) == 1
            failure = submission["failures"][0]
            assert failure["code"] == "engine_unavailable" and failure["budget_consumed"] is True
            ledger = run("inspect-queue-family", family_id, *common)
            assert (
                ledger["budget"]["consumed_attempts"] == 1
                and ledger["budget"]["remaining_attempts"] == 1
            )
            assert ledger["attempts"][0]["outcome_kind"] == "queue_attempt_failure_v1"
            report["budget"] = ledger
        report["accepted"] = True
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        "Installed queue execution: frozen family, shared budget, durable outcomes "
        "and independent inspection passed."
    )


if __name__ == "__main__":
    main()
