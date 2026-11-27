"""Real durable fourth-invocation decisions with synthetic trusted host observations."""

from __future__ import annotations

import copy
import dataclasses
import fcntl
import json
import os
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_restricted_reference_ec2 as host_records
import test_restricted_reference_ec2_recovery as first_recovery
from test_restricted_reference_ec2_recovery_v2 import CURRENT as PREVIOUS
from test_restricted_reference_ec2_recovery_v2 import manifest_for, publish, record
from test_restricted_reference_ec2_recovery_v2 import recovery as recovery
from test_restricted_reference_ec2_recovery_v2 import v2 as v2
from test_restricted_reference_ec2_recovery_v2 import v2_history as v2_history

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

CURRENT = "f" * 40
BOOT = "44444444-4444-4444-4444-444444444444"
RETRIEVAL_BOOT = "5e83ad22-d623-4ddd-87f8-41a27a599f2d"
base_host = host_records.host


@pytest.fixture
def host(base_host, monkeypatch):
    # The driver correctly accepts only the three literal historical run IDs.
    # Configure the original fixture before its genuine first factory call.
    original_run = "ec201aab11254e8bb7cd1573a96a0001"
    monkeypatch.setattr(host_records, "RUN_ID", original_run)
    monkeypatch.setattr(first_recovery, "RUN_ID", original_run)
    return base_host


def prepare_policy(run):
    run.prepare_host()
    run.policy_evidence_dir.mkdir()
    preload = run.policy_evidence_dir / "preload-manifest.json"
    preload.write_bytes(ec2.canonical({"provider_context": run.provider_record})[:-1])
    setup = run.policy_evidence_dir / "policy-setup.json"
    setup.write_bytes(
        ec2.canonical(
            {
                "provider_context": run.provider_record,
                "preload_manifest_sha256": record(preload)["sha256"],
            }
        )
    )
    run.policy_ready(
        preload_sha256=record(preload)["sha256"], report_sha256=record(setup)["sha256"]
    )


def ready(case):
    run = case.claim()
    prepare_policy(run)
    run.acquire_runner()
    return run


def raw_result(run, ticket, manifest_sha256, *, failure=None):
    return {
        "name": ticket.name,
        "nonce": ticket.nonce,
        "payload_started": True,
        "failure": failure,
        "stop_confirmed": True,
        "cleanup_confirmed": True,
        "host_facts": {
            "manifest_sha256": manifest_sha256,
            "admission_number": ticket.admission_number,
            "original_admission_ns": ticket.admitted_ns,
            "original_deadline_ns": ticket.deadline_ns,
        },
    }


