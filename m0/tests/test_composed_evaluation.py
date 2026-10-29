"""M8 contract validation and privacy through the public Framework entry point."""
from dataclasses import replace
import json

import pytest

from core.composition.evaluation import (EvaluationContract, PublicEvaluationData,
    PrivateEvaluationData, binding_for, validate_request)
from core.composition.defaults import GreedyPolicy, MetricAdmission, composed_profile, default_registry
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.llm import UsageError
from core.x1.checkpoint import RunCheckpoint
from test_composed_runtime import TASK, CountingLLM, config, framework, records


class NativeDomain:
    evaluator_version = 'native-v1'
    evaluation_context = 'sha256:' + 'b' * 64

    def __init__(self, defect=None):
        self.defect, self.calls, self.requests = defect, 0, []

    def validate_request(self, request):
        validate_request(request)
        if self.defect == 'unsupported':
            raise ValueError('domain does not support requested fidelity')

    async def evaluate(self, proposal, request):
        self.calls += 1
        self.requests.append(request)
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context)
        replacements = {'candidate': {'candidate_id': 'foreign'},
                        'artifact': {'artifact_sha256': 'c' * 64},
                        'context': {'evaluation_context': 'sha256:' + 'c' * 64},
                        'version': {'evaluator_version': 'foreign-v2'},
                        'request': {'request_sha256': 'sha256:' + 'd' * 64},
                        'split': {'split_id': 'final_audit'}}
        if self.defect in replacements:
            binding = replace(binding, **replacements[self.defect])
        contract = EvaluationContract(binding, ('token', 'eval_count'),
            public=PublicEvaluationData({'lesson': 'PUBLIC_LESSON'}),
            private=PrivateEvaluationData({'heldout/score': 0.98}, {'secret': 'PRIVATE_CANARY'}))
        if self.defect == 'missing_measurement':
            contract = replace(contract, measured_cost_units=('eval_count',))
        if self.defect == 'missing_contract':
            contract = None
        return EvalResult(EvalStatus.OK, {'dev/score': 0.25 + 0.1 * proposal.candidate.created_cycle},
            cost=CostVec(tokens_in=4, tokens_out=3, eval_count=1), fidelity=request.fidelity,
            uncertainty=0.01, text_feedback='PUBLIC_FEEDBACK', partial_curves_ref='curve:one',
            trajectory_ref='trajectory:one', artifacts_ref='artifact:one', contract=contract)


def native_framework(path, domain=None, **kwargs):
    profile = composed_profile()
    profile['domain'] = {'name': 'native'}
    return framework(path, profile=profile, evaluator=domain or NativeDomain(), **kwargs)


def test_native_domain_metadata_and_cost_survive_framework_checkpoint_resume_replay(tmp_path):
    full = native_framework(tmp_path / 'full', cfg=config(max_generations=2))
    expected = full.evolve(TASK)
    partial = native_framework(tmp_path / 'split', cfg=config(max_generations=2, stop_after_generation=0))
    partial.evolve(TASK)
    resumed = native_framework(tmp_path / 'split', cfg=config(max_generations=2, resume_from_checkpoint=True))
    actual = resumed.evolve(TASK)
    assert {k:v for k,v in actual.items() if k != "checkpoint_ref"} == {
        k:v for k,v in expected.items() if k != "checkpoint_ref"}
    for row in records(resumed, 'composed_evidence'):
        result = row['evidence']['eval_result']
        assert result['contract']['private']['data']['secret'] == 'PRIVATE_CANARY'
        assert result['contract']['binding']['evaluation_context'] == NativeDomain.evaluation_context
        assert result['partial_curves_ref'] == 'curve:one'
        assert result['trajectory_ref'] == 'trajectory:one'
        assert result['uncertainty'] == 0.01
        assert result['cost']['tokens_out'] == 3
    assert sum(actual['ledger']['spent'].values()) == 3 * 1007
    assert resumed.replay()['replay_certificate']['passed']


@pytest.mark.parametrize('defect', ['candidate', 'artifact', 'context', 'version', 'request', 'split'])
def test_returned_identity_cannot_be_filled_in_from_expected_binding(tmp_path, defect):
    domain = NativeDomain(defect)
    fw = native_framework(tmp_path, domain, cfg=config(max_generations=0))
    with pytest.raises(ValueError):
        fw.evolve(TASK)
    assert domain.calls == 1
    assert not records(fw, 'composed_decision')
    assert not records(fw, 'state_mutation')
    assert records(fw, 'composed_cycle_failed')[0]['known_tokens'] == 1007
    assert not fw._composed.budget.reserves


@pytest.mark.parametrize('defect', ['missing_measurement', 'missing_contract'])
def test_unknown_measurement_retains_reservation_instead_of_certifying_zero(tmp_path, defect):
    domain = NativeDomain(defect)
    fw = native_framework(tmp_path, domain, cfg=config(max_generations=0))
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    assert domain.calls == 1
    assert fw._composed.budget.reserves
    assert not records(fw, 'composed_decision')
    assert not records(fw, 'composed_cycle_failed')


