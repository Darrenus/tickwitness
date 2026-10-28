"""Pin, collect and relocate real saved-fixture search evidence without replay."""

import shutil
import socket
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest
from test_search_findings import execute, inspect, prepare

from tickwitness.application.bounded_search import run_bounded_search_campaign
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_evidence import (
    collect_search_artifacts,
    export_search_evidence,
    verify_search_package,
)
from tickwitness.application.search_findings import evaluate_search_findings
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_campaign_store import (
    LocalSearchCampaignStore,
    SearchCampaignNotFoundError,
)
from tickwitness.infrastructure.search_evidence_bundles import (
    export_search_evidence_bundle,
    read_search_evidence_bundle,
)
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry


def forbidden(*_args, **_kwargs):
    raise AssertionError("Portable verification cannot open an original source or execute")


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def inputs(case, authority_id):
    def campaign(plan_id):
        budget = LocalCampaignBudgetStore(case.root / "runs")
        try:
            return LocalSearchCampaignStore(budget.managed_root(plan_id))
        except SearchCampaignNotFoundError:
            return None

    receipt = evaluate_search_findings(
        authority_id,
        split="development",
        findings_factory=lambda: LocalSearchFindingRegistry(case.root / "findings"),
        campaign_inspector=lambda plan_id: inspect(case, plan_id),
    )
    return receipt, {
        "expected_report_id": receipt["report_id"],
        "split": "development",
        "findings_factory": lambda: LocalSearchFindingRegistry(case.root / "findings"),
        "datasets_factory": lambda: LocalDatasetStore(case.root / "data", create=False),
        "budgets_factory": lambda: LocalCampaignBudgetStore(case.root / "runs"),
        "campaigns_factory": campaign,
        "ledger_factory": lambda: LocalAttemptLedger(case.root / "runs", create=False),
        "campaign_inspector": lambda plan_id: inspect(case, plan_id),
        "producer_version": "fixture",
    }


def test_export_delete_originals_and_core_only_reaudit(experiment_case, monkeypatch):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    execute(case, plan_id)
    original, options = inputs(case, authority_id)
    source_dirs = [case.root / name for name in ("data", "registry", "plans", "runs", "findings")]
    before = {str(path): tree(path) for path in source_dirs}
    destination = case.root / "exported"

    def publisher(artifacts):
        export_search_evidence_bundle(destination, artifacts)
        return read_search_evidence_bundle(destination)

    exported = export_search_evidence(authority_id, **options, publisher=publisher)
    assert exported["report"] == original["report"]
    assert exported["report_id"] == original["report_id"]
    assert exported["finalization_status"] == "FINAL"
    assert {str(path): tree(path) for path in source_dirs} == before
    moved = case.root / "relocated"
    destination.rename(moved)
    for path in source_dirs:
        shutil.rmtree(path)
    for store in (
        LocalDatasetStore,
        LocalAttemptLedger,
        LocalCampaignBudgetStore,
        LocalSearchCampaignStore,
        LocalSearchFindingRegistry,
        LocalSearchPlanRegistry,
    ):
        monkeypatch.setattr(store, "__init__", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    verified = verify_search_package(
        read_search_evidence_bundle(moved), expected_bundle_id=exported["bundle_id"]
    )
    assert verified == exported
    assert all(not path.exists() for path in source_dirs)


def test_wrong_report_pin_prevents_publication(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    execute(case, plan_id)
    _original, options = inputs(case, authority_id)
    options["expected_report_id"] = "0" * 64
    before = tree(case.root)
    with pytest.raises(EvidenceValidationError, match="expected-report-id"):
        export_search_evidence(authority_id, **options, publisher=forbidden)
    assert tree(case.root) == before


def test_publisher_cannot_substitute_a_different_payload(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    execute(case, plan_id)
    _original, options = inputs(case, authority_id)
    with pytest.raises(EvidenceValidationError, match="publisher returned different"):
        export_search_evidence(
            authority_id, **options, publisher=lambda _: SimpleNamespace(artifacts={})
        )


def test_collection_limit_stops_before_publication_and_preserves_originals(
    experiment_case, monkeypatch
):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    execute(case, plan_id)
    _original, options = inputs(case, authority_id)
    before = tree(case.root)
    monkeypatch.setattr("tickwitness.application.search_evidence.MAX_TOTAL_BYTES", 1)
    with pytest.raises(EvidenceValidationError, match="export profile"):
        export_search_evidence(authority_id, **options, publisher=forbidden)
    assert tree(case.root) == before


def test_no_inner_campaign_does_not_open_a_ledger(experiment_case):
    case = experiment_case
    plan_id, authority_id = prepare(case)
    run_bounded_search_campaign(
        plan_id,
        canonical(
            {
                "kind": "campaign_budget_request_v1",
                "schema_version": 1,
                "max_evaluations": 1,
                "max_wall_time_ms": 1,
                "max_storage_bytes": 32 * 1024 * 1024,
            }
        ),
        split="development",
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans"),
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        budgets_factory=lambda: LocalCampaignBudgetStore(case.root / "runs", create=True),
        execution_inspector=lambda: None,
        supervise=lambda _: SimpleNamespace(
            reason="time_limit", exit_code=8, elapsed_ns=1_000_000, stdout=b"", stderr=b""
        ),
        nonce_factory=lambda: "a" * 32,
    )
    original, options = inputs(case, authority_id)
    options["ledger_factory"] = forbidden
    assert original["report"]["outcome"] == "NOT_EVALUABLE"
    payload = collect_search_artifacts(authority_id, **options)
    assert not any(role.startswith(("reservation/", "attempt/", "cas/")) for role in payload)
    assert not (case.root / "runs" / "slots").exists()


def test_confirmation_rejected_before_factories_or_identity():
    with pytest.raises(ConfirmationAccessDenied):
        collect_search_artifacts(
            "invalid",
            expected_report_id="invalid",
            split="confirmation",
            findings_factory=forbidden,
            datasets_factory=forbidden,
            budgets_factory=forbidden,
            campaigns_factory=forbidden,
            ledger_factory=forbidden,
            campaign_inspector=forbidden,
            producer_version="fixture",
        )
    with pytest.raises(ConfirmationAccessDenied):
        verify_search_package(SimpleNamespace(), expected_bundle_id="invalid", split="confirmation")