def catalog(case, *, count=24):
    """Use real admissions/outcomes; these metadata fixtures are never isolation evidence."""
    run = ready(case)
    run.artifact_dir.mkdir()
    manifest_path = run.artifact_dir / "manifest.json"
    manifest_path.write_bytes(ec2.canonical(manifest_for(run)))
    manifest_sha = record(manifest_path)["sha256"]
    cases = []
    for index, name in enumerate(ec2.FIXED_PROBES):
        if index >= count:
            cases.append(
                {
                    "name": name,
                    "admission_submitted": False,
                    "status": "UNKNOWN",
                    "reason": "not_admitted_after_original_window_or_uncertainty",
                }
            )
            continue
        case.host.clock[0] += 1000
        ticket = run.reserve_probe(name=name, nonce=f"{index + 1:032x}")
        run.admit_probe(ticket)
        expected_failures = {
            "cpu": "deadline_exceeded",
            "detached": "deadline_exceeded",
            "output_flood": "stdout_limit",
        }
        failure = expected_failures.get(name) if count == 19 else None
        result = raw_result(run, ticket, manifest_sha, failure=failure)
        path = run.run_dir / f"case-{index + 1:02d}.json"
        path.write_bytes(ec2.canonical(result))
        run.finish_probe(
            ticket,
            result_sha256=record(path)["sha256"],
            stop_confirmed=True,
            cleanup_confirmed=True,
            failure=failure,
        )
        unknown = count == 19 and index == 18
        cases.append(
            {
                "name": name,
                "nonce": ticket.nonce,
                "admission_submitted": True,
                "admission": dataclasses.asdict(ticket),
                "status": "UNKNOWN" if unknown else "PASS",
                "reason": (
                    "Missing separate host and guest namespace IDs"
                    if unknown
                    else "actual_scoped_control_evidence"
                ),
                "payload_started": True,
                "execution_evidence": record(path),
            }
        )
    snapshot = run.snapshot()
    report = {
        "kind": f"restricted_reference_ec2_recovery_qualification_v{run.recovery_schema_version}",
        "schema_version": run.recovery_schema_version,
        "controls_status": "QUALIFIED_REFERENCE_ONLY" if count == 24 else "NOT_QUALIFIED",
        "production_m1": "DISABLED",
        "independent_human_security_review": "NOT_PERFORMED",
        "external_human_reproduction": "0/0/PENDING",
        "research_reservations": 0,
        "replay_engine_invocations": 0,
        "source_revision": run.source_revision,
        "run_id": run.run_id,
        "boot_id": run.boot_id,
        "acceptance_gate": "matching_durable_terminal_and_final_report_sha256",
        "original_qualification_budget": {"max_admissions": 24, "window_ns": ec2.WINDOW_NS},
        "cases": cases,
        "scope": "Synthetic durable decisions; no actual host qualification",
        "stop_scope": "Independent AWS state readback required",
        "recovery_context": run.recovery_context,
        "durable_budget_status": "CONFIRMED",
        "durable_budget": dataclasses.asdict(snapshot),
        "admissions_charged": count,
        "confirmed_backend_admissions": count,
        "backend_unconfirmed_admissions": 0,
        "pending_probe_outcomes": 0,
        "recovery_accounting": run.recovery_accounting(snapshot),
        "admission_accounting_scope": "Synthetic fixture; original submitted slots stay charged",
        "provider_context": run.provider_record,
        "manifest_sha256": manifest_sha,
        "completed_at_monotonic_ns": case.host.clock[0],
        "observed_payload_starts": count,
    }
    return run, report


@pytest.fixture
def v3_history(v2, monkeypatch):
    old, report = catalog(v2, count=19)
    old.finish(outcome="NOT_QUALIFIED", reason="fixed_catalog_incomplete")
    publish(old, report)
    paths = {
        "claim_sha256": old.run_dir / "claim.json",
        "state_sha256": old.run_dir / "state.json",
        "report_sha256": old.run_dir / "qualification-report.json",
        "source_lock_sha256": v2.source_lock,
        "manifest_sha256": old.artifact_dir / "manifest.json",
        "plan_sha256": v2.plan_path,
        "consumption_sha256": v2.consumption,
        "policy_setup_sha256": old.policy_evidence_dir / "policy-setup.json",
        "policy_preload_sha256": old.policy_evidence_dir / "preload-manifest.json",
        "identity_document_sha256": old.run_dir / "instance-identity-document.json",
    }
    case_paths = {f"case-{i:02d}.json": old.run_dir / f"case-{i:02d}.json" for i in range(1, 20)}
    history = {
        "original": copy.deepcopy(ec2.RECOVERY_V2_HISTORY["original"]),
        "recovery": copy.deepcopy(ec2.RECOVERY_V2_HISTORY["recovery"]),
        "recovery_v2": {
            **ec2.RECOVERY_V3_HISTORY["recovery_v2"],
            "source_revision": PREVIOUS,
            "run_id": old.run_id,
            "boot_id": old.boot_id,
            "charged": 19,
            "backend_confirmed": 19,
            **{key: record(path)["sha256"] for key, path in paths.items()},
            "case_sha256": {key: record(path)["sha256"] for key, path in case_paths.items()},
        },
    }
    monkeypatch.setattr(ec2, "RECOVERY_V3_HISTORY", history)
    os.close(old._lock_fd)
    old._lock_fd = -1
    v2.host.boot[0], v2.host.clock[0] = BOOT, 4000
    directory = v2.host.root / "recovery-v3"
    directory.mkdir()
    stop = directory / "operator-stop.md"
    stop.write_bytes(b"Synthetic stopped retrieval boot; not an admission or attestation.\n")
    monkeypatch.setattr(ec2, "RECOVERY_V3_STOP_SHA256", record(stop)["sha256"])
    helper = v2.host.source / ec2.RECOVERY_V3_SOURCE_FILES[-1]
    helper.write_bytes(b"synthetic v3 preparation source\n")
    source_lock = v2.host.root / "sources" / CURRENT / "source-lock.json"
    source_lock.parent.mkdir()
    source_lock.write_bytes(
        ec2.canonical(
            {
                "kind": "restricted_reference_ec2_recovery_source_lock_v3",
                "schema_version": 3,
                "source_revision": CURRENT,
                "source_root": str(v2.host.source),
                "files": {
                    relative: {
                        key: record(v2.host.source / relative)[key] for key in ("sha256", "bytes")
                    }
                    for relative in ec2.RECOVERY_V3_SOURCE_FILES
                },
            }
        )
    )
    preserved = {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in v2.host.root.rglob("*")
        if path.is_file()
    }
    case = SimpleNamespace(
        host=v2.host,
        previous=v2,
        old=old,
        paths=paths,
        case_paths=case_paths,
        history=history,
        stop=stop,
        helper=helper,
        source_lock=source_lock,
        preserved=preserved,
        plan_path=directory / "plan.json",
        consumption=directory / "consumption.json",
        new_dir=v2.host.root / "runs" / ec2.RECOVERY_V3_RUN_ID,
        runs=[],
    )
    yield case
    for run in case.runs:
        with suppress(OSError):
            os.close(run._lock_fd)


