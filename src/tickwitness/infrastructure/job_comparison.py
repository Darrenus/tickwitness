"""Trusted composition for the first allowlisted, read-only managed operation."""

from pathlib import Path
from typing import cast

from tickwitness.application.reduction_comparison import (
    compare_reduction_run,
    verify_reduction_comparison,
)
from tickwitness.domain.evidence.reduction_comparison import load_reduction_comparison_export
from tickwitness.domain.evidence.run_records import EvidenceValidationError
from tickwitness.domain.jobs.contracts import JobSpec, load_job_spec
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle


def execute_comparison(spec: JobSpec, *, saved: bytes | None = None) -> bytes:
    """Reopen pinned observations; saved output is independently reconstructed."""
    checked = load_job_spec(spec.canonical_bytes)
    request = cast("dict[str, object]", checked.document["request"])
    root = Path(cast("str", request["input_root"]))
    source_path = root / cast("str", request["source_evidence"])
    if not source_path.resolve().is_relative_to(root.resolve()):
        raise EvidenceValidationError("Job source evidence escapes its configured input root")
    source = read_search_evidence_bundle(source_path)

    def ledger_factory() -> LocalAttemptLedger:
        return LocalAttemptLedger(Path(cast("str", request["runs"])), create=False)

    if saved is None:
        result = compare_reduction_run(
            cast("str", request["run_id"]),
            source=source,
            ledger_factory=ledger_factory,
            expected_bundle_id=cast("str", request["expected_bundle_id"]),
            expected_report_id=cast("str", request["expected_report_id"]),
            split="development",
        )
    else:
        comparison_id, _ = load_reduction_comparison_export(saved)
        result = verify_reduction_comparison(
            cast("str", request["run_id"]),
            saved,
            expected_comparison_id=comparison_id,
            source=source,
            ledger_factory=ledger_factory,
            expected_bundle_id=cast("str", request["expected_bundle_id"]),
            expected_report_id=cast("str", request["expected_report_id"]),
            split="development",
        )
    return result.export_bytes
