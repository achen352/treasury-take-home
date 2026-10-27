"""Catches any attempt to write to disk, using Python's audit hooks (PEP 578).

Audit hooks can't be removed once added, so one hook is installed for the whole test run and
only records while a `no_disk_writes()` block is active. Code imported for the first time can
write bytecode caches, so callers run the code once before guarding it.
"""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_WRITE_EVENTS = frozenset(
    {
        "os.mkdir",
        "os.rename",
        "os.remove",
        "os.truncate",
        "shutil.copyfile",
        "tempfile.mkstemp",
        "tempfile.mkdtemp",
    }
)
_active: list[list[str]] = []
_installed = False


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if not _active:
        return
    if event == "open":
        path, mode, flags = args
        writes_by_mode = isinstance(mode, str) and any(c in mode for c in "wax+")
        writes_by_flags = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        if writes_by_mode or writes_by_flags:
            _active[-1].append(f"open {path!r} mode={mode!r} flags={flags!r}")
    elif event in _WRITE_EVENTS:
        _active[-1].append(f"{event} {args!r}")


@contextmanager
def no_disk_writes() -> Iterator[list[str]]:
    """Yield a list that collects every file write attempted inside the block."""
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
    writes: list[str] = []
    _active.append(writes)
    try:
        yield writes
    finally:
        _active.pop()
