"""Read-only association and re-audit of committed baseline/intervention runs."""

from collections.abc import Callable
from typing import cast

from tickwitness.application.experiments import (
    DatasetEvidenceReader,
    ExecutableReader,
    run_artifacts,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.scenario_execution import ScenarioLedger, scenario_run_evidence
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    identity,
    load_run_receipt,
)
from tickwitness.domain.evidence.scenario_comparison import ScenarioComparison
from tickwitness.domain.evidence.scenario_records import load_scenario_run_receipt
from tickwitness.domain.replay.contracts import load_replay_result
from tickwitness.domain.research_contracts.executable import load_executable_protocol


def compare_scenario_runs(
    baseline_run_id: str,
    scenario_run_id: str,
    *,
    split: str,
    ledger_factory: Callable[[], ScenarioLedger],
    registry_factory: Callable[[], ExecutableReader],
    datasets_factory: Callable[[], DatasetEvidenceReader],
) -> ScenarioComparison:
    """Audit two existing outcomes without an engine, writes or attempt reservation."""
    if split != "development":
        raise ConfirmationAccessDenied("Scenario comparisons permit development evidence only")
    identity(baseline_run_id)
    identity(scenario_run_id)
    if baseline_run_id == scenario_run_id:
        raise EvidenceValidationError("A baseline and scenario must reference different runs")
    ledger = ledger_factory()
    baseline = load_run_receipt(ledger.read_artifact(baseline_run_id, max_bytes=16_384))
    scenario = load_scenario_run_receipt(ledger.read_artifact(scenario_run_id, max_bytes=16_384))
    if baseline.run_id != baseline_run_id or scenario.run_id != scenario_run_id:
        raise EvidenceValidationError("Comparison run identity differs from requested evidence")
    left, right = baseline.document, scenario.document
    baseline_bindings = cast("dict[str, str]", left["bindings"])
    intent = cast("dict[str, object]", right["intent"])
    source_bindings = cast("dict[str, str]", intent["bindings"])
    if (
        left["protocol_id"] != right["protocol_id"]
        or left["claim_revision_id"] != right["claim_revision_id"]
        or baseline_bindings["dataset_id"] != source_bindings["development_dataset_id"]
        or baseline_bindings["data_sha256"] != source_bindings["source_normalized_sha256"]
        or baseline_bindings["replay_spec_id"] != source_bindings["replay_spec_id"]
    ):
        raise EvidenceValidationError("Runs do not share the declared development baseline")
    registry, datasets = registry_factory(), datasets_factory()
    artifacts = run_artifacts(baseline_run_id, ledger=ledger, registry=registry, datasets=datasets)
    checked = scenario_run_evidence(
        scenario_run_id, ledger=ledger, registry=registry, datasets=datasets
    )
    protocol = load_executable_protocol(artifacts["protocol"])
    if protocol.canonical_bytes != checked.view.validated.protocol.canonical_bytes:
        raise EvidenceValidationError("Comparison protocol evidence changed between reads")
    if artifacts["normalized"] != checked.view.validated.replay_input.normalized_bytes:
        raise EvidenceValidationError("Comparison source evidence changed between reads")
    if artifacts["attempt"] != baseline.canonical_bytes or checked.receipt != scenario:
        raise EvidenceValidationError("Comparison outcomes changed between reads")
    return ScenarioComparison(
        protocol,
        checked.view.validated.replay_input,
        checked.view,
        baseline,
        checked.receipt,
        load_replay_result(artifacts["replay_result"]),
        checked.result,
    )
