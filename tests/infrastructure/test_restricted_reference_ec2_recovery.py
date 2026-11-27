"""Real filesystem fault decisions with a synthetic trusted host, never OS qualification."""

from __future__ import annotations

import dataclasses
import fcntl
import json
import os
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_restricted_reference_ec2 import BOOT, REVISION, RUN_ID, prepared
from test_restricted_reference_ec2 import host as host

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

CURRENT = "d" * 40


@pytest.fixture
def recovery(host, monkeypatch):
    """Pins are replaced by synthetic bytes; the actual admission/filesystem logic runs."""
    old = prepared(host)
    old.acquire_runner()
    ticket = old.reserve_probe(name="positive", nonce="1" * 32)
    old.admit_probe(ticket)
    result = {
        "name": "positive",
        "nonce": ticket.nonce,
        "payload_started": False,
        "failure": "setup_refused",
        "stop_confirmed": True,
        "cleanup_confirmed": True,
    }
    result_path = old.run_dir / "case-01.json"
    result_path.write_bytes(ec2.canonical(result))
    digest = ec2._sha(result_path.read_bytes())
    old.finish_probe(
        ticket,
        result_sha256=digest,
        stop_confirmed=True,
        cleanup_confirmed=True,
        failure="setup_refused",
    )
    old.finish(outcome="NOT_QUALIFIED", reason="fixed_catalog_incomplete")
    report = {
        "kind": "restricted_reference_ec2_qualification_v1",
        "source_revision": REVISION,
        "run_id": RUN_ID,
        "boot_id": BOOT,
        "controls_status": "NOT_QUALIFIED",
        "admissions_charged": 1,
        "confirmed_backend_admissions": 1,
        "backend_unconfirmed_admissions": 0,
        "pending_probe_outcomes": 0,
        "observed_payload_starts": 0,
        "research_reservations": 0,
        "replay_engine_invocations": 0,
        "cases": [
            {"name": name, "status": "UNKNOWN", "admission_submitted": i == 0}
            for i, name in enumerate(ec2.FIXED_PROBES)
        ],
    }
    (old.run_dir / "qualification-report.json").write_bytes(ec2.canonical(report))
    os.close(old._lock_fd)
    previous = {
        **ec2.RECOVERY_PREDECESSOR,
        "source_revision": REVISION,
        "run_id": RUN_ID,
        "boot_id": BOOT,
    }
    paths = {
        "host_claim_sha256": host.root / "host-admission.json",
        "claim_sha256": old.run_dir / "claim.json",
        "state_sha256": old.run_dir / "state.json",
        "report_sha256": old.run_dir / "qualification-report.json",
        "case_sha256": result_path,
        "source_lock_sha256": host.lock,
    }
    for key, path in paths.items():
        previous[key] = ec2._sha(path.read_bytes())
    monkeypatch.setattr(ec2, "RECOVERY_PREDECESSOR", previous)
    stop = host.root / "recovery-evidence" / "operator-stop.md"
    stop.parent.mkdir()
    stop.write_bytes(b"Synthetic owner Stop observation; not cloud attestation.\n")
    monkeypatch.setattr(ec2, "RECOVERY_STOP_SHA256", ec2._sha(stop.read_bytes()))
    helper = host.source / ec2.RECOVERY_SOURCE_FILES[-1]
    helper.write_bytes(b"synthetic trusted preparation source\n")
    current_lock = host.root / "sources" / CURRENT / "source-lock.json"
    current_lock.parent.mkdir()
    current_lock.write_bytes(
        ec2.canonical(
            {
                "kind": "restricted_reference_ec2_recovery_source_lock_v1",
                "schema_version": 1,
                "source_revision": CURRENT,
                "source_root": str(host.source),
                "files": {
                    relative: {
                        "sha256": ec2._sha((host.source / relative).read_bytes()),
                        "bytes": len((host.source / relative).read_bytes()),
                    }
                    for relative in ec2.RECOVERY_SOURCE_FILES
                },
            }
        )
    )
    host.boot[0] = "22222222-2222-2222-2222-222222222222"
    host.clock[0] = 2000
    plan = ec2.recovery_plan_document(
        source_revision=CURRENT,
        run_id=ec2.RECOVERY_RUN_ID,
        plan_id=ec2.RECOVERY_PLAN_ID,
    )
    plan_path = host.root / "recovery-plan.json"
    plan_path.write_bytes(ec2.canonical(plan))
    old_bytes = {path: path.read_bytes() for path in paths.values()}
    runs = []

    def claim():
        run = ec2.Ec2Run.claim_recovery(
            source_revision=CURRENT,
            run_id=ec2.RECOVERY_RUN_ID,
            plan_id=ec2.RECOVERY_PLAN_ID,
        )
        runs.append(run)
        return run

    context = SimpleNamespace(
        host=host,
        old=old,
        paths=paths,
        stop=stop,
        plan=plan,
        plan_path=plan_path,
        current_lock=current_lock,
        helper=helper,
        old_bytes=old_bytes,
        claim=claim,
        consumption=host.root / "recovery-consumption.json",
        new_dir=host.root / "runs" / ec2.RECOVERY_RUN_ID,
    )
    yield context
    for run in runs:
        with suppress(OSError):
            os.close(run._lock_fd)


