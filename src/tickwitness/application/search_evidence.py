"""Collect and publish complete local search snapshots without executing a trial."""

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Protocol, cast

from tickwitness.application.bounded_search import BudgetReader
from tickwitness.application.experiments import DatasetEvidenceReader
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_evidence_verification import (
    inspect_search_artifacts,
    verify_search_artifacts,
)
from tickwitness.application.search_execution import CampaignReader, SearchLedger
from tickwitness.application.search_findings import SearchFindingReader, evaluate_search_findings
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    identity,
    parse,
)
from tickwitness.domain.evidence.scenario_records import load_scenario_intent
from tickwitness.domain.evidence.search_evidence import MAX_FILES, MAX_TOTAL_BYTES, role_limit
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import load_search_finding_protocol
from tickwitness.domain.search.budgets import load_allocation, load_campaign_budget

type Row = dict[str, object]


class _CollectedArtifacts(dict[str, bytes]):
    """Stop collection before accumulating a whole unsupported multi-gigabyte run."""

    def __init__(self) -> None:
        super().__init__()
        self._sizes: dict[str, int] = {}
        self._total = 0

    def __setitem__(self, role: str, raw: bytes) -> None:
        if type(raw) is not bytes or not 0 < len(raw) <= role_limit(role):
            raise EvidenceValidationError("Search evidence role exceeds its byte limit: " + role)
        if role in self:
            if self[role] != raw:
                raise EvidenceValidationError("Search evidence role changed during collection: " + role)
            return
        sha = digest(raw)
        if sha not in self._sizes:
            if self._total + len(raw) > MAX_TOTAL_BYTES or len(self._sizes) + 2 > MAX_FILES:
                raise EvidenceValidationError("Search evidence exceeds its complete export profile")
            self._sizes[sha] = len(raw)
            self._total += len(raw)
        super().__setitem__(role, raw)


class SearchEvidencePackage(Protocol):
    @property
    def bundle_id(self) -> str: ...
    @property
    def manifest_bytes(self) -> bytes: ...
    @property
    def artifacts(self) -> dict[str, bytes]: ...


def _development(split: str) -> None:
    if split != "development":
        raise ConfirmationAccessDenied("Search evidence permits development artifacts only")


def verify_search_package(
    package: SearchEvidencePackage,
    *,
    expected_bundle_id: str | None = None,
    split: str = "development",
) -> Row:
    """Re-establish source, execution and findings from a complete immutable package."""
    _development(split)
    bundle_id = identity(package.bundle_id)
    if expected_bundle_id is not None and identity(expected_bundle_id) != bundle_id:
        raise EvidenceValidationError("Search bundle differs from the expected pinned identity")
    artifacts = package.artifacts
    expected = canonical({
        "kind": "search_evidence_bundle_v1",
        "schema_version": 1,
        "scope": "development_scoped_search_evidence_v1",
        "roles": {
            role: {"sha256": digest(raw), "size_bytes": len(raw),
                   "ref": "objects/sha256/" + digest(raw)}
            for role, raw in artifacts.items()
        },
    })
    if type(package.manifest_bytes) is not bytes or package.manifest_bytes != expected or digest(expected) != bundle_id:
        raise EvidenceValidationError("Search manifest differs from its exact content closure")
    return {**verify_search_artifacts(artifacts), "bundle_id": bundle_id}


