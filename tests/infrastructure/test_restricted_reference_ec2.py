"""Fault tests use a fake trusted host; they are not reference qualification evidence."""

from __future__ import annotations

import dataclasses
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

REVISION = "a" * 40
RUN_ID = "b" * 32
BOOT = "11111111-1111-1111-1111-111111111111"
DIGEST = "c" * 64


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """Only root filesystem/host observations are replaced; durable state logic is real."""
    root = tmp_path / "root"
    source = tmp_path / "source"
    source.mkdir()
    clock = [1000]
    boot = [BOOT]
    monkeypatch.setattr(ec2, "ROOT", root)
    monkeypatch.setattr(ec2, "SOURCE_ROOT", source)
    monkeypatch.setattr(ec2.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(ec2, "_boot_id", lambda: boot[0])
    monkeypatch.setattr(ec2, "_owner", lambda: {"pid": 123, "start_ticks": 456, "uid": 0})
    monkeypatch.setattr(
        ec2,
        "_host",
        lambda: {
            "boot_id": boot[0],
            "system": "Linux",
            "release": "fixture-release",
            "version": "fixture-version",
            "architecture": "x86_64",
            "os_release": {"ID": "ubuntu", "VERSION_ID": "24.04"},
            "controller_uid": 0,
            "controller_gid": 0,
            "controller_label": "unconfined",
        },
    )

    def directory(path: Path, *, create: bool = False) -> None:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        assert path.is_dir() and not path.is_symlink()

    monkeypatch.setattr(ec2, "_secure_directory", directory)
    monkeypatch.setattr(
        ec2,
        "_regular_root",
        lambda info: stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o022,
    )
    files = {}
    for relative in ec2.SOURCE_FILES:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (relative + "\n").encode()
        path.write_bytes(raw)
        files[relative] = {"sha256": ec2._sha(raw), "bytes": len(raw)}
    lock_dir = root / "sources" / REVISION
    lock_dir.mkdir(parents=True)
    lock = lock_dir / "source-lock.json"
    lock.write_bytes(
        ec2.canonical(
            {
                "kind": "restricted_reference_ec2_source_lock_v1",
                "schema_version": 1,
                "source_revision": REVISION,
                "source_root": str(source),
                "files": files,
            }
        )
    )
    requests = []

    def metadata(*, deadline_ns: int) -> bytes:
        requests.append(deadline_ns)
        return ec2.canonical({**ec2.EXPECTED_IDENTITY, "privateIp": "10.0.0.1"})

    monkeypatch.setattr(ec2, "_metadata", metadata)
    return SimpleNamespace(
        root=root,
        source=source,
        clock=clock,
        boot=boot,
        lock=lock,
        requests=requests,
    )


def prepared(host: SimpleNamespace) -> ec2.Ec2Run:
    run = ec2.Ec2Run.claim(source_revision=REVISION, run_id=RUN_ID)
    run.prepare_host()
    run.policy_evidence_dir.mkdir()
    preload = b"preload\n"
    report = b"report\n"
    (run.policy_evidence_dir / "preload-manifest.json").write_bytes(preload)
    (run.policy_evidence_dir / "policy-setup.json").write_bytes(report)
    run.policy_ready(preload_sha256=ec2._sha(preload), report_sha256=ec2._sha(report))
    return run


def test_original_anchors_survive_setup_and_runner(host: SimpleNamespace) -> None:
    run = prepared(host)
    host.clock[0] += 20_000_000_000
    budget = run.acquire_runner()
    assert budget.started_ns == 1000
    assert budget.deadline_ns == 1000 + ec2.WINDOW_NS
    assert run.setup_deadline_ns == 1000 + ec2.SETUP_NS
    assert budget.charged == 0
    assert not run.artifact_dir.exists()


def test_submitted_ticket_is_durable_before_backend_and_never_refunded(
    host: SimpleNamespace,
) -> None:
    run = prepared(host)
    run.acquire_runner()
    ticket = run.reserve_probe(name="positive", nonce="1" * 32)
    durable = json.loads((run.run_dir / "state.json").read_bytes())
    assert durable["charged"] == 1
    assert durable["backend_confirmed"] == 0
    assert durable["admissions"][0]["outcome"] is None
    with pytest.raises(ValueError, match="uncertain"):
        run.reserve_probe(name="filesystem", nonce="2" * 32)
    run.finish(outcome="NOT_QUALIFIED", reason="backend_lost")
    assert run.snapshot().charged == 1
    assert run.snapshot().unconfirmed == 1
    assert run.snapshot().poisoned
    assert ticket.deadline_ns == ticket.admitted_ns + ec2.PROBE_NS


def test_ticket_cannot_be_changed_or_accepted_twice(host: SimpleNamespace) -> None:
    run = prepared(host)
    run.acquire_runner()
    ticket = run.reserve_probe(name="positive", nonce="1" * 32)
    with pytest.raises(ValueError, match="identity differs"):
        run.admit_probe(dataclasses.replace(ticket, deadline_ns=ticket.deadline_ns + 1))
    run.admit_probe(ticket)
    with pytest.raises(ValueError, match="twice"):
        run.admit_probe(ticket)
    assert run.snapshot().charged == run.snapshot().backend_confirmed == 1


def test_duplicate_constructor_poison_does_not_reset(host: SimpleNamespace) -> None:
    run = prepared(host)
    run.acquire_runner()
    run.reserve_probe(name="positive", nonce="1" * 32)
    with pytest.raises(ValueError, match="phase"):
        run.acquire_runner()
    assert run.snapshot().charged == 1
    assert run.snapshot().poisoned
    assert run.snapshot().started_ns == 1000


def test_clock_crossing_during_revalidation_never_grants_a_late_slot(
    host: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = prepared(host)
    run.acquire_runner()
    revalidate = run.revalidate

    def cross_deadline(*, deadline_ns: int) -> dict[str, object]:
        row = revalidate(deadline_ns=deadline_ns)
        host.clock[0] = run.deadline_ns
        return row

    monkeypatch.setattr(run, "revalidate", cross_deadline)
    with pytest.raises(TimeoutError, match="before durable charge"):
        run.reserve_probe(name="positive", nonce="1" * 32)
    assert run.snapshot().charged == 0
    assert json.loads((run.run_dir / "state.json").read_bytes())["charged"] == 0


def test_persistent_host_and_selected_run_are_never_automatically_reused(
    host: SimpleNamespace,
) -> None:
    run = prepared(host)
    run.finish(outcome="NOT_QUALIFIED", reason="done")
    old_claim = (run.run_dir / "claim.json").read_bytes()
    with pytest.raises(FileExistsError):
        ec2.Ec2Run.claim(source_revision=REVISION, run_id="d" * 32)
    assert (run.run_dir / "claim.json").read_bytes() == old_claim


def test_cross_boot_records_terminal_uncertainty(host: SimpleNamespace) -> None:
    run = prepared(host)
    run.acquire_runner()
    run.reserve_probe(name="positive", nonce="1" * 32)
    host.boot[0] = "22222222-2222-2222-2222-222222222222"
    with pytest.raises(ValueError, match="earlier boot"):
        run.revalidate(deadline_ns=run.deadline_ns)
    state = json.loads((run.run_dir / "state.json").read_bytes())
    assert state["poisoned"] is True
    assert state["charged"] == 1
    assert state["boot_id"] == BOOT
    assert state["phase"] == "TERMINAL"


def test_source_unknown_fields_refuse_and_preserve_failed_claim(host: SimpleNamespace) -> None:
    lock = json.loads(host.lock.read_bytes())
    lock["provider_override"] = "anything"
    host.lock.write_bytes(ec2.canonical(lock))
    with pytest.raises(ValueError, match="unknown"):
        ec2.Ec2Run.claim(source_revision=REVISION, run_id=RUN_ID)
    state = json.loads((host.root / "runs" / RUN_ID / "state.json").read_bytes())
    assert state["poisoned"] is True
    assert state["phase"] == "TERMINAL"
    assert state["charged"] == 0


def test_fifo_source_lock_is_refused_without_blocking_before_type_check(
    host: SimpleNamespace,
) -> None:
    host.lock.unlink()
    os.mkfifo(host.lock, mode=0o600)
    with pytest.raises(ValueError, match="Untrusted"):
        ec2.Ec2Run.claim(source_revision=REVISION, run_id=RUN_ID)
    assert json.loads((host.root / "runs" / RUN_ID / "state.json").read_bytes())["poisoned"]


def test_revalidation_is_cached_and_detects_changed_source(host: SimpleNamespace) -> None:
    run = prepared(host)
    first = run.provider_record
    assert run.revalidate(deadline_ns=run.deadline_ns) == first
    assert len(host.requests) == 1
    (host.source / ec2.SOURCE_FILES[0]).write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="changed"):
        run.revalidate(deadline_ns=run.deadline_ns)
    assert len(host.requests) == 1
    assert run.snapshot().poisoned


@pytest.mark.parametrize("field,value", [("unexpected", True), ("schema_version", True)])
def test_provider_record_has_explicit_strict_schema_even_in_own_durable_state(
    host: SimpleNamespace,
    field: str,
    value: object,
) -> None:
    run = prepared(host)
    run._state["provider_context"][field] = value
    run._persist()
    with pytest.raises(ValueError, match=r"[Uu]nknown"):
        run.revalidate(deadline_ns=run.deadline_ns)


def test_loader_repeat_and_metadata_mismatch_do_not_retry(
    host: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def wrong(*, deadline_ns: int) -> bytes:
        calls.append(deadline_ns)
        return ec2.canonical({**ec2.EXPECTED_IDENTITY, "instanceId": "i-wrong"})

    monkeypatch.setattr(ec2, "_metadata", wrong)
    run = ec2.Ec2Run.claim(source_revision=REVISION, run_id=RUN_ID)
    with pytest.raises(ValueError, match="identity differs"):
        run.prepare_host()
    with pytest.raises(ValueError, match="poison"):
        run.prepare_host()
    assert len(calls) == 1
    assert run.snapshot().poisoned


def test_persistence_failure_fences_original_charge(
    host: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = prepared(host)
    run.acquire_runner()

    def failed_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected fsync/replace uncertainty")

    monkeypatch.setattr(ec2.os, "replace", failed_replace)
    with pytest.raises(OSError, match="uncertainty"):
        run.reserve_probe(name="positive", nonce="1" * 32)
    assert (run.run_dir / "persistence-uncertain").read_bytes() == b"FENCED\n"
    assert run._state["charged"] == 1
    with pytest.raises(ValueError, match="fenced"):
        run.snapshot()


def test_outcome_failure_poison_and_partial_catalog_cannot_qualify(host: SimpleNamespace) -> None:
    run = prepared(host)
    run.acquire_runner()
    ticket = run.reserve_probe(name="positive", nonce="1" * 32)
    run.admit_probe(ticket)
    run.finish_probe(
        ticket,
        result_sha256=DIGEST,
        stop_confirmed=False,
        cleanup_confirmed=False,
        failure="setup_refused",
    )
    assert run.snapshot().charged == 1
    assert run.snapshot().poisoned
    with pytest.raises(ValueError, match="Incomplete"):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None)


def test_only_catalog_specific_controlled_termination_preserves_admissions(
    host: SimpleNamespace,
) -> None:
    run = prepared(host)
    run.acquire_runner()
    for index, name in enumerate(ec2.FIXED_PROBES):
        ticket = run.reserve_probe(name=name, nonce=f"{index + 1:032x}")
        run.admit_probe(ticket)
        failure = (
            "deadline_exceeded"
            if name in {"cpu", "detached"}
            else ("stdout_limit" if name == "output_flood" else None)
        )
        run.finish_probe(
            ticket,
            result_sha256=DIGEST,
            stop_confirmed=True,
            cleanup_confirmed=True,
            failure=failure,
        )
        assert not run.snapshot().poisoned
    assert run.snapshot().charged == 24
    assert run.snapshot().pending_outcomes == 0
    with pytest.raises(ValueError, match="bound final report"):
        run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None)
    report = {
        "kind": "restricted_reference_ec2_qualification_v1",
        "schema_version": 1,
        "source_revision": REVISION,
        "run_id": RUN_ID,
        "boot_id": BOOT,
        "controls_status": "QUALIFIED_REFERENCE_ONLY",
        "production_m1": "DISABLED",
        "acceptance_gate": "matching_durable_terminal_and_final_report_sha256",
        "admissions_charged": 24,
        "confirmed_backend_admissions": 24,
        "pending_probe_outcomes": 0,
        "durable_budget": dataclasses.asdict(run.snapshot()),
        "durable_budget_status": "CONFIRMED",
        "cases": [{"name": name, "status": "PASS"} for name in ec2.FIXED_PROBES],
    }
    raw = ec2.canonical(report)
    final_path = run.run_dir / "qualification-report.json"
    final_path.write_bytes(raw)
    run.finish(outcome="QUALIFIED_REFERENCE_ONLY", reason=None, final_report_sha256=ec2._sha(raw))
    assert run.qualification_receipt()["final_report_sha256"] == ec2._sha(raw)
    report["failure"] = "injected publication uncertainty"
    final_path.write_bytes(ec2.canonical(report))
    with pytest.raises(ValueError, match="digest differ"):
        run.qualification_receipt()


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_metadata_combined_alarm_bounds_slow_drip(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    clock = [0]
    handlers = {}
    timers = []
    calls = []

    def get_handler(number: int) -> object:
        return handlers.get(number, ec2.signal.SIG_DFL)

    def set_handler(number: int, handler: object) -> object:
        old = get_handler(number)
        handlers[number] = handler
        return old

    def expire() -> None:
        clock[0] = 5_000_000_001
        handlers[ec2.signal.SIGALRM](ec2.signal.SIGALRM, None)

    class Response:
        status = 200

        def read1(self, _limit: int) -> bytes:
            if stage == "body":
                expire()
            return b""

    class Connection:
        sock = None

        def __init__(self, endpoint: str, *, timeout: float) -> None:
            assert endpoint == "169.254.169.254"
            assert timeout <= 5

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            calls.append((method, path, headers))

        def getresponse(self) -> Response:
            if stage == "headers":
                expire()
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(ec2.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(ec2.signal, "getitimer", lambda _timer: (0.0, 0.0))
    monkeypatch.setattr(ec2.signal, "getsignal", get_handler)
    monkeypatch.setattr(ec2.signal, "signal", set_handler)
    monkeypatch.setattr(ec2.signal, "setitimer", lambda *args: timers.append(args))
    monkeypatch.setattr(ec2.http.client, "HTTPConnection", Connection)
    with pytest.raises(TimeoutError, match="combined"):
        ec2._metadata(deadline_ns=30_000_000_000)
    assert len(calls) == 1
    assert calls[0][0] == "PUT"
    assert timers[0] == (ec2.signal.ITIMER_REAL, 5.0)
    assert timers[-1] == (ec2.signal.ITIMER_REAL, 0)
    assert handlers[ec2.signal.SIGALRM] == ec2.signal.SIG_DFL


def test_duplicate_json_and_existing_controller_alarm_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        ec2._json(b'{"schema_version":1,"schema_version":2}')
    monkeypatch.setattr(ec2.signal, "getitimer", lambda _timer: (1.0, 0.0))
    with pytest.raises(ValueError, match="existing controller alarm"):
        ec2._metadata(deadline_ns=ec2.time.monotonic_ns() + ec2.SETUP_NS)


@pytest.mark.parametrize(
    "fault,expected_calls",
    [
        ("redirect", 1),
        ("oversized_token", 1),
        ("oversized_iid", 2),
    ],
)
def test_metadata_does_not_redirect_retry_or_exceed_body_caps(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    expected_calls: int,
) -> None:
    calls = []

    class Response:
        def __init__(self, payload: bytes, status: int = 200) -> None:
            self.payload = payload
            self.status = status

        def read1(self, limit: int) -> bytes:
            chunk, self.payload = self.payload[:limit], self.payload[limit:]
            return chunk

    class Connection:
        sock = None

        def __init__(self, endpoint: str, *, timeout: float) -> None:
            assert endpoint == "169.254.169.254" and timeout <= 5

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            calls.append((method, path, headers))

        def getresponse(self) -> Response:
            if fault == "redirect":
                return Response(b"", status=302)
            if len(calls) == 1:
                return Response(b"t" * (4097 if fault == "oversized_token" else 32))
            return Response(b"d" * 16385)

        def close(self) -> None:
            pass

    monkeypatch.setattr(ec2.http.client, "HTTPConnection", Connection)
    with pytest.raises(ValueError, match=r"refused|exceeds"):
        ec2._metadata(deadline_ns=ec2.time.monotonic_ns() + ec2.SETUP_NS)
    assert len(calls) == expected_calls
    assert calls[0][0] == "PUT"
    if len(calls) == 2:
        assert calls[1][0] == "GET"
