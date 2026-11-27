"""Real filesystem preparation faults; synthetic pins never qualify an EC2 host."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tickwitness.infrastructure import restricted_reference_ec2 as ec2

SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_ec2_reference_recovery.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_recovery_preparation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preparation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparation)
REVISION = "a" * 40
NEW_BOOT = "22222222-2222-2222-2222-222222222222"
OLD_BOOT = "11111111-1111-1111-1111-111111111111"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def prepared_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """Replace host ownership/identity observations, not plan or durable file logic."""
    root = tmp_path / "root"
    source = tmp_path / "source"
    root.mkdir(mode=0o700)
    source.mkdir(mode=0o700)
    monkeypatch.setattr(ec2, "ROOT", root)
    monkeypatch.setattr(ec2, "SOURCE_ROOT", source)
    monkeypatch.setattr(preparation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(preparation.sys, "platform", "linux")
    monkeypatch.setattr(preparation.platform, "machine", lambda: "x86_64")
    boot = [NEW_BOOT]
    monkeypatch.setattr(
        ec2,
        "_host",
        lambda: {
            "system": "Linux",
            "release": "fixture-kernel",
            "version": "fixture-version",
            "architecture": "x86_64",
            "os_release": {"ID": "ubuntu", "VERSION_ID": "24.04"},
            "boot_id": boot[0],
            "controller_uid": 0,
            "controller_gid": 0,
            "controller_label": "unconfined",
        },
    )

    def directory(path: Path, *, create: bool = False) -> None:
        assert path == tmp_path or tmp_path in path.parents
        if create:
            path.mkdir(parents=True, exist_ok=True)
        for current in (path, *path.parents):
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
                raise ValueError("Untrusted fixture directory ancestry")
            if current == tmp_path:
                break

    monkeypatch.setattr(ec2, "_secure_directory", directory)
    monkeypatch.setattr(
        ec2,
        "_regular_root",
        lambda info: stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o022,
    )
    files = {}
    for relative in ec2.RECOVERY_SOURCE_FILES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (relative + "\n").encode()
        target.write_bytes(raw)
        files[relative] = {"sha256": _digest(raw), "bytes": len(raw)}
    lock_dir = root / "sources" / REVISION
    lock_dir.mkdir(parents=True)
    source_lock = lock_dir / "source-lock.json"
    source_lock.write_bytes(
        ec2.canonical(
            {
                "kind": "restricted_reference_ec2_recovery_source_lock_v1",
                "schema_version": 1,
                "source_revision": REVISION,
                "source_root": str(source),
                "files": files,
            }
        )
    )
    previous = dict(ec2.RECOVERY_PREDECESSOR)
    previous.update(source_revision="c" * 40, run_id="d" * 32, boot_id=OLD_BOOT)
    old_dir = root / "runs" / str(previous["run_id"])
    old_dir.mkdir(parents=True)
    owner = {"pid": 123, "start_ticks": 456, "uid": 0, "invocation": "e" * 64}
    identity = {key: previous[key] for key in ("source_revision", "run_id", "boot_id")}
    clocks = {
        "started_ns": 1000,
        "deadline_ns": 1000 + ec2.WINDOW_NS,
        "setup_deadline_ns": 1000 + ec2.SETUP_NS,
    }
    claim = {
        "kind": "restricted_reference_ec2_claim_v1",
        "schema_version": 1,
        **identity,
        **clocks,
        "owner": owner,
    }
    raw_claim = ec2.canonical(claim)
    host_claim = root / "host-admission.json"
    host_claim.write_bytes(raw_claim)
    host_claim.chmod(0o600)
    (old_dir / "claim.json").write_bytes(raw_claim)
    previous["host_claim_sha256"] = previous["claim_sha256"] = _digest(raw_claim)
    result = {
        "name": "positive",
        "nonce": "f" * 32,
        "payload_started": False,
        "started": True,
        "actual_exit_code": 2,
        "failure": "setup_refused",
        "stop_confirmed": True,
        "cleanup_confirmed": True,
    }
    raw_case = ec2.canonical(result)
    case_path = old_dir / "case-01.json"
    case_path.write_bytes(raw_case)
    previous["case_sha256"] = _digest(raw_case)
    admission = {
        **identity,
        "admission_number": 1,
        "name": "positive",
        "nonce": "f" * 32,
        "admitted_ns": 2000,
        "deadline_ns": 2000 + ec2.PROBE_NS,
        "accepted": True,
        "outcome": {
            "result_sha256": previous["case_sha256"],
            "stop_confirmed": True,
            "cleanup_confirmed": True,
            "failure": "setup_refused",
        },
    }
    state = {
        "kind": "restricted_reference_ec2_run_v1",
        "schema_version": 1,
        **identity,
        **clocks,
        "owner": owner,
        "phase": "TERMINAL",
        "host_preparation_started": True,
        "provider_context": None,
        "policy_receipts": None,
        "charged": 1,
        "backend_confirmed": 1,
        "admissions": [admission],
        "poisoned": True,
        "outcome": "NOT_QUALIFIED",
        "reason": "fixed_catalog_incomplete",
        "final_report_sha256": None,
    }
    state_path = old_dir / "state.json"
    state_path.write_bytes(ec2.canonical(state))
    previous["state_sha256"] = _digest(state_path.read_bytes())
    report = {
        "kind": "restricted_reference_ec2_qualification_v1",
        "schema_version": 1,
        **identity,
        "controls_status": "NOT_QUALIFIED",
        "admissions_charged": 1,
        "confirmed_backend_admissions": 1,
        "backend_unconfirmed_admissions": 0,
        "pending_probe_outcomes": 0,
        "observed_payload_starts": 0,
        "research_reservations": 0,
        "replay_engine_invocations": 0,
        "cases": [
            {"name": name, "admission_submitted": index == 0, "status": "UNKNOWN"}
            for index, name in enumerate(ec2.FIXED_PROBES)
        ],
    }
    report_path = old_dir / "qualification-report.json"
    report_path.write_bytes(ec2.canonical(report))
    previous["report_sha256"] = _digest(report_path.read_bytes())
    old_lock_dir = root / "sources" / str(previous["source_revision"])
    old_lock_dir.mkdir()
    old_lock = old_lock_dir / "source-lock.json"
    old_lock.write_bytes(
        ec2.canonical(
            {
                "kind": "restricted_reference_ec2_source_lock_v1",
                "schema_version": 1,
                "source_revision": previous["source_revision"],
                "source_root": "/opt/tickwitness-reference/" + str(previous["source_revision"]),
                "files": {},
            }
        )
    )
    previous["source_lock_sha256"] = _digest(old_lock.read_bytes())
    monkeypatch.setattr(ec2, "RECOVERY_PREDECESSOR", previous)
    evidence_dir = root / "recovery-evidence"
    evidence_dir.mkdir()
    stop = evidence_dir / "operator-stop.md"
    stop.write_bytes(b"trusted fixture owner Stop observation\n")
    monkeypatch.setattr(ec2, "RECOVERY_STOP_SHA256", _digest(stop.read_bytes()))

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Plan preparation cannot allocate clocks or qualification authority")

    monkeypatch.setattr(ec2.time, "monotonic_ns", forbidden)
    monkeypatch.setattr(ec2, "_metadata", forbidden)
    monkeypatch.setattr(ec2.Ec2Run, "claim", forbidden)
    monkeypatch.setattr(ec2.Ec2Run, "claim_recovery", forbidden)
    return SimpleNamespace(
        root=root,
        source=source,
        source_lock=source_lock,
        host_claim=host_claim,
        old_dir=old_dir,
        state=state,
        state_path=state_path,
        boot=boot,
        stop=stop,
        previous=previous,
    )


def prepare() -> dict[str, object]:
    return preparation.prepare_plan(source_revision=REVISION, plan_id=ec2.RECOVERY_PLAN_ID)


def test_preparation_creates_only_private_plan_and_retains_old_claim(prepared_host) -> None:
    original = prepared_host.host_claim.read_bytes()
    identity = prepared_host.host_claim.stat()
    previous_umask = os.umask(0o077)
    try:
        record = prepare()
        retained_umask = os.umask(0o077)
    finally:
        os.umask(previous_umask)
    path = prepared_host.root / "recovery-plan.json"
    raw = path.read_bytes()
    document = json.loads(raw)
    assert retained_umask == 0o077
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert document["plan_id"] == ec2.RECOVERY_PLAN_ID
    assert document["run_id"] == ec2.RECOVERY_RUN_ID
    assert document["source_revision"] == REVISION
    assert document["freeze_revision"] == ec2.RECOVERY_FREEZE_REVISION
    assert document["predecessor"] == prepared_host.previous
    assert document["allowance"] == ec2.RECOVERY_ALLOWANCE
    assert raw == ec2.canonical(document)
    assert record == {"path": str(path), "sha256": _digest(raw), "bytes": len(raw)}
    assert prepared_host.host_claim.read_bytes() == original
    assert prepared_host.host_claim.stat().st_ino == identity.st_ino
    assert prepared_host.host_claim.stat().st_mode == identity.st_mode
    assert not (prepared_host.root / "recovery-consumption.json").exists()
    assert not (prepared_host.root / "runs" / ec2.RECOVERY_RUN_ID).exists()


@pytest.mark.parametrize("name", ["recovery-plan.json", "recovery-consumption.json"])
@pytest.mark.parametrize("symlink", [False, True])
def test_existing_plan_or_consumption_is_never_followed_or_replaced(
    prepared_host,
    name,
    symlink,
) -> None:
    path = prepared_host.root / name
    target = prepared_host.root / "foreign-retained"
    if symlink:
        target.write_bytes(b"retained")
        path.symlink_to(target)
    else:
        path.write_bytes(b"")
    with pytest.raises(ValueError, match="Existing recovery"):
        prepare()
    assert path.is_symlink() is symlink
    if symlink:
        assert target.read_bytes() == b"retained"
    else:
        assert path.read_bytes() == b""


def test_read_only_host_mutex_blocks_a_concurrent_preparer(prepared_host) -> None:
    descriptor = os.open(prepared_host.host_claim, os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            prepare()
    finally:
        os.close(descriptor)
    assert not (prepared_host.root / "recovery-plan.json").exists()


def test_host_mutex_symlink_is_not_followed(prepared_host) -> None:
    original = prepared_host.host_claim.read_bytes()
    target = prepared_host.root / "foreign-host-claim"
    target.write_bytes(original)
    prepared_host.host_claim.unlink()
    prepared_host.host_claim.symlink_to(target)
    with pytest.raises(OSError):
        prepare()
    assert target.read_bytes() == original
    assert prepared_host.host_claim.is_symlink()
    assert not (prepared_host.root / "recovery-plan.json").exists()


def test_original_host_mutex_remains_locked_during_plan_publication(
    prepared_host,
    monkeypatch,
) -> None:
    writer = ec2.write_exclusive
    publications = []

    def write_under_lock(path, raw):
        descriptor = os.open(prepared_host.host_claim, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        publications.append(path)
        writer(path, raw)

    monkeypatch.setattr(ec2, "write_exclusive", write_under_lock)
    prepare()
    assert publications == [prepared_host.root / "recovery-plan.json"]


def test_consumption_appearing_during_validation_is_not_overwritten(
    prepared_host,
    monkeypatch,
) -> None:
    builder = ec2.recovery_plan_document
    consumption = prepared_host.root / "recovery-consumption.json"

    def consumed(**arguments):
        result = builder(**arguments)
        consumption.write_bytes(b"uncertain retained consumption")
        return result

    monkeypatch.setattr(ec2, "recovery_plan_document", consumed)
    with pytest.raises(ValueError, match="Existing recovery"):
        prepare()
    assert consumption.read_bytes() == b"uncertain retained consumption"
    assert not (prepared_host.root / "recovery-plan.json").exists()


def test_replaced_host_mutex_refuses_before_plan_publication(prepared_host, monkeypatch) -> None:
    builder = ec2.recovery_plan_document

    def replaced(**arguments):
        result = builder(**arguments)
        raw = prepared_host.host_claim.read_bytes()
        prepared_host.host_claim.unlink()
        prepared_host.host_claim.write_bytes(raw)
        return result

    monkeypatch.setattr(ec2, "recovery_plan_document", replaced)
    with pytest.raises(ValueError, match=r"Original host mutex.*(?:identity|root file)"):
        prepare()
    assert not (prepared_host.root / "recovery-plan.json").exists()


def test_same_boot_cannot_prepare_another_qualification(prepared_host) -> None:
    prepared_host.boot[0] = OLD_BOOT
    with pytest.raises(ValueError, match="boot"):
        prepare()
    assert not (prepared_host.root / "recovery-plan.json").exists()


@pytest.mark.parametrize("changed", ["source", "history", "stop"])
def test_unbound_source_history_or_stop_bytes_cannot_prepare_plan(prepared_host, changed) -> None:
    target = {
        "source": prepared_host.source / "scripts/prepare_ec2_reference_recovery.py",
        "history": prepared_host.state_path,
        "stop": prepared_host.stop,
    }[changed]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError):
        prepare()
    assert not (prepared_host.root / "recovery-plan.json").exists()


@pytest.mark.parametrize(
    "changed", ["old_kind", "unknown_field", "missing_helper", "boolean_schema"]
)
def test_non_recovery_or_ambiguous_source_lock_never_creates_plan(prepared_host, changed) -> None:
    document = json.loads(prepared_host.source_lock.read_bytes())
    if changed == "old_kind":
        document["kind"] = "restricted_reference_ec2_source_lock_v1"
    elif changed == "unknown_field":
        document["extra_authority"] = True
    elif changed == "missing_helper":
        del document["files"]["scripts/prepare_ec2_reference_recovery.py"]
    else:
        document["schema_version"] = True
    prepared_host.source_lock.write_bytes(ec2.canonical(document))
    with pytest.raises(ValueError):
        prepare()
    assert not (prepared_host.root / "recovery-plan.json").exists()


def test_pending_predecessor_outcome_is_refused_even_with_matching_fixture_hash(
    prepared_host,
    monkeypatch,
) -> None:
    prepared_host.state["admissions"][0]["outcome"] = None
    prepared_host.state_path.write_bytes(ec2.canonical(prepared_host.state))
    previous = {
        **prepared_host.previous,
        "state_sha256": _digest(prepared_host.state_path.read_bytes()),
    }
    monkeypatch.setattr(ec2, "RECOVERY_PREDECESSOR", previous)
    with pytest.raises(ValueError, match=r"pending|unknown"):
        prepare()
    assert not (prepared_host.root / "recovery-plan.json").exists()


def test_nonroot_preparation_refuses_before_plan_write(prepared_host, monkeypatch) -> None:
    monkeypatch.setattr(preparation.os, "geteuid", lambda: 1000)
    with pytest.raises(ValueError, match="root Linux"):
        prepare()
    assert not (prepared_host.root / "recovery-plan.json").exists()


@pytest.mark.parametrize("changed", ["platform", "architecture"])
def test_unsupported_local_host_observation_refuses_preparation(
    prepared_host,
    monkeypatch,
    changed,
) -> None:
    if changed == "platform":
        monkeypatch.setattr(preparation.sys, "platform", "darwin")
    else:
        monkeypatch.setattr(preparation.platform, "machine", lambda: "aarch64")
    with pytest.raises(ValueError, match="root Linux"):
        prepare()
    assert not (prepared_host.root / "recovery-plan.json").exists()


@pytest.mark.parametrize(
    "source_revision,plan_id",
    [
        ("A" * 40, ec2.RECOVERY_PLAN_ID),
        (REVISION, "alternate-plan"),
        ("../other", ec2.RECOVERY_PLAN_ID),
    ],
)
def test_fixed_source_and_plan_identity_are_required(
    prepared_host,
    source_revision,
    plan_id,
) -> None:
    with pytest.raises(ValueError, match="fixed plan"):
        preparation.prepare_plan(source_revision=source_revision, plan_id=plan_id)
    assert not (prepared_host.root / "recovery-plan.json").exists()


def test_uncertain_parent_fsync_preserves_plan_and_refuses_repreparation(
    prepared_host,
    monkeypatch,
) -> None:
    def uncertain(_path):
        raise OSError("injected uncertain plan directory durability")

    monkeypatch.setattr(ec2, "_fsync_dir", uncertain)
    with pytest.raises(OSError, match="uncertain"):
        prepare()
    path = prepared_host.root / "recovery-plan.json"
    retained = path.read_bytes()
    with pytest.raises(ValueError, match="Existing recovery"):
        prepare()
    assert path.read_bytes() == retained
    assert not (prepared_host.root / "recovery-consumption.json").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--source", REVISION, "--plan-id", ec2.RECOVERY_PLAN_ID],
        ["--source-revision", REVISION, "--plan", ec2.RECOVERY_PLAN_ID],
        [
            "--source-revision",
            REVISION,
            "--plan-id",
            ec2.RECOVERY_PLAN_ID,
            "--path",
            "/tmp/other",
        ],
    ],
)
def test_unknown_cli_options_never_prepare(arguments, monkeypatch) -> None:
    def forbidden(**_kwargs):
        raise AssertionError("Unknown options cannot reach plan preparation")

    monkeypatch.setattr(preparation, "prepare_plan", forbidden)
    with pytest.raises(SystemExit) as exited:
        preparation.main(arguments)
    assert exited.value.code == 2


def test_successful_cli_reports_preparation_only(prepared_host, capsys) -> None:
    assert preparation.main(["--source-revision", REVISION, "--plan-id", ec2.RECOVERY_PLAN_ID]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PREPARED_ONLY"
    assert result["qualification_started"] is False
    assert result["production_m1"] == "DISABLED"
    assert result["plan"]["sha256"] == _digest(
        (prepared_host.root / "recovery-plan.json").read_bytes()
    )
