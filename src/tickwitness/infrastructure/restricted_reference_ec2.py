"""Fixed, owner-trusted EC2 qualification identity and one durable admission budget.

This is not a general remote provider or an execution backend. Trusted provisioning
must create the source lock before invocation. No import performs host operations.
"""

from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import http.client
import json
import os
import platform
import re
import secrets
import signal
import stat
import threading
import time
from pathlib import Path
from typing import cast

type Row = dict[str, object]
ROOT = Path("/var/lib/tickwitness-reference-ec2")
SOURCE_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_IDENTITY = {
    "instanceId": "i-0d79530ca78320939",
    "region": "ap-southeast-1",
    "imageId": "ami-09289bc217ad5e9e7",
    "instanceType": "m7i.2xlarge",
    "architecture": "x86_64",
}
SOURCE_FILES = (
    "src/tickwitness/infrastructure/restricted_reference_ec2.py",
    "scripts/qualify_restricted_reference_ec2.py",
    "scripts/prepare_reference_policy_ec2.py",
    "scripts/prepare_reference_policy.py",
    "scripts/qualify_restricted_reference.py",
    "src/tickwitness/infrastructure/restricted_reference.py",
    "src/tickwitness/infrastructure/restricted_reference_bootstrap.py",
    "scripts/restricted_reference_payload.py",
    "research/security/reference-ec2.apparmor",
)
WINDOW_NS = 600_000_000_000
SETUP_NS = 30_000_000_000
PROBE_NS = 10_000_000_000
MAX_ADMISSIONS = 24
FIXED_PROBES = (
    "positive", "filesystem", "readonly", "environment", "identity", "network_ipv4",
    "network_ipv6", "network_dns", "network_loopback", "inherited_fds", "memory", "pids",
    "disk_bytes", "inodes", "fds", "file_size", "cpu", "output_flood", "detached",
    "namespace_denial", "privileged_syscalls", "abi_denial", "malformed_output", "stdio_closed",
)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_STATE_KEYS = {
    "kind", "schema_version", "source_revision", "run_id", "boot_id", "owner",
    "started_ns", "deadline_ns", "setup_deadline_ns", "phase", "host_preparation_started",
    "provider_context", "policy_receipts", "charged", "backend_confirmed", "admissions",
    "poisoned", "outcome", "reason",
    "final_report_sha256",
}


def canonical(value: object) -> bytes:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return raw + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object, keys: set[str], label: str) -> Row:
    if not isinstance(value, dict) or set(value) != keys or any(
        not isinstance(key, str) for key in value
    ):
        raise ValueError("Invalid or unknown " + label + " fields")
    return cast(Row, value)


