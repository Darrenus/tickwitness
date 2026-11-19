#!/usr/bin/env python3
"""Prepare the one frozen AppArmor userns authorization on a fresh remote VM.

This trusted-host setup adds one selected policy. It neither qualifies the
reference launcher nor enables product M1, and it never replaces global policy.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

PROFILE_NAME = "tickwitness-reference-bwrap"
ATTACHMENT = "/usr/bin/bwrap"
POLICY_SHA256 = "a71430ec3060e80404e01d2ece292ef9569837eb5e679deccd7fd8d9d8be9427"
POLICY_SOURCE = Path(__file__).resolve().parents[1] / "research/security/reference-bwrap.apparmor"
STAGED_POLICY = Path("/etc/apparmor.d/tickwitness-reference-bwrap")
EVIDENCE = Path("/tmp/tickwitness-reference-policy-evidence")
PARSER = Path("/usr/sbin/apparmor_parser")
DPKG = Path("/usr/bin/dpkg-query")
ABI = Path("/etc/apparmor.d/abi/4.0")
PARSER_CONFIG = Path("/etc/apparmor/parser.conf")
LIBAPPARMOR = Path("/usr/lib/x86_64-linux-gnu/libapparmor.so.1")
FEATURE_ROOT = Path("/sys/kernel/security/apparmor/features")
PROFILE_TABLE = Path("/sys/kernel/security/apparmor/profiles")
PROFILE_ROOT = Path("/sys/kernel/security/apparmor/policy/profiles")
RESTRICT = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
WINDOW_NS = 30_000_000_000
STREAM_LIMIT = 65_536
DOCUMENT_LIMIT = 262_144
SUCCESS_FIELDS = {
    "kind", "schema_version", "status", "profile_name", "attachment", "mode", "policy",
    "identities", "features", "loader", "loaded_profiles_before", "loaded_profiles_after",
    "restrict_before", "restrict_after", "source_revision", "preload_manifest_sha256",
}
_STABLE = (
    "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size",
    "st_mtime_ns", "st_ctime_ns",
)


class SetupRefused(ValueError):
    """Required selected input or known policy state was not established."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def check_window(deadline: int) -> None:
    if time.monotonic_ns() >= deadline:
        raise TimeoutError("Original policy setup window exhausted")


def remote_guard() -> None:
    if (
        os.geteuid() != 0 or sys.platform != "linux" or platform.machine() != "x86_64"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise SetupRefused("Policy setup requires its fixed root GitHub-hosted Linux VM")


def write_exclusive(path: Path, raw: bytes, *, limit: int = DOCUMENT_LIMIT) -> None:
    if len(raw) > limit:
        raise SetupRefused("Fixed evidence file exceeds its declared bound")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o644)


def evidence_directory(path: Path) -> None:
    """Make only our fixed evidence ancestors traversable despite a private umask."""
    relative = path.relative_to(EVIDENCE)
    current = EVIDENCE
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        try:
            current.mkdir(mode=0o755)
        except FileExistsError:
            pass
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise SetupRefused("Evidence directory identity is not owned by this controller")
        current.chmod(0o755, follow_symlinks=False)


def bounded_read(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise SetupRefused("Required input is not a regular file: " + str(path))
        pieces = []
        count = 0
        while count <= limit:
            piece = os.read(descriptor, limit + 1 - count)
            if not piece:
                break
            pieces.append(piece)
            count += len(piece)
        raw = b"".join(pieces)
        after = os.fstat(descriptor)
        if (
            len(raw) > limit or (before.st_size > 0 and len(raw) != before.st_size)
            or any(getattr(before, key) != getattr(after, key) for key in _STABLE)
        ):
            raise SetupRefused("Required input changed or exceeded its bound: " + str(path))
        return raw
    finally:
        os.close(descriptor)


def file_identity(path: Path, deadline: int, *, optional: bool = False) -> dict[str, object]:
    check_window(deadline)
    try:
        real = path.resolve(strict=True)
    except FileNotFoundError:
        if optional and not os.path.lexists(path):
            return {
                "path": str(path), "realpath": None, "exists": False,
                "sha256": None, "bytes": None, "reason": "not_present",
            }
        raise SetupRefused("Required identity input is absent: " + str(path)) from None
    descriptor = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode) or before.st_uid != 0
            or before.st_mode & 0o022 or before.st_nlink != 1
        ):
            raise SetupRefused("Required identity is not an immutable root-owned file")
        digest = hashlib.sha256()
        count = 0
        while True:
            check_window(deadline)
            raw = os.read(descriptor, 65_536)
            if not raw:
                break
            digest.update(raw)
            count += len(raw)
        after = os.fstat(descriptor)
        if count != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in _STABLE
        ):
            raise SetupRefused("Required identity changed during hashing")
        return {
            "path": str(path), "realpath": str(real), "exists": True,
            "sha256": digest.hexdigest(), "bytes": count,
            "uid": before.st_uid, "gid": before.st_gid,
            "mode": stat.S_IMODE(before.st_mode), "device": before.st_dev,
            "inode": before.st_ino, "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns,
        }
    finally:
        os.close(descriptor)


