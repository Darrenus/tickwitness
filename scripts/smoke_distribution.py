#!/usr/bin/env python3
"""Exercise an installed wheel from a separate directory using only stdlib."""

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, type=Path)
    arguments = parser.parse_args()
    # Keep the venv executable path: resolving its symlink would select base Python.
    interpreter = str(arguments.python.absolute())
    with TemporaryDirectory(prefix="tickwitness-installed-") as temporary:
        directory = Path(temporary)
        sample = {
            "schema_version": 1,
            "type": "snapshot",
            "source": "synthetic",
            "instrument": "WHEEL-USD",
            "session": "wheel-smoke",
            "capture_seq": 1,
            "event_time_ns": 100,
            "receive_time_ns": None,
            "last_sequence": 10,
            "bids": [[99, 5]],
            "asks": [[101, 5]],
        }
        development = [
            sample,
            {
                **sample,
                "type": "delta",
                "capture_seq": 2,
                "event_time_ns": 110,
                "receive_time_ns": 115,
                "first_sequence": 11,
                "last_sequence": 11,
                "bids": [[99, 6]],
                "asks": [],
            },
        ]
        confirmation = {
            **sample,
            "capture_seq": 3,
            "event_time_ns": 200,
            "receive_time_ns": 205,
            "last_sequence": 20,
            "bids": [[98, 5]],
            "asks": [[102, 5]],
        }
        (directory / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in development), encoding="utf-8"
        )
        (directory / "confirmation.jsonl").write_text(
            json.dumps(confirmation) + "\n", encoding="utf-8"
        )
        store = directory / "store"

        def run(*command: str, expected: int = 0) -> dict[str, object]:
            result = subprocess.run(
                [interpreter, "-I", "-m", "tickwitness", *command],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != expected:
                raise RuntimeError(f"Installed CLI failed: {result.stdout}\n{result.stderr}")
            return json.loads(result.stdout if expected == 0 else result.stderr)

        command = (
            "import-events",
            "events.jsonl",
            "--input-root",
            str(directory),
            "--store",
            str(store),
        )
        first = run(*command)
        repeated = run(*command)
        assert first["created"] is True
        assert repeated["created"] is False
        assert first["dataset_id"] == repeated["dataset_id"]
        identity = str(first["dataset_id"])
        inspected = run("inspect-dataset", identity, "--store", str(store))
        assert inspected["report"] == first["report"]
        assert inspected["report"]["unknown_receive_count"] == 1
        assert inspected["report"]["replay_certified"] is False

        confirmed = run(
            "import-events",
            "confirmation.jsonl",
            "--input-root",
            str(directory),
            "--store",
            str(store),
        )
        confirmation_id = str(confirmed["dataset_id"])
        assert confirmation_id != identity
        request = {
            "schema_version": 1,
            "claim": {
                "title": "Installed wheel synthetic declaration",
                "hypothesis": "Under the declared model synthetic net marked PnL exceeds zero.",
                "metric": "net_marked_pnl_v1",
                "comparator": "gt",
                "threshold": "-000.000",
                "unit": "synthetic_quote_units",
            },
            "strategy_name": "wheel_smoke_v1",
            "parameters": {"size_lots": 1, "post_only": True, "optional": None},
            "configuration": {
                "fee_model_id": "declared_fee_demo_v1",
                "execution_model_id": "declared_execution_demo_v1",
                "clock_policy_id": "capture_order_unbound_v1",
            },
            "budget": {"max_scenarios": 10, "max_wall_seconds": 60, "max_events": 1000},
            "seed": 42,
        }
        (directory / "request.json").write_text(json.dumps(request), encoding="utf-8")
        # Parsing/binding this source must never execute it during freezing or reading.
        (directory / "strategy.py").write_text(
            "raise RuntimeError('wheel smoke source must not execute')\n", encoding="utf-8"
        )
        registry = directory / "registry"
        freeze_command = (
            "freeze-protocol",
            "request.json",
            "--input-root",
            str(directory),
            "--strategy-source",
            "strategy.py",
            "--development-dataset",
            identity,
            "--confirmation-dataset",
            confirmation_id,
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        frozen = run(*freeze_command)
        repeated_protocol = run(*freeze_command)
        assert frozen["created"] is True
        assert repeated_protocol["created"] is False
        assert repeated_protocol["protocol_id"] == frozen["protocol_id"]
        protocol_id = str(frozen["protocol_id"])
        assert frozen["document"]["execution_ready"] is False
        assert frozen["document"]["read_policy"] == "development_only_v1"
        assert frozen["document"]["claim"]["threshold"] == "0"
        assert frozen["document"]["datasets"] == {
            "development": identity,
            "confirmation": confirmation_id,
        }
        protocol = run(
            "inspect-protocol",
            protocol_id,
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        assert protocol["document"] == frozen["document"]
        assert protocol["created"] is False
        observations = run(
            "read-protocol-data",
            protocol_id,
            "--split",
            "development",
            "--limit",
            "1",
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        assert observations["dataset_id"] == identity
        assert observations["observations"] == [sample]
        assert observations["total_records"] == 2
        assert observations["truncated"] is True
        missing_store = directory / "must-remain-absent" / "store"
        missing_registry = directory / "must-remain-absent" / "registry"
        denied = run(
            "read-protocol-data",
            protocol_id,
            "--split",
            "confirmation",
            "--limit",
            "1",
            "--store",
            str(missing_store),
            "--registry",
            str(missing_registry),
            expected=5,
        )
        assert denied["error"]["code"] == "confirmation_access_denied"
        assert not missing_store.parent.exists()

        raw_reference = first["manifest"]["objects"]["raw"]["ref"]
        (store / raw_reference).write_bytes(b"tampered")
        failure = run("inspect-dataset", identity, "--store", str(store), expected=3)
        assert failure["error"]["code"] == "store_integrity_or_publication_failure"
    print(
        "Installed wheel: data import/inspect, protocol freeze/inspect/development read, "
        "idempotency, confirmation denial, unknown-time and tamper checks passed."
    )


if __name__ == "__main__":
    main()