@pytest.fixture
def v3(v3_history):
    case = v3_history
    case.plan = ec2.recovery_v3_plan_document(
        source_revision=CURRENT, run_id=ec2.RECOVERY_V3_RUN_ID, plan_id=ec2.RECOVERY_V3_PLAN_ID
    )
    case.plan_path.write_bytes(ec2.canonical(case.plan))

    def claim():
        run = ec2.Ec2Run.claim_recovery_v3(
            source_revision=CURRENT, run_id=ec2.RECOVERY_V3_RUN_ID, plan_id=ec2.RECOVERY_V3_PLAN_ID
        )
        case.runs.append(run)
        return run

    case.claim = claim
    return case


def assert_preserved(case):
    for path, (raw, inode) in case.preserved.items():
        assert path.read_bytes() == raw and path.stat().st_ino == inode


def rebind_history(case, monkeypatch, pins):
    monkeypatch.setattr(ec2, "RECOVERY_V3_HISTORY", pins)
    case.plan["history"] = copy.deepcopy(pins)
    case.plan_path.write_bytes(ec2.canonical(case.plan))


def test_exact_v3_selection_keeps_schema_and_historical_charge_independent():
    assert ec2.RECOVERY_V3_FREEZE_REVISION == "72c83a02d47a403d5f9d33aad2f84ccaba7ec6a4"
    assert ec2.RECOVERY_V3_PLAN_ID == "ec2-recovery-20261127-v3"
    assert ec2.RECOVERY_V3_RUN_ID == "ec201aab11254e8bb7cd1573a96a0004"
    assert ec2.RECOVERY_V3_PRIOR_CHARGED == 21
    assert len(ec2.RECOVERY_V3_SOURCE_FILES) == 10
    assert ec2.RECOVERY_V3_SOURCE_FILES[-1] == "scripts/prepare_ec2_reference_recovery_v3.py"
    assert ec2.RECOVERY_V2_ALLOWANCE["max_cumulative_admissions"] == 26
    assert ec2.RECOVERY_V3_ALLOWANCE["max_cumulative_admissions"] == 45