def ready(recovery):
    run = recovery.claim()
    run.prepare_host()
    run.policy_evidence_dir.mkdir()
    (run.policy_evidence_dir / "preload-manifest.json").write_bytes(b"preload\n")
    (run.policy_evidence_dir / "policy-setup.json").write_bytes(b"policy\n")
    run.policy_ready(preload_sha256=ec2._sha(b"preload\n"), report_sha256=ec2._sha(b"policy\n"))
    run.acquire_runner()
    return run


def test_recovery_literal_pins_do_not_select_arbitrary_followups():
    assert ec2.RECOVERY_PLAN_ID == "ec2-recovery-20261126-v1"
    assert ec2.RECOVERY_RUN_ID == "ec201aab11254e8bb7cd1573a96a0002"
    assert ec2.RECOVERY_FREEZE_REVISION == "a19cff330df5a04e405c83baebcfb0bddf3498fa"
    assert ec2.RECOVERY_PREDECESSOR["charged"] == 1
    assert (
        ec2.RECOVERY_PREDECESSOR["state_sha256"]
        == "2b4b455b60f97d5052ae4bcb81c01f41566708a9c9486a94de71dee03eb13a5d"
    )
    assert len(ec2.SOURCE_FILES) == 9 and len(ec2.RECOVERY_SOURCE_FILES) == 10


def test_readonly_plan_preparation_allocates_no_window_or_consumption(recovery):
    before = {path: path.read_bytes() for path in recovery.host.root.rglob("*") if path.is_file()}
    expected = ec2.recovery_plan_document(
        source_revision=CURRENT,
        run_id=ec2.RECOVERY_RUN_ID,
        plan_id=ec2.RECOVERY_PLAN_ID,
    )
    assert expected == recovery.plan
    assert before == {
        path: path.read_bytes() for path in recovery.host.root.rglob("*") if path.is_file()
    }
    assert not recovery.consumption.exists() and not recovery.new_dir.exists()


def test_original_history_and_factory_entry_anchors_survive_validation(recovery, monkeypatch):
    original = ec2._recovery_history

    def delayed(seals):
        value = original(seals)
        recovery.host.clock[0] += 3_000_000_000
        return value

    monkeypatch.setattr(ec2, "_recovery_history", delayed)
    run = recovery.claim()
    assert run.started_ns == 2000
    assert run.setup_deadline_ns == 2000 + ec2.SETUP_NS
    assert run.deadline_ns == 2000 + ec2.WINDOW_NS
    budget = run.snapshot()
    accounting = run.recovery_accounting(budget)
    assert accounting["current_charged"] == 0 and accounting["cumulative_charged"] == 1
    assert accounting["prior_backend_confirmed"] == 1
    assert all(path.read_bytes() == raw for path, raw in recovery.old_bytes.items())
    assert len(recovery.host.requests) == 1  # Historical fixture request only.
    assert json.loads(recovery.consumption.read_bytes())["started_ns"] == 2000


