"""Freeze auditable declarations and expose only their development observations.

This enforces application routing. It does not hide files from the host owner,
approve engine execution, evaluate a metric, or create a run-attempt ledger.
"""

import ast
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.domain.research_contracts.protocols import (
    FrozenProtocol,
    ProtocolValidationError,
    build_frozen_protocol,
    load_frozen_protocol,
)

_MAX_STRATEGY_BYTES = 256 * 1024


class ConfirmationAccessDenied(PermissionError):
    """The current application phase never exposes confirmation observations."""


class ProtocolRecord(Protocol):
    @property
    def protocol_id(self) -> str: ...

    @property
    def canonical_bytes(self) -> bytes: ...

    @property
    def strategy_sha256(self) -> str: ...

    @property
    def created(self) -> bool: ...


class ProtocolReader(Protocol):
    def get(self, protocol_id: str) -> ProtocolRecord: ...


class ProtocolRepository(ProtocolReader, Protocol):
    def seal(self, protocol_bytes: bytes, strategy_bytes: bytes) -> ProtocolRecord: ...


@dataclass(frozen=True, slots=True)
class ProtocolReceipt:
    protocol_id: str
    claim_revision_id: str
    created: bool
    document: dict[str, object]


@dataclass(frozen=True, slots=True)
class DevelopmentRead:
    protocol_id: str
    dataset_id: str
    observations: tuple[dict[str, object], ...]
    total_records: int
    truncated: bool


def _strategy_digest(source: bytes) -> str:
    if not isinstance(source, bytes) or not 0 < len(source) <= _MAX_STRATEGY_BYTES:
        raise ProtocolValidationError("Strategy source must contain 1 to 262144 bytes")
    try:
        text = source.decode("utf-8", errors="strict")
        ast.parse(text, mode="exec", feature_version=(3, 12))
    except (UnicodeError, SyntaxError, ValueError, RecursionError) as error:
        raise ProtocolValidationError("Strategy source must be UTF-8 Python 3.12 syntax") from error
    return hashlib.sha256(source).hexdigest()


def _dataset_records(dataset_id: str, datasets: DatasetReader) -> tuple[dict[str, object], ...]:
    try:
        data = read_accepted_events(dataset_id, datasets)
    except DataAccessError as error:
        raise ProtocolValidationError(str(error)) from error
    return tuple(cast("dict[str, object]", json.loads(line)) for line in data.splitlines())


def _stream(record: dict[str, object]) -> tuple[str, str, str]:
    return (
        cast("str", record["source"]),
        cast("str", record["instrument"]),
        cast("str", record["session"]),
    )


def _semantic_identity(record: dict[str, object]) -> bytes:
    # Stable origin identities cannot become independent observations by changing
    # timestamps, capture metadata, or conflicting market payloads.
    content = {
        "source": record["source"],
        "instrument": record["instrument"],
        "session": record["session"],
    }
    if record["type"] == "trade":
        content.update({"kind": "trade", "trade_id": record["trade_id"]})
    else:
        last = record["last_sequence"]
        content.update(
            {
                "kind": "book_sequence_interval",
                "first_sequence": record["first_sequence"] if record["type"] == "delta" else last,
                "last_sequence": last,
            }
        )
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).digest()


def _assert_forward_disjoint(
    development: tuple[dict[str, object], ...], confirmation: tuple[dict[str, object], ...]
) -> None:
    def ranges(
        records: tuple[dict[str, object], ...], *, book_sequences: bool = False
    ) -> dict[tuple[str, str, str], tuple[int, int]]:
        result: dict[tuple[str, str, str], tuple[int, int]] = {}
        for record in records:
            stream = _stream(record)
            if book_sequences:
                if record["type"] == "trade":
                    continue
                last = cast("int", record["last_sequence"])
                first = cast("int", record["first_sequence"]) if record["type"] == "delta" else last
            else:
                first = last = cast("int", record["capture_seq"])
            low, high = result.get(stream, (first, last))
            result[stream] = min(low, first), max(high, last)
        return result

    dev_ranges, confirmation_ranges = ranges(development), ranges(confirmation)
    if dev_ranges.keys() != confirmation_ranges.keys() or any(
        dev_ranges[stream][1] >= confirmation_ranges[stream][0] for stream in dev_ranges
    ):
        raise ProtocolValidationError(
            "Partitions must be disjoint forward captures of the same streams"
        )
    dev_book = ranges(development, book_sequences=True)
    confirmation_book = ranges(confirmation, book_sequences=True)
    if any(
        dev_book[stream][1] >= confirmation_book[stream][0]
        for stream in dev_book.keys() & confirmation_book.keys()
    ):
        raise ProtocolValidationError(
            "Partitions contain overlapping or reversed book sequence ranges"
        )
    dev_observations = {_semantic_identity(record) for record in development}
    if any(_semantic_identity(record) in dev_observations for record in confirmation):
        raise ProtocolValidationError("Partitions contain overlapping market observations")


