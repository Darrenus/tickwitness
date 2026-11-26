"""Real procfs membership shape, without creating a qualification or hostile task."""

import os
import sys
import time
from pathlib import Path

import pytest

from tickwitness.infrastructure import restricted_reference as reference

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Requires the Linux procfs membership producer"
)


def test_real_sampler_preserves_host_namespace_ids_and_process_relationships(tmp_path: Path):
    pid = os.getpid()
    (tmp_path / "cgroup.procs").write_text(f"{pid}\n")
    facts = {"active_member_observations": []}
    before = time.monotonic_ns()
    reference.ReferenceRunner._record_members(tmp_path, facts, "before_kill")
    after = time.monotonic_ns()

    sample = facts["active_member_observations"][0]
    assert sample["phase"] == "before_kill"
    assert before <= sample["observed_at_ns"] <= after
    assert sample["cgroup_procs"] == [pid]
    assert len(sample["members"]) == 1
    member = sample["members"][0]
    raw_status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    assert "observation" not in member
    assert member["pid"] == pid
    assert member["parent_pid"] == os.getppid()
    assert member["sid_host"] == os.getsid(0)
    # Preserve the kernel's host-only or nested columns; never invent a guest ID.
    assert member["namespace_pids"] == raw_status["NSpid"].strip()
    assert member["namespace_session_ids"] == raw_status["NSsid"].strip()
    assert member["namespace_pids"].split()[0] == str(pid)
    assert member["namespace_session_ids"].split()[0] == str(os.getsid(0))


def test_real_sampler_retains_an_unobservable_member_instead_of_dropping_it(tmp_path: Path):
    pid = os.getpid()
    absent_pid = int(Path("/proc/sys/kernel/pid_max").read_text()) + 1
    (tmp_path / "cgroup.procs").write_text(f"{pid}\n{absent_pid}\n")
    facts = {"active_member_observations": []}
    reference.ReferenceRunner._record_members(tmp_path, facts, "before_kill")
    sample = facts["active_member_observations"][0]
    assert sample["cgroup_procs"] == [pid, absent_pid]
    assert [member["pid"] for member in sample["members"]] == [pid, absent_pid]
    assert sample["members"][1] == {
        "pid": absent_pid,
        "observation": None,
        "reason": "exited_or_incomplete",
    }
