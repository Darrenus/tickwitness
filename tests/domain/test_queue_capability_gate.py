"""Qualification must not silently enable queue execution through the old profile."""

import json
from pathlib import Path

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence.evaluation import EvaluationValidationError, evaluate_replay
from tickwitness.domain.replay.capabilities import ReplayCapability, UnsupportedCapabilityError
from tickwitness.domain.replay.contracts import ReplayInput, build_replay_result
from tickwitness.domain.replay.specs import ReplayValidationError, build_replay_spec
from tickwitness.infrastructure.nautilus_replay import NautilusReplayAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_original_native_profile_does_not_claim_explicit_queue_allocation() -> None:
    with pytest.raises(UnsupportedCapabilityError) as caught:
        NautilusReplayAdapter().capabilities.require(
            frozenset({ReplayCapability.EXPLICIT_QUEUE_ALLOCATION})
        )
    assert caught.value.missing == frozenset({ReplayCapability.EXPLICIT_QUEUE_ALLOCATION})


def test_existing_replay_spec_rejects_a_silently_added_queue_policy() -> None:
    document = json.loads((FIXTURES / "evidence-replay-spec.json").read_bytes())
    document["queue_policy"] = "cancel_front_first_v1"
    with pytest.raises(ReplayValidationError):
        build_replay_spec(json.dumps(document).encode())


def test_existing_accounting_auditor_rejects_the_new_probe_semantic() -> None:
    spec = build_replay_spec((FIXTURES / "evidence-replay-spec.json").read_bytes())
    normalized = normalize_events(
        (FIXTURES / "evidence-events.jsonl").read_bytes()
    ).normalized_bytes
    source = ReplayInput("a" * 64, normalized, spec)
    document = json.loads((FIXTURES / "evidence-result.json").read_bytes())
    document["dataset_id"] = source.dataset_id
    assert (
        evaluate_replay(source, build_replay_result(document)).document["audit_status"]
        == "verified"
    )
    document["engine"]["semantic_id"] = "nautilus_public_shadow_fifo_queue_probe_v1"
    result = build_replay_result(document)
    with pytest.raises(EvaluationValidationError):
        evaluate_replay(source, result)
