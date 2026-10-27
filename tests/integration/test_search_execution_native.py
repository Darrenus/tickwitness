"""A real native EOF stops a campaign without dispatching or replaying its suffix."""

import json
import secrets
from importlib import metadata
from pathlib import Path

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment
from tickwitness.application.search_execution import inspect_search_campaign, run_search_plan
from tickwitness.application.search_planning import freeze_search_plan
from tickwitness.domain.evidence.run_records import digest
from tickwitness.domain.evidence.scenario_records import load_scenario_run_receipt
from tickwitness.domain.replay.contracts import load_replay_result
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
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


def test_real_pending_submit_eof_stops_campaign_and_repeat_only_reaudits(
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
                    "title": "Sequential synthetic pending-submit EOF",
                    "hypothesis": "The original marked baseline exceeds zero.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "0",
                    "unit": "USD",
                },
                "replay_spec": json.loads((EXAMPLES / "replay-eof-spec.json").read_bytes()),
                "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 10},
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
    search_request = json.dumps(
        {
            "kind": "search_plan_request_v1",
            "schema_version": 1,
            "search_seed": 17,
            "max_proposals": 2,
            "generator": {"kind": "grid", "values_ns": [0, 1]},
        }
    ).encode()
    plans = LocalSearchPlanRegistry(tmp_path / "plans", create=True)
    plan = freeze_search_plan(
        frozen.protocol_id,
        assumption,
        search_request,
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        plans_factory=lambda: plans,
    )
    ledger = LocalAttemptLedger(tmp_path / "runs")
    campaigns = LocalSearchCampaignStore(tmp_path / "runs", create=True)
    calls = []

    def engine(timeout):
        reservations = ledger.list_reservations(
            load_executable_protocol(registry.get(frozen.protocol_id).canonical_bytes)
        )
        assert len(reservations) == 1
        attempt = reservations[0]
        assert campaigns.get_dispatch(plan["plan_id"], 1) is not None
        assert campaigns.get_link(plan["plan_id"], 1) is not None
        assert ledger.get_intent(attempt.attempt_id) is not None
        assert ledger.get_outcome(attempt.attempt_id) is None
        calls.append(attempt.attempt_id)
        return SubprocessReplayAdapter(timeout_seconds=timeout)

    report = run_search_plan(
        plan["plan_id"],
        split="development",
        plans_factory=lambda: plans,
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        ledger_factory=lambda: ledger,
        ledger_reader_factory=lambda: LocalAttemptLedger(tmp_path / "runs", create=False),
        campaigns_factory=lambda: campaigns,
        engine_factory=engine,
        nonce_factory=lambda: secrets.token_hex(16),
    )
    assert report["status"] == "stopped"
    assert report["stop_reason"] == "candidate_incomplete"
    assert report["exit_code"] == 7
    assert report["counts"] == {
        "eligible": 2,
        "dispatched": 1,
        "reserved": 1,
        "completed": 0,
        "failed": 0,
        "incomplete": 1,
        "unfinalized": 0,
    }
    first, second = report["candidates"]
    assert first["status"] == "INCOMPLETE"
    assert first["attempt_index"] == 1
    assert first["budget_consumed"] is True
    assert first["reservation_link_present"] is True
    assert first["raw_result_audited"] is True
    assert first["evaluation"]["metric_observation"] == {
        "metric": "net_marked_pnl_v1", "unit": "USD", "eligible": False, "value": None,
    }
    assert "claim_observation" not in first["evaluation"]
    assert first["evaluation"]["scope"]["search_performed"] is False
    assert first["evaluation"]["scope"]["baseline_claim_evaluated"] is False
    assert second["status"] == "NOT_DISPATCHED"
    assert second["attempt_id"] is None
    assert second["budget_consumed"] is False
    assert campaigns.get_dispatch(plan["plan_id"], 2) is None
    assert campaigns.get_link(plan["plan_id"], 2) is None
    assert campaigns.get_result(plan["plan_id"], 2) is None
    assert report["scope"]["claim_evaluated"] is False
    assert report["scope"]["finding_issued"] is False
    assert calls == [first["attempt_id"]]

    receipt = load_scenario_run_receipt(ledger.get_outcome(first["attempt_id"]))
    assert receipt.run_id == first["run_id"] == first["outcome_id"]
    result_bytes = ledger.read_artifact(receipt.document["bindings"]["replay_result_sha256"])
    assert campaigns.get_result(plan["plan_id"], 1) == result_bytes
    result = load_replay_result(result_bytes).document
    assert result["execution_status"] == "incomplete"
    assert result["completeness"]["processed_records"] == 2
    assert result["completeness"]["stop_reason"] == "pending_commands_at_data_end"
    assert result["completeness"]["pending_commands"][0]["command_type"] == "submit"
    assert result["completeness"]["pending_commands"][0]["source_ref"]["capture_seq"] == 2
    assert result["completeness"]["open_orders"][0]["status"] == "SUBMITTED"
    assert result["fill_trace"] == []
    assert result["account_trace"][-1]["native_time_ns"] == 1_700_000_003_000_000_000
    assert result["data_sha256"] == digest(source)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Existing campaign must only inspect, never reserve or replay")

    monkeypatch.setattr(LocalAttemptLedger, "reserve_with_nonce", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file()
    }
    repeated = run_search_plan(
        plan["plan_id"],
        split="development",
        plans_factory=lambda: plans,
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        ledger_factory=lambda: ledger,
        ledger_reader_factory=lambda: LocalAttemptLedger(tmp_path / "runs", create=False),
        campaigns_factory=lambda: campaigns,
        engine_factory=forbidden,
        nonce_factory=forbidden,
    )
    inspected = inspect_search_campaign(
        plan["plan_id"],
        split="development",
        plans_factory=lambda: plans,
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        ledger_factory=lambda: LocalAttemptLedger(tmp_path / "runs", create=False),
        campaigns_factory=lambda: LocalSearchCampaignStore(tmp_path / "runs", create=False),
    )
    assert repeated == inspected == report
    assert inspected["verification"]["native_replayed"] is False
    assert inspected["verification"]["outcomes_reaudited"] is True
    assert len(ledger.list_reservations(
        load_executable_protocol(registry.get(frozen.protocol_id).canonical_bytes)
    )) == 1
    assert {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file()
    } == before
    assert data.read_normalized(development) == source
