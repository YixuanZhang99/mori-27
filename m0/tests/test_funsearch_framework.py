"""M7 Framework integration fixture; no external model or benchmark score."""
import hashlib
import json
from dataclasses import replace
import pytest
from core.executor.evaluation_contract import ItemOutcome
from test_composed_budget import Domain, Provider, TASK
from test_configured_construction import profile, build

TEMPLATE = 'def priority(x):\n    return x\n'


def assembly():
    value = profile(projection=[])
    value['operators'] = [{'name': 'draft'}, {'name': 'funsearch'}]
    value['execution']['constructor'] = {'name': 'funsearch_prompt',
        'options': {'template': TEMPLATE, 'function_name': 'priority'}}
    value['policy'] = {'name': 'funsearch', 'options': {
        'case_ids': ['a', 'b'], 'islands': 2, 'seed': 7, 'prompt_size': 2,
        'temperature': 1.0, 'temperature_period': 10, 'metric': 'score',
        'template': TEMPLATE, 'template_ref': 'sha256:' + hashlib.sha256(TEMPLATE.encode()).hexdigest(),
        'function_name': 'priority', 'reset_interval': 2}}
    return value


class CodeProvider(Provider):
    def __call__(self, prompt):
        super().__call__(prompt)
        request = json.loads(prompt)
        return json.dumps({'artifact': f'def priority(x):\n    return x + {self.generation_index}\n',
                           'hypothesis': request['hypothesis']})


class NumericDomain(Domain):
    async def evaluate(self, proposal, request):
        result = await super().evaluate(proposal, request)
        cycle = proposal.candidate.created_cycle
        items = (ItemOutcome('a', metrics={'score': .1 + cycle * .01}, visibility='public'),
                 ItemOutcome('b', metrics={'score': .7 + cycle * .01}, visibility='public'))
        return replace(result, contract=replace(result.contract, items=items))


def test_framework_constructs_funsearch_candidates_and_replays_without_new_calls(tmp_path):
    provider = CodeProvider(); domain = NumericDomain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=2)
    result = fw.evolve(TASK)
    events = list(fw.store.read())
    assert result['runtime'] == 'composed-v9-m7'
    assert len([r for r in events if r['kind'] == 'funsearch_public_candidate']) == 3
    assert len([r for r in events if r['kind'] == 'funsearch_selection']) == 2
    assert len([r for r in events if r['kind'] == 'funsearch_materialization']) == 2
    assert len([r for r in events if r['kind'] == 'funsearch_reset']) == 1
    requests = [json.loads(prompt) for prompt in provider.prompts]
    assert [request['recipe']['kind'] for request in requests] == ['draft', 'funsearch', 'funsearch']
    assert all('priority_v0' in request['recipe']['instructions'][0] for request in requests[1:])
    before = provider.calls, len(domain.calls)
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert (provider.calls, len(domain.calls)) == before


def test_invalid_generated_program_is_charged_and_never_evaluated(tmp_path):
    class InvalidProvider(CodeProvider):
        def __call__(self, prompt):
            response = json.loads(super().__call__(prompt))
            response['artifact'] = 'def priority(x, unexpected):\n    return x\n'
            return json.dumps(response)
    provider, domain = InvalidProvider(), NumericDomain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=0)
    fw.evolve(TASK)
    assert provider.calls == 1
    assert not domain.calls
    assert not list(fw.store.read('funsearch_public_candidate'))
    assert next(iter(fw._composed.frontier.nodes.values())).eval_status == 'failed_to_run'


def test_funsearch_requires_matching_constructor_before_provider_call(tmp_path):
    configured = assembly()
    configured['execution']['constructor']['options']['template'] = 'def priority(x):\n    return 0\n'
    provider = CodeProvider()
    fw = build(tmp_path, assembly=configured, provider=provider, domain=NumericDomain())
    with pytest.raises(ValueError, match='bounded M7'):
        fw.evolve(TASK)
    assert provider.calls == 0


def test_funsearch_resume_uses_checkpointed_selection_state(tmp_path):
    provider, domain = CodeProvider(), NumericDomain()
    first = build(tmp_path, assembly=assembly(), provider=provider, domain=domain,
                  generations=2, stop=0)
    first.evolve(TASK)
    resumed = build(tmp_path, assembly=assembly(), provider=CodeProvider(), domain=NumericDomain(),
                    generations=2, resume=True)
    resumed.evolve(TASK)
    assert len(list(resumed.store.read('funsearch_public_candidate'))) == 3
    assert len(list(resumed.store.read('funsearch_selection'))) == 2
    assert resumed.replay(TASK)['replay_certificate']['passed']


def test_failed_child_is_abandoned_and_later_selection_can_continue(tmp_path):
    class OneInvalidChild(CodeProvider):
        def __call__(self, prompt):
            response = json.loads(super().__call__(prompt))
            if self.calls == 2:
                response['artifact'] = 'def priority(x, extra):\n    return x\n'
            return json.dumps(response)
    provider, domain = OneInvalidChild(), NumericDomain()
    fw = build(tmp_path, assembly=assembly(), provider=provider, domain=domain, generations=2)
    fw.evolve(TASK)
    assert provider.calls == 3
    assert len(domain.calls) == 2
    assert len(list(fw.store.read('funsearch_abandonment'))) == 1
    assert len(list(fw.store.read('funsearch_public_candidate'))) == 2
    assert fw.replay(TASK)['replay_certificate']['passed']
