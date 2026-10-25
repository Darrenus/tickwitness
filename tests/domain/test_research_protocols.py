"""Freeze declarations deterministically without granting execution or holdout access."""

import hashlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Inexact, localcontext
from typing import cast

import pytest

from tickwitness.domain.research_contracts import (
    FrozenProtocol,
    ProtocolValidationError,
    build_frozen_protocol,
    load_frozen_protocol,
)

DEVELOPMENT = "a" * 64
CONFIRMATION = "b" * 64
STRATEGY = "c" * 64


def _request() -> dict[str, object]:
    return {
        "schema_version": 1,
        "claim": {
            "title": "Synthetic net marked PnL declaration",
            "hypothesis": "Under the frozen declared model the net marked PnL exceeds zero.",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "-000.000",
            "unit": "synthetic_quote_units",
        },
        "strategy_name": "synthetic_strategy_v1",
        "parameters": {"size_lots": 1, "post_only": True, "label": "synthetic", "optional": None},
        "configuration": {
            "fee_model_id": "declared_fee_demo_v1",
            "execution_model_id": "declared_execution_demo_v1",
            "clock_policy_id": "capture_order_unbound_v1",
        },
        "budget": {"max_scenarios": 10, "max_wall_seconds": 60, "max_events": 1_000},
        "seed": 42,
    }


def _encoded(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _build(request: dict[str, object] | None = None) -> FrozenProtocol:
    return build_frozen_protocol(
        _encoded(_request() if request is None else request),
        development_dataset_id=DEVELOPMENT,
        confirmation_dataset_id=CONFIRMATION,
        strategy_sha256=STRATEGY,
    )


def _changed(path: tuple[str, ...], value: object) -> dict[str, object]:
    request = _request()
    target = request
    for field in path[:-1]:
        target = cast("dict[str, object]", target[field])
    target[path[-1]] = value
    return request


def test_frozen_document_binds_normalized_claim_and_full_declaration() -> None:
    frozen = _build()
    document = frozen.document

    assert document == {
        "kind": "frozen_research_protocol_v1",
        "schema_version": 1,
        "execution_ready": False,
        "read_policy": "development_only_v1",
        "claim_revision_id": frozen.claim_revision_id,
        "claim": {**cast("dict[str, object]", _request()["claim"]), "threshold": "0"},
        "datasets": {"development": DEVELOPMENT, "confirmation": CONFIRMATION},
        "strategy": {"name": "synthetic_strategy_v1", "sha256": STRATEGY},
        "parameters": _request()["parameters"],
        "configuration": _request()["configuration"],
        "budget": _request()["budget"],
        "seed": 42,
    }
    assert frozen.protocol_id == hashlib.sha256(frozen.canonical_bytes).hexdigest()
    assert (
        frozen.claim_revision_id
        == hashlib.sha256(_encoded(cast("dict[str, object]", document["claim"]))).hexdigest()
    )
    assert "protocol_id" not in document
    assert frozen.canonical_bytes == _encoded(document)
    assert load_frozen_protocol(frozen.canonical_bytes) == frozen


def test_whitespace_key_order_and_equivalent_thresholds_have_identical_identities() -> None:
    request = _request()
    pretty = json.dumps(dict(reversed(list(request.items()))), indent=2).encode()
    first = build_frozen_protocol(
        pretty,
        development_dataset_id=DEVELOPMENT,
        confirmation_dataset_id=CONFIRMATION,
        strategy_sha256=STRATEGY,
    )
    second = _build(_changed(("claim", "threshold"), "+0.000"))

    assert first == second


def test_documents_are_detached_and_the_frozen_value_cannot_be_mutated() -> None:
    frozen = _build()
    view = frozen.document
    cast("dict[str, object]", view["claim"])["threshold"] = "999"
    cast("dict[str, object]", view["parameters"])["size_lots"] = 999
    view["execution_ready"] = True

    assert frozen.document["execution_ready"] is False
    assert cast("dict[str, object]", frozen.document["claim"])["threshold"] == "0"
    assert cast("dict[str, object]", frozen.document["parameters"])["size_lots"] == 1
    assert not hasattr(frozen, "__dict__")
    with pytest.raises(FrozenInstanceError):
        frozen.protocol_id = "0" * 64  # type: ignore[misc]
    with pytest.raises(ProtocolValidationError, match="identities"):
        replace(frozen, protocol_id="0" * 64)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("configuration", "fee_model_id"), "another_declared_fee"),
        (("configuration", "execution_model_id"), "another_declared_execution"),
        (("parameters", "size_lots"), 2),
        (("budget", "max_scenarios"), 20),
        (("seed",), 43),
        (("strategy_name",), "another_strategy_name"),
    ],
)
def test_execution_configuration_changes_protocol_but_not_claim(
    path: tuple[str, ...], value: object
) -> None:
    first = _build()
    revised = _build(_changed(path, value))

    assert revised.protocol_id != first.protocol_id
    assert revised.claim_revision_id == first.claim_revision_id
    assert revised.document["execution_ready"] is False


