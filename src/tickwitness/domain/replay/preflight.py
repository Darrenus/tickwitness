"""Strict bounded qualification checks performed before any native-engine import."""

import json
from typing import cast

from tickwitness.domain.data_evidence import DataValidationError, ValidationLimits, normalize_events
from tickwitness.domain.replay._validation import (
    INT64_MAX,
    MAX_DATA_BYTES,
    MAX_EVENTS,
    ReplayValidationError,
    digest,
    ratio,
)
from tickwitness.domain.replay.contracts import PreparedReplay, ReplayEvent, ReplayInput

_MAX_BOOK_LEVELS = 1_000
_MAX_PHYSICAL_VALUE = 1_000_000_000


def _mapped(units: int, increment: str, label: str) -> None:
    numerator, denominator = ratio(increment)
    if units * numerator > _MAX_PHYSICAL_VALUE * denominator:
        raise ReplayValidationError(f"{label} exceeds the supported physical mapping range")


def _notional(price: int, quantity: int, price_increment: str, size_increment: str) -> None:
    price_numerator, price_denominator = ratio(price_increment)
    size_numerator, size_denominator = ratio(size_increment)
    if price * quantity * price_numerator * size_numerator > (
        _MAX_PHYSICAL_VALUE * price_denominator * size_denominator
    ):
        raise ReplayValidationError("Derived quote notional exceeds the supported 1e9 bound")


def _update(book: dict[int, int], levels: tuple[tuple[int, int], ...]) -> None:
    for price, quantity in levels:
        if quantity == 0:
            if price not in book:
                raise ReplayValidationError("Delta cannot delete an absent price level")
            del book[price]
        else:
            book[price] = quantity
    if len(book) > _MAX_BOOK_LEVELS:
        raise ReplayValidationError("Active book exceeds 1000 levels per side")


