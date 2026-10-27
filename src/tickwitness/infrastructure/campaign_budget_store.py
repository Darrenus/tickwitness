"""Immutable bounded-campaign control records beside the original attempt ledger.

Only the parent coordinator owns the plan lock. Child admission writes are part
of that same sequential operation. Managed payloads live below managed/; these
control records use the separately reserved control/terminal capacity.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import cast

from tickwitness.domain.search.budgets import (
    MAX_CAMPAIGN_BUDGET_BYTES,
    TERMINAL_RESERVE_BYTES,
    CampaignBudget,
    CampaignBudgetValidationError,
    load_allocation,
    load_budget_stop,
    load_campaign_budget,
)

_PENDING = re.compile(r"\.pending-[0-9a-f]{32}\Z")
_ENTRY = re.compile(r"([0-9]{4})\.json\Z")


class CampaignBudgetStoreError(ValueError):
    """Control evidence cannot be safely read or published; commit may be uncertain."""


class CampaignBudgetNotFoundError(CampaignBudgetStoreError):
    """The bounded campaign root or budget is absent."""


class CampaignBudgetBusyError(CampaignBudgetStoreError):
    """A parent supervisor already holds this plan's nonblocking lock."""


def _identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise CampaignBudgetStoreError("Plan ID requires 64 lowercase hexadecimal characters")
    return value


def _ordinal(value: object) -> str:
    if type(value) is not int or not 1 <= value <= 1_024:
        raise CampaignBudgetStoreError("Allocation ordinal must be an integer in [1, 1024]")
    return f"{value:04}.json"


