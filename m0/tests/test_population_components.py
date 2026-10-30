"""Actual population, retrieval, crossover, evaluation and state APIs (no driver wiring)."""
import asyncio
import hashlib
import json
from dataclasses import replace

import pytest

from core.budget.types import AccountingStamp
from core.composition.budget import HierarchicalBudget
from core.composition.context import ContextMemory, ContextPackBuilder
from core.composition.contracts import OperatorRequest, Proposal
from core.composition.defaults import InProcessExecutor, MetricAdmission, OperatorFailure
from core.composition.evaluation import (EvaluationContract, PrivateEvaluationData, binding_for,
    comparison_projection, encode_evidence, public_projection, validate_evidence)
from core.composition.population import CrossoverOperator, PopulationPolicy
from core.composition.provider import MeteredProvider
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus
from core.frontier.population import PopulationFrontier
from core.llm import UsageError
from core.memory.types import ScopeContext
from core.policy.types import MutationOp, StateMutation
from core.state import StateApplier
from core.x1.store import AppendOnlyStore

CONTEXT = 'sha256:' + 'a' * 64


class Domain:
    async def evaluate(self, proposal, request):
        return EvalResult(EvalStatus.OK, {'dev/score': len(proposal.artifact)},
            CostVec(tokens_in=2, eval_count=1), fidelity=request.fidelity,
            text_feedback='lesson:' + proposal.candidate.id,
            contract=EvaluationContract(binding_for(proposal, request, evaluator_version='domain-v1',
                evaluation_context=CONTEXT), ('token', 'eval_count'),
                private=PrivateEvaluationData(data={'secret': 'PRIVATE_PARENT_CANARY'})))


class Provider:
    def __init__(self, answer='A+B', unknown=False):
        self.prompts, self.answer, self.unknown = [], answer, unknown
    def __call__(self, prompt):
        self.prompts.append(prompt)
        self.last_usage = None if self.unknown else {'total_tokens': 7}
        return self.answer


def execute(proposal):
    return asyncio.run(InProcessExecutor().execute(proposal, EvalRequest('dev'), Domain()))


def parent_request():
    parents = (Proposal(Candidate('a'), 'A'), Proposal(Candidate('b'), 'B'))
    evidence = tuple(public_projection(execute(parent)) for parent in parents)
    return OperatorRequest('combine both improvements', 'child', 2, parents, evidence,
        {'context_pack_ref': 'sha256:' + 'b' * 64, 'retrieval': {'memory': [{'body': 'actual scoped lesson'}]}})


def test_text_crossover_consumes_two_bound_parents_public_evidence_and_contextpack():
    provider = Provider(); request = parent_request()
    result = asyncio.run(CrossoverOperator(MeteredProvider(provider)).propose(request))
    assert result.candidate.parents == ['a', 'b'] and result.artifact == 'A+B'
    assert result.candidate.context_pack_ref == request.context['context_pack_ref']
    assert result.cost == CostVec(tokens_in=7, node_count=1)
    assert result.measured_cost_units == ('token', 'node', 'eval_count')
    prompt = provider.prompts[0]
    assert '"candidate_id": "a"' in prompt and '"candidate_id": "b"' in prompt
    assert '"artifact": "A"' in prompt and '"artifact": "B"' in prompt
    assert 'lesson:a' in prompt and 'lesson:b' in prompt and 'actual scoped lesson' in prompt
    assert 'PRIVATE_PARENT_CANARY' not in prompt


@pytest.mark.parametrize('fault', ['single_parent', 'duplicate', 'artifact', 'wrong_evidence', 'failed', 'heldout'])
def test_crossover_rejects_invalid_parent_authority_before_provider_call(fault):
    request = parent_request(); provider = Provider()
    if fault == 'single_parent': request = replace(request, parents=request.parents[:1], evidence=request.evidence[:1])
    elif fault == 'duplicate': request = replace(request, parents=(request.parents[0], request.parents[0]))
    elif fault == 'artifact': request = replace(request, parents=(replace(request.parents[0], artifact='forged'), request.parents[1]))
    elif fault == 'wrong_evidence': request = replace(request, evidence=tuple(reversed(request.evidence)))
    elif fault == 'failed':
        first = request.evidence[0]
        failed = replace(first, executor_status='failed_to_run', eval_result=replace(first.eval_result, status=EvalStatus.FAILED_TO_RUN))
        request = replace(request, evidence=(failed, request.evidence[1]))
    else:
        first = request.evidence[0]
        changed = replace(first, eval_result=replace(first.eval_result, contract=replace(first.eval_result.contract,
            binding=replace(first.eval_result.contract.binding, split_id='admission'))))
        request = replace(request, evidence=(changed, request.evidence[1]))
    with pytest.raises(ValueError):
        asyncio.run(CrossoverOperator(MeteredProvider(provider)).propose(request))
    assert provider.prompts == []


