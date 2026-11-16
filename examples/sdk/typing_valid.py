"""Static-only downstream compatibility examples; never execute these requests."""

from pathlib import Path
from typing import assert_type

from tickwitness.sdk import (
    SDK_CONTRACT_VERSION,
    Client,
    DevelopmentRead,
    ImportReceipt,
    ProtocolReceipt,
    SDKError,
    ValidationLimits,
)


def supported(client: Client, input_root: Path, identity: str) -> None:
    assert_type(SDK_CONTRACT_VERSION, int)
    assert_type(
        client.import_events("development.jsonl", input_root=input_root), ImportReceipt
    )
    assert_type(
        client.import_events(
            "development.jsonl", input_root=input_root, limits=ValidationLimits(max_records=2)
        ),
        ImportReceipt,
    )
    assert_type(client.inspect_dataset(identity), ImportReceipt)
    assert_type(
        client.freeze_protocol(
            "request.json",
            input_root=input_root,
            strategy_source="strategy.py",
            development_dataset_id=identity,
            confirmation_dataset_id=identity,
        ),
        ProtocolReceipt,
    )
    assert_type(client.inspect_protocol(identity), ProtocolReceipt)
    assert_type(client.read_protocol_data(identity), DevelopmentRead)
    assert_type(client.read_protocol_data(identity, split="development", limit=2), DevelopmentRead)
    assert_type(client.read_protocol_data(identity, split="confirmation"), DevelopmentRead)
    error = SDKError("example", "diagnostic", 2)
    assert_type(error.code, str)
    assert_type(error.exit_code, int)
    assert_type(error.as_dict(), dict[str, object])
