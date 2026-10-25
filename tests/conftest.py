"""Native-free valid replay receipts for boundary-failure tests."""

import hashlib
import json

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
