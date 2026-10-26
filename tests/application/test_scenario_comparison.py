"""Pair committed saved-native runs without spending budget or trusting loose hashes."""

import json
from pathlib import Path

import pytest

from tickwitness.application.experiments import ProtocolRunError, freeze_experiment, run_experiment
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.scenario_comparison import compare_scenario_runs
from tickwitness.application.scenario_execution import run_scenario
from tickwitness.domain.evidence.run_records import EvidenceValidationError, digest, parse
from tickwitness.domain.evidence.scenario_records import load_scenario_run_receipt
from tickwitness.domain.replay.contracts import build_replay_result
from tickwitness.infrastructure.attempt_ledger import AttemptLedgerError, LocalAttemptLedger
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter


def requests() -> tuple[bytes, bytes]:
    examples = Path(__file__).resolve().parents[2] / "examples"
    assumption = (examples / "assumption-request.json").read_bytes()
    scenario = json.loads((examples / "scenario-request.json").read_bytes())
    scenario["additional_delay"]["value"] = 0
    return assumption, json.dumps(scenario).encode()


def baseline(case, **changes):
    options = {
        "split": "development",
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
        "ledger_factory": case.ledger_factory,
        "engine_factory": case.engine_factory,
    }
    options.update(changes)
    return run_experiment(case.frozen.protocol_id, **options)


def scenario(case, *, protocol_id=None):
    return run_scenario(
        case.frozen.protocol_id if protocol_id is None else protocol_id,
        *requests(),
        split="development",
        registry_factory=lambda: case.registry,
        datasets_factory=lambda: case.data,
        ledger_factory=case.ledger_factory,
        engine_factory=case.engine_factory,
    )


