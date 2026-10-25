#!/usr/bin/env python3
"""Exercise versioned experiments with an installed wheel, never source-path imports."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--save-sample", type=Path)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-evidence-wheel-") as temporary:
        directory = Path(temporary)
        store, registry, runs = (directory / name for name in ("data", "registry", "runs"))

        def run(*command: str, expected: int = 0):
            result = subprocess.run(
                [interpreter, "-I", "-m", "tickwitness", *command],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != expected or (expected and result.stdout):
                raise RuntimeError(
                    f"Installed evidence CLI failed: {result.stdout}\n{result.stderr}"
                )
            return json.loads(result.stdout if expected == 0 else result.stderr)

        ids = []
        for name in ("replay-partials.jsonl", "replay-confirmation.jsonl"):
            receipt = run(
                "import-events", name, "--input-root", str(examples), "--store", str(store)
            )
            ids.append(receipt["dataset_id"])
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
        repeated = run(
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
        assert repeated["protocol_id"] == frozen["protocol_id"] and repeated["created"] is False
        protocol_id = frozen["protocol_id"]
        missing = directory / "never-created"
        denied = run(
            "replay-protocol",
            protocol_id,
            "--split",
            "confirmation",
            "--store",
            str(missing / "data"),
            "--registry",
            str(missing / "registry"),
            "--runs",
            str(missing / "runs"),
            expected=5,
        )
        assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
        command = (
            "replay-protocol",
            protocol_id,
            "--store",
            str(store),
            "--registry",
            str(registry),
            "--runs",
            str(runs),
        )
        result = run(*command, expected=0 if arguments.native else 6)
        if arguments.native:
            observation = result["evaluation"]["claim_observation"]
            assert observation["eligible"] is True and observation["value"] == "-2"
            assert observation["satisfied"] is False
            destination = directory / "exported"
            exported = run(
                "export-evidence",
                result["run_id"],
                str(destination),
                "--store",
                str(store),
                "--registry",
                str(registry),
                "--runs",
                str(runs),
            )
            assert exported["native_replayed"] is False and exported["accounting_verified"] is True
            relocated = directory / "relocated"
            destination.rename(relocated)
            for path in (store, registry, runs):
                shutil.rmtree(path)
            verified = run("verify-evidence", str(relocated))
            assert verified == exported
            if arguments.save_sample is not None:
                if arguments.save_sample.exists():
                    raise RuntimeError("Sample destination already exists")
                shutil.copytree(relocated, arguments.save_sample)
            manifest = json.loads((relocated / "manifest.json").read_bytes())
            victim = relocated / manifest["roles"]["replay_result"]["ref"]
            victim.write_bytes(b"tampered")
            assert (
                run("verify-evidence", str(relocated), expected=3)["error"]["code"]
                == "research_store_integrity_or_io_failure"
            )
        else:
            failure = result["error"]
            assert failure["budget_consumed"] is True
            attempt = run("inspect-attempt", failure["attempt_id"], "--runs", str(runs))
            assert (
                attempt["state"] == "finalized"
                and attempt["outcome"]["kind"] == "replay_attempt_failure_v1"
            )
            sample = examples / "evidence-demo"
            verified = run("verify-evidence", str(sample))
            assert verified["accounting_verified"] is True and verified["native_replayed"] is False
    print(
        "Installed evidence workflow: versioned freeze, budgeted replay, "
        "portable offline verification passed."
    )


if __name__ == "__main__":
    main()
