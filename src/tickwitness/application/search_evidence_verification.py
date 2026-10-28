"""Rebuild scoped search evidence from immutable in-memory record ports.

No local workspace, SQLite database, native worker, or original store is opened.
FINAL is the supplied evidence's content/audit closure, never proof of an
authentic producer, original publication or complete historical trial ledger.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Never, cast

from tickwitness.application.bounded_search import inspect_bounded_search_campaign
from tickwitness.application.search_execution import inspect_search_campaign
from tickwitness.application.search_findings import evaluate_search_findings
from tickwitness.domain.assumptions.derivation import derive_replay_view
from tickwitness.domain.assumptions.specs import (
    load_assumption_spec,
    load_scenario_spec,
    validate_scenario_spec,
)
from tickwitness.domain.data_evidence.events import normalize_events
from tickwitness.domain.evidence.run_records import AttemptReservation, canonical, digest, parse
from tickwitness.domain.evidence.scenario_records import build_scenario_intent, load_scenario_intent
from tickwitness.domain.evidence.search_evidence import (
    SearchEvidenceValidationError,
    validate_snapshot,
)
from tickwitness.domain.replay.comparison import compare_replay_results
from tickwitness.domain.replay.contracts import ReplayInput, load_replay_result
from tickwitness.domain.replay.specs import build_replay_spec
from tickwitness.domain.research_contracts.executable import ExecutableProtocol, load_executable_protocol
from tickwitness.domain.research_contracts.search_finding_protocol import (
    SearchFindingProtocol,
    load_search_finding_protocol,
)
from tickwitness.domain.search.plans import SearchPlan

type Row = dict[str, object]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SearchEvidenceValidationError(message)


def _same(actual: object, expected: object, message: str) -> None:
    if isinstance(actual, bytes) or isinstance(expected, bytes):
        _require(type(actual) is bytes and type(expected) is bytes and actual == expected, message)
    else:
        _require(canonical({"v": actual}) == canonical({"v": expected}), message)


def _deny(*_args: object, **_kwargs: object) -> Never:
    raise SearchEvidenceValidationError("Sealed search verification cannot reserve, replay or write")


@dataclass(frozen=True, slots=True)
class _DataRecord:
    dataset_id: str
    manifest: Row
    report: Row
    created: bool = False


@dataclass(frozen=True, slots=True)
class _ProtocolRecord:
    protocol_id: str
    canonical_bytes: bytes
    created: bool = False


@dataclass(frozen=True, slots=True)
class _PlanRecord:
    plan_id: str
    canonical_bytes: bytes
    created: bool = False


class _Datasets:
    def __init__(self, dataset_id: str, artifacts: dict[str, bytes]) -> None:
        manifest = parse(artifacts["dataset_manifest"], limit=64 * 1024)
        _require(manifest.keys() == {"schema_version", "format_id", "objects"}, "Source manifest fields differ")
        _same([manifest["schema_version"], manifest["format_id"]],
              [1, "tickwitness.normalized-events.v1"], "Unsupported sealed source format")
        _same(canonical(manifest), artifacts["dataset_manifest"], "Sealed source manifest is not canonical")
        _same(digest(artifacts["dataset_manifest"]), dataset_id, "Sealed source dataset identity differs")
        objects = manifest["objects"]
        _require(isinstance(objects, dict) and objects.keys() == {"raw", "normalized", "report"}, "Source manifest closure differs")
        objects = cast("Row", objects)
        for role in ("raw", "normalized", "report"):
            data = artifacts[role]
            sha = digest(data)
            _same(objects[role], {"sha256": sha, "size_bytes": len(data), "ref": "objects/sha256/" + sha}, "Sealed source reference differs: " + role)
        normalized = normalize_events(artifacts["raw"])
        _same(normalized.normalized_bytes, artifacts["normalized"], "Source raw normalization does not reproduce")
        _same(canonical(normalized.report), artifacts["report"], "Source quality report does not reproduce")
        _same(normalized.report["quality_status"], "accepted", "Sealed source is quarantined")
        self.record = _DataRecord(dataset_id, manifest, parse(artifacts["report"], limit=4 * 1024 * 1024))
        self.normalized = artifacts["normalized"]

    def get(self, dataset_id: str) -> _DataRecord:
        _same(dataset_id, self.record.dataset_id, "Unexpected sealed dataset reference")
        return self.record

    def read_normalized(self, dataset_id: str, *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
        self.get(dataset_id)
        _require(type(max_bytes) is int and 0 < len(self.normalized) <= max_bytes, "Sealed normalized source exceeds the requested bound")
        return self.normalized


class _Registry:
    def __init__(self, protocol: ExecutableProtocol) -> None:
        self.protocol = protocol

    def get(self, protocol_id: str) -> _ProtocolRecord:
        _same(protocol_id, self.protocol.protocol_id, "Unexpected sealed protocol reference")
        return _ProtocolRecord(protocol_id, self.protocol.canonical_bytes)


class _Plans:
    def __init__(self, plan: SearchPlan) -> None:
        self.plan = plan

    def get(self, plan_id: str) -> _PlanRecord:
        _same(plan_id, self.plan.plan_id, "Unexpected sealed plan reference")
        return _PlanRecord(plan_id, self.plan.canonical_bytes)


class _Findings:
    def __init__(self, authority: SearchFindingProtocol) -> None:
        self.authority = authority

    def get(self, protocol_id: str) -> SearchFindingProtocol:
        _same(protocol_id, self.authority.protocol_id, "Unexpected sealed finding authority")
        return self.authority


class _Budgets:
    def __init__(self, artifacts: dict[str, bytes], snapshot: Row) -> None:
        self.artifacts, self.snapshot = artifacts, snapshot

    def _plan(self, plan_id: str) -> None:
        _same(plan_id, self.snapshot["plan_id"], "Unexpected sealed budget plan")

    def get_budget(self, plan_id: str) -> bytes:
        self._plan(plan_id)
        return self.artifacts["budget"]

    def get_allocations(self, plan_id: str) -> tuple[bytes, ...]:
        self._plan(plan_id)
        return tuple(self.artifacts[f"allocation/{ordinal:04}"] for ordinal in cast("list[int]", self.snapshot["allocations"]))

    def get_stop(self, plan_id: str) -> bytes | None:
        self._plan(plan_id)
        return self.artifacts.get("outer_stop")

    def check_tree(self, plan_id: str) -> Row:
        self._plan(plan_id)
        return {"budget": True, "stop": self.snapshot["outer_stop"],
                "allocations": tuple(cast("list[int]", self.snapshot["allocations"])),
                "managed": self.snapshot["inner_campaign"]}

    def control_payload_bytes(self, plan_id: str) -> int:
        self._plan(plan_id)
        return sum(len(value) for role, value in self.artifacts.items() if role in ("budget", "outer_stop") or role.startswith("allocation/"))


class _Campaign:
    def __init__(self, artifacts: dict[str, bytes], snapshot: Row) -> None:
        self.artifacts, self.snapshot = artifacts, snapshot

    def _plan(self, plan_id: str) -> None:
        _same(plan_id, self.snapshot["plan_id"], "Unexpected sealed campaign plan")

    def get_campaign(self, plan_id: str) -> bytes | None:
        self._plan(plan_id)
        return self.artifacts.get("campaign")

    def get_dispatch(self, plan_id: str, ordinal: int) -> bytes | None:
        self._plan(plan_id)
        return self.artifacts.get(f"candidate/{ordinal:04}/dispatch")

    def get_link(self, plan_id: str, ordinal: int) -> bytes | None:
        self._plan(plan_id)
        return self.artifacts.get(f"candidate/{ordinal:04}/link")

    def get_result(self, plan_id: str, ordinal: int) -> bytes | None:
        self._plan(plan_id)
        return self.artifacts.get(f"candidate/{ordinal:04}/result")

    def get_stop(self, plan_id: str) -> bytes | None:
        self._plan(plan_id)
        return self.artifacts.get("inner_stop")

    def check_tree(self, plan_id: str) -> dict[str, tuple[int, ...]]:
        self._plan(plan_id)
        return {category: tuple(cast("int", row["ordinal"]) for row in cast("list[Row]", self.snapshot["candidates"]) if row[flag])
                for flag, category in (("dispatch", "dispatches"), ("link", "links"), ("result", "results"))}


class _Ledger:
    def __init__(self, artifacts: dict[str, bytes], snapshot: Row, protocol: ExecutableProtocol) -> None:
        self.artifacts, self.snapshot, self.protocol = artifacts, snapshot, protocol
        self.reservations = tuple(AttemptReservation(cast("str", row["attempt_id"]), artifacts[f"reservation/{row['index']:04}"])
                                  for row in cast("list[Row]", snapshot["reservations"]))
        self.selected = {cast("str", row["attempt_id"]): row for row in cast("list[Row]", snapshot["attempts"])}

    reserve = staticmethod(_deny)
    reserve_with_nonce = staticmethod(_deny)
    bind_intent = staticmethod(_deny)
    publish = staticmethod(_deny)

    def list_reservations(self, owner: ExecutableProtocol) -> tuple[AttemptReservation, ...]:
        _same(owner.canonical_bytes, self.protocol.canonical_bytes, "Original reservation owner differs")
        return self.reservations

    def get_reservation(self, attempt_id: str) -> AttemptReservation:
        result = next((item for item in self.reservations if item.attempt_id == attempt_id), None)
        if result is None:
            raise SearchEvidenceValidationError("Sealed reservation is absent: " + attempt_id)
        return result

    def get_intent(self, attempt_id: str) -> bytes | None:
        self.get_reservation(attempt_id)
        _require(attempt_id in self.selected, "Unselected attempt intent was not sealed")
        return self.artifacts.get("attempt/" + attempt_id + "/intent")

    def get_outcome(self, attempt_id: str) -> bytes | None:
        self.get_reservation(attempt_id)
        _require(attempt_id in self.selected, "Unselected attempt outcome was not sealed")
        return self.artifacts.get("attempt/" + attempt_id + "/outcome")

    def read_artifact(self, content_hash: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes:
        role = "cas/" + content_hash
        if role not in self.artifacts:
            raise SearchEvidenceValidationError("Missing sealed ledger role: " + role)
        raw = self.artifacts[role]
        _require(type(max_bytes) is int and 1 <= max_bytes <= 16 * 1024 * 1024 and len(raw) <= max_bytes, "Sealed CAS object exceeds requested bound: " + content_hash)
        _same(digest(raw), content_hash, "Sealed CAS address differs")
        return raw


def _intent_closures(artifacts: dict[str, bytes], snapshot: Row, protocol: ExecutableProtocol, datasets: _Datasets) -> None:
    spec = build_replay_spec(canonical(cast("Row", protocol.document["replay_spec"])))
    replay_input = ReplayInput(datasets.record.dataset_id, datasets.normalized, spec)
    for row in cast("list[Row]", snapshot["attempts"]):
        if not row["intent"]:
            continue
        intent_raw = artifacts["attempt/" + cast("str", row["attempt_id"]) + "/intent"]
        intent = load_scenario_intent(intent_raw)
        bindings = cast("Row", intent.document["bindings"])
        assumptions = load_assumption_spec(artifacts["cas/" + cast("str", bindings["assumption_id"])])
        scenario = load_scenario_spec(artifacts["cas/" + cast("str", bindings["scenario_id"])])
        view = derive_replay_view(validate_scenario_spec(scenario, assumptions, protocol=protocol, replay_input=replay_input))
        _same(build_scenario_intent(view).canonical_bytes, intent_raw, "Committed intent differs from independent source derivation")
        _same(artifacts["cas/" + cast("str", bindings["derived_view_id"])], view.canonical_bytes, "Committed derived-view descriptor differs")
        _same(artifacts["cas/" + cast("str", bindings["derived_normalized_sha256"])], view.replay_input.normalized_bytes, "Committed derived tape differs from independent source")


def _diagnostics(bounded: Row, artifacts: dict[str, bytes]) -> Row:
    execution = bounded["execution"]
    completed = [] if execution is None else [row for row in cast("list[Row]", cast("Row", execution)["candidates"])
                                             if row["status"] == "COMPLETED" and row["raw_result_audited"] is True]
    pairs: list[Row] = []
    for left, right in zip(completed, completed[1:], strict=False):
        left_ordinal, right_ordinal = cast("int", left["ordinal"]), cast("int", right["ordinal"])
        comparison = compare_replay_results(load_replay_result(artifacts[f"candidate/{left_ordinal:04}/result"]),
                                            load_replay_result(artifacts[f"candidate/{right_ordinal:04}/result"]))
        pairs.append({"left_ordinal": left_ordinal, "right_ordinal": right_ordinal,
                      "left_run_id": left["run_id"], "right_run_id": right["run_id"],
                      "comparison": comparison.document})
    _require(len(pairs) <= 99, "Too many adjacent completed-candidate comparisons")
    return {"kind": "search_evidence_diagnostics_v1", "schema_version": 1,
            "comparison_policy": "adjacent_completed_candidate_traces_v1",
            "baseline_comparison_performed": False, "causal_attribution_issued": False,
            "native_replayed": False, "pairs": pairs}


def _inspect(artifacts: dict[str, bytes], snapshot: Row) -> tuple[Row, Row, Row]:
    authority = load_search_finding_protocol(artifacts["finding_protocol"])
    protocol = load_executable_protocol(canonical(cast("Row", authority.plan.document["protocol"])))
    datasets = _Datasets(cast("str", snapshot["dataset_id"]), artifacts)
    registry, plans = _Registry(protocol), _Plans(authority.plan)
    budgets, campaign = _Budgets(artifacts, snapshot), _Campaign(artifacts, snapshot)
    ledger = _Ledger(artifacts, snapshot, protocol)
    _intent_closures(artifacts, snapshot, protocol, datasets)

    def inner() -> Row | None:
        if not snapshot["inner_campaign"]:
            return None
        return inspect_search_campaign(authority.plan.plan_id, split="development",
            plans_factory=lambda: plans, registry_factory=lambda: registry,
            datasets_factory=lambda: datasets, ledger_factory=lambda: ledger,
            campaigns_factory=lambda: campaign)

    bounded = inspect_bounded_search_campaign(authority.plan.plan_id, split="development",
        plans_factory=lambda: plans, registry_factory=lambda: registry,
        datasets_factory=lambda: datasets, budgets_factory=lambda: budgets,
        execution_inspector=inner)
    finding = evaluate_search_findings(authority.protocol_id, split="development",
        findings_factory=lambda: _Findings(authority), campaign_inspector=lambda _plan_id: bounded)
    return bounded, finding, _diagnostics(bounded, artifacts)


def inspect_search_artifacts(artifacts: Mapping[str, bytes]) -> tuple[Row, Row, Row]:
    """Rebuild proof before collector adds derived report/diagnostic roles."""
    try:
        snapshot = validate_snapshot(artifacts, require_derived=False)
        return _inspect(dict(artifacts), snapshot)
    except SearchEvidenceValidationError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise SearchEvidenceValidationError("Cannot reconstruct sealed search evidence: " + str(error)) from error


def verify_search_artifacts(artifacts: Mapping[str, bytes]) -> Row:
    """Verify closed bytes by reconstructing the real readonly audit pipeline."""
    try:
        snapshot = validate_snapshot(artifacts)
        contents = dict(artifacts)
        bounded, finding, diagnostics = _inspect(contents, snapshot)
        _same(canonical(cast("Row", finding["report"])), contents["finding_report"], "Sealed finding report does not reproduce from source and ledger closure")
        _same(canonical(diagnostics), contents["diagnostics"], "Sealed trace diagnostics do not reproduce")
        return {"kind": "search_evidence_verification_receipt_v1", "schema_version": 1,
            "report_id": finding["report_id"], "report": finding["report"],
            "diagnostics": diagnostics, "diagnostics_sha256": digest(contents["diagnostics"]),
            "snapshot": snapshot, "snapshot_id": digest(contents["snapshot"]),
            "budget_id": bounded["budget_id"], "finalization_status": "FINAL",
            "verification": {"integrity_verified": True, "bindings_verified": True,
                "source_revalidated": True, "plan_recomputed": True,
                "ledger_content_reconstructed": snapshot["ledger_prefix_observed"], "findings_recomputed": True,
                "diagnostics_recomputed": True, "portable_evidence_verified": True,
                "reservation_prefix_reconstructed": snapshot["ledger_prefix_observed"],
                "native_replayed": False, "attempt_reserved": False,
                "author_signature_verified": False, "human_domain_approval_verified": False,
                "original_publication_verified": False, "producer_version_authenticated": False,
                "full_attempt_history_verified": False, "confirmation_reference_checked": False,
                "runtime_limits_reenforced": False, "physical_storage_usage_verified": False}}
    except SearchEvidenceValidationError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise SearchEvidenceValidationError("Invalid sealed search evidence: " + str(error)) from error
