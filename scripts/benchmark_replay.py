#!/usr/bin/env python3
"""Measure ten independent native qualification runs of an original tiny fixture.

Run with a Python environment containing an installed TickWitness wheel and its
fixed NautilusTrader dependency set. No arbitrary strategy or protocol is loaded.
Durations measure adapter.run, including any work/lazy imports inside that call;
they exclude interpreter startup and work performed before the call.
"""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.replay.comparison import compare_replay_results
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult, load_replay_result
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore

_RUNS = 10
_BASE = 1_700_000_000_000_000_000
_SECOND = 1_000_000_000


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(*, changed: bool = False) -> tuple[bytes, bytes]:
    def event(kind: str, capture: int, offset: int, **fields: object) -> dict[str, object]:
        return {
            "schema_version": 1,
            "type": kind,
            "source": "synthetic",
            "instrument": "EUR-USD",
            "session": "s03-baseline-001",
            "capture_seq": capture,
            "event_time_ns": _BASE + offset,
            "receive_time_ns": _BASE + offset + 100 + (1 if changed and capture == 1 else 0),
            **fields,
        }

    events = [
        event(
            "snapshot",
            1,
            0,
            last_sequence=10,
            bids=[[100, 1], [99, 10]],
            asks=[[103, 10], [104, 10]],
        ),
        event(
            "delta",
            2,
            _SECOND // 2,
            first_sequence=11,
            last_sequence=11,
            bids=[[100, 4]],
            asks=[],
        ),
        event(
            "trade",
            3,
            _SECOND,
            trade_id="s03-trade-1",
            price_ticks=100,
            quantity_lots=2,
            aggressor_side="sell",
        ),
        event(
            "delta",
            4,
            _SECOND + 1,
            first_sequence=12,
            last_sequence=12,
            bids=[[100, 2]],
            asks=[],
        ),
        event(
            "trade",
            5,
            2 * _SECOND,
            trade_id="s03-trade-2",
            price_ticks=100,
            quantity_lots=1,
            aggressor_side="sell",
        ),
        event(
            "delta",
            6,
            2 * _SECOND + 1,
            first_sequence=13,
            last_sequence=13,
            bids=[[100, 1]],
            asks=[],
        ),
        event(
            "delta",
            7,
            3 * _SECOND,
            first_sequence=14,
            last_sequence=14,
            bids=[[100, 1]],
            asks=[],
        ),
    ]
    spec = {
        "schema_version": 1,
        "clock_policy_id": "receive_order_v1",
        "instrument": {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "price_increment": "1",
            "size_increment": "1",
        },
        "account": {"starting_cash": "10000"},
        "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
        "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
        "strategy": {
            "kind": "single_limit_buy_v1",
            "submit_capture_seq": 1,
            "limit_price_ticks": 100,
            "quantity_lots": 2,
            "cancel_after_first_fill": False,
        },
        "seed": 7,
    }
    return b"".join(_canonical(value) + b"\n" for value in events), _canonical(spec)


def _worker(*, changed: bool) -> None:
    from tickwitness.infrastructure.nautilus_replay import NautilusReplayAdapter

    raw, spec_bytes = _fixture(changed=changed)
    normalized = normalize_events(raw)
    with TemporaryDirectory(prefix="tickwitness-baseline-input-") as temporary:
        dataset = LocalDatasetStore(Path(temporary) / "store").publish(
            raw, normalized.normalized_bytes, normalized.report
        )
        replay_input = ReplayInput(
            dataset.dataset_id, normalized.normalized_bytes, build_replay_spec(spec_bytes)
        )
        # Deliberately outside timing. The adapter still repeats its own guard.
        preflight_replay(replay_input)
        adapter = NautilusReplayAdapter()
        started = time.perf_counter_ns()
        result = adapter.run(replay_input)
        duration_ns = time.perf_counter_ns() - started
    print(json.dumps({"duration_ns": duration_ns, "result_json": result.canonical_bytes.decode()}))


def _run_once(*, changed: bool = False) -> tuple[int, ReplayResult, dict[str, object]]:
    # absolute(), rather than resolve(), preserves a venv executable symlink.
    interpreter = str(Path(sys.executable).absolute())
    with TemporaryDirectory(prefix="tickwitness-baseline-cwd-") as temporary:
        wall_started = time.perf_counter_ns()
        completed = subprocess.run(
            [
                interpreter,
                "-I",
                str(Path(__file__).absolute()),
                "--worker",
                "changed" if changed else "baseline",
            ],
            cwd=temporary,
            capture_output=True,
            check=False,
            timeout=60,
        )
        worker_wall_ns = time.perf_counter_ns() - wall_started
    if completed.returncode:
        raise RuntimeError(
            f"Native qualification failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', errors='replace')[-4096:]}"
        )
    packet = json.loads(completed.stdout)
    duration = packet["duration_ns"]
    if type(duration) is not int or duration <= 0:
        raise RuntimeError("Worker did not return a positive raw duration")
    result = load_replay_result(packet["result_json"].encode("utf-8"))
    diagnostics: dict[str, object] = {
        "worker_wall_ns": worker_wall_ns,
        "stderr_bytes": len(completed.stderr),
        "stderr_sha256": _digest(completed.stderr),
    }
    return duration, result, diagnostics


