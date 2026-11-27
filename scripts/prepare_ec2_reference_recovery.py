#!/usr/bin/env python3
"""Prepare the one frozen EC2 recovery plan without claiming qualification."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import sys
from pathlib import Path

# -I removes the script directory; only the provisioned checkout supplies imports.
_SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SOURCE / "src"))
from tickwitness.infrastructure import restricted_reference_ec2 as ec2  # noqa: E402

type Row = dict[str, object]


def _absence(path: Path) -> None:
    if os.path.lexists(path):
        raise ValueError("Existing recovery plan or consumption cannot be reused: " + str(path))


def _locked_claim(fd: int, path: Path) -> tuple[bytes, tuple[int, ...]]:
    before = os.fstat(fd)
    if not ec2._regular_root(before) or before.st_size > 65_536:
        raise ValueError("Original host mutex is not a bounded secure root file")
    if ec2._stable(before) != ec2._stable(path.lstat()):
        raise ValueError("Original host mutex path identity differs")
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, 65_537)
    after = os.fstat(fd)
    if (
        len(raw) != before.st_size
        or ec2._stable(before) != ec2._stable(after)
        or ec2._stable(after) != ec2._stable(path.lstat())
        or hashlib.sha256(raw).hexdigest() != ec2.RECOVERY_PREDECESSOR["host_claim_sha256"]
    ):
        raise ValueError("Original host mutex bytes or identity changed")
    return raw, ec2._stable(after)


def prepare_plan(*, source_revision: str, plan_id: str) -> Row:
    """Validate retained history and first-create a plan, never a claim or window."""
    if (
        type(source_revision) is not str
        or re.fullmatch("[0-9a-f]{40}", source_revision) is None
        or type(plan_id) is not str
        or plan_id != ec2.RECOVERY_PLAN_ID
    ):
        raise ValueError("The fixed plan and actual lowercase source revision are required")
    if os.geteuid() != 0 or sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("Recovery preparation requires the selected root Linux x86_64 host")
    ec2._secure_directory(ec2.ROOT)
    plan_path = ec2.ROOT / "recovery-plan.json"
    consumption = ec2.ROOT / "recovery-consumption.json"
    _absence(plan_path)
    _absence(consumption)
    lock_path = ec2.ROOT / "host-admission.json"
    descriptor = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = _locked_claim(descriptor, lock_path)
        # Recheck under the same host mutex used by the future qualification.
        _absence(plan_path)
        _absence(consumption)
        plan = ec2.recovery_plan_document(
            source_revision=source_revision,
            run_id=ec2.RECOVERY_RUN_ID,
            plan_id=plan_id,
        )
        if _locked_claim(descriptor, lock_path) != original:
            raise ValueError("Original host mutex changed during plan validation")
        _absence(plan_path)
        _absence(consumption)
        raw = ec2.canonical(plan)
        if len(raw) > 65_536:
            raise ValueError("Recovery plan exceeds its fixed document bound")
        # Existing or partially written plans are never replaced or removed.
        ec2.write_exclusive(plan_path, raw)
        observed, _ = ec2._secure_read(plan_path, 65_536)
        if observed != raw or _locked_claim(descriptor, lock_path) != original:
            raise ValueError("Plan publication or original host identity is uncertain")
        _absence(consumption)
        return {
            "path": str(plan_path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    finally:
        os.close(descriptor)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--plan-id", required=True)
    args = parser.parse_args(arguments)
    try:
        record = prepare_plan(source_revision=args.source_revision, plan_id=args.plan_id)
    except Exception as error:
        sys.stderr.write(
            "recovery_preparation_refused: "
            + type(error).__name__
            + ": "
            + str(error)[:2048]
            + "\n"
        )
        return 78
    sys.stdout.write(
        json.dumps(
            {
                "status": "PREPARED_ONLY",
                "plan_id": args.plan_id,
                "source_revision": args.source_revision,
                "plan": record,
                "qualification_started": False,
                "production_m1": "DISABLED",
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
