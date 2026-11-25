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
    ],
)
def test_unknown_or_abbreviated_options_cannot_claim(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    def forbidden_claim(**kwargs: object) -> None:
        raise AssertionError("Invalid CLI cannot claim qualification authority")

    monkeypatch.setattr(qualification.Ec2Run, "claim", forbidden_claim)
    with pytest.raises(SystemExit) as exited:
        qualification.main(arguments)
    assert exited.value.code == 2


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    events = []
    mode = ["pass"]

    class Run:
        run_dir = tmp_path
        artifact_dir = tmp_path / "artifacts"
        source_revision = REVISION
        run_id = RUN_ID
        boot_id = "actual-fake-boot"
        started_ns = 1000
        deadline_ns = 10**30
        provider_record = {"provider": "fake unit fixture"}
        charged = 0
        confirmed = 0
        outcomes = 0
        finished = []

        def snapshot(self) -> BudgetSnapshot:
            if mode[0] == "reserve_persist_uncertain" and self.charged:
                raise ValueError("injected fenced durable counters")
            return BudgetSnapshot(
                self.started_ns, self.deadline_ns, 24, self.charged, self.confirmed,
                self.charged - self.confirmed, False,
                self.charged - self.outcomes,
            )

        def reserve_probe(self, *, name: str, nonce: str) -> ProbeAdmission:
            self.charged += 1
            events.append(("reserve", name, self.charged))
            if mode[0] == "reserve_persist_uncertain":
                raise OSError("injected uncertain submitted ticket")
            return ProbeAdmission(
                RUN_ID, self.boot_id, REVISION, self.charged, name, nonce, 1000, 10**30,
            )

        def finish(
            self, *, outcome: str, reason: str | None, final_report_sha256: str | None = None,
        ) -> None:
            if outcome == "QUALIFIED_REFERENCE_ONLY":
                assert final_report_sha256 == qualification.hashlib.sha256(
                    (tmp_path / "qualification-report.json").read_bytes()
                ).hexdigest()
                assert mode[0] != "terminal_failure" or self.charged == 24
                if mode[0] == "terminal_failure":
                    raise OSError("injected terminal write failure")
            self.finished.append((outcome, reason))
            events.append(("finish", outcome))

        def qualification_receipt(self) -> dict[str, object]:
            if mode[0] == "receipt_failure":
                raise OSError("injected final receipt failure")
            return {"controls_status": "QUALIFIED_REFERENCE_ONLY"}

    run = Run()

    def claim(*, source_revision: str, run_id: str) -> Run:
        assert source_revision == REVISION and run_id == RUN_ID
        events.append(("claim", source_revision, run_id))
        return run

    def prepare_policy(*, ec2_run: Run) -> dict[str, object]:
        assert ec2_run is run
        events.append(("loader",))
        if mode[0] == "setup_failure":
            raise ValueError("injected loader refusal")
        return {}

    def assess_probe(
        result: dict[str, object], name: str, nonce: str, manifest: str,
    ) -> dict[str, object]:
        assert result["name"] == name and result["nonce"] == nonce and manifest == "d" * 64
        return {"status": "FAIL" if mode[0] == "fail" else "PASS", "reason": "unit fixture"}

    class Runner:
        manifest = {"fixed_cases": list(qualification.PROBE_NAMES)}
        manifest_sha256 = "d" * 64

        def __init__(self, artifact: Path, payload: Path, *, ec2_run: Run) -> None:
            assert artifact == run.artifact_dir and ec2_run is run
            assert payload.name == "restricted_reference_payload.py"
            events.append(("runner",))

        def run_probe(
            self, name: str, *, arguments: tuple[str, ...], ec2_admission: ProbeAdmission,
        ) -> dict[str, object]:
            assert run.charged == ec2_admission.admission_number
            report = json.loads((tmp_path / "qualification-report.json").read_bytes())
            assert report["admissions_charged"] == run.charged
            events.append(("backend", name))
            if mode[0] == "lost_before_confirm":
                raise OSError("injected backend loss")
            run.confirmed += 1
            if mode[0] == "cancel":
                raise InterruptedError("injected cancellation")
            run.outcomes += 1
            return {"name": name, "nonce": arguments[0], "payload_started": True}

    monkeypatch.setattr(qualification, "Ec2Run", SimpleNamespace(claim=claim))
    monkeypatch.setattr(qualification, "ReferenceRunner", Runner)
    monkeypatch.setattr(
        qualification, "_script",
        lambda name: SimpleNamespace(prepare_policy=prepare_policy)
        if name == "prepare_reference_policy_ec2.py"
        else SimpleNamespace(assess_probe=assess_probe),
    )
    return SimpleNamespace(run=run, events=events, mode=mode, path=tmp_path)


def invoke() -> int:
    return qualification.main(["--source-revision", REVISION, "--run-id", RUN_ID])


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


@pytest.mark.parametrize("mode", ["fail", "lost_before_confirm", "cancel"])
def test_failures_preserve_submitted_charge_and_stop_the_catalog(
    driver: SimpleNamespace, mode: str,
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
    driver: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
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
    driver: SimpleNamespace, mode: str,
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
        qualification.main([
            "--source-revision", REVISION, "--run-id", RUN_ID, "--evidence-dir", "/tmp/other",
        ])
    assert error.value.code == 2