def test_validation_cannot_receive_a_fresh_setup_deadline(recovery, monkeypatch):
    original = ec2._recovery_history

    def delayed(seals):
        value = original(seals)
        recovery.host.clock[0] += ec2.SETUP_NS
        return value

    monkeypatch.setattr(ec2, "_recovery_history", delayed)
    with pytest.raises(TimeoutError, match="deadline exhausted during validation"):
        recovery.claim()
    assert not recovery.consumption.exists() and not recovery.new_dir.exists()
    assert len(recovery.host.requests) == 1


def test_same_boot_cannot_resume_the_predecessor_window(recovery):
    recovery.host.boot[0] = BOOT
    with pytest.raises(ValueError, match="different actual boot"):
        recovery.claim()
    assert not recovery.consumption.exists()


def test_old_inode_is_a_readonly_cloexec_global_mutex_and_no_third_invocation(recovery):
    run = recovery.claim()
    assert fcntl.fcntl(run._lock_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert fcntl.fcntl(run._lock_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    assert (
        os.fstat(run._lock_fd).st_ino == (recovery.host.root / "host-admission.json").stat().st_ino
    )
    with pytest.raises(BlockingIOError):
        recovery.claim()
    run.finish(outcome="NOT_QUALIFIED", reason="fixture ended")
    os.close(run._lock_fd)
    with pytest.raises(FileExistsError):
        recovery.claim()
    with pytest.raises(FileExistsError):
        ec2.Ec2Run.claim(source_revision=CURRENT, run_id="e" * 32)
    assert all(path.read_bytes() == raw for path, raw in recovery.old_bytes.items())


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown_authority", True),
        ("schema_version", True),
        ("schema_version", 1.0),
        ("freeze_revision", "f" * 40),
        ("source_revision", REVISION),
        ("run_id", "f" * 32),
        ("plan_id", "another-plan"),
    ],
)
def test_invalid_or_unknown_plan_never_consumes_allowance(recovery, field, value):
    plan = {**recovery.plan, field: value}
    recovery.plan_path.write_bytes(ec2.canonical(plan))
    with pytest.raises(ValueError):
        recovery.claim()
    assert not recovery.consumption.exists() and not recovery.new_dir.exists()


@pytest.mark.parametrize("value", [True, 24.0, 25])
def test_allowance_type_and_cap_changes_are_not_authority(recovery, value):
    plan = json.loads(recovery.plan_path.read_bytes())
    plan["allowance"]["max_admissions"] = value
    recovery.plan_path.write_bytes(ec2.canonical(plan))
    with pytest.raises(ValueError):
        recovery.claim()
    assert not recovery.consumption.exists()


def test_pinned_history_still_requires_integer_counters(recovery, monkeypatch):
    path = recovery.paths["state_sha256"]
    state = json.loads(path.read_bytes())
    state["charged"] = True
    path.write_bytes(ec2.canonical(state))
    monkeypatch.setattr(
        ec2,
        "RECOVERY_PREDECESSOR",
        {
            **ec2.RECOVERY_PREDECESSOR,
            "state_sha256": ec2._sha(path.read_bytes()),
        },
    )
    with pytest.raises(ValueError, match="predecessor charged type"):
        recovery.claim()
    assert not recovery.consumption.exists()


def test_duplicate_plan_json_fields_are_refused_before_consumption(recovery):
    raw = recovery.plan_path.read_bytes().replace(
        b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1
    )
    recovery.plan_path.write_bytes(raw)
    with pytest.raises(ValueError, match="Duplicate"):
        recovery.claim()
    assert not recovery.consumption.exists()


@pytest.mark.parametrize(
    "target",
    [
        "host_claim_sha256",
        "claim_sha256",
        "state_sha256",
        "report_sha256",
        "case_sha256",
        "source_lock_sha256",
        "stop",
        "helper",
        "current_lock",
    ],
)
def test_changed_predecessor_stop_or_source_refuses_without_new_run(recovery, target):
    path = recovery.paths[target] if target in recovery.paths else getattr(recovery, target)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        recovery.claim()
    assert not recovery.consumption.exists() and not recovery.new_dir.exists()


@pytest.mark.parametrize(
    "target", ["state_sha256", "report_sha256", "stop", "helper", "plan_path", "consumption"]
)
def test_live_lineage_or_source_change_stops_further_admission(recovery, target):
    run = recovery.claim()
    path = recovery.paths[target] if target in recovery.paths else getattr(recovery, target)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match=r"changed|differ"):
        run.snapshot()
    assert recovery.consumption.exists()
    assert run._state["charged"] == 0


