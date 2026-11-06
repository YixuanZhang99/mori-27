"""Reference process evidence is read only from its own bounded artifacts."""
import json

import pytest

from zoo.circle_packing.host_runtime import _read_verified_worker_result


def worker_artifacts(tmp_path):
    execution_id = 'a' * 32
    root = tmp_path / 'executor-processes' / execution_id
    root.mkdir(parents=True)
    files = {'result_path': root / 'result.json', 'stdout_path': root / 'stdout.txt',
             'stderr_path': root / 'stderr.txt'}
    files['result_path'].write_text(json.dumps({'returncode': 0, 'timeout': False}))
    files['stdout_path'].write_text('report')
    files['stderr_path'].write_text('diagnostics')
    return files, {'execution_id': execution_id, **{key: str(value) for key, value in files.items()}}


def test_read_worker_result_from_bound_files(tmp_path):
    _, started = worker_artifacts(tmp_path)
    assert _read_verified_worker_result(tmp_path, started) == {
        'returncode': 0, 'timeout': False, 'stdout': 'report', 'stderr': 'diagnostics', 'wrapper_error': None}


@pytest.mark.parametrize('change', ['symlink', 'directory-symlink', 'hardlink', 'oversize',
                                   'duplicate-json', 'boolean-returncode'])
def test_reject_untrusted_worker_artifacts(tmp_path, change):
    files, started = worker_artifacts(tmp_path)
    output, result = files['stdout_path'], files['result_path']
    if change == 'symlink':
        output.unlink()
        output.symlink_to(result)
    elif change == 'directory-symlink':
        directory = output.parent
        moved = directory.with_name('moved')
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    elif change == 'hardlink':
        (output.parent / 'alias').hardlink_to(output)
    elif change == 'oversize':
        output.write_bytes(b'x' * (8 * 1024 * 1024 + 1))
    elif change == 'duplicate-json':
        result.write_text('{"returncode":0,"returncode":0,"timeout":false}')
    else:
        result.write_text('{"returncode":false,"timeout":false}')
    with pytest.raises(ValueError):
        _read_verified_worker_result(tmp_path, started)
