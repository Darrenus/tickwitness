#!/usr/bin/env python3
"""Qualify installed bounded reduction search using one original live ledger."""

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

_GOLDEN = {
    "bundle_id": "2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369",
    "report_id": "398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb",
}
_STATE_FLAGS = {
    "from_origin_prefix_replayed": True,
    "state_projection_audited": True,
    "focus_state_captured": False,
    "pre_engine_end_state_captured": False,
    "initial_state_materialized": False,
    "checkpoint_used": False,
    "checkpoint_resume_verified": False,
    "reduced_predicate_evaluated": False,
    "witness_preservation_verified": False,
    "margin_lock_algorithm_certified": False,
}
_PRESERVATION_SCOPE = {
    "phase": "development",
    "authority": "original_false_witness_numeric_criterion_v1",
    "source_claim_evaluated": False,
    "baseline_truth_evaluated": False,
    "original_finding_rewritten": False,
    "original_predicate_domain_extended": False,
    "budget_owner_changed": False,
    "global_minimum_verified": False,
    "local_minimum_verified": False,
    "checkpoint_resume_verified": False,
    "global_ledger_authenticity_verified": False,
    "author_signature_verified": False,
    "human_domain_approval_verified": False,
    "confirmation_accessed": False,
}
_SEARCH_VERIFICATION = {
    "source_package_reaudited": True,
    "plan_recomputed": True,
    "observed_original_prefix_matched": True,
    "greedy_traversal_recomputed": True,
    "committed_outcomes_reaudited": True,
    "saved_assessments_recomputed": True,
    "native_replayed": False,
    "attempt_reserved": False,
    "source_claim_evaluated": False,
    "baseline_truth_evaluated": False,
    "original_predicate_domain_extended": False,
    "local_minimum_verified": False,
    "global_minimum_verified": False,
    "checkpoint_resume_verified": False,
    "global_ledger_authenticity_verified": False,
    "full_attempt_history_verified": False,
    "author_signature_verified": False,
    "monotonic_clock_authenticity_verified": False,
    "physical_storage_usage_verified": False,
    "hard_total_deadline_enforced": False,
    "total_storage_quota_enforced": False,
    "hard_cancel_enforced": False,
}
_POINTS = (
    (7, 1_000_000_000, "NOT_PRESERVED"),
    (6, 2_000_000_000, "PRESERVED"),
    (6, 1_000_000_000, "NOT_PRESERVED"),
    (5, 2_000_000_000, "PRESERVED"),
    (5, 1_000_000_000, "NOT_PRESERVED"),
    (4, 2_000_000_000, "PRESERVED"),
    (4, 1_000_000_000, "NOT_EVALUABLE"),
)

_GUARD = """
import importlib.abc
from importlib import metadata
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
try:
    metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Reduction search inspection requires an installed core-only runtime')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Core inspection cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_confirmation import (
    LocalConfirmationRegistry, LocalConfirmationExposureLedger,
)
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry
from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args, **kwargs):
    raise AssertionError('Guarded operation cannot execute, reserve, publish or use network')
mode = sys.argv.pop(1)
socket.socket = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
subprocess.Popen = forbidden
BoundedReplayAdapter.__init__ = forbidden
SubprocessReplayAdapter.__init__ = forbidden
for repository in (LocalCampaignBudgetStore, LocalExecutableProtocolRegistry,
                   LocalDatasetStore, LocalProtocolRegistry,
                   LocalConfirmationRegistry, LocalConfirmationExposureLedger,
                   LocalSearchFindingRegistry, LocalSearchPlanRegistry):
    repository.__init__ = forbidden
original_search_init = LocalSearchCampaignStore.__init__
def namespace_init(self, *args, **kwargs):
    if type(self) is LocalSearchCampaignStore:
        forbidden()
    return original_search_init(self, *args, **kwargs)
LocalSearchCampaignStore.__init__ = namespace_init
for name in ('bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
if mode != 'exhaustion':
    for name in ('reserve', 'reserve_with_nonce'):
        setattr(LocalAttemptLedger, name, forbidden)
if mode == 'readonly':
    for name in ('start', 'write_dispatch', 'write_link', 'write_result',
                 'write_stop', 'write_cancel'):
        setattr(LocalReductionCampaignStore, name, forbidden)
"""

_PRE_IO = """
from tickwitness.application.reduction_search import (
    freeze_reduction_search, run_reduction_search,
    inspect_reduction_search, cancel_reduction_search,
)
from tickwitness.application.research import ConfirmationAccessDenied
class Unreadable:
    def __getattribute__(self, name):
        raise AssertionError('Confirmation operation accessed evidence: ' + name)
for operation in ('freeze', 'run', 'inspect', 'cancel'):
    try:
        common = dict(source=Unreadable(), split='confirmation',
                      ledger_factory=forbidden, store_factory=forbidden)
        if operation == 'freeze':
            freeze_reduction_search(Unreadable(), Unreadable(),
                                    expected_bundle_id='invalid',
                                    expected_report_id='invalid',
                                    split='confirmation', ledger_factory=forbidden,
                                    store_factory=forbidden)
        elif operation == 'run':
            run_reduction_search('invalid', **common, engine_factory=forbidden)
        elif operation == 'inspect':
            inspect_reduction_search('invalid', **common)
        else:
            cancel_reduction_search('invalid', **common)
    except ConfirmationAccessDenied:
        pass
    else:
        raise AssertionError('Confirmation operation returned a result')
print(json.dumps({'confirmation_operations_rejected_before_io': 4}))
"""

