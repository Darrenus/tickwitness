"""Bounded, deterministic freezing of declarations without IO or execution.

Content identities bind declared text and configuration. They do not certify
datasets, clock evidence, an engine, a strategy, or scientific validity.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Never, cast

_MAX_REQUEST_BYTES = 65_536
# The frozen envelope adds bounded identities and policy fields to the request.
_MAX_FROZEN_BYTES = _MAX_REQUEST_BYTES + 4_096
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_DECIMAL = re.compile(r"([+-]?)([0-9]+)(?:\.([0-9]+))?\Z")
_REQUEST_FIELDS = frozenset(
    {"schema_version", "claim", "strategy_name", "parameters", "configuration", "budget", "seed"}
)
_DOCUMENT_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "execution_ready",
        "read_policy",
        "claim_revision_id",
        "claim",
        "datasets",
        "strategy",
        "parameters",
        "configuration",
        "budget",
        "seed",
    }
)
_CLAIM_FIELDS = frozenset({"title", "hypothesis", "metric", "comparator", "threshold", "unit"})
_CONFIGURATION_FIELDS = frozenset({"fee_model_id", "execution_model_id", "clock_policy_id"})
_BUDGET_BOUNDS = {
    "max_scenarios": 1_000_000,
    "max_wall_seconds": 86_400,
    "max_events": 1_000_000_000,
}


class ProtocolValidationError(ValueError):
    """A declaration or stored frozen document violates the version-one contract."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class FrozenProtocol:
    """Validated immutable bytes and identities, with detached document views."""

    protocol_id: str
    claim_revision_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        protocol_id, claim_revision_id = _validated_frozen(self.canonical_bytes)
        if self.protocol_id != protocol_id or self.claim_revision_id != claim_revision_id:
            raise ProtocolValidationError(
                "FrozenProtocol identities do not match canonical content"
            )

    @property
    def document(self) -> dict[str, object]:
        """Return a fresh decoded value; callers cannot mutate the frozen evidence."""
        return _parse(self.canonical_bytes, max_bytes=_MAX_FROZEN_BYTES)


def _reject_float(_value: str) -> Never:
    raise ProtocolValidationError("Floating-point numbers and non-finite constants are not allowed")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolValidationError("Duplicate JSON object key")
        value[key] = item
    return value


def _parse(data: bytes, *, max_bytes: int = _MAX_REQUEST_BYTES) -> dict[str, object]:
    if not isinstance(data, bytes) or not data or len(data) > max_bytes:
        raise ProtocolValidationError(
            f"Protocol input must be nonempty bytes within {max_bytes // 1024} KiB"
        )
    try:
        decoded: object = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except ProtocolValidationError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProtocolValidationError(
            "Protocol must be a valid bounded UTF-8 JSON object"
        ) from error
    if not isinstance(decoded, dict):
        raise ProtocolValidationError("Protocol must be a JSON object")
    return cast("dict[str, object]", decoded)


