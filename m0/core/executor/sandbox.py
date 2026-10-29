"""Bubblewrap isolation for untrusted M7 evaluation commands.

This backend isolates filesystem, network, process/IPC namespaces and environment,
and by default installs the versioned dangerous-syscall seccomp denylist.  It is
not a complete resource-limit policy or a boundary against a hostile kernel.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from core.executor.seccomp import (SECCOMP_FD_PLACEHOLDER, build_seccomp_policy)
from core.executor.workspace import safe_relative


class BubblewrapSandbox:
    """Build a least-privilege bwrap command without persisting host environment."""

    SAFE_ENV = ("AR_FIDELITY", "AR_BUDGET_TOKEN", "AR_SEED_SET")

    def __init__(self, executable: str = "bwrap", *, seccomp: bool = True):
        self.executable = shutil.which(executable) if "/" not in executable else executable
        if not self.executable or not Path(self.executable).is_file():
            raise RuntimeError("BubblewrapSandbox requires an installed bwrap executable")
        if not isinstance(seccomp, bool):
            raise TypeError("BubblewrapSandbox seccomp must be explicitly boolean")
        self.seccomp = seccomp

    def seccomp_spec(self) -> dict | None:
        """Return canonical policy for the durable process spec, if enabled."""
        return build_seccomp_policy() if self.seccomp else None

    @staticmethod
    def _directories(command: list[str], path: Path) -> None:
        parents = list(path.parents)
        for directory in reversed(parents):
            if directory != directory.parent:
                command.extend(["--dir", str(directory)])

    def wrap(self, args: list[str], cwd: Path, protected_paths=(),
             data_dir: str = "", env: dict | None = None) -> list[str]:
        root = cwd.resolve()
        if not args or not root.is_dir():
            raise ValueError("sandbox requires a command and existing workspace")
        command = [self.executable]
        if self.seccomp:
            # ProcessJournal's wrapper replaces this marker with a real inherited
            # memfd number; bwrap never receives the placeholder itself.
            command.extend(["--seccomp", SECCOMP_FD_PLACEHOLDER])
        command.extend(["--unshare-all", "--die-with-parent",
                   "--new-session", "--cap-drop", "ALL", "--clearenv",
                   "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
                   "--setenv", "LD_LIBRARY_PATH",
                   "/usr/local/lib:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu",
                   "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp"])
        for key in self.SAFE_ENV:
            if env is not None and key in env:
                command.extend(["--setenv", key, str(env[key])])
        for source in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
            path = Path(source)
            if path.exists():
                command.extend(["--ro-bind", source, source])
        # Some unprivileged hosts forbid a fresh procfs mount even with userns.
        # Keep an empty /proc rather than weakening namespace isolation or failing open.
        command.extend(["--tmpfs", "/tmp", "--dev", "/dev", "--dir", "/proc"])
        self._directories(command, root)
        command.extend(["--bind", str(root), str(root)])
        for relative in protected_paths:
            protected = safe_relative(root, relative)
            if not protected.exists():
                raise ValueError(f"sandbox protected path is missing: {relative}")
            command.extend(["--ro-bind", str(protected), str(protected)])
        if data_dir:
            data = Path(data_dir).resolve()
            if not data.is_dir():
                raise ValueError("sandbox data_dir must be an existing directory")
            self._directories(command, data)
            command.extend(["--ro-bind", str(data), str(data)])
        command.extend(["--chdir", str(root), "--", *args])
        return command
