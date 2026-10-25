"""Observation correctness: retain evidence, reject malformed input, never repair history."""

import json
from typing import cast

import pytest

from tickwitness.domain.data_evidence import (
    DataValidationError,
    ValidationLimits,
    normalize_events,
)


def _common(event_type: str, capture_seq: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": event_type,
        "source": "fixture",
        "instrument": "SYN-USD",
        "session": "capture-1",
        "capture_seq": capture_seq,
        "event_time_ns": 100,
        "receive_time_ns": 105,
    }


def _snapshot(capture_seq: int = 1, last: int = 10) -> dict[str, object]:
    return {
        **_common("snapshot", capture_seq),
        "last_sequence": last,
        "bids": [[100, 2]],
        "asks": [[102, 3]],
    }


def _delta(capture_seq: int = 2, first: int = 11, last: int = 11) -> dict[str, object]:
    return {
        **_common("delta", capture_seq),
        "first_sequence": first,
        "last_sequence": last,
        "bids": [[100, 0]],
        "asks": [],
    }


def _trade(capture_seq: int = 3, trade_id: str = "trade-1") -> dict[str, object]:
    return {
        **_common("trade", capture_seq),
        "trade_id": trade_id,
        "price_ticks": 100,
        "quantity_lots": 1,
        "aggressor_side": "sell",
    }


def _jsonl(*records: dict[str, object]) -> bytes:
    return b"".join(
        json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n" for record in records
    )


def _rows(report: dict[str, object], key: str) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", report[key])


def _codes(report: dict[str, object]) -> list[object]:
    return [finding["code"] for finding in _rows(report, "findings")]


def _dispositions(report: dict[str, object]) -> list[object]:
    return [row["disposition"] for row in _rows(report, "record_states")]


def test_normal_snapshot_delta_trade_and_canonical_output_are_deterministic() -> None:
    raw = _jsonl(_snapshot(), _delta(), _trade())
    result = normalize_events(raw)

    assert result == normalize_events(raw)
    assert result == normalize_events(result.normalized_bytes)
    assert result.report["record_count"] == 3
    assert result.report["quality_status"] == "accepted"
    assert result.report["stream_count"] == 1
    assert result.report["findings"] == []
    assert _dispositions(result.report) == ["applied", "applied", "observed"]
    assert _rows(result.report, "book_epochs")[0] == {
        "stream": {"source": "fixture", "instrument": "SYN-USD", "session": "capture-1"},
        "epoch": 1,
        "start_line": 1,
        "end_line": 3,
        "snapshot_sequence": 10,
        "last_sequence": 11,
        "closed_by": None,
    }
    assert result.report["replay_certified"] is False
    assert result.report["book_state_reconstructed"] is False
    assert result.report["validation_scope"] == "schema_and_sequence_preflight"
    assert "full_book_state_and_crossed_book" in cast("list[str]", result.report["not_checked"])
    assert result.report["clock_binding"] == "unbound"
    json.dumps(result.report, allow_nan=False)


def test_unknown_receive_time_stays_unknown_and_clock_domains_are_not_compared() -> None:
    snapshot = {**_snapshot(), "receive_time_ns": None}
    delta = {**_delta(), "event_time_ns": 500, "receive_time_ns": 10}
    result = normalize_events(_jsonl(snapshot, delta))

    records = [json.loads(line) for line in result.normalized_bytes.splitlines()]
    assert records[0]["receive_time_ns"] is None
    assert records[1]["receive_time_ns"] == 10
    assert result.report["unknown_receive_count"] == 1
    assert result.report["quality_status"] == "accepted"
    finding = _rows(result.report, "findings")[0]
    assert finding["code"] == "UNKNOWN_RECEIVE_TIME"
    assert finding["line"] == 1
    assert finding["stream"] == {
        "source": "fixture",
        "instrument": "SYN-USD",
        "session": "capture-1",
    }


def test_event_timestamps_do_not_reorder_captured_records() -> None:
    records = [_snapshot(), {**_delta(), "event_time_ns": 1}, _trade()]
    result = normalize_events(_jsonl(*records))

    assert [json.loads(line)["type"] for line in result.normalized_bytes.splitlines()] == [
        "snapshot",
        "delta",
        "trade",
    ]
    assert result.report["quality_status"] == "accepted"


