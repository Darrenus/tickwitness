"""Offline semantic closure uses recorded remote native evidence, never a fake engine.

The golden preserves actual #85 native callbacks and persisted receipts. Dataset
bytes reproduce the installed smoke's original synthetic source construction;
its manifest identity must match the already-recorded frozen protocol.
"""

import json
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.domain.evidence.tagged_pair_verification import (
    assess_tagged_pair_artifacts,
    verify_tagged_pair_artifacts,
)
from tickwitness.domain.evidence.tagged_queue_records import load_tagged_queue_run_receipt
from tickwitness.domain.replay._validation import ReplayValidationError
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "fixtures" / "tagged-pair-native-golden.json"
ERRORS = (EvidenceValidationError, ReplayValidationError, ProtocolValidationError)


def actual_artifacts(final_mark=100):
    recorded = json.loads(GOLDEN.read_bytes())
    assert recorded["provenance"]["engineering_run"] == 40286175944
    assert recorded["provenance"]["job"] == 121450395382
    selected = next(case for case in recorded["cases"] if case["final_mark_ticks"] == final_mark)
    rows = [
        json.loads(line)
        for line in (ROOT / "examples" / "queue-observations.jsonl").read_bytes().splitlines()
    ]
    if final_mark != 100:
        rows[-1]["bids"].append([final_mark, 2])
    raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
    validated = normalize_events(raw)
    artifacts = {
        "protocol": canonical(selected["protocol"]),
        "raw": raw,
        "normalized": validated.normalized_bytes,
        "report": canonical(validated.report),
    }
    manifest = {
        "schema_version": 1,
        "format_id": "tickwitness.normalized-events.v1",
        "objects": {
            role: {
                "sha256": digest(artifacts[role]),
                "size_bytes": len(artifacts[role]),
                "ref": "objects/sha256/" + digest(artifacts[role]),
            }
            for role in ("raw", "normalized", "report")
        },
    }
    artifacts["dataset_manifest"] = canonical(manifest)
    assert (
        digest(artifacts["dataset_manifest"])
        == selected["protocol"]["bindings"]["development_dataset_id"]
    )
    for prefix, run in zip(("front", "back"), selected["runs"], strict=True):
        for role in ("result", "evaluation", "receipt"):
            artifacts[f"{prefix}_{role}"] = canonical(run[role])
        receipt = load_tagged_queue_run_receipt(artifacts[f"{prefix}_receipt"])
        assert receipt.document["bindings"]["replay_result_sha256"] == digest(
            artifacts[f"{prefix}_result"]
        )
        assert receipt.document["bindings"]["evaluation_sha256"] == digest(
            artifacts[f"{prefix}_evaluation"]
        )
    return artifacts


def _rewrite(artifacts, role, update):
    document = json.loads(artifacts[role])
    update(document)
    artifacts[role] = canonical(document)


def _rehash_run(artifacts, prefix):
    """Close hashes after an attack, so only independent semantics can reject it."""
    result_hash = digest(artifacts[f"{prefix}_result"])
    _rewrite(
        artifacts, f"{prefix}_evaluation", lambda doc: doc.update(replay_result_sha256=result_hash)
    )
    evaluation_hash = digest(artifacts[f"{prefix}_evaluation"])
    _rewrite(
        artifacts,
        f"{prefix}_receipt",
        lambda doc: doc["bindings"].update(
            replay_result_sha256=result_hash, evaluation_sha256=evaluation_hash
        ),
    )


def _sealed(artifacts):
    return {**artifacts, "assessment": assess_tagged_pair_artifacts(artifacts).canonical_bytes}


