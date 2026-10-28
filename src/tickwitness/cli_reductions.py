"""Prepare complete replay prefixes without executing or reserving an attempt."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.reductions import prepare_reduction_input, verify_reduction_input
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import EvidenceValidationError, identity
from tickwitness.domain.reduction.contracts import load_reduction_request
from tickwitness.infrastructure.reduction_bundles import LocalReductionBundles
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

COMMANDS = frozenset({"prepare-reduction-input", "verify-reduction-input"})


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    prepare = commands.add_parser(
        "prepare-reduction-input", help="Seal a full necessary prefix for a selected false witness"
    )
    prepare.add_argument("source", help="Relative source evidence directory under --input-root")
    prepare.add_argument("request", help="Relative reduction request .json under --input-root")
    prepare.add_argument("--expected-bundle-id", required=True)
    prepare.add_argument("--expected-report-id", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser(
        "verify-reduction-input", help="Recompute a prepared input from the complete source evidence"
    )
    verify.add_argument("preparation", type=Path)
    verify.add_argument("--source-evidence", required=True)
    verify.add_argument("--expected-preparation-id", required=True)
    for command in (prepare, verify):
        command.add_argument("--input-root", required=True, type=Path)
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def _source_path(root: Path, name: str) -> Path:
    relative = Path(name)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {".", ".."} for part in relative.parts)
        or str(relative) != name
    ):
        raise EvidenceValidationError("Source evidence must be a relative path under input-root")
    candidate = root / relative
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise EvidenceValidationError("Source evidence must remain under input-root")
    return candidate


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Reduction input preparation permits development only")
    bundles = LocalReductionBundles(arguments.input_root)
    if arguments.command == "verify-reduction-input":
        identity(arguments.expected_preparation_id)
        preparation = bundles.read(arguments.preparation)
        source = read_search_evidence_bundle(
            _source_path(arguments.input_root, arguments.source_evidence)
        )
        return verify_reduction_input(
            preparation,
            source=source,
            expected_preparation_id=arguments.expected_preparation_id,
            split=arguments.split,
        )
    raw = read_regular_file(
        arguments.input_root,
        arguments.request,
        max_bytes=64 * 1024,
        allowed_suffixes=frozenset({".json"}),
    )
    load_reduction_request(raw)
    identity(arguments.expected_bundle_id)
    identity(arguments.expected_report_id)
    source = read_search_evidence_bundle(_source_path(arguments.input_root, arguments.source))
    prepared = prepare_reduction_input(
        source,
        raw,
        expected_bundle_id=arguments.expected_bundle_id,
        expected_report_id=arguments.expected_report_id,
        split=arguments.split,
    )
    published = bundles.publish(prepared, arguments.output)
    reread = bundles.read(arguments.output)
    if (
        reread.manifest_bytes != published.manifest_bytes
        or reread.artifacts != published.artifacts
    ):
        raise EvidenceValidationError("Published reduction input changed before readback")
    receipt = verify_reduction_input(
        reread,
        source=source,
        expected_preparation_id=prepared.preparation_id,
        split=arguments.split,
    )
    return {**receipt, "status": "PREPARED_INPUT_ONLY"}