def test_a_copied_context_cannot_expand_the_live_allowance(recovery):
    run = recovery.claim()
    copy = run.recovery_context
    copy["allowance"]["max_admissions"] = 999
    assert run.recovery_context["allowance"]["max_admissions"] == 24
    run._state["recovery_context"]["allowance"]["max_admissions"] = 999
    run._persist()
    with pytest.raises(ValueError, match="recovery context"):
        run.snapshot()


@pytest.mark.parametrize("value", [False, 0.0])
def test_snapshot_argument_cannot_hide_bool_or_float_counters(recovery, value):
    run = recovery.claim()
    changed = dataclasses.replace(run.snapshot(), charged=value)
    with pytest.raises(ValueError, match="snapshot"):
        run.recovery_accounting(changed)


@pytest.mark.parametrize("field,value", [("admission_number", True), ("admitted_ns", 2000.0)])
def test_recovery_backend_refuses_type_coerced_ticket_without_accepting(recovery, field, value):
    run = ready(recovery)
    ticket = run.reserve_probe(name="positive", nonce="2" * 32)
    with pytest.raises(ValueError):
        run.admit_probe(dataclasses.replace(ticket, **{field: value}))
    snapshot = run.snapshot()
    assert snapshot.charged == 1 and snapshot.backend_confirmed == 0
    assert run.recovery_accounting(snapshot)["cumulative_charged"] == 2


def test_partial_consumption_is_retained_and_cannot_be_retried(recovery, monkeypatch):
    original = ec2.write_exclusive

    def partial(path, raw):
        if path == recovery.consumption:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, raw[:8])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            raise OSError("injected partial consumption")
        original(path, raw)

    monkeypatch.setattr(ec2, "write_exclusive", partial)
    with pytest.raises(OSError, match="partial"):
        recovery.claim()
    assert recovery.consumption.stat().st_size == 8 and not recovery.new_dir.exists()
    monkeypatch.setattr(ec2, "write_exclusive", original)
    with pytest.raises(FileExistsError):
        recovery.claim()
    assert all(path.read_bytes() == raw for path, raw in recovery.old_bytes.items())


def test_parent_fsync_failure_after_consumption_retains_the_used_allowance(recovery, monkeypatch):
    original = ec2._fsync_dir

    def failed(path):
        if path == recovery.host.root and recovery.consumption.exists():
            raise OSError("injected consumption parent fsync")
        original(path)

    monkeypatch.setattr(ec2, "_fsync_dir", failed)
    with pytest.raises(OSError, match="fsync"):
        recovery.claim()
    assert recovery.consumption.exists() and not recovery.new_dir.exists()
    monkeypatch.setattr(ec2, "_fsync_dir", original)
    with pytest.raises(FileExistsError):
        recovery.claim()


def test_run_creation_failure_does_not_erase_consumption(recovery, monkeypatch):
    original = Path.mkdir

    def failed(path, *args, **kwargs):
        if path == recovery.new_dir:
            raise OSError("injected successor directory failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", failed)
    with pytest.raises(OSError, match="successor"):
        recovery.claim()
    assert recovery.consumption.exists() and not recovery.new_dir.exists()
    monkeypatch.setattr(Path, "mkdir", original)
    with pytest.raises(FileExistsError):
        recovery.claim()


def test_submitted_uncertainty_is_not_refunded_or_reported_as_cumulative_one(recovery, monkeypatch):
    run = ready(recovery)

    def failed_replace(*args):
        raise OSError("injected successor state uncertainty")

    monkeypatch.setattr(ec2.os, "replace", failed_replace)
    with pytest.raises(OSError, match="uncertainty"):
        run.reserve_probe(name="positive", nonce="3" * 32)
    assert run._state["charged"] == 1
    with pytest.raises(ValueError, match="fenced"):
        run.snapshot()
    assert recovery.consumption.exists()


def test_changed_object_clock_type_cannot_reassign_the_original_anchor(recovery):
    run = recovery.claim()
    run.started_ns = float(run.started_ns)
    with pytest.raises(ValueError, match="live original recovery"):
        run.snapshot()


