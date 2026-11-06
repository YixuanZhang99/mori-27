"""Offline named recipe is a reproducible plumbing fixture, not a benchmark."""
import json
import os
import subprocess
import sys

import pytest


def test_default_cli_runs_without_credentials_or_external_network(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if 'API_KEY' not in key and not key.startswith('KAGGLE_')}
    env.update(PYTHONHASHSEED='0', PYTHONPATH=os.pathsep.join(sys.path))
    result = subprocess.run([sys.executable, '-m', 'zoo.circle_packing.runner',
        '--output', str(tmp_path / 'run'), '--iterations', '1'],
        env=env, capture_output=True, text=True, timeout=90, check=True)
    report = json.loads(result.stdout)
    assert report['mode'] == 'fixture' and report['performance_claim'] is False
    assert report['provider_calls'] == 1
    assert report['replay_certificate']['passed']
    assert report['replay_certificate']['external_calls'] == 0


def test_refuses_live_until_governed_runner_is_ready(tmp_path):
    from zoo.circle_packing.runner import run
    with pytest.raises(ValueError, match='live'):
        run(tmp_path / 'run', mode='live', seed=0, iterations=1)
    assert not (tmp_path / 'run').exists()


def test_fixture_terminal_recovery_replays_without_new_calls(tmp_path, monkeypatch):
    from zoo.circle_packing.runner import FixtureProvider, run
    from zoo.circle_packing.domain import CirclePackingDomain
    monkeypatch.setenv('PYTHONHASHSEED', '0')
    provider = FixtureProvider()
    first = run(tmp_path / 'run', iterations=1, provider=provider)
    assert provider.calls == 1
    def forbidden(*args, **kwargs):
        raise AssertionError('terminal recovery called the provider')
    monkeypatch.setattr(FixtureProvider, '__call__', forbidden)
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
    restored = run(tmp_path / 'run', iterations=1, provider=provider)
    assert restored['provider_calls'] == 1 and provider.calls == 1
    assert restored['replay_certificate']['passed']
    with pytest.raises(ValueError):
        run(tmp_path / 'run', iterations=2, provider=provider)
    from core.x1.checkpoint import payload_digest
    terminal_path = tmp_path / 'run' / 'terminal.json'
    terminal = json.loads(terminal_path.read_text())
    terminal['report']['replay_certificate']['external_calls'] = 1
    terminal['report_sha256'] = payload_digest(terminal['report'])
    terminal_path.write_text(json.dumps(terminal))
    with pytest.raises(ValueError):
        run(tmp_path / 'run', iterations=1, provider=provider)


def test_fixture_rejects_non_fixture_provider_before_creating_output(tmp_path):
    from zoo.circle_packing.runner import run
    with pytest.raises(ValueError, match='offline provider'):
        run(tmp_path / 'run', provider=lambda value: value)
    assert not (tmp_path / 'run').exists()
