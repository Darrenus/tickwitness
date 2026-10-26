"""Fail explicitly when a requested replay capability is unavailable.

These types record a declared capability set, not proof that an engine satisfies it.
Adapters must acquire their evidence through contract tests in later Sprints.
"""

from dataclasses import dataclass
from enum import StrEnum


class ReplayCapability(StrEnum):
    """Capabilities needed by the initial engine feasibility investigation."""

    INPUT_EVENT_TRACE = "input_event_trace"
    DECISION_TRACE = "decision_trace"
    ORDER_LIFECYCLE = "order_lifecycle"
    FILL_TRACE = "fill_trace"
    ACCOUNT_LEDGER = "account_ledger"
    EXPLICIT_QUEUE_ALLOCATION = "explicit_queue_allocation"
    CHECKPOINT = "checkpoint"


class UnsupportedCapabilityError(ValueError):
    """The requested replay cannot run with the declared engine capabilities."""

    def __init__(
        self,
        engine_id: str,
        engine_version: str,
        missing: frozenset[ReplayCapability],
    ) -> None:
        self.engine_id = engine_id
        self.engine_version = engine_version
        self.missing = missing
        names = ", ".join(sorted(item.value for item in missing))
        super().__init__(f"{engine_id}@{engine_version} does not support: {names}")


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    """Version-specific declarations; absent capabilities never silently fall back."""

    engine_id: str
    engine_version: str
    supported: frozenset[ReplayCapability]

    def require(self, requested: frozenset[ReplayCapability]) -> None:
        """Reject the entire request when any requested capability is missing."""
        missing = requested - self.supported
        if missing:
            raise UnsupportedCapabilityError(self.engine_id, self.engine_version, missing)
