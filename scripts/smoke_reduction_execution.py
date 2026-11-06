#!/usr/bin/env python3
"""Qualify installed full-origin prefix runs against one original live budget."""

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
_FLAGS = {
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
_SCOPE = {
    "phase": "development",
    "authority": "reduction_prefix_state_audit_only_v1",
    "source_claim_authority_extended": False,
    "budget_owner_changed": False,
}
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
    raise AssertionError('Reduction inspection requires an installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Reduction verification cannot import native')
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
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args, **kwargs):
    raise AssertionError('Reduction inspection cannot execute, write, reserve or use network')
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
                   LocalSearchCampaignStore, LocalSearchFindingRegistry,
                   LocalSearchPlanRegistry):
    repository.__init__ = forbidden
for name in ('bind_intent', 'publish', 'reserve_with_nonce'):
    setattr(LocalAttemptLedger, name, forbidden)
ledger_init = LocalAttemptLedger.__init__
def readonly_ledger_init(self, *args, **kwargs):
    if kwargs.get('create', True) is not False:
        forbidden()
    return ledger_init(self, *args, **kwargs)
LocalAttemptLedger.__init__ = readonly_ledger_init
if mode != 'exhaustion':
    LocalAttemptLedger.reserve = forbidden
"""
_PRE_IO = """
from tickwitness.application.reduction_execution import (
    run_reduction_input, inspect_reduction_run, inspect_reduction_attempt,
)
from tickwitness.application.research import ConfirmationAccessDenied
class Unreadable:
    def __getattribute__(self, name):
        raise AssertionError('Confirmation operation accessed source/preparation: ' + name)
for operation in ('run', 'inspect', 'recover'):
    try:
        if operation == 'run':
            run_reduction_input(Unreadable(), Unreadable(),
                                expected_preparation_id='invalid', split='confirmation',
                                ledger_factory=forbidden, engine_factory=forbidden)
        elif operation == 'inspect':
            inspect_reduction_run('invalid', source=Unreadable(), split='confirmation',
                                  ledger_factory=forbidden)
        else:
            inspect_reduction_attempt('invalid', Unreadable(), Unreadable(),
                                      expected_preparation_id='invalid',
                                      expected_bundle_id='invalid',
                                      expected_report_id='invalid',split='confirmation',
                                      ledger_factory=forbidden)
    except ConfirmationAccessDenied:
        pass
    else:
        raise AssertionError('Confirmation access returned a result')
