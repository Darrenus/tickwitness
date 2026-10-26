"""Read-only semantic qualification, without a market-compatibility certificate.

The existing queue family authorizes model execution and accounting only. This
report separates its conserved external tape from one deliberately literal
single-counted insertion projection. A residual falsifies that projection, not
every possible ghost/probe model, and never evaluates the source claim.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.assumptions.queue_constraints import MAX_QUEUE_LOTS
from tickwitness.domain.evidence.evaluation import EvaluationValidationError, _money
from tickwitness.domain.evidence.queue_evaluation import evaluate_queue_replay
from tickwitness.domain.evidence.run_records import EvidenceValidationError
from tickwitness.domain.replay._validation import (
    ReplayValidationError,
    canonical,
    digest,
    exact,
    identity,
    integer,
    parse,
    text,
)
from tickwitness.domain.replay.contracts import _source_ref
from tickwitness.domain.replay.queue_contracts import (
    ENGINE,
    QueueReplayInput,
    QueueReplayResult,
    load_queue_replay_result,
)
from tickwitness.domain.research_contracts.protocols import _threshold
from tickwitness.domain.research_contracts.queue_family import QUEUE_POLICY_IDS

Row = dict[str, object]
MAX_QUEUE_SEMANTICS_BYTES = 4 * 1024 * 1024
_POLICY = "queue_pair_semantics_qualification_v1"
_PROJECTION = "literal_order_insertion_single_counted_trade_v1"
_SCOPE: Row = {
    "phase": "development",
    "scenario_kind": "MODEL_SENSITIVITY",
    "source_claim_evaluated": False,
    "claim_verdict_issued": False,
    "finding_issued": False,
}
_COMPATIBILITY: Row = {
    "status": "not_established",
    "reason": "shadow_probe_joint_projection_unverified",
}
_FLOW = {"additions_lots", "cancellations_lots", "trade_lots",
         "cancel_ahead_lots", "cancel_behind_lots"}


class QueueSemanticsValidationError(EvidenceValidationError):
    """The requested pair or its bounded qualification contract is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QueueSemanticsValidationError(message)


def _equal(left: object, right: object, message: str) -> None:
    _require(canonical({"value": left}) == canonical({"value": right}), message)


def _rows(value: object, label: str, *, nonempty: bool = False) -> list[Row]:
    _require(isinstance(value, list) and len(value) <= 1000, label + " must be bounded")
    rows = cast("list[object]", value)
    _require(not nonempty or bool(rows), label + " cannot be empty")
    _require(all(isinstance(row, dict) for row in rows), label + " rows must be objects")
    return cast("list[Row]", rows)


def _state(value: object) -> Row:
    state = exact(value, {"ahead_lots", "behind_lots", "external_lots"}, "queue state")
    for key, item in state.items():
        integer(item, key, 0, MAX_QUEUE_LOTS)
    _require(cast("int", state["ahead_lots"]) + cast("int", state["behind_lots"]) == state["external_lots"],
             "Queue state does not conserve external volume")
    return state


