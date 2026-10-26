"""Real native pairs locate response differences without inventing global causality."""

import json
from importlib import metadata
from pathlib import Path

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment, run_experiment
from tickwitness.application.scenario_comparison import compare_scenario_runs
from tickwitness.application.scenario_execution import run_scenario
from tickwitness.domain.evidence.run_records import load_run_receipt
from tickwitness.domain.evidence.scenario_records import load_scenario_run_receipt
from tickwitness.domain.replay.contracts import load_replay_result
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
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


def _case(root: Path, *, pending: bool = False):
    data = LocalDatasetStore(root / "data")
    source_name = "replay-eof-pending.jsonl" if pending else "replay-partials.jsonl"
    development = import_events((EXAMPLES / source_name).read_bytes(), lambda: data).dataset_id
    confirmation = import_events(
        (EXAMPLES / "replay-confirmation.jsonl").read_bytes(), lambda: data
    ).dataset_id
    registry = LocalExecutableProtocolRegistry(root / "registry")
    request = json.loads((EXAMPLES / "stress-experiment-request.json").read_bytes())
    request["budget"]["max_attempts"] = 2 if pending else 5
    if pending:
        request["replay_spec"] = json.loads((EXAMPLES / "replay-eof-spec.json").read_bytes())
    frozen = freeze_experiment(
        json.dumps(request).encode(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation,
        datasets_factory=lambda: data,
        registry_factory=lambda: registry,
    )
    ledger = LocalAttemptLedger(root / "runs")
    return frozen.protocol_id, data, registry, ledger


def _scenario(protocol_id, data, registry, ledger, *, anchor: int, delay: int):
    assumption = json.loads((EXAMPLES / "stress-assumption-request.json").read_bytes())
    assumption["transform"]["from_capture_seq"] = anchor
    candidate = json.loads((EXAMPLES / "stress-zero-request.json").read_bytes())
    candidate["additional_delay"]["value"] = delay
    return run_scenario(
        protocol_id,
        json.dumps(assumption).encode(),
        json.dumps(candidate).encode(),
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        ledger_factory=lambda: ledger,
        engine_factory=lambda timeout: SubprocessReplayAdapter(timeout_seconds=timeout),
    )


def _baseline(protocol_id, data, registry, ledger):
    return run_experiment(
        protocol_id,
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        ledger_factory=lambda: ledger,
        engine_factory=lambda timeout: SubprocessReplayAdapter(timeout_seconds=timeout),
    )


def _slots(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted((root / "runs" / "slots").rglob("*.json"))
    }


def _forbid_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Comparing committed runs cannot consume a slot or replay native")

    monkeypatch.setattr(LocalAttemptLedger, "reserve", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "run", forbidden)


def _compare(baseline, scenario, data, registry, ledger):
    return compare_scenario_runs(
        baseline.run_id,
        scenario.run_id,
        split="development",
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
        ledger_factory=lambda: ledger,
    )


def test_real_cancel_pair_zero_control_and_uniform_translation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol_id, data, registry, ledger = _case(tmp_path)
    baseline = _baseline(protocol_id, data, registry, ledger)
    zero = _scenario(protocol_id, data, registry, ledger, anchor=4, delay=0)
    suffix = _scenario(protocol_id, data, registry, ledger, anchor=4, delay=2_000_000_000)
    uniform = _scenario(protocol_id, data, registry, ledger, anchor=1, delay=2_000_000_000)
    original_slots = _slots(tmp_path)
    assert len(original_slots) == 4

    baseline_receipt = load_run_receipt(ledger.read_artifact(baseline.run_id))
    uniform_receipt = load_scenario_run_receipt(ledger.read_artifact(uniform.run_id))
    baseline_result = load_replay_result(
        ledger.read_artifact(baseline_receipt.document["bindings"]["replay_result_sha256"])
    ).document
    uniform_result = load_replay_result(
        ledger.read_artifact(uniform_receipt.document["bindings"]["replay_result_sha256"])
    ).document
    assert (
        baseline_result["decision_trace"][0]["fields"]["order_id"]
        != (uniform_result["decision_trace"][0]["fields"]["order_id"])
    )
    baseline_reason = next(
        row["fields"]["reason"]
        for row in baseline_result["order_trace"]
        if row["kind"] == "OrderCancelRejected"
    )
    uniform_reason = next(
        row["fields"]["reason"]
        for row in uniform_result["order_trace"]
        if row["kind"] == "OrderCancelRejected"
    )
    assert baseline_reason != uniform_reason
    assert [row["fields"]["source_trade_id"] for row in baseline_result["input_trace"]] == [
        row["fields"]["source_trade_id"] for row in uniform_result["input_trace"]
    ]

    _forbid_execution(monkeypatch)
    unchanged = _compare(baseline, zero, data, registry, ledger).document
    changed = _compare(baseline, suffix, data, registry, ledger).document
    shifted = _compare(baseline, uniform, data, registry, ledger).document

    for document in (unchanged, changed, shifted):
        assert document["controlled_intervention"] is True
        assert document["strictly_paired"] is False
        assert document["trace_comparison"]["global_earliest_claimed"] is False
        assert document["numeric_comparison"]["status"] == "comparable"
        assert document["numeric_comparison"]["baseline_value"] == "-2"
    assert unchanged["numeric_comparison"]["delta"] == "0"
    assert unchanged["trace_comparison"]["business_trace_changed"] is False
    assert unchanged["trace_comparison"]["business"]["first_divergence"] is None
    assert shifted["numeric_comparison"]["delta"] == "0"
    assert shifted["trace_comparison"]["raw_trace_changed"] is True
    assert shifted["trace_comparison"]["business_trace_changed"] is False
    assert shifted["trace_comparison"]["business"]["first_divergence"] is None
    assert changed["numeric_comparison"]["scenario_value"] == "-1"
    assert changed["numeric_comparison"]["delta"] == "1"
    assert changed["trace_comparison"]["business_trace_changed"] is True
    difference = changed["trace_comparison"]["business"]["first_divergence"]
    assert difference["section"] == "order_trace"
    assert difference["left_trace_ref"]["kind"] == "OrderFilled"
    assert difference["left_trace_ref"]["source_ref"]["capture_seq"] == 5
    assert difference["right_trace_ref"]["kind"] == "OrderCanceled"
    assert difference["right_trace_ref"]["source_ref"]["capture_seq"] == 4
    assert _slots(tmp_path) == original_slots
    assert _compare(baseline, suffix, data, registry, ledger).document == changed


def test_real_pending_eof_pair_stays_unvalued_even_when_business_traces_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol_id, data, registry, ledger = _case(tmp_path, pending=True)
    baseline = _baseline(protocol_id, data, registry, ledger)
    zero = _scenario(protocol_id, data, registry, ledger, anchor=2, delay=0)
    assert baseline.execution_status == zero.execution_status == "incomplete"
    original_slots = _slots(tmp_path)
    assert len(original_slots) == 2

    _forbid_execution(monkeypatch)
    comparison = _compare(baseline, zero, data, registry, ledger)
    document = comparison.document
    numeric = document["numeric_comparison"]
    assert numeric["status"] == "not_comparable"
    assert numeric["reason"] == "baseline_not_eligible"
    assert numeric["baseline_value"] is numeric["scenario_value"] is numeric["delta"] is None
    assert document["trace_comparison"]["business_trace_changed"] is False
    assert document["trace_comparison"]["business"]["first_divergence"] is None
    assert _slots(tmp_path) == original_slots