def test_duplicate_capture_is_retained_without_reapplication() -> None:
    snapshot = _snapshot()
    result = normalize_events(_jsonl(snapshot, snapshot, _delta()))

    assert result.report["record_count"] == 3
    assert len(result.normalized_bytes.splitlines()) == 3
    assert _dispositions(result.report) == ["applied", "ignored_duplicate", "applied"]
    assert _codes(result.report) == ["DUPLICATE_CAPTURE"]
    assert len(_rows(result.report, "book_epochs")) == 1


def test_newly_captured_duplicate_and_stale_deltas_do_not_reapply() -> None:
    result = normalize_events(
        _jsonl(_snapshot(), _delta(), _delta(3), _delta(4, 5, 6), _delta(5, 12, 12))
    )

    assert _dispositions(result.report) == [
        "applied",
        "applied",
        "ignored_duplicate",
        "ignored_stale",
        "applied",
    ]
    assert _codes(result.report) == ["DUPLICATE_DELTA", "STALE_DELTA"]
    assert _rows(result.report, "book_epochs")[0]["last_sequence"] == 12


def test_book_gap_closes_epoch_and_only_fresh_snapshot_reestablishes_state() -> None:
    result = normalize_events(
        _jsonl(
            _snapshot(),
            _delta(),
            _delta(3, 13, 13),
            _delta(4, 14, 14),
            _snapshot(5, 14),
            _delta(6, 15, 15),
        )
    )

    assert result.report["quality_status"] == "quarantined"
    assert _dispositions(result.report) == [
        "applied",
        "applied",
        "quarantined",
        "quarantined",
        "applied",
        "applied",
    ]
    assert _codes(result.report) == ["BOOK_SEQUENCE_GAP", "MISSING_VALID_SNAPSHOT"]
    first, second = _rows(result.report, "book_epochs")
    assert (first["start_line"], first["end_line"], first["last_sequence"]) == (1, 2, 11)
    assert first["closed_by"] == "BOOK_SEQUENCE_GAP"
    assert (second["start_line"], second["end_line"], second["epoch"]) == (5, 6, 2)


def test_snapshot_older_than_observed_gap_cannot_restore_the_missing_path() -> None:
    result = normalize_events(
        _jsonl(_snapshot(), _delta(2, 12, 12), _snapshot(3, 11), _snapshot(4, 12))
    )

    assert _dispositions(result.report) == ["applied", "quarantined", "ignored_stale", "applied"]
    assert "STALE_SNAPSHOT" in _codes(result.report)
    assert result.report["quality_status"] == "quarantined"


def test_delta_before_snapshot_is_importable_but_quarantined() -> None:
    result = normalize_events(_jsonl(_delta(1), _snapshot(2, 11)))

    assert _dispositions(result.report) == ["quarantined", "applied"]
    assert result.report["quality_status"] == "quarantined"
    assert _rows(result.report, "book_epochs")[0]["start_line"] == 2


def test_overlapping_delta_is_not_trimmed_or_reordered() -> None:
    result = normalize_events(_jsonl(_snapshot(), _delta(2, 10, 11)))

    assert _codes(result.report) == ["OVERLAPPING_DELTA"]
    assert _dispositions(result.report) == ["applied", "quarantined"]
    assert json.loads(result.normalized_bytes.splitlines()[1])["first_sequence"] == 10


def test_capture_gap_and_out_of_order_record_quarantine_without_sorting() -> None:
    result = normalize_events(_jsonl(_snapshot(), _delta(3), _delta(2), _snapshot(4, 11)))

    assert result.report["quality_status"] == "quarantined"
    assert "CAPTURE_SEQUENCE_GAP" in _codes(result.report)
    assert "OUT_OF_ORDER_CAPTURE" in _codes(result.report)
    assert _dispositions(result.report) == [
        "applied",
        "quarantined",
        "ignored_out_of_order",
        "applied",
    ]
    assert [json.loads(line)["capture_seq"] for line in result.normalized_bytes.splitlines()] == [
        1,
        3,
        2,
        4,
    ]


