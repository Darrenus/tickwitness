"""Fixed third-invocation filesystem decisions; synthetic records are not a host pass."""

from __future__ import annotations

import dataclasses
import fcntl
import json
import os
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_restricted_reference_ec2 import host as host
from test_restricted_reference_ec2_recovery import CURRENT as PREVIOUS
from test_restricted_reference_ec2_recovery import recovery as recovery

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

CURRENT = "e" * 40
BOOT = "33333333-3333-3333-3333-333333333333"


def record(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": ec2._sha(raw), "bytes": len(raw)}


def manifest_for(run):
    result = dict.fromkeys(ec2.RECOVERY_MANIFEST_KEYS)
    version = run.recovery_schema_version
    result.update(
        kind=f"restricted_reference_ec2_recovery_manifest_v{version}",
        schema_version=version,
        source_revision=run.source_revision,
        provider_context=run.provider_record,
        recovery_context=run.recovery_context,
        production_m1_enabled=False,
        available_for_probe=True,
        unavailable_reasons=[],
        fixed_cases=list(ec2.FIXED_PROBES),
        qualification_started_ns=run.started_ns,
        qualification_deadline_ns=run.deadline_ns,
        recovery_accounting_phase="pre_probe_manifest",
        recovery_accounting=run.recovery_accounting(run.snapshot()),
        runtime_closure_scope="Synthetic publication decisions, not isolation evidence",
    )
    return result


@pytest.fixture
def v2_history(recovery, monkeypatch):
    """Construct two real durable failures; only observations and frozen pins are synthetic."""
    original_metadata = ec2._metadata

    def raw_metadata(*, deadline_ns):
        # AWS returns raw pretty JSON, not our authority-record canonical encoding.
        value = json.loads(original_metadata(deadline_ns=deadline_ns))
        return json.dumps(value, indent=2).encode()

    monkeypatch.setattr(ec2, "_metadata", raw_metadata)
    old = recovery.claim()
    old.prepare_host()
    old.policy_evidence_dir.mkdir()
    preload = {"provider_context": old.provider_record}
    preload_path = old.policy_evidence_dir / "preload-manifest.json"
    # This shared producer uses canonical JSON without our authority-record LF.
    preload_path.write_bytes(ec2.canonical(preload)[:-1])
    setup = {
        "provider_context": old.provider_record,
        "preload_manifest_sha256": record(preload_path)["sha256"],
    }
    setup_path = old.policy_evidence_dir / "policy-setup.json"
    setup_path.write_bytes(ec2.canonical(setup))
    old.policy_ready(
        preload_sha256=record(preload_path)["sha256"],
        report_sha256=record(setup_path)["sha256"],
    )
    old.acquire_runner()
    manifest_path = old.artifact_dir / "manifest.json"
    old.artifact_dir.mkdir()
    manifest_path.write_bytes(ec2.canonical(manifest_for(old)))
    ticket = old.reserve_probe(name="positive", nonce="a" * 32)
    old.admit_probe(ticket)
    case_path = old.run_dir / "case-01.json"
    case_path.write_bytes(
        ec2.canonical(
            {
                "name": "positive",
                "nonce": ticket.nonce,
                "payload_started": False,
                "failure": "setup_refused",
                "stop_confirmed": True,
                "cleanup_confirmed": True,
                "host_facts": {
                    "manifest_sha256": record(manifest_path)["sha256"],
                    "admission_number": 1,
                    "original_admission_ns": ticket.admitted_ns,
                    "original_deadline_ns": ticket.deadline_ns,
                },
            }
        )
    )
    old.finish_probe(
        ticket,
        result_sha256=record(case_path)["sha256"],
        stop_confirmed=True,
        cleanup_confirmed=True,
        failure="setup_refused",
    )
    old.finish(outcome="NOT_QUALIFIED", reason="fixed_catalog_incomplete")
    cases = [
        {"name": name, "status": "UNKNOWN", "admission_submitted": i == 0}
        for i, name in enumerate(ec2.FIXED_PROBES)
    ]
    cases[0].update(
        admission=dataclasses.asdict(ticket),
        nonce=ticket.nonce,
        execution_evidence=record(case_path),
    )
    report = {
        "kind": "restricted_reference_ec2_recovery_qualification_v1",
        "schema_version": 1,
        "source_revision": PREVIOUS,
        "run_id": old.run_id,
        "boot_id": old.boot_id,
        "controls_status": "NOT_QUALIFIED",
        "admissions_charged": 1,
        "confirmed_backend_admissions": 1,
        "backend_unconfirmed_admissions": 0,
        "pending_probe_outcomes": 0,
        "observed_payload_starts": 0,
        "research_reservations": 0,
        "replay_engine_invocations": 0,
        "cases": cases,
        "provider_context": old.provider_record,
        "recovery_context": old.recovery_context,
        "manifest_sha256": record(manifest_path)["sha256"],
        "recovery_accounting": old.recovery_accounting(old.snapshot()),
    }
    report_path = old.run_dir / "qualification-report.json"
    report_path.write_bytes(ec2.canonical(report))
    paths = {
        "claim_sha256": old.run_dir / "claim.json",
        "state_sha256": old.run_dir / "state.json",
        "report_sha256": report_path,
        "case_sha256": case_path,
        "source_lock_sha256": recovery.current_lock,
        "manifest_sha256": manifest_path,
        "plan_sha256": recovery.plan_path,
        "consumption_sha256": recovery.consumption,
        "policy_setup_sha256": setup_path,
        "policy_preload_sha256": preload_path,
        "identity_document_sha256": old.run_dir / "instance-identity-document.json",
    }
    history = {
        "original": dict(ec2.RECOVERY_PREDECESSOR),
        "recovery": {
            **ec2.RECOVERY_V2_HISTORY["recovery"],
            "source_revision": PREVIOUS,
            "run_id": old.run_id,
            "boot_id": old.boot_id,
            **{key: record(path)["sha256"] for key, path in paths.items()},
        },
    }
    monkeypatch.setattr(ec2, "RECOVERY_V2_HISTORY", history)
    os.close(old._lock_fd)
    old._lock_fd = -1
    recovery.host.boot[0], recovery.host.clock[0] = BOOT, 3000
    directory = recovery.host.root / "recovery-v2"
    directory.mkdir()
    stop = directory / "operator-stop.md"
    stop.write_bytes(b"Synthetic second Stop owner observation, never AWS attestation.\n")
    monkeypatch.setattr(ec2, "RECOVERY_V2_STOP_SHA256", record(stop)["sha256"])
    helper = recovery.host.source / ec2.RECOVERY_V2_SOURCE_FILES[-1]
    helper.write_bytes(b"synthetic v2 preparation source\n")
    lock = recovery.host.root / "sources" / CURRENT / "source-lock.json"
    lock.parent.mkdir()
    lock.write_bytes(
        ec2.canonical(
            {
                "kind": "restricted_reference_ec2_recovery_source_lock_v2",
                "schema_version": 2,
                "source_revision": CURRENT,
                "source_root": str(recovery.host.source),
                "files": {
                    relative: {
                        key: record(recovery.host.source / relative)[key]
                        for key in ("sha256", "bytes")
                    }
                    for relative in ec2.RECOVERY_V2_SOURCE_FILES
                },
            }
        )
    )
    preserved = {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in recovery.host.root.rglob("*")
        if path.is_file()
    }
    context = SimpleNamespace(
        host=recovery.host,
        previous=recovery,
        old=old,
        paths=paths,
        history=history,
        stop=stop,
        helper=helper,
        source_lock=lock,
        preserved=preserved,
        plan_path=directory / "plan.json",
        consumption=directory / "consumption.json",
        new_dir=recovery.host.root / "runs" / ec2.RECOVERY_V2_RUN_ID,
        runs=[],
    )
    yield context
    for run in context.runs:
        with suppress(OSError):
            os.close(run._lock_fd)


@pytest.fixture
def v2(v2_history):
    v2_history.plan = ec2.recovery_v2_plan_document(
        source_revision=CURRENT, run_id=ec2.RECOVERY_V2_RUN_ID, plan_id=ec2.RECOVERY_V2_PLAN_ID
    )
    v2_history.plan_path.write_bytes(ec2.canonical(v2_history.plan))

    def claim():
        run = ec2.Ec2Run.claim_recovery_v2(
            source_revision=CURRENT, run_id=ec2.RECOVERY_V2_RUN_ID, plan_id=ec2.RECOVERY_V2_PLAN_ID
        )
        v2_history.runs.append(run)
        return run

    v2_history.claim = claim
    return v2_history


def ready(v2):
    run = v2.claim()
    run.prepare_host()
    run.policy_evidence_dir.mkdir()
    for name in ("preload-manifest.json", "policy-setup.json"):
        (run.policy_evidence_dir / name).write_bytes(b"synthetic policy receipt\n")
    digest = ec2._sha(b"synthetic policy receipt\n")
    run.policy_ready(preload_sha256=digest, report_sha256=digest)
    run.acquire_runner()
    return run


def assert_preserved(v2):
    for path, (raw, inode) in v2.preserved.items():
        assert path.read_bytes() == raw and path.stat().st_ino == inode


def test_fixed_selection_and_closure_do_not_extend_old_v1_authority():
    assert ec2.RECOVERY_V2_FREEZE_REVISION == "5ef1945c154cc944900a6d042f947bba0d620fd9"
    assert ec2.RECOVERY_V2_PLAN_ID == "ec2-recovery-20261127-v2"
    assert ec2.RECOVERY_V2_RUN_ID.endswith("0003")
    assert len(ec2.RECOVERY_SOURCE_FILES) == len(ec2.RECOVERY_V2_SOURCE_FILES) == 10
    assert ec2.RECOVERY_SOURCE_FILES[-1] not in ec2.RECOVERY_V2_SOURCE_FILES
    assert ec2.RECOVERY_ALLOWANCE["max_cumulative_admissions"] == 25
    assert ec2.RECOVERY_V2_ALLOWANCE["max_cumulative_admissions"] == 26


@pytest.mark.parametrize("version", [True, 2.0, 0, 3])
def test_manifest_version_argument_is_exact_and_never_coerced(version):
    with pytest.raises(ValueError, match="version"):
        ec2.validate_recovery_manifest_shape({}, version=version)


@pytest.mark.parametrize("changed", ["old_source", "old_plan", "fourth_run"])
def test_no_old_source_selection_or_fourth_run_is_an_implicit_retry(v2, changed):
    arguments = {
        "source_revision": CURRENT,
        "run_id": ec2.RECOVERY_V2_RUN_ID,
        "plan_id": ec2.RECOVERY_V2_PLAN_ID,
    }
    if changed == "old_source":
        arguments["source_revision"] = PREVIOUS
    elif changed == "old_plan":
        arguments["plan_id"] = ec2.RECOVERY_PLAN_ID
    else:
        arguments["run_id"] = "ec201aab11254e8bb7cd1573a96a0004"
    with pytest.raises(ValueError, match="fixed v2"):
        ec2.Ec2Run.claim_recovery_v2(**arguments)
    assert not v2.consumption.exists() and not v2.new_dir.exists()


def test_actual_two_failures_and_pretty_metadata_are_readonly_then_counted(v2):
    raw = v2.paths["identity_document_sha256"].read_bytes()
    assert raw != ec2.canonical(json.loads(raw))
    run = v2.claim()
    assert run.recovery_schema_version == 2
    assert run.started_ns == 3000 and run.deadline_ns == 3000 + ec2.WINDOW_NS
    assert run.setup_deadline_ns == 3000 + ec2.SETUP_NS
    accounting = run.recovery_accounting(run.snapshot())
    assert len(accounting) == 14 and accounting["prior_charged"] == 2
    assert accounting["cumulative_charged"] == accounting["cumulative_backend_confirmed"] == 2
    assert accounting["historical_run_ids"] == [ec2.RECOVERY_PREDECESSOR["run_id"], v2.old.run_id]
    consumption = json.loads(v2.consumption.read_bytes())
    assert len(consumption) == 16 and consumption["schema_version"] == 2
    assert consumption["history_state_sha256"] == {
        key: value["state_sha256"] for key, value in v2.history.items()
    }
    assert len(v2.host.requests) == 2  # Neither the plan nor v2 claim contacts IMDS.
    assert_preserved(v2)


def test_original_inode_readonly_mutex_excludes_overlap_and_no_fourth_window(v2):
    run = v2.claim()
    assert fcntl.fcntl(run._lock_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert fcntl.fcntl(run._lock_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    assert os.fstat(run._lock_fd).st_ino == (v2.host.root / "host-admission.json").stat().st_ino
    with pytest.raises(BlockingIOError):
        v2.claim()
    run.finish(outcome="NOT_QUALIFIED", reason="synthetic ended")
    os.close(run._lock_fd)
    run._lock_fd = -1
    with pytest.raises(FileExistsError):
        v2.claim()
    with pytest.raises(FileExistsError):
        v2.previous.claim()
    with pytest.raises(FileExistsError):
        ec2.Ec2Run.claim(source_revision=CURRENT, run_id="f" * 32)
    assert_preserved(v2)


@pytest.mark.parametrize("slot", ["original", "recovery"])
def test_both_old_boots_refuse_without_new_consumption(v2, slot):
    v2.host.boot[0] = v2.history[slot]["boot_id"]
    with pytest.raises(ValueError, match="both failed boots"):
        v2.claim()
    assert not v2.consumption.exists() and not v2.new_dir.exists()


def test_validation_time_uses_entry_anchors_and_cannot_extend_setup(v2, monkeypatch):
    original = ec2._recovery_v2_history

    def delayed(seals):
        result = original(seals)
        v2.host.clock[0] += ec2.SETUP_NS
        return result

    monkeypatch.setattr(ec2, "_recovery_v2_history", delayed)
    with pytest.raises(TimeoutError):
        v2.claim()
    assert not v2.consumption.exists() and not v2.new_dir.exists()


@pytest.mark.parametrize(
    "target",
    [
        "claim_sha256",
        "state_sha256",
        "report_sha256",
        "case_sha256",
        "source_lock_sha256",
        "manifest_sha256",
        "plan_sha256",
        "consumption_sha256",
        "policy_setup_sha256",
        "policy_preload_sha256",
        "identity_document_sha256",
        "stop",
        "helper",
        "source_lock",
    ],
)
def test_changed_second_history_or_current_source_refuses_before_consumption(v2, target):
    path = v2.paths[target] if target in v2.paths else getattr(v2, target)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        v2.claim()
    assert not v2.consumption.exists() and not v2.new_dir.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown", True),
        ("schema_version", True),
        ("schema_version", 2.0),
        ("plan_id", ec2.RECOVERY_PLAN_ID),
        ("run_id", ec2.RECOVERY_RUN_ID),
        ("freeze_revision", "f" * 40),
    ],
)
def test_plan_version_lineage_unknown_fields_and_type_coercion_are_not_permission(v2, field, value):
    plan = {**v2.plan, field: value}
    v2.plan_path.write_bytes(ec2.canonical(plan))
    with pytest.raises(ValueError):
        v2.claim()
    assert not v2.consumption.exists()


def test_duplicate_plan_key_is_refused_before_any_consumption(v2):
    v2.plan_path.write_bytes(
        v2.plan_path.read_bytes().replace(
            b'"schema_version":2', b'"schema_version":2,"schema_version":2', 1
        )
    )
    with pytest.raises(ValueError, match="Duplicate"):
        v2.claim()
    assert not v2.consumption.exists()


@pytest.mark.parametrize("fault", ["partial", "fsync", "mkdir", "silent_partial"])
def test_consumption_faults_are_durable_used_allowances_not_free_retries(v2, monkeypatch, fault):
    write, sync, mkdir = ec2.write_exclusive, ec2._fsync_dir, Path.mkdir

    def failed_write(path, raw):
        if path == v2.consumption and fault in {"partial", "silent_partial"}:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, raw[:9])
                os.fsync(fd)
            finally:
                os.close(fd)
            if fault == "partial":
                raise OSError("injected partial v2 consumption")
            return
        write(path, raw)

    def failed_sync(path):
        if fault == "fsync" and path == v2.consumption.parent and v2.consumption.exists():
            raise OSError("injected v2 consumption parent fsync")
        sync(path)

    def failed_mkdir(path, *args, **kwargs):
        if fault == "mkdir" and path == v2.new_dir:
            raise OSError("injected successor mkdir")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(ec2, "write_exclusive", failed_write)
    monkeypatch.setattr(ec2, "_fsync_dir", failed_sync)
    monkeypatch.setattr(Path, "mkdir", failed_mkdir)
    with pytest.raises((OSError, ValueError)):
        v2.claim()
    retained = v2.consumption.read_bytes()
    assert retained and not v2.new_dir.exists() and len(v2.host.requests) == 2
    monkeypatch.setattr(ec2, "write_exclusive", write)
    monkeypatch.setattr(ec2, "_fsync_dir", sync)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(FileExistsError):
        v2.claim()
    assert v2.consumption.read_bytes() == retained
    assert_preserved(v2)


