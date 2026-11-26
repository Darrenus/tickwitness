"""Real Linux procfs formatting regression, not a hostile-control qualification."""

import os
import re
import select
import subprocess
import sys
import time
from contextlib import suppress

import pytest

from tickwitness.infrastructure import restricted_reference as reference

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Requires the Linux procfs producer"
)

_CHILD = """
import resource
import select
import sys

resource.setrlimit(resource.RLIMIT_FSIZE, (8388608, 8388608))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_RTPRIO, (0, 0))
print("ready", flush=True)
if select.select([sys.stdin], [], [], 15)[0]:
    sys.stdin.buffer.read(1)
"""

_LABELS = ("Max file size", "Max open files", "Max core file size", "Max realtime priority")


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    assert remaining > 0, "Trusted limits producer exceeded its observation deadline"
    return remaining


def _read_ready(process, deadline):
    assert process.stdout is not None
    descriptor = process.stdout.fileno()
    ready = bytearray()
    while not ready.endswith(b"\n"):
        assert select.select([descriptor], [], [], _remaining(deadline))[0], "No child readiness"
        chunk = os.read(descriptor, 16)
        assert chunk, "Trusted limits child exited before readiness"
        ready.extend(chunk)
        assert len(ready) <= 16, "Unexpected trusted-child output"
    assert ready == b"ready\n"


def _read_live_limits(process, deadline):
    assert process.poll() is None, "Limits must be observed on a live child"
    descriptor = os.open(f"/proc/{process.pid}/limits", os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    raw = bytearray()
    try:
        while True:
            assert select.select([descriptor], [], [], _remaining(deadline))[0], "Procfs not ready"
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            raw.extend(chunk)
            assert len(raw) <= 65536, "Unexpectedly large procfs limits record"
    finally:
        os.close(descriptor)
    _remaining(deadline)
    assert process.poll() is None, "Child exited during independent procfs observation"
    return raw.decode("ascii")


@pytest.fixture(scope="module")
def linux_process_limits():
    import resource

    constraints = (
        resource.RLIMIT_FSIZE,
        resource.RLIMIT_NOFILE,
        resource.RLIMIT_CORE,
        resource.RLIMIT_RTPRIO,
    )
    parent_before = tuple(resource.getrlimit(item) for item in constraints)
    deadline = time.monotonic() + 10
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", _CHILD],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _read_ready(process, deadline)
        return _read_live_limits(process, deadline)
    finally:
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.kill()
        try:
            process.communicate(timeout=5)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                assert stream is not None
                stream.close()
            assert tuple(resource.getrlimit(item) for item in constraints) == parent_before


def _producer_row(raw, label):
    rows = [line for line in raw.splitlines(keepends=True) if line.startswith(f"{label} ")]
    assert len(rows) == 1, "The real producer must provide exactly one selected row"
    return rows[0]


def _replace_field(raw, label, index, replacement):
    row = _producer_row(raw, label)
    field = list(re.finditer(r"\S+", row[len(label) :]))[index]
    start, end = len(label) + field.start(), len(label) + field.end()
    changed = row[:start] + replacement + row[end:]
    return raw.replace(row, changed, 1)


def test_live_linux_proc_limits_and_observed_unit_padding_are_accepted(linux_process_limits):
    raw = linux_process_limits
    reference._validate_process_limits(raw)
    for label, unit in (
        ("Max file size", "bytes"),
        ("Max core file size", "bytes"),
        ("Max open files", "files"),
    ):
        row = _producer_row(raw, label)
        assert row.endswith(" \n"), "Observe the kernel's trailing unit-column padding"
        assert row.rstrip(" \n").endswith(unit)


@pytest.mark.parametrize(
    "label,replacement", list(zip(_LABELS, ("8388607", "63", "1", "1"), strict=True))
)
@pytest.mark.parametrize("column", [0, 1], ids=["soft", "hard"])
def test_actual_proc_limits_with_wrong_soft_or_hard_ceiling_are_refused(
    linux_process_limits, label, replacement, column
):
    changed = _replace_field(linux_process_limits, label, column, replacement)
    with pytest.raises(ValueError, match="Independent hard/soft process ceiling readback differs"):
        reference._validate_process_limits(changed)


@pytest.mark.parametrize("label", _LABELS)
def test_actual_proc_limits_with_a_missing_required_row_are_refused(linux_process_limits, label):
    row = _producer_row(linux_process_limits, label)
    with pytest.raises(ValueError, match="Independent hard/soft process ceiling readback differs"):
        reference._validate_process_limits(linux_process_limits.replace(row, "", 1))


@pytest.mark.parametrize("label", _LABELS)
def test_actual_proc_limits_with_duplicate_required_rows_are_refused(linux_process_limits, label):
    row = _producer_row(linux_process_limits, label)
    with pytest.raises(ValueError, match="Independent hard/soft process ceiling readback differs"):
        reference._validate_process_limits(linux_process_limits + row)


@pytest.mark.parametrize("label", _LABELS[:3])
def test_actual_proc_limits_with_wrong_units_are_refused(linux_process_limits, label):
    changed = _replace_field(linux_process_limits, label, 2, "wrong-units")
    with pytest.raises(ValueError, match="Independent hard/soft process ceiling readback differs"):
        reference._validate_process_limits(changed)


def test_actual_unitless_priority_row_with_an_added_unit_is_refused(linux_process_limits):
    row = _producer_row(linux_process_limits, "Max realtime priority")
    changed = linux_process_limits.replace(row, row.rstrip(" \n") + " priority\n", 1)
    with pytest.raises(ValueError, match="Independent hard/soft process ceiling readback differs"):
        reference._validate_process_limits(changed)
