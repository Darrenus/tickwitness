"""Use real processes for unavailable, timed out, oversized and malformed worker paths."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec
from tickwitness.infrastructure.replay_worker import _request
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError, SubprocessReplayAdapter


def replay_input() -> ReplayInput:
    request = {
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
    raw = (
        json.dumps(
            {
                "schema_version": 1,
                "type": "snapshot",
                "source": "synthetic",
                "instrument": "EUR-USD",
                "session": "process-test",
                "capture_seq": 1,
                "event_time_ns": 100,
                "receive_time_ns": 100,
                "last_sequence": 10,
                "bids": [[100, 1], [99, 10]],
                "asks": [[103, 10], [104, 10]],
            }
        )
        + "\n"
    ).encode()
    return ReplayInput(
        "a" * 64,
        normalize_events(raw).normalized_bytes,
        build_replay_spec(json.dumps(request).encode()),
    )


def fake_interpreter(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "worker"
    # A local controlled executable models a failed worker without mocking Popen.
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o700)
    return path


@pytest.mark.skipif(
    importlib.util.find_spec("nautilus_trader") is not None,
    reason="This case verifies the intentionally minimal core installation",
)
def test_core_install_returns_dependency_failure_from_real_worker() -> None:
    with pytest.raises(ReplayProcessError) as caught:
        SubprocessReplayAdapter().run(replay_input())

    assert caught.value.exit_code == 6
    assert caught.value.code == "engine_unavailable"


def test_timeout_terminates_real_process(tmp_path: Path) -> None:
    interpreter = fake_interpreter(tmp_path, "import time\ntime.sleep(10)\n")

    with pytest.raises(ReplayProcessError) as caught:
        SubprocessReplayAdapter(timeout_seconds=1, python_executable=interpreter).run(
            replay_input()
        )

    assert caught.value.code == "engine_timeout"


def test_malformed_worker_result_is_rejected(tmp_path: Path) -> None:
    interpreter = fake_interpreter(tmp_path, "print('{}')\n")

    with pytest.raises(ReplayProcessError) as caught:
        SubprocessReplayAdapter(python_executable=interpreter).run(replay_input())

    assert caught.value.code == "engine_invalid_result"


def test_worker_output_quota_is_enforced(tmp_path: Path) -> None:
    interpreter = fake_interpreter(tmp_path, "import os\nos.write(2, b'x' * 70000)\n")

    with pytest.raises(ReplayProcessError) as caught:
        SubprocessReplayAdapter(python_executable=interpreter).run(replay_input())

    assert caught.value.code == "engine_output_limit", repr(caught.value.__cause__)


def test_missing_interpreter_is_explicitly_unavailable(tmp_path: Path) -> None:
    with pytest.raises(ReplayProcessError) as caught:
        SubprocessReplayAdapter(python_executable=tmp_path / "absent").run(replay_input())

    assert caught.value.exit_code == 6


def test_worker_cannot_return_a_different_engine_semantics(
    tmp_path: Path, replay_result_factory
) -> None:
    request = replay_input()
    result = replay_result_factory(
        request,
        engine={
            "id": "nautilus-trader",
            "version": "1.231.0",
            "semantic_id": "different_model",
        },
    )
    interpreter = fake_interpreter(
        tmp_path, f"import sys\nsys.stdout.buffer.write({result.canonical_bytes!r})\n"
    )

    with pytest.raises(ReplayProcessError) as caught:
        SubprocessReplayAdapter(python_executable=interpreter).run(request)

    assert caught.value.code == "engine_invalid_result"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b'{"schema_version":1,"schema_version":1}',
        b'{"schema_version":1,"dataset_id":"a","normalized":null,"spec":"x"}',
        b'{"schema_version":1,"dataset_id":"a","normalized":"x","spec":"x","path":"/tmp"}',
    ],
)
def test_worker_rejects_invalid_envelope_before_dependency_import(raw: bytes) -> None:
    with pytest.raises(ReplayValidationError):
        _request(raw)


@pytest.mark.parametrize("timeout", [True, 0, 61, 1.5])
def test_supervisor_configuration_is_bounded(timeout: object) -> None:
    with pytest.raises(ReplayValidationError):
        SubprocessReplayAdapter(timeout_seconds=timeout)