@pytest.mark.parametrize("changed", ["development", "confirmation", "strategy"])
def test_dataset_and_strategy_content_changes_do_not_rewrite_the_claim(changed: str) -> None:
    first = _build()
    revised = build_frozen_protocol(
        _encoded(_request()),
        development_dataset_id="d" * 64 if changed == "development" else DEVELOPMENT,
        confirmation_dataset_id="d" * 64 if changed == "confirmation" else CONFIRMATION,
        strategy_sha256="d" * 64 if changed == "strategy" else STRATEGY,
    )

    assert revised.protocol_id != first.protocol_id
    assert revised.claim_revision_id == first.claim_revision_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hypothesis", "A different falsifiable statement."),
        ("threshold", "1"),
        ("comparator", "ge"),
    ],
)
def test_changed_proposition_creates_a_new_claim_revision(field: str, value: str) -> None:
    first = _build()
    revised = _build(_changed(("claim", field), value))

    assert revised.claim_revision_id != first.claim_revision_id
    assert revised.protocol_id != first.protocol_id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("000123.450000", "123.45"),
        ("-001.2300", "-1.23"),
        ("-0", "0"),
        ("+0", "0"),
        ("-000.000", "0"),
        ("+001.000", "1"),
        ("-0.000000000000000001", "-0.000000000000000001"),
        ("9999999999999999999999999999", "9999999999999999999999999999"),
    ],
)
def test_decimal_normalization_is_exact(text: str, expected: str) -> None:
    frozen = _build(_changed(("claim", "threshold"), text))
    assert cast("dict[str, object]", frozen.document["claim"])["threshold"] == expected


def test_decimal_global_precision_cannot_round_or_change_frozen_content() -> None:
    request = _changed(("claim", "threshold"), "1234567890.123456789012345678")
    expected = _build(request)
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        actual = _build(request)

    assert actual == expected
    assert cast("dict[str, object]", actual.document["claim"])["threshold"] == (
        "1234567890.123456789012345678"
    )


