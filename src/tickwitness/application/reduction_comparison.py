"""Reaudit an original false scenario and a committed prefix without execution.

Portable source bytes establish observed facts, never replacement ledger slots.
Comparison and verification are read-only and do not resume a reduction search.
"""

from collections.abc import Callable
from typing import cast

from tickwitness.application.reduction_execution import (
    ReductionLedger,
    _checked_prefix,
    _Preparation,
    _prepare,
    _snapshot,
    inspect_reduction_run,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_evidence import SearchEvidencePackage, verify_search_package
from tickwitness.domain.evidence.reduction_comparison import (
    ReductionComparison,
    load_reduction_comparison_export,
)
from tickwitness.domain.evidence.reduction_records import (
    MAX_REDUCTION_RECORD_BYTES,
    MAX_REDUCTION_STATE_AUDIT_BYTES,
    load_reduction_run_receipt,
)
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
    identity,
)
from tickwitness.domain.evidence.scenario_records import load_scenario_run_receipt
from tickwitness.domain.reduction.contracts import role_limit
from tickwitness.domain.replay.contracts import load_replay_result
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import (
    load_search_finding_protocol,
)

type Row = dict[str, object]
_RESULT_LIMIT = 16 * 1024 * 1024


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Reduction comparison permits development evidence only")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _read(
    ledger: ReductionLedger, sha: str, limit: int, observed: list[tuple[str, bytes, int]]
) -> bytes:
    raw = ledger.read_artifact(identity(sha), max_bytes=limit)
    _require(digest(raw) == sha, "Comparison artifact differs from its content identity")
    observed.append((sha, raw, limit))
    return raw


def _reservation(document: Row) -> AttemptReservation:
    raw = canonical(cast("Row", document["attempt"]))
    return AttemptReservation(digest(raw), raw)


def _committed(
    ledger: ReductionLedger,
    reservation: AttemptReservation,
    outcome: bytes,
    intent: bytes,
) -> None:
    _require(
        ledger.get_reservation(reservation.attempt_id) == reservation
        and ledger.get_outcome(reservation.attempt_id) == outcome
        and ledger.get_intent(reservation.attempt_id) == intent,
        "Comparison requires the exact committed reservation, intent and outcome",
    )