def _module_digest(name: str) -> str:
    module = importlib.util.find_spec(name)
    if module is None or module.origin is None:
        raise RuntimeError(f"Installed module is missing: {name}")
    return _digest(Path(module.origin).read_bytes())


def _write(directory: Path, name: str, value: object) -> None:
    (directory / name).write_text(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _benchmark(directory: Path) -> None:
    observations: list[dict[str, object]] = []
    golden: ReplayResult | None = None
    for index in range(_RUNS):
        duration, result, diagnostics = _run_once()
        if result.document["execution_status"] != "completed":
            raise RuntimeError("Baseline did not complete its fixed qualification workload")
        if golden is None:
            golden = result
        comparison = compare_replay_results(golden, result)
        if not comparison.strictly_paired or not comparison.semantically_equal:
            raise RuntimeError(f"Run {index + 1} changed declared conditions or semantics")
        observations.append(
            {
                "run": index + 1,
                "duration_ns": duration,
                "result_sha256": _digest(result.canonical_bytes),
                "strictly_paired_to_first": comparison.strictly_paired,
                "semantically_equal_to_first": comparison.semantically_equal,
                **diagnostics,
            }
        )
    if golden is None:
        raise RuntimeError("No native result was measured")
    changed_duration, changed, changed_diagnostics = _run_once(changed=True)
    changed_comparison = compare_replay_results(golden, changed)
    changed_document = changed_comparison.document
    if (
        changed_comparison.strictly_paired
        or changed_comparison.semantically_equal
        or changed_document["first_divergence"] is None
        or changed_document["first_decision_divergence"] is None
    ):
        raise RuntimeError(
            "Known receive-time change was not localized in input and decision traces"
        )
    raw, spec_bytes = _fixture()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fixture-events.jsonl").write_bytes(raw)
    (directory / "fixture-spec.json").write_bytes(spec_bytes + b"\n")
    (directory / "golden-result.json").write_bytes(golden.canonical_bytes)
    (directory / "changed-result.json").write_bytes(changed.canonical_bytes)
    _write(directory, "changed-comparison.json", changed_document)
    summary: dict[str, object] = {
        "kind": "sprint_03_native_qualification_baseline_v1",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "runs": observations,
        "run_count": _RUNS,
        "all_strictly_paired": True,
        "all_semantically_equal": True,
        "golden_result_sha256": _digest(golden.canonical_bytes),
        "environment": golden.document["environment"],
        "engine": golden.document["engine"],
        "machine_observation": {
            "machine": platform.machine(),
            "python_implementation": platform.python_implementation(),
            "python_compiler": platform.python_compiler(),
            "logical_cpu_count": os.cpu_count(),
            "perf_counter_resolution_seconds": str(time.get_clock_info("perf_counter").resolution),
        },
        "installed_package_versions": {
            distribution.metadata["Name"]: distribution.version
            for distribution in importlib.metadata.distributions()
        },
        "installed_module_sha256": {
            name: _module_digest(name)
            for name in (
                "tickwitness.infrastructure.nautilus_replay",
                "tickwitness.infrastructure._nautilus_native",
                "nautilus_trader.backtest.engine",
            )
        },
        "benchmark_script_sha256": _digest(Path(__file__).read_bytes()),
        "fixture_raw_sha256": _digest(raw),
        "fixture_spec_sha256": _digest(build_replay_spec(spec_bytes).canonical_bytes),
        "changed_control": {
            "change": "First source receive_time_ns increases by exactly 1 ns; all else unchanged.",
            "duration_ns": changed_duration,
            "result_sha256": _digest(changed.canonical_bytes),
            **changed_diagnostics,
        },
        "timing_scope": "adapter.run only; work and lazy imports inside that call are included",
        "worker_wall_scope": (
            "subprocess.run wall time, including startup, input preparation and sealing, "
            "adapter.run, serialization and exit; startup is not separately isolated"
        ),
        "limits": [
            "Original seven-event single-instrument built-in buy qualification only.",
            "Ten fresh isolated processes on one machine; not a platform support certification.",
            "No FrozenProtocol, arbitrary source, research verdict, live API or external data.",
            "No throughput, P99, native-only timing, wrapper overhead or real-market claim.",
        ],
    }
    _write(directory, "summary.json", summary)
    print(
        json.dumps(
            {
                "runs": _RUNS,
                "all_strictly_paired": True,
                "all_semantically_equal": True,
                "golden_result_sha256": summary["golden_result_sha256"],
                "first_changed_input_pointer": cast(
                    "dict[str, object]", changed_document["first_divergence"]
                )["json_pointer"],
                "first_changed_decision_pointer": cast(
                    "dict[str, object]", changed_document["first_decision_divergence"]
                )["json_pointer"],
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--worker", choices=("baseline", "changed"), help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.worker is not None:
        _worker(changed=arguments.worker == "changed")
    elif arguments.output_dir is not None:
        _benchmark(arguments.output_dir)
    else:
        parser.error("--output-dir is required")


if __name__ == "__main__":
    main()