def freeze_protocol(
    request: bytes,
    *,
    development_dataset_id: str,
    confirmation_dataset_id: str,
    strategy_source: bytes,
    datasets: DatasetReader,
    registry_factory: Callable[[], ProtocolRepository],
) -> ProtocolReceipt:
    """Validate real bindings before creating a registry or exposing a declaration."""
    strategy_sha256 = _strategy_digest(strategy_source)
    frozen = build_frozen_protocol(
        request,
        development_dataset_id=development_dataset_id,
        confirmation_dataset_id=confirmation_dataset_id,
        strategy_sha256=strategy_sha256,
    )
    development = _dataset_records(development_dataset_id, datasets)
    confirmation = _dataset_records(confirmation_dataset_id, datasets)
    _assert_forward_disjoint(development, confirmation)
    stored = registry_factory().seal(frozen.canonical_bytes, strategy_source)
    if (
        stored.protocol_id != frozen.protocol_id
        or stored.canonical_bytes != frozen.canonical_bytes
        or stored.strategy_sha256 != strategy_sha256
    ):
        raise ProtocolValidationError("Registry returned a conflicting protocol identity")
    return ProtocolReceipt(
        frozen.protocol_id, frozen.claim_revision_id, stored.created, frozen.document
    )


def _load_protocol(protocol_id: str, registry: ProtocolReader) -> FrozenProtocol:
    stored = registry.get(protocol_id)
    frozen = load_frozen_protocol(stored.canonical_bytes)
    strategy = cast("dict[str, str]", frozen.document["strategy"])
    if (
        stored.protocol_id != protocol_id
        or frozen.protocol_id != protocol_id
        or stored.strategy_sha256 != strategy["sha256"]
    ):
        raise ProtocolValidationError("Registered protocol identity does not match")
    return frozen


def inspect_protocol(
    protocol_id: str, registry: ProtocolReader, datasets: DatasetReader
) -> ProtocolReceipt:
    """Verify registered source and dataset references; do not expose observations."""
    frozen = _load_protocol(protocol_id, registry)
    references = cast("dict[str, str]", frozen.document["datasets"])
    for identity in references.values():
        if datasets.get(identity).dataset_id != identity:
            raise ProtocolValidationError("Protocol dataset reference does not match")
    return ProtocolReceipt(frozen.protocol_id, frozen.claim_revision_id, False, frozen.document)


def read_protocol_data(
    protocol_id: str,
    *,
    split: str,
    registry_factory: Callable[[], ProtocolReader],
    datasets_factory: Callable[[], DatasetReader],
    limit: int = 100,
) -> DevelopmentRead:
    """Return development observations only; confirmation denial precedes all I/O."""
    if split != "development":
        raise ConfirmationAccessDenied(
            "Only development data is accessible in this application phase"
        )
    if type(limit) is not int or not 1 <= limit <= 1_000:
        raise ProtocolValidationError("Read limit must be an integer from 1 to 1000")
    frozen = _load_protocol(protocol_id, registry_factory())
    budget = cast("dict[str, int]", frozen.document["budget"])
    if limit > budget["max_events"]:
        raise ProtocolValidationError("Read limit exceeds the frozen max_events budget")
    references = cast("dict[str, str]", frozen.document["datasets"])
    identity = references["development"]
    observations = _dataset_records(identity, datasets_factory())
    return DevelopmentRead(
        frozen.protocol_id,
        identity,
        observations[:limit],
        len(observations),
        len(observations) > limit,
    )