@pytest.mark.parametrize(
    "target",
    [
        "state_sha256",
        "consumption_sha256",
        "manifest_sha256",
        "plan_path",
        "consumption",
        "stop",
        "helper",
    ],
)
def test_live_old_or_new_authority_change_stops_before_a_probe(v2, target):
    run = v2.claim()
    path = v2.paths[target] if target in v2.paths else getattr(v2, target)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match=r"changed|differ"):
        run.snapshot()
    assert run._state["charged"] == 0 and v2.consumption.exists()


@pytest.mark.parametrize("value", [False, 0.0])
def test_snapshot_numeric_coercion_cannot_authenticate_a_budget(v2, value):
    run = v2.claim()
    with pytest.raises(ValueError, match="snapshot"):
        run.recovery_accounting(dataclasses.replace(run.snapshot(), charged=value))


def test_state_context_cannot_redefine_version_or_historical_charge(v2):
    run = v2.claim()
    copy = run.recovery_context
    copy["history"]["recovery"]["charged"] = 0
    assert run.recovery_schema_version == 2
    run._state["recovery_context"]["schema_version"] = 1
    run._persist()
    with pytest.raises(ValueError, match="context"):
        _ = run.recovery_schema_version


def test_pending_backend_and_persistence_uncertainty_keep_the_third_charge(v2, monkeypatch):
    run = ready(v2)
    ticket = run.reserve_probe(name="positive", nonce="c" * 32)
    snapshot = run.snapshot()
    assert snapshot.charged == 1 and snapshot.unconfirmed == snapshot.pending_outcomes == 1
    assert run.recovery_accounting(snapshot)["cumulative_charged"] == 3
    with pytest.raises(ValueError):
        run.admit_probe(dataclasses.replace(ticket, admission_number=True))

    def uncertain(*_args):
        raise OSError("injected durable admission uncertainty")

    monkeypatch.setattr(ec2.os, "replace", uncertain)
    with pytest.raises(OSError):
        run.admit_probe(ticket)
    with pytest.raises(ValueError, match="fenced"):
        run.recovery_accounting(snapshot)
    assert run._state["charged"] == 1 and v2.consumption.exists()


