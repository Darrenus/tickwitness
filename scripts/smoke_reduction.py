#!/usr/bin/env python3
"""Qualify installed core reduction preparation without a new research attempt."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory

_SOURCE = {
    "bundle_id": "2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369",
    "report_id": "398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb",
}
_CLEAN = {
    "bundle_id": "c5c3080fc6ab0ebd81b71373faee2f282e99feb95b904dd36bbc9631bd2b2c5e",
    "report_id": "8b902a687eeeb6897aa9237074b8a4fe7e5b336264a47bf52a9cc8427c20b3da",
}
_FLAGS = {
    "checkpoint_supported": False,
    "checkpoint_used": False,
    "initial_state_materialized": False,
    "requires_full_prefix_replay": True,
    "native_replayed": False,
    "attempt_reserved": False,
    "reduced_predicate_evaluated": False,
    "witness_preservation_verified": False,
    "checkpoint_resume_verified": False,
}
_GUARD = """
import importlib.abc
from importlib import metadata
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path
try:
    metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Reduction acceptance requires an installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Reduction preparation cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_confirmation import (
    LocalConfirmationRegistry, LocalConfirmationExposureLedger,
)
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
def forbidden(*args, **kwargs):
    raise AssertionError('Reduction preparation cannot use old stores, budgets, workers or network')
socket.socket = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
subprocess.Popen = forbidden
for repository in (LocalAttemptLedger, LocalCampaignBudgetStore,
                   LocalExecutableProtocolRegistry, LocalDatasetStore,
                   LocalProtocolRegistry, LocalConfirmationRegistry,
                   LocalConfirmationExposureLedger, LocalSearchCampaignStore,
                   LocalSearchFindingRegistry, LocalSearchPlanRegistry):
    repository.__init__ = forbidden
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
for name in ('start', 'write_allocation', 'write_stop'):
    setattr(LocalCampaignBudgetStore, name, forbidden)
LocalDatasetStore.publish = forbidden
LocalExecutableProtocolRegistry.seal = forbidden
LocalProtocolRegistry.seal = forbidden
LocalSearchFindingRegistry.freeze = forbidden
LocalSearchPlanRegistry.seal = forbidden
"""
_PRE_IO = """
from tickwitness.application.reductions import (
    prepare_reduction_input, verify_reduction_input,
)
from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.domain.reduction.contracts import ReductionValidationError
class UnreadablePackage:
    def __getattribute__(self, name):
        raise AssertionError('Unsafe request accessed package property: ' + name)
valid = {'kind': 'reduction_request_v1', 'schema_version': 1,
         'witness_ordinal': 3, 'focus_from_capture_seq': 4,
         'through_capture_seq': 6, 'additional_delay_ns': 1000000000}
import json
invalid = [
    b'{',
    json.dumps({**valid, 'witness_ordinal': True}).encode(),
    json.dumps({**valid, 'additional_delay_ns': -1}).encode(),
    json.dumps({**valid, 'checkpoint': {}}).encode(),
    json.dumps({**valid, 'seed': 1}).encode(),
    json.dumps({**valid, 'strategy': 'replacement'}).encode(),
    json.dumps({key: value for key, value in valid.items()
                if key != 'through_capture_seq'}).encode(),
    json.dumps(valid).encode()[:-1] + b',"witness_ordinal":3}',
]
for raw in invalid:
    try:
        prepare_reduction_input(UnreadablePackage(), raw,
                                expected_bundle_id='0' * 64,
                                expected_report_id='0' * 64)
    except ReductionValidationError:
        pass
    else:
        raise AssertionError('Unsafe request returned a preparation')
for operation in ('prepare', 'verify'):
    try:
        if operation == 'prepare':
            prepare_reduction_input(UnreadablePackage(), b'{',
                                    expected_bundle_id='invalid',
                                    expected_report_id='invalid', split='confirmation')
        else:
            verify_reduction_input(UnreadablePackage(), source=UnreadablePackage(),
                                   expected_preparation_id='invalid', split='confirmation')
    except ConfirmationAccessDenied:
        pass
    else:
        raise AssertionError('Confirmation split was accepted')
print(json.dumps({'unsafe_requests_rejected_before_package_access': len(invalid),
                  'confirmation_operations_rejected_before_package_access': 2},
                 sort_keys=True))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(value: object) -> str:
    return _sha(_canonical(value))


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


