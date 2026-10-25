"""Deterministic comparisons of validated qualification results.

Trace ordinals are local to their channel. The fixed channel comparison order
does not imply a total chronological or causal order across native callbacks.
Matching observations never turn a change of conditions into a paired run.
"""

import json
from dataclasses import dataclass, field
from typing import cast

from tickwitness.domain.replay.contracts import ReplayResult
from tickwitness.domain.replay.specs import ReplayValidationError

_CONDITIONS = (
    ("engine", "engine"),
    ("environment", "environment"),
    ("specification", "spec_id"),
    ("data", "dataset_id"),
    ("data", "data_sha256"),
)
_TRACE_ORDER = (
    "input_trace",
    "decision_trace",
    "order_trace",
    "fill_trace",
    "account_trace",
)
_SEMANTIC_ORDER = (*_TRACE_ORDER, "execution_status", "completeness")


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    """Detached JSON evidence about conditions and observed differences."""

    left: ReplayResult
    right: ReplayResult
    canonical_bytes: bytes = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.left, ReplayResult) or not isinstance(self.right, ReplayResult):
            raise ReplayValidationError("Comparison requires two validated ReplayResult values")
        document = _compare_documents(self.left.document, self.right.document)
        canonical = json.dumps(
            document, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        object.__setattr__(self, "canonical_bytes", canonical)

    @property
    def document(self) -> dict[str, object]:
        """Return a fresh view so a caller cannot mutate the comparison evidence."""
        return cast("dict[str, object]", json.loads(self.canonical_bytes))

    @property
    def strictly_paired(self) -> bool:
        return cast("bool", self.document["strictly_paired"])

    @property
    def semantically_equal(self) -> bool:
        return cast("bool", self.document["semantically_equal"])


def _pointer_component(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _difference(
    pointer: str,
    left: object,
    right: object,
    *,
    left_present: bool = True,
    right_present: bool = True,
) -> dict[str, object]:
    return {
        "json_pointer": pointer,
        "left_present": left_present,
        "right_present": right_present,
        "left_value": left,
        "right_value": right,
    }


def _first_difference(left: object, right: object, pointer: str) -> dict[str, object] | None:
    # Python equates True with 1; JSON evidence must retain that type difference.
    if type(left) is not type(right):
        return _difference(pointer, left, right)
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(left.keys() | right.keys()):
            path = f"{pointer}/{_pointer_component(key)}"
            if key not in left:
                return _difference(path, None, right[key], left_present=False)
            if key not in right:
                return _difference(path, left[key], None, right_present=False)
            difference = _first_difference(left[key], right[key], path)
            if difference is not None:
                return difference
        return None
    if isinstance(left, list) and isinstance(right, list):
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=False)):
            difference = _first_difference(left_item, right_item, f"{pointer}/{index}")
            if difference is not None:
                return difference
        common = min(len(left), len(right))
        if len(left) < len(right):
            return _difference(f"{pointer}/{common}", None, right[common], left_present=False)
        if len(left) > len(right):
            return _difference(f"{pointer}/{common}", left[common], None, right_present=False)
        return None
    return None if left == right else _difference(pointer, left, right)


def _trace_reference(
    document: dict[str, object], channel: str, index: int
) -> dict[str, object] | None:
    rows = cast("list[dict[str, object]]", document[channel])
    if index >= len(rows):
        return None
    row = rows[index]
    return {"channel": channel, "ordinal": row["ordinal"], "source_ref": row["source_ref"]}


def _section_difference(
    left: dict[str, object], right: dict[str, object], section: str
) -> dict[str, object] | None:
    difference = _first_difference(left[section], right[section], f"/{section}")
    if difference is None:
        return None
    difference["section"] = section
    difference["left_trace_ref"] = None
    difference["right_trace_ref"] = None
    if section in _TRACE_ORDER:
        index = int(cast("str", difference["json_pointer"]).split("/")[2])
        difference["left_trace_ref"] = _trace_reference(left, section, index)
        difference["right_trace_ref"] = _trace_reference(right, section, index)
    return difference


def _compare_documents(
    left_document: dict[str, object], right_document: dict[str, object]
) -> dict[str, object]:
    conditions: list[dict[str, object]] = []
    for category, condition_field in _CONDITIONS:
        difference = _first_difference(
            left_document[condition_field], right_document[condition_field], f"/{condition_field}"
        )
        if difference is not None:
            difference["category"] = category
            # Keep the complete condition, even if several engine/version fields
            # changed and the pointer identifies only the first differing leaf.
            difference["left_condition"] = left_document[condition_field]
            difference["right_condition"] = right_document[condition_field]
            conditions.append(difference)
    first_divergence = next(
        (
            difference
            for section in _SEMANTIC_ORDER
            if (difference := _section_difference(left_document, right_document, section))
            is not None
        ),
        None,
    )
    return {
        "kind": "replay_qualification_comparison_v1",
        "schema_version": 1,
        "strictly_paired": not conditions,
        "condition_differences": conditions,
        "semantically_equal": first_divergence is None,
        "first_divergence": first_divergence,
        "first_decision_divergence": _section_difference(
            left_document, right_document, "decision_trace"
        ),
        "comparison_order": list(_SEMANTIC_ORDER),
    }


def compare_replay_results(left: ReplayResult, right: ReplayResult) -> ReplayComparison:
    """Compare verified DTOs without ignoring any declared running condition.

    Semantic equality covers all five traces, termination status and completeness.
    It is an observation, not a scientific verdict, engine equivalence proof, or
    permission to treat different data/specifications/environments as paired.
    """
    return ReplayComparison(left, right)
