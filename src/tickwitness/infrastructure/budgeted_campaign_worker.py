"""Trusted budgeted coordinator entry point; its descendants share the supervised group."""

import resource
import secrets
import signal
import sys
import time
from pathlib import Path
from typing import cast

from tickwitness.application.search_execution import run_search_plan
from tickwitness.domain.evidence.run_records import canonical, identity, parse
from tickwitness.domain.search.budgets import load_campaign_budget
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.campaign_budget_store import (
    CampaignBudgetStoreError,
    LocalCampaignBudgetStore,
)
from tickwitness.infrastructure.campaign_resource_guard import (
    CampaignLimitReached,
    CampaignResourceGuard,
    activate_resource_guard,
)
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry


def _request(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > 64 * 1024:
        raise ValueError("Campaign IPC exceeds its bounded request size")
    value: object = parse(raw, limit=64 * 1024)
    fields = {
        "schema_version",
        "plan_id",
        "budget_id",
        "runs",
        "plans",
        "store",
        "registry",
        "engine_python",
        "deadline_ns",
    }
    if (
        not isinstance(value, dict)
        or value.keys() != fields
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("Invalid trusted campaign IPC fields")
    identity(value["plan_id"])
    identity(value["budget_id"])
    for name in ("runs", "plans", "store", "registry"):
        if (
            not isinstance(value[name], str)
            or not value[name]
            or len(value[name]) > 4096
            or "\x00" in value[name]
        ):
            raise ValueError("Invalid trusted campaign path")
    if value["engine_python"] is not None and not isinstance(value["engine_python"], str):
        raise ValueError("Invalid trusted engine interpreter")
    if type(value["deadline_ns"]) is not int or value["deadline_ns"] <= 0:
        raise ValueError("Invalid absolute campaign deadline")
    return cast("dict[str, object]", value)


def main() -> int:
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
    # Native crashes must not create an unmetered core-dump payload.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        request = _request(sys.stdin.buffer.read(64 * 1024 + 1))
        plan_id = cast("str", request["plan_id"])
        runs = Path(cast("str", request["runs"]))
        budgets = LocalCampaignBudgetStore(runs, create=True)
        raw = budgets.get_budget(plan_id)
        if raw is None:
            raise ValueError("Frozen outer budget is missing")
        budget = load_campaign_budget(raw)
        if budget.budget_id != request["budget_id"]:
            raise ValueError("Outer budget identity differs from the supervised request")
        deadline = cast("int", request["deadline_ns"])
        guard = CampaignResourceGuard(budget, budgets, time.monotonic_ns, deadline)
        managed = budgets.managed_root(plan_id)
        engine = request["engine_python"]
        engine_path = Path(engine) if isinstance(engine, str) else None

        def admit(ordinal: int) -> None:
            guard.admit(ordinal)

        with activate_resource_guard(guard):
            report = run_search_plan(
                plan_id,
                split="development",
                plans_factory=lambda: LocalSearchPlanRegistry(
                    Path(cast("str", request["plans"])), create=False
                ),
                registry_factory=lambda: LocalExecutableProtocolRegistry(
                    Path(cast("str", request["registry"])), create=False
                ),
                datasets_factory=lambda: LocalDatasetStore(
                    Path(cast("str", request["store"])), create=False
                ),
                ledger_factory=lambda: LocalAttemptLedger(runs, create=True),
                ledger_reader_factory=lambda: LocalAttemptLedger(runs, create=False),
                campaigns_factory=lambda: LocalSearchCampaignStore(managed, create=True),
                engine_factory=lambda timeout: BoundedReplayAdapter(
                    timeout_seconds=timeout,
                    deadline_ns=deadline,
                    python_executable=engine_path,
                ),
                nonce_factory=lambda: secrets.token_hex(16),
                candidate_gate=admit,
            )
        reason = "completed" if report["status"] == "completed" else "execution_stopped"
        code = cast("int", report["exit_code"])
    except CampaignLimitReached as error:
        reason, code = error.reason, 8
    except CampaignBudgetStoreError:
        reason, code = "publication_unconfirmed", 3
    except Exception:
        reason, code = "worker_failed", 7
    sys.stdout.buffer.write(canonical({"reason": reason, "exit_code": code}))
    sys.stdout.buffer.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
