"""Search coordination binds frozen candidates without rewriting old scenario scope."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError, replace

import pytest
from test_scenario_derivation import context

from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.evidence.run_records import AttemptReservation, canonical, digest
from tickwitness.domain.evidence.scenario_records import (
    build_scenario_intent,
)
from tickwitness.domain.search.execution import (
    MAX_CAMPAIGN_BYTES,
    MAX_SEARCH_EXECUTION_RECORD_BYTES,
    SearchCampaign,
    SearchExecutionValidationError,
    build_campaign,
    build_dispatch,
    build_link,
    build_stop,
    load_campaign,
    load_dispatch,
    load_link,
    load_stop,
)
from tickwitness.domain.search.plans import build_search_plan


CAMPAIGN_NONCE = "a" * 32
RESERVATION_NONCE = "b" * 32


def values(*, only_rejected=False):
    validated = context(delay=0)
    request = {
        "kind": "search_plan_request_v1",
        "schema_version": 1,
        "search_seed": 17,
        "max_proposals": 4,
        "generator": {
            "kind": "grid",
            "values_ns": [20_000_001] * 4 if only_rejected else [0, 0, 20_000_001, 9],
        },
    }
    plan = build_search_plan(
        canonical(request), protocol=validated.protocol, assumptions=validated.assumptions
    )
    campaign = build_campaign(plan, CAMPAIGN_NONCE)
    intent = build_scenario_intent(derive_replay_view(validated))
    return plan, campaign, intent


def dispatched():
    _, campaign, intent = values()
    dispatch = build_dispatch(campaign, 1, RESERVATION_NONCE, intent)
    return campaign, dispatch


def reservation(dispatch, **changes):
    document = {
        "kind": "replay_attempt_reservation_v1",
        "schema_version": 1,
        "protocol_id": dispatch.document["protocol_id"],
        "attempt_index": 1,
        "nonce": RESERVATION_NONCE,
        "max_wall_seconds": 60,
        "created_at_utc": "2026-10-27T00:00:00.000000+00:00",
    }
    document.update(changes)
    raw = canonical(document)
    return AttemptReservation(digest(raw), raw)


def test_campaign_rebuilds_complete_plan_and_preserves_its_original_scope():
    plan, campaign, _ = values()
    assert campaign.campaign_id == digest(campaign.canonical_bytes)
    assert campaign.document["plan"] == plan.document
    assert campaign.document["protocol_id"] == plan.document["protocol_id"]
    assert campaign.document["execution_policy"] == "sequential_receive_delay_attempts_v1"
    assert campaign.document["plan"]["scope"]["execution_performed"] is False
    assert campaign.document["scope"] == {
        "phase": "development",
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "calibration_status": "uncalibrated",
        "evaluation_kind": "scenario_metric_observation_v1",
        "claim_evaluated": False,
        "findings_issued": False,
        "confirmation_accessed": False,
        "statistical_trial_history_certified": False,
    }
    assert load_campaign(campaign.canonical_bytes) == campaign
    assert build_campaign(plan, CAMPAIGN_NONCE) == campaign
    assert build_campaign(plan, "c" * 32).campaign_id != campaign.campaign_id
    detached = campaign.document
    detached["plan"]["journal"][0]["status"] = "EXECUTED"
    assert campaign.document["plan"]["journal"][0]["status"] == "ELIGIBLE"
    with pytest.raises(FrozenInstanceError):
        campaign.campaign_id = "f" * 64
    with pytest.raises(SearchExecutionValidationError, match="identity"):
        replace(campaign, campaign_id="f" * 64)


@pytest.mark.parametrize("nonce", ["", "a" * 31, "A" * 32, "g" * 32, 1, True, None])
def test_campaign_and_dispatch_nonce_must_be_bounded_correlation_tokens(nonce):
    plan, campaign, intent = values()
    with pytest.raises(SearchExecutionValidationError):
        build_campaign(plan, nonce)
    with pytest.raises(SearchExecutionValidationError):
        build_dispatch(campaign, 1, nonce, intent)


@pytest.mark.parametrize(
    "change", ["scope", "policy", "version", "plan_id", "protocol_id", "journal", "extra"]
)
def test_campaign_rejects_all_hash_recomputed_declaration_or_scope_forgery(change):
    _, campaign, _ = values()
    document = campaign.document
    if change == "scope":
        document["scope"]["findings_issued"] = True
    elif change == "policy":
        document["execution_policy"] = "unbounded_v1"
    elif change == "version":
        document["schema_version"] = True
    elif change == "plan_id":
        document["plan_id"] = "f" * 64
    elif change == "protocol_id":
        document["protocol_id"] = "f" * 64
    elif change == "journal":
        document["plan"]["journal"][0]["delay_ns"] = 1
        document["plan_id"] = digest(canonical(document["plan"]))
    else:
        document["finding"] = "NO_COUNTEREXAMPLE_FOUND"
    raw = canonical(document)
    with pytest.raises(SearchExecutionValidationError):
        load_campaign(raw)
    with pytest.raises(SearchExecutionValidationError):
        SearchCampaign(digest(raw), raw)


def test_dispatch_binds_unique_eligible_row_and_original_intent_without_scope_changes():
    campaign, dispatch = dispatched()
    assert load_dispatch(dispatch.canonical_bytes, campaign=campaign) == dispatch
    document = dispatch.document
    assert document["ordinal"] == 1
    assert document["campaign_id"] == campaign.campaign_id
    assert document["plan_id"] == campaign.document["plan_id"]
    assert document["intent"]["scope"]["search_performed"] is False
    assert document["intent"]["scope"]["baseline_claim_evaluated"] is False
    detached = dispatch.document
    detached["intent"]["scope"]["search_performed"] = True
    assert dispatch.document["intent"]["scope"]["search_performed"] is False
    with pytest.raises(FrozenInstanceError):
        dispatch.dispatch_id = "f" * 64
    with pytest.raises(SearchExecutionValidationError):
        replace(dispatch, dispatch_id="f" * 64)


@pytest.mark.parametrize("ordinal", [0, True, 2, 3, 4, 5, 1_025, "1"])
def test_dispatch_rejects_duplicate_rejected_unlisted_and_wrong_scenario_ordinals(ordinal):
    _, campaign, intent = values()
    # Ordinal 4 is eligible but points at delay 9, while this intent binds delay 0.
    with pytest.raises(SearchExecutionValidationError):
        build_dispatch(campaign, ordinal, RESERVATION_NONCE, intent)


@pytest.mark.parametrize(
    "change",
    [
        "campaign", "plan", "protocol", "scenario", "ordinal", "assumption", "source", "spec",
        "claim", "scope", "version", "extra",
    ],
)
def test_dispatch_context_rejects_rehashed_bindings_and_privilege_changes(change):
    campaign, dispatch = dispatched()
    document = dispatch.document
    if change in {"campaign", "plan", "protocol", "scenario"}:
        document[change + "_id"] = "f" * 64
    elif change == "ordinal":
        document["ordinal"] = 4
    elif change in {"assumption", "source", "spec"}:
        key = {
            "assumption": "assumption_id",
            "source": "source_normalized_sha256",
            "spec": "replay_spec_id",
        }[change]
        document["intent"]["bindings"][key] = "f" * 64
    elif change == "claim":
        document["intent"]["claim_revision_id"] = "f" * 64
    elif change == "scope":
        document["intent"]["scope"]["search_performed"] = True
    elif change == "version":
        document["schema_version"] = True
    else:
        document["budget_refund"] = True
    with pytest.raises(SearchExecutionValidationError):
        load_dispatch(canonical(document), campaign=campaign)


def test_new_campaign_cannot_silently_relabel_an_existing_dispatch():
    plan, campaign, _ = values()
    _, dispatch = dispatched()
    other = build_campaign(plan, "c" * 32)
    with pytest.raises(SearchExecutionValidationError):
        load_dispatch(dispatch.canonical_bytes, campaign=other)
    object.__setattr__(campaign, "campaign_id", "f" * 64)
    with pytest.raises(SearchExecutionValidationError):
        load_dispatch(dispatch.canonical_bytes, campaign=campaign)


def test_link_roundtrip_binds_full_original_reservation_and_committed_nonce():
    _, dispatch = dispatched()
    attempt = reservation(dispatch)
    raw = build_link(dispatch, attempt)
    assert load_link(raw, dispatch=dispatch) == attempt
    document = dispatch.document
    assert attempt.document["nonce"] == document["reservation_nonce"]
    assert attempt.protocol_id == document["protocol_id"]
    # A link proves declared binding. Actual slot closure and protocol-specific
    # max_attempts/wall budget must still be verified against the real ledger.


@pytest.mark.parametrize(
    "change",
    [
        "nonce", "protocol", "attempt_id", "dispatch_id", "ordinal", "scenario", "campaign",
        "plan", "version", "extra",
    ],
)
def test_link_cannot_reassign_the_attempt_or_dispatch_when_all_hashes_are_recomputed(change):
    _, dispatch = dispatched()
    attempt = reservation(dispatch)
    if change == "nonce":
        with pytest.raises(SearchExecutionValidationError):
            build_link(dispatch, reservation(dispatch, nonce="c" * 32))
        return
    if change == "protocol":
        with pytest.raises(SearchExecutionValidationError):
            build_link(dispatch, reservation(dispatch, protocol_id="f" * 64))
        return
    if change == "attempt_id":
        object.__setattr__(attempt, "attempt_id", "f" * 64)
        with pytest.raises(SearchExecutionValidationError):
            build_link(dispatch, attempt)
        return
    raw = build_link(dispatch, attempt)
    from tickwitness.domain.evidence.run_records import parse

    document = parse(raw)
    if change == "ordinal":
        document["ordinal"] = True
    elif change in {"scenario", "campaign", "plan"}:
        document[change + "_id"] = "f" * 64
    elif change == "dispatch_id":
        document["dispatch_id"] = "f" * 64
    elif change == "version":
        document["schema_version"] = True
    else:
        document["refund"] = True
    with pytest.raises(SearchExecutionValidationError):
        load_link(canonical(document), dispatch=dispatch)


@pytest.mark.parametrize(
    "reason",
    [
        "attempt_budget_exhausted", "candidate_failed", "candidate_incomplete",
        "reservation_unconfirmed", "publication_unconfirmed",
    ],
)
def test_candidate_stop_is_a_diagnostic_bound_to_an_eligible_ordinal(reason):
    _, campaign, _ = values()
    raw = build_stop(
        campaign, reason, ordinal=1, error_code="diagnostic_v1", message="Observed failure"
    )
    document = load_stop(raw, campaign=campaign)
    assert document["reason"] == reason
    assert document["ordinal"] == 1
    assert document["error_code"] == "diagnostic_v1"
    assert "finding" not in document
    with pytest.raises(SearchExecutionValidationError):
        build_stop(campaign, reason, ordinal=2)
    with pytest.raises(SearchExecutionValidationError):
        build_stop(campaign, reason, ordinal=True)


def test_exhaustion_and_empty_eligible_set_have_separate_nonfinding_stops():
    _, campaign, _ = values()
    assert load_stop(
        build_stop(campaign, "planned_candidates_exhausted"), campaign=campaign
    )["ordinal"] is None
    _, empty, _ = values(only_rejected=True)
    assert load_stop(build_stop(empty, "no_eligible_candidates"), campaign=empty)["reason"] == (
        "no_eligible_candidates"
    )
    with pytest.raises(SearchExecutionValidationError):
        build_stop(campaign, "no_eligible_candidates")
    with pytest.raises(SearchExecutionValidationError):
        build_stop(empty, "planned_candidates_exhausted")
    with pytest.raises(SearchExecutionValidationError):
        build_stop(campaign, "planned_candidates_exhausted", ordinal=1)
    with pytest.raises(SearchExecutionValidationError):
        build_stop(campaign, "planned_candidates_exhausted", error_code="false_success")
    assert load_stop(
        build_stop(campaign, "publication_unconfirmed"), campaign=campaign
    )["ordinal"] is None


@pytest.mark.parametrize(
    "reason", ["NO_COUNTEREXAMPLE_FOUND", "COUNTEREXAMPLE_FOUND", "cancelled", "", None, True]
)
def test_stop_never_accepts_research_finding_or_unknown_reason(reason):
    _, campaign, _ = values()
    with pytest.raises(SearchExecutionValidationError):
        build_stop(campaign, reason)


@pytest.mark.parametrize("key,value", [
    ("error_code", ""), ("error_code", "Upper"), ("error_code", "a" * 129),
    ("error_code", True), ("message", ""), ("message", "a" * 4_097),
    ("message", "line\nbreak"), ("message", "\ud800"), ("message", True),
])
def test_stop_diagnostic_details_are_strict_and_bounded(key, value):
    _, campaign, _ = values()
    with pytest.raises(SearchExecutionValidationError):
        build_stop(campaign, "candidate_failed", ordinal=1, **{key: value})


@pytest.mark.parametrize("change", ["campaign", "plan", "protocol", "schema", "extra", "ordinal"])
def test_stop_rejects_rehashed_wrong_context_or_types(change):
    _, campaign, _ = values()
    from tickwitness.domain.evidence.run_records import parse

    document = parse(build_stop(campaign, "candidate_failed", ordinal=1))
    if change in {"campaign", "plan", "protocol"}:
        document[change + "_id"] = "f" * 64
    elif change == "schema":
        document["schema_version"] = True
    elif change == "ordinal":
        document["ordinal"] = True
    else:
        document["finding"] = "ROBUST"
    with pytest.raises(SearchExecutionValidationError):
        load_stop(canonical(document), campaign=campaign)


@pytest.mark.parametrize("raw", [b"", bytearray(b"{}"), b" " * (MAX_CAMPAIGN_BYTES + 1)])
def test_campaign_input_is_bounded_and_immutable(raw):
    with pytest.raises(SearchExecutionValidationError):
        load_campaign(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"", bytearray(b"{}"), b" " * (MAX_SEARCH_EXECUTION_RECORD_BYTES + 1),
        b'{"schema_version":1,"schema_version":1}', b'{"schema_version":1.0}',
        b'{"schema_version":NaN}',
    ],
)
def test_execution_record_inputs_reject_noncanonical_or_unbounded_content(raw):
    campaign, dispatch = dispatched()
    for load in (
        lambda: load_dispatch(raw, campaign=campaign),
        lambda: load_link(raw, dispatch=dispatch),
        lambda: load_stop(raw, campaign=campaign),
    ):
        with pytest.raises(SearchExecutionValidationError):
            load()


def test_domain_coordination_uses_no_io_or_native_imports(monkeypatch):
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in {"sqlite3", "socket", "subprocess"} or name.startswith(
            ("nautilus_trader", "tickwitness.infrastructure", "tickwitness.application")
        ):
            raise AssertionError("Coordination records cannot import IO or native")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    campaign, dispatch = dispatched()
    assert load_campaign(campaign.canonical_bytes) == campaign
    assert load_dispatch(dispatch.canonical_bytes, campaign=campaign) == dispatch
    attempt = reservation(dispatch)
    assert load_link(build_link(dispatch, attempt), dispatch=dispatch) == attempt


@pytest.mark.parametrize("forgery", ["plan", "campaign", "intent", "dispatch"])
def test_builders_reconstruct_dataclasses_instead_of_trusting_identity_markers(forgery):
    plan, campaign, intent = values()
    dispatch = build_dispatch(campaign, 1, RESERVATION_NONCE, intent)
    attempt = reservation(dispatch)
    with pytest.raises(SearchExecutionValidationError):
        if forgery == "plan":
            object.__setattr__(plan, "plan_id", "f" * 64)
            build_campaign(plan, CAMPAIGN_NONCE)
        elif forgery == "campaign":
            object.__setattr__(campaign, "campaign_id", "f" * 64)
            build_dispatch(campaign, 1, RESERVATION_NONCE, intent)
        elif forgery == "intent":
            object.__setattr__(intent, "intent_id", "f" * 64)
            build_dispatch(campaign, 1, RESERVATION_NONCE, intent)
        else:
            object.__setattr__(dispatch, "dispatch_id", "f" * 64)
            build_link(dispatch, attempt)
