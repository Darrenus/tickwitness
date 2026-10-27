"""Reporting authority is a separate immutable contract, never a source upgrade."""

import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from test_tagged_pair_verification import actual_artifacts

from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.research_contracts.tagged_finding_protocol import (
    FINDING_AUTHORITY_ID,
    FINDING_LIMITATIONS,
    FINDING_RULES,
    FINDING_SCOPE,
    FINDING_TYPES,
    TaggedFindingProtocol,
    TaggedFindingValidationError,
    build_tagged_finding_protocol,
    load_tagged_finding_protocol,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import load_tagged_queue_protocol


def finding_request(title="Conditional tagged findings"):
    return {
        "kind": "tagged_finding_request_v1",
        "schema_version": 1,
        "title": title,
        "authority": FINDING_AUTHORITY_ID,
    }


def subject():
    return load_tagged_queue_protocol(actual_artifacts()["protocol"])


def build(request=None):
    return build_tagged_finding_protocol(
        canonical(finding_request() if request is None else request), subject_protocol=subject()
    )


def test_finding_authority_binds_full_unchanged_subject_and_own_rules():
    original = subject()
    before = original.canonical_bytes
    protocol = build_tagged_finding_protocol(
        canonical(finding_request()), subject_protocol=original
    )
    document = protocol.document
    assert protocol.subject_protocol == original
    assert document["subject_protocol"] == original.document
    assert original.canonical_bytes == before
    assert document["subject_protocol"]["scope"]["finding_issued"] is False
    assert document["authority"]["id"] == FINDING_AUTHORITY_ID
    assert document["authority"]["allowed_finding_types"] == list(FINDING_TYPES)
    assert document["authority"]["execution_authority_extended"] is False
    assert document["authority"]["source_claim_authority_granted"] is False
    assert document["authority"]["truth_target"] == "frozen_predicate_per_hidden_allocation_v1"
    assert (
        document["authority"]["counterexample_quantifier"] == "for_all_listed_policy_witnesses_v1"
    )
    assert "quantifier" not in document["authority"]
    assert document["rules"] == FINDING_RULES
    assert document["scope"] == FINDING_SCOPE
    assert document["limitations"] == list(FINDING_LIMITATIONS)
    assert document["bindings"]["subject_protocol_id"] == original.protocol_id
    assert document["bindings"]["claim_revision_id"] == original.claim_revision_id
    assert document["bindings"]["gross_constraint_id"] == original.constraint.constraint_id
    assert protocol.protocol_id == digest(protocol.canonical_bytes)


def test_authority_identity_roundtrip_and_detached_views():
    protocol = build()
    assert load_tagged_finding_protocol(protocol.canonical_bytes) == protocol
    assert build(finding_request("Another report title")).protocol_id != protocol.protocol_id
    document = protocol.document
    document["rules"]["true_true"] = ["COUNTEREXAMPLE_FOUND"]
    document["subject_protocol"]["scope"]["finding_issued"] = True
    assert protocol.document["rules"]["true_true"] == ["NO_COUNTEREXAMPLE_FOUND"]
    assert protocol.subject_protocol.document["scope"]["finding_issued"] is False
    with pytest.raises(FrozenInstanceError):
        protocol.protocol_id = "a" * 64
    with pytest.raises(TaggedFindingValidationError, match="identity"):
        replace(protocol, protocol_id="a" * 64)


@pytest.mark.parametrize(
    "attack",
    [
        "allowed_type",
        "source_authority",
        "execution_authority",
        "scope",
        "rules",
        "evidence_policy",
        "report_policy",
        "policy_order",
        "binding",
        "subject_scope",
        "version_bool",
        "extra",
    ],
)
def test_rehashed_contract_cannot_change_authority_or_source(attack):
    doc = build().document
    if attack == "allowed_type":
        doc["authority"]["allowed_finding_types"].append("INSUFFICIENT_EVIDENCE")
    elif attack in ("source_authority", "execution_authority"):
        key = (
            "source_claim_authority_granted"
            if attack == "source_authority"
            else "execution_authority_extended"
        )
        doc["authority"][key] = True
    elif attack == "scope":
        doc["scope"]["market_impact_verified"] = True
    elif attack == "rules":
        doc["rules"]["false_false"] = ["NO_COUNTEREXAMPLE_FOUND"]
    elif attack in ("evidence_policy", "report_policy"):
        doc[attack] = "unapproved_v1"
    elif attack == "policy_order":
        doc["policies"].reverse()
    elif attack == "binding":
        doc["bindings"]["claim_revision_id"] = "0" * 64
    elif attack == "subject_scope":
        doc["subject_protocol"]["scope"]["finding_issued"] = True
    elif attack == "version_bool":
        doc["schema_version"] = True
    else:
        doc["claim_override"] = "positive"
    raw = canonical(doc)
    with pytest.raises(TaggedFindingValidationError):
        TaggedFindingProtocol(digest(raw), raw)


@pytest.mark.parametrize(
    "declaration",
    [
        {**finding_request(), "schema_version": True},
        {**finding_request(), "authority": "arbitrary_findings_v1"},
        {**finding_request(), "kind": "tagged_queue_request_v1"},
        {**finding_request(), "threshold": "-999"},
        finding_request(" padded "),
        finding_request(""),
        finding_request("x" * 201),
    ],
)
def test_request_is_exact_bounded_and_cannot_change_claim(declaration):
    with pytest.raises(TaggedFindingValidationError):
        build(declaration)


def test_request_duplicate_float_noncanonical_and_forged_subject_boundaries():
    source = subject()
    for raw in (
        b'{"kind":"tagged_finding_request_v1","kind":"bad"}',
        b'{"kind":"tagged_finding_request_v1","schema_version":1.0,'
        b'"title":"x","authority":"conditional_tagged_findings_v1"}',
        b"{}" * 9000,
    ):
        with pytest.raises(TaggedFindingValidationError):
            build_tagged_finding_protocol(raw, subject_protocol=source)
    with pytest.raises(TaggedFindingValidationError):
        build_tagged_finding_protocol(
            canonical(finding_request()),
            subject_protocol=SimpleNamespace(
                canonical_bytes=source.canonical_bytes, protocol_id=source.protocol_id
            ),
        )
    raw = json.dumps(build().document, indent=2).encode()
    with pytest.raises(TaggedFindingValidationError):
        load_tagged_finding_protocol(raw)
