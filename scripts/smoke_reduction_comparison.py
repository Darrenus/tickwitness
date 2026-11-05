#!/usr/bin/env python3
"""Audit installed comparisons of already executed original/reduced evidence.

This script never starts a replay or reserves an attempt. Its native profiles
consume the actual eleven-slot reduction-search qualification from the same CI
job; a core-only interpreter reaudits the copied source, ledger and comparisons.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

_GOLDEN = {
    "bundle_id": "2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369",
    "report_id": "398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb",
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
_SCOPE = {
    "phase": "development",
    "authority": "original_reduced_witness_review_v1",
    "source_claim_evaluated": False,
    "baseline_truth_evaluated": False,
    "original_finding_rewritten": False,
    "original_predicate_domain_extended": False,
    "budget_owner_changed": False,
    "numeric_effect_comparable": False,
    "global_earliest_claimed": False,
    "causal_attribution_issued": False,
    "shared_terminal_state_captured": False,
    "local_minimum_verified": False,
    "global_minimum_verified": False,
    "checkpoint_resume_verified": False,
    "full_attempt_history_verified": False,
    "global_ledger_authenticity_verified": False,
    "author_signature_verified": False,
    "human_domain_approval_verified": False,
    "confirmation_accessed": False,
}
_DOMAIN_VERIFICATION = {
    "original_scenario_reaudited": True,
    "reduced_state_reaudited": True,
    "preservation_recomputed": True,
    "input_partition_recomputed": True,
    "trace_comparison_recomputed": True,
    "native_replayed": False,
    "attempt_reserved": False,
    "live_ledger_reaudited": False,
    "source_claim_evaluated": False,
    "baseline_truth_evaluated": False,
    "shared_terminal_state_captured": False,
    "global_earliest_claimed": False,
    "causal_attribution_issued": False,
}
_CLI_VERIFICATION = {
    "source_package_reaudited": True,
    "observed_live_prefix_matched": True,
    "original_witness_reaudited": True,
    "reduction_run_reaudited": True,
    "comparison_recomputed": True,
    "saved_report_matched": True,
    "native_replayed": False,
    "attempt_reserved": False,
    "evidence_written": False,
    "source_claim_evaluated": False,
    "baseline_truth_evaluated": False,
    "global_earliest_claimed": False,
    "causal_attribution_issued": False,
    "confirmation_accessed": False,
    "full_attempt_history_verified": False,
    "author_signature_verified": False,
    "human_domain_approval_verified": False,
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
    raise AssertionError('Comparison requires an installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Comparison cannot import native')
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
    raise AssertionError('Comparison cannot execute, reserve, publish, repair or use network')
socket.socket = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
subprocess.Popen = forbidden
BoundedReplayAdapter.__init__ = forbidden
SubprocessReplayAdapter.__init__ = forbidden
for repository in (LocalCampaignBudgetStore, LocalExecutableProtocolRegistry,
                   LocalDatasetStore, LocalProtocolRegistry,
                   LocalConfirmationRegistry, LocalConfirmationExposureLedger,
                   LocalSearchCampaignStore, LocalReductionCampaignStore,
                   LocalSearchFindingRegistry, LocalSearchPlanRegistry):
    repository.__init__ = forbidden
original_ledger_init = LocalAttemptLedger.__init__
def readonly_ledger_init(self, *args, **kwargs):
    if kwargs.get('create', True) is not False:
        forbidden()
    return original_ledger_init(self, *args, **kwargs)
LocalAttemptLedger.__init__ = readonly_ledger_init
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
"""
_PRE_IO = """
from tickwitness.application.reduction_comparison import (
    compare_reduction_run, verify_reduction_comparison,
)
from tickwitness.application.research import ConfirmationAccessDenied
class Unreadable:
    def __getattribute__(self, name):
        raise AssertionError('Confirmation operation read evidence: ' + name)
for operation in ('compare', 'verify'):
    try:
        options = dict(source=Unreadable(), expected_bundle_id='invalid',
                       expected_report_id='invalid', split='confirmation',
                       ledger_factory=forbidden)
        if operation == 'compare':
            compare_reduction_run('invalid', **options)
        else:
            verify_reduction_comparison('invalid', Unreadable(),
                                        expected_comparison_id='invalid', **options)
    except ConfirmationAccessDenied:
        pass
    else:
        raise AssertionError('Confirmation operation returned a result')
print(json.dumps({'confirmation_operations_rejected_before_io': 2}))
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
    intent = ledger.get_intent(reservation.attempt_id)
    outcome = ledger.get_outcome(reservation.attempt_id)
    slots.append({'attempt_id': reservation.attempt_id,
                  'attempt_index': reservation.attempt_index,
                  'reservation': reservation.document,
                  'intent_id': None if intent is None else digest(intent),
                  'outcome_id': None if outcome is None else digest(outcome),
                  'outcome_kind': None if outcome is None else json.loads(outcome)['kind']})
print(json.dumps({'protocol_id': protocol.protocol_id,
                  'budget': protocol.document['budget'], 'slots': slots}, sort_keys=True))
"""
_RUNTIME = """
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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AssertionError("Qualification workspace cannot contain symlinks")
        if path.is_file():
            result[str(path.relative_to(root))] = _sha(path.read_bytes())
    return result


@contextmanager
def _workspace(records: Path, report: Path) -> Iterator[Path]:
    with TemporaryDirectory(prefix="tickwitness-reduction-comparison-") as temporary:
        root = Path(temporary)
        try:
            yield root
        except BaseException as error:
            for accepted in (
                report,
                root / "reduction-comparison-smoke" / "report.json",
                records / "reduction-comparison-smoke" / "report.json",
            ):
                with suppress(OSError):
                    accepted.unlink(missing_ok=True)
            try:
                shutil.copytree(root, records, dirs_exist_ok=True)
                (records / "diagnostic-capture.json").write_bytes(
                    _canonical(
                        {
                            "kind": "reduction_comparison_workspace_diagnostics_v1",
                            "accepted": False,
                            "exception_type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                )
            except Exception as diagnostic_error:
                print("Failed to preserve diagnostics: " + str(diagnostic_error), file=sys.stderr)
            raise


def _ref(index: int, event: dict) -> dict:
    return {"line": index + 1, "capture_seq": event["capture_seq"], "event_type": event["type"]}


def _export(report: dict) -> dict:
    return {
        "kind": "reduction_comparison_export_v1",
        "schema_version": 1,
        "comparison_id": _sha(_canonical(report)),
        "report": report,
    }


def _check_case(export: dict, upstream: dict, case: dict, original_events: list[dict], expected):
    through, delay, outcome = expected
    assert export.keys() == {"kind", "schema_version", "comparison_id", "report"}
    assert export["kind"] == "reduction_comparison_export_v1" and export["schema_version"] == 1
    report = export["report"]
    assert export["comparison_id"] == _sha(_canonical(report))
    assert report["kind"] == "reduction_comparison_v1" and report["schema_version"] == 1
    assert report["scope"] == _SCOPE and report["verification"] == _DOMAIN_VERIFICATION
    assert report["reduced_assessment"] == case["step"]["assessment"]
    assert report["reduced_assessment"]["outcome"] == outcome
    assert report["both_false_witnesses"] is (
        True if outcome == "PRESERVED" else False if outcome == "NOT_PRESERVED" else None
    )
    original = report["original_observation"]
    assert {key: original[key] for key in ("metric", "unit", "comparator", "threshold")} == {
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "comparator": "lt",
        "threshold": "-1.5",
    }
    assert original["eligible"] is True and original["truth"] is False
    assert original["value"] == "-1" and original["reason"] is None
    bindings = report["bindings"]
    assert bindings["source"]["bundle_id"] == upstream["lifecycle"]["source"]["bundle_id"]
    assert bindings["source"]["report_id"] == upstream["lifecycle"]["source"]["report_id"]
    assert bindings["source"]["witness_ordinal"] == 3
    witness = upstream["lifecycle"]["source_finding"]["report"]["witnesses"][0]
    assert bindings["original"]["run_id"] == witness["run_id"]
    assert bindings["original"]["attempt_id"] == witness["attempt_id"]
    assert bindings["original"]["result_sha256"] == witness["raw_result_sha256"]
    assert bindings["original"]["evaluation_sha256"] == witness["evaluation_sha256"]
    assert bindings["reduced"]["run_id"] == case["step"]["run_id"]
    assert bindings["reduced"]["attempt_id"] == case["step"]["attempt_id"]
    assert bindings["reduced"]["assessment_id"] == case["step"]["assessment_id"]
    assert bindings["original"]["attempt_id"] != bindings["reduced"]["attempt_id"]

    partition = report["input_difference"]
    refs = [_ref(index, event) for index, event in enumerate(original_events)]
    assert partition["reference_policy"] == "original_source_line_capture_seq_event_type_v1"
    assert partition["source_event_count"] == 7
    assert partition["retained_event_count"] == through
    assert partition["removed_event_count"] == 7 - through
    assert partition["original_additional_delay_ns"] == 2_000_000_000
    assert partition["reduced_additional_delay_ns"] == delay
    assert partition["origin_ref"] == refs[0]
    assert partition["focus_ref"] == refs[3]
    assert partition["through_ref"] == refs[through - 1]
    assert partition["minimum_through_capture_seq"] == 4
    assert partition["retained_refs"] == refs[:through]
    assert partition["warmup_refs"] == refs[:3]
    assert partition["review_refs"] == refs[3:through]
    assert partition["removed_events"] == [
        {
            "source_ref": refs[index],
            "original_event": original_events[index],
            "original_line_sha256": _sha(_canonical(original_events[index])),
        }
        for index in range(through, 7)
    ]
    changed = []
    if delay != 2_000_000_000:
        for index in range(3, through):
            before = original_events[index]
            after = {**before, "receive_time_ns": before["receive_time_ns"] - 1_000_000_000}
            changed.append(
                {
                    "source_ref": refs[index],
                    "original_line_sha256": _sha(_canonical(before)),
                    "reduced_line_sha256": _sha(_canonical(after)),
                    "field_differences": [
                        {
                            "json_pointer": "/receive_time_ns",
                            "original_value": before["receive_time_ns"],
                            "reduced_value": after["receive_time_ns"],
                        }
                    ],
                }
            )
    assert partition["changed_retained_events"] == changed

    horizon = report["horizon"]
    assert horizon["policy"] == "whole_recorded_runs_including_unequal_eof_v1"
    assert horizon["original_event_count"] == 7 and horizon["reduced_event_count"] == through
    assert horizon["shared_input_event_count"] == through
    assert horizon["same_input_horizon"] is (through == 7)
    assert horizon["shared_terminal_state_captured"] is False
    assert horizon["original"]["through_ref"] == refs[-1]
    assert horizon["reduced"]["through_ref"] == refs[through - 1]
    assert horizon["original"]["execution_status"] == "completed"
    assert horizon["original"]["valuation_status"] == "valued"
    assert horizon["reduced"]["execution_status"] == case["result"]["execution_status"]
    assert horizon["reduced"]["completeness"] == case["result"]["completeness"]
    assert horizon["reduced"]["valuation_status"] == (
        "not_eligible" if outcome == "NOT_EVALUABLE" else "valued"
    )
    trace = report["trace_comparison"]
    assert trace["global_earliest_claimed"] is False
    assert trace["comparison_order"] == [
        "input_trace",
        "decision_trace",
        "order_trace",
        "fill_trace",
        "account_trace",
        "execution_status",
        "completeness",
    ]
    assert trace["within_channel_order"] == "recorded_ordinal_then_sorted_json_keys_v1"
    assert trace["projection_policy"]["id"] == "coupled_stress_business_projection_v1"
    assert trace["projection_policy"]["unknown_fields_preserved"] is True
    assert trace["projection_policy"]["raw_values_and_trace_references_retained"] is True
    if through < 7:
        for view in ("raw", "business"):
            first = trace[view]["per_channel_first"]["input_trace"]
            if view == "business" or delay == 2_000_000_000:
                assert first["json_pointer"] == f"/input_trace/{through}"
                assert first["left_present"] is True and first["right_present"] is False
                assert first["left_trace_ref"]["source_ref"] == refs[through]
                assert first["right_trace_ref"] is None
    if delay == 1_000_000_000:
        first = trace["raw"]["per_channel_first"]["input_trace"]
        assert first["left_trace_ref"]["source_ref"] == refs[3]
        assert first["right_trace_ref"]["source_ref"] == refs[3]
        assert first["left_raw_value"] - first["right_raw_value"] == 1_000_000_000
        assert trace["business"]["per_channel_first"]["order_trace"] is not None
        if through == 7:
            assert trace["business"]["per_channel_first"]["input_trace"] is None
        if outcome == "NOT_PRESERVED":
            fills = trace["business"]["per_channel_first"]["fill_trace"]
            assert fills["json_pointer"] == "/fill_trace/1"
            assert fills["left_present"] is False and fills["right_present"] is True
            assert fills["right_trace_ref"]["source_ref"] == refs[4]
    assert "numeric_comparison" not in report


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "source-report", "source-records", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--core-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.records_dir.exists() or arguments.report.exists():
        raise FileExistsError("Comparison report and records must be new destinations")
    verifier = str(arguments.python.absolute())
    source_before = _tree(arguments.source_records)
    source_report_bytes = arguments.source_report.read_bytes()
    source_report = json.loads(source_report_bytes)
    assert source_report["kind"] == "installed_reduction_search_acceptance_v1"
    assert source_report["accepted"] is True
    assert source_report["native_execution"] is (not arguments.core_only)
    assert (
        source_report_bytes
        == (arguments.source_records / "reduction-search-smoke" / "report.json").read_bytes()
    )
    manifest = json.loads((arguments.source_records / "artifact-files.json").read_bytes())
    assert {name: sha for name, sha in source_before.items() if name != "artifact-files.json"} == (
        manifest
    )
    with _workspace(arguments.records_dir, arguments.report) as root:
        inputs, cwd, transcripts = (
            root / name for name in ("input-root", "unrelated-cwd", "transcripts")
        )
        for path in (inputs, cwd, transcripts):
            path.mkdir()
        upstream = inputs / "upstream"
        shutil.copytree(arguments.source_records, upstream)
        (root / "upstream-report.json").write_bytes(source_report_bytes)
        protected_before = _tree(upstream)
        assert protected_before == source_before
        calls = []

        def invoke(entry: list[str], command: tuple[str, ...], *, expected=0, text_output=False):
            completed = subprocess.run(
                [verifier, "-I", "-B", *entry, *command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=240,
            )
            record = {
                "executable": verifier,
                "entry": entry,
                "command": list(command),
                "expected_exit_code": expected,
                "exit_code": completed.returncode,
                "stdout_format": "markdown" if text_output else "json",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            calls.append(record)
            (transcripts / f"{len(calls):04d}.json").write_bytes(_canonical(record))
            if completed.returncode != expected or (
                completed.stderr if expected == 0 else completed.stdout
            ):
                raise RuntimeError(
                    f"Installed comparison exited {completed.returncode}, expected {expected}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            payload = completed.stdout if expected == 0 else completed.stderr
            return payload if text_output else json.loads(payload)

        def run(*command: str, expected=0, text_output=False):
            result = invoke(
                ["-c", _GUARD + "\nraise SystemExit(main(sys.argv[1:]))\n"],
                command,
                expected=expected,
                text_output=text_output,
            )
            assert _tree(upstream) == protected_before
            if expected == 0 and not text_output:
                assert calls[-1]["stdout"] == _canonical(result).decode("utf-8")
            return result

        def helper(code: str, *command: str):
            result = invoke(["-c", _GUARD + code], command)
            assert _tree(upstream) == protected_before
            return result

        runtime = invoke(["-c", _RUNTIME], ())
        prefix = str(arguments.python.absolute().parent.parent.resolve())
        assert str(Path(runtime["prefix"]).resolve()) == prefix
        assert Path(runtime["prefix"]).resolve() != Path(runtime["base_prefix"]).resolve()
        assert runtime["native_distribution"] is None
        assert runtime["project_version"] == "0.2.0.dev0"
        identity = {
            "requested_executable": verifier,
            "requested_venv_prefix_resolved": prefix,
            "runtime": runtime,
        }
        (root / "interpreter-identity.json").write_bytes(_canonical(identity))
        pre_io = helper(_PRE_IO)
        assert pre_io == {"confirmation_operations_rejected_before_io": 2}
        rejections = []
        for command in ("compare-reduction-run", "verify-reduction-comparison"):
            positional = ("invalid",)
            if command == "verify-reduction-comparison":
                positional += ("missing-export.json", "--expected-comparison-id", "invalid")
            rejected = run(
                command,
                *positional,
                "--source-evidence",
                "missing-source",
                "--input-root",
                str(root / "never-input"),
                "--runs",
                str(root / "never-runs"),
                "--expected-bundle-id",
                "invalid",
                "--expected-report-id",
                "invalid",
                "--split",
                "confirmation",
                expected=5,
            )
            assert rejected["error"]["code"] == "confirmation_access_denied"
            rejections.append({"name": command + "-confirmation", "error": rejected})
        assert not (root / "never-input").exists() and not (root / "never-runs").exists()

        def common(source_name, bundle, report, runs):
            return (
                "--source-evidence",
                source_name,
                "--input-root",
                str(inputs),
                "--runs",
                str(runs),
                "--expected-bundle-id",
                bundle,
                "--expected-report-id",
                report,
            )

        old_common = common(
            "upstream/input-root/old-exhausted-source",
            _GOLDEN["bundle_id"],
            _GOLDEN["report_id"],
            root / "never-runs",
        )
        missing = run("compare-reduction-run", "0" * 64, *old_common, expected=4)
        assert missing["error"]["code"] == "research_evidence_not_found"
        rejections.append({"name": "missing-live-ledger", "error": missing})
        (inputs / "invalid-export.json").write_bytes(b"{}")
        invalid = run(
            "verify-reduction-comparison",
            "0" * 64,
            "invalid-export.json",
            "--expected-comparison-id",
            "0" * 64,
            *old_common,
            expected=2,
        )
        assert invalid["error"]["code"] == "invalid_research_evidence"
        rejections.append({"name": "invalid-export", "error": invalid})
        assert not (root / "never-runs").exists()

        lifecycle = None
        if not arguments.core_only:
            source = source_report["lifecycle"]["source"]
            runs = upstream / "live-runs"
            options = common(
                "upstream/input-root/live-source",
                source["bundle_id"],
                source["report_id"],
                runs,
            )
            before = helper(
                _LEDGER_VIEW,
                str(upstream / "input-root" / "live-source"),
                str(runs),
                source["bundle_id"],
            )
            assert before == source_report["lifecycle"]["after"]
            assert before["budget"] == {
                "max_attempts": 11,
                "max_events": 1000,
                "max_wall_seconds": 60,
            }
            assert [slot["attempt_index"] for slot in before["slots"]] == list(range(1, 12))
            event_bytes = (upstream / "input-root" / "replay-partials.jsonl").read_bytes()
            events = [json.loads(line) for line in event_bytes.splitlines()]
            original_events = deepcopy(events)
            for event in original_events[3:]:
                event["receive_time_ns"] += 2_000_000_000
            exports = inputs / "exports"
            exports.mkdir()
            cases = []
            for index, (case, expected) in enumerate(
                zip(source_report["lifecycle"]["main"]["cases"], _POINTS, strict=True), start=1
            ):
                run_id = case["step"]["run_id"]
                export = run("compare-reduction-run", run_id, *options)
                _check_case(export, source_report, case, original_events, expected)
                path = exports / f"main-{index:02d}.json"
                path.write_bytes(_canonical(export))
                verified = run(
                    "verify-reduction-comparison",
                    run_id,
                    str(path.relative_to(inputs)),
                    "--expected-comparison-id",
                    export["comparison_id"],
                    *options,
                )
                assert verified == {
                    "kind": "reduction_comparison_verification_receipt_v1",
                    "schema_version": 1,
                    "comparison_id": export["comparison_id"],
                    "report": export["report"],
                    "verification": _CLI_VERIFICATION,
                }
                cases.append({"export": export, "verification": verified})
            assert len(cases) == 7
            best_id = source_report["lifecycle"]["main"]["report"]["best"]["run_id"]
            repeated = run("compare-reduction-run", best_id, *options)
            assert repeated == cases[5]["export"]
            markdown = run(
                "compare-reduction-run",
                best_id,
                *options,
                "--format",
                "markdown",
                text_output=True,
            )
            assert repeated["comparison_id"] in markdown
            assert source["bundle_id"] in markdown and best_id in markdown
            assert "PRESERVED" in markdown
            (root / "best-comparison.md").write_text(markdown, encoding="utf-8")
            cancelled = source_report["lifecycle"]["cancel_after_actual_native"]["hook"]["report"]
            cancelled_export = run(
                "compare-reduction-run", cancelled["steps"][0]["run_id"], *options
            )
            cancelled_case = source_report["lifecycle"]["cancel_after_actual_native"]["cases"][0]
            _check_case(
                cancelled_export, source_report, cancelled_case, original_events, _POINTS[0]
            )

            attacks = []
            preserved = cases[1]["export"]
            for name in ("numeric-preservation", "removed-content", "business-divergence"):
                forged = deepcopy(preserved["report"])
                if name == "numeric-preservation":
                    assessment = forged["reduced_assessment"]
                    assessment["outcome"] = "NOT_PRESERVED"
                    assessment["criterion_observation"].update(value="-2", truth=True)
                    forged["both_false_witnesses"] = False
                    forged["bindings"]["reduced"]["assessment_id"] = _sha(_canonical(assessment))
                elif name == "removed-content":
                    removed = forged["input_difference"]["removed_events"][0]
                    removed["original_event"]["receive_time_ns"] += 1
                    removed["original_line_sha256"] = _sha(_canonical(removed["original_event"]))
                else:
                    trace = forged["trace_comparison"]
                    trace["business"]["first_divergence"] = None
                    for channel in trace["business"]["per_channel_first"]:
                        trace["business"]["per_channel_first"][channel] = None
                    trace["business_trace_changed"] = False
                attack = _export(forged)
                attack_path = exports / (name + ".json")
                attack_path.write_bytes(_canonical(attack))
                rejected = run(
                    "verify-reduction-comparison",
                    forged["bindings"]["reduced"]["run_id"],
                    str(attack_path.relative_to(inputs)),
                    "--expected-comparison-id",
                    attack["comparison_id"],
                    *options,
                    expected=2,
                )
                assert rejected["error"]["code"] == "invalid_research_evidence"
                attacks.append(
                    {"name": name, "comparison_id": attack["comparison_id"], "error": rejected}
                )
            bad_pin = run(
                "compare-reduction-run",
                best_id,
                *common("upstream/input-root/live-source", "0" * 64, source["report_id"], runs),
                expected=2,
            )
            assert bad_pin["error"]["code"] == "invalid_research_evidence"
            wrong_run = run("compare-reduction-run", "0" * 64, *options, expected=4)
            assert wrong_run["error"]["code"] == "research_evidence_not_found"
            cas_failures = []
            best_inspection = source_report["lifecycle"]["main"]["cases"][5]["inspection"]
            audit_sha = best_inspection["receipt"]["bindings"]["state_audit_sha256"]
            for name, expected, code in (
                ("missing", 4, "research_evidence_not_found"),
                ("corrupt", 3, "research_store_integrity_or_io_failure"),
            ):
                altered = inputs / (name + "-run-cas")
                shutil.copytree(runs, altered)
                target = altered / "objects" / "sha256" / audit_sha
                if name == "missing":
                    target.unlink()
                else:
                    target.write_bytes(target.read_bytes() + b" ")
                altered_before = _tree(altered)
                rejected = run(
                    "compare-reduction-run",
                    best_id,
                    *common(
                        "upstream/input-root/live-source",
                        source["bundle_id"],
                        source["report_id"],
                        altered,
                    ),
                    expected=expected,
                )
                assert rejected["error"]["code"] == code and _tree(altered) == altered_before
                cas_failures.append({"name": name, "error": rejected, "sha256": audit_sha})
            after = helper(
                _LEDGER_VIEW,
                str(upstream / "input-root" / "live-source"),
                str(runs),
                source["bundle_id"],
            )
            assert after == before
            lifecycle = {
                "source_bundle_id": source["bundle_id"],
                "source_report_id": source["report_id"],
                "before": before,
                "after": after,
                "main": cases,
                "cancelled_actual_run_comparison": cancelled_export,
                "repeated_best": repeated,
                "markdown_path": "best-comparison.md",
                "rehashed_forgeries": attacks,
                "wrong_source_pin": bad_pin,
                "missing_run": wrong_run,
                "cas_failures": cas_failures,
                "native_runs_reused": 8,
                "new_native_runs": 0,
                "new_attempts": 0,
            }
        assert _tree(upstream) == protected_before
        assert _tree(arguments.source_records) == source_before
        assert arguments.source_report.read_bytes() == source_report_bytes
        report = {
            "kind": "installed_reduction_comparison_acceptance_v1",
            "accepted": True,
            "core_only_profile": arguments.core_only,
            "native_execution": False,
            "native_replayed": False,
            "native_execution_performed": False,
            "upstream_native_evidence_reused": not arguments.core_only,
            "interpreter_identity": identity,
            "pre_io": pre_io,
            "rejections": rejections,
            "upstream_report_sha256": _sha(source_report_bytes),
            "upstream_records_manifest_sha256": source_before["artifact-files.json"],
            "upstream_report_path": "upstream-report.json",
            "upstream_records_path": "input-root/upstream",
            "upstream_bytes_unchanged": True,
            "lifecycle": lifecycle,
            "readonly_guard": {
                "core_only": True,
                "native_and_workers_forbidden": True,
                "reservations_and_all_publications_forbidden": True,
                "ledger_create_false_required": True,
                "old_research_stores_forbidden": True,
                "network_and_sqlite_forbidden": True,
            },
            "scope": _SCOPE,
            "new_attempts": 0,
            "new_native_runs": 0,
            "external_attempts": 0,
            "external_attempt_gate": "PENDING",
        }
        inner = root / "reduction-comparison-smoke" / "report.json"
        inner.parent.mkdir()
        inner.write_bytes(_canonical(report))
        shutil.copytree(root, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(_tree(arguments.records_dir))
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
