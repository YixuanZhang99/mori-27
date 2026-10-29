"""Three-layer evaluation, query caps and frozen final audit through Framework."""
from dataclasses import asdict
import json

import pytest

from core.composition.evaluation import EvaluationContract, PrivateEvaluationData, binding_for
from core.composition.defaults import composed_profile
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.x1.checkpoint import RunCheckpoint
from test_composed_runtime import TASK, CountingLLM, config, framework, records


class LayeredDomain:
    evaluator_version = 'layered-v1'
    evaluation_context = 'sha256:' + 'b' * 64
    contexts = {'dev': evaluation_context, 'admission': 'sha256:' + 'c' * 64,
                'final_audit': 'sha256:' + 'd' * 64}

    def __init__(self, fail_gate=False, invalid_gate=False):
        self.calls = []
        self.fail_gate, self.invalid_gate = fail_gate, invalid_gate

    def validate_request(self, request):
        request.validate()
        if request.split_id not in self.contexts or request.fidelity != request.split_id:
            raise ValueError('unsupported evaluation split or fidelity')
        if request.time_limit is not None or request.budget_token is not None or request.resume_from is not None:
            raise ValueError('unsupported execution constraints')

    def evaluation_context_for(self, request):
        return self.contexts[request.split_id]

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        self.calls.append((proposal.candidate.id, request.split_id, request.seed_set))
        cycle = proposal.candidate.created_cycle
        values = {'dev': [0.4,0.9,0.8,0.95], 'admission': [0.8,0.6,0.85,0.7], 'final_audit':[0.9,0.95,0.1,1.0]}
        score = values[request.split_id][cycle % 4]
        if request.seed_set:
            score = sum(score + seed * 0.00001 for seed in request.seed_set) / len(request.seed_set)
        status = EvalStatus.FAILED_TO_RUN if self.fail_gate and request.split_id == 'admission' and cycle == 1 else EvalStatus.OK
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context_for(request))
        if self.invalid_gate and request.split_id == 'admission':
            from dataclasses import replace
            binding = replace(binding, candidate_id='foreign')
        return EvalResult(status, {'dev/score':score} if status is EvalStatus.OK else {},
            CostVec(tokens_in=7, eval_count=1), fidelity=request.fidelity,
            text_feedback='DEV_FEEDBACK' if request.split_id=='dev' else request.split_id.upper()+'_FEEDBACK_CANARY',
            contract=EvaluationContract(binding, ('token','eval_count'),
                private=PrivateEvaluationData(data={'secret':request.split_id.upper()+'_PRIVATE_CANARY'})))


def layered(path, *, domain=None, llm=None, options=None, cfg=None, knowledge=None):
    profile = composed_profile(mode='research' if knowledge else 'benchmark')
    profile['domain'] = {'name':'native'}
    profile['admission'] = {'name':'layered', 'options':options or {}}
    if knowledge:
        profile['knowledge'] = {'name':'local_files', 'options':knowledge}
    return framework(path, profile=profile, evaluator=domain or LayeredDomain(), llm=llm,
                     cfg=cfg or config(max_generations=3))


def test_dev_overfit_does_not_promote_and_final_reverse_score_cannot_change_frozen_winner(tmp_path):
    domain, llm = LayeredDomain(), CountingLLM()
    fw = layered(tmp_path, domain=domain, llm=llm,
                 options={'admission_seeds':[11,23], 'final_seeds':[37]})
    result = fw.evolve(TASK)
    report = result['reporting']
    ids = [row['proposal']['candidate']['id'] for row in records(fw,'composed_evidence')]
    assert report['dev_best']['candidate_id'] == ids[3]
    assert report['gate_selected']['candidate_id'] == result['best_candidate_id'] == ids[2]
    assert report['final_audit']['selected_id'] == ids[2]
    assert report['final_audit']['evidence']['eval_result']['metrics']['dev/score'] < 0.2
    assert [split for _,split,_ in domain.calls] == ['dev','admission'] * 4 + ['final_audit']
    assert report['gate_calls'] == 4 and report['final_audit']['calls'] == 1
    assert all(seeds == [11,23] for _,split,seeds in domain.calls if split=='admission')
    assert domain.calls[-1][2] == [37]
    assert sum(result['ledger']['spent'].values()) == 4*1007+5*7
    assert 'ADMISSION_FEEDBACK_CANARY' not in repr(llm.prompts)
    assert 'FINAL_FEEDBACK_CANARY' not in repr(llm.prompts)
    payload = RunCheckpoint.load(tmp_path/'checkpoint.json').payload
    assert 'FINAL_FEEDBACK_CANARY' not in json.dumps(payload['memory'])
    assert 'FINAL_FEEDBACK_CANARY' not in payload['frontier_checkpoint']
    assert 'FINAL_FEEDBACK_CANARY' not in json.dumps(payload['module_states']['policy:0'])
    assert fw.replay()['replay_certificate']['passed']


