"""Bind a deterministic development valuation to its versioned claim and protocol."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import cast

from tickwitness.domain.evidence.evaluation import evaluate_replay
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult
from tickwitness.domain.research_contracts.executable import ExecutableProtocol

SCOPE: Mapping[str, object] = MappingProxyType(
    {
        "phase": "development",
        "scenario_id": "baseline_v1",
        "search_performed": False,
    }
)


@dataclass(frozen=True, slots=True)
class ProtocolEvaluation:
    protocol: ExecutableProtocol
    replay_input: ReplayInput
    result: ReplayResult
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.protocol, ExecutableProtocol)
            or not isinstance(self.replay_input, ReplayInput)
            or not isinstance(self.result, ReplayResult)
        ):
            raise EvidenceValidationError("Protocol evaluation requires validated immutable values")
        document = self.protocol.document
        datasets = cast("dict[str, str]", document["datasets"])
        budget = cast("dict[str, int]", document["budget"])
        if (
            self.replay_input.dataset_id != datasets["development"]
            or self.replay_input.spec.spec_id != document["replay_spec_id"]
        ):
            raise EvidenceValidationError(
                "Evaluation input differs from the frozen development binding"
            )
        if len(self.replay_input.normalized_bytes.splitlines()) > budget["max_events"]:
            raise EvidenceValidationError("Frozen event budget exceeded")
        if canonical(cast("dict[str, object]", self.result.document["engine"])) != canonical(
            cast("dict[str, object]", document["engine"])
        ):
            raise EvidenceValidationError("Result engine differs from the frozen model")
        audited = evaluate_replay(self.replay_input, self.result)
        base = audited.document
        claim = cast("dict[str, str]", document["claim"])
        eligible = base["valuation_status"] == "valued"
        value: str | None = None
        satisfied: bool | None = None
        if eligible:
            value = cast("dict[str, str]", base["valuation"])["net_marked_pnl"]
            number, threshold = Fraction(value), Fraction(claim["threshold"])
            satisfied = {
                "gt": number > threshold,
                "ge": number >= threshold,
                "lt": number < threshold,
                "le": number <= threshold,
            }[claim["comparator"]]
        encoded = canonical(
            {
                "kind": "protocol_evaluation_v1",
                "schema_version": 1,
                "protocol_id": self.protocol.protocol_id,
                "claim_revision_id": self.protocol.claim_revision_id,
                "scope": dict(SCOPE),
                "claim_observation": {
                    "eligible": eligible,
                    "satisfied": satisfied,
                    "value": value,
                    "metric": claim["metric"],
                    "unit": "USD",
                    "comparator": claim["comparator"],
                    "threshold": claim["threshold"],
                },
                "replay_evaluation": base,
            }
        )
        object.__setattr__(self, "canonical_bytes", encoded)

    @property
    def evaluation_id(self) -> str:
        return digest(self.canonical_bytes)

    @property
    def document(self) -> dict[str, object]:
        return parse(self.canonical_bytes, limit=4 * 1024 * 1024)