def test_nineteen_durable_old_cases_remain_unknown_then_new_budget_starts_at_twenty_one(v3):
    old_state = json.loads(v3.paths["state_sha256"].read_bytes())
    old_report = json.loads(v3.paths["report_sha256"].read_bytes())
    assert old_state["poisoned"] is False and old_state["charged"] == 19
    assert [case["status"] for case in old_report["cases"]] == ["PASS"] * 18 + ["UNKNOWN"] * 6
    assert old_report["cases"][18]["admission_submitted"] is True
    assert all(case["admission_submitted"] is False for case in old_report["cases"][19:])
    run = v3.claim()
    assert run.recovery_schema_version == 3
    budget = run.recovery_accounting(run.snapshot())
    assert len(budget) == 14 and budget["prior_charged"] == budget["prior_backend_confirmed"] == 21
    assert budget["current_charged"] == budget["current_backend_confirmed"] == 0
    assert budget["cumulative_charged"] == budget["cumulative_backend_confirmed"] == 21
    assert budget["historical_run_ids"] == [item["run_id"] for item in v3.history.values()]
    consumption = json.loads(v3.consumption.read_bytes())
    assert len(consumption) == 16 and consumption["schema_version"] == 3
    assert consumption["prior_charged"] == 21 and consumption["max_cumulative_admissions"] == 45
    assert consumption["history_state_sha256"] == {
        key: value["state_sha256"] for key, value in v3.history.items()
    }
    assert run.started_ns == 4000 and run.setup_deadline_ns == 4000 + ec2.SETUP_NS
    assert len(v3.host.requests) == 3
    assert_preserved(v3)


def test_one_original_readonly_cloexec_mutex_and_v3_used_fence_never_reopen_v2(v3):
    run = v3.claim()
    assert fcntl.fcntl(run._lock_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert fcntl.fcntl(run._lock_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    assert os.fstat(run._lock_fd).st_ino == (v3.host.root / "host-admission.json").stat().st_ino
    with pytest.raises(BlockingIOError):
        v3.claim()
    run.finish(outcome="NOT_QUALIFIED", reason="synthetic ended")
    os.close(run._lock_fd)
    run._lock_fd = -1
    with pytest.raises(FileExistsError):
        v3.claim()
    with pytest.raises(FileExistsError):
        v3.previous.claim()
    assert_preserved(v3)


@pytest.mark.parametrize("slot", ["original", "recovery", "recovery_v2", "retrieval"])
def test_all_three_old_qualification_boots_and_the_uncharged_retrieval_boot_refuse(v3, slot):
    v3.host.boot[0] = RETRIEVAL_BOOT if slot == "retrieval" else v3.history[slot]["boot_id"]
    with pytest.raises(ValueError):
        v3.claim()
    assert not v3.consumption.exists() and not v3.new_dir.exists()


def test_history_validation_consumes_the_original_entry_setup_clock(v3, monkeypatch):
    original = ec2._recovery_v3_history

    def delayed(seals):
        observed = original(seals)
        v3.host.clock[0] += ec2.SETUP_NS
        return observed

    monkeypatch.setattr(ec2, "_recovery_v3_history", delayed)
    with pytest.raises(TimeoutError):
        v3.claim()
    assert not v3.consumption.exists() and not v3.new_dir.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown", True),
        ("schema_version", True),
        ("schema_version", 3.0),
        ("plan_id", ec2.RECOVERY_V2_PLAN_ID),
        ("run_id", ec2.RECOVERY_V2_RUN_ID),
        ("freeze_revision", "0" * 40),
    ],
)
def test_plan_unknown_fields_old_lineage_and_numeric_lookalikes_refuse(v3, field, value):
    v3.plan_path.write_bytes(ec2.canonical(v3.plan | {field: value}))
    with pytest.raises(ValueError):
        v3.claim()
    assert not v3.consumption.exists() and not v3.new_dir.exists()


def test_duplicate_plan_key_is_not_a_new_authority(v3):
    v3.plan_path.write_bytes(
        v3.plan_path.read_bytes().replace(
            b'"schema_version":3', b'"schema_version":3,"schema_version":3', 1
        )
    )
    with pytest.raises(ValueError, match="Duplicate"):
        v3.claim()
    assert not v3.consumption.exists()


@pytest.mark.parametrize("change", ["old_source", "old_plan", "fifth_run"])
def test_v3_factory_cannot_dispatch_another_plan_run_or_historical_source(v3, change):
    arguments = {
        "source_revision": CURRENT,
        "run_id": ec2.RECOVERY_V3_RUN_ID,
        "plan_id": ec2.RECOVERY_V3_PLAN_ID,
    }
    if change == "old_source":
        arguments["source_revision"] = PREVIOUS
    elif change == "old_plan":
        arguments["plan_id"] = ec2.RECOVERY_V2_PLAN_ID
    else:
        arguments["run_id"] = "ec201aab11254e8bb7cd1573a96a0005"
    with pytest.raises(ValueError):
        ec2.Ec2Run.claim_recovery_v3(**arguments)
    assert not v3.consumption.exists()


