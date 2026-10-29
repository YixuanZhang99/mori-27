#!/usr/bin/env python3
"""Safely simulate AutoResearch seccomp BPF decisions without installing a filter.

Usage: python3 autoresearch-audit-seccomp-probe.py /path/to/project/m0

This imports only the existing policy's pure bytecode builder. It never calls
prctl, seccomp, add_key, ptrace, or any other target kernel syscall, and it does
not create a subprocess. The result demonstrates filter decisions, not a real
kernel exploit or a Bubblewrap sandbox escape.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import struct
import sys


def simulate(program: bytes, syscall_number: int, architecture: int) -> int:
    """Interpret the small LD/JEQ/RET instruction subset in this policy."""
    if len(program) % 8:
        raise ValueError("Malformed BPF instruction length")
    instructions = list(struct.iter_unpack("<HBBI", program))
    accumulator = 0
    pc = 0
    steps = 0
    while 0 <= pc < len(instructions):
        steps += 1
        if steps > 10_000:
            raise ValueError("Interpreter step limit exceeded")
        code, jump_true, jump_false, value = instructions[pc]
        if code == 0x20:  # BPF_LD | BPF_W | BPF_ABS
            if value not in (0, 4):
                raise ValueError("Unsupported seccomp_data offset")
            accumulator = syscall_number if value == 0 else architecture
            pc += 1
        elif code == 0x15:  # BPF_JMP | BPF_JEQ | BPF_K
            pc += 1 + (jump_true if accumulator == value else jump_false)
        elif code == 0x06:  # BPF_RET | BPF_K
            return value
        else:
            raise ValueError(f"Unsupported BPF opcode: {code:#x}")
    raise ValueError("BPF program exited without returning a decision")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("m0_root", type=Path)
    args = parser.parse_args()
    source = args.m0_root.resolve() / "core/executor/seccomp.py"
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("autoresearch_audit_policy", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load policy: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    program = module._filter_bytes()
    cases = [
        ("native_add_key", 248, 0xC000003E),
        ("x32_add_key", 248 | 0x40000000, 0xC000003E),
        ("native_ptrace", 101, 0xC000003E),
        ("x32_ptrace", 521 | 0x40000000, 0xC000003E),
        ("different_audit_arch", 248, 0x40000003),
    ]
    labels = {0x00050001: "ERRNO_EPERM", 0x7FFF0000: "ALLOW", 0x80000000: "KILL_PROCESS"}
    results = []
    for name, number, architecture in cases:
        decision = simulate(program, number, architecture)
        results.append({"case": name, "syscall_number": number,
                        "audit_arch": f"{architecture:#010x}",
                        "decision": labels.get(decision, "OTHER"),
                        "return_value": f"{decision:#010x}"})
    report = {
        "mode": "pure_python_bpf_interpreter",
        "target_syscalls_invoked": False,
        "kernel_filter_installed": False,
        "real_kernel_exploit_verified": False,
        "bubblewrap_escape_verified": False,
        "source": str(source),
        "cases": results,
        "interpretation": "ALLOW proves only this BPF policy would allow the numbered request; actual execution depends on kernel ABI support and other isolation layers.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
