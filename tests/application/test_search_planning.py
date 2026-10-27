"""Source and publication boundaries for candidate planning, without a replay worker."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.search_planning import freeze_search_plan, inspect_search_plan
from tickwitness.domain.assumptions.specs import AssumptionValidationError
from tickwitness.domain.evidence.run_records import EvidenceValidationError
from tickwitness.domain.research_contracts.executable import build_executable_protocol
from tickwitness.domain.search.plans import SearchPlanValidationError
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry


def requests():
    assumption = {
        "kind": "assumption_request_v1",
        "schema_version": 1,
        "scenario_kind": "COUNTERFACTUAL_STRESS",
        "transform": {"semantic_id": "replay_receive_suffix_shift_v1", "from_capture_seq": 4},
        "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
        "parameter_basis": {
            "kind": "researcher_defined",
            "calibration_status": "uncalibrated",
            "calibration_evidence_refs": [],
        },
    }
    search = {
        "kind": "search_plan_request_v1",
        "schema_version": 1,
        "search_seed": 17,
        "max_proposals": 4,
        "generator": {"kind": "grid", "values_ns": [0, 0, 10_000_000, 30_000_000]},
    }
    return assumption, search


def freeze(case, *, assumption=None, search=None, plans_factory=None, **overrides):
    default_assumption, default_search = requests()
    arguments = {
        "split": "development",
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
        "plans_factory": plans_factory or (
            lambda: LocalSearchPlanRegistry(case.root / "plans", create=True)
        ),
    }
    arguments.update(overrides)
    return freeze_search_plan(
        case.frozen.protocol_id,
        json.dumps(assumption if assumption is not None else default_assumption).encode(),
        json.dumps(search if search is not None else default_search).encode(),
        **arguments,
    )


def inspect(case, plan_id, **overrides):
    arguments = {
        "split": "development",
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
        "plans_factory": lambda: LocalSearchPlanRegistry(case.root / "plans", create=False),
    }
    arguments.update(overrides)
    return inspect_search_plan(plan_id, **arguments)


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def forbidden():
    raise AssertionError("This boundary must fail before accessing another port")


def test_freeze_and_inspect_revalidate_source_without_creating_attempts(experiment_case):
    case = experiment_case
    original = tree(case.root)
    result = freeze(case)
    assert result["created"] is True
    assert result["plan"]["counts"] == {"proposed": 4, "eligible": 2, "duplicate": 1, "rejected": 1}
    assert [row["status"] for row in result["plan"]["journal"]] == [
        "ELIGIBLE", "DUPLICATE", "ELIGIBLE", "REJECTED"
    ]
    assert result["scope"] == {
        "execution_started": False, "attempt_reserved": False,
        "search_performed": False, "finding_issued": False,
    }
    assert result["verification"] == {
        "plan_recomputed": True, "source_revalidated": True,
        "derived_candidates_checked": True, "native_replayed": False,
    }
    after = tree(case.root)
    repeated = freeze(case)
    assert repeated == dict(result, created=False)
    assert inspect(case, result["plan_id"]) == repeated
    assert tree(case.root) == after
    assert {name: raw for name, raw in after.items() if name in original} == original
    assert not (case.root / "runs").exists()
    assert not (case.root / "ledger").exists()


@pytest.mark.parametrize("operation", ["freeze", "inspect"])
def test_confirmation_refused_before_identity_and_all_factories(operation):
    with pytest.raises(ConfirmationAccessDenied):
        if operation == "freeze":
            freeze_search_plan(
                "bad", b"bad", b"bad", split="confirmation",
                registry_factory=forbidden, datasets_factory=forbidden, plans_factory=forbidden,
            )
        else:
            inspect_search_plan(
                "bad", split="confirmation", registry_factory=forbidden,
                datasets_factory=forbidden, plans_factory=forbidden,
            )


@pytest.mark.parametrize("operation", ["freeze", "inspect"])
def test_bad_identity_does_not_open_factories(operation):
    with pytest.raises(EvidenceValidationError):
        if operation == "freeze":
            freeze_search_plan(
                "bad", b"{}", b"{}", split="development",
                registry_factory=forbidden, datasets_factory=forbidden, plans_factory=forbidden,
            )
        else:
            inspect_search_plan(
                "bad", split="development", registry_factory=forbidden,
                datasets_factory=forbidden, plans_factory=forbidden,
            )


def test_planning_reads_only_development_not_confirmation(experiment_case):
    case = experiment_case
    accessed = []

    class DevelopmentOnly:
        def get(self, dataset_id):
            assert dataset_id == case.development
            accessed.append(dataset_id)
            return case.data.get(dataset_id)

        def read_normalized(self, dataset_id, *, max_bytes):
            assert dataset_id == case.development
            return case.data.read_normalized(dataset_id, max_bytes=max_bytes)

    result = freeze(case, datasets_factory=DevelopmentOnly)
    inspect(case, result["plan_id"], datasets_factory=DevelopmentOnly)
    assert accessed == [case.development, case.development]


@pytest.mark.parametrize("failure", ["anchor", "calibrated", "unknown_search", "bad_seed"])
def test_invalid_requests_never_open_plan_writer(experiment_case, failure):
    assumption, search = requests()
    if failure == "anchor":
        assumption["transform"]["from_capture_seq"] = 99999
    elif failure == "calibrated":
        assumption["parameter_basis"]["calibration_status"] = "calibrated"
    elif failure == "unknown_search":
        search["authorize_execution"] = True
    else:
        search["search_seed"] = True
    with pytest.raises(SearchPlanValidationError):
        freeze(experiment_case, assumption=assumption, search=search, plans_factory=forbidden)


def test_derived_preflight_failure_aborts_whole_plan(experiment_case, monkeypatch):
    def invalid(_validated):
        raise AssumptionValidationError("injected derivation defect")

    monkeypatch.setattr("tickwitness.application.search_planning.derive_replay_view", invalid)
    with pytest.raises(SearchPlanValidationError, match="derivation defect"):
        freeze(experiment_case, plans_factory=forbidden)


def test_work_bound_rejects_before_any_derivation_or_publication(experiment_case, monkeypatch):
    monkeypatch.setattr("tickwitness.application.search_planning.MAX_DERIVED_EVENT_CHECKS", 1)
    monkeypatch.setattr("tickwitness.application.search_planning.derive_replay_view", forbidden)
    with pytest.raises(SearchPlanValidationError, match="work limit"):
        freeze(experiment_case, plans_factory=forbidden)


def test_all_rejected_plan_is_not_search_completion(experiment_case):
    assumption, search = requests()
    search["generator"] = {
        "kind": "random_integer_with_replacement", "minimum_ns": 30_000_000, "maximum_ns": 30_000_000,
    }
    result = freeze(experiment_case, assumption=assumption, search=search)
    assert result["plan"]["counts"] == {"proposed": 4, "eligible": 0, "duplicate": 3, "rejected": 1}
    assert result["scope"]["search_performed"] is False
    assert result["scope"]["finding_issued"] is False


def test_inspect_detects_original_raw_corruption(experiment_case):
    case = experiment_case
    plan = freeze(case)
    raw = case.root / "data" / "objects" / "sha256" / hashlib.sha256(case.raw).hexdigest()
    raw.write_bytes(case.raw + b" ")
    before = tree(case.root)
    from tickwitness.infrastructure.local_dataset_store import DatasetStoreError

    with pytest.raises(DatasetStoreError):
        inspect(case, plan["plan_id"])
    assert tree(case.root) == before


@pytest.mark.parametrize("conflict", ["id", "bytes", "created"])
def test_writer_cannot_substitute_its_receipt(experiment_case, conflict):
    class ConflictingWriter:
        def seal(self, raw):
            return SimpleNamespace(
                plan_id="0" * 64 if conflict == "id" else hashlib.sha256(raw).hexdigest(),
                canonical_bytes=b"{}" if conflict == "bytes" else raw,
                created=1 if conflict == "created" else True,
            )

    with pytest.raises(SearchPlanValidationError):
        freeze(experiment_case, plans_factory=ConflictingWriter)


def test_inspect_cannot_substitute_another_valid_plan(experiment_case):
    case = experiment_case
    original = freeze(case)
    _, search = requests()
    search["search_seed"] += 1
    another = freeze(case, search=search)
    record = LocalSearchPlanRegistry(case.root / "plans").get(another["plan_id"])

    class WrongReader:
        def get(self, _identity):
            return record

    with pytest.raises(SearchPlanValidationError, match="conflicting identity"):
        inspect(case, original["plan_id"], plans_factory=WrongReader, registry_factory=forbidden)


def test_subject_registry_cannot_substitute_valid_protocol(experiment_case):
    case = experiment_case
    plan = freeze(case)
    changed = dict(case.request, budget={"max_attempts": 3, "max_wall_seconds": 60, "max_events": 100})
    other = build_executable_protocol(
        json.dumps(changed).encode(), development_dataset_id=case.development,
        confirmation_dataset_id=case.confirmation,
    )

    class WrongSubject:
        def get(self, _identity):
            return SimpleNamespace(protocol_id=other.protocol_id, canonical_bytes=other.canonical_bytes)

    with pytest.raises(SearchPlanValidationError, match="conflicting evidence"):
        inspect(case, plan["plan_id"], registry_factory=WrongSubject, datasets_factory=forbidden)
