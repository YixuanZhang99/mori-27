"""Bubblewrap isolation for untrusted M7 evaluation commands.

This backend isolates filesystem, network, process/IPC namespaces and environment,
and by default installs the versioned dangerous-syscall seccomp denylist.  It is
not a complete resource-limit policy or a boundary against a hostile kernel.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.executor.seccomp import (SECCOMP_FD_PLACEHOLDER, build_seccomp_policy)
from core.executor.workspace import safe_relative


# Run only from the read-only system Python, with workspace imports disabled.
# bwrap arms PID 1's parent-death signal before exec; fork the untrusted command
# only afterwards, rather than racing bwrap's separate init startup. This does
# not close bwrap's earlier setup-before-exec parent-death window.
_NAMESPACE_INIT = '''import os,sys
if os.getpid() != 1:
    raise SystemExit('sandbox init requires its own PID namespace')
import ctypes,signal
libc = ctypes.CDLL(None, use_errno=True)
death_signal = ctypes.c_int()
if libc.prctl(2, ctypes.byref(death_signal), 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), 'PR_GET_PDEATHSIG')
if death_signal.value != signal.SIGKILL:
    raise SystemExit('sandbox init requires inherited parent-death SIGKILL')
if libc.prctl(4, 0, 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), 'PR_SET_DUMPABLE')
# wrap's cleared environment never supplies a locale. Undo Python startup's
# C-locale coercion before launching a non-Python command.
os.environ.pop('LC_CTYPE', None)
arguments = [os.fsencode(value) for value in sys.argv[1:]]
argv = (ctypes.c_char_p * (len(arguments) + 1))(*arguments, None)
libc.execvp.argtypes = (ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p))
libc.execvp.restype = ctypes.c_int
signal.signal(signal.SIGINT, signal.SIG_DFL)
child = os.fork()
if child == 0:
    for name in ('SIGPIPE', 'SIGXFZ', 'SIGXFSZ'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_DFL)
    libc.execvp(argv[0], argv)
    print('sandbox command exec failed: ' + os.strerror(ctypes.get_errno()),
          file=sys.stderr, flush=True)
    os._exit(1)
while True:
    pid, status = os.wait()
    if pid == child:
        if os.WIFEXITED(status):
            os._exit(os.WEXITSTATUS(status))
        if os.WIFSIGNALED(status):
            os._exit(128 + os.WTERMSIG(status))
'''


def sandbox_child_path():
    """Keep the host-selected bwrap available in a sanitized child environment."""
    executable = shutil.which('bwrap')
    if not executable or not Path(executable).is_file():
        raise RuntimeError('BubblewrapSandbox requires an installed bwrap executable')
    return str(Path(executable).absolute().parent) + os.pathsep + os.defpath


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
             data_dir: str = "", env: dict | None = None, readonly_paths=()) -> list[str]:
        root = cwd.resolve()
        if not args or not root.is_dir():
            raise ValueError("sandbox requires a command and existing workspace")
        command = [self.executable]
        if self.seccomp:
            # ProcessJournal's wrapper replaces this marker with a real inherited
            # memfd number; bwrap never receives the placeholder itself.
            command.extend(["--seccomp", SECCOMP_FD_PLACEHOLDER])
        command.extend(["--unshare-all", "--die-with-parent", "--as-pid-1",
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
        for value in readonly_paths:
            readonly = Path(value).resolve(strict=True)
            if not readonly.is_dir() or readonly == root or root in readonly.parents or readonly in root.parents:
                raise ValueError("read-only runtime must be a separate directory")
            self._directories(command, readonly)
            command.extend(["--ro-bind", str(readonly), str(readonly)])
        command.extend(["--chdir", str(root), "--", "/usr/bin/python3", "-I", "-S",
                        "-c", _NAMESPACE_INIT, *args])
        return command
