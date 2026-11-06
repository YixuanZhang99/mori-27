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


@pytest.mark.parametrize('difference', ['program_ref', 'metrics', 'metric_type'])
def test_reference_cell_rejects_worker_and_physical_stage_disagreement(monkeypatch, difference):
    from zoo.circle_packing import reference_selection as module
    selected = {'id': 'candidate-1', 'program_ref': 'sha256:' + 'a' * 64,
                'metrics': {'validity': 1.0, 'combined_score': .5}}
    stage = {'program_ref': selected['program_ref'], 'metrics': dict(selected['metrics']), 'stage_count': 1}
    if difference == 'program_ref':
        stage['program_ref'] = 'sha256:' + 'b' * 64
    elif difference == 'metric_type':
        stage['metrics'] = {'validity': True, 'combined_score': .5}
    else:
        stage['metrics'] = {'validity': 0.0}
    monkeypatch.setattr(module, 'audit_anchored_reference_worker', lambda *args, **kwargs: {'worker_ref': 'a' * 64})
    monkeypatch.setattr(module, 'audit_anchored_reference_physical', lambda *args, **kwargs: stage)
    with pytest.raises(ValueError, match='worker.*stage'):
        module.audit_anchored_reference_cell(None, None, 'run', worker_proof={}, stdout='', stderr='',
            selected=selected, options={}, stamp={}, governance={}, rows=[], request_ids=['a' * 32])


def test_worker_receipt_must_match_anchored_final_stage(monkeypatch):
    from zoo.circle_packing import reference_selection as module
    anchor = {'worker_ref': 'a' * 64, 'cell_id': 'vendor-0', 'request_ids': ['1' * 32, '2' * 32]}
    monkeypatch.setattr(module, '_validated_reference_snapshot', lambda *args: anchor)
    started = {'execution_id': 'a' * 32, 'cell_id': 'vendor-0', 'worker_ref': 'a' * 64,
               'candidate_id': 'cell-worker', 'attempt': 1}
    terminal = {'execution_id': 'a' * 32, 'candidate_id': 'cell-worker', 'attempt': 1,
                'returncode': 0, 'timeout': False, 'recovered': False}
    selected = {'id': 'p', 'program_ref': 'sha256:' + 'a' * 64, 'metrics': {}}
    report = {'schema_version': 1, 'mode': 'fixture', 'performance_claim': False,
              'controller': 'pinned_openevolve', 'selected_program': selected,
              'selection_stage_request_id': '3' * 32}
    stdout = json.dumps(report)
    proof = {'schema_version': 1, 'started': started, 'terminal': terminal,
             'result': {'returncode': 0, 'timeout': False, 'wrapper_error': None,
                        'stdout_sha256': hashlib.sha256(stdout.encode()).hexdigest(),
                        'stderr_sha256': hashlib.sha256(b'').hexdigest()}}
    from core.x1.checkpoint import payload_digest
    anchor['worker_proof_sha256'] = payload_digest(proof)
    with pytest.raises(ValueError, match='stage'):
        module.audit_anchored_reference_worker(None, None, 'run', proof, stdout=stdout, stderr='', selected=selected)
