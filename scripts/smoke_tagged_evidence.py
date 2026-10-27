#!/usr/bin/env python3
"""Exercise installed native export and core-only tagged pair verification remotely.

Only stdlib is imported by this control process. Product operations use isolated
installed interpreters; original stores are deleted before the core verifies the
relocated fixed-tree bundle. Fixtures are original synthetic public observations.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

POLICIES = ["protected_tag_front_cancel_v1", "protected_tag_back_cancel_v1"]
_OFFLINE_GUARD = """
import importlib.abc
from importlib import metadata
import socket
import sqlite3
import subprocess
import sys
try:
    metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Verifier environment must have no native extra installed')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Offline verifier cannot import native')
sys.meta_path.insert(0, NoNative())
def forbidden(*args, **kwargs):
    raise AssertionError('Offline verifier cannot access stores, database, network or worker')
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry
sqlite3.connect = forbidden
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
for repository in (LocalAttemptLedger, LocalExecutableProtocolRegistry,
                   LocalDatasetStore, LocalTaggedQueueRegistry):
    repository.__init__ = forbidden
raise SystemExit(main(sys.argv[1:]))
"""
_GOLDEN_BUNDLE = """
import json
from pathlib import Path
import sys
from tickwitness.application.tagged_pair_evidence import verify_tagged_pair_package
from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.evidence.tagged_pair_verification import assess_tagged_pair_artifacts
from tickwitness.infrastructure.tagged_evidence_bundles import export_tagged_pair_bundle
recorded = json.loads(Path(sys.argv[1]).read_bytes())
assert recorded['provenance']['engineering_run'] == 40286175944
assert recorded['provenance']['job'] == 121450395382
mark = int(sys.argv[3])
selected = next(case for case in recorded['cases'] if case['final_mark_ticks'] == mark)
rows = [json.loads(line) for line in Path(sys.argv[2]).read_bytes().splitlines()]
if mark != 100:
    rows[-1]['bids'].append([mark, 2])
raw = ''.join(json.dumps(row) + chr(10) for row in rows).encode()
validated = normalize_events(raw)
artifacts = {'protocol': canonical(selected['protocol']), 'raw': raw,
             'normalized': validated.normalized_bytes, 'report': canonical(validated.report)}
manifest = {'schema_version': 1, 'format_id': 'tickwitness.normalized-events.v1',
            'objects': {role: {'sha256': digest(artifacts[role]),
                               'size_bytes': len(artifacts[role]),
                               'ref': 'objects/sha256/' + digest(artifacts[role])}
                        for role in ('raw', 'normalized', 'report')}}
artifacts['dataset_manifest'] = canonical(manifest)
dataset_id = selected['protocol']['bindings']['development_dataset_id']
assert digest(artifacts['dataset_manifest']) == dataset_id
for prefix, run in zip(('front', 'back'), selected['runs'], strict=True):
    for role in ('result', 'evaluation', 'receipt'):
        artifacts[prefix + '_' + role] = canonical(run[role])
artifacts['assessment'] = assess_tagged_pair_artifacts(artifacts).canonical_bytes
bundle = export_tagged_pair_bundle(Path(sys.argv[4]), artifacts)
print(json.dumps(verify_tagged_pair_package(bundle), sort_keys=True))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def _run(
    interpreter: str, cwd: Path, *command: str, expected: int = 0, guarded: bool = False
) -> dict:
    invocation = (
        [interpreter, "-I", "-c", _OFFLINE_GUARD]
        if guarded
        else [interpreter, "-I", "-m", "tickwitness"]
    )
    completed = subprocess.run(
        [*invocation, *command], cwd=cwd, capture_output=True, text=True, check=False, timeout=180
    )
    if completed.returncode != expected:
        raise RuntimeError(
            f"Installed tagged evidence exited {completed.returncode}: "
            f"{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(completed.stdout if completed.stdout else completed.stderr)


def _replace(value: object, substitutions: dict[str, str]) -> object:
    if isinstance(value, str):
        return substitutions.get(value, value)
    if isinstance(value, list):
        return [_replace(item, substitutions) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, substitutions) for key, item in value.items()}
    return value


