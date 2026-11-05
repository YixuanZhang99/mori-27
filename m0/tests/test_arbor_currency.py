"""Real loopback transport and temporary currency authority for Arbor planning."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.loop import Framework, LoopConfig
from core.llm import ProviderBudgetExhausted, UsageError
from test_configured_construction import records
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import reply
from test_mle_composed import TEST_ANONYMIZATION_KEY, TrustedFixtureRunner, fixture_public
from zoo.mle_bench_lite.arbor_runner import FixtureProvider, governed_setup
from zoo.mle_bench_lite.composed_domain import PublicTrainDomain
from zoo.mle_bench_lite.public_train import PublicTrainBundle


@pytest.fixture
def arbor_endpoint():
    class State:
        def __init__(self):
            self.requests, self.unknown_planning = [], False
            self.fixture = FixtureProvider()
    state = State()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            wire = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            prompt = wire['messages'][-1]['content']
            request = json.loads(prompt)
            state.requests.append(request)
            response = reply(choices=[{'finish_reason': 'stop', 'message': {
                'content': state.fixture(prompt)}}])
            if state.unknown_planning and request.get('kind') == 'arbor_ideation':
                response.pop('usage')
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    state.url = f'http://127.0.0.1:{server.server_port}/v1'
    yield state
    server.shutdown(); server.server_close(); worker.join(timeout=5)


def build(tmp_path, endpoint, monkeypatch, *, planning_cap=4, cycles=3, resume=False):
    from zoo.mle_bench_lite import governed_provider
    original = governed_provider.GovernedCNYProvider
    class Local(original):
        def __init__(self, model, base_url, **kwargs):
            if 'planning' in kwargs.get('phase_call_limits', {}):
                kwargs['phase_call_limits'] = {**kwargs['phase_call_limits'], 'planning': planning_cap}
            super().__init__(model, endpoint.url, **kwargs)
    monkeypatch.setattr(governed_provider, 'GovernedCNYProvider', Local)
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget(tmp_path / 'campaign.db') if resume else campaign_fixture(tmp_path)
    public = tmp_path / 'public'
    if not public.exists():
        fixture_public(public)
    bundle = PublicTrainBundle(public, tmp_path / 'inputs',
        'spooky-author-identification', 7, anonymization_key=TEST_ANONYMIZATION_KEY, dev_scoring='task_metric')
    runner = TrustedFixtureRunner()
    domain = PublicTrainDomain(bundle, tmp_path / 'candidates', runner=runner)
    profile, registry, provider = governed_setup(bundle, tmp_path, ledger=ledger, api_key='fixture-only-secret',
        split_seed=7, search_seed=0, max_cycles=cycles, runner=runner, solution_timeout=120)
    fw = Framework.from_profile(profile, provider, domain,
        LoopConfig(max_generations=cycles - 1, total_budget=profile['budget']['options']['limits']['global']['token'],
                   reeval_floor=0, resume_from_checkpoint=resume), str(tmp_path / 'composed'), component_registry=registry)
    domain.restore_evidence(fw.store.read('composed_evidence'))
    return fw, ledger, domain


def test_planning_construction_and_synthesis_have_real_currency_receipts(tmp_path, arbor_endpoint, monkeypatch):
    fw, ledger, domain = build(tmp_path, arbor_endpoint, monkeypatch)
    result = fw.evolve('Fit public training priors and evaluate the frozen CSV predictions.')
    assert result['reporting']['final_audit']['state'] == 'complete'
    assert domain.training_invocations == 3
    starts = records(fw, 'composed_provider_started')
    assert len(starts) == len(arbor_endpoint.requests) == 16  # 1 control + 3*(idea+code) + 2+3+4 syntheses.
    contexts = [r['invocation']['external_context'] for r in starts]
    assert sum(c['phase'] == 'planning' for c in contexts) == 12
    assert sum(c['lane'] == 'control' for c in contexts) == 1
    assert len({c['session_id'] for c in contexts}) == 2
    audit = fw.inspect()['governance']['external_currency']
    assert audit['protection_valid'] and not audit['unknown_cost_calls'] and not audit['integrity_violations']
    before = ledger.snapshot()
    assert before['settled_upper_bound_micro_cny'] == 16 * 38 and before['pending_calls'] == []
    assert fw.replay()['replay_certificate']['passed']
    assert len(arbor_endpoint.requests) == 16 and ledger.snapshot() == before
    monkeypatch.undo()
    resumed, _, resumed_domain = build(tmp_path, arbor_endpoint, monkeypatch, resume=True)
    restored = resumed.evolve('Fit public training priors and evaluate the frozen CSV predictions.')
    assert restored['best_candidate_id'] == result['best_candidate_id']
    assert resumed_domain.training_invocations == 0
    import copy
    def replay_adapters(_path, _store):
        return copy.deepcopy(resumed._composed.llm), PublicTrainDomain(
            resumed_domain.bundle, tmp_path / 'candidates', runner=TrustedFixtureRunner())
    assert resumed.replay(adapter_factory=replay_adapters)['replay_certificate']['passed']
    assert len(arbor_endpoint.requests) == 16 and ledger.snapshot() == before


def test_declared_planning_cap_stops_before_another_http_request(tmp_path, arbor_endpoint, monkeypatch):
    fw, ledger, _ = build(tmp_path, arbor_endpoint, monkeypatch, planning_cap=1, cycles=1)
    with pytest.raises(ProviderBudgetExhausted):
        fw.evolve('Fit public training priors.')
    assert len(arbor_endpoint.requests) == 4  # Control, idea, construction, leaf; global is refused.
    assert records(fw, 'composed_evidence') == []
    assert ledger.snapshot()['pending_calls'] == []
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 4 * 38


def test_unknown_planning_usage_stays_pending_and_does_not_construct(tmp_path, arbor_endpoint, monkeypatch):
    arbor_endpoint.unknown_planning = True
    fw, ledger, _ = build(tmp_path, arbor_endpoint, monkeypatch, cycles=1)
    with pytest.raises(UsageError):
        fw.evolve('Fit public training priors.')
    assert len(arbor_endpoint.requests) == 2
    assert not records(fw, 'arbor_dispatched')
    assert len(ledger.snapshot()['pending_calls']) == 1
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 38


def test_capacity_refused_ideation_resumes_without_retry(tmp_path, arbor_endpoint, monkeypatch):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    def controls_only(path):
        ledger = CampaignBudget.create(path / 'campaign.db', limit_micro_cny=4456448)
        ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                                 expected_head=ledger.snapshot()['journal_head'])
        return ledger
    monkeypatch.setattr(__import__(__name__), 'campaign_fixture', controls_only)
    fw, ledger, _ = build(tmp_path, arbor_endpoint, monkeypatch, cycles=1)
    result = fw.evolve('Fit public training priors.')
    assert result['best_candidate_id'] is None
    assert len(arbor_endpoint.requests) == 1
    before = ledger.snapshot()
    assert not before['pending_calls']
    monkeypatch.undo()
    resumed, _, domain = build(tmp_path, arbor_endpoint, monkeypatch, cycles=1, resume=True)
    restored = resumed.evolve('Fit public training priors.')
    assert restored['best_candidate_id'] is None and restored['stop_reason'] == result['stop_reason']
    assert domain.training_invocations == 0 and len(arbor_endpoint.requests) == 1
    assert ledger.snapshot() == before
    assert resumed.replay()['replay_certificate']['passed']


def test_independent_currency_audit_covers_planning_and_construction(tmp_path, arbor_endpoint, monkeypatch):
    from zoo.mle_bench_lite.m7_pilot_audit import audit_currency_receipts
    fw, ledger, _ = build(tmp_path, arbor_endpoint, monkeypatch)
    fw.evolve('Fit public training priors.')
    before = ledger.snapshot()
    audited = audit_currency_receipts(tmp_path / 'composed', ledger, expected_model='deepseek-flash')
    assert audited['construction']['provider_calls'] == 4
    assert audited['provider_calls_by_phase'] == {'operator': 4, 'planning': 12}
    assert audited['settled_micro_cny'] == 16 * 38
    assert ledger.snapshot() == before
    path = tmp_path / 'composed/x1.jsonl'
    original = path.read_text()
    rows = [json.loads(line) for line in original.splitlines()]
    start = next(i for i, row in enumerate(rows) if row['kind'] == 'composed_provider_started'
                 and row['payload']['invocation']['external_context']['phase'] == 'planning')
    end = next(i for i in range(start + 1, len(rows)) if rows[i]['kind'] == 'composed_provider_completed')
    import copy
    for mutation in ('missing', 'tokens', 'result', 'context'):
        changed = copy.deepcopy(rows)
        if mutation == 'missing':
            del changed[start:end + 1]
        elif mutation == 'context':
            changed[start]['payload']['invocation']['external_context']['phase'] = 'operator'
        else:
            changed[end]['payload'][mutation] = 1000 if mutation == 'tokens' else 'forged planner answer'
        path.write_text(''.join(json.dumps(row) + '\n' for row in changed))
        with pytest.raises(ValueError):
            audit_currency_receipts(tmp_path / 'composed', ledger, expected_model='deepseek-flash')
        path.write_text(original)


def test_complete_live_runner_audits_all_phases_and_resumes_without_http(tmp_path, arbor_endpoint, monkeypatch):
    # The test replaces only the HTTP endpoint, source marker and sandbox with a
    # trusted test-program runner; it exercises the actual live orchestration,
    # independent currency/physical audits, submission, and terminal resume.
    from zoo.mle_bench_lite import arbor_runner, composed_domain, governed_provider
    original = governed_provider.GovernedCNYProvider
    class LocalProvider(original):
        def __init__(self, model, base_url, **kwargs):
            super().__init__(model, arbor_endpoint.url, **kwargs)
    class LocalRunner(TrustedFixtureRunner):
        @staticmethod
        def validate_paths(*_paths):
            pass
        def preflight(self, **_options):
            return {'ready': True, 'fixture': True}
    monkeypatch.setattr(governed_provider, 'GovernedCNYProvider', LocalProvider)
    monkeypatch.setattr(composed_domain, 'SandboxRunner', LocalRunner)
    monkeypatch.setattr(arbor_runner, 'source_identity', lambda: {'commit': 'test-source', 'dirty': False})
    ledger = campaign_fixture(tmp_path)
    public = fixture_public(tmp_path / 'public')
    key = tmp_path / 'key'; key.write_bytes(TEST_ANONYMIZATION_KEY); key.chmod(0o600)
    options = dict(output=tmp_path / 'run', public_root=public, task_id='spooky-author-identification',
                   max_cycles=3, ledger=ledger, api_key='fixture-only-secret', anonymization_key_path=key)
    report = arbor_runner.run(**options)
    assert report['run_state'] == 'completed'
    assert report['independent_currency_receipts']['provider_calls_by_phase'] == {'operator': 4, 'planning': 12}
    assert report['independent_physical_submission']
    assert report['replay_certificate']['passed'] and report['replay_certificate']['external_calls'] == 0
    assert (tmp_path / 'run/submission.csv').is_file()
    before = ledger.snapshot(), len(arbor_endpoint.requests)
    resumed = arbor_runner.run(**options, resume=True)
    assert resumed['run_state'] == 'completed'
    assert resumed['submission'] == report['submission']
    assert resumed['training_invocations_this_process'] == 0
    assert (ledger.snapshot(), len(arbor_endpoint.requests)) == before
