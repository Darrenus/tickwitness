"""Portable re-audit of two tagged reconstructions; no ledger, IO or native runtime.

Selected reservations are evidence of their declared slots, never proof of all
attempt history or authentic authorship. Hashes close bytes; source replay audit
rebuilds economics. The frozen protocol still authorizes no production finding.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.tagged_queue_evaluation import evaluate_tagged_queue_replay
from tickwitness.domain.evidence.tagged_queue_records import (
    TaggedQueueAttemptReservation,
    build_tagged_queue_intent,
    load_tagged_queue_run_receipt,
)
from tickwitness.domain.replay._validation import exact
from tickwitness.domain.replay.tagged_queue_contracts import (
    TaggedQueueReplayInput,
    load_tagged_queue_replay_result,
)
from tickwitness.domain.research_contracts.tagged_queue_protocol import (
    TAGGED_MODEL,
    TAGGED_POLICY_IDS,
    TAGGED_SCOPE,
    TaggedQueueProtocol,
    load_tagged_queue_protocol,
)

Row = dict[str, object]
_MIB = 1024 * 1024
MAX_ASSESSMENT_BYTES = 256 * 1024
PAYLOAD_LIMITS = {
    "protocol": 256 * 1024,
    "dataset_manifest": 64 * 1024,
    "raw": 8 * _MIB,
    "normalized": 8 * _MIB,
    "report": 4 * _MIB,
    "front_result": 16 * _MIB,
    "front_evaluation": 64 * 1024,
    "front_receipt": _MIB,
    "back_result": 16 * _MIB,
    "back_evaluation": 64 * 1024,
    "back_receipt": _MIB,
}
PAYLOAD_ROLES = frozenset(PAYLOAD_LIMITS)
ARTIFACT_ROLES = PAYLOAD_ROLES | {"assessment"}
_POLICY = "tagged_queue_pair_offline_audit_v1"
_FLAGS = {
    "integrity_verified": True,
    "bindings_verified": True,
    "source_revalidated": True,
    "queue_execution_audited": True,
    "native_replayed": False,
    "author_signature_verified": False,
    "confirmation_reference_checked": False,
    "full_attempt_ledger_checked": False,
    "ledger_commitment_checked": False,
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _equal(actual: object, expected: object, message: str) -> None:
    _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _payload(artifacts: dict[str, bytes], *, sealed: bool) -> dict[str, bytes]:
    roles = ARTIFACT_ROLES if sealed else PAYLOAD_ROLES
    _require(
        type(artifacts) is dict and artifacts.keys() == roles,
        "Tagged pair requires exact artifact roles",
    )
    limits = {**PAYLOAD_LIMITS, "assessment": MAX_ASSESSMENT_BYTES}
    for role, value in artifacts.items():
        _require(
            type(value) is bytes and 0 < len(value) <= limits[role],
            "Tagged artifact is empty, mutable or exceeds its bound: " + role,
        )
    return dict(artifacts)


def _source(artifacts: dict[str, bytes], protocol: TaggedQueueProtocol) -> None:
    bindings = cast("dict[str, str]", protocol.document["bindings"])
    manifest_raw = artifacts["dataset_manifest"]
    manifest = exact(
        parse(manifest_raw, limit=65_536),
        {"schema_version", "format_id", "objects"},
        "Dataset manifest",
    )
    _equal(
        [manifest["schema_version"], manifest["format_id"]],
        [1, "tickwitness.normalized-events.v1"],
        "Unsupported tagged dataset format",
    )
    _require(canonical(manifest) == manifest_raw, "Tagged dataset manifest must be canonical")
    _equal(
        digest(manifest_raw),
        bindings["development_dataset_id"],
        "Tagged dataset identity differs from frozen source",
    )
    objects = exact(manifest["objects"], {"raw", "normalized", "report"}, "Dataset objects")
    for role in ("raw", "normalized", "report"):
        content = artifacts[role]
        sha = digest(content)
        _equal(
            objects[role],
            {"sha256": sha, "size_bytes": len(content), "ref": f"objects/sha256/{sha}"},
            "Tagged source closure differs: " + role,
        )
    normalized = normalize_events(artifacts["raw"])
    _require(
        normalized.normalized_bytes == artifacts["normalized"]
        and canonical(normalized.report) == artifacts["report"],
        "Tagged source normalization or quality report does not reproduce",
    )
    _equal(
        normalized.report["quality_status"], "accepted", "Quarantined tagged evidence is ineligible"
    )
    _equal(
        digest(artifacts["normalized"]),
        bindings["normalized_sha256"],
        "Tagged normalized source differs from frozen input",
    )


def _run(
    artifacts: dict[str, bytes], protocol: TaggedQueueProtocol, role: str, policy: str
) -> tuple[Row, Row]:
    receipt = load_tagged_queue_run_receipt(artifacts[role + "_receipt"])
    run = receipt.document
    _require(canonical(run) == receipt.canonical_bytes, "Tagged run receipt must be canonical")
    _equal(
        [run["protocol_id"], run["claim_revision_id"], run["execution_status"]],
        [protocol.protocol_id, protocol.claim_revision_id, "completed"],
        "Tagged run has a different protocol/claim/status",
    )
    intent = build_tagged_queue_intent(protocol, policy)
    _equal(
        run["intent"], intent.document, "Tagged role has a different full frozen intent or policy"
    )
    attempt_raw = canonical(cast("Row", run["attempt"]))
    attempt = TaggedQueueAttemptReservation(digest(attempt_raw), attempt_raw)
    # Receipt loader enforces owner identity, index bound, and frozen wall time.
    result = load_tagged_queue_replay_result(artifacts[role + "_result"])
    request = TaggedQueueReplayInput(protocol, artifacts["normalized"], policy)
    evaluation = evaluate_tagged_queue_replay(request, result)
    _require(
        evaluation.canonical_bytes == artifacts[role + "_evaluation"],
        "Tagged evaluation does not reproduce from source and actual callbacks",
    )
    _equal(
        run["bindings"],
        {
            "replay_result_sha256": digest(result.canonical_bytes),
            "evaluation_sha256": evaluation.evaluation_id,
        },
        "Tagged receipt hash bindings differ",
    )
    edoc, rdoc = evaluation.document, result.document
    claim = cast("Row", edoc["claim_evaluation"])
    return {
        "role": role,
        "policy_id": policy,
        "run_id": receipt.run_id,
        "attempt_id": attempt.attempt_id,
        "attempt_index": attempt.attempt_index,
        "intent_id": intent.intent_id,
        "result_sha256": digest(result.canonical_bytes),
        "evaluation_sha256": evaluation.evaluation_id,
        "truth": claim["truth"],
        "valuation": edoc["valuation"],
        "horizon": rdoc["horizon_snapshot"],
    }, cast("Row", rdoc["environment"])


def _assess(artifacts: dict[str, bytes]) -> Row:
    protocol = load_tagged_queue_protocol(artifacts["protocol"])
    _source(artifacts, protocol)
    front, front_env = _run(artifacts, protocol, "front", TAGGED_POLICY_IDS[0])
    back, back_env = _run(artifacts, protocol, "back", TAGGED_POLICY_IDS[1])
    _require(
        front["attempt_id"] != back["attempt_id"]
        and front["attempt_index"] != back["attempt_index"],
        "Tagged pair reuses the same attempt or shared budget slot",
    )
    _require(front["run_id"] != back["run_id"], "Tagged pair reuses a run")
    truths = [front["truth"], back["truth"]]
    same_env = canonical(front_env) == canonical(back_env)
    eligible = all(type(truth) is bool for truth in truths)
    reason = (
        "execution_environment_mismatch"
        if not same_env
        else "claim_evaluation_ineligible"
        if not eligible
        else None
    )
    relation = (
        "ineligible"
        if reason
        else "opposite_truth_values"
        if truths[0] != truths[1]
        else "same_truth_value"
    )
    witnesses = TaggedQueueReplayInput(
        protocol, artifacts["normalized"], TAGGED_POLICY_IDS[0]
    ).witnesses
    return {
        "kind": "tagged_queue_pair_assessment_v1",
        "schema_version": 1,
        "audit_policy": _POLICY,
        "bindings": {role: digest(data) for role, data in sorted(artifacts.items())},
        "protocol_id": protocol.protocol_id,
        "claim_revision_id": protocol.claim_revision_id,
        "dataset_id": cast("Row", protocol.document["bindings"])["development_dataset_id"],
        "witness_pair_id": witnesses.witness_id,
        "model": protocol.document["model"],
        "scope": protocol.document["scope"],
        "runs": [front, back],
        "comparison": {
            "relation": relation,
            "truths": truths,
            "same_execution_environment": same_env,
            "ineligible_reason": reason,
        },
        "findings": [],
    }


@dataclass(frozen=True, slots=True)
class TaggedPairAssessment:
    """Immutable derived bytes; semantic authority requires the complete artifact set."""

    canonical_bytes: bytes

    def __post_init__(self) -> None:
        from tickwitness.domain.assumptions.queue_constraints import MAX_QUEUE_LOTS
        from tickwitness.domain.evidence.evaluation import _decimal, _money, _number
        from tickwitness.domain.replay._validation import integer
        from tickwitness.domain.replay.contracts import _source_ref
        from tickwitness.domain.replay.tagged_queue_contracts import _account

        doc = parse(self.canonical_bytes, limit=MAX_ASSESSMENT_BYTES)
        exact(
            doc,
            {
                "kind",
                "schema_version",
                "audit_policy",
                "bindings",
                "protocol_id",
                "claim_revision_id",
                "dataset_id",
                "witness_pair_id",
                "model",
                "scope",
                "runs",
                "comparison",
                "findings",
            },
            "Tagged pair assessment",
        )
        _equal(
            [doc["kind"], doc["schema_version"], doc["audit_policy"]],
            ["tagged_queue_pair_assessment_v1", 1, _POLICY],
            "Unsupported tagged pair assessment",
        )
        bindings = exact(doc["bindings"], set(PAYLOAD_ROLES), "Tagged pair bindings")
        for key, value in bindings.items():
            identity(value)
        for key in ("protocol_id", "claim_revision_id", "dataset_id", "witness_pair_id"):
            identity(doc[key])
        _equal(doc["scope"], TAGGED_SCOPE, "Tagged assessment cannot expand frozen authority")
        _equal(doc["model"], TAGGED_MODEL, "Tagged assessment model differs")
        _equal(doc["findings"], [], "Tagged assessment cannot issue findings")
        _equal(doc["protocol_id"], bindings["protocol"], "Assessment protocol identity differs")
        _equal(
            doc["dataset_id"], bindings["dataset_manifest"], "Assessment dataset identity differs"
        )

        def mark(value: object) -> Row:
            checked = exact(
                value, {"source_ref", "price_ticks", "available_quantity_lots"}, "Tagged mark"
            )
            _source_ref(checked["source_ref"])
            integer(checked["price_ticks"], "mark price", 1)
            integer(checked["available_quantity_lots"], "mark quantity", 1)
            return checked

        runs = doc["runs"]
        _require(type(runs) is list and len(runs) == 2, "Assessment requires two ordered runs")
        checked_runs: list[Row] = []
        for value, role, policy in zip(
            cast("list[object]", runs), ("front", "back"), TAGGED_POLICY_IDS, strict=True
        ):
            run = exact(
                value,
                {
                    "role",
                    "policy_id",
                    "run_id",
                    "attempt_id",
                    "attempt_index",
                    "intent_id",
                    "result_sha256",
                    "evaluation_sha256",
                    "truth",
                    "valuation",
                    "horizon",
                },
                "Tagged assessment run",
            )
            _equal(
                [run["role"], run["policy_id"]],
                [role, policy],
                "Assessment run role/policy differs",
            )
            for key in ("run_id", "attempt_id", "intent_id", "result_sha256", "evaluation_sha256"):
                identity(run[key])
            integer(run["attempt_index"], "attempt index", 1, 100)
            for key, suffix in (
                ("run_id", "receipt"),
                ("result_sha256", "result"),
                ("evaluation_sha256", "evaluation"),
            ):
                _equal(
                    run[key],
                    bindings[role + "_" + suffix],
                    "Assessment run hash differs from artifact binding",
                )
            valuation = exact(
                run["valuation"],
                {
                    "policy_id",
                    "eligible",
                    "reason",
                    "mark",
                    "net_marked_pnl",
                    "unit",
                    "interpretation",
                },
                "Tagged assessment valuation",
            )
            _equal(
                [valuation["policy_id"], valuation["unit"], valuation["interpretation"]],
                [
                    "tagged_inventory_final_visible_bid_flat_zero_v1",
                    "USD",
                    "conditional_tagged_inventory_mark_not_liquidation",
                ],
                "Unsupported assessment valuation",
            )
            _require(
                type(valuation["eligible"]) is bool,
                "Assessment valuation eligibility must be boolean",
            )
            valuation_mark = mark(valuation["mark"])
            if valuation["eligible"]:
                _equal(
                    valuation["reason"], None, "Eligible assessment valuation has exclusion reason"
                )
                pnl = _number(valuation["net_marked_pnl"], "assessment net marked PnL")
                _equal(
                    valuation["net_marked_pnl"],
                    _decimal(pnl),
                    "Assessment marked PnL is not canonical",
                )
                _require(type(run["truth"]) is bool, "Eligible assessment truth must be boolean")
            else:
                _equal(
                    [valuation["reason"], valuation["net_marked_pnl"], run["truth"]],
                    ["native_fee_rounding_ambiguous", None, None],
                    "Ineligible assessment valuation must withhold truth",
                )
            horizon = exact(
                run["horizon"],
                {
                    "source_ref",
                    "native_time_ns",
                    "queue_state",
                    "native_target_lots",
                    "mark",
                    "account",
                },
                "Tagged assessment horizon",
            )
            source = _source_ref(horizon["source_ref"])
            assert source is not None
            _equal(source["event_type"], "delta", "Assessment horizon must be a final checkpoint")
            integer(source["line"], "horizon line", 2)
            integer(source["capture_seq"], "horizon capture", 2)
            integer(horizon["native_time_ns"], "horizon native time")
            state = exact(
                horizon["queue_state"],
                {
                    "ahead_lots",
                    "own_live_lots",
                    "behind_lots",
                    "external_lots",
                    "total_lots",
                    "own_filled_lots",
                },
                "Tagged assessment queue",
            )
            quantities = {key: integer(item, key, 0, MAX_QUEUE_LOTS) for key, item in state.items()}
            ahead, own, behind, filled = (
                quantities[key]
                for key in ("ahead_lots", "own_live_lots", "behind_lots", "own_filled_lots")
            )
            requested = own + filled
            integer(requested, "tagged quantity", 1, MAX_QUEUE_LOTS)
            _equal(
                [state["external_lots"], state["total_lots"]],
                [ahead + behind, ahead + own + behind],
                "Assessment horizon queue does not conserve total",
            )
            integer(horizon["native_target_lots"], "horizon target quantity", 0, MAX_QUEUE_LOTS)
            _equal(
                horizon["native_target_lots"],
                state["total_lots"],
                "Assessment native target differs from queue total",
            )
            horizon_mark = mark(horizon["mark"])
            _equal(horizon_mark, valuation_mark, "Assessment valuation mark differs from horizon")
            _equal(
                horizon_mark["source_ref"],
                horizon["source_ref"],
                "Assessment mark is not from final checkpoint",
            )
            _account(horizon["account"])
            account = cast("Row", horizon["account"])
            _equal(
                [
                    account["account_type"],
                    account["oms_type"],
                    account["currency"],
                    account["book_type"],
                    account["native_money_precision"],
                ],
                ["MARGIN", "NETTING", "USD", "L2_MBP", 2],
                "Unsupported assessment horizon account",
            )
            _equal(
                account["money_rounding_policy"],
                "native_v1_f64_notional_then_USD_Money_precision_2",
                "Unsupported assessment rounding policy",
            )
            _equal(
                account["cash_semantics"],
                "native_margin_balance_not_spot_notional_debit",
                "Unsupported assessment cash semantics",
            )
            _equal(
                [account["net_position_lots"], account["observed_fill_lots"]],
                [filled, filled],
                "Assessment horizon position differs from tagged fills",
            )
            total = _money(account["cash_total"], "assessment cash")
            free = _money(account["cash_free"], "assessment free cash")
            locked = _money(account["cash_locked"], "assessment locked cash", nonnegative=True)
            _money(account["observed_commission"], "assessment commission", nonnegative=True)
            _require(free + locked == total, "Assessment horizon cash does not conserve total")
            orders = cast("list[Row]", account["orders"])
            _require(len(orders) == 1, "Assessment horizon requires a single tagged order")
            order = orders[0]
            _equal(
                [
                    order["quantity_lots"],
                    order["filled_quantity_lots"],
                    order["remaining_quantity_lots"],
                ],
                [requested, filled, own],
                "Assessment horizon order differs from tagged queue",
            )
            status = "FILLED" if own == 0 else "PARTIALLY_FILLED" if filled else "ACCEPTED"
            _equal(order["status"], status, "Assessment horizon order is not pre-cleanup")
            checked_runs.append(run)

        front, back = checked_runs
        for key in ("run_id", "attempt_id", "attempt_index", "intent_id"):
            _require(front[key] != back[key], "Assessment reuses a run, attempt, slot or intent")
        front_horizon, back_horizon = cast("Row", front["horizon"]), cast("Row", back["horizon"])
        for key in ("source_ref", "native_time_ns", "native_target_lots", "mark"):
            _equal(
                front_horizon[key],
                back_horizon[key],
                "Assessment horizons do not share the observation",
            )
        front_state = cast("dict[str, int]", front_horizon["queue_state"])
        back_state = cast("dict[str, int]", back_horizon["queue_state"])
        _equal(
            front_state["own_live_lots"] + front_state["own_filled_lots"],
            back_state["own_live_lots"] + back_state["own_filled_lots"],
            "Assessment runs use different tagged quantities",
        )
        comparison = exact(
            doc["comparison"],
            {"relation", "truths", "same_execution_environment", "ineligible_reason"},
            "Tagged assessment comparison",
        )
        _require(
            type(comparison["same_execution_environment"]) is bool,
            "Assessment environment equality must be boolean",
        )
        truths = [front["truth"], back["truth"]]
        _equal(comparison["truths"], truths, "Assessment comparison rewrites run truth")
        eligible = all(type(truth) is bool for truth in truths)
        reason = (
            "execution_environment_mismatch"
            if comparison["same_execution_environment"] is False
            else "claim_evaluation_ineligible"
            if not eligible
            else None
        )
        relation = (
            "ineligible"
            if reason
            else "opposite_truth_values"
            if truths[0] != truths[1]
            else "same_truth_value"
        )
        _equal(
            [comparison["relation"], comparison["ineligible_reason"]],
            [relation, reason],
            "Assessment comparison eligibility or relation differs",
        )
        _require(canonical(doc) == self.canonical_bytes, "Tagged assessment must be canonical")

    @property
    def assessment_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> Row:
        return parse(self.canonical_bytes, limit=MAX_ASSESSMENT_BYTES)


def assess_tagged_pair_artifacts(artifacts: dict[str, bytes]) -> TaggedPairAssessment:
    """Rebuild source, both feasible queues, native callbacks and pair relation."""
    checked = _payload(artifacts, sealed=False)
    try:
        return TaggedPairAssessment(canonical(_assess(checked)))
    except EvidenceValidationError:
        raise
    except ValueError as error:
        raise EvidenceValidationError(str(error)) from error


def verify_tagged_pair_artifacts(artifacts: dict[str, bytes]) -> Row:
    """Recompute the sealed assessment; no datastore or native execution is available."""
    checked = _payload(artifacts, sealed=True)
    supplied = checked.pop("assessment")
    assessment = assess_tagged_pair_artifacts(checked)
    _require(assessment.canonical_bytes == supplied, "Sealed tagged assessment does not reproduce")
    return {
        "kind": "tagged_queue_pair_offline_verification_v1",
        "schema_version": 1,
        "assessment_id": assessment.assessment_id,
        "assessment": assessment.document,
        **_FLAGS,
    }
