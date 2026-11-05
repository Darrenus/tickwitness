"""Declared offline consistency fixtures, never additional native executions.

Saved callback facts are rebound together with their actual tape/specification.
Installed CI separately compares the existing real eleven-slot qualification.
"""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import localcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_reduction_records import receipt_document as reduction_receipt_document

from tickwitness.domain.assumptions import (
    build_assumption_spec,
    build_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.reduction_comparison import (
    COMPARISON_SCOPE,
    COMPARISON_VERIFICATION,
    MAX_REDUCTION_COMPARISON_EXPORT_BYTES,
    ReductionComparison,
    load_reduction_comparison_export,
)
from tickwitness.domain.evidence.reduction_records import build_reduction_run_receipt
from tickwitness.domain.evidence.run_records import (
    AttemptReservation,
    EvidenceValidationError,
    canonical,
    digest,
)
from tickwitness.domain.evidence.scenario_records import (
    SCENARIO_SCOPE,
    ScenarioEvaluation,
    build_scenario_intent,
    build_scenario_run_receipt,
)
from tickwitness.domain.reduction.contracts import (
    ReductionSource,
    build_reduction_recipe,
    materialize_reduction,
)
from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import (
    FINDING_AUTHORITY_ID,
    build_search_finding_protocol,
)
from tickwitness.domain.search.plans import build_search_plan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _reservation(protocol, index):
    raw = canonical(
        {
            "kind": "replay_attempt_reservation_v1",
            "schema_version": 1,
            "protocol_id": protocol.protocol_id,
            "attempt_index": index,
            "nonce": ("a" if index == 1 else "b") * 32,
            "max_wall_seconds": 60,
            "created_at_utc": "2026-10-26T00:00:00.000000+00:00",
        }
    )
    return AttemptReservation(digest(raw), raw)


def _result(replay_input, *, captures, delay, count, tail_mark):
    """Rebind a saved complete trace to a declared consistent prefix/clock fixture."""
    document = json.loads((FIXTURES / "evidence-result.json").read_bytes())
    for channel in ("input_trace", "decision_trace", "order_trace", "fill_trace", "account_trace"):
        kept = []
        for row in document[channel]:
            reference = row["source_ref"]
            if reference is not None:
                line = reference["line"]
                if line > count:
                    continue
                reference["capture_seq"] = captures[line - 1]
                if line >= 4:
                    row["native_time_ns"] += delay
                    for key in (
                        "receive_time_ns",
                        "native_ts_event_ns",
                        "native_ts_init_ns",
                        "native_event_ts_ns",
                        "native_init_ts_ns",
                    ):
                        if key in row["fields"]:
                            row["fields"][key] += delay
                if channel == "input_trace":
                    row["fields"]["native_internal_id"] = (
                        f"CAPTURE-{captures[line - 1]}"
                        if reference["event_type"] == "trade"
                        else str(captures[line - 1])
                    )
                    if line == 7 and tail_mark:
                        row["fields"]["bids"] = [[100, 0]]
            if channel == "account_trace" and row["kind"] == "final_account_snapshot":
                continue
            row["ordinal"] = len(kept)
            kept.append(row)
        document[channel] = kept
    final = deepcopy(document["account_trace"][-1])
    final.update(
        kind="final_account_snapshot",
        ordinal=len(document["account_trace"]),
        source_ref=None,
        native_time_ns=document["input_trace"][-1]["native_time_ns"],
    )
    if count == 7 and tail_mark:
        final["fields"]["bid_levels"] = 1
    document["account_trace"].append(final)
    document["dataset_id"] = replay_input.dataset_id
    document["spec_id"] = replay_input.spec.spec_id
    document["data_sha256"] = digest(replay_input.normalized_bytes)
    document["completeness"].update(input_records=count, processed_records=count)
    if count == 4:
        document["execution_status"] = "incomplete"
        document["completeness"].update(
            stop_reason="input_exhausted_with_open_orders",
            open_orders=[
                {
                    "order_id": final["fields"]["orders"][0]["order_id"],
                    "status": "PARTIALLY_FILLED",
                }
            ],
        )
    return build_replay_result(document)


def comparison_case(
    *,
    count=6,
    capture_start=1,
    original_delay=0,
    reduced_delay=0,
    comparator="gt",
    threshold="0",
    tail_mark=False,
    focus_index=3,
):
    captures = list(range(capture_start, capture_start + 7))
    events = [
        json.loads(line) for line in (FIXTURES / "evidence-events.jsonl").read_bytes().splitlines()
    ]
    for event, capture in zip(events, captures, strict=True):
        event["capture_seq"] = capture
    if tail_mark:
        events[-1]["bids"] = [[100, 0]]
    normalized = normalize_events(b"\n".join(canonical(event) for event in events) + b"\n")
    spec_document = json.loads((FIXTURES / "evidence-replay-spec.json").read_bytes())
    spec_document["strategy"]["submit_capture_seq"] = captures[0]
    spec = build_replay_spec(canonical(spec_document))
    protocol = build_executable_protocol(
        canonical(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Offline original/reduced observation fixture",
                    "hypothesis": "The declared endpoint satisfies the frozen threshold.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": comparator,
                    "threshold": threshold,
                    "unit": "USD",
                },
                "replay_spec": spec.document,
                "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 100},
            }
        ),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
    )
    source_input = ReplayInput("a" * 64, normalized.normalized_bytes, spec)
    assumptions = build_assumption_spec(
        canonical(
            {
                "kind": "assumption_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "transform": {
                    "semantic_id": "replay_receive_suffix_shift_v1",
                    "from_capture_seq": captures[3],
                },
                "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
                "parameter_basis": {
                    "kind": "researcher_defined",
                    "calibration_status": "uncalibrated",
                    "calibration_evidence_refs": [],
                },
            }
        ),
        protocol=protocol,
        replay_input=source_input,
    )
    scenario = build_scenario_spec(
        canonical(
            {
                "kind": "scenario_request_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "additional_delay": {"value": original_delay, "unit": "ns"},
            }
        ),
        assumptions=assumptions,
    )
    validation = validate_scenario_spec(
        scenario, assumptions, protocol=protocol, replay_input=source_input
    )
    view = derive_replay_view(validation)
    original_result = _result(
        view.replay_input, captures=captures, delay=original_delay, count=7, tail_mark=tail_mark
    )
    original_evaluation = ScenarioEvaluation(view, original_result)
    original_receipt = build_scenario_run_receipt(
        {
            "kind": "scenario_run_receipt_v1",
            "schema_version": 1,
            "attempt": _reservation(protocol, 1).document,
            "protocol_id": protocol.protocol_id,
            "claim_revision_id": protocol.claim_revision_id,
            "execution_status": "completed",
            "scope": dict(SCENARIO_SCOPE),
            "intent": build_scenario_intent(view).document,
            "bindings": {
                "replay_result_sha256": digest(original_result.canonical_bytes),
                "evaluation_sha256": original_evaluation.evaluation_id,
            },
        }
    )
    plan = build_search_plan(
        canonical(
            {
                "kind": "search_plan_request_v1",
                "schema_version": 1,
                "search_seed": 7,
                "max_proposals": 1,
                "generator": {"kind": "grid", "values_ns": [original_delay]},
            }
        ),
        protocol=protocol,
        assumptions=assumptions,
    )
    authority = build_search_finding_protocol(
        canonical(
            {
                "kind": "search_finding_request_v1",
                "schema_version": 1,
                "title": "Offline original/reduced numeric criterion",
                "authority": FINDING_AUTHORITY_ID,
            }
        ),
        plan=plan,
    )
    source = ReductionSource(
        "c" * 64,
        "d" * 64,
        authority.protocol_id,
        authority.document["predicate_id"],
        original_receipt.run_id,
        1,
        validation,
    )
    recipe = build_reduction_recipe(
        canonical(
            {
                "kind": "reduction_request_v1",
                "schema_version": 1,
                "witness_ordinal": 1,
                "focus_from_capture_seq": captures[focus_index],
                "through_capture_seq": captures[count - 1],
                "additional_delay_ns": reduced_delay,
            }
        ),
        source=source,
    )
    materialized = materialize_reduction(recipe, source=source)
    reduced_result = _result(
        materialized.replay_input,
        captures=captures,
        delay=reduced_delay,
        count=count,
        tail_mark=tail_mark,
    )
    reduced_receipt = build_reduction_run_receipt(
        reduction_receipt_document(
            SimpleNamespace(
                materialized=materialized,
                result=reduced_result,
                reservation=_reservation(protocol, 2),
            )
        )
    )
    return SimpleNamespace(
        authority=authority,
        materialized=materialized,
        original_receipt=original_receipt,
        original_result=original_result,
        reduced_receipt=reduced_receipt,
        reduced_result=reduced_result,
    )


