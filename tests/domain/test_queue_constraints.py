"""External queue conservation is not a native fill or market-compatibility proof."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.assumptions.queue_constraints import (
    CLASSIFICATION,
    MAX_QUEUE_LOTS,
    QueueConstraintSpec,
    QueueConstraintValidationError,
    build_queue_constraint_spec,
    load_queue_constraint_spec,
    validate_queue_constraints,
)
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.replay._validation import canonical, digest
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def request() -> dict:
    return json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())


def observations() -> list[dict]:
    return [
        json.loads(line)
        for line in (EXAMPLES / "queue-observations.jsonl").read_bytes().splitlines()
    ]


def context(*, records=None, spec_changes=None, budget=1000):
    source = (EXAMPLES / "queue-observations.jsonl").read_bytes()
    if records is not None:
        source = b"\n".join(canonical(row) for row in records) + b"\n"
    data = normalize_events(source).normalized_bytes
    experiment = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    for group, values in (spec_changes or {}).items():
        experiment["replay_spec"][group].update(values)
    experiment["budget"]["max_events"] = budget
    spec = build_replay_spec(canonical(experiment["replay_spec"]))
    protocol = build_executable_protocol(
        canonical(experiment), development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
    )
    return SimpleNamespace(protocol=protocol, replay_input=ReplayInput("a" * 64, data, spec))


def build(declaration=None, *, case=None):
    case = context() if case is None else case
    return build_queue_constraint_spec(
        canonical(request() if declaration is None else declaration),
        protocol=case.protocol,
        replay_input=case.replay_input,
    )


def validate(constraint, case=None):
    case = context() if case is None else case
    return validate_queue_constraints(
        constraint, protocol=case.protocol, replay_input=case.replay_input
    )


def test_two_cancel_allocations_share_external_observations_and_have_no_fill_claim() -> None:
    case = context()
    source = case.replay_input.normalized_bytes
    constraint = build(case=case)
    pair = validate(constraint, case)
    doc = pair.document
    assert doc["constraint_id"] == constraint.constraint_id
    assert doc["classification"] == CLASSIFICATION == "MODEL_SENSITIVITY_CANDIDATE"
    assert doc["source_bindings_verified"] is doc["flow_conservation_verified"] is True
    for key in (
        "actual_acceptance_verified",
        "impact_compatibility_verified",
        "native_execution_verified",
        "execution_approved",
    ):
        assert doc[key] is False
        assert constraint.document[key] is False
    front, back = doc["interpretations"]
    assert front["policy_id"] == "cancel_front_first_v1"
    assert back["policy_id"] == "cancel_back_first_v1"
    assert front["final_state"] == {"ahead_lots": 0, "behind_lots": 2, "external_lots": 2}
    assert back["final_state"] == {"ahead_lots": 2, "behind_lots": 0, "external_lots": 2}
    assert [row["after"]["external_lots"] for row in front["trace"]] == [5, 8, 5, 2, 2, 2]
    assert [row["after"]["external_lots"] for row in front["trace"]] == [
        row["after"]["external_lots"] for row in back["trace"]
    ]
    assert front["trace"][2]["flow"]["cancel_ahead_lots"] == 3
    assert back["trace"][2]["flow"]["cancel_behind_lots"] == 3
    assert front["trace"][3]["flow"]["trade_lots"] == 3
    assert front["trace"][4]["flow"]["cancellations_lots"] == 0
    assert front["trace"][3]["source_ref"] == {"line": 4, "capture_seq": 4, "event_type": "trade"}
    assert case.replay_input.normalized_bytes == source
    for absent in (
        b'"fills"',
        b'"capacity"',
        b'"valuation"',
        b'"claim_observation"',
        b'"findings"',
    ):
        assert absent not in pair.canonical_bytes


def test_source_bindings_target_identity_and_detached_frozen_documents() -> None:
    case = context()
    first = build(case=case)
    reordered = json.dumps(request(), sort_keys=False, indent=2).encode()
    repeated = build_queue_constraint_spec(
        reordered, protocol=case.protocol, replay_input=case.replay_input
    )
    assert first == repeated == load_queue_constraint_spec(first.canonical_bytes)
    assert first.constraint_id == digest(first.canonical_bytes)
    assert first.document["bindings"] == {
        "protocol_id": case.protocol.protocol_id,
        "development_dataset_id": case.replay_input.dataset_id,
        "normalized_sha256": digest(case.replay_input.normalized_bytes),
        "replay_spec_id": case.replay_input.spec.spec_id,
    }
    assert first.document["target"] == {
        "source": "synthetic",
        "instrument": "EUR-USD",
        "session": "replay-fixture-v1",
        "side": "bid",
        "price_ticks": 100,
    }
    pair = validate(first, case)
    assert pair.validation_id == digest(pair.canonical_bytes)
    doc = pair.document
    doc["interpretations"][0]["final_state"]["ahead_lots"] = 999
    assert validate(first, case).document == pair.document
    with pytest.raises(FrozenInstanceError):
        first.constraint_id = "0" * 64
    with pytest.raises(FrozenInstanceError):
        pair.canonical_bytes = b"{}"


def test_explicit_gross_churn_is_a_different_declared_model_not_inferred_from_net_depth() -> None:
    original = build()
    alternative = request()
    alternative["updates"][1].update(additions_lots=3, cancellations_lots=6)
    changed = build(alternative)
    assert changed.constraint_id != original.constraint_id
    assert changed.document["updates"][1]["additions_lots"] == 3
    assert changed.document["updates"][1]["cancellations_lots"] == 6
    assert validate(changed).document["classification"] == "MODEL_SENSITIVITY_CANDIDATE"


def test_no_cancel_negative_control_has_identical_queue_states_for_both_policies() -> None:
    rows = observations()
    rows[2]["bids"] = [[100, 8]]
    rows[4]["bids"] = rows[5]["bids"] = [[100, 5]]
    declaration = request()
    declaration["updates"][1]["cancellations_lots"] = 0
    pair = validate(build(declaration, case=context(records=rows)), context(records=rows)).document
    front, back = pair["interpretations"]
    assert front["trace"] == back["trace"]
    assert (
        front["final_state"]
        == back["final_state"]
        == {
            "ahead_lots": 2,
            "behind_lots": 3,
            "external_lots": 5,
        }
    )


def test_same_time_inputs_keep_capture_order_without_resorting() -> None:
    rows = observations()
    for row in rows:
        row["receive_time_ns"] = 1_700_000_000_000_000_000
        row["event_time_ns"] = 1_699_999_999_999_999_900
    case = context(records=rows)
    pair = validate(build(case=case), case).document
    assert [
        row["source_ref"]["capture_seq"] for row in pair["interpretations"][0]["trace"]
    ] == list(range(1, 7))
    assert pair["interpretations"][0]["final_state"]["external_lots"] == 2


@pytest.mark.parametrize(
    "change", ["unknown", "classification", "bindings", "target", "finding", "execute"]
)
def test_requests_cannot_self_supply_bindings_labels_or_execution(change) -> None:
    declaration = request()
    declaration[change] = "OBSERVATION_COMPATIBLE" if change == "classification" else True
    with pytest.raises(QueueConstraintValidationError):
        build(declaration)


@pytest.mark.parametrize(
    "field,value",
    [
        ("priority", "pro_rata"),
        ("hidden_liquidity", "possible"),
        ("impact", "verified"),
        ("flow_timing", "cancels_then_adds"),
    ],
)
def test_unsupported_assumption_cannot_silently_change_model(field, value) -> None:
    declaration = request()
    declaration["assumptions"][field] = value
    with pytest.raises(QueueConstraintValidationError):
        build(declaration)


@pytest.mark.parametrize("mutation", ["calibrated", "nonempty_evidence", "missing_basis"])
def test_parameter_basis_does_not_upgrade_itself_to_observation_evidence(mutation) -> None:
    declaration = request()
    if mutation == "calibrated":
        declaration["parameter_basis"]["calibration_status"] = "calibrated"
    elif mutation == "nonempty_evidence":
        declaration["parameter_basis"]["calibration_evidence_refs"] = ["c" * 64]
    else:
        del declaration["parameter_basis"]
    with pytest.raises(QueueConstraintValidationError):
        build(declaration)


@pytest.mark.parametrize(
    "field,value",
    [
        ("entry_capture_seq", True),
        ("entry_capture_seq", 2),
        ("schema_version", True),
        ("schema_version", 2),
        ("model_profile_id", "native_queue_front"),
    ],
)
def test_strict_markers_and_true_integer_entry(field, value) -> None:
    declaration = request()
    declaration[field] = value
    with pytest.raises(QueueConstraintValidationError):
        build(declaration)


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_seq", True),
        ("capture_seq", 1),
        ("additions_lots", -1),
        ("cancellations_lots", True),
        ("additions_lots", MAX_QUEUE_LOTS + 1),
        ("trade_capture_seqs", [True]),
        ("trade_capture_seqs", [4, 4]),
    ],
)
def test_update_integer_ranges_and_duplicate_trade_references(field, value) -> None:
    declaration = request()
    declaration["updates"][2][field] = value
    with pytest.raises(QueueConstraintValidationError):
        build(declaration)


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "unsorted", "wrong_interval", "omit_trade", "double_count"]
)
def test_complete_checkpoint_partition_and_trade_reconciliation(mutation) -> None:
    declaration = request()
    if mutation == "missing":
        declaration["updates"].pop()
    elif mutation == "extra":
        declaration["updates"].insert(
            2,
            {
                "capture_seq": 4,
                "additions_lots": 0,
                "cancellations_lots": 0,
                "trade_capture_seqs": [],
            },
        )
    elif mutation == "unsorted":
        declaration["updates"].reverse()
    elif mutation == "wrong_interval":
        declaration["updates"][1]["trade_capture_seqs"] = [4]
    elif mutation == "omit_trade":
        declaration["updates"][2]["trade_capture_seqs"] = []
    else:
        declaration["updates"][2]["cancellations_lots"] = 3
    with pytest.raises(QueueConstraintValidationError):
        build(declaration)


def test_trade_after_last_checkpoint_is_explicitly_unreconciled_at_eof() -> None:
    case = context(records=observations()[:4])
    declaration = request()
    declaration["updates"] = declaration["updates"][:2]
    with pytest.raises(QueueConstraintValidationError, match="EOF reconciliation"):
        build(declaration, case=case)


@pytest.mark.parametrize("side,price", [("buy", 100), ("sell", 99)])
def test_other_trade_scope_is_rejected_not_ignored(side, price) -> None:
    rows = observations()
    rows[3].update(aggressor_side=side, price_ticks=price)
    with pytest.raises(QueueConstraintValidationError, match="only target-price sell"):
        build(case=context(records=rows))


def test_trade_cannot_be_financed_by_addition_at_a_later_checkpoint() -> None:
    rows = observations()
    rows[3]["quantity_lots"] = 6
    declaration = request()
    declaration["updates"][2]["additions_lots"] = 3
    with pytest.raises(QueueConstraintValidationError, match="trade exceeds"):
        build(declaration, case=context(records=rows))


@pytest.mark.parametrize(
    "changes",
    [
        {"execution": {"insert_latency_ns": 1}},
        {"strategy": {"submit_capture_seq": 2}},
        {"strategy": {"limit_price_ticks": 98}},
    ],
)
def test_native_acceptance_is_not_assumed_for_unsupported_entry_conditions(changes) -> None:
    with pytest.raises(QueueConstraintValidationError):
        build(case=context(spec_changes=changes))


def test_frozen_event_budget_is_enforced_without_engine_or_attempt() -> None:
    with pytest.raises(QueueConstraintValidationError, match="event budget"):
        build(case=context(budget=5))


@pytest.mark.parametrize(
    "binding", ["protocol_id", "development_dataset_id", "normalized_sha256", "replay_spec_id"]
)
def test_self_consistent_rehashed_wrong_source_binding_is_rejected(binding) -> None:
    document = build().document
    document["bindings"][binding] = "c" * 64
    forged = load_queue_constraint_spec(canonical(document))
    with pytest.raises(QueueConstraintValidationError, match="bindings mismatch"):
        validate(forged)


def test_target_is_rederived_from_the_actual_protocol_and_source() -> None:
    document = build().document
    document["target"]["price_ticks"] = 99
    with pytest.raises(QueueConstraintValidationError, match="target differs"):
        validate(load_queue_constraint_spec(canonical(document)))


@pytest.mark.parametrize(
    "flag",
    [
        "actual_acceptance_verified",
        "impact_compatibility_verified",
        "native_execution_verified",
        "execution_approved",
    ],
)
def test_loaders_cannot_bless_native_or_market_proofs(flag) -> None:
    document = build().document
    document[flag] = True
    with pytest.raises(QueueConstraintValidationError):
        load_queue_constraint_spec(canonical(document))


def test_frozen_identity_tampering_is_rechecked_when_validating() -> None:
    original = build()
    forged = object.__new__(QueueConstraintSpec)
    object.__setattr__(forged, "constraint_id", "0" * 64)
    object.__setattr__(forged, "canonical_bytes", original.canonical_bytes)
    with pytest.raises(QueueConstraintValidationError, match="identity mismatch"):
        validate(forged)
    with pytest.raises(QueueConstraintValidationError):
        replace(original, constraint_id="0" * 64)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"[]",
        b"\xff",
        b"{" + b" " * 65536 + b"}",
        b'{"kind":1,"kind":2}',
        b'{"kind":1.0}',
        b'{"kind":NaN}',
    ],
)
def test_bounded_json_rejects_bad_encoding_duplicates_floats_and_nonfinite(raw) -> None:
    with pytest.raises(QueueConstraintValidationError):
        build_queue_constraint_spec(
            raw, protocol=context().protocol, replay_input=context().replay_input
        )


@pytest.mark.parametrize("raw", [None, "{}", [], b"", b"{} "])
def test_loader_requires_canonical_immutable_bounded_bytes(raw) -> None:
    with pytest.raises(QueueConstraintValidationError):
        load_queue_constraint_spec(raw)