def test_conflicting_capture_id_preserves_evidence_and_terminates_epoch() -> None:
    result = normalize_events(_jsonl(_snapshot(), {**_snapshot(), "bids": [[100, 3]]}))

    assert _codes(result.report) == ["CAPTURE_SEQUENCE_CONFLICT"]
    assert _dispositions(result.report) == ["applied", "quarantined"]
    assert result.report["quality_status"] == "quarantined"


def test_conflicting_delta_range_is_not_accepted_as_a_duplicate() -> None:
    result = normalize_events(_jsonl(_snapshot(), _delta(), {**_delta(3), "bids": [[100, 3]]}))

    assert _codes(result.report) == ["DELTA_SEQUENCE_CONFLICT"]
    assert result.report["quality_status"] == "quarantined"


def test_delta_retransmission_level_order_does_not_change_semantic_identity() -> None:
    delta = {**_delta(), "bids": [[100, 0], [99, 3]], "asks": [[102, 5], [103, 7]]}
    reordered = {**_delta(3), "bids": [[99, 3], [100, 0]], "asks": [[103, 7], [102, 5]]}
    result = normalize_events(_jsonl(_snapshot(), delta, reordered))

    assert result.report["quality_status"] == "accepted"
    assert _codes(result.report) == ["DUPLICATE_DELTA"]
    assert _dispositions(result.report) == ["applied", "applied", "ignored_duplicate"]
    retained = [json.loads(line) for line in result.normalized_bytes.splitlines()]
    assert retained[1]["bids"] == [[100, 0], [99, 3]]
    assert retained[2]["bids"] == [[99, 3], [100, 0]]
    assert retained[2]["asks"] == [[103, 7], [102, 5]]
    assert delta["bids"] == [[100, 0], [99, 3]]
    assert reordered["asks"] == [[103, 7], [102, 5]]


def test_reordered_delta_with_changed_quantity_is_still_a_conflict() -> None:
    delta = {**_delta(), "bids": [[100, 0], [99, 3]], "asks": [[102, 5], [103, 7]]}
    changed = {**_delta(3), "bids": [[99, 4], [100, 0]], "asks": [[103, 7], [102, 5]]}
    result = normalize_events(_jsonl(_snapshot(), delta, changed))

    assert result.report["quality_status"] == "quarantined"
    assert _codes(result.report) == ["DELTA_SEQUENCE_CONFLICT"]
    assert _dispositions(result.report) == ["applied", "applied", "quarantined"]


def test_duplicate_trade_and_conflicting_trade_id_are_distinguished() -> None:
    duplicate = normalize_events(_jsonl(_snapshot(), _trade(2), _trade(3)))
    conflict = normalize_events(_jsonl(_snapshot(), _trade(2), {**_trade(3), "quantity_lots": 2}))

    assert _codes(duplicate.report) == ["DUPLICATE_TRADE"]
    assert _dispositions(duplicate.report) == ["applied", "observed", "ignored_duplicate"]
    assert duplicate.report["quality_status"] == "accepted"
    assert _codes(conflict.report) == ["TRADE_ID_CONFLICT"]
    assert conflict.report["quality_status"] == "quarantined"
    assert len(conflict.normalized_bytes.splitlines()) == 3


