"""Export requires actual committed native runs and leaves the source state unchanged."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_tagged_queue_application_native import tagged_native_app as tagged_native_app
from test_tagged_queue_native import native

from tickwitness.application.tagged_pair_evidence import (
    export_tagged_pair,
    tagged_pair_artifacts,
    verify_tagged_pair_package,
)
from tickwitness.application.tagged_queue_execution import (
    run_tagged_queue_model,
    run_tagged_queue_pair,
)
from tickwitness.domain.evidence.run_records import EvidenceValidationError
from tickwitness.domain.research_contracts.tagged_queue_protocol import TAGGED_POLICY_IDS
from tickwitness.infrastructure.tagged_evidence_bundles import (
    export_tagged_pair_bundle,
    read_tagged_pair_bundle,
)
from tickwitness.infrastructure.tagged_queue_replay import NautilusTaggedQueueReplayAdapter

pytestmark = native


def _state(root: Path):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for name in ("data", "registry", "ledger")
        for path in (root / name).rglob("*")
        if path.is_file()
    }


def _ports(case):
    return {
        "ledger": case.ledger,
        "protocols": case.factories["protocols_factory"](),
        "datasets": case.factories["datasets_factory"](),
    }


def test_two_actual_native_runs_export_canonically_in_either_argument_order(
    tagged_native_app, monkeypatch
):
    case = tagged_native_app
    pair = run_tagged_queue_pair(
        case.protocol.protocol_id,
        split="development",
        replay_factory=lambda _: NautilusTaggedQueueReplayAdapter(),
        **case.factories,
    )
    assert pair["status"] == "completed"
    left, right = (run["run_id"] for run in pair["runs"])
    before = _state(case.root)

    def forbidden(*args, **kwargs):
        pytest.fail("Export cannot consume new attempts or run native")

    monkeypatch.setattr(case.ledger, "reserve", forbidden)
    monkeypatch.setattr(NautilusTaggedQueueReplayAdapter, "run", forbidden)
    artifacts = tagged_pair_artifacts(left, right, **_ports(case))
    assert tagged_pair_artifacts(right, left, **_ports(case)) == artifacts
    exported = export_tagged_pair(
        left,
        right,
        split="development",
        **case.factories,
        exporter=lambda payload: export_tagged_pair_bundle(case.root / "portable", payload),
    )
    verified = verify_tagged_pair_package(
        read_tagged_pair_bundle(case.root / "portable"), expected_bundle_id=exported["bundle_id"]
    )
    assert exported == verified
    assert verified["assessment"]["comparison"]["truths"] == [False, False]
    assert verified["ledger_commitment_checked"] is False
    assert _state(case.root) == before


def test_two_actual_runs_of_one_policy_do_not_make_a_pair_or_publish_output(tagged_native_app):
    case = tagged_native_app
    runs = [
        run_tagged_queue_model(
            case.protocol.protocol_id,
            TAGGED_POLICY_IDS[0],
            split="development",
            replay_factory=lambda _: NautilusTaggedQueueReplayAdapter(),
            **case.factories,
        )
        for _ in range(2)
    ]

    def forbidden(payload):
        pytest.fail("Invalid pair must fail before invoking exporter")

    before = _state(case.root)
    with pytest.raises(EvidenceValidationError, match="one run of each"):
        export_tagged_pair(
            runs[0].run_id,
            runs[1].run_id,
            split="development",
            **case.factories,
            exporter=forbidden,
        )
    assert _state(case.root) == before


def test_unfinalized_reservation_cannot_replace_a_completed_receipt(tagged_native_app):
    case = tagged_native_app
    first = run_tagged_queue_model(
        case.protocol.protocol_id,
        TAGGED_POLICY_IDS[0],
        split="development",
        replay_factory=lambda _: NautilusTaggedQueueReplayAdapter(),
        **case.factories,
    )
    unresolved = case.ledger.reserve(case.protocol)
    before = _state(case.root)
    with pytest.raises(EvidenceValidationError):
        tagged_pair_artifacts(first.run_id, unresolved.attempt_id, **_ports(case))
    assert _state(case.root) == before


def test_valid_portable_callbacks_do_not_bypass_original_committed_outcome_check(tagged_native_app):
    case = tagged_native_app
    pair = run_tagged_queue_pair(
        case.protocol.protocol_id,
        split="development",
        replay_factory=lambda _: NautilusTaggedQueueReplayAdapter(),
        **case.factories,
    )
    ports = _ports(case)
    ledger = SimpleNamespace(
        read_artifact=case.ledger.read_artifact,
        get_reservation=case.ledger.get_reservation,
        get_intent=case.ledger.get_intent,
        get_outcome=lambda _: None,
    )
    ports["ledger"] = ledger
    before = _state(case.root)
    with pytest.raises(EvidenceValidationError, match="committed"):
        tagged_pair_artifacts(*(run["run_id"] for run in pair["runs"]), **ports)
    assert _state(case.root) == before
