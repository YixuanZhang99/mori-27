"""CLI evidence and real loopback billing for the frozen OR3 recipe."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from core.loop import Framework, LoopConfig
from test_funsearch_holdout import prepared, TEMPLATE, TASK
from test_governed_cny_framework import campaign_fixture


class FrozenCrash(BaseException):
    pass


def test_fixture_cli_without_git_freezes_and_reuses_reports(tmp_path, monkeypatch):
    from zoo.funsearch_binpacking import runner
    installed = tmp_path / 'installed' / 'm0' / 'zoo' / 'funsearch_binpacking' / 'runner.py'
    installed.parent.mkdir(parents=True)
    monkeypatch.setattr(runner, '__file__', str(installed))
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path))
    output = tmp_path / 'run'
    args = ['--mode', 'fixture', '--max-proposals', '1', '--output', str(output)]
    assert runner.main(args) == 0
    frozen = json.loads((output / 'run-manifest.json').read_text())
    report = json.loads((output / 'method-report.json').read_text())
    assert frozen['source_commit'] is None
    assert report['result']['reporting']['final_audit']['state'] == 'completed'
    assert report['search']['attempted'] == report['search']['successful'] == 2
    assert report['baseline']['splits']['dev']['mean_score'] == -1
    from core.tasks.funsearch_priority_sandbox import SandboxedPriority
    monkeypatch.setattr(SandboxedPriority, '__enter__', lambda _self: pytest.fail('repeated worker'))
    monkeypatch.setattr(runner.FixtureProvider, '__call__', lambda *_args: pytest.fail('repeated model'))
    assert runner.main(args + ['--resume', '--final-only']) == 0
    with pytest.raises(ValueError, match='frozen run manifest'):
        runner.main(args + ['--resume', '--max-proposals', '2'])
    assert json.loads((output / 'run-manifest.json').read_text()) == frozen
    with pytest.raises(SystemExit):
        runner.main(['--mode', 'live', '--output', str(tmp_path / 'live')])
    assert not (tmp_path / 'live').exists()


def test_final_only_cannot_start_an_unfrozen_search(tmp_path):
    from zoo.funsearch_binpacking import runner
    output = tmp_path / 'unfrozen'
    with pytest.raises(ValueError, match='frozen selection'):
        runner.main(['--mode', 'fixture', '--output', str(output), '--resume', '--final-only'])
    assert not output.exists()


def test_frozen_only_command_finishes_terminal_worker_without_provider(tmp_path, monkeypatch):
    from zoo.funsearch_binpacking import runner
    from core.composition.recovery import ContinuationStore
    from core.tasks.funsearch_priority_sandbox import SandboxedPriority
    original = ContinuationStore.append
    def crash(self, kind, payload):
        original(self, kind, payload)
        if kind == 'metric_final_frozen':
            raise FrozenCrash()
    output = tmp_path / 'run'
    args = ['--mode', 'fixture', '--max-proposals', '1', '--output', str(output)]
    with monkeypatch.context() as patch:
        patch.setattr(ContinuationStore, 'append', crash)
        with pytest.raises(FrozenCrash):
            runner.main(args)
    entered = []
    real_enter = SandboxedPriority.__enter__
    def counted(self):
        entered.append(self.source)
        return real_enter(self)
    monkeypatch.setattr(SandboxedPriority, '__enter__', counted)
    monkeypatch.setattr(runner.FixtureProvider, '__call__', lambda *_args: pytest.fail('final requested model'))
    assert runner.main(args + ['--resume', '--final-only']) == 0
    assert entered == [TEMPLATE]


def test_malformed_initial_program_produces_failure_report(tmp_path, monkeypatch):
    from zoo.funsearch_binpacking import runner
    def invalid(self, _prompt):
        self.last_usage = {'total_tokens': 1}
        return 'not a construction JSON object'
    monkeypatch.setattr(runner.FixtureProvider, '__call__', invalid)
    output = tmp_path / 'run'
    assert runner.main(['--mode', 'fixture', '--max-proposals', '0', '--output', str(output)]) == 0
    report = json.loads((output / 'method-report.json').read_text())
    assert report['search'] == {'attempted': 1, 'successful': 0, 'failed': 1, 'failure_rate': 1.0}
    assert report['result']['reporting']['final_audit']['state'] == 'skipped'
    assert report['result']['best_candidate_id'] is None
    assert report['replay_passed']


@pytest.fixture
def endpoint():
    state = SimpleNamespace(requests=[], fail_control=False)
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state.requests.append(request)
            prompt = json.loads(request['messages'][0]['content'])
            content = 'invalid control' if state.fail_control and len(state.requests) == 1 else json.dumps(
                {'artifact': TEMPLATE, 'hypothesis': prompt['hypothesis']})
            body = json.dumps({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 3,
                'completion_tokens': 4, 'total_tokens': 7}, 'choices': [{'finish_reason': 'stop',
                'message': {'content': content}}]}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    state.url = f'http://127.0.0.1:{server.server_port}/v1'
    yield state
    server.shutdown(); server.server_close(); worker.join(timeout=5)


@pytest.mark.parametrize('failed_control', [False, True])
def test_governed_programs_and_control_share_original_cost_authority(tmp_path, endpoint, failed_control):
    from zoo.funsearch_binpacking.data import FrozenOR3
    from zoo.funsearch_binpacking.runner import governed_setup
    data = FrozenOR3.from_manifest(prepared(tmp_path / 'data'))
    ledger = campaign_fixture(tmp_path)
    endpoint.fail_control = failed_control
    profile, registry, provider = governed_setup(data, seed=0, max_proposals=1,
        ledger=ledger, api_key='fixture-only', base_url=endpoint.url, max_completion_tokens=16384)
    fw = Framework.from_profile(profile, provider, data,
        LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'], reeval_floor=0),
        str(tmp_path / 'run'), component_registry=registry)
    result = fw.evolve(TASK)
    assert result['reporting']['final_audit']['state'] == 'completed'
    assert len(endpoint.requests) == 3  # 2 main constructors + 1 independent constructor; no solver calls.
    main = {r['payload']['candidate_id'] for r in fw.store.read('funsearch_public_candidate')}
    controls = {r['payload']['candidate_id'] for r in fw.store.read('governed_control_terminal')}
    assert len(main) == 2 and len(controls) == 1 and main.isdisjoint(controls)
    assert [r['payload']['status'] for r in fw.store.read('governed_control_terminal')] == [
        'failed' if failed_control else 'evaluated']
    snapshot = ledger.snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] == 3 * 38
    assert not snapshot['pending_calls'] and snapshot['reserved_micro_cny'] == 0
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert len(endpoint.requests) == 3 and ledger.snapshot() == snapshot