def compare(case, left, right, **changes):
    options = {
        "split": "development",
        "ledger_factory": case.ledger_factory,
        "registry_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
    }
    options.update(changes)
    return compare_scenario_runs(left.run_id, right.run_id, **options)


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_zero_pair_is_a_deterministic_read_only_query_after_budget_is_exhausted(
    experiment_case, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = experiment_case
    left, right = baseline(case), scenario(case)
    before = snapshot(case.root)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Pairing cannot reserve, publish or invoke a native engine")

    for method in ("reserve", "publish", "bind_intent"):
        monkeypatch.setattr(LocalAttemptLedger, method, forbidden)
    monkeypatch.setattr(SubprocessReplayAdapter, "__init__", forbidden)
    report = compare(case, left, right)
    repeated = compare(case, left, right)
    assert report.canonical_bytes == repeated.canonical_bytes
    assert report.comparison_id == repeated.comparison_id == digest(report.canonical_bytes)
    document = report.document
    assert document["controlled_intervention"] is True
    assert document["strictly_paired"] is False
    assert document["bindings"]["baseline"]["run_id"] == left.run_id
    assert document["bindings"]["scenario"]["run_id"] == right.run_id
    assert document["numeric_comparison"]["status"] == "comparable"
    assert document["numeric_comparison"]["baseline_value"] == "-2"
    assert document["numeric_comparison"]["scenario_value"] == "-2"
    assert document["numeric_comparison"]["delta"] == "0"
    assert document["trace_comparison"]["business_trace_changed"] is False
    assert document["trace_comparison"]["business"]["first_divergence"] is None
    assert document["scope"]["baseline_claim_recomputed_for_integrity"] is True
    assert document["scope"]["scenario_claim_evaluated"] is False
    assert document["scope"]["claim_verdict_issued"] is False
    document["numeric_comparison"]["delta"] = "99"
    assert report.document == repeated.document
    assert snapshot(case.root) == before


@pytest.mark.parametrize("split", ["confirmation", "invalid", "DEVELOPMENT"])
def test_denied_split_precedes_identity_and_every_repository_factory(split: str) -> None:
    def forbidden():
        raise AssertionError("Denied comparison cannot access repositories")

    with pytest.raises(ConfirmationAccessDenied):
        compare_scenario_runs(
            "../invalid",
            "not-an-id",
            split=split,
            ledger_factory=forbidden,
            registry_factory=forbidden,
            datasets_factory=forbidden,
        )


@pytest.mark.parametrize("bad_id", ["../escape", "A" * 64, "0" * 63, True])
@pytest.mark.parametrize("side", ["baseline", "scenario"])
def test_bad_identity_precedes_every_factory(bad_id, side: str) -> None:
    def forbidden():
        raise AssertionError("Invalid identity cannot access repositories")

    values = {"baseline": "0" * 64, "scenario": "1" * 64, side: bad_id}
    with pytest.raises(EvidenceValidationError):
        compare_scenario_runs(
            values["baseline"],
            values["scenario"],
            split="development",
            ledger_factory=forbidden,
            registry_factory=forbidden,
            datasets_factory=forbidden,
        )


def test_reversed_roles_and_same_run_are_rejected_before_source_read(experiment_case) -> None:
    case = experiment_case
    left, right = baseline(case), scenario(case)

    def forbidden():
        raise AssertionError("Invalid run roles cannot read source data")

    for first, second in ((right, left), (left, left), (right, right)):
        with pytest.raises(EvidenceValidationError):
            compare(case, first, second, datasets_factory=forbidden)


def test_cross_protocol_pair_is_rejected_before_source_read(experiment_case) -> None:
    case = experiment_case
    left = baseline(case)
    request = json.loads(json.dumps(case.request))
    request["claim"]["threshold"] = "-4"
    other = freeze_experiment(
        json.dumps(request).encode(),
        development_dataset_id=case.development,
        confirmation_dataset_id=case.confirmation,
        datasets_factory=lambda: case.data,
        registry_factory=lambda: case.registry,
    )
    right = scenario(case, protocol_id=other.protocol_id)

    def forbidden():
        raise AssertionError("Unrelated protocols cannot read source observations")

    with pytest.raises(EvidenceValidationError):
        compare(case, left, right, datasets_factory=forbidden)


def test_environment_change_is_not_silently_accepted_as_controlled_pair(experiment_case) -> None:
    case = experiment_case
    saved = case.engine_factory(60)

    class DifferentMetadata:
        def run(self, replay_input):
            document = saved.run(replay_input).document
            document["environment"]["python_version"] = "different-recorded-environment"
            return build_replay_result(document)

    left = baseline(case, engine_factory=lambda _timeout: DifferentMetadata())
    right = scenario(case)
    with pytest.raises(EvidenceValidationError, match=r"[Ee]nvironment"):
        compare(case, left, right)


def test_uncommitted_run_cannot_be_compared_even_if_receipt_cas_exists(experiment_case) -> None:
    case = experiment_case
    left, right = baseline(case), scenario(case)
    actual = case.ledger_factory()

    class UncommittedPort:
        def __getattr__(self, name):
            return getattr(actual, name)

        def get_outcome(self, attempt_id):
            return None if attempt_id == left.attempt_id else actual.get_outcome(attempt_id)

    with pytest.raises(EvidenceValidationError, match="committed"):
        compare(case, left, right, ledger_factory=UncommittedPort)


@pytest.mark.parametrize("interrupted", [False, True])
def test_failed_or_interrupted_attempt_identity_is_not_a_successful_scenario_run(
    experiment_case, interrupted: bool
) -> None:
    case = experiment_case
    left = baseline(case)

    def fail(_timeout):
        if interrupted:
            raise KeyboardInterrupt()
        raise RuntimeError("Synthetic worker failure before any result")

    with pytest.raises(KeyboardInterrupt if interrupted else ProtocolRunError):
        run_scenario(
            case.frozen.protocol_id,
            *requests(),
            split="development",
            registry_factory=lambda: case.registry,
            datasets_factory=lambda: case.data,
            ledger_factory=case.ledger_factory,
            engine_factory=fail,
        )
    slot = case.root / "runs" / "slots" / case.frozen.protocol_id / "0002.json"
    attempt_id = digest(slot.read_bytes())

    def forbidden():
        raise AssertionError("An attempt reservation cannot be compared as an audited run")

    with pytest.raises(EvidenceValidationError):
        compare_scenario_runs(
            left.run_id,
            attempt_id,
            split="development",
            ledger_factory=case.ledger_factory,
            registry_factory=lambda: case.registry,
            datasets_factory=forbidden,
        )


@pytest.mark.parametrize(
    "role",
    [
        "baseline_result",
        "baseline_evaluation",
        "scenario_result",
        "scenario_evaluation",
        "scenario_intent",
        "derived_view",
        "derived_tape",
    ],
)
def test_real_cas_corruption_never_yields_a_comparison(experiment_case, role: str) -> None:
    case = experiment_case
    left, right = baseline(case), scenario(case)
    ledger = case.ledger_factory()
    base = parse(ledger.read_artifact(left.run_id))
    stress = load_scenario_run_receipt(ledger.read_artifact(right.run_id)).document
    content_hash = {
        "baseline_result": base["bindings"]["replay_result_sha256"],
        "baseline_evaluation": base["bindings"]["evaluation_sha256"],
        "scenario_result": stress["bindings"]["replay_result_sha256"],
        "scenario_evaluation": stress["bindings"]["evaluation_sha256"],
        "scenario_intent": right.intent_id,
        "derived_view": right.derived_view_id,
        "derived_tape": stress["intent"]["bindings"]["derived_normalized_sha256"],
    }[role]
    path = case.root / "runs" / "objects" / "sha256" / content_hash
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AttemptLedgerError):
        compare(case, left, right)
