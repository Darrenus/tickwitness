"""Driver orchestration with real files; synthetic runs never qualify an EC2 host."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure.restricted_reference_ec2 import (
    RECOVERY_MANIFEST_KEYS,
    RECOVERY_PLAN_ID,
    RECOVERY_V2_PLAN_ID,
    RECOVERY_V2_RUN_ID,
    BudgetSnapshot,
    ProbeAdmission,
    canonical,
)

SCRIPT = Path(__file__).parents[1] / "scripts" / "qualify_restricted_reference_ec2.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_ec2_qualification_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)
REVISION = "a" * 40
HISTORY_IDS = ["ec201aab11254e8bb7cd1573a96a0001", "ec201aab11254e8bb7cd1573a96a0002"]


def invoke() -> int:
    return qualification.main(
        [
            "--source-revision",
            REVISION,
            "--run-id",
            RECOVERY_V2_RUN_ID,
            "--recovery-plan",
            RECOVERY_V2_PLAN_ID,
        ]
    )


@pytest.fixture
def v2_driver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    events = []
    fault = SimpleNamespace(
        mode="pass",
        version=2,
        context_changes={},
        accounting_changes={},
        manifest_changes={},
        manifest_removals=set(),
        receipt_changes={},
        receipt_accounting_changes={},
    )

    class Run:
        source_revision = REVISION
        run_id = RECOVERY_V2_RUN_ID
        boot_id = "33333333-3333-3333-3333-333333333333"
        started_ns = 1000
        deadline_ns = 600_000_001_000
        setup_deadline_ns = 30_000_001_000
        run_dir = tmp_path
        artifact_dir = tmp_path / "qualification"

        def __init__(self):
            self.charged = self.confirmed = self.outcomes = 0
            self.recovery_context = None
            self.provider_record = {}
            self.tickets = []
            self.raw_results = {}
            self.finished = []
            self.success_hash = None

        @property
        def recovery_schema_version(self):
            return fault.version

        def snapshot(self):
            if self.charged and fault.mode in {"reserve_uncertain", "snapshot_uncertain"}:
                raise ValueError("Uncertain current submitted slot")
            return BudgetSnapshot(
                self.started_ns,
                self.deadline_ns,
                24,
                self.charged,
                self.confirmed,
                self.charged - self.confirmed,
                False,
                self.charged - self.outcomes,
            )

        def recovery_accounting(self, snapshot):
            assert snapshot == self.snapshot()
            if self.charged and fault.mode == "accounting_uncertain":
                raise ValueError("Uncertain current cumulative counters")
            return {
                "kind": "restricted_reference_ec2_recovery_budget_v2",
                "schema_version": 2,
                "plan_id": RECOVERY_V2_PLAN_ID,
                "historical_run_ids": list(HISTORY_IDS),
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
                **fault.accounting_changes,
            }

        def reserve_probe(self, *, name, nonce):
            self.charged += 1
            events.append(("reserve", name, self.charged))
            if fault.mode == "reserve_uncertain":
                raise OSError("Submitted ticket durability uncertain")
            ticket = ProbeAdmission(
                self.run_id,
                self.boot_id,
                self.source_revision,
                self.charged,
                name,
                nonce,
                self.started_ns,
                self.started_ns + 10_000_000_000,
            )
            self.tickets.append(ticket)
            return ticket

        def finish(self, *, outcome, reason, final_report_sha256=None):
            if outcome == "QUALIFIED_REFERENCE_ONLY":
                if fault.mode == "terminal_uncertain":
                    raise OSError("Terminal durability uncertain")
                if fault.mode == "raw_case_changed":
                    (self.run_dir / "case-01.json").write_bytes(b"changed raw bytes\n")
                raw = (self.run_dir / "qualification-report.json").read_bytes()
                assert hashlib.sha256(raw).hexdigest() == final_report_sha256
                document = json.loads(raw)
                assert document["schema_version"] == 2
                assert document["recovery_accounting"]["current_charged"] == 24
                assert document["recovery_accounting"]["cumulative_charged"] == 26
                assert len(document["cases"]) == len(self.tickets) == 24
                for index, case in enumerate(document["cases"], 1):
                    path = self.run_dir / f"case-{index:02d}.json"
                    actual = path.read_bytes()
                    if actual != self.raw_results[index]:
                        raise ValueError("Independent durable backend raw-case binding differs")
                    assert canonical(case["admission"]) == canonical(
                        dataclasses.asdict(self.tickets[index - 1])
                    )
                    assert case["execution_evidence"] == {
                        "path": str(path),
                        "sha256": hashlib.sha256(actual).hexdigest(),
                        "bytes": len(actual),
                    }
                    assert case["nonce"] == self.tickets[index - 1].nonce
                    assert case["name"] == self.tickets[index - 1].name
                self.success_hash = final_report_sha256
            self.finished.append((outcome, reason))
            events.append(("finish", outcome))

        def qualification_receipt(self):
            events.append(("receipt_readback",))
            if fault.mode == "receipt_uncertain":
                raise OSError("Terminal receipt readback uncertain")
            document = json.loads((self.run_dir / "qualification-report.json").read_bytes())
            return {
                "kind": "restricted_reference_ec2_recovery_terminal_receipt_v2",
                "schema_version": 2,
                "run_id": self.run_id,
                "source_revision": self.source_revision,
                "boot_id": self.boot_id,
                "final_report_sha256": self.success_hash,
                "controls_status": "QUALIFIED_REFERENCE_ONLY",
                "production_m1": "DISABLED",
                "recovery_context": copy.deepcopy(self.recovery_context),
                "recovery_accounting": {
                    **document["recovery_accounting"],
                    **fault.receipt_accounting_changes,
                },
                **fault.receipt_changes,
            }

    run = Run()

    def forbidden(**_kwargs):
        pytest.fail("A v2 selection reached a default or v1 factory")

    def claim_v2(*, source_revision, run_id, plan_id):
        assert (source_revision, run_id, plan_id) == (
            REVISION,
            RECOVERY_V2_RUN_ID,
            RECOVERY_V2_PLAN_ID,
        )
        if fault.mode == "claim_refused":
            events.append(("v2_refused",))
            raise ValueError("Already consumed fixed v2 invocation")
        with (tmp_path / "consumption-marker").open("xb") as stream:
            stream.write(b"one invocation retained\n")
        events.append(("v2_consumed",))
        if fault.mode == "consumed_before_factory_failure":
            raise OSError("Factory failed after irreversible consumption")
        if fault.mode != "missing_context":
            run.recovery_context = {
                "kind": "restricted_reference_ec2_recovery_context_v2",
                "schema_version": 2,
                "plan_id": RECOVERY_V2_PLAN_ID,
                "plan": {"path": "synthetic plan; not host authority"},
                "history": {
                    "original": {"run_id": HISTORY_IDS[0], "charged": 1},
                    "recovery": {"run_id": HISTORY_IDS[1], "charged": 1},
                },
                "consumption": {"path": str(tmp_path / "consumption-marker")},
                "invocation": {"source_revision": REVISION, "run_id": RECOVERY_V2_RUN_ID},
                "allowance": {"max_admissions": 24, "max_cumulative_admissions": 26},
                **fault.context_changes,
            }
        run.provider_record = {
            "kind": "restricted_reference_ec2_recovery_host_v2",
            "schema_version": 2,
            "recovery_context": copy.deepcopy(run.recovery_context),
        }
        return run

    def prepare_policy(*, ec2_run):
        assert ec2_run is run
        events.append(("loader",))
        if fault.mode == "loader_refused":
            raise ValueError("Fixed policy preparation refused")

    class Runner:
        def __init__(self, artifact, payload, *, ec2_run):
            assert ec2_run is run and artifact == run.artifact_dir
            assert payload.name == "restricted_reference_payload.py"
            events.append(("runner",))
            artifact.mkdir()
            self.manifest = dict.fromkeys(RECOVERY_MANIFEST_KEYS)
            self.manifest.update(
                kind="restricted_reference_ec2_recovery_manifest_v2",
                schema_version=2,
                source_revision=REVISION,
                production_m1_enabled=False,
                available_for_probe=True,
                unavailable_reasons=[],
                fixed_cases=list(qualification.PROBE_NAMES),
                qualification_started_ns=run.started_ns,
                qualification_deadline_ns=run.deadline_ns,
                provider_context=copy.deepcopy(run.provider_record),
                recovery_context=copy.deepcopy(run.recovery_context),
                recovery_accounting=run.recovery_accounting(run.snapshot()),
                recovery_accounting_phase="pre_probe_manifest",
            )
            self.manifest.update(fault.manifest_changes)
            for field in fault.manifest_removals:
                del self.manifest[field]
            raw = canonical(self.manifest)
            (artifact / "manifest.json").write_bytes(raw)
            self.manifest_sha256 = hashlib.sha256(raw).hexdigest()

        def run_probe(self, name, *, arguments, ec2_admission):
            events.append(("backend", name))
            assert ec2_admission is run.tickets[-1]
            published = json.loads((run.run_dir / "qualification-report.json").read_bytes())
            assert published["admissions_charged"] == run.charged
            assert published["recovery_accounting"]["cumulative_charged"] == 2 + run.charged
            if fault.mode == "backend_ack_lost":
                raise OSError("Backend admission ACK lost")
            run.confirmed += 1
            if fault.mode == "cancelled":
                raise InterruptedError("Controller cancelled")
            run.outcomes += 1
            result = {
                "name": name,
                "nonce": arguments[0],
                "payload_started": True,
                "stop_confirmed": True,
                "cleanup_confirmed": True,
                "failure": None,
                "host_facts": {
                    "manifest_sha256": self.manifest_sha256,
                    "admission_number": ec2_admission.admission_number,
                    "original_admission_ns": ec2_admission.admitted_ns,
                    "original_deadline_ns": ec2_admission.deadline_ns,
                },
            }
            run.raw_results[ec2_admission.admission_number] = canonical(result)
            return result

    def assess(result, name, nonce, manifest):
        assert result["name"] == name and result["nonce"] == nonce
        assert manifest == result["host_facts"]["manifest_sha256"]
        return {
            "status": "FAIL" if fault.mode == "failed_control" else "PASS",
            "reason": "actual_scoped_control_evidence",
        }

    monkeypatch.setattr(
        qualification,
        "Ec2Run",
        SimpleNamespace(claim=forbidden, claim_recovery=forbidden, claim_recovery_v2=claim_v2),
    )
    monkeypatch.setattr(qualification, "ReferenceRunner", Runner)
    monkeypatch.setattr(qualification.time, "monotonic_ns", lambda: 2000)
    monkeypatch.setattr(
        qualification,
        "_script",
        lambda name: (
            SimpleNamespace(prepare_policy=prepare_policy)
            if name == "prepare_reference_policy_ec2.py"
            else SimpleNamespace(assess_probe=assess)
        ),
    )
    return SimpleNamespace(run=run, fault=fault, events=events, path=tmp_path)


def report(driver):
    return json.loads((driver.path / "qualification-report.json").read_bytes())


def test_v2_publishes_twenty_four_raw_bound_cases_before_terminal_and_receipt(v2_driver, capsys):
    assert invoke() == 0
    result = report(v2_driver)
    assert result["kind"] == "restricted_reference_ec2_recovery_qualification_v2"
    assert result["schema_version"] == 2
    assert [event[0] for event in v2_driver.events[:3]] == ["v2_consumed", "loader", "runner"]
    assert v2_driver.events[-1] == ("receipt_readback",)
    assert len(list(v2_driver.path.glob("case-*.json"))) == 24
    assert len({ticket.nonce for ticket in v2_driver.run.tickets}) == 24
    assert result["recovery_accounting"]["historical_run_ids"] == HISTORY_IDS
    assert result["recovery_accounting"]["cumulative_charged"] == 26
    initial = json.loads((v2_driver.run.artifact_dir / "manifest.json").read_bytes())
    assert initial["recovery_accounting"]["current_charged"] == 0
    assert initial["recovery_accounting"]["cumulative_charged"] == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["terminal_receipt"]["final_report_sha256"] == v2_driver.run.success_hash
    assert summary["recovery_accounting"] == result["recovery_accounting"]
    assert result["research_reservations"] == result["replay_engine_invocations"] == 0


@pytest.mark.parametrize("mode", ["claim_refused", "consumed_before_factory_failure"])
def test_v2_factory_refusal_has_no_fallback_or_invented_zero_authority(v2_driver, capsys, mode):
    v2_driver.fault.mode = mode
    assert invoke() == 1
    assert len(v2_driver.events) == 1
    assert not (v2_driver.path / "qualification-report.json").exists()
    assert (v2_driver.path / "consumption-marker").exists() == (
        mode == "consumed_before_factory_failure"
    )
    assert capsys.readouterr().out == ""


def test_v2_second_invocation_cannot_overwrite_committed_results(v2_driver, capsys):
    assert invoke() == 0
    original = (v2_driver.path / "qualification-report.json").read_bytes()
    capsys.readouterr()
    assert invoke() == 1
    assert (v2_driver.path / "qualification-report.json").read_bytes() == original
    assert v2_driver.run.charged == 24
    assert len([event for event in v2_driver.events if event[0] == "backend"]) == 24
    assert capsys.readouterr().out == ""


def test_v2_missing_context_cannot_publish_zero_charge_authority(v2_driver):
    v2_driver.fault.mode = "missing_context"
    assert invoke() == 1
    result = report(v2_driver)
    assert result["durable_budget_status"] == "UNKNOWN"
    assert "recovery_context" not in result and "recovery_accounting" not in result
    assert "admissions_charged" not in result and "durable_budget" not in result
    assert all(event[0] != "loader" for event in v2_driver.events)


def test_v2_loader_refusal_preserves_two_history_charges_without_probe(v2_driver):
    v2_driver.fault.mode = "loader_refused"
    assert invoke() == 1
    result = report(v2_driver)
    assert result["admissions_charged"] == 0
    assert result["recovery_accounting"]["cumulative_charged"] == 2
    assert all(event[0] not in {"runner", "reserve", "backend"} for event in v2_driver.events)


@pytest.mark.parametrize("version", [None, 1, True, 2.0, 3])
def test_v2_requires_the_actual_exact_version_property(v2_driver, version):
    v2_driver.fault.version = version
    assert invoke() == 1
    result = report(v2_driver)
    assert result["durable_budget_status"] == "UNKNOWN"
    assert "admissions_charged" not in result and "recovery_accounting" not in result
    assert all(event[0] not in {"loader", "runner", "backend"} for event in v2_driver.events)


def test_missing_version_property_is_not_inferred_from_v2_context(v2_driver, monkeypatch):
    monkeypatch.delattr(type(v2_driver.run), "recovery_schema_version")
    assert invoke() == 1
    assert report(v2_driver)["durable_budget_status"] == "UNKNOWN"
    assert all(event[0] != "loader" for event in v2_driver.events)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "restricted_reference_ec2_recovery_context_v1"},
        {"schema_version": True},
        {"schema_version": 2.0},
        {"plan_id": RECOVERY_PLAN_ID},
    ],
)
def test_v2_cannot_acquire_different_context_authority(v2_driver, changes):
    v2_driver.fault.context_changes.update(changes)
    assert invoke() == 1
    assert "admissions_charged" not in report(v2_driver)
    assert all(event[0] != "loader" for event in v2_driver.events)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "restricted_reference_ec2_recovery_budget_v1"},
        {"schema_version": True},
        {"plan_id": RECOVERY_PLAN_ID},
        {"historical_run_ids": list(reversed(HISTORY_IDS))},
        {"prior_charged": 1},
        {"prior_charged": True},
        {"prior_backend_confirmed": 2.0},
        {"cumulative_charged": 0},
        {"max_cumulative_admissions": 25},
        {"unexpected": "authority"},
    ],
)
def test_v2_budget_requires_exact_two_run_history_and_types(v2_driver, changes):
    v2_driver.fault.accounting_changes.update(changes)
    assert invoke() == 1
    assert report(v2_driver)["durable_budget_status"] == "UNKNOWN"
    assert "durable_budget" not in report(v2_driver)
    assert all(event[0] != "loader" for event in v2_driver.events)


@pytest.mark.parametrize(
    "changes,removed",
    [
        ({"kind": "restricted_reference_ec2_recovery_manifest_v1"}, None),
        ({"schema_version": 1}, None),
        ({"schema_version": True}, None),
        ({"recovery_context": {}}, None),
        ({"recovery_accounting_phase": "terminal"}, None),
        ({"fixture_scope": "Unknown top-level fields are not authority"}, None),
        ({}, "os_release"),
    ],
)
def test_v2_manifest_refusal_precedes_first_charge(v2_driver, changes, removed):
    v2_driver.fault.manifest_changes.update(changes)
    if removed is not None:
        v2_driver.fault.manifest_removals.add(removed)
    assert invoke() == 1
    result = report(v2_driver)
    assert result["admissions_charged"] == 0
    assert result["recovery_accounting"]["cumulative_charged"] == 2
    assert all(event[0] not in {"reserve", "backend"} for event in v2_driver.events)


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_charged", 24),
        ("cumulative_charged", 26),
        ("prior_charged", True),
        ("historical_run_ids", list(reversed(HISTORY_IDS))),
    ],
)
def test_v2_manifest_requires_its_initial_snapshot_not_a_terminal_budget(v2_driver, field, value):
    initial = v2_driver.run.recovery_accounting(v2_driver.run.snapshot())
    v2_driver.fault.manifest_changes["recovery_accounting"] = {**initial, field: value}
    assert invoke() == 1
    result = report(v2_driver)
    assert result["admissions_charged"] == 0
    assert result["recovery_accounting"]["cumulative_charged"] == 2
    assert all(event[0] not in {"reserve", "backend"} for event in v2_driver.events)


@pytest.mark.parametrize(
    "mode", ["reserve_uncertain", "snapshot_uncertain", "accounting_uncertain"]
)
def test_v2_uncertainty_retains_charge_and_only_explicit_lower_bounds(v2_driver, mode):
    v2_driver.fault.mode = mode
    assert invoke() == 1
    result = report(v2_driver)
    assert v2_driver.run.charged == 1
    assert result["durable_budget_status"] == "UNKNOWN"
    assert "admissions_charged" not in result and "durable_budget" not in result
    assert "recovery_accounting" not in result
    lower = result["last_confirmed_recovery_accounting_lower_bound"]
    assert lower["current_charged"] == 0 and lower["cumulative_charged"] == 2
    assert all(event[0] != "backend" for event in v2_driver.events)


@pytest.mark.parametrize("mode", ["backend_ack_lost", "cancelled", "failed_control"])
def test_v2_failed_case_retains_both_history_charges_and_current_slot(v2_driver, mode):
    v2_driver.fault.mode = mode
    assert invoke() == 1
    result = report(v2_driver)
    assert result["recovery_accounting"]["prior_charged"] == 2
    assert result["recovery_accounting"]["current_charged"] == 1
    assert result["recovery_accounting"]["cumulative_charged"] == 3
    assert len([event for event in v2_driver.events if event[0] == "backend"]) == 1
    assert all(case["admission_submitted"] is False for case in result["cases"][1:])


@pytest.mark.parametrize("mode", ["raw_case_changed", "terminal_uncertain", "receipt_uncertain"])
def test_v2_finalization_failure_never_refunds_or_publishes_success(v2_driver, capsys, mode):
    v2_driver.fault.mode = mode
    assert invoke() == 1
    result = report(v2_driver)
    assert result["controls_status"] == "NOT_QUALIFIED"
    assert result["recovery_accounting"]["cumulative_charged"] == 26
    assert capsys.readouterr().out == ""
    assert (v2_driver.path / "consumption-marker").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "restricted_reference_ec2_recovery_terminal_receipt_v1"},
        {"schema_version": 1},
        {"schema_version": True},
        {"final_report_sha256": "0" * 64},
        {"recovery_context": {}},
        {"recovery_accounting": {}},
        {"unexpected": True},
    ],
)
def test_v2_receipt_mismatch_invalidates_pair_without_reopening_terminal(
    v2_driver, capsys, changes
):
    v2_driver.fault.receipt_changes.update(changes)
    assert invoke() == 1
    assert report(v2_driver)["controls_status"] == "NOT_QUALIFIED"
    assert v2_driver.run.finished == [("QUALIFIED_REFERENCE_ONLY", None)]
    assert (
        v2_driver.run.success_hash
        != hashlib.sha256((v2_driver.path / "qualification-report.json").read_bytes()).hexdigest()
    )
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("changes", [{"current_unconfirmed": False}, {"prior_charged": 2.0}])
def test_v2_receipt_numeric_lookalikes_do_not_equal_final_authority(v2_driver, capsys, changes):
    v2_driver.fault.receipt_accounting_changes.update(changes)
    assert invoke() == 1
    assert report(v2_driver)["controls_status"] == "NOT_QUALIFIED"
    assert v2_driver.run.charged == 24
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("option", ["--recovery", "--recovery-plan-path", "--fourth-window"])
def test_v2_has_no_abbreviation_arbitrary_path_or_further_window(v2_driver, option):
    with pytest.raises(SystemExit) as exited:
        qualification.main(
            ["--source-revision", REVISION, "--run-id", RECOVERY_V2_RUN_ID, option, "other"]
        )
    assert exited.value.code == 2
    assert v2_driver.events == []
