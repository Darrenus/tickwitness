#!/usr/bin/env python3
"""Run the one frozen dedicated-EC2 reference qualification, never a research task."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import secrets
import signal
import sys
import time
from pathlib import Path
from types import ModuleType

# -I removes the script directory. Only this root-provisioned checkout supplies imports.
_SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SOURCE / "src"))
from tickwitness.infrastructure.restricted_reference import (  # noqa: E402
    PROBE_NAMES,
    ReferenceRunner,
)
from tickwitness.infrastructure.restricted_reference_ec2 import (  # noqa: E402
    FIXED_PROBES,
    MAX_ADMISSIONS,
    RECOVERY_PLAN_ID,
    RECOVERY_V2_PLAN_ID,
    WINDOW_NS,
    Ec2Run,
    canonical,
    validate_recovery_manifest_shape,
)

type Row = dict[str, object]


def _script(name: str) -> ModuleType:
    path = _SOURCE / "scripts" / name
    spec = importlib.util.spec_from_file_location("_tickwitness_ec2_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise ValueError("Missing fixed trusted qualification helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, document: Row, *, first: bool = False, limit: int = 262144) -> str:
    raw = canonical(document)
    if len(raw) > limit:
        raise ValueError("Qualification evidence exceeds its fixed byte bound")
    target = path if first else path.with_name(path.name + ".next-" + secrets.token_hex(16))
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if not first:
        os.replace(target, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(raw).hexdigest()


def _recovery_kind(role: str, version: int) -> str:
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Unsupported fixed recovery schema")
    return f"restricted_reference_ec2_recovery_{role}_v{version}"


def _recovery_version(run: Ec2Run) -> int | None:
    context = run.recovery_context
    version = run.recovery_schema_version
    if version is None:
        if context is not None:
            raise ValueError("Default authority cannot carry recovery context")
        return None
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Recovery authority has an unsupported schema version")
    selected = 1 if version == 1 else 2
    if (
        not isinstance(context, dict)
        or context.get("kind") != _recovery_kind("context", selected)
        or type(context.get("schema_version")) is not int
        or context.get("schema_version") != selected
        or context.get("plan_id") != (RECOVERY_PLAN_ID if selected == 1 else RECOVERY_V2_PLAN_ID)
    ):
        raise ValueError("Recovery authority differs from its verified schema context")
    return selected


def _report_recovery_version(report: Row) -> int | None:
    if type(report.get("schema_version")) is not int:
        raise ValueError("Qualification report has an invalid schema version")
    if (
        report.get("kind") == "restricted_reference_ec2_qualification_v1"
        and report["schema_version"] == 1
    ):
        return None
    for version in (1, 2):
        if (
            report.get("kind") == _recovery_kind("qualification", version)
            and report["schema_version"] == version
        ):
            return version
    raise ValueError("Qualification report has an unsupported recovery schema")


def _budget(run: Ec2Run, report: Row) -> None:
    try:
        snapshot = run.snapshot()
        accounting = run.recovery_accounting(snapshot)
        version = _recovery_version(run)
        if version != _report_recovery_version(report):
            raise ValueError("Qualification report differs from its actual recovery version")
        if version is not None:
            if (
                accounting is None
                or accounting.get("kind") != _recovery_kind("budget", version)
                or type(accounting.get("schema_version")) is not int
                or accounting.get("schema_version") != version
                or accounting.get("plan_id")
                != (RECOVERY_PLAN_ID if version == 1 else RECOVERY_V2_PLAN_ID)
                or canonical(run.recovery_context) != canonical(report.get("recovery_context"))
            ):
                raise ValueError("Recovery counters lack their established immutable context")
            if version == 2 and canonical(accounting) != canonical(
                {
                    "kind": _recovery_kind("budget", 2),
                    "schema_version": 2,
                    "plan_id": RECOVERY_V2_PLAN_ID,
                    "historical_run_ids": [
                        "ec201aab11254e8bb7cd1573a96a0001",
                        "ec201aab11254e8bb7cd1573a96a0002",
                    ],
                    "prior_charged": 2,
                    "prior_backend_confirmed": 2,
                    "current_charged": snapshot.charged,
                    "current_backend_confirmed": snapshot.backend_confirmed,
                    "current_unconfirmed": snapshot.unconfirmed,
                    "current_pending_outcomes": snapshot.pending_outcomes,
                    "cumulative_charged": 2 + snapshot.charged,
                    "cumulative_backend_confirmed": 2 + snapshot.backend_confirmed,
                    "max_current_admissions": 24,
                    "max_cumulative_admissions": 26,
                }
            ):
                raise ValueError("Recovery v2 counters differ from the fixed two-run history")
        elif accounting is not None:
            raise ValueError("Default qualification cannot acquire recovery accounting")
    except Exception:
        previous = report.pop("durable_budget", None)
        if previous is not None:
            report["last_confirmed_budget_lower_bound"] = previous
        previous_recovery = report.pop("recovery_accounting", None)
        if previous_recovery is not None:
            report["last_confirmed_recovery_accounting_lower_bound"] = previous_recovery
        report["durable_budget_status"] = "UNKNOWN"
        report["budget_uncertainty_scope"] = (
            "Last confirmed counters are a lower bound, not authoritative current zero; "
            "an uncertain submitted slot is retained and never refunded or retried."
        )
        for key in (
            "admissions_charged",
            "confirmed_backend_admissions",
            "backend_unconfirmed_admissions",
            "pending_probe_outcomes",
        ):
            report.pop(key, None)
        raise
    report["durable_budget_status"] = "CONFIRMED"
    report["durable_budget"] = dataclasses.asdict(snapshot)
    report["admissions_charged"] = snapshot.charged
    report["confirmed_backend_admissions"] = snapshot.backend_confirmed
    report["backend_unconfirmed_admissions"] = snapshot.unconfirmed
    report["pending_probe_outcomes"] = snapshot.pending_outcomes
    if accounting is not None:
        report["recovery_accounting"] = accounting
    report["admission_accounting_scope"] = (
        "Submitted slots are charged before backend calls; backend ACK and pending outcome "
        "are separate durable counts. Failed or unknown slots are never refunded."
    )


def _cancel(_number: int, _frame: object) -> None:
    raise InterruptedError("qualification_controller_cancelled")


def _recovery_manifest(run: Ec2Run, manifest: Row) -> None:
    version = _recovery_version(run)
    if version is None:
        raise ValueError("Recovery manifest requires an actual recovery authority")
    manifest = validate_recovery_manifest_shape(manifest, version=version)
    context = run.recovery_context
    snapshot = run.snapshot()
    accounting = run.recovery_accounting(snapshot)
    if (
        context is None
        or accounting is None
        or snapshot.charged != 0
        or snapshot.backend_confirmed != 0
        or snapshot.pending_outcomes != 0
        or snapshot.unconfirmed != 0
        or snapshot.poisoned
        or manifest.get("kind") != _recovery_kind("manifest", version)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != version
        or manifest.get("source_revision") != run.source_revision
        or manifest.get("production_m1_enabled") is not False
        or type(manifest.get("qualification_started_ns")) is not int
        or manifest.get("qualification_started_ns") != run.started_ns
        or type(manifest.get("qualification_deadline_ns")) is not int
        or manifest.get("qualification_deadline_ns") != run.deadline_ns
        or canonical(manifest.get("provider_context")) != canonical(run.provider_record)
        or canonical(manifest.get("recovery_context")) != canonical(context)
        or manifest.get("recovery_accounting_phase") != "pre_probe_manifest"
        or canonical(manifest.get("recovery_accounting")) != canonical(accounting)
    ):
        raise ValueError("Recovery manifest lacks its bound pre-probe lineage and accounting")


def _recovery_receipt(run: Ec2Run, report: Row, receipt: Row, digest: str) -> None:
    version = _recovery_version(run)
    if version is None or version != _report_recovery_version(report):
        raise ValueError("Recovery receipt requires its actual report schema authority")
    expected = {
        "kind": _recovery_kind("terminal_receipt", version),
        "schema_version": version,
        "run_id": run.run_id,
        "source_revision": run.source_revision,
        "boot_id": run.boot_id,
        "final_report_sha256": digest,
        "controls_status": "QUALIFIED_REFERENCE_ONLY",
        "production_m1": "DISABLED",
        "recovery_context": report["recovery_context"],
        "recovery_accounting": report["recovery_accounting"],
    }
    if canonical(receipt) != canonical(expected):
        raise ValueError("Recovery terminal receipt differs from the bound complete report")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--recovery-plan", choices=(RECOVERY_PLAN_ID, RECOVERY_V2_PLAN_ID))
    args = parser.parse_args(arguments)
    if args.recovery_plan is None:
        selected_version = None
    elif args.recovery_plan == RECOVERY_PLAN_ID:
        selected_version = 1
    elif args.recovery_plan == RECOVERY_V2_PLAN_ID:
        selected_version = 2
    else:
        parser.error("Unsupported fixed recovery selection")
    run: Ec2Run | None = None
    cases: list[Row] = []
    report: Row = {
        "kind": (
            "restricted_reference_ec2_qualification_v1"
            if selected_version is None
            else _recovery_kind("qualification", selected_version)
        ),
        "schema_version": 1 if selected_version is None else selected_version,
        "controls_status": "NOT_QUALIFIED",
        "production_m1": "DISABLED",
        "independent_human_security_review": "NOT_PERFORMED",
        "external_human_reproduction": "0/0/PENDING",
        "research_reservations": 0,
        "replay_engine_invocations": 0,
        "source_revision": args.source_revision,
        "run_id": args.run_id,
        "acceptance_gate": "matching_durable_terminal_and_final_report_sha256",
        "original_qualification_budget": {
            "max_admissions": MAX_ADMISSIONS,
            "window_ns": WINDOW_NS,
        },
        "cases": cases,
        "scope": "Owner-trusted fixed EC2 synthetic controls; product M1 remains DISABLED",
        "stop_scope": "Lifecycle service requests Stop; independent AWS state readback required",
    }
    previous_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _cancel)
    terminal = False
    report_created = False
    try:
        # Either factory captures this invocation's anchors before any setup;
        # recovery also retains the separately charged predecessor in its context.
        if selected_version is None:
            run = Ec2Run.claim(source_revision=args.source_revision, run_id=args.run_id)
        elif selected_version == 1:
            run = Ec2Run.claim_recovery(
                source_revision=args.source_revision,
                run_id=args.run_id,
                plan_id=args.recovery_plan,
            )
        else:
            run = Ec2Run.claim_recovery_v2(
                source_revision=args.source_revision,
                run_id=args.run_id,
                plan_id=args.recovery_plan,
            )
        if selected_version is not None:
            context = run.recovery_context
            if context is None or _recovery_version(run) != selected_version:
                raise ValueError("Recovery factory returned no matching established lineage")
            report["recovery_context"] = context
        report["boot_id"] = run.boot_id
        report_path = run.run_dir / "qualification-report.json"
        _budget(run, report)
        _write(report_path, report, first=True)
        report_created = True
        if PROBE_NAMES != FIXED_PROBES or len(PROBE_NAMES) != MAX_ADMISSIONS:
            raise ValueError("Frozen closed synthetic catalog differs")
        loader = _script("prepare_reference_policy_ec2.py")
        assessment_module = _script("qualify_restricted_reference.py")
        loader.prepare_policy(ec2_run=run)
        report["provider_context"] = run.provider_record
        runner = ReferenceRunner(
            run.artifact_dir,
            _SOURCE / "scripts" / "restricted_reference_payload.py",
            ec2_run=run,
        )
        if runner.manifest.get("fixed_cases") != list(PROBE_NAMES):
            raise ValueError("Frozen manifest catalog differs")
        if args.recovery_plan is not None:
            _recovery_manifest(run, runner.manifest)
        report["manifest_sha256"] = runner.manifest_sha256
        stopped = False
        for name in PROBE_NAMES:
            if stopped or time.monotonic_ns() >= run.deadline_ns:
                cases.append(
                    {
                        "name": name,
                        "admission_submitted": False,
                        "status": "UNKNOWN",
                        "reason": "not_admitted_after_original_window_or_uncertainty",
                    }
                )
                continue
            nonce = secrets.token_hex(16)
            # fsync the submitted charge before entering a backend that might fail to return.
            admission = run.reserve_probe(name=name, nonce=nonce)
            case: Row = {
                "name": name,
                "nonce": nonce,
                "admission_submitted": True,
                "admission": dataclasses.asdict(admission),
                "status": "UNKNOWN",
                "reason": "execution_outcome_unavailable",
            }
            cases.append(case)
            _budget(run, report)
            _write(report_path, report)
            result = runner.run_probe(name, arguments=(nonce,), ec2_admission=admission)
            result_path = run.run_dir / f"case-{admission.admission_number:02d}.json"
            result_hash = _write(result_path, result, first=True, limit=2_097_152)
            assessment = assessment_module.assess_probe(result, name, nonce, runner.manifest_sha256)
            case.update(
                {
                    **assessment,
                    "execution_evidence": {
                        "path": str(result_path),
                        "sha256": result_hash,
                        "bytes": result_path.stat().st_size,
                    },
                    "payload_started": result.get("payload_started") is True,
                }
            )
            _budget(run, report)
            _write(report_path, report)
            stopped = assessment["status"] != "PASS"
        all_passed = len(cases) == MAX_ADMISSIONS and all(
            case["status"] == "PASS" for case in cases
        )
        outcome = "QUALIFIED_REFERENCE_ONLY" if all_passed else "NOT_QUALIFIED"
        report["controls_status"] = outcome
        report["completed_at_monotonic_ns"] = time.monotonic_ns()
        report["observed_payload_starts"] = sum(
            case.get("payload_started") is True for case in cases
        )
        _budget(run, report)
        final_report_hash = _write(report_path, report)
        run.finish(
            outcome=outcome,
            reason=None if all_passed else "fixed_catalog_incomplete",
            final_report_sha256=final_report_hash if all_passed else None,
        )
        terminal = True
        receipt = run.qualification_receipt() if all_passed else None
        if args.recovery_plan is not None and all_passed:
            if receipt is None:
                raise ValueError("Successful recovery has no matching terminal receipt")
            _recovery_receipt(run, report, receipt, final_report_hash)
        summary: Row = {
            "controls_status": outcome,
            "production_m1": "DISABLED",
            "admissions_charged": report["admissions_charged"],
            "manifest_sha256": runner.manifest_sha256,
            "run_id": run.run_id,
            "boot_id": run.boot_id,
            "terminal_receipt": receipt,
        }
        if args.recovery_plan is not None:
            summary.update(
                recovery_context=report["recovery_context"],
                recovery_accounting=report["recovery_accounting"],
            )
        sys.stdout.write(json.dumps(summary) + "\n")
        return 0 if all_passed else 1
    except BaseException as error:
        report["controls_status"] = "NOT_QUALIFIED"
        report["failure"] = {"type": type(error).__name__, "reason": str(error)[:2048]}
        represented = {case["name"] for case in cases}
        for name in PROBE_NAMES:
            if name not in represented:
                cases.append(
                    {
                        "name": name,
                        "admission_submitted": False,
                        "status": "UNKNOWN",
                        "reason": "not_admitted_after_harness_failure",
                    }
                )
        if run is not None:
            if not terminal:
                try:
                    run.finish(outcome="NOT_QUALIFIED", reason=type(error).__name__)
                    terminal = True
                except Exception as finish_error:
                    report["durable_finalization"] = {
                        "status": "UNKNOWN",
                        "type": type(finish_error).__name__,
                    }
            try:
                _budget(run, report)
            except Exception as accounting_error:
                report["accounting_failure"] = {"type": type(accounting_error).__name__}
            try:
                _write(
                    run.run_dir / "qualification-report.json",
                    report,
                    first=not report_created,
                )
            except Exception as publication_error:
                sys.stderr.write(
                    "qualification_evidence_uncertain: " + type(publication_error).__name__ + "\n"
                )
        sys.stderr.write("restricted_reference_ec2_not_qualified: " + type(error).__name__ + "\n")
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