_LEDGER_VIEW = """
from tickwitness.application.search_evidence import verify_search_package
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import (
    load_search_finding_protocol,
)
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle
source = read_search_evidence_bundle(Path(sys.argv[1]))
verify_search_package(source, expected_bundle_id=sys.argv[3])
authority = load_search_finding_protocol(source.artifacts['finding_protocol'])
protocol = load_executable_protocol(canonical(authority.plan.document['protocol']))
ledger = LocalAttemptLedger(Path(sys.argv[2]), create=False)
slots = []
for reservation in ledger.list_reservations(protocol):
    outcome = ledger.get_outcome(reservation.attempt_id)
    intent = ledger.get_intent(reservation.attempt_id)
    slots.append({'attempt_id': reservation.attempt_id,
                  'attempt_index': reservation.attempt_index,
                  'reservation': reservation.document,
                  'intent_id': None if intent is None else digest(intent),
                  'outcome_id': None if outcome is None else digest(outcome),
                  'outcome_kind': None if outcome is None else json.loads(outcome)['kind']})
print(json.dumps({'protocol_id': protocol.protocol_id,
                  'budget': protocol.document['budget'], 'slots': slots}, sort_keys=True))
"""

_READ_ARTIFACT = """
ledger = LocalAttemptLedger(Path(sys.argv[1]), create=False)
print(ledger.read_artifact(sys.argv[2]).decode('utf-8'))
"""

_CANCEL_AFTER_NATIVE = """
import json
from pathlib import Path
import sys
from tickwitness.application.reduction_search import (
    run_reduction_search, cancel_reduction_search,
)
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
plan_id, source_path, runs_path = sys.argv[1:]
source = read_search_evidence_bundle(Path(source_path))
ledger_factory = lambda: LocalAttemptLedger(Path(runs_path), create=False)
store_factory = lambda: LocalReductionCampaignStore(Path(runs_path), create=True)
calls, cancellations = [], []
class CancelAfterActualNative:
    def __init__(self, timeout):
        self.delegate = SubprocessReplayAdapter(timeout_seconds=timeout)
    def run(self, replay_input):
        result = self.delegate.run(replay_input)
        calls.append({'dataset_id': replay_input.dataset_id,
                      'processed_records': result.document['completeness']['processed_records']})
        if len(calls) == 1:
            cancellations.append(cancel_reduction_search(
                plan_id, source=source, split='development',
                ledger_factory=ledger_factory, store_factory=store_factory))
        return result
report = run_reduction_search(
    plan_id, source=source, split='development', ledger_factory=ledger_factory,
    store_factory=store_factory, engine_factory=CancelAfterActualNative)
assert len(calls) == len(cancellations) == 1
assert cancellations[0]['status'] == 'CANCEL_REQUESTED'
print(json.dumps({'controlled_cancellation_hook': 'after_actual_native_before_return_v1',
                  'actual_native_calls': calls, 'cancellations': cancellations,
                  'report': report}, sort_keys=True))
"""