def compare_reduction_run(
    run_id: str,
    *,
    source: SearchEvidencePackage,
    expected_bundle_id: str,
    expected_report_id: str,
    split: str,
    ledger_factory: Callable[[], ReductionLedger],
) -> ReductionComparison:
    """Rebuild both actual observations without reserving or publishing anything."""
    _development(split)
    requested = identity(run_id)
    bundle_id, report_id = identity(expected_bundle_id), identity(expected_report_id)
    snapshot = _snapshot(source)
    verified = verify_search_package(snapshot, expected_bundle_id=bundle_id)
    _require(verified["report_id"] == report_id, "Comparison source report pin differs")
    authority = load_search_finding_protocol(snapshot.artifacts["finding_protocol"])
    source_protocol = load_executable_protocol(
        canonical(cast("Row", authority.plan.document["protocol"]))
    )
    ledger = ledger_factory()
    _checked_prefix(snapshot, source_protocol, ledger)
    inspected = inspect_reduction_run(
        requested, source=snapshot, split="development", ledger_factory=lambda: ledger
    )
    observed: list[tuple[str, bytes, int]] = []
    reduced_raw = _read(ledger, requested, MAX_REDUCTION_RECORD_BYTES, observed)
    reduced = load_reduction_run_receipt(reduced_raw)
    _require(
        reduced.run_id == requested and canonical(cast("Row", inspected["receipt"])) == reduced_raw,
        "Reduction outcome changed after independent inspection",
    )
    reduced_document = reduced.document
    intent = cast("Row", reduced_document["intent"])
    bindings = cast("dict[str, str]", intent["bindings"])
    _require(
        bindings["source_bundle_id"] == bundle_id and bindings["source_report_id"] == report_id,
        "Reduction belongs to another pinned source",
    )
    artifacts = {
        "recipe": _read(ledger, bindings["recipe_id"], role_limit("recipe"), observed),
        "materialization": _read(
            ledger,
            bindings["materialization_sha256"],
            role_limit("materialization"),
            observed,
        ),
        "normalized": _read(
            ledger, bindings["normalized_sha256"], role_limit("normalized"), observed
        ),
    }
    preparation = _Preparation(
        bindings["preparation_id"],
        _read(ledger, bindings["preparation_manifest_sha256"], 64 * 1024, observed),
        tuple(sorted(artifacts.items())),
    )
    prepared, _ = _prepare(preparation, snapshot, bindings["preparation_id"])
    protocol = prepared.materialization.source.validation.protocol
    _require(
        protocol.canonical_bytes == source_protocol.canonical_bytes,
        "Comparison preparation belongs to another original protocol",
    )
    _checked_prefix(snapshot, protocol, ledger)
    original_run_id = prepared.materialization.source.source_run_id
    source_artifacts = snapshot.artifacts
    try:
        original_raw = source_artifacts[f"cas/{original_run_id}"]
        original = load_scenario_run_receipt(original_raw)
        original_bindings = cast("dict[str, str]", original.document["bindings"])
        original_result_raw = source_artifacts["cas/" + original_bindings["replay_result_sha256"]]
    except KeyError as error:
        raise EvidenceValidationError("Original witness CAS closure is incomplete") from error
    _require(
        original.run_id == original_run_id
        and digest(original_raw) == original_run_id
        and digest(original_result_raw) == original_bindings["replay_result_sha256"],
        "Original witness differs from the pinned source content",
    )
    _require(
        _read(ledger, original_run_id, 16 * 1024, observed) == original_raw
        and _read(ledger, original_bindings["replay_result_sha256"], _RESULT_LIMIT, observed)
        == original_result_raw,
        "Original witness differs from its live content closure",
    )
    reduced_bindings = cast("dict[str, str]", reduced_document["bindings"])
    reduced_result = load_replay_result(
        _read(ledger, reduced_bindings["replay_result_sha256"], _RESULT_LIMIT, observed)
    )
    _require(
        _read(
            ledger,
            reduced_bindings["state_audit_sha256"],
            MAX_REDUCTION_STATE_AUDIT_BYTES,
            observed,
        )
        == canonical(cast("Row", inspected["state_audit"])),
        "Reduction state audit changed after independent inspection",
    )
    original_reservation, reduced_reservation = (
        _reservation(original.document),
        _reservation(reduced_document),
    )
    original_intent = canonical(cast("Row", original.document["intent"]))
    reduced_intent = canonical(intent)
    for reservation, outcome, committed_intent in (
        (original_reservation, original_raw, original_intent),
        (reduced_reservation, reduced_raw, reduced_intent),
    ):
        _committed(ledger, reservation, outcome, committed_intent)
    comparison = ReductionComparison(
        authority=authority,
        materialized=prepared.materialization,
        original_receipt=original,
        original_result=load_replay_result(original_result_raw),
        reduced_receipt=reduced,
        reduced_result=reduced_result,
    )
    # Recheck observed content, including original source CAS, after all domain
    # computation. A newly appended legal suffix is allowed; replacement is not.
    _checked_prefix(snapshot, protocol, ledger)
    for reservation, outcome, committed_intent in (
        (original_reservation, original_raw, original_intent),
        (reduced_reservation, reduced_raw, reduced_intent),
    ):
        _committed(ledger, reservation, outcome, committed_intent)
    for sha, raw, limit in observed:
        _require(
            ledger.read_artifact(sha, max_bytes=limit) == raw,
            "Observed comparison artifact changed between reads",
        )
    return comparison


def verify_reduction_comparison(
    run_id: str,
    export_raw: bytes,
    *,
    expected_comparison_id: str,
    source: SearchEvidencePackage,
    expected_bundle_id: str,
    expected_report_id: str,
    split: str,
    ledger_factory: Callable[[], ReductionLedger],
) -> ReductionComparison:
    """Verify saved presentation only by rebuilding its actual immutable evidence."""
    _development(split)
    requested = identity(run_id)
    expected = identity(expected_comparison_id)
    bundle_id, report_id = identity(expected_bundle_id), identity(expected_report_id)
    comparison_id, _ = load_reduction_comparison_export(export_raw)
    _require(comparison_id == expected, "Comparison export differs from its expected pin")
    comparison = compare_reduction_run(
        requested,
        source=source,
        expected_bundle_id=bundle_id,
        expected_report_id=report_id,
        split="development",
        ledger_factory=ledger_factory,
    )
    _require(
        comparison.comparison_id == expected and comparison.export_bytes == export_raw,
        "Saved comparison differs from independently recomputed actual evidence",
    )
    return comparison