@pytest.mark.parametrize(
    "value",
    [
        0,
        True,
        "NaN",
        "Infinity",
        "1e3",
        " 0",
        "0 ",
        ".5",
        "1.",
        "+",
        "1_000",
        "\uff11\uff12",
        "1" * 29,
        "0." + "0" * 19,
    ],
)
def test_non_decimal_or_over_precision_thresholds_are_rejected(value: object) -> None:
    with pytest.raises(ProtocolValidationError):
        _build(_changed(("claim", "threshold"), value))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("schema_version",), 2),
        (("claim", "title"), ""),
        (("claim", "title"), "x" * 201),
        (("claim", "hypothesis"), "x" * 2_001),
        (("claim", "hypothesis"), "bad\ncontrol"),
        (("claim", "title"), "\ud800"),
        (("claim", "metric"), "sharpe"),
        (("claim", "comparator"), "eq"),
        (("claim", "unit"), "../quote"),
        (("strategy_name",), ""),
        (("strategy_name",), "x" * 129),
        (("configuration", "fee_model_id"), ""),
        (("configuration", "execution_model_id"), "../engine"),
        (("configuration", "clock_policy_id"), "verified_utc"),
        (("budget", "max_scenarios"), 0),
        (("budget", "max_scenarios"), True),
        (("budget", "max_scenarios"), 1_000_001),
        (("budget", "max_wall_seconds"), 86_401),
        (("budget", "max_events"), 1_000_000_001),
        (("seed",), True),
        (("seed",), -1),
        (("seed",), 1 << 63),
        (("parameters",), {"x": []}),
        (("parameters",), {"x": {"nested": 1}}),
        (("parameters",), {"x": "x" * 1_025}),
        (("parameters",), {"x": 1 << 63}),
        (("parameters",), {"x": -(1 << 63) - 1}),
        (("parameters",), {"x" * 65: 1}),
        (("parameters",), {f"key{i}": 1 for i in range(33)}),
    ],
)
def test_invalid_declarations_fail_with_domain_errors(path: tuple[str, ...], value: object) -> None:
    request = _changed(path, value)
    # ensure_ascii=True keeps an invalid surrogate representable in the input JSON.
    raw = json.dumps(request, ensure_ascii=True).encode()
    with pytest.raises(ProtocolValidationError) as caught:
        build_frozen_protocol(
            raw,
            development_dataset_id=DEVELOPMENT,
            confirmation_dataset_id=CONFIRMATION,
            strategy_sha256=STRATEGY,
        )
    assert caught.value.message == str(caught.value)


def test_supported_scalar_and_budget_boundaries_do_not_approve_execution() -> None:
    request = _request()
    request["parameters"] = {"empty": "", "minimum": -(1 << 63), "maximum": (1 << 63) - 1}
    request["budget"] = {
        "max_scenarios": 1_000_000,
        "max_wall_seconds": 86_400,
        "max_events": 1_000_000_000,
    }
    request["seed"] = (1 << 63) - 1
    frozen = _build(request)

    assert frozen.document["parameters"] == request["parameters"]
    assert frozen.document["execution_ready"] is False
    assert frozen.document["read_policy"] == "development_only_v1"


@pytest.mark.parametrize("location", [None, "claim", "configuration", "budget"])
def test_unknown_fields_cannot_smuggle_execution_or_policy(location: str | None) -> None:
    request = _request()
    target = request if location is None else cast("dict[str, object]", request[location])
    target["execution_ready"] = True
    with pytest.raises(ProtocolValidationError, match="fields"):
        _build(request)


def test_missing_fields_are_rejected() -> None:
    request = _request()
    del request["seed"]
    with pytest.raises(ProtocolValidationError, match="fields"):
        _build(request)


@pytest.mark.parametrize("field", ["development", "confirmation", "strategy"])
@pytest.mark.parametrize("bad", ["A" * 64, "g" * 64, "a" * 63, "../" + "a" * 64])
def test_content_ids_require_exact_lowercase_sha256(field: str, bad: str) -> None:
    with pytest.raises(ProtocolValidationError, match="hexadecimal"):
        build_frozen_protocol(
            _encoded(_request()),
            development_dataset_id=bad if field == "development" else DEVELOPMENT,
            confirmation_dataset_id=bad if field == "confirmation" else CONFIRMATION,
            strategy_sha256=bad if field == "strategy" else STRATEGY,
        )


def test_same_dataset_identity_cannot_be_both_development_and_confirmation() -> None:
    with pytest.raises(ProtocolValidationError, match="must differ"):
        build_frozen_protocol(
            _encoded(_request()),
            development_dataset_id=DEVELOPMENT,
            confirmation_dataset_id=DEVELOPMENT,
            strategy_sha256=STRATEGY,
        )


@pytest.mark.parametrize("bad", [1.0, float("nan"), float("inf"), float("-inf")])
def test_float_tokens_are_rejected_even_in_parameters(bad: float) -> None:
    with pytest.raises(ProtocolValidationError, match="Floating-point"):
        _build(_changed(("parameters",), {"x": bad}))