@contextmanager
def _preserved_workspace(records: Path, report: Path) -> Iterator[Path]:
    with TemporaryDirectory(prefix="tickwitness-reduction-wheel-") as temporary:
        root = Path(temporary)
        failure = None
        try:
            yield root
        except BaseException as error:
            failure = error
            for accepted_report in (
                report,
                root / "reduction-input-smoke" / "report.json",
                records / "reduction-input-smoke" / "report.json",
            ):
                with suppress(OSError):
                    accepted_report.unlink(missing_ok=True)
            raise
        finally:
            if not records.exists():
                try:
                    shutil.copytree(root, records)
                    (records / "diagnostic-capture.json").write_bytes(
                        _canonical(
                            {
                                "kind": "reduction_smoke_workspace_diagnostics_v1",
                                "accepted": False,
                                "exception_type": (
                                    type(failure).__name__ if failure is not None else None
                                ),
                                "message": str(failure) if failure is not None else None,
                            }
                        )
                    )
                    (records / "artifact-files.json").write_bytes(_canonical(_tree(records)))
                except Exception as diagnostic_error:
                    if failure is None:
                        raise
                    print(
                        "Failed to preserve reduction diagnostics: " + str(diagnostic_error),
                        file=sys.stderr,
                    )


def _request(*, focus: int = 4, through: int = 6, delay: int = 2_000_000_000) -> dict:
    return {
        "kind": "reduction_request_v1",
        "schema_version": 1,
        "witness_ordinal": 3,
        "focus_from_capture_seq": focus,
        "through_capture_seq": through,
        "additional_delay_ns": delay,
    }


def _source_role(source: Path, name: str) -> bytes:
    manifest = json.loads((source / "manifest.json").read_bytes())
    item = manifest["roles"][name]
    raw = (source / item["ref"]).read_bytes()
    assert _sha(raw) == item["sha256"] and len(raw) == item["size_bytes"]
    return raw


def _candidate_bytes(original: bytes, delay: int) -> bytes:
    expected = []
    for raw in original.splitlines(keepends=True):
        event = json.loads(raw)
        if event["capture_seq"] >= 4:
            before = f'"receive_time_ns":{event["receive_time_ns"]},'.encode("ascii")
            after = f'"receive_time_ns":{event["receive_time_ns"] + delay},'.encode("ascii")
            assert raw.count(before) == 1
            raw = raw.replace(before, after, 1)
        expected.append(raw)
    return b"".join(expected)


