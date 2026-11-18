"""Public SDK adapters retain real persistence, admission and error contracts."""

import errno
import hashlib
import json
from dataclasses import MISSING, FrozenInstanceError, asdict, fields
from inspect import Parameter, signature
from pathlib import Path

import pytest

import tickwitness.sdk as sdk
from tickwitness.application import datasets, research
from tickwitness.cli import main as cli_main
from tickwitness.domain.data_evidence.events import DataValidationError, normalize_events
from tickwitness.domain.research_contracts.protocols import (
    ProtocolValidationError,
    build_frozen_protocol,
)
from tickwitness.infrastructure.local_dataset_store import (
    DatasetNotFoundError,
    DatasetStoreError,
    LocalDatasetStore,
)
from tickwitness.infrastructure.local_protocol_registry import (
    LocalProtocolRegistry,
    ProtocolNotFoundError,
    ProtocolRegistryError,
)
from tickwitness.infrastructure.safe_input import InputReadError

EXAMPLES = Path(__file__).parent.parent / "examples"


def fixture_inputs(root: Path) -> None:
    for source, target in (
        ("normalized-events-valid.jsonl", "development.jsonl"),
        ("normalized-events-confirmation.jsonl", "confirmation.jsonl"),
        ("research-request.json", "request.json"),
    ):
        (root / target).write_bytes((EXAMPLES / source).read_bytes())
    (root / "strategy.py").write_bytes(b"raise AssertionError('must never execute')\n")


def freeze(client: sdk.Client, root: Path) -> sdk.ProtocolReceipt:
    development = client.import_events("development.jsonl", input_root=root)
    confirmation = client.import_events("confirmation.jsonl", input_root=root)
    return client.freeze_protocol(
        "request.json",
        input_root=root,
        strategy_source="strategy.py",
        development_dataset_id=development.dataset_id,
        confirmation_dataset_id=confirmation.dataset_id,
    )


def files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def cli_freeze_args(
    root: Path,
    *,
    store: Path,
    registry: Path,
    development_dataset_id: str,
    confirmation_dataset_id: str,
) -> list[str]:
    return [
        "freeze-protocol",
        "request.json",
        "--input-root",
        str(root),
        "--strategy-source",
        "strategy.py",
        "--development-dataset",
        development_dataset_id,
        "--confirmation-dataset",
        confirmation_dataset_id,
        "--store",
        str(store),
        "--registry",
        str(registry),
    ]


def test_public_values_are_the_existing_application_types() -> None:
    assert sdk.SDK_CONTRACT_VERSION == 1
    assert set(sdk.__all__) == {
        "SDK_CONTRACT_VERSION",
        "Client",
        "SDKError",
        "ValidationLimits",
        "ImportReceipt",
        "ProtocolReceipt",
        "DevelopmentRead",
    }
    assert sdk.ImportReceipt is datasets.ImportReceipt
    assert sdk.ProtocolReceipt is research.ProtocolReceipt
    assert sdk.DevelopmentRead is research.DevelopmentRead
    assert sdk.ValidationLimits is datasets.ValidationLimits
    for value, names in (
        (sdk.ImportReceipt, ("dataset_id", "created", "manifest", "report")),
        (sdk.ProtocolReceipt, ("protocol_id", "claim_revision_id", "created", "document")),
        (
            sdk.DevelopmentRead,
            ("protocol_id", "dataset_id", "observations", "total_records", "truncated"),
        ),
    ):
        public_fields = fields(value)
        assert tuple(field.name for field in public_fields) == names
        for field in public_fields:
            assert field.default is MISSING
            assert field.default_factory is MISSING
    assert tuple(field.name for field in fields(sdk.ValidationLimits)) == (
        "max_bytes",
        "max_records",
        "max_line_bytes",
        "max_levels_per_side",
    )
    assert asdict(sdk.ValidationLimits()) == {
        "max_bytes": 8 * 1024 * 1024,
        "max_records": 100_000,
        "max_line_bytes": 65_536,
        "max_levels_per_side": 1_000,
    }


