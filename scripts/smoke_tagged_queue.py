#!/usr/bin/env python3
"""Qualify installed tagged reconstruction and its durable CLI outside the checkout.

Run only on remote CPU verification workers. The control process imports stdlib
only; all product operations use the actual installed wheel in isolated mode.
Both cases are original synthetic observations, not historical market evidence.
"""

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

POLICIES = ["protected_tag_front_cancel_v1", "protected_tag_back_cancel_v1"]


def _tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def _case(interpreter: str, examples: Path, root: Path, *, native: bool,
          final_mark: int) -> dict[str, object]:
    root.mkdir()
    store, registry, ledger = [root / name for name in ("data", "registry", "ledger")]
    fixtures = root / "fixtures"
    fixtures.mkdir()
    observations = [json.loads(line) for line in (examples / "queue-observations.jsonl").read_text().splitlines()]
    if final_mark != 100:
        observations[-1]["bids"].append([final_mark, 2])
    (fixtures / "observations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in observations), encoding="utf-8")
    (fixtures / "confirmation.jsonl").write_bytes((examples / "replay-confirmation.jsonl").read_bytes())

    def run(*command: str, expected: int = 0):
        result = subprocess.run([interpreter, "-I", "-m", "tickwitness", *command], cwd=root,
                                capture_output=True, text=True, check=False, timeout=150)
        if result.returncode != expected:
            raise RuntimeError(f"Installed tagged CLI exited {result.returncode}: {result.stdout}\n{result.stderr}")
        return json.loads(result.stdout if result.stdout else result.stderr)

    ids = [run("import-events", name, "--input-root", str(fixtures), "--store", str(store))["dataset_id"]
           for name in ("observations.jsonl", "confirmation.jsonl")]
    source = run("freeze-experiment", "experiment-request.json", "--input-root", str(examples),
                 "--development-dataset", ids[0], "--confirmation-dataset", ids[1],
                 "--store", str(store), "--registry", str(registry))
    freeze_args = ("freeze-tagged-queue", source["protocol_id"], "tagged-queue-request.json",
                   "queue-constraint-request.json", "--input-root", str(examples),
                   "--store", str(store), "--registry", str(registry))
    frozen = run(*freeze_args)
    repeated = run(*freeze_args)
    protocol_id = frozen["protocol_id"]
    protocol = frozen["protocol"]
    assert frozen["created"] is True and repeated["created"] is False
    assert repeated["protocol_id"] == protocol_id and repeated["protocol"] == protocol
    assert protocol["policies"] == POLICIES
    assert protocol["budget"]["max_attempts"] == 2 and not ledger.exists()
    assert protocol["claim_revision_id"] != protocol["source_protocol"]["claim_revision_id"]
    assert protocol["scope"]["source_claim_evaluated"] is False
    assert protocol["scope"]["literal_order_insertion"] is False
    assert protocol["scope"]["finding_issued"] is False
    assert protocol["model"]["intervention_id"] == "relabel_existing_tail_quantity_v1"
    common = ("--store", str(store), "--registry", str(registry), "--ledger", str(ledger))
    missing = root / "must-not-exist"
    for command in ("run-tagged-queue-pair", "inspect-tagged-queue", "inspect-tagged-queue-run"):
        refused = run(command, "bad-id", "--store", str(missing / "data"), "--registry", str(missing / "registry"),
                      "--ledger", str(missing / "ledger"), "--split", "confirmation", expected=5)
        assert refused["error"]["code"] == "confirmation_access_denied" and not missing.exists()
    submission = run("run-tagged-queue-pair", protocol_id, *common, expected=0 if native else 6)
    result = {"final_mark_ticks": final_mark, "source_protocol_id": source["protocol_id"],
              "frozen": frozen, "submission": submission}
    if not native:
        assert submission["status"] == "failed" and len(submission["failures"]) == 1
        failure = submission["failures"][0]
        assert failure["code"] == "engine_unavailable" and failure["budget_consumed"] is True
        inspection = run("inspect-tagged-queue", protocol_id, *common)
        assert inspection["budget"]["consumed_attempts"] == 1
        assert inspection["budget"]["remaining_attempts"] == 1
        assert inspection["attempts"][0]["outcome_kind"] == "tagged_queue_attempt_failure_v1"
        assert inspection["attempts"][0]["policy_id"] == POLICIES[0]
        assert inspection["verification"]["native_replayed"] is False
        result["budget"] = inspection
        result["missing_extra_no_refund_verified"] = True
        return result
    assert submission["status"] == "completed" and submission["failures"] == []
    front, back = submission["runs"]
    assert [front["policy_id"], back["policy_id"]] == POLICIES
    assert front["protocol_id"] == back["protocol_id"] == protocol_id
    assert front["attempt_id"] != back["attempt_id"]
    for item, lots, fee, pnl, truth, final_status in (
        (front, 2, "2", "-2" if final_mark == 100 else "2", final_mark > 100, "FILLED"),
        (back, 0, "0", "0", False, "CANCELED"),
    ):
        evaluation = item["evaluation"]
        assert evaluation["filled_quantity_lots"] == lots
        assert evaluation["actual_commission"] == fee
        assert evaluation["valuation"]["eligible"] is True
        assert evaluation["valuation"]["net_marked_pnl"] == pnl
        assert evaluation["valuation"]["mark"]["price_ticks"] == final_mark
        assert evaluation["claim_evaluation"]["truth"] is truth
        assert evaluation["claim_evaluation"]["claim_revision_id"] == protocol["claim_revision_id"]
        assert evaluation["final_order_status"] == final_status
        assert evaluation["scope"]["source_claim_evaluated"] is False
        assert evaluation["scope"]["finding_issued"] is False and evaluation["findings"] == []
    before = _tree(root)
    inspected = [run("inspect-tagged-queue-run", item["run_id"], *common) for item in (front, back)]
    for item, own, external, status in zip(inspected, (0, 2), (2, 0), ("FILLED", "CANCELED"), strict=True):
        assert item["verification"]["native_replayed"] is False
        assert item["verification"]["queue_execution_audited"] is True
        native_result = item["result"]
        horizon, cleanup = native_result["horizon_snapshot"], native_result["cleanup"]
        assert native_result["execution_status"] == "completed"
        assert native_result["bindings"]["protocol_id"] == protocol_id
        assert horizon["native_target_lots"] == horizon["queue_state"]["total_lots"] == 2
        assert horizon["queue_state"]["own_live_lots"] == own
        assert horizon["queue_state"]["external_lots"] == external
        assert cleanup["canceled_own_lots"] == own and cleanup["own_live_after_cleanup"] == 0
        assert cleanup["projected_total_after_cleanup"] == external
        assert cleanup["projected_external_after_cleanup"] == external
        assert cleanup["native_status"] == status and cleanup["native_unfilled_lots"] == own
        assert cleanup["book_role"] == "recorded_observation_cache"
        accepted = [row for row in native_result["order_trace"] if row["kind"] == "OrderAccepted"]
        assert len(accepted) == 1
        acceptance = accepted[0]["fields"]["actual_acceptance"]
        assert accepted[0]["source_ref"]["capture_seq"] == 1
        assert acceptance["native_bid_lots"] == 5
        assert acceptance["queue"]["ahead_lots"] == 3 and acceptance["queue"]["own_live_lots"] == 2
        assert acceptance["acceptance_role"] == "tagged_reconstruction_proxy"
        trades = [row for row in native_result["queue_trace"] if row["kind"] == "trade"]
        assert len(trades) == 1
        flow = trades[0]["flow"]
        assert flow["trade_lots"] == (flow["external_trade_ahead_lots"] + flow["own_trade_lots"] + flow["external_trade_behind_lots"]) == 3
        assert trades[0]["native_filled_lots"] == trades[0]["granted_lots"] == flow["own_trade_lots"] == 2 - own
        for row in native_result["queue_trace"]:
            state = row["after"]
            assert state["total_lots"] == state["ahead_lots"] + state["own_live_lots"] + state["behind_lots"]
            if row["observed_total_lots"] is not None:
                assert state["total_lots"] == row["observed_total_lots"]
        assert native_result["account_trace"][-2]["phase"] == "claim_horizon"
        assert native_result["account_trace"][-1]["phase"] == "post_horizon_cleanup"
        terminal = native_result["order_trace"][-1]
        assert terminal["kind"] == ("OrderFilled" if own == 0 else "OrderCanceled")
        if own:
            assert terminal["phase"] == "post_horizon_cleanup"
            assert terminal["native_time_ns"] == horizon["native_time_ns"]
    inspection = run("inspect-tagged-queue", protocol_id, *common)
    assert inspection["budget"]["consumed_attempts"] == 2 and inspection["budget"]["remaining_attempts"] == 0
    assert {row["policy_id"] for row in inspection["attempts"]} == set(POLICIES)
    exhausted = run("run-tagged-queue-pair", protocol_id, *common, expected=8)
    assert exhausted["status"] == "failed" and exhausted["failures"][0]["budget_consumed"] is False
    assert exhausted["failures"][0]["code"] == "attempt_budget_exhausted"
    assert run("inspect-tagged-queue-run", front["run_id"], *common) == inspected[0]
    assert run("inspect-tagged-queue-run", back["run_id"], *common) == inspected[1]
    assert before == _tree(root), "Reinspection or exhausted run changed committed bytes"
    result.update({"inspected_runs": inspected, "budget": inspection, "exhaustion": exhausted,
                   "read_only_tree_verified": True, "single_counted_allocation_verified": True})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    interpreter = str(args.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-tagged-installed-") as temporary:
        root = Path(temporary)
        cases = [_case(interpreter, examples, root / "standard", native=args.native, final_mark=100)]
        if args.native:
            cases.append(_case(interpreter, examples, root / "bid102", native=True, final_mark=102))
    report = {"kind": "installed_tagged_queue_acceptance_v1", "native": args.native,
              "fixture_kind": "original_synthetic", "source_claim_evaluated": False,
              "finding_issued": False, "cases": cases, "accepted": True}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                               encoding="utf-8")
    print("Installed tagged reconstruction: frozen claim, single-counted native fills, horizon/cleanup and durable shared-budget inspection passed.")


if __name__ == "__main__":
    main()
