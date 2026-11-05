"""Saved offline callback facts exercise control; actual native runs qualify in CI."""

from copy import deepcopy

import pytest
from test_reduction_execution import Proxy, forbidden
from test_reduction_execution import reduction_case as reduction_case
from test_reductions import Unreadable
from test_search_findings import tree

from tickwitness.application.reduction_search import (
    ReductionSearchPublicationError,
    cancel_reduction_search,
    freeze_reduction_search,
    inspect_reduction_search,
    run_reduction_search,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    parse,
)
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.reduction_campaign_store import LocalReductionCampaignStore


def request(*, steps=3, cap=60_000):
    return canonical(
        {
            "kind": "reduction_search_request_v1",
            "schema_version": 1,
            "witness_ordinal": 1,
            "focus_from_capture_seq": 4,
            "max_steps": steps,
            "max_wall_time_ms": cap,
        }
    )


class OfflinePrefixEngine:
    """Declared consistency fixture, never a product-selectable native engine."""

    def __init__(self, value):
        self.value = value

    def run(self, replay_input):
        base = (
            self.value.case.engine_factory(60)
            .run(self.value.prepared.materialization.replay_input)
            .document
        )
        count = len(replay_input.normalized_bytes.splitlines())
        assert count in (4, 5, 6)
        document = deepcopy(base)
        document["dataset_id"] = replay_input.dataset_id
        document["data_sha256"] = digest(replay_input.normalized_bytes)
        document["environment"]["platform"] = "offline-reduction-control-fixture"
        for channel in ("input_trace", "decision_trace", "order_trace", "fill_trace"):
            document[channel] = [
                row for row in document[channel] if row["source_ref"]["capture_seq"] <= count
            ]
            for ordinal, row in enumerate(document[channel]):
                row["ordinal"] = ordinal
        accounts = [
            row
            for row in document["account_trace"]
            if row["kind"] != "final_account_snapshot"
            and (row["source_ref"] is None or row["source_ref"]["capture_seq"] <= count)
        ]
        final = deepcopy(document["account_trace"][-1])
        final.update(
            ordinal=len(accounts), native_time_ns=document["input_trace"][-1]["native_time_ns"]
        )
        if count == 4:
            final["fields"] = deepcopy(accounts[-1]["fields"])
            order = final["fields"]["orders"][0]
            document["execution_status"] = "incomplete"
            document["completeness"].update(
                open_orders=[{"order_id": order["order_id"], "status": "PARTIALLY_FILLED"}],
                stop_reason="input_exhausted_with_open_orders",
            )
        document["account_trace"] = [*accounts, final]
        document["completeness"].update(input_records=count, processed_records=count)
        return build_replay_result(document)


@pytest.fixture
def search_case(reduction_case):
    value = reduction_case
    value.store = LocalReductionCampaignStore(value.case.root / "runs", create=True)
    value.engine = lambda _timeout: OfflinePrefixEngine(value)
    return value


def freeze(value, *, steps=3, cap=60_000, **overrides):
    options = {
        "expected_bundle_id": value.source.bundle_id,
        "expected_report_id": digest(value.source.artifacts["finding_report"]),
        "split": "development",
        "ledger_factory": lambda: value.ledger,
        "store_factory": lambda: value.store,
    }
    options.update(overrides)
    return freeze_reduction_search(value.source, request(steps=steps, cap=cap), **options)


def run(value, plan_id, **overrides):
    options = {
        "source": value.source,
        "split": "development",
        "ledger_factory": lambda: value.ledger,
        "store_factory": lambda: value.store,
        "engine_factory": value.engine,
        "monotonic_ns": lambda: 1,
    }
    options.update(overrides)
    return run_reduction_search(plan_id, **options)


def inspect(value, plan_id, **overrides):
    options = {
        "source": value.source,
        "split": "development",
        "ledger_factory": lambda: value.ledger,
        "store_factory": lambda: value.store,
    }
    options.update(overrides)
    return inspect_reduction_search(plan_id, **options)


