"""Frozen M7 pilot protocol and legacy compatibility."""
import shlex

import pytest

from zoo.mle_bench_lite import pilot
from zoo.mle_bench_lite.composed_agent import build_governed_profile


def test_pilot_freezes_m7_profile_and_selects_explicit_runtime():
    kwargs = {'variant': 'full', 'token_budget': 3_000_000, 'seed': 1, 'iterations': 3}
    profile = pilot._profile(**kwargs, runtime='m7', max_completion_tokens=16384)
    assert profile == build_governed_profile(**kwargs, max_completion_tokens=16384)
    command = shlex.split(pilot._command('deepseek-flash', 3_000_000, 120, 3,
                                       max_completion_tokens=16384, spending_ledger_path='/tmp/campaign',
                                       runtime='m7'))
    assert command[command.index('--runtime') + 1] == 'm7'
    assert pilot._profile(**kwargs)['schema_version'] == 1


def test_pilot_refuses_m7_budget_before_data_or_network():
    with pytest.raises(ValueError, match='hard'):
        pilot._plan('deepseek-flash', 60_000, 600, 120, 3, [1], list(pilot.DEFAULT_TASKS),
                    spending_ledger_path='/tmp/no-campaign', runtime='m7')


def test_agent_cli_explicit_m7_passes_protected_paths(monkeypatch, tmp_path, capsys):
    from zoo.mle_bench_lite import composed_agent
    observed = {}
    def fixture(**kwargs):
        observed.update(kwargs)
        return {'ok': True}
    monkeypatch.setattr(composed_agent, 'run_governed_agent', fixture)
    monkeypatch.setenv('MLE_OFFICIAL_ROOT', str(tmp_path / 'official'))
    monkeypatch.setenv('MLE_DATA_ROOT', str(tmp_path / 'data'))
    assert composed_agent.main(['--runtime', 'm7', '--workspace', str(tmp_path / 'workspace'),
        '--task', 'spooky-author-identification', '--variant', 'baseline', '--model', 'deepseek-flash',
        '--token-budget', '3000000', '--spending-ledger', str(tmp_path / 'campaign')]) == 0
    assert observed['spending_ledger_path'] == tmp_path / 'campaign'
    assert observed['protected_roots'] == (str(tmp_path / 'official'), str(tmp_path / 'data'))
    assert 'ok' in capsys.readouterr().out
