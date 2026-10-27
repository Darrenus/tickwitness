"""Bounded append-only campaign files in a separate namespace of a run root.

This adapter stores opaque immutable bytes. The application revalidates domain
schemas, identities and original attempt/outcome closure. Root parents are
trusted owner configuration, not a hostile-host sandbox.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path

_HEADER_LIMIT = 4 * 1024 * 1024
_RECORD_LIMIT = 64 * 1024
_RESULT_LIMIT = 16 * 1024 * 1024
_MAX_ORDINAL = 1_024
_PENDING = re.compile(r"\.pending-[0-9a-f]{32}\Z")
_ENTRY = re.compile(r"([0-9]{4})\.json\Z")


class SearchCampaignStoreError(ValueError):
    """Campaign bytes cannot safely be stored or read; publication may be uncertain."""


class SearchCampaignNotFoundError(SearchCampaignStoreError):
    """The run root or campaign namespace does not exist."""


class SearchCampaignBusyError(SearchCampaignStoreError):
    """Another coordinator holds the same plan's nonblocking execution lock."""


def _identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SearchCampaignStoreError("Plan ID requires 64 lowercase hex characters")
    return value


def _ordinal(value: object) -> str:
    if type(value) is not int or not 1 <= value <= _MAX_ORDINAL:
        raise SearchCampaignStoreError("Candidate ordinal must be an integer in [1, 1024]")
    return f"{value:04}.json"


def _bounded(raw: bytes, limit: int) -> None:
    if not isinstance(raw, bytes) or not raw or len(raw) > limit:
        raise SearchCampaignStoreError("Campaign evidence must be nonempty bounded immutable bytes")


