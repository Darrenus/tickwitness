"""Separate authority and no-publication-on-error finding issuance boundaries."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_tagged_pair_package import golden_payload

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_findings import (
    freeze_finding_protocol, inspect_finding_protocol, issue_tagged_findings, verify_finding_package,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.domain.evidence.tagged_finding_report import (
    TaggedFindingIneligibleError, build_tagged_finding_report,
)
from tickwitness.domain.evidence.tagged_pair_verification import assess_tagged_pair_artifacts
from tickwitness.domain.evidence.tagged_queue_evaluation import evaluate_tagged_queue_replay
from tickwitness.domain.evidence.tagged_queue_records import build_tagged_queue_run_receipt
from tickwitness.domain.replay.tagged_queue_contracts import TaggedQueueReplayInput, build_tagged_queue_replay_result
from tickwitness.domain.research_contracts.tagged_finding_protocol import build_tagged_finding_protocol
from tickwitness.domain.research_contracts.tagged_queue_protocol import load_tagged_queue_protocol
from tickwitness.infrastructure.tagged_evidence_bundles import export_tagged_pair_bundle
from tickwitness.infrastructure.tagged_finding_bundles import export_tagged_finding_bundle, read_tagged_finding_bundle
from tickwitness.infrastructure.tagged_finding_registry import LocalTaggedFindingRegistry
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry

ROOT = Path(__file__).resolve().parents[2]


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _publish(path):
    def publish(artifacts):
        export_tagged_finding_bundle(path, artifacts)
        return read_tagged_finding_bundle(path)
    return publish


@pytest.fixture
def finding_case(tmp_path):
    pair = golden_payload()
    source = export_tagged_pair_bundle(tmp_path / "pair", pair)
    subjects = LocalTaggedQueueRegistry(tmp_path / "registry", create=True)
    subject = load_tagged_queue_protocol(pair["protocol"])
    subjects.seal(subject.canonical_bytes)
    findings = LocalTaggedFindingRegistry(tmp_path / "registry", create=True)
    request = (ROOT / "examples/tagged-finding-request.json").read_bytes()
    frozen = freeze_finding_protocol(subject.protocol_id, request, split="development",
        subjects_factory=lambda: subjects, findings_factory=lambda: findings)
    return SimpleNamespace(root=tmp_path, pair=pair, source=source, subject=subject,
        subjects=subjects, findings=findings, request=request, frozen=frozen,
        finding_id=frozen.protocol.protocol_id)


def test_freeze_is_separate_idempotent_and_preserves_execution_authority(finding_case):
    c = finding_case
    before = _tree(c.root / "registry")
    repeated = freeze_finding_protocol(c.subject.protocol_id, c.request, split="development",
        subjects_factory=lambda: c.subjects, findings_factory=lambda: c.findings)
    assert repeated.created is False and repeated.protocol == c.frozen.protocol
    inspected = inspect_finding_protocol(c.finding_id, findings_factory=lambda: c.findings)
    assert inspected["protocol"] == c.frozen.protocol.document
    assert c.frozen.protocol.subject_protocol.canonical_bytes == c.subject.canonical_bytes
    assert c.subject.document["scope"]["finding_issued"] is False
    assert c.subjects.get(c.subject.protocol_id).canonical_bytes == c.subject.canonical_bytes
    assert _tree(c.root / "registry") == before


def test_final_receipt_follows_closed_report_publication_without_authentication_claims(finding_case):
    c = finding_case
    before_source, before_registry = _tree(c.root / "pair"), _tree(c.root / "registry")
    result = issue_tagged_findings(c.finding_id, expected_source_bundle_id=c.source.bundle_id,
        split="development", findings_factory=lambda: c.findings, source_factory=lambda: c.source,
        publisher=_publish(c.root / "report"))
    assert result["finalization_status"] == "FINAL"
    assert result["source_pair_bundle_id"] == c.source.bundle_id
    assert result["finding_protocol_id"] == c.finding_id
    assert [f["type"] for f in result["report"]["findings"]] == ["COUNTEREXAMPLE_FOUND"]
    assert result["report"]["finalization"]["report_publication_state"] == "UNASSERTED"
    for name in ("native_replayed", "author_signature_verified", "human_domain_approval_verified",
                 "original_publication_verified", "confirmation_reference_checked",
                 "full_attempt_ledger_checked", "ledger_commitment_checked"):
        assert result[name] is False
    assert result == verify_finding_package(read_tagged_finding_bundle(c.root / "report"), expected_bundle_id=result["bundle_id"])
    assert _tree(c.root / "pair") == before_source and _tree(c.root / "registry") == before_registry


def test_issuer_wrong_pin_or_subject_never_calls_publisher(finding_case):
    c = finding_case
    def forbidden(artifacts):
        pytest.fail("Ineligible request cannot publish")
    with pytest.raises(EvidenceValidationError, match="pinned identity"):
        issue_tagged_findings(c.finding_id, expected_source_bundle_id="0" * 64, split="development",
            findings_factory=lambda: c.findings, source_factory=lambda: c.source, publisher=forbidden)
    other = export_tagged_pair_bundle(c.root / "other-source", golden_payload(102))
    with pytest.raises(EvidenceValidationError, match="frozen subject"):
        issue_tagged_findings(c.finding_id, expected_source_bundle_id=other.bundle_id, split="development",
            findings_factory=lambda: c.findings, source_factory=lambda: other, publisher=forbidden)


def test_verified_environment_mismatch_is_not_rewritten_as_a_finding(finding_case):
    c = finding_case
    payload = dict(c.pair)
    changed = json.loads(payload["back_result"])
    changed["environment"]["platform"] += " different-context"
    result = build_tagged_queue_replay_result(changed)
    request = TaggedQueueReplayInput(c.subject, payload["normalized"], changed["bindings"]["policy_id"])
    evaluation = evaluate_tagged_queue_replay(request, result)
    receipt = json.loads(payload["back_receipt"])
    receipt["bindings"] = {"replay_result_sha256": digest(result.canonical_bytes), "evaluation_sha256": evaluation.evaluation_id}
    payload.update(back_result=result.canonical_bytes, back_evaluation=evaluation.canonical_bytes,
                   back_receipt=build_tagged_queue_run_receipt(receipt).canonical_bytes)
    del payload["assessment"]
    payload["assessment"] = assess_tagged_pair_artifacts(payload).canonical_bytes
    source = export_tagged_pair_bundle(c.root / "ineligible", payload)
    before = _tree(c.root / "ineligible")
    def forbidden(artifacts):
        pytest.fail("Verified but ineligible pair cannot publish a report")
    with pytest.raises(TaggedFindingIneligibleError) as error:
        issue_tagged_findings(c.finding_id, expected_source_bundle_id=source.bundle_id, split="development",
            findings_factory=lambda: c.findings, source_factory=lambda: source, publisher=forbidden)
    assert error.value.reason == "execution_environment_mismatch"
    assert error.value.source_pair_bundle_id == source.bundle_id
    assert evaluation.document["claim_evaluation"]["truth"] is False
    assert _tree(c.root / "ineligible") == before


def test_publisher_cannot_substitute_another_valid_authority(finding_case):
    c = finding_case
    request = json.loads(c.request)
    request["title"] += " alternative authority"
    other_protocol = build_tagged_finding_protocol(canonical(request), subject_protocol=c.subject)
    other_report = build_tagged_finding_report(other_protocol, c.pair)
    other = export_tagged_finding_bundle(c.root / "other-report", {**c.pair,
        "finding_protocol": other_protocol.canonical_bytes, "finding_report": other_report.canonical_bytes})
    assert verify_finding_package(other)["report_id"] == other_report.report_id
    with pytest.raises(EvidenceValidationError, match="different evidence"):
        issue_tagged_findings(c.finding_id, expected_source_bundle_id=c.source.bundle_id, split="development",
            findings_factory=lambda: c.findings, source_factory=lambda: c.source, publisher=lambda _: other)


def test_verifier_pin_precedes_semantic_artifact_access():
    class Untouched:
        bundle_id = "a" * 64
        def __getattr__(self, name):
            pytest.fail("Wrong pin must fail before accessing remaining package fields")
    with pytest.raises(EvidenceValidationError, match="pinned identity"):
        verify_finding_package(Untouched(), expected_bundle_id="b" * 64)


def test_confirmation_refused_before_factories_or_package_fields():
    def forbidden(*args):
        pytest.fail("No confirmation access")
    with pytest.raises(ConfirmationAccessDenied):
        freeze_finding_protocol("bad", b"bad", split="confirmation", subjects_factory=forbidden, findings_factory=forbidden)
    with pytest.raises(ConfirmationAccessDenied):
        inspect_finding_protocol("bad", split="confirmation", findings_factory=forbidden)
    with pytest.raises(ConfirmationAccessDenied):
        issue_tagged_findings("bad", expected_source_bundle_id="bad", split="confirmation",
            findings_factory=forbidden, source_factory=forbidden, publisher=forbidden)
    with pytest.raises(ConfirmationAccessDenied):
        verify_finding_package(SimpleNamespace(), split="confirmation")