def parse_profiles(raw: bytes) -> list[dict[str, str]]:
    records = []
    names = set()
    for line in raw.decode("utf-8").splitlines():
        if not line or " (" not in line or not line.endswith(")"):
            raise SetupRefused("Loaded profile table is malformed or incomplete")
        name, mode = line.rsplit(" (", 1)
        mode = mode[:-1]
        if (
            not name
            or mode not in {"enforce", "complain", "kill", "unconfined", "prompt", "default_allow"}
            or name in names
        ):
            raise SetupRefused("Loaded profile identity is ambiguous")
        names.add(name)
        records.append({"name": name, "mode": mode})
    return sorted(records, key=lambda item: item["name"])


def expand_fixed_braces(expression: str, depth: int = 0) -> list[str]:
    """Expand only finite literal alternatives; this is not an AARE matcher."""
    if depth > 4:
        raise SetupRefused("Attachment brace depth exceeds the selected bound")
    opening = expression.find("{")
    if opening < 0:
        if "}" in expression:
            raise SetupRefused("Attachment expression has unbalanced braces")
        return [expression]
    nesting = 0
    closing = None
    for index in range(opening, len(expression)):
        if expression[index] == "{":
            nesting += 1
        elif expression[index] == "}":
            nesting -= 1
            if nesting == 0:
                closing = index
                break
    if closing is None:
        raise SetupRefused("Attachment expression has unbalanced braces")
    body = expression[opening + 1:closing]
    choices = []
    nesting = 0
    previous = 0
    for index, character in enumerate(body):
        nesting += int(character == "{") - int(character == "}")
        if character == "," and nesting == 0:
            choices.append(body[previous:index])
            previous = index + 1
    choices.append(body[previous:])
    if len(choices) < 2:
        raise SetupRefused("Unknown single-alternative attachment expression")
    result = []
    for choice in choices:
        expanded = expression[:opening] + choice + expression[closing + 1:]
        result.extend(expand_fixed_braces(expanded, depth + 1))
        if len(result) > 64:
            raise SetupRefused("Attachment alternatives exceed the selected bound")
    return sorted(set(result))


def _prefix_may_conflict(expression: str) -> bool:
    targets = {ATTACHMENT, "/bin/bwrap"}
    specials = set("\\*?[]{}()@^")
    prefix = ""
    for character in expression:
        if character in specials:
            break
        prefix += character
    else:
        normalized = os.path.normpath(expression)
        if expression.startswith("/"):
            normalized = "/" + normalized.lstrip("/")
        return normalized in targets
    normalized = os.path.normpath(prefix) if prefix else ""
    return any(target.startswith(normalized) for target in targets)


def attachment_may_conflict(attachment: str) -> bool:
    """Only exclude literal alternatives proven unable to match the fixed path."""
    if not attachment or attachment == "<unknown>":
        raise SetupRefused("Loaded attachment expression is unknown")
    if any(character in attachment for character in ("@", "\\", "[", "]")):
        return _prefix_may_conflict(attachment)
    return any(_prefix_may_conflict(value) for value in expand_fixed_braces(attachment))


def validate_policy_bytes(raw: bytes) -> None:
    if sha(raw) != POLICY_SHA256:
        raise SetupRefused("Selected source policy bytes differ from their frozen pin")

