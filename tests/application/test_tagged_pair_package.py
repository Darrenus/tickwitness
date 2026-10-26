"""Portable core verification uses recorded real remote native callbacks."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_pair_evidence import export_tagged_pair, verify_tagged_pair_package
from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.evidence.run_records import EvidenceValidationError, canonical, digest
from tickwitness.domain.evidence.tagged_pair_verification import assess_tagged_pair_artifacts
from tickwitness.infrastructure.tagged_evidence_bundles import export_tagged_pair_bundle, read_tagged_pair_bundle

ROOT = Path(__file__).resolve().parents[2]


def golden_payload(final_mark=100):
    golden = json.loads((ROOT / "tests/fixtures/tagged-pair-native-golden.json").read_bytes())
    case = next(item for item in golden["cases"] if item["final_mark_ticks"] == final_mark)
    rows = [json.loads(line) for line in (ROOT / "examples/queue-observations.jsonl").read_bytes().splitlines()]
    if final_mark != 100:
        rows[-1]["bids"].append([final_mark, 2])
    raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
    normalized = normalize_events(raw)
    artifacts = {"protocol": canonical(case["protocol"]), "raw": raw,
                 "normalized": normalized.normalized_bytes, "report": canonical(normalized.report)}
    manifest = {"schema_version": 1, "format_id": "tickwitness.normalized-events.v1", "objects": {
        role: {"sha256": digest(artifacts[role]), "size_bytes": len(artifacts[role]),
               "ref": "objects/sha256/" + digest(artifacts[role])}
        for role in ("raw", "normalized", "report")}}
    artifacts["dataset_manifest"] = canonical(manifest)
    assert digest(artifacts["dataset_manifest"]) == case["protocol"]["bindings"]["development_dataset_id"]
    for prefix, run in zip(("front", "back"), case["runs"], strict=True):
        for role in ("result", "evaluation", "receipt"):
            artifacts[prefix + "_" + role] = canonical(run[role])
    artifacts["assessment"] = assess_tagged_pair_artifacts(artifacts).canonical_bytes
    return artifacts


@pytest.fixture
def sealed_pair(tmp_path):
    artifacts = golden_payload()
    destination = tmp_path / "bundle"
    package = export_tagged_pair_bundle(destination, artifacts)
    return destination, package


def test_export_adapter_cannot_substitute_another_valid_pair(sealed_pair, tmp_path, monkeypatch):
    from tickwitness.application import tagged_pair_evidence as application

    _, requested = sealed_pair
    different = export_tagged_pair_bundle(tmp_path / "different-pair", golden_payload(102))
    assert verify_tagged_pair_package(different)["assessment"]["comparison"]["truths"] == [True, False]
    # Isolate the publication port: source/committed-outcome auditing is covered separately.
    monkeypatch.setattr(application, "tagged_pair_artifacts", lambda *a, **kw: requested.artifacts)
    with pytest.raises(EvidenceValidationError, match="different tagged pair"):
        export_tagged_pair("a" * 64, "b" * 64, split="development", ledger_factory=lambda: None,
            protocols_factory=lambda: None, datasets_factory=lambda: None,
            exporter=lambda _: different)


def test_portable_receipt_distinguishes_economics_from_authorship_or_ledger(sealed_pair):
    destination, package = sealed_pair
    result = verify_tagged_pair_package(read_tagged_pair_bundle(destination), expected_bundle_id=package.bundle_id)
    assert result["bundle_id"] == package.bundle_id
    assert result["assessment"]["comparison"]["truths"] == [False, False]
    assert result["queue_execution_audited"] is True
    for name in ("native_replayed", "author_signature_verified", "confirmation_reference_checked",
                 "full_attempt_ledger_checked", "ledger_commitment_checked"):
        assert result[name] is False
    assert result["assessment"]["findings"] == []


def test_identity_pin_is_checked_before_semantic_artifacts_are_accessed():
    class Untouched:
        bundle_id = "a" * 64
        @property
        def artifacts(self):
            pytest.fail("Wrong identity must be rejected before semantic artifacts")
        @property
        def manifest_bytes(self):
            pytest.fail("Wrong identity must be rejected before accessing manifest")
    with pytest.raises(EvidenceValidationError, match="pinned identity"):
        verify_tagged_pair_package(Untouched(), expected_bundle_id="b" * 64)


def test_package_port_cannot_forge_identity_or_manifest_despite_valid_economics(sealed_pair):
    _, package = sealed_pair
    fake = SimpleNamespace(bundle_id="a" * 64, manifest_bytes=package.manifest_bytes, artifacts=package.artifacts)
    with pytest.raises(EvidenceValidationError, match="identity"):
        verify_tagged_pair_package(fake)
    manifest = package.manifest
    manifest["scope"] = "unapproved_scope"
    wrong = canonical(manifest)
    fake.bundle_id, fake.manifest_bytes = digest(wrong), wrong
    with pytest.raises(EvidenceValidationError, match="manifest"):
        verify_tagged_pair_package(fake)


def test_confirmation_refused_before_any_repository_or_exporter():
    def forbidden(*args):
        pytest.fail("No confirmation access or publication")
    with pytest.raises(ConfirmationAccessDenied):
        export_tagged_pair("not-an-id", "also-invalid", split="confirmation",
            ledger_factory=forbidden, protocols_factory=forbidden,
            datasets_factory=forbidden, exporter=forbidden)
    class Untouched:
        def __getattr__(self, name):
            pytest.fail("No portable evidence reads under confirmation")
    with pytest.raises(ConfirmationAccessDenied):
        verify_tagged_pair_package(Untouched(), split="confirmation")


def test_offline_cli_blocks_native_database_network_worker_and_original_stores(sealed_pair, tmp_path):
    destination, package = sealed_pair
    script = '''
import importlib.abc
import sqlite3
import socket
import subprocess
import sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("nautilus_trader"):
            raise AssertionError("Offline audit cannot import native")
sys.meta_path.insert(0, NoNative())
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry
def forbidden(*args, **kwargs):
    raise AssertionError("Offline audit cannot use original stores, database, network or workers")
sqlite3.connect = forbidden
socket.socket.connect = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
for cls in (LocalAttemptLedger, LocalDatasetStore, LocalTaggedQueueRegistry):
    cls.__init__ = forbidden
raise SystemExit(main(["verify-tagged-queue-pair", sys.argv[1], "--expected-bundle-id", sys.argv[2]]))
'''
    empty = tmp_path / "empty"
    empty.mkdir()
    before = {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    result = subprocess.run([sys.executable, "-I", "-c", script, str(destination), package.bundle_id],
                            cwd=empty, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    verified = json.loads(result.stdout)
    assert verified["native_replayed"] is False and verified["source_revalidated"] is True
    assert before == {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