class LocalCampaignBudgetStore:
    """No-follow regular files, no-replace writes, and immutable allocation order."""

    def __init__(self, root: Path, *, create: bool = False) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise CampaignBudgetStoreError("Budget storage requires POSIX no-follow operations")
        if type(create) is not bool:
            raise CampaignBudgetStoreError("create must be a boolean")
        self._root = Path(root).absolute()
        self._writable = create
        try:
            if create:
                self._create_root()
            elif not self._root.exists():
                if self._root.is_symlink():
                    raise CampaignBudgetStoreError("Budget root cannot be a symlink")
                raise CampaignBudgetNotFoundError("Bounded campaign root does not exist")
            with self._namespace(create=create):
                pass
        except FileNotFoundError as error:
            raise CampaignBudgetNotFoundError("Bounded campaign namespace does not exist") from error
        except OSError as error:
            raise CampaignBudgetStoreError(f"Cannot open campaign budget store: {error}") from error

    def managed_root(self, plan_id: str) -> Path:
        """Return a fixed trusted path without creating or repairing any directory."""
        _identity(plan_id)
        return self._root / "bounded-search-campaigns" / plan_id / "managed"

    def get_budget(self, plan_id: str) -> bytes | None:
        raw = self._get(plan_id, None, "budget.json", MAX_CAMPAIGN_BUDGET_BYTES)
        if raw is not None:
            try:
                budget = load_campaign_budget(raw)
                if budget.document["plan_id"] != plan_id:
                    raise CampaignBudgetStoreError("Budget belongs to another plan")
            except CampaignBudgetValidationError as error:
                raise CampaignBudgetStoreError(f"Invalid frozen campaign budget: {error}") from error
        return raw

    def start(self, plan_id: str, raw: bytes) -> None:
        try:
            budget = load_campaign_budget(raw)
            if budget.document["plan_id"] != _identity(plan_id):
                raise CampaignBudgetStoreError("Budget belongs to another plan")
        except CampaignBudgetValidationError as error:
            raise CampaignBudgetStoreError(f"Invalid campaign budget: {error}") from error
        self._put(plan_id, None, "budget.json", raw, MAX_CAMPAIGN_BUDGET_BYTES)

    def _budget(self, plan_id: str) -> CampaignBudget:
        raw = self.get_budget(plan_id)
        if raw is None:
            raise CampaignBudgetNotFoundError("Campaign budget has not been started")
        return load_campaign_budget(raw)

    def get_allocations(self, plan_id: str) -> tuple[bytes, ...]:
        budget = self._budget(plan_id)
        records: list[tuple[int, bytes]] = []
        try:
            with self._campaign(plan_id) as directory, ExitStack() as stack:
                try:
                    allocations = self._directory(stack, directory, "allocations", False)
                except FileNotFoundError:
                    return ()
                names = os.listdir(allocations)
                if len(names) > 200:
                    raise CampaignBudgetStoreError("Allocation directory contains too many files")
                for name in names:
                    if _PENDING.fullmatch(name):
                        try:
                            self._check_regular(allocations, name, MAX_CAMPAIGN_BUDGET_BYTES)
                        except FileNotFoundError:
                            pass
                        continue
                    match = _ENTRY.fullmatch(name)
                    if match is None or not 1 <= int(match.group(1)) <= 1_024:
                        raise CampaignBudgetStoreError("Unknown allocation evidence name")
                    raw = self._read(allocations, name, MAX_CAMPAIGN_BUDGET_BYTES)
                    document = load_allocation(raw, budget=budget)
                    if document["ordinal"] != int(match.group(1)):
                        raise CampaignBudgetStoreError("Allocation filename differs from its ordinal")
                    records.append((cast("int", document["index"]), raw))
        except (OSError, CampaignBudgetValidationError) as error:
            raise CampaignBudgetStoreError(f"Cannot verify campaign allocations: {error}") from error
        records.sort()
        if [index for index, _ in records] != list(range(1, len(records) + 1)):
            raise CampaignBudgetStoreError("Campaign allocation indexes are not a unique prefix")
        return tuple(raw for _, raw in records)

    def write_allocation(self, plan_id: str, ordinal: int, raw: bytes) -> None:
        budget = self._budget(plan_id)
        try:
            document = load_allocation(raw, budget=budget)
        except CampaignBudgetValidationError as error:
            raise CampaignBudgetStoreError(f"Invalid campaign allocation: {error}") from error
        if document["ordinal"] != ordinal:
            raise CampaignBudgetStoreError("Allocation ordinal differs from requested target")
        if self.get_stop(plan_id) is not None:
            raise CampaignBudgetStoreError("A terminated campaign cannot admit another candidate")
        records = self.get_allocations(plan_id)
        for existing in records:
            prior = load_allocation(existing, budget=budget)
            if prior["ordinal"] == ordinal:
                if existing != raw:
                    raise CampaignBudgetStoreError("Immutable allocation already differs")
                self._put(plan_id, "allocations", _ordinal(ordinal), raw, MAX_CAMPAIGN_BUDGET_BYTES)
                return
        if document["index"] != len(records) + 1:
            raise CampaignBudgetStoreError("New allocation must append the next index")
        self._put(plan_id, "allocations", _ordinal(ordinal), raw, MAX_CAMPAIGN_BUDGET_BYTES)

    def get_stop(self, plan_id: str) -> bytes | None:
        budget = self._budget(plan_id)
        raw = self._get(plan_id, None, "stop.json", TERMINAL_RESERVE_BYTES)
        if raw is not None:
            try:
                load_budget_stop(raw, budget=budget)
            except CampaignBudgetValidationError as error:
                raise CampaignBudgetStoreError(f"Invalid campaign budget stop: {error}") from error
        return raw

    def control_payload_bytes(self, plan_id: str) -> int:
        """Count visible control payloads, including crash staging but excluding managed/."""
        self.check_tree(plan_id)
        total = 0
        try:
            with ExitStack() as stack:
                try:
                    directory = stack.enter_context(self._campaign(plan_id))
                except FileNotFoundError:
                    return 0
                for name in os.listdir(directory):
                    if name == "managed":
                        continue
                    if name == "allocations":
                        child = self._directory(stack, directory, name, False)
                        for entry in os.listdir(child):
                            try:
                                total += self._payload_size(child, entry, MAX_CAMPAIGN_BUDGET_BYTES)
                            except FileNotFoundError:
                                if _PENDING.fullmatch(entry):
                                    continue
                                raise
                    else:
                        try:
                            total += self._payload_size(directory, name, MAX_CAMPAIGN_BUDGET_BYTES)
                        except FileNotFoundError:
                            if _PENDING.fullmatch(name):
                                continue
                            raise
        except OSError as error:
            raise CampaignBudgetStoreError(f"Cannot measure control evidence: {error}") from error
        return total

    def write_stop(self, plan_id: str, raw: bytes) -> None:
        budget = self._budget(plan_id)
        try:
            load_budget_stop(raw, budget=budget)
        except CampaignBudgetValidationError as error:
            raise CampaignBudgetStoreError(f"Invalid campaign budget stop: {error}") from error
        self._put(plan_id, None, "stop.json", raw, TERMINAL_RESERVE_BYTES)

    @contextmanager
    def lock(self, plan_id: str) -> Iterator[None]:
        import fcntl

        self._write_allowed()
        try:
            with self._campaign(plan_id, create=True) as directory:
                descriptor = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     mode=0o600, dir_fd=directory)
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise CampaignBudgetStoreError("Budget lock must be a regular file")
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise CampaignBudgetBusyError("Bounded campaign is already running") from error
                    try:
                        os.fsync(descriptor)
                        os.fsync(directory)
                        yield
                    finally:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        except OSError as error:
            raise CampaignBudgetStoreError(f"Cannot lock campaign budget: {error}") from error

    def check_tree(self, plan_id: str) -> dict[str, object]:
        """Validate the control tree; managed/ is independently checked by its reader."""
        inventory: dict[str, object] = {"budget": False, "stop": False, "allocations": (), "managed": False}
        try:
            with ExitStack() as stack:
                try:
                    directory = stack.enter_context(self._campaign(plan_id))
                except FileNotFoundError:
                    return inventory
                names = os.listdir(directory)
                budget_raw = self.get_budget(plan_id)
                if len(names) > 206:
                    raise CampaignBudgetStoreError("Budget directory is oversized")
                for name in names:
                    if name == "managed":
                        self._directory(stack, directory, name, False)
                        inventory["managed"] = True
                    elif name == "allocations":
                        child = self._directory(stack, directory, name, False)
                        if budget_raw is not None:
                            budget = load_campaign_budget(budget_raw)
                            inventory["allocations"] = tuple(
                                load_allocation(raw, budget=budget)["ordinal"]
                                for raw in self.get_allocations(plan_id)
                            )
                        else:
                            children = os.listdir(child)
                            if len(children) > 200:
                                raise CampaignBudgetStoreError("Allocation directory is oversized")
                            ordinals: list[int] = []
                            for entry in children:
                                match = _ENTRY.fullmatch(entry)
                                if _PENDING.fullmatch(entry) is None and (
                                    match is None or not 1 <= int(match.group(1)) <= 1_024
                                ):
                                    raise CampaignBudgetStoreError("Unknown orphan allocation name")
                                try:
                                    self._check_regular(child, entry, MAX_CAMPAIGN_BUDGET_BYTES)
                                except FileNotFoundError:
                                    if _PENDING.fullmatch(entry):
                                        continue
                                    raise
                                if match is not None:
                                    ordinals.append(int(match.group(1)))
                            inventory["allocations"] = tuple(sorted(ordinals))
                    elif name in ("budget.json", "stop.json", ".lock") or _PENDING.fullmatch(name):
                        try:
                            self._check_regular(directory, name, MAX_CAMPAIGN_BUDGET_BYTES)
                        except FileNotFoundError:
                            if _PENDING.fullmatch(name):
                                continue
                            raise
                        if name == "budget.json":
                            self.get_budget(plan_id)
                            inventory["budget"] = True
                        elif name == "stop.json":
                            if budget_raw is not None:
                                self.get_stop(plan_id)
                            inventory["stop"] = True
                    else:
                        raise CampaignBudgetStoreError("Unknown bounded campaign entry")
        except OSError as error:
            raise CampaignBudgetStoreError(f"Cannot check budget evidence: {error}") from error
        return inventory

    def _write_allowed(self) -> None:
        if not self._writable:
            raise CampaignBudgetStoreError("Budget store was opened read-only")

    def _get(self, plan_id: str, category: str | None, name: str, limit: int) -> bytes | None:
        _identity(plan_id)
        try:
            with self._campaign(plan_id) as directory, ExitStack() as stack:
                parent = directory if category is None else self._directory(stack, directory, category, False)
                return self._read(parent, name, limit)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise CampaignBudgetStoreError(f"Cannot read campaign budget: {error}") from error

    def _put(self, plan_id: str, category: str | None, name: str, raw: bytes, limit: int) -> None:
        _identity(plan_id)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
            raise CampaignBudgetStoreError("Budget evidence must be nonempty bounded immutable bytes")
        self._write_allowed()
        try:
            with self._campaign(plan_id, create=True) as directory, ExitStack() as stack:
                parent = directory if category is None else self._directory(stack, directory, category, True)
                self._publish(parent, name, raw, limit)
        except OSError as error:
            raise CampaignBudgetStoreError(
                f"Budget publication unconfirmed; inspect existing evidence before retry: {error}"
            ) from error

    @contextmanager
    def _namespace(self, *, create: bool = False) -> Iterator[int]:
        with ExitStack() as stack:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            yield self._directory(stack, root, "bounded-search-campaigns", create)

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
                raise CampaignBudgetStoreError("Budget evidence is not a bounded regular file")
        finally:
            os.close(descriptor)

    @staticmethod
    def _payload_size(directory: int, name: str, limit: int) -> int:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise CampaignBudgetStoreError("Control evidence is not a bounded regular file")
            return info.st_size
        finally:
            os.close(descriptor)

    @staticmethod
    def _read(directory: int, name: str, limit: int, *, durable: bool = False) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise CampaignBudgetStoreError("Budget evidence is not a bounded regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
            if not 0 < len(raw) <= limit:
                raise CampaignBudgetStoreError("Budget evidence exceeds its byte cap")
            if durable:
                os.fsync(descriptor)
            return raw
        finally:
            os.close(descriptor)

    def _publish(self, directory: int, name: str, raw: bytes, limit: int) -> None:
        try:
            existing = self._read(directory, name, limit, durable=True)
            if existing != raw:
                raise CampaignBudgetStoreError("Immutable budget evidence already differs")
            os.fsync(directory)
            return
        except FileNotFoundError:
            pass
        temporary = f".pending-{secrets.token_hex(16)}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             mode=0o600, dir_fd=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError as error:
                if self._read(directory, name, limit, durable=True) != raw:
                    raise CampaignBudgetStoreError("Immutable budget evidence already differs") from error
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)


BudgetStore = LocalCampaignBudgetStore