@pytest.mark.parametrize(
    "change,diagnostic",
    [
        ("boolean_counter", "charged type"),
        ("pending", "admission outcome"),
        ("unconfirmed", "backend_confirmed"),
        ("owner", "state owner"),
        ("clock", "original deadline"),
    ],
)
def test_second_history_semantics_refuse_even_with_its_digest_rebound(
    v2, monkeypatch, change, diagnostic
):
    path = v2.paths["state_sha256"]
    state = json.loads(path.read_bytes())
    if change == "boolean_counter":
        state["charged"] = True
    elif change == "pending":
        state["admissions"][0]["outcome"] = None
    elif change == "unconfirmed":
        state["backend_confirmed"] = 0
    elif change == "owner":
        state["owner"]["pid"] += 1
    else:
        state["deadline_ns"] += 1
    path.write_bytes(ec2.canonical(state))
    pins = json.loads(ec2.canonical(v2.history))
    pins["recovery"]["state_sha256"] = record(path)["sha256"]
    monkeypatch.setattr(ec2, "RECOVERY_V2_HISTORY", pins)
    with pytest.raises(ValueError, match=diagnostic):
        v2.claim()
    assert not v2.consumption.exists()


def test_old_manifest_cannot_be_rewritten_to_new_prior_count_even_with_hashes_rebound(
    v2, monkeypatch
):
    manifest_path = v2.paths["manifest_sha256"]
    manifest = json.loads(manifest_path.read_bytes())
    manifest["recovery_accounting"]["cumulative_charged"] = 2
    manifest_path.write_bytes(ec2.canonical(manifest))
    case_path = v2.paths["case_sha256"]
    result = json.loads(case_path.read_bytes())
    result["host_facts"]["manifest_sha256"] = record(manifest_path)["sha256"]
    case_path.write_bytes(ec2.canonical(result))
    state_path = v2.paths["state_sha256"]
    state = json.loads(state_path.read_bytes())
    state["admissions"][0]["outcome"]["result_sha256"] = record(case_path)["sha256"]
    state_path.write_bytes(ec2.canonical(state))
    report_path = v2.paths["report_sha256"]
    report = json.loads(report_path.read_bytes())
    report["manifest_sha256"] = record(manifest_path)["sha256"]
    report["cases"][0]["execution_evidence"] = record(case_path)
    report_path.write_bytes(ec2.canonical(report))
    pins = json.loads(ec2.canonical(v2.history))
    for key in ("manifest_sha256", "case_sha256", "state_sha256", "report_sha256"):
        pins["recovery"][key] = record(v2.paths[key])["sha256"]
    monkeypatch.setattr(ec2, "RECOVERY_V2_HISTORY", pins)
    with pytest.raises(ValueError, match="second pre-probe accounting"):
        v2.claim()
    assert not v2.consumption.exists()


