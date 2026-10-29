"""Versioned x86_64 seccomp denylist for Bubblewrap evaluation commands.

This is a small, explicit dangerous-syscall denylist, not an allowlist, cgroup,
complete resource policy, or boundary against a hostile kernel.  The canonical
classic-BPF program rejects listed syscalls and non-native x32 encodings with
EPERM and kills on audit-architecture mismatch.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import platform
import struct
from collections.abc import Callable
from contextlib import contextmanager

SECCOMP_POLICY_NAME = "dangerous-syscall-denylist"
SECCOMP_POLICY_VERSION = 2
SECCOMP_FD_PLACEHOLDER = "__AR_SECCOMP_FD__"
SECCOMP_BWRAP_MEMFD = "bwrap_memfd"
SECCOMP_DIRECT_PRCTL = "direct_prctl"
SECCOMP_DELIVERIES = {SECCOMP_BWRAP_MEMFD, SECCOMP_DIRECT_PRCTL}

# Linux x86_64 syscall numbers are part of the policy, not host-header discovery.
_X86_64_SYSCALLS = {
    "add_key": 248,
    "bpf": 321,
    "delete_module": 176,
    "finit_module": 313,
    "fsconfig": 431,
    "fsmount": 432,
    "fsopen": 430,
    "fspick": 433,
    "init_module": 175,
    "kexec_file_load": 320,
    "kexec_load": 246,
    "keyctl": 250,
    "mount": 165,
    "mount_setattr": 442,
    "move_mount": 429,
    "name_to_handle_at": 303,
    "open_by_handle_at": 304,
    "open_tree": 428,
    "perf_event_open": 298,
    "pivot_root": 155,
    "ptrace": 101,
    "reboot": 169,
    "request_key": 249,
    "setns": 308,
    "swapoff": 168,
    "swapon": 167,
    "umount2": 166,
    "unshare": 272,
    "userfaultfd": 323,
}
DENIED_SYSCALLS = tuple(sorted(_X86_64_SYSCALLS))

_AUDIT_ARCH_X86_64 = 0xC000003E
# x32 shares AUDIT_ARCH_X86_64, so the audit-architecture check alone cannot
# distinguish its syscall table. Also reject the untagged x32-only range that
# Linux kernels before 5.4 incorrectly accepted. See seccomp(2), Filters.
_X32_SYSCALL_BIT = 0x40000000
_X32_LEGACY_SYSCALL_RANGE = (512, 547)
_BPF_LD_W_ABS = 0x20
_BPF_JMP_JEQ_K = 0x15
_BPF_JMP_JGE_K = 0x35
_BPF_JMP_JSET_K = 0x45
_BPF_RET_K = 0x06
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ERRNO_EPERM = 0x00050000 | 1
_SECCOMP_RET_ALLOW = 0x7FFF0000


def _instruction(code: int, jt: int, jf: int, value: int) -> bytes:
    return struct.pack("<HBBI", code, jt, jf, value)


def _filter_bytes() -> bytes:
    instructions = [
        _instruction(_BPF_LD_W_ABS, 0, 0, 4),  # seccomp_data.arch
        _instruction(_BPF_JMP_JEQ_K, 1, 0, _AUDIT_ARCH_X86_64),
        _instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_KILL_PROCESS),
        _instruction(_BPF_LD_W_ABS, 0, 0, 0),  # seccomp_data.nr
        # Reject every x32-tagged number, including nominally harmless calls;
        # this policy supports only the native x86_64 ABI.
        _instruction(_BPF_JMP_JSET_K, 0, 1, _X32_SYSCALL_BIT),
        _instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO_EPERM),
        # If nr < 512 or nr >= 548, continue to the native denylist. Otherwise
        # reject the legacy untagged x32 range before any syscall can execute.
        _instruction(_BPF_JMP_JGE_K, 0, 2, _X32_LEGACY_SYSCALL_RANGE[0]),
        _instruction(_BPF_JMP_JGE_K, 1, 0, _X32_LEGACY_SYSCALL_RANGE[1] + 1),
        _instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO_EPERM),
    ]
    for name in DENIED_SYSCALLS:
        instructions.extend([
            _instruction(_BPF_JMP_JEQ_K, 0, 1, _X86_64_SYSCALLS[name]),
            _instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO_EPERM),
        ])
    instructions.append(_instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW))
    return b"".join(instructions)


def build_seccomp_policy(architecture: str | None = None) -> dict:
    """Return the only filter program accepted by this policy version."""
    architecture = platform.machine() if architecture is None else architecture
    if architecture != "x86_64":
        raise RuntimeError(
            f"seccomp policy v{SECCOMP_POLICY_VERSION} requires x86_64; got {architecture}")
    encoded = _filter_bytes()
    return {
        "schema_version": 1,
        "policy": SECCOMP_POLICY_NAME,
        "policy_version": SECCOMP_POLICY_VERSION,
        "architecture": "x86_64",
        "action": "errno:EPERM",
        "denied_syscall_bits": _X32_SYSCALL_BIT,
        "denied_syscall_ranges": [list(_X32_LEGACY_SYSCALL_RANGE)],
        "denied_syscalls": list(DENIED_SYSCALLS),
        "filter_sha256": hashlib.sha256(encoded).hexdigest(),
        "filter_base64": base64.b64encode(encoded).decode("ascii"),
    }


def validate_seccomp_policy(payload: dict) -> bytes:
    """Fail closed unless payload exactly denotes the canonical host policy.

    Rebuilding rather than trusting a digest also rejects a tampered filter whose
    attacker-controlled SHA256 field was recomputed. Older policy versions are
    not silently upgraded: a durable v1 spec must not launch under its weaker
    ABI rules or be relabeled as having executed with v2.
    """
    if not isinstance(payload, dict):
        raise ValueError("seccomp policy must be an object")
    expected = build_seccomp_policy(payload.get("architecture"))
    if payload != expected:
        raise ValueError("seccomp policy differs from the canonical versioned denylist")
    encoded = base64.b64decode(expected["filter_base64"], validate=True)
    if hashlib.sha256(encoded).hexdigest() != expected["filter_sha256"]:
        raise ValueError("seccomp filter digest mismatch")
    return encoded


def validate_seccomp_delivery(payload: dict | None, delivery: str | None) -> str | None:
    if payload is None:
        if delivery is not None:
            raise ValueError("seccomp delivery requires a policy")
        return None
    if delivery not in SECCOMP_DELIVERIES:
        raise ValueError("seccomp policy requires explicit bwrap_memfd or direct_prctl delivery")
    return delivery


def direct_seccomp_preexec(payload: dict) -> Callable[[], None]:
    """Prepare a direct prctl installer before fork; no Python imports in the child."""
    encoded = validate_seccomp_policy(payload)

    class SockFilter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                    ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]

    class SockProg(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(SockFilter))]

    filters = (SockFilter * (len(encoded) // 8)).from_buffer_copy(encoded)
    program = SockProg(len(filters), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.restype = ctypes.c_int

    def install() -> None:
        # PR_SET_NO_NEW_PRIVS is required for an unprivileged direct filter.
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, "PR_SET_NO_NEW_PRIVS failed")
        # PR_SET_SECCOMP + SECCOMP_MODE_FILTER installs a kernel-copied program.
        if libc.prctl(22, 2, ctypes.byref(program)) != 0:
            error = ctypes.get_errno()
            raise OSError(error, "PR_SET_SECCOMP failed")

    return install


def materialize_seccomp(args: list[str], payload: dict | None,
                        delivery: str | None = None) -> tuple[list[str], int | None]:
    """Validate policy and prepare its explicit bwrap or direct delivery."""
    if payload is not None and delivery is None:
        delivery = SECCOMP_BWRAP_MEMFD  # v56 durable-spec compatibility
    validate_seccomp_delivery(payload, delivery)
    args = list(args)
    markers = [index for index, value in enumerate(args)
               if value == SECCOMP_FD_PLACEHOLDER]
    if payload is None:
        if markers:
            raise ValueError("seccomp fd placeholder requires a durable policy")
        return args, None
    encoded = validate_seccomp_policy(payload)
    if delivery == SECCOMP_DIRECT_PRCTL:
        if markers:
            raise ValueError("direct_prctl seccomp cannot use a bwrap fd placeholder")
        return args, None
    if len(markers) != 1 or markers[0] == 0 or args[markers[0] - 1] != "--seccomp":
        raise ValueError("seccomp policy requires exactly one bwrap --seccomp fd marker")
    if not hasattr(os, "memfd_create"):
        raise RuntimeError("seccomp policy requires os.memfd_create")
    fd = os.memfd_create(f"autoresearch-seccomp-v{SECCOMP_POLICY_VERSION}")
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("failed to write seccomp memfd")
            view = view[written:]
        os.lseek(fd, 0, os.SEEK_SET)
    except BaseException:
        os.close(fd)
        raise
    args[markers[0]] = str(fd)
    return args, fd


@contextmanager
def seccomp_arguments(args: list[str], payload: dict | None):
    """Yield Popen-ready args/pass_fds and close the parent fd immediately after."""
    replaced, fd = materialize_seccomp(args, payload)
    try:
        yield replaced, () if fd is None else (fd,)
    finally:
        if fd is not None:
            os.close(fd)


def seccomp_policy_summary(payload: dict | None) -> dict | None:
    """Public journal metadata; filter bytes remain only in the durable spec."""
    if payload is None:
        return None
    validate_seccomp_policy(payload)
    return {key: value for key, value in payload.items() if key != "filter_base64"}