def compare(fixture=None, **changes):
    values = vars(comparison_case() if fixture is None else fixture).copy()
    values.update(changes)
    return ReductionComparison(**values)


def test_actual_tail_partition_retains_warmup_and_removed_original_events():
    fixture = comparison_case()
    comparison = compare(fixture)
    report = comparison.document
    difference = report["input_difference"]
    assert difference["source_event_count"] == 7
    assert difference["retained_event_count"] == 6
    assert difference["removed_event_count"] == 1
    assert [row["capture_seq"] for row in difference["warmup_refs"]] == [1, 2, 3]
    assert [row["capture_seq"] for row in difference["review_refs"]] == [4, 5, 6]
    removed = difference["removed_events"][0]
    assert removed["source_ref"] == {"line": 7, "capture_seq": 7, "event_type": "delta"}
    assert removed["original_event"]["bids"] == [[100, 1]]
    assert removed["original_line_sha256"] == digest(canonical(removed["original_event"]))
    assert difference["changed_retained_events"] == []
    assert report["both_false_witnesses"] is True
    assert report["original_observation"]["value"] == "-2"
    assert report["reduced_assessment"]["outcome"] == "PRESERVED"
    assert report["horizon"]["same_input_horizon"] is False
    assert report["horizon"]["shared_terminal_state_captured"] is False
    assert report["horizon"]["original"]["through_ref"]["capture_seq"] == 7
    assert report["horizon"]["reduced"]["through_ref"]["capture_seq"] == 6
    trace = report["trace_comparison"]
    assert trace["raw"]["first_divergence"]["json_pointer"] == "/input_trace/6"
    assert trace["raw"]["first_divergence"]["right_present"] is False
    assert trace["business"]["first_divergence"]["json_pointer"] == "/input_trace/6"
    assert trace["global_earliest_claimed"] is False