def complete_catalog(v2):
    run = ready(v2)
    run.artifact_dir.mkdir()
    manifest = manifest_for(run)
    manifest_path = run.artifact_dir / "manifest.json"
    manifest_path.write_bytes(ec2.canonical(manifest))
    cases = []
    for index, name in enumerate(ec2.FIXED_PROBES):
        ticket = run.reserve_probe(name=name, nonce=f"{index + 1:032x}")
        run.admit_probe(ticket)
        path = run.run_dir / f"case-{index + 1:02d}.json"
        path.write_bytes(
            ec2.canonical(
                {
                    "name": name,
                    "nonce": ticket.nonce,
                    "payload_started": True,
                    "failure": None,
                    "stop_confirmed": True,
                    "cleanup_confirmed": True,
                    "host_facts": {
                        "manifest_sha256": record(manifest_path)["sha256"],
                        "admission_number": index + 1,
                        "original_admission_ns": ticket.admitted_ns,
                        "original_deadline_ns": ticket.deadline_ns,
                    },
                }
            )
        )
        run.finish_probe(
            ticket,
            result_sha256=record(path)["sha256"],
            stop_confirmed=True,
            cleanup_confirmed=True,
            failure=None,
        )
        cases.append(
            {
                "name": name,
                "nonce": ticket.nonce,
                "admission_submitted": True,
                "admission": dataclasses.asdict(ticket),
                "status": "PASS",
                "reason": "actual_scoped_control_evidence",
                "payload_started": True,
                "execution_evidence": record(path),
            }
        )
    snapshot = run.snapshot()
    report = {
        "kind": "restricted_reference_ec2_recovery_qualification_v2",
        "schema_version": 2,
        "controls_status": "QUALIFIED_REFERENCE_ONLY",
        "production_m1": "DISABLED",
        "independent_human_security_review": "NOT_PERFORMED",
        "external_human_reproduction": "0/0/PENDING",
        "research_reservations": 0,
        "replay_engine_invocations": 0,
        "source_revision": CURRENT,
        "run_id": run.run_id,
        "boot_id": run.boot_id,
        "acceptance_gate": "matching_durable_terminal_and_final_report_sha256",
        "original_qualification_budget": {"max_admissions": 24, "window_ns": ec2.WINDOW_NS},
        "cases": cases,
        "scope": "Synthetic publication decisions; product M1 disabled",
        "stop_scope": "Independent AWS state readback required",
        "recovery_context": run.recovery_context,
        "durable_budget_status": "CONFIRMED",
        "durable_budget": dataclasses.asdict(snapshot),
        "admissions_charged": 24,
        "confirmed_backend_admissions": 24,
        "backend_unconfirmed_admissions": 0,
        "pending_probe_outcomes": 0,
        "recovery_accounting": run.recovery_accounting(snapshot),
        "admission_accounting_scope": "Synthetic fixture; submitted slots stay charged",
        "provider_context": run.provider_record,
        "manifest_sha256": record(manifest_path)["sha256"],
        "completed_at_monotonic_ns": v2.host.clock[0],
        "observed_payload_starts": 24,
    }
    return run, report


