"""A new built-in v2 value cannot mutate or override frozen v1 declarations."""

import hashlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Inexact, localcontext
from typing import cast

import pytest

from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol,
    ProtocolValidationError,
    build_executable_protocol,
    load_executable_protocol,
)
from tickwitness.domain.research_contracts.protocols import (
    build_frozen_protocol,
    load_frozen_protocol,
)


def request() -> dict[str, object]:
    return {
        "schema_version": 2,
        "claim": {
            "title": "Original synthetic qualification claim",
            "hypothesis": "The built-in order has positive net marked PnL under this model.",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "-000.000",
            "unit": "USD",
        },
        "replay_spec": {
            "schema_version": 1,
            "clock_policy_id": "receive_order_v1",
            "instrument": {
                "base_currency": "EUR",
                "quote_currency": "USD",
                "price_increment": "1.00",
                "size_increment": "1",
            },
            "account": {"starting_cash": "10000.00"},
            "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
            "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
            "strategy": {
                "kind": "single_limit_buy_v1",
                "submit_capture_seq": 1,
                "limit_price_ticks": 100,
                "quantity_lots": 2,
                "cancel_after_first_fill": False,
            },
            "seed": 7,
        },
        "budget": {"max_attempts": 3, "max_wall_seconds": 30, "max_events": 1_000},
    }


def encoded(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def build(value: dict[str, object] | None = None) -> ExecutableProtocol:
    return build_executable_protocol(
        encoded(request() if value is None else value),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
    )


def changed(path: tuple[str, ...], value: object) -> dict[str, object]:
    document = request()
    target = document
    for key in path[:-1]:
        target = cast("dict[str, object]", target[key])
    target[path[-1]] = value
    return document


def test_exact_document_binds_spec_claim_builtin_semantics_and_development_policy() -> None:
    protocol = build()
    document = protocol.document
    spec = build_replay_spec(encoded(cast("dict[str, object]", request()["replay_spec"])))
    claim = {**cast("dict[str, object]", request()["claim"]), "threshold": "0"}
    assert document == {
        "kind": "executable_research_protocol_v2",
        "schema_version": 2,
        "read_policy": "development_only_v1",
        "evaluation_policy": "last_observed_bid_mark_v1",
        "claim_revision_id": hashlib.sha256(encoded(claim)).hexdigest(),
        "claim": claim,
        "datasets": {"development": "a" * 64, "confirmation": "b" * 64},
        "strategy": {
            "kind": "builtin",
            "id": "single_limit_buy_v1",
            "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1",
        },
        "engine": {
            "id": "nautilus-trader",
            "version": "1.231.0",
            "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1",
        },
        "replay_spec_id": spec.spec_id,
        "replay_spec": spec.document,
        "budget": request()["budget"],
    }
    assert protocol.protocol_id == hashlib.sha256(protocol.canonical_bytes).hexdigest()
    assert protocol.claim_revision_id == document["claim_revision_id"]
    assert load_executable_protocol(protocol.canonical_bytes) == protocol
    assert "execution_ready" not in document
    assert "sha256" not in cast("dict[str, object]", document["strategy"])


def test_equivalent_request_encoding_and_decimals_produce_identical_values() -> None:
    value = changed(("claim", "threshold"), "+0.00")
    cast("dict[str, object]", cast("dict[str, object]", value["replay_spec"])["fees"])[
        "maker_rate"
    ] = "+00.0100"
    assert build(value) == build()
    pretty = json.dumps(dict(reversed(list(request().items()))), indent=2).encode()
    assert (
        build_executable_protocol(
            pretty, development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
        )
        == build()
    )


def test_nested_documents_are_detached_and_direct_construction_checks_identity() -> None:
    protocol = build()
    view = protocol.document
    cast("dict[str, object]", view["claim"])["threshold"] = "999"
    cast("dict[str, object]", view["budget"])["max_attempts"] = 100
    assert protocol == build()
    assert not hasattr(protocol, "__dict__")
    with pytest.raises(FrozenInstanceError):
        protocol.protocol_id = "0" * 64  # type: ignore[misc]
    with pytest.raises(ProtocolValidationError, match="identities"):
        replace(protocol, claim_revision_id="0" * 64)
    with pytest.raises(ProtocolValidationError):
        replace(protocol, canonical_bytes=bytearray(protocol.canonical_bytes))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path,value",
    [
        (("replay_spec", "fees", "maker_rate"), "0.015"),
        (("replay_spec", "execution", "insert_latency_ns"), 100),
        (("replay_spec", "strategy", "quantity_lots"), 3),
        (("replay_spec", "seed"), 8),
        (("budget", "max_attempts"), 4),
    ],
)
def test_execution_or_budget_changes_make_a_new_protocol_with_same_claim(
    path: tuple[str, ...], value: object
) -> None:
    previous, revised = build(), build(changed(path, value))
    assert previous.protocol_id != revised.protocol_id
    assert previous.claim_revision_id == revised.claim_revision_id


@pytest.mark.parametrize(
    "field,value", [("threshold", "1"), ("comparator", "ge"), ("hypothesis", "A revised claim.")]
)
def test_changed_proposition_makes_a_new_claim(field: str, value: str) -> None:
    assert build(changed(("claim", field), value)).claim_revision_id != build().claim_revision_id


