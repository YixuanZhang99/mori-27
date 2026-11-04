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


def test_m7_preflight_reports_missing_campaign_without_launch(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    result = pilot.preflight_pilot(tmp_path / 'official', tmp_path / 'data', model='deepseek-flash',
        token_budget=3_000_000, iterations=3, runtime='m7', spending_ledger_path=tmp_path / 'missing.db')
    assert result['plan']['runtime'] == 'm7'
    assert not result['ready'] and not result['benchmark_execution']
    assert any(item['requirement'] == 'campaign_currency_budget' for item in result['missing'])
    assert not (tmp_path / 'missing.db').exists()


def test_synthetic_m7_six_slot_pilot_freezes_before_grading(tmp_path, monkeypatch):
    import json
    import shutil
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from test_mle_pilot import fixtures, grader
    from test_mle_composed import fixture_public, TrustedFixtureRunner
    from zoo.mle_bench_lite.composed_agent import run_governed_agent
    from zoo.mle_bench_lite.cny_budget import CampaignBudget

    official, data, manifest = fixtures(tmp_path)
    for task in pilot.DEFAULT_TASKS:
        public = data / task / 'prepared/public'
        shutil.rmtree(public)
        fixture_public(public, task)
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    code = '''import csv,json
p=json.load(open("data/protocol.json"))
with open("data/predict.csv", newline="") as f: rows=list(csv.DictReader(f))
cols=p["output_columns"]; n=len(cols)-1
with open("predictions.csv","w",newline="") as f:
 w=csv.writer(f); w.writerow(cols)
 for row in rows: w.writerow([row["row_id"]]+[1/n if p["kind"]=="classification" else 1.0]*n)
'''
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            content = json.loads(req['messages'][0]['content'])
            calls.append(content)
            result = json.dumps({'artifact': code, 'hypothesis': content['hypothesis']})
            raw = json.dumps({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 3,
                'completion_tokens': 4, 'total_tokens': 7}, 'choices': [{'finish_reason': 'length' if len(calls) == 2 else 'stop',
                'message': {'content': result}}]}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(raw)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    endpoint = f'http://127.0.0.1:{server.server_port}/v1'
    monkeypatch.setenv('OPENAI_API_BASE', endpoint)
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-only')
    def execute(_command, workspace, task, seed, arm, limit, run_dir, agent_env):
        start = time.monotonic()
        run_governed_agent(workspace=workspace, task_id=task, model='deepseek-flash', api_base=endpoint,
            token_budget=3_000_000, seed=seed, iterations=3, variant=arm, max_completion_tokens=16384,
            solution_timeout=120, runner=TrustedFixtureRunner(), api_key='fixture-only',
            anonymization_key_path=agent_env['MLE_ANONYMIZATION_KEY_PATH'], spending_ledger_path=ledger.path)
        return {'agent_returncode': 0, 'timed_out': False, 'actual_costs': {'wallclock': time.monotonic()-start}}
    monkeypatch.setattr(pilot, '_execute_agent', execute)
    try:
        result = pilot.run_pilot(official, data, tmp_path / 'pilot', model='deepseek-flash',
            token_budget=3_000_000, time_limit=600, solution_timeout=120, iterations=3, seeds=(1,),
            manifest_path=manifest, spending_ledger_path=ledger.path, grader_factory=grader, runtime='m7')
        assert result['pilot_complete'] and result['evidence_kind'] == 'protocol_fixture'
        assert len(result['runs']) == 6 and all(row['status'] == 'graded' for row in result['runs'])
        assert len(calls) == 30 and ledger.snapshot()['settled_upper_bound_micro_cny'] == 30 * 38
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_m7_launch_exception_blocks_remaining_slots(tmp_path, monkeypatch):
    import shutil
    from test_mle_pilot import fixtures, grader
    from test_mle_composed import fixture_public
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    official, data, manifest = fixtures(tmp_path)
    for task in pilot.DEFAULT_TASKS:
        public = data / task / 'prepared/public'
        shutil.rmtree(public)
        fixture_public(public, task)
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:1/v1')
    calls = []
    def failed(*args, **kwargs):
        calls.append(1)
        raise OSError('fixture launch failure')
    monkeypatch.setattr(pilot, '_execute_agent', failed)
    report = pilot.run_pilot(official, data, tmp_path / 'pilot', model='deepseek-flash',
        token_budget=3_000_000, time_limit=600, solution_timeout=120, iterations=3, seeds=(1,),
        manifest_path=manifest, spending_ledger_path=ledger.path, grader_factory=grader, runtime='m7')
    assert len(calls) == 1 and len(report['runs']) == 6
    assert all(row['status'] == 'failed' for row in report['runs'])
    assert all(row.get('blocked_before_execution') for row in report['runs'][1:])
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 0
