"""Trusted namespace init refuses an unsafe launch and preserves command behavior."""
import subprocess
import sys

import pytest

from core.executor.sandbox import BubblewrapSandbox


def test_sandbox_bootstrap_refuses_payload_outside_pid_namespace(tmp_path):
    # Execute the actual command portion without bwrap creating a namespace.
    # The bootstrap must refuse before workspace-controlled code can run.
    sandbox = BubblewrapSandbox(executable=sys.executable, seccomp=False)
    command = sandbox.wrap([sys.executable, '-c',
        "from pathlib import Path; Path('payload-ran').write_text('unsafe')"], tmp_path)
    result = subprocess.run(command[command.index('--') + 1:], cwd=tmp_path,
                            capture_output=True, timeout=5)
    assert result.returncode != 0
    assert b'sandbox init requires its own PID namespace' in result.stderr
    assert not (tmp_path / 'payload-ran').exists()


@pytest.mark.linux
@pytest.mark.parametrize(('command', 'expected'), [
    (['/usr/bin/python3', '-c', 'import sys; sys.exit(0)'], 0),
    (['/usr/bin/python3', '-c', 'import sys; sys.exit(17)'], 17),
    (['/usr/bin/python3', '-c', 'import os,signal; os.kill(os.getpid(), signal.SIGTERM)'], 143),
    (['/bin/sh', '-c', 'kill -PIPE $$'], 141),
    (['/sandbox-command-does-not-exist'], 1),
])
def test_namespace_init_preserves_payload_exit_status(tmp_path, command, expected):
    sandbox = BubblewrapSandbox(seccomp=False)
    result = subprocess.run(sandbox.wrap(command, tmp_path),
                            capture_output=True, timeout=10)
    assert result.returncode == expected, result.stderr.decode(errors='replace')


@pytest.mark.linux
def test_namespace_init_refuses_missing_parent_death_signal(tmp_path):
    sandbox = BubblewrapSandbox(seccomp=False)
    command = sandbox.wrap(['/usr/bin/python3', '-c',
        "from pathlib import Path; Path('payload-ran').write_text('unsafe')"], tmp_path)
    command.remove('--die-with-parent')
    result = subprocess.run(command, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert b'sandbox init requires inherited parent-death SIGKILL' in result.stderr
    assert not (tmp_path / 'payload-ran').exists()


@pytest.mark.linux
def test_namespace_init_preserves_shell_fallback_for_executable_script(tmp_path):
    script = tmp_path / 'without-shebang'
    script.write_text('printf "%s\\n" "$1"\n')
    script.chmod(0o755)
    sandbox = BubblewrapSandbox(seccomp=False)
    result = subprocess.run(sandbox.wrap([str(script), 'fallback argument'], tmp_path),
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout == b'fallback argument\n'


@pytest.mark.linux
def test_namespace_init_does_not_add_locale_to_non_python_payload(tmp_path):
    sandbox = BubblewrapSandbox(seccomp=False)
    result = subprocess.run(sandbox.wrap(['/usr/bin/env', '-0'], tmp_path),
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    values = dict(item.split(b'=', 1) for item in result.stdout.split(b'\0') if item)
    assert b'LC_CTYPE' not in values


@pytest.mark.linux
def test_namespace_init_never_imports_workspace_modules(tmp_path):
    for name in ('ctypes', 'signal', 'sitecustomize'):
        (tmp_path / (name + '.py')).write_text(
            "from pathlib import Path; Path('untrusted-init').write_text('loaded'); "
            "raise RuntimeError('workspace code ran in namespace init')\n")
    sandbox = BubblewrapSandbox(seccomp=False)
    result = subprocess.run(sandbox.wrap(['/usr/bin/true'], tmp_path),
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert not (tmp_path / 'untrusted-init').exists()


@pytest.mark.linux
def test_namespace_init_reaps_orphans_and_preserves_payload_arguments(tmp_path):
    sandbox = BubblewrapSandbox(seccomp=False)
    program = '''import os,sys,time
assert os.getpid() != 1 and os.getppid() == 1
assert sys.argv[1:] == ['argument with spaces', '--literal']
assert os.environ['AR_SEED_SET'] == 'fixture-seeds'
reader, writer = os.pipe()
middle = os.fork()
if middle == 0:
    os.close(reader)
    orphan = os.fork()
    if orphan == 0:
        os._exit(0)
    os.write(writer, str(orphan).encode('ascii'))
    os._exit(0)
os.close(writer)
orphan = int(os.read(reader, 32))
os.close(reader)
os.waitpid(middle, 0)
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    try:
        os.kill(orphan, 0)
    except ProcessLookupError:
        print('orphan reaped', flush=True)
        break
    time.sleep(.01)
else:
    raise AssertionError('namespace init did not reap the orphan')
'''
    result = subprocess.run(sandbox.wrap(['/usr/bin/python3', '-c', program,
        'argument with spaces', '--literal'], tmp_path, env={'AR_SEED_SET': 'fixture-seeds'}),
        capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout == b'orphan reaped\n'