def _validate_trace(value: object, policy: str) -> list[Row]:
    rows = _rows(value, "External-only trace", nonempty=True)
    previous: Row | None = None
    last_capture = last_line = 0
    last_time = 0
    for index, row in enumerate(rows):
        exact(row, {"kind", "source_ref", "receive_time_ns", "before", "flow", "after",
                    "recorded_external_lots"}, "External-only step")
        ref = _source_ref(row["source_ref"])
        assert ref is not None
        last_capture = integer(ref["capture_seq"], "capture_seq", last_capture + 1)
        last_line = integer(ref["line"], "line", last_line + 1, 1000)
        last_time = integer(row["receive_time_ns"], "receive_time_ns", last_time)
        flow = exact(row["flow"], _FLOW, "external flow")
        for key, item in flow.items():
            integer(item, key, 0, MAX_QUEUE_LOTS)
        after = _state(row["after"])
        if index == 0:
            _equal([row["kind"], ref["event_type"], ref["capture_seq"], ref["line"], row["before"]],
                   ["declared_entry", "snapshot", 1, 1, None], "External entry differs")
            _equal(flow, {key: 0 for key in _FLOW}, "Entry cannot consume flow")
            _equal(after["behind_lots"], 0, "Entry cannot contain volume behind the probe")
            integer(after["ahead_lots"], "entry ahead", 1, MAX_QUEUE_LOTS)
        else:
            _equal(row["before"], previous, "External predecessor differs")
            assert previous is not None
            ahead, behind = cast("int", previous["ahead_lots"]), cast("int", previous["behind_lots"])
            if row["kind"] == "trade":
                _equal(ref["event_type"], "trade", "Trade reference type differs")
                trade = cast("int", flow["trade_lots"])
                _require(0 < trade <= ahead + behind, "Trade exceeds external queue")
                consumed_ahead = min(ahead, trade)
                ahead -= consumed_ahead
                behind -= trade - consumed_ahead
                _equal(flow, {key: trade if key == "trade_lots" else 0 for key in _FLOW},
                       "Trade also consumes checkpoint flow")
            else:
                _equal([row["kind"], ref["event_type"]], ["checkpoint", "delta"],
                       "Unsupported external checkpoint")
                behind += cast("int", flow["additions_lots"])
                cancellation = cast("int", flow["cancellations_lots"])
                _require(cancellation <= ahead + behind, "Cancellation exceeds external queue")
                front = (min(cancellation, ahead) if policy == QUEUE_POLICY_IDS[0]
                         else max(0, cancellation - behind))
                back = cancellation - front
                _equal([flow["trade_lots"], flow["cancel_ahead_lots"], flow["cancel_behind_lots"]],
                       [0, front, back], "Checkpoint cancellation policy differs")
                ahead -= front
                behind -= back
            _equal(after, {"ahead_lots": ahead, "behind_lots": behind,
                           "external_lots": ahead + behind}, "External transition differs")
        if row["kind"] == "trade":
            _equal(row["recorded_external_lots"], None, "Trade has no absolute L2 checkpoint")
        else:
            _equal(row["recorded_external_lots"], after["external_lots"],
                   "External projection differs from absolute source checkpoint")
        previous = after
    _equal(rows[-1]["kind"], "checkpoint", "Final external projection lacks reconciliation")
    return rows


def _single_counted(trace: list[Row], own_by_line: dict[int, int]) -> Row:
    """Compute a necessary volume residual for one explicitly named projection."""
    trades: list[Row] = []
    checkpoints: list[Row] = []
    cumulative = 0
    contradiction = False
    for row in trace:
        ref = cast("Row", row["source_ref"])
        if row["kind"] == "trade":
            public = cast("int", cast("Row", row["flow"])["trade_lots"])
            own = own_by_line.get(cast("int", ref["line"]), 0)
            cumulative += own
            total = public + own
            residual = max(0, total - public)
            trades.append({
                "source_ref": ref, "receive_time_ns": row["receive_time_ns"],
                "public_trade_lots": public, "external_consumed_lots": public,
                "own_filled_lots": own, "total_allocated_lots": total,
                "over_allocation_lots": residual,
            })
            contradiction |= residual > 0
        else:
            observed = cast("int", row["recorded_external_lots"])
            checkpoints.append({
                "source_ref": ref, "receive_time_ns": row["receive_time_ns"],
                "recorded_external_lots": observed, "cumulative_own_filled_lots": cumulative,
                "candidate_projected_external_lots": observed + cumulative,
                "mismatch_lots": cumulative,
            })
            contradiction |= cumulative > 0
    return {
        "projection_id": _PROJECTION,
        "status": "contradiction" if contradiction else "necessary_checks_passed",
        "trades": trades,
        "checkpoints": checkpoints,
    }


