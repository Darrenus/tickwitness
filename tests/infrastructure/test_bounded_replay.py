"""Real bounded pipes and deadline acceptance, without local/native fake modes."""

import importlib.util
import os
import time

import pytest
from test_subprocess_replay import fake_interpreter, replay_input

from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.infrastructure import bounded_replay
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError


@pytest.mark.parametrize("timeout", [True, 0, 61, 1.5])
def test_original_attempt_cap_remains_strict(timeout):
    with pytest.raises(ReplayValidationError):
        BoundedReplayAdapter(timeout_seconds=timeout, deadline_ns=1)


@pytest.mark.parametrize("deadline", [True, 0, -1, 1.5, 1 << 63])
def test_absolute_deadline_is_a_positive_int64(deadline):
    with pytest.raises(ReplayValidationError):
        BoundedReplayAdapter(deadline_ns=deadline)


def test_expired_campaign_does_not_construct_worker(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Expired deadline cannot launch a worker")

    monkeypatch.setattr(bounded_replay.subprocess, "Popen", forbidden)
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(deadline_ns=100, clock_ns=lambda: 100).run(replay_input())
    assert caught.value.code == "campaign_time_limit" and caught.value.exit_code == 8


def test_preflight_time_is_part_of_the_same_nonrenewable_deadline(monkeypatch):
    actual = bounded_replay.preflight_replay
    clock = [100]

    def preflight(value):
        result = actual(value)
        clock[0] = 300
        return result

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Preflight already exhausted campaign time")

    monkeypatch.setattr(bounded_replay, "preflight_replay", preflight)
    monkeypatch.setattr(bounded_replay.subprocess, "Popen", forbidden)
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(deadline_ns=200, clock_ns=lambda: clock[0]).run(replay_input())
    assert caught.value.code == "campaign_time_limit"


def test_subsecond_campaign_deadline_terminates_a_real_worker(tmp_path):
    executable = fake_interpreter(tmp_path, "import time\ntime.sleep(10)\n")
    started = time.monotonic()
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(
            deadline_ns=time.monotonic_ns() + 150_000_000,
            python_executable=executable,
        ).run(replay_input())
    assert caught.value.code == "campaign_time_limit"
    assert caught.value.exit_code == 8
    assert time.monotonic() - started < 3


def test_original_per_attempt_limit_can_expire_before_campaign(tmp_path):
    executable = fake_interpreter(tmp_path, "import time\ntime.sleep(10)\n")
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(
            timeout_seconds=1,
            deadline_ns=time.monotonic_ns() + 10_000_000_000,
            python_executable=executable,
        ).run(replay_input())
    assert caught.value.code == "engine_timeout" and caught.value.exit_code == 7


def test_real_stderr_flood_is_bounded_and_never_spooled(tmp_path):
    executable = fake_interpreter(
        tmp_path, "import os\nwhile True:\n    os.write(2, b'x' * 65536)\n"
    )
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(
            deadline_ns=time.monotonic_ns() + 5_000_000_000,
            python_executable=executable,
        ).run(replay_input())
    assert caught.value.code == "engine_output_limit"
    assert not any(path.name.startswith(".pending") for path in tmp_path.rglob("*"))


def test_success_uses_inherited_group_and_pipe_only_io(tmp_path, replay_result_factory):
    source = replay_input()
    result = replay_result_factory(source)
    executable = fake_interpreter(
        tmp_path,
        "import os,sys\n"
        "sys.stdin.buffer.read()\n"
        f"assert os.getpgrp() == {os.getpgrp()}\n"
        f"sys.stdout.buffer.write({result.canonical_bytes!r})\n",
    )
    actual = BoundedReplayAdapter(
        deadline_ns=time.monotonic_ns() + 5_000_000_000,
        python_executable=executable,
    ).run(source)
    assert actual == result
    assert sorted(path.name for path in tmp_path.iterdir()) == ["worker"]


def test_result_exiting_after_deadline_cannot_be_accepted(
    tmp_path, monkeypatch, replay_result_factory
):
    source = replay_input()
    result = replay_result_factory(source)
    executable = fake_interpreter(tmp_path, "print('{}')\n")
    clock = [100]

    def late_exchange(process, *_args, **_kwargs):
        assert process.wait(timeout=3) == 0
        clock[0] = 201
        return result.canonical_bytes, b""

    monkeypatch.setattr(bounded_replay, "_pipe_exchange", late_exchange)
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(
            deadline_ns=200,
            python_executable=executable,
            clock_ns=lambda: clock[0],
        ).run(source)
    assert caught.value.code == "campaign_time_limit"


def test_parsing_cannot_extend_result_acceptance_past_deadline(
    tmp_path, monkeypatch, replay_result_factory
):
    source = replay_input()
    result = replay_result_factory(source)
    executable = fake_interpreter(tmp_path, "print('{}')\n")
    clock = [100]
    actual_load = bounded_replay.load_replay_result
    parsed = []

    def exchange(process, *_args, **_kwargs):
        assert process.wait(timeout=3) == 0
        return result.canonical_bytes, b""

    def late_load(raw):
        loaded = actual_load(raw)
        parsed.append(raw)
        clock[0] = 201
        return loaded

    monkeypatch.setattr(bounded_replay, "_pipe_exchange", exchange)
    monkeypatch.setattr(bounded_replay, "load_replay_result", late_load)
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(
            deadline_ns=200,
            clock_ns=lambda: clock[0],
            python_executable=executable,
        ).run(source)
    assert caught.value.code == "campaign_time_limit"
    assert parsed == [result.canonical_bytes]


def test_other_engine_or_input_cannot_use_the_frozen_result(tmp_path, replay_result_factory):
    source = replay_input()
    result = replay_result_factory(source, dataset_id="f" * 64)
    executable = fake_interpreter(
        tmp_path, f"import sys\nsys.stdout.buffer.write({result.canonical_bytes!r})\n"
    )
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(
            deadline_ns=time.monotonic_ns() + 5_000_000_000,
            python_executable=executable,
        ).run(source)
    assert caught.value.code == "engine_invalid_result"


def test_missing_interpreter_remains_an_explicit_engine_failure(tmp_path):
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(
            deadline_ns=time.monotonic_ns() + 5_000_000_000,
            python_executable=tmp_path / "missing",
        ).run(replay_input())
    assert caught.value.code == "engine_unavailable" and caught.value.exit_code == 6


@pytest.mark.skipif(
    importlib.util.find_spec("nautilus_trader") is not None,
    reason="Verifies the intentionally minimal core installation",
)
def test_core_worker_returns_real_missing_extra_failure():
    with pytest.raises(ReplayProcessError) as caught:
        BoundedReplayAdapter(deadline_ns=time.monotonic_ns() + 5_000_000_000).run(replay_input())
    assert caught.value.code == "engine_unavailable" and caught.value.exit_code == 6
