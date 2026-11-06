"""The reported reference winner must match the actual saved upstream artifact."""
import hashlib
import json

import pytest


def artifacts(tmp_path):
    best = tmp_path / 'host-run' / 'host' / 'best'
    best.mkdir(parents=True)
    code = 'def run():\n    return 1\n'
    selected = {'id': 'candidate-1', 'program_ref': 'sha256:' + hashlib.sha256(code.encode()).hexdigest(),
                'metrics': {'validity': 1.0, 'combined_score': 0.5}}
    (best / 'best_program.py').write_text(code)
    (best / 'best_program_info.json').write_text(json.dumps({'id': selected['id'], 'metrics': selected['metrics']}))
    return best, code, selected


def test_reference_selection_reads_and_binds_saved_code_and_metadata(tmp_path):
    from zoo.circle_packing.reference_selection import read_reference_selection
    _, _, selected = artifacts(tmp_path)
    result = read_reference_selection(tmp_path, selected)
    assert result == {'saved_program_ref': selected['program_ref']}


@pytest.mark.parametrize('change', ['program', 'id', 'metrics', 'symlink', 'directory-symlink', 'hardlink',
                                   'oversize', 'duplicate-field'])
def test_reference_selection_rejects_substituted_artifacts(tmp_path, change):
    from zoo.circle_packing.reference_selection import read_reference_selection
    best, _, selected = artifacts(tmp_path)
    code = best / 'best_program.py'
    info = best / 'best_program_info.json'
    if change == 'program':
        code.write_text('different')
    elif change in ('id', 'metrics'):
        value = json.loads(info.read_text())
        value[change] = 'wrong' if change == 'id' else {'validity': 0.0}
        info.write_text(json.dumps(value))
    elif change == 'symlink':
        code.unlink()
        code.symlink_to(info)
    elif change == 'directory-symlink':
        moved = best.with_name('other')
        best.rename(moved)
        best.symlink_to(moved, target_is_directory=True)
    elif change == 'hardlink':
        (best / 'alias.py').hardlink_to(code)
    elif change == 'oversize':
        code.write_text('x' * (1024 * 1024 + 1))
    else:
        info.write_text('{"id":"candidate-1","id":"candidate-1","metrics":{}}')
    with pytest.raises(ValueError):
        read_reference_selection(tmp_path, selected)
