"""Stress-report authority never changes an existing execution contract."""

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from test_scenario_derivation import context

from tickwitness.domain.assumptions.specs import load_assumption_spec
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import (
    FINDING_AUTHORITY_ID,
    FINDING_LIMITATIONS,
    FINDING_SCOPE,
    SearchFindingProtocol,
    SearchFindingValidationError,
    build_search_finding_protocol,
    load_search_finding_protocol,
)
from tickwitness.domain.search.plans import build_search_plan


def finding_request(**changes):
    return {
        "kind": "search_finding_request_v1",
        "schema_version": 1,
        "title": "Finite conditional stress criterion",
        "authority": FINDING_AUTHORITY_ID,
        **changes,
    }


def frozen_plan(*, comparator="gt", threshold="0", values=None):
    validated = context()
    protocol_doc = validated.protocol.document
    protocol_doc["claim"].update(comparator=comparator, threshold=threshold)
    protocol_doc["claim_revision_id"] = digest(canonical(protocol_doc["claim"]))
    protocol = load_executable_protocol(canonical(protocol_doc))
    assumptions_doc = validated.assumptions.document
    assumptions_doc["bindings"]["protocol_id"] = protocol.protocol_id
    assumptions = load_assumption_spec(canonical(assumptions_doc))
    proposals = [0, 1] if values is None else values
    return build_search_plan(
        canonical({
            "kind": "search_plan_request_v1", "schema_version": 1, "search_seed": 7,
            "max_proposals": len(proposals), "generator": {"kind": "grid", "values_ns": proposals},
        }),
        protocol=protocol,
        assumptions=assumptions,
    )


def authority(*, comparator="gt", threshold="0", values=None):
    return build_search_finding_protocol(
        canonical(finding_request()),
        plan=frozen_plan(comparator=comparator, threshold=threshold, values=values),
    )


def test_protocol_preserves_plan_and_creates_a_distinct_conditional_predicate():
    plan = frozen_plan(values=[0, 0, 1, 20_000_001])
    before = plan.canonical_bytes
    protocol = build_search_finding_protocol(canonical(finding_request()), plan=plan)
    doc = protocol.document
    assert protocol.plan == plan and plan.canonical_bytes == before
    assert doc["plan"]["scope"]["findings_issued"] is False
    assert doc["predicate"]["criterion"] == {
        "metric": "net_marked_pnl_v1", "unit": "USD", "comparator": "gt", "threshold": "0",
    }
    assert doc["predicate"]["criterion_origin"] == "source_claim_numeric_criterion_only_v1"
    assert doc["predicate_id"] == digest(canonical(doc["predicate"]))
    assert doc["predicate_id"] != doc["bindings"]["source_claim_revision_id"]
    assert doc["predicate_id"] != protocol.protocol_id
    assert doc["scope"] == FINDING_SCOPE
    assert doc["limitations"] == list(FINDING_LIMITATIONS)
    assert doc["authority"]["execution_authority_extended"] is False
    assert doc["authority"]["source_claim_authority_granted"] is False
    assert doc["authority"]["budget_owner_changed"] is False
    assert doc["scope"]["preregistration_verified"] is False
    assert "runtime_environment_not_harmonized" in doc["limitations"]
    assert "no_delay_only_causal_attribution" in doc["limitations"]


def test_protocol_roundtrip_identity_and_detached_document():
    protocol = authority()
    assert protocol.protocol_id == digest(protocol.canonical_bytes)
    assert load_search_finding_protocol(protocol.canonical_bytes) == protocol
    doc = protocol.document
    doc["predicate"]["criterion"]["threshold"] = "1000"
    assert protocol.document["predicate"]["criterion"]["threshold"] == "0"
    with pytest.raises(FrozenInstanceError):
        protocol.protocol_id = "a" * 64
    with pytest.raises(SearchFindingValidationError, match="identity"):
        replace(protocol, protocol_id="a" * 64)


@pytest.mark.parametrize("attack", ["criterion", "predicate_id", "scope", "rules", "binding", "owner", "execution", "preregistration", "version_bool", "extra"])
def test_rehashed_protocol_cannot_promote_scope_or_choose_a_different_criterion(attack):
    doc = authority().document
    if attack == "criterion":
        doc["predicate"]["criterion"]["threshold"] = "-100"
        doc["predicate_id"] = digest(canonical(doc["predicate"]))
    elif attack == "predicate_id":
        doc["predicate_id"] = doc["bindings"]["source_claim_revision_id"]
    elif attack == "scope":
        doc["scope"]["source_claim_evaluated"] = True
    elif attack == "rules":
        doc["rules"]["valid_but_unknown_empty_failed_unfinalized"] = "NO_COUNTEREXAMPLE_FOUND"
    elif attack == "binding":
        doc["bindings"]["source_protocol_id"] = "a" * 64
    elif attack == "owner":
        doc["authority"]["budget_owner_changed"] = True
    elif attack == "execution":
        doc["authority"]["execution_authority_extended"] = True
    elif attack == "preregistration":
        doc["scope"]["preregistration_verified"] = True
    elif attack == "version_bool":
        doc["schema_version"] = True
    else:
        doc["new_authority"] = True
    raw = canonical(doc)
    with pytest.raises(SearchFindingValidationError):
        SearchFindingProtocol(digest(raw), raw)


@pytest.mark.parametrize("changes", [
    {"authority": "conditional_tagged_findings_v1"}, {"schema_version": True},
    {"title": " padded "}, {"title": ""}, {"title": "a" * 201},
    {"threshold": "-100"}, {"predicate": {"comparator": "lt"}},
])
def test_request_cannot_extend_authority_or_select_a_favorable_threshold(changes):
    with pytest.raises(SearchFindingValidationError):
        build_search_finding_protocol(canonical(finding_request(**changes)), plan=frozen_plan())


@pytest.mark.parametrize("raw", [b"", b"{}", b'{"title":"x","title":"y"}', b'{"schema_version":NaN}', b" " * 16_385])
def test_request_rejects_malformed_or_oversized_json(raw):
    with pytest.raises(SearchFindingValidationError):
        build_search_finding_protocol(raw, plan=frozen_plan())


def test_protocol_rejects_a_duck_type_or_forged_plan_identity():
    plan = frozen_plan()
    with pytest.raises(SearchFindingValidationError):
        build_search_finding_protocol(canonical(finding_request()), plan=SimpleNamespace(canonical_bytes=plan.canonical_bytes, plan_id=plan.plan_id))
    forged = object.__new__(type(plan))
    object.__setattr__(forged, "canonical_bytes", plan.canonical_bytes)
    object.__setattr__(forged, "plan_id", "a" * 64)
    with pytest.raises(SearchFindingValidationError):
        build_search_finding_protocol(canonical(finding_request()), plan=forged)