def _model(replay_input: QueueReplayInput, result: QueueReplayResult) -> Row:
    evaluation = evaluate_queue_replay(replay_input, result)
    interpretations = cast("list[Row]", replay_input.feasibility.document["interpretations"])
    selected = next(row for row in interpretations if row["policy_id"] == replay_input.policy_id)
    events = {event.line: event for event in replay_input.prepared.events}
    trace: list[Row] = []
    for row in cast("list[Row]", selected["trace"]):
        event = events[cast("int", cast("Row", row["source_ref"])["line"])]
        recorded = None if event.event_type == "trade" else dict(event.bids).get(
            cast("int", cast("Row", replay_input.family.constraint.document["target"])["price_ticks"])
        trace.append({**row, "recorded_external_lots": recorded})
    own_by_line: dict[int, int] = {}
    for row in cast("list[Row]", result.document["fill_trace"]):
        line = cast("int", cast("Row", row["source_ref"])["line"])
        own_by_line[line] = own_by_line.get(line, 0) + cast("int", cast("Row", row["fields"])["quantity_lots"])
    return {
        "policy_id": replay_input.policy_id, "result_sha256": digest(result.canonical_bytes),
        "evaluation_sha256": evaluation.evaluation_id, "execution_audit_status": "verified",
        "filled_quantity_lots": evaluation.document["filled_quantity_lots"],
        "actual_commission": evaluation.document["actual_commission"],
        "external_only_projection": {"status": "verified", "trace": trace},
        "single_counted_insertion": _single_counted(trace, own_by_line),
    }


def _validate_model(value: object, policy: str) -> Row:
    model = exact(value, {"policy_id", "result_sha256", "evaluation_sha256", "execution_audit_status",
                          "filled_quantity_lots", "actual_commission", "external_only_projection",
                          "single_counted_insertion"}, "Queue semantic model")
    _equal(model["policy_id"], policy, "Queue pair policies or order differ")
    for key in ("result_sha256", "evaluation_sha256"):
        identity(model[key], key)
    _equal(model["execution_audit_status"], "verified", "Semantic input execution is not audited")
    integer(model["filled_quantity_lots"], "filled_quantity_lots", 0, MAX_QUEUE_LOTS)
    _money(model["actual_commission"], "actual_commission", nonnegative=True)
    projection = exact(model["external_only_projection"], {"status", "trace"}, "External projection")
    _equal(projection["status"], "verified", "External source projection is not verified")
    trace = _validate_trace(projection["trace"], policy)
    insertion = exact(model["single_counted_insertion"], {"projection_id", "status", "trades", "checkpoints"},
                      "Single-counted insertion diagnostic")
    own: dict[int, int] = {}
    for row in _rows(insertion["trades"], "Insertion trades"):
        exact(row, {"source_ref", "receive_time_ns", "public_trade_lots", "external_consumed_lots",
                    "own_filled_lots", "total_allocated_lots", "over_allocation_lots"}, "Insertion trade")
        ref = _source_ref(row["source_ref"])
        assert ref is not None
        line = cast("int", ref["line"])
        _require(line not in own, "Duplicate insertion trade")
        own[line] = integer(row["own_filled_lots"], "own_filled_lots", 0, MAX_QUEUE_LOTS)
    _equal(insertion, _single_counted(trace, own), "Insertion allocation/residual diagnostic differs")
    _equal(sum(own.values()), model["filled_quantity_lots"], "Insertion fills differ from native audit")
    return model


def _validated(raw: bytes) -> Row:
    document = exact(parse(raw, MAX_QUEUE_SEMANTICS_BYTES), {
        "kind", "schema_version", "qualification_policy", "scope", "bindings", "common_conditions",
        "observation_compatibility", "predicate", "models", "pair_relation", "findings",
    }, "Queue pair semantics")
    _equal([document["kind"], document["schema_version"], document["qualification_policy"]],
           ["queue_pair_semantics_v1", 1, _POLICY], "Unsupported queue semantic qualification")
    _equal(document["scope"], _SCOPE, "Queue semantic scope cannot issue findings or evaluate source claims")
    _equal(document["observation_compatibility"], _COMPATIBILITY, "No compatibility certificate is supported")
    _equal([document["pair_relation"], document["findings"]], ["not_evaluable", []],
           "This qualification cannot issue a truth relation or findings")
    bindings = exact(document["bindings"], {"family_id", "source_protocol_id", "source_claim_revision_id",
                                           "dataset_id", "data_sha256", "spec_id", "constraint_id"},
                     "Queue semantic bindings")
    for key, value in bindings.items():
        identity(value, key)
    common = exact(document["common_conditions"], {"engine", "environment", "target", "assumptions", "parameter_basis"},
                   "Queue semantic conditions")
    _equal(common["engine"], ENGINE, "Queue semantic engine differs")
    environment = exact(common["environment"], {"python_version", "platform", "package_versions"}, "Environment")
    text(environment["python_version"], "python_version")
    text(environment["platform"], "platform", 512)
    packages = environment["package_versions"]
    _require(isinstance(packages, dict) and 1 <= len(packages) <= 128, "Bounded package versions required")
    for key, value in cast("Row", packages).items():
        text(key, "package")
        text(value, "version")
    _equal(cast("Row", packages).get("nautilus_trader"), "1.231.0", "Native package version differs")
    target = exact(common["target"], {"source", "instrument", "session", "side", "price_ticks"}, "Queue target")
    for key in ("source", "instrument", "session"):
        text(target[key], key, 128)
    _equal([target["instrument"], target["side"]], ["EUR-USD", "bid"], "Queue target profile differs")
    integer(target["price_ticks"], "price_ticks", 1)
    _equal(common["assumptions"], {"priority": "fifo", "hidden_liquidity": "excluded",
                                  "impact": "shadow_no_impact_unverified",
                                  "flow_timing": "adds_then_cancels_at_checkpoint_v1"}, "Queue assumptions differ")
    _equal(common["parameter_basis"], {"kind": "researcher_defined", "calibration_status": "uncalibrated",
                                      "calibration_evidence_refs": []}, "Queue parameter basis differs")
    predicate = exact(document["predicate"], {"status", "reason", "metric", "unit", "comparator", "threshold",
                                            "source_claim_revision_id", "values", "satisfied", "truth_divergence"},
                      "Unsupported source-claim predicate")
    _equal([predicate["status"], predicate["reason"], predicate["metric"], predicate["unit"],
            predicate["source_claim_revision_id"]],
           ["not_evaluable", "queue_family_claim_lineage_only", "net_marked_pnl_v1", "USD",
            bindings["source_claim_revision_id"]], "Source-claim observation changed")
    _require(predicate["comparator"] in ("gt", "ge", "lt", "le"), "Unsupported source comparator")
    _equal(predicate["threshold"], _threshold(predicate["threshold"]), "Source threshold is not canonical")
    _equal([predicate["values"], predicate["satisfied"], predicate["truth_divergence"]],
           [{policy: None for policy in QUEUE_POLICY_IDS}, {policy: None for policy in QUEUE_POLICY_IDS}, None],
           "Unfrozen queue predicate cannot yield values or truth")
    models = _rows(document["models"], "Queue models", nonempty=True)
    _require(len(models) == 2, "Exactly two frozen policies are required")
    for value, policy in zip(models, QUEUE_POLICY_IDS, strict=True):
        _validate_model(value, policy)
    left, right = (cast("Row", model["external_only_projection"]) for model in models)
    # Cancellation locations may differ. The public flow totals and observations may not.
    def public_trace(projection: Row) -> list[Row]:
        result: list[Row] = []
        for row in cast("list[Row]", projection["trace"]):
            item = {key: row[key] for key in ("kind", "source_ref", "receive_time_ns", "flow", "recorded_external_lots")}
            flow = dict(cast("Row", item["flow"]))
            flow.pop("cancel_ahead_lots")
            flow.pop("cancel_behind_lots")
            item["flow"] = flow
            result.append(item)
        return result
    _equal(public_trace(left), public_trace(right), "Policy projections do not share public observations and flow")
    _require(canonical(document) == raw, "Queue semantic qualification requires canonical JSON")
    return document


@dataclass(frozen=True, slots=True)
class QueuePairQualification:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        try:
            _validated(self.canonical_bytes)
        except (ReplayValidationError, EvaluationValidationError, ValueError) as error:
            raise QueueSemanticsValidationError(str(error)) from error

    @property
    def qualification_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, MAX_QUEUE_SEMANTICS_BYTES)