def collect_search_artifacts(
    finding_protocol_id: str,
    *,
    expected_report_id: str,
    split: str,
    findings_factory: Callable[[], SearchFindingReader],
    datasets_factory: Callable[[], DatasetEvidenceReader],
    budgets_factory: Callable[[], BudgetReader],
    campaigns_factory: Callable[[str], CampaignReader | None],
    ledger_factory: Callable[[], SearchLedger],
    campaign_inspector: Callable[[str], Row],
    producer_version: str,
) -> dict[str, bytes]:
    """Collect actual committed bytes, including explicit observed absences.

    The original ledger is not opened when no inner campaign exists. A sealed
    prefix is an observed content snapshot, not authentic stop-time trial history.
    """
    _development(split)
    identity(finding_protocol_id)
    identity(expected_report_id)
    reader = findings_factory()
    authority = load_search_finding_protocol(reader.get(finding_protocol_id).canonical_bytes)
    if authority.protocol_id != finding_protocol_id:
        raise EvidenceValidationError("Search evidence authority differs from the requested ID")

    def current() -> Row:
        return evaluate_search_findings(
            finding_protocol_id, split=split, findings_factory=findings_factory,
            campaign_inspector=campaign_inspector,
        )

    before = current()
    if before["report_id"] != expected_report_id:
        raise EvidenceValidationError("Current search report differs from expected-report-id")
    plan = authority.plan
    protocol = load_executable_protocol(canonical(cast("Row", plan.document["protocol"])))
    dataset_id = cast("dict[str, str]", protocol.document["datasets"])["development"]
    source = datasets_factory().read_artifacts(dataset_id)
    if set(source) != {"dataset_manifest", "raw", "normalized", "report"}:
        raise EvidenceValidationError("Development dataset requires its exact four-object closure")
    payload = _CollectedArtifacts()
    for role, raw in source.items():
        payload[role] = raw
    payload["finding_protocol"] = authority.canonical_bytes
    payload["finding_report"] = canonical(cast("Row", before["report"]))
    budgets = budgets_factory()
    budget_raw = budgets.get_budget(plan.plan_id)
    if budget_raw is None:
        raise EvidenceValidationError("Missing committed search budget")
    budget = load_campaign_budget(budget_raw)
    payload["budget"] = budget_raw
    allocations = budgets.get_allocations(plan.plan_id)
    allocation_ordinals: list[int] = []
    for raw in allocations:
        allocation = load_allocation(raw, budget=budget)
        ordinal = cast("int", allocation["ordinal"])
        allocation_ordinals.append(ordinal)
        payload[f"allocation/{ordinal:04}"] = raw
    outer_stop = budgets.get_stop(plan.plan_id)
    if outer_stop is not None:
        payload["outer_stop"] = outer_stop
    store = campaigns_factory(plan.plan_id)
    campaign = None if store is None else store.get_campaign(plan.plan_id)
    inner_stop: bytes | None = None
    if campaign is not None:
        payload["campaign"] = campaign
        assert store is not None
        inner_stop = store.get_stop(plan.plan_id)
        if inner_stop is not None:
            payload["inner_stop"] = inner_stop
    candidates: list[Row] = []
    nonces: set[str] = set()
    for proposal in cast("list[Row]", plan.document["journal"]):
        if proposal["status"] != "ELIGIBLE":
            continue
        ordinal = cast("int", proposal["ordinal"])
        row: Row = {"ordinal": ordinal}
        for field in ("dispatch", "link", "result"):
            raw = None
            if campaign is not None:
                assert store is not None
                if field == "dispatch":
                    raw = store.get_dispatch(plan.plan_id, ordinal)
                elif field == "link":
                    raw = store.get_link(plan.plan_id, ordinal)
                else:
                    raw = store.get_result(plan.plan_id, ordinal)
            row[field] = raw is not None
            if raw is not None:
                payload[f"candidate/{ordinal:04}/{field}"] = raw
                if field == "dispatch":
                    nonces.add(cast("str", parse(raw, limit=64 * 1024)["reservation_nonce"]))
        candidates.append(row)
    reservations: list[Row] = []
    attempts: list[Row] = []
    cas: set[str] = set()
    if campaign is not None:
        ledger = ledger_factory()

        def add_cas(sha: str, limit: int, referenced_by: str) -> None:
            identity(sha)
            try:
                raw = ledger.read_artifact(sha, max_bytes=limit)
            except ValueError as error:
                raise EvidenceValidationError(
                    f"Cannot collect cas/{sha} referenced by {referenced_by}: {error}"
                ) from error
            if digest(raw) != sha:
                raise EvidenceValidationError(f"Source cas/{sha} identity differs")
            payload["cas/" + sha] = raw
            cas.add(sha)

        for reservation in ledger.list_reservations(protocol):
            actual = ledger.get_reservation(reservation.attempt_id)
            if actual != reservation:
                raise EvidenceValidationError("Original reservation changed during collection")
            index, attempt_id = reservation.attempt_index, reservation.attempt_id
            reservations.append({"index": index, "attempt_id": attempt_id})
            payload[f"reservation/{index:04}"] = reservation.canonical_bytes
            add_cas(attempt_id, 16 * 1024, f"reservation/{index:04}")
            if reservation.document["nonce"] not in nonces:
                continue
            intent = ledger.get_intent(attempt_id)
            outcome = ledger.get_outcome(attempt_id)
            attempts.append({"attempt_id": attempt_id, "intent": intent is not None,
                             "outcome": outcome is not None})
            for field, raw in (("intent", intent), ("outcome", outcome)):
                if raw is not None:
                    role = f"attempt/{attempt_id}/{field}"
                    payload[role] = raw
                    add_cas(digest(raw), 16 * 1024, role)
            if intent is not None:
                bindings = cast("dict[str, str]", load_scenario_intent(intent).document["bindings"])
                for field in ("assumption_id", "scenario_id", "derived_view_id", "derived_normalized_sha256"):
                    add_cas(bindings[field], 8 * 1024 * 1024 if field == "derived_normalized_sha256" else 64 * 1024, "attempt/" + attempt_id + "/intent")
            if outcome is not None:
                document = parse(outcome)
                if document["kind"] == "scenario_run_receipt_v1":
                    refs = cast("dict[str, str]", document["bindings"])
                    add_cas(refs["replay_result_sha256"], 16 * 1024 * 1024, "attempt/" + attempt_id + "/outcome")
                    add_cas(refs["evaluation_sha256"], 4 * 1024 * 1024, "attempt/" + attempt_id + "/outcome")
    payload["snapshot"] = canonical({
        "kind": "search_evidence_snapshot_v1", "schema_version": 1,
        "finding_protocol_id": finding_protocol_id, "plan_id": plan.plan_id,
        "protocol_id": protocol.protocol_id, "dataset_id": dataset_id,
        "budget_id": budget.budget_id, "producer_version": producer_version,
        "allocations": allocation_ordinals, "outer_stop": outer_stop is not None,
        "inner_campaign": campaign is not None, "inner_stop": inner_stop is not None,
        "ledger_prefix_observed": campaign is not None,
        "reservations": reservations, "candidates": candidates,
        "attempts": attempts, "cas": sorted(cas),
    })
    _bounded, rebuilt, diagnostics = inspect_search_artifacts(payload)
    if rebuilt["report_id"] != expected_report_id or canonical(cast("Row", rebuilt["report"])) != payload["finding_report"]:
        raise EvidenceValidationError("Collected evidence differs from the pinned search report")
    payload["diagnostics"] = canonical(diagnostics)
    verified = verify_search_artifacts(payload)
    if verified["report_id"] != expected_report_id or current()["report_id"] != expected_report_id:
        raise EvidenceValidationError("Search source changed while evidence was collected; retry")
    return dict(payload)


