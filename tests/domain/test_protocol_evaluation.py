"""The protocol wrapper cannot turn an ambiguous native fee into a known claim value."""

import json

import pytest
from test_evaluation import _ambiguous_fixture

from tickwitness.domain.evidence.protocol_evaluation import ProtocolEvaluation
from tickwitness.domain.research_contracts.executable import build_executable_protocol


@pytest.mark.parametrize("actual", ["10000.06", "10000.07"])
def test_ambiguous_fee_keeps_claim_unknown_even_with_an_easy_usd_threshold(actual: str) -> None:
    replay_input, result = _ambiguous_fixture(actual)
    request = {
        "schema_version": 2,
        "claim": {
            "title": "Original ambiguity regression",
            "hypothesis": "The marked value exceeds a deliberately easy threshold.",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "-1000000000",
            "unit": "USD",
        },
        "replay_spec": replay_input.spec.document,
        "budget": {"max_attempts": 1, "max_wall_seconds": 30, "max_events": 7},
    }
    protocol = build_executable_protocol(
        json.dumps(request).encode(),
        development_dataset_id=replay_input.dataset_id,
        confirmation_dataset_id="b" * 64,
    )
    evaluation = ProtocolEvaluation(protocol, replay_input, result).document
    assert evaluation["claim_observation"] == {
        "eligible": False,
        "satisfied": None,
        "value": None,
        "metric": "net_marked_pnl_v1",
        "unit": "USD",
        "comparator": "gt",
        "threshold": "-1000000000",
    }
    assert evaluation["replay_evaluation"]["fee_model_verification"]["status"] == "ambiguous"
    assert evaluation["replay_evaluation"]["valuation"] is None
