"""Real pinned-native fee evidence must pass the independent native-free audit.

These five full replays use original example inputs. The ambiguous case must
remain ineligible on every platform, whichever native raw mode supplied its fee.
"""

from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path
from typing import cast

import pytest

from tickwitness.domain.data_evidence import normalize_events
from tickwitness.domain.evidence import evaluate_replay
from tickwitness.domain.evidence.protocol_evaluation import ProtocolEvaluation
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.infrastructure.nautilus_replay import NautilusReplayAdapter

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _native_present() -> bool:
    try:
        metadata.version("nautilus_trader")
    except metadata.PackageNotFoundError:
        return False
    return True


pytestmark = pytest.mark.skipif(not _native_present(), reason="optional Nautilus extra absent")


def _replay(changes: dict[str, dict[str, object]]) -> tuple[ReplayInput, ReplayResult]:
    specification = json.loads((EXAMPLES / "replay-spec.json").read_bytes())
    for group, fields in changes.items():
        specification[group].update(fields)
    normalized = normalize_events(
        (EXAMPLES / "replay-partials.jsonl").read_bytes()
    ).normalized_bytes
    replay_input = ReplayInput(
        hashlib.sha256(normalized).hexdigest(),
        normalized,
        build_replay_spec(json.dumps(specification).encode()),
    )
    return replay_input, NautilusReplayAdapter().run(replay_input)


@pytest.mark.parametrize(
    "changes,actual_fee,exact_fee,net_pnl",
    [
        pytest.param({}, "1", "1.00", "-2", id="default-unique"),
        pytest.param(
            {
                "instrument": {"price_increment": "0.01", "size_increment": "0.1"},
                "fees": {"maker_rate": "0.05"},
            },
            "0.01",
            "0.00500",
            "-0.02",
            id="half-cent",
        ),
        pytest.param(
            {
                "instrument": {"price_increment": "0.01", "size_increment": "0.1"},
                "fees": {"maker_rate": "0.04999999"},
            },
            "0",
            "0.00499999900",
            "0",
            id="below-half-cent",
        ),
        pytest.param(
            {"instrument": {"price_increment": "0.00005"}, "fees": {"maker_rate": "0.5"}},
            "0.01",
            "0.002500",
            "-0.02",
            id="two-stage-usd-quantization",
        ),
    ],
)
def test_actual_native_fee_and_cache_pass_independent_exact_audit(
    changes: dict[str, dict[str, object]], actual_fee: str, exact_fee: str, net_pnl: str
) -> None:
    replay_input, replay_result = _replay(changes)
    result = replay_result.document
    assert result["execution_status"] == "completed"
    fills = cast("list[dict[str, object]]", result["fill_trace"])
    assert len(fills) == 2
    for fill in fills:
        fields = cast("dict[str, object]", fill["fields"])
        assert fields["commission"] == actual_fee
        assert fields["exact_decimal_fee_before_native_quantization"] == exact_fee
    evaluation = evaluate_replay(replay_input, replay_result).document
    assert evaluation["valuation_status"] == "valued"
    assert (
        cast("dict[str, object]", evaluation["fee_model_verification"])["status"]
        == "verified_unique"
    )
    assert cast("dict[str, object]", evaluation["valuation"])["net_marked_pnl"] == net_pnl


def test_real_native_raw_mode_ambiguity_keeps_protocol_claim_unknown() -> None:
    replay_input, replay_result = _replay(
        {
            "instrument": {"price_increment": "100.00065"},
            "account": {"starting_cash": "100000"},
            "fees": {"maker_rate": "1"},
        }
    )
    result = replay_result.document
    assert result["execution_status"] == "completed"
    fills = cast("list[dict[str, object]]", result["fill_trace"])
    assert len(fills) == 2
    fees = {cast("dict[str, object]", fill["fields"])["commission"] for fill in fills}
    assert len(fees) == 1
    assert fees <= {"10000.06", "10000.07"}
    evaluation = evaluate_replay(replay_input, replay_result).document
    assert evaluation["valuation_status"] == "not_eligible"
    assert evaluation["ineligibility_reason"] == "ambiguous_native_fee_model"
    assert evaluation["mark"] is evaluation["valuation"] is None
    assert evaluation["fee_model_verification"] == {
        "policy_id": "nautilus_v1_binary64_usd_double_quantization_v1",
        "status": "ambiguous",
        "raw_precision_candidates": [9, 16],
        "ambiguous_fill_ordinals": [0, 1],
    }
    protocol = build_executable_protocol(
        json.dumps(
            {
                "schema_version": 2,
                "claim": {
                    "title": "Original native ambiguity regression",
                    "hypothesis": "The marked value exceeds a deliberately easy threshold.",
                    "metric": "net_marked_pnl_v1",
                    "comparator": "gt",
                    "threshold": "-1000000000",
                    "unit": "USD",
                },
                "replay_spec": replay_input.spec.document,
                "budget": {"max_attempts": 1, "max_wall_seconds": 30, "max_events": 7},
            }
        ).encode(),
        development_dataset_id=replay_input.dataset_id,
        confirmation_dataset_id="b" * 64,
    )
    observation = ProtocolEvaluation(protocol, replay_input, replay_result).document[
        "claim_observation"
    ]
    assert cast("dict[str, object]", observation)["eligible"] is False
    assert cast("dict[str, object]", observation)["satisfied"] is None
    assert cast("dict[str, object]", observation)["value"] is None
