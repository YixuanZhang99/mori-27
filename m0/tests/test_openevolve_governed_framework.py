"""Real Framework currency/role plumbing over loopback, never a paid run."""
import json

import pytest
from core.loop import Framework, LoopConfig
from core.llm import UsageError
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint, reply
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.mle_bench_lite.composed_domain import SandboxRunner


def test_governed_circle_run_binds_roles_control_cost_and_replay(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.governed import governed_setup
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content':
        '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # governed fixture\n>>>>>>> REPLACE\n'}}]))
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    result = fw.evolve('Improve the arrangement of 26 circles in a square')
    assert 'governed-external' in result['runtime']
    wire = json.loads(local_endpoint.requests[0])
    assert [message['role'] for message in wire['messages']] == ['system', 'user']
    audit = fw._composed.governed.external.audit()
    assert audit['protection_valid'] and not audit['unknown_cost_calls']
    assert campaign.snapshot()['pending_calls'] == []
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 38
    controls = fw.inspect()['governance']
    assert controls['completed'] == 1 and controls['unresolved'] == 0
    def adapters(path, store):
        _, _, fresh_provider = governed_setup(tmp_path / 'run', ledger=campaign,
            api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
            max_completion_tokens=4)
        return fresh_provider, CirclePackingDomain(tmp_path / 'replay-domain', runner=SandboxRunner())
    def forbidden(*args, **kwargs):
        raise AssertionError('recorded replay made an HTTP request')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 1
    for path in (tmp_path / 'run').rglob('*'):
        if path.is_file():
            assert b'fixture-only-secret' not in path.read_bytes()


def test_governed_circle_unknown_usage_keeps_reservation(tmp_path, local_endpoint):
    from zoo.circle_packing.governed import governed_setup
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append(reply(usage=None))
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(UsageError):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    assert len(local_endpoint.requests) == 1
    assert len(campaign.snapshot()['pending_calls']) == 1
