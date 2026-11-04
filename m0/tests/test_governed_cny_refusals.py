"""Independent review regressions: refusal proof remains auditable."""
from core.loop import Framework
from test_governed_cny_framework import framework, campaign_fixture, answers, local_endpoint, TASK

def test_main_physical_refusal_drains_controls(tmp_path, local_endpoint):
    campaign=campaign_fixture(tmp_path)
    answers(local_endpoint,4)
    initial,_=framework(tmp_path/'run',campaign,local_endpoint)
    rt=initial._composed
    profile=rt.assembly.to_dict()
    profile['budget']['options']['operation_reservations']['operator']['token']=1
    fw=Framework.from_profile(profile,rt.llm,rt.evaluator,rt.cfg,str(rt.workdir),component_registry=rt.registry)
    fw.evolve(TASK)
    assert fw.inspect()['governance']['completed']==2
    assert len(local_endpoint.requests)==2

def test_missing_key_does_not_leave_unauditable_known_zero_invocation(tmp_path, local_endpoint):
    campaign=campaign_fixture(tmp_path)
    fw,_=framework(tmp_path/'run',campaign,local_endpoint)
    # Existing provider constructor permits omitted key; simulate process-wide
    # local configuration absent for all fresh sessions before any transport.
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    old = GovernedCNYProvider.validate_dispatch
    def missing(self,body):
        self._api_key=None
        return old(self,body)
    from unittest.mock import patch
    with patch.object(GovernedCNYProvider,'validate_dispatch',missing):
        fw.evolve(TASK)
    assert not local_endpoint.requests
    # A known zero-cost pre-admission refusal must be inspectable; no alleged
    # paid uncertainty or evidence corruption was actually encountered.
    fw.inspect()


def test_zero_usage_planning_is_count_bounded_and_drains_controls(tmp_path, local_endpoint):
    from core.composition.defaults import GreedyPolicy
    from test_governed_cny_framework import BOUND
    from test_governed_cny_provider import reply
    campaign = campaign_fixture(tmp_path)
    initial, _ = framework(tmp_path / 'run', campaign, local_endpoint)
    runtime = initial._composed
    class RepeatedPlanner(GreedyPolicy):
        def __init__(self, context):
            super().__init__(context.scope_context)
            self.llm = context.llm
        async def observe(self, state, budget):
            for _ in range(3):
                self.llm('planning')
            return await super().observe(state, budget)
    runtime.registry.register('policy', 'zero-usage-planner', lambda context, options: RepeatedPlanner(context))
    profile = runtime.assembly.to_dict()
    profile['policy'] = {'name': 'zero-usage-planner'}
    profile['budget']['options']['operation_reservations']['planning']['token'] = BOUND
    answers(local_endpoint, 1)
    local_endpoint.responses.append(reply(usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}))
    answers(local_endpoint, 3)
    run = Framework.from_profile(profile, runtime.llm, runtime.evaluator, runtime.cfg, str(runtime.workdir),
                                 component_registry=runtime.registry)
    run.evolve(TASK)
    report = run.inspect()['governance']
    assert report['completed'] == 2 and report['unresolved'] == 0
    assert len(local_endpoint.requests) == 3  # Two controls and one planning call.
    operations = campaign.snapshot()['operations']
    assert len([row for row in operations if row.get('phase') == 'planning']) == 1
    assert not campaign.snapshot()['pending_calls']
