"""Qualify a sealed dataset through the replay port, without executing a research protocol."""

import hashlib
from collections.abc import Callable

from tickwitness.application.data_access import DataAccessError, DatasetReader, read_accepted_events
from tickwitness.domain.replay.comparison import ReplayComparison, compare_replay_results
from tickwitness.domain.replay.contracts import (
    ReplayInput,
    ReplayPort,
    ReplayResult,
    load_replay_result,
)
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec


def replay_dataset(
    dataset_id: str,
    request: bytes,
    *,
    datasets_factory: Callable[[], DatasetReader],
    engine_factory: Callable[[], ReplayPort],
) -> ReplayResult:
    """Validate bindings before constructing an engine or importing its dependency.

    This trusted local qualification entry accepts an explicit dataset. It is
    not a FrozenProtocol executor or an exploratory Agent/holdout access grant.
    """
    spec = build_replay_spec(request)
    try:
        data = read_accepted_events(dataset_id, datasets_factory())
    except DataAccessError as error:
        raise ReplayValidationError(str(error)) from error
    replay_input = ReplayInput(dataset_id, data, spec)
    preflight_replay(replay_input)
    result = engine_factory().run(replay_input)
    document = result.document
    if (
        document["dataset_id"] != dataset_id
        or document["data_sha256"] != hashlib.sha256(data).hexdigest()
        or document["spec_id"] != spec.spec_id
    ):
        raise ReplayValidationError("Replay result does not match the requested immutable input")
    return result


def compare_replays(left: bytes, right: bytes) -> ReplayComparison:
    """Accept canonical result files, including the CLI's single terminal newline."""
    return compare_replay_results(
        load_replay_result(left.removesuffix(b"\n")),
        load_replay_result(right.removesuffix(b"\n")),
    )
