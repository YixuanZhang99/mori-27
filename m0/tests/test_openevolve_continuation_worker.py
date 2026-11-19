"""The frozen fixture worker consumes the exact continuation authorities."""
from pathlib import Path
import pytest

from test_openevolve_continuation_controller import setup

pytestmark = pytest.mark.linux


def test_worker_restores_versioned_fixture_clock_and_bound_runtime(tmp_path, monkeypatch):
    from zoo.circle_packing.mori_fixture_worker import prepare_fixture_authorities
    ledger, draft, clock, _, source, _runtime, artifacts = setup(tmp_path, monkeypatch)
    config = {'plan': draft, 'ref': 'sha256:' + draft['draft_sha256'], 'runtime_manifest': {},
              'source_manifest': {}, 'source': str(source / 'source/m0'), 'runtime': artifacts['runtime'],
              'ledger': str(ledger.path), 'clock': str(tmp_path / 'clock.jsonl'),
              'output': str(tmp_path / 'out'), 'base_url': 'http://127.0.0.1:12345',
              'campaign_id': draft['campaign_id'], 'seed': 0}
    before = ledger.snapshot()
    restored, runner = prepare_fixture_authorities(config, ledger=ledger)
    assert restored._record == clock._record
    assert runner.manifest_binding['runtime_ref'] == artifacts['runtime_ref']
    after_restore = ledger.snapshot()
    assert after_restore['journal_head']['seq'] == before['journal_head']['seq'] + 1
    assert after_restore['settled_upper_bound_micro_cny'] == before['settled_upper_bound_micro_cny']
    assert after_restore['remaining_micro_cny'] == before['remaining_micro_cny']
    with pytest.raises(ValueError):
        prepare_fixture_authorities({**config, 'ref': 'sha256:' + '0' * 64}, ledger=ledger)
    with pytest.raises(ValueError):
        prepare_fixture_authorities({**config, 'seed': 1}, ledger=ledger)
    (Path(artifacts['runtime']) / 'package.py').write_text('tampered')
    with pytest.raises(ValueError): prepare_fixture_authorities(config, ledger=ledger)
    assert ledger.snapshot() == after_restore