def qualify_queue_pair(
    left_input: QueueReplayInput, left_result: QueueReplayResult,
    right_input: QueueReplayInput, right_result: QueueReplayResult,
) -> QueuePairQualification:
    """Audit a controlled pair; never grant observation-compatibility or claim permission."""
    try:
        _require(type(left_input) is QueueReplayInput and type(right_input) is QueueReplayInput,
                 "Queue semantics requires immutable queue inputs")
        _require(type(left_result) is QueueReplayResult and type(right_result) is QueueReplayResult,
                 "Queue semantics requires immutable queue results")
        pairs = {item.policy_id: (QueueReplayInput(item.family, item.normalized_bytes, item.policy_id),
                                  load_queue_replay_result(result.canonical_bytes))
                 for item, result in ((left_input, left_result), (right_input, right_result))}
        _require(set(pairs) == set(QUEUE_POLICY_IDS), "Pair must contain exactly front and back policies")
        ordered = [pairs[policy] for policy in QUEUE_POLICY_IDS]
        first_input, first_result = ordered[0]
        second_input, second_result = ordered[1]
        _require(first_input.family.canonical_bytes == second_input.family.canonical_bytes,
                 "Queue pair does not share a complete frozen family")
        _require(first_input.normalized_bytes == second_input.normalized_bytes,
                 "Queue pair does not share actual normalized source bytes")
        _equal(first_input.replay_input.dataset_id, second_input.replay_input.dataset_id, "Queue pair dataset differs")
        for key in ("engine", "environment"):
            _equal(first_result.document[key], second_result.document[key], "Queue pair common condition differs: " + key)
        family = first_input.family
        claim = cast("Row", family.source_protocol.document["claim"])
        source = first_input.bindings
        constraint = family.constraint.document
        return QueuePairQualification(canonical({
            "kind": "queue_pair_semantics_v1", "schema_version": 1, "qualification_policy": _POLICY,
            "scope": dict(_SCOPE),
            "bindings": {"family_id": family.family_id, "source_protocol_id": family.source_protocol.protocol_id,
                         "source_claim_revision_id": family.claim_revision_id, "dataset_id": source["dataset_id"],
                         "data_sha256": source["data_sha256"], "spec_id": source["spec_id"], "constraint_id": source["constraint_id"]},
            "common_conditions": {"engine": first_result.document["engine"], "environment": first_result.document["environment"],
                                  "target": constraint["target"], "assumptions": constraint["assumptions"], "parameter_basis": constraint["parameter_basis"]},
            "observation_compatibility": dict(_COMPATIBILITY),
            "predicate": {"status": "not_evaluable", "reason": "queue_family_claim_lineage_only",
                          "metric": claim["metric"], "unit": claim["unit"], "comparator": claim["comparator"], "threshold": claim["threshold"],
                          "source_claim_revision_id": family.claim_revision_id,
                          "values": {policy: None for policy in QUEUE_POLICY_IDS}, "satisfied": {policy: None for policy in QUEUE_POLICY_IDS},
                          "truth_divergence": None},
            "models": [_model(item, result) for item, result in ordered],
            "pair_relation": "not_evaluable", "findings": [],
        }))
    except (ReplayValidationError, EvaluationValidationError, ValueError) as error:
        raise QueueSemanticsValidationError(str(error)) from error


def load_queue_pair_qualification(raw: bytes) -> QueuePairQualification:
    return QueuePairQualification(raw)
