#!/usr/bin/env python3
"""Qualify installed finding authority, issue and independent core verification.

The input pairs were produced by the preceding installed-evidence smoke. This
control process uses stdlib only and creates no research attempts or native runs.
All product actions use isolated installed core interpreters on remote workers.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

PAIR_ROLES = frozenset({
    "protocol", "dataset_manifest", "raw", "normalized", "report",
    "front_result", "front_evaluation", "front_receipt",
    "back_result", "back_evaluation", "back_receipt", "assessment",
})
_GUARD = '''
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
    raise AssertionError('Finding smoke requires an installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Finding workflow cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry
from tickwitness.infrastructure.tagged_finding_registry import LocalTaggedFindingRegistry
def forbidden(*args, **kwargs):
    raise AssertionError('Finding workflow cannot access database, network or workers')
sqlite3.connect = forbidden
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
for repository in (LocalAttemptLedger, LocalExecutableProtocolRegistry, LocalDatasetStore):
    repository.__init__ = forbidden
if sys.argv[1] == 'verify-tagged-findings':
    for repository in (LocalTaggedQueueRegistry, LocalTaggedFindingRegistry):
        repository.__init__ = forbidden
raise SystemExit(main(sys.argv[1:]))
'''
_SETUP_SUBJECT = '''
import json
from pathlib import Path
import sys
from tickwitness.domain.research_contracts.tagged_queue_protocol import load_tagged_queue_protocol
from tickwitness.infrastructure.tagged_evidence_bundles import read_tagged_pair_bundle
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry
pair = read_tagged_pair_bundle(Path(sys.argv[1]))
subject = load_tagged_queue_protocol(pair.artifacts['protocol'])
assert subject.document['scope']['finding_issued'] is False
stored = LocalTaggedQueueRegistry(Path(sys.argv[2]), create=True).seal(subject.canonical_bytes)
print(json.dumps({'subject_protocol_id': stored.protocol_id, 'source_pair_bundle_id': pair.bundle_id}))
'''
_INELIGIBLE_PAIR = '''
import json
from pathlib import Path
import sys
from tickwitness.domain.evidence.run_records import canonical, digest
from tickwitness.domain.evidence.tagged_pair_verification import assess_tagged_pair_artifacts
from tickwitness.domain.evidence.tagged_queue_evaluation import evaluate_tagged_queue_replay
from tickwitness.domain.evidence.tagged_queue_records import build_tagged_queue_run_receipt
from tickwitness.domain.replay.tagged_queue_contracts import TaggedQueueReplayInput, build_tagged_queue_replay_result
from tickwitness.domain.research_contracts.tagged_queue_protocol import load_tagged_queue_protocol, TAGGED_POLICY_IDS
from tickwitness.infrastructure.tagged_evidence_bundles import read_tagged_pair_bundle, export_tagged_pair_bundle
pair = read_tagged_pair_bundle(Path(sys.argv[1]))
payload = pair.artifacts
subject = load_tagged_queue_protocol(payload['protocol'])
changed = json.loads(payload['back_result'])
changed['environment']['platform'] += '-controlled-ineligible-label'
result = build_tagged_queue_replay_result(changed)
evaluation = evaluate_tagged_queue_replay(TaggedQueueReplayInput(subject, payload['normalized'], TAGGED_POLICY_IDS[1]), result)
receipt = json.loads(payload['back_receipt'])
receipt['bindings'] = {'replay_result_sha256': digest(result.canonical_bytes), 'evaluation_sha256': evaluation.evaluation_id}
payload['back_result'] = result.canonical_bytes
payload['back_evaluation'] = evaluation.canonical_bytes
payload['back_receipt'] = build_tagged_queue_run_receipt(receipt).canonical_bytes
payload.pop('assessment')
assessment = assess_tagged_pair_artifacts(payload)
assert assessment.document['comparison']['relation'] == 'ineligible'
payload['assessment'] = assessment.canonical_bytes
bundle = export_tagged_pair_bundle(Path(sys.argv[2]), payload)
print(json.dumps({'bundle_id': bundle.bundle_id, 'assessment': assessment.document}))
'''


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def _run(interpreter: str, cwd: Path, *command: str, expected: int = 0) -> dict:
    process = subprocess.run([interpreter, "-I", "-c", _GUARD, *command], cwd=cwd,
                             capture_output=True, text=True, check=False, timeout=180)
    if process.returncode != expected:
        raise RuntimeError(f"Installed finding workflow exited {process.returncode}: "
                           f"{process.stdout}\n{process.stderr}")
    return json.loads(process.stdout if process.stdout else process.stderr)


def _helper(interpreter: str, cwd: Path, source: str, *arguments: str) -> dict:
    process = subprocess.run([interpreter, "-I", "-c", source, *arguments], cwd=cwd,
                             capture_output=True, text=True, check=False, timeout=180)
    if process.returncode:
        raise RuntimeError(f"Finding smoke setup failed: {process.stderr}")
    return json.loads(process.stdout)


def _payload(root: Path) -> dict[str, bytes]:
    manifest = json.loads((root / "manifest.json").read_bytes())
    return {role: (root / "objects" / "sha256" / reference["sha256"]).read_bytes()
            for role, reference in manifest["roles"].items()}


def _identity(payload: dict[str, bytes], *, pair: bool) -> str:
    selected = {role: value for role, value in payload.items() if not pair or role in PAIR_ROLES}
    return _digest(_canonical({
        "kind": "tagged_queue_pair_evidence_bundle_v1" if pair else "tagged_finding_evidence_bundle_v1",
        "schema_version": 1,
        "scope": "development_tagged_queue_pair_v1" if pair else "development_conditional_tagged_findings_v1",
        "roles": {role: {"sha256": _digest(value), "size_bytes": len(value),
                         "ref": "objects/sha256/" + _digest(value)}
                  for role, value in selected.items()},
    }))


def _write(payload: dict[str, bytes], destination: Path) -> str:
    objects = destination / "objects" / "sha256"
    objects.mkdir(parents=True)
    for data in payload.values():
        (objects / _digest(data)).write_bytes(data)
    manifest = _canonical({
        "kind": "tagged_finding_evidence_bundle_v1", "schema_version": 1,
        "scope": "development_conditional_tagged_findings_v1",
        "roles": {role: {"sha256": _digest(data), "size_bytes": len(data),
                         "ref": "objects/sha256/" + _digest(data)}
                  for role, data in payload.items()},
    })
    (destination / "manifest.json").write_bytes(manifest)
    return _digest(manifest)


def _replace(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    return value


def _attack(source: Path, destination: Path, *, allocation: bool) -> str:
    payload = _payload(source)
    if not allocation:
        report = json.loads(payload["finding_report"])
        report["findings"][0]["type"] = "UNAUTHORIZED_FINDING"
        payload["finding_report"] = _canonical(report)
    else:
        replacements: dict[str, str] = {}
        old_pair_id = _identity(payload, pair=True)
        result = json.loads(payload["front_result"])
        next(row for row in result["queue_trace"] if row["kind"] == "trade")["flow"]["external_trade_behind_lots"] += 1
        changed = _canonical(result)
        replacements[_digest(payload["front_result"])] = _digest(changed)
        payload["front_result"] = changed
        for role in ("front_evaluation", "front_receipt", "assessment"):
            original = payload[role]
            changed = _canonical(_replace(json.loads(original), replacements))
            replacements[_digest(original)] = _digest(changed)
            payload[role] = changed
        replacements[old_pair_id] = _identity(payload, pair=True)
        payload["finding_report"] = _canonical(_replace(json.loads(payload["finding_report"]), replacements))
    return _write(payload, destination)


def _check(receipt: dict, expected_types: set[str], pair_id: str, truths: list[bool]) -> None:
    assert receipt["source_pair_bundle_id"] == pair_id
    assert receipt["finalization_status"] == "FINAL"
    assert receipt["finalization_basis"] == "sealed_finding_evidence_content_v1"
    for flag in ("integrity_verified", "bindings_verified", "source_revalidated",
                 "queue_execution_audited", "findings_recomputed"):
        assert receipt[flag] is True
    for flag in ("native_replayed", "author_signature_verified", "human_domain_approval_verified",
                 "original_publication_verified", "confirmation_reference_checked",
                 "full_attempt_ledger_checked", "ledger_commitment_checked"):
        assert receipt[flag] is False
    report = receipt["report"]
    assert report["execution_status"] == "completed"
    assert {finding["type"] for finding in report["findings"]} == expected_types
    assert len(report["findings"]) == len(expected_types)
    for finding in report["findings"]:
        target = ("per_interpretation_predicate_truth_given_public_observations_v1"
                  if finding["type"] == "NOT_IDENTIFIABLE_WITHIN_MODEL"
                  else "robust_satisfaction_across_listed_witnesses_v1")
        assert finding["conclusion_target"] == target
        if finding["type"] == "COUNTEREXAMPLE_FOUND":
            expected_policies = [policy for policy, truth in zip(
                ("protected_tag_front_cancel_v1", "protected_tag_back_cancel_v1"),
                truths, strict=True) if truth is False]
            assert [witness["policy_id"] for witness in finding["witnesses"]] == expected_policies
            assert all(witness["truth"] is False for witness in finding["witnesses"])
        else:
            assert [witness["truth"] for witness in finding["witnesses"]] == truths
    assert isinstance(report["completeness"], dict)


def _case(issuer: str, verifier: str, source: Path, source_case: dict, root: Path,
          request: Path, preserved: Path | None) -> dict:
    root.mkdir()
    pair = root / "pair"
    shutil.copytree(source, pair)
    before_pair = _tree(pair)
    registry = root / "authority-registry"
    setup = _helper(issuer, root, _SETUP_SUBJECT, str(pair), str(registry))
    pair_id = source_case["verification"]["bundle_id"]
    assert setup["source_pair_bundle_id"] == pair_id
    assert _identity(_payload(pair), pair=True) == pair_id
    freeze_args = ("freeze-tagged-finding-protocol", setup["subject_protocol_id"], request.name,
                   "--input-root", str(request.parent), "--registry", str(registry))
    frozen = _run(issuer, root, *freeze_args)
    repeated = _run(issuer, root, *freeze_args)
    authority_id = frozen["finding_protocol_id"]
    assert frozen["created"] is True and repeated["created"] is False
    assert repeated["finding_protocol_id"] == authority_id
    assert _digest(_canonical(frozen["protocol"])) == authority_id
    inspected = _run(issuer, root, "inspect-tagged-finding-protocol", authority_id,
                     "--registry", str(registry))
    assert inspected["protocol"] == frozen["protocol"]
    before_registry = _tree(registry)
    output, duplicate = root / "issued", root / "duplicate"
    issue_args = ("issue-tagged-findings", authority_id, str(pair), "--expected-bundle-id", pair_id,
                  "--registry", str(registry))
    issued = _run(issuer, root, *issue_args, "--output", str(output))
    duplicate_receipt = _run(issuer, root, *issue_args, "--output", str(duplicate))
    assert duplicate_receipt == issued
    assert _tree(registry) == before_registry and _tree(pair) == before_pair
    truths = {
        (100, "gt"): [False, False],
        (102, "gt"): [True, False],
        (102, "ge"): [True, True],
        (100, "ge"): [False, True],
    }[(source_case["mark_ticks"], source_case["comparator"])]
    assert source_case["verification"]["assessment"]["comparison"]["truths"] == truths
    expected_types = ({"NOT_IDENTIFIABLE_WITHIN_MODEL", "COUNTEREXAMPLE_FOUND"}
                      if truths[0] != truths[1] else {"COUNTEREXAMPLE_FOUND"}
                      if truths[0] is False else {"NO_COUNTEREXAMPLE_FOUND"})
    _check(issued, expected_types, pair_id, truths)
    assert issued["finding_protocol_id"] == authority_id
    original_output = _tree(output)
    assert _run(issuer, root, *issue_args, "--output", str(output), expected=3)["error"]
    assert _tree(output) == original_output
    wrong_output = root / "wrong-pin-output"
    refused = _run(issuer, root, "issue-tagged-findings", authority_id, str(pair),
                   "--expected-bundle-id", "0" * 64, "--registry", str(registry),
                   "--output", str(wrong_output), expected=2)
    assert refused["error"] and not wrong_output.exists()
    ineligible_path = root / "ineligible-pair"
    ineligible = _helper(issuer, root, _INELIGIBLE_PAIR, str(pair), str(ineligible_path))
    unknown_output = root / "must-not-issue"
    blocked = _run(issuer, root, "issue-tagged-findings", authority_id, str(ineligible_path),
                   "--expected-bundle-id", ineligible["bundle_id"], "--registry", str(registry),
                   "--output", str(unknown_output), expected=9)
    assert blocked["error"]["code"] == "tagged_finding_ineligible" and not unknown_output.exists()
    missing = root / "missing"
    denied = _run(issuer, root, "freeze-tagged-finding-protocol", "bad", "missing.json",
                  "--input-root", str(missing), "--registry", str(missing / "registry"),
                  "--split", "confirmation", expected=5)
    assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
    relocated = root / "relocated-finding"
    output.rename(relocated)
    shutil.rmtree(registry)
    shutil.rmtree(pair)
    shutil.rmtree(ineligible_path)
    shutil.rmtree(duplicate)
    assert not registry.exists() and not pair.exists()
    before = _tree(relocated)
    verified = _run(verifier, root, "verify-tagged-findings", str(relocated),
                    "--expected-bundle-id", issued["bundle_id"])
    assert verified == issued
    _check(verified, expected_types, pair_id, truths)
    assert _run(verifier, root, "verify-tagged-findings", str(relocated),
                "--expected-bundle-id", "0" * 64, expected=2)["error"]
    assert _run(verifier, root, "verify-evidence", str(relocated), expected=3)["error"]
    assert _run(verifier, root, "verify-tagged-queue-pair", str(relocated), expected=3)["error"]
    assert _run(verifier, root, "verify-tagged-findings", str(source), expected=3)["error"]
    denied = _run(verifier, root, "verify-tagged-findings", str(missing),
                  "--split", "confirmation", expected=5)
    assert denied["error"]["code"] == "confirmation_access_denied" and not missing.exists()
    attacks = []
    for name, allocation in (("report", False), ("allocation", True)):
        altered = root / ("rehashed-" + name)
        altered_id = _attack(relocated, altered, allocation=allocation)
        refused = _run(verifier, root, "verify-tagged-findings", str(altered),
                       "--expected-bundle-id", altered_id, expected=2)
        assert refused["error"]
        attacks.append(name)
    assert _tree(relocated) == before
    assert _tree(source) == before_pair
    if preserved is not None:
        shutil.copytree(relocated, preserved)
    return {"mark_ticks": source_case["mark_ticks"], "comparator": source_case["comparator"],
            "source_pair_bundle_id": pair_id, "frozen": frozen, "issuance": issued,
            "verification": verified, "authority_registry_and_issuance_pair_deleted": True,
            "core_only_guard_verified": True, "ineligible_pair_refused_without_output": True,
            "no_overwrite_verified": True, "same_evidence_same_identity": True,
            "read_only_tree_verified": True, "wrong_identity_pin_rejected": True,
            "legacy_kind_isolation_verified": True, "fully_rehashed_attacks_rejected": attacks}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--verifier-python", type=Path, required=True)
    parser.add_argument("--pairs-dir", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--bundles-dir", type=Path, required=True)
    args = parser.parse_args()
    source_report = json.loads(args.source_report.read_bytes())
    assert source_report["accepted"] is True
    args.bundles_dir.mkdir(parents=True, exist_ok=False)
    request = Path(__file__).resolve().parents[1] / "examples" / "tagged-finding-request.json"
    cases = []
    with TemporaryDirectory(prefix="tickwitness-finding-authority-") as temporary:
        root = Path(temporary)
        for case in source_report["cases"]:
            prefix = "standard-" if case["mark_ticks"] == 100 else "bid102-"
            name = prefix + case["comparator"]
            cases.append(_case(str(args.python.absolute()), str(args.verifier_python.absolute()),
                               args.pairs_dir / name, case, root / name, request,
                               args.bundles_dir / name))
    report = {"kind": "installed_tagged_finding_acceptance_v1", "accepted": True,
              "source_fresh_native_runs": source_report["fresh_native_runs"],
              "new_native_calls": False, "cases": cases}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print("Installed tagged findings: explicit frozen authority, scoped findings, relocated "
          "core verification and fully rehashed attacks passed without new native calls.")


if __name__ == "__main__":
    main()