def capture_attachments(
    root: Path, profiles: list[dict[str, str]], deadline: int
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []

    def visit(directory: Path, parent: str, depth: int) -> None:
        if depth > 8:
            raise SetupRefused("Loaded policy namespace depth is ambiguous")
        for item in sorted(directory.iterdir()):
            check_window(deadline)
            if not item.is_dir() or item.is_symlink() or len(records) >= 512:
                raise SetupRefused("Loaded profile introspection is missing or excessive")
            name = bounded_read(item / "name", 4096).decode().strip()
            mode = bounded_read(item / "mode", 4096).decode().strip()
            attach = bounded_read(item / "attach", 4096).decode().strip()
            full = parent + "//" + name if parent and not name.startswith(parent + "//") else name
            records.append({"name": full, "mode": mode, "attachment": attach})
            if len(canonical(records)) > DOCUMENT_LIMIT:
                raise SetupRefused("Loaded attachment metadata exceeds its report bound")
            children = item / "profiles"
            if children.exists():
                visit(children, full, depth + 1)

    visit(root, "", 0)
    actual = sorted(
        ({"name": row["name"], "mode": row["mode"]} for row in records),
        key=lambda row: row["name"],
    )
    if actual != profiles:
        raise SetupRefused("Loaded profile table and attachment introspection disagree")
    return sorted(records, key=lambda row: row["name"])


def refuse_conflicts(
    profiles: list[dict[str, str]], attachments: list[dict[str, str]]
) -> None:
    if any(row["name"] == PROFILE_NAME for row in profiles):
        raise SetupRefused("Selected profile already exists; reuse or replacement is forbidden")
    if any(attachment_may_conflict(row["attachment"]) for row in attachments):
        raise SetupRefused("A loaded or ambiguous executable attachment conflicts with bwrap")


def capture_features(root: Path, deadline: int) -> tuple[dict[str, object], dict[str, bytes]]:
    files: list[dict[str, object]] = []
    contents: dict[str, bytes] = {}
    total = 0

    def visit(directory: Path, depth: int) -> None:
        nonlocal total
        if depth > 8:
            raise SetupRefused("Kernel feature tree exceeds its bound")
        for item in sorted(directory.iterdir()):
            check_window(deadline)
            mode = item.lstat().st_mode
            if stat.S_ISDIR(mode):
                visit(item, depth + 1)
            elif stat.S_ISREG(mode):
                if len(files) >= 256:
                    raise SetupRefused("Kernel feature file count exceeds its bound")
                raw = bounded_read(item, 4096)
                total += len(raw)
                if total > 1_048_576:
                    raise SetupRefused("Kernel feature bytes exceed their bound")
                relative = str(item.relative_to(root))
                contents[relative] = raw
                files.append({
                    "path": str(item), "relative_path": relative,
                    "sha256": sha(raw), "bytes": len(raw),
                })
            else:
                raise SetupRefused("Unknown kernel feature input type")

    visit(root, 0)
    if not files:
        raise SetupRefused("Required kernel feature closure is empty")
    return {"files": files, "canonical_sha256": sha(canonical(files))}, contents


def parse_packages(raw: str) -> dict[str, str]:
    result = {}
    for line in raw.splitlines():
        values = line.split("\t")
        if len(values) != 3 or values[2] != "install ok installed":
            raise SetupRefused("Required package identity is missing or ambiguous")
        name = values[0].split(":", 1)[0]
        if (
            name not in {"apparmor", "libapparmor1", "bubblewrap"}
            or name in result or not values[1]
        ):
            raise SetupRefused("Required package identity differs")
        result[name] = values[1]
    if set(result) != {"apparmor", "libapparmor1", "bubblewrap"}:
        raise SetupRefused("Required package closure is incomplete")
    return result


def validate_parser_config(raw: bytes | None) -> dict[str, object]:
    """Reject every option that can redirect or enlarge the selected input closure."""
    options = []
    if raw is not None:
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise SetupRefused("Parser configuration is not known UTF-8 input") from error
        for original in lines:
            line = original.strip()
            if not line or line.startswith("#"):
                continue
            if line != "write-cache" or options:
                raise SetupRefused("Parser configuration has an unsupported or duplicate option")
            options.append(line)
    return {
        "kind": "fixed_parser_configuration_guard_v1",
        "exists": raw is not None,
        "source_sha256": sha(raw) if raw is not None else None,
        "allowed_options": options,
        "cache_disabled_for_all_parser_commands": True,
        "input_redirection_options_permitted": False,
    }


def checked_parser_version(
    config_raw: bytes | None, deadline: int
) -> tuple[dict[str, object], dict[str, object]]:
    guard = validate_parser_config(config_raw)
    record = bounded_command(
        (str(PARSER), "--skip-cache", "--version"), deadline, capture_number=1
    )
    return guard, record


def bounded_command(
    argv: tuple[str, ...], deadline: int, *, capture_number: int
) -> dict[str, object]:
    check_window(deadline)
    started = time.monotonic_ns()
    retained = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = None
    timed_out = False
    error_record = None
    process = None
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            close_fds=True, start_new_session=True,
        )
        with selectors.DefaultSelector() as selector:
            for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                if stream is None:
                    raise SetupRefused("Parser capture pipes are missing")
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            while selector.get_map() or process.poll() is None:
                if time.monotonic_ns() >= deadline:
                    timed_out = True
                    break
                for key, _events in selector.select(timeout=0.01):
                    raw = os.read(key.fd, 4096)
                    if not raw:
                        selector.unregister(key.fileobj)
                        continue
                    label = key.data
                    available = STREAM_LIMIT - len(retained[label])
                    retained[label].extend(raw[:available])
                    if len(raw) > available:
                        overflow = label
                        break
                if overflow:
                    break
        if timed_out or overflow:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=max(0.001, (deadline - time.monotonic_ns()) / 1e9))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        error_record = {
            "type": type(error).__name__, "errno": getattr(error, "errno", None),
            "reason": str(error)[:1024],
        }
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=max(0.001, (deadline - time.monotonic_ns()) / 1e9))
            except (OSError, subprocess.SubprocessError):
                pass
    finally:
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
    record = {
        "argv": list(argv), "started": process is not None,
        "returncode": process.poll() if process is not None else None,
        "stop_confirmed": process is not None and process.poll() is not None,
        "exception": error_record,
        "started_monotonic_ns": started, "finished_monotonic_ns": time.monotonic_ns(),
        "original_deadline_ns": deadline, "timed_out": timed_out, "overflow": overflow,
        "stop_scope": "Owned trusted setup helper; not a hostile task containment claim",
    }
    for label, buffer in retained.items():
        raw = bytes(buffer)
        destination = EVIDENCE / ("command-" + str(capture_number) + "." + label)
        write_exclusive(destination, raw, limit=STREAM_LIMIT)
        record[label] = raw[:4096].decode("utf-8", errors="replace")
        record[label + "_preview_truncated"] = len(raw) > 4096
        record[label + "_bytes"] = len(raw)
        record[label + "_sha256"] = sha(raw)
        record[label + "_file"] = str(destination)
    return record