def publish(run, report):
    path = run.run_dir / "qualification-report.json"
    path.write_bytes(ec2.canonical(report))
    return record(path)["sha256"]


def test_full_new_catalog_keeps_initial_two_then_final_twenty_six_and_receipt(v2):
    run, report = complete_catalog(v2)
    manifest = json.loads((run.artifact_dir / "manifest.json").read_bytes())
    assert manifest["recovery_accounting"]["current_charged"] == 0
    assert manifest["recovery_accounting"]["cumulative_charged"] == 2
    digest = publish(run, report)
    run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    receipt = run.qualification_receipt()
    assert receipt["kind"] == "restricted_reference_ec2_recovery_terminal_receipt_v2"
    assert receipt["schema_version"] == 2 and len(receipt) == 10
    assert receipt["final_report_sha256"] == digest
    assert receipt["recovery_accounting"] == report["recovery_accounting"]
    assert receipt["recovery_accounting"]["current_charged"] == 24
    assert receipt["recovery_accounting"]["cumulative_charged"] == 26
    assert receipt["recovery_context"] == run.recovery_context
    assert_preserved(v2)
    with pytest.raises(ValueError):
        run.reserve_probe(name="positive", nonce="f" * 32)
    (run.run_dir / "qualification-report.json").write_bytes(b"{}\n")
    with pytest.raises(ValueError):
        run.qualification_receipt()