def _rehash_allocation_attack(source: Path, destination: Path) -> str:
    """Keep every outer hash closed while falsifying a native trade partition."""
    manifest = json.loads((source / "manifest.json").read_bytes())
    payload = {
        role: (source / reference["ref"]).read_bytes()
        for role, reference in manifest["roles"].items()
    }
    substitutions: dict[str, str] = {}
    result = json.loads(payload["front_result"])
    trade = next(row for row in result["queue_trace"] if row["kind"] == "trade")
    trade["flow"]["external_trade_behind_lots"] += 1
    changed = _canonical(result)
    substitutions[_digest(payload["front_result"])] = _digest(changed)
    payload["front_result"] = changed
    for role in ("front_evaluation", "front_receipt", "assessment"):
        original = payload[role]
        changed = _canonical(_replace(json.loads(original), substitutions))
        substitutions[_digest(original)] = _digest(changed)
        payload[role] = changed
    for role, data in payload.items():
        content_hash = _digest(data)
        manifest["roles"][role] = {
            "sha256": content_hash,
            "size_bytes": len(data),
            "ref": f"objects/sha256/{content_hash}",
        }
    objects = destination / "objects" / "sha256"
    objects.mkdir(parents=True)
    for data in payload.values():
        (objects / _digest(data)).write_bytes(data)
    manifest_bytes = _canonical(manifest)
    (destination / "manifest.json").write_bytes(manifest_bytes)
    return _digest(manifest_bytes)


def _check_receipt(receipt: dict, *, relation: str, truths: list[bool]) -> None:
    assert receipt["kind"] == "tagged_queue_pair_offline_verification_v1"
    for field in (
        "integrity_verified",
        "bindings_verified",
        "source_revalidated",
        "queue_execution_audited",
    ):
        assert receipt[field] is True
    for field in (
        "native_replayed",
        "author_signature_verified",
        "confirmation_reference_checked",
        "full_attempt_ledger_checked",
        "ledger_commitment_checked",
    ):
        assert receipt[field] is False
    assessment = receipt["assessment"]
    assert assessment["kind"] == "tagged_queue_pair_assessment_v1"
    assert assessment["findings"] == []
    assert assessment["scope"]["source_claim_evaluated"] is False
    assert assessment["scope"]["finding_issued"] is False
    assert [item["policy_id"] for item in assessment["runs"]] == POLICIES
    assert [item["truth"] for item in assessment["runs"]] == truths
    assert assessment["comparison"]["relation"] == relation
    assert assessment["comparison"]["same_execution_environment"] is True
    assert assessment["comparison"]["ineligible_reason"] is None


