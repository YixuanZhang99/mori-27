"""Offline loopback currency governance with separate OR3 controls."""
import hashlib
import json
import shutil

import pytest

from core.loop import Framework
from test_construction_currency import answer, build as currency_build
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint
from test_funsearch_framework import TASK, assembly
from zoo.funsearch_binpacking.domain import OR3DevDomain


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
@pytest.mark.parametrize('interrupted', [False, True])
def test_governed_funsearch_controls_never_enter_main_population(tmp_path, local_endpoint, monkeypatch, interrupted):
    ids = [f'{i:02}' for i in range(10)]
    data = {key: {'capacity': 10, 'num_items': 2, 'items': [6, 4]} for key in ids}
    path = tmp_path / 'dev.json'; path.write_text(json.dumps(data))
    template = 'def priority(item, bins):\n    return -(bins - item)\n'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    def domain():
        return OR3DevDomain(path, expected_sha256=digest, template=template, timeout=10)
    campaign = campaign_fixture(tmp_path)
    def make_framework(*, resume=False):
        base, _ = currency_build(tmp_path / ('unused-resume' if resume else 'unused'), campaign,
            local_endpoint, cap=1, attempts=1, pause=0 if interrupted and not resume else None, resume=resume)
        config = base._composed.assembly.to_dict()
        funsearch = assembly()
        funsearch['policy']['options'].update(case_ids=ids, template=template,
            template_ref='sha256:' + hashlib.sha256(template.encode()).hexdigest())
        funsearch['execution']['constructor']['options']['template'] = template
        funsearch['execution']['spec']['hypothesis_frozen'] = False
        config['policy'], config['operators'], config['execution'] = (
            funsearch['policy'], funsearch['operators'], funsearch['execution'])
        config['budget']['options']['fidelity_rungs'][0].pop('seed_set', None)
        config['governance']['controls']['request'].pop('seed_set', None)
        config['governance']['controls']['domain'] = {'name': 'or3-control-fixture'}
        registry = base._composed.registry
        registry.register('domain', 'or3-control-fixture', lambda _ctx, _opts: domain(),
            governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
        return Framework.from_profile(config, base._composed.llm, domain(), base._composed.cfg,
                                      str(tmp_path / 'run'), component_registry=registry)
    local_endpoint.responses.extend(answer(json.dumps({'artifact': template,
        'hypothesis': 'Fixture hypothesis'})) for _ in range(4))
    fw = make_framework()
    fw.evolve(TASK)
    if interrupted:
        before_resume = len(local_endpoint.requests)
        fw = make_framework(resume=True)
        fw.evolve(TASK)
        assert before_resume < len(local_endpoint.requests) == 4
    main = {row['payload']['candidate_id'] for row in fw.store.read('funsearch_public_candidate')}
    controls = {row['payload']['candidate_id'] for row in fw.store.read('governed_control_terminal')}
    assert len(main) == 2 and len(controls) == 2 and main.isdisjoint(controls)
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 152
    inspection = fw.inspect()['governance']['external_currency']
    assert inspection['protection_valid'] and not inspection['integrity_violations']
    assert fw._composed.governed.external.audit()['construction']['provider_calls'] == 4
    for body in local_endpoint.requests:
        prompt = json.loads(json.loads(body)['messages'][0]['content'])
        assert template in prompt['recipe']['instructions'] or 'named priority' in prompt['recipe']['task_desc'] or \
            any(template in instruction for instruction in prompt['recipe']['instructions'])
    before = campaign.snapshot()
    from test_governed_cny_framework import CountedProvider
    monkeypatch.setattr(CountedProvider, 'perform_request', lambda *_args: pytest.fail('replay requested HTTP'))
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert campaign.snapshot() == before
