"""Final finding rules consume actual recorded remote native evidence only."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from test_tagged_pair_verification import actual_artifacts

from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.domain.evidence.tagged_finding_report import (
    FINDING_ARTIFACT_ROLES,
    TaggedFindingIneligibleError,
    TaggedFindingReport,
    build_tagged_finding_report,
    load_tagged_finding_report,
    tagged_pair_bundle_id,
    verify_tagged_finding_artifacts,
)
from tickwitness.domain.evidence.tagged_pair_verification import assess_tagged_pair_artifacts
from tickwitness.domain.evidence.tagged_queue_evaluation import evaluate_tagged_queue_replay
from tickwitness.domain.evidence.tagged_queue_records import build_tagged_queue_run_receipt
from tickwitness.domain.replay.tagged_queue_contracts import TaggedQueueReplayInput, build_tagged_queue_replay_result
from tickwitness.domain.research_contracts.tagged_finding_protocol import build_tagged_finding_protocol
from tickwitness.domain.research_contracts.tagged_queue_protocol import load_tagged_queue_protocol

ROOT = Path(__file__).resolve().parents[2]


def finding_pair(case="false_false"):
    if case == "true_true":
        recorded = json.loads((ROOT / "tests/fixtures/tagged-finding-ge-native-golden.json").read_bytes())
        assert recorded["provenance"]["engineering_run"] == 40292165942
        assert recorded["provenance"]["job"] == 121469735870
        artifacts = {role: raw.encode() for role, raw in recorded["artifacts"].items()}
        assert digest(recorded["source_manifest_bytes"].encode()) == tagged_pair_bundle_id(artifacts)
        return artifacts
    artifacts = actual_artifacts(100 if case == "false_false" else 102)
    artifacts["assessment"] = assess_tagged_pair_artifacts(artifacts).canonical_bytes
    return artifacts


def authority(artifacts):
    return build_tagged_finding_protocol(canonical({"kind": "tagged_finding_request_v1", "schema_version": 1,
        "title": "Conditional tagged finding rule regression", "authority": "conditional_tagged_findings_v1"}),
        subject_protocol=load_tagged_queue_protocol(artifacts["protocol"]))


@pytest.fixture(scope="module")
def reports():
    return {case: (finding_pair(case), build_tagged_finding_report(authority(finding_pair(case)), finding_pair(case)))
            for case in ("false_false", "true_false", "true_true")}


@pytest.mark.parametrize("case,types,truths", [
    ("false_false", ["COUNTEREXAMPLE_FOUND"], [False, False]),
    ("true_false", ["NOT_IDENTIFIABLE_WITHIN_MODEL", "COUNTEREXAMPLE_FOUND"], [True, False]),
    ("true_true", ["NO_COUNTEREXAMPLE_FOUND"], [True, True]),
])
def test_three_prescribed_rules_from_actual_remote_native_records(reports, case, types, truths):
    artifacts, report = reports[case]
    document = report.document
    assert [finding["type"] for finding in document["findings"]] == types
    assert [row["truth"] for row in document["assessment"]["runs"]] == truths
    assert document["finalization"] == {"source_evidence_state": "CONTENT_CLOSED", "report_publication_state": "UNASSERTED"}
    assert document["execution_status"] == "completed"
    assert document["source_pair_bundle_id"] == tagged_pair_bundle_id(artifacts)
    assert document["completeness"]["coverage_complete_for_listed_policies"] is True
    assert document["completeness"]["admissible_world_space_exhausted"] is False
    assert document["scope"]["source_claim_evaluated"] is False
    assert document["finding_protocol"]["subject_protocol"]["scope"]["finding_issued"] is False
    for finding in document["findings"]:
        assert finding["scope"] == document["scope"]
        assert finding["limitations"]
        refs = finding["witnesses"]
        assert all(ref["result_sha256"] == document["evidence_bindings"][ref["role"] + "_result"] for ref in refs)
        if finding["type"] == "NOT_IDENTIFIABLE_WITHIN_MODEL":
            assert finding["conclusion_target"] == "per_interpretation_predicate_truth_given_public_observations_v1"
            assert len(refs) == 2 and {ref["truth"] for ref in refs} == {True, False}
        elif finding["type"] == "COUNTEREXAMPLE_FOUND":
            assert finding["conclusion_target"] == "robust_satisfaction_across_listed_witnesses_v1"
            assert refs and all(ref["truth"] is False for ref in refs)
        else:
            assert finding["conclusion_target"] == "robust_satisfaction_across_listed_witnesses_v1"
            assert len(refs) == 2 and all(ref["truth"] is True for ref in refs)
    assert load_tagged_finding_report(report.canonical_bytes) == report


def test_full_fourteen_artifacts_reproduce_the_report_and_subject(reports):
    artifacts, report = reports["true_false"]
    protocol = authority(artifacts)
    package = {**artifacts, "finding_protocol": protocol.canonical_bytes, "finding_report": report.canonical_bytes}
    assert package.keys() == FINDING_ARTIFACT_ROLES
    assert verify_tagged_finding_artifacts(package) == report
    assert report.report_id == digest(report.canonical_bytes)
    view = report.document
    view["findings"] = []
    assert report.document["findings"]
    with pytest.raises(FrozenInstanceError):
        report.canonical_bytes = b"{}"


@pytest.mark.parametrize("attack", ["claim", "authority", "source", "finding_type", "counter_witness", "same_truth_notid", "scope", "completeness", "final_publication", "final_status", "limitations", "binding", "unknown", "version_bool"])
def test_rehashed_report_cannot_rewrite_rubric_scope_or_publication(reports, attack):
    _, original = reports["true_false"]
    doc = original.document
    if attack == "claim":
        doc["claim_revision_id"] = "0" * 64
    elif attack == "authority":
        doc["finding_protocol"]["authority"]["source_claim_authority_granted"] = True
    elif attack == "source":
        doc["subject_protocol_id"] = "0" * 64
    elif attack == "finding_type":
        doc["findings"][1]["type"] = "NO_COUNTEREXAMPLE_FOUND"
    elif attack == "counter_witness":
        doc["findings"][1]["witnesses"] = doc["findings"][0]["witnesses"]
    elif attack == "same_truth_notid":
        doc["findings"][0]["witnesses"][0]["truth"] = False
    elif attack == "scope":
        doc["findings"][0]["scope"]["market_impact_verified"] = True
    elif attack == "completeness":
        doc["completeness"]["admissible_world_space_exhausted"] = True
    elif attack == "final_publication":
        doc["finalization"]["report_publication_state"] = "PUBLISHED"
    elif attack == "final_status":
        doc["execution_status"] = "failed"
    elif attack == "limitations":
        doc["limitations"] = []
    elif attack == "binding":
        doc["evidence_bindings"]["front_result"] = "0" * 64
    elif attack == "version_bool":
        doc["schema_version"] = True
    else:
        doc["author_signature_verified"] = True
    with pytest.raises(EvidenceValidationError):
        TaggedFindingReport(canonical(doc))


def test_valid_but_different_execution_environments_refuse_issuance_without_erasing_source():
    artifacts = finding_pair("true_false")
    subject = load_tagged_queue_protocol(artifacts["protocol"])
    result_doc = json.loads(artifacts["back_result"])
    result_doc["environment"]["platform"] += "-different-context"
    result = build_tagged_queue_replay_result(result_doc)
    request = TaggedQueueReplayInput(subject, artifacts["normalized"], subject.document["policies"][1])
    evaluation = evaluate_tagged_queue_replay(request, result)
    receipt = json.loads(artifacts["back_receipt"])
    receipt["bindings"] = {"replay_result_sha256": digest(result.canonical_bytes), "evaluation_sha256": evaluation.evaluation_id}
    artifacts.update(back_result=result.canonical_bytes, back_evaluation=evaluation.canonical_bytes,
                     back_receipt=build_tagged_queue_run_receipt(receipt).canonical_bytes)
    artifacts.pop("assessment")
    artifacts["assessment"] = assess_tagged_pair_artifacts(artifacts).canonical_bytes
    before = dict(artifacts)
    with pytest.raises(TaggedFindingIneligibleError) as rejected:
        build_tagged_finding_report(authority(artifacts), artifacts)
    assert rejected.value.reason == "execution_environment_mismatch"
    assert rejected.value.source_pair_bundle_id == tagged_pair_bundle_id(artifacts)
    assert artifacts == before
    assert json.loads(artifacts["front_evaluation"])["claim_evaluation"]["truth"] is True
    assert json.loads(artifacts["back_evaluation"])["claim_evaluation"]["truth"] is False


def test_corrupt_callbacks_after_all_hashes_are_reclosed_are_errors_not_findings(reports):
    artifacts, report = reports["true_false"]
    payload = dict(artifacts)
    result = json.loads(payload["front_result"])
    result["queue_trace"][3]["flow"]["own_trade_lots"] += 1
    payload["front_result"] = canonical(result)
    evaluation = json.loads(payload["front_evaluation"])
    evaluation["replay_result_sha256"] = digest(payload["front_result"])
    payload["front_evaluation"] = canonical(evaluation)
    receipt = json.loads(payload["front_receipt"])
    receipt["bindings"] = {"replay_result_sha256": digest(payload["front_result"]), "evaluation_sha256": digest(payload["front_evaluation"])}
    payload["front_receipt"] = canonical(receipt)
    with pytest.raises(EvidenceValidationError):
        build_tagged_finding_report(authority(artifacts), payload)
    package = {**payload, "finding_protocol": authority(artifacts).canonical_bytes, "finding_report": report.canonical_bytes}
    with pytest.raises(EvidenceValidationError):
        verify_tagged_finding_artifacts(package)


def test_different_subject_or_missing_source_cannot_receive_authority(reports):
    artifacts, report = reports["true_false"]
    with pytest.raises(EvidenceValidationError, match="subject"):
        build_tagged_finding_report(authority(finding_pair("false_false")), artifacts)
    package = {**artifacts, "finding_protocol": authority(artifacts).canonical_bytes, "finding_report": report.canonical_bytes}
    package.pop("raw")
    with pytest.raises(EvidenceValidationError):
        verify_tagged_finding_artifacts(package)
