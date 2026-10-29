#!/usr/bin/env python3
"""Fail early when the current interpreter cannot run the actual Linux sandbox."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "m0"))


def main() -> int:
    if sys.platform != "linux" or platform.machine() != "x86_64":
        print("Full acceptance requires Linux x86_64. Use `make check` for Mac development.", file=sys.stderr)
        return 1
    from core.executor.process import start_ticks
    from core.executor.sandbox import BubblewrapSandbox
    from core.executor.seccomp import seccomp_arguments

    if start_ticks(os.getpid()) is None:
        print("Linux /proc process identity is unavailable.", file=sys.stderr)
        return 1
    try:
        sandbox = BubblewrapSandbox()
        with tempfile.TemporaryDirectory(prefix="mori27-preflight-") as directory:
            command = sandbox.wrap(
                [sys.executable, "-c", "import sys; assert sys.version_info[:2] == (3, 12); print('sandbox Python ready')"],
                Path(directory), env={})
            with seccomp_arguments(command, sandbox.seccomp_spec()) as (args, pass_fds):
                result = subprocess.run(args, pass_fds=pass_fds, capture_output=True,
                                        text=True, timeout=30)
            if result.returncode:
                print(result.stderr, file=sys.stderr)
                print("Sandbox startup failed. Check user namespaces and place Python/venv under /usr (see docs/DEVELOPMENT.md).", file=sys.stderr)
                return 1
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"Linux execution preflight failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"platform": platform.platform(), "python": sys.executable,
                      "bwrap": shutil.which("bwrap"), "sandbox_python": "passed"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
