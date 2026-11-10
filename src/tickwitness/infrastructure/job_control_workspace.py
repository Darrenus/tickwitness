"""No-follow owned scratch and lifetime locks; never signal persisted PIDs."""

from __future__ import annotations

import fcntl
import os
import stat
import time
from pathlib import Path
from typing import cast

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.domain.evidence.run_records import canonical, identity, parse
from tickwitness.infrastructure.campaign_resource_guard import charge_managed_write

type Row = dict[str, object]
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_SEAL_FIELDS = {
    "kind",
    "schema_version",
    "job_id",
    "policy_id",
    "job_attempt_id",
    "coordinator_id",
    "workspace_device",
    "workspace_inode",
    "scratch_device",
    "scratch_inode",
    "lifetime_device",
    "lifetime_inode",
}
MAX_WORKSPACE_ENTRIES = 16_384
MAX_WORKSPACE_DEPTH = 32


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobStoreError(message)


def _owned(info: os.stat_result, *, directory: bool) -> None:
    _require(
        (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        and info.st_uid == os.geteuid()
        and info.st_mode & 0o022 == 0
        and (directory or info.st_nlink == 1),
        "Workspace identity requires safe same-user directories and unaliased regular files",
    )


def _same(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


class OwnedJobWorkspace:
    """Exactly one sealed attempt directory; partial setup remains quarantined."""

    def __init__(self, directory: Path, policy_id: str, row: Row) -> None:
        self.directory = directory
        self.policy_id = identity(policy_id)
        self.job_id = identity(row["job_id"])
        attempt = cast("Row", row["attempt"])
        self.attempt_id = identity(attempt["job_attempt_id"])
        self.coordinator_id = identity(attempt["coordinator_id"])
        self.path = directory / "workspaces" / self.attempt_id
        self.scratch = self.path / "scratch"
        self.root_fd: int | None = None
        self.workspaces_fd: int | None = None
        self.attempt_fd: int | None = None
        self.lifetime_fd: int | None = None
        self.seal: Row | None = None
        self.removed = False

    @staticmethod
    def _mkdir(parent: int, name: str, *, existing: bool) -> None:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            if not existing:
                raise JobConflictError("Owned workspace exists; inspect or explicitly reclaim it")
        else:
            os.fsync(parent)

    def _open(self) -> None:
        self.root_fd = os.open(self.directory, _DIRECTORY_FLAGS)
        _owned(os.fstat(self.root_fd), directory=True)
        self.workspaces_fd = os.open("workspaces", _DIRECTORY_FLAGS, dir_fd=self.root_fd)
        _owned(os.fstat(self.workspaces_fd), directory=True)
        self.attempt_fd = os.open(
            self.attempt_id, _DIRECTORY_FLAGS, dir_fd=self.workspaces_fd
        )
        _owned(os.fstat(self.attempt_fd), directory=True)

    def create(self) -> None:
        root = os.open(self.directory, _DIRECTORY_FLAGS)
        try:
            _owned(os.fstat(root), directory=True)
            self._mkdir(root, "workspaces", existing=True)
        finally:
            os.close(root)
        parent = os.open(self.directory / "workspaces", _DIRECTORY_FLAGS)
        try:
            _owned(os.fstat(parent), directory=True)
            self._mkdir(parent, self.attempt_id, existing=False)
        finally:
            os.close(parent)
        self._open()
        descriptor = cast("int", self.attempt_fd)
        self._mkdir(descriptor, "scratch", existing=False)
        scratch = os.stat("scratch", dir_fd=descriptor, follow_symlinks=False)
        self.lifetime_fd = os.open(
            "lifetime.lock",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
        _owned(os.fstat(self.lifetime_fd), directory=False)
        fcntl.flock(self.lifetime_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lifetime = os.fstat(self.lifetime_fd)
        workspace = os.fstat(descriptor)
        self.seal = {
            "kind": "job_workspace_v1",
            "schema_version": 1,
            "job_id": self.job_id,
            "policy_id": self.policy_id,
            "job_attempt_id": self.attempt_id,
            "coordinator_id": self.coordinator_id,
            "workspace_device": workspace.st_dev,
            "workspace_inode": workspace.st_ino,
            "scratch_device": scratch.st_dev,
            "scratch_inode": scratch.st_ino,
            "lifetime_device": lifetime.st_dev,
            "lifetime_inode": lifetime.st_ino,
        }
        raw = canonical(self.seal)
        charge_managed_write(len(raw))
        seal_fd = os.open(
            "workspace.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=descriptor,
        )
        try:
            pending = memoryview(raw)
            while pending:
                written = os.write(seal_fd, pending)
                _require(written > 0, "Workspace seal write made no progress")
                pending = pending[written:]
            os.fsync(seal_fd)
        finally:
            os.close(seal_fd)
        os.fsync(self.lifetime_fd)
        os.fsync(descriptor)
        self.verify()

    def close_parent_lifetime(self) -> None:
        if self.lifetime_fd is not None:
            descriptor, self.lifetime_fd = self.lifetime_fd, None
            # LOCK_UN would release the child's inherited open-file-description lock.
            os.close(descriptor)

    def close(self) -> None:
        self.close_parent_lifetime()
        for name in ("attempt_fd", "workspaces_fd", "root_fd"):
            descriptor = getattr(self, name)
            if descriptor is not None:
                setattr(self, name, None)
                os.close(descriptor)

    def _read_seal(self) -> Row:
        descriptor = os.open("workspace.json", os.O_RDONLY | os.O_NOFOLLOW,
                             dir_fd=cast("int", self.attempt_fd))
        try:
            info = os.fstat(descriptor)
            _owned(info, directory=False)
            _require(0 < info.st_size <= 4096, "Workspace seal size differs")
            raw = os.read(descriptor, 4097)
        finally:
            os.close(descriptor)
        row = parse(raw, limit=4096)
        _require(set(row) == _SEAL_FIELDS and canonical(row) == raw, "Workspace seal fields differ")
        _require(row["kind"] == "job_workspace_v1" and type(row["schema_version"]) is int
                 and row["schema_version"] == 1, "Workspace seal version differs")
        for key, expected in (("job_id", self.job_id), ("policy_id", self.policy_id),
                              ("job_attempt_id", self.attempt_id),
                              ("coordinator_id", self.coordinator_id)):
            _require(identity(row[key]) == expected, "Workspace seal identity differs: " + key)
        for key in _SEAL_FIELDS - {"kind", "schema_version", "job_id", "policy_id",
                                  "job_attempt_id", "coordinator_id"}:
            _require(type(row[key]) is int and cast("int", row[key]) >= 0,
                     "Workspace seal inode field differs")
        return row

    def verify(self) -> None:
        _require(self.root_fd is not None and self.workspaces_fd is not None
                 and self.attempt_fd is not None, "Workspace descriptors are unavailable")
        current = os.open(self.directory, _DIRECTORY_FLAGS)
        try:
            _owned(os.fstat(current), directory=True)
            _require(_same(os.fstat(current), os.fstat(cast("int", self.root_fd))),
                     "Job control workspace root was replaced")
        finally:
            os.close(current)
        for parent, name, held in (
            (cast("int", self.root_fd), "workspaces", cast("int", self.workspaces_fd)),
            (cast("int", self.workspaces_fd), self.attempt_id, cast("int", self.attempt_fd)),
        ):
            found = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _owned(found, directory=True)
            _require(_same(found, os.fstat(held)), "Owned workspace directory was replaced")
        try:
            row = self._read_seal()
        except ValueError as error:
            if isinstance(error, JobStoreError):
                raise
            raise JobStoreError("Workspace seal is invalid: " + str(error)) from error
        if self.seal is not None:
            _require(row == self.seal, "Workspace seal was replaced")
        self.seal = row
        actual = os.fstat(cast("int", self.attempt_fd))
        _require((actual.st_dev, actual.st_ino) == (row["workspace_device"], row["workspace_inode"]),
                 "Workspace inode does not match its seal")
        _require(set(os.listdir(cast("int", self.attempt_fd)))
                 in ({"workspace.json", "lifetime.lock", "scratch"},
                     {"workspace.json", "lifetime.lock"}),
                 "Workspace journal contains an unknown entry")

    def cleanup(self, *, group_absent: bool, deadline_ns: int) -> None:
        _require(group_absent, "Worker group stop is unconfirmed; scratch is retained")
        self.close_parent_lifetime()
        self.verify()
        descriptor = cast("int", self.attempt_fd)
        lock_fd = os.open("lifetime.lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=descriptor)
        try:
            lock = os.fstat(lock_fd)
            _owned(lock, directory=False)
            seal = cast("Row", self.seal)
            _require(lock.st_size == 0 and (lock.st_dev, lock.st_ino)
                     == (seal["lifetime_device"], seal["lifetime_inode"]),
                     "Workspace lifetime identity differs")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise JobConflictError("Worker lifetime is still held; scratch is retained") from error
            try:
                info = os.stat("scratch", dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                self.removed = True
                return
            _owned(info, directory=True)
            _require((info.st_dev, info.st_ino) == (seal["scratch_device"], seal["scratch_inode"]),
                     "Scratch directory does not match its immutable seal")
            scratch = os.open("scratch", _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                _require(_same(info, os.fstat(scratch)), "Scratch changed during cleanup")
                remaining = [MAX_WORKSPACE_ENTRIES]
                self._clear(scratch, remaining, 0, deadline_ns, info.st_dev)
                os.fsync(scratch)
            finally:
                os.close(scratch)
            self.verify()
            _require(_same(info, os.stat("scratch", dir_fd=descriptor, follow_symlinks=False)),
                     "Scratch was replaced during cleanup")
            os.rmdir("scratch", dir_fd=descriptor)
            os.fsync(descriptor)
            self.removed = True
        finally:
            os.close(lock_fd)

    @classmethod
    def _clear(cls, directory: int, remaining: list[int], depth: int,
               deadline_ns: int, device: int) -> None:
        _require(depth <= MAX_WORKSPACE_DEPTH, "Owned scratch depth exceeds cleanup bound")
        with os.scandir(directory) as entries:
            for entry in entries:
                _require(time.monotonic_ns() < deadline_ns, "Owned scratch cleanup grace expired")
                remaining[0] -= 1
                _require(remaining[0] >= 0, "Owned scratch entry count exceeds cleanup bound")
                info = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                _require(info.st_uid == os.geteuid() and info.st_dev == device,
                         "Scratch entry ownership or filesystem differs")
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, _DIRECTORY_FLAGS, dir_fd=directory)
                    try:
                        _require(_same(info, os.fstat(child)), "Scratch child was replaced")
                        cls._clear(child, remaining, depth + 1, deadline_ns, device)
                    finally:
                        os.close(child)
                    _require(_same(info, os.stat(entry.name, dir_fd=directory,
                                                follow_symlinks=False)),
                             "Scratch child changed during cleanup")
                    os.rmdir(entry.name, dir_fd=directory)
                else:
                    # Unlink the owned directory entry, including a symlink itself; never follow it.
                    os.unlink(entry.name, dir_fd=directory)


def reclaim_workspace(directory: Path, policy_id: str, snapshot: Row, *, grace_ns: int) -> Row:
    """Reclaim only the one snapshot-bound workspace after explicit reconciliation."""
    _require(snapshot["state"] != "RUNNING", "Reconcile the RUNNING Job before reclamation")
    parent = directory / "workspaces"
    try:
        parent_info = parent.lstat()
    except FileNotFoundError:
        return {"workspace_found": False, "workspace_removed": False}
    _owned(parent_info, directory=True)
    parent_fd = os.open(parent, _DIRECTORY_FLAGS)
    try:
        _require(_same(parent_info, os.fstat(parent_fd)), "Workspace namespace was replaced")
        names = os.listdir(parent_fd)
        if snapshot["attempt"] is None:
            _require(not names, "Unclaimed Job has an unknown workspace")
            return {"workspace_found": False, "workspace_removed": False}
        attempt_id = identity(cast("Row", snapshot["attempt"])["job_attempt_id"])
        _require(names in ([], [attempt_id]), "Workspace namespace has an unknown attempt")
        if not names:
            return {"workspace_found": False, "workspace_removed": False}
    finally:
        os.close(parent_fd)
    workspace = OwnedJobWorkspace(directory, policy_id, snapshot)
    try:
        workspace._open()
        workspace.cleanup(group_absent=True, deadline_ns=time.monotonic_ns() + grace_ns)
        return {"workspace_found": True, "workspace_removed": workspace.removed}
    except FileNotFoundError as error:
        raise JobStoreError("Incomplete workspace cannot be silently reclaimed") from error
    finally:
        workspace.close()