def _object(value: object, fields: frozenset[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or value.keys() != fields:
        raise ProtocolValidationError(f"{label} contains missing or unknown fields")
    return cast("dict[str, object]", value)


def _text(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ProtocolValidationError(f"{label} must be a string of at most {maximum} characters")
    if not allow_empty and (not value or value != value.strip()):
        raise ProtocolValidationError(f"{label} must be nonempty without surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ProtocolValidationError(f"{label} cannot contain control characters")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ProtocolValidationError(
            f"{label} must contain valid Unicode scalar values"
        ) from error
    return value


def _identifier(value: object, label: str, maximum: int = 128) -> str:
    text = _text(value, label, maximum)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ProtocolValidationError(f"{label} must be a bounded non-path identifier")
    return text


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ProtocolValidationError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolValidationError(f"{label} must be an integer in [{minimum}, {maximum}]")
    return value


def _threshold(value: object) -> str:
    if not isinstance(value, str):
        raise ProtocolValidationError("claim.threshold must be a decimal string")
    match = _DECIMAL.fullmatch(value)
    if match is None:
        raise ProtocolValidationError("claim.threshold must be plain decimal without an exponent")
    sign, integer, fraction = match.groups()
    fraction = fraction or ""
    if len(integer) + len(fraction) > 28 or len(fraction) > 18:
        raise ProtocolValidationError("claim.threshold exceeds 28 digits or 18 fractional places")
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    magnitude = integer + ("." + fraction if fraction else "")
    return "-" + magnitude if sign == "-" and magnitude != "0" else magnitude


def _claim(value: object) -> dict[str, object]:
    claim = _object(value, _CLAIM_FIELDS, "claim")
    title = _text(claim["title"], "claim.title", 200)
    hypothesis = _text(claim["hypothesis"], "claim.hypothesis", 2_000)
    if claim["metric"] != "net_marked_pnl_v1":
        raise ProtocolValidationError("Only declared metric net_marked_pnl_v1 is supported")
    if claim["comparator"] not in ("gt", "ge", "lt", "le"):
        raise ProtocolValidationError("claim.comparator must be gt, ge, lt, or le")
    return {
        "title": title,
        "hypothesis": hypothesis,
        "metric": "net_marked_pnl_v1",
        "comparator": claim["comparator"],
        "threshold": _threshold(claim["threshold"]),
        "unit": _identifier(claim["unit"], "claim.unit", 64),
    }


def _parameters(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or len(value) > 32:
        raise ProtocolValidationError("parameters must be an object with at most 32 entries")
    result: dict[str, object] = {}
    for key, item in value.items():
        name = _identifier(key, "parameter name", 64)
        if item is None or type(item) is bool:
            result[name] = item
        elif type(item) is int:
            result[name] = _integer(item, "parameter integer", _INT64_MIN, _INT64_MAX)
        elif isinstance(item, str):
            result[name] = _text(item, "parameter string", 1_024, allow_empty=True)
        else:
            raise ProtocolValidationError("parameters may contain only bounded JSON scalar values")
    return result


def _configuration(value: object) -> dict[str, object]:
    configuration = _object(value, _CONFIGURATION_FIELDS, "configuration")
    if configuration["clock_policy_id"] != "capture_order_unbound_v1":
        raise ProtocolValidationError("Only clock policy capture_order_unbound_v1 is supported")
    return {
        "fee_model_id": _identifier(configuration["fee_model_id"], "fee_model_id"),
        "execution_model_id": _identifier(
            configuration["execution_model_id"], "execution_model_id"
        ),
        "clock_policy_id": "capture_order_unbound_v1",
    }


def _budget(value: object) -> dict[str, object]:
    budget = _object(value, frozenset(_BUDGET_BOUNDS), "budget")
    return {key: _integer(budget[key], key, 1, maximum) for key, maximum in _BUDGET_BOUNDS.items()}


def _canonical(document: dict[str, object]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_document(
    request: dict[str, object],
    *,
    development_dataset_id: str,
    confirmation_dataset_id: str,
    strategy_sha256: str,
) -> dict[str, object]:
    request = _object(request, _REQUEST_FIELDS, "request")
    _integer(request["schema_version"], "schema_version", 1, 1)
    development = _hash(development_dataset_id, "development_dataset_id")
    confirmation = _hash(confirmation_dataset_id, "confirmation_dataset_id")
    if development == confirmation:
        raise ProtocolValidationError("Development and confirmation dataset identities must differ")
    strategy_hash = _hash(strategy_sha256, "strategy_sha256")
    claim = _claim(request["claim"])
    claim_revision_id = _digest(_canonical(claim))
    return {
        "kind": "frozen_research_protocol_v1",
        "schema_version": 1,
        "execution_ready": False,
        "read_policy": "development_only_v1",
        "claim_revision_id": claim_revision_id,
        "claim": claim,
        "datasets": {"development": development, "confirmation": confirmation},
        "strategy": {
            "name": _identifier(request["strategy_name"], "strategy_name"),
            "sha256": strategy_hash,
        },
        "parameters": _parameters(request["parameters"]),
        "configuration": _configuration(request["configuration"]),
        "budget": _budget(request["budget"]),
        "seed": _integer(request["seed"], "seed", 0, _INT64_MAX),
    }


def _validated_frozen(canonical: bytes) -> tuple[str, str]:
    document = _object(
        _parse(canonical, max_bytes=_MAX_FROZEN_BYTES), _DOCUMENT_FIELDS, "frozen document"
    )
    if document["kind"] != "frozen_research_protocol_v1":
        raise ProtocolValidationError("Unsupported frozen document kind")
    if document["execution_ready"] is not False:
        raise ProtocolValidationError("Frozen declarations cannot approve execution")
    if document["read_policy"] != "development_only_v1":
        raise ProtocolValidationError("Frozen declarations cannot grant confirmation access")
    claimed_revision = _hash(document["claim_revision_id"], "claim_revision_id")
    datasets = _object(document["datasets"], frozenset({"development", "confirmation"}), "datasets")
    strategy = _object(document["strategy"], frozenset({"name", "sha256"}), "strategy")
    request = {
        "schema_version": document["schema_version"],
        "claim": document["claim"],
        "strategy_name": strategy["name"],
        "parameters": document["parameters"],
        "configuration": document["configuration"],
        "budget": document["budget"],
        "seed": document["seed"],
    }
    rebuilt = _build_document(
        request,
        development_dataset_id=_hash(datasets["development"], "development_dataset_id"),
        confirmation_dataset_id=_hash(datasets["confirmation"], "confirmation_dataset_id"),
        strategy_sha256=_hash(strategy["sha256"], "strategy_sha256"),
    )
    if rebuilt["claim_revision_id"] != claimed_revision:
        raise ProtocolValidationError("claim_revision_id does not match the normalized claim")
    if _canonical(rebuilt) != canonical:
        raise ProtocolValidationError("Frozen document must have its exact canonical encoding")
    return _digest(canonical), claimed_revision


def build_frozen_protocol(
    request: bytes,
    *,
    development_dataset_id: str,
    confirmation_dataset_id: str,
    strategy_sha256: str,
) -> FrozenProtocol:
    """Freeze bounded declarations; do not execute strategies or inspect datasets."""
    document = _build_document(
        _parse(request),
        development_dataset_id=development_dataset_id,
        confirmation_dataset_id=confirmation_dataset_id,
        strategy_sha256=strategy_sha256,
    )
    canonical = _canonical(document)
    return FrozenProtocol(_digest(canonical), cast("str", document["claim_revision_id"]), canonical)


def load_frozen_protocol(canonical: bytes) -> FrozenProtocol:
    """Rebuild declarations and identities, rejecting forged policy or encodings."""
    protocol_id, claim_revision_id = _validated_frozen(canonical)
    return FrozenProtocol(protocol_id, claim_revision_id, canonical)
