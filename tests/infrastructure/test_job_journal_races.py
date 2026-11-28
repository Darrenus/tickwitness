"""Optional rollback-journal races refuse observations without weakening IO checks."""

import errno
import os
import sqlite3
import stat
from contextlib import contextmanager

import pytest
from test_sqlite_job_store import NOW, tree
from test_sqlite_job_store import job_case as job_case

from tickwitness.application.jobs import JobConflictError, JobStoreError
from tickwitness.infrastructure.sqlite_job_store import SqliteJobStore

JOURNAL = "catalog.sqlite3-journal"
CATALOG = "catalog.sqlite3"


def queued(value):
    with value.store.coordinator():
        return value.store.submit(value.spec, now_ns=NOW)


@contextmanager
def real_journal(root):
    """A real transaction changes a header cookie and restores it before COMMIT."""
    connection = sqlite3.connect(root / CATALOG, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("PRAGMA user_version=2")
        connection.execute("PRAGMA user_version=1")
        assert (root / JOURNAL).is_file()
        assert (root / JOURNAL).stat().st_size > 0
        yield connection
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def commit_at_boundary(patch, root, connection, phase, *, after_unlink=None, stat_errno=None):
    """Commit at one preflight boundary, then delegate the actual failing syscall."""
    actual_open, actual_stat, actual_fstat = os.open, os.stat, os.fstat
    observed = {"opened": False, "commits": 0, "sqlite_connects": 0, "named_failures": []}

    def commit():
        assert observed["commits"] == 0
        assert (root / JOURNAL).is_file()
        connection.commit()
        assert not (root / JOURNAL).exists()
        observed["commits"] += 1
        observed["after_commit"] = tree(root)

    def opened(path, flags, *args, **kwargs):
        if path == JOURNAL and kwargs.get("dir_fd") is not None:
            if phase == "open":
                commit()
            descriptor = actual_open(path, flags, *args, **kwargs)
            observed["opened"] = True
            observed["descriptor"] = descriptor
            if phase == "fstat":
                before = actual_fstat(descriptor)
                assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                commit()
                after = actual_fstat(descriptor)
                assert stat.S_ISREG(after.st_mode) and after.st_nlink == 0
                assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
                with pytest.raises(FileNotFoundError) as missing:
                    actual_stat(path, dir_fd=kwargs["dir_fd"], follow_symlinks=False)
                assert missing.value.errno == errno.ENOENT and missing.value.filename == JOURNAL
                observed["zero_link_verified"] = True
                if after_unlink is not None:
                    after_unlink()
                observed["after_boundary"] = tree(root)
            return descriptor
        return actual_open(path, flags, *args, **kwargs)

    def statted(path, *args, **kwargs):
        if path == JOURNAL and kwargs.get("dir_fd") is not None and observed["opened"]:
            if phase == "restat":
                commit()
            elif stat_errno is not None:
                assert phase == "fstat" and kwargs.get("follow_symlinks") is False
                error = OSError(stat_errno, "Declared named zero-link journal IO failure", JOURNAL)
                observed["named_failures"].append(error)
                raise error
        return actual_stat(path, *args, **kwargs)

    def no_sqlite_observation(*args, **kwargs):
        observed["sqlite_connects"] += 1
        raise AssertionError("A conflicted preflight must not open or yield a SQLite observation")

    patch.setattr(os, "open", opened)
    patch.setattr(os, "stat", statted)
    patch.setattr(sqlite3, "connect", no_sqlite_observation)
    return observed


def assert_preflight_closed(observed):
    assert observed["sqlite_connects"] == 0
    if "descriptor" in observed:
        with pytest.raises(OSError) as closed:
            os.fstat(observed["descriptor"])
        assert closed.value.errno == errno.EBADF


@pytest.mark.parametrize("phase", ["open", "restat", "fstat"])
@pytest.mark.parametrize("method", ["get", "events", "result"])
def test_real_commit_journal_disappearance_is_an_explicit_read_conflict(
    job_case, monkeypatch, phase, method
):
    value = job_case
    original = queued(value)
    history = value.store.events(value.spec.spec_id)
    reader = SqliteJobStore(value.root, create=False)
    with real_journal(value.root) as writer, monkeypatch.context() as patch:
        observed = commit_at_boundary(patch, value.root, writer, phase)
        try:
            with pytest.raises(JobConflictError, match="read is busy; retry read") as caught:
                getattr(reader, method)(value.spec.spec_id)
        finally:
            assert_preflight_closed(observed)
            assert observed["commits"] == 1 and not writer.in_transaction
            assert tree(value.root) == observed["after_commit"]
            if phase == "fstat":
                assert observed["zero_link_verified"]
    cause = caught.value.__cause__
    assert isinstance(cause, FileNotFoundError)
    assert cause.errno == errno.ENOENT and cause.filename == JOURNAL
    assert caught.value.code == "job_conflict" and caught.value.exit_code == 9
    assert reader.get(value.spec.spec_id) == original
    assert reader.events(value.spec.spec_id) == history
    assert reader.result(value.spec.spec_id) is None
    assert tree(value.root) == observed["after_commit"]


@pytest.mark.parametrize("phase", ["open", "restat", "fstat"])
def test_real_commit_journal_disappearance_keeps_writer_io_unconfirmed(
    job_case, monkeypatch, phase
):
    value = job_case
    original = queued(value)
    with value.store.coordinator():
        with real_journal(value.root) as writer:
            with monkeypatch.context() as patch:
                observed = commit_at_boundary(patch, value.root, writer, phase)
                try:
                    with (
                        pytest.raises(JobStoreError) as caught,
                        value.store._connection(write=True),
                    ):
                        pytest.fail("A failed writer preflight must not yield a connection")
                finally:
                    assert_preflight_closed(observed)
            assert observed["commits"] == 1
            assert tree(value.root) == observed["after_commit"]
        assert not isinstance(caught.value, JobConflictError)
        assert caught.value.exit_code == 3
        cause = caught.value.__cause__
        if phase == "fstat":
            assert observed["zero_link_verified"] and cause is None
            assert str(caught.value) == "Job catalog files must be unaliased regular files"
        else:
            assert isinstance(cause, FileNotFoundError) and cause.errno == errno.ENOENT
        assert value.store.get(value.spec.spec_id) == original


@pytest.mark.parametrize("phase", ["open", "restat"])
@pytest.mark.parametrize("failure_errno", [errno.EACCES, errno.EIO])
def test_nonmissing_journal_io_errors_never_become_read_conflicts(
    job_case, monkeypatch, phase, failure_errno
):
    value = job_case
    queued(value)
    journal = value.root / JOURNAL
    journal.write_bytes(b"")
    before = tree(value.root)
    actual_open, actual_stat = os.open, os.stat
    did_open = False

    def failed():
        raise OSError(failure_errno, "Declared non-ENOENT journal IO failure", JOURNAL)

    def opened(path, flags, *args, **kwargs):
        nonlocal did_open
        if path == JOURNAL and kwargs.get("dir_fd") is not None:
            if phase == "open":
                failed()
            descriptor = actual_open(path, flags, *args, **kwargs)
            did_open = True
            return descriptor
        return actual_open(path, flags, *args, **kwargs)

    def statted(path, *args, **kwargs):
        if path == JOURNAL and kwargs.get("dir_fd") is not None and did_open:
            assert phase == "restat"
            failed()
        return actual_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        patch.setattr(os, "stat", statted)
        with pytest.raises(JobStoreError) as caught:
            value.store.get(value.spec.spec_id)
    assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
    assert isinstance(caught.value.__cause__, OSError)
    assert caught.value.__cause__.errno == failure_errno
    assert tree(value.root) == before


@pytest.mark.parametrize("entry", ["symlink", "hardlink", "fifo", "directory"])
def test_persistent_unsafe_optional_journal_is_retained_and_refused(job_case, entry):
    value = job_case
    queued(value)
    journal = value.root / JOURNAL
    outside = value.root.parent / "protected-outside"
    outside.write_bytes(b"outside bytes must remain unchanged")
    if entry == "symlink":
        journal.symlink_to(outside)
    elif entry == "hardlink":
        os.link(outside, journal)
    elif entry == "fifo":
        os.mkfifo(journal)
    else:
        journal.mkdir()
    before, before_stat = tree(value.root), journal.lstat()
    with pytest.raises(JobStoreError) as caught:
        value.store.get(value.spec.spec_id)
    assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
    after_stat = journal.lstat()
    assert (before_stat.st_dev, before_stat.st_ino, before_stat.st_mode, before_stat.st_nlink) == (
        after_stat.st_dev,
        after_stat.st_ino,
        after_stat.st_mode,
        after_stat.st_nlink,
    )
    assert tree(value.root) == before
    assert outside.read_bytes() == b"outside bytes must remain unchanged"


def test_missing_mandatory_catalog_is_not_an_optional_journal_read_conflict(job_case):
    value = job_case
    queued(value)
    reader = SqliteJobStore(value.root, create=False)
    (value.root / CATALOG).unlink()
    before = tree(value.root)
    with pytest.raises(JobStoreError) as caught:
        reader.get(value.spec.spec_id)
    assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
    cause = caught.value.__cause__
    assert isinstance(cause, FileNotFoundError) and cause.filename == CATALOG
    assert tree(value.root) == before and not (value.root / CATALOG).exists()


def test_replaced_optional_journal_identity_is_not_a_disappearance_conflict(job_case, monkeypatch):
    value = job_case
    queued(value)
    journal = value.root / JOURNAL
    journal.write_bytes(b"original journal fixture")
    replacement = value.root.parent / "replacement-journal"
    replacement.write_bytes(b"replacement journal must remain visible")
    assert replacement.stat().st_ino != journal.stat().st_ino
    actual_open, actual_stat = os.open, os.stat
    observed = {"opened": False, "replaced": False}

    def opened(path, flags, *args, **kwargs):
        descriptor = actual_open(path, flags, *args, **kwargs)
        if path == JOURNAL and kwargs.get("dir_fd") is not None:
            observed["opened"] = True
        return descriptor

    def statted(path, *args, **kwargs):
        if path == JOURNAL and kwargs.get("dir_fd") is not None and observed["opened"]:
            assert not observed["replaced"]
            os.replace(replacement, journal)
            observed["replaced"] = True
            observed["after_replace"] = tree(value.root)
        return actual_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        patch.setattr(os, "stat", statted)
        with pytest.raises(JobStoreError, match="path changed while open") as caught:
            value.store.get(value.spec.spec_id)
    assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
    assert observed["replaced"] and tree(value.root) == observed["after_replace"]
    assert journal.read_bytes() == b"replacement journal must remain visible"


@pytest.mark.parametrize("entry", ["regular", "symlink", "fifo", "directory"])
def test_zero_link_open_journal_with_a_current_replacement_remains_strict(
    job_case, monkeypatch, entry
):
    value = job_case
    queued(value)
    reader = SqliteJobStore(value.root, create=False)
    journal = value.root / JOURNAL
    outside = value.root.parent / "protected-replacement-target"
    outside.write_bytes(b"protected replacement target")

    def replace():
        if entry == "regular":
            journal.write_bytes(b"current replacement must remain visible")
        elif entry == "symlink":
            journal.symlink_to(outside)
        elif entry == "fifo":
            os.mkfifo(journal)
        else:
            journal.mkdir()

    with real_journal(value.root) as writer:
        with monkeypatch.context() as patch:
            observed = commit_at_boundary(patch, value.root, writer, "fstat", after_unlink=replace)
            try:
                with pytest.raises(JobStoreError) as caught:
                    reader.get(value.spec.spec_id)
            finally:
                assert_preflight_closed(observed)
            replacement_stat = journal.lstat()
        assert observed["commits"] == 1 and observed["zero_link_verified"]
        assert not writer.in_transaction
        assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
        assert tree(value.root) == observed["after_boundary"]
    retained = journal.lstat()
    assert (retained.st_dev, retained.st_ino, retained.st_mode, retained.st_nlink) == (
        replacement_stat.st_dev,
        replacement_stat.st_ino,
        replacement_stat.st_mode,
        replacement_stat.st_nlink,
    )
    assert outside.read_bytes() == b"protected replacement target"
    if entry == "regular":
        assert journal.read_bytes() == b"current replacement must remain visible"
    elif entry == "symlink":
        assert journal.readlink() == outside


@pytest.mark.parametrize(
    "failure_errno", [errno.EACCES, errno.EPERM, errno.EIO, errno.ELOOP, errno.ENOTDIR]
)
def test_zero_link_open_journal_other_named_stat_errno_never_becomes_a_conflict(
    job_case, monkeypatch, failure_errno
):
    value = job_case
    original = queued(value)
    reader = SqliteJobStore(value.root, create=False)
    with real_journal(value.root) as writer:
        with monkeypatch.context() as patch:
            observed = commit_at_boundary(
                patch, value.root, writer, "fstat", stat_errno=failure_errno
            )
            try:
                with pytest.raises(JobStoreError) as caught:
                    reader.get(value.spec.spec_id)
            finally:
                assert_preflight_closed(observed)
        assert observed["commits"] == 1 and observed["zero_link_verified"]
        assert not writer.in_transaction
        assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
        # The old product refuses before named stat; the corrected branch must retain
        # the actual non-ENOENT cause if it reaches this additional validation.
        assert len(observed["named_failures"]) <= 1
        if observed["named_failures"]:
            assert caught.value.__cause__ is observed["named_failures"][0]
            assert caught.value.__cause__.errno == failure_errno
        assert tree(value.root) == observed["after_commit"]
    assert reader.get(value.spec.spec_id) == original
    assert tree(value.root) == observed["after_commit"]


def unlink_at_open(patch, root, name, *, regular):
    """Remove an actually opened fixture without inventing an fstat observation."""
    actual_open, actual_stat, actual_fstat = os.open, os.stat, os.fstat
    observed = {"opened": False, "sqlite_connects": 0}

    def opened(path, flags, *args, **kwargs):
        descriptor = actual_open(path, flags, *args, **kwargs)
        if path == name and kwargs.get("dir_fd") is not None:
            assert not observed["opened"]
            observed["opened"] = True
            observed["descriptor"] = descriptor
            before = actual_fstat(descriptor)
            assert stat.S_ISREG(before.st_mode) is regular and before.st_nlink == 1
            os.unlink(path, dir_fd=kwargs["dir_fd"])
            after = actual_fstat(descriptor)
            assert stat.S_ISREG(after.st_mode) is regular and after.st_nlink == 0
            assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
            with pytest.raises(FileNotFoundError) as missing:
                actual_stat(path, dir_fd=kwargs["dir_fd"], follow_symlinks=False)
            assert missing.value.errno == errno.ENOENT and missing.value.filename == name
            observed["after_unlink"] = tree(root)
        return descriptor

    def no_sqlite_observation(*args, **kwargs):
        observed["sqlite_connects"] += 1
        raise AssertionError("Unsafe zero-link preflight must not connect to SQLite")

    patch.setattr(os, "open", opened)
    patch.setattr(sqlite3, "connect", no_sqlite_observation)
    return observed


@pytest.mark.parametrize("name", [CATALOG, "coordinator.lock"])
def test_zero_link_open_mandatory_file_is_never_an_optional_journal_conflict(
    job_case, monkeypatch, name
):
    value = job_case
    queued(value)
    reader = SqliteJobStore(value.root, create=False)
    with monkeypatch.context() as patch:
        observed = unlink_at_open(patch, value.root, name, regular=True)
        try:
            with pytest.raises(JobStoreError) as caught:
                if name == CATALOG:
                    reader.get(value.spec.spec_id)
                else:
                    reader.coordinator_active()
        finally:
            assert_preflight_closed(observed)
    assert observed["opened"]
    assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
    assert str(caught.value) == "Job catalog files must be unaliased regular files"
    assert tree(value.root) == observed["after_unlink"]
    assert not (value.root / name).exists()


def test_zero_link_open_nonregular_journal_is_never_an_absence_conflict(job_case, monkeypatch):
    value = job_case
    queued(value)
    reader = SqliteJobStore(value.root, create=False)
    os.mkfifo(value.root / JOURNAL)
    with monkeypatch.context() as patch:
        observed = unlink_at_open(patch, value.root, JOURNAL, regular=False)
        try:
            with pytest.raises(JobStoreError) as caught:
                reader.get(value.spec.spec_id)
        finally:
            assert_preflight_closed(observed)
    assert observed["opened"]
    assert not isinstance(caught.value, JobConflictError) and caught.value.exit_code == 3
    assert str(caught.value) == "Job catalog files must be unaliased regular files"
    assert tree(value.root) == observed["after_unlink"]
    assert not (value.root / JOURNAL).exists()