@pytest.mark.parametrize("raw", [b"", b"\xff", b"[]", b"{} {}", b"\xef\xbb\xbf{}"])
def test_malformed_non_utf8_or_nonobject_request_is_rejected(raw: bytes) -> None:
    with pytest.raises(ProtocolValidationError):
        build_frozen_protocol(
            raw,
            development_dataset_id=DEVELOPMENT,
            confirmation_dataset_id=CONFIRMATION,
            strategy_sha256=STRATEGY,
        )


def test_duplicate_json_keys_and_request_byte_limit_are_enforced() -> None:
    raw = _encoded(_request())
    duplicate = raw.replace(b'"seed":42', b'"seed":42,"seed":43')
    with pytest.raises(ProtocolValidationError, match="Duplicate"):
        build_frozen_protocol(
            duplicate,
            development_dataset_id=DEVELOPMENT,
            confirmation_dataset_id=CONFIRMATION,
            strategy_sha256=STRATEGY,
        )
    with pytest.raises(ProtocolValidationError, match="64 KiB"):
        build_frozen_protocol(
            raw + b" " * (65_537 - len(raw)),
            development_dataset_id=DEVELOPMENT,
            confirmation_dataset_id=CONFIRMATION,
            strategy_sha256=STRATEGY,
        )
    assert (
        build_frozen_protocol(
            raw + b" " * (65_536 - len(raw)),
            development_dataset_id=DEVELOPMENT,
            confirmation_dataset_id=CONFIRMATION,
            strategy_sha256=STRATEGY,
        )
        == _build()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "executed_protocol"),
        ("schema_version", True),
        ("execution_ready", True),
        ("execution_ready", 0),
        ("read_policy", "confirmation_open"),
        ("claim_revision_id", "0" * 64),
        ("protocol_id", "0" * 64),
    ],
)
def test_load_rebuilds_rules_and_rejects_forged_frozen_fields(field: str, value: object) -> None:
    document = _build().document
    document[field] = value
    with pytest.raises(ProtocolValidationError):
        load_frozen_protocol(_encoded(document))


def test_full_size_valid_request_can_expand_into_the_bounded_frozen_envelope() -> None:
    request = _request()
    parameters: dict[str, object] = {f"key{i}": "\U0001f600" * 1_024 for i in range(15)}
    request["parameters"] = parameters
    parameters["tail"] = ""
    remaining = 65_536 - len(_encoded(request))
    parameters["tail"] = "\U0001f600" * (remaining // 4) + "x" * (remaining % 4)
    raw = _encoded(request)
    assert len(raw) == 65_536
    assert len(cast("str", parameters["tail"])) <= 1_024

    frozen = _build(request)

    assert 65_536 < len(frozen.canonical_bytes) <= 69_632
    assert load_frozen_protocol(frozen.canonical_bytes) == frozen
    assert frozen.document["parameters"] == parameters


def test_load_rejects_noncanonical_bytes_and_noncanonical_threshold() -> None:
    frozen = _build()
    with pytest.raises(ProtocolValidationError, match="canonical"):
        load_frozen_protocol(json.dumps(frozen.document, indent=2).encode())
    document = frozen.document
    cast("dict[str, object]", document["claim"])["threshold"] = "-0.000"
    with pytest.raises(ProtocolValidationError, match="canonical"):
        load_frozen_protocol(_encoded(document))


def test_loading_a_valid_new_document_returns_a_new_identity_not_authenticity() -> None:
    frozen = _build()
    document = deepcopy(frozen.document)
    claim = cast("dict[str, object]", document["claim"])
    claim["hypothesis"] = "An explicitly different declared proposition."
    document["claim_revision_id"] = hashlib.sha256(_encoded(claim)).hexdigest()
    revised = load_frozen_protocol(_encoded(document))

    assert revised.protocol_id != frozen.protocol_id
    assert revised.claim_revision_id != frozen.claim_revision_id
    assert revised.document["execution_ready"] is False
    with pytest.raises(ProtocolValidationError):
        FrozenProtocol(frozen.protocol_id, revised.claim_revision_id, revised.canonical_bytes)
