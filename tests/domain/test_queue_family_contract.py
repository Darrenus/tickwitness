"""A queue family is a new shared execution owner, never a compatibility finding."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ProtocolValidationError,
    build_executable_protocol,
    load_executable_protocol,
)
from tickwitness.domain.research_contracts.queue_family import (
    QUEUE_ENGINE_SEMANTIC_ID,
    QUEUE_POLICY_IDS,
    QueueFamilyProtocol,
    QueueFamilyValidationError,
    build_queue_family_protocol,
    load_queue_family_protocol,
    validate_queue_family_input,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def request() -> dict:
    return {
        "kind": "queue_family_request_v1",
        "schema_version": 1,
        "cancel_at_capture_seq": 6,
        "budget": {"max_attempts": 2, "max_wall_seconds": 30, "max_events": 1000},
    }


def rows() -> list[dict]:
    return [
        json.loads(line)
        for line in (EXAMPLES / "queue-observations.jsonl").read_bytes().splitlines()
    ]


def context(*, records=None, spec_changes=None, source_budget=None):
    source = (EXAMPLES / "queue-observations.jsonl").read_bytes()
    if records is not None:
        source = b"\n".join(canonical(row) for row in records) + b"\n"
    data = normalize_events(source).normalized_bytes
    experiment = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    for group, values in (spec_changes or {}).items():
        experiment["replay_spec"][group].update(values)
    if source_budget:
        experiment["budget"].update(source_budget)
    spec = build_replay_spec(canonical(experiment["replay_spec"]))
    protocol = build_executable_protocol(
        canonical(experiment), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    return SimpleNamespace(protocol=protocol, replay_input=ReplayInput("a" * 64, data, spec))


def build(declaration=None, *, case=None, queue_request=None):
    case = context() if case is None else case
    return build_queue_family_protocol(
        canonical(request() if declaration is None else declaration),
        source_protocol=case.protocol,
        replay_input=case.replay_input,
        queue_request=(
            (EXAMPLES / "queue-constraint-request.json").read_bytes()
            if queue_request is None
            else queue_request
        ),
    )


def test_family_binds_complete_source_constraint_and_one_shared_budget() -> None:
    case = context()
    before = case.protocol.canonical_bytes
    family = build(case=case)
    document = family.document
    assert document["kind"] == "queue_family_protocol_v1"
    assert document["source_protocol"] == case.protocol.document
    assert family.source_protocol == case.protocol
    assert document["constraint"] == family.constraint.document
    assert document["bindings"] == {
        "source_protocol_id": case.protocol.protocol_id,
        "development_dataset_id": "a" * 64,
        "normalized_sha256": digest(case.replay_input.normalized_bytes),
        "replay_spec_id": case.replay_input.spec.spec_id,
        "queue_constraint_id": family.constraint.constraint_id,
    }
    assert document["policies"] == list(QUEUE_POLICY_IDS)
    assert document["budget_policy"] == "shared_queue_family_budget_v1"
    assert document["budget"] == request()["budget"]
    assert family.protocol_id == family.family_id == digest(family.canonical_bytes)
    assert family.claim_revision_id == case.protocol.claim_revision_id
    assert family.protocol_id != case.protocol.protocol_id
    assert document["engine"]["semantic_id"] == QUEUE_ENGINE_SEMANTIC_ID
    assert document["strategy"] == {
        "kind": "single_limit_buy_cancel_at_capture_v1",
        "submit_capture_seq": 1,
        "cancel_at_capture_seq": 6,
    }
    assert document["scope"] == {
        "phase": "development",
        "scenario_kind": "MODEL_SENSITIVITY",
        "impact_compatibility_verified": False,
        "claim_verdict_issued": False,
    }
    assert document["parameter_basis"]["calibration_status"] == "uncalibrated"
    pair = validate_queue_family_input(family, case.replay_input)
    assert pair.document["source_bindings_verified"] is True
    assert pair.document["native_execution_verified"] is False
    assert pair.document["impact_compatibility_verified"] is False
    assert case.protocol.canonical_bytes == before


def test_canonical_determinism_frozen_dto_and_detached_document() -> None:
    family = build()
    assert build() == load_queue_family_protocol(family.canonical_bytes) == family
    view = family.document
    view["budget"]["max_attempts"] = 100
    assert family.document["budget"]["max_attempts"] == 2
    with pytest.raises(FrozenInstanceError):
        family.protocol_id = "0" * 64  # type: ignore[misc]
    with pytest.raises(QueueFamilyValidationError, match="identity"):
        replace(family, protocol_id="0" * 64)


def test_v2_source_is_not_queue_authorization_and_readers_do_not_overlap() -> None:
    case = context()
    family = build(case=case)
    with pytest.raises(ProtocolValidationError):
        load_executable_protocol(family.canonical_bytes)
    with pytest.raises(QueueFamilyValidationError):
        load_queue_family_protocol(case.protocol.canonical_bytes)
    with pytest.raises(QueueFamilyValidationError):
        validate_queue_family_input(case.protocol, case.replay_input)


def test_family_attempts_are_its_own_shared_budget_not_two_source_protocol_clones() -> None:
    case = context(source_budget={"max_attempts": 1, "max_wall_seconds": 1})
    family = build(case=case)
    assert family.document["budget"]["max_attempts"] == 2
    assert family.source_protocol.document["budget"]["max_attempts"] == 1
    changed = request()
    changed["budget"]["max_attempts"] = 3
    assert build(changed, case=case).protocol_id != family.protocol_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_attempts", 1),
        ("max_attempts", 101),
        ("max_attempts", True),
        ("max_wall_seconds", 0),
        ("max_wall_seconds", 61),
        ("max_events", 0),
        ("max_events", 1001),
        ("max_events", True),
    ],
)
def test_bounded_family_budget_requires_two_shared_attempts(field, value) -> None:
    declaration = request()
    declaration["budget"][field] = value
    with pytest.raises(QueueFamilyValidationError):
        build(declaration)


def test_event_budget_is_inherited_and_actual_event_count_is_checked() -> None:
    with pytest.raises(QueueFamilyValidationError, match="max_events"):
        build(case=context(source_budget={"max_events": 6}))
    declaration = request()
    declaration["budget"]["max_events"] = 5
    with pytest.raises(QueueFamilyValidationError, match="shared family event budget"):
        build(declaration)
    declaration["budget"]["max_events"] = 6
    assert build(declaration, case=context(source_budget={"max_events": 6}))


@pytest.mark.parametrize(
    "changes",
    [
        {"execution": {"insert_latency_ns": 1}},
        {"execution": {"cancel_latency_ns": 1}},
        {"strategy": {"submit_capture_seq": 2}},
        {"strategy": {"cancel_after_first_fill": True}},
    ],
)
def test_unsupported_acceptance_and_strategy_conditions_are_rejected(changes) -> None:
    with pytest.raises(QueueFamilyValidationError):
        build(case=context(spec_changes=changes))


def test_general_source_quantity_settings_are_preserved_without_fixed_fixture_parameters() -> None:
    case = context(spec_changes={"strategy": {"quantity_lots": 3}})
    family = build(case=case)
    assert family.source_protocol.document["replay_spec"]["strategy"]["quantity_lots"] == 3
    assert validate_queue_family_input(family, case.replay_input)


@pytest.mark.parametrize("capture", [True, 1, 4, 5, 7])
def test_cancellation_requires_final_declared_checkpoint(capture) -> None:
    declaration = request()
    declaration["cancel_at_capture_seq"] = capture
    with pytest.raises(QueueFamilyValidationError):
        build(declaration)


def test_cancellation_must_also_be_the_actual_final_target_bid_checkpoint() -> None:
    records = rows()
    tail = dict(records[-1])
    tail.update(capture_seq=7, first_sequence=15, last_sequence=15, bids=[], asks=[[104, 11]])
    records.append(tail)
    with pytest.raises(QueueFamilyValidationError, match="actual final target bid checkpoint"):
        build(case=context(records=records))


@pytest.mark.parametrize("field", ["bindings", "source_protocol", "policies", "scope", "finding"])
def test_request_cannot_self_supply_evidence_bindings_or_policy_approval(field) -> None:
    declaration = request()
    declaration[field] = True
    with pytest.raises(QueueFamilyValidationError):
        build(declaration)


@pytest.mark.parametrize(
    "mutation",
    [
        "kind",
        "schema",
        "read_policy",
        "budget_policy",
        "policy_order",
        "single_policy",
        "engine",
        "strategy",
        "basis",
        "scope_phase",
        "scope_truth",
        "scope_impact",
        "scope_finding",
        "source_id",
        "constraint_id",
        "source_content",
    ],
)
def test_self_consistent_hash_does_not_bless_changed_fixed_policies_or_bindings(mutation) -> None:
    document = build().document
    if mutation == "kind":
        document["kind"] = "executable_research_protocol_v2"
    elif mutation == "schema":
        document["schema_version"] = True
    elif mutation in ("read_policy", "budget_policy"):
        document[mutation] = "independent_or_confirmation"
    elif mutation == "policy_order":
        document["policies"].reverse()
    elif mutation == "single_policy":
        document["policies"].pop()
    elif mutation == "engine":
        document["engine"]["semantic_id"] = "nautilus_v1_receive_order_single_limit_buy_v1"
    elif mutation == "strategy":
        document["strategy"]["submit_capture_seq"] = True
    elif mutation == "basis":
        document["parameter_basis"]["calibration_status"] = "calibrated"
    elif mutation == "scope_phase":
        document["scope"]["phase"] = "confirmation"
    elif mutation == "scope_truth":
        document["scope"]["scenario_kind"] = "NOT_IDENTIFIABLE"
    elif mutation == "scope_impact":
        document["scope"]["impact_compatibility_verified"] = True
    elif mutation == "scope_finding":
        document["scope"]["claim_verdict_issued"] = True
    elif mutation == "source_id":
        document["bindings"]["source_protocol_id"] = "c" * 64
    elif mutation == "constraint_id":
        document["bindings"]["queue_constraint_id"] = "c" * 64
    else:
        document["source_protocol"]["claim"]["title"] = "Rehashed source modification"
    with pytest.raises(QueueFamilyValidationError):
        load_queue_family_protocol(canonical(document))


def test_loader_structure_is_not_proof_of_actual_normalized_source() -> None:
    case = context()
    document = build(case=case).document
    document["constraint"]["bindings"]["normalized_sha256"] = "c" * 64
    document["bindings"]["normalized_sha256"] = "c" * 64
    document["bindings"]["queue_constraint_id"] = digest(canonical(document["constraint"]))
    forged = load_queue_family_protocol(canonical(document))
    with pytest.raises(QueueFamilyValidationError, match="bindings mismatch"):
        validate_queue_family_input(forged, case.replay_input)


@pytest.mark.parametrize("mutation", ["confirmation", "bytes", "spec"])
def test_actual_dataset_hash_and_replay_spec_are_rechecked(mutation) -> None:
    case = context()
    family = build(case=case)
    actual = case.replay_input
    if mutation == "confirmation":
        actual = ReplayInput("b" * 64, actual.normalized_bytes, actual.spec)
    elif mutation == "bytes":
        records = rows()
        records[-1]["event_time_ns"] -= 1
        actual = context(records=records).replay_input
    else:
        actual = context(spec_changes={"strategy": {"quantity_lots": 3}}).replay_input
    with pytest.raises(QueueFamilyValidationError):
        validate_queue_family_input(family, actual)


def test_forged_frozen_dto_identity_is_revalidated_before_input_checks() -> None:
    original = build()
    forged = object.__new__(QueueFamilyProtocol)
    object.__setattr__(forged, "protocol_id", "0" * 64)
    object.__setattr__(forged, "canonical_bytes", original.canonical_bytes)
    with pytest.raises(QueueFamilyValidationError, match="identity"):
        validate_queue_family_input(forged, context().replay_input)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        bytearray(b"{}"),
        b"",
        b"{}",
        b"[]",
        b"\xff",
        b'{"kind":1,"kind":2}',
        b'{"kind":1.0}',
        b'{"kind":NaN}',
        b" " * (256 * 1024 + 1),
    ],
)
def test_loader_requires_bounded_canonical_bytes_without_duplicate_or_float_json(raw) -> None:
    with pytest.raises(QueueFamilyValidationError):
        load_queue_family_protocol(raw)


def test_noncanonical_document_is_rejected_even_with_a_matching_new_hash() -> None:
    family = build()
    with pytest.raises(QueueFamilyValidationError, match="canonical"):
        load_queue_family_protocol(family.canonical_bytes + b" ")
