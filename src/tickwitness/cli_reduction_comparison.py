"""Read-only exports and review views of original/reduced execution evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast

from tickwitness.application.reduction_comparison import (
    compare_reduction_run,
    verify_reduction_comparison,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.cli_reductions import _source_path
from tickwitness.domain.evidence.reduction_comparison import (
    MAX_REDUCTION_COMPARISON_EXPORT_BYTES,
    ReductionComparison,
    load_reduction_comparison_export,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, identity
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

COMMANDS = frozenset({"compare-reduction-run", "verify-reduction-comparison"})
VERIFICATION: Mapping[str, object] = MappingProxyType(
    {
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
)
type Row = dict[str, object]


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    compare = commands.add_parser(
        "compare-reduction-run",
        help="Audit original/reduced evidence and locate recorded differences",
    )
    compare.add_argument("run_id")
    compare.add_argument("--format", choices=("json", "markdown"), default="json")
    verify = commands.add_parser(
        "verify-reduction-comparison", help="Independently recompute a saved comparison export"
    )
    verify.add_argument("run_id")
    verify.add_argument("export", help="Canonical comparison export .json under --input-root")
    verify.add_argument("--expected-comparison-id", required=True)
    for command in (compare, verify):
        command.add_argument("--source-evidence", required=True)
        command.add_argument("--input-root", type=Path, required=True)
        command.add_argument("--runs", type=Path, required=True)
        command.add_argument("--expected-bundle-id", required=True)
        command.add_argument("--expected-report-id", required=True)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def _json_block(value: object) -> str:
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
    longest = max((len(item) for item in re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return fence + "json\n" + content + "\n" + fence


def _ref(value: object) -> str:
    if value is None:
        return "none"
    row = cast("Row", value)
    return f"capture {row['capture_seq']} / line {row['line']} / {row['event_type']}"


def render_markdown(comparison: ReductionComparison) -> str:
    """Render only independently audited facts, retaining the JSON evidence references."""
    document = comparison.document
    bindings = cast("Row", document["bindings"])
    original = cast("Row", bindings["original"])
    reduced = cast("Row", bindings["reduced"])
    inputs = cast("Row", document["input_difference"])
    horizon = cast("Row", document["horizon"])
    assessment = cast("Row", document["reduced_assessment"])
    traces = cast("Row", document["trace_comparison"])
    sections = [
        "# TickWitness reduction comparison",
        f"Comparison ID: `{comparison.comparison_id}`",
        f"Original false scenario witness: `{original['run_id']}`",
        f"Reduced execution: `{reduced['run_id']}`",
        "## Input coverage",
        f"Retained {inputs['retained_event_count']} of {inputs['source_event_count']} events; "
        f"removed {inputs['removed_event_count']} trailing events.",
        f"Origin: {_ref(inputs['origin_ref'])}\n\n"
        f"Focus: {_ref(inputs['focus_ref'])}\n\n"
        f"Through: {_ref(inputs['through_ref'])}",
        f"Additional delay: {inputs['original_additional_delay_ns']} → "
        f"{inputs['reduced_additional_delay_ns']} ns.",
        _json_block(
            {
                "retained_refs": inputs["retained_refs"],
                "warmup_refs": inputs["warmup_refs"],
                "review_refs": inputs["review_refs"],
            }
        ),
        "## Removed trailing events",
        _json_block(inputs["removed_events"]),
        "## Changes within retained events",
        _json_block(inputs["changed_retained_events"]),
        "## Original criterion on each observed horizon",
        f"Reduced outcome: **{assessment['outcome']}**. "
        f"Both false witnesses: `{json.dumps(document['both_false_witnesses'])}`.",
        _json_block(
            {
                "original": document["original_observation"],
                "reduced": assessment["criterion_observation"],
                "horizon": horizon,
            }
        ),
        "## First recorded differences by channel",
        "Rows retain actual source references and raw values. Channels use their recorded "
        "ordinal and sorted JSON field order. Whole recorded runs include their own EOF; "
        "these references do not establish a global earliest event or a causal effect.",
        _json_block(traces),
        "## Conditions and scope",
        _json_block(
            {
                "bindings": bindings,
                "condition_differences": document["condition_differences"],
                "scope": document["scope"],
                "verification": document["verification"],
            }
        ),
    ]
    return "\n\n".join(sections) + "\n"


def execute(arguments: argparse.Namespace) -> str:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Reduction comparisons permit development evidence only")
    identity(arguments.run_id)
    identity(arguments.expected_bundle_id)
    identity(arguments.expected_report_id)
    raw: bytes | None = None
    if arguments.command == "verify-reduction-comparison":
        expected = identity(arguments.expected_comparison_id)
        raw = read_regular_file(
            arguments.input_root,
            arguments.export,
            max_bytes=MAX_REDUCTION_COMPARISON_EXPORT_BYTES,
            allowed_suffixes=frozenset({".json"}),
        )
        comparison_id, _ = load_reduction_comparison_export(raw)
        if comparison_id != expected:
            raise EvidenceValidationError("Comparison export differs from its expected identity")
    source = read_search_evidence_bundle(
        _source_path(arguments.input_root, arguments.source_evidence)
    )

    def ledger_factory() -> LocalAttemptLedger:
        return LocalAttemptLedger(arguments.runs, create=False)

    if raw is not None:
        comparison = verify_reduction_comparison(
            arguments.run_id,
            raw,
            expected_comparison_id=arguments.expected_comparison_id,
            source=source,
            expected_bundle_id=arguments.expected_bundle_id,
            expected_report_id=arguments.expected_report_id,
            split=arguments.split,
            ledger_factory=ledger_factory,
        )
        return canonical(
            {
                "kind": "reduction_comparison_verification_receipt_v1",
                "schema_version": 1,
                "comparison_id": comparison.comparison_id,
                "report": comparison.document,
                "verification": dict(VERIFICATION),
            }
        ).decode("utf-8")
    comparison = compare_reduction_run(
        arguments.run_id,
        source=source,
        expected_bundle_id=arguments.expected_bundle_id,
        expected_report_id=arguments.expected_report_id,
        split=arguments.split,
        ledger_factory=ledger_factory,
    )
    if arguments.format == "markdown":
        return render_markdown(comparison)
    return comparison.export_bytes.decode("utf-8")