_ALTER_ASSESSMENT = """
import json
from pathlib import Path
import sys
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore
runs, plan_id = Path(sys.argv[1]), sys.argv[2]
store = LocalReductionCampaignStore(runs, create=False)
raw = store.get_result(plan_id, 2)
document = json.loads(raw)
assert document['outcome'] == 'PRESERVED'
document['outcome'] = 'NOT_PRESERVED'
document['criterion_observation'].update(value='-2', truth=True)
altered = canonical(document)
target = runs / 'reduction-campaigns' / plan_id / 'results' / '0002.json'
assert target.read_bytes() == raw
target.write_bytes(altered)
print(json.dumps({'original_assessment_sha256': digest(raw),
                  'altered_assessment_sha256': digest(altered)}, sort_keys=True))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


@contextmanager
def _workspace(records: Path, report: Path) -> Iterator[Path]:
    with TemporaryDirectory(prefix="tickwitness-reduction-search-") as temporary:
        root = Path(temporary)
        failure = None
        try:
            yield root
        except BaseException as error:
            failure = error
            for accepted in (
                report,
                root / "reduction-search-smoke" / "report.json",
                records / "reduction-search-smoke" / "report.json",
            ):
                with suppress(OSError):
                    accepted.unlink(missing_ok=True)
            raise
        finally:
            if failure is not None:
                try:
                    shutil.copytree(root, records, dirs_exist_ok=True)
                    (records / "diagnostic-capture.json").write_bytes(
                        _canonical(
                            {
                                "kind": "reduction_search_workspace_diagnostics_v1",
                                "accepted": False,
                                "exception_type": type(failure).__name__,
                                "message": str(failure),
                            }
                        )
                    )
                except Exception as diagnostic_error:
                    print(
                        "Failed to preserve diagnostics: " + str(diagnostic_error), file=sys.stderr
                    )


def _request(steps: int) -> dict:
    return {
        "kind": "reduction_search_request_v1",
        "schema_version": 1,
        "witness_ordinal": 3,
        "focus_from_capture_seq": 4,
        "max_steps": steps,
        "max_wall_time_ms": 120000,
    }


def _point(through: int, delay: int) -> dict:
    return {"through_capture_seq": through, "additional_delay_ns": delay}


def _assert_original_records(root: Path, before: dict[str, str]) -> None:
    after = _tree(root)
    assert all(after.get(name) == digest for name, digest in before.items())


def _check_scope(scope: dict) -> None:
    assert scope["phase"] == "development"
    assert scope["authority"] == "bounded_reduction_search_v1"
    for key in (
        "source_claim_evaluated",
        "baseline_truth_evaluated",
        "original_predicate_domain_extended",
        "budget_owner_changed",
        "global_minimum_verified",
        "local_minimum_verified",
        "checkpoint_resume_verified",
        "confirmation_accessed",
    ):
        assert scope[key] is False


def _check_report(report: dict, frozen: dict, *, reason: str, count: int, exit_code: int) -> None:
    assert report["kind"] == "reduction_search_report_v1" and report["schema_version"] == 1
    assert report["plan_id"] == frozen["plan_id"]
    assert report["plan"] == frozen["plan"]
    assert _sha(_canonical(report["plan"])) == report["plan_id"]
    assert report["stop_reason"] == report["stop"]["reason"] == reason
    assert report["exit_code"] == exit_code
    assert report["status"] == ("COMPLETED" if reason == "neighborhood_checked" else "STOPPED")
    assert len(report["steps"]) == count
    assert [step["index"] for step in report["steps"]] == list(range(1, count + 1))
    assert report["plan"]["original_budget"] == {
        "max_attempts": 11,
        "max_events": 1000,
        "max_wall_seconds": 60,
    }
    _check_scope(report["plan"]["scope"])
    assert report["scope"] == report["plan"]["scope"]
    assert report["verification"] == _SEARCH_VERIFICATION
    assert report["plan"]["request"]["focus_from_capture_seq"] == 4
    assert report["plan"]["request"]["max_wall_time_ms"] == 120000


def _check_actual_step(step: dict, inspected: dict, result: dict, *, expected, slot: int) -> dict:
    through, delay, outcome = expected
    assessment = step["assessment"]
    assert step["point"] == _point(through, delay)
    assert step["execution_error"] is None
    assert assessment["kind"] == "reduction_preservation_assessment_v1"
    assert assessment["outcome"] == outcome
    assert assessment["scope"] == _PRESERVATION_SCOPE
    assert inspected["run_id"] == step["run_id"]
    assert inspected["attempt_id"] == step["attempt_id"]
    assert inspected["budget"]["attempt_index"] == slot
    assert inspected["budget"]["max_attempts"] == 11
    assert inspected["budget"]["max_wall_seconds"] == 60
    assert inspected["budget"]["max_events"] == 1000
    receipt, audit = inspected["receipt"], inspected["state_audit"]
    source = assessment["source"]
    bindings = receipt["intent"]["bindings"]
    assert source["bundle_id"] == bindings["source_bundle_id"]
    assert source["report_id"] == bindings["source_report_id"]
    assert source["finding_protocol_id"] == bindings["source_finding_protocol_id"]
    assert source["witness_run_id"] == bindings["source_run_id"]
    assert source["witness_ordinal"] == 3
    assert source["protocol_id"] == receipt["protocol_id"]
    assert source["claim_revision_id"] == receipt["claim_revision_id"]
    assert _sha(_canonical(receipt)) == step["run_id"]
    assert receipt["bindings"]["replay_result_sha256"] == _sha(_canonical(result))
    assert receipt["bindings"]["state_audit_sha256"] == _sha(_canonical(audit))
    candidate = assessment["candidate"]
    assert candidate["run_id"] == step["run_id"]
    assert candidate["attempt_id"] == step["attempt_id"]
    assert candidate["intent_id"] == inspected["intent_id"]
    for name in ("replay_result_sha256", "state_audit_sha256"):
        assert candidate[name] == receipt["bindings"][name]
    assert candidate["preparation_id"] == inspected["preparation"]["preparation_id"]
    assert candidate["recipe_id"] == inspected["preparation"]["recipe_id"]
    assert candidate["prefix_context_id"] == result["dataset_id"]
    assert candidate["prefix_context_id"] == inspected["preparation"]["prefix_context_id"]
    assert audit["flags"] == _STATE_FLAGS
    assert audit["state_boundary"] == "after_native_run_before_dispose_v1"
    assert audit["coverage"]["retained_event_count"] == through
    assert audit["coverage"]["warmup_event_count"] == 3
    assert result["completeness"]["input_records"] == through
    assert result["completeness"]["processed_records"] == through
    assert [row["source_ref"]["capture_seq"] for row in result["input_trace"]] == list(
        range(1, through + 1)
    )
    base = 1_700_000_000_000_000_000
    offsets = (
        0,
        500_000_000,
        1_000_000_000,
        1_000_000_001,
        2_000_000_000,
        2_000_000_001,
        3_000_000_000,
    )
    times = [
        base + offset + (delay if index >= 3 else 0)
        for index, offset in enumerate(offsets[:through])
    ]
    assert [row["native_time_ns"] for row in result["input_trace"]] == times
    assert [row["fields"]["receive_time_ns"] for row in result["input_trace"]] == times
    initial, terminal = audit["initial_account"], audit["terminal_state"]
    assert initial == result["account_trace"][0]
    assert initial["fields"]["cash_total"] == "10000"
    assert initial["fields"]["net_position_lots"] == 0
    assert initial["fields"]["orders"] == []
    assert terminal["account"] == result["account_trace"][-1]
    assert terminal["open_orders"] == result["completeness"]["open_orders"]
    assert terminal["pending_commands"] == result["completeness"]["pending_commands"]
    observation = assessment["criterion_observation"]
    assert {key: observation[key] for key in ("metric", "unit", "comparator", "threshold")} == {
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "comparator": "lt",
        "threshold": "-1.5",
    }
    if outcome == "NOT_EVALUABLE":
        assert observation["eligible"] is False
        assert observation["truth"] is observation["value"] is None
        assert observation["reason"] == "execution_incomplete"
        assert result["execution_status"] == "incomplete"
        assert audit["replay_evaluation"]["valuation_status"] == "not_eligible"
        assert terminal["stop_reason"] == "pending_commands_at_data_end"
        assert len(terminal["open_orders"]) == len(terminal["pending_commands"]) == 1
        assert terminal["open_orders"][0]["status"] == "PENDING_CANCEL"
        assert terminal["pending_commands"][0]["command_id"] == "command-1"
        assert terminal["account"]["fields"]["orders"][0]["remaining_quantity_lots"] == 1
        lots = 1
    else:
        assert observation["eligible"] is True and observation["reason"] is None
        assert observation["truth"] is (outcome == "NOT_PRESERVED")
        assert observation["value"] == ("-1" if outcome == "PRESERVED" else "-2")
        assert result["execution_status"] == "completed"
        assert terminal["stop_reason"] == "input_exhausted"
        assert terminal["open_orders"] == terminal["pending_commands"] == []
        lots = 1 if outcome == "PRESERVED" else 2
        orders = terminal["account"]["fields"]["orders"]
        assert len(orders) == 1
        assert orders[0]["status"] == ("CANCELED" if outcome == "PRESERVED" else "FILLED")
        assert orders[0]["remaining_quantity_lots"] == (1 if outcome == "PRESERVED" else 0)
        if outcome == "PRESERVED":
            acknowledgements = [
                row for row in result["order_trace"] if row["kind"] == "OrderCanceled"
            ]
            assert len(acknowledgements) == 1
            assert acknowledgements[0]["source_ref"]["capture_seq"] == 4
            assert acknowledgements[0]["native_time_ns"] == base + 3_000_000_001
            assert acknowledgements[0]["fields"]["pending_command_ids"] == []
        else:
            filled = [
                (index, row)
                for index, row in enumerate(result["order_trace"])
                if row["kind"] == "OrderFilled" and row["source_ref"]["capture_seq"] == 5
            ]
            rejected = [
                (index, row)
                for index, row in enumerate(result["order_trace"])
                if row["kind"] == "OrderCancelRejected"
            ]
            assert len(filled) == len(rejected) == 1
            assert filled[0][0] < rejected[0][0]
            for _, row in (filled[0], rejected[0]):
                assert row["source_ref"]["capture_seq"] == 5
                assert row["native_time_ns"] == base + 3_000_000_000
                assert row["fields"]["status"] == "FILLED"
            assert filled[0][1]["fields"]["pending_command_ids"] == ["command-1"]
            assert rejected[0][1]["fields"]["pending_command_ids"] == []
    assert [row["source_ref"]["capture_seq"] for row in result["fill_trace"]] == (
        [3] if lots == 1 else [3, 5]
    )
    assert [row["fields"]["quantity_lots"] for row in result["fill_trace"]] == [1] * lots
    assert [row["fields"]["commission"] for row in result["fill_trace"]] == ["1"] * lots
    assert terminal["account"]["fields"]["net_position_lots"] == lots
    assert terminal["account"]["fields"]["observed_commission"] == str(lots)
    assert terminal["account"]["fields"]["observed_fill_lots"] == lots
    assert terminal["account"]["fields"]["cash_total"] == str(10000 - lots)
    return {"step": step, "inspection": inspected, "result": result}


def _same_report(actual: dict, expected: dict) -> None:
    for name in (
        "plan_id",
        "plan",
        "source",
        "steps",
        "best",
        "stop",
        "status",
        "stop_reason",
        "exit_code",
        "counts",
        "cancellation",
    ):
        assert actual[name] == expected[name], name


def _native_lifecycle(
    run, invoke, helper, native: str, verifier: str, examples: Path, root: Path, inputs: Path
):
    for name in (
        "replay-partials.jsonl",
        "replay-confirmation.jsonl",
        "stress-assumption-request.json",
        "search-execution-grid-request.json",
        "search-finding-request.json",
    ):
        shutil.copyfile(examples / name, inputs / name)
    experiment = json.loads((examples / "stress-experiment-request.json").read_bytes())
    experiment["claim"].update(
        title="Synthetic eleven-slot local reduction qualification",
        hypothesis="The declared synthetic marked PnL is below minus 1.5 USD.",
        comparator="lt",
        threshold="-1.5",
    )
    experiment["budget"]["max_attempts"] = 11
    (inputs / "live-experiment.json").write_bytes(_canonical(experiment))
    (inputs / "source-search-budget.json").write_bytes(
        _canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": 2,
                "max_wall_time_ms": 120000,
                "max_storage_bytes": 512 * 1024 * 1024,
            }
        )
    )
    data, registry, plans, runs, findings = (
        root / name for name in ("data", "registry", "plans", "live-runs", "findings")
    )
    dataset_ids = [
        run("import-events", name, "--input-root", str(inputs), "--store", str(data))["dataset_id"]
        for name in ("replay-partials.jsonl", "replay-confirmation.jsonl")
    ]
    frozen = run(
        "freeze-experiment",
        "live-experiment.json",
        "--input-root",
        str(inputs),
        "--development-dataset",
        dataset_ids[0],
        "--confirmation-dataset",
        dataset_ids[1],
        "--store",
        str(data),
        "--registry",
        str(registry),
    )
    search = run(
        "freeze-search-plan",
        frozen["protocol_id"],
        "stress-assumption-request.json",
        "search-execution-grid-request.json",
        "--input-root",
        str(inputs),
        "--store",
        str(data),
        "--registry",
        str(registry),
        "--plans",
        str(plans),
    )
    authority = run(
        "freeze-search-finding-protocol",
        search["plan_id"],
        "search-finding-request.json",
        "--input-root",
        str(inputs),
        "--plans",
        str(plans),
        "--finding-registry",
        str(findings),
    )
    baseline = run(
        "replay-protocol",
        frozen["protocol_id"],
        "--store",
        str(data),
        "--registry",
        str(registry),
        "--runs",
        str(runs),
        producer=True,
    )
    common = (
        "--plans",
        str(plans),
        "--store",
        str(data),
        "--registry",
        str(registry),
        "--runs",
        str(runs),
    )
    campaign = run(
        "run-bounded-search-plan",
        search["plan_id"],
        "source-search-budget.json",
        "--input-root",
        str(inputs),
        *common,
        producer=True,
    )
    finding = run(
        "evaluate-search-findings",
        authority["protocol_id"],
        *common,
        "--finding-registry",
        str(findings),
    )
    source_finding = finding["report"]
    assert source_finding["outcome"] == "COUNTEREXAMPLE_FOUND"
    assert source_finding["planned_predicate_truth"] is False
    assert [row["ordinal"] for row in source_finding["witnesses"]] == [3]
    assert source_finding["coverage"]["audited_ordinals"] == [1, 3]
    observed = source_finding["candidate_assessments"]
    assert [
        (row["ordinal"], row["metric_observation"]["value"], row["truth"]) for row in observed
    ] == [(1, "-2", True), (3, "-1", False)]
    source = run(
        "export-search-evidence",
        authority["protocol_id"],
        "--expected-report-id",
        finding["report_id"],
        *common,
        "--finding-registry",
        str(findings),
        "--output",
        str(inputs / "live-source"),
    )
    source_path = inputs / "live-source"
    source_before, original_records = _tree(source_path), _tree(runs)
    before = helper(_LEDGER_VIEW, str(source_path), str(runs), source["bundle_id"])
    assert before["protocol_id"] == frozen["protocol_id"]
    assert before["budget"] == {"max_attempts": 11, "max_events": 1000, "max_wall_seconds": 60}
    assert [row["attempt_index"] for row in before["slots"]] == [1, 2, 3]
    assert before["slots"][0]["outcome_id"] == baseline["run_id"]
    assert [row["outcome_kind"] for row in before["slots"]] == [
        "research_run_receipt_v1",
        "scenario_run_receipt_v1",
        "scenario_run_receipt_v1",
    ]

    def freeze(name: str, max_steps: int) -> dict:
        (inputs / (name + ".json")).write_bytes(_canonical(_request(max_steps)))
        plan = run(
            "freeze-reduction-search",
            "live-source",
            name + ".json",
            "--input-root",
            str(inputs),
            "--expected-bundle-id",
            source["bundle_id"],
            "--expected-report-id",
            source["report_id"],
            "--runs",
            str(runs),
            guard="control",
        )
        assert _sha(_canonical(plan["plan"])) == plan["plan_id"]
        assert plan["plan"]["request"] == _request(max_steps)
        assert plan["plan"]["initial"] == _point(7, 2_000_000_000)
        assert plan["plan"]["minimum_through_capture_seq"] == 4
        assert plan["plan"]["source_capture_seqs"] == list(range(1, 8))
        assert plan["plan"]["policy"]["operator_order"] == ["halve_delay", "trim_last_event"]
        for name in (
            "attempt_reserved",
            "native_replayed",
            "reduced_predicate_evaluated",
            "witness_preservation_verified",
        ):
            assert plan[name] is False
        _check_scope(plan["plan"]["scope"])
        return plan

    def common_reduction(plan: dict) -> tuple[str, ...]:
        return (
            plan["plan_id"],
            "--source-evidence",
            "live-source",
            "--input-root",
            str(inputs),
            "--runs",
            str(runs),
        )

    def inspect(plan: dict) -> dict:
        tree_before = _tree(runs)
        report = run("inspect-reduction-search", *common_reduction(plan), guard="readonly")
        assert _tree(runs) == tree_before
        return report

    def audit_steps(report: dict, *, first_slot: int, expectations: tuple) -> list[dict]:
        cases = []
        tree_before = _tree(runs)
        for step, expected in zip(report["steps"], expectations, strict=True):
            inspected = run(
                "inspect-reduction-run",
                step["run_id"],
                "--source-evidence",
                "live-source",
                "--input-root",
                str(inputs),
                "--runs",
                str(runs),
                guard="readonly",
            )
            result = helper(
                _READ_ARTIFACT, str(runs), inspected["receipt"]["bindings"]["replay_result_sha256"]
            )
            cases.append(
                _check_actual_step(
                    step,
                    inspected,
                    result,
                    expected=expected,
                    slot=first_slot + len(cases),
                )
            )
            assert step["assessment"]["source"]["predicate_id"] == source_finding["predicate_id"]
        assert _tree(runs) == tree_before
        return cases

    before_start = freeze("cancel-before-start", 9)
    cancellation = run("cancel-reduction-search", *common_reduction(before_start), guard="control")
    assert cancellation["status"] == "CANCEL_REQUESTED"
    assert cancellation["attempt_reserved"] is cancellation["native_replayed"] is False
    pre_cancelled = run(
        "run-reduction-search",
        *common_reduction(before_start),
        guard="control",
    )
    _check_report(pre_cancelled, before_start, reason="cancelled", count=0, exit_code=0)
    assert pre_cancelled["cancellation"]["effective"] is True
    assert pre_cancelled["best"]["origin"] == "SOURCE_WITNESS"
    assert pre_cancelled["best"]["assessment_id"] is None
    _same_report(inspect(before_start), pre_cancelled)
    after_pre_cancel = helper(_LEDGER_VIEW, str(source_path), str(runs), source["bundle_id"])
    assert after_pre_cancel == before

    after_native = freeze("cancel-after-native", 8)
    hook = invoke(
        native,
        ["-c", _CANCEL_AFTER_NATIVE],
        (after_native["plan_id"], str(source_path), str(runs)),
    )
    cancelled = hook["report"]
    assert hook["controlled_cancellation_hook"] == "after_actual_native_before_return_v1"
    assert len(hook["actual_native_calls"]) == 1
    assert hook["actual_native_calls"][0]["processed_records"] == 7
    _check_report(cancelled, after_native, reason="cancelled", count=1, exit_code=0)
    assert cancelled["cancellation"]["effective"] is True
    assert cancelled["best"]["origin"] == "SOURCE_WITNESS"
    assert cancelled["best"]["point"] == _point(7, 2_000_000_000)
    assert cancelled["best"]["run_id"] == source_finding["witnesses"][0]["run_id"]
    assert cancelled["best"]["assessment_id"] is None
    assert cancelled["counts"] == {
        "dispatched": 1,
        "assessed": 1,
        "preserved": 0,
        "not_preserved": 1,
        "not_evaluable": 0,
        "failed": 0,
        "unfinalized": 0,
    }
    cancelled_cases = audit_steps(cancelled, first_slot=4, expectations=(_POINTS[0],))
    _same_report(inspect(after_native), cancelled)

    main_plan = freeze("main-search", 7)
    main = run("run-reduction-search", *common_reduction(main_plan), producer=True)
    _check_report(main, main_plan, reason="neighborhood_checked", count=7, exit_code=0)
    assert main["counts"] == {
        "dispatched": 7,
        "assessed": 7,
        "preserved": 3,
        "not_preserved": 3,
        "not_evaluable": 1,
        "failed": 0,
        "unfinalized": 0,
    }
    main_cases = audit_steps(main, first_slot=5, expectations=_POINTS)
    assert main["best"]["origin"] == "REDUCTION_RUN"
    assert main["best"]["point"] == _point(4, 2_000_000_000)
    assert main["best"]["cost"] == [4, 2_000_000_000]
    assert main["best"]["run_id"] == main["steps"][5]["run_id"]
    assert main["best"]["assessment_id"] == _sha(_canonical(main["steps"][5]["assessment"]))
    assert main["cancellation"]["request"] is None
    assert main["cancellation"]["effective"] is False
    _same_report(inspect(main_plan), main)
    unchanged = _tree(runs)
    for plan, saved in (
        (before_start, pre_cancelled),
        (after_native, cancelled),
        (main_plan, main),
    ):
        repeated = run("run-reduction-search", *common_reduction(plan), guard="readonly")
        _same_report(repeated, saved)
    assert _tree(runs) == unchanged
    re_frozen = freeze("main-search", 7)
    assert re_frozen["plan_id"] == main_plan["plan_id"]
    assert _tree(runs) == unchanged
    terminal_cancel = run(
        "cancel-reduction-search",
        *common_reduction(main_plan),
        guard="control",
    )
    assert terminal_cancel["status"] == "ALREADY_TERMINAL"
    assert _tree(runs) == unchanged

    after = helper(_LEDGER_VIEW, str(source_path), str(runs), source["bundle_id"])
    assert [row["attempt_index"] for row in after["slots"]] == list(range(1, 12))
    assert after["slots"][:3] == before["slots"]
    assert all(row["outcome_kind"] == "reduction_run_receipt_v1" for row in after["slots"][3:])
    _assert_original_records(runs, original_records)
    exhaustion_plan = freeze("exhausted-search", 10)
    before_exhaustion = _tree(runs)
    exhausted = run(
        "run-reduction-search",
        *common_reduction(exhaustion_plan),
        expected=8,
        structured=True,
        guard="exhaustion",
    )
    _check_report(
        exhausted,
        exhaustion_plan,
        reason="original_attempt_budget_exhausted",
        count=1,
        exit_code=8,
    )
    assert exhausted["steps"][0]["attempt_id"] is None
    assert exhausted["steps"][0]["run_id"] is None
    assert exhausted["steps"][0]["assessment"] is None
    assert exhausted["best"]["origin"] == "SOURCE_WITNESS"
    _same_report(inspect(exhaustion_plan), exhausted)
    _same_report(
        run(
            "run-reduction-search",
            *common_reduction(exhaustion_plan),
            guard="readonly",
            expected=8,
            structured=True,
        ),
        exhausted,
    )
    _assert_original_records(runs, before_exhaustion)
    assert helper(_LEDGER_VIEW, str(source_path), str(runs), source["bundle_id"]) == after
    altered = root / "altered-assessment-runs"
    shutil.copytree(runs, altered)
    attack = invoke(
        verifier,
        ["-c", _ALTER_ASSESSMENT],
        (str(altered), main_plan["plan_id"]),
    )
    attack_before, original_before_attack = _tree(altered), _tree(runs)
    rejected = run(
        "inspect-reduction-search",
        main_plan["plan_id"],
        "--source-evidence",
        "live-source",
        "--input-root",
        str(inputs),
        "--runs",
        str(altered),
        guard="readonly",
        expected=2,
    )
    assert rejected["error"]["code"] == "invalid_research_evidence"
    assert _tree(altered) == attack_before and _tree(runs) == original_before_attack
    assert _tree(source_path) == source_before
    return {
        "frozen": frozen,
        "search_plan": search,
        "source_campaign": campaign,
        "baseline": baseline,
        "source_finding": finding,
        "source": source,
        "before": before,
        "after": after,
        "cancel_before_start": {
            "plan": before_start,
            "request": cancellation,
            "report": pre_cancelled,
        },
        "cancel_after_actual_native": {
            "plan": after_native,
            "hook": hook,
            "cases": cancelled_cases,
        },
        "main": {"frozen": main_plan, "report": main, "cases": main_cases},
        "original_budget_exhaustion": {"frozen": exhaustion_plan, "report": exhausted},
        "altered_assessment_rejected": {"mutation": attack, "error": rejected},
        "source_bundle_unchanged": True,
        "original_records_unchanged": True,
        "cooperative_cancellation_only": True,
        "existing_runs_inspected_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "verifier-python", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--core-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.records_dir.exists():
        raise FileExistsError("Records destination already exists")
    native, verifier = str(arguments.python.absolute()), str(arguments.verifier_python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    committed_before = _tree(examples / "alpha")
    with _workspace(arguments.records_dir, arguments.report) as root:
        inputs, cwd, transcripts = (
            root / name for name in ("input-root", "unrelated-cwd", "transcripts")
        )
        for path in (inputs, cwd, transcripts):
            path.mkdir()
        calls = []

        def invoke(
            executable: str,
            entry: list[str],
            command: tuple[str, ...],
            *,
            expected: int = 0,
            structured: bool = False,
        ) -> dict:
            completed = subprocess.run(
                [executable, "-I", *entry, *command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=240,
            )
            record = {
                "executable": executable,
                "entry": entry,
                "command": list(command),
                "expected_exit_code": expected,
                "exit_code": completed.returncode,
                "structured_nonzero_report": structured,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            calls.append(record)
            (transcripts / f"{len(calls):04d}.json").write_bytes(_canonical(record))
            stdout_expected = expected == 0 or structured
            payload = completed.stdout if stdout_expected else completed.stderr
            unexpected = completed.stderr if stdout_expected else completed.stdout
            if completed.returncode != expected or unexpected:
                raise RuntimeError(
                    f"Installed reducer exited {completed.returncode}, expected {expected}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            return json.loads(payload)

        def run(
            *command: str,
            expected: int = 0,
            producer: bool = False,
            guard: str | None = None,
            structured: bool = False,
        ) -> dict:
            if guard is not None:
                entry = ["-c", _GUARD + "\nraise SystemExit(main(sys.argv[1:]))\n"]
                command = (guard, *command)
            else:
                entry = ["-m", "tickwitness"]
            return invoke(
                native if producer else verifier,
                entry,
                command,
                expected=expected,
                structured=structured,
            )

        def helper(code: str, *command: str) -> dict:
            return invoke(verifier, ["-c", _GUARD + code], ("readonly", *command))

        runtime_query = """
