"""One measured lifecycle against the real physical authority, across phases."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.budget.ledger import BudgetError
from core.composition.contracts import OperatorFailure, Proposal
from core.executor.types import Candidate, CostVec, EvalRequest, EvidenceRecord
from core.llm import UsageError
from test_composed_budget import Domain, TASK, build

PHASES = ('planning', 'operator', 'evaluation')


class Interrupted(BaseException):
    pass


def prepare(path, phase, governance=None):
    from core.composition.invocation import InvocationLifecycle
    fw = build(path, generations=0)
    fw.evolve(TASK)
    runtime = fw._composed
    provider = runtime.parts['provider']
    provider.raw_provider.tokens = 1
    candidate = Candidate('extra-lifecycle-candidate')
    request = EvalRequest('dev')
    receipt = runtime._reserve_physical(candidate, 'dev' if phase == 'evaluation' else phase,
                                        'extra', request=request if phase == 'evaluation' else None)
    assert receipt.granted
    owner = InvocationLifecycle(runtime.budget, runtime.store, runtime._settle_physical,
                                governance=governance)
    return runtime, owner, provider, candidate, request, receipt


def invoke_phase(owner, phase, provider, candidate, request, receipt, *, failure=None):
    cost = CostVec(tokens_in=1, node_count=1 if phase == 'operator' else 0)
    coverage = ('token', 'node', 'eval_count')
    proposal = Proposal(candidate, 'candidate artifact', cost, coverage)
    domain = Domain()

    async def invoke():
        provider('one measured request')
        if failure == 'ordinary':
            raise RuntimeError('ordinary failure')
        if failure == 'interrupted':
            raise Interrupted('process disappeared')
        if failure == 'typed':
            raise OperatorFailure(cost, 'known failed sample', measured_cost_units=coverage)
        if phase == 'evaluation':
            result = await domain.evaluate(proposal, request)
            return EvidenceRecord(candidate.id, replace(result, cost=CostVec(tokens_in=1, eval_count=1)))
        return proposal if phase == 'operator' else 'planned'

    if phase == 'planning':
        return asyncio.run(owner.planning(receipt, provider, invoke))
    if phase == 'operator':
        async def propose(_):
            return await invoke()
        return asyncio.run(owner.operator(SimpleNamespace(propose=propose), object(), candidate,
                                          receipt, provider=provider))
    return asyncio.run(owner.evaluation(receipt, provider, invoke, identity={}, domain=domain))


def operation_events(runtime, receipt):
    return [row['payload'] for row in runtime.store.read('hierarchical_budget')
            if row['payload']['data'].get('intent_id') == receipt.intent_id]


@pytest.mark.parametrize('phase', PHASES)
def test_each_phase_settles_real_charge_once_and_refuses_a_second_dispatch(tmp_path, phase):
    runtime, owner, provider, candidate, request, receipt = prepare(tmp_path, phase)
    before = provider.raw_provider.calls
    invoke_phase(owner, phase, provider, candidate, request, receipt)
    events = operation_events(runtime, receipt)
    assert [row['event'] for row in events] == ['start', 'settle']
    assert events[-1]['data']['actual_costs'] == {
        'token': 1, 'node': int(phase == 'operator'), 'eval_count': int(phase == 'evaluation')}
    with pytest.raises(BudgetError, match='unstarted'):
        invoke_phase(owner, phase, provider, candidate, request, receipt)
    assert provider.raw_provider.calls == before + 1


@pytest.mark.parametrize('phase', PHASES)
def test_unknown_usage_retains_reservation_for_every_phase(tmp_path, phase):
    runtime, owner, provider, candidate, request, receipt = prepare(tmp_path, phase)
    provider.raw_provider.unknown = True
    with pytest.raises(UsageError):
        invoke_phase(owner, phase, provider, candidate, request, receipt)
    assert [row['event'] for row in operation_events(runtime, receipt)] == ['start', 'unresolved']
    assert runtime.budget.state()['global']['reserved'] == receipt.amounts


@pytest.mark.parametrize('phase', PHASES)
def test_process_interruption_is_not_reclassified_as_known_failure(tmp_path, phase):
    runtime, owner, provider, candidate, request, receipt = prepare(tmp_path, phase)
    with pytest.raises(Interrupted):
        invoke_phase(owner, phase, provider, candidate, request, receipt, failure='interrupted')
    assert [row['event'] for row in operation_events(runtime, receipt)] == ['start']
    assert runtime.budget.state()['global']['reserved'] == receipt.amounts


def test_ordinary_planning_failure_settles_known_usage_before_propagating(tmp_path):
    runtime, owner, provider, candidate, request, receipt = prepare(tmp_path, 'planning')
    with pytest.raises(RuntimeError, match='ordinary failure'):
        invoke_phase(owner, 'planning', provider, candidate, request, receipt, failure='ordinary')
    events = operation_events(runtime, receipt)
    assert [row['event'] for row in events] == ['start', 'settle']
    assert events[-1]['data']['actual_costs']['token'] == 1


def test_typed_operator_failure_returns_failed_sample_after_charging(tmp_path):
    runtime, owner, provider, candidate, request, receipt = prepare(tmp_path, 'operator')
    proposal, failure = invoke_phase(owner, 'operator', provider, candidate, request, receipt, failure='typed')
    assert isinstance(failure, OperatorFailure) and proposal.artifact == ''
    assert [row['event'] for row in operation_events(runtime, receipt)] == ['start', 'settle']
    assert operation_events(runtime, receipt)[-1]['data']['actual_costs']['token'] == 1


def test_integrity_failure_cannot_erase_a_known_planning_charge(tmp_path):
    class ChangedBinding:
        exited = False

        @contextmanager
        def meter(self, provider, receipt, **kwargs):
            yield
            self.exited = True

        def check_integrity(self, receipt):
            assert self.exited
            raise UsageError('binding changed after measured call')

    runtime, owner, provider, candidate, request, receipt = prepare(tmp_path, 'planning', ChangedBinding())
    with pytest.raises(UsageError, match='binding changed'):
        invoke_phase(owner, 'planning', provider, candidate, request, receipt)
    events = operation_events(runtime, receipt)
    assert [row['event'] for row in events] == ['start', 'settle']
    assert events[-1]['data']['actual_costs']['token'] == 1


def test_legacy_native_exception_does_not_attest_a_supervisor_measurement(tmp_path):
    from core.composition.worktree import MeasuredCommandError
    runtime, owner, provider, candidate, request, receipt = prepare(tmp_path, 'evaluation')

    async def unsupported():
        provider('native call without supervisor attestation')
        raise MeasuredCommandError('unbound native failure', CostVec(tokens_in=1, eval_count=1),
                                   ('token', 'eval_count', 'node'),
                                   raw_response_path='not-an-attestation.json', wall_seconds=0.1)

    with pytest.raises(MeasuredCommandError, match='unbound native'):
        asyncio.run(owner.evaluation(receipt, provider, unsupported, identity={}, domain=Domain()))
    assert [row['event'] for row in operation_events(runtime, receipt)] == ['start', 'unresolved']
    assert runtime.budget.state()['global']['reserved'] == receipt.amounts