class LocalSearchCampaignStore:
    """No-follow reads and atomic no-replace publication of one plan's execution.

    Reads never create or repair files. A later fsync failure does not establish
    that a published name is absent. Incomplete staging files remain observable
    but are never interpreted as committed campaign evidence.
    """

    def __init__(self, root: Path, *, create: bool = False) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise SearchCampaignStoreError("Campaign storage requires POSIX no-follow operations")
        if type(create) is not bool:
            raise SearchCampaignStoreError("create must be a boolean")
        self._root = Path(root).absolute()
        self._writable = create
        try:
            if create:
                self._create_root()
            elif not self._root.exists():
                if self._root.is_symlink():
                    raise SearchCampaignStoreError("Campaign root cannot be a symlink")
                raise SearchCampaignNotFoundError("Search campaign root does not exist")
            with self._namespace(create=create):
                pass
        except FileNotFoundError as error:
            raise SearchCampaignNotFoundError("Search campaign namespace does not exist") from error
        except OSError as error:
            raise SearchCampaignStoreError(f"Cannot open search campaign store: {error}") from error

    def get_campaign(self, plan_id: str) -> bytes | None:
        return self._get(plan_id, None, "campaign.json", _HEADER_LIMIT)

    def start(self, plan_id: str, raw: bytes) -> None:
        self._put(plan_id, None, "campaign.json", raw, _HEADER_LIMIT)

    def get_dispatch(self, plan_id: str, ordinal: int) -> bytes | None:
        return self._get(plan_id, "dispatches", _ordinal(ordinal), _RECORD_LIMIT)

    def write_dispatch(self, plan_id: str, ordinal: int, raw: bytes) -> None:
        self._put(plan_id, "dispatches", _ordinal(ordinal), raw, _RECORD_LIMIT)

    def get_link(self, plan_id: str, ordinal: int) -> bytes | None:
        return self._get(plan_id, "links", _ordinal(ordinal), _RECORD_LIMIT)

    def write_link(self, plan_id: str, ordinal: int, raw: bytes) -> None:
        self._put(plan_id, "links", _ordinal(ordinal), raw, _RECORD_LIMIT)

    def get_result(self, plan_id: str, ordinal: int) -> bytes | None:
        return self._get(plan_id, "results", _ordinal(ordinal), _RESULT_LIMIT)

    def write_result(self, plan_id: str, ordinal: int, raw: bytes) -> None:
        self._put(plan_id, "results", _ordinal(ordinal), raw, _RESULT_LIMIT)

    def get_stop(self, plan_id: str) -> bytes | None:
        return self._get(plan_id, None, "stop.json", _RECORD_LIMIT)

    def write_stop(self, plan_id: str, raw: bytes) -> None:
        self._put(plan_id, None, "stop.json", raw, _RECORD_LIMIT)

    @contextmanager
    def lock(self, plan_id: str) -> Iterator[None]:
        """Serialize one plan's coordinator; do not wait or authorize resumption."""
        import fcntl

        self._write_allowed()
        try:
            with self._campaign(plan_id, create=True) as directory:
                descriptor = os.open(
                    ".lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                    mode=0o600,
                    dir_fd=directory,
                )
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise SearchCampaignStoreError("Campaign lock must be a regular file")
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise SearchCampaignBusyError(
                            "Search campaign is already running"
                        ) from error
                    try:
                        os.fsync(descriptor)
                        os.fsync(directory)
                        yield
                    finally:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        except OSError as error:
            raise SearchCampaignStoreError(f"Cannot lock search campaign: {error}") from error

    def check_tree(self, plan_id: str) -> dict[str, tuple[int, ...]]:
        """Reject unrecognized or unsafe entries without deleting crash staging."""
        inventory: dict[str, tuple[int, ...]] = {
            "dispatches": (),
            "links": (),
            "results": (),
        }
        try:
            with ExitStack() as campaign_stack:
                try:
                    directory = campaign_stack.enter_context(self._campaign(plan_id))
                except FileNotFoundError:
                    return inventory
                names = os.listdir(directory)
                if len(names) > 2 * _MAX_ORDINAL + 6:
                    raise SearchCampaignStoreError("Campaign directory contains too many files")
                for name in names:
                    if name in ("dispatches", "links", "results"):
                        with ExitStack() as stack:
                            child = self._directory(stack, directory, name, False)
                            children = os.listdir(child)
                            if len(children) > 2 * _MAX_ORDINAL:
                                raise SearchCampaignStoreError("Candidate directory is oversized")
                            limit = _RESULT_LIMIT if name == "results" else _RECORD_LIMIT
                            ordinals: list[int] = []
                            for filename in children:
                                match = _ENTRY.fullmatch(filename)
                                if _PENDING.fullmatch(filename) is None and (
                                    match is None or not 1 <= int(match.group(1)) <= _MAX_ORDINAL
                                ):
                                    raise SearchCampaignStoreError(
                                        "Unknown candidate evidence name"
                                    )
                                try:
                                    self._check_regular(child, filename, limit)
                                except FileNotFoundError:
                                    if _PENDING.fullmatch(filename):
                                        continue
                                    raise
                                if match is not None:
                                    ordinals.append(int(match.group(1)))
                            inventory[name] = tuple(sorted(ordinals))
                    elif name in ("campaign.json", "stop.json", ".lock") or _PENDING.fullmatch(
                        name
                    ):
                        limit = (
                            _HEADER_LIMIT
                            if name == "campaign.json" or _PENDING.fullmatch(name)
                            else _RECORD_LIMIT
                        )
                        try:
                            self._check_regular(directory, name, limit)
                        except FileNotFoundError:
                            if _PENDING.fullmatch(name):
                                continue
                            raise
                    else:
                        raise SearchCampaignStoreError("Unknown search campaign entry")
        except OSError as error:
            raise SearchCampaignStoreError(f"Cannot validate campaign tree: {error}") from error
        return inventory

    def _write_allowed(self) -> None:
        if not self._writable:
            raise SearchCampaignStoreError("Store was opened read-only")

    def _get(self, plan_id: str, category: str | None, name: str, limit: int) -> bytes | None:
        _identity(plan_id)
        try:
            with self._campaign(plan_id) as directory, ExitStack() as stack:
                parent = (
                    directory
                    if category is None
                    else self._directory(stack, directory, category, False)
                )
                return self._read(parent, name, limit)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise SearchCampaignStoreError(
                f"Cannot read search campaign evidence: {error}"
            ) from error

    def _put(self, plan_id: str, category: str | None, name: str, raw: bytes, limit: int) -> None:
        _identity(plan_id)
        _bounded(raw, limit)
        self._write_allowed()
        try:
            with self._campaign(plan_id, create=True) as directory:
                with ExitStack() as stack:
                    parent = (
                        directory
                        if category is None
                        else self._directory(stack, directory, category, True)
                    )
                    self._publish(parent, name, raw, limit)
        except OSError as error:
            raise SearchCampaignStoreError(
                f"Campaign publication unconfirmed; inspect existing evidence before retry: {error}"
            ) from error

    @contextmanager
    def _namespace(self, *, create: bool = False) -> Iterator[int]:
        with ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            yield self._directory(stack, root, "search-campaigns", create)

    @contextmanager
    def _campaign(self, plan_id: str, *, create: bool = False) -> Iterator[int]:
        _identity(plan_id)
        with self._namespace() as directory, ExitStack() as stack:
            yield self._directory(stack, directory, plan_id, create)

    @staticmethod
    def _directory(stack: ExitStack, parent: int, name: str, create: bool) -> int:
        if create:
            with suppress(FileExistsError):
                os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        stack.callback(os.close, descriptor)
        return descriptor

    def _create_root(self) -> None:
        missing: list[Path] = []
        current = self._root
        while not current.exists():
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            with suppress(FileExistsError):
                path.mkdir(mode=0o700)
            with ExitStack() as stack:
                child = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, child)
                parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                stack.callback(os.close, parent)
                os.fsync(child)
                os.fsync(parent)

    @staticmethod
    def _check_regular(directory: int, name: str, limit: int) -> None:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise SearchCampaignStoreError("Campaign evidence is not a bounded regular file")
        finally:
            os.close(descriptor)

    @staticmethod
    def _read(directory: int, name: str, limit: int, *, durable: bool = False) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise SearchCampaignStoreError("Campaign evidence is not a bounded regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
            _bounded(raw, limit)
            if durable:
                os.fsync(descriptor)
            return raw
        finally:
            os.close(descriptor)

    def _publish(self, directory: int, name: str, raw: bytes, limit: int) -> None:
        try:
            existing = self._read(directory, name, limit, durable=True)
            if existing != raw:
                raise SearchCampaignStoreError("Immutable campaign evidence already differs")
            os.fsync(directory)
            return
        except FileNotFoundError:
            pass
        temporary = f".pending-{secrets.token_hex(16)}"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode=0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                if self._read(directory, name, limit, durable=True) != raw:
                    raise SearchCampaignStoreError(
                        "Immutable campaign evidence already differs"
                    ) from error
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