def _json(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> Row:
        result: Row = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    return cast(object, json.loads(raw, object_pairs_hook=pairs))


def _secure_directory(path: Path, *, create: bool = False) -> None:
    if not path.is_absolute():
        raise ValueError("Absolute trusted directory required")
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if not create:
                raise
            _secure_directory(part.parent, create=True)
            part.mkdir(mode=0o700)
            info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Untrusted directory ancestry: " + str(part))


def _secure_read(path: Path, limit: int) -> tuple[bytes, tuple[int, int, int, int, int]]:
    _secure_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not _regular_root(info) or info.st_size > limit:
            raise ValueError("Untrusted or oversized root file: " + str(path))
        raw = os.read(fd, limit + 1)
        after = os.fstat(fd)
        seal = (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_size)
        if len(raw) > limit or len(raw) != info.st_size or _stable(info) != _stable(after):
            raise ValueError("Trusted file changed during bounded read")
        return raw, seal
    finally:
        os.close(fd)


def _stable(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
        info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _regular_root(info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
        and not info.st_mode & 0o022
    )


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_exclusive(path: Path, raw: bytes) -> None:
    """Create a bounded root-owned observation, never replace a prior observation."""
    if len(raw) > 262_144:
        raise ValueError("Root evidence exceeds bound")
    _secure_directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _file_record(path: Path, limit: int) -> tuple[Row, tuple[int, int, int, int, int]]:
    raw, seal = _secure_read(path, limit)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}, seal


def _boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if not _BOOT.fullmatch(value):
        raise ValueError("Missing actual kernel boot identity")
    return value


def _owner() -> Row:
    # Field22 starttime binds this PID, not a recycled numeric PID.
    raw = Path("/proc/self/stat").read_text()
    fields = raw[raw.rfind(")") + 2:].split()
    if len(fields) < 20 or not fields[19].isdecimal():
        raise ValueError("Missing actual controller process identity")
    return {"pid": os.getpid(), "start_ticks": int(fields[19]), "uid": os.geteuid()}


def _host() -> Row:
    if platform.system() != "Linux" or platform.machine() != "x86_64" or os.geteuid() != 0:
        raise ValueError("Dedicated reference requires actual root Linux x86_64")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise ValueError("Dedicated reference requires actual Ubuntu24.04")
    label = Path("/proc/self/attr/current").read_text().strip()
    status = Path("/proc/self/status").read_text().splitlines()
    if label != "unconfined" or "NoNewPrivs:\t0" not in status:
        raise ValueError("Controller must retain original unconfined pre-NNP context")
    return {
        "system": platform.system(), "release": platform.release(), "version": platform.version(),
        "architecture": platform.machine(), "os_release": release, "boot_id": _boot_id(),
        "controller_uid": os.geteuid(), "controller_gid": os.getegid(), "controller_label": label,
    }


def _metadata(*, deadline_ns: int) -> bytes:
    """One direct bounded IMDSv2 PUT/GET. No redirect, proxy, retry or token storage."""
    deadline = min(deadline_ns, time.monotonic_ns() + 5_000_000_000)

    def request(method: str, path: str, headers: dict[str, str], limit: int) -> bytes:
        remaining = deadline - time.monotonic_ns()
        if remaining <= 0:
            raise TimeoutError("Original IMDS/setup deadline exhausted")
        connection = http.client.HTTPConnection("169.254.169.254", timeout=remaining / 1e9)
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("IMDSv2 refused fixed request")
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining = deadline - time.monotonic_ns()
                if remaining <= 0:
                    raise TimeoutError("Original IMDS/setup deadline exhausted")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining / 1e9)
                chunk = response.read1(min(4096, limit + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError("IMDSv2 response exceeds bound")
                chunks.append(chunk)
            if time.monotonic_ns() >= deadline:
                raise TimeoutError("Original IMDS/setup deadline exhausted")
            return b"".join(chunks)
        finally:
            connection.close()

    if threading.current_thread() is not threading.main_thread():
        raise ValueError("Bounded IMDS setup requires the trusted main controller thread")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise ValueError("Refusing to replace an existing controller alarm")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expired(_number: int, _frame: object) -> None:
        raise TimeoutError("Original combined IMDS/setup deadline exhausted")

    remaining = deadline - time.monotonic_ns()
    if remaining <= 0:
        raise TimeoutError("Original IMDS/setup deadline exhausted")
    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, remaining / 1e9)
        token_raw = request(
            "PUT", "/latest/api/token", {"X-aws-ec2-metadata-token-ttl-seconds": "60"}, 4096
        )
        token = token_raw.decode("ascii")
        if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ValueError("Invalid bounded IMDSv2 token")
        return request(
            "GET", "/latest/dynamic/instance-identity/document",
            {"X-aws-ec2-metadata-token": token}, 16384,
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


@dataclasses.dataclass(frozen=True)
class BudgetSnapshot:
    started_ns: int
    deadline_ns: int
    max_admissions: int
    charged: int
    backend_confirmed: int
    unconfirmed: int
    poisoned: bool
    pending_outcomes: int = 0


@dataclasses.dataclass(frozen=True)
class ProbeAdmission:
    run_id: str
    boot_id: str
    source_revision: str
    admission_number: int
    name: str
    nonce: str
    admitted_ns: int
    deadline_ns: int


class Ec2Run:
    """A non-reconstructible live claim; all durable charges precede backend calls."""

    source_revision: str
    run_id: str
    boot_id: str
    started_ns: int
    deadline_ns: int
    setup_deadline_ns: int
    run_dir: Path
    staged_policy: Path
    policy_evidence_dir: Path
    artifact_dir: Path
    _owner: Row
    _host: Row
    _lock_fd: int
    _fenced: bool
    _state: Row
    _claim_raw: bytes
    _seals: dict[str, tuple[Row, tuple[int, int, int, int, int]]]
    _source_lock: Row
    _provider_source: Row

    def __init__(self) -> None:
        raise TypeError("Use the exclusive Ec2Run.claim factory")

    @classmethod
    def claim(cls, *, source_revision: str, run_id: str) -> Ec2Run:
        if cls is not Ec2Run:
            raise TypeError("Only the fixed Ec2Run authority can claim this reference")
        if not _HEX40.fullmatch(source_revision) or not _HEX32.fullmatch(run_id):
            raise ValueError("Actual lowercase source commit and explicit32-hex run required")
        started = time.monotonic_ns()
        host = _host()
        owner = _owner()
        _secure_directory(ROOT, create=True)
        _secure_directory(ROOT / "runs", create=True)
        lock_path = ROOT / "host-admission.json"
        lock_fd = os.open(
            lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        instance: Ec2Run | None = None
        # The persistent host claim is intentionally never removed or automatically reused.
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            instance = object.__new__(cls)
            instance.source_revision = source_revision
            instance.run_id = run_id
            instance.boot_id = str(host["boot_id"])
            instance.started_ns = started
            instance.deadline_ns = started + WINDOW_NS
            instance.setup_deadline_ns = started + SETUP_NS
            instance.run_dir = ROOT / "runs" / run_id
            instance.staged_policy = instance.run_dir / "policy.apparmor"
            instance.policy_evidence_dir = instance.run_dir / "policy-evidence"
            instance.artifact_dir = instance.run_dir / "qualification"
            instance.run_dir.mkdir(mode=0o700)
            _fsync_dir(instance.run_dir.parent)
            instance._owner = {**owner, "invocation": secrets.token_hex(32)}
            instance._host = host
            instance._lock_fd = lock_fd
            instance._fenced = False
            instance._seals = {}
            instance._state = {
                "kind": "restricted_reference_ec2_run_v1", "schema_version": 1,
                "source_revision": source_revision, "run_id": run_id,
                "boot_id": instance.boot_id, "owner": instance._owner,
                "started_ns": started, "deadline_ns": instance.deadline_ns,
                "setup_deadline_ns": instance.setup_deadline_ns, "phase": "CLAIMED",
                "host_preparation_started": False, "provider_context": None,
                "policy_receipts": None, "charged": 0, "backend_confirmed": 0,
                "admissions": [], "poisoned": False, "outcome": None, "reason": None,
                "final_report_sha256": None,
            }
            claim = canonical({
                "kind": "restricted_reference_ec2_claim_v1", "schema_version": 1,
                "source_revision": source_revision, "run_id": run_id,
                "boot_id": instance.boot_id, "owner": instance._owner,
                "started_ns": started, "deadline_ns": instance.deadline_ns,
                "setup_deadline_ns": instance.setup_deadline_ns,
            })
            if os.write(lock_fd, claim) != len(claim):
                raise OSError("Partial durable host claim write")
            os.fsync(lock_fd)
            _fsync_dir(ROOT)
            write_exclusive(instance.run_dir / "claim.json", claim)
            write_exclusive(instance.run_dir / "state.json", canonical(instance._state))
            instance._claim_raw = claim
            instance._bind_source()
            instance.require_phase("CLAIMED")
            return instance
        except BaseException:
            if instance is not None and hasattr(instance, "_state"):
                try:
                    instance._state["phase"] = "TERMINAL"
                    instance._state["poisoned"] = True
                    instance._state["outcome"] = "NOT_QUALIFIED"
                    instance._state["reason"] = "claim_failed_or_uncertain"
                    instance._persist()
                except Exception:
                    pass
            os.close(lock_fd)
            # Every partially-created claim survives. Never erase an uncertain admission.
            raise

    def _bind_source(self) -> None:
        path = ROOT / "sources" / self.source_revision / "source-lock.json"
        raw, seal = _secure_read(path, 65536)
        document = _mapping(
            _json(raw), {"kind", "schema_version", "source_revision", "source_root", "files"},
            "source-lock",
        )
        if (
            document["kind"] != "restricted_reference_ec2_source_lock_v1"
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or document["source_revision"] != self.source_revision
            or document["source_root"] != str(SOURCE_ROOT)
        ):
            raise ValueError("Trusted actual source-lock identity differs")
        files = _mapping(document["files"], set(SOURCE_FILES), "source closure")
        self._seals[str(path)] = (
            {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}, seal
        )
        for relative in SOURCE_FILES:
            expected = _mapping(files[relative], {"sha256", "bytes"}, "source entry")
            if (
                not isinstance(expected["sha256"], str)
                or not _HEX64.fullmatch(expected["sha256"])
                or type(expected["bytes"]) is not int
                or not 0 < cast(int, expected["bytes"]) <= 1_048_576
            ):
                raise ValueError("Invalid actual source digest or length")
            source_path = SOURCE_ROOT / relative
            actual, source_seal = _file_record(source_path, 1_048_576)
            if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
                raise ValueError("Actual trusted source bytes differ")
            self._seals[str(source_path)] = (actual, source_seal)
        self._source_lock = self._seals[str(path)][0]
        self._provider_source = self._seals[
            str(SOURCE_ROOT / SOURCE_FILES[0])
        ][0]

    def _live(self) -> None:
        if self._fenced:
            raise ValueError("Durable claim is fenced after uncertain persistence")
        for field in (
            "source_revision", "run_id", "boot_id", "started_ns", "deadline_ns",
            "setup_deadline_ns",
        ):
            if getattr(self, field) != self._state[field]:
                raise ValueError("Original claim identity or clock cannot be reassigned")
        expected_dir = ROOT / "runs" / self.run_id
        if (
            self.run_dir != expected_dir or self.staged_policy != expected_dir / "policy.apparmor"
            or self.policy_evidence_dir != expected_dir / "policy-evidence"
            or self.artifact_dir != expected_dir / "qualification"
        ):
            raise ValueError("Fixed claim paths cannot be redirected")
        if _boot_id() != self.boot_id:
            self._state["phase"] = "TERMINAL"
            self._state["outcome"] = "NOT_QUALIFIED"
            self._poison("boot_identity_changed")
            raise ValueError("An earlier boot cannot resume its qualification")
        if _owner() != {key: self._owner[key] for key in ("pid", "start_ticks", "uid")}:
            raise ValueError("Claim owner invocation differs")
        info = os.fstat(self._lock_fd)
        current = (ROOT / "host-admission.json").lstat()
        if _stable(info) != _stable(current) or not _regular_root(info):
            raise ValueError("Live host claim identity differs")
        os.lseek(self._lock_fd, 0, os.SEEK_SET)
        if os.read(self._lock_fd, 65537) != self._claim_raw:
            raise ValueError("Live host claim contents differ")
        claim_raw, _ = _secure_read(self.run_dir / "claim.json", 65536)
        state_raw, _ = _secure_read(self.run_dir / "state.json", 262144)
        state = _mapping(_json(state_raw), _STATE_KEYS, "durable run")
        if claim_raw != self._claim_raw or canonical(state) != canonical(self._state):
            raise ValueError("Durable run identity or counters differ")

    def _persist(self) -> None:
        temporary = self.run_dir / ("state-next-" + secrets.token_hex(16) + ".json")
        try:
            write_exclusive(temporary, canonical(self._state))
            os.replace(temporary, self.run_dir / "state.json")
            _fsync_dir(self.run_dir)
        except BaseException:
            self._fenced = True
            # An exclusive, persistent marker prevents an uncertain write being retried.
            try:
                write_exclusive(self.run_dir / "persistence-uncertain", b"FENCED\n")
            except OSError:
                pass
            raise

    def _poison(self, reason: str) -> None:
        self._state["poisoned"] = True
        self._state["reason"] = reason[:2048]
        self._persist()

    def require_phase(self, phase: str) -> None:
        self._live()
        if self._state["phase"] != phase or self._state["poisoned"] is not False:
            if self._state["phase"] != "TERMINAL" and self._state["poisoned"] is False:
                self._poison("duplicate_or_out_of_order_phase_entry")
            raise ValueError("Qualification phase/poison fence refuses this operation")

    @property
    def provider_record(self) -> Row:
        value = self._state["provider_context"]
        record = _mapping(value, {
            "kind", "schema_version", "provider", "expected_identity", "observed_identity",
            "source_revision", "run_id", "boot_id", "host", "gha_metadata",
            "gha_metadata_reason", "provider_source", "source_lock", "identity_document",
        }, "provider context")
        if (
            record["kind"] != "restricted_reference_ec2_host_v1"
            or type(record["schema_version"]) is not int or record["schema_version"] != 1
            or record["provider"] != "aws_ec2_dedicated_v1"
            or record["source_revision"] != self.source_revision
            or record["run_id"] != self.run_id or record["boot_id"] != self.boot_id
            or record["gha_metadata"] is not None
            or record["gha_metadata_reason"] != "not_applicable_aws_ec2"
        ):
            raise ValueError("Unknown or mismatched fixed provider identity/schema")
        for field in ("expected_identity", "observed_identity"):
            identity = _mapping(record[field], set(EXPECTED_IDENTITY), field)
            if identity != EXPECTED_IDENTITY or any(
                type(value) is not str for value in identity.values()
            ):
                raise ValueError("Unknown/mismatched selected EC2 identity")
        host = _mapping(record["host"], {
            "system", "release", "version", "architecture", "os_release", "boot_id",
            "controller_uid", "controller_gid", "controller_label",
        }, "provider host")
        release = host["os_release"]
        if (
            host != self._host or host["system"] != "Linux" or host["architecture"] != "x86_64"
            or host["boot_id"] != self.boot_id or host["controller_label"] != "unconfined"
            or type(host["controller_uid"]) is not int or host["controller_uid"] != 0
            or type(host["controller_gid"]) is not int
            or not isinstance(host["release"], str) or not host["release"]
            or not isinstance(host["version"], str) or not host["version"]
            or not isinstance(release, dict) or release.get("ID") != "ubuntu"
            or release.get("VERSION_ID") != "24.04"
            or any(type(key) is not str or type(value) is not str for key, value in release.items())
        ):
            raise ValueError("Missing/mismatched actual provider host tuple")
        for field, path, limit in (
            ("provider_source", SOURCE_ROOT / SOURCE_FILES[0], 1_048_576),
            ("source_lock", ROOT / "sources" / self.source_revision / "source-lock.json", 65536),
            ("identity_document", self.run_dir / "instance-identity-document.json", 16384),
        ):
            item = _mapping(record[field], {"path", "sha256", "bytes"}, field)
            if (
                item["path"] != str(path) or not isinstance(item["sha256"], str)
                or not _HEX64.fullmatch(item["sha256"]) or type(item["bytes"]) is not int
                or not 0 < cast(int, item["bytes"]) <= limit
                or self._seals.get(str(path), (None, None))[0] != item
            ):
                raise ValueError("Unbound provider source/cache receipt")
        return cast(Row, _json(canonical(record)))

    def prepare_host(self) -> Row:
        self.require_phase("CLAIMED")
        if self._state["host_preparation_started"] is not False:
            raise ValueError("Host setup is single-use and cannot be retried")
        self._state["host_preparation_started"] = True
        self._persist()
        try:
            if time.monotonic_ns() >= self.setup_deadline_ns:
                raise TimeoutError("Original setup deadline exhausted")
            raw = _metadata(deadline_ns=self.setup_deadline_ns)
            document = _json(raw)
            if not isinstance(document, dict):
                raise ValueError("Missing actual instance identity document")
            observed: Row = {}
            for key, expected in EXPECTED_IDENTITY.items():
                if type(document.get(key)) is not str or document[key] != expected:
                    raise ValueError("Actual selected EC2 identity differs: " + key)
                observed[key] = document[key]
            path = self.run_dir / "instance-identity-document.json"
            write_exclusive(path, raw)
            iid_record, iid_seal = _file_record(path, 16384)
            self._seals[str(path)] = (iid_record, iid_seal)
            self._state["provider_context"] = {
                "kind": "restricted_reference_ec2_host_v1", "schema_version": 1,
                "provider": "aws_ec2_dedicated_v1", "expected_identity": dict(EXPECTED_IDENTITY),
                "observed_identity": observed, "source_revision": self.source_revision,
                "run_id": self.run_id, "boot_id": self.boot_id, "host": self._host,
                "gha_metadata": None, "gha_metadata_reason": "not_applicable_aws_ec2",
                "provider_source": self._provider_source, "source_lock": self._source_lock,
                "identity_document": iid_record,
            }
            self._persist()
            return self.revalidate(deadline_ns=self.setup_deadline_ns)
        except BaseException:
            self._poison("host_preparation_failed_or_uncertain")
            raise

    def revalidate(self, *, deadline_ns: int) -> Row:
        self._live()
        if (
            type(deadline_ns) is not int or deadline_ns > self.deadline_ns
            or time.monotonic_ns() >= deadline_ns or self._state["poisoned"] is not False
            or self._state["phase"] == "TERMINAL"
        ):
            raise ValueError("Original claim deadline/phase refuses admission")
        for path, (expected, seal) in self._seals.items():
            actual, actual_seal = _file_record(Path(path), 1_048_576)
            if actual != expected or actual_seal != seal:
                self._poison("trusted_source_or_cached_identity_changed")
                raise ValueError("Frozen trusted source or identity cache changed")
        return self.provider_record

    def policy_ready(self, *, preload_sha256: str, report_sha256: str) -> None:
        self.require_phase("CLAIMED")
        self.revalidate(deadline_ns=self.setup_deadline_ns)
        for name, digest in (
            ("preload-manifest.json", preload_sha256), ("policy-setup.json", report_sha256),
        ):
            if not _HEX64.fullmatch(digest):
                raise ValueError("Invalid policy receipt digest")
            record, _ = _file_record(self.policy_evidence_dir / name, 262144)
            if record["sha256"] != digest:
                raise ValueError("Actual policy receipt digest differs")
        self._state["policy_receipts"] = {
            "preload_sha256": preload_sha256, "report_sha256": report_sha256,
        }
        self._state["phase"] = "POLICY_READY"
        self._persist()

    def acquire_runner(self) -> BudgetSnapshot:
        self.require_phase("POLICY_READY")
        self.revalidate(deadline_ns=self.deadline_ns)
        self._state["phase"] = "QUALIFYING"
        self._persist()
        return self.snapshot()

    def snapshot(self) -> BudgetSnapshot:
        self._live()
        charged = cast(int, self._state["charged"])
        confirmed = cast(int, self._state["backend_confirmed"])
        return BudgetSnapshot(
            self.started_ns, self.deadline_ns, MAX_ADMISSIONS, charged, confirmed,
            charged - confirmed, self._state["poisoned"] is True,
            sum(row["outcome"] is None for row in self._admissions()),
        )

    def _admissions(self) -> list[Row]:
        return cast(list[Row], self._state["admissions"])

    def reserve_probe(self, *, name: str, nonce: str) -> ProbeAdmission:
        self.require_phase("QUALIFYING")
        self.revalidate(deadline_ns=self.deadline_ns)
        if not _HEX32.fullmatch(nonce):
            raise ValueError("Fixed probe identity/nonce missing")
        admissions = self._admissions()
        if (
            len(admissions) >= MAX_ADMISSIONS
            or name != FIXED_PROBES[len(admissions)]
            or any(row["name"] == name or row["nonce"] == nonce for row in admissions)
            or any(row["outcome"] is None for row in admissions)
        ):
            raise ValueError("Original shared admissions exhausted, duplicate or uncertain")
        admitted = time.monotonic_ns()
        if admitted >= self.deadline_ns:
            raise TimeoutError("Original qualification window exhausted before durable charge")
        ticket = ProbeAdmission(
            self.run_id, self.boot_id, self.source_revision, len(admissions) + 1, name, nonce,
            admitted, min(self.deadline_ns, admitted + PROBE_NS),
        )
        admissions.append({**dataclasses.asdict(ticket), "accepted": False, "outcome": None})
        self._state["charged"] = len(admissions)
        self._persist()  # durable charge occurs before any backend call
        return ticket

    def _ticket(self, admission: ProbeAdmission) -> Row:
        if type(admission) is not ProbeAdmission or not 1 <= admission.admission_number <= 24:
            raise ValueError("Actual durable admission ticket required")
        rows = self._admissions()
        if admission.admission_number > len(rows):
            raise ValueError("Admission was not durably submitted")
        row = rows[admission.admission_number - 1]
        ticket = dataclasses.asdict(admission)
        if {key: row[key] for key in ticket} != ticket:
            raise ValueError("Admission source/run/boot/deadline identity differs")
        return row

    def admit_probe(self, admission: ProbeAdmission) -> None:
        self.require_phase("QUALIFYING")
        row = self._ticket(admission)
        self.revalidate(deadline_ns=admission.deadline_ns)
        if row["accepted"] is not False or row["outcome"] is not None:
            raise ValueError("Durable admission cannot be accepted twice")
        row["accepted"] = True
        self._state["backend_confirmed"] = cast(int, self._state["backend_confirmed"]) + 1
        self._persist()

    def finish_probe(
        self, admission: ProbeAdmission, *, result_sha256: str, stop_confirmed: bool,
        cleanup_confirmed: bool, failure: str | None,
    ) -> None:
        self._live()
        row = self._ticket(admission)
        if (
            self._state["phase"] != "QUALIFYING" or row["accepted"] is not True
            or row["outcome"] is not None or not _HEX64.fullmatch(result_sha256)
            or type(stop_confirmed) is not bool or type(cleanup_confirmed) is not bool
            or (failure is not None and not isinstance(failure, str))
        ):
            raise ValueError("Probe outcome cannot replace or invent an admission")
        row["outcome"] = {
            "result_sha256": result_sha256, "stop_confirmed": stop_confirmed,
            "cleanup_confirmed": cleanup_confirmed, "failure": failure,
        }
        expected_termination = (
            admission.name in {"cpu", "detached"} and failure == "deadline_exceeded"
        ) or (
            admission.name == "output_flood" and failure in {"stdout_limit", "stderr_limit"}
        )
        if (
            (failure is not None and not expected_termination)
            or not stop_confirmed or not cleanup_confirmed
        ):
            self._state["poisoned"] = True
            self._state["reason"] = "probe_failed_or_stop_cleanup_uncertain"
        self._persist()

    def finish(
        self, *, outcome: str, reason: str | None, final_report_sha256: str | None = None,
    ) -> None:
        self._live()
        if self._state["phase"] == "TERMINAL":
            raise ValueError("Terminal run cannot be replaced or restarted")
        if outcome not in {"NOT_QUALIFIED", "QUALIFIED_REFERENCE_ONLY"}:
            raise ValueError("Unknown fixed qualification outcome")
        pending = any(row["outcome"] is None for row in self._admissions())
        if outcome == "QUALIFIED_REFERENCE_ONLY" and (
            self._state["phase"] != "QUALIFYING" or self._state["poisoned"] is not False
            or pending or len(self._admissions()) != len(FIXED_PROBES)
        ):
            raise ValueError("Incomplete/uncertain run cannot qualify")
        if outcome == "QUALIFIED_REFERENCE_ONLY":
            self._check_final_report(final_report_sha256)
        elif final_report_sha256 is not None:
            raise ValueError("Unqualified outcomes do not authenticate a successful report")
        self._state["poisoned"] = self._state["poisoned"] is True or pending
        self._state["phase"] = "TERMINAL"
        self._state["outcome"] = outcome
        self._state["reason"] = reason[:2048] if reason is not None else None
        self._state["final_report_sha256"] = final_report_sha256
        self._persist()

    def _check_final_report(self, digest: str | None) -> Row:
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise ValueError("Successful qualification requires a bound final report")
        raw, _ = _secure_read(self.run_dir / "qualification-report.json", 262144)
        report = _json(raw)
        if not isinstance(report, dict) or _sha(raw) != digest:
            raise ValueError("Final report and durable terminal digest differ")
        cases = report.get("cases")
        if (
            report.get("kind") != "restricted_reference_ec2_qualification_v1"
            or type(report.get("schema_version")) is not int or report.get("schema_version") != 1
            or report.get("source_revision") != self.source_revision
            or report.get("run_id") != self.run_id
            or report.get("boot_id") != self.boot_id
            or report.get("controls_status") != "QUALIFIED_REFERENCE_ONLY"
            or report.get("production_m1") != "DISABLED"
            or report.get("acceptance_gate") != "matching_durable_terminal_and_final_report_sha256"
            or report.get("admissions_charged") != MAX_ADMISSIONS
            or report.get("confirmed_backend_admissions") != MAX_ADMISSIONS
            or report.get("pending_probe_outcomes") != 0
            or type(report.get("pending_probe_outcomes")) is not int
            or report.get("durable_budget_status") != "CONFIRMED"
            or report.get("durable_budget") != dataclasses.asdict(self.snapshot())
            or report.get("failure") is not None
            or not isinstance(cases, list) or len(cases) != len(FIXED_PROBES)
        ):
            raise ValueError("Final report lacks complete matching scoped evidence")
        for name, case in zip(FIXED_PROBES, cases, strict=True):
            if (
                not isinstance(case, dict) or case.get("name") != name
                or case.get("status") != "PASS"
            ):
                raise ValueError("Final report has incomplete fixed-case evidence")
        return cast(Row, report)

    def qualification_receipt(self) -> Row:
        """A terminal outcome alone is insufficient: re-read its bound complete report."""
        self._live()
        if (
            self._state["phase"] != "TERMINAL"
            or self._state["outcome"] != "QUALIFIED_REFERENCE_ONLY"
            or self._state["poisoned"] is not False
        ):
            raise ValueError("No complete successful terminal qualification")
        digest = self._state["final_report_sha256"]
        self._check_final_report(cast(str | None, digest))
        return {
            "kind": "restricted_reference_ec2_terminal_receipt_v1", "schema_version": 1,
            "run_id": self.run_id, "source_revision": self.source_revision,
            "boot_id": self.boot_id, "final_report_sha256": digest,
            "controls_status": "QUALIFIED_REFERENCE_ONLY", "production_m1": "DISABLED",
        }