@pytest.mark.parametrize(
    "final_mark,truths,relation,pnl",
    [
        (100, [False, False], "same_truth_value", ["-2", "0"]),
        (102, [True, False], "opposite_truth_values", ["2", "0"]),
    ],
)
def test_actual_remote_native_goldens_reproduce_without_native(final_mark, truths, relation, pnl):
    artifacts = actual_artifacts(final_mark)
    assessment = assess_tagged_pair_artifacts(artifacts)
    doc = assessment.document
    assert doc["comparison"]["truths"] == truths
    assert doc["comparison"]["relation"] == relation
    assert doc["comparison"]["same_execution_environment"] is True
    assert doc["comparison"]["ineligible_reason"] is None
    assert [run["valuation"]["net_marked_pnl"] for run in doc["runs"]] == pnl
    assert [run["horizon"]["native_target_lots"] for run in doc["runs"]] == [2, 2]
    assert doc["bindings"] == {role: digest(raw) for role, raw in artifacts.items()}
    assert doc["findings"] == [] and doc["scope"]["finding_issued"] is False
    assert doc["scope"]["source_claim_evaluated"] is False
    receipt = verify_tagged_pair_artifacts({**artifacts, "assessment": assessment.canonical_bytes})
    assert receipt["assessment"] == doc
    assert receipt["assessment_id"] == assessment.assessment_id
    for key in (
        "integrity_verified",
        "bindings_verified",
        "source_revalidated",
        "queue_execution_audited",
    ):
        assert receipt[key] is True
    for key in (
        "native_replayed",
        "author_signature_verified",
        "confirmation_reference_checked",
        "full_attempt_ledger_checked",
        "ledger_commitment_checked",
    ):
        assert receipt[key] is False


def test_fully_rehashed_false_inventory_value_is_not_certified():
    artifacts = actual_artifacts()

    def fake_value(doc):
        doc["valuation"]["net_marked_pnl"] = "2"
        doc["claim_evaluation"]["truth"] = True

    _rewrite(artifacts, "front_evaluation", fake_value)
    _rehash_run(artifacts, "front")
    with pytest.raises(ERRORS):
        assess_tagged_pair_artifacts(artifacts)


@pytest.mark.parametrize(
    "attack", ["trade_double_count", "clock", "acceptance", "horizon", "cleanup", "native_fee"]
)
def test_fully_rehashed_native_evidence_requires_independent_source_audit(attack):
    artifacts = actual_artifacts()

    def corrupt(doc):
        if attack == "trade_double_count":
            row = next(row for row in doc["queue_trace"] if row["kind"] == "trade")
            row["flow"]["external_trade_behind_lots"] += 1
        elif attack == "clock":
            doc["input_trace"][0]["native_time_ns"] += 1
        elif attack == "acceptance":
            row = next(row for row in doc["order_trace"] if row["kind"] == "OrderAccepted")
            row["fields"]["actual_acceptance"]["acceptance_role"] = "historical_owner"
        elif attack == "horizon":
            doc["horizon_snapshot"]["native_target_lots"] += 1
        elif attack == "cleanup":
            doc["cleanup"]["projected_total_after_cleanup"] += 1
        else:
            doc["fill_trace"][0]["fields"]["commission"] = "3"

    _rewrite(artifacts, "front_result", corrupt)
    _rehash_run(artifacts, "front")
    with pytest.raises(ERRORS):
        assess_tagged_pair_artifacts(artifacts)


def test_two_distinct_reservation_ids_cannot_occupy_the_same_budget_slot():
    artifacts = actual_artifacts()
    front = json.loads(artifacts["front_receipt"])
    _rewrite(
        artifacts,
        "back_receipt",
        lambda doc: doc["attempt"].update(attempt_index=front["attempt"]["attempt_index"]),
    )
    assert digest(artifacts["front_receipt"]) != digest(artifacts["back_receipt"])
    with pytest.raises(ERRORS):
        assess_tagged_pair_artifacts(artifacts)


