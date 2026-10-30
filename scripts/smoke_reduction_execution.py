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
    "bundle_id": "2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4b1a8e9e6c43c78369",
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
if mode != 'exhaustion':
    LocalAttemptLedger.reserve = forbidden
"""
_PRE_IO = """
from tickwitness.application.reduction_execution import (
    run_reduction_input, inspect_reduction_run,
)
from tickwitness.application.research import ConfirmationAccessDenied
class Unreadable:
    def __getattribute__(self, name):
        raise AssertionError('Confirmation operation accessed source/preparation: ' + name)
for operation in ('run', 'inspect'):
    try:
        if operation == 'run':
            run_reduction_input(Unreadable(), Unreadable(),
                                expected_preparation_id='invalid', split='confirmation',
                                ledger_factory=forbidden, engine_factory=forbidden)
        else:
            inspect_reduction_run('invalid', source=Unreadable(), split='confirmation',
                                  ledger_factory=forbidden)
    except ConfirmationAccessDenied:
        pass
    else:
        raise AssertionError('Confirmation access returned a result')
print(json.dumps({'confirmation_operations_rejected_before_package_and_factory_io': 2}))
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
    inspected: dict, submitted: dict, prepared: dict, *, slot: int,
    focus: int, through: int, pending: bool, result: dict,
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
            "line": focus, "capture_seq": focus,
            "event_type": "delta" if focus == 4 else "trade",
        },
        "through_ref": {"line": through, "capture_seq": through, "event_type": "delta"},
    }
    assert [row["source_ref"]["capture_seq"] for row in result["input_trace"]] == list(
        range(1, through + 1)
    )
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
    assert terminal["account"]["fields"]["net_position_lots"] == 1
    assert terminal["account"]["fields"]["observed_commission"] == "1"
    assert terminal["account"]["fields"]["observed_fill_lots"] == 1
    assert audit["cash_lock_verification"] == "nonnegative_and_total_equals_free_plus_locked_v1"
    assert len(result["fill_trace"]) == 1
    assert result["fill_trace"][0]["source_ref"]["capture_seq"] == 3
    assert result["fill_trace"][0]["fields"]["quantity_lots"] == 1
    assert audit["replay_evaluation"]["ledger"]["actual_commission"] == "1"
    assert audit["replay_evaluation"]["ledger"]["filled_quantity_lots"] == 1
    if pending:
        assert submitted["execution_status"] == receipt["execution_status"] == "incomplete"
        assert audit["execution_status"] == result["execution_status"] == "incomplete"
        assert terminal["stop_reason"] == "pending_commands_at_data_end"
        assert len(terminal["open_orders"]) == len(terminal["pending_commands"]) == 1
        assert terminal["open_orders"][0]["status"] == "PENDING_CANCEL"
        assert terminal["open_orders"][0]["remaining_quantity_lots"] == 1
        command = terminal["pending_commands"][0]
        assert command["command_id"] == "command-1" and command["command_type"] == "cancel"
        assert command["source_ref"] == {"line": 3, "capture_seq": 3, "event_type": "trade"}
        assert audit["replay_evaluation"]["valuation_status"] == "not_eligible"
        assert audit["replay_evaluation"]["valuation"] is None
    else:
        assert submitted["execution_status"] == receipt["execution_status"] == "completed"
        assert audit["execution_status"] == result["execution_status"] == "completed"
        assert terminal["open_orders"] == terminal["pending_commands"] == []
        assert any(row["kind"] == "OrderCanceled" for row in result["order_trace"])
        assert terminal["account"]["fields"]["orders"][0]["status"] == "CANCELED"
    verified = inspected["verification"]
    for key in (
        "integrity_verified", "bindings_verified", "source_package_reaudited",
        "observed_source_prefix_matched", "preparation_recomputed", "state_audit_recomputed",
    ):
        assert verified[key] is True
    for key in (
        "native_replayed", "attempt_reserved", "checkpoint_resume_verified",
        "witness_preservation_verified", "full_attempt_history_verified",
        "global_ledger_authenticity_verified", "source_claim_authority_extended",
    ):
        assert verified[key] is False


