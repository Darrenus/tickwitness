"""Original-budget, durable-correlation and fail-closed automatic evaluation tests."""

import json
import secrets

import pytest

from tickwitness.application.experiments import run_experiment
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_execution import inspect_search_campaign, run_search_plan
from tickwitness.application.search_planning import freeze_search_plan
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest, parse
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.domain.research_contracts.executable import load_executable_protocol
from tickwitness.domain.search.execution import SearchExecutionValidationError
from tickwitness.infrastructure.attempt_ledger import AttemptLedgerError
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError


def prepare(case, *, values=None, seed=17):
    assumption = {
        "kind": "assumption_request_v1", "schema_version": 1,
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "transform": {"semantic_id": "replay_receive_suffix_shift_v1", "from_capture_seq": 2},
        "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
        "parameter_basis": {"kind": "researcher_defined", "calibration_status": "uncalibrated",
                            "calibration_evidence_refs": []},
    }
    candidates = [0, 0, 30_000_000] if values is None else values
    request = {"kind": "search_plan_request_v1", "schema_version": 1, "search_seed": seed,
               "max_proposals": len(candidates), "generator": {"kind": "grid", "values_ns": candidates}}
    return freeze_search_plan(
        case.frozen.protocol_id, canonical(assumption), canonical(request), split="development",
        registry_factory=lambda: case.registry, datasets_factory=lambda: case.data,
        plans_factory=lambda: LocalSearchPlanRegistry(case.root / "plans", create=True),
    )["plan_id"]


def factories(case):
    return {
        "split": "development",
        "plans_factory": lambda: LocalSearchPlanRegistry(case.root / "plans"),
        "registry_factory": lambda: case.registry, "datasets_factory": lambda: case.data,
        "ledger_factory": case.ledger_factory,
        "ledger_reader_factory": lambda: LocalAttemptLedger(case.root / "runs", create=False),
        "campaigns_factory": lambda: LocalSearchCampaignStore(case.root / "runs", create=True),
        "engine_factory": case.engine_factory, "nonce_factory": lambda: secrets.token_hex(16),
    }


def run(case, plan_id, **changes):
    options = factories(case)
    options.update(changes)
    return run_search_plan(plan_id, **options)


def inspect(case, plan_id, **changes):
    options = factories(case)
    options.pop("engine_factory")
    options.pop("nonce_factory")
    options.pop("ledger_reader_factory")
    options["ledger_factory"] = lambda: LocalAttemptLedger(case.root / "runs", create=False)
    options["campaigns_factory"] = lambda: LocalSearchCampaignStore(case.root / "runs")
    options.update(changes)
    return inspect_search_campaign(plan_id, **options)


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def forbidden(*_args, **_kwargs):
    raise AssertionError("This stage must not invoke another port or worker")