@pytest.mark.parametrize(
    "change",
    [
        "v1_kind",
        "bool_schema",
        "unknown_report",
        "old_ticket",
        "old_case_path",
        "missing_history",
        "boolean_history",
        "unknown_context",
        "missing_payload_gate",
    ],
)
def test_success_publication_cannot_mix_older_results_or_drop_two_charges(v2, change):
    run, report = complete_catalog(v2)
    if change == "v1_kind":
        report["kind"] = "restricted_reference_ec2_recovery_qualification_v1"
    elif change == "bool_schema":
        report["schema_version"] = True
    elif change == "unknown_report":
        report["free_retry"] = True
    elif change == "old_ticket":
        report["cases"][0]["admission"]["source_revision"] = PREVIOUS
    elif change == "old_case_path":
        report["cases"][0]["execution_evidence"] = record(v2.paths["case_sha256"])
    elif change == "missing_history":
        report["recovery_accounting"]["cumulative_charged"] = 24
    elif change == "boolean_history":
        report["recovery_accounting"]["prior_charged"] = True
    elif change == "unknown_context":
        report["recovery_context"]["another_window"] = True
    else:
        report["cases"][0]["payload_started"] = False
    digest = publish(run, report)
    with pytest.raises(ValueError):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    assert run._state["final_report_sha256"] is None and v2.consumption.exists()
    assert run.recovery_accounting(run.snapshot())["cumulative_charged"] == 26


