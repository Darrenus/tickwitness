"""Validate first, then publish immutable data through a repository port."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tickwitness.domain.data_evidence.events import ValidationLimits, normalize_events


class DatasetRecord(Protocol):
    """Published language exposed by a dataset repository, without storage internals."""

    @property
    def dataset_id(self) -> str: ...

    @property
    def manifest(self) -> dict[str, object]: ...

    @property
    def report(self) -> dict[str, object]: ...

    @property
    def created(self) -> bool: ...


class DatasetRepository(Protocol):
    """Storage port: the domain and use case do not depend on SQLite or CAS paths."""

    def publish(
        self,
        raw: bytes,
        normalized: bytes,
        report: dict[str, object],
        *,
        format_id: str = "tickwitness.normalized-events.v1",
    ) -> DatasetRecord: ...

    def get(self, dataset_id: str) -> DatasetRecord: ...

    def list_datasets(self) -> tuple[DatasetRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class ImportReceipt:
    """A publication receipt; sealing integrity is distinct from replay suitability."""

    dataset_id: str
    created: bool
    manifest: dict[str, object]
    report: dict[str, object]


def import_events(
    raw: bytes,
    repository_factory: Callable[[], DatasetRepository],
    *,
    limits: ValidationLimits | None = None,
) -> ImportReceipt:
    """Reject malformed or over-budget input before constructing the destination."""
    dataset = normalize_events(raw, limits if limits is not None else ValidationLimits())
    record = repository_factory().publish(raw, dataset.normalized_bytes, dataset.report)
    return ImportReceipt(record.dataset_id, record.created, record.manifest, record.report)


def inspect_dataset(dataset_id: str, repository: DatasetRepository) -> ImportReceipt:
    """Read a dataset only after the repository verifies its artifact closure."""
    record = repository.get(dataset_id)
    return ImportReceipt(record.dataset_id, False, record.manifest, record.report)