def cancel(value, plan_id, **overrides):
    options = {
        "source": value.source,
        "split": "development",
        "ledger_factory": lambda: value.ledger,
        "store_factory": lambda: value.store,
    }
    options.update(overrides)
    return cancel_reduction_search(plan_id, **options)


def test_freeze_is_header_only_idempotent_and_requires_existing_source_prefix(search_case):
    value = search_case
    before = tree(value.case.root / "runs" / "slots")
    frozen = freeze(value)
    assert frozen["native_replayed"] is frozen["attempt_reserved"] is False
    assert value.store.get_campaign(frozen["plan_id"]) == canonical(frozen["plan"])
    assert tree(value.case.root / "runs" / "slots") == before
    assert freeze(value)["plan_id"] == frozen["plan_id"]
    empty = LocalAttemptLedger(value.case.root / "empty")
    with pytest.raises(EvidenceValidationError, match="shorter"):
        freeze(value, ledger_factory=lambda: empty, store_factory=forbidden)


def test_greedy_execution_reaudits_real_cas_and_unknown_does_not_certify_minimum(search_case):
    value = search_case
    frozen = freeze(value)
    source_before = tree(value.case.root / "portable-source")
    report = run(value, frozen["plan_id"])
    assert report["stop_reason"] == "neighborhood_checked" and report["exit_code"] == 0
    assert [step["point"]["through_capture_seq"] for step in report["steps"]] == [6, 5, 4]
    assert [step["assessment"]["outcome"] for step in report["steps"]] == [
        "PRESERVED",
        "PRESERVED",
        "NOT_EVALUABLE",
    ]
    assert [step["attempt_index"] for step in report["steps"]] == [3, 4, 5]
    assert report["best"]["origin"] == "REDUCTION_RUN"
    assert report["best"]["point"] == {"through_capture_seq": 5, "additional_delay_ns": 0}
    assert report["best"]["cost"] == [5, 0]
    assert report["scope"]["global_minimum_verified"] is False
    assert report["scope"]["local_minimum_verified"] is False
    assert report["steps"][-1]["assessment"]["criterion_observation"]["truth"] is None
    assert tree(value.case.root / "portable-source") == source_before
    assert inspect(value, frozen["plan_id"]) == report


def test_existing_execution_only_inspects_without_clock_or_native_retry(search_case, monkeypatch):
    value = search_case
    plan_id = freeze(value, steps=1)["plan_id"]
    report = run(value, plan_id)
    assert report["stop_reason"] == "step_limit"
    before = tree(value.case.root)
    for name in ("reserve", "reserve_with_nonce", "bind_intent", "publish"):
        monkeypatch.setattr(value.ledger, name, forbidden)
    for name in (
        "start",
        "write_dispatch",
        "write_link",
        "write_result",
        "write_stop",
        "write_cancel",
    ):
        monkeypatch.setattr(value.store, name, forbidden)
    assert run(value, plan_id, engine_factory=forbidden, monotonic_ns=forbidden) == report
    assert inspect(value, plan_id) == report
    assert cancel(value, plan_id)["status"] == "ALREADY_TERMINAL"
    assert tree(value.case.root) == before


def test_prestart_cancel_takes_no_slot_and_duplicate_signal_is_readonly(search_case, monkeypatch):
    value = search_case
    plan_id = freeze(value)["plan_id"]
    first = cancel(value, plan_id)
    monkeypatch.setattr(value.store, "write_cancel", forbidden)
    assert cancel(value, plan_id) == first
    report = run(value, plan_id, engine_factory=forbidden)
    assert report["stop_reason"] == "cancelled" and report["counts"]["dispatched"] == 0
    assert report["best"]["origin"] == "SOURCE_WITNESS"
    assert report["cancellation"]["effective"] is True
    owner = value.prepared.materialization.source.validation.protocol
    assert len(value.ledger.list_reservations(owner)) == 2