def _native_lifecycle(run, helper, examples: Path, root: Path, inputs: Path,
                      preparations: Path) -> dict:
    for filename in (
        "replay-partials.jsonl", "replay-confirmation.jsonl",
        "stress-assumption-request.json", "search-execution-grid-request.json",
        "search-finding-request.json",
    ):
        shutil.copyfile(examples / filename, inputs / filename)
    request = json.loads((examples / "stress-experiment-request.json").read_bytes())
    request["claim"]["title"] = "Synthetic five-slot origin-prefix qualification"
    request["budget"]["max_attempts"] = 5
    (inputs / "live-experiment.json").write_bytes(_canonical(request))
    (inputs / "live-budget.json").write_bytes(_canonical({
        "kind": "campaign_budget_request_v1", "schema_version": 1,
        "max_evaluations": 2, "max_wall_time_ms": 120000,
        "max_storage_bytes": 512 * 1024 * 1024,
    }))
    data, registry, plans, runs, findings = (
        root / name for name in ("data", "registry", "plans", "live-runs", "findings")
    )
    dataset_ids = [
        run("import-events", filename, "--input-root", str(inputs), "--store", str(data))
        ["dataset_id"]
        for filename in ("replay-partials.jsonl", "replay-confirmation.jsonl")
    ]
    frozen = run(
        "freeze-experiment", "live-experiment.json", "--input-root", str(inputs),
        "--development-dataset", dataset_ids[0], "--confirmation-dataset", dataset_ids[1],
        "--store", str(data), "--registry", str(registry),
    )
    plan = run(
        "freeze-search-plan", frozen["protocol_id"], "stress-assumption-request.json",
        "search-execution-grid-request.json", "--input-root", str(inputs),
        "--store", str(data), "--registry", str(registry), "--plans", str(plans),
    )
    authority = run(
        "freeze-search-finding-protocol", plan["plan_id"], "search-finding-request.json",
        "--input-root", str(inputs), "--plans", str(plans),
        "--finding-registry", str(findings),
    )
    baseline = run(
        "replay-protocol", frozen["protocol_id"], "--store", str(data),
        "--registry", str(registry), "--runs", str(runs), producer=True,
    )
    common = ("--plans", str(plans), "--store", str(data),
              "--registry", str(registry), "--runs", str(runs))
    campaign = run(
        "run-bounded-search-plan", plan["plan_id"], "live-budget.json",
        "--input-root", str(inputs), *common, producer=True,
    )
    finding = run(
        "evaluate-search-findings", authority["protocol_id"], *common,
        "--finding-registry", str(findings),
    )
    report = finding["report"]
    assert report["outcome"] == "COUNTEREXAMPLE_FOUND"
    assert report["planned_predicate_truth"] is False
    assert [row["ordinal"] for row in report["witnesses"]] == [1, 3]
    assert report["coverage"]["audited_ordinals"] == [1, 3]
    source = run(
        "export-search-evidence", authority["protocol_id"],
        "--expected-report-id", finding["report_id"], *common,
        "--finding-registry", str(findings), "--output", str(inputs / "live-source"),
    )
    source_before = _tree(inputs / "live-source")
    ledger_before = _tree(runs)
    before = helper(_LEDGER_VIEW, str(inputs / "live-source"), str(runs), source["bundle_id"])
    assert before["protocol_id"] == frozen["protocol_id"]
    assert before["budget"]["max_attempts"] == 5
    assert [row["attempt_index"] for row in before["slots"]] == [1, 2, 3]
    assert before["slots"][0]["outcome_id"] == baseline["run_id"]
    assert [row["outcome_kind"] for row in before["slots"]] == [
        "research_run_receipt_v1", "scenario_run_receipt_v1", "scenario_run_receipt_v1"
    ]
    cases = []
    for name, focus, through, slot, pending in (
        ("pending-cancel", 4, 4, 4, True),
        ("settled-cancel", 5, 6, 5, False),
    ):
        (inputs / (name + ".json")).write_bytes(_canonical(_request(focus, through)))
        prepared = run(
            "prepare-reduction-input", "live-source", name + ".json",
            "--input-root", str(inputs), "--expected-bundle-id", source["bundle_id"],
            "--expected-report-id", source["report_id"],
            "--output", str(preparations / name),
        )
        assert _tree(runs) == (ledger_before if not cases else cases[-1]["ledger_tree"])
        submitted = run(
            "run-reduction-input", str(preparations / name), "--source-evidence",
            "live-source", "--input-root", str(inputs), "--expected-preparation-id",
            prepared["preparation_id"], "--runs", str(runs), producer=True,
        )
        current_before = _tree(runs)
        inspected = run(
            "inspect-reduction-run", submitted["run_id"], "--source-evidence",
            "live-source", "--input-root", str(inputs), "--runs", str(runs), guarded=True,
        )
        raw = helper(
            _READ_ARTIFACT, str(runs), inspected["receipt"]["bindings"]["replay_result_sha256"]
        )
        _check_inspection(
            inspected, submitted, prepared, slot=slot, focus=focus,
            through=through, pending=pending, result=raw,
        )
        assert _tree(runs) == current_before
        assert _tree(inputs / "live-source") == source_before
        cases.append({
            "name": name, "request": _request(focus, through), "prepared": prepared,
            "submission": submitted, "inspection": inspected, "result": raw,
            "ledger_tree": current_before,
        })
    after = helper(_LEDGER_VIEW, str(inputs / "live-source"), str(runs), source["bundle_id"])
    assert [row["attempt_index"] for row in after["slots"]] == [1, 2, 3, 4, 5]
    assert after["slots"][:3] == before["slots"]
    assert all(after["slots"][index]["outcome_kind"] == "reduction_run_receipt_v1"
               for index in (3, 4))
    assert all(_tree(runs).get(path) == digest for path, digest in ledger_before.items())
    exhausted_before = _tree(runs)
    exhausted = run(
        "run-reduction-input", str(preparations / "settled-cancel"),
        "--source-evidence", "live-source", "--input-root", str(inputs),
        "--expected-preparation-id", cases[1]["prepared"]["preparation_id"],
        "--runs", str(runs), expected=8, exhaustion=True,
    )
    assert exhausted["error"]["code"] == "attempt_budget_exhausted"
    assert _tree(runs) == exhausted_before
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
        "inspect-reduction-run", altered_run, "--source-evidence", "live-source",
        "--input-root", str(inputs), "--runs", str(altered), expected=2, guarded=True,
    )
    assert attack["error"]["code"] == "invalid_research_evidence"
    assert _tree(altered) == attack_before and _tree(runs) == exhausted_before
    return {
        "frozen": frozen, "plan": plan, "campaign": campaign, "baseline": baseline,
        "finding": finding, "source": source, "before": before, "after": after,
        "cases": [{key: value for key, value in case.items() if key != "ledger_tree"}
                  for case in cases],
        "budget_exhaustion": exhausted,
        "rehashed_state_claim_rejected": {"run_id": altered_run, "error": attack},
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
                [executable, "-I", *entry, *command], cwd=cwd, capture_output=True,
                text=True, check=False, timeout=240,
            )
            record = {
                "executable": executable, "entry": entry, "command": list(command),
                "expected_exit_code": expected, "exit_code": completed.returncode,
                "stdout": completed.stdout, "stderr": completed.stderr,
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
            *command: str, expected: int = 0, producer: bool = False,
            guarded: bool = False, exhaustion: bool = False,
        ) -> dict:
            if guarded or exhaustion:
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
            ("producer", arguments.python), ("verifier", arguments.verifier_python)
        ):
            runtime = invoke(str(requested.absolute()), ["-c", runtime_query], ())
            expected_prefix = str(requested.absolute().parent.parent.resolve())
            assert str(Path(runtime["prefix"]).resolve()) == expected_prefix, runtime
            assert (
                Path(runtime["prefix"]).resolve() != Path(runtime["base_prefix"]).resolve()
            ), runtime
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
        assert pre_io == {"confirmation_operations_rejected_before_package_and_factory_io": 2}
        errors = []
        for command in ("run-reduction-input", "inspect-reduction-run"):
            positional = (
                (str(root / "missing-preparation"), "--expected-preparation-id", "invalid")
                if command == "run-reduction-input" else ("invalid",)
            )
            rejected = run(
                command, *positional, "--source-evidence", "missing-source",
                "--input-root", str(root / "missing-input-root"),
                "--runs", str(root / "missing-runs"), "--split", "confirmation",
                expected=5, guarded=True,
            )
            assert rejected["error"]["code"] == "confirmation_access_denied"
            errors.append({"name": command + "-confirmation", "error": rejected})
        assert not (root / "missing-input-root").exists()
        assert not (root / "missing-runs").exists()
        shutil.copytree(examples / "alpha" / "counterexample", inputs / "old-exhausted-source")
        (inputs / "old-prefix.json").write_bytes(_canonical(_request(4, 4)))
        old_prepared = run(
            "prepare-reduction-input", "old-exhausted-source", "old-prefix.json",
            "--input-root", str(inputs), "--expected-bundle-id", _GOLDEN["bundle_id"],
            "--expected-report-id", _GOLDEN["report_id"],
            "--output", str(preparations / "old-prefix"),
        )
        empty = root / "empty-live-ledger"
        invoke(
            verifier,
            ["-c", "import json,sys; from pathlib import Path; "
             "from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger; "
             "LocalAttemptLedger(Path(sys.argv[1])); print(json.dumps({'created_empty':True}))"],
            (str(empty),),
        )
        empty_before = _tree(empty)
        for name, ledger, expected, code in (
            ("old-source-missing-ledger", root / "never-created-ledger", 4,
             "research_evidence_not_found"),
            ("old-source-empty-ledger", empty, 2, "invalid_research_evidence"),
        ):
            rejected = run(
                "run-reduction-input", str(preparations / "old-prefix"),
                "--source-evidence", "old-exhausted-source", "--input-root", str(inputs),
                "--expected-preparation-id", old_prepared["preparation_id"],
                "--runs", str(ledger), expected=expected, guarded=True,
            )
            assert rejected["error"]["code"] == code
            errors.append({"name": name, "error": rejected})
        assert _tree(empty) == empty_before and not (root / "never-created-ledger").exists()
        lifecycle = None
        if not arguments.core_only:
            lifecycle = _native_lifecycle(run, helper, examples, root, inputs, preparations)
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
            "old_source_and_empty_ledger_unchanged": _tree(empty) == empty_before,
            "lifecycle": lifecycle,
            "readonly_inspection_guard": {
                "core_only": True, "native_and_workers_forbidden": True,
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