def test_dataset_identity_changes_protocol_and_never_grants_confirmation_reads() -> None:
    revised = build_executable_protocol(
        encoded(request()), development_dataset_id="c" * 64, confirmation_dataset_id="d" * 64
    )
    assert revised.protocol_id != build().protocol_id
    assert revised.claim_revision_id == build().claim_revision_id
    assert revised.document["read_policy"] == "development_only_v1"


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("schema_version",), 1),
        (("claim", "metric"), "sharpe"),
        (("claim", "unit"), "EUR"),
        (("claim", "threshold"), "1e2"),
        (("claim", "threshold"), "1" * 29),
        (("claim", "comparator"), "eq"),
        (("claim", "title"), "\ud800"),
        (("budget", "max_attempts"), 0),
        (("budget", "max_attempts"), 101),
        (("budget", "max_attempts"), True),
        (("budget", "max_wall_seconds"), 61),
        (("budget", "max_events"), 10_001),
        (("budget", "max_events"), -1),
        (("replay_spec",), "external.json"),
        (("replay_spec", "strategy", "kind"), "user_python"),
        (("replay_spec", "strategy", "source"), "print('do not run')"),
        (("replay_spec", "clock_policy_id"), "UTC_certified"),
        (("execution_ready",), True),
        (("source",), "print('do not run')"),
    ],
)
def test_unsupported_values_unknown_fields_and_source_are_rejected(
    path: tuple[str, ...], value: object
) -> None:
    # ASCII encoding lets escaped invalid Unicode reach the strict domain boundary.
    raw = json.dumps(changed(path, value)).encode()
    with pytest.raises(ProtocolValidationError):
        build_executable_protocol(
            raw, development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
        )


@pytest.mark.parametrize(
    "development,confirmation", [("a" * 64, "a" * 64), ("../bad", "b" * 64), ("A" * 64, "b" * 64)]
)
def test_dataset_ids_are_distinct_digests(development: str, confirmation: str) -> None:
    with pytest.raises(ProtocolValidationError):
        build_executable_protocol(
            encoded(request()),
            development_dataset_id=development,
            confirmation_dataset_id=confirmation,
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"[]",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1.0}',
        b"[" * 1100,
        b" " * (128 * 1024 + 1),
    ],
)
def test_malformed_float_duplicate_oversize_input_is_rejected(raw: bytes) -> None:
    with pytest.raises(ProtocolValidationError):
        build_executable_protocol(
            raw, development_dataset_id="a" * 64, confirmation_dataset_id="b" * 64
        )


@pytest.mark.parametrize(
    "path,value",
    [
        (("kind",), "frozen_research_protocol_v1"),
        (("schema_version",), True),
        (("read_policy",), "confirmation_unsealed"),
        (("evaluation_policy",), "last_midpoint"),
        (("claim_revision_id",), "0" * 64),
        (("replay_spec_id",), "0" * 64),
        (("strategy", "id"), "user_python"),
        (("strategy", "sha256"), "0" * 64),
        (("engine", "version"), "2.0"),
        (("engine", "semantic_id"), "other"),
        (("execution_ready",), True),
    ],
)
def test_loader_rebuilds_fixed_policies_and_all_hashes(
    path: tuple[str, ...], value: object
) -> None:
    document = deepcopy(build().document)
    target = document
    for key in path[:-1]:
        target = cast("dict[str, object]", target[key])
    target[path[-1]] = value
    with pytest.raises(ProtocolValidationError):
        load_executable_protocol(encoded(document))


def test_loader_requires_canonical_bytes_and_global_decimal_context_is_irrelevant() -> None:
    protocol = build()
    with pytest.raises(ProtocolValidationError, match="encoding"):
        load_executable_protocol(json.dumps(protocol.document, indent=2).encode())
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert build() == protocol
        assert load_executable_protocol(protocol.canonical_bytes) == protocol


def test_v1_remains_a_non_executable_declaration_without_implicit_upgrade() -> None:
    legacy_request = {
        "schema_version": 1,
        "claim": request()["claim"],
        "strategy_name": "original_declared_strategy",
        "parameters": {},
        "configuration": {
            "fee_model_id": "declared",
            "execution_model_id": "declared",
            "clock_policy_id": "capture_order_unbound_v1",
        },
        "budget": {"max_scenarios": 3, "max_wall_seconds": 30, "max_events": 1_000},
        "seed": 7,
    }
    legacy = build_frozen_protocol(
        encoded(legacy_request),
        development_dataset_id="a" * 64,
        confirmation_dataset_id="b" * 64,
        strategy_sha256="c" * 64,
    )
    assert legacy.document["execution_ready"] is False
    assert legacy.claim_revision_id == build().claim_revision_id
    with pytest.raises(ProtocolValidationError):
        load_executable_protocol(legacy.canonical_bytes)
    with pytest.raises(ProtocolValidationError):
        load_frozen_protocol(build().canonical_bytes)
    assert load_frozen_protocol(legacy.canonical_bytes) == legacy