def complete_catalog(recovery):
    """Synthetic fixed outcomes test publication binding, not native controls."""
    run = ready(recovery)
    initial = run.snapshot()
    manifest = {
        "kind": "restricted_reference_ec2_recovery_manifest_v1",
        "schema_version": 1,
        "source_revision": CURRENT,
        "provider_context": run.provider_record,
        "recovery_context": run.recovery_context,
        "production_m1_enabled": False,
        "available_for_probe": True,
        "fixed_cases": list(ec2.FIXED_PROBES),
        "qualification_started_ns": run.started_ns,
        "qualification_deadline_ns": run.deadline_ns,
        "recovery_accounting_phase": "pre_probe_manifest",
        "recovery_accounting": run.recovery_accounting(initial),
        "unavailable_reasons": [],
        "os_release": None,
        "kernel": None,
        "architecture": None,
        "python_version": None,
        "libc_version": None,
        "runner_image_os": None,
        "runner_image_version": None,
        "controller_uid": None,
        "controller_gid": None,
        "reserved_uid_gid": None,
        "binaries": None,
        "host_mountinfo": None,
        "host_namespaces": None,
        "controllers": None,
        "apparmor": None,
        "explicit_userns_authorization": None,
        "bwrap_actual_version": None,
        "bwrap_package_version": None,
        "parent_subtree_control": None,
        "controller_limits": None,
        "syscall_mapping": None,
        "bpf_sha256": None,
        "bpf_hex": None,
        "guest_environment": None,
        "mount_plan": None,
        "bwrap_argv_template": None,
        "limits": None,
        "runtime_closure_scope": "Synthetic publication decisions, not isolation evidence",
    }
    run.artifact_dir.mkdir()
    manifest_raw = ec2.canonical(manifest)
    (run.artifact_dir / "manifest.json").write_bytes(manifest_raw)
    manifest_sha = ec2._sha(manifest_raw)
    cases = []
    for index, name in enumerate(ec2.FIXED_PROBES):
        ticket = run.reserve_probe(name=name, nonce=f"{index + 1:032x}")
        run.admit_probe(ticket)
        result = {
            "name": name,
            "nonce": ticket.nonce,
            "payload_started": True,
            "failure": None,
            "stop_confirmed": True,
            "cleanup_confirmed": True,
            "host_facts": {
                "manifest_sha256": manifest_sha,
                "admission_number": index + 1,
                "original_admission_ns": ticket.admitted_ns,
                "original_deadline_ns": ticket.deadline_ns,
            },
        }
        path = run.run_dir / f"case-{index + 1:02d}.json"
        raw = ec2.canonical(result)
        path.write_bytes(raw)
        run.finish_probe(
            ticket,
            result_sha256=ec2._sha(raw),
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
                "execution_evidence": {
                    "path": str(path),
                    "sha256": ec2._sha(raw),
                    "bytes": len(raw),
                },
            }
        )
    snapshot = run.snapshot()
    report = {
        "kind": "restricted_reference_ec2_recovery_qualification_v1",
        "schema_version": 1,
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
        "scope": "Owner-trusted fixed EC2 synthetic controls; product M1 remains DISABLED",
        "stop_scope": "Lifecycle service requests Stop; independent AWS state readback required",
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
        "manifest_sha256": manifest_sha,
        "completed_at_monotonic_ns": recovery.host.clock[0],
        "observed_payload_starts": 24,
    }
    return run, report


def publish_report(run, report):
    raw = ec2.canonical(report)
    (run.run_dir / "qualification-report.json").write_bytes(raw)
    return ec2._sha(raw)


