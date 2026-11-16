"""Optional rollback-journal races refuse observations without weakening IO checks."""

import errno
import os
import sqlite3
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


def commit_at_boundary(patch, root, connection, phase):
    """Commit at one preflight boundary, then delegate the actual failing syscall."""
    actual_open, actual_stat = os.open, os.stat
    observed = {"opened": False, "commits": 0}

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
            return descriptor
        return actual_open(path, flags, *args, **kwargs)

    def statted(path, *args, **kwargs):
        if path == JOURNAL and kwargs.get("dir_fd") is not None and observed["opened"]:
            assert phase == "restat"
            commit()
        return actual_stat(path, *args, **kwargs)

    def no_sqlite_observation(*args, **kwargs):
        raise AssertionError("A conflicted preflight must not open or yield a SQLite observation")

    patch.setattr(os, "open", opened)
    patch.setattr(os, "stat", statted)
    patch.setattr(sqlite3, "connect", no_sqlite_observation)
    return observed


@pytest.mark.parametrize("phase", ["open", "restat"])
@pytest.mark.parametrize("method", ["get", "events", "result"])
def test_real_commit_journal_disappearance_is_an_explicit_read_conflict(
    job_case, monkeypatch, phase, method
):
    value = job_case
    original = queued(value)
    history = value.store.events(value.spec.spec_id)
    reader = SqliteJobStore(value.root, create=False)
    with real_journal(value.root) as writer:
        with monkeypatch.context() as patch:
            observed = commit_at_boundary(patch, value.root, writer, phase)
            with pytest.raises(JobConflictError, match="read is busy; retry read") as caught:
                getattr(reader, method)(value.spec.spec_id)
        assert observed["commits"] == 1 and not writer.in_transaction
        assert tree(value.root) == observed["after_commit"]
    cause = caught.value.__cause__
    assert isinstance(cause, FileNotFoundError)
    assert cause.errno == errno.ENOENT and cause.filename == JOURNAL
    assert caught.value.code == "job_conflict" and caught.value.exit_code == 9
    assert reader.get(value.spec.spec_id) == original
    assert reader.events(value.spec.spec_id) == history
    assert reader.result(value.spec.spec_id) is None
    assert tree(value.root) == observed["after_commit"]


@pytest.mark.parametrize("phase", ["open", "restat"])
def test_real_commit_journal_disappearance_keeps_writer_io_unconfirmed(
    job_case, monkeypatch, phase
):
    value = job_case
    original = queued(value)
    with value.store.coordinator():
        with real_journal(value.root) as writer:
            with monkeypatch.context() as patch:
                observed = commit_at_boundary(patch, value.root, writer, phase)
                with pytest.raises(JobStoreError) as caught, value.store._connection(write=True):
                    pytest.fail("A failed writer preflight must not yield a connection")
            assert observed["commits"] == 1
            assert tree(value.root) == observed["after_commit"]
        assert not isinstance(caught.value, JobConflictError)
        assert caught.value.exit_code == 3
        cause = caught.value.__cause__
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
