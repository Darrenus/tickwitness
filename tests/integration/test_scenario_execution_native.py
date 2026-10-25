"""Real supervised native EOF remains incomplete through durable scenario inspection."""

import json
from importlib import metadata
from pathlib import Path

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment
from tickwitness.application.scenario_execution import inspect_scenario_run, run_scenario
from tickwitness.domain.evidence.run_records import digest
from tickwitness.domain.evidence.scenario_records import load_scenario_run_receipt
from tickwitness.domain.replay.contracts import load_replay_result
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _pinned_native_installed() -> bool:
    try:
        return metadata.version("nautilus_trader") == "1.231.0"
    except metadata.PackageNotFoundError:
        return False


pytestmark = pytest.mark.skipif(
    not _pinned_native_installed(), reason="optional pinned Nautilus extra absent"
)


def test_real_pending_submit_eof_does_not_become_a_valued_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(
        (EXAMPLES / "replay-eof-pending.jsonl").read_bytes(), lambda: data
    ).dataset_id
    confirmation = import_events(
        (EXAMPLES / "replay-confirmation.jsonl").read_bytes(), lambda: data
    ).dataset_id
    source = data.read_normalized(development)
    registry = LocalExecutableProtocolRegistry(tmp_path / "registry")
    frozen = freeze_experiment(
        json.dumps(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Synthetic pending-submit EOF",
                    "hypothesis": "The original marked baseline exceeds zero.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "0",
                    "unit": "USD",
                },
                "replay_spec": json.loads((EXAMPLES / "replay-eof-spec.json").read_bytes()),
                "budget": {"max_attempts": 1, "max_wall_seconds": 60, "max_events": 10},
            }
        ).encode(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        datasets_factory=lambda: data,
        registry_factory=lambda: registry,
    )
    assumption = json.dumps(
        {
            "kind": "assumption_request_v1",
            "schema_version": 1,
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "transform": {
                "semantic_id": "replay_receive_suffix_shift_v1",
                "from_capture_seq": 2,
            },
            "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
            "parameter_basis": {
                "kind": "researcher_defined",
                "calibration_status": "uncalibrated",
                "calibration_evidence_refs": [],
            },
        }
    ).encode()
    scenario = json.dumps(
        {
            "kind": "scenario_request_v1",
            "schema_version": 1,
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "additional_delay": {"value": 0, "unit": "ns"},
        }
    ).encode()
    ledger = LocalAttemptLedger(tmp_path / "runs")
    submission = run_scenario(
        frozen.protocol_id,
        assumption,
        scenario,
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        ledger_factory=lambda: ledger,
        engine_factory=lambda timeout: SubprocessReplayAdapter(timeout_seconds=timeout),
    )

    assert submission.execution_status == "incomplete"
    assert submission.evaluation["metric_observation"] == {
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "eligible": False,
        "value": None,
    }
    assert "claim_observation" not in submission.evaluation
    audited = submission.evaluation["replay_evaluation"]
    assert audited["execution_status"] == "incomplete"
    assert audited["valuation_status"] == "not_eligible"
    assert audited["ineligibility_reason"] == "execution_incomplete"
    assert audited["valuation"] is None
    receipt = load_scenario_run_receipt(ledger.read_artifact(submission.run_id))
    result = load_replay_result(
        ledger.read_artifact(receipt.document["bindings"]["replay_result_sha256"])
    ).document
    assert result["execution_status"] == "incomplete"
    assert result["completeness"]["processed_records"] == 2
    assert result["completeness"]["stop_reason"] == "pending_commands_at_data_end"
    assert result["completeness"]["pending_commands"][0]["command_type"] == "submit"
    assert result["completeness"]["pending_commands"][0]["source_ref"]["capture_seq"] == 2
    assert result["completeness"]["open_orders"][0]["status"] == "SUBMITTED"
    assert result["fill_trace"] == []
    assert result["account_trace"][-1]["native_time_ns"] == 1_700_000_003_000_000_000
    assert result["data_sha256"] == digest(source)
    assert result["dataset_id"] == submission.derived_view_id != development

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Inspection cannot rerun native or settle a pending command")

    monkeypatch.setattr(SubprocessReplayAdapter, "run", forbidden)
    inspected = inspect_scenario_run(
        submission.run_id, ledger=ledger, registry=registry, datasets=data
    )
    assert inspected["receipt"]["execution_status"] == "incomplete"
    assert inspected["evaluation"] == submission.evaluation
    assert inspected["verification"]["native_replayed"] is False
    assert inspected["verification"]["derivation_recomputed"] is True
    assert inspected["verification"]["accounting_verified"] is True
    assert data.read_normalized(development) == source