@pytest.mark.parametrize(
    "target",
    [
        "claim_sha256",
        "state_sha256",
        "report_sha256",
        "manifest_sha256",
        "consumption_sha256",
        "source_lock_sha256",
        "policy_preload_sha256",
        "identity_document_sha256",
        "stop",
        "helper",
        "source_lock",
        "case-19.json",
    ],
)
def test_changed_old_raw_records_or_current_closure_refuse_before_new_consumption(v3, target):
    path = v3.paths.get(target) or v3.case_paths.get(target) or getattr(v3, target)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        v3.claim()
    assert not v3.consumption.exists() and not v3.new_dir.exists()


@pytest.mark.parametrize(
    "change", ["charged_bool", "poisoned", "pending", "unconfirmed", "owner", "clock"]
)
def test_third_history_semantics_refuse_even_when_state_and_plan_hashes_are_rebound(
    v3, monkeypatch, change
):
    path = v3.paths["state_sha256"]
    state = json.loads(path.read_bytes())
    if change == "charged_bool":
        state["charged"] = True
    elif change == "poisoned":
        state["poisoned"] = True
    elif change == "pending":
        state["admissions"][18]["outcome"] = None
    elif change == "unconfirmed":
        state["backend_confirmed"] = 18
    elif change == "owner":
        state["owner"]["pid"] += 1
    else:
        state["deadline_ns"] += 1
    path.write_bytes(ec2.canonical(state))
    pins = copy.deepcopy(v3.history)
    pins["recovery_v2"]["state_sha256"] = record(path)["sha256"]
    rebind_history(v3, monkeypatch, pins)
    with pytest.raises(ValueError):
        v3.claim()
    assert not v3.consumption.exists()


@pytest.mark.parametrize("fault", ["manifest_prior", "mixed_nonce", "retroactive_pass"])
def test_old_accounting_and_unknown_verdict_cannot_be_changed_with_all_hashes_rebound(
    v3, monkeypatch, fault
):
    manifest_path = v3.paths["manifest_sha256"]
    manifest = json.loads(manifest_path.read_bytes())
    if fault == "manifest_prior":
        manifest["recovery_accounting"]["cumulative_charged"] = 21
        manifest["recovery_accounting"]["cumulative_backend_confirmed"] = 21
        manifest_path.write_bytes(ec2.canonical(manifest))
    manifest_sha = record(manifest_path)["sha256"]
    state_path, report_path = v3.paths["state_sha256"], v3.paths["report_sha256"]
    old_state = json.loads(state_path.read_bytes())
    old_report = json.loads(report_path.read_bytes())
    old_report["manifest_sha256"] = manifest_sha
    for index, path in enumerate(v3.case_paths.values()):
        result = json.loads(path.read_bytes())
        result["host_facts"]["manifest_sha256"] = manifest_sha
        if fault == "mixed_nonce" and index == 18:
            result["nonce"] = "f" * 32
        path.write_bytes(ec2.canonical(result))
        old_state["admissions"][index]["outcome"]["result_sha256"] = record(path)["sha256"]
        old_report["cases"][index]["execution_evidence"] = record(path)
    if fault == "retroactive_pass":
        old_report["cases"][18]["status"] = "PASS"
    state_path.write_bytes(ec2.canonical(old_state))
    report_path.write_bytes(ec2.canonical(old_report))
    pins = copy.deepcopy(v3.history)
    for key in ("state_sha256", "report_sha256", "manifest_sha256"):
        pins["recovery_v2"][key] = record(v3.paths[key])["sha256"]
    pins["recovery_v2"]["case_sha256"] = {
        key: record(path)["sha256"] for key, path in v3.case_paths.items()
    }
    rebind_history(v3, monkeypatch, pins)
    with pytest.raises(ValueError):
        v3.claim()
    assert not v3.consumption.exists()


