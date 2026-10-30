"""Shared Linux process identity parsing for the owner and detached wrapper.

Keep this module dependency-free beyond the standard library: the detached
wrapper loads it by file path without importing the executor package.
"""
from __future__ import annotations

from pathlib import Path
import sys


def _darwin_identity(pid: int) -> tuple[int, int]:
    """Read microsecond process birth time from Darwin's libproc, never `ps`.

    The proc_bsdinfo layout is the public sys/proc_info.h PROC_PIDTBSDINFO
    structure. A short read or a different pid is not an identity.
    """
    import ctypes
    class BsdInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint32) for name in (
            "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid",
            "svuid", "svgid", "reserved")] + [
            ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)] + [
            (name, ctypes.c_uint32) for name in ("nfiles", "pgid", "pjobc", "tdev", "tpgid")] + [
            ("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]
    if type(pid) is not int or pid <= 0:
        raise ValueError("invalid process pid")
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    call = library.proc_pidinfo
    call.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    call.restype = ctypes.c_int
    info = BsdInfo()
    if call(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info) or info.pid != pid \
            or info.start_usec >= 1_000_000 or info.start_sec == 0:
        raise OSError("stable Darwin process identity unavailable")
    return info.start_sec * 1_000_000 + info.start_usec, info.status


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
        if sys.platform == "darwin":
            return _darwin_identity(pid)[0]
        value = int(_stat_fields(pid)[19])  # field 22, with state at index 0
        return value if value >= 0 else None
    except (OSError, ValueError, IndexError, UnicodeError):
        return None


def process_alive(pid: int, expected_start: int | None) -> bool:
    if type(expected_start) is not int or expected_start < 0:
        return False
    try:
        if sys.platform == "darwin":
            started, status = _darwin_identity(pid)
            return started == expected_start and status != 5  # SZOMB, sys/proc.h
        fields = _stat_fields(pid)
        return int(fields[19]) == expected_start and fields[0] != "Z"
    except (OSError, ValueError, IndexError, UnicodeError):
        return False
