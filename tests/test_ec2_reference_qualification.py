"""Driver decision faults only: these fakes never execute or qualify a native probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure.restricted_reference_ec2 import BudgetSnapshot, ProbeAdmission

SCRIPT = Path(__file__).parents[1] / "scripts" / "qualify_restricted_reference_ec2.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_ec2_qualification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)
REVISION = "a" * 40
RUN_ID = "b" * 32


@pytest.mark.parametrize(
    "arguments",
    [
        ["--source", REVISION, "--run-id", RUN_ID],
        ["--source-revision", REVISION, "--run", RUN_ID],
        ["--source-revision", REVISION, "--run-id", RUN_ID, "--provider", "other"],
        ["--source-revision", REVISION, "--run-id", RUN_ID, "--recovery", "other"],
        ["--source-revision", REVISION, "--run-id", RUN_ID, "--recovery-plan", "other"],
        ["--source-revision", REVISION, "--run-id", RUN_ID, "--recovery-plan", "/tmp/plan.json"],
    ],
)
def test_unknown_or_abbreviated_options_cannot_claim(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    def forbidden_claim(**kwargs: object) -> None:
        raise AssertionError("Invalid CLI cannot claim qualification authority")

    monkeypatch.setattr(qualification.Ec2Run, "claim", forbidden_claim)
    monkeypatch.setattr(qualification.Ec2Run, "claim_recovery", forbidden_claim)
    with pytest.raises(SystemExit) as exited:
        qualification.main(arguments)
    assert exited.value.code == 2


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    events = []
    mode = ["pass"]
    manifest_changes: dict[str, object] = {}
    receipt_changes: dict[str, object] = {}

    class Run:
        run_dir = tmp_path
        artifact_dir = tmp_path / "artifacts"
        source_revision = REVISION
        run_id = RUN_ID
        boot_id = "actual-fake-boot"
        started_ns = 1000
        deadline_ns = 10**30
        charged = 0
        confirmed = 0
        outcomes = 0

        def __init__(self) -> None:
            self.provider_record = {"provider": "fake unit fixture"}
            self.recovery_context: dict[str, object] | None = None
            self.finished: list[tuple[str, str | None]] = []

        def snapshot(self) -> BudgetSnapshot:
            if mode[0] == "reserve_persist_uncertain" and self.charged:
                raise ValueError("injected fenced durable counters")
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

        def recovery_accounting(self, snapshot: BudgetSnapshot) -> dict[str, object] | None:
            if self.recovery_context is None:
                return None
            if mode[0] == "recovery_accounting_uncertain" and self.charged:
                raise ValueError("injected uncertain cumulative counters")
            assert snapshot == self.snapshot()
            return {
                "kind": "restricted_reference_ec2_recovery_budget_v1",
                "schema_version": 1,
                "plan_id": qualification.RECOVERY_PLAN_ID,
                "predecessor_run_id": "fixture-predecessor",
                "prior_charged": 1,
                "prior_backend_confirmed": 1,
                "current_charged": snapshot.charged,
                "current_backend_confirmed": snapshot.backend_confirmed,
                "current_unconfirmed": snapshot.unconfirmed,
                "current_pending_outcomes": snapshot.pending_outcomes,
                "cumulative_charged": 1 + snapshot.charged,
                "cumulative_backend_confirmed": 1 + snapshot.backend_confirmed,
                "max_current_admissions": 24,
                "max_cumulative_admissions": 25,
            }

        def reserve_probe(self, *, name: str, nonce: str) -> ProbeAdmission:
            self.charged += 1
            events.append(("reserve", name, self.charged))
            if mode[0] == "reserve_persist_uncertain":
                raise OSError("injected uncertain submitted ticket")
            return ProbeAdmission(
                RUN_ID,
                self.boot_id,
                REVISION,
                self.charged,
                name,
                nonce,
                1000,
                10**30,
            )

        def finish(
            self,
            *,
            outcome: str,
            reason: str | None,
            final_report_sha256: str | None = None,
        ) -> None:
            if outcome == "QUALIFIED_REFERENCE_ONLY":
                assert (
                    final_report_sha256
                    == qualification.hashlib.sha256(
                        (tmp_path / "qualification-report.json").read_bytes()
                    ).hexdigest()
                )
                assert mode[0] != "terminal_failure" or self.charged == 24
                if mode[0] == "terminal_failure":
                    raise OSError("injected terminal write failure")
            self.finished.append((outcome, reason))
            events.append(("finish", outcome))

        def qualification_receipt(self) -> dict[str, object]:
            if mode[0] == "receipt_failure":
                raise OSError("injected final receipt failure")
            if self.recovery_context is not None:
                raw = (tmp_path / "qualification-report.json").read_bytes()
                document = json.loads(raw)
                receipt = {
                    "kind": "restricted_reference_ec2_recovery_terminal_receipt_v1",
                    "schema_version": 1,
                    "run_id": self.run_id,
                    "source_revision": self.source_revision,
                    "boot_id": self.boot_id,
                    "final_report_sha256": qualification.hashlib.sha256(raw).hexdigest(),
                    "controls_status": "QUALIFIED_REFERENCE_ONLY",
                    "production_m1": "DISABLED",
                    "recovery_context": self.recovery_context,
                    "recovery_accounting": document["recovery_accounting"],
                    **receipt_changes,
                }
                if mode[0] == "receipt_accounting_boolean":
                    receipt["recovery_accounting"] = {
                        **document["recovery_accounting"],
                        "prior_charged": True,
                    }
                return receipt
            return {"controls_status": "QUALIFIED_REFERENCE_ONLY"}

    run = Run()

    def claim(*, source_revision: str, run_id: str) -> Run:
        assert source_revision == REVISION and run_id == RUN_ID
        events.append(("claim", source_revision, run_id))
        return run

    def claim_recovery(*, source_revision: str, run_id: str, plan_id: str) -> Run:
        assert source_revision == REVISION and run_id == RUN_ID
        assert plan_id == qualification.RECOVERY_PLAN_ID
        if mode[0] == "recovery_claim_refused":
            events.append(("recovery_claim_refused",))
            raise ValueError("injected consumed or invalid recovery plan")
        events.append(("recovery_consumed", source_revision, run_id, plan_id))
        if mode[0] != "recovery_factory_missing_context":
            run.recovery_context = {
                "kind": "restricted_reference_ec2_recovery_context_v1",
                "schema_version": 1,
                "plan_id": plan_id,
                "fixture_scope": "driver decisions, not actual recovery authority",
            }
            run.provider_record = {
                "provider": "fake unit fixture",
                "recovery_context": run.recovery_context,
            }
        return run

    def prepare_policy(*, ec2_run: Run) -> dict[str, object]:
        assert ec2_run is run
        events.append(("loader",))
        if mode[0] == "setup_failure":
            raise ValueError("injected loader refusal")
        return {}

    def assess_probe(
        result: dict[str, object],
        name: str,
        nonce: str,
        manifest: str,
    ) -> dict[str, object]:
        assert result["name"] == name and result["nonce"] == nonce and manifest == "d" * 64
        return {"status": "FAIL" if mode[0] == "fail" else "PASS", "reason": "unit fixture"}

    class Runner:
        manifest_sha256 = "d" * 64

        def __init__(self, artifact: Path, payload: Path, *, ec2_run: Run) -> None:
            self.manifest = {"fixed_cases": list(qualification.PROBE_NAMES)}
            if run.recovery_context is not None:
                self.manifest.update(
                    kind="restricted_reference_ec2_recovery_manifest_v1",
                    schema_version=1,
                    source_revision=run.source_revision,
                    production_m1_enabled=False,
                    qualification_started_ns=run.started_ns,
                    qualification_deadline_ns=run.deadline_ns,
                    provider_context=run.provider_record,
                    recovery_context=run.recovery_context,
                    recovery_accounting=run.recovery_accounting(run.snapshot()),
                    recovery_accounting_phase="pre_probe_manifest",
                )
                if mode[0] == "manifest_accounting_boolean":
                    self.manifest["recovery_accounting"] = {
                        **self.manifest["recovery_accounting"],
                        "prior_charged": True,
                    }
                self.manifest.update(manifest_changes)
            assert artifact == run.artifact_dir and ec2_run is run
            assert payload.name == "restricted_reference_payload.py"
            events.append(("runner",))

        def run_probe(
            self,
            name: str,
            *,
            arguments: tuple[str, ...],
            ec2_admission: ProbeAdmission,
        ) -> dict[str, object]:
            assert run.charged == ec2_admission.admission_number
            report = json.loads((tmp_path / "qualification-report.json").read_bytes())
            assert report["admissions_charged"] == run.charged
            if run.recovery_context is not None:
                assert report["recovery_accounting"]["current_charged"] == run.charged
                assert report["recovery_accounting"]["cumulative_charged"] == 1 + run.charged
            events.append(("backend", name))
            if mode[0] == "lost_before_confirm":
                raise OSError("injected backend loss")
            run.confirmed += 1
            if mode[0] == "cancel":
                raise InterruptedError("injected cancellation")
            run.outcomes += 1
            return {"name": name, "nonce": arguments[0], "payload_started": True}

    monkeypatch.setattr(
        qualification, "Ec2Run", SimpleNamespace(claim=claim, claim_recovery=claim_recovery)
    )
    monkeypatch.setattr(qualification, "ReferenceRunner", Runner)
    monkeypatch.setattr(
        qualification,
        "_script",
        lambda name: (
            SimpleNamespace(prepare_policy=prepare_policy)
            if name == "prepare_reference_policy_ec2.py"
            else SimpleNamespace(assess_probe=assess_probe)
        ),
    )
    return SimpleNamespace(
        run=run,
        events=events,
        mode=mode,
        path=tmp_path,
        manifest_changes=manifest_changes,
        receipt_changes=receipt_changes,
    )


def invoke() -> int:
    return qualification.main(["--source-revision", REVISION, "--run-id", RUN_ID])


def invoke_recovery() -> int:
    return qualification.main(
        [
            "--source-revision",
            REVISION,
            "--run-id",
            RUN_ID,
            "--recovery-plan",
            qualification.RECOVERY_PLAN_ID,
        ]
    )


def report(driver: SimpleNamespace) -> dict[str, object]:
    return json.loads((driver.path / "qualification-report.json").read_bytes())


def test_driver_claims_before_setup_and_reserves_before_each_backend(
    driver: SimpleNamespace,
) -> None:
    assert invoke() == 0
    assert [event[0] for event in driver.events[:3]] == ["claim", "loader", "runner"]
    for index, event in enumerate(driver.events):
        if event[0] == "backend":
            assert driver.events[index - 1][0] == "reserve"
    result = report(driver)
    assert result["admissions_charged"] == 24
    assert result["confirmed_backend_admissions"] == 24
    assert result["backend_unconfirmed_admissions"] == 0
    assert result["controls_status"] == "QUALIFIED_REFERENCE_ONLY"
    assert result["production_m1"] == "DISABLED"
    assert result["external_human_reproduction"] == "0/0/PENDING"
    assert result["research_reservations"] == result["replay_engine_invocations"] == 0
    assert result["kind"] == "restricted_reference_ec2_qualification_v1"
    assert "recovery_context" not in result and "recovery_accounting" not in result


@pytest.mark.parametrize("mode", ["fail", "lost_before_confirm", "cancel"])
def test_failures_preserve_submitted_charge_and_stop_the_catalog(
    driver: SimpleNamespace,
    mode: str,
) -> None:
    driver.mode[0] = mode
    assert invoke() == 1
    result = report(driver)
    assert result["controls_status"] == "NOT_QUALIFIED"
    assert result["admissions_charged"] == 1
    assert result["confirmed_backend_admissions"] == (0 if mode == "lost_before_confirm" else 1)
    assert result["backend_unconfirmed_admissions"] == (1 if mode == "lost_before_confirm" else 0)
    cases = result["cases"]
    assert len(cases) == 24
    assert all(case["admission_submitted"] is False for case in cases[1:])
    assert len([event for event in driver.events if event[0] == "backend"]) == 1
    assert driver.run.finished[-1][0] == "NOT_QUALIFIED"


def test_loader_failure_never_constructs_backend_or_charges_probe(driver: SimpleNamespace) -> None:
    driver.mode[0] = "setup_failure"
    assert invoke() == 1
    result = report(driver)
    assert result["admissions_charged"] == 0
    assert result["controls_status"] == "NOT_QUALIFIED"
    assert all(event[0] != "runner" for event in driver.events)
    assert len(result["cases"]) == 24


def test_fenced_charge_is_unknown_and_previous_zero_is_only_a_lower_bound(
    driver: SimpleNamespace,
) -> None:
    driver.mode[0] = "reserve_persist_uncertain"
    assert invoke() == 1
    result = report(driver)
    assert driver.run.charged == 1
    assert result["durable_budget_status"] == "UNKNOWN"
    assert "admissions_charged" not in result
    assert result["last_confirmed_budget_lower_bound"]["charged"] == 0
    assert "not authoritative current zero" in result["budget_uncertainty_scope"]
    assert all(event[0] != "backend" for event in driver.events)


def test_first_report_failure_finishes_claim_before_payload(
    driver: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_write(*_args: object, **_kwargs: object) -> str:
        raise OSError("injected durable report failure")

    monkeypatch.setattr(qualification, "_write", failed_write)
    assert invoke() == 1
    assert driver.run.charged == 0
    assert driver.run.finished == [("NOT_QUALIFIED", "OSError")]
    assert all(event[0] != "loader" for event in driver.events)


@pytest.mark.parametrize("mode", ["terminal_failure", "receipt_failure"])
def test_report_or_terminal_alone_cannot_publish_success(
    driver: SimpleNamespace,
    mode: str,
) -> None:
    driver.mode[0] = mode
    assert invoke() == 1
    result = report(driver)
    assert result["controls_status"] == "NOT_QUALIFIED"
    assert result["admissions_charged"] == 24
    assert result["pending_probe_outcomes"] == 0
    assert "failure" in result
    if mode == "terminal_failure":
        assert driver.run.finished[-1][0] == "NOT_QUALIFIED"


def test_cli_has_no_host_policy_command_or_evidence_override() -> None:
    with pytest.raises(SystemExit) as error:
        qualification.main(
            [
                "--source-revision",
                REVISION,
                "--run-id",
                RUN_ID,
                "--evidence-dir",
                "/tmp/other",
            ]
        )
    assert error.value.code == 2


def test_recovery_consumes_explicit_plan_before_setup_and_retains_historical_charge(
    driver: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert invoke_recovery() == 0
    assert [event[0] for event in driver.events[:3]] == [
        "recovery_consumed",
        "loader",
        "runner",
    ]
    assert all(event[0] != "claim" for event in driver.events)
    result = report(driver)
    assert result["kind"] == "restricted_reference_ec2_recovery_qualification_v1"
    assert result["recovery_context"] == driver.run.recovery_context
    accounting = result["recovery_accounting"]
    assert accounting["prior_charged"] == accounting["prior_backend_confirmed"] == 1
    assert accounting["current_charged"] == accounting["current_backend_confirmed"] == 24
    assert accounting["cumulative_charged"] == accounting["cumulative_backend_confirmed"] == 25
    assert accounting["current_unconfirmed"] == accounting["current_pending_outcomes"] == 0
    assert result["research_reservations"] == result["replay_engine_invocations"] == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["recovery_accounting"] == accounting
    assert summary["terminal_receipt"]["recovery_context"] == result["recovery_context"]
    assert summary["terminal_receipt"]["final_report_sha256"] == qualification.hashlib.sha256(
        (driver.path / "qualification-report.json").read_bytes()
    ).hexdigest()


def test_recovery_claim_refusal_never_falls_back_or_claims_zero_charge_authority(
    driver: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    driver.mode[0] = "recovery_claim_refused"
    assert invoke_recovery() == 1
    assert driver.events == [("recovery_claim_refused",)]
    assert not (driver.path / "qualification-report.json").exists()
    captured = capsys.readouterr()
    assert captured.out == "" and "not_qualified" in captured.err


def test_recovery_factory_missing_context_cannot_publish_authoritative_zero(
    driver: SimpleNamespace,
) -> None:
    driver.mode[0] = "recovery_factory_missing_context"
    assert invoke_recovery() == 1
    result = report(driver)
    assert result["kind"] == "restricted_reference_ec2_recovery_qualification_v1"
    assert result["durable_budget_status"] == "UNKNOWN"
    assert "recovery_context" not in result and "recovery_accounting" not in result
    assert "admissions_charged" not in result and "durable_budget" not in result
    assert all(event[0] not in {"loader", "runner", "backend", "claim"} for event in driver.events)


@pytest.mark.parametrize("mode", ["reserve_persist_uncertain", "recovery_accounting_uncertain"])
def test_recovery_uncertainty_retains_only_confirmed_per_run_and_cumulative_lower_bounds(
    driver: SimpleNamespace,
    mode: str,
) -> None:
    driver.mode[0] = mode
    assert invoke_recovery() == 1
    result = report(driver)
    assert driver.run.charged == 1
    assert result["durable_budget_status"] == "UNKNOWN"
    assert "admissions_charged" not in result and "durable_budget" not in result
    assert "recovery_accounting" not in result
    assert result["last_confirmed_budget_lower_bound"]["charged"] == 0
    previous = result["last_confirmed_recovery_accounting_lower_bound"]
    assert previous["prior_charged"] == previous["cumulative_charged"] == 1
    assert previous["current_charged"] == 0
    assert all(event[0] != "backend" for event in driver.events)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "restricted_reference_ec2_manifest_v1"),
        ("schema_version", True),
        ("source_revision", "c" * 40),
        ("production_m1_enabled", True),
        ("qualification_started_ns", 1001),
        ("qualification_deadline_ns", 10**30 + 1),
        ("provider_context", {}),
        ("recovery_context", {}),
        ("recovery_accounting", {}),
        ("recovery_accounting_phase", "terminal"),
    ],
)
def test_recovery_manifest_lineage_or_initial_accounting_change_prevents_admission(
    driver: SimpleNamespace,
    field: str,
    value: object,
) -> None:
    driver.manifest_changes[field] = value
    assert invoke_recovery() == 1
    result = report(driver)
    assert result["controls_status"] == "NOT_QUALIFIED"
    assert result["admissions_charged"] == 0
    assert result["recovery_accounting"]["cumulative_charged"] == 1
    assert all(event[0] not in {"reserve", "backend"} for event in driver.events)


def test_boolean_historical_manifest_charge_is_not_equal_authority(
    driver: SimpleNamespace,
) -> None:
    driver.mode[0] = "manifest_accounting_boolean"
    assert invoke_recovery() == 1
    assert report(driver)["admissions_charged"] == 0
    assert all(event[0] != "backend" for event in driver.events)


@pytest.mark.parametrize("mode", ["fail", "lost_before_confirm", "cancel"])
def test_recovery_failed_current_case_never_refunds_the_historical_charge(
    driver: SimpleNamespace,
    mode: str,
) -> None:
    driver.mode[0] = mode
    assert invoke_recovery() == 1
    result = report(driver)
    accounting = result["recovery_accounting"]
    assert accounting["prior_charged"] == accounting["current_charged"] == 1
    assert accounting["cumulative_charged"] == 2
    assert accounting["current_backend_confirmed"] == (0 if mode == "lost_before_confirm" else 1)
    assert result["controls_status"] == "NOT_QUALIFIED"
    assert len([event for event in driver.events if event[0] == "backend"]) == 1
    assert all(case["admission_submitted"] is False for case in result["cases"][1:])


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "restricted_reference_ec2_terminal_receipt_v1"),
        ("schema_version", True),
        ("final_report_sha256", "0" * 64),
        ("recovery_context", {}),
        ("recovery_accounting", {}),
        ("unexpected", True),
    ],
)
def test_recovery_terminal_receipt_cannot_drop_or_change_its_bound_history(
    driver: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: object,
) -> None:
    driver.receipt_changes[field] = value
    assert invoke_recovery() == 1
    assert report(driver)["controls_status"] == "NOT_QUALIFIED"
    assert capsys.readouterr().out == ""


def test_boolean_historical_terminal_charge_does_not_publish_success(
    driver: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    driver.mode[0] = "receipt_accounting_boolean"
    assert invoke_recovery() == 1
    assert report(driver)["controls_status"] == "NOT_QUALIFIED"
    assert capsys.readouterr().out == ""
