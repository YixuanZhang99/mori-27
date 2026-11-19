"""Real process death at durable bridge publication boundaries; no HTTP."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

import pytest

from core.composition.external_provider import ExternalRunContext, GovernedCallContext
from core.llm import UsageError
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
from test_governed_cny_bridge import Store


CHILD = r'''
import json, os, signal, sys
from pathlib import Path
from types import SimpleNamespace
from test_governed_cny_bridge import setup
path, boundary = Path(sys.argv[1]), sys.argv[2]
ledger, bridge, run, context, providers, calls, store, physical = setup.__wrapped__(path, SimpleNamespace())
(path / 'recovery.json').write_text(json.dumps({'run': run.to_dict(), 'context': context.to_dict(),
    'physical': physical, 'rows': store.rows}))
raw = providers['control-0000']
perform = raw.perform_request
def counted(body):
    with (path / 'dispatch-count').open('ab') as stream:
        stream.write(b'1\n')
        stream.flush()
        os.fsync(stream.fileno())
    return perform(body)
raw.perform_request = counted
save = bridge._save
def cut(name, value):
    save(name, value)
    if name.endswith('.' + boundary):
        os.kill(os.getpid(), signal.SIGKILL)
bridge._save = cut
bridge.invoke(context, ('prompt',), {})
raise AssertionError('did not reach requested durable boundary')
'''


def exercise_crash(path, boundary):
    path.mkdir(parents=True, exist_ok=True)
    m0 = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(m0), str(m0 / 'tests'))))
    killed = subprocess.run([sys.executable, '-c', CHILD, str(path), boundary], env=env,
                            capture_output=True, text=True, timeout=15)
    assert killed.returncode == -signal.SIGKILL, killed.stdout + killed.stderr
    saved = json.loads((path / 'recovery.json').read_text())
    ledger = CampaignBudget(path / 'campaign.db')
    store = Store()
    store.rows = saved['rows']
    providers = {key: GovernedCNYProvider('deepseek-flash', 'http://127.0.0.1:1',
        campaign_binding=ledger.manifest_binding(), max_completion_tokens=4, api_key='fixture')
        for key in ('main', 'control-0000')}
    def forbidden(body):
        raise AssertionError('recovery attempted provider transport')
    for provider in providers.values():
        provider.perform_request = forbidden
    def lookup(intent, *, fingerprint):
        assert intent == saved['physical']['intent_id']
        assert fingerprint == saved['physical']['physical_fingerprint']
        return saved['physical']
    run = ExternalRunContext(**saved['run'], store=store, physical_identity_lookup=lookup,
                             provider_sessions=providers)
    context = GovernedCallContext.from_dict(saved['context'])
    bridge = CNYInvocationBridge(ledger)
    bridge.bind_run(run)
    count_file = path / 'dispatch-count'
    before = count_file.read_bytes() if count_file.exists() else b''
    assert before.count(b'1\n') == (0 if boundary in {'prepared', 'dispatch'} else 1)
    if boundary == 'dispatch':
        for _ in range(2):
            with pytest.raises(UsageError, match='no durable provider outcome'):
                bridge.recover(context, context.argument_sha256)
        assert ledger.snapshot()['pending_calls']
        assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 0
    else:
        for _ in range(2):
            outcome = bridge.recover(context, context.argument_sha256)
            assert outcome.outcome == ('known_refused' if boundary == 'prepared' else 'returned')
        assert ledger.snapshot()['pending_calls'] == []
        assert ledger.snapshot()['settled_upper_bound_micro_cny'] == (0 if boundary == 'prepared' else 36)
    assert (count_file.read_bytes() if count_file.exists() else b'') == before


@pytest.mark.parametrize('boundary', ['prepared', 'dispatch', 'response', 'outcome'])
def test_sigkill_recovery_has_no_second_transport_or_charge(tmp_path, boundary):
    exercise_crash(tmp_path, boundary)


def test_response_publication_recovery_on_normal_filesystem():
    # Separate from tmpfs tests: exercise fsync + atomic publication on /tmp.
    with tempfile.TemporaryDirectory(prefix='mori-cny-normal-fs-', dir='/tmp') as directory:
        exercise_crash(Path(directory), 'response')
