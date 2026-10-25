"""A strict built-in replay qualification spec, distinct from frozen research protocols."""

from dataclasses import dataclass

from tickwitness.domain.replay._validation import (
    ReplayValidationError as ReplayValidationError,
)
from tickwitness.domain.replay._validation import (
    canonical,
    decimal,
    decimal_range,
    digest,
    exact,
    integer,
    parse,
)

_SPEC_LIMIT = 65_536
_FIELDS = {
    "schema_version",
    "clock_policy_id",
    "instrument",
    "account",
    "fees",
    "execution",
    "strategy",
    "seed",
}


def _validated(document: dict[str, object]) -> dict[str, object]:
    exact(document, _FIELDS, "ReplaySpec")
    integer(document["schema_version"], "schema_version", 1, 1)
    if document["clock_policy_id"] != "receive_order_v1":
        raise ReplayValidationError("Only the declared receive_order_v1 mapping is supported")
    instrument = exact(
        document["instrument"],
        {"base_currency", "quote_currency", "price_increment", "size_increment"},
        "instrument",
    )
    if instrument["base_currency"] != "EUR" or instrument["quote_currency"] != "USD":
        raise ReplayValidationError("Qualification supports only source instrument EUR-USD")
    price = decimal(instrument["price_increment"], "price_increment")
    size = decimal(instrument["size_increment"], "size_increment")
    decimal_range(price, "price_increment", 0, 1_000_000, positive=True)
    decimal_range(size, "size_increment", 0, 1_000_000, positive=True)
    account = exact(document["account"], {"starting_cash"}, "account")
    cash = decimal(account["starting_cash"], "starting_cash", precision=2)
    decimal_range(cash, "starting_cash", 0, 1_000_000_000, positive=True)
    fees = exact(document["fees"], {"maker_rate", "taker_rate"}, "fees")
    maker, taker = (
        decimal(fees["maker_rate"], "maker_rate"),
        decimal(fees["taker_rate"], "taker_rate"),
    )
    decimal_range(maker, "maker_rate", 0, 1)
    decimal_range(taker, "taker_rate", 0, 1)
    execution = exact(
        document["execution"], {"insert_latency_ns", "cancel_latency_ns"}, "execution"
    )
    insert = integer(execution["insert_latency_ns"], "insert_latency_ns", 0, 60_000_000_000)
    cancel = integer(execution["cancel_latency_ns"], "cancel_latency_ns", 0, 60_000_000_000)
    strategy = exact(
        document["strategy"],
        {
            "kind",
            "submit_capture_seq",
            "limit_price_ticks",
            "quantity_lots",
            "cancel_after_first_fill",
        },
        "strategy",
    )
    if strategy["kind"] != "single_limit_buy_v1":
        raise ReplayValidationError("Only built-in single_limit_buy_v1 is supported")
    if type(strategy["cancel_after_first_fill"]) is not bool:
        raise ReplayValidationError("cancel_after_first_fill must be a boolean")
    return {
        "schema_version": 1,
        "clock_policy_id": "receive_order_v1",
        "instrument": {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "price_increment": price,
            "size_increment": size,
        },
        "account": {"starting_cash": cash},
        "fees": {"maker_rate": maker, "taker_rate": taker},
        "execution": {"insert_latency_ns": insert, "cancel_latency_ns": cancel},
        "strategy": {
            "kind": "single_limit_buy_v1",
            "submit_capture_seq": integer(strategy["submit_capture_seq"], "submit_capture_seq", 1),
            "limit_price_ticks": integer(strategy["limit_price_ticks"], "limit_price_ticks", 1),
            "quantity_lots": integer(strategy["quantity_lots"], "quantity_lots", 1),
            "cancel_after_first_fill": strategy["cancel_after_first_fill"],
        },
        "seed": integer(document["seed"], "seed"),
    }


@dataclass(frozen=True, slots=True)
class ReplaySpec:
    spec_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        document = _validated(parse(self.canonical_bytes, _SPEC_LIMIT))
        if (
            canonical(document) != self.canonical_bytes
            or digest(self.canonical_bytes) != self.spec_id
        ):
            raise ReplayValidationError("ReplaySpec identity or canonical encoding does not match")

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, _SPEC_LIMIT)


def build_replay_spec(raw: bytes) -> ReplaySpec:
    encoded = canonical(_validated(parse(raw, _SPEC_LIMIT)))
    return ReplaySpec(digest(encoded), encoded)


def load_replay_spec(canonical_bytes: bytes) -> ReplaySpec:
    parse(canonical_bytes, _SPEC_LIMIT)
    return ReplaySpec(digest(canonical_bytes), canonical_bytes)
