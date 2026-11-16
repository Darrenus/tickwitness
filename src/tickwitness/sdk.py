"""Stable local SDK subset over the same application services as the CLI.

This adapter binds data and declarations and reads bounded development
observations. It does not execute research or grant confirmation access.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from re import fullmatch
from typing import Literal

from tickwitness.application import datasets as _datasets
from tickwitness.application import research as _research
from tickwitness.application.datasets import ImportReceipt as ImportReceipt
from tickwitness.application.research import DevelopmentRead as DevelopmentRead
from tickwitness.application.research import ProtocolReceipt as ProtocolReceipt
from tickwitness.domain.data_evidence.events import DataValidationError as _DataValidationError
from tickwitness.domain.data_evidence.events import ValidationLimits as ValidationLimits
from tickwitness.domain.research_contracts.protocols import (
    ProtocolValidationError as _ProtocolValidationError,
)
from tickwitness.infrastructure.local_dataset_store import (
    DatasetNotFoundError as _DatasetNotFoundError,
)
from tickwitness.infrastructure.local_dataset_store import DatasetStoreError as _DatasetStoreError
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore as _LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import (
    LocalProtocolRegistry as _LocalProtocolRegistry,
)
from tickwitness.infrastructure.local_protocol_registry import (
    ProtocolNotFoundError as _ProtocolNotFoundError,
)
from tickwitness.infrastructure.local_protocol_registry import (
    ProtocolRegistryError as _ProtocolRegistryError,
)
from tickwitness.infrastructure.safe_input import InputReadError as _InputReadError
from tickwitness.infrastructure.safe_input import read_jsonl as _read_jsonl
from tickwitness.infrastructure.safe_input import read_regular_file as _read_regular_file

__all__ = (
    "SDK_CONTRACT_VERSION",
    "Client",
    "DevelopmentRead",
    "ImportReceipt",
    "ProtocolReceipt",
    "SDKError",
    "ValidationLimits",
)

SDK_CONTRACT_VERSION = 1


class SDKError(RuntimeError):
    """A covered adapter failure with CLI-compatible code and exit semantics."""

    def __init__(self, code: str, message: str, exit_code: int) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        """Return a fresh CLI-shaped error envelope, without traceback objects."""
        return {"error": {"code": self.code, "message": str(self)}}


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except _InputReadError as error:
        raise SDKError("unsafe_input", str(error), 2) from error
    except _DataValidationError as error:
        raise SDKError("invalid_data", str(error), 2) from error
    except _ProtocolValidationError as error:
        raise SDKError("invalid_protocol", str(error), 2) from error
    except _research.ConfirmationAccessDenied as error:
        raise SDKError("confirmation_access_denied", str(error), 5) from error
    except _DatasetNotFoundError as error:
        raise SDKError("dataset_not_found", str(error), 4) from error
    except _DatasetStoreError as error:
        raise SDKError("store_integrity_or_publication_failure", str(error), 3) from error
    except _ProtocolNotFoundError as error:
        raise SDKError("protocol_not_found", str(error), 4) from error
    except _ProtocolRegistryError as error:
        raise SDKError("protocol_integrity_or_publication_failure", str(error), 3) from error
    except OSError as error:
        raise SDKError("io_failure", str(error), 3) from error


def _identity(value: str, name: str) -> None:
    if fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SDKError("invalid_sdk_argument", f"{name} must be a lowercase SHA-256 digest", 2)


@dataclass(frozen=True, slots=True, kw_only=True)
class Client:
    """Handle-free trusted local configuration; construction performs no IO.

    Results are existing shallow-frozen application values. Their nested JSON
    is detached from storage, not recursively immutable. All writes and reads
    retain the original application validation and publication semantics.
    """

    store: Path
    registry: Path

    def import_events(
        self, input: str, *, input_root: Path, limits: ValidationLimits | None = None
    ) -> ImportReceipt:
        """Safely import one relative JSONL file, validating before publication."""
        bounded = ValidationLimits() if limits is None else limits

        def operation() -> ImportReceipt:
            raw = _read_jsonl(input_root, input, max_bytes=bounded.max_bytes)
            return _datasets.import_events(
                raw, lambda: _LocalDatasetStore(self.store), limits=bounded
            )

        return _call(operation)

    def inspect_dataset(self, dataset_id: str) -> ImportReceipt:
        """Verify an existing dataset closure without creating a destination."""
        _identity(dataset_id, "dataset_id")
        return _call(
            lambda: _datasets.inspect_dataset(
                dataset_id, _LocalDatasetStore(self.store, create=False)
            )
        )

    def freeze_protocol(
        self,
        input: str,
        *,
        input_root: Path,
        strategy_source: str,
        development_dataset_id: str,
        confirmation_dataset_id: str,
    ) -> ProtocolReceipt:
        """Bind a declaration to disjoint datasets and source, without execution."""
        _identity(development_dataset_id, "development_dataset_id")
        _identity(confirmation_dataset_id, "confirmation_dataset_id")

        def operation() -> ProtocolReceipt:
            request = _read_regular_file(
                input_root, input, max_bytes=64 * 1024, allowed_suffixes=frozenset({".json"})
            )
            source = _read_regular_file(
                input_root,
                strategy_source,
                max_bytes=256 * 1024,
                allowed_suffixes=frozenset({".py"}),
            )
            return _research.freeze_protocol(
                request,
                development_dataset_id=development_dataset_id,
                confirmation_dataset_id=confirmation_dataset_id,
                strategy_source=source,
                datasets=_LocalDatasetStore(self.store, create=False),
                registry_factory=lambda: _LocalProtocolRegistry(self.registry),
            )

        return _call(operation)

    def inspect_protocol(self, protocol_id: str) -> ProtocolReceipt:
        """Verify registered declaration/source and existing dataset references."""
        _identity(protocol_id, "protocol_id")
        return _call(
            lambda: _research.inspect_protocol(
                protocol_id,
                _LocalProtocolRegistry(self.registry, create=False),
                _LocalDatasetStore(self.store, create=False),
            )
        )

    def read_protocol_data(
        self,
        protocol_id: str,
        *,
        split: Literal["development", "confirmation"] = "development",
        limit: int = 100,
    ) -> DevelopmentRead:
        """Read bounded development observations; other splits refuse before IO."""
        if split == "development":
            _identity(protocol_id, "protocol_id")
        return _call(
            lambda: _research.read_protocol_data(
                protocol_id,
                split=split,
                limit=limit,
                registry_factory=lambda: _LocalProtocolRegistry(self.registry, create=False),
                datasets_factory=lambda: _LocalDatasetStore(self.store, create=False),
            )
        )