def test_non_one_capture_origin_retains_actual_source_line_and_capture_references():
    report = compare(comparison_case(capture_start=10)).document
    difference = report["input_difference"]
    assert difference["retained_event_count"] == 6
    assert difference["focus_ref"] == {"line": 4, "capture_seq": 13, "event_type": "delta"}
    assert difference["through_ref"] == {"line": 6, "capture_seq": 15, "event_type": "delta"}
    assert difference["minimum_through_capture_seq"] == 13
    assert difference["removed_events"][0]["source_ref"] == {
        "line": 7,
        "capture_seq": 16,
        "event_type": "delta",
    }


def test_capture_gaps_are_rejected_before_a_comparison_source_can_be_frozen():
    original = comparison_case().materialized.source.validation.replay_input
    events = [json.loads(line) for line in original.normalized_bytes.splitlines()]
    events[-1]["capture_seq"] += 1
    normalized = normalize_events(b"\n".join(canonical(event) for event in events) + b"\n")
    invalid = ReplayInput(original.dataset_id, normalized.normalized_bytes, original.spec)
    with pytest.raises(ReplayValidationError, match="Replay rejects gaps"):
        preflight_replay(invalid)


def test_noop_has_equal_observed_traces_but_still_distinct_consumed_attempts():
    report = compare(comparison_case(count=7)).document
    assert report["input_difference"]["removed_events"] == []
    assert report["trace_comparison"]["raw_trace_changed"] is False
    assert report["trace_comparison"]["business_trace_changed"] is False
    assert report["condition_differences"]
    assert report["horizon"]["same_input_horizon"] is True
    assert (
        report["bindings"]["original"]["attempt_id"] != report["bindings"]["reduced"]["attempt_id"]
    )


