"""Portable integrity, binding and accounting verification; no native engine is run."""

from typing import cast

from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.evidence.protocol_evaluation import SCOPE, ProtocolEvaluation
from tickwitness.domain.evidence.run_records import (
    EvidenceValidationError,
    canonical,
    digest,
    load_run_receipt,
    parse,
)
from tickwitness.domain.replay.contracts import ReplayInput, load_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import load_executable_protocol

ROLES = frozenset(
    {
        "protocol",
        "dataset_manifest",
        "raw",
        "normalized",
        "report",
        "replay_result",
        "evaluation",
        "attempt",
    }
)


def verify_artifacts(artifacts: dict[str, bytes]) -> dict[str, object]:
    """Recompute portable claims; hashes alone do not bless an altered ledger."""
    if (
        not isinstance(artifacts, dict)
        or artifacts.keys() != ROLES
        or any(not isinstance(value, bytes) for value in artifacts.values())
    ):
        raise EvidenceValidationError("Evidence requires the exact immutable role set")
    protocol = load_executable_protocol(artifacts["protocol"])
    document = protocol.document
    references = cast("dict[str, str]", document["datasets"])
    manifest = parse(artifacts["dataset_manifest"], limit=65_536)
    if (
        set(manifest) != {"schema_version", "format_id", "objects"}
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["format_id"] != "tickwitness.normalized-events.v1"
    ):
        raise EvidenceValidationError("Unsupported dataset manifest")
    if digest(artifacts["dataset_manifest"]) != references["development"]:
        raise EvidenceValidationError("Dataset manifest differs from the protocol binding")
    objects = manifest["objects"]
    if not isinstance(objects, dict) or set(objects) != {"raw", "normalized", "report"}:
        raise EvidenceValidationError("Dataset closure is incomplete")
    for role in ("raw", "normalized", "report"):
        content_hash = digest(artifacts[role])
        expected: dict[str, object] = {
            "sha256": content_hash,
            "size_bytes": len(artifacts[role]),
            "ref": f"objects/sha256/{content_hash}",
        }
        if canonical({"reference": objects[role]}) != canonical({"reference": expected}):
            raise EvidenceValidationError(f"Dataset {role} reference does not match content")
    validated = normalize_events(artifacts["raw"])
    if (
        validated.normalized_bytes != artifacts["normalized"]
        or canonical(validated.report) != artifacts["report"]
    ):
        raise EvidenceValidationError("Dataset normalization or quality report does not reproduce")
    if validated.report["quality_status"] != "accepted":
        raise EvidenceValidationError("Quarantined evidence cannot be evaluated")
    spec = build_replay_spec(canonical(cast("dict[str, object]", document["replay_spec"])))
    replay_input = ReplayInput(references["development"], artifacts["normalized"], spec)
    result = load_replay_result(artifacts["replay_result"])
    evaluation = ProtocolEvaluation(protocol, replay_input, result)
    if evaluation.canonical_bytes != artifacts["evaluation"]:
        raise EvidenceValidationError("Protocol valuation or claim observation does not reproduce")
    receipt = load_run_receipt(artifacts["attempt"])
    run = receipt.document
    if (
        run["protocol_id"] != protocol.protocol_id
        or run["claim_revision_id"] != protocol.claim_revision_id
        or run["execution_status"] != result.document["execution_status"]
    ):
        raise EvidenceValidationError("Run receipt does not match protocol and execution")
    if canonical(cast("dict[str, object]", run["scope"])) != canonical(dict(SCOPE)):
        raise EvidenceValidationError("Unsupported run scope")
    budget = cast("dict[str, int]", document["budget"])
    attempt = cast("dict[str, object]", run["attempt"])
    if (
        cast("int", attempt["attempt_index"]) > budget["max_attempts"]
        or attempt["max_wall_seconds"] != budget["max_wall_seconds"]
    ):
        raise EvidenceValidationError("Reservation differs from the frozen attempt budget")
    expected_bindings: dict[str, object] = {
        "dataset_id": references["development"],
        "data_sha256": digest(artifacts["normalized"]),
        "replay_spec_id": spec.spec_id,
        "replay_result_sha256": digest(artifacts["replay_result"]),
        "evaluation_sha256": evaluation.evaluation_id,
    }
    if canonical(cast("dict[str, object]", run["bindings"])) != canonical(expected_bindings):
        raise EvidenceValidationError("Run receipt content bindings do not match")
    return {
        "kind": "offline_verification_receipt_v1",
        "schema_version": 1,
        "run_id": receipt.run_id,
        "protocol_id": protocol.protocol_id,
        "dataset_id": references["development"],
        "evaluation_id": evaluation.evaluation_id,
        "verification_level": "integrity_bindings_accounting_v1",
        "integrity_verified": True,
        "bindings_verified": True,
        "accounting_verified": True,
        "fee_model_verification": cast(
            "dict[str, object]", evaluation.document["replay_evaluation"]
        )["fee_model_verification"],
        "native_replayed": False,
        "author_signature_verified": False,
        "confirmation_reference_checked": False,
        "full_attempt_ledger_checked": False,
        "execution_status": result.document["execution_status"],
        "scope": dict(SCOPE),
        "claim_observation": evaluation.document["claim_observation"],
    }
