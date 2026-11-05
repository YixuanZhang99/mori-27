"""Original-row identities survive extraction and source drift is refused."""
import hashlib
import json

import pytest

from zoo.gepa_gsm8k.prepare_data import prepare, SOURCE_SHA256
from zoo.gepa_gsm8k.domain import FrozenDataset


def test_preparation_freezes_original_rows_and_rejects_changed_source(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir()
    for split in ('train', 'test'):
        raw = ''.join(json.dumps({'question': f'{split} question {i}', 'answer': '#### 7'}) + '\n'
                      for i in range(128)).encode()
        (source / (split + '.jsonl')).write_bytes(raw)
        monkeypatch.setitem(SOURCE_SHA256, split, hashlib.sha256(raw).hexdigest())
    output = tmp_path / 'pilot'
    prepare(source, output)
    data = FrozenDataset.from_manifest(output / 'manifest.json')
    assert data.ids('train')[-1].endswith(':train:000063')
    assert data.ids('validation')[0].endswith(':train:000064')
    assert data.ids('test')[-1].endswith(':test:000127')
    assert not set(data.ids('train')) & set(data.ids('validation'))
    (source / 'train.jsonl').write_text('changed')
    with pytest.raises(ValueError, match='source hash'):
        prepare(source, tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


def test_cli_freezes_source_and_profile_before_run_and_rejects_changed_resume(tmp_path):
    from zoo.gepa_gsm8k.runner import main
    output = tmp_path / 'run'
    arguments = ['--mode', 'fixture', '--max-proposals', '0', '--output', str(output)]
    assert main(arguments) == 0
    frozen = json.loads((output / 'run-manifest.json').read_text())
    report = json.loads((output / 'method-report.json').read_text())
    assert frozen['source_commit'] == report['source_commit']
    assert frozen['dataset_identity'] == report['dataset_identity']
    assert main(arguments + ['--resume']) == 0
    with pytest.raises(ValueError, match='frozen run manifest'):
        main(arguments + ['--resume', '--seed', '1'])
    assert json.loads((output / 'run-manifest.json').read_text()) == frozen


def test_fixture_runs_without_git_but_live_requires_a_source_commit(tmp_path, monkeypatch, capsys):
    from zoo.gepa_gsm8k import runner
    installed = tmp_path / 'installed' / 'm0' / 'zoo' / 'gepa_gsm8k' / 'runner.py'
    installed.parent.mkdir(parents=True)
    monkeypatch.setattr(runner, '__file__', str(installed))
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path))
    output = tmp_path / 'fixture'
    args = ['--mode', 'fixture', '--max-proposals', '0', '--output', str(output)]
    assert runner.main(args) == 0
    manifest = json.loads((output / 'run-manifest.json').read_text())
    assert manifest['source_commit'] is None and manifest['source_dirty'] is None
    assert runner.main(args + ['--resume']) == 0
    live_output = tmp_path / 'live'
    with pytest.raises(SystemExit) as error:
        runner.main(['--mode', 'live', '--output', str(live_output)])
    assert error.value.code == 2
    assert 'live evidence requires a Git checkout' in capsys.readouterr().err
    assert not live_output.exists()
