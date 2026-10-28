#!/usr/bin/env python3
"""Qualify installed portable search evidence without creating another research attempt.

The controller uses original synthetic records produced by the preceding finding
acceptance. It deletes its copied issuer workspace before core-only verification
of relocated bundles. Product operations run only on installed remote workers.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

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
    raise AssertionError('Search evidence acceptance requires a core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Search evidence cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_finding_registry import LocalSearchFindingRegistry
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
def forbidden(*args, **kwargs):
    raise AssertionError('Search evidence cannot execute, reserve, publish or use network')
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
for name in ('start', 'write_dispatch', 'write_link', 'write_result', 'write_stop'):
    setattr(LocalSearchCampaignStore, name, forbidden)
for name in ('start', 'write_allocation', 'write_stop'):
    setattr(LocalCampaignBudgetStore, name, forbidden)
LocalSearchFindingRegistry.freeze = forbidden
LocalSearchPlanRegistry.seal = forbidden
LocalExecutableProtocolRegistry.seal = forbidden
LocalDatasetStore.publish = forbidden
if sys.argv[1] == 'verify-search-evidence':
    sqlite3.connect = forbidden
    tempfile.TemporaryDirectory = forbidden
    tempfile.mkdtemp = forbidden
    for repository in (LocalAttemptLedger, LocalCampaignBudgetStore,
                       LocalExecutableProtocolRegistry, LocalDatasetStore,
                       LocalSearchCampaignStore, LocalSearchFindingRegistry,
                       LocalSearchPlanRegistry):
        repository.__init__ = forbidden
raise SystemExit(main(sys.argv[1:]))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def _run(interpreter: str, cwd: Path, *command: str, expected: int = 0) -> dict:
    process = subprocess.run(
        [interpreter, "-I", "-c", _GUARD, *command],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if process.returncode != expected or (process.stderr if expected == 0 else process.stdout):
        raise RuntimeError(
            f"Installed search evidence exited {process.returncode}: "
            f"{process.stdout}\n{process.stderr}"
        )
    return json.loads(process.stdout if expected == 0 else process.stderr)


def _paths(records: Path, name: str) -> tuple[Path, Path]:
    if name.startswith("source-"):
        root = records / "budget-source"
        return root, root / ("runs-" + name.removeprefix("source-"))
    if name == "empty-original-budget":
        root = records / "budget-source"
        return root, root / "runs-normal"
    root = records / "true-criterion"
    suffix = {
        "all-true": "normal",
        "evaluation-true-prefix": "evaluation",
        "storage-true-prefix": "storage",
        "original-budget-true-prefix": "normal",
    }[name]
    return root, root / ("runs-" + suffix)


def _export_arguments(case: dict, records: Path) -> tuple[str, ...]:
    paths, runs = _paths(records, case["name"])
    receipt = case["receipt"]
    return (
        "export-search-evidence",
        receipt["report"]["finding_protocol_id"],
        "--expected-report-id",
        receipt["report_id"],
        "--plans",
        str(paths / "plans"),
        "--store",
        str(paths / "data"),
        "--registry",
        str(paths / "registry"),
        "--runs",
        str(runs),
        "--finding-registry",
        str(records / "findings"),
    )


def _check(receipt: dict, case: dict) -> None:
    assert receipt["kind"] == "search_evidence_verification_receipt_v1"
    assert receipt["schema_version"] == 1
    assert receipt["finalization_status"] == "FINAL"
    assert receipt["report_id"] == case["receipt"]["report_id"]
    assert receipt["report"] == case["receipt"]["report"]
    assert _digest(_canonical(receipt["report"])) == receipt["report_id"]
    snapshot = receipt["snapshot"]
    report = receipt["report"]
    assert snapshot["kind"] == "search_evidence_snapshot_v1"
    assert snapshot["finding_protocol_id"] == report["finding_protocol_id"]
    assert snapshot["plan_id"] == report["plan_id"]
    assert snapshot["budget_id"] == report["budget"]["campaign_budget_id"]
    assert snapshot["dataset_id"] == report["finding_protocol"]["bindings"][
        "development_dataset_id"
    ]
    assert isinstance(snapshot["producer_version"], str) and snapshot["producer_version"]
    if case["bounded"]["execution"] is None:
        assert snapshot["ledger_prefix_observed"] is False
        for name in ("reservations", "attempts", "cas"):
            assert snapshot[name] == []
    else:
        assert snapshot["ledger_prefix_observed"] is True
    verified = receipt["verification"]
    for name in (
        "integrity_verified", "bindings_verified", "source_revalidated", "plan_recomputed",
        "ledger_content_reconstructed", "findings_recomputed", "diagnostics_recomputed",
        "portable_evidence_verified",
    ):
        assert verified[name] is True
    assert verified["reservation_prefix_reconstructed"] is snapshot["ledger_prefix_observed"]
    for name in (
        "native_replayed", "attempt_reserved", "author_signature_verified",
        "human_domain_approval_verified", "original_publication_verified",
        "producer_version_authenticated", "full_attempt_history_verified",
        "confirmation_reference_checked", "runtime_limits_reenforced",
        "physical_storage_usage_verified",
    ):
        assert verified[name] is False
    diagnostic = receipt["diagnostics"]
    assert diagnostic["kind"] == "search_evidence_diagnostics_v1"
    assert diagnostic["comparison_policy"] == "adjacent_completed_candidate_traces_v1"
    assert receipt["diagnostics_sha256"] == _digest(_canonical(diagnostic))
    assert receipt["snapshot_id"] == _digest(_canonical(snapshot))
    for name in ("baseline_comparison_performed", "causal_attribution_issued", "native_replayed"):
        assert diagnostic[name] is False
    completed = [
        row
        for row in report["candidate_assessments"]
        if row["status"] == "COMPLETED" and row["raw_result_audited"] is True
    ]
    pairs = diagnostic["pairs"]
    assert len(pairs) == max(0, len(completed) - 1)
    for pair, left, right in zip(pairs, completed[:-1], completed[1:], strict=True):
        assert pair["left_ordinal"] == left["ordinal"]
        assert pair["right_ordinal"] == right["ordinal"]
        assert pair["left_run_id"] == left["run_id"]
        assert pair["right_run_id"] == right["run_id"]
        assert pair["comparison"]["kind"] == "replay_qualification_comparison_v1"


def _rehash_attack(source: Path, destination: Path, *, diagnostics: bool) -> str:
    manifest = json.loads((source / "manifest.json").read_bytes())
    payload = {
        role: (source / reference["ref"]).read_bytes()
        for role, reference in manifest["roles"].items()
    }
    role = "diagnostics" if diagnostics else "finding_report"
    changed = json.loads(payload[role])
    if diagnostics:
        changed["baseline_comparison_performed"] = True
    else:
        changed["planned_predicate_truth"] = changed["planned_predicate_truth"] is not True
    payload[role] = _canonical(changed)
    objects = destination / "objects" / "sha256"
    objects.mkdir(parents=True)
    for name, raw in payload.items():
        content_hash = _digest(raw)
        manifest["roles"][name] = {
            "sha256": content_hash, "size_bytes": len(raw),
            "ref": "objects/sha256/" + content_hash,
        }
        (objects / content_hash).write_bytes(raw)
    raw_manifest = _canonical(manifest)
    (destination / "manifest.json").write_bytes(raw_manifest)
    return _digest(raw_manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--verifier-python", type=Path)
    parser.add_argument("--finding-report", required=True, type=Path)
    parser.add_argument("--finding-records", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--bundles-dir", required=True, type=Path)
    arguments = parser.parse_args()
    issuer = str(arguments.python.absolute())
    verifier = str((arguments.verifier_python or arguments.python).absolute())
    source = json.loads(arguments.finding_report.read_bytes())
    assert source["kind"] == "installed_search_finding_acceptance_v1" and source["accepted"] is True
    assert len(source["cases"]) == (10 if source["native_execution"] else 3)
    original_records = arguments.finding_records.absolute()
    original_tree = _tree(original_records)
    cases = []
    with TemporaryDirectory(prefix="tickwitness-portable-search-") as temporary:
        root = Path(temporary)
        workspace = root / "issuer-workspace"
        shutil.copytree(original_records, workspace)
        before_workspace = _tree(workspace)
        staged = root / "exported"
        staged.mkdir()
        issued = {}
        for case in source["cases"]:
            destination = staged / case["name"]
            receipt = _run(
                issuer, root, *_export_arguments(case, workspace), "--output", str(destination)
            )
            _check(receipt, case)
            manifest = (destination / "manifest.json").read_bytes()
            assert _digest(manifest) == receipt["bundle_id"]
            issued[case["name"]] = receipt
        assert _tree(workspace) == before_workspace
        first = source["cases"][0]
        original_bundle = staged / first["name"]
        first_tree = _tree(original_bundle)
        assert _run(
            issuer, root, *_export_arguments(first, workspace), "--output", str(original_bundle),
            expected=3,
        )["error"]
        assert _tree(original_bundle) == first_tree
        duplicate = root / "duplicate"
        repeated = _run(
            issuer, root, *_export_arguments(first, workspace), "--output", str(duplicate)
        )
        assert repeated["bundle_id"] == issued[first["name"]]["bundle_id"]
        assert repeated["report"] == issued[first["name"]]["report"]
        wrong = list(_export_arguments(first, workspace))
        wrong[3] = "0" * 64
        wrong_output = root / "wrong-report"
        refused = _run(issuer, root, *wrong, "--output", str(wrong_output), expected=2)
        assert refused["error"] and not wrong_output.exists()
        absent = root / "never-created"
        denied = _run(
            issuer, root, "export-search-evidence", "invalid", "--expected-report-id", "invalid",
            "--plans", str(absent), "--store", str(absent), "--registry", str(absent),
            "--runs", str(absent), "--finding-registry", str(absent),
            "--output", str(absent / "output"), "--split", "confirmation", expected=5,
        )
        assert denied["error"]["code"] == "confirmation_access_denied" and not absent.exists()
        assert _tree(workspace) == before_workspace
        relocated = root / "unrelated-parent" / "relocated"
        relocated.parent.mkdir()
        staged.rename(relocated)
        shutil.rmtree(workspace)
        shutil.rmtree(duplicate)
        assert not workspace.exists() and not staged.exists()
        cwd = root / "verifier-cwd"
        cwd.mkdir()
        for case in source["cases"]:
            bundle = relocated / case["name"]
            before = _tree(bundle)
            exported = issued[case["name"]]
            command = (
                "verify-search-evidence", str(bundle), "--expected-bundle-id",
                exported["bundle_id"],
            )
            verified = _run(verifier, cwd, *command)
            _check(verified, case)
            assert verified["bundle_id"] == exported["bundle_id"]
            assert verified["diagnostics"] == exported["diagnostics"]
            assert verified["snapshot"] == exported["snapshot"]
            assert _run(verifier, cwd, *command) == verified
            assert _tree(bundle) == before
            cases.append({
                "name": case["name"], "export": exported, "verification": verified,
                "issuer_workspace_deleted": True, "bundle_relocated": True,
                "same_semantic_report": True, "diagnostics_recomputed": True,
                "core_only_offline_guard": True, "readonly_byte_tree_preserved": True,
                "same_receipt_on_repeat": True,
            })
        first_bundle = relocated / first["name"]
        assert _run(
            verifier, cwd, "verify-search-evidence", str(first_bundle),
            "--expected-bundle-id", "0" * 64, expected=2,
        )["error"]
        assert _run(
            verifier, cwd, "verify-search-evidence", str(absent),
            "--split", "confirmation", expected=5,
        )["error"]["code"] == "confirmation_access_denied"
        assert not absent.exists()
        missing = root / "missing-object"
        shutil.copytree(first_bundle, missing)
        manifest = json.loads((missing / "manifest.json").read_bytes())
        raw = manifest["roles"]["raw"]
        (missing / raw["ref"]).unlink()
        error = _run(
            verifier, cwd, "verify-search-evidence", str(missing), expected=3
        )["error"]
        assert error["code"] == "search_evidence_object_missing"
        assert error["sha256"] == raw["sha256"]
        assert "raw" in error["roles"]
        attacks = []
        for name, diagnostic in (("finding", False), ("diagnostics", True)):
            attack = root / ("rehash-" + name)
            attack_id = _rehash_attack(first_bundle, attack, diagnostics=diagnostic)
            refused = _run(
                verifier, cwd, "verify-search-evidence", str(attack),
                "--expected-bundle-id", attack_id, expected=2,
            )
            assert refused["error"] and "report" not in refused
            attacks.append(name)
        assert _tree(original_records) == original_tree
        arguments.bundles_dir.mkdir(parents=True, exist_ok=False)
        for case in source["cases"]:
            shutil.copytree(relocated / case["name"], arguments.bundles_dir / case["name"])
        acceptance = {
            "kind": "installed_search_evidence_acceptance_v1", "accepted": True,
            "synthetic_data": True, "source_native_execution": source["native_execution"],
            "new_native_calls": False, "new_attempts_reserved": False,
            "source_records_unchanged": True, "issuer_workspace_deleted": True,
            "wrong_report_pin_rejected": True, "wrong_bundle_pin_rejected": True,
            "no_overwrite_verified": True, "same_evidence_same_bundle_identity": True,
            "confirmation_refused_before_io": True, "missing_object_error": error,
            "fully_rehashed_attacks_rejected": attacks, "cases": cases,
        }
        arguments.report.write_text(json.dumps(acceptance, sort_keys=True, indent=2) + "\n")
        print(
            "Installed portable search evidence: relocation and offline semantic re-audit passed."
        )


if __name__ == "__main__":
    main()
