"""Scenario checks bind real saved development evidence without running research."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.scenarios import validate_scenario_contracts
from tickwitness.domain.assumptions import AssumptionValidationError
from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.research_contracts.executable import (
    ProtocolValidationError,
    build_executable_protocol,
)
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import (
    ExecutableProtocolNotFoundError,
    LocalExecutableProtocolRegistry,
)
from tickwitness.infrastructure.local_dataset_store import DatasetStoreError, LocalDatasetStore
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def requests() -> tuple[dict, dict]:
    return (
        {
            "kind": "assumption_request_v1",
            "schema_version": 1,
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "transform": {
                "semantic_id": "replay_receive_suffix_shift_v1",
                "from_capture_seq": 2,
            },
            "additional_delay": {"minimum": 0, "maximum": 20_000_000, "unit": "ns"},
            "parameter_basis": {
                "kind": "researcher_defined",
                "calibration_status": "uncalibrated",
                "calibration_evidence_refs": [],
            },
        },
        {
            "kind": "scenario_request_v1",
            "schema_version": 1,
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "additional_delay": {"value": 20_000_000, "unit": "ns"},
        },
    )


def validate(case, assumption=None, scenario=None, **changes):
    default_assumption, default_scenario = requests()
    arguments = {
        "split": "development",
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
    }
    arguments.update(changes)
    return validate_scenario_contracts(
        case.frozen.protocol_id,
        json.dumps(default_assumption if assumption is None else assumption).encode(),
        json.dumps(default_scenario if scenario is None else scenario).encode(),
        **arguments,
    )


def test_real_development_bindings_are_checked_without_replay_or_attempts(
    experiment_case, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    original = case.data.read_normalized(case.development)
    catalog = tuple(record.dataset_id for record in case.data.list_datasets())
    protocols = tuple((case.root / "registry" / "protocols").iterdir())
    access = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Contract validation must not start an engine or reserve an attempt")

    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "publish", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "seal", forbidden)

    class DevelopmentOnlyReader:
        def get(self, dataset_id):
            access.append(dataset_id)
            assert dataset_id == case.development
            return case.data.get(dataset_id)

        def read_normalized(self, dataset_id, *, max_bytes):
            access.append(dataset_id)
            assert dataset_id == case.development
            return case.data.read_normalized(dataset_id, max_bytes=max_bytes)

    receipt = validate(case, datasets_factory=DevelopmentOnlyReader)

    document = receipt.document
    assumption, scenario, validation = (
        document["assumption"],
        document["scenario"],
        document["validation"],
    )
    expected_bindings = {
        "protocol_id": case.frozen.protocol_id,
        "development_dataset_id": case.development,
        "normalized_sha256": hashlib.sha256(original).hexdigest(),
        "replay_spec_id": case.frozen.document["replay_spec_id"],
    }
    assert assumption["bindings"] == expected_bindings
    assert scenario["assumption_id"] == receipt.assumption_id
    assert validation["bindings"] == expected_bindings
    assert validation["assumption_id"] == receipt.assumption_id
    assert validation["scenario_id"] == receipt.scenario_id
    assert validation["source_bindings_verified"] is True
    assert validation["input_constraints_verified"] is True
    assert validation["execution_approved"] is False
    assert validation["calibration_status"] == "uncalibrated"
    assert validation["scenario_kind"] == "COUNTERFACTUAL_STRESS"
    assert validation["additional_delay"] == {"value": 20_000_000, "unit": "ns"}
    assert access
    assert set(access) == {case.development}
    assert case.data.read_normalized(case.development) == original
    assert tuple(record.dataset_id for record in case.data.list_datasets()) == catalog
    assert tuple((case.root / "registry" / "protocols").iterdir()) == protocols
    assert not (case.root / "runs").exists()


def test_canonical_identity_is_stable_and_documents_are_detached(experiment_case) -> None:
    case = experiment_case
    assumption, scenario = requests()
    first = validate(case, assumption, scenario)
    repeated = validate_scenario_contracts(
        case.frozen.protocol_id,
        json.dumps(assumption, sort_keys=True, indent=2).encode(),
        json.dumps(scenario, sort_keys=True, indent=2).encode(),
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
    )
    assert (first.assumption_id, first.scenario_id) == (
        repeated.assumption_id,
        repeated.scenario_id,
    )
    document = first.document
    document["assumption"]["bindings"]["development_dataset_id"] = case.confirmation
    document["validation"]["execution_approved"] = True
    assert first.document == repeated.document

    scenario["additional_delay"]["value"] = 0
    different_candidate = validate(case, assumption, scenario)
    assert different_candidate.assumption_id == first.assumption_id
    assert different_candidate.scenario_id != first.scenario_id
    assumption["additional_delay"]["maximum"] = 30_000_000
    different_range = validate(case, assumption, scenario)
    assert different_range.assumption_id != first.assumption_id
    assert different_range.scenario_id != different_candidate.scenario_id


@pytest.mark.parametrize("split", ["confirmation", "unknown", "DEVELOPMENT"])
def test_non_development_denial_precedes_identity_requests_and_factories(split: str) -> None:
    def forbidden():
        raise AssertionError("Denied access must not initialize or inspect repositories")

    with pytest.raises(ConfirmationAccessDenied):
        validate_scenario_contracts(
            "../invalid-protocol",
            b"not json",
            b"not json",
            split=split,
            registry_factory=forbidden,
            datasets_factory=forbidden,
        )


@pytest.mark.parametrize("protocol_id", ["../escape", "A" * 64, "0" * 63, True])
def test_invalid_identity_does_not_open_either_repository(protocol_id) -> None:
    def forbidden():
        raise AssertionError("Invalid identity must fail before repository access")

    with pytest.raises(AssumptionValidationError, match="identity"):
        validate_scenario_contracts(
            protocol_id,
            b"{}",
            b"{}",
            split="development",
            registry_factory=forbidden,
            datasets_factory=forbidden,
        )


@pytest.mark.parametrize("conflict", ["record_identity", "content_identity", "invalid_content"])
def test_registry_identity_and_protocol_bytes_are_independently_checked(
    experiment_case, conflict: str
) -> None:
    case = experiment_case
    stored = case.registry.get(case.frozen.protocol_id)
    requested = "0" * 64 if conflict == "content_identity" else case.frozen.protocol_id
    record = SimpleNamespace(
        protocol_id="0" * 64 if conflict == "record_identity" else requested,
        canonical_bytes=b"{}" if conflict == "invalid_content" else stored.canonical_bytes,
    )

    class ConflictingRegistry:
        def get(self, protocol_id):
            assert protocol_id == requested
            return record

    def forbidden():
        raise AssertionError("Conflicting executable evidence must fail before data access")

    assumption, scenario = requests()
    with pytest.raises(
        ProtocolValidationError if conflict == "invalid_content" else AssumptionValidationError
    ):
        validate_scenario_contracts(
            requested,
            json.dumps(assumption).encode(),
            json.dumps(scenario).encode(),
            split="development",
            registry_factory=ConflictingRegistry,
            datasets_factory=forbidden,
        )


def test_missing_registry_is_not_created(tmp_path) -> None:
    def forbidden():
        raise AssertionError("Missing protocol must fail before opening data")

    with pytest.raises(ExecutableProtocolNotFoundError):
        validate_scenario_contracts(
            "0" * 64,
            b"{}",
            b"{}",
            split="development",
            registry_factory=lambda: LocalExecutableProtocolRegistry(
                tmp_path / "registry", create=False
            ),
            datasets_factory=forbidden,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["range", "anchor", "kind", "calibration", "candidate"])
def test_invalid_or_unsupported_contract_never_becomes_executable(
    experiment_case, failure: str
) -> None:
    case = experiment_case
    assumption, scenario = requests()
    if failure == "range":
        assumption["additional_delay"]["maximum"] = -1
    elif failure == "anchor":
        assumption["transform"]["from_capture_seq"] = 999
    elif failure == "kind":
        assumption["scenario_kind"] = "HISTORICAL_INTERPRETATION"
    elif failure == "calibration":
        assumption["parameter_basis"]["calibration_status"] = "calibrated"
    else:
        scenario["additional_delay"]["value"] = 20_000_001

    with pytest.raises(AssumptionValidationError):
        validate(case, assumption, scenario)
    assert not (case.root / "runs").exists()


@pytest.mark.parametrize("forgery", ["certified", "quarantined", "typed_record_count"])
def test_self_consistent_store_report_cannot_bless_invalid_quality(
    experiment_case, forgery: str
) -> None:
    case = experiment_case
    normalized = normalize_events(case.raw)
    report = dict(normalized.report)
    if forgery == "certified":
        report["replay_certified"] = True
    elif forgery == "quarantined":
        report["quality_status"] = "quarantined"
    else:
        report["record_count"] = float(report["record_count"])
    forged = case.data.publish(case.raw, normalized.normalized_bytes, report)
    protocol = build_executable_protocol(
        json.dumps(case.request).encode(),
        development_dataset_id=forged.dataset_id,
        confirmation_dataset_id=case.confirmation,
    )
    case.registry.seal(protocol.canonical_bytes)
    assumption, scenario = requests()

    with pytest.raises(AssumptionValidationError, match="report"):
        validate_scenario_contracts(
            protocol.protocol_id,
            json.dumps(assumption).encode(),
            json.dumps(scenario).encode(),
            split="development",
            registry_factory=lambda: case.registry,
            datasets_factory=lambda: case.data,
        )
    assert not (case.root / "runs").exists()


def test_raw_object_tampering_is_not_hidden_by_normalized_bytes(experiment_case) -> None:
    case = experiment_case
    raw_path = case.root / "data" / "objects" / "sha256" / hashlib.sha256(case.raw).hexdigest()
    raw_path.write_bytes(case.raw + b" ")

    with pytest.raises(DatasetStoreError):
        validate(case)
    assert not (case.root / "runs").exists()


def test_valid_declarations_still_obey_the_frozen_event_budget(experiment_case) -> None:
    case = experiment_case
    request = dict(
        case.request,
        budget={"max_attempts": 2, "max_wall_seconds": 60, "max_events": 1},
    )
    protocol = build_executable_protocol(
        json.dumps(request).encode(),
        development_dataset_id=case.development,
        confirmation_dataset_id=case.confirmation,
    )
    case.registry.seal(protocol.canonical_bytes)
    assumption, scenario = requests()

    with pytest.raises(AssumptionValidationError, match="event budget"):
        validate_scenario_contracts(
            protocol.protocol_id,
            json.dumps(assumption).encode(),
            json.dumps(scenario).encode(),
            split="development",
            registry_factory=lambda: case.registry,
            datasets_factory=lambda: case.data,
        )
    assert not (case.root / "runs").exists()
