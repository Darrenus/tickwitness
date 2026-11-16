"""Static-only deliberate errors, checked by exact line/code; do not execute."""

from tickwitness.sdk import Client


def rejected(client: Client, identity: str) -> None:
    client.read_protocol_data(identity, limit="not-an-integer")  # expect-error: arg-type
    receipt: str = client.inspect_dataset(identity)  # expect-error: assignment
    client.run_job(identity)  # expect-error: attr-defined
    print(receipt)
