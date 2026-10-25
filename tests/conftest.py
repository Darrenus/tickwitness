"""Native-free valid replay receipts for boundary-failure tests."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result


@pytest.fixture
def replay_result_factory():
    def make(request: ReplayInput, **changes: object):
        records = [json.loads(line) for line in request.normalized_bytes.splitlines()]
        document = {
            "kind": "replay_qualification_result_v1",
            "schema_version": 1,
            "engine": {
                "id": "nautilus-trader",
                "version": "1.231.0",
                "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1",
            },
            "environment": {
                "python_version": "fixture",
                "platform": "fixture",
                "package_versions": {"nautilus-trader": "1.231.0"},
            },
            "dataset_id": request.dataset_id,
            "data_sha256": hashlib.sha256(request.normalized_bytes).hexdigest(),
            "spec_id": request.spec.spec_id,
            "execution_status": "completed",
            "completeness": {
                "input_records": len(records),
                "processed_records": len(records),
                "open_orders": [],
                "pending_commands": [],
                "stop_reason": "input_exhausted",
            },
            "input_trace": [
                {
                    "kind": "fixture_input",
                    "ordinal": index,
                    "native_time_ns": record["receive_time_ns"],
                    "source_ref": {
                        "line": index + 1,
                        "capture_seq": record["capture_seq"],
                        "event_type": record["type"],
                    },
                    "fields": {},
                }
                for index, record in enumerate(records)
            ],
            "decision_trace": [],
            "order_trace": [],
            "fill_trace": [],
            "account_trace": [],
        }
        document.update(changes)
        return build_replay_result(document)

    return make


@pytest.fixture
def experiment_case(tmp_path: Path):
    """A genuine saved native fixture, never a product fake-engine switch."""
    from tickwitness.application.datasets import import_events
    from tickwitness.application.experiments import freeze_experiment
    from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
    from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
    from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore

    fixture = Path(__file__).parent / "fixtures"
    raw = (fixture / "evidence-events.jsonl").read_bytes()
    spec = json.loads((fixture / "evidence-replay-spec.json").read_bytes())
    golden = json.loads((fixture / "evidence-result.json").read_bytes())
    data = LocalDatasetStore(tmp_path / "data")
    development = import_events(raw, lambda: data).dataset_id
    snapshot = json.loads(raw.splitlines()[0])
    snapshot.update(
        capture_seq=100,
        last_sequence=100,
        event_time_ns=1700000010000000000,
        receive_time_ns=1700000010000000100,
        bids=[[101, 5], [100, 10]],
        asks=[[104, 10], [105, 10]],
    )
    confirmation = import_events((json.dumps(snapshot) + "\n").encode(), lambda: data).dataset_id
    request = {
        "schema_version": 2,
        "claim": {
            "title": "Saved native fixture",
            "hypothesis": "Net marked value exceeds minus three USD under the declared model",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "-3",
            "unit": "USD",
        },
        "replay_spec": spec,
        "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 100},
    }
    registry = LocalExecutableProtocolRegistry(tmp_path / "registry")
    frozen = freeze_experiment(
        json.dumps(request).encode(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        datasets_factory=lambda: data,
        registry_factory=lambda: registry,
    )

    class FixtureEngine:
        def run(self, replay_input: ReplayInput):
            assert (
                hashlib.sha256(replay_input.normalized_bytes).hexdigest() == golden["data_sha256"]
            )
            assert replay_input.spec.spec_id == golden["spec_id"]
            result = dict(golden, dataset_id=replay_input.dataset_id)
            return build_replay_result(result)

    return SimpleNamespace(
        root=tmp_path,
        data=data,
        registry=registry,
        frozen=frozen,
        development=development,
        confirmation=confirmation,
        request=request,
        raw=raw,
        spec=spec,
        ledger_factory=lambda: LocalAttemptLedger(tmp_path / "runs"),
        engine_factory=lambda timeout: FixtureEngine(),
    )