def test_legal_clock_changes_have_complete_input_differences_and_projection_scope():
    report = compare(comparison_case(count=7, original_delay=20_000_000)).document
    difference = report["input_difference"]
    assert difference["original_additional_delay_ns"] == 20_000_000
    assert difference["reduced_additional_delay_ns"] == 0
    assert [row["source_ref"]["capture_seq"] for row in difference["changed_retained_events"]] == [
        4,
        5,
        6,
        7,
    ]
    for row in difference["changed_retained_events"]:
        assert row["original_line_sha256"] != row["reduced_line_sha256"]
        field = row["field_differences"][0]
        assert field["json_pointer"] == "/receive_time_ns"
        assert field["original_value"] - field["reduced_value"] == 20_000_000
    assert report["trace_comparison"]["raw_trace_changed"] is True
    assert report["trace_comparison"]["business_trace_changed"] is False
    assert (
        report["trace_comparison"]["projection_policy"]["source_event_time_and_payload_preserved"]
        is True
    )


def test_audited_native_identifiers_are_normalized_only_in_the_business_view():
    fixture = comparison_case(count=7)
    changed = fixture.reduced_result.document
    old_id = changed["decision_trace"][0]["fields"]["order_id"]
    for channel in ("decision_trace", "order_trace", "fill_trace", "account_trace"):
        for row in changed[channel]:
            fields = row["fields"]
            if fields.get("order_id") == old_id:
                fields["order_id"] = "different-native-order"
            for order in fields.get("orders", []):
                if order["order_id"] == old_id:
                    order["order_id"] = "different-native-order"
            if channel == "fill_trace":
                fields["native_trade_id"] = "different-native-fill-" + str(row["ordinal"])
    result = build_replay_result(changed)
    receipt = build_reduction_run_receipt(
        reduction_receipt_document(
            SimpleNamespace(
                materialized=fixture.materialized,
                result=result,
                reservation=_reservation(fixture.materialized.source.validation.protocol, 2),
            )
        )
    )
    report = compare(fixture, reduced_receipt=receipt, reduced_result=result).document
    assert report["both_false_witnesses"] is True
    assert report["trace_comparison"]["raw_trace_changed"] is True
    assert report["trace_comparison"]["business_trace_changed"] is False
    raw = report["trace_comparison"]["raw"]["first_divergence"]
    assert raw["section"] == "decision_trace"
    assert raw["right_raw_value"] == "different-native-order"


def test_focus_is_a_review_boundary_and_does_not_hide_changed_warmup():
    report = compare(comparison_case(original_delay=20_000_000, focus_index=4)).document
    difference = report["input_difference"]
    assert [row["capture_seq"] for row in difference["warmup_refs"]] == [1, 2, 3, 4]
    assert [row["capture_seq"] for row in difference["review_refs"]] == [5, 6]
    assert difference["changed_retained_events"][0]["source_ref"]["capture_seq"] == 4
    assert report["horizon"]["shared_input_event_count"] == 6
    assert report["scope"]["shared_terminal_state_captured"] is False


def test_each_endpoint_has_its_own_mark_and_non_preserved_remains_explicit():
    report = compare(comparison_case(tail_mark=True, threshold="-3")).document
    assert report["original_observation"]["value"] == "-4"
    assert report["original_observation"]["truth"] is False
    assert report["reduced_assessment"]["criterion_observation"]["value"] == "-2"
    assert report["reduced_assessment"]["outcome"] == "NOT_PRESERVED"
    assert report["both_false_witnesses"] is False
    assert report["horizon"]["original"]["mark"]["price"] == "99"
    assert report["horizon"]["reduced"]["mark"]["price"] == "100"
    assert report["scope"]["numeric_effect_comparable"] is False
    assert "numeric_delta" not in report