def preflight_replay(replay_input: ReplayInput) -> PreparedReplay:
    """Accept only supported complete input; return truly immutable native-free DTOs.

    The receive-order mapping is a declared simulation clock, not UTC evidence.
    No strategy source, frozen protocol, claim evaluator or holdout is executed.
    """
    if not isinstance(replay_input, ReplayInput):
        raise ReplayValidationError("Replay preflight requires ReplayInput")
    try:
        validated = normalize_events(
            replay_input.normalized_bytes,
            ValidationLimits(max_bytes=MAX_DATA_BYTES, max_records=MAX_EVENTS),
        )
    except DataValidationError as error:
        raise ReplayValidationError("Replay input violates normalized-events-v1") from error
    if validated.normalized_bytes != replay_input.normalized_bytes:
        raise ReplayValidationError("Replay input must already have canonical normalized encoding")
    if validated.report["quality_status"] != "accepted" or validated.report["findings"]:
        raise ReplayValidationError(
            "Replay rejects gaps, duplicates, stale records and unknown clocks"
        )
    if validated.report["stream_count"] != 1:
        raise ReplayValidationError("Qualification supports exactly one source/instrument/session")

    spec = replay_input.spec.document
    instrument = cast("dict[str, str]", spec["instrument"])
    price_increment, size_increment = instrument["price_increment"], instrument["size_increment"]
    strategy = cast("dict[str, object]", spec["strategy"])
    _mapped(cast("int", strategy["limit_price_ticks"]), price_increment, "Order price")
    order_quantity = cast("int", strategy["quantity_lots"])
    _mapped(order_quantity, size_increment, "Order quantity")
    _notional(
        cast("int", strategy["limit_price_ticks"]), order_quantity, price_increment, size_increment
    )
    records = [
        cast("dict[str, object]", json.loads(line))
        for line in validated.normalized_bytes.splitlines()
    ]
    first = records[0]
    stream = (
        cast("str", first["source"]),
        cast("str", first["instrument"]),
        cast("str", first["session"]),
    )
    if stream[1] != "EUR-USD":
        raise ReplayValidationError(
            "Source instrument must be EUR-USD; asset relabeling is unsupported"
        )
    if first["type"] != "snapshot":
        raise ReplayValidationError(
            "Qualification requires one initial snapshot as its first record"
        )
    bids: dict[int, int] = {}
    asks: dict[int, int] = {}
    events: list[ReplayEvent] = []
    last_receive: int | None = None
    for line, record in enumerate(records, start=1):
        event_type = cast("str", record["type"])
        event_time = cast("int", record["event_time_ns"])
        receive = cast("int", record["receive_time_ns"])
        if event_time > receive or (last_receive is not None and receive < last_receive):
            raise ReplayValidationError(
                "receive_order_v1 requires event<=receive and nondecreasing receive"
            )
        last_receive = receive
        if event_type == "snapshot" and line != 1:
            raise ReplayValidationError("Resnapshot qualification is not supported")
        bid_updates = tuple(
            tuple(level) for level in cast("list[list[int]]", record.get("bids", []))
        )
        ask_updates = tuple(
            tuple(level) for level in cast("list[list[int]]", record.get("asks", []))
        )
        # These pairs were shape/type checked by the normalized-events domain.
        bids_tuple = cast("tuple[tuple[int, int], ...]", bid_updates)
        asks_tuple = cast("tuple[tuple[int, int], ...]", ask_updates)
        for price, quantity in bids_tuple + asks_tuple:
            _mapped(price, price_increment, "Book price")
            _mapped(quantity, size_increment, "Book quantity")
            _notional(price, quantity, price_increment, size_increment)
            _notional(price, order_quantity, price_increment, size_increment)
        if event_type == "delta" and not bids_tuple and not asks_tuple:
            raise ReplayValidationError("Empty/no-op native delta batches are unsupported")
        if event_type in ("snapshot", "delta"):
            _update(bids, bids_tuple)
            _update(asks, asks_tuple)
            if not bids or not asks or max(bids) >= min(asks):
                raise ReplayValidationError("Qualification rejects empty, locked or crossed books")
        else:
            _mapped(cast("int", record["price_ticks"]), price_increment, "Trade price")
            _mapped(cast("int", record["quantity_lots"]), size_increment, "Trade quantity")
            _notional(
                cast("int", record["price_ticks"]),
                cast("int", record["quantity_lots"]),
                price_increment,
                size_increment,
            )
            _notional(
                cast("int", record["price_ticks"]), order_quantity, price_increment, size_increment
            )
        events.append(
            ReplayEvent(
                line=line,
                capture_seq=cast("int", record["capture_seq"]),
                event_type=event_type,
                event_time_ns=event_time,
                receive_time_ns=receive,
                last_sequence=cast("int | None", record.get("last_sequence")),
                first_sequence=cast("int | None", record.get("first_sequence")),
                bids=bids_tuple,
                asks=asks_tuple,
                trade_id=cast("str | None", record.get("trade_id")),
                price_ticks=cast("int | None", record.get("price_ticks")),
                quantity_lots=cast("int | None", record.get("quantity_lots")),
                aggressor_side=cast("str | None", record.get("aggressor_side")),
            )
        )
    if strategy["submit_capture_seq"] not in {event.capture_seq for event in events}:
        raise ReplayValidationError("submit_capture_seq must identify an actual input record")
    execution = cast("dict[str, int]", spec["execution"])
    if last_receive is not None and (
        last_receive + execution["insert_latency_ns"] + execution["cancel_latency_ns"] > INT64_MAX
    ):
        raise ReplayValidationError("Declared native latency horizon exceeds int64 timestamp range")
    return PreparedReplay(
        replay_input=replay_input,
        spec=replay_input.spec,
        dataset_id=replay_input.dataset_id,
        data_sha256=digest(replay_input.normalized_bytes),
        stream=stream,
        events=tuple(events),
    )