def test_current_source_lock_requires_exact_producer_canonical_bytes(v3):
    value = json.loads(v3.source_lock.read_bytes())
    v3.source_lock.write_bytes(json.dumps(value, indent=2).encode() + b"\n")
    v3.plan["source_lock"] = record(v3.source_lock)
    v3.plan_path.write_bytes(ec2.canonical(v3.plan))
    with pytest.raises(ValueError):
        v3.claim()
    assert not v3.consumption.exists()


@pytest.mark.parametrize("fault", ["partial", "silent_partial", "fsync", "mkdir"])
def test_uncertain_consumption_is_permanently_used_before_metadata_or_run(v3, monkeypatch, fault):
    write, sync, mkdir = ec2.write_exclusive, ec2._fsync_dir, Path.mkdir

    def failed_write(path, raw):
        if path == v3.consumption and fault in {"partial", "silent_partial"}:
            with path.open("xb") as stream:
                stream.write(raw[:9])
                stream.flush()
                os.fsync(stream.fileno())
            if fault == "partial":
                raise OSError("partial v3 consumption")
            return
        write(path, raw)

    def failed_sync(path):
        if fault == "fsync" and path == v3.consumption.parent and v3.consumption.exists():
            raise OSError("uncertain v3 parent fsync")
        sync(path)

    def failed_mkdir(path, *args, **kwargs):
        if fault == "mkdir" and path == v3.new_dir:
            raise OSError("new run creation failed")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(ec2, "write_exclusive", failed_write)
    monkeypatch.setattr(ec2, "_fsync_dir", failed_sync)
    monkeypatch.setattr(Path, "mkdir", failed_mkdir)
    with pytest.raises((OSError, ValueError)):
        v3.claim()
    retained = v3.consumption.read_bytes()
    assert retained and not v3.new_dir.exists() and len(v3.host.requests) == 3
    monkeypatch.setattr(ec2, "write_exclusive", write)
    monkeypatch.setattr(ec2, "_fsync_dir", sync)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(FileExistsError):
        v3.claim()
    assert v3.consumption.read_bytes() == retained
    assert_preserved(v3)


@pytest.mark.parametrize("field,value", [("prior_charged", 3), ("max_cumulative_admissions", 27)])
def test_consumption_cannot_turn_schema_three_into_three_historical_charges(v3, field, value):
    run = v3.claim()
    data = json.loads(v3.consumption.read_bytes())
    data[field] = value
    v3.consumption.write_bytes(ec2.canonical(data))
    with pytest.raises(ValueError):
        run.snapshot()
    assert run._state["charged"] == 0


def test_mutable_state_cannot_redefine_the_independently_retained_context(v3):
    run = v3.claim()
    observed = run.recovery_context
    observed["history"]["recovery_v2"]["charged"] = 0
    assert run.recovery_context["history"]["recovery_v2"]["charged"] == 19
    run._state["recovery_context"]["schema_version"] = 2
    run._persist()
    with pytest.raises(ValueError):
        _ = run.recovery_schema_version


def test_semantically_equal_noncanonical_live_state_still_fences(v3):
    run = v3.claim()
    path = run.run_dir / "state.json"
    path.write_bytes(json.dumps(json.loads(path.read_bytes()), indent=2).encode() + b"\n")
    with pytest.raises(ValueError):
        run.snapshot()
    assert v3.consumption.exists() and run._state["charged"] == 0


def test_pending_submission_is_twenty_two_charged_but_only_twenty_one_confirmed(v3):
    run = ready(v3)
    run.reserve_probe(name="positive", nonce="c" * 32)
    snapshot = run.snapshot()
    assert snapshot.charged == snapshot.unconfirmed == snapshot.pending_outcomes == 1
    budget = run.recovery_accounting(snapshot)
    assert budget["cumulative_charged"] == 22
    assert budget["cumulative_backend_confirmed"] == 21
    with pytest.raises(ValueError):
        run.reserve_probe(name="filesystem", nonce="d" * 32)
    assert run._state["charged"] == 1 and v3.consumption.exists()


@pytest.mark.parametrize("value", [False, 0.0])
def test_numeric_snapshot_lookalikes_cannot_authenticate_the_new_accounting(v3, value):
    run = v3.claim()
    with pytest.raises(ValueError):
        run.recovery_accounting(dataclasses.replace(run.snapshot(), charged=value))


