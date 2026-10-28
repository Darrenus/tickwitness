#!/usr/bin/env python3
"""Qualify a transferable installed-core alpha kit without new research execution."""

import argparse
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory

_CASES = {
    "counterexample": {
        "path": "counterexample",
        "bundle_id": "2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369",
        "report_id": "398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb",
        "outcome": "COUNTEREXAMPLE_FOUND",
        "truth": False,
        "attempt_indices": [2, 3],
    },
    "clean_control": {
        "path": "clean-control",
        "bundle_id": "c5c3080fc6ab0ebd81b71373faee2f282e99feb95b904dd36bbc9631bd2b2c5e",
        "report_id": "8b902a687eeeb6897aa9237074b8a4fe7e5b336264a47bf52a9cc8427c20b3da",
        "outcome": "NO_COUNTEREXAMPLE_FOUND",
        "truth": True,
        "attempt_indices": [1, 2],
    },
}
_GATES = {
    "technical_checks": "PASS",
    "external_attempts": 0,
    "external_successes": 0,
    "external_attempt_gate": "PENDING",
    "release_decision": "TECHNICAL_ALPHA_ONLY_EXTERNAL_PENDING",
}
_SCOPE = {
    "native_replayed": False,
    "new_research_attempts": False,
    "confirmation_accessed": False,
    "source_claim_authority_extended": False,
    "global_history_authenticated": False,
    "external_identity_authenticated": False,
    "power_loss_durability_certified": False,
    "s10_recovery_qualified": False,
}
_GUARD = """
import importlib.abc
from importlib import metadata
import socket
import sqlite3
import subprocess
import sys
import tempfile
try:
    metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Alpha acceptance requires an installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Alpha qualification cannot import native')
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
    raise AssertionError('Alpha qualification cannot use original stores, workers or network')
socket.socket = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden
subprocess.Popen = forbidden
tempfile.TemporaryDirectory = forbidden
tempfile.mkdtemp = forbidden
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
raise SystemExit(main(sys.argv[1:]))
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
    with TemporaryDirectory(prefix="tickwitness-alpha-wheel-") as temporary:
        root = Path(temporary)
        failure = None
        try:
            yield root
        except BaseException as error:
            failure = error
            with suppress(OSError):
                report.unlink(missing_ok=True)
            raise
        finally:
            if not records.exists():
                try:
                    shutil.copytree(root, records)
                    (records / "diagnostic-capture.json").write_bytes(
                        _canonical(
                            {
                                "kind": "alpha_smoke_workspace_diagnostics_v1",
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
                        "Failed to preserve alpha smoke diagnostics: " + str(diagnostic_error),
                        file=sys.stderr,
                    )


def _check_scorecard(receipt: dict, kit_id: str, suite: dict) -> None:
    assert receipt["kind"] == "alpha_scorecard_receipt_v1" and receipt["schema_version"] == 1
    assert receipt["finalization_status"] == "LOCAL_RECOMPUTED_TECHNICAL_ONLY"
    assert receipt["kit_id"] == kit_id and receipt["suite_id"] == _identity(suite)
    scorecard = receipt["scorecard"]
    assert _identity(scorecard) == receipt["scorecard_id"]
    assert scorecard["kind"] == "alpha_scorecard_v1" and scorecard["schema_version"] == 1
    assert scorecard["kit_id"] == kit_id and scorecard["suite"] == suite
    assert scorecard["suite_id"] == receipt["suite_id"]
    assert scorecard["gates"] == _GATES and scorecard["scope"] == _SCOPE
    assert receipt["verification"] == {
        "case_contents_reaudited": True,
        "invalid_validator_reexecuted": True,
        "publication_boundaries_reexecuted": True,
        "postcommit_case_contents_reaudited": True,
        "saved_flags_trusted": False,
    }
    for name, expected in _CASES.items():
        actual = scorecard["cases"][name]
        assert actual["bundle_id"] == expected["bundle_id"]
        assert actual["report_id"] == expected["report_id"]
        assert actual["outcome"] == expected["outcome"]
        assert actual["planned_predicate_truth"] is expected["truth"]
        assert actual["eligible_ordinals"] == actual["audited_ordinals"] == [1, 3]
        assert actual["witness_ordinals"] == [1, 3]
        assert actual["coverage_complete_for_plan"] is True
        assert actual["unknown_ordinals"] == actual["unevaluated_ordinals"] == []
        assert actual["true_ordinals"] == ([1, 3] if expected["truth"] else [])
        assert actual["false_ordinals"] == ([] if expected["truth"] else [1, 3])
        assert actual["outer_status"] == actual["outer_stop_reason"] == "completed"
        assert actual["inner_status"] == "completed"
        assert actual["inner_stop_reason"] == "planned_candidates_exhausted"
    invalid = scorecard["invalid_perturbation"]
    assert invalid["kind"] == "alpha_invalid_perturbation_check_v1"
    assert invalid["source_bundle_id"] == _CASES["counterexample"]["bundle_id"]
    assert invalid["source_case"] == "counterexample"
    assert invalid["policy"] == "frozen_delay_upper_bound_plus_one_v1"
    assert invalid["validator"] == "validate_scenario_spec_v1"
    assert invalid["frozen_maximum_ns"] == 2_000_000_000
    assert invalid["challenge_delay_ns"] == 2_000_000_001
    assert invalid["outcome"] == "REJECTED"
    assert invalid["reason_code"] == "scenario_delay_outside_frozen_assumption_range"
    assert invalid["scenario_id"] == _identity(
        {
            "kind": "scenario_spec_v1",
            "schema_version": 1,
            "scenario_kind": "COUNTERFACTUAL_STRESS",
            "assumption_id": invalid["assumption_id"],
            "additional_delay": {"value": invalid["challenge_delay_ns"], "unit": "ns"},
        }
    )
    probe = scorecard["publication_probe"]
    assert probe["kind"] == "alpha_kit_publication_probe_v1"
    assert probe["profile"] == "alpha_kit_precommit_sync_postcommit_parent_sync_v1"
    assert probe["kit_id"] == kit_id
    assert probe["normal_publication"] == {
        "published_kit_id": kit_id,
        "readback_kit_id": kit_id,
        "success_returned": True,
    }
    assert probe["existing_destination"] == {
        "exception_type": "AlphaKitDestinationExistsError",
        "success_returned": False,
        "original_tree_unchanged": True,
    }
    assert probe["precommit_sync_failure"] == {
        "fault_injected": True,
        "exception_type": "AlphaKitError",
        "success_returned": False,
        "target_exists": False,
        "staging_entries_remaining": 0,
    }
    assert probe["postcommit_parent_sync_failure"] == {
        "fault_injected": True,
        "exception_type": "AlphaKitDurabilityError",
        "success_returned": False,
        "target_exists": True,
        "retained_kit_id": kit_id,
    }


def _check_probe(root: Path, kit: Path) -> None:
    assert sorted(path.name for path in root.iterdir()) == ["normal", "postcommit"]
    assert _tree(root / "normal") == _tree(kit)
    assert _tree(root / "postcommit") == _tree(kit)
    assert not (root / "precommit").exists()


def _package_handoff(root: Path, kit: Path, manifest: dict, kit_id: str) -> dict:
    archive_path = root / "alpha-reproduction-kit.tar.gz"
    prefix = "tickwitness-alpha-kit"
    contents = {relative: (kit / relative).read_bytes() for relative in sorted(_tree(kit))}
    directories = {prefix}
    for relative in contents:
        directories.update(
            prefix + "/" + str(parent) for parent in Path(relative).parents if str(parent) != "."
        )
    with (
        archive_path.open("wb") as output,
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for name in sorted(directories):
            entry = tarfile.TarInfo(name)
            entry.type, entry.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(entry)
        for relative, raw in contents.items():
            entry = tarfile.TarInfo(prefix + "/" + relative)
            entry.size, entry.mode = len(raw), 0o644
            archive.addfile(entry, io.BytesIO(raw))
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        files = {member.name: member for member in members if member.isfile()}
        assert len(members) == len(files) + len(directories)
        assert set(files) == {prefix + "/" + relative for relative in contents}
        assert all(member.isfile() or member.isdir() for member in members)
        for relative, raw in contents.items():
            stream = archive.extractfile(files[prefix + "/" + relative])
            assert stream is not None and stream.read() == raw
        extracted = root / "archive-extraction"
        extracted.mkdir()
        archive.extractall(extracted, filter="data")
    assert _tree(extracted / prefix) == _tree(kit)
    wheel_path = manifest["wheel_path"]
    archive_sha256 = _sha(archive_path.read_bytes())
    checksum_command = (
        "printf '%s  %s\\n' '"
        + archive_sha256
        + "' 'alpha-reproduction-kit.tar.gz' | shasum -a 256 -c -"
    )
    commands = [
        "python3.12 -m venv ./tickwitness-alpha-env",
        "./tickwitness-alpha-env/bin/python -m pip install --no-index --no-deps ./"
        + prefix
        + "/"
        + wheel_path,
        "./tickwitness-alpha-env/bin/python -I ./"
        + prefix
        + "/reproduce.py --kit ./"
        + prefix
        + " --expected-kit-id "
        + kit_id
        + " --participant-id external-reviewer-01 --participant-role external_user"
        + " --output ./tickwitness-alpha-submission-01",
    ]
    handoff = {
        "kind": "alpha_reproduction_handoff_v1",
        "schema_version": 1,
        "expected_kit_id": kit_id,
        "archive": {
            "path": archive_path.name,
            "sha256": archive_sha256,
            "size_bytes": archive_path.stat().st_size,
            "root": prefix,
        },
        "wheel": {"path": wheel_path, **manifest["files"][wheel_path]},
        "producer": manifest["producer"],
        "external_attempts": 0,
        "external_successes": 0,
        "external_attempt_gate": "PENDING",
        "participant_role_is_self_reported": True,
        "archive_digest_requires_separate_owner_confirmation": True,
        "pre_install_checksum_command": checksum_command,
        "commands_after_extraction": commands,
    }
    (root / "handoff.json").write_bytes(_canonical(handoff))
    (root / "HANDOFF.txt").write_text(
        "TickWitness technical alpha reproduction handoff\n\n"
        + "Expected kit ID: "
        + kit_id
        + "\n"
        + "Archive SHA-256: "
        + handoff["archive"]["sha256"]
        + "\n"
        + "Wheel path: "
        + wheel_path
        + "\n"
        + "Wheel SHA-256: "
        + handoff["wheel"]["sha256"]
        + "\n"
        + "Assembler revision: "
        + manifest["producer"]["source_revision"]
        + "\n"
        + "External attempts/successes: 0/0; gate PENDING. No release authorized.\n\n"
        + "Before extracting or installing, confirm the archive SHA-256 with the owner "
        + "through a separate trusted channel; do not trust this sidecar alone.\n"
        + "After confirming the digest, run this system checksum command and continue "
        + "only if it reports OK:\n\n"
        + checksum_command
        + "\n\nExtract alpha-reproduction-kit.tar.gz in a new directory.\n"
        + "Use Linux/macOS and Python 3.12-3.14. Then run these three steps:\n\n"
        + "\n\n".join(commands)
        + "\n\n"
        + "The external_user role is an example for the actual external participant; "
        + "maintainers use maintainer and CI uses automation.\n"
        + "Return the complete new submission directory, including failed attempts. "
        + "The runner never uploads files or authenticates identity.\n",
        encoding="utf-8",
    )
    return handoff


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("python", "wheel", "corpus-root", "guide", "runner", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    corpus = arguments.corpus_root.absolute()
    source_before = _tree(corpus)
    source_files = {
        "wheel": (arguments.wheel, _sha(arguments.wheel.read_bytes())),
        "guide": (arguments.guide, _sha(arguments.guide.read_bytes())),
        "runner": (arguments.runner, _sha(arguments.runner.read_bytes())),
    }
    with _preserved_workspace(arguments.records_dir, arguments.report) as root:
        assembly, publication, cwd, results, probes = (
            root / name
            for name in ("assembly-inputs", "assembled", "unrelated-cwd", "results", "probes")
        )
        for directory in (assembly, publication, cwd, results, probes):
            directory.mkdir()
        runtime_query = """
