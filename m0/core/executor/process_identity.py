"""Shared Linux process identity parsing for the owner and detached wrapper.

Keep this module dependency-free beyond the standard library: the detached
wrapper loads it by file path without importing the executor package.
"""
from __future__ import annotations

from pathlib import Path


def _stat_fields(pid: int) -> list[str]:
    if type(pid) is not int or pid <= 0:
        raise ValueError("invalid process pid")
    text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    identity, opening, remainder = text.partition("(")
    _name, closing, fields = remainder.rpartition(")")
    # comm may contain spaces, newlines, '(' or ')'. The kernel's final ')'
    # separates it from field 3; splitting the whole record shifts field 22.
    if not opening or not closing or identity.strip() != str(pid):
        raise ValueError("invalid process stat identity")
    return fields.split()


def start_ticks(pid: int) -> int | None:
    try:
        value = int(_stat_fields(pid)[19])  # field 22, with state at index 0
        return value if value >= 0 else None
    except (OSError, ValueError, IndexError, UnicodeError):
        return None


def process_alive(pid: int, expected_start: int | None) -> bool:
    if type(expected_start) is not int or expected_start < 0:
        return False
    try:
        fields = _stat_fields(pid)
        return int(fields[19]) == expected_start and fields[0] != "Z"
    except (OSError, ValueError, IndexError, UnicodeError):
        return False
