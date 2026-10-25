"""Bounded POSIX input reads anchored to an explicitly chosen directory.

The configured root and its parents are trusted owner configuration. Every
relative path component below that root is opened without following symlinks.
This is an import boundary, not a sandbox for malicious code running as owner.
"""

import os
import stat
from contextlib import ExitStack
from pathlib import Path


class InputReadError(ValueError):
    """An input is unsafe, unsupported, changed during reading, or exceeds its budget."""


def read_jsonl(input_root: Path, relative_path: str, *, max_bytes: int) -> bytes:
    """Read one regular JSONL file within a trusted root, with a hard byte bound."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise InputReadError("max_bytes must be a positive integer")
    parts = relative_path.split("/")
    if (
        not relative_path
        or len(relative_path) > 4096
        or len(parts) > 64
        or "\\" in relative_path
        or "\x00" in relative_path
        or any(part in {"", ".", ".."} for part in parts)
        or not parts[-1].endswith(".jsonl")
    ):
        raise InputReadError("Input must be a relative .jsonl path without traversal")
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise InputReadError("Safe directory-relative import is unsupported on this platform")

    try:
        with ExitStack() as stack:
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory_fd = os.open(input_root, directory_flags)
            stack.callback(os.close, directory_fd)
            for part in parts[:-1]:
                directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                stack.callback(os.close, directory_fd)

            # Nonblocking open lets us reject a FIFO instead of waiting for a writer.
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
            )
            stack.callback(os.close, descriptor)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise InputReadError("Input must be a regular file")
            if before.st_size > max_bytes:
                raise InputReadError("Input exceeds max_bytes")
            chunks = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(65_536, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise InputReadError("Input exceeds max_bytes")
            after = os.fstat(descriptor)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise InputReadError("Input changed while being read")
            return b"".join(chunks)
    except OSError as error:
        raise InputReadError(f"Cannot safely open input: {error.strerror}") from error