def test_empty_crossover_records_known_usage_and_unknown_provider_usage_is_not_zero():
    provider = Provider(answer='')
    with pytest.raises(OperatorFailure) as failure:
        asyncio.run(CrossoverOperator(MeteredProvider(provider)).propose(parent_request()))
    assert failure.value.cost == CostVec(tokens_in=7, node_count=1)
    unknown = Provider(unknown=True)
    with pytest.raises(UsageError):
        asyncio.run(CrossoverOperator(MeteredProvider(unknown)).propose(parent_request()))


def test_population_policy_bootstraps_roots_then_drives_configured_two_parent_sampling():
    policy = PopulationPolicy(ScopeContext('run', 'task', 'domain'))
    frontier = PopulationFrontier(capacity=2, selection='uniform')
    state = {'operators': ['draft', 'crossover'], 'frontier': json.loads(frontier.view('json')), 'cycle': 0}
    asyncio.run(policy.observe(state, {}))
    assert asyncio.run(policy.select(frontier, {})) == []
    for identifier in ('a', 'b'):
        proposal = Proposal(Candidate(identifier), identifier)
        frontier.add(proposal.candidate, execute(proposal))
        frontier.finalize(identifier, admitted=identifier == 'a', reason='actual decision',
            selected_id='a', decision_ref='receipt:' + identifier)
    view = PopulationFrontier.restore(frontier.checkpoint())
    parents = asyncio.run(policy.select(view, {}))
    assert set(parents) == {'a', 'b'} and len(view.sampling_receipts) == 1
    assert frontier.rng_state == {'counter': 0, 'calls': 0}
    frontier.commit_sampling(view.sampling_receipts)
    assert frontier.rng_state == view.rng_state
    ideas = asyncio.run(policy.ideate({}, Proposal(Candidate('a'), 'A'), 1))
    assert ideas[0]['operator'] == 'crossover'
    restored = PopulationPolicy(policy._baseline.context)
    restored.restore_state(policy.checkpoint_state())
    assert restored.checkpoint_state() == policy.checkpoint_state()


