"""Versioned built-in research protocols, separate from immutable v1 declarations.

This value binds supported execution and valuation semantics. Dataset closure,
development-only reads and attempt reservations remain application obligations.
"""

from dataclasses import dataclass
from typing import cast

from tickwitness.domain.replay.specs import (
    ReplayValidationError,
    build_replay_spec,
)
from tickwitness.domain.research_contracts.protocols import (
    ProtocolValidationError as ProtocolValidationError,
)
from tickwitness.domain.research_contracts.protocols import (
    _canonical,
    _claim,
    _digest,
    _hash,
    _integer,
    _object,
    _parse,
)

MAX_EXECUTABLE_BYTES = 128 * 1024
ENGINE_ID = "nautilus-trader"
ENGINE_VERSION = "1.231.0"
ENGINE_SEMANTIC_ID = "nautilus_v1_receive_order_single_limit_buy_v1"
EVALUATION_POLICY = "last_observed_bid_mark_v1"
_REQUEST_FIELDS = frozenset({"schema_version", "claim", "replay_spec", "budget"})
_DOCUMENT_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "read_policy",
        "evaluation_policy",
        "claim_revision_id",
        "claim",
        "datasets",
        "strategy",
        "engine",
        "replay_spec_id",
        "replay_spec",
        "budget",
    }
)
_BUDGET_BOUNDS = {"max_attempts": 100, "max_wall_seconds": 60, "max_events": 10_000}


def _encode(value: dict[str, object]) -> bytes:
    try:
        return _canonical(value)
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ProtocolValidationError(
            "Executable protocol must contain valid JSON values"
        ) from error


def _build_document(
    request: dict[str, object],
    *,
    development_dataset_id: str,
    confirmation_dataset_id: str,
) -> dict[str, object]:
    request = _object(request, _REQUEST_FIELDS, "executable request")
    _integer(request["schema_version"], "schema_version", 2, 2)
    development = _hash(development_dataset_id, "development_dataset_id")
    confirmation = _hash(confirmation_dataset_id, "confirmation_dataset_id")
    if development == confirmation:
        raise ProtocolValidationError("Development and confirmation dataset identities must differ")
    claim = _claim(request["claim"])
    if claim["unit"] != "USD":
        raise ProtocolValidationError("Executable net_marked_pnl_v1 claims require unit USD")
    if not isinstance(request["replay_spec"], dict):
        raise ProtocolValidationError("replay_spec must be an embedded JSON object")
    try:
        replay_spec = build_replay_spec(_encode(cast("dict[str, object]", request["replay_spec"])))
    except ReplayValidationError as error:
        raise ProtocolValidationError(f"Unsupported embedded replay_spec: {error}") from error
    budget = _object(request["budget"], frozenset(_BUDGET_BOUNDS), "budget")
    return {
        "kind": "executable_research_protocol_v2",
        "schema_version": 2,
        "read_policy": "development_only_v1",
        "evaluation_policy": EVALUATION_POLICY,
        "claim_revision_id": _digest(_encode(claim)),
        "claim": claim,
        "datasets": {"development": development, "confirmation": confirmation},
        "strategy": {
            "kind": "builtin",
            "id": "single_limit_buy_v1",
            "semantic_id": ENGINE_SEMANTIC_ID,
        },
        "engine": {
            "id": ENGINE_ID,
            "version": ENGINE_VERSION,
            "semantic_id": ENGINE_SEMANTIC_ID,
        },
        "replay_spec_id": replay_spec.spec_id,
        "replay_spec": replay_spec.document,
        "budget": {
            key: _integer(budget[key], key, 1, maximum) for key, maximum in _BUDGET_BOUNDS.items()
        },
    }


def _validated(canonical_bytes: bytes) -> tuple[str, str]:
    document = _object(
        _parse(canonical_bytes, max_bytes=MAX_EXECUTABLE_BYTES),
        _DOCUMENT_FIELDS,
        "executable document",
    )
    datasets = _object(document["datasets"], frozenset({"development", "confirmation"}), "datasets")
    rebuilt = _build_document(
        {
            "schema_version": document["schema_version"],
            "claim": document["claim"],
            "replay_spec": document["replay_spec"],
            "budget": document["budget"],
        },
        development_dataset_id=_hash(datasets["development"], "development_dataset_id"),
        confirmation_dataset_id=_hash(datasets["confirmation"], "confirmation_dataset_id"),
    )
    # Compare exact encoding, never Python equality (where True == 1 == 1.0).
    if _encode(rebuilt) != canonical_bytes:
        raise ProtocolValidationError("Executable document policies, identities or encoding differ")
    return _digest(canonical_bytes), cast("str", rebuilt["claim_revision_id"])


@dataclass(frozen=True, slots=True)
class ExecutableProtocol:
    """An immutable version-two value; not a permission to read confirmation data."""

    protocol_id: str
    claim_revision_id: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        identities = _validated(self.canonical_bytes)
        if identities != (self.protocol_id, self.claim_revision_id):
            raise ProtocolValidationError("ExecutableProtocol identities do not match content")

    @property
    def document(self) -> dict[str, object]:
        return _parse(self.canonical_bytes, max_bytes=MAX_EXECUTABLE_BYTES)


def build_executable_protocol(
    request: bytes,
    *,
    development_dataset_id: str,
    confirmation_dataset_id: str,
) -> ExecutableProtocol:
    """Bind a built-in spec and claim; never inspect datasets or reserve an attempt."""
    document = _build_document(
        _parse(request, max_bytes=MAX_EXECUTABLE_BYTES),
        development_dataset_id=development_dataset_id,
        confirmation_dataset_id=confirmation_dataset_id,
    )
    encoded = _encode(document)
    return ExecutableProtocol(_digest(encoded), cast("str", document["claim_revision_id"]), encoded)


def load_executable_protocol(canonical_bytes: bytes) -> ExecutableProtocol:
    """Rebuild every fixed marker and content identity; reject declarations from v1."""
    protocol_id, claim_revision_id = _validated(canonical_bytes)
    return ExecutableProtocol(protocol_id, claim_revision_id, canonical_bytes)
