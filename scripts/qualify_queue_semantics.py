#!/usr/bin/env python3
"""Remote, fixed-case qualification of queue projection and predicate semantics.

Every native model execution passes through the persistent shared-budget use
case. The explicitly frozen predicate is a semantic diagnostic, not permission
to evaluate a family source claim or issue a market non-identifiability finding.
The only command-line input is the report destination; observations and cases
are original fixed synthetic fixtures shipped with the source archive.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment
from tickwitness.application.queue_execution import (
    freeze_queue_family,
    inspect_queue_family,
    inspect_queue_run,
    queue_run_evidence,
    run_queue_family,
)
from tickwitness.application.queue_semantics import inspect_queue_semantics
from tickwitness.domain.evidence.qualification_predicates import (
    build_qualification_predicate,
    compare_qualification_predicates,
    qualify_predicate,
)
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.queue_family_registry import LocalQueueFamilyRegistry
from tickwitness.infrastructure.queue_replay import QueueSubprocessReplayAdapter

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ("cancel_front_first_v1", "cancel_back_first_v1")
CASE_IDS = (
    "standard_gt_zero",
    "higher_mark_gt_zero",
    "higher_mark_ge_zero",
    "standard_gt_minus_two",
    "no_cancel_control",
    "gross_churn_checkpoint",
    "same_time_capture_order",
    "flat_zero_comparator_boundaries",
)


def _check(case: dict[str, Any], name: str, actual: object, expected: object) -> None:
    case["checks"].append(
        {
            "name": name,
            "actual": actual,
            "expected": expected,
            "passed": canonical({"value": actual}) == canonical({"value": expected}),
        }
    )


def _fixture(case_id: str) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    if case_id not in CASE_IDS:
        raise ValueError("Only fixed original queue semantics qualification cases are supported")
    rows = [
        json.loads(line)
        for line in (ROOT / "examples" / "queue-observations.jsonl").read_bytes().splitlines()
    ]
    declaration = json.loads((ROOT / "examples" / "queue-constraint-request.json").read_bytes())
    source = json.loads((ROOT / "examples" / "experiment-request.json").read_bytes())
    if case_id.startswith("higher_mark"):
        rows[-1]["bids"] = [[100, 2], [102, 5]]
    if case_id in ("no_cancel_control", "flat_zero_comparator_boundaries"):
        rows[2]["bids"] = [[100, 8]]
        rows[4]["bids"] = rows[5]["bids"] = [[100, 5]]
        declaration["updates"][1]["cancellations_lots"] = 0
    if case_id == "gross_churn_checkpoint":
        declaration["updates"][1].update(additions_lots=1, cancellations_lots=4)
        rows[3]["quantity_lots"] = 2
        rows[4]["bids"] = rows[5]["bids"] = [[100, 3]]
    if case_id == "same_time_capture_order":
        for row in rows:
            row["receive_time_ns"] = rows[0]["receive_time_ns"]
            row["event_time_ns"] = rows[0]["event_time_ns"]
    source["claim"].update(
        title="Fixed queue semantics qualification: " + case_id,
        hypothesis="Source lineage only; this run does not evaluate a production claim.",
    )
    source["budget"]["max_attempts"] = 2
    return b"\n".join(canonical(row) for row in rows) + b"\n", declaration, source


def _predicates(case_id: str):
    comparators = (
        ("gt", "ge", "lt", "le")
        if case_id == "flat_zero_comparator_boundaries"
        else ("ge" if case_id == "higher_mark_ge_zero" else "gt",)
    )
    threshold = "-2" if case_id == "standard_gt_minus_two" else "0"
    return [
        build_qualification_predicate(
            canonical(
                {
                    "kind": "queue_qualification_predicate_v1",
                    "schema_version": 1,
                    "purpose": "semantic_qualification_only",
                    "metric": "net_marked_pnl_v1",
                    "unit": "USD",
                    "comparator": comparator,
                    "threshold": threshold,
                    "evaluation_policy": "qualification_flat_zero_last_visible_bid_v1",
                }
            )
        )
        for comparator in comparators
    ]


def _expected(case_id: str, comparator: str) -> tuple[list[int], list[str], list[bool]]:
    if case_id in ("no_cancel_control", "flat_zero_comparator_boundaries"):
        truth = comparator in ("ge", "le")
        return [0, 0], ["0", "0"], [truth, truth]
    values = ["1", "0"] if case_id.startswith("higher_mark") else ["-1", "0"]
    if case_id == "higher_mark_gt_zero":
        truths = [True, False]
    elif case_id in ("higher_mark_ge_zero", "standard_gt_minus_two"):
        truths = [True, True]
    else:
        truths = [False, False]
    return [1, 0], values, truths


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def run_case(case_id: str) -> dict[str, Any]:
    # Reject an unknown case before touching a fixture, storage or native runtime.
    if case_id not in CASE_IDS:
        raise ValueError("Only fixed original queue semantics qualification cases are supported")
    case: dict[str, Any] = {"case_id": case_id, "passed": False, "checks": []}
    try:
        raw, declaration, source_request = _fixture(case_id)
        predicates = _predicates(case_id)
        # Freeze every candidate policy before constructing the source and calling native.
        case["frozen_predicates"] = [
            {"predicate_id": predicate.predicate_id, "predicate": predicate.document}
            for predicate in predicates
        ]
        case["stages"] = ["qualification_predicates_frozen"]
        case["source_observations_jsonl"] = raw.decode("utf-8")
        case["source_observations_sha256"] = digest(raw)
        case["queue_request"] = declaration
        case["source_request"] = source_request
        with TemporaryDirectory(prefix="tickwitness-queue-semantics-") as temporary:
            root = Path(temporary)
            datasets = LocalDatasetStore(root / "data")
            registry = LocalExecutableProtocolRegistry(root / "registry")
            families = LocalQueueFamilyRegistry(root / "families")
            development = import_events(raw, lambda: datasets).dataset_id
            confirmation = import_events(
                (ROOT / "examples" / "replay-confirmation.jsonl").read_bytes(), lambda: datasets
            ).dataset_id
            source = freeze_experiment(
                canonical(source_request),
                development_dataset_id=development,
                confirmation_dataset_id=confirmation,
                registry_factory=lambda: registry,
                datasets_factory=lambda: datasets,
            )
            frozen = freeze_queue_family(
                source.protocol_id,
                canonical(
                    {
                        "kind": "queue_family_request_v1",
                        "schema_version": 1,
                        "cancel_at_capture_seq": 6,
                        "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 1000},
                    }
                ),
                canonical(declaration),
                split="development",
                registry_factory=lambda: registry,
                datasets_factory=lambda: datasets,
                families_factory=lambda: families,
            )
            case["family_id"] = frozen.family_id
            case["family"] = frozen.family.document
            case["stages"].append("source_and_shared_budget_family_frozen")
            calls: list[dict[str, Any]] = []

            def replay_factory(timeout: int):
                class ActualNativeExecution:
                    def run(self, replay_input):
                        ledger = LocalAttemptLedger(root / "runs", create=False)
                        reservations = ledger.list_reservations(frozen.family)
                        intent = ledger.get_intent(reservations[-1].attempt_id)
                        if intent is None:
                            raise AssertionError("Native invocation lacks a committed intent")
                        calls.append(
                            {
                                "policy_id": replay_input.policy_id,
                                "attempt_id": reservations[-1].attempt_id,
                                "intent_sha256": digest(intent),
                                "max_wall_seconds": timeout,
                            }
                        )
                        return QueueSubprocessReplayAdapter(timeout_seconds=timeout).run(
                            replay_input
                        )

                return ActualNativeExecution()

            submission = run_queue_family(
                frozen.family_id,
                split="development",
                families_factory=lambda: families,
                datasets_factory=lambda: datasets,
                ledger_factory=lambda: LocalAttemptLedger(root / "runs"),
                replay_factory=replay_factory,
            )
            case["submission"] = submission
            case["native_calls"] = calls
            case["stages"].append("persistent_native_dual_execution_completed")
            _check(case, "two model executions completed", submission["status"], "completed")
            _check(
                case,
                "exact frozen policy invocation order",
                [row["policy_id"] for row in calls],
                list(POLICIES),
            )
            _check(
                case, "different consumed attempts", len({row["attempt_id"] for row in calls}), 2
            )
            if submission["status"] != "completed":
                return case
            run_ids = [run["run_id"] for run in submission["runs"]]
            ledger = LocalAttemptLedger(root / "runs", create=False)
            before = _snapshot(root)
            inspected = [
                inspect_queue_run(
                    run_id,
                    split="development",
                    families_factory=lambda: families,
                    datasets_factory=lambda: datasets,
                    ledger_factory=lambda: ledger,
                )
                for run_id in run_ids
            ]
            evidence = [
                queue_run_evidence(run_id, ledger=ledger, families=families, datasets=datasets)
                for run_id in run_ids
            ]
            pair = inspect_queue_semantics(
                *run_ids,
                split="development",
                families_factory=lambda: families,
                datasets_factory=lambda: datasets,
                ledger_factory=lambda: ledger,
            )
            budget = inspect_queue_family(
                frozen.family_id,
                split="development",
                families_factory=lambda: families,
                datasets_factory=lambda: datasets,
                ledger_factory=lambda: ledger,
            )
            case["runs"] = inspected
            case["normalized_observations_jsonl"] = evidence[
                0
            ].replay_input.normalized_bytes.decode("utf-8")
            case["production_pair_qualification"] = pair
            case["budget_inspection"] = budget
            case["diagnostic_predicates"] = []
            for predicate in predicates:
                observations = [
                    qualify_predicate(item.replay_input, item.result, predicate)
                    for item in evidence
                ]
                comparison = compare_qualification_predicates(*observations)
                case["diagnostic_predicates"].append(
                    {
                        "predicate_id": predicate.predicate_id,
                        "observations": [item.document for item in observations],
                        "comparison": comparison,
                    }
                )
                comparator = predicate.document["comparator"]
                filled, values, truths = _expected(case_id, comparator)
                _check(
                    case,
                    f"{comparator} independently predicted fill lots",
                    [item.evaluation.document["filled_quantity_lots"] for item in evidence],
                    filled,
                )
                _check(
                    case,
                    f"{comparator} exact marked diagnostic values",
                    [item.document["value"] for item in observations],
                    values,
                )
                _check(
                    case,
                    f"{comparator} independently predicted truth values",
                    [item.document["satisfied"] for item in observations],
                    truths,
                )
                _check(
                    case,
                    f"{comparator} diagnostic relation",
                    comparison["diagnostic_status"],
                    "DIAGNOSTIC_PREDICATE_DISAGREEMENT"
                    if truths[0] != truths[1]
                    else "DIAGNOSTIC_PREDICATE_AGREEMENT",
                )
                _check(
                    case,
                    f"{comparator} no source claim authority",
                    [item.document["scope"]["source_claim_evaluated"] for item in observations],
                    [False, False],
                )
                _check(case, f"{comparator} diagnostic findings", comparison["findings"], [])
            _check(
                case,
                "same exact normalized observation bytes",
                evidence[0].replay_input.normalized_bytes
                == evidence[1].replay_input.normalized_bytes,
                True,
            )
            _check(case, "shared slots consumed", budget["budget"]["consumed_attempts"], 2)
            _check(case, "shared slots remaining", budget["budget"]["remaining_attempts"], 0)
            _check(
                case,
                "pair inspection never replays native",
                pair["verification"]["native_replayed"],
                False,
            )
            _check(
                case,
                "scope stays model sensitivity",
                pair["scope"]["scenario_kind"],
                "MODEL_SENSITIVITY",
            )
            _check(
                case,
                "actual observation compatibility remains unproved",
                pair["observation_compatibility"]["status"],
                "not_established",
            )
            _check(
                case,
                "source claim cannot be evaluated",
                pair["predicate"]["reason"],
                "queue_family_claim_lineage_only",
            )
            _check(
                case, "production pair truth is null", pair["predicate"]["truth_divergence"], None
            )
            _check(case, "production findings stay empty", pair["findings"], [])
            _check(
                case,
                "source-projected external histories verified",
                [model["external_only_projection"]["status"] for model in pair["models"]],
                ["verified", "verified"],
            )
            expected_fill = _expected(case_id, predicates[0].document["comparator"])[0][0]
            _check(
                case,
                "one named joint insertion accounting diagnostic",
                [model["single_counted_insertion"]["status"] for model in pair["models"]],
                [
                    "contradiction" if expected_fill else "necessary_checks_passed",
                    "necessary_checks_passed",
                ],
            )
            public_trade = 2 if case_id == "gross_churn_checkpoint" else 3
            trade_accounting = [
                model["single_counted_insertion"]["trades"][0] for model in pair["models"]
            ]
            _check(
                case,
                "single public trade cannot simultaneously fund external and own fills",
                [
                    [
                        row[key]
                        for key in (
                            "public_trade_lots",
                            "external_consumed_lots",
                            "own_filled_lots",
                            "total_allocated_lots",
                            "over_allocation_lots",
                        )
                    ]
                    for row in trade_accounting
                ],
                [
                    [
                        public_trade,
                        public_trade,
                        expected_fill,
                        public_trade + expected_fill,
                        expected_fill,
                    ],
                    [public_trade, public_trade, 0, public_trade, 0],
                ],
            )
            checkpoint = [
                next(
                    row
                    for row in model["single_counted_insertion"]["checkpoints"]
                    if row["source_ref"]["capture_seq"] == 5
                )
                for model in pair["models"]
            ]
            observed = 3 if case_id == "gross_churn_checkpoint" else 5 if not expected_fill else 2
            _check(
                case,
                "named insertion projection predicts the independently calculated mismatch",
                [
                    [
                        row[key]
                        for key in (
                            "recorded_external_lots",
                            "cumulative_own_filled_lots",
                            "candidate_projected_external_lots",
                            "mismatch_lots",
                        )
                    ]
                    for row in checkpoint
                ],
                [
                    [observed, expected_fill, observed + expected_fill, expected_fill],
                    [observed, 0, observed, 0],
                ],
            )
            _check(
                case, "read-only diagnostics create no additional native invocation", len(calls), 2
            )
            _check(
                case,
                "all read-only qualification leaves storage bytes unchanged",
                _snapshot(root) == before,
                True,
            )
            case["stages"].append("read_only_projection_and_predicate_diagnostics_completed")
        case["passed"] = bool(case["checks"]) and all(check["passed"] for check in case["checks"])
    except Exception as error:
        case["error"] = {"type": type(error).__name__, "message": str(error)}
    return case


def qualify() -> dict[str, Any]:
    cases = [run_case(case_id) for case_id in CASE_IDS]
    return {
        "kind": "queue_semantics_native_qualification_v1",
        "schema_version": 1,
        "qualification_scope": {
            "fixed_original_cases_only": True,
            "arbitrary_user_execution_enabled": False,
        },
        "production_finding_enabled": False,
        "user_data_valuation_enabled": False,
        "finding_issued": False,
        "observation_compatibility_proved": False,
        "cases": cases,
        "case_count": len(cases),
        "check_count": sum(len(case["checks"]) for case in cases),
        "semantics_qualified": all(case["passed"] for case in cases),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = qualify()
    raw = canonical(report) + b"\n"
    if arguments.output is None:
        print(raw.decode("utf-8"), end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_bytes(raw)
    return 0 if report["semantics_qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