def test_reverse_execution_indices_still_keep_canonical_policy_roles():
    artifacts = actual_artifacts()
    _rewrite(artifacts, "front_receipt", lambda doc: doc["attempt"].update(attempt_index=2))
    _rewrite(artifacts, "back_receipt", lambda doc: doc["attempt"].update(attempt_index=1))
    assessment = assess_tagged_pair_artifacts(artifacts).document
    assert [run["role"] for run in assessment["runs"]] == ["front", "back"]
    assert [run["attempt_index"] for run in assessment["runs"]] == [2, 1]
    assert assessment["comparison"]["relation"] == "same_truth_value"


@pytest.mark.parametrize("attack", ["policy", "wall", "claim", "bool_index", "incomplete"])
def test_receipt_cannot_cross_policy_claim_budget_or_execution(attack):
    artifacts = actual_artifacts()

    def corrupt(doc):
        if attack == "policy":
            doc["intent"]["policy_id"] = "protected_tag_front_cancel_v1"
        elif attack == "wall":
            doc["attempt"]["max_wall_seconds"] -= 1
        elif attack == "claim":
            doc["claim_revision_id"] = "f" * 64
        elif attack == "bool_index":
            doc["attempt"]["attempt_index"] = True
        else:
            doc["execution_status"] = "incomplete"

    _rewrite(artifacts, "back_receipt", corrupt)
    with pytest.raises(ERRORS):
        assess_tagged_pair_artifacts(artifacts)


def test_different_environment_seals_audited_evidence_but_withholds_comparison():
    artifacts = actual_artifacts(102)
    _rewrite(
        artifacts,
        "back_result",
        lambda doc: doc["environment"].update(platform="different platform"),
    )
    _rehash_run(artifacts, "back")
    doc = assess_tagged_pair_artifacts(artifacts).document
    assert doc["comparison"]["same_execution_environment"] is False
    assert doc["comparison"]["truths"] == [True, False]
    assert doc["comparison"]["relation"] == "ineligible"
    assert doc["comparison"]["ineligible_reason"] == "execution_environment_mismatch"
    assert doc["findings"] == []
    assert verify_tagged_pair_artifacts(_sealed(artifacts))["queue_execution_audited"] is True


@pytest.mark.parametrize("attack", ["truth", "relation", "scope", "finding", "binding", "unknown"])
def test_rehashed_assessment_is_recomputed_not_trusted(attack):
    artifacts = _sealed(actual_artifacts(102))

    def corrupt(doc):
        if attack == "truth":
            doc["comparison"]["truths"] = [True, True]
        elif attack == "relation":
            doc["comparison"]["relation"] = "same_truth_value"
        elif attack == "scope":
            doc["scope"]["historical_owner_verified"] = True
        elif attack == "finding":
            doc["findings"] = [{"type": "NOT_IDENTIFIABLE_WITHIN_MODEL"}]
        elif attack == "binding":
            doc["bindings"]["front_result"] = "0" * 64
        else:
            doc["extra"] = "not permitted"

    _rewrite(artifacts, "assessment", corrupt)
    with pytest.raises(ERRORS):
        verify_tagged_pair_artifacts(artifacts)


@pytest.mark.parametrize("role", ["raw", "normalized", "report", "dataset_manifest"])
def test_dataset_closure_cannot_be_replaced_or_detached(role):
    artifacts = actual_artifacts()
    artifacts[role] = artifacts[role] + b" "
    with pytest.raises(ERRORS):
        assess_tagged_pair_artifacts(artifacts)


@pytest.mark.parametrize("mutation", ["missing", "extra", "mutable", "empty"])
def test_pair_artifact_roles_and_immutable_bytes_are_exact(mutation):
    artifacts = actual_artifacts()
    if mutation == "missing":
        del artifacts["front_result"]
    elif mutation == "extra":
        artifacts["confirmation"] = b"secret"
    elif mutation == "mutable":
        artifacts["raw"] = bytearray(artifacts["raw"])
    else:
        artifacts["raw"] = b""
    with pytest.raises(ERRORS):
        assess_tagged_pair_artifacts(artifacts)
