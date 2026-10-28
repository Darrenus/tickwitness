"""Confirmation authority never resets stable origin exposure or grants execution."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_executable_protocol import build as executable_source
from test_research_protocols import _build as frozen_source

from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.research_contracts.confirmation import (
    SCOPE,
    ConfirmationAlreadyExposed,
    ConfirmationValidationError,
    build_confirmation_exposure,
    build_confirmation_protocol,
    footprints_overlap,
    load_confirmation_exposure,
    load_confirmation_protocol,
    load_origin_footprint,
    origin_footprint,
)


def event(*, kind="snapshot", capture=2, sequence=20, trade_id="trade-1", **changes):
    row = {
        "schema_version": 1,
        "type": kind,
        "source": "synthetic",
        "instrument": "TEST-USD",
        "session": "confirmation-test",
        "capture_seq": capture,
        "event_time_ns": capture * 100,
        "receive_time_ns": None,
    }
    if kind == "trade":
        row.update(trade_id=trade_id, price_ticks=101, quantity_lots=2, aggressor_side="sell")
    else:
        row.update(last_sequence=sequence, bids=[[99, 5]], asks=[[101, 5]])
        if kind == "delta":
            row["first_sequence"] = sequence
    row.update(changes)
    return row


def tape(*records):
    return normalize_events(b"".join(canonical(row) + b"\n" for row in records)).normalized_bytes


def request(**changes):
    return canonical(
        {
            "kind": "confirmation_request_v1",
            "schema_version": 1,
            "title": "One frozen window",
            "max_events": 1000,
            **changes,
        }
    )


def build(*, source=None, data=None, **changes):
    return build_confirmation_protocol(
        request(**changes),
        source_protocol=(source or frozen_source()).canonical_bytes,
        confirmation_normalized=data or tape(event()),
    )


@pytest.mark.parametrize("source_factory", [frozen_source, executable_source])
def test_independent_exact_authority_preserves_source_and_has_no_execution_grant(source_factory):
    source = source_factory()
    protocol = build(source=source)
    document = protocol.document
    assert load_confirmation_protocol(protocol.canonical_bytes) == protocol
    assert protocol.protocol_id == digest(protocol.canonical_bytes)
    assert document["source_protocol"] == source.document
    assert document["source_protocol"]["read_policy"] == "development_only_v1"
    assert document["bindings"] == {
        "source_protocol_id": source.protocol_id,
        "source_claim_revision_id": source.claim_revision_id,
        "development_dataset_id": "a" * 64,
        "confirmation_dataset_id": "b" * 64,
        "confirmation_normalized_sha256": digest(tape(event())),
        "confirmation_event_count": 1,
        "origin_footprint_id": origin_footprint((event(),)).footprint_id,
    }
    assert document["scope"] == SCOPE
    document["scope"]["engine_execution_authorized"] = True
    assert protocol.document["scope"]["engine_execution_authorized"] is False
    with pytest.raises(ConfirmationValidationError):
        replace(protocol, protocol_id="0" * 64)


def test_origin_identity_ignores_capture_clocks_and_market_payload():
    initial = event(kind="trade")
    revised = event(
        kind="trade",
        capture=50,
        event_time_ns=9999,
        receive_time_ns=9998,
        price_ticks=203,
        quantity_lots=7,
    )
    first, second = origin_footprint((initial,)), origin_footprint((revised,))
    assert first == second
    assert footprints_overlap(first, second)
    left, right = build(data=tape(initial)), build(data=tape(revised))
    assert left.protocol_id != right.protocol_id
    assert (
        left.document["bindings"]["origin_footprint_id"]
        == right.document["bindings"]["origin_footprint_id"]
    )


def test_closed_book_intervals_intersect_despite_slicing_and_resegmentation():
    full = origin_footprint(
        (
            event(),
            event(kind="delta", capture=3, sequence=23, first_sequence=21),
            event(kind="delta", capture=4, sequence=25, first_sequence=24),
        )
    )
    resegmented = origin_footprint(
        (event(), event(kind="delta", capture=3, sequence=25, first_sequence=21))
    )
    assert full == resegmented
    assert full.document["streams"][0]["book_intervals"] == [[20, 25]]
    assert footprints_overlap(full, origin_footprint((event(sequence=22),)))
    assert not footprints_overlap(full, origin_footprint((event(sequence=26),)))
    assert not footprints_overlap(
        full, origin_footprint((event(sequence=22, session="another-trusted-session"),))
    )


def test_trade_overlap_requires_stable_identity_and_stream():
    first = origin_footprint((event(kind="trade"),))
    assert not footprints_overlap(
        first, origin_footprint((event(kind="trade", trade_id="trade-2"),))
    )
    assert not footprints_overlap(
        first, origin_footprint((event(kind="trade", instrument="OTHER-USD"),))
    )
    assert footprints_overlap(
        first, origin_footprint((event(kind="trade", capture=99, quantity_lots=999),))
    )


@pytest.mark.parametrize(
    "right_intervals,expected",
    [([[2, 4]], True), ([[3, 5], [9, 11], [15, 17]], False), ([[3, 5], [9, 12]], True)],
)
def test_book_interval_scan_preserves_closed_endpoints_and_disjoint_interleaving(
    right_intervals, expected
):
    left_document = origin_footprint((event(),)).document
    left_document["streams"][0]["book_intervals"] = [[0, 2], [6, 8], [12, 14]]
    right_document = deepcopy(left_document)
    right_document["streams"][0]["book_intervals"] = right_intervals
    left = load_origin_footprint(canonical(left_document))
    right = load_origin_footprint(canonical(right_document))
    assert footprints_overlap(left, right) is expected
    assert footprints_overlap(right, left) is expected


@pytest.mark.parametrize(
    "change", ["unknown", "boolean", "uncoalesced", "unsorted", "empty", "float", "duplicate"]
)
def test_footprint_loader_rejects_rehashed_noncanonical_coverage(change):
    document = origin_footprint((event(),)).document
    stream = document["streams"][0]
    if change == "unknown":
        document["capture_identity"] = "override"
    elif change == "boolean":
        stream["book_intervals"] = [[True, 20]]
    elif change == "uncoalesced":
        stream["book_intervals"] = [[20, 20], [21, 22]]
    elif change == "unsorted":
        stream["trade_ids"] = ["z", "a"]
    elif change == "empty":
        stream["book_intervals"] = []
    elif change == "float":
        stream["book_intervals"] = [[20.0, 20]]
    else:
        document["streams"].append(deepcopy(stream))
    with pytest.raises(ConfirmationValidationError):
        load_origin_footprint(canonical(document))


@pytest.mark.parametrize(
    "changes",
    [
        {"max_events": True},
        {"max_events": 0},
        {"max_events": 1001},
        {"title": "bad\nname"},
        {"kind": "other"},
        {"override": True},
    ],
)
def test_invalid_request_never_creates_confirmation_authority(changes):
    with pytest.raises(ConfirmationValidationError):
        build(**changes)


def test_confirmation_requires_whole_accepted_canonical_window_within_frozen_limits():
    data = tape(event(), event(kind="trade", capture=3))
    with pytest.raises(ConfirmationValidationError):
        build(data=data, max_events=1)
    with pytest.raises(ConfirmationValidationError):
        build(data=json.dumps(event()).encode() + b"\n")
    with pytest.raises(ConfirmationValidationError):
        build_confirmation_protocol(
            request(), source_protocol=frozen_source().canonical_bytes, confirmation_normalized=b""
        )
    source = frozen_source().document
    source["budget"]["max_events"] = 1
    with pytest.raises(ConfirmationValidationError):
        build_confirmation_protocol(
            request(), source_protocol=canonical(source), confirmation_normalized=data
        )


@pytest.mark.parametrize(
    "change", ["scope", "binding", "hash", "policy", "source", "schema", "whitespace"]
)
def test_rehashed_protocol_cannot_expand_permission_or_rewrite_source_binding(change):
    document = build().document
    if change == "scope":
        document["scope"]["historical_unseen_certified"] = True
    elif change == "binding":
        document["bindings"]["source_protocol_id"] = "f" * 64
    elif change == "hash":
        document["bindings"]["origin_footprint_id"] = "f" * 64
    elif change == "policy":
        document["read_policy"]["id"] = "reopen_v1"
    elif change == "source":
        document["source_protocol"]["read_policy"] = "confirmation_access"
    elif change == "schema":
        document["schema_version"] = True
    raw = json.dumps(document, indent=2).encode() if change == "whitespace" else canonical(document)
    with pytest.raises(ConfirmationValidationError):
        load_confirmation_protocol(raw)


def test_exposure_is_immutable_consumption_with_actual_conflict_records():
    protocol = build()
    exposure = build_confirmation_exposure(protocol)
    assert load_confirmation_exposure(exposure.canonical_bytes) == exposure
    assert exposure.document["state"] == "EXPOSED"
    assert exposure.document["confirmation_protocol_id"] == protocol.protocol_id
    assert "output_succeeded" not in exposure.document
    assert ConfirmationAlreadyExposed((exposure,)).exposures == (exposure,)
    changed = exposure.document
    changed["origin_footprint_id"] = "f" * 64
    with pytest.raises(ConfirmationValidationError):
        load_confirmation_exposure(canonical(changed))
    changed = exposure.document
    changed["state"] = "UNEXPOSED"
    with pytest.raises(ConfirmationValidationError):
        load_confirmation_exposure(canonical(changed))
    with pytest.raises(ConfirmationValidationError):
        ConfirmationAlreadyExposed(())


def test_profile_bounds_and_duplicate_json_are_rejected(monkeypatch):
    valid = build()
    monkeypatch.setattr(
        "tickwitness.domain.research_contracts.confirmation.MAX_CONFIRMATION_PROTOCOL_BYTES",
        len(valid.canonical_bytes) - 1,
    )
    with pytest.raises(ConfirmationValidationError):
        load_confirmation_protocol(valid.canonical_bytes)
    with pytest.raises(ConfirmationValidationError):
        build_confirmation_protocol(
            b'{"kind":"confirmation_request_v1","kind":"confirmation_request_v1"}',
            source_protocol=frozen_source().canonical_bytes,
            confirmation_normalized=tape(event()),
        )
