"""v2 ABI guards: portable bytecode semantics and real Linux delivery probes.

The pure interpreter evaluates generated classic BPF without invoking any
syscall. Linux probes use invalid arguments for potentially mutating calls and
also test harmless getpid, so missing kernel x32 support cannot mimic EPERM.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor.sandbox import BubblewrapSandbox
from core.executor.seccomp import (build_seccomp_policy, direct_seccomp_preexec,
                                   materialize_seccomp, seccomp_arguments,
                                   validate_seccomp_policy)

ARCH_X86_64 = 0xC000003E
X32_BIT = 0x40000000
ALLOW = 0x7FFF0000
EPERM = 0x00050001
KILL_PROCESS = 0x80000000


def run_filter(program: bytes, number: int, architecture: int = ARCH_X86_64) -> int:
    """Execute only the load/jump/return cBPF subset used by this policy."""
    instructions = list(struct.iter_unpack("<HBBI", program))
    accumulator = 0
    pc = 0
    for _ in range(len(instructions) + 1):
        assert 0 <= pc < len(instructions), "filter fell off its program"
        code, true_jump, false_jump, value = instructions[pc]
        if code == 0x20:  # LD W ABS, uint32 seccomp_data fields
            assert value in (0, 4)
            accumulator = (number if value == 0 else architecture) & 0xFFFFFFFF
            pc += 1
        elif code in (0x15, 0x35, 0x45):  # JEQ, unsigned JGE, JSET
            condition = (accumulator == value if code == 0x15 else
                         accumulator >= value if code == 0x35 else
                         bool(accumulator & value))
            pc += 1 + (true_jump if condition else false_jump)
        elif code == 0x06:  # RET K
            return value
        else:
            raise AssertionError(f"unexpected BPF opcode {code:#x}")
    raise AssertionError("filter did not terminate")


def canonical_program() -> bytes:
    return validate_seccomp_policy(build_seccomp_policy("x86_64"))


def test_native_syscalls_retain_their_existing_decisions():
    program = canonical_program()
    # Ordinary read/write/close/getpid/exit remain permitted. Selected dangerous
    # calls are independently pinned to Linux's native syscall numbers.
    for number in (0, 1, 3, 39, 60, 231):
        assert run_filter(program, number) == ALLOW
    for number in (101, 165, 248, 250, 272, 321, 323, 442):
        assert run_filter(program, number) == EPERM


def test_all_x32_tagged_numbers_are_rejected_before_native_matching():
    program = canonical_program()
    # Include allowed native numbers, denied ones, all x32-specific numbers and
    # values outside today's syscall tables. The bit guard is ABI-wide.
    for number in (*range(548), 1024, 0x20000000, 0x3FFFFFFF, 0x80000000):
        assert run_filter(program, number | X32_BIT) == EPERM, number


def test_legacy_x32_range_and_exact_boundaries():
    program = canonical_program()
    assert run_filter(program, 511) == ALLOW
    for number in range(512, 548):
        assert run_filter(program, number) == EPERM, number
    assert run_filter(program, 548) == ALLOW


@pytest.mark.parametrize("architecture", [0, 0x40000003, 0xC00000B7, 0xFFFFFFFF])
def test_wrong_audit_architecture_is_killed_even_for_otherwise_allowed_calls(architecture):
    program = canonical_program()
    for number in (0, 39, 101, 512, 39 | X32_BIT):
        assert run_filter(program, number, architecture) == KILL_PROCESS


def test_stale_v1_policy_cannot_be_replayed_or_relabelled_as_v2():
    policy = build_seccomp_policy("x86_64")
    instructions = list(struct.iter_unpack("<HBBI", base64.b64decode(policy["filter_base64"])))
    # v1 contained the same four-instruction architecture guard followed by the
    # native denylist. Removing the five ABI instructions recreates that flaw.
    vulnerable = b"".join(struct.pack("<HBBI", *instruction)
                          for instruction in instructions[:4] + instructions[9:])
    assert run_filter(vulnerable, 39 | X32_BIT) == ALLOW
    old = copy.deepcopy(policy)
    old.update(policy_version=1, filter_base64=base64.b64encode(vulnerable).decode(),
               filter_sha256=hashlib.sha256(vulnerable).hexdigest())
    old.pop("denied_syscall_bits")
    old.pop("denied_syscall_ranges")
    with pytest.raises(ValueError, match="canonical versioned denylist"):
        validate_seccomp_policy(old)
    relabelled = copy.deepcopy(policy)
    relabelled.update(filter_base64=old["filter_base64"], filter_sha256=old["filter_sha256"])
    with pytest.raises(ValueError, match="canonical versioned denylist"):
        validate_seccomp_policy(relabelled)
    # Validation precedes memfd creation or any target process launch.
    with pytest.raises(ValueError, match="canonical versioned denylist"):
        materialize_seccomp(["python", "-c", "pass"], old, "direct_prctl")


@pytest.mark.parametrize("field,value", [
    ("denied_syscall_bits", 0),
    ("denied_syscall_ranges", []),
    ("denied_syscall_ranges", [[513, 547]]),
])
def test_abi_guard_metadata_is_part_of_the_canonical_policy(field, value):
    policy = build_seccomp_policy("x86_64")
    policy[field] = value
    with pytest.raises(ValueError, match="canonical versioned denylist"):
        validate_seccomp_policy(policy)


KERNEL_PROBE = """
import ctypes, errno, json, os
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
results = []
for number in (39, 101, 39 | 0x40000000, 101 | 0x40000000,
               521 | 0x40000000, 512, 521, 547):
    ctypes.set_errno(0)
    # Invalid request/fd/signal arguments make the probe non-mutating even if a
    # regression permits the call. Native and x32 getpid are harmless getters.
    result = libc.syscall(ctypes.c_long(number), *[ctypes.c_long(-1)] * 6)
    error = ctypes.get_errno()
    results.append([number, result, error])
    if number == 39:
        assert result == os.getpid(), results
    else:
        assert result == -1 and error == errno.EPERM, results
print(json.dumps(results))
"""


@pytest.mark.linux
@pytest.mark.skipif(sys.platform != "linux" or platform.machine() != "x86_64",
                    reason="real ABI filter delivery requires Linux x86_64")
@pytest.mark.parametrize("delivery", ["direct_prctl", "bwrap_memfd"])
def test_real_kernel_rejects_abi_encodings_for_both_delivery_paths(tmp_path, delivery):
    policy = build_seccomp_policy()
    command = [sys.executable, "-c", KERNEL_PROBE]
    if delivery == "direct_prctl":
        result = subprocess.run(command, preexec_fn=direct_seccomp_preexec(policy),
                                capture_output=True, text=True, timeout=10)
    else:
        if shutil.which("bwrap") is None:
            pytest.skip("real ABI filter delivery requires bubblewrap")
        sandbox = BubblewrapSandbox()
        wrapped = sandbox.wrap(command, tmp_path, env={})
        with seccomp_arguments(wrapped, policy) as (arguments, pass_fds):
            result = subprocess.run(arguments, pass_fds=pass_fds,
                                    capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    observations = json.loads(result.stdout)
    assert len(observations) == 8
    assert [row[2] for row in observations[1:]] == [1] * 7
