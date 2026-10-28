"""Validate frozen bindings, then consume one whole managed confirmation window.

The durable exposure transaction precedes observation release. An exception,
interrupted delivery or invalid port receipt cannot refund that consumption.
Existing exploration and execution policies do not change.
"""

import json
from collections.abc import Callable
from typing import Protocol, cast

from tickwitness.application.data_access import (
    DataAccessError,
    DatasetReader,
    assert_forward_disjoint,
    read_accepted_events,
)
from tickwitness.domain.evidence.run_records import canonical, identity
from tickwitness.domain.research_contracts.confirmation import (
    SCOPE,
    ConfirmationAlreadyExposed,
    ConfirmationExposure,
    ConfirmationProtocol,
    ConfirmationValidationError,
    OriginFootprint,
    build_confirmation_exposure,
    build_confirmation_protocol,
    footprints_overlap,
    load_confirmation_exposure,
    load_confirmation_protocol,
    load_origin_footprint,
)
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.protocols import (
    ProtocolValidationError,
    _parse,
    load_frozen_protocol,
)

type Row = dict[str, object]


class SourceRecord(Protocol):
    @property
    def protocol_id(self) -> str: ...
    @property
    def canonical_bytes(self) -> bytes: ...


class SourceReader(Protocol):
    """Read an actual source record, including its repository's strategy closure."""

    def get(self, protocol_id: str) -> SourceRecord: ...


class ConfirmationRecord(Protocol):
    @property
    def protocol_id(self) -> str: ...
    @property
    def canonical_bytes(self) -> bytes: ...
    @property
    def created(self) -> bool: ...


class ConfirmationRepository(Protocol):
    def get(self, protocol_id: str) -> ConfirmationRecord: ...
    def seal(self, canonical_bytes: bytes) -> ConfirmationRecord: ...


class ExposureReader(Protocol):
    def find_conflicts(self, footprint: OriginFootprint) -> tuple[ConfirmationExposure, ...]: ...


class ExposureRepository(ExposureReader, Protocol):
    """Atomically recheck origin conflicts and durably commit before returning."""

    def expose(self, protocol: ConfirmationProtocol) -> ConfirmationExposure: ...


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfirmationValidationError(message)


def _identity(protocol_id: str) -> None:
    try:
        identity(protocol_id)
    except ValueError as error:
        raise ConfirmationValidationError(str(error)) from error


def _source(protocol_id: str, reader: SourceReader) -> SourceRecord:
    _identity(protocol_id)
    record = reader.get(protocol_id)
    try:
        identity(protocol_id)
        document = _parse(record.canonical_bytes, max_bytes=128 * 1024)
        if document.get("kind") == "frozen_research_protocol_v1":
            value = load_frozen_protocol(record.canonical_bytes)
            actual_id = value.protocol_id
        else:
            actual_id = load_executable_protocol(record.canonical_bytes).protocol_id
        _require(
            record.protocol_id == protocol_id == actual_id,
            "Actual source protocol identity differs",
        )
        return record
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ConfirmationValidationError(
            "Invalid actual source protocol: " + str(error)
        ) from error


def _records(data: bytes) -> tuple[Row, ...]:
    return tuple(cast("Row", json.loads(line)) for line in data.splitlines())