def test_unsupported_request_is_rejected_before_provider_call(tmp_path):
    llm, domain = CountingLLM(), NativeDomain('unsupported')
    fw = native_framework(tmp_path, domain, llm=llm)
    with pytest.raises(ValueError, match='support'):
        fw.evolve(TASK)
    assert llm.calls == domain.calls == 0
    assert not records(fw, 'composed_cycle_started')


def test_private_data_is_durable_but_cannot_reach_search_or_admission(tmp_path):
    observations = []
    class InspectPolicy(GreedyPolicy):
        async def observe(self, state, budget):
            observations.append(repr(state))
            return await super().observe(state, budget)
        async def absorb(self, evidence):
            observations.append(repr(evidence))
            return await super().absorb(evidence)
    class InspectAdmission(MetricAdmission):
        def judge(self, evidence, incumbent):
            assert not hasattr(evidence.eval_result, 'cost')
            assert not hasattr(evidence.eval_result, 'contract')
            observations.append(repr(evidence))
            return super().judge(evidence, incumbent)
    registry = default_registry()
    registry.register('policy', 'inspect', lambda ctx, opts: InspectPolicy(ctx.scope_context))
    registry.register('admission', 'inspect', lambda ctx, opts: InspectAdmission())
    profile = composed_profile()
    profile.update(domain={'name':'native'}, policy={'name':'inspect'}, admission={'name':'inspect'})
    llm = CountingLLM()
    fw = framework(tmp_path, profile=profile, evaluator=NativeDomain(), llm=llm,
                   registry=registry, cfg=config(max_generations=1))
    fw.evolve(TASK)
    assert 'PRIVATE_CANARY' not in repr(observations + llm.prompts)
    payload = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    assert 'PRIVATE_CANARY' not in json.dumps(payload['memory'])
    assert 'PRIVATE_CANARY' not in payload['frontier_checkpoint']
    assert 'PRIVATE_CANARY' in json.dumps(payload['evidence'])


def test_old_unbound_composed_checkpoint_is_rejected_before_new_paid_work(tmp_path):
    fw = native_framework(tmp_path, cfg=config(max_generations=0))
    fw.evolve(TASK)
    checkpoint = RunCheckpoint.load(tmp_path / 'checkpoint.json')
    payload = checkpoint.payload
    payload['runtime'] = 'composed-v1'
    RunCheckpoint.create(payload).save(tmp_path / 'checkpoint.json')
    llm, domain = CountingLLM(), NativeDomain()
    resumed = native_framework(tmp_path, domain, llm=llm,
                               cfg=config(max_generations=0, resume_from_checkpoint=True))
    before = resumed.store.path.read_bytes()
    with pytest.raises(ValueError, match='runtime'):
        resumed.evolve(TASK)
    assert llm.calls == domain.calls == 0
    assert resumed.store.path.read_bytes() == before


def test_tampered_bound_checkpoint_fails_without_new_journal_or_paid_calls(tmp_path):
    fw = native_framework(tmp_path, cfg=config(max_generations=0))
    fw.evolve(TASK)
    payload = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    candidate_id = next(iter(payload['evidence']))
    payload['evidence'][candidate_id]['eval_result']['contract']['binding']['artifact_sha256'] = 'e' * 64
    RunCheckpoint.create(payload).save(tmp_path / 'checkpoint.json')
    llm, domain = CountingLLM(), NativeDomain()
    resumed = native_framework(tmp_path, domain, llm=llm,
        cfg=config(max_generations=0, resume_from_checkpoint=True))
    before = resumed.store.path.read_bytes()
    with pytest.raises(ValueError, match='binding'):
        resumed.evolve(TASK)
    assert llm.calls == domain.calls == 0
    assert resumed.store.path.read_bytes() == before


@pytest.mark.parametrize('status', [EvalStatus.FAILED_TO_RUN, EvalStatus.TIMEOUT, EvalStatus.INVALID])
def test_failed_evaluation_remains_typed_and_charged_without_promotion(tmp_path, status):
    class FailedDomain(NativeDomain):
        async def evaluate(self, proposal, request):
            result = await super().evaluate(proposal, request)
            return replace(result, status=status, metrics={})
    domain = FailedDomain()
    fw = native_framework(tmp_path, domain, cfg=config(max_generations=0))
    result = fw.evolve(TASK)
    assert result['best_candidate_id'] is None
    assert sum(result['ledger']['spent'].values()) == 1007
    row = records(fw, 'composed_evidence')[0]['evidence']
    assert row['eval_result']['status'] == status.value
    assert row['executor_status'] == status.value
    assert records(fw, 'composed_decision')[0]['decision']['admit'] is False
    assert fw.replay()['replay_certificate']['passed']