def test_completed_campaign_reuses_original_budget_and_repeat_never_executes(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    baseline = run_experiment(
        case.frozen.protocol_id, split="development", registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data, ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )
    report = run(case, plan_id)
    assert report["status"] == "completed" and report["exit_code"] == 0
    assert report["stop_reason"] == "planned_candidates_exhausted"
    assert report["counts"] == {"eligible": 1, "dispatched": 1, "reserved": 1,
                                "completed": 1, "failed": 0, "incomplete": 0, "unfinalized": 0}
    candidate = report["candidates"][0]
    assert candidate["attempt_index"] == 2
    assert candidate["attempt_id"] != baseline.attempt_id
    assert candidate["evaluation"]["metric_observation"]["value"] == "-2"
    assert candidate["raw_result_audited"] is True
    assert candidate["reservation_link_present"] is True
    assert report["scope"]["finding_issued"] is False
    assert candidate["evaluation"]["scope"]["search_performed"] is False
    before = tree(case.root)
    assert inspect(case, plan_id) == report
    assert run(case, plan_id, engine_factory=forbidden, nonce_factory=forbidden) == report
    assert tree(case.root) == before
    other = prepare(case, seed=18)
    stopped = run(case, other, engine_factory=forbidden)
    assert stopped["exit_code"] == 8
    assert stopped["candidates"][0]["status"] == "BUDGET_EXHAUSTED"
    assert stopped["candidates"][0]["budget_consumed"] is False
    assert stopped["counts"]["reserved"] == 0


def test_worker_is_constructed_after_dispatch_slot_link_and_intent(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    seen = []

    def engine(timeout):
        store, ledger = LocalSearchCampaignStore(case.root / "runs"), case.ledger_factory()
        dispatch = parse(store.get_dispatch(plan_id, 1))
        reservation = ledger.list_reservations(
            load_executable_protocol(case.registry.get(case.frozen.protocol_id).canonical_bytes)
        )[0]
        assert reservation.document["nonce"] == dispatch["reservation_nonce"]
        assert parse(store.get_link(plan_id, 1))["reservation"] == reservation.document
        assert parse(ledger.get_intent(reservation.attempt_id)) == dispatch["intent"]
        assert ledger.get_outcome(reservation.attempt_id) is None
        seen.append(reservation.attempt_id)
        return case.engine_factory(timeout)

    report = run(case, plan_id, engine_factory=engine)
    assert seen == [report["candidates"][0]["attempt_id"]]


def test_second_candidate_failure_preserves_first_and_stops_suffix(experiment_case):
    case = experiment_case
    plan_id = prepare(case, values=[0, 1, 2])
    calls = []

    def engine(timeout):
        calls.append(timeout)
        if len(calls) > 1:
            raise RuntimeError("injected worker startup failure\nwith detail")
        return case.engine_factory(timeout)

    report = run(case, plan_id, engine_factory=engine)
    assert report["status"] == "stopped" and report["exit_code"] == 7
    assert [row["status"] for row in report["candidates"]] == ["COMPLETED", "FAILED", "NOT_DISPATCHED"]
    assert report["counts"]["reserved"] == 2 and len(calls) == 2
    assert report["candidates"][0]["evaluation"]["metric_observation"]["value"] == "-2"
    assert inspect(case, plan_id) == report
    assert run(case, plan_id, engine_factory=forbidden) == report


def test_missing_engine_is_committed_failure_not_a_candidate_refusal(experiment_case):
    case = experiment_case
    plan_id = prepare(case, values=[0, 1])

    def missing(_timeout):
        raise ReplayProcessError("engine_unavailable", "missing optional dependency", 6)

    report = run(case, plan_id, engine_factory=missing)
    assert report["exit_code"] == 6 and report["counts"]["reserved"] == 1
    assert [row["status"] for row in report["candidates"]] == ["FAILED", "NOT_DISPATCHED"]
    assert report["candidates"][0]["raw_result_sha256"] is None
    assert report["candidates"][0]["error"]["code"] == "engine_unavailable"


@pytest.mark.parametrize("committed", [False, True])
def test_reservation_exception_uses_nonce_recovery_and_never_claims_no_consumption(experiment_case, committed):
    case = experiment_case
    plan_id = prepare(case, values=[0, 1])
    actual = case.ledger_factory()

    class UncertainLedger:
        def __getattr__(self, name):
            return getattr(actual, name)

        def reserve_with_nonce(self, owner, nonce):
            if committed:
                actual.reserve_with_nonce(owner, nonce)
            raise AttemptLedgerError("reservation publication uncertain")

    report = run(case, plan_id, ledger_factory=UncertainLedger, engine_factory=forbidden)
    candidate = report["candidates"][0]
    assert report["exit_code"] == 3 and report["stop_reason"] == "reservation_unconfirmed"
    assert candidate["budget_consumed"] is (True if committed else None)
    assert candidate["status"] == ("RESERVED_UNFINALIZED" if committed else "RESERVATION_UNCONFIRMED")
    assert candidate["reservation_link_present"] is False
    assert report["candidates"][1]["status"] == "NOT_DISPATCHED"
    assert inspect(case, plan_id) == report
    assert run(case, plan_id, engine_factory=forbidden) == report


def test_link_publication_failure_is_recoverable_from_original_nonce(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    actual = LocalSearchCampaignStore(case.root / "runs", create=True)

    class LinkFailure:
        def __getattr__(self, name):
            return getattr(actual, name)

        def write_link(self, *_args):
            raise OSError("link did not commit")

    report = run(case, plan_id, campaigns_factory=LinkFailure, engine_factory=forbidden)
    assert report["candidates"][0]["budget_consumed"] is True
    assert report["candidates"][0]["status"] == "RESERVED_UNFINALIZED"
    assert inspect(case, plan_id) == report


def test_success_outcome_committed_then_response_error_does_not_become_failure(experiment_case):
    case = experiment_case
    plan_id = prepare(case, values=[0, 1])
    actual = case.ledger_factory()

    class LostResponse:
        def __getattr__(self, name):
            return getattr(actual, name)

        def publish(self, reservation, outcome, *, artifacts=()):
            actual.publish(reservation, outcome, artifacts=artifacts)
            raise AttemptLedgerError("response lost after durable commit")

    report = run(case, plan_id, ledger_factory=LostResponse)
    assert report["stop_reason"] == "publication_unconfirmed" and report["exit_code"] == 3
    assert [row["status"] for row in report["candidates"]] == ["COMPLETED", "NOT_DISPATCHED"]
    assert report["candidates"][0]["run_id"] == report["candidates"][0]["outcome_id"]
    assert inspect(case, plan_id) == report


def test_audit_rejection_keeps_captured_raw_result_without_marking_it_audited(experiment_case):
    case = experiment_case
    plan_id = prepare(case)

    def corrupt(timeout):
        underlying = case.engine_factory(timeout)

        class BadAccounting:
            def run(self, source):
                document = underlying.run(source).document
                document["account_trace"][-1]["fields"]["cash_total"] = "999"
                return build_replay_result(document)

        return BadAccounting()

    report = run(case, plan_id, engine_factory=corrupt)
    candidate = report["candidates"][0]
    assert candidate["status"] == "FAILED" and candidate["budget_consumed"] is True
    raw = LocalSearchCampaignStore(case.root / "runs").get_result(plan_id, 1)
    assert raw is not None and candidate["raw_result_sha256"] == digest(raw)
    assert candidate["raw_result_audited"] is False
    assert candidate["evaluation"] is None
    assert inspect(case, plan_id) == report


def test_interrupt_leaves_reserved_unfinalized_and_repeat_does_not_resume(experiment_case):
    case = experiment_case
    plan_id = prepare(case, values=[0, 1])

    def interrupt(_timeout):
        raise KeyboardInterrupt("simulated process interruption")

    with pytest.raises(KeyboardInterrupt):
        run(case, plan_id, engine_factory=interrupt)
    report = inspect(case, plan_id)
    assert report["status"] == "unfinalized" and report["stop"] is None
    assert [row["status"] for row in report["candidates"]] == ["RESERVED_UNFINALIZED", "NOT_DISPATCHED"]
    assert report["candidates"][0]["budget_consumed"] is True
    assert run(case, plan_id, engine_factory=forbidden) == report


def test_zero_eligible_plan_still_has_no_findings_or_budget_reservation(experiment_case):
    case = experiment_case
    plan_id = prepare(case, values=[30_000_000, 30_000_000])
    report = run(case, plan_id, engine_factory=forbidden)
    assert report["status"] == "completed" and report["stop_reason"] == "no_eligible_candidates"
    assert report["counts"]["reserved"] == 0
    assert report["scope"]["finding_issued"] is False


@pytest.mark.parametrize("operation", ["run", "inspect"])
def test_confirmation_and_bad_ids_fail_before_factories(operation):
    options = {"split": "confirmation", "plans_factory": forbidden, "registry_factory": forbidden,
               "datasets_factory": forbidden, "ledger_factory": forbidden, "campaigns_factory": forbidden}
    call = run_search_plan if operation == "run" else inspect_search_campaign
    if operation == "run":
        options.update(engine_factory=forbidden, nonce_factory=forbidden, ledger_reader_factory=forbidden)
    with pytest.raises(ConfirmationAccessDenied):
        call("bad", **options)
    options["split"] = "development"
    with pytest.raises(EvidenceValidationError):
        call("bad", **options)


@pytest.mark.parametrize("role", ["dispatch", "link", "result", "stop", "header"])
def test_inspect_rejects_changed_execution_artifacts_even_with_canonical_rehash(experiment_case, role):
    case = experiment_case
    plan_id = prepare(case)
    run(case, plan_id)
    root = case.root / "runs" / "search-campaigns" / plan_id
    paths = {"dispatch": root / "dispatches" / "0001.json", "link": root / "links" / "0001.json",
             "result": root / "results" / "0001.json", "stop": root / "stop.json", "header": root / "campaign.json"}
    path = paths[role]
    document = json.loads(path.read_bytes())
    if role == "dispatch":
        document["reservation_nonce"] = "f" * 32
    elif role == "link":
        document["reservation"]["attempt_index"] = 2
    elif role == "result":
        document["account_trace"][-1]["fields"]["cash_total"] = "999"
    elif role == "stop":
        document["reason"] = "no_eligible_candidates"
    else:
        document["scope"]["claim_evaluated"] = True
    path.write_bytes(canonical(document))
    before = tree(case.root)
    with pytest.raises((EvidenceValidationError, ValueError)):
        inspect(case, plan_id)
    assert tree(case.root) == before


def test_unknown_candidate_file_cannot_be_ignored(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    run(case, plan_id)
    root = case.root / "runs" / "search-campaigns" / plan_id
    (root / "dispatches" / "0002.json").write_bytes((root / "dispatches" / "0001.json").read_bytes())
    with pytest.raises(SearchExecutionValidationError, match="extra"):
        inspect(case, plan_id)


def test_source_corruption_before_run_never_creates_execution_root(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    path = case.root / "data" / "objects" / "sha256" / digest(case.raw)
    path.write_bytes(case.raw + b" ")
    with pytest.raises(ValueError):
        run(case, plan_id, engine_factory=forbidden, campaigns_factory=forbidden, ledger_factory=forbidden)
    assert not (case.root / "runs").exists()


def test_failure_inspection_requires_committed_intent_even_from_a_substituting_port(experiment_case):
    case = experiment_case
    plan_id = prepare(case)

    def missing(_timeout):
        raise ReplayProcessError("engine_unavailable", "missing extra", 6)

    run(case, plan_id, engine_factory=missing)
    actual = case.ledger_factory()

    class MissingIntentPort:
        def __getattr__(self, name):
            return getattr(actual, name)

        def get_intent(self, _attempt_id):
            return None

    with pytest.raises(SearchExecutionValidationError, match="committed dispatch intent"):
        inspect(case, plan_id, ledger_factory=MissingIntentPort)


def test_intent_publication_failure_preserves_consumed_slot_without_starting_worker(experiment_case):
    case = experiment_case
    plan_id = prepare(case)
    actual = case.ledger_factory()

    class MissingIntentWriter:
        def __getattr__(self, name):
            return getattr(actual, name)

        def bind_intent(self, *_args, **_kwargs):
            raise AttemptLedgerError("intent publication unavailable")

    report = run(case, plan_id, ledger_factory=MissingIntentWriter, engine_factory=forbidden)
    assert report["stop_reason"] == "publication_unconfirmed"
    assert report["candidates"][0]["status"] == "RESERVED_UNFINALIZED"
    assert report["candidates"][0]["budget_consumed"] is True
    assert report["candidates"][0]["outcome_id"] is None
    assert inspect(case, plan_id) == report
