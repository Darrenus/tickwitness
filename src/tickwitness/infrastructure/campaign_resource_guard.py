"""Per-process write admission for one nonresumable bounded campaign.

The parent supervisor enforces process time. This guard additionally checks the
same absolute deadline before each admission/write, and protects every managed
payload write from consuming beyond its conservative reserved envelope.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import cast

from tickwitness.domain.search.budgets import (
    CANDIDATE_RESERVE_BYTES,
    CONTROL_RESERVE_BYTES,
    TERMINAL_RESERVE_BYTES,
    CampaignBudget,
    build_allocation,
    load_campaign_budget,
)
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore


class CampaignLimitReached(BaseException):
    """Stop before an unadmitted write/attempt, bypassing legacy Exception catchers."""

    def __init__(self, reason: str) -> None:
        if reason not in ("evaluation_limit", "storage_limit", "time_limit"):
            raise ValueError("Unsupported resource limit reason")
        self.reason = self.code = reason
        self.exit_code = 8
        super().__init__(reason)


class CampaignResourceGuardError(ValueError):
    """A guard configuration, clock or proposed write is invalid."""


class CampaignResourceGuard:
    """Sequential candidate lanes; reservations and write charges are never refunded."""

    def __init__(
        self, budget: CampaignBudget, store: LocalCampaignBudgetStore,
        clock_ns: Callable[[], int], deadline_ns: int,
    ) -> None:
        if type(budget) is not CampaignBudget:
            raise CampaignResourceGuardError("Guard requires an actual frozen campaign budget")
        checked = load_campaign_budget(budget.canonical_bytes)
        if checked.budget_id != budget.budget_id:
            raise CampaignResourceGuardError("Guard budget identity differs")
        if type(deadline_ns) is not int or deadline_ns <= 0:
            raise CampaignResourceGuardError("Deadline must be a positive absolute monotonic integer")
        self.budget, self.store, self.clock_ns, self.deadline_ns = checked, store, clock_ns, deadline_ns
        self._plan_id = cast("str", checked.document["plan_id"])
        if store.get_budget(self._plan_id) != checked.canonical_bytes:
            raise CampaignResourceGuardError("Guard budget is not the committed outer budget")
        if store.get_allocations(self._plan_id) or store.get_stop(self._plan_id) is not None:
            raise CampaignResourceGuardError("A budget guard cannot resume an existing execution")
        self._limits = cast("dict[str, int]", checked.document["limits"])
        self._control = store.control_payload_bytes(self._plan_id)
        if self._control > CONTROL_RESERVE_BYTES - TERMINAL_RESERVE_BYTES:
            raise CampaignResourceGuardError("Existing control payload exceeds reserved capacity")
        self._index = 0
        self._ordinal: int | None = None
        self._candidate_charged = 0
        self._charged_by_ordinal: dict[int, int] = {}
        self._admitted: set[int] = set()
        self._last_clock = -1
        self._poisoned = False
        self._mutex = RLock()
        self.check_time()

    def check_time(self) -> None:
        with self._mutex:
            if self._poisoned:
                raise CampaignResourceGuardError("Admission publication is uncertain; guard cannot continue")
            now = self.clock_ns()
            if type(now) is not int or now < 0 or now < self._last_clock:
                raise CampaignResourceGuardError("Monotonic clock returned an invalid or regressing value")
            self._last_clock = now
            if now >= self.deadline_ns:
                raise CampaignLimitReached("time_limit")

    def admit(self, ordinal: int) -> bytes:
        with self._mutex:
            self.check_time()
            if type(ordinal) is not int or not 1 <= ordinal <= 1_024:
                raise CampaignResourceGuardError("Candidate ordinal must be an integer in [1, 1024]")
            if ordinal in self._admitted:
                raise CampaignResourceGuardError("Candidate admission cannot be reused")
            if self._index >= self._limits["max_evaluations"]:
                raise CampaignLimitReached("evaluation_limit")
            next_index = self._index + 1
            reserved = CONTROL_RESERVE_BYTES + next_index * CANDIDATE_RESERVE_BYTES
            if reserved > self._limits["max_storage_bytes"]:
                raise CampaignLimitReached("storage_limit")
            raw = build_allocation(self.budget, ordinal, next_index)
            self._charge_control(len(raw))
            # The application will stop on publication uncertainty. Never retry
            # this guard after a failed return whose file may already exist.
            self._index = next_index
            self._admitted.add(ordinal)
            try:
                self.store.write_allocation(self._plan_id, ordinal, raw)
            except BaseException:
                self._poisoned = True
                raise
            self._ordinal = ordinal
            self._candidate_charged = 0
            self._charged_by_ordinal[ordinal] = 0
            return raw

    def _charge_control(self, nbytes: int) -> None:
        if self._control + nbytes > CONTROL_RESERVE_BYTES - TERMINAL_RESERVE_BYTES:
            raise CampaignLimitReached("storage_limit")
        self._control += nbytes

    def before_write(self, nbytes: int) -> None:
        with self._mutex:
            self.check_time()
            if type(nbytes) is not int or nbytes < 0:
                raise CampaignResourceGuardError("Write charge must be a nonnegative integer")
            if self._ordinal is None:
                self._charge_control(nbytes)
                return
            if self._candidate_charged + nbytes > CANDIDATE_RESERVE_BYTES:
                raise CampaignLimitReached("storage_limit")
            self._candidate_charged += nbytes
            self._charged_by_ordinal[self._ordinal] = self._candidate_charged

    @property
    def usage(self) -> dict[str, object]:
        with self._mutex:
            return {
                "control_charged_bytes": self._control,
                "allocation_count": self._index,
                "reserved_storage_bytes": CONTROL_RESERVE_BYTES + self._index * CANDIDATE_RESERVE_BYTES,
                "current_ordinal": self._ordinal,
                "current_candidate_charged_bytes": self._candidate_charged,
                "candidate_charges": dict(self._charged_by_ordinal),
            }


_ACTIVE_GUARD: ContextVar[CampaignResourceGuard | None] = ContextVar("campaign_resource_guard", default=None)


@contextmanager
def activate_resource_guard(guard: CampaignResourceGuard) -> Iterator[None]:
    if type(guard) is not CampaignResourceGuard:
        raise CampaignResourceGuardError("Expected an actual resource guard")
    token = _ACTIVE_GUARD.set(guard)
    try:
        yield
    finally:
        _ACTIVE_GUARD.reset(token)


def charge_managed_write(nbytes: int) -> None:
    """Called immediately before a new payload file is opened for writing."""
    guard = _ACTIVE_GUARD.get()
    if guard is not None:
        guard.before_write(nbytes)