def test_call_budget_blocks_next_admission_call_but_all_development_runs_and_one_final_remain(tmp_path):
    domain = LayeredDomain()
    fw = layered(tmp_path, domain=domain, options={'call_budget':1})
    result = fw.evolve(TASK)
    assert [split for _,split,_ in domain.calls].count('dev') == 4
    assert [split for _,split,_ in domain.calls].count('admission') == 1
    assert [split for _,split,_ in domain.calls].count('final_audit') == 1
    assert result['reporting']['gate_calls'] == 1
    assert any('call budget' in row['decision']['reason'] for row in records(fw,'composed_decision'))


def test_failed_admission_call_consumes_cap_and_known_cost_and_does_not_admit(tmp_path):
    domain = LayeredDomain(fail_gate=True)
    fw = layered(tmp_path, domain=domain, options={'call_budget':2})
    result = fw.evolve(TASK)
    assert result['reporting']['gate_calls'] == 2
    assert [split for _,split,_ in domain.calls].count('admission') == 2
    assert [row['decision']['admit'] for row in records(fw,'composed_decision')] == [True,False,False,False]
    assert sum(result['ledger']['spent'].values()) == 4*1007+3*7


def test_global_budget_denies_gate_before_invocation_without_spending_query_cap(tmp_path):
    domain = LayeredDomain()
    fw = layered(tmp_path, domain=domain, cfg=config(total_budget=2200, max_generations=0))
    result = fw.evolve(TASK)
    assert [split for _,split,_ in domain.calls] == ['dev']
    assert result['reporting']['gate_calls'] == 0
    assert result['reporting']['gate_selected'] is None
    assert result['reporting']['final_audit']['state'] == 'no_selection'
    assert sum(result['ledger']['spent'].values()) == 1007


def test_resume_restores_calls_and_only_terminal_run_performs_final_audit(tmp_path):
    opts = {'admission_seeds':[3]}
    first_domain = LayeredDomain()
    first = layered(tmp_path, domain=first_domain, options=opts, cfg=config(max_generations=3,stop_after_generation=1))
    partial = first.evolve(TASK)
    assert partial['reporting']['final_audit']['state']=='not_frozen'
    assert 'final_audit' not in [split for _,split,_ in first_domain.calls]
    resumed_domain = LayeredDomain()
    resumed = layered(tmp_path, domain=resumed_domain, options=opts,
                      cfg=config(max_generations=3,resume_from_checkpoint=True))
    result = resumed.evolve(TASK)
    assert [split for _,split,_ in resumed_domain.calls] == ['dev','admission','dev','admission','final_audit']
    assert result['reporting']['gate_calls']==4
    completed_domain = LayeredDomain()
    completed = layered(tmp_path, domain=completed_domain, options=opts,
                        cfg=config(max_generations=3,resume_from_checkpoint=True))
    assert completed.evolve(TASK)==result
    assert completed_domain.calls==[]
    assert completed.replay()['replay_certificate']['passed']


def test_content_split_collision_is_rejected_before_any_provider_call(tmp_path):
    domain, llm = LayeredDomain(), CountingLLM()
    domain.contexts = {**domain.contexts,'admission':domain.evaluation_context}
    fw = layered(tmp_path, domain=domain, llm=llm)
    with pytest.raises(ValueError,match='distinct'):
        fw.evolve(TASK)
    assert domain.calls==[] and llm.calls==0 and not fw.store.path.exists()


def test_invalid_gate_identity_is_charged_but_cannot_emit_admission_receipt(tmp_path):
    domain = LayeredDomain(invalid_gate=True)
    fw = layered(tmp_path, domain=domain, cfg=config(max_generations=0))
    with pytest.raises(ValueError,match='binding'):
        fw.evolve(TASK)
    assert fw._composed.layered.gate_calls==1
    assert not records(fw,'layered_admission_receipt')
    assert not fw._composed.budget.reserves
    assert sum(fw._composed.budget.account_summary()['spent'].values())==1014
    assert not records(fw,'state_mutation')


def test_blocked_source_is_rejected_before_operator_and_evaluation(tmp_path):
    source=tmp_path/'source.txt';source.write_text('forbidden source text')
    knowledge={'ground_files':[{'path':str(source)}],'audit_files':[]}
    llm,domain=CountingLLM(),LayeredDomain()
    fw=layered(tmp_path/'run',domain=domain,llm=llm,knowledge=knowledge,
               options={'blocked_sources':[source.as_uri()]})
    with pytest.raises(ValueError,match='blocked source'):
        fw.evolve(TASK)
    assert llm.calls==0 and domain.calls==[]


def test_two_layer_mode_explicitly_reports_final_disabled(tmp_path):
    domain=LayeredDomain()
    fw=layered(tmp_path,domain=domain,options={'layers':['dev','admission']},cfg=config(max_generations=0))
    result=fw.evolve(TASK)
    assert result['reporting']['final_audit']['state']=='disabled'
    assert [split for _,split,_ in domain.calls]==['dev','admission']
