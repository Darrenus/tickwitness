"""Compare verified evidence without silently pairing changed conditions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from tickwitness.domain.replay.comparison import ReplayComparison, compare_replay_results
from tickwitness.domain.replay.contracts import (
    ReplayResult,
    ReplayValidationError,
    build_replay_result,
)


def row(kind: str, ordinal: int = 0, *, capture: int = 1) -> dict[str, object]:
    return {
        "kind": kind,
        "ordinal": ordinal,
        "native_time_ns": 100,
        "source_ref": {"line": capture, "capture_seq": capture, "event_type": "snapshot"},
        "fields": {"value": "original"},
    }


def document() -> dict[str, object]:
    return {
        "kind": "replay_qualification_result_v1",
        "schema_version": 1,
        "engine": {
            "id": "nautilus-trader",
            "version": "1.231.0",
            "semantic_id": "qualification-l2-v1",
        },
        "environment": {
            "python_version": "3.12.14",
            "platform": "synthetic-test-platform",
            "package_versions": {"nautilus-trader": "1.231.0"},
        },
        "dataset_id": "a" * 64,
        "data_sha256": "b" * 64,
        "spec_id": "c" * 64,
        "execution_status": "completed",
        "completeness": {
            "input_records": 1,
            "processed_records": 1,
            "open_orders": [],
            "pending_commands": [],
            "stop_reason": "input_exhausted",
        },
        "input_trace": [row("input")],
        "decision_trace": [row("submit")],
        "order_trace": [row("accepted")],
        "fill_trace": [row("fill")],
        "account_trace": [row("state")],
    }


def result(value: dict[str, object] | None = None) -> ReplayResult:
    return build_replay_result(document() if value is None else value)


def test_identical_results_have_no_divergence_and_detached_comparison_views() -> None:
    original = result()
    comparison = compare_replay_results(original, original)

    assert comparison.strictly_paired is True
    assert comparison.semantically_equal is True
    assert comparison.document["condition_differences"] == []
    assert comparison.document["first_divergence"] is None
    assert comparison.document["first_decision_divergence"] is None
    view = comparison.document
    view["strictly_paired"] = False
    assert comparison.strictly_paired is True
    assert compare_replay_results(original, original).canonical_bytes == comparison.canonical_bytes


@pytest.mark.parametrize("invalid", [b"{}", bytearray(b"{}"), {}, None])
def test_constructor_requires_verified_results_and_never_accepts_raw_receipt(
    invalid: object,
) -> None:
    with pytest.raises(ReplayValidationError, match="validated ReplayResult"):
        ReplayComparison(invalid, result())
    with pytest.raises(ReplayValidationError, match="validated ReplayResult"):
        ReplayComparison(result(), invalid)


def test_comparison_bytes_are_derived_and_frozen_including_dataclass_replace() -> None:
    original = result()
    comparison = ReplayComparison(original, original)
    with pytest.raises(FrozenInstanceError):
        comparison.canonical_bytes = b"{}"
    with pytest.raises(TypeError):
        ReplayComparison(original, original, canonical_bytes=b"{}")
    changed = document()
    changed["spec_id"] = "d" * 64
    replacement = replace(comparison, right=result(changed))
    assert replacement.strictly_paired is False
    assert comparison.strictly_paired is True


@pytest.mark.parametrize(
    ("field", "value", "category", "pointer"),
    [
        (
            "engine",
            {"id": "nautilus-trader", "version": "1.232.0", "semantic_id": "qualification-l2-v1"},
            "engine",
            "/engine/version",
        ),
        (
            "environment",
            {
                "python_version": "3.13.0",
                "platform": "synthetic-test-platform",
                "package_versions": {"nautilus-trader": "1.231.0"},
            },
            "environment",
            "/environment/python_version",
        ),
        ("spec_id", "d" * 64, "specification", "/spec_id"),
        ("dataset_id", "d" * 64, "data", "/dataset_id"),
        ("data_sha256", "d" * 64, "data", "/data_sha256"),
    ],
)
def test_changed_conditions_never_become_strictly_paired_even_with_equal_traces(
    field: str, value: object, category: str, pointer: str
) -> None:
    changed = document()
    changed[field] = value

    comparison = compare_replay_results(result(), result(changed))

    assert comparison.strictly_paired is False
    assert comparison.semantically_equal is True
    assert comparison.document["first_divergence"] is None
    assert comparison.document["condition_differences"][0]["category"] == category
    assert comparison.document["condition_differences"][0]["json_pointer"] == pointer


def test_all_changed_condition_dimensions_remain_visible() -> None:
    changed = document()
    changed["engine"]["version"] = "1.232.0"
    changed["environment"]["python_version"] = "3.13.0"
    changed["spec_id"] = "d" * 64
    changed["dataset_id"] = "e" * 64
    changed["data_sha256"] = "f" * 64

    differences = compare_replay_results(result(), result(changed)).document[
        "condition_differences"
    ]

    assert [difference["category"] for difference in differences] == [
        "engine",
        "environment",
        "specification",
        "data",
        "data",
    ]
    assert differences[0]["right_condition"]["version"] == "1.232.0"


def test_multiple_engine_changes_preserve_full_versions_beyond_first_pointer() -> None:
    changed = document()
    changed["engine"] = {"id": "another-engine", "version": "2.0.0", "semantic_id": "v2"}

    difference = compare_replay_results(result(), result(changed)).document[
        "condition_differences"
    ][0]

    assert difference["json_pointer"] == "/engine/id"
    assert difference["left_condition"]["version"] == "1.231.0"
    assert difference["right_condition"]["version"] == "2.0.0"


def test_first_decision_divergence_has_stable_source_and_pointer() -> None:
    changed = document()
    changed["decision_trace"][0]["fields"]["value"] = "changed"

    comparison = compare_replay_results(result(), result(changed))
    difference = comparison.document["first_divergence"]

    assert comparison.strictly_paired is True
    assert comparison.semantically_equal is False
    assert difference["json_pointer"] == "/decision_trace/0/fields/value"
    assert difference["left_trace_ref"] == {
        "channel": "decision_trace",
        "ordinal": 0,
        "source_ref": {"line": 1, "capture_seq": 1, "event_type": "snapshot"},
    }
    assert difference["right_trace_ref"] == difference["left_trace_ref"]
    assert comparison.document["first_decision_divergence"] == difference


def test_input_and_decision_differences_are_separately_reported_when_data_changed() -> None:
    changed = document()
    changed["data_sha256"] = "d" * 64
    changed["input_trace"][0]["fields"]["value"] = "changed input"
    changed["decision_trace"][0]["fields"]["value"] = "changed decision"

    comparison = compare_replay_results(result(), result(changed)).document

    assert comparison["strictly_paired"] is False
    assert comparison["first_divergence"]["section"] == "input_trace"
    assert comparison["first_decision_divergence"]["section"] == "decision_trace"


def test_same_timestamp_second_fill_is_not_deduplicated() -> None:
    left = document()
    left["input_trace"].append(row("input", 1, capture=2))
    left["completeness"]["input_records"] = 2
    left["completeness"]["processed_records"] = 2
    left["fill_trace"].append(row("fill", 1, capture=2))
    right = deepcopy(left)
    right["fill_trace"][1]["fields"]["value"] = "changed second fill"

    difference = compare_replay_results(result(left), result(right)).document["first_divergence"]

    assert difference["json_pointer"] == "/fill_trace/1/fields/value"
    assert difference["left_trace_ref"]["ordinal"] == 1
    assert difference["left_trace_ref"]["source_ref"]["capture_seq"] == 2


@pytest.mark.parametrize("missing_left", [False, True])
def test_missing_trace_row_has_presence_and_available_side_reference(missing_left: bool) -> None:
    shorter = document()
    shorter["fill_trace"] = []
    left, right = (result(shorter), result()) if missing_left else (result(), result(shorter))

    difference = compare_replay_results(left, right).document["first_divergence"]

    assert difference["json_pointer"] == "/fill_trace/0"
    assert difference["left_present"] is not missing_left
    assert difference["right_present"] is missing_left
    assert (difference["left_trace_ref"] is None) is missing_left
    assert (difference["right_trace_ref"] is None) is not missing_left


def test_json_pointer_escaping_and_strict_boolean_integer_distinction() -> None:
    left = document()
    left["account_trace"][0]["fields"] = {"a/b~c": True}
    right = deepcopy(left)
    right["account_trace"][0]["fields"]["a/b~c"] = 1

    difference = compare_replay_results(result(left), result(right)).document["first_divergence"]

    assert difference["json_pointer"] == "/account_trace/0/fields/a~1b~0c"
    assert difference["left_value"] is True
    assert type(difference["right_value"]) is int


def test_completeness_is_semantic_evidence_even_when_traces_match() -> None:
    left = document()
    left["execution_status"] = "incomplete"
    left["completeness"]["stop_reason"] = "input_exhausted_with_open_orders"
    left["completeness"]["open_orders"] = [{"order_id": "order-1", "status": "ACCEPTED"}]
    right = deepcopy(left)
    right["completeness"]["open_orders"][0]["status"] = "PARTIALLY_FILLED"

    comparison = compare_replay_results(result(left), result(right))
    difference = comparison.document["first_divergence"]

    assert comparison.semantically_equal is False
    assert difference["json_pointer"] == "/completeness/open_orders/0/status"
    assert difference["left_trace_ref"] is None
    assert difference["right_trace_ref"] is None


def test_failure_status_is_not_ignored_when_observed_traces_match() -> None:
    changed = document()
    changed["execution_status"] = "failed"
    changed["completeness"]["stop_reason"] = "engine_error"

    comparison = compare_replay_results(result(), result(changed)).document

    assert comparison["semantically_equal"] is False
    assert comparison["first_divergence"]["json_pointer"] == "/execution_status"
    assert comparison["first_decision_divergence"] is None


def test_fixed_channel_order_does_not_sort_away_native_trace_order() -> None:
    changed = document()
    changed["decision_trace"][0]["native_time_ns"] = 50
    changed["fill_trace"][0]["native_time_ns"] = 10

    comparison = compare_replay_results(result(), result(changed)).document

    assert comparison["first_divergence"]["section"] == "decision_trace"
    assert comparison["comparison_order"] == [
        "input_trace",
        "decision_trace",
        "order_trace",
        "fill_trace",
        "account_trace",
        "execution_status",
        "completeness",
    ]