def test_full_current_catalog_binds_cumulative_twenty_five_and_terminal_receipt(recovery):
    run, report = complete_catalog(recovery)
    digest = publish_report(run, report)
    run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    receipt = run.qualification_receipt()
    assert receipt["kind"] == "restricted_reference_ec2_recovery_terminal_receipt_v1"
    assert receipt["final_report_sha256"] == digest
    assert receipt["recovery_accounting"]["cumulative_charged"] == 25
    assert receipt["recovery_accounting"]["current_charged"] == 24
    assert receipt["recovery_accounting"]["prior_charged"] == 1
    assert receipt["recovery_context"] == run.recovery_context
    assert all(path.read_bytes() == raw for path, raw in recovery.old_bytes.items())
    with pytest.raises(ValueError):
        run.reserve_probe(name="positive", nonce="f" * 32)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_report",
        "old_kind",
        "boolean_history",
        "float_history",
        "omitted_history",
        "mixed_ticket",
        "old_case_path",
        "unknown_case",
        "missing_gate",
        "wrong_context",
    ],
)
def test_success_cannot_drop_history_or_mix_predecessor_cases(recovery, change):
    run, report = complete_catalog(recovery)
    if change == "unknown_report":
        report["authority_override"] = True
    elif change == "old_kind":
        report["kind"] = "restricted_reference_ec2_qualification_v1"
    elif change in {"boolean_history", "float_history"}:
        report["recovery_accounting"]["prior_charged"] = (
            True if change == "boolean_history" else 1.0
        )
    elif change == "omitted_history":
        report["recovery_accounting"]["cumulative_charged"] = 24
    elif change == "mixed_ticket":
        report["cases"][0]["admission"]["source_revision"] = REVISION
    elif change == "old_case_path":
        report["cases"][0]["execution_evidence"]["path"] = str(recovery.paths["case_sha256"])
    elif change == "unknown_case":
        report["cases"][0]["free_retry"] = True
    elif change == "missing_gate":
        report["cases"][0]["payload_started"] = False
    else:
        report["recovery_context"]["invocation"]["boot_id"] = BOOT
    digest = publish_report(run, report)
    with pytest.raises(ValueError):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    assert run._state["final_report_sha256"] is None
    assert recovery.consumption.exists() and run.snapshot().charged == 24


def test_changed_actual_case_bytes_fail_even_when_report_hash_is_recomputed(recovery):
    run, report = complete_catalog(recovery)
    path = run.run_dir / "case-01.json"
    result = json.loads(path.read_bytes())
    result["host_facts"]["manifest_sha256"] = "f" * 64
    raw = ec2.canonical(result)
    path.write_bytes(raw)
    report["cases"][0]["execution_evidence"] = {
        "path": str(path),
        "sha256": ec2._sha(raw),
        "bytes": len(raw),
    }
    digest = publish_report(run, report)
    with pytest.raises(ValueError, match="durable current recovery outcome"):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    assert recovery.consumption.exists()


@pytest.mark.parametrize("change", ["unknown", "missing"])
def test_final_manifest_shape_refuses_even_with_all_observation_hashes_rebound(recovery, change):
    run, report = complete_catalog(recovery)
    manifest_path = run.artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if change == "unknown":
        manifest["unknown_manifest_authority"] = True
    else:
        del manifest["os_release"]
    manifest_raw = ec2.canonical(manifest)
    manifest_path.write_bytes(manifest_raw)
    report["manifest_sha256"] = ec2._sha(manifest_raw)
    for index, case in enumerate(report["cases"]):
        path = run.run_dir / f"case-{index + 1:02d}.json"
        result = json.loads(path.read_bytes())
        result["host_facts"]["manifest_sha256"] = report["manifest_sha256"]
        raw = ec2.canonical(result)
        path.write_bytes(raw)
        case["execution_evidence"] = {
            "path": str(path),
            "sha256": ec2._sha(raw),
            "bytes": len(raw),
        }
        # Rebind the synthetic durable fixture as well: rejection must be the
        # manifest's exact shape, not a stale raw-case/outcome/report digest.
        run._state["admissions"][index]["outcome"]["result_sha256"] = ec2._sha(raw)
    run._persist()
    digest = publish_report(run, report)
    assert ec2._sha(manifest_path.read_bytes()) == report["manifest_sha256"]
    for index, case in enumerate(report["cases"]):
        path = run.run_dir / f"case-{index + 1:02d}.json"
        actual = ec2._sha(path.read_bytes())
        assert actual == case["execution_evidence"]["sha256"]
        assert actual == run._state["admissions"][index]["outcome"]["result_sha256"]
    consumed = recovery.consumption.read_bytes()
    with pytest.raises(ValueError, match="recovery manifest fields"):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=digest)
    assert run._state["final_report_sha256"] is None
    assert run.recovery_accounting(run.snapshot())["cumulative_charged"] == 25
    assert recovery.consumption.read_bytes() == consumed