def _case(
    interpreter: str,
    verifier: str,
    examples: Path,
    root: Path,
    *,
    mark: int,
    comparator: str,
    preserved: Path | None,
) -> dict:
    root.mkdir()
    state = root / "original-state"
    state.mkdir()
    fixtures = state / "fixtures"
    fixtures.mkdir()
    observations = [
        json.loads(line)
        for line in (examples / "queue-observations.jsonl").read_text().splitlines()
    ]
    if mark != 100:
        observations[-1]["bids"].append([mark, 2])
    (fixtures / "observations.jsonl").write_bytes(
        b"\n".join(_canonical(row) for row in observations) + b"\n"
    )
    (fixtures / "confirmation.jsonl").write_bytes(
        (examples / "replay-confirmation.jsonl").read_bytes()
    )
    for name in ("experiment-request.json", "queue-constraint-request.json"):
        (fixtures / name).write_bytes((examples / name).read_bytes())
    request = json.loads((examples / "tagged-queue-request.json").read_bytes())
    request["claim"]["comparator"] = comparator
    (fixtures / "tagged-request.json").write_bytes(_canonical(request))
    store, registry, ledger = [state / name for name in ("data", "registry", "ledger")]

    def run(*command: str, expected: int = 0) -> dict:
        return _run(interpreter, root, *command, expected=expected)

    datasets = [
        run("import-events", name, "--input-root", str(fixtures), "--store", str(store))[
            "dataset_id"
        ]
        for name in ("observations.jsonl", "confirmation.jsonl")
    ]
    source = run(
        "freeze-experiment",
        "experiment-request.json",
        "--input-root",
        str(fixtures),
        "--development-dataset",
        datasets[0],
        "--confirmation-dataset",
        datasets[1],
        "--store",
        str(store),
        "--registry",
        str(registry),
    )
    frozen = run(
        "freeze-tagged-queue",
        source["protocol_id"],
        "tagged-request.json",
        "queue-constraint-request.json",
        "--input-root",
        str(fixtures),
        "--store",
        str(store),
        "--registry",
        str(registry),
    )
    common = ("--store", str(store), "--registry", str(registry), "--ledger", str(ledger))
    submitted = run("run-tagged-queue-pair", frozen["protocol_id"], *common)
    assert submitted["status"] == "completed"
    front, back = submitted["runs"]
    assert front["attempt_id"] != back["attempt_id"]
    assert [item["evaluation"]["filled_quantity_lots"] for item in (front, back)] == [2, 0]
    truths = {
        (100, "gt"): [False, False],
        (102, "gt"): [True, False],
        (102, "ge"): [True, True],
        (100, "ge"): [False, True],
    }[(mark, comparator)]
    relation = "opposite_truth_values" if truths[0] != truths[1] else "same_truth_value"
    bundle, repeated = root / "bundle", root / "repeated"
    before = _tree(state)
    exported = run(
        "export-tagged-queue-pair",
        front["run_id"],
        back["run_id"],
        *common,
        "--output",
        str(bundle),
    )
    reverse = run(
        "export-tagged-queue-pair",
        back["run_id"],
        front["run_id"],
        *common,
        "--output",
        str(repeated),
    )
    assert exported == reverse and before == _tree(state)
    _check_receipt(exported, relation=relation, truths=truths)
    destination_before = _tree(bundle)
    refused = run(
        "export-tagged-queue-pair",
        front["run_id"],
        back["run_id"],
        *common,
        "--output",
        str(bundle),
        expected=3,
    )
    assert refused["error"]["code"] == "bundle_destination_exists"
    assert _tree(bundle) == destination_before and before == _tree(state)
    missing = root / "must-not-exist"
    denied = run(
        "export-tagged-queue-pair",
        "a" * 64,
        "b" * 64,
        "--store",
        str(missing / "data"),
        "--registry",
        str(missing / "registry"),
        "--ledger",
        str(missing / "ledger"),
        "--output",
        str(missing / "output"),
        "--split",
        "confirmation",
        expected=5,
    )
    assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
    relocated = root / "relocated"
    bundle.rename(relocated)
    shutil.rmtree(state)
    shutil.rmtree(repeated)
    assert not state.exists() and not bundle.exists()
    empty = root / "empty-verifier-cwd"
    empty.mkdir()

    def offline(*command: str, expected: int = 0) -> dict:
        return _run(verifier, empty, *command, expected=expected, guarded=True)

    source_before = _tree(relocated)
    verified = offline(
        "verify-tagged-queue-pair", str(relocated), "--expected-bundle-id", exported["bundle_id"]
    )
    assert verified == exported
    _check_receipt(verified, relation=relation, truths=truths)
    wrong_pin = offline(
        "verify-tagged-queue-pair", str(relocated), "--expected-bundle-id", "0" * 64, expected=2
    )
    assert wrong_pin["error"]
    assert offline("verify-evidence", str(relocated), expected=3)["error"]
    assert offline("verify-tagged-queue-pair", str(examples / "evidence-demo"), expected=3)["error"]
    denied = offline(
        "verify-tagged-queue-pair", str(missing / "bundle"), "--split", "confirmation", expected=5
    )
    assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
    assert _tree(relocated) == source_before
    attack = root / "rehashed-allocation-attack"
    attack_id = _rehash_allocation_attack(relocated, attack)
    rejected = offline(
        "verify-tagged-queue-pair", str(attack), "--expected-bundle-id", attack_id, expected=2
    )
    assert rejected["error"]
    assert _tree(relocated) == source_before
    if preserved is not None:
        shutil.copytree(relocated, preserved)
    return {
        "mark_ticks": mark,
        "comparator": comparator,
        "submission": submitted,
        "export": exported,
        "verification": verified,
        "bundle_manifest": json.loads((relocated / "manifest.json").read_bytes()),
        "original_state_deleted": True,
        "core_only_guard_verified": True,
        "read_only_tree_verified": True,
        "reverse_export_same_identity": True,
        "no_overwrite_verified": True,
        "wrong_identity_pin_rejected": True,
        "legacy_kind_isolation_verified": True,
        "fully_rehashed_allocation_attack_rejected": True,
    }


