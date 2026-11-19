"""A frozen continuation controller executes in a separate loopback fixture process."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from core.composition.recovery import ContinuationStore
from core.x1.checkpoint import payload_digest
from test_governed_cny_provider import local_endpoint, reply
from test_openevolve_continuation_event import fixture_pair_ledger
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.continuation_binding import bind_fixture_continuation
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.circle_packing.continuation_runtime import prepare_continuation_runtime
from zoo.circle_packing.mori_supervisor import launch_fixture_controller

pytestmark = pytest.mark.linux


def assert_supervisor_record(config, clock, directory, ledger):
    rows = list(ContinuationStore(directory / 'controller.jsonl').read())
    starts = [row['payload'] for row in rows if row['kind'] == 'executor_process_started']
    finishes = [row['payload'] for row in rows if row['kind'] == 'executor_process_finished']
    assert len(starts) == len(finishes) == 1
    start, finish = starts[0], finishes[0]
    binding = {'schema_version': 1, 'cell_id': clock._record['cell_id'],
        'deadline_ref': clock._record['record_sha256'], 'config_sha256': payload_digest(config),
        'directory': str(directory), 'entry': 'zoo.circle_packing.mori_fixture_worker'}
    assert ledger.cell_worker_claim(clock._record['cell_id']) == {
        'deadline_ref': clock._record['record_sha256'], 'worker_ref': payload_digest(binding)}
    assert start['worker_ref'] == payload_digest(binding)
    assert finish['execution_id'] == start['execution_id'] and finish['returncode'] == 0 and not finish['timeout']
    spec = json.loads(Path(start['spec_path']).read_text())
    assert spec['args'] == [str(Path(config['runtime']) / 'bin/python'), '-m', binding['entry'],
                            str(directory / 'config.json')]
    assert spec['absolute_deadline'] == {'boot_id': clock._record['boot_id'],
        'deadline_ns': clock._record['start_ns'] + clock._record['seconds'] * 1_000_000_000}


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
    config = {'plan': draft, 'ref': ref, 'runtime_manifest': {}, 'source_manifest': {},
              'source': str(source / 'source/m0'), 'runtime': artifacts['runtime'],
              'ledger': str(ledger.path), 'clock': str(tmp_path / 'clock.jsonl'),
              'output': str(tmp_path / 'controller'), 'base_url': local_endpoint.url,
              'campaign_id': draft['campaign_id'], 'seed': 0}
    content = '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # fixture\n>>>>>>> REPLACE\n'
    local_endpoint.responses.extend([reply(choices=[{'finish_reason': 'stop', 'message': {'content': content}}]) for _ in range(16)])
    executable = str(Path(artifacts['runtime']) / 'bin/python')
    directory = tmp_path / 'supervisor'
    process = launch_fixture_controller(config, deadline=clock, directory=directory)
    assert process['returncode'] == 0 and not process['timeout'], process['stderr'][-4000:]
    assert_supervisor_record(config, clock, directory, ledger)
    result = json.loads(process['stdout'])
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