import json
import sys
print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix,
                  'base_prefix': sys.base_prefix}, sort_keys=True))
"""
        runtime_process = subprocess.run(
            [interpreter, "-I", "-c", runtime_query],
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
            f"Requested interpreter {interpreter!r} did not select a virtual environment: "
            f"prefix={runtime['prefix']!r}, base_prefix={runtime['base_prefix']!r}"
        )
        for expected in _CASES.values():
            shutil.copytree(corpus / expected["path"], assembly / expected["path"])
        wheel = assembly / arguments.wheel.name
        shutil.copyfile(arguments.wheel, wheel)
        shutil.copyfile(arguments.guide, assembly / "guide.md")
        shutil.copyfile(arguments.runner, assembly / "runner.py")
        assembly_before = _tree(assembly)

        def run(*command: str, expected: int = 0) -> dict:
            completed = subprocess.run(
                [interpreter, "-I", "-c", _GUARD, *command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            if completed.returncode != expected or (
                completed.stderr if expected == 0 else completed.stdout
            ):
                raise RuntimeError(
                    f"Installed alpha CLI exited {completed.returncode}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            return json.loads(completed.stdout if expected == 0 else completed.stderr)

        export_command = (
            "export-alpha-kit",
            "--counterexample",
            str(assembly / "counterexample"),
            "--clean-control",
            str(assembly / "clean-control"),
            "--wheel",
            str(wheel),
            "--guide",
            str(assembly / "guide.md"),
            "--runner",
            str(assembly / "runner.py"),
            "--source-revision",
            arguments.source_revision,
        )
        published = publication / "kit"
        exported = run(*export_command, "--output", str(published))
        assert exported["kind"] == "alpha_kit_export_receipt_v1"
        assert exported["technical_qualification_performed"] is False
        assert exported["external_attempts"] == 0 and exported["release_authorized"] is False
        assert exported["source_revision"] == arguments.source_revision
        kit_id = exported["kit_id"]
        manifest = json.loads((published / "manifest.json").read_bytes())
        assert _identity(manifest) == kit_id
        assert manifest["producer"]["source_revision"] == arguments.source_revision
        suite = manifest["suite"]
        assert _identity(suite) == exported["suite_id"]
        for name, expected in _CASES.items():
            assert suite["cases"][name] == {
                "bundle_id": expected["bundle_id"],
                "report_id": expected["report_id"],
            }
        original = _tree(published)
        conflict = run(*export_command, "--output", str(published), expected=3)
        assert conflict["error"]["code"] == "alpha_kit_destination_exists"
        assert _tree(published) == original and _tree(assembly) == assembly_before
        kit = root / "kit"
        published.rename(kit)
        shutil.rmtree(assembly)
        publication.rmdir()
        assert not assembly.exists() and not published.exists()

        def qualify(target: Path, probe: Path, *, pin: str = kit_id, expected: int = 0) -> dict:
            return run(
                "qualify-alpha-kit",
                str(target),
                "--expected-kit-id",
                pin,
                "--probe-root",
                str(probe),
                expected=expected,
            )

        receipt = qualify(kit, probes / "initial")
        _check_scorecard(receipt, kit_id, suite)
        _check_probe(probes / "initial", kit)
        (results / "scorecard.json").write_bytes(_canonical(receipt))
        repeated = qualify(kit, probes / "repeat")
        assert repeated == receipt
        _check_probe(probes / "repeat", kit)
        verified = run(
            "verify-alpha-scorecard",
            str(kit),
            "scorecard.json",
            "--input-root",
            str(results),
            "--expected-kit-id",
            kit_id,
            "--probe-root",
            str(probes / "saved-verification"),
        )
        assert verified == receipt
        _check_probe(probes / "saved-verification", kit)
        postcommit = qualify(probes / "initial" / "postcommit", probes / "postcommit-reaudit")
        assert postcommit == receipt
        _check_probe(probes / "postcommit-reaudit", kit)
        occupied_before = _tree(probes / "initial")
        occupied = qualify(kit, probes / "initial", expected=3)
        assert occupied["error"]["code"] == "alpha_kit_destination_exists"
        assert _tree(probes / "initial") == occupied_before
        wrong_probe = probes / "wrong-pin"
        wrong_pin = qualify(kit, wrong_probe, pin="0" * 64, expected=3)
        assert wrong_pin["error"]["code"] == "alpha_kit_integrity_or_io_failure"
        assert not wrong_probe.exists()

        case_receipts = {}
        for name, expected in _CASES.items():
            evidence = run(
                "verify-search-evidence",
                str(kit / "cases" / expected["path"]),
                "--expected-bundle-id",
                expected["bundle_id"],
            )
            assert evidence["report_id"] == expected["report_id"]
            assert evidence["report"]["outcome"] == expected["outcome"]
            assert evidence["report"]["planned_predicate_truth"] is expected["truth"]
            indices = [row["attempt_index"] for row in evidence["report"]["candidate_assessments"]]
            assert indices == expected["attempt_indices"]
            assert evidence["verification"]["native_replayed"] is False
            assert evidence["verification"]["attempt_reserved"] is False
            (results / (name + ".json")).write_bytes(_canonical(evidence))
            case_receipts[name] = evidence

        forged = json.loads(_canonical(receipt))
        invalid = forged["scorecard"]["invalid_perturbation"]
        invalid["frozen_maximum_ns"] += 1
        invalid["challenge_delay_ns"] += 1
        invalid["scenario_id"] = _identity(
            {
                "kind": "scenario_spec_v1",
                "schema_version": 1,
                "scenario_kind": "COUNTERFACTUAL_STRESS",
                "assumption_id": invalid["assumption_id"],
                "additional_delay": {"value": invalid["challenge_delay_ns"], "unit": "ns"},
            }
        )
        forged["scorecard_id"] = _identity(forged["scorecard"])
        (results / "rehashed-invalid-oracle.json").write_bytes(_canonical(forged))
        forged_probe = probes / "rehashed-invalid-oracle"
        rejected = run(
            "verify-alpha-scorecard",
            str(kit),
            "rehashed-invalid-oracle.json",
            "--input-root",
            str(results),
            "--expected-kit-id",
            kit_id,
            "--probe-root",
            str(forged_probe),
            expected=2,
        )
        assert rejected["error"]["code"] == "invalid_alpha_evidence"
        _check_probe(forged_probe, kit)  # The canonical forgery reached fresh full execution.

        corruptions = []
        for name in ("missing-readme", "extra-hidden-file"):
            corrupt = root / name
            shutil.copytree(kit, corrupt)
            if name == "missing-readme":
                (corrupt / "README.md").unlink()
            else:
                (corrupt / ".unexpected").write_bytes(b"not an allowed kit object")
            before = _tree(corrupt)
            probe = probes / name
            error = qualify(corrupt, probe, expected=3)
            assert error["error"]["code"] == "alpha_kit_integrity_or_io_failure"
            assert not probe.exists() and _tree(corrupt) == before
            corruptions.append(
                {
                    "name": name,
                    "error": error,
                    "probe_not_created": True,
                    "corrupt_tree_unchanged": True,
                }
            )

        submissions = root / "submissions"
        submissions.mkdir()
        runner_reports = []
        for name, pin, runner_exit, process_exit, outcome in (
            ("automation-success", kit_id, 0, 0, "VERIFIED"),
            ("automation-failed-pin", "0" * 64, 10, 3, "FAILED"),
        ):
            output = submissions / name
            completed = subprocess.run(
                [
                    interpreter,
                    "-I",
                    str(kit / "reproduce.py"),
                    "--kit",
                    str(kit),
                    "--expected-kit-id",
                    pin,
                    "--participant-id",
                    "installed-smoke",
                    "--participant-role",
                    "automation",
                    "--output",
                    str(output),
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=240,
            )
            if completed.returncode != runner_exit or completed.stderr:
                raise RuntimeError(
                    f"Actual standalone runner exited {completed.returncode}: "
                    f"{completed.stdout}\n{completed.stderr}"
                )
            written = json.loads(completed.stdout)
            submission = json.loads((output / "submission.json").read_bytes())
            actual = submission["submission"]
            assert submission["submission_id"] == _identity(actual) == written["submission_id"]
            assert actual["kind"] == "alpha_reproduction_submission_v1"
            assert actual["outcome"] == written["outcome"] == outcome
            assert actual["process_exit_code"] == process_exit
            assert actual["participant"] == {"id": "installed-smoke", "role_declared": "automation"}
            assert actual["expected_kit_id"] == pin
            assert actual["review_status"] == "SELF_REPORTED_UNREVIEWED"
            assert actual["participant_identity_authenticated"] is False
            assert actual["external_gate_updated"] is written["external_gate_updated"] is False
            assert actual["environment"]["tickwitness"] == manifest["producer"]["version"]
            assert actual["command"][0] == runtime["executable"], (
                f"Runner executable mismatch: requested={interpreter!r}, "
                f"runtime={runtime['executable']!r}, actual={actual['command'][0]!r}"
            )
            if outcome == "VERIFIED":
                saved = json.loads((output / "scorecard.json").read_bytes())
                assert saved == receipt and actual["scorecard_id"] == receipt["scorecard_id"]
                _check_probe(output / "publication-probe", kit)
            else:
                assert not (output / "scorecard.json").exists()
                assert actual["scorecard_id"] is None and actual["stdout"]["text"] == ""
                observed = json.loads(actual["stderr"]["text"])
                assert observed["error"]["code"] == "alpha_kit_integrity_or_io_failure"
                assert not (output / "publication-probe").exists()
            runner_reports.append(
                {
                    "name": name,
                    "runner_exit_code": runner_exit,
                    "written": written,
                    "submission_record": submission,
                }
            )

        assert _tree(kit) == original and _tree(corpus) == source_before
        for path, before in source_files.values():
            assert _sha(path.read_bytes()) == before
        handoff = _package_handoff(root, kit, manifest, kit_id)
        archived_receipt = qualify(
            root / "archive-extraction" / "tickwitness-alpha-kit", probes / "archive-reaudit"
        )
        assert archived_receipt == receipt
        _check_probe(probes / "archive-reaudit", kit)
        assert _tree(kit) == original
        report = {
            "kind": "installed_alpha_scorecard_acceptance_v1",
            "accepted": True,
            "synthetic_data": True,
            "source_revision": arguments.source_revision,
            "interpreter_identity": interpreter_identity,
            "export": exported,
            "receipt": receipt,
            "case_reaudits": case_receipts,
            "corruptions": corruptions,
            "runner_attempts": runner_reports,
            "wrong_kit_pin_error": wrong_pin,
            "occupied_probe_error": occupied,
            "existing_kit_error": conflict,
            "rehashed_invalid_oracle_error": rejected,
            "guarded_qualification_and_verification": True,
            "standalone_runner_unmodified": True,
            "runner_subprocess_guarded": False,
            "runner_uses_same_core_only_interpreter": True,
            "assembly_inputs_deleted": True,
            "kit_relocated": True,
            "source_byte_trees_unchanged": True,
            "immutable_kit_tree_unchanged": True,
            "same_receipt_on_repeat": True,
            "saved_receipt_freshly_recomputed": True,
            "postcommit_content_independently_reaudited": True,
            "controlled_faults_actually_executed": True,
            "rehashed_invalid_oracle_freshly_rejected": True,
            "failed_submission_retained": True,
            "handoff": handoff,
            "archive_exact_kit_only": True,
            "archive_extracted_kit_freshly_reaudited": True,
            "external_attempts": 0,
            "external_successes": 0,
            "external_attempt_gate": "PENDING",
            "new_native_calls": False,
            "new_research_attempts": False,
            "old_budget_mutations": False,
        }
        shutil.copytree(root, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(_tree(arguments.records_dir))
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print("Installed alpha kit: real corpus, boundaries and unreviewed submissions passed")


if __name__ == "__main__":
    main()
