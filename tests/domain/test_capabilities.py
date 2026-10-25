"""Behavioral contract: unsupported engine requests cannot silently degrade."""

import pytest

from tickwitness.domain.replay.capabilities import (
    EngineCapabilities,
    ReplayCapability,
    UnsupportedCapabilityError,
)


def test_replay_rejects_partial_support_and_identifies_every_missing_requirement() -> None:
    capabilities = EngineCapabilities(
        engine_id="fixture-engine",
        engine_version="test-1",
        supported=frozenset({ReplayCapability.INPUT_EVENT_TRACE}),
    )
    request = frozenset(
        {
            ReplayCapability.INPUT_EVENT_TRACE,
            ReplayCapability.FILL_TRACE,
            ReplayCapability.DECISION_TRACE,
        }
    )

    with pytest.raises(UnsupportedCapabilityError) as caught:
        capabilities.require(request)

    assert caught.value.engine_id == "fixture-engine"
    assert caught.value.engine_version == "test-1"
    assert caught.value.missing == frozenset(
        {ReplayCapability.FILL_TRACE, ReplayCapability.DECISION_TRACE}
    )
    assert str(caught.value) == (
        "fixture-engine@test-1 does not support: decision_trace, fill_trace"
    )
    assert capabilities.supported == frozenset({ReplayCapability.INPUT_EVENT_TRACE})


@pytest.mark.parametrize(
    "requested",
    [
        frozenset(),
        frozenset({ReplayCapability.INPUT_EVENT_TRACE}),
        frozenset({ReplayCapability.INPUT_EVENT_TRACE, ReplayCapability.FILL_TRACE}),
    ],
)
def test_replay_accepts_requests_with_complete_declared_support(
    requested: frozenset[ReplayCapability],
) -> None:
    capabilities = EngineCapabilities(
        engine_id="fixture-engine",
        engine_version="test-1",
        supported=frozenset({ReplayCapability.INPUT_EVENT_TRACE, ReplayCapability.FILL_TRACE}),
    )

    capabilities.require(requested)


def test_engine_version_capabilities_are_checked_independently() -> None:
    previous = EngineCapabilities("fixture-engine", "test-1", frozenset())
    current = EngineCapabilities(
        "fixture-engine", "test-2", frozenset({ReplayCapability.CHECKPOINT})
    )
    requested = frozenset({ReplayCapability.CHECKPOINT})

    current.require(requested)
    with pytest.raises(UnsupportedCapabilityError):
        previous.require(requested)