@pytest.mark.parametrize("change", ["unknown", "missing", "v1_schema", "wrong_initial_count"])
def test_manifest_refusal_after_rebinding_every_raw_case_and_durable_outcome(v2, change):
    run, report = complete_catalog(v2)
    path = run.artifact_dir / "manifest.json"
    manifest = json.loads(path.read_bytes())
    if change == "unknown":
        manifest["another_window"] = True
    elif change == "missing":
        del manifest["os_release"]
    elif change == "v1_schema":
        manifest["schema_version"] = 1
    else:
        manifest["recovery_accounting"]["cumulative_charged"] = 26
    path.write_bytes(ec2.canonical(manifest))
    report["manifest_sha256"] = record(path)["sha256"]
    for index, case in enumerate(report["cases"]):
        result_path = run.run_dir / f"case-{index + 1:02d}.json"
        result = json.loads(result_path.read_bytes())
        result["host_facts"]["manifest_sha256"] = report["manifest_sha256"]
        result_path.write_bytes(ec2.canonical(result))
        case["execution_evidence"] = record(result_path)
        run._state["admissions"][index]["outcome"]["result_sha256"] = record(result_path)["sha256"]
    run._persist()
    digest = publish(run, report)
    with pytest.raises(ValueError, match=r"manifest|accounting"):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    assert run._state["final_report_sha256"] is None
    assert run.recovery_accounting(run.snapshot())["cumulative_charged"] == 26
