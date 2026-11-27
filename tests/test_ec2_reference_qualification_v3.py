"""The real v3 driver and durable authority share one synthetic trusted filesystem.

Only host observations, policy preparation and probe execution are substituted;
the actual factories, tickets, outcome accounting and report/receipt checks run.
No fixture result qualifies a host or executes a research engine.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

sys.path.insert(0, str(Path(__file__).parent / "infrastructure"))
from test_restricted_reference_ec2_recovery_v3 import (
    CURRENT,
    assert_preserved,
    manifest_for,
    prepare_policy,
    raw_result,
    record,
)
from test_restricted_reference_ec2_recovery_v3 import base_host as base_host
from test_restricted_reference_ec2_recovery_v3 import host as host
from test_restricted_reference_ec2_recovery_v3 import recovery as recovery
from test_restricted_reference_ec2_recovery_v3 import v2 as v2
from test_restricted_reference_ec2_recovery_v3 import v2_history as v2_history
from test_restricted_reference_ec2_recovery_v3 import v3 as v3
from test_restricted_reference_ec2_recovery_v3 import v3_history as v3_history

SCRIPT = Path(__file__).parents[1] / "scripts" / "qualify_restricted_reference_ec2.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_ec2_qualification_v3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


def invoke():
    return qualification.main(
        [
            "--source-revision",
            CURRENT,
            "--run-id",
            ec2.RECOVERY_V3_RUN_ID,
            "--recovery-plan",
            ec2.RECOVERY_V3_PLAN_ID,
        ]
    )


@pytest.fixture
def driver(v3, monkeypatch):
    fault = SimpleNamespace(
        mode="pass",
        version=3,
        context_changes={},
        accounting_changes={},
        manifest_changes={},
        manifest_removals=set(),
        receipt_changes={},
    )
    events, runs = [], []
    claim = ec2.Ec2Run.claim_recovery_v3
    original_budget = qualification._budget

    def forbidden(**_arguments):
        pytest.fail("An explicit v3 selection reached a default/v1/v2 factory")

    def selected(**arguments):
        events.append("factory")
        if fault.mode == "claim_refused":
            raise ValueError("Synthetic pre-consumption refusal")
        run = claim(**arguments)
        v3.runs.append(run)
        runs.append(run)
        if fault.mode == "factory_ack_lost":
            raise OSError("Factory reply unavailable after durable consumption")
        if type(fault.version) is not int or fault.version != 3:
            monkeypatch.setattr(
                ec2.Ec2Run, "recovery_schema_version", property(lambda _run: fault.version)
            )
        if fault.context_changes:
            context = run.recovery_context | copy.deepcopy(fault.context_changes)
            monkeypatch.setattr(ec2.Ec2Run, "recovery_context", property(lambda _run: context))
        accounting = run.recovery_accounting

        def changed_accounting(snapshot):
            return accounting(snapshot) | copy.deepcopy(fault.accounting_changes)

        run.recovery_accounting = changed_accounting
        reserve, snapshot, finish, receipt = (
            run.reserve_probe,
            run.snapshot,
            run.finish,
            run.qualification_receipt,
        )

        def reserve_probe(**request):
            events.append("reserve")
            ticket = reserve(**request)
            if fault.mode in {"reserve_unknown", "snapshot_unknown"}:
                raise OSError("Submitted original ticket reply is unknown")
            return ticket

        def observed_snapshot():
            if fault.mode == "snapshot_unknown" and run._state["charged"]:
                raise OSError("Current durable budget observation is unavailable")
            return snapshot()

        def finish_run(**request):
            events.append(("finish", request["outcome"]))
            if fault.mode == "raw_case_changed":
                (run.run_dir / "case-01.json").write_bytes(b"changed raw case\n")
            finish(**request)
            if fault.mode == "terminal_ack_lost":
                raise OSError("Terminal committed; its acknowledgement is unknown")

        def read_receipt():
            events.append("receipt")
            result = receipt()
            if fault.mode == "receipt_unknown":
                raise OSError("Independent receipt reply unavailable")
            return result | copy.deepcopy(fault.receipt_changes)

        run.reserve_probe = reserve_probe
        run.snapshot = observed_snapshot
        run.finish = finish_run
        run.qualification_receipt = read_receipt
        return run

    def budget(run, report):
        events.append("budget")
        original_budget(run, report)

    def policy(*, ec2_run):
        events.append("policy")
        if fault.mode == "policy_refused":
            raise ValueError("Synthetic policy observation refused")
        prepare_policy(ec2_run)

    class Runner:
        def __init__(self, artifact_dir, payload, *, ec2_run):
            events.append("runner")
            assert payload.name == "restricted_reference_payload.py"
            self.run = ec2_run
            self.run.acquire_runner()
            artifact_dir.mkdir()
            self.manifest = manifest_for(self.run)
            self.manifest.update(copy.deepcopy(fault.manifest_changes))
            for key in fault.manifest_removals:
                del self.manifest[key]
            path = artifact_dir / "manifest.json"
            path.write_bytes(ec2.canonical(self.manifest))
            self.manifest_sha256 = record(path)["sha256"]

        def run_probe(self, name, *, arguments, ec2_admission):
            events.append(("backend", name))
            assert arguments == (ec2_admission.nonce,)
            submitted = json.loads((self.run.run_dir / "qualification-report.json").read_bytes())
            assert submitted["admissions_charged"] == ec2_admission.admission_number
            assert submitted["recovery_accounting"]["cumulative_charged"] == (
                21 + ec2_admission.admission_number
            )
            self.run.admit_probe(ec2_admission)
            if fault.mode == "backend_ack_lost":
                raise OSError("Backend accepted; outcome reply unavailable")
            v3.host.clock[0] += 1
            result = raw_result(self.run, ec2_admission, self.manifest_sha256)
            self.run.finish_probe(
                ec2_admission,
                result_sha256=ec2._sha(ec2.canonical(result)),
                stop_confirmed=True,
                cleanup_confirmed=True,
                failure=None,
            )
            return result

    def assess(result, name, nonce, manifest):
        assert (result["name"], result["nonce"]) == (name, nonce)
        assert result["host_facts"]["manifest_sha256"] == manifest
        return {
            "status": "UNKNOWN" if fault.mode == "unknown_case" else "PASS",
            "reason": "synthetic execution decision; never host isolation evidence",
        }

    monkeypatch.setattr(
        qualification,
        "Ec2Run",
        SimpleNamespace(
            claim=forbidden,
            claim_recovery=forbidden,
            claim_recovery_v2=forbidden,
            claim_recovery_v3=selected,
        ),
    )
    monkeypatch.setattr(qualification, "ReferenceRunner", Runner)
    monkeypatch.setattr(qualification, "_budget", budget)
    monkeypatch.setattr(
        qualification,
        "_script",
        lambda name: (
            SimpleNamespace(prepare_policy=policy)
            if name == "prepare_reference_policy_ec2.py"
            else SimpleNamespace(assess_probe=assess)
        ),
    )
    return SimpleNamespace(case=v3, fault=fault, runs=runs, events=events, path=v3.new_dir)


def document(driver):
    return json.loads((driver.path / "qualification-report.json").read_bytes())


def state(driver):
    return json.loads((driver.path / "state.json").read_bytes())


def test_real_driver_binds_new_cases_and_terminal_receipt_to_forty_five(driver, capsys):
    assert invoke() == 0
    report = document(driver)
    durable = state(driver)
    summary = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == 3 and report["recovery_accounting"]["prior_charged"] == 21
    assert report["recovery_accounting"]["cumulative_charged"] == 45
    assert len(report["cases"]) == len(durable["admissions"]) == 24
    assert len(list(driver.path.glob("case-*.json"))) == 24
    assert len({row["nonce"] for row in durable["admissions"]}) == 24
    report_hash = record(driver.path / "qualification-report.json")["sha256"]
    assert durable["final_report_sha256"] == report_hash
    assert summary["terminal_receipt"]["final_report_sha256"] == durable["final_report_sha256"]
    assert summary["recovery_accounting"] == report["recovery_accounting"]
    assert report["research_reservations"] == report["replay_engine_invocations"] == 0
    initial = json.loads((driver.path / "qualification/manifest.json").read_bytes())
    assert initial["recovery_accounting"]["current_charged"] == 0
    assert initial["recovery_accounting"]["cumulative_charged"] == 21
    assert_preserved(driver.case)


@pytest.mark.parametrize("mode", ["claim_refused", "factory_ack_lost"])
def test_factory_refusal_has_no_fallback_or_invented_zero_budget(driver, capsys, mode):
    driver.fault.mode = mode
    assert invoke() == 1
    assert driver.events == ["factory"]
    assert not (driver.path / "qualification-report.json").exists()
    assert driver.case.consumption.exists() == (mode == "factory_ack_lost")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("version", [None, 1, 2, True, 3.0, 4])
def test_driver_requires_exact_new_version_not_just_nonempty_context(driver, version):
    driver.fault.version = version
    assert invoke() == 1
    assert document(driver)["durable_budget_status"] == "UNKNOWN"
    assert "recovery_accounting" not in document(driver)
    assert "policy" not in driver.events and "reserve" not in driver.events


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "restricted_reference_ec2_recovery_context_v2"},
        {"schema_version": True},
        {"plan_id": ec2.RECOVERY_V2_PLAN_ID},
    ],
)
def test_new_selection_cannot_acquire_older_or_ambiguous_context_authority(driver, change):
    driver.fault.context_changes.update(change)
    assert invoke() == 1
    assert "admissions_charged" not in document(driver)
    assert "policy" not in driver.events and "reserve" not in driver.events


@pytest.mark.parametrize(
    "change",
    [
        {"prior_charged": 3},
        {"prior_backend_confirmed": 21.0},
        {"current_unconfirmed": False},
        {"max_cumulative_admissions": 27},
        {"historical_run_ids": ["old"]},
        {"unknown": True},
    ],
)
def test_complete_budget_shape_cannot_confuse_schema_three_with_history_twenty_one(driver, change):
    driver.fault.accounting_changes.update(change)
    assert invoke() == 1
    assert document(driver)["durable_budget_status"] == "UNKNOWN"
    assert "admissions_charged" not in document(driver)
    assert "policy" not in driver.events and "reserve" not in driver.events


@pytest.mark.parametrize(
    "changes,removed",
    [
        ({"schema_version": 2}, None),
        ({"schema_version": True}, None),
        ({"recovery_accounting_phase": "terminal"}, None),
        ({"fixture_scope": "unknown field"}, None),
        ({}, "os_release"),
    ],
)
def test_strict_manifest_refusal_precedes_any_new_admission(driver, changes, removed):
    driver.fault.manifest_changes.update(changes)
    if removed is not None:
        driver.fault.manifest_removals.add(removed)
    assert invoke() == 1
    assert state(driver)["charged"] == 0
    assert document(driver)["recovery_accounting"]["cumulative_charged"] == 21
    assert "reserve" not in driver.events


@pytest.mark.parametrize("mode", ["reserve_unknown", "backend_ack_lost", "unknown_case"])
def test_failed_or_unknown_first_case_retains_twenty_one_history_and_its_new_charge(driver, mode):
    driver.fault.mode = mode
    assert invoke() == 1
    assert state(driver)["charged"] == 1
    assert document(driver)["recovery_accounting"]["cumulative_charged"] == 22
    assert all(case["admission_submitted"] is False for case in document(driver)["cases"][1:])
    assert len([event for event in driver.events if event == "reserve"]) == 1


def test_snapshot_uncertainty_preserves_explicit_lower_bounds_never_current_zero(driver):
    driver.fault.mode = "snapshot_unknown"
    assert invoke() == 1
    report = document(driver)
    assert state(driver)["charged"] == 1
    assert report["durable_budget_status"] == "UNKNOWN" and "durable_budget" not in report
    assert "recovery_accounting" not in report and "admissions_charged" not in report
    assert report["last_confirmed_recovery_accounting_lower_bound"]["cumulative_charged"] == 21


def test_policy_refusal_preserves_all_history_without_starting_a_probe(driver):
    driver.fault.mode = "policy_refused"
    assert invoke() == 1
    assert document(driver)["recovery_accounting"]["cumulative_charged"] == 21
    assert state(driver)["charged"] == 0
    assert "runner" not in driver.events and "reserve" not in driver.events


def test_finish_validation_failure_cannot_rewrite_a_possibly_submitted_report(driver, capsys):
    driver.fault.mode = "raw_case_changed"
    assert invoke() == 1
    assert document(driver)["controls_status"] == "QUALIFIED_REFERENCE_ONLY"
    assert state(driver)["phase"] != "TERMINAL"
    assert state(driver)["final_report_sha256"] is None
    assert state(driver)["charged"] == 24
    assert "receipt" not in driver.events
    finishes = [
        event for event in driver.events if isinstance(event, tuple) and event[0] == "finish"
    ]
    assert len(finishes) == 1
    assert "budget" not in driver.events[driver.events.index(finishes[0]) + 1 :]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("mode", ["terminal_ack_lost", "receipt_unknown"])
def test_terminal_ack_or_receipt_failure_never_rewrites_its_bound_report(driver, capsys, mode):
    driver.fault.mode = mode
    assert invoke() == 1
    report_path = driver.path / "qualification-report.json"
    assert document(driver)["controls_status"] == "QUALIFIED_REFERENCE_ONLY"
    assert state(driver)["final_report_sha256"] == record(report_path)["sha256"]
    assert state(driver)["phase"] == "TERMINAL" and state(driver)["charged"] == 24
    finishes = [
        event for event in driver.events if isinstance(event, tuple) and event[0] == "finish"
    ]
    assert finishes == [("finish", "QUALIFIED_REFERENCE_ONLY")]
    last_finish = driver.events.index(("finish", "QUALIFIED_REFERENCE_ONLY"))
    assert "budget" not in driver.events[last_finish + 1 :]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"kind": "restricted_reference_ec2_recovery_terminal_receipt_v2"},
        {"recovery_accounting": {}},
        {"final_report_sha256": "0" * 64},
        {"unknown": True},
    ],
)
def test_wrong_receipt_preserves_committed_pair_without_success(driver, capsys, change):
    driver.fault.receipt_changes.update(change)
    assert invoke() == 1
    digest = record(driver.path / "qualification-report.json")["sha256"]
    assert state(driver)["final_report_sha256"] == digest
    assert document(driver)["controls_status"] == "QUALIFIED_REFERENCE_ONLY"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("unknown_case", [False, True])
def test_broken_summary_channel_preserves_both_successful_and_unsuccessful_terminal_reports(
    driver, monkeypatch, capsys, unknown_case
):
    if unknown_case:
        driver.fault.mode = "unknown_case"

    class BrokenOutput:
        def write(self, _value):
            raise BrokenPipeError("Summary transport disconnected")

    monkeypatch.setattr(
        qualification, "sys", SimpleNamespace(stdout=BrokenOutput(), stderr=sys.stderr)
    )
    assert invoke() == 1
    report = document(driver)
    assert "failure" not in report
    expected = "NOT_QUALIFIED" if unknown_case else "QUALIFIED_REFERENCE_ONLY"
    assert report["controls_status"] == expected
    assert state(driver)["phase"] == "TERMINAL"
    if not unknown_case:
        digest = record(driver.path / "qualification-report.json")["sha256"]
        assert state(driver)["final_report_sha256"] == digest
    finishes = [
        event for event in driver.events if isinstance(event, tuple) and event[0] == "finish"
    ]
    assert len(finishes) == 1
    assert "terminal_observation_uncertain" in capsys.readouterr().err


def test_retrying_the_driver_cannot_reexecute_or_overwrite_a_submitted_success(driver, capsys):
    assert invoke() == 0
    path = driver.path / "qualification-report.json"
    before, inode = path.read_bytes(), path.stat().st_ino
    capsys.readouterr()
    assert invoke() == 1
    assert path.read_bytes() == before and path.stat().st_ino == inode
    backends = [
        event for event in driver.events if isinstance(event, tuple) and event[0] == "backend"
    ]
    assert len(backends) == 24
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("mode", ["unknown_case", "policy_refused"])
def test_not_qualified_terminal_ack_loss_keeps_original_report_and_never_refinalizes(
    driver, monkeypatch, capsys, mode
):
    driver.fault.mode = mode
    actual_finish = ec2.Ec2Run.finish
    submitted = []

    def persisted_then_unknown(run, **request):
        path = run.run_dir / "qualification-report.json"
        submitted.append((path.read_bytes(), path.stat().st_ino, request))
        actual_finish(run, **request)
        raise OSError("Actual NOT_QUALIFIED terminal committed; reply unavailable")

    monkeypatch.setattr(ec2.Ec2Run, "finish", persisted_then_unknown)
    assert invoke() == 1
    assert len(submitted) == 1
    path = driver.path / "qualification-report.json"
    assert (path.read_bytes(), path.stat().st_ino) == submitted[0][:2]
    assert submitted[0][2]["outcome"] == "NOT_QUALIFIED"
    durable = state(driver)
    assert durable["phase"] == "TERMINAL" and durable["outcome"] == "NOT_QUALIFIED"
    assert durable["final_report_sha256"] is None
    assert durable["charged"] == (1 if mode == "unknown_case" else 0)
    finish_index = driver.events.index(("finish", "NOT_QUALIFIED"))
    assert "budget" not in driver.events[finish_index + 1 :]
    assert "receipt" not in driver.events
    assert capsys.readouterr().out == ""