def test_real_component_api_cycle_keeps_one_population_dag_and_closes_memory_and_physical_budget(tmp_path):
    store = AppendOnlyStore(tmp_path / 'events.jsonl')
    scope = ScopeContext('run', 'task', 'domain')
    frontier = PopulationFrontier(capacity=2, selection='uniform', store=store)
    memory = ContextMemory(store, scope, CONTEXT)
    applier, policy = StateApplier(frontier, memory, store), PopulationPolicy(scope)
    options = {'limits': {level: {'token': 100, 'node': 10, 'eval_count': 10} for level in ('global', 'direction', 'candidate')},
        'reservation': {'token': 5, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'operator': {'token': 10, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev'}]}
    budget = HierarchicalBudget(options, AccountingStamp('offline', 'model', 'tokenizer', 'price', 'logical'), store)
    proposals, evidence = {}, {}
    def materialize(proposal, operator_receipt=None):
        candidate = proposal.candidate
        direction = candidate.parents[0] if candidate.parents else candidate.id
        receipt = operator_receipt or budget.reserve_operation('op:' + candidate.id, candidate, direction, 'operator')
        budget.settle_operation(receipt.intent_id, {'token': proposal.cost.tokens_in, 'node': 1, 'eval_count': 0},
            measured_units=budget.units, fingerprint=receipt.fingerprint)
        request = budget.allocate(candidate, direction_id=direction)
        evaluation = budget.reserve_operation('dev:' + candidate.id, candidate, direction, 'dev', request=request)
        measured = asyncio.run(InProcessExecutor().execute(proposal, request, Domain()))
        validate_evidence(measured)
        budget.settle_operation(evaluation.intent_id, {'token': 2, 'node': 0, 'eval_count': 1},
            measured_units=budget.units, fingerprint=evaluation.fingerprint)
        public = public_projection(measured)
        applier.apply(StateMutation(MutationOp.ADD_NODE, candidate.id, {'candidate': candidate, 'evidence': public}, 'evaluated'))
        receipt_ref = 'sha256:' + hashlib.sha256(json.dumps(encode_evidence(measured), sort_keys=True).encode()).hexdigest()
        mutations = memory.prepare_mutations(asyncio.run(policy.absorb(public)), public, receipt_ref, cycle=candidate.created_cycle)
        applier.apply_all(mutations)
        incumbent = evidence.get(frontier.protected_id)
        decision = MetricAdmission().judge(comparison_projection(measured), comparison_projection(incumbent) if incumbent else None)
        applier.apply(StateMutation(MutationOp.POPULATION_FINALIZE, candidate.id, {'admitted': decision.admit,
            'reason': decision.reason, 'selected_id': candidate.id if decision.admit else frontier.protected_id,
            'decision_ref': receipt_ref}, 'actual M9 outcome'))
        proposals[candidate.id], evidence[candidate.id] = proposal, measured
    materialize(Proposal(Candidate('a'), 'A'))
    materialize(Proposal(Candidate('b', created_cycle=1), 'B'))
    view = PopulationFrontier.restore(frontier.checkpoint())
    parents = asyncio.run(policy.select(view, budget.state()))
    frontier.commit_sampling(view.sampling_receipts)
    pack = ContextPackBuilder(memory, {'context_scope': 'parents'}).retrieve(frontier, parents, 'lessons', 2)
    assert {row['body'] for row in pack.to_dict()['memory']} == {'lesson:a', 'lesson:b'}
    request = OperatorRequest('combine', 'child', 2, tuple(proposals[parent] for parent in parents),
        tuple(public_projection(evidence[parent]) for parent in parents),
        {'context_pack_ref': pack.ref, 'retrieval': pack.to_dict()})
    provisional = Candidate('child', parents, created_cycle=2)
    reserved = budget.reserve_operation('op:child', provisional, parents[0], 'operator')
    provider = Provider()
    child = asyncio.run(CrossoverOperator(MeteredProvider(provider)).propose(request))
    materialize(child, reserved)
    assert child.candidate.parents == parents and frontier.nodes['child'].depth == 1
    assert frontier.protected_id == 'child' and len(frontier.member_ids) == 2 and len(frontier.nodes) == 3
    assert len(memory.entries) == 3 and all(entry.level == 'L2' for entry in memory.entries.values())
    assert budget.state()['global']['used'] == {'token': 13, 'node': 3, 'eval_count': 3}
    assert not budget.state()['open_intents']
    assert 'lesson:a' in provider.prompts[0] and 'lesson:b' in provider.prompts[0]
    restored = PopulationFrontier.restore(frontier.checkpoint())
    assert restored.nodes['child'].parent_ids == parents and restored.rng_state == frontier.rng_state


def test_exact_population_policy_has_known_zero_local_gpu_and_usd_but_subclasses_do_not():
    from types import SimpleNamespace
    from core.composition.hierarchical_runtime import HierarchicalRuntime
    from core.memory.types import ScopeContext
    controller = HierarchicalRuntime()
    meter = SimpleNamespace(measured_cost_units=('token', 'node', 'eval_count', 'gpu_hours', 'usd'))
    controller.parts = {'operators': (meter,), 'domain': meter, 'skills': (),
                        'policy': PopulationPolicy(ScopeContext('run', 'task', 'domain'))}
    controller.budget = SimpleNamespace(units=('token', 'gpu_hours', 'usd'),
        options={'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]})
    controller._validate_domain = lambda request: request.validate()
    controller._preflight_hierarchical()
    class ArbitraryPolicy(PopulationPolicy):
        pass
    controller.parts['policy'] = ArbitraryPolicy(ScopeContext('run', 'task', 'domain'))
    with pytest.raises(ValueError, match='supported local adapter'):
        controller._preflight_hierarchical()