def test_incomplete_prefix_remains_unknown_with_actual_open_order_and_eof():
    report = compare(comparison_case(count=4)).document
    assert report["both_false_witnesses"] is None
    assessment = report["reduced_assessment"]
    assert assessment["outcome"] == "NOT_EVALUABLE"
    assert assessment["criterion_observation"]["truth"] is None
    assert assessment["criterion_observation"]["value"] is None
    assert report["horizon"]["reduced"]["execution_status"] == "incomplete"
    assert report["horizon"]["reduced"]["mark"] is None
    assert report["horizon"]["reduced"]["completeness"]["open_orders"]
    assert report["trace_comparison"]["business"]["per_channel_first"]["fill_trace"] is not None


@pytest.mark.parametrize(
    ("comparator", "threshold"),
    [("gt", "-2"), ("ge", "-1.999999999999999999"), ("lt", "-2"), ("le", "-2.000000000000000001")],
)
def test_original_false_threshold_is_exact_under_a_low_decimal_context(comparator, threshold):
    fixture = comparison_case(comparator=comparator, threshold=threshold)
    with localcontext() as context:
        context.prec = 2
        report = compare(fixture).document
    assert report["original_observation"]["truth"] is False
    assert report["reduced_assessment"]["outcome"] == "PRESERVED"


def test_an_original_true_result_cannot_be_presented_as_a_false_source_witness():
    with pytest.raises(EvidenceValidationError, match="frozen criterion false"):
        compare(comparison_case(comparator="ge", threshold="-2"))


@pytest.mark.parametrize(
    "attack",
    ["original_result", "original_evaluation", "status", "owner", "claim", "index", "timeout"],
)
def test_rehashed_original_receipt_cannot_replace_binding_owner_or_original_budget(attack):
    fixture = comparison_case()
    document = fixture.original_receipt.document
    if attack in ("original_result", "original_evaluation"):
        key = "replay_result_sha256" if attack == "original_result" else "evaluation_sha256"
        document["bindings"][key] = "f" * 64
    elif attack == "status":
        document["execution_status"] = "incomplete"
    elif attack == "owner":
        for row in (document, document["attempt"], document["intent"]):
            row["protocol_id"] = "f" * 64
    elif attack == "claim":
        document["claim_revision_id"] = "f" * 64
        document["intent"]["claim_revision_id"] = "f" * 64
    else:
        document["attempt"]["attempt_index" if attack == "index" else "max_wall_seconds"] = (
            3 if attack == "index" else 59
        )
    forged = build_scenario_run_receipt(document)
    # Rebind source and recipe as well, so only an outer-ID check cannot pass.
    source = replace(fixture.materialized.source, source_run_id=forged.run_id)
    recipe = build_reduction_recipe(
        canonical(
            {
                "kind": "reduction_request_v1",
                "schema_version": 1,
                "witness_ordinal": 1,
                **fixture.materialized.recipe.document["operators"],
            }
        ),
        source=source,
    )
    materialized = materialize_reduction(recipe, source=source)
    reduced_document = fixture.reduced_result.document
    reduced_document["dataset_id"] = materialized.replay_input.dataset_id
    reduced_result = build_replay_result(reduced_document)
    reduced_receipt = build_reduction_run_receipt(
        reduction_receipt_document(
            SimpleNamespace(
                materialized=materialized,
                result=reduced_result,
                reservation=_reservation(source.validation.protocol, 2),
            )
        )
    )
    with pytest.raises(EvidenceValidationError):
        compare(
            fixture,
            original_receipt=forged,
            materialized=materialized,
            reduced_result=reduced_result,
            reduced_receipt=reduced_receipt,
        )


def test_original_raw_account_corruption_is_validation_failure_not_unknown():
    fixture = comparison_case()
    result = fixture.original_result.document
    result["account_trace"][-1]["fields"]["cash_total"] = "9999"
    with pytest.raises(EvidenceValidationError):
        compare(fixture, original_result=build_replay_result(result))


