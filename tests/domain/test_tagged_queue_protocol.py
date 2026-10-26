"""Tagged reconstruction owns a new frozen claim and conditional observation contract."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import ReplaySpec, build_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    ProtocolValidationError,
    build_executable_protocol,
    load_executable_protocol,
)
from tickwitness.domain.research_contracts.queue_family import (
    QueueFamilyValidationError,
    load_queue_family_protocol,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TAGGED_ENGINE_SEMANTIC_ID,
    TAGGED_MODEL,
    TAGGED_POLICY_IDS,
    TAGGED_SCOPE,
    TaggedQueueProtocol,
    TaggedQueueValidationError,
    build_tagged_queue_protocol,
    load_tagged_queue_protocol,
    validate_tagged_queue_input,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def request() -> dict:
    return {
        "kind": "tagged_queue_request_v1",
        "schema_version": 1,
        "claim": {
            "title": "Conditional tagged net inventory mark",
            "hypothesis": "The already displayed tagged participant has a positive net mark.",
            "metric": "tagged_inventory_net_marked_pnl_v1",
            "unit": "USD",
            "comparator": "gt",
            "threshold": "0",
        },
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
    source_protocol = build_executable_protocol(
        canonical(experiment), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    return SimpleNamespace(protocol=source_protocol, replay_input=ReplayInput("a" * 64, data, spec))


def build(declaration=None, *, case=None, queue_request=None):
    case = context() if case is None else case
    return build_tagged_queue_protocol(
        canonical(request() if declaration is None else declaration),
        source_protocol=case.protocol,
        replay_input=case.replay_input,
        queue_request=(
            (EXAMPLES / "queue-constraint-request.json").read_bytes()
            if queue_request is None
            else queue_request
        ),
    )


def test_frozen_contract_owns_claim_projection_intervention_and_shared_budget() -> None:
    case = context()
    original = case.protocol.canonical_bytes, case.replay_input.normalized_bytes
    protocol = build(case=case)
    doc = protocol.document
    assert doc["kind"] == "tagged_queue_reconstruction_protocol_v1"
    assert doc["source_protocol"] == case.protocol.document
    assert protocol.source_protocol == case.protocol
    assert doc["gross_constraint_source"] == protocol.constraint.document
    assert doc["gross_source_usage"] == "source_and_gross_flow_lineage_only_v1"
    assert doc["bindings"] == {
        "source_protocol_id": case.protocol.protocol_id,
        "development_dataset_id": "a" * 64,
        "normalized_sha256": digest(case.replay_input.normalized_bytes),
        "replay_spec_id": case.replay_input.spec.spec_id,
        "gross_constraint_id": protocol.constraint.constraint_id,
    }
    assert protocol.claim_revision_id == digest(canonical(request()["claim"]))
    assert protocol.claim_revision_id != case.protocol.claim_revision_id
    assert doc["claim"] == request()["claim"]
    assert (
        doc["policies"]
        == list(TAGGED_POLICY_IDS)
        == ["protected_tag_front_cancel_v1", "protected_tag_back_cancel_v1"]
    )
    assert doc["engine"]["semantic_id"] == TAGGED_ENGINE_SEMANTIC_ID
    assert doc["model"] == TAGGED_MODEL
    assert doc["model"]["intervention_id"] == "relabel_existing_tail_quantity_v1"
    assert doc["model"]["projection_id"] == "inclusive_tagged_fifo_total_depth_v1"
    assert doc["model"]["terminal_policy"] == "observe_mark_then_cancel_after_horizon_v1"
    assert doc["strategy"] == {
        "kind": "tagged_passive_order_at_entry_v1",
        "entry_capture_seq": 1,
        "horizon_capture_seq": 6,
        "tagged_quantity_lots": 2,
        "target_price_ticks": 100,
    }
    assert doc["scope"] == TAGGED_SCOPE
    assert all(
        doc["scope"][key] is False
        for key in (
            "historical_owner_verified",
            "literal_order_insertion",
            "market_impact_verified",
            "source_claim_evaluated",
            "finding_issued",
        )
    )
    assert doc["budget_policy"] == "shared_tagged_queue_budget_v1"
    assert doc["budget"] == request()["budget"]
    assert doc["gross_constraint_source"]["execution_approved"] is False
    assert (case.protocol.canonical_bytes, case.replay_input.normalized_bytes) == original


def test_canonical_determinism_identity_detached_views_and_immutable_values() -> None:
    protocol = build()
    reordered = json.dumps(request(), indent=2, sort_keys=False).encode()
    case = context()
    repeated = build_tagged_queue_protocol(
        reordered,
        source_protocol=case.protocol,
        replay_input=case.replay_input,
        queue_request=(EXAMPLES / "queue-constraint-request.json").read_bytes(),
    )
    assert protocol == repeated == load_tagged_queue_protocol(protocol.canonical_bytes)
    assert protocol.protocol_id == digest(protocol.canonical_bytes)
    doc = protocol.document
    doc["scope"]["finding_issued"] = True
    doc["claim"]["threshold"] = "999"
    assert protocol.document["claim"]["threshold"] == "0"
    assert protocol.document["scope"]["finding_issued"] is False
    with pytest.raises(FrozenInstanceError):
        protocol.protocol_id = "0" * 64
    with pytest.raises(TaggedQueueValidationError, match="identity"):
        replace(protocol, protocol_id="0" * 64)


@pytest.mark.parametrize("comparator", ["gt", "ge", "lt", "le"])
def test_claim_comparison_is_frozen_and_decimal_threshold_normalized(comparator) -> None:
    declaration = request()
    declaration["claim"].update(comparator=comparator, threshold="+000.5000")
    changed = build(declaration)
    assert changed.document["claim"]["threshold"] == "0.5"
    assert changed.document["claim"]["comparator"] == comparator
    assert changed.claim_revision_id != build().claim_revision_id


def test_old_source_and_family_parsers_never_accept_tagged_contract() -> None:
    protocol = build()
    with pytest.raises(ProtocolValidationError):
        load_executable_protocol(protocol.canonical_bytes)
    with pytest.raises(QueueFamilyValidationError):
        load_queue_family_protocol(protocol.canonical_bytes)
    with pytest.raises(TaggedQueueValidationError):
        load_tagged_queue_protocol(context().protocol.canonical_bytes)
    with pytest.raises(TaggedQueueValidationError):
        validate_tagged_queue_input(context().protocol, context().replay_input)


def test_frozen_budget_is_a_single_new_owner_and_not_source_budget_clones() -> None:
    case = context(source_budget={"max_attempts": 1, "max_wall_seconds": 1})
    protocol = build(case=case)
    assert protocol.document["budget"]["max_attempts"] == 2
    assert protocol.source_protocol.document["budget"]["max_attempts"] == 1
    declaration = request()
    declaration["budget"]["max_attempts"] = 3
    assert build(declaration, case=case).protocol_id != protocol.protocol_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_attempts", 1),
        ("max_attempts", 101),
        ("max_attempts", True),
        ("max_wall_seconds", 0),
        ("max_wall_seconds", 61),
        ("max_wall_seconds", True),
        ("max_events", 0),
        ("max_events", 1001),
        ("max_events", True),
    ],
)
def test_shared_budget_is_bounded_and_requires_true_integers(field, value) -> None:
    declaration = request()
    declaration["budget"][field] = value
    with pytest.raises(TaggedQueueValidationError):
        build(declaration)


def test_event_budget_cannot_exceed_source_and_rejects_actual_overflow_before_execution() -> None:
    with pytest.raises(TaggedQueueValidationError, match="max_events"):
        build(case=context(source_budget={"max_events": 6}))
    declaration = request()
    declaration["budget"]["max_events"] = 5
    with pytest.raises(TaggedQueueValidationError, match="event budget"):
        build(declaration)
    declaration["budget"]["max_events"] = 6
    assert build(declaration, case=context(source_budget={"max_events": 6}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("metric", "net_marked_pnl_v1"),
        ("unit", "EUR"),
        ("comparator", "eq"),
        ("threshold", 0),
        ("threshold", "NaN"),
        ("threshold", "1e2"),
        ("title", " padded"),
        ("title", ""),
        ("hypothesis", "bad\nline"),
    ],
)
def test_claim_is_distinct_and_strictly_declared(field, value) -> None:
    declaration = request()
    declaration["claim"][field] = value
    with pytest.raises(TaggedQueueValidationError):
        build(declaration)


@pytest.mark.parametrize(
    "field",
    [
        "bindings",
        "source_protocol",
        "policies",
        "model",
        "scope",
        "finding",
        "evaluation_policy",
    ],
)
def test_request_cannot_supply_runtime_authority_or_evidence(field) -> None:
    declaration = request()
    declaration[field] = True
    with pytest.raises(TaggedQueueValidationError):
        build(declaration)


@pytest.mark.parametrize(
    "changes",
    [
        {"execution": {"insert_latency_ns": 1}},
        {"execution": {"cancel_latency_ns": 1}},
        {"strategy": {"submit_capture_seq": 2}},
        {"strategy": {"cancel_after_first_fill": True}},
    ],
)
def test_acceptance_profile_rejects_unsupported_source_conditions(changes) -> None:
    with pytest.raises(TaggedQueueValidationError):
        build(case=context(spec_changes=changes))


def test_horizon_must_be_actual_last_source_target_checkpoint() -> None:
    records = rows()
    tail = dict(records[-1])
    tail.update(capture_seq=7, first_sequence=15, last_sequence=15, bids=[], asks=[[104, 11]])
    records.append(tail)
    with pytest.raises(TaggedQueueValidationError, match="final target checkpoint"):
        build(case=context(records=records))


@pytest.mark.parametrize(
    "mutation",
    [
        "kind",
        "schema",
        "read_policy",
        "budget_policy",
        "policy_order",
        "old_policy",
        "engine",
        "strategy_entry",
        "strategy_quantity",
        "horizon",
        "claim_revision",
        "gross_usage",
        "projection",
        "intervention",
        "terminal",
        "basis",
        "scope_phase",
        "scope_historical",
        "scope_insertion",
        "scope_impact",
        "scope_source_claim",
        "scope_finding",
        "source_id",
        "constraint_id",
        "source_content",
        "extra",
        "missing",
    ],
)
def test_rehash_cannot_bless_changed_fixed_contract_or_embedded_identity(mutation) -> None:
    doc = build().document
    if mutation == "kind":
        doc["kind"] = "queue_family_protocol_v1"
    elif mutation == "schema":
        doc["schema_version"] = True
    elif mutation in ("read_policy", "budget_policy"):
        doc[mutation] = "confirmation_or_independent"
    elif mutation == "policy_order":
        doc["policies"].reverse()
    elif mutation == "old_policy":
        doc["policies"][0] = "cancel_front_first_v1"
    elif mutation == "engine":
        doc["engine"]["semantic_id"] = "nautilus_external_fifo_shadow_queue_execution_v1"
    elif mutation == "strategy_entry":
        doc["strategy"]["entry_capture_seq"] = True
    elif mutation == "strategy_quantity":
        doc["strategy"]["tagged_quantity_lots"] = 1
    elif mutation == "horizon":
        doc["strategy"]["horizon_capture_seq"] = 5
    elif mutation == "claim_revision":
        doc["claim_revision_id"] = doc["source_protocol"]["claim_revision_id"]
    elif mutation == "gross_usage":
        doc["gross_source_usage"] = "native_model_authorization"
    elif mutation in ("projection", "intervention"):
        doc["model"][mutation + "_id"] = "literal_insert"
    elif mutation == "terminal":
        doc["model"]["terminal_policy"] = "cancel_before_mark"
    elif mutation == "basis":
        doc["parameter_basis"]["calibration_status"] = "calibrated"
    elif mutation == "scope_phase":
        doc["scope"]["phase"] = "confirmation"
    elif mutation.startswith("scope_"):
        key = {
            "scope_historical": "historical_owner_verified",
            "scope_insertion": "literal_order_insertion",
            "scope_impact": "market_impact_verified",
            "scope_source_claim": "source_claim_evaluated",
            "scope_finding": "finding_issued",
        }[mutation]
        doc["scope"][key] = True
    elif mutation == "source_id":
        doc["bindings"]["source_protocol_id"] = "c" * 64
    elif mutation == "constraint_id":
        doc["bindings"]["gross_constraint_id"] = "c" * 64
    elif mutation == "source_content":
        doc["source_protocol"]["claim"]["title"] = "Rehashed source edit"
    elif mutation == "extra":
        doc["actual_owner_verified"] = True
    else:
        del doc["scope"]
    with pytest.raises(TaggedQueueValidationError):
        load_tagged_queue_protocol(canonical(doc))


def test_loader_does_not_certify_unread_source_even_when_hashes_are_self_consistent() -> None:
    case = context()
    doc = build(case=case).document
    doc["gross_constraint_source"]["bindings"]["normalized_sha256"] = "c" * 64
    doc["bindings"]["normalized_sha256"] = "c" * 64
    doc["bindings"]["gross_constraint_id"] = digest(canonical(doc["gross_constraint_source"]))
    forged = load_tagged_queue_protocol(canonical(doc))
    with pytest.raises(TaggedQueueValidationError, match="bindings mismatch"):
        validate_tagged_queue_input(forged, case.replay_input)


@pytest.mark.parametrize(
    "mutation", ["confirmation", "bytes", "spec", "protocol_identity", "spec_identity"]
)
def test_actual_source_and_forged_immutable_identity_are_rechecked(mutation) -> None:
    case = context()
    protocol = build(case=case)
    actual = case.replay_input
    if mutation == "confirmation":
        actual = ReplayInput("b" * 64, actual.normalized_bytes, actual.spec)
    elif mutation == "bytes":
        records = rows()
        records[-1]["event_time_ns"] -= 1
        actual = context(records=records).replay_input
    elif mutation == "spec":
        actual = context(spec_changes={"account": {"starting_cash": "9999"}}).replay_input
    elif mutation == "protocol_identity":
        forged = object.__new__(TaggedQueueProtocol)
        object.__setattr__(forged, "canonical_bytes", protocol.canonical_bytes)
        object.__setattr__(forged, "protocol_id", "0" * 64)
        protocol = forged
    else:
        forged_spec = object.__new__(ReplaySpec)
        object.__setattr__(forged_spec, "canonical_bytes", actual.spec.canonical_bytes)
        object.__setattr__(forged_spec, "spec_id", "0" * 64)
        actual = ReplayInput(actual.dataset_id, actual.normalized_bytes, forged_spec)
    with pytest.raises(TaggedQueueValidationError):
        validate_tagged_queue_input(protocol, actual)


def test_forged_source_protocol_hash_is_not_used_as_configuration_authority() -> None:
    case = context()
    forged = object.__new__(ExecutableProtocol)
    object.__setattr__(forged, "protocol_id", "0" * 64)
    object.__setattr__(forged, "claim_revision_id", case.protocol.claim_revision_id)
    object.__setattr__(forged, "canonical_bytes", case.protocol.canonical_bytes)
    case.protocol = forged
    with pytest.raises(TaggedQueueValidationError, match="identities"):
        build(case=case)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "{}",
        [],
        b"",
        b"[]",
        b"{}",
        b"\xff",
        b'{"kind":1,"kind":2}',
        b'{"kind":1.0}',
        b'{"kind":NaN}',
        b"{" + b" " * 16384 + b"}",
    ],
)
def test_bounded_request_rejects_invalid_json_duplicates_floats_and_nonbytes(raw) -> None:
    case = context()
    with pytest.raises(TaggedQueueValidationError):
        build_tagged_queue_protocol(
            raw,
            source_protocol=case.protocol,
            replay_input=case.replay_input,
            queue_request=(EXAMPLES / "queue-constraint-request.json").read_bytes(),
        )


@pytest.mark.parametrize("raw", [None, "{}", [], b"", b"{} "])
def test_protocol_loader_requires_canonical_bounded_immutable_bytes(raw) -> None:
    with pytest.raises(TaggedQueueValidationError):
        load_tagged_queue_protocol(raw)


def test_even_valid_document_cannot_change_its_canonical_encoding() -> None:
    with pytest.raises(TaggedQueueValidationError, match="encoding"):
        load_tagged_queue_protocol(json.dumps(build().document, indent=2).encode())