def test_complete_new_catalog_preserves_preprobe_twenty_one_then_binds_final_forty_five(v3):
    run, report = catalog(v3)
    initial = json.loads((run.artifact_dir / "manifest.json").read_bytes())
    assert initial["recovery_accounting"]["current_charged"] == 0
    assert initial["recovery_accounting"]["cumulative_charged"] == 21
    digest = publish(run, report)
    run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    receipt = run.qualification_receipt()
    assert len(receipt) == 10 and receipt["schema_version"] == 3
    assert receipt["kind"] == "restricted_reference_ec2_recovery_terminal_receipt_v3"
    assert receipt["final_report_sha256"] == digest
    assert receipt["recovery_accounting"] == report["recovery_accounting"]
    assert receipt["recovery_accounting"]["current_charged"] == 24
    assert receipt["recovery_accounting"]["cumulative_charged"] == 45
    assert receipt["production_m1"] == "DISABLED"
    assert_preserved(v3)
    with pytest.raises(ValueError):
        run.reserve_probe(name="positive", nonce="f" * 32)


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_report",
        "old_version",
        "prior_three",
        "missing_history",
        "old_ticket",
        "old_case",
        "boolean_count",
        "missing_case",
        "raw_case_changed",
        "noncanonical",
    ],
)
def test_final_report_rejects_mixed_or_ambiguous_authority_without_refunding_twenty_four(v3, fault):
    run, report = catalog(v3)
    if fault == "unknown_report":
        report["unknown"] = True
    elif fault == "old_version":
        report["schema_version"] = 2
    elif fault == "prior_three":
        report["recovery_accounting"]["prior_charged"] = 3
    elif fault == "missing_history":
        del report["recovery_context"]["history"]["recovery_v2"]
    elif fault == "old_ticket":
        report["cases"][0]["admission"]["run_id"] = v3.old.run_id
    elif fault == "old_case":
        report["cases"][0]["execution_evidence"] = record(v3.case_paths["case-01.json"])
    elif fault == "boolean_count":
        report["recovery_accounting"]["current_unconfirmed"] = False
    elif fault == "missing_case":
        report["cases"].pop()
    elif fault == "raw_case_changed":
        (run.run_dir / "case-01.json").write_bytes(b"mixed old raw data\n")
    if fault == "noncanonical":
        path = run.run_dir / "qualification-report.json"
        path.write_bytes(json.dumps(report, indent=2).encode() + b"\n")
        digest = record(path)["sha256"]
    else:
        digest = publish(run, report)
    with pytest.raises(ValueError):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    assert run._state["charged"] == 24 and run._state["final_report_sha256"] is None
    assert v3.consumption.exists()
    with pytest.raises(ValueError):
        run.reserve_probe(name="positive", nonce="f" * 32)


@pytest.mark.parametrize("fault", ["unknown", "missing", "noncanonical"])
def test_final_manifest_shape_remains_strict_after_all_raw_hashes_are_rebound(v3, fault):
    run, report = catalog(v3)
    path = run.artifact_dir / "manifest.json"
    manifest = json.loads(path.read_bytes())
    if fault == "unknown":
        manifest["unknown_observation"] = "not a permitted top-level key"
    elif fault == "missing":
        del manifest["os_release"]
    path.write_bytes(
        json.dumps(manifest, indent=2).encode() + b"\n"
        if fault == "noncanonical"
        else ec2.canonical(manifest)
    )
    digest = record(path)["sha256"]
    report["manifest_sha256"] = digest
    for index, case in enumerate(report["cases"]):
        case_path = run.run_dir / f"case-{index + 1:02d}.json"
        raw = json.loads(case_path.read_bytes())
        raw["host_facts"]["manifest_sha256"] = digest
        case_path.write_bytes(ec2.canonical(raw))
        case["execution_evidence"] = record(case_path)
        run._state["admissions"][index]["outcome"]["result_sha256"] = record(case_path)["sha256"]
    run._persist()
    report_hash = publish(run, report)
    with pytest.raises(ValueError, match="manifest"):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=report_hash)
    assert run._state["charged"] == 24 and v3.consumption.exists()