def _partitions(source: bytes, datasets: DatasetReader) -> tuple[bytes, tuple[Row, ...]]:
    document = cast("Row", json.loads(source))
    refs = cast("dict[str, str]", document["datasets"])
    try:
        development = read_accepted_events(refs["development"], datasets)
        confirmation = read_accepted_events(refs["confirmation"], datasets)
    except DataAccessError as error:
        raise ConfirmationValidationError(
            "Invalid actual confirmation partitions: " + str(error)
        ) from error
    try:
        records = _records(confirmation)
        assert_forward_disjoint(_records(development), records)
        return confirmation, records
    except (ProtocolValidationError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ConfirmationValidationError(
            "Invalid actual confirmation partitions: " + str(error)
        ) from error


def _load(protocol_id: str, registry: ConfirmationRepository) -> ConfirmationProtocol:
    try:
        identity(protocol_id)
        record = registry.get(protocol_id)
        protocol = load_confirmation_protocol(record.canonical_bytes)
        _require(
            record.protocol_id == protocol_id == protocol.protocol_id,
            "Registered confirmation identity differs",
        )
        return protocol
    except ConfirmationValidationError:
        raise
    except (KeyError, TypeError, AttributeError) as error:
        raise ConfirmationValidationError(
            "Invalid confirmation registry record: " + str(error)
        ) from error


def _footprint(protocol: ConfirmationProtocol) -> OriginFootprint:
    return load_origin_footprint(canonical(cast("Row", protocol.document["origin_footprint"])))


def _conflicts(
    protocol: ConfirmationProtocol, reader: ExposureReader
) -> tuple[ConfirmationExposure, ...]:
    footprint = _footprint(protocol)
    conflicts = reader.find_conflicts(footprint)
    _require(
        type(conflicts) is tuple and len(conflicts) <= 256,
        "Invalid managed exposure conflict inventory",
    )
    result: list[ConfirmationExposure] = []
    for record in conflicts:
        checked = load_confirmation_exposure(record.canonical_bytes)
        _require(checked.exposure_id == record.exposure_id, "Managed exposure identity differs")
        other = load_origin_footprint(canonical(cast("Row", checked.document["origin_footprint"])))
        _require(
            footprints_overlap(footprint, other), "Managed exposure does not overlap this window"
        )
        result.append(checked)
    _require(
        len({record.exposure_id for record in result}) == len(result),
        "Duplicate managed exposure conflict",
    )
    return tuple(sorted(result, key=lambda record: record.exposure_id))


def _receipt(
    protocol: ConfirmationProtocol, created: bool, conflicts: tuple[ConfirmationExposure, ...]
) -> Row:
    return {
        "kind": "confirmation_protocol_receipt_v1",
        "schema_version": 1,
        "protocol_id": protocol.protocol_id,
        "created": created,
        "document": protocol.document,
        "exposure_status": "ALREADY_EXPOSED_IN_LEDGER"
        if conflicts
        else "NO_MATCHING_EXPOSURE_IN_LEDGER",
        "related_exposure_ids": [record.exposure_id for record in conflicts],
        "scope": dict(SCOPE),
    }


def _revalidate(
    protocol: ConfirmationProtocol,
    source_factory: Callable[[], SourceReader],
    datasets_factory: Callable[[], DatasetReader],
) -> tuple[Row, ...]:
    document = protocol.document
    source_id = cast("str", cast("Row", document["bindings"])["source_protocol_id"])
    source = _source(source_id, source_factory())
    _require(
        source.canonical_bytes == canonical(cast("Row", document["source_protocol"])),
        "Actual source differs from the frozen confirmation declaration",
    )
    normalized, records = _partitions(source.canonical_bytes, datasets_factory())
    request = canonical(
        {
            "kind": "confirmation_request_v1",
            "schema_version": 1,
            "title": document["title"],
            "max_events": cast("Row", document["read_policy"])["max_events"],
        }
    )
    rebuilt = build_confirmation_protocol(
        request, source_protocol=source.canonical_bytes, confirmation_normalized=normalized
    )
    _require(
        rebuilt.canonical_bytes == protocol.canonical_bytes,
        "Actual confirmation source, data or origin footprint differs",
    )
    return records


def freeze_confirmation_protocol(
    request: bytes,
    *,
    source_protocol_id: str,
    source_factory: Callable[[], SourceReader],
    datasets_factory: Callable[[], DatasetReader],
    confirmations_factory: Callable[[], ConfirmationRepository],
    exposures_factory: Callable[[], ExposureRepository],
) -> Row:
    """Preflight real partitions before creating new confirmation state."""
    _identity(source_protocol_id)
    source = _source(source_protocol_id, source_factory())
    normalized, _records_value = _partitions(source.canonical_bytes, datasets_factory())
    protocol = build_confirmation_protocol(
        request, source_protocol=source.canonical_bytes, confirmation_normalized=normalized
    )
    conflicts = _conflicts(protocol, exposures_factory())
    stored = confirmations_factory().seal(protocol.canonical_bytes)
    _require(
        stored.protocol_id == protocol.protocol_id
        and stored.canonical_bytes == protocol.canonical_bytes
        and type(stored.created) is bool,
        "Confirmation registry returned conflicting declaration evidence",
    )
    return _receipt(protocol, stored.created, conflicts)


def inspect_confirmation_protocol(
    protocol_id: str,
    *,
    source_factory: Callable[[], SourceReader],
    datasets_factory: Callable[[], DatasetReader],
    confirmations_factory: Callable[[], ConfirmationRepository],
    exposures_factory: Callable[[], ExposureRepository],
) -> Row:
    """Revalidate actual bindings and managed exposure associations, without release."""
    _identity(protocol_id)
    protocol = _load(protocol_id, confirmations_factory())
    _revalidate(protocol, source_factory, datasets_factory)
    return _receipt(protocol, False, _conflicts(protocol, exposures_factory()))


def open_confirmation_protocol(
    protocol_id: str,
    *,
    source_factory: Callable[[], SourceReader],
    datasets_factory: Callable[[], DatasetReader],
    confirmations_factory: Callable[[], ConfirmationRepository],
    exposures_factory: Callable[[], ExposureRepository],
) -> Row:
    """Consume the full window durably before returning its first observations."""
    _identity(protocol_id)
    protocol = _load(protocol_id, confirmations_factory())
    ledger = exposures_factory()
    conflicts = _conflicts(protocol, ledger)
    if conflicts:
        raise ConfirmationAlreadyExposed(conflicts)
    records = _revalidate(protocol, source_factory, datasets_factory)
    expected = build_confirmation_exposure(protocol)
    exposed = ledger.expose(protocol)
    checked = load_confirmation_exposure(exposed.canonical_bytes)
    _require(
        checked.exposure_id == exposed.exposure_id == expected.exposure_id
        and checked.canonical_bytes == expected.canonical_bytes,
        "Exposure port returned conflicting committed evidence; exposure is not refunded",
    )
    return {
        "kind": "confirmation_observation_release_v1",
        "schema_version": 1,
        "protocol_id": protocol.protocol_id,
        "dataset_id": checked.document["confirmation_dataset_id"],
        "exposure_id": checked.exposure_id,
        "exposure": checked.document,
        "observations": list(records),
        "total_records": len(records),
        "truncated": False,
        "scope": dict(SCOPE),
    }
