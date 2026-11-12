"""Injected write failures leave publication retryable without changing evidence."""

import errno
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from tickwitness.infrastructure.local_dataset_store import DatasetStoreError, LocalDatasetStore

RAW = b"new complete raw bytes for the bounded write-fault fixture\n"
NORMALIZED = b'{"fixture":"new normalized evidence"}\n'
REPORT: dict[str, object] = {"fixture": "new write-fault candidate"}


def immutable_files(root: Path) -> dict[str, bytes]:
    """Exclude ordinary SQLite lifecycle metadata from the immutable-byte claim."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for directory in (root / "objects" / "sha256", root / "manifests")
        for path in directory.iterdir()
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("fault", "expected_errno"),
    [("positive_short", errno.EIO), ("zero_short", errno.EIO), ("enospc", errno.ENOSPC)],
)
def test_incomplete_write_preserves_baseline_and_allows_explicit_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, expected_errno: int
) -> None:
    root = tmp_path / "store"
    store = LocalDatasetStore(root)
    baseline = store.publish(
        b"healthy previously published raw", b"healthy normalized", {"fixture": "healthy baseline"}
    )
    baseline_readback = store.read_artifacts(baseline.dataset_id)
    before = immutable_files(root)
    objects = root / "objects" / "sha256"
    target = objects / hashlib.sha256(RAW).hexdigest()
    assert not target.exists()
    actual_fdopen = os.fdopen
    observed: list[dict[str, object]] = []

    class FaultedWriter:
        def __init__(self, stream):
            self.stream = stream

        def write(self, data):
            assert not observed, "A publication must not silently retry an incomplete write"
            count = 0 if fault == "zero_short" else len(data) // 2
            written = self.stream.write(data[:count])
            # Make the declared prefix a real file observation, not merely a
            # mocked return value. This flush belongs to fault preparation.
            self.stream.flush()
            pending = list(objects.glob(".pending-*"))
            assert len(pending) == 1
            prefix = pending[0].read_bytes()
            assert written == count and prefix == data[:count]
            observed.append({"requested": len(data), "written": written, "prefix": prefix})
            if fault == "enospc":
                raise OSError(errno.ENOSPC, "Injected exhaustion after an actual pending prefix")
            return written

        def flush(self):
            return self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

    @contextmanager
    def faulted_fdopen(descriptor, mode, *args, **kwargs):
        with actual_fdopen(descriptor, mode, *args, **kwargs) as stream:
            yield FaultedWriter(stream) if mode == "wb" and not observed else stream

    with monkeypatch.context() as patch:
        patch.setattr(os, "fdopen", faulted_fdopen)
        with pytest.raises(DatasetStoreError) as caught:
            store.publish(RAW, NORMALIZED, REPORT)

    cause = caught.value.__cause__
    assert isinstance(cause, OSError) and cause.errno == expected_errno
    assert len(observed) == 1 and observed[0]["requested"] == len(RAW)
    assert observed[0]["written"] == (0 if fault == "zero_short" else len(RAW) // 2)
    assert not target.exists()
    assert immutable_files(root) == before
    assert not list(objects.glob(".pending-*"))
    assert not list((root / "manifests").glob(".pending-*"))
    assert [record.dataset_id for record in store.list_datasets()] == [baseline.dataset_id]
    assert store.read_artifacts(baseline.dataset_id) == baseline_readback

    # Removing only the injection does not run a retry. The caller explicitly
    # publishes the complete source, then explicitly observes idempotence.
    recovered = store.publish(RAW, NORMALIZED, REPORT)
    repeated = store.publish(RAW, NORMALIZED, REPORT)
    assert recovered.created is True and repeated.created is False
    assert recovered.dataset_id == repeated.dataset_id
    assert target.read_bytes() == RAW
    assert recovered.report == REPORT
    assert store.read_artifacts(baseline.dataset_id) == baseline_readback
    assert {record.dataset_id for record in store.list_datasets()} == {
        baseline.dataset_id,
        recovered.dataset_id,
    }
    for relative, content in before.items():
        assert (root / relative).read_bytes() == content
    assert not list(objects.glob(".pending-*"))
    assert not list((root / "manifests").glob(".pending-*"))