def test_streams_have_independent_capture_and_book_sequences() -> None:
    other = {"instrument": "OTHER-USD"}
    result = normalize_events(
        _jsonl(_snapshot(), {**_snapshot(), **other}, _delta(), {**_delta(), **other})
    )

    assert result.report["stream_count"] == 2
    assert result.report["quality_status"] == "accepted"
    assert len(_rows(result.report, "book_epochs")) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("capture_seq", True),
        ("capture_seq", 0),
        ("capture_seq", 1 << 63),
        ("event_time_ns", False),
        ("event_time_ns", -1),
        ("event_time_ns", 1 << 63),
        ("receive_time_ns", "unknown"),
        ("receive_time_ns", 1 << 63),
        ("last_sequence", 1 << 63),
        ("last_sequence", True),
        ("source", ""),
        ("source", " padded "),
        ("source", "bad\nidentifier"),
        ("source", "x" * 257),
        ("source", "\ud800"),
        ("type", "unknown"),
        ("bids", [[100, 0]]),
        ("bids", [[100, True]]),
        ("bids", [[True, 1]]),
        ("bids", [[100, 1], [100, 2]]),
        ("bids", [[100, 1, 2]]),
        ("asks", {}),
    ],
)
def test_invalid_snapshot_fields_fail_atomically(field: str, value: object) -> None:
    with pytest.raises(DataValidationError, match="line 2") as caught:
        normalize_events(_jsonl(_snapshot(), {**_snapshot(2), field: value}))

    assert caught.value.message == str(caught.value)


@pytest.mark.parametrize(
    "record",
    [
        {**_snapshot(), "extra": "not allowed"},
        {key: value for key, value in _snapshot().items() if key != "receive_time_ns"},
        {**_delta(), "first_sequence": 12, "last_sequence": 11},
        {**_trade(), "aggressor_side": "unknown"},
        {**_trade(), "trade_id": ""},
        {**_trade(), "price_ticks": 0},
        {**_trade(), "quantity_lots": 0},
    ],
)
def test_missing_unknown_and_type_specific_fields_are_strict(record: dict[str, object]) -> None:
    with pytest.raises(DataValidationError):
        normalize_events(_jsonl(record))


@pytest.mark.parametrize("value", [1.0, float("nan"), float("inf"), float("-inf")])
def test_float_syntax_and_nonfinite_constants_are_rejected(value: float) -> None:
    with pytest.raises(DataValidationError, match="floating-point"):
        normalize_events(_jsonl({**_snapshot(), "event_time_ns": value}))


@pytest.mark.parametrize("raw", [b"", b"\xff", b"[]", b"{}\n\n", b"\xef\xbb\xbf{}", b"{broken"])
def test_empty_non_utf8_non_object_blank_and_malformed_input_are_rejected(raw: bytes) -> None:
    with pytest.raises(DataValidationError):
        normalize_events(raw)


def test_duplicate_json_keys_are_rejected_instead_of_last_value_winning() -> None:
    raw = _jsonl(_snapshot()).replace(
        b'"source":"fixture"', b'"source":"fixture","source":"replacement"'
    )
    with pytest.raises(DataValidationError, match="duplicate JSON object key"):
        normalize_events(raw)


def test_crlf_missing_final_newline_and_key_order_have_the_same_canonical_bytes() -> None:
    record = _snapshot()
    canonical = normalize_events(_jsonl(record))
    reversed_record = dict(reversed(list(record.items())))

    assert normalize_events(_jsonl(record).replace(b"\n", b"\r\n")) == canonical
    assert normalize_events(_jsonl(record).rstrip(b"\n")) == canonical
    assert normalize_events(_jsonl(reversed_record)) == canonical


def test_raw_record_line_and_depth_limits_are_enforced() -> None:
    raw = _jsonl(_snapshot())
    assert normalize_events(raw, ValidationLimits(max_bytes=len(raw))).report["record_count"] == 1
    with pytest.raises(DataValidationError, match="max_bytes"):
        normalize_events(raw, ValidationLimits(max_bytes=len(raw) - 1))
    with pytest.raises(DataValidationError, match="max_records"):
        normalize_events(_jsonl(_snapshot(), _delta()), ValidationLimits(max_records=1))
    with pytest.raises(DataValidationError, match="max_line_bytes"):
        normalize_events(raw, ValidationLimits(max_line_bytes=len(raw) - 2))
    with pytest.raises(DataValidationError, match="max_levels_per_side"):
        normalize_events(
            _jsonl({**_snapshot(), "bids": [[100, 1], [99, 1]]}),
            ValidationLimits(max_levels_per_side=1),
        )


@pytest.mark.parametrize("value", [0, -1, True])
def test_limits_require_real_positive_integers(value: int) -> None:
    with pytest.raises(DataValidationError, match="positive integer"):
        ValidationLimits(max_bytes=value)
