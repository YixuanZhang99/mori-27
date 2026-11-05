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