print(json.dumps({'confirmation_operations_rejected_before_package_and_factory_io': 3}))
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
_READ_OUTCOME = """
ledger = LocalAttemptLedger(Path(sys.argv[1]), create=False)
raw = ledger.get_outcome(sys.argv[2])
assert raw is not None
print(raw.decode('utf-8'))
"""
_ACK_LOSS = """
import hashlib,json,sys
from pathlib import Path
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
trace=Path(sys.argv.pop(1))
native_run=SubprocessReplayAdapter.run
publish=LocalAttemptLedger.publish
def record(value):
    with trace.open('a') as stream:
        stream.write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n')
def counted_run(self,replay_input):
    record({'kind':'native_adapter_run_started_v1','dataset_id':replay_input.dataset_id})
    return native_run(self,replay_input)
def lost_ack(self,reservation,raw,*,artifacts=()):
    committed=publish(self,reservation,raw,artifacts=artifacts)
    record({'kind':'actual_research_outcome_committed_before_injected_ack_loss_v1',
            'attempt_id':reservation.attempt_id,'outcome_id':committed,
            'outcome_sha256':hashlib.sha256(raw).hexdigest()})
    raise OSError('Qualification injected acknowledgement loss after actual outcome commit')
SubprocessReplayAdapter.run=counted_run
LocalAttemptLedger.publish=lost_ack
raise SystemExit(main(sys.argv[1:]))
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
def _preserved_workspace(records: Path, report: Path) -> Iterator[Path]:
    with TemporaryDirectory(prefix="tickwitness-reduction-execution-") as temporary:
        root = Path(temporary)
        failure = None
        try:
            yield root
        except BaseException as error:
            failure = error
            for accepted_report in (
                report,
                root / "reduction-execution-smoke" / "report.json",
                records / "reduction-execution-smoke" / "report.json",
            ):
                with suppress(OSError):
                    accepted_report.unlink(missing_ok=True)
            raise
        finally:
            if not records.exists():
                try:
                    shutil.copytree(root, records)
                    (records / "diagnostic-capture.json").write_bytes(
                        _canonical(
                            {
                                "kind": "reduction_execution_workspace_diagnostics_v1",
                                "accepted": False,
                                "exception_type": (
                                    type(failure).__name__ if failure is not None else None
                                ),
                                "message": str(failure) if failure is not None else None,
                            }
                        )
                    )
                except Exception as diagnostic_error:
                    if failure is None:
                        raise
                    print(
                        "Failed to preserve reduction execution diagnostics: "
                        + str(diagnostic_error),
                        file=sys.stderr,
                    )


def _request(focus: int, through: int) -> dict:
    return {
        "kind": "reduction_request_v1",
        "schema_version": 1,
        "witness_ordinal": 3,
        "focus_from_capture_seq": focus,
        "through_capture_seq": through,
        "additional_delay_ns": 1_000_000_000,
    }


def _check_inspection(
    inspected: dict,
    submitted: dict,
    prepared: dict,
    *,
    slot: int,
    focus: int,
    through: int,
    pending: bool,
    result: dict,
) -> None:
    assert inspected["run_id"] == submitted["run_id"]
    assert inspected["attempt_id"] == submitted["attempt_id"]
    assert inspected["intent_id"] == submitted["intent_id"]
    assert inspected["preparation"]["preparation_id"] == prepared["preparation_id"]
    assert inspected["budget"]["attempt_index"] == slot
    assert inspected["budget"]["max_attempts"] == 5
    assert inspected["budget"]["max_wall_seconds"] == 60
    assert inspected["budget"]["max_events"] == 1000
    receipt = inspected["receipt"]
    assert receipt["kind"] == "reduction_run_receipt_v1" and receipt["schema_version"] == 1
    assert _sha(_canonical(receipt)) == inspected["run_id"]
    assert receipt["attempt"]["attempt_index"] == slot
    assert receipt["attempt"]["protocol_id"] == inspected["protocol_id"]
    assert receipt["scope"] == _SCOPE
    intent = receipt["intent"]
    assert intent["kind"] == "reduction_execution_intent_v1"
    assert _sha(_canonical(intent)) == submitted["intent_id"]
    assert intent["protocol_id"] == inspected["protocol_id"]
    assert intent["scope"] == _SCOPE
    assert intent["state_boundary"] == "after_native_run_before_dispose_v1"
    assert intent["flags"] == dict.fromkeys(_FLAGS, False)
    assert intent["bindings"]["preparation_manifest_sha256"] == prepared["preparation_id"]
    assert intent["bindings"]["preparation_id"] == prepared["preparation_id"]
    assert intent["bindings"]["prefix_context_id"] == prepared["prefix_context_id"]
    audit = inspected["state_audit"]
    assert audit == submitted["state_audit"]
    assert audit["kind"] == "reduction_state_audit_v1" and audit["schema_version"] == 1
    assert audit["audit_status"] == "verified" and audit["scope"] == _SCOPE
    assert audit["state_boundary"] == "after_native_run_before_dispose_v1"
    assert audit["flags"] == _FLAGS
    assert _sha(_canonical(audit)) == receipt["bindings"]["state_audit_sha256"]
    assert audit["intent_id"] == submitted["intent_id"]
    assert audit["bindings"]["replay_result_sha256"] == _sha(_canonical(result))
    assert receipt["bindings"]["replay_result_sha256"] == _sha(_canonical(result))
    assert audit["coverage"] == {
        "source_event_count": 7,
        "retained_event_count": through,
        "processed_records": through,
        "warmup_event_count": focus - 1,
        "origin_ref": {"line": 1, "capture_seq": 1, "event_type": "snapshot"},
        "focus_ref": {
            "line": focus,
            "capture_seq": focus,
            "event_type": "delta" if focus == 4 else "trade",
        },
        "through_ref": {"line": through, "capture_seq": through, "event_type": "delta"},
    }
    assert [row["source_ref"]["capture_seq"] for row in result["input_trace"]] == list(
        range(1, through + 1)
    )
    expected_times = [
        1_700_000_000_000_000_000 + offset
        for offset in (0, 500_000_000, 1_000_000_000, 2_000_000_001, 3_000_000_000, 3_000_000_001)
    ][:through]
    assert [row["native_time_ns"] for row in result["input_trace"]] == expected_times
    assert [row["fields"]["receive_time_ns"] for row in result["input_trace"]] == expected_times
    assert result["dataset_id"] == prepared["prefix_context_id"]
    assert result["data_sha256"] == audit["bindings"]["normalized_sha256"]
    initial, terminal = audit["initial_account"], audit["terminal_state"]
    assert initial == result["account_trace"][0]
    assert initial["kind"] == "initial_account_snapshot" and initial["source_ref"] is None
    assert initial["fields"]["cash_total"] == "10000"
    assert initial["fields"]["net_position_lots"] == 0
    assert terminal["account"] == result["account_trace"][-1]
    assert terminal["account"]["kind"] == "final_account_snapshot"
    assert terminal["open_orders"] == result["completeness"]["open_orders"]
    assert terminal["pending_commands"] == result["completeness"]["pending_commands"]
    assert terminal["stop_reason"] == result["completeness"]["stop_reason"]
    expected_lots = 1 if pending else 2
    assert terminal["account"]["fields"]["net_position_lots"] == expected_lots
    assert terminal["account"]["fields"]["observed_commission"] == str(expected_lots)
    assert terminal["account"]["fields"]["observed_fill_lots"] == expected_lots
    assert audit["cash_lock_verification"] == "nonnegative_and_total_equals_free_plus_locked_v1"
    assert [row["source_ref"]["capture_seq"] for row in result["fill_trace"]] == (
        [3] if pending else [3, 5]
    )
    assert [row["fields"]["quantity_lots"] for row in result["fill_trace"]] == [1] * expected_lots
    assert [row["fields"]["commission"] for row in result["fill_trace"]] == ["1"] * expected_lots
    assert [row["native_time_ns"] for row in result["fill_trace"]] == (
        [expected_times[2]] if pending else [expected_times[2], expected_times[4]]
    )
    assert audit["replay_evaluation"]["ledger"]["actual_commission"] == str(expected_lots)
    assert audit["replay_evaluation"]["ledger"]["filled_quantity_lots"] == expected_lots
    if pending:
        assert submitted["execution_status"] == receipt["execution_status"] == "incomplete"
        assert audit["execution_status"] == result["execution_status"] == "incomplete"
        assert terminal["stop_reason"] == "pending_commands_at_data_end"
        assert len(terminal["open_orders"]) == len(terminal["pending_commands"]) == 1
        open_order = terminal["open_orders"][0]
        assert open_order["status"] == "PENDING_CANCEL"
        account_orders = [
            order
            for order in terminal["account"]["fields"]["orders"]
            if order["order_id"] == open_order["order_id"]
        ]
        assert len(account_orders) == 1
        assert account_orders[0]["status"] == "PENDING_CANCEL"
        assert account_orders[0]["remaining_quantity_lots"] == 1
        command = terminal["pending_commands"][0]
        assert command["command_id"] == "command-1" and command["command_type"] == "cancel"
        assert command["source_ref"] == {"line": 3, "capture_seq": 3, "event_type": "trade"}
        assert audit["replay_evaluation"]["valuation_status"] == "not_eligible"
        assert audit["replay_evaluation"]["valuation"] is None
    else:
        assert submitted["execution_status"] == receipt["execution_status"] == "completed"
        assert audit["execution_status"] == result["execution_status"] == "completed"
        assert terminal["open_orders"] == terminal["pending_commands"] == []
        assert terminal["stop_reason"] == "input_exhausted"
        assert not any(row["kind"] == "OrderCanceled" for row in result["order_trace"])
        second_fills = [
            (index, row)
            for index, row in enumerate(result["order_trace"])
            if row["kind"] == "OrderFilled" and row["source_ref"]["capture_seq"] == 5
        ]
        rejections = [
            (index, row)
            for index, row in enumerate(result["order_trace"])
            if row["kind"] == "OrderCancelRejected"
        ]
        assert len(second_fills) == len(rejections) == 1
        fill_index, second_fill = second_fills[0]
        rejection_index, rejection = rejections[0]
        assert fill_index < rejection_index
        for row in (second_fill, rejection):
            assert row["source_ref"] == {"line": 5, "capture_seq": 5, "event_type": "trade"}
            assert row["native_time_ns"] == 1_700_000_003_000_000_000
            assert row["fields"]["status"] == "FILLED"
        assert second_fill["fields"]["pending_command_ids"] == ["command-1"]
        assert rejection["fields"]["pending_command_ids"] == []
        assert rejection["fields"]["order_id"] == second_fill["fields"]["order_id"]
        account_orders = [
            order
            for order in terminal["account"]["fields"]["orders"]
            if order["order_id"] == second_fill["fields"]["order_id"]
        ]
        assert len(account_orders) == 1
        assert account_orders[0]["status"] == "FILLED"
        assert account_orders[0]["filled_quantity_lots"] == 2
        assert account_orders[0]["remaining_quantity_lots"] == 0
    verified = inspected["verification"]
    for key in (
        "integrity_verified",
        "bindings_verified",
        "source_package_reaudited",
        "observed_source_prefix_matched",
        "preparation_recomputed",
        "state_audit_recomputed",
    ):
        assert verified[key] is True
    for key in (
        "native_replayed",
        "attempt_reserved",
        "checkpoint_resume_verified",
        "witness_preservation_verified",
        "full_attempt_history_verified",
        "global_ledger_authenticity_verified",
        "source_claim_authority_extended",
    ):
        assert verified[key] is False


def _check_attempt_recovery(
    recovered: dict, source: dict, prepared: dict, inspected: dict
) -> None:
    assert recovered["kind"] == "reduction_attempt_recovery_v1"
    assert recovered["schema_version"] == 1
    assert recovered["source"] == {
        "bundle_id": source["bundle_id"],
        "report_id": source["report_id"],
        "protocol_id": inspected["protocol_id"],
    }
    assert recovered["preparation_id"] == prepared["preparation_id"]
    assert recovered["attempt"] == inspected["receipt"]["attempt"]
    assert recovered["status"] == "committed_result"
    assert recovered["recovery"] == {
        "disposition": "result_reverified_without_execution",
        "restart_mode": "frozen_origin_new_attempt_only_v1",
        "checkpoint_supported": False,
        "execution_authorized": False,
    }
    assert recovered["bindings"] == {
        "intent_id": inspected["intent_id"],
        "outcome_id": inspected["run_id"],
        "run_id": inspected["run_id"],
    }
    assert recovered["final_manifest"] == inspected["receipt"]
    assert _sha(_canonical(recovered["final_manifest"])) == inspected["run_id"]
    assert recovered["verification"] == {
        **dict.fromkeys(
            (
                "source_reaudited",
                "preparation_recomputed",
                "observed_source_prefix_matched",
                "reservation_verified",
                "preparation_binding_verified",
                "preparation_cas_verified",
                "terminal_reverified",
                "observation_only",
            ),
            True,
        ),
        **dict.fromkeys(
            (
                "attempt_reserved",
                "native_replayed",
                "research_published",
                "job_state_changed",
                "checkpoint_restored",
                "retry_performed",
                "budget_refunded",
                "global_absence_verified",
                "global_ledger_authenticity_verified",
            ),
            False,
        ),
    }


def _native_lifecycle(
    run, helper, examples: Path, root: Path, inputs: Path, preparations: Path
) -> dict:
    for filename in (
        "replay-partials.jsonl",
        "replay-confirmation.jsonl",
        "stress-assumption-request.json",
        "search-execution-grid-request.json",
        "search-finding-request.json",
    ):
        shutil.copyfile(examples / filename, inputs / filename)
    request = json.loads((examples / "stress-experiment-request.json").read_bytes())
    request["claim"]["title"] = "Synthetic five-slot origin-prefix qualification"
    request["budget"]["max_attempts"] = 5
    (inputs / "live-experiment.json").write_bytes(_canonical(request))
    (inputs / "live-budget.json").write_bytes(
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
        run("import-events", filename, "--input-root", str(inputs), "--store", str(data))[
            "dataset_id"
        ]
        for filename in ("replay-partials.jsonl", "replay-confirmation.jsonl")
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
    plan = run(
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
        plan["plan_id"],
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
        plan["plan_id"],
        "live-budget.json",
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
    report = finding["report"]
    assert report["outcome"] == "COUNTEREXAMPLE_FOUND"
    assert report["planned_predicate_truth"] is False
    assert [row["ordinal"] for row in report["witnesses"]] == [1, 3]
    assert report["coverage"]["audited_ordinals"] == [1, 3]
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
    source_before = _tree(inputs / "live-source")
    ledger_before = _tree(runs)
    before = helper(_LEDGER_VIEW, str(inputs / "live-source"), str(runs), source["bundle_id"])
    assert before["protocol_id"] == frozen["protocol_id"]
    assert before["budget"]["max_attempts"] == 5
    assert [row["attempt_index"] for row in before["slots"]] == [1, 2, 3]
    assert before["slots"][0]["outcome_id"] == baseline["run_id"]
    assert [row["outcome_kind"] for row in before["slots"]] == [
        "research_run_receipt_v1",
        "scenario_run_receipt_v1",
        "scenario_run_receipt_v1",
    ]
    cases = []
    for name, focus, through, slot, pending in (
        ("pending-cancel", 4, 4, 4, True),
        ("filled-cancel-rejected", 5, 6, 5, False),
    ):
        (inputs / (name + ".json")).write_bytes(_canonical(_request(focus, through)))
        prepared = run(
            "prepare-reduction-input",
            "live-source",
            name + ".json",
            "--input-root",
            str(inputs),
            "--expected-bundle-id",
            source["bundle_id"],
            "--expected-report-id",
            source["report_id"],
            "--output",
            str(preparations / name),
        )
        assert _tree(runs) == (ledger_before if not cases else cases[-1]["ledger_tree"])
        command = (
            "run-reduction-input",
            str(preparations / name),
            "--source-evidence",
            "live-source",
            "--input-root",
            str(inputs),
            "--expected-preparation-id",
            prepared["preparation_id"],
            "--runs",
            str(runs),
        )
        acknowledgement = None
        if pending:
            submitted = run(*command, producer=True)
        else:
            trace = root / "outcome-ack-loss.jsonl"
            acknowledgement = run(
                *command, producer=True, expected=3, ack_loss_trace=trace
            )
            assert acknowledgement["error"]["code"] == "attempt_outcome_unconfirmed"
            attempt_id = acknowledgement["error"]["attempt_id"]
            committed = helper(_READ_OUTCOME, str(runs), attempt_id)
            assert committed["kind"] == "reduction_run_receipt_v1"
            assert _sha(_canonical(committed["attempt"])) == attempt_id
            audit = helper(
                _READ_ARTIFACT, str(runs), committed["bindings"]["state_audit_sha256"]
            )
            submitted = {
                "run_id": _sha(_canonical(committed)),
                "attempt_id": attempt_id,
                "intent_id": _sha(_canonical(committed["intent"])),
                "execution_status": committed["execution_status"],
                "state_audit": audit,
            }
            observed = [json.loads(line) for line in trace.read_bytes().splitlines()]
            assert observed == [
                {
                    "kind": "native_adapter_run_started_v1",
                    "dataset_id": prepared["prefix_context_id"],
                },
                {
                    "kind": "actual_research_outcome_committed_before_injected_ack_loss_v1",
                    "attempt_id": attempt_id,
                    "outcome_id": submitted["run_id"],
                    "outcome_sha256": submitted["run_id"],
                },
            ]
        current_before = _tree(runs)
        inspected = run(
            "inspect-reduction-run",
            submitted["run_id"],
            "--source-evidence",
            "live-source",
            "--input-root",
            str(inputs),
            "--runs",
            str(runs),
            guarded=True,
        )
        raw = helper(
            _READ_ARTIFACT, str(runs), inspected["receipt"]["bindings"]["replay_result_sha256"]
        )
        _check_inspection(
            inspected,
            submitted,
            prepared,
            slot=slot,
            focus=focus,
            through=through,
            pending=pending,
            result=raw,
        )
        assert _tree(runs) == current_before
        assert _tree(inputs / "live-source") == source_before
        recovery_command = (
            "inspect-reduction-attempt",
            submitted["attempt_id"],
            str(preparations / name),
            "--expected-preparation-id",
            prepared["preparation_id"],
            "--expected-bundle-id",
            source["bundle_id"],
            "--expected-report-id",
            source["report_id"],
            "--source-evidence",
            "live-source",
            "--input-root",
            str(inputs),
            "--runs",
            str(runs),
        )
        protected = {
            "source": _tree(inputs / "live-source"),
            "preparation": _tree(preparations / name),
            "ledger": _tree(runs),
        }
        recovered = run(*recovery_command, guarded=True)
        repeated = run(*recovery_command, guarded=True)
        _check_attempt_recovery(recovered, source, prepared, inspected)
        assert recovered == repeated
        assert _canonical(recovered) == _canonical(repeated)
        assert {
            "source": _tree(inputs / "live-source"),
            "preparation": _tree(preparations / name),
            "ledger": _tree(runs),
        } == protected
        cases.append(
            {
                "name": name,
                "request": _request(focus, through),
                "prepared": prepared,
                "submission": submitted,
                "inspection": inspected,
                "result": raw,
                "attempt_recovery": recovered,
                "repeated_attempt_recovery": repeated,
                "submission_acknowledgement": {
                    "confirmed": acknowledgement is None,
                    "injected_post_commit_exception": acknowledgement,
                    "submission_fields_reconstructed_from_committed_evidence": (
                        acknowledgement is not None
                    ),
                },
                "ledger_tree": current_before,
            }
        )
    after = helper(_LEDGER_VIEW, str(inputs / "live-source"), str(runs), source["bundle_id"])
    assert [row["attempt_index"] for row in after["slots"]] == [1, 2, 3, 4, 5]
    assert after["slots"][:3] == before["slots"]
    assert all(
        after["slots"][index]["outcome_kind"] == "reduction_run_receipt_v1" for index in (3, 4)
    )
    assert all(_tree(runs).get(path) == digest for path, digest in ledger_before.items())
    exhausted_before = _tree(runs)
    exhausted = run(
        "run-reduction-input",
        str(preparations / "filled-cancel-rejected"),
        "--source-evidence",
        "live-source",
        "--input-root",
        str(inputs),
        "--expected-preparation-id",
        cases[1]["prepared"]["preparation_id"],
        "--runs",
        str(runs),
        expected=8,
        exhaustion=True,
    )
    assert exhausted["error"]["code"] == "attempt_budget_exhausted"
    assert _tree(runs) == exhausted_before
    recovery_errors = []
    for name, position, replacement, expected, code in (
        ("missing-original-attempt", 1, "0" * 64, 4, "research_evidence_not_found"),
        (
            "wrong-frozen-preparation",
            1,
            cases[0]["submission"]["attempt_id"],
            2,
            "invalid_research_evidence",
        ),
        (
            "changed-source-pin",
            recovery_command.index("--expected-bundle-id") + 1,
            "0" * 64,
            2,
            "invalid_research_evidence",
        ),
    ):
        changed = list(recovery_command)
        changed[position] = replacement
        rejected = run(*changed, expected=expected, guarded=True)
        assert rejected["error"]["code"] == code
        assert _tree(runs) == exhausted_before
        assert _tree(inputs / "live-source") == source_before
        recovery_errors.append({"name": name, "error": rejected})
    altered = root / "rehashed-audit-runs"
    shutil.copytree(runs, altered)
    altered_audit = json.loads(_canonical(cases[0]["submission"]["state_audit"]))
    altered_audit["flags"]["focus_state_captured"] = True
    audit_raw = _canonical(altered_audit)
    audit_id = _sha(audit_raw)
    (altered / "objects" / "sha256" / audit_id).write_bytes(audit_raw)
    altered_receipt = json.loads(_canonical(cases[0]["inspection"]["receipt"]))
    altered_receipt["bindings"]["state_audit_sha256"] = audit_id
    receipt_raw = _canonical(altered_receipt)
    altered_run = _sha(receipt_raw)
    (altered / "objects" / "sha256" / altered_run).write_bytes(receipt_raw)
    (altered / "outcomes" / (cases[0]["submission"]["attempt_id"] + ".json")).write_bytes(
        receipt_raw
    )
    attack_before = _tree(altered)
    attack = run(
        "inspect-reduction-run",
        altered_run,
        "--source-evidence",
        "live-source",
        "--input-root",
        str(inputs),
        "--runs",
        str(altered),
        expected=2,
        guarded=True,
    )
    assert attack["error"]["code"] == "invalid_research_evidence"
    assert _tree(altered) == attack_before and _tree(runs) == exhausted_before
    recovery_attack = run(
        "inspect-reduction-attempt",
        cases[0]["submission"]["attempt_id"],
        str(preparations / cases[0]["name"]),
        "--expected-preparation-id",
        cases[0]["prepared"]["preparation_id"],
        "--expected-bundle-id",
        source["bundle_id"],
        "--expected-report-id",
        source["report_id"],
        "--source-evidence",
        "live-source",
        "--input-root",
        str(inputs),
        "--runs",
        str(altered),
        expected=2,
        guarded=True,
    )
    assert recovery_attack["error"]["code"] == "invalid_research_evidence"
    assert _tree(altered) == attack_before and _tree(runs) == exhausted_before
    return {
        "frozen": frozen,
        "plan": plan,
        "campaign": campaign,
        "baseline": baseline,
        "finding": finding,
        "source": source,
        "before": before,
        "after": after,
        "cases": [
            {key: value for key, value in case.items() if key != "ledger_tree"} for case in cases
        ],
        "budget_exhaustion": exhausted,
        "rehashed_state_claim_rejected": {"run_id": altered_run, "error": attack},
        "attempt_recovery": {
            "actual_native_result_attempts_reverified": 2,
            "statuses_observed": ["committed_result"],
            "statuses_not_qualified_by_this_native_lifecycle": [
                "reserved_without_intent", "reserved_unfinalized", "committed_failure"
            ],
            "post_commit_ack_loss_injected": True,
            "ack_loss_native_adapter_invocations": 1,
            "ack_loss_trace_path": "outcome-ack-loss.jsonl",
            "recovery_native_invocations": 0,
            "recovery_attempt_reservations": 0,
            "recovery_research_publications": 0,
            "original_five_slot_budget_unchanged": True,
            "no_process_death_or_retry_qualified": True,
            "repeated_reports_equal": True,
            "protected_source_preparation_ledger_bytes_unchanged": True,
            "rejections": recovery_errors,
            "rehashed_state_claim_rejected": recovery_attack,
        },
        "source_bundle_unchanged": _tree(inputs / "live-source") == source_before,
        "original_records_unchanged": True,
        "preparation_reserved_no_slots": True,
        "each_prefix_executed_once_from_origin": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "verifier-python", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--core-only", action="store_true")
    arguments = parser.parse_args()
    native = str(arguments.python.absolute())
    verifier = str(arguments.verifier_python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    committed_before = _tree(examples / "alpha")
    with _preserved_workspace(arguments.records_dir, arguments.report) as root:
        inputs, cwd, transcripts, preparations = (
            root / name for name in ("input-root", "unrelated-cwd", "transcripts", "preparations")
        )
        for directory in (inputs, cwd, transcripts, preparations):
            directory.mkdir()
        calls = []

        def invoke(
            executable: str, entry: list[str], command: tuple[str, ...], *, expected: int = 0
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
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            calls.append(record)
            (transcripts / f"{len(calls):04d}.json").write_bytes(_canonical(record))
            payload = completed.stdout if expected == 0 else completed.stderr
            unexpected = completed.stderr if expected == 0 else completed.stdout
            if completed.returncode != expected or unexpected:
                raise RuntimeError(
                    f"Installed prefix command exited {completed.returncode}, expected {expected}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            return json.loads(payload)

        def run(
            *command: str,
            expected: int = 0,
            producer: bool = False,
            guarded: bool = False,
            exhaustion: bool = False,
            ack_loss_trace: Path | None = None,
        ) -> dict:
            if ack_loss_trace is not None:
                assert producer and not guarded and not exhaustion and expected == 3
                entry = ["-c", _ACK_LOSS]
                command = (str(ack_loss_trace), *command)
            elif guarded or exhaustion:
                entry = ["-c", _GUARD + "\nraise SystemExit(main(sys.argv[1:]))\n"]
                command = ("exhaustion" if exhaustion else "readonly", *command)
            else:
                entry = ["-m", "tickwitness"]
            return invoke(native if producer else verifier, entry, command, expected=expected)

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
            assert str(Path(runtime["prefix"]).resolve()) == expected_prefix, runtime
            assert Path(runtime["prefix"]).resolve() != Path(runtime["base_prefix"]).resolve(), (
                runtime
            )
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
        assert pre_io == {"confirmation_operations_rejected_before_package_and_factory_io": 3}
        errors = []
        for command in (
            "run-reduction-input", "inspect-reduction-run", "inspect-reduction-attempt"
        ):
            if command == "run-reduction-input":
                positional = (
                    str(root / "missing-preparation"), "--expected-preparation-id", "invalid"
                )
            elif command == "inspect-reduction-attempt":
                positional = (
                    "invalid", str(root / "missing-preparation"),
                    "--expected-preparation-id", "invalid",
                    "--expected-bundle-id", "invalid", "--expected-report-id", "invalid",
                )
            else:
                positional = ("invalid",)
            rejected = run(
                command,
                *positional,
                "--source-evidence",
                "missing-source",
                "--input-root",
                str(root / "missing-input-root"),
                "--runs",
                str(root / "missing-runs"),
                "--split",
                "confirmation",
                expected=5,
                guarded=True,
            )
            assert rejected["error"]["code"] == "confirmation_access_denied"
            errors.append({"name": command + "-confirmation", "error": rejected})
        assert not (root / "missing-input-root").exists()
        assert not (root / "missing-runs").exists()
        shutil.copytree(examples / "alpha" / "counterexample", inputs / "old-exhausted-source")
        old_source_before = _tree(inputs / "old-exhausted-source")
        (inputs / "old-prefix.json").write_bytes(_canonical(_request(4, 4)))
        old_prepared = run(
            "prepare-reduction-input",
            "old-exhausted-source",
            "old-prefix.json",
            "--input-root",
            str(inputs),
            "--expected-bundle-id",
            _GOLDEN["bundle_id"],
            "--expected-report-id",
            _GOLDEN["report_id"],
            "--output",
            str(preparations / "old-prefix"),
        )
        empty = root / "empty-live-ledger"
        invoke(
            verifier,
            [
                "-c",
                "import json,sys; from pathlib import Path; "
                "from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger; "
                "LocalAttemptLedger(Path(sys.argv[1])); print(json.dumps({'created_empty':True}))",
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
                "run-reduction-input",
                str(preparations / "old-prefix"),
                "--source-evidence",
                "old-exhausted-source",
                "--input-root",
                str(inputs),
                "--expected-preparation-id",
                old_prepared["preparation_id"],
                "--runs",
                str(ledger),
                expected=expected,
                guarded=True,
            )
            assert rejected["error"]["code"] == code
            errors.append({"name": name, "error": rejected})
            recovery_rejected = run(
                "inspect-reduction-attempt",
                "0" * 64,
                str(preparations / "old-prefix"),
                "--source-evidence",
                "old-exhausted-source",
                "--input-root",
                str(inputs),
                "--expected-preparation-id",
                old_prepared["preparation_id"],
                "--expected-bundle-id",
                _GOLDEN["bundle_id"],
                "--expected-report-id",
                _GOLDEN["report_id"],
                "--runs",
                str(ledger),
                expected=expected,
                guarded=True,
            )
            assert recovery_rejected["error"]["code"] == code
            errors.append({"name": name + "-attempt-recovery", "error": recovery_rejected})
        assert _tree(empty) == empty_before and not (root / "never-created-ledger").exists()
        lifecycle = None
        if not arguments.core_only:
            lifecycle = _native_lifecycle(run, helper, examples, root, inputs, preparations)
        assert _tree(inputs / "old-exhausted-source") == old_source_before
        assert _tree(examples / "alpha") == committed_before
        report = {
            "kind": "installed_reduction_execution_acceptance_v1",
            "accepted": True,
            "native_execution": not arguments.core_only,
            "interpreter_identities": identities,
            "pre_io": pre_io,
            "core_rejections": errors,
            "committed_exhausted_source_pins": _GOLDEN,
            "old_source_not_restored_or_renewed": True,
            "old_source_and_empty_ledger_unchanged": (
                _tree(inputs / "old-exhausted-source") == old_source_before
                and _tree(empty) == empty_before
            ),
            "lifecycle": lifecycle,
            "attempt_recovery": {
                "authority": "readonly_original_reduction_attempt_recovery_v1",
                "native_statuses_qualified": (
                    [] if arguments.core_only else ["committed_result"]
                ),
                "other_statuses_covered_by_unit_fixtures_only": [
                    "reserved_without_intent", "reserved_unfinalized", "committed_failure"
                ],
                "post_commit_ack_loss_qualified": not arguments.core_only,
                "new_attempts_for_inspection": 0,
                "native_replays_for_inspection": 0,
                "research_publications_for_inspection": 0,
                "managed_retry_or_job_recovery_qualified": False,
                "actual_process_death_qualified": False,
            },
            "readonly_inspection_guard": {
                "core_only": True,
                "native_and_workers_forbidden": True,
                "reservation_and_publication_forbidden": True,
                "old_dataset_and_registry_access_forbidden": True,
                "network_and_sqlite_forbidden": True,
            },
            "state_boundary": "after_native_run_before_dispose_v1",
            "focus_state_captured": False,
            "initial_state_materialized": False,
            "checkpoint_resume_verified": False,
            "reduced_predicate_evaluated": False,
            "witness_preservation_verified": False,
            "external_attempts": 0,
            "external_attempt_gate": "PENDING",
        }
        report_path = root / "reduction-execution-smoke" / "report.json"
        report_path.parent.mkdir()
        report_path.write_bytes(_canonical(report))
        shutil.copytree(root, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(_tree(arguments.records_dir))
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
