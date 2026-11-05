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