def require_command(record: dict[str, object]) -> None:
    if (
        record.get("started") is not True or record.get("stop_confirmed") is not True
        or record.get("returncode") != 0 or record.get("timed_out")
        or record.get("overflow") or record.get("exception") is not None
    ):
        raise SetupRefused("Required fixed setup command did not complete successfully")


def loaded_after_is_selected(
    before: list[dict[str, str]], after: list[dict[str, str]],
    attachments: list[dict[str, str]],
) -> bool:
    expected = sorted(
        before + [{"name": PROFILE_NAME, "mode": "unconfined"}], key=lambda row: row["name"]
    )
    selected = [row for row in attachments if row["name"] == PROFILE_NAME]
    return (
        after == expected and len(selected) == 1
        and selected[0] == {"name": PROFILE_NAME, "mode": "unconfined", "attachment": ATTACHMENT}
    )


def main() -> int:
    started = time.monotonic_ns()
    deadline = started + WINDOW_NS
    created = False
    load_submitted = False
    commands: list[dict[str, object]] = []
    observations: dict[str, object] = {}
    phase = "remote_guard"
    try:
        if len(sys.argv) != 1:
            raise SetupRefused("Policy setup accepts no caller-selected arguments")
        remote_guard()
        EVIDENCE.mkdir(mode=0o755)
        created = True
        EVIDENCE.chmod(0o755)
        if EVIDENCE.lstat().st_uid != 0 or EVIDENCE.is_symlink():
            raise SetupRefused("Policy evidence directory is not fresh root-owned state")
        phase = "preflight"
        revision = os.environ.get("GITHUB_SHA", "")
        if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise SetupRefused("Actual source revision is unavailable")
        if any(
            not os.environ.get(key, "").isdecimal()
            for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
        ):
            raise SetupRefused("Actual workflow run identity is unavailable")
        if os.path.lexists(STAGED_POLICY):
            raise SetupRefused("Staged policy already exists; no overwrite is permitted")
        restrict_before = bounded_read(RESTRICT, 16).decode().strip()
        enabled = bounded_read(Path("/sys/module/apparmor/parameters/enabled"), 16).decode().strip()
        controller_label = bounded_read(Path("/proc/self/attr/current"), 4096).decode().strip()
        if restrict_before != "1" or enabled != "Y" or controller_label != "unconfined":
            raise SetupRefused("Required unchanged AppArmor host state is unavailable")
        release_raw = bounded_read(Path("/etc/os-release").resolve(strict=True), 65_536).decode()
        release = {
            key: value.strip('"')
            for line in release_raw.splitlines() if "=" in line
            for key, value in [line.split("=", 1)]
        }
        if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
            raise SetupRefused("Observed OS is outside the selected Ubuntu24.04 family")
        controller_status = bounded_read(Path("/proc/self/status"), 65_536).decode()
        status_fields = {
            key: value.strip()
            for line in controller_status.splitlines() if ":" in line
            for key, value in [line.split(":", 1)]
        }
        if status_fields.get("NoNewPrivs") != "0":
            raise SetupRefused("Controller already has incompatible no-new-privileges state")
        before = parse_profiles(bounded_read(PROFILE_TABLE, DOCUMENT_LIMIT))
        attachments_before = capture_attachments(PROFILE_ROOT, before, deadline)
        observations.update({
            "loaded_profiles_before": before, "attachments_before": attachments_before,
            "restrict_before": restrict_before, "apparmor_enabled": enabled,
            "controller_label": controller_label,
        })
        refuse_conflicts(before, attachments_before)
        source = bounded_read(POLICY_SOURCE, 65_536)
        validate_policy_bytes(source)
        identities = {
            "bwrap": file_identity(Path(ATTACHMENT), deadline),
            "parser": file_identity(PARSER, deadline),
            "abi": file_identity(ABI, deadline),
            "parser_config": file_identity(PARSER_CONFIG, deadline, optional=True),
            "libapparmor": file_identity(LIBAPPARMOR, deadline),
        }
        if identities["bwrap"]["mode"] & 0o6000 or identities["parser"]["mode"] & 0o6000:
            raise SetupRefused("Selected bwrap/parser has privilege-bearing mode bits")
        if identities["abi"]["bytes"] > 65_536 or (
            identities["parser_config"]["exists"] and identities["parser_config"]["bytes"] > 65_536
        ):
            raise SetupRefused("ABI or parser configuration exceeds its bound")
        config_raw = (
            bounded_read(PARSER_CONFIG, 65_536) if identities["parser_config"]["exists"] else None
        )
        configuration_guard = validate_parser_config(config_raw)
        if config_raw is not None and sha(config_raw) != identities["parser_config"]["sha256"]:
            raise SetupRefused("Observed parser configuration bytes changed")
        observations["parser_configuration_guard"] = configuration_guard
        library = ctypes.CDLL(str(identities["libapparmor"]["realpath"]), use_errno=True)
        if not getattr(library, "aa_change_profile", None):
            raise SetupRefused("Bound libapparmor lacks the required transition symbol")
        dpkg_identity = file_identity(DPKG, deadline)
        features, feature_bytes = capture_features(FEATURE_ROOT, deadline)
        phase = "readonly_commands"
        if file_identity(PARSER_CONFIG, deadline, optional=True) != identities["parser_config"]:
            raise SetupRefused("Parser configuration changed before version observation")
        configuration_guard, version = checked_parser_version(config_raw, deadline)
        commands.append(version)
        require_command(version)
        if version["stdout_preview_truncated"] or not version["stdout"].strip():
            raise SetupRefused("Observed parser version output is empty")
        packages = bounded_command((
            str(DPKG), "--show", "--showformat=${binary:Package}\t${Version}\t${Status}\n",
            "apparmor", "libapparmor1", "bubblewrap",
        ), deadline, capture_number=2)
        commands.append(packages)
        require_command(packages)
        if packages["stdout_preview_truncated"]:
            raise SetupRefused("Observed package response exceeded its semantic bound")
        package_versions = parse_packages(packages["stdout"])
        phase = "stage_and_freeze"
        write_exclusive(STAGED_POLICY, source, limit=65_536)
        policy = {"path": str(STAGED_POLICY), "sha256": sha(source), "bytes": len(source)}
        staged_identity = file_identity(STAGED_POLICY, deadline)
        host = {
            "system": platform.system(), "release": platform.release(),
            "version": platform.version(), "architecture": platform.machine(),
            "os_release": release_raw,
            "boot_id": bounded_read(Path("/proc/sys/kernel/random/boot_id"), 128).decode().strip(),
            "runner_image_os": os.environ.get("ImageOS"),  # noqa: SIM112 -- provider spelling
            "runner_image_version": os.environ.get("ImageVersion"),  # noqa: SIM112
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "controller_uid": os.geteuid(), "controller_gid": os.getegid(),
            "controller_label": controller_label,
        }
        loader_raw = bounded_read(Path(__file__), 65_536)
        loader_source = {
            "path": str(Path(__file__)), "sha256": sha(loader_raw), "bytes": len(loader_raw),
        }
        argv = (
            str(PARSER), "--add", "--skip-cache", "--base=/etc/apparmor.d", str(STAGED_POLICY)
        )
        preload = {
            "kind": "restricted_reference_policy_preload_v1", "schema_version": 1,
            "profile_name": PROFILE_NAME, "attachment": ATTACHMENT, "mode": "unconfined",
            "policy": policy, "staged_identity": staged_identity,
            "policy_source": {
                "path": str(POLICY_SOURCE), "sha256": sha(source), "bytes": len(source),
            },
            "identities": identities, "features": features, "host": host,
            "loaded_profiles_before": before, "attachments_before": attachments_before,
            "restrict_before": restrict_before, "source_revision": os.environ.get("GITHUB_SHA"),
            "parser_argv": list(argv), "parser_version": version, "packages": package_versions,
            "parser_configuration_guard": configuration_guard,
            "dpkg_identity": dpkg_identity, "loader_source": loader_source,
            "original_started_ns": started,
            "original_deadline_ns": deadline, "max_commands": 3, "per_stream_bytes": STREAM_LIMIT,
        }
        preload_raw = canonical(preload)
        write_exclusive(EVIDENCE / "preload-manifest.json", preload_raw)
        preload_sha = sha(preload_raw)
        write_exclusive(EVIDENCE / "preload-manifest.sha256", (preload_sha + "\n").encode())
        evidence_directory(EVIDENCE / "inputs")
        write_exclusive(EVIDENCE / "inputs/policy", source, limit=65_536)
        for key, original in (("abi", ABI), ("parser_config", PARSER_CONFIG)):
            if identities[key]["exists"]:
                write_exclusive(
                    EVIDENCE / "inputs" / key, bounded_read(original, 65_536), limit=65_536
                )
        evidence_directory(EVIDENCE / "kernel-features")
        for relative, content in feature_bytes.items():
            target = EVIDENCE / "kernel-features" / relative
            evidence_directory(target.parent)
            write_exclusive(target, content, limit=4096)
        for key, path in (
            ("bwrap", Path(ATTACHMENT)), ("parser", PARSER), ("abi", ABI),
            ("parser_config", PARSER_CONFIG), ("libapparmor", LIBAPPARMOR),
        ):
            if file_identity(path, deadline, optional=key == "parser_config") != identities[key]:
                raise SetupRefused("Pre-load binary/configuration identity changed")
        if file_identity(STAGED_POLICY, deadline) != staged_identity:
            raise SetupRefused("Exclusive staged policy identity changed")
        if capture_features(FEATURE_ROOT, deadline)[0] != features:
            raise SetupRefused("Pre-load kernel feature closure changed")
        current = parse_profiles(bounded_read(PROFILE_TABLE, DOCUMENT_LIMIT))
        current_attachments = capture_attachments(PROFILE_ROOT, current, deadline)
        if current != before or current_attachments != attachments_before:
            raise SetupRefused("Loaded policy state changed before the one authorized add")
        if bounded_read(RESTRICT, 16).decode().strip() != "1":
            raise SetupRefused("Global userns restriction changed before add")
        if sha(bounded_read(Path(__file__), 65_536)) != loader_source["sha256"]:
            raise SetupRefused("Trusted loader source changed before add")
        phase = "one_add"
        check_window(deadline)
        load_submitted = True
        loaded = bounded_command(argv, deadline, capture_number=3)
        commands.append(loaded)
        phase = "post_load_readback"
        after = parse_profiles(bounded_read(PROFILE_TABLE, DOCUMENT_LIMIT))
        attachments_after = capture_attachments(PROFILE_ROOT, after, deadline)
        restrict_after = bounded_read(RESTRICT, 16).decode().strip()
        observations.update({
            "loaded_profiles_after": after, "attachments_after": attachments_after,
            "restrict_after": restrict_after,
        })
        require_command(loaded)
        check_window(deadline)
        foreign_after = [row for row in attachments_after if row["name"] != PROFILE_NAME]
        if (
            restrict_after != "1" or foreign_after != attachments_before
            or not loaded_after_is_selected(before, after, attachments_after)
        ):
            raise SetupRefused(
                "Loaded profile name/mode/attachment or unchanged restriction was not established"
            )
        loader = {
            **loaded, "version": version["stdout"], "packages": package_versions,
            "commands": commands, "original_started_ns": started, "original_deadline_ns": deadline,
            "host": host, "policy_source": preload["policy_source"],
            "loader_source": loader_source,
            "staged_identity": staged_identity, "dpkg_identity": dpkg_identity,
            "attachments_before": attachments_before, "attachments_after": attachments_after,
            "parser_configuration_guard": configuration_guard,
            "bounds": {"window_ns": WINDOW_NS, "max_commands": 3, "per_stream_bytes": STREAM_LIMIT},
        }
        report = {
            "kind": "restricted_reference_policy_setup_v1", "schema_version": 1,
            "status": "LOADED_REFERENCE_ONLY", "profile_name": PROFILE_NAME,
            "attachment": ATTACHMENT, "mode": "unconfined", "policy": policy,
            "identities": identities, "features": features, "loader": loader,
            "loaded_profiles_before": before, "loaded_profiles_after": after,
            "restrict_before": restrict_before, "restrict_after": restrict_after,
            "source_revision": os.environ.get("GITHUB_SHA"),
            "preload_manifest_sha256": preload_sha,
        }
        if set(report) != SUCCESS_FIELDS:
            raise SetupRefused("Internal success receipt schema differs")
        write_exclusive(EVIDENCE / "policy-setup.json", canonical(report) + b"\n")
        sys.stdout.write(json.dumps({"status": report["status"], "profile": PROFILE_NAME}) + "\n")
        return 0
    except Exception as error:
        report = {
            "kind": "restricted_reference_policy_setup_failure_v1", "schema_version": 1,
            "status": "UNKNOWN" if load_submitted else "REFUSED", "phase": phase,
            "reason": (type(error).__name__ + ": " + str(error))[:2048],
            "load_submitted": load_submitted, "commands": commands,
            "original_started_ns": started, "original_deadline_ns": deadline,
            "source_revision": os.environ.get("GITHUB_SHA"),
            "product_m1": "DISABLED", "retry_performed": False,
            "observations": observations,
        }
        if len(canonical(report)) + 1 > DOCUMENT_LIMIT:
            report["observations"] = {
                "retained": False, "reason": "report_bound_exceeded",
                "canonical_sha256": sha(canonical(observations)),
            }
        if created:
            target = EVIDENCE / "policy-setup.json"
            if os.path.lexists(target):
                target = EVIDENCE / "policy-setup-failure.json"
            write_exclusive(target, canonical(report) + b"\n")
        sys.stderr.write("reference_policy_not_ready: " + type(error).__name__ + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