def _core_case(
    verifier: str, examples: Path, root: Path, *, mark: int, preserved: Path | None
) -> dict:
    """Build portable evidence from actual recorded callbacks, without a new run."""
    root.mkdir()
    bundle = root / "bundle"
    completed = subprocess.run(
        [
            verifier,
            "-I",
            "-c",
            _GOLDEN_BUNDLE,
            str(examples.parent / "tests" / "fixtures" / "tagged-pair-native-golden.json"),
            str(examples / "queue-observations.jsonl"),
            str(mark),
            str(bundle),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if completed.returncode:
        raise RuntimeError(f"Installed core golden closure failed: {completed.stderr}")
    exported = json.loads(completed.stdout)
    relocated = root / "relocated"
    bundle.rename(relocated)
    before = _tree(relocated)
    verified = _run(
        verifier,
        root,
        "verify-tagged-queue-pair",
        str(relocated),
        "--expected-bundle-id",
        exported["bundle_id"],
        guarded=True,
    )
    truths = [False, False] if mark == 100 else [True, False]
    relation = "same_truth_value" if mark == 100 else "opposite_truth_values"
    _check_receipt(verified, relation=relation, truths=truths)
    assert verified == exported and _tree(relocated) == before
    attack = root / "rehashed-allocation-attack"
    attack_id = _rehash_allocation_attack(relocated, attack)
    rejected = _run(
        verifier,
        root,
        "verify-tagged-queue-pair",
        str(attack),
        "--expected-bundle-id",
        attack_id,
        expected=2,
        guarded=True,
    )
    assert rejected["error"] and _tree(relocated) == before
    if preserved is not None:
        shutil.copytree(relocated, preserved)
    return {
        "mark_ticks": mark,
        "comparator": "gt",
        "verification": verified,
        "recorded_engineering_run": 40286175944,
        "recorded_native_job": 121450395382,
        "fresh_native_runs": False,
        "original_state_absent": True,
        "core_only_guard_verified": True,
        "read_only_tree_verified": True,
        "fully_rehashed_allocation_attack_rejected": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--verifier-python", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--bundles-dir", type=Path)
    parser.add_argument("--core-only", action="store_true")
    arguments = parser.parse_args()
    examples = Path(__file__).resolve().parents[1] / "examples"
    if arguments.bundles_dir is not None:
        arguments.bundles_dir.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="tickwitness-tagged-evidence-") as temporary:
        root = Path(temporary)
        cases = []
        profiles = (("standard-gt", 100, "gt"), ("bid102-gt", 102, "gt"))
        if not arguments.core_only:
            profiles += (("bid102-ge", 102, "ge"), ("standard-ge", 100, "ge"))
        for name, mark, comparator in profiles:
            preserved = None if arguments.bundles_dir is None else arguments.bundles_dir / name
            if arguments.core_only:
                cases.append(
                    _core_case(
                        str(arguments.verifier_python.absolute()),
                        examples,
                        root / name,
                        mark=mark,
                        preserved=preserved,
                    )
                )
            else:
                cases.append(
                    _case(
                        str(arguments.python.absolute()),
                        str(arguments.verifier_python.absolute()),
                        examples,
                        root / name,
                        mark=mark,
                        comparator=comparator,
                        preserved=preserved,
                    )
                )
    report = {
        "kind": "installed_tagged_pair_evidence_acceptance_v1",
        "accepted": True,
        "fixture_kind": "original_synthetic",
        "cases": cases,
        "fresh_native_runs": not arguments.core_only,
        "source_claim_evaluated": False,
        "finding_issued": False,
    }
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_bytes(_canonical(report) + b"\n")
    print(
        "Installed tagged pair evidence: relocated bundles audited by core without original "
        "stores, native, SQLite, network or workers; identity and rehash attacks passed."
    )


if __name__ == "__main__":
    main()