def test_inflight_cancel_preserves_current_outcome_before_stopping_next_dispatch(search_case):
    value = search_case
    plan_id = freeze(value)["plan_id"]

    class RequestAfterRun:
        def run(self, replay_input):
            result = OfflinePrefixEngine(value).run(replay_input)
            assert cancel(value, plan_id)["status"] == "CANCEL_REQUESTED"
            return result

    report = run(value, plan_id, engine_factory=lambda _timeout: RequestAfterRun())
    assert report["stop_reason"] == "cancelled"
    assert len(report["steps"]) == 1 and report["steps"][0]["assessment"]["outcome"] == "PRESERVED"
    assert report["best"]["run_id"] == report["steps"][0]["run_id"]
    assert value.ledger.get_outcome(report["steps"][0]["attempt_id"]) is not None
    assert report["verification"]["hard_cancel_enforced"] is False


def test_elapsed_admission_cutoff_prevents_first_dispatch_without_claiming_hard_deadline(
    search_case,
):
    value = search_case
    plan_id = freeze(value, cap=1)["plan_id"]
    times = iter([0, 1_000_000, 1_000_000])
    report = run(value, plan_id, monotonic_ns=lambda: next(times), engine_factory=forbidden)
    assert report["stop_reason"] == "admission_deadline"
    assert report["steps"] == [] and report["exit_code"] == 0
    assert report["stop"]["elapsed_ns"] == 1_000_000
    assert report["verification"]["hard_total_deadline_enforced"] is False


def test_original_attempt_budget_stops_another_plan_without_engine_or_refund(search_case):
    value = search_case
    run(value, freeze(value)["plan_id"])
    owner = value.prepared.materialization.source.validation.protocol
    before = value.ledger.list_reservations(owner)
    plan_id = freeze(value, steps=4)["plan_id"]
    report = run(value, plan_id, engine_factory=forbidden)
    assert report["stop_reason"] == "original_attempt_budget_exhausted"
    assert report["exit_code"] == 8
    assert report["steps"][0]["attempt_id"] is None
    assert report["steps"][0]["budget_consumed"] is False
    assert value.ledger.list_reservations(owner) == before


def test_operational_failure_is_not_a_preservation_assessment(search_case):
    value = search_case
    plan_id = freeze(value)["plan_id"]

    def unavailable(_timeout):
        raise RuntimeError("bounded engine construction failed")

    report = run(value, plan_id, engine_factory=unavailable)
    assert report["stop_reason"] == "operational_failure" and report["exit_code"] == 7
    assert report["steps"][0]["assessment"] is None
    assert report["steps"][0]["status"] == "FAILED"
    assert report["counts"]["failed"] == 1 and report["counts"]["unfinalized"] == 0
    assert report["best"]["origin"] == "SOURCE_WITNESS"


def test_interruption_retains_consumed_unfinalized_slot_and_never_resumes(search_case):
    value = search_case
    plan_id = freeze(value)["plan_id"]

    class Interrupted:
        def run(self, _input):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(value, plan_id, engine_factory=lambda _timeout: Interrupted())
    report = run(value, plan_id, engine_factory=forbidden, monotonic_ns=forbidden)
    assert report["status"] == "UNFINALIZED" and report["exit_code"] == 3
    assert report["stop"] is None and report["steps"][0]["budget_consumed"] is True
    assert report["steps"][0]["attempt_index"] == 3
    assert value.ledger.get_outcome(report["steps"][0]["attempt_id"]) is None


@pytest.mark.parametrize("method", ["write_dispatch", "write_link", "write_result", "write_stop"])
@pytest.mark.parametrize("after_commit", [False, True])
def test_uncertain_control_publication_never_retries_or_reports_success(
    search_case,
    method,
    after_commit,
):
    value = search_case
    plan_id = freeze(value, steps=1)["plan_id"]
    calls = []
    original = getattr(value.store, method)

    def fail(*args, **kwargs):
        calls.append(args)
        if after_commit:
            original(*args, **kwargs)
        raise OSError("uncertain control publication")

    proxy = Proxy(value.store, **{method: fail})
    with pytest.raises(ReductionSearchPublicationError):
        run(value, plan_id, store_factory=lambda: proxy)
    assert len(calls) == 1
    report = inspect(value, plan_id)
    if method != "write_dispatch" or after_commit:
        owner = value.prepared.materialization.source.validation.protocol
        before = value.ledger.list_reservations(owner)
        assert run(value, plan_id, engine_factory=forbidden, monotonic_ns=forbidden) == report
        assert value.ledger.list_reservations(owner) == before
    if method in ("write_result", "write_stop"):
        assert value.ledger.get_outcome(report["steps"][0]["attempt_id"]) is not None


