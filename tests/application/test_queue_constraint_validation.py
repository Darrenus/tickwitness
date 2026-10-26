"""Queue declarations bind saved development evidence without native execution."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.datasets import import_events
from tickwitness.application.experiments import freeze_experiment
from tickwitness.application.queue_constraints import validate_queue_contracts
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.assumptions.queue_constraints import QueueConstraintValidationError
from tickwitness.domain.evidence.run_records import digest
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

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def case(root: Path):
    raw = (EXAMPLES / "queue-observations.jsonl").read_bytes()
    data = LocalDatasetStore(root / "data")
    development = import_events(raw, lambda: data).dataset_id
    confirmation = json.loads(raw.splitlines()[0])
    confirmation.update(
        capture_seq=100,
        last_sequence=100,
        event_time_ns=1_700_000_010_000_000_000,
        receive_time_ns=1_700_000_010_000_000_100,
    )
    confirmation_id = import_events(
        (json.dumps(confirmation) + "\n").encode(), lambda: data
    ).dataset_id
    registry = LocalExecutableProtocolRegistry(root / "registry")
    request = json.loads((EXAMPLES / "experiment-request.json").read_bytes())
    frozen = freeze_experiment(
        json.dumps(request).encode(),
        development_dataset_id=development,
        confirmation_dataset_id=confirmation_id,
        registry_factory=lambda: registry,
        datasets_factory=lambda: data,
    )
    return SimpleNamespace(
        root=root,
        data=data,
        registry=registry,
        frozen=frozen,
        development=development,
        confirmation=confirmation_id,
        protocol_request=request,
    )


def request() -> dict:
    return json.loads((EXAMPLES / "queue-constraint-request.json").read_bytes())


def validate(saved, proposed=None, **changes):
    options = {
        "split": "development",
        "registry_factory": lambda: saved.registry,
        "datasets_factory": lambda: saved.data,
    }
    options.update(changes)
    return validate_queue_contracts(
        saved.frozen.protocol_id,
        json.dumps(request() if proposed is None else proposed).encode(),
        **options,
    )


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_real_source_two_shadow_allocations_remain_read_only_and_unapproved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = case(tmp_path)
    before = snapshot(tmp_path)
    accesses = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Constraint checks cannot construct execution or write evidence")

    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    monkeypatch.setattr(LocalDatasetStore, "publish", forbidden)
    monkeypatch.setattr(LocalExecutableProtocolRegistry, "seal", forbidden)

    class DevelopmentOnly:
        def get(self, dataset_id):
            accesses.append(dataset_id)
            assert dataset_id == saved.development
            return saved.data.get(dataset_id)

        def read_normalized(self, dataset_id, *, max_bytes):
            accesses.append(dataset_id)
            assert dataset_id == saved.development
            return saved.data.read_normalized(dataset_id, max_bytes=max_bytes)

    receipt = validate(saved, datasets_factory=DevelopmentOnly)
    document = receipt.document
    assert set(document) == {"constraint_id", "validation_id", "constraint", "validation"}
    assert document["constraint_id"] == digest(receipt.constraint.canonical_bytes)
    assert document["validation_id"] == digest(receipt.validation.canonical_bytes)
    constraint, validation = document["constraint"], document["validation"]
    expected_bindings = {
        "protocol_id": saved.frozen.protocol_id,
        "development_dataset_id": saved.development,
        "normalized_sha256": digest(saved.data.read_normalized(saved.development)),
        "replay_spec_id": saved.frozen.document["replay_spec_id"],
    }
    assert constraint["bindings"] == validation["bindings"] == expected_bindings
    assert validation["constraint_id"] == document["constraint_id"]
    assert validation["source_bindings_verified"] is True
    assert validation["flow_conservation_verified"] is True
    for value in (constraint, validation):
        assert value["classification"] == "MODEL_SENSITIVITY_CANDIDATE"
        assert value["actual_acceptance_verified"] is False
        assert value["impact_compatibility_verified"] is False
        assert value["native_execution_verified"] is False
        assert value["execution_approved"] is False
    interpretations = validation["interpretations"]
    assert [value["policy_id"] for value in interpretations] == [
        "cancel_front_first_v1",
        "cancel_back_first_v1",
    ]
    assert interpretations[0]["final_state"] == {
        "ahead_lots": 0,
        "behind_lots": 2,
        "external_lots": 2,
    }
    assert interpretations[1]["final_state"] == {
        "ahead_lots": 2,
        "behind_lots": 0,
        "external_lots": 2,
    }
    for interpretation in interpretations:
        assert [row["source_ref"]["capture_seq"] for row in interpretation["trace"]] == list(
            range(1, 7)
        )
    assert (
        not {
            "fill_trace",
            "account_trace",
            "valuation",
            "metric_observation",
            "claim_observation",
            "findings",
        }
        & validation.keys()
    )
    assert accesses and set(accesses) == {saved.development}
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "runs").exists()


def test_canonical_receipts_are_stable_and_document_mutations_are_detached(tmp_path: Path) -> None:
    saved = case(tmp_path)
    first = validate(saved)
    repeated = validate_queue_contracts(
        saved.frozen.protocol_id,
        json.dumps(request(), sort_keys=True, indent=2).encode(),
        split="development",
        registry_factory=lambda: saved.registry,
        datasets_factory=lambda: saved.data,
    )
    assert first.document == repeated.document
    assert first.constraint.canonical_bytes == repeated.constraint.canonical_bytes
    assert first.validation.canonical_bytes == repeated.validation.canonical_bytes
    document = first.document
    document["constraint"]["execution_approved"] = True
    document["validation"]["interpretations"][0]["final_state"]["ahead_lots"] = 99
    assert first.document == repeated.document


@pytest.mark.parametrize("split", ["confirmation", "unknown", "DEVELOPMENT"])
def test_denied_split_precedes_identity_request_and_repository_factories(split: str) -> None:
    def forbidden():
        raise AssertionError("Denied queue access cannot initialize a repository")

    with pytest.raises(ConfirmationAccessDenied):
        validate_queue_contracts(
            "../bad-id",
            b"invalid JSON",
            split=split,
            registry_factory=forbidden,
            datasets_factory=forbidden,
        )


@pytest.mark.parametrize("protocol_id", [True, "0" * 63, "A" * 64, "../escape"])
def test_invalid_identity_precedes_repository_factories(protocol_id) -> None:
    def forbidden():
        raise AssertionError("Invalid identity cannot initialize a repository")

    with pytest.raises(QueueConstraintValidationError):
        validate_queue_contracts(
            protocol_id,
            b"{}",
            split="development",
            registry_factory=forbidden,
            datasets_factory=forbidden,
        )


@pytest.mark.parametrize("conflict", ["record_id", "content_id", "invalid_content"])
def test_conflicting_protocol_fails_before_source_factory(tmp_path: Path, conflict: str) -> None:
    saved = case(tmp_path)
    stored = saved.registry.get(saved.frozen.protocol_id)
    requested = "0" * 64 if conflict == "content_id" else saved.frozen.protocol_id

    class Registry:
        def get(self, _identity):
            return SimpleNamespace(
                protocol_id="0" * 64 if conflict == "record_id" else requested,
                canonical_bytes=b"{}" if conflict == "invalid_content" else stored.canonical_bytes,
            )

    def forbidden():
        raise AssertionError("Invalid protocol cannot inspect source data")

    with pytest.raises(
        ProtocolValidationError if conflict == "invalid_content" else QueueConstraintValidationError
    ):
        validate_queue_contracts(
            requested,
            json.dumps(request()).encode(),
            split="development",
            registry_factory=Registry,
            datasets_factory=forbidden,
        )


@pytest.mark.parametrize(
    "mutation",
    ["bindings", "basis", "impact", "entry", "flow", "duplicate_trade", "missing_checkpoint"],
)
def test_invalid_constraint_is_not_execution_or_failure_evidence(
    tmp_path: Path, mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = case(tmp_path)
    proposed = request()
    if mutation == "bindings":
        proposed["bindings"] = {"protocol_id": saved.frozen.protocol_id}
    elif mutation == "basis":
        proposed["parameter_basis"]["calibration_status"] = "calibrated"
    elif mutation == "impact":
        proposed["assumptions"]["impact"] = "observation_compatible"
    elif mutation == "entry":
        proposed["entry_capture_seq"] = True
    elif mutation == "flow":
        proposed["updates"][0]["additions_lots"] = 4
    elif mutation == "duplicate_trade":
        proposed["updates"][2]["trade_capture_seqs"] = [4, 4]
    else:
        proposed["updates"].pop()
    before = snapshot(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid queue declarations cannot access execution")

    monkeypatch.setattr(LocalAttemptLedger, "__init__", forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    with pytest.raises(QueueConstraintValidationError):
        validate(saved, proposed)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("change", ["record", "normalized"])
def test_source_record_and_normalized_evidence_are_independently_checked(
    tmp_path: Path, change: str
) -> None:
    saved = case(tmp_path)

    class Source:
        def get(self, dataset_id):
            return saved.data.get(saved.confirmation if change == "record" else dataset_id)

        def read_normalized(self, dataset_id, *, max_bytes):
            if change == "normalized":
                return b"{}\n"
            return saved.data.read_normalized(dataset_id, max_bytes=max_bytes)

    with pytest.raises(QueueConstraintValidationError):
        validate(saved, datasets_factory=Source)
    assert not (tmp_path / "runs").exists()


def test_source_revalidation_enforces_frozen_event_budget(tmp_path: Path) -> None:
    saved = case(tmp_path)
    proposed_protocol = saved.protocol_request
    proposed_protocol["budget"]["max_events"] = 5
    protocol = build_executable_protocol(
        json.dumps(proposed_protocol).encode(),
        development_dataset_id=saved.development,
        confirmation_dataset_id=saved.confirmation,
    )
    saved.registry.seal(protocol.canonical_bytes)
    with pytest.raises(QueueConstraintValidationError):
        validate_queue_contracts(
            protocol.protocol_id,
            json.dumps(request()).encode(),
            split="development",
            registry_factory=lambda: saved.registry,
            datasets_factory=lambda: saved.data,
        )
    assert not (tmp_path / "runs").exists()


def test_missing_registry_is_not_created_and_precedes_source_factory(tmp_path: Path) -> None:
    def forbidden():
        raise AssertionError("Missing registry cannot open a dataset store")

    with pytest.raises(ExecutableProtocolNotFoundError):
        validate_queue_contracts(
            "0" * 64,
            b"{}",
            split="development",
            registry_factory=lambda: LocalExecutableProtocolRegistry(
                tmp_path / "absent", create=False
            ),
            datasets_factory=forbidden,
        )
    assert not (tmp_path / "absent").exists()


def test_missing_source_store_is_not_created(tmp_path: Path) -> None:
    saved = case(tmp_path / "saved")
    missing = tmp_path / "absent-data"
    with pytest.raises(DatasetStoreError):
        validate(saved, datasets_factory=lambda: LocalDatasetStore(missing, create=False))
    assert not missing.exists()