@pytest.mark.parametrize(
    ("public_callable", "expected"),
    [
        (
            sdk.Client,
            (
                ("store", Parameter.KEYWORD_ONLY, Parameter.empty),
                ("registry", Parameter.KEYWORD_ONLY, Parameter.empty),
            ),
        ),
        (
            sdk.Client.import_events,
            (
                ("self", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("input", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("input_root", Parameter.KEYWORD_ONLY, Parameter.empty),
                ("limits", Parameter.KEYWORD_ONLY, None),
            ),
        ),
        (
            sdk.Client.inspect_dataset,
            (
                ("self", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("dataset_id", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
            ),
        ),
        (
            sdk.Client.freeze_protocol,
            (
                ("self", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("input", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("input_root", Parameter.KEYWORD_ONLY, Parameter.empty),
                ("strategy_source", Parameter.KEYWORD_ONLY, Parameter.empty),
                ("development_dataset_id", Parameter.KEYWORD_ONLY, Parameter.empty),
                ("confirmation_dataset_id", Parameter.KEYWORD_ONLY, Parameter.empty),
            ),
        ),
        (
            sdk.Client.inspect_protocol,
            (
                ("self", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("protocol_id", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
            ),
        ),
        (
            sdk.Client.read_protocol_data,
            (
                ("self", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("protocol_id", Parameter.POSITIONAL_OR_KEYWORD, Parameter.empty),
                ("split", Parameter.KEYWORD_ONLY, "development"),
                ("limit", Parameter.KEYWORD_ONLY, 100),
            ),
        ),
    ],
)
def test_public_signatures_preserve_names_keyword_boundaries_and_defaults(
    public_callable, expected
) -> None:
    assert tuple(
        (parameter.name, parameter.kind, parameter.default)
        for parameter in signature(public_callable).parameters.values()
    ) == expected


def test_client_is_frozen_handle_free_configuration(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Construction must not access protected storage")

    monkeypatch.setattr(sdk, "_LocalDatasetStore", forbidden)
    monkeypatch.setattr(sdk, "_LocalProtocolRegistry", forbidden)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    assert not list(tmp_path.iterdir())
    assert not hasattr(client, "__dict__")
    with pytest.raises(FrozenInstanceError):
        client.store = tmp_path / "elsewhere"
    with pytest.raises(TypeError):
        sdk.Client(tmp_path / "store", tmp_path / "registry")


def test_real_import_freeze_bounded_read_repeat_and_detached_values(tmp_path: Path) -> None:
    fixture_inputs(tmp_path)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    imported = client.import_events("development.jsonl", input_root=tmp_path)
    assert imported.created is True
    assert imported.report["unknown_receive_count"] == 1
    assert client.import_events("development.jsonl", input_root=tmp_path).created is False
    inspected = client.inspect_dataset(imported.dataset_id)
    assert inspected.created is False and inspected.manifest == imported.manifest
    protocol = freeze(client, tmp_path)
    assert protocol.created is True and protocol.document["execution_ready"] is False
    assert freeze(client, tmp_path).created is False
    assert client.inspect_protocol(protocol.protocol_id).document == protocol.document
    read = client.read_protocol_data(protocol.protocol_id, limit=1)
    assert read.dataset_id == imported.dataset_id
    assert read.total_records == 2 and read.truncated is True
    assert len(read.observations) == 1
    assert read.observations[0]["receive_time_ns"] is None

    imported.report["quality_status"] = "invented"
    imported.manifest["format_id"] = "invented"
    protocol.document["budget"] = {"max_events": 999999}
    read.observations[0]["capture_seq"] = 999999
    restored = client.inspect_dataset(imported.dataset_id)
    assert restored.report["quality_status"] == "accepted"
    assert restored.manifest["format_id"] == "tickwitness.normalized-events.v1"
    assert (
        client.inspect_protocol(protocol.protocol_id).document["budget"]
        != protocol.document["budget"]
    )
    assert (
        client.read_protocol_data(protocol.protocol_id, limit=1).observations[0]["capture_seq"] == 1
    )
    assert "observations" not in asdict(client.inspect_protocol(protocol.protocol_id))


def test_import_delegates_raw_bytes_limits_and_lazy_repository(tmp_path: Path, monkeypatch) -> None:
    fixture_inputs(tmp_path)
    limits = sdk.ValidationLimits(max_bytes=2048, max_records=3)
    expected = sdk.ImportReceipt("a" * 64, True, {}, {})
    seen = []

    def existing(raw, repository_factory, *, limits):
        assert raw == (tmp_path / "development.jsonl").read_bytes()
        assert not (tmp_path / "store").exists()
        seen.append(limits)
        return expected

    monkeypatch.setattr(datasets, "import_events", existing)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    assert client.import_events("development.jsonl", input_root=tmp_path, limits=limits) is expected
    assert seen == [limits]
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("split", ["confirmation", "unknown", None, 7])
def test_denied_split_uses_application_admission_before_ids_limits_or_io(
    tmp_path: Path, monkeypatch, split
) -> None:
    seen = []
    existing = research.read_protocol_data

    def observed(*args, **kwargs):
        seen.append(kwargs["split"])
        return existing(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Denied admission must precede protected IO")

    monkeypatch.setattr(research, "read_protocol_data", observed)
    monkeypatch.setattr(sdk, "_LocalDatasetStore", forbidden)
    monkeypatch.setattr(sdk, "_LocalProtocolRegistry", forbidden)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        client.read_protocol_data(None, split=split, limit=False)
    assert (caught.value.code, caught.value.exit_code) == ("confirmation_access_denied", 5)
    assert isinstance(caught.value.__cause__, research.ConfirmationAccessDenied)
    assert seen == [split] and not list(tmp_path.iterdir())


@pytest.mark.parametrize("identity", ["../outside", "A" * 64, "a" * 63, "a" * 64 + "\n"])
@pytest.mark.parametrize("method", ["inspect_dataset", "inspect_protocol", "read_protocol_data"])
def test_invalid_identity_is_an_adapter_refusal_before_store_access(
    tmp_path: Path, monkeypatch, identity: str, method: str
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Identity framing must precede protected IO")

    monkeypatch.setattr(sdk, "_LocalDatasetStore", forbidden)
    monkeypatch.setattr(sdk, "_LocalProtocolRegistry", forbidden)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        getattr(client, method)(identity)
    assert (caught.value.code, caught.value.exit_code) == ("invalid_sdk_argument", 2)
    assert caught.value.__cause__ is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("field", ["development_dataset_id", "confirmation_dataset_id"])
def test_freeze_identity_refusal_precedes_input_reads(tmp_path: Path, field: str) -> None:
    identities = {"development_dataset_id": "a" * 64, "confirmation_dataset_id": "b" * 64}
    identities[field] = "bad"
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        client.freeze_protocol(
            "missing.json",
            input_root=tmp_path / "missing",
            strategy_source="missing.py",
            **identities,
        )
    assert (caught.value.code, caught.value.exit_code) == ("invalid_sdk_argument", 2)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("failure", ["traversal", "symlink", "oversized", "invalid_data"])
def test_import_refuses_before_destination_creation(tmp_path: Path, failure: str) -> None:
    fixture_inputs(tmp_path)
    source, limits = "development.jsonl", None
    if failure == "traversal":
        source = "../outside.jsonl"
    elif failure == "symlink":
        (tmp_path / "link.jsonl").symlink_to(tmp_path / source)
        source = "link.jsonl"
    elif failure == "oversized":
        limits = sdk.ValidationLimits(max_bytes=1)
    else:
        (tmp_path / source).write_bytes(b"not JSON\n")
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        client.import_events(source, input_root=tmp_path, limits=limits)
    assert caught.value.code == ("invalid_data" if failure == "invalid_data" else "unsafe_input")
    assert caught.value.exit_code == 2 and caught.value.__cause__ is not None
    assert not client.store.exists() and not client.registry.exists()


@pytest.mark.parametrize("limit", [False, 0, 1001, 1.5])
def test_invalid_development_limit_uses_application_validation_before_io(
    tmp_path: Path, monkeypatch, limit
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Application limit validation must precede repository factories")

    monkeypatch.setattr(sdk, "_LocalDatasetStore", forbidden)
    monkeypatch.setattr(sdk, "_LocalProtocolRegistry", forbidden)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        client.read_protocol_data("a" * 64, limit=limit)
    assert (caught.value.code, caught.value.exit_code) == ("invalid_protocol", 2)
    assert isinstance(caught.value.__cause__, ProtocolValidationError)
    assert not list(tmp_path.iterdir())


def test_frozen_event_limit_cannot_be_increased_by_adapter(tmp_path: Path) -> None:
    fixture_inputs(tmp_path)
    request = json.loads((tmp_path / "request.json").read_bytes())
    request["budget"]["max_events"] = 1
    (tmp_path / "request.json").write_text(json.dumps(request))
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    protocol = freeze(client, tmp_path)
    before = files(client.registry)
    with pytest.raises(sdk.SDKError) as caught:
        client.read_protocol_data(protocol.protocol_id, limit=2)
    assert (caught.value.code, caught.value.exit_code) == ("invalid_protocol", 2)
    assert client.read_protocol_data(protocol.protocol_id, limit=1).truncated is True
    assert files(client.registry) == before


@pytest.mark.parametrize(
    ("method", "code", "cause"),
    [
        ("inspect_dataset", "dataset_not_found", DatasetNotFoundError),
        ("inspect_protocol", "protocol_not_found", ProtocolNotFoundError),
    ],
)
def test_missing_valid_identity_has_distinct_error_without_creating_roots(
    tmp_path: Path, method: str, code: str, cause
) -> None:
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        getattr(client, method)("a" * 64)
    assert (caught.value.code, caught.value.exit_code) == (code, 4)
    assert isinstance(caught.value.__cause__, cause)
    assert not list(tmp_path.iterdir())


def test_corrupt_dataset_refuses_without_overwriting_evidence(tmp_path: Path) -> None:
    fixture_inputs(tmp_path)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    receipt = client.import_events("development.jsonl", input_root=tmp_path)
    target = client.store / receipt.manifest["objects"]["raw"]["ref"]
    original = target.read_bytes()
    target.write_bytes(b"X" + original[1:])
    corrupted = target.read_bytes()
    with pytest.raises(sdk.SDKError) as caught:
        client.inspect_dataset(receipt.dataset_id)
    assert (caught.value.code, caught.value.exit_code) == (
        "store_integrity_or_publication_failure",
        3,
    )
    assert isinstance(caught.value.__cause__, DatasetStoreError)
    assert target.read_bytes() == corrupted and corrupted != original


@pytest.mark.parametrize(
    ("original", "code", "exit_code"),
    [
        (InputReadError("unsafe"), "unsafe_input", 2),
        (DataValidationError("invalid data"), "invalid_data", 2),
        (ProtocolValidationError("invalid protocol"), "invalid_protocol", 2),
        (research.ConfirmationAccessDenied("denied"), "confirmation_access_denied", 5),
        (DatasetNotFoundError("missing"), "dataset_not_found", 4),
        (DatasetStoreError("bad store"), "store_integrity_or_publication_failure", 3),
        (ProtocolNotFoundError("missing"), "protocol_not_found", 4),
        (ProtocolRegistryError("bad registry"), "protocol_integrity_or_publication_failure", 3),
        (PermissionError(errno.EACCES, "access refused"), "io_failure", 3),
    ],
)
def test_covered_error_translation_retains_cause_and_cli_envelope(
    tmp_path: Path, monkeypatch, original: Exception, code: str, exit_code: int
) -> None:
    fixture_inputs(tmp_path)

    def failed(*args, **kwargs):
        raise original

    monkeypatch.setattr(datasets, "import_events", failed)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(sdk.SDKError) as caught:
        client.import_events("development.jsonl", input_root=tmp_path)
    error = caught.value
    assert isinstance(error, RuntimeError) and error.__cause__ is original
    assert (error.code, error.exit_code, str(error)) == (code, exit_code, str(original))
    assert error.as_dict() == {"error": {"code": code, "message": str(original)}}
    changed = error.as_dict()
    changed["error"]["code"] = "invented"
    assert error.as_dict()["error"]["code"] == code
    assert not client.store.exists()


@pytest.mark.parametrize("original", [ValueError("bug"), TypeError("bug"), RuntimeError("bug")])
def test_unknown_programming_errors_are_not_translated(
    tmp_path: Path, monkeypatch, original
) -> None:
    fixture_inputs(tmp_path)

    def failed(*args, **kwargs):
        raise original

    monkeypatch.setattr(datasets, "import_events", failed)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(type(original)) as caught:
        client.import_events("development.jsonl", input_root=tmp_path)
    assert caught.value is original and not isinstance(caught.value, sdk.SDKError)


def test_limits_value_validation_and_wrong_python_arguments_remain_programming_errors(
    tmp_path: Path,
) -> None:
    with pytest.raises(DataValidationError):
        sdk.ValidationLimits(max_records=False)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "registry")
    with pytest.raises(TypeError):
        client.inspect_dataset(None)
    with pytest.raises(TypeError):
        client.read_protocol_data("a" * 64, unrelated=True)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("future_policy", True),
        ("schema_version", 2),
    ],
)
def test_event_schema_refusals_match_cli_before_creating_destinations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str, value: object
) -> None:
    fixture_inputs(tmp_path)
    path = tmp_path / "development.jsonl"
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    records[0][field] = value
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    invalid = path.read_bytes()
    client = sdk.Client(store=tmp_path / "sdk-store", registry=tmp_path / "sdk-registry")

    with pytest.raises(sdk.SDKError) as caught:
        client.import_events(path.name, input_root=tmp_path)

    assert (caught.value.code, caught.value.exit_code) == ("invalid_data", 2)
    assert isinstance(caught.value.__cause__, DataValidationError)
    cli_store = tmp_path / "cli-store"
    assert (
        cli_main(
            [
                "import-events",
                path.name,
                "--input-root",
                str(tmp_path),
                "--store",
                str(cli_store),
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err) == caught.value.as_dict()
    assert path.read_bytes() == invalid
    assert not client.store.exists() and not client.registry.exists()
    assert not cli_store.exists()


@pytest.mark.parametrize(
    ("section", "extra_value"),
    [
        (None, True),
        ("claim", True),
        ("configuration", True),
        ("budget", True),
        ("parameters", {"nested": 1}),
        ("parameters", [1]),
    ],
)
def test_request_schema_refusals_match_cli_without_publishing_or_rewriting_data(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    section: str | None,
    extra_value: object,
) -> None:
    fixture_inputs(tmp_path)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "sdk-registry")
    development = client.import_events("development.jsonl", input_root=tmp_path)
    confirmation = client.import_events("confirmation.jsonl", input_root=tmp_path)
    previous = (
        asdict(client.inspect_dataset(development.dataset_id)),
        asdict(client.inspect_dataset(confirmation.dataset_id)),
    )
    evidence = files(client.store / "objects"), files(client.store / "manifests")
    request_path = tmp_path / "request.json"
    request = json.loads(request_path.read_bytes())
    target = request if section is None else request[section]
    target["execution_ready"] = extra_value
    request_path.write_text(json.dumps(request))
    inputs = {
        name: (tmp_path / name).read_bytes()
        for name in (
            "development.jsonl",
            "confirmation.jsonl",
            "request.json",
            "strategy.py",
        )
    }

    with pytest.raises(sdk.SDKError) as caught:
        client.freeze_protocol(
            request_path.name,
            input_root=tmp_path,
            strategy_source="strategy.py",
            development_dataset_id=development.dataset_id,
            confirmation_dataset_id=confirmation.dataset_id,
        )

    assert (caught.value.code, caught.value.exit_code) == ("invalid_protocol", 2)
    assert isinstance(caught.value.__cause__, ProtocolValidationError)
    cli_registry = tmp_path / "cli-registry"
    assert (
        cli_main(
            cli_freeze_args(
                tmp_path,
                store=client.store,
                registry=cli_registry,
                development_dataset_id=development.dataset_id,
                confirmation_dataset_id=confirmation.dataset_id,
            )
        )
        == 2
    )
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err) == caught.value.as_dict()
    assert not client.registry.exists() and not cli_registry.exists()
    assert (files(client.store / "objects"), files(client.store / "manifests")) == evidence
    assert (
        asdict(client.inspect_dataset(development.dataset_id)),
        asdict(client.inspect_dataset(confirmation.dataset_id)),
    ) == previous
    assert {name: (tmp_path / name).read_bytes() for name in inputs} == inputs


def test_open_scalar_parameters_are_preserved_by_sdk_and_cli_without_new_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_inputs(tmp_path)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "sdk-registry")
    original = freeze(client, tmp_path)
    request_path = tmp_path / "request.json"
    request = json.loads(request_path.read_bytes())
    request["parameters"].update(
        execution_ready=True,
        custom_label="  declared scalar  ",
        custom_optional=None,
        custom_negative=-1,
    )
    request_path.write_text(json.dumps(request))

    revised = freeze(client, tmp_path)

    assert revised.created is True and revised.protocol_id != original.protocol_id
    assert revised.claim_revision_id == original.claim_revision_id
    assert revised.document["parameters"] == request["parameters"]
    assert revised.document["execution_ready"] is False
    assert revised.document["read_policy"] == original.document["read_policy"]
    assert revised.document["budget"] == original.document["budget"]
    assert revised.document["datasets"] == original.document["datasets"]
    assert client.inspect_protocol(revised.protocol_id).document == revised.document
    read = client.read_protocol_data(revised.protocol_id, limit=1)
    assert read.observations[0]["receive_time_ns"] is None
    cli_registry = tmp_path / "cli-registry"
    assert (
        cli_main(
            cli_freeze_args(
                tmp_path,
                store=client.store,
                registry=cli_registry,
                development_dataset_id=revised.document["datasets"]["development"],
                confirmation_dataset_id=revised.document["datasets"]["confirmation"],
            )
        )
        == 0
    )
    output = capsys.readouterr()
    assert output.err == "" and json.loads(output.out) == asdict(revised)


def test_inspection_preserves_report_extensions_but_research_binding_refuses_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_inputs(tmp_path)
    client = sdk.Client(store=tmp_path / "store", registry=tmp_path / "sdk-registry")
    confirmation = client.import_events("confirmation.jsonl", input_root=tmp_path)
    raw = (tmp_path / "development.jsonl").read_bytes()
    normalized = normalize_events(raw)
    report = dict(normalized.report, extension_note={"producer": "fixture", "enabled": True})
    stored = LocalDatasetStore(client.store, create=False).publish(
        raw, normalized.normalized_bytes, report
    )
    evidence = files(client.store / "objects"), files(client.store / "manifests")

    inspected = client.inspect_dataset(stored.dataset_id)

    assert inspected.created is False and inspected.report == report
    assert inspected.report["extension_note"] == {"producer": "fixture", "enabled": True}
    assert inspected.report["replay_certified"] is False
    with pytest.raises(sdk.SDKError) as rejected_freeze:
        client.freeze_protocol(
            "request.json",
            input_root=tmp_path,
            strategy_source="strategy.py",
            development_dataset_id=stored.dataset_id,
            confirmation_dataset_id=confirmation.dataset_id,
        )
    assert (rejected_freeze.value.code, rejected_freeze.value.exit_code) == (
        "invalid_protocol",
        2,
    )
    assert isinstance(rejected_freeze.value.__cause__, ProtocolValidationError)
    assert not client.registry.exists()

    # A valid declaration fixture isolates the read path from the freeze refusal.
    # It is sealed by existing domain/storage APIs, not admitted as research data.
    source = (tmp_path / "strategy.py").read_bytes()
    declaration = build_frozen_protocol(
        (tmp_path / "request.json").read_bytes(),
        development_dataset_id=stored.dataset_id,
        confirmation_dataset_id=confirmation.dataset_id,
        strategy_sha256=hashlib.sha256(source).hexdigest(),
    )
    LocalProtocolRegistry(client.registry).seal(declaration.canonical_bytes, source)
    registry_before = files(client.registry)
    assert client.inspect_protocol(declaration.protocol_id).document == declaration.document
    with pytest.raises(sdk.SDKError) as rejected_read:
        client.read_protocol_data(declaration.protocol_id, limit=1)
    assert (rejected_read.value.code, rejected_read.value.exit_code) == ("invalid_protocol", 2)
    assert isinstance(rejected_read.value.__cause__, ProtocolValidationError)
    assert (
        cli_main(
            [
                "read-protocol-data",
                declaration.protocol_id,
                "--store",
                str(client.store),
                "--registry",
                str(client.registry),
                "--limit",
                "1",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err) == rejected_read.value.as_dict()
    assert client.inspect_dataset(stored.dataset_id).report == report
    assert (files(client.store / "objects"), files(client.store / "manifests")) == evidence
    assert files(client.registry) == registry_before