def _check_package(path: Path, receipt: dict, request: dict, original: bytes) -> dict:
    assert sorted(item.name for item in path.iterdir()) == [
        "manifest.json",
        "materialization.json",
        "normalized.jsonl",
        "recipe.json",
    ]
    manifest_raw = (path / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest_raw == _canonical(manifest)
    assert receipt["preparation_id"] == _sha(manifest_raw)
    assert manifest["kind"] == "reduction_preparation_bundle_v1"
    assert manifest["schema_version"] == 1
    assert manifest["scope"] == "development_input_preparation_only_v1"
    assert set(manifest["roles"]) == {"recipe", "materialization", "normalized"}
    for role, filename in (
        ("recipe", "recipe.json"),
        ("materialization", "materialization.json"),
        ("normalized", "normalized.jsonl"),
    ):
        raw = (path / filename).read_bytes()
        assert manifest["roles"][role] == {
            "ref": filename,
            "sha256": _sha(raw),
            "size_bytes": len(raw),
        }
    recipe_raw = (path / "recipe.json").read_bytes()
    material_raw = (path / "materialization.json").read_bytes()
    recipe, material = json.loads(recipe_raw), json.loads(material_raw)
    assert recipe_raw == _canonical(recipe) and material_raw == _canonical(material)
    assert recipe["kind"] == "reduction_recipe_v1" and recipe["schema_version"] == 1
    assert recipe["flags"] == material["flags"] == _FLAGS
    assert recipe["source"]["bundle_id"] == _SOURCE["bundle_id"]
    assert recipe["source"]["report_id"] == _SOURCE["report_id"]
    assert recipe["source"]["witness_ordinal"] == 3
    assert recipe["source"]["source_normalized_sha256"] == _sha(original)
    assert recipe["operators"] == {
        name: request[name]
        for name in ("focus_from_capture_seq", "through_capture_seq", "additional_delay_ns")
    }
    assert recipe["execution_policy"] == {
        "id": "replay_from_original_origin_v1",
        "checkpoint_used": False,
        "prefix_reuse_allowed": False,
    }
    assert (
        recipe["scope"]
        == material["scope"]
        == {
            "phase": "development",
            "authority": "input_preparation_only_v1",
            "source_claim_authority_extended": False,
            "budget_owner_changed": False,
        }
    )
    assert material["kind"] == "materialized_reduction_input_v1"
    assert material["schema_version"] == 1
    assert material["recipe_id"] == receipt["recipe_id"] == _sha(recipe_raw)
    context, retained, candidate = (
        material["prefix_context"],
        material["retained"],
        material["candidate"],
    )
    assert _identity(context) == material["prefix_context_id"] == receipt["prefix_context_id"]
    assert context["recipe_id"] == material["recipe_id"]
    assert context["source_bundle_id"] == _SOURCE["bundle_id"]
    assert context["source_report_id"] == _SOURCE["report_id"]
    assert context["source_normalized_sha256"] == _sha(original)
    assert context["candidate_scenario_id"] == candidate["scenario_id"]
    assert context["candidate_full_view_id"] == candidate["full_view_id"]
    assert candidate["scenario_id"] == _identity(candidate["scenario"])
    assert candidate["scenario_id"] == receipt["candidate_scenario_id"]
    assert candidate["additional_delay_ns"] == request["additional_delay_ns"]
    assert candidate["scenario"]["additional_delay"] == {
        "value": request["additional_delay_ns"],
        "unit": "ns",
    }
    full = _candidate_bytes(original, request["additional_delay_ns"])
    lines = full.splitlines(keepends=True)
    expected = b"".join(lines[: request["through_capture_seq"]])
    warmup = b"".join(lines[: request["focus_from_capture_seq"] - 1])
    assert candidate["full_event_count"] == 7
    assert candidate["full_normalized_sha256"] == _sha(full)
    assert (path / "normalized.jsonl").read_bytes() == expected
    events = [json.loads(raw) for raw in expected.splitlines()]
    assert [event["capture_seq"] for event in events] == list(
        range(1, request["through_capture_seq"] + 1)
    )
    assert events[0]["type"] == "snapshot"
    for name, value in {
        "event_count": request["through_capture_seq"],
        "warmup_event_count": request["focus_from_capture_seq"] - 1,
        "normalized_sha256": _sha(expected),
        "warmup_normalized_sha256": _sha(warmup),
    }.items():
        assert retained[name] == context[name] == value
    for name, capture in (
        ("origin_ref", 1),
        ("focus_ref", request["focus_from_capture_seq"]),
        ("through_ref", request["through_capture_seq"]),
    ):
        reference = {
            "line": capture,
            "capture_seq": capture,
            "event_type": events[capture - 1]["type"],
        }
        assert retained[name] == context[name] == reference
    changes = {
        "strictly_shorter_input": request["through_capture_seq"] < 7,
        "parameter_contracted": request["additional_delay_ns"] < 2_000_000_000,
        "focus_window_narrowed": request["focus_from_capture_seq"] > 1,
    }
    assert material["changes"] == changes
    assert receipt["kind"] == "reduction_input_receipt_v1" and receipt["schema_version"] == 1
    assert receipt["scope"] == "development_input_preparation_only_v1"
    assert receipt["source_bundle_id"] == _SOURCE["bundle_id"]
    assert receipt["source_report_id"] == _SOURCE["report_id"]
    assert receipt["source_protocol_id"] == recipe["source"]["source_protocol_id"]
    assert receipt["source_event_count"] == 7
    assert receipt["event_count"] == retained["event_count"]
    assert receipt["warmup_event_count"] == retained["warmup_event_count"]
    for name in ("focus_from_capture_seq", "through_capture_seq", "additional_delay_ns"):
        assert receipt[name] == request[name]
    for name, value in {**_FLAGS, **changes}.items():
        assert receipt[name] is value
    assert material["prefix_context_id"] not in {
        recipe["source"]["source_dataset_id"],
        candidate["full_view_id"],
    }
    return material


def _rehash(path: Path) -> str:
    manifest = json.loads((path / "manifest.json").read_bytes())
    for item in manifest["roles"].values():
        raw = (path / item["ref"]).read_bytes()
        item.update(sha256=_sha(raw), size_bytes=len(raw))
    raw = _canonical(manifest)
    (path / "manifest.json").write_bytes(raw)
    return _sha(raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "corpus-root", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    corpus = arguments.corpus_root.absolute()
    corpus_before = _tree(corpus)
    with _preserved_workspace(arguments.records_dir, arguments.report) as root:
        issuer, outputs, cwd, transcripts = (
            root / name for name in ("issuer-inputs", "prepared", "unrelated-cwd", "transcripts")
        )
        for directory in (issuer, outputs, cwd, transcripts):
            directory.mkdir()
        query = (
            "import json,sys; print(json.dumps({'executable':sys.executable,"
            "'prefix':sys.prefix,'base_prefix':sys.base_prefix},sort_keys=True))"
        )
        runtime_process = subprocess.run(
            [interpreter, "-I", "-c", query],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        runtime = json.loads(runtime_process.stdout)
        expected_prefix = str(arguments.python.absolute().parent.parent.resolve())
        interpreter_identity = {
            "requested_executable": interpreter,
            "requested_venv_prefix_resolved": expected_prefix,
            "runtime": runtime,
        }
        (root / "interpreter-identity.json").write_bytes(_canonical(interpreter_identity))
        assert str(Path(runtime["prefix"]).resolve()) == expected_prefix, (
            f"Requested interpreter {interpreter!r} uses prefix {runtime['prefix']!r}; "
            f"expected virtual environment {expected_prefix!r}"
        )
        assert Path(runtime["prefix"]).resolve() != Path(runtime["base_prefix"]).resolve(), (
            f"Requested interpreter {interpreter!r} is not a venv: {runtime!r}"
        )
        for name in ("counterexample", "clean-control"):
            shutil.copytree(corpus / name, issuer / name)
        original = _source_role(issuer / "counterexample", "normalized")
        assert len(original.splitlines()) == 7
        sources_before = {
            name: _tree(issuer / name) for name in ("counterexample", "clean-control")
        }
        denied = (str(corpus.resolve()),)
        guard = (
            _GUARD
            + "\n_denied_roots = "
            + repr(denied)
            + "\n"
            + """
def deny_original_paths(event, arguments):
    if event == 'open' and arguments and isinstance(arguments[0], (str, bytes)):
        filename = arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0]
        resolved = Path(filename).resolve()
        if any(resolved.is_relative_to(Path(root)) for root in _denied_roots):
            raise AssertionError('Reduction acceptance read original corpus: ' + filename)
sys.addaudithook(deny_original_paths)
"""
        )
        invocations = []

        def execute(code: str, *command: str, expected: int = 0) -> dict:
            process = subprocess.run(
                [interpreter, "-I", "-c", guard + code, *command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            record = {
                "command": list(command),
                "expected_exit_code": expected,
                "exit_code": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
            invocations.append(record)
            (transcripts / f"{len(invocations):04d}.json").write_bytes(_canonical(record))
            if process.returncode != expected or (
                process.stderr if expected == 0 else process.stdout
            ):
                raise RuntimeError(
                    f"Installed reduction CLI exited {process.returncode}, expected {expected}: "
                    f"{process.stdout}\n{process.stderr}"
                )
            return json.loads(process.stdout if expected == 0 else process.stderr)

        def run(*command: str, expected: int = 0) -> dict:
            return execute("\nraise SystemExit(main(sys.argv[1:]))\n", *command, expected=expected)

        pre_io = execute(_PRE_IO)
        assert pre_io == {
            "unsafe_requests_rejected_before_package_access": 8,
            "confirmation_operations_rejected_before_package_access": 2,
        }

        def prepare(
            name: str,
            request: dict,
            *,
            source: str = "counterexample",
            pins: dict | None = None,
            expected: int = 0,
        ) -> dict:
            (issuer / (name + ".json")).write_bytes(_canonical(request))
            selected = _SOURCE if pins is None else pins
            return run(
                "prepare-reduction-input",
                source,
                name + ".json",
                "--input-root",
                str(issuer),
                "--expected-bundle-id",
                selected["bundle_id"],
                "--expected-report-id",
                selected["report_id"],
                "--output",
                str(outputs / name),
                expected=expected,
            )

        requests = {
            "no-op": _request(focus=1, through=7),
            "focused-prefix": _request(),
            "contracted-prefix": _request(delay=1_000_000_000),
            "affected-warmup": _request(focus=5, delay=1_000_000_000),
            "anchor-ended-prefix": _request(through=4),
        }
        cases = []
        materials = {}
        for name, request in requests.items():
            receipt = prepare(name, request)
            assert receipt["status"] == "PREPARED_INPUT_ONLY"
            materials[name] = _check_package(outputs / name, receipt, request, original)
            cases.append({"name": name, "request": request, "prepared": receipt})
        assert (
            materials["no-op"]["candidate"]["scenario_id"]
            == (
                json.loads((outputs / "no-op" / "recipe.json").read_bytes())["source"][
                    "source_scenario_id"
                ]
            )
        )
        for field in ("scenario_id", "full_view_id", "full_normalized_sha256"):
            assert (
                materials["focused-prefix"]["candidate"][field]
                != (materials["contracted-prefix"]["candidate"][field])
            )
        assert (
            materials["focused-prefix"]["prefix_context_id"]
            != (materials["contracted-prefix"]["prefix_context_id"])
        )
        assert materials["affected-warmup"]["retained"]["warmup_normalized_sha256"] != (
            _sha(b"".join(_candidate_bytes(original, 2_000_000_000).splitlines(keepends=True)[:4]))
        )
        rejected = []
        invalid = {
            "missing-endpoint": _request(through=8),
            "missing-focus": _request(focus=8, through=7),
            "reversed-focus": _request(focus=6, through=4),
            "missing-transform-anchor": _request(focus=1, through=3),
            "delay-expansion": _request(delay=2_000_000_001),
            "nonwitness-ordinal": {**_request(), "witness_ordinal": 2},
            "checkpoint-operator": {**_request(), "checkpoint": {}},
        }
        for name, request in invalid.items():
            error = prepare(name, request, expected=2)
            assert error["error"]["code"] == "invalid_research_evidence"
            assert not (outputs / name).exists()
            rejected.append({"name": name, "error": error})
        clean_error = prepare(
            "true-control", _request(), source="clean-control", pins=_CLEAN, expected=2
        )
        assert clean_error["error"]["code"] == "invalid_research_evidence"
        assert not (outputs / "true-control").exists()
        rejected.append({"name": "true-control", "error": clean_error})
        for key in ("bundle_id", "report_id"):
            name = "wrong-source-" + key
            error = prepare(name, _request(), pins={**_SOURCE, key: "0" * 64}, expected=2)
            assert error["error"]["code"] == "invalid_research_evidence"
            assert not (outputs / name).exists()
            rejected.append({"name": name, "error": error})
        for name, before in sources_before.items():
            assert _tree(issuer / name) == before
        relocated = root / "relocated"
        relocated.mkdir()
        relocated_source = relocated / "source-root"
        relocated_source.mkdir()
        for name in sources_before:
            shutil.copytree(issuer / name, relocated_source / name)
        shutil.move(str(outputs), relocated / "preparations")
        shutil.rmtree(issuer)
        assert not issuer.exists() and not outputs.exists()
        guard += (
            "\n_denied_roots += " + repr((str(issuer.resolve()), str(outputs.resolve()))) + "\n"
        )
        outputs = relocated / "preparations"
        for case in cases:
            verified = run(
                "verify-reduction-input",
                str(outputs / case["name"]),
                "--input-root",
                str(relocated_source),
                "--source-evidence",
                "counterexample",
                "--expected-preparation-id",
                case["prepared"]["preparation_id"],
            )
            assert verified == {**case["prepared"], "status": "RECOMPUTED_PREPARATION_ONLY"}
            _check_package(outputs / case["name"], verified, case["request"], original)
            case["relocated_verification"] = verified
        attacks = root / "attacks"
        attacks.mkdir()

        def reject_saved(name: str, expected: int, code: str, mutate) -> None:
            target = attacks / name
            shutil.copytree(outputs / "focused-prefix", target)
            preparation_id = mutate(target)
            error = run(
                "verify-reduction-input",
                str(target),
                "--input-root",
                str(relocated_source),
                "--source-evidence",
                "counterexample",
                "--expected-preparation-id",
                preparation_id,
                expected=expected,
            )
            assert error["error"]["code"] == code
            rejected.append({"name": name, "error": error, "preparation_id": preparation_id})

        def remove_middle_delta(target: Path) -> str:
            normalized = target / "normalized.jsonl"
            lines = normalized.read_bytes().splitlines(keepends=True)
            assert json.loads(lines[1])["type"] == "delta"
            altered = b"".join(lines[:1] + lines[2:])
            normalized.write_bytes(altered)
            material_path = target / "materialization.json"
            material = json.loads(material_path.read_bytes())
            for part in (material["retained"], material["prefix_context"]):
                part["normalized_sha256"] = _sha(altered)
                part["event_count"] = 5
                part["warmup_event_count"] = 2
                part["warmup_normalized_sha256"] = _sha(b"".join(lines[:1] + lines[2:3]))
            material["prefix_context_id"] = _identity(material["prefix_context"])
            material_path.write_bytes(_canonical(material))
            return _rehash(target)

        def claim_checkpoint(target: Path) -> str:
            path = target / "materialization.json"
            document = json.loads(path.read_bytes())
            document["flags"]["checkpoint_used"] = True
            document["flags"]["initial_state_materialized"] = True
            path.write_bytes(_canonical(document))
            return _rehash(target)

        def change_context(target: Path) -> str:
            path = target / "materialization.json"
            document = json.loads(path.read_bytes())
            document["prefix_context"]["candidate_scenario_id"] = "0" * 64
            document["prefix_context_id"] = _identity(document["prefix_context"])
            path.write_bytes(_canonical(document))
            return _rehash(target)

        reject_saved(
            "rehashed-middle-delta-deletion", 2, "invalid_research_evidence", remove_middle_delta
        )
        reject_saved("rehashed-checkpoint-claim", 2, "invalid_research_evidence", claim_checkpoint)
        reject_saved(
            "rehashed-scenario-prefix-binding", 2, "invalid_research_evidence", change_context
        )

        def missing_materialization(target: Path) -> str:
            preparation_id = _sha((target / "manifest.json").read_bytes())
            (target / "materialization.json").unlink()
            return preparation_id

        def tamper_bytes(target: Path) -> str:
            preparation_id = _sha((target / "manifest.json").read_bytes())
            path = target / "normalized.jsonl"
            path.write_bytes(path.read_bytes() + b" ")
            return preparation_id

        reject_saved(
            "missing-materialization",
            3,
            "research_store_integrity_or_io_failure",
            missing_materialization,
        )
        reject_saved(
            "unrehashed-normalized-bytes", 3, "research_store_integrity_or_io_failure", tamper_bytes
        )
        for command in ("prepare-reduction-input", "verify-reduction-input"):
            if command == "prepare-reduction-input":
                positional = (
                    "missing-source",
                    "missing-request.json",
                    "--expected-bundle-id",
                    "invalid",
                    "--expected-report-id",
                    "invalid",
                    "--output",
                    str(root / "must-not-publish"),
                )
            else:
                positional = (
                    str(root / "missing-preparation"),
                    "--source-evidence",
                    "missing-source",
                    "--expected-preparation-id",
                    "invalid",
                )
            error = run(
                command,
                *positional,
                "--input-root",
                str(root / "missing-input-root"),
                "--split",
                "confirmation",
                expected=5,
            )
            assert error["error"]["code"] == "confirmation_access_denied"
            rejected.append({"name": command + "-confirmation-pre-io", "error": error})
        assert not (root / "must-not-publish").exists()
        for name, before in sources_before.items():
            assert _tree(relocated_source / name) == before
        assert _tree(corpus) == corpus_before
        report = {
            "kind": "installed_reduction_input_acceptance_v1",
            "accepted": True,
            "source_pins": _SOURCE,
            "cases": cases,
            "rejections": rejected,
            "pre_io": pre_io,
            "interpreter_identity": interpreter_identity,
            "guard": {
                "installed_core_only": True,
                "native_import_forbidden": True,
                "original_stores_and_sqlite_forbidden": True,
                "network_and_workers_forbidden": True,
                "attempt_reservation_and_budget_writes_forbidden": True,
                "original_corpus_reads_forbidden": True,
            },
            "copied_issuer_workspace_deleted": True,
            "source_and_preparations_relocated": True,
            "source_records_unchanged": True,
            "all_preparations_require_full_prefix_replay": True,
            "initial_state_materialized": False,
            "witness_preservation_verified": False,
            "new_research_attempts": False,
            "external_attempts": 0,
            "external_attempt_gate": "PENDING",
        }
        report_path = root / "reduction-input-smoke" / "report.json"
        report_path.parent.mkdir()
        report_path.write_bytes(_canonical(report))
        shutil.copytree(root, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(_tree(arguments.records_dir))
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_bytes(_canonical(report))


if __name__ == "__main__":
    main()