import json
import sys
from importlib import metadata
try:
    native = metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    native = None
print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix,
                  'base_prefix': sys.base_prefix, 'native_distribution': native,
                  'project_version': metadata.version('tickwitness')}, sort_keys=True))
"""
        identities = {}
        for name, requested in (
            ("producer", arguments.python),
            ("verifier", arguments.verifier_python),
        ):
            runtime = invoke(str(requested.absolute()), ["-c", runtime_query], ())
            expected_prefix = str(requested.absolute().parent.parent.resolve())
            assert str(Path(runtime["prefix"]).resolve()) == expected_prefix
            assert Path(runtime["prefix"]).resolve() != Path(runtime["base_prefix"]).resolve()
            assert runtime["project_version"] == "0.2.0.dev0"
            identities[name] = {
                "requested_executable": str(requested.absolute()),
                "requested_venv_prefix_resolved": expected_prefix,
                "runtime": runtime,
            }
        assert identities["verifier"]["runtime"]["native_distribution"] is None
        assert identities["producer"]["runtime"]["native_distribution"] == (
            None if arguments.core_only else "1.231.0"
        )
        (root / "interpreter-identities.json").write_bytes(_canonical(identities))
        pre_io = helper(_PRE_IO)
        assert pre_io == {"confirmation_operations_rejected_before_io": 4}
        rejections = []
        for command in (
            "freeze-reduction-search",
            "run-reduction-search",
            "inspect-reduction-search",
            "cancel-reduction-search",
        ):
            if command == "freeze-reduction-search":
                positional = (
                    "missing-source",
                    "missing-request.json",
                    "--expected-bundle-id",
                    "invalid",
                    "--expected-report-id",
                    "invalid",
                )
            else:
                positional = ("invalid", "--source-evidence", "missing-source")
            rejected = run(
                command,
                *positional,
                "--input-root",
                str(root / "missing-input-root"),
                "--runs",
                str(root / "missing-runs"),
                "--split",
                "confirmation",
                expected=5,
                guard="readonly",
            )
            assert rejected["error"]["code"] == "confirmation_access_denied"
            rejections.append({"name": command + "-confirmation", "error": rejected})
        assert not (root / "missing-input-root").exists()
        assert not (root / "missing-runs").exists()
        shutil.copytree(examples / "alpha" / "counterexample", inputs / "old-exhausted-source")
        old_source_before = _tree(inputs / "old-exhausted-source")
        (inputs / "old-search.json").write_bytes(_canonical(_request(7)))
        empty = root / "empty-live-ledger"
        invoke(
            verifier,
            [
                "-c",
                (
                    "import json,sys; from pathlib import Path; "
                    "from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger; "
                    "LocalAttemptLedger(Path(sys.argv[1])); "
                    "print(json.dumps({'created_empty':True}))"
                ),
            ],
            (str(empty),),
        )
        empty_before = _tree(empty)
        for name, ledger, expected, code in (
            (
                "old-source-missing-ledger",
                root / "never-created-ledger",
                4,
                "research_evidence_not_found",
            ),
            ("old-source-empty-ledger", empty, 2, "invalid_research_evidence"),
        ):
            rejected = run(
                "freeze-reduction-search",
                "old-exhausted-source",
                "old-search.json",
                "--input-root",
                str(inputs),
                "--expected-bundle-id",
                _GOLDEN["bundle_id"],
                "--expected-report-id",
                _GOLDEN["report_id"],
                "--runs",
                str(ledger),
                expected=expected,
                guard="control",
            )
            assert rejected["error"]["code"] == code
            rejections.append({"name": name, "error": rejected})
        assert empty.is_dir() and _tree(empty) == empty_before
        assert not (empty / "reduction-campaigns").exists()
        assert not (root / "never-created-ledger").exists()
        lifecycle = None
        if not arguments.core_only:
            lifecycle = _native_lifecycle(
                run,
                invoke,
                helper,
                native,
                verifier,
                examples,
                root,
                inputs,
            )
        assert _tree(inputs / "old-exhausted-source") == old_source_before
        assert _tree(examples / "alpha") == committed_before
        report = {
            "kind": "installed_reduction_search_acceptance_v1",
            "accepted": True,
            "native_execution": not arguments.core_only,
            "interpreter_identities": identities,
            "pre_io": pre_io,
            "core_rejections": rejections,
            "committed_exhausted_source_pins": _GOLDEN,
            "old_source_and_empty_ledger_unchanged": True,
            "lifecycle": lifecycle,
            "readonly_inspection_guard": {
                "core_only": True,
                "native_and_workers_forbidden": True,
                "reservation_and_publication_forbidden": True,
                "old_research_stores_forbidden": True,
                "network_and_sqlite_forbidden": True,
            },
            "cancellation_scope": "between_candidates_after_current_bounded_attempt_v1",
            "elapsed_limit_scope": "between_candidate_admission_not_hard_total_deadline_v1",
            "hard_total_wall_deadline_verified": False,
            "hard_storage_quota_verified": False,
            "reducer_evaluation_scope": {
                "source_claim_evaluated": False,
                "baseline_truth_evaluated": False,
                "original_predicate_domain_extended": False,
            },
            "source_bootstrap_baseline_evaluation_included": not arguments.core_only,
            "new_baseline_flip_issued": False,
            "local_minimum_verified": False,
            "global_minimum_verified": False,
            "checkpoint_resume_verified": False,
            "external_attempts": 0,
            "external_attempt_gate": "PENDING",
        }
        inner_report = root / "reduction-search-smoke" / "report.json"
        inner_report.parent.mkdir()
        inner_report.write_bytes(_canonical(report))
        shutil.copytree(root, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(_tree(arguments.records_dir))
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
