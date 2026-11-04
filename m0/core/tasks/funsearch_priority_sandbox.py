"""Experimental isolated priority subprocess; not yet a durable task runner."""
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

import numpy as np

from core.composition.funsearch_validator import program_validator
from core.executor.sandbox import BubblewrapSandbox
from core.executor.seccomp import seccomp_arguments


PROCESS_CREATION_POLICY = 'deny-fork-clone-x86_64-v1'

_RUNNER = '''import ctypes,errno,json,resource,runpy,sys
resource.setrlimit(resource.RLIMIT_CPU, (__CPU_LIMIT__, __CPU_LIMIT__))
resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3))
resource.setrlimit(resource.RLIMIT_FSIZE, (1024 ** 2, 1024 ** 2))
import numpy as np
# The outer sandbox has already installed the x86-64 architecture/x32 guard.
# Stack an irreversible filter before loading the candidate: no fork, vfork,
# clone, or clone3 (including thread creation) is permitted.
class Filter(ctypes.Structure):
    _fields_ = [("code",ctypes.c_ushort),("jt",ctypes.c_ubyte),("jf",ctypes.c_ubyte),("k",ctypes.c_uint32)]
class Program(ctypes.Structure):
    _fields_ = [("len",ctypes.c_ushort),("filter",ctypes.POINTER(Filter))]
rules=[Filter(0x20,0,0,0)]
for number in (56,57,58,435):
    rules.extend((Filter(0x15,0,1,number),Filter(0x06,0,0,0x00050000|errno.EPERM)))
rules.append(Filter(0x06,0,0,0x7fff0000))
filters=(Filter*len(rules))(*rules)
program=Program(len(filters),filters)
libc=ctypes.CDLL(None,use_errno=True)
if libc.prctl(38,1,0,0,0)!=0 or libc.prctl(22,2,ctypes.byref(program))!=0:
    raise RuntimeError("cannot install process-creation filter")
priority=runpy.run_path("candidate.py",init_globals={"np":np})["priority"]
for line in sys.stdin.buffer:
    request=json.loads(line)
    result=np.asarray(priority(request["item"],np.asarray(request["bins"]))).tolist()
    print(json.dumps(result,allow_nan=False,separators=(",",":")),flush=True)
'''


class SandboxedPriority:
    """Exchange bounded priority vectors with a data-free Bubblewrap child."""
    def __init__(self, template, source, *, timeout):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('a finite positive total timeout is required')
        if program_validator(template, 'priority')(source):
            raise ValueError('candidate differs from the frozen function contract')
        self.source, self.timeout = source, float(timeout)
        self.process, self.directory, self.buffer = None, None, bytearray()

    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='mori-priority-')
        root = Path(self.directory.name)
        (root / 'candidate.py').write_text(self.source)
        (root / 'runner.py').write_text(_RUNNER.replace('__CPU_LIMIT__', str(math.ceil(self.timeout) + 1)))

        try:
            sandbox = BubblewrapSandbox()
            command = sandbox.wrap([sys.executable, str(root / 'runner.py')], root,
                                   protected_paths=('candidate.py', 'runner.py'))
            boundary = command.index('--')
            command[boundary:boundary] = ['--setenv', 'OPENBLAS_NUM_THREADS', '1']
            with seccomp_arguments(command, sandbox.seccomp_spec()) as (args, fds):
                self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=fds)
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            self.deadline = time.monotonic() + self.timeout
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _wait(self, stream, event):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('sandboxed priority exceeded its total deadline')
        with selectors.DefaultSelector() as selector:
            selector.register(stream, event)
            if not selector.select(remaining):
                raise TimeoutError('sandboxed priority exceeded its total deadline')

    def __call__(self, item, bins):
        if self.process is None or self.process.poll() is not None:
            raise ValueError('sandboxed priority process is unavailable')
        encoded = (json.dumps({'item': int(item), 'bins': np.asarray(bins).tolist()},
                              allow_nan=False, separators=(',', ':')) + '\n').encode()
        view = memoryview(encoded)
        while view:
            self._wait(self.process.stdin, selectors.EVENT_WRITE)
            view = view[os.write(self.process.stdin.fileno(), view):]
        while b'\n' not in self.buffer:
            self._wait(self.process.stdout, selectors.EVENT_READ)
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise ValueError('sandboxed priority produced no result')
            self.buffer.extend(chunk)
            if len(self.buffer) > 1024 ** 2:
                raise ValueError('sandboxed priority response exceeds the limit')
        line, _, rest = self.buffer.partition(b'\n')
        self.buffer = bytearray(rest)
        try:
            result = np.asarray(json.loads(line))
        except (ValueError, TypeError) as error:
            raise ValueError('sandboxed priority returned invalid JSON') from error
        if result.shape != np.asarray(bins).shape or result.dtype.kind not in 'fiu' or not np.isfinite(result).all():
            raise ValueError('sandboxed priority returned an invalid score vector')
        return result

    def __exit__(self, *_args):
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
        return False