def export_search_evidence(
    finding_protocol_id: str,
    *,
    expected_report_id: str,
    split: str,
    findings_factory: Callable[[], SearchFindingReader],
    datasets_factory: Callable[[], DatasetEvidenceReader],
    budgets_factory: Callable[[], BudgetReader],
    campaigns_factory: Callable[[str], CampaignReader | None],
    ledger_factory: Callable[[], SearchLedger],
    campaign_inspector: Callable[[str], Row],
    producer_version: str,
    publisher: Callable[[Mapping[str, bytes]], SearchEvidencePackage],
) -> Row:
    payload = collect_search_artifacts(
        finding_protocol_id, expected_report_id=expected_report_id, split=split,
        findings_factory=findings_factory, datasets_factory=datasets_factory,
        budgets_factory=budgets_factory, campaigns_factory=campaigns_factory,
        ledger_factory=ledger_factory, campaign_inspector=campaign_inspector,
        producer_version=producer_version,
    )
    published = publisher(MappingProxyType(dict(payload)))
    if published.artifacts != payload:
        raise EvidenceValidationError("Search publisher returned different evidence")
    receipt = verify_search_package(published, split=split)
    if receipt["report_id"] != expected_report_id:
        raise EvidenceValidationError("Published search evidence differs from the requested report")
    return receipt
