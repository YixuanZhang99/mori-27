"""A frozen continuation controller executes in a separate loopback fixture process."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from core.composition.recovery import ContinuationStore
from test_governed_cny_provider import local_endpoint, reply
from test_openevolve_continuation_event import fixture_pair_ledger
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.continuation_binding import bind_fixture_continuation
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime

pytestmark = pytest.mark.linux


def test_frozen_worker_runs_six_cycle_continuation(tmp_path, local_endpoint):
    cache = os.environ.get('MORI_TEST_OFFLINE_CACHE')
    if not cache:
        pytest.skip('requires an explicitly supplied offline uv cache')
    repository = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
    ledger, original_proof = fixture_pair_ledger(tmp_path)
    before = ledger.snapshot()
    draft = build_continuation_draft(ledger.circle_continuation_inventory(expected_head=before['journal_head']),
        experiment_id='circle-v2', source_commit=commit,
        dependency_lock_sha256=hashlib.sha256((checkout / 'm0/uv.lock').read_bytes()).hexdigest(),
        method_changes=['independent frozen loopback fixture'])
    source, runtime_bundle = tmp_path / 'source-bundle', tmp_path / 'runtime-bundle'
    artifacts = prepare_continuation_runtime(ledger, draft, checkout=checkout, source_directory=source,
        directory=runtime_bundle, uv_cache=cache, base_python='/usr/bin/python3.12')
    bind_fixture_continuation(ledger, draft, checkout=checkout, source_directory=source,
                              runtime_directory=runtime_bundle, base_python='/usr/bin/python3.12')
    ref = 'sha256:' + draft['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(ledger),
        cell_id='circle-v2--mori-0', plan_ref=ref, seconds=draft['limits']['wallclock_seconds'])
    ledger.claim_cell_worker('circle-v2--mori-0', clock._record['record_sha256'], 'a' * 64)
    config = {'plan': draft, 'ref': ref, 'runtime_manifest': {}, 'source_manifest': {},
              'source': str(source / 'source/m0'), 'runtime': artifacts['runtime'],
              'ledger': str(ledger.path), 'clock': str(tmp_path / 'clock.jsonl'),
              'output': str(tmp_path / 'controller'), 'base_url': local_endpoint.url,
              'campaign_id': draft['campaign_id'], 'seed': 0}
    config_path = tmp_path / 'config.json'
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(config, stream)
    content = '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # fixture\n>>>>>>> REPLACE\n'
    local_endpoint.responses.extend([reply(choices=[{'finish_reason': 'stop', 'message': {'content': content}}]) for _ in range(16)])
    env = {'PATH': os.defpath, 'HOME': str(tmp_path), 'PYTHONPATH': config['source'],
           'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    executable = str(Path(artifacts['runtime']) / 'bin/python')
    process = subprocess.run([executable, '-m', 'zoo.circle_packing.mori_fixture_worker', str(config_path)],
                             cwd=config['source'], env=env, capture_output=True, text=True, timeout=900)
    assert process.returncode == 0, process.stderr[-4000:]
    result = json.loads(process.stdout)
    assert result['mode'] == 'fixture' and result['performance_claim'] is False and result['replay_passed']
    assert result['executable'] == executable
    for key in ('source', 'governed_source'):
        assert Path(config['source']) in Path(result[key]).resolve().parents
    assert (Path(config['source']) / 'vendor/openevolve').resolve() in Path(result['vendor_source']).resolve().parents
    rows = [json.loads(line) for line in (tmp_path / 'controller/framework/x1.jsonl').read_text().splitlines()]
    assert [row['payload']['cycle'] for row in rows if row['kind'] == 'composed_cycle_started'] == list(range(7))
    assert len(local_endpoint.requests) == 6
    assert all(json.loads(request)['thinking'] == {'type': 'disabled'} for request in local_endpoint.requests)
    after = ledger.snapshot()
    assert after['settled_upper_bound_micro_cny'] > before['settled_upper_bound_micro_cny']
    assert not after['pending_calls'] and not after['protected_micro_cny'] and not after['protection_breaches']
    assert ledger.first_pair_audit() == original_proof
