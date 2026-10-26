"""Pure conserved FIFO completions for a conditional tagged-participant model.

The observed total already includes the tagged tranche. A trade consumes each
lot exactly once, from external ahead, tagged live quantity, then external
behind. Post-horizon administrative cancellation is explicitly not an observed
market event; this module never fabricates one or calls the native engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from tickwitness.domain.assumptions.queue_constraints import MAX_QUEUE_LOTS
from tickwitness.domain.replay._validation import canonical, digest, parse
from tickwitness.domain.replay.contracts import PreparedReplay, ReplayInput

if TYPE_CHECKING:
    from tickwitness.domain.research_contracts.tagged_queue_protocol import TaggedQueueProtocol

_LIMIT = 4 * 1024 * 1024


def _require(condition: bool, message: str) -> None:
    from tickwitness.domain.research_contracts.tagged_queue_protocol import (
        TaggedQueueValidationError,
    )

    if not condition:
        raise TaggedQueueValidationError(message)


def _state(ahead: int, own: int, behind: int, filled: int) -> dict[str, object]:
    _require(
        all(0 <= value <= MAX_QUEUE_LOTS for value in (ahead, own, behind, filled)),
        "Tagged FIFO state is negative or exceeds its bound",
    )
    _require(ahead + own + behind <= MAX_QUEUE_LOTS, "Tagged total depth exceeds its bound")
    return {
        "ahead_lots": ahead,
        "own_live_lots": own,
        "behind_lots": behind,
        "external_lots": ahead + behind,
        "total_lots": ahead + own + behind,
        "own_filled_lots": filled,
    }


def _interpretation(
    protocol: TaggedQueueProtocol, prepared: PreparedReplay, policy: str
) -> dict[str, object]:
    document = protocol.document
    strategy = cast("dict[str, int]", document["strategy"])
    target, requested = strategy["target_price_ticks"], strategy["tagged_quantity_lots"]
    first = prepared.events[0]
    initial = dict(first.bids)[target]
    _require(requested <= initial, "Tagged tranche exceeds initial observed target quantity")
    ahead, own, behind, filled = initial - requested, requested, 0, 0
    updates = {
        cast("int", row["capture_seq"]): row
        for row in cast("list[dict[str, object]]", protocol.constraint.document["updates"])
    }
    trace: list[dict[str, object]] = []
    bids: dict[int, int] = {}
    mark_ref: dict[str, object] | None = None
    for event in prepared.events:
        before = None if event.line == 1 else _state(ahead, own, behind, filled)
        flow = {
            key: 0
            for key in (
                "additions_lots",
                "cancellations_lots",
                "trade_lots",
                "cancel_ahead_lots",
                "cancel_behind_lots",
                "external_trade_ahead_lots",
                "own_trade_lots",
                "external_trade_behind_lots",
            )
        }
        observed: int | None = None
        kind = "entry" if event.line == 1 else "unrelated"
        if event.event_type != "trade":
            for price, depth in event.bids:
                if depth:
                    bids[price] = depth
                else:
                    bids.pop(price, None)
            mark_ref = event.source_ref
        if event.line == 1:
            observed = initial
        elif event.event_type == "trade":
            quantity = cast("int", event.quantity_lots)
            _require(quantity <= ahead + own + behind, "Trade exceeds the inclusive tagged book")
            external_ahead = min(quantity, ahead)
            own_trade = min(quantity - external_ahead, own)
            external_behind = quantity - external_ahead - own_trade
            _require(external_behind <= behind, "Trade allocation exceeds external tail")
            ahead -= external_ahead
            own -= own_trade
            behind -= external_behind
            filled += own_trade
            flow.update(
                trade_lots=quantity,
                external_trade_ahead_lots=external_ahead,
                own_trade_lots=own_trade,
                external_trade_behind_lots=external_behind,
            )
            _require(
                external_ahead + own_trade + external_behind == quantity,
                "Trade is not allocated exactly once",
            )
            kind = "trade"
        elif event.capture_seq in updates:
            update = updates[event.capture_seq]
            addition, cancellation = (
                cast("int", update["additions_lots"]),
                cast("int", update["cancellations_lots"]),
            )
            behind += addition
            _require(
                cancellation <= ahead + behind,
                "External cancellation would consume the protected tagged tranche",
            )
            if policy == "protected_tag_front_cancel_v1":
                cancel_ahead = min(cancellation, ahead)
                cancel_behind = cancellation - cancel_ahead
            else:
                cancel_behind = min(cancellation, behind)
                cancel_ahead = cancellation - cancel_behind
            ahead -= cancel_ahead
            behind -= cancel_behind
            flow.update(
                additions_lots=addition,
                cancellations_lots=cancellation,
                cancel_ahead_lots=cancel_ahead,
                cancel_behind_lots=cancel_behind,
            )
            observed = dict(event.bids)[target]
            kind = "checkpoint"
        after = _state(ahead, own, behind, filled)
        _require(
            own + filled == requested, "Tagged quantity was cancelled or created within the horizon"
        )
        if observed is not None:
            _require(
                after["total_lots"] == observed,
                "Inclusive tagged FIFO projection differs from the recorded total depth",
            )
        trace.append(
            {
                "kind": kind,
                "source_ref": event.source_ref,
                "receive_time_ns": event.receive_time_ns,
                "before": before,
                "flow": flow,
                "after": after,
                "observed_total_lots": observed,
                "own_fill_grant_lots": flow["own_trade_lots"],
            }
        )
    _require(bool(bids) and mark_ref is not None, "Tagged horizon has no visible bid mark")
    best = max(bids)
    last = prepared.events[-1]
    return {
        "policy_id": policy,
        "trace": trace,
        "horizon": {
            "source_ref": last.source_ref,
            "receive_time_ns": last.receive_time_ns,
            "state": _state(ahead, own, behind, filled),
            "mark": {
                "source_ref": mark_ref,
                "price_ticks": best,
                "available_quantity_lots": bids[best],
            },
            "post_horizon_cancel_lots": own,
        },
    }


@dataclass(frozen=True, slots=True)
class TaggedQueueWitnessPair:
    protocol: TaggedQueueProtocol
    replay_input: ReplayInput
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        from tickwitness.domain.research_contracts.tagged_queue_protocol import (
            TAGGED_POLICY_IDS,
            _checked_input,
        )

        checked, prepared = _checked_input(self.protocol, self.replay_input)
        document = checked.document
        encoded = canonical(
            {
                "kind": "tagged_queue_witness_pair_v1",
                "schema_version": 1,
                "protocol_id": checked.protocol_id,
                "bindings": document["bindings"],
                "model": document["model"],
                "scope": document["scope"],
                "interpretations": [
                    _interpretation(checked, prepared, policy) for policy in TAGGED_POLICY_IDS
                ],
            }
        )
        _require(len(encoded) <= _LIMIT, "Tagged witness pair exceeds its byte bound")
        object.__setattr__(self, "canonical_bytes", encoded)

    @property
    def witness_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, _LIMIT)