@pytest.mark.parametrize(
    "attack",
    [
        "assessment",
        "greedy_point",
        "operational_stop",
        "cancel_marker",
        "stop_reason_list",
        "stop_reason_object",
    ],
)
def test_rehashed_semantic_control_tampering_is_rejected_without_repair(search_case, attack):
    value = search_case
    plan_id = freeze(value, steps=1)["plan_id"]
    run(value, plan_id)
    base = value.case.root / "runs" / "reduction-campaigns" / plan_id
    if attack == "assessment":
        target = base / "results" / "0001.json"
        row = parse(target.read_bytes(), limit=128 * 1024)
        row["outcome"] = "NOT_PRESERVED"
        row["criterion_observation"]["truth"] = True
        row["criterion_observation"]["value"] = "1"
    elif attack == "greedy_point":
        target = base / "dispatches" / "0001.json"
        row = parse(target.read_bytes())
        row["point"]["through_capture_seq"] = 5
    elif attack == "operational_stop":
        target = base / "stop.json"
        row = parse(target.read_bytes())
        row.update(
            reason="operational_failure",
            exit_code=7,
            blocked_point=parse((base / "dispatches" / "0001.json").read_bytes())["point"],
            error={"code": "invented_failure", "message": "not observed", "exit_code": 7},
        )
    elif attack in ("stop_reason_list", "stop_reason_object"):
        target = base / "stop.json"
        row = parse(target.read_bytes())
        row["reason"] = [] if attack == "stop_reason_list" else {}
    else:
        target = base / "cancel.json"
        row = {"kind": "invented_cancel"}
    target.write_bytes(canonical(row))
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        inspect(value, plan_id)
    assert tree(value.case.root) == before


def test_bad_existing_cancel_fails_validation_without_attempting_to_overwrite(search_case):
    value = search_case
    plan_id = freeze(value)["plan_id"]
    path = value.case.root / "runs" / "reduction-campaigns" / plan_id / "cancel.json"
    path.write_bytes(canonical({"kind": "not_the_cancel_contract"}))
    before = tree(value.case.root)
    with pytest.raises(EvidenceValidationError):
        cancel(value, plan_id, store_factory=lambda: Proxy(value.store, write_cancel=forbidden))
    assert tree(value.case.root) == before


@pytest.mark.parametrize("operation", ["freeze", "run", "inspect", "cancel"])
def test_confirmation_rejection_precedes_identifiers_sources_and_factories(operation):
    with pytest.raises(ConfirmationAccessDenied):
        if operation == "freeze":
            freeze_reduction_search(
                Unreadable(),
                b"bad",
                expected_bundle_id="bad",
                expected_report_id="bad",
                split="confirmation",
                ledger_factory=forbidden,
                store_factory=forbidden,
            )
        else:
            function = {
                "run": run_reduction_search,
                "inspect": inspect_reduction_search,
                "cancel": cancel_reduction_search,
            }[operation]
            extras = {"engine_factory": forbidden} if operation == "run" else {}
            function(
                "bad",
                source=Unreadable(),
                split="confirmation",
                ledger_factory=forbidden,
                store_factory=forbidden,
                **extras,
            )


def test_forged_plan_does_not_authorize_source_or_budget_changes(search_case):
    value = search_case
    frozen = freeze(value)
    fake = deepcopy(frozen["plan"])
    fake["original_budget"]["max_attempts"] = 6
    fake_raw = canonical(fake)
    fake_id = digest(fake_raw)
    value.store.start(fake_id, fake_raw)
    with pytest.raises(EvidenceValidationError, match="reproduce"):
        run(value, fake_id, engine_factory=forbidden)
