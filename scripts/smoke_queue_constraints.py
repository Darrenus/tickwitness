#!/usr/bin/env python3
"""Validate installed queue constraints without a native engine or research attempt."""

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-queue-constraints-") as temporary:
        directory = Path(temporary)
        store, registry = directory / "data", directory / "registry"

        def run(*command: str, expected: int = 0):
            result = subprocess.run(
                [interpreter, "-I", "-m", "tickwitness", *command],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if result.returncode != expected or (expected and result.stdout):
                raise RuntimeError(f"Installed queue CLI failed: {result.stdout}\n{result.stderr}")
            return json.loads(result.stdout if expected == 0 else result.stderr)

        ids = [
            run("import-events", name, "--input-root", str(examples), "--store", str(store))[
                "dataset_id"
            ]
            for name in ("queue-observations.jsonl", "replay-confirmation.jsonl")
        ]
        frozen = run(
            "freeze-experiment",
            "experiment-request.json",
            "--input-root",
            str(examples),
            "--development-dataset",
            ids[0],
            "--confirmation-dataset",
            ids[1],
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        before = {
            str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*")
            if path.is_file()
        }
        command = (
            "validate-queue-constraints",
            frozen["protocol_id"],
            "queue-constraint-request.json",
            "--input-root",
            str(examples),
            "--store",
            str(store),
            "--registry",
            str(registry),
        )
        receipt = run(*command)
        assert run(*command) == receipt
        validation = receipt["validation"]
        assert validation["classification"] == "MODEL_SENSITIVITY_CANDIDATE"
        for key in (
            "actual_acceptance_verified",
            "impact_compatibility_verified",
            "native_execution_verified",
            "execution_approved",
        ):
            assert validation[key] is False
        assert validation["source_bindings_verified"] is True
        assert validation["flow_conservation_verified"] is True
        assert validation["bindings"]["development_dataset_id"] == ids[0]
        front, back = validation["interpretations"]
        assert front["policy_id"] == "cancel_front_first_v1"
        assert back["policy_id"] == "cancel_back_first_v1"
        assert front["final_state"] == {"ahead_lots": 0, "behind_lots": 2, "external_lots": 2}
        assert back["final_state"] == {"ahead_lots": 2, "behind_lots": 0, "external_lots": 2}
        after = {
            str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*")
            if path.is_file()
        }
        assert before == after and not (directory / "runs").exists()
        missing = directory / "never-created"
        denied = run(
            "validate-queue-constraints",
            "invalid-id",
            "absent.json",
            "--split",
            "confirmation",
            "--input-root",
            str(missing),
            "--store",
            str(missing / "data"),
            "--registry",
            str(missing / "registry"),
            expected=5,
        )
        assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
        invalid_request = json.loads((examples / "queue-constraint-request.json").read_bytes())
        invalid_request["updates"][2]["cancellations_lots"] = 3
        (directory / "double-count.json").write_text(json.dumps(invalid_request), encoding="utf-8")
        invalid = run(
            "validate-queue-constraints",
            frozen["protocol_id"],
            "double-count.json",
            "--input-root",
            str(directory),
            "--store",
            str(store),
            "--registry",
            str(registry),
            expected=2,
        )
        assert invalid["error"]["code"] == "invalid_queue_constraints"
    print(
        "Installed queue constraints: source-bound, conserved, "
        "read-only and fail-closed checks passed."
    )


if __name__ == "__main__":
    main()
