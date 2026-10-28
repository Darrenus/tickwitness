"""Actual source/data preflight with irreversible memory-port release boundaries."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from test_research import freeze, request, setup_data, snapshot, trade

from tickwitness.application.confirmation import (
    freeze_confirmation_protocol,
    inspect_confirmation_protocol,
    open_confirmation_protocol,
)
from tickwitness.application.datasets import import_events
from tickwitness.application.research import ConfirmationAccessDenied, read_protocol_data
from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.research_contracts.confirmation import (
    SCOPE,
    ConfirmationAlreadyExposed,
    ConfirmationValidationError,
    build_confirmation_exposure,
    footprints_overlap,
    load_confirmation_protocol,
    load_origin_footprint,
)


def forbidden(*_args, **_kwargs):
    raise AssertionError("This path must not open data, source, or writable state")


@dataclass(frozen=True)
class Record:
    protocol_id: str
    canonical_bytes: bytes
    created: bool


class Registry:
    def __init__(self):
        self.records = {}

    def seal(self, raw):
        protocol = load_confirmation_protocol(raw)
        created = protocol.protocol_id not in self.records
        self.records[protocol.protocol_id] = Record(protocol.protocol_id, raw, False)
        return Record(protocol.protocol_id, raw, created)

    def get(self, identity):
        return self.records[identity]


class Ledger:
    def __init__(self):
        self.records = []
        self.after_commit = None
        self.race = None
        self.calls = 0

    def find_conflicts(self, footprint):
        return tuple(
            record
            for record in self.records
            if footprints_overlap(
                footprint, load_origin_footprint(canonical(record.document["origin_footprint"]))
            )
        )

    def expose(self, protocol):
        self.calls += 1
        if self.race is not None:
            self.records.append(self.race)
        footprint = load_origin_footprint(canonical(protocol.document["origin_footprint"]))
        conflicts = self.find_conflicts(footprint)
        if conflicts:
            raise ConfirmationAlreadyExposed(conflicts)
        record = build_confirmation_exposure(protocol)
        self.records.append(record)
        if self.after_commit is not None:
            return self.after_commit(record)
        return record


def confirmation_request(**changes):
    return canonical(
        {
            "kind": "confirmation_request_v1",
            "schema_version": 1,
            "title": "Confirmation release",
            "max_events": 10,
            **changes,
        }
    )


def setup(tmp_path, *, confirmation_raw=None):
    data, development, confirmation = setup_data(tmp_path)
    if confirmation_raw is not None:
        confirmation = import_events(confirmation_raw, lambda: data).dataset_id
    source = freeze(tmp_path, data, development, confirmation, request())
    from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry

    registry, ledger = Registry(), Ledger()
    options = {
        "source_factory": lambda: LocalProtocolRegistry(tmp_path / "registry", create=False),
        "datasets_factory": lambda: data,
        "confirmations_factory": lambda: registry,
        "exposures_factory": lambda: ledger,
    }
    return SimpleNamespace(
        data=data,
        source=source,
        development=development,
        confirmation=confirmation,
        registry=registry,
        ledger=ledger,
        options=options,
    )


def frozen(case, **changes):
    return freeze_confirmation_protocol(
        confirmation_request(**changes), source_protocol_id=case.source.protocol_id, **case.options
    )


def test_freeze_is_idempotent_and_first_release_commits_entire_window(tmp_path):
    case = setup(tmp_path, confirmation_raw=snapshot(3, price=199) + trade(4, event_time=400))
    first, repeated = frozen(case), frozen(case)
    assert first["created"] is True
    assert repeated["created"] is False
    assert first["protocol_id"] == repeated["protocol_id"]
    assert first["exposure_status"] == "NO_MATCHING_EXPOSURE_IN_LEDGER"
    assert not case.ledger.records
    assert "observations" not in first
    opened = open_confirmation_protocol(first["protocol_id"], **case.options)
    assert len(case.ledger.records) == 1
    assert opened["exposure_id"] == case.ledger.records[0].exposure_id
    assert opened["exposure"] == case.ledger.records[0].document
    assert opened["observations"][0]["bids"] == [[199, 5]]
    assert opened["total_records"] == len(opened["observations"]) == 2
    assert opened["truncated"] is False
    assert opened["scope"] == SCOPE
    assert opened["exposure"]["origin_footprint"] == first["document"]["origin_footprint"]
    inspected = inspect_confirmation_protocol(first["protocol_id"], **case.options)
    assert "observations" not in inspected
    assert inspected["exposure_status"] == "ALREADY_EXPOSED_IN_LEDGER"
    assert inspected["related_exposure_ids"] == [opened["exposure_id"]]
    renamed = frozen(case, title="Renaming does not restore a holdout")
    assert renamed["protocol_id"] != first["protocol_id"]
    assert renamed["exposure_status"] == "ALREADY_EXPOSED_IN_LEDGER"
    assert frozen(case)["exposure_status"] == "ALREADY_EXPOSED_IN_LEDGER"
    for protocol_id in (first["protocol_id"], renamed["protocol_id"]):
        options = {**case.options, "datasets_factory": forbidden, "source_factory": forbidden}
        with pytest.raises(ConfirmationAlreadyExposed) as caught:
            open_confirmation_protocol(protocol_id, **options)
        assert caught.value.exposures == tuple(case.ledger.records)
    assert case.ledger.calls == 1


def test_executable_source_needs_no_v1_strategy_property(experiment_case):
    case = experiment_case
    registry, ledger = Registry(), Ledger()
    options = {
        "source_factory": lambda: case.registry,
        "datasets_factory": lambda: case.data,
        "confirmations_factory": lambda: registry,
        "exposures_factory": lambda: ledger,
    }
    receipt = freeze_confirmation_protocol(
        confirmation_request(), source_protocol_id=case.frozen.protocol_id, **options
    )
    assert receipt["document"]["source_protocol"]["kind"] == "executable_research_protocol_v2"
    opened = open_confirmation_protocol(receipt["protocol_id"], **options)
    assert opened["total_records"] == 1
    assert not (case.root / "runs").exists()


@pytest.mark.parametrize("after_commit", ["error", "interrupt", "wrong_receipt"])
def test_committed_but_undelivered_window_is_never_refunded(tmp_path, after_commit):
    case = setup(tmp_path)
    receipt = frozen(case)

    def fail(record):
        if after_commit == "error":
            raise OSError("durability or output uncertainty after commit")
        if after_commit == "interrupt":
            raise KeyboardInterrupt()
        return SimpleNamespace(exposure_id="0" * 64, canonical_bytes=record.canonical_bytes)

    case.ledger.after_commit = fail
    with pytest.raises((OSError, KeyboardInterrupt, ConfirmationValidationError)):
        open_confirmation_protocol(receipt["protocol_id"], **case.options)
    assert len(case.ledger.records) == 1
    with pytest.raises(ConfirmationAlreadyExposed):
        open_confirmation_protocol(
            receipt["protocol_id"],
            **{**case.options, "source_factory": forbidden, "datasets_factory": forbidden},
        )
    assert case.ledger.calls == 1


def test_atomic_exposure_rechecks_a_race_after_initial_fresh_read(tmp_path):
    case = setup(tmp_path)
    first, other = frozen(case), frozen(case, title="Competing authority")
    competing = build_confirmation_exposure(
        load_confirmation_protocol(case.registry.get(other["protocol_id"]).canonical_bytes)
    )
    case.ledger.race = competing
    with pytest.raises(ConfirmationAlreadyExposed) as caught:
        open_confirmation_protocol(first["protocol_id"], **case.options)
    assert caught.value.exposures == (competing,)
    assert case.ledger.records == [competing]


@pytest.mark.parametrize("change", ["request_budget", "source_budget", "bad_source", "bad_data"])
def test_invalid_preflight_does_not_create_writable_confirmation_state(tmp_path, change):
    case = setup(tmp_path, confirmation_raw=snapshot(3) + trade(4, event_time=400))
    options = {**case.options, "confirmations_factory": forbidden, "exposures_factory": forbidden}
    source_id = case.source.protocol_id
    declaration = (
        confirmation_request(max_events=1) if change == "request_budget" else confirmation_request()
    )
    if change == "source_budget":
        draft = request()
        import json

        document = json.loads(draft)
        document["budget"]["max_events"] = 1
        source = freeze(
            tmp_path, case.data, case.development, case.confirmation, canonical(document)
        )
        source_id = source.protocol_id
    elif change == "bad_source":
        options["source_factory"] = lambda: SimpleNamespace(
            get=lambda _: SimpleNamespace(protocol_id=source_id, canonical_bytes=b"{}")
        )
    elif change == "bad_data":
        options["datasets_factory"] = lambda: SimpleNamespace(
            get=lambda _: SimpleNamespace(dataset_id="0" * 64, manifest={}, report={})
        )
    with pytest.raises(ConfirmationValidationError):
        freeze_confirmation_protocol(declaration, source_protocol_id=source_id, **options)
    assert not case.ledger.records


def test_open_revalidates_actual_bindings_before_consumption(tmp_path):
    case = setup(tmp_path)
    receipt = frozen(case)
    options = {
        **case.options,
        "source_factory": lambda: SimpleNamespace(
            get=lambda _: SimpleNamespace(
                protocol_id=case.source.protocol_id, canonical_bytes=b"{}"
            )
        ),
    }
    with pytest.raises(ConfirmationValidationError):
        open_confirmation_protocol(receipt["protocol_id"], **options)
    assert not case.ledger.records
    assert case.ledger.calls == 0


def test_exposure_metadata_cannot_report_unrelated_conflicts(tmp_path):
    case = setup(tmp_path)
    receipt = frozen(case)
    other = setup(tmp_path / "other", confirmation_raw=snapshot(7))
    other_receipt = frozen(other)
    exposure = build_confirmation_exposure(
        load_confirmation_protocol(other.registry.get(other_receipt["protocol_id"]).canonical_bytes)
    )
    options = {
        **case.options,
        "exposures_factory": lambda: SimpleNamespace(find_conflicts=lambda _: (exposure,)),
    }
    with pytest.raises(ConfirmationValidationError, match="does not overlap"):
        inspect_confirmation_protocol(receipt["protocol_id"], **options)


def test_old_exploration_interface_keeps_confirmation_denial_before_io(tmp_path):
    case = setup(tmp_path)
    receipt = frozen(case)
    open_confirmation_protocol(receipt["protocol_id"], **case.options)
    with pytest.raises(ConfirmationAccessDenied):
        read_protocol_data(
            case.source.protocol_id,
            split="confirmation",
            registry_factory=forbidden,
            datasets_factory=forbidden,
        )


def test_source_repository_failures_keep_their_integrity_or_not_found_type(tmp_path):
    case = setup(tmp_path)

    class SourceIntegrityError(ValueError):
        pass

    def fail(_):
        raise SourceIntegrityError("actual strategy CAS is absent")

    options = {
        **case.options,
        "source_factory": lambda: SimpleNamespace(get=fail),
        "confirmations_factory": forbidden,
        "exposures_factory": forbidden,
    }
    with pytest.raises(SourceIntegrityError):
        freeze_confirmation_protocol(
            confirmation_request(), source_protocol_id=case.source.protocol_id, **options
        )


def test_changed_source_and_registry_inherit_repacked_origins_but_disjoint_trade_is_allowed(
    tmp_path,
):
    case = setup(tmp_path, confirmation_raw=trade(3, event_time=300))
    first = frozen(case)
    released = open_confirmation_protocol(first["protocol_id"], **case.options)
    from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry

    for trade_id, expected in (
        ("trade-1", "ALREADY_EXPOSED_IN_LEDGER"),
        ("trade-2", "NO_MATCHING_EXPOSURE_IN_LEDGER"),
    ):
        raw = trade(30, event_time=9999, quantity=7, trade_id=trade_id)
        changed_data = import_events(raw.replace(b'"source":', b'"source" :'), lambda: case.data)
        source_root = tmp_path / trade_id
        source = freeze(
            source_root,
            case.data,
            case.development,
            changed_data.dataset_id,
            request(hypothesis="A new claim and source registry"),
        )
        registry = Registry()
        options = {
            **case.options,
            "source_factory": lambda root=source_root: LocalProtocolRegistry(
                root / "registry", create=False
            ),
            "confirmations_factory": lambda current=registry: current,
        }
        declaration = freeze_confirmation_protocol(
            confirmation_request(title="Changed declaration"),
            source_protocol_id=source.protocol_id,
            **options,
        )
        assert declaration["exposure_status"] == expected
        if trade_id == "trade-1":
            assert declaration["related_exposure_ids"] == [released["exposure_id"]]
            with pytest.raises(ConfirmationAlreadyExposed):
                open_confirmation_protocol(declaration["protocol_id"], **options)
        else:
            second = open_confirmation_protocol(declaration["protocol_id"], **options)
            assert second["exposure_id"] != released["exposure_id"]
    assert len(case.ledger.records) == 2


@pytest.mark.parametrize("invalid", ["invalid", "A" * 64, "../protocol", "", True])
def test_invalid_identity_precedes_every_application_factory(invalid):
    options = {
        "source_factory": forbidden,
        "datasets_factory": forbidden,
        "confirmations_factory": forbidden,
        "exposures_factory": forbidden,
    }
    with pytest.raises(ConfirmationValidationError):
        freeze_confirmation_protocol(confirmation_request(), source_protocol_id=invalid, **options)
    for service in (inspect_confirmation_protocol, open_confirmation_protocol):
        with pytest.raises(ConfirmationValidationError):
            service(invalid, **options)