def test_same_slot_or_changed_environment_is_not_a_controlled_reduction_pair():
    fixture = comparison_case()
    same_slot = fixture.reduced_receipt.document
    same_slot["attempt"] = fixture.original_receipt.document["attempt"]
    with pytest.raises(EvidenceValidationError, match="distinct consumed attempts"):
        compare(fixture, reduced_receipt=build_reduction_run_receipt(same_slot))
    changed = fixture.reduced_result.document
    changed["environment"]["platform"] = "another-runtime"
    result = build_replay_result(changed)
    receipt = build_reduction_run_receipt(
        reduction_receipt_document(
            SimpleNamespace(
                materialized=fixture.materialized,
                result=result,
                reservation=_reservation(fixture.materialized.source.validation.protocol, 2),
            )
        )
    )
    with pytest.raises(EvidenceValidationError, match="running condition differs: environment"):
        compare(fixture, reduced_receipt=receipt, reduced_result=result)


def test_report_is_detached_immutable_and_does_not_rewrite_old_record_flags():
    fixture = comparison_case()
    before = fixture.reduced_receipt.canonical_bytes
    comparison = compare(fixture)
    report = comparison.document
    assert report["scope"] == dict(COMPARISON_SCOPE)
    assert report["verification"] == dict(COMPARISON_VERIFICATION)
    report["scope"]["causal_attribution_issued"] = True
    report["input_difference"]["removed_events"] = []
    assert comparison.document["scope"]["causal_attribution_issued"] is False
    assert comparison.document["input_difference"]["removed_events"]
    assert fixture.reduced_receipt.canonical_bytes == before
    assert (
        fixture.reduced_receipt.document["intent"]["flags"]["witness_preservation_verified"]
        is False
    )
    with pytest.raises(FrozenInstanceError):
        comparison.canonical_bytes = b"{}"


def test_export_is_canonical_bound_and_encoding_validation_is_not_semantic_verification():
    comparison = compare()
    assert load_reduction_comparison_export(comparison.export_bytes) == (
        comparison.comparison_id,
        comparison.document,
    )
    export = json.loads(comparison.export_bytes)
    export["report"]["input_difference"]["removed_event_count"] = 0
    export["comparison_id"] = digest(canonical(export["report"]))
    # A matching hash proves encoding only. Application verification must rebuild it.
    assert load_reduction_comparison_export(canonical(export))[1] != comparison.document


@pytest.mark.parametrize(
    "attack", ["newline", "duplicate", "float", "scope", "schema_bool", "hash", "extra", "oversize"]
)
def test_export_encoding_identity_and_scope_attacks_are_rejected(attack):
    comparison = compare()
    document = json.loads(comparison.export_bytes)
    if attack == "newline":
        raw = comparison.export_bytes + b"\n"
    elif attack == "duplicate":
        raw = comparison.export_bytes[:-1] + b',"schema_version":1}'
    elif attack == "float":
        raw = comparison.export_bytes.replace(b'"schema_version":1', b'"schema_version":1.0', 1)
    elif attack == "oversize":
        raw = b" " * (MAX_REDUCTION_COMPARISON_EXPORT_BYTES + 1)
    else:
        if attack == "scope":
            document["report"]["scope"]["causal_attribution_issued"] = True
            document["comparison_id"] = digest(canonical(document["report"]))
        elif attack == "schema_bool":
            document["schema_version"] = True
        elif attack == "hash":
            document["comparison_id"] = "f" * 64
        else:
            document["extra"] = None
        raw = canonical(document)
    with pytest.raises(EvidenceValidationError):
        load_reduction_comparison_export(raw)


@pytest.mark.parametrize(
    "field",
    [
        "authority",
        "materialized",
        "original_receipt",
        "original_result",
        "reduced_receipt",
        "reduced_result",
    ],
)
def test_untyped_evidence_never_becomes_a_comparison(field):
    with pytest.raises(EvidenceValidationError, match="typed original"):
        compare(**{field: SimpleNamespace()})
