"""Ingest a declaration's development observations through the public Python SDK.

Run against the shipped fixtures, with new owned absolute output roots. This
consumer neither executes the declared strategy nor evaluates its research claim.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import cast

from tickwitness.sdk import (
    SDK_CONTRACT_VERSION,
    Client,
    DevelopmentRead,
    SDKError,
)


def summarize(observations: DevelopmentRead) -> dict[str, object]:
    """Produce a downstream capture-order summary without inventing clocks."""
    return {
        "kind": "development_capture_summary_v1",
        "protocol_id": observations.protocol_id,
        "dataset_id": observations.dataset_id,
        "observed_records": len(observations.observations),
        "total_records": observations.total_records,
        "truncated": observations.truncated,
        "capture_sequences": [row["capture_seq"] for row in observations.observations],
        "unknown_receive_times": sum(
            row["receive_time_ns"] is None for row in observations.observations
        ),
        "research_claim_evaluated": False,
    }


def integrate(*, input_root: Path, store: Path, registry: Path) -> dict[str, object]:
    """Persist inputs and obtain a bounded, verified development projection."""
    client = Client(store=store, registry=registry)
    first = client.import_events("development.jsonl", input_root=input_root)
    confirmation = client.import_events("confirmation.jsonl", input_root=input_root)
    duplicate = client.import_events("development.jsonl", input_root=input_root)
    inspected = client.inspect_dataset(first.dataset_id)
    frozen = client.freeze_protocol(
        "request.json",
        input_root=input_root,
        strategy_source="strategy.py",
        development_dataset_id=first.dataset_id,
        confirmation_dataset_id=confirmation.dataset_id,
    )
    repeated_protocol = client.freeze_protocol(
        "request.json",
        input_root=input_root,
        strategy_source="strategy.py",
        development_dataset_id=first.dataset_id,
        confirmation_dataset_id=confirmation.dataset_id,
    )
    protocol = client.inspect_protocol(frozen.protocol_id)
    observations = client.read_protocol_data(frozen.protocol_id, limit=1)
    # An ordinary explicit duplicate publication closes any ordinary read-only
    # SQLite sidecars before this example hands its owned store to another tool.
    quiescence = client.import_events("development.jsonl", input_root=input_root)
    return {
        "sdk_contract_version": SDK_CONTRACT_VERSION,
        "dataset_first": cast("dict[str, object]", asdict(first)),
        "confirmation_first": cast("dict[str, object]", asdict(confirmation)),
        "dataset_repeated": cast("dict[str, object]", asdict(duplicate)),
        "dataset_inspected": cast("dict[str, object]", asdict(inspected)),
        "protocol_first": cast("dict[str, object]", asdict(frozen)),
        "protocol_repeated": cast("dict[str, object]", asdict(repeated_protocol)),
        "protocol_inspected": cast("dict[str, object]", asdict(protocol)),
        "development": cast("dict[str, object]", asdict(observations)),
        "summary": summarize(observations),
        "quiescence": cast("dict[str, object]", asdict(quiescence)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = integrate(
            input_root=arguments.input_root,
            store=arguments.store,
            registry=arguments.registry,
        )
    except SDKError as error:
        print(json.dumps(error.as_dict(), sort_keys=True), file=sys.stderr)
        return error.exit_code
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
