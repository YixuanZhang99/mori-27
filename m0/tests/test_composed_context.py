"""Actual M5/M6 feedback through Framework, including isolation and recovery."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from core.composition.defaults import GreedyPolicy, composed_profile, default_registry
from core.executor.types import EvalStatus
from core.policy.types import MutationOp
from core.x1.checkpoint import RunCheckpoint
from test_composed_runtime import TASK, CountingLLM, config, framework, records
from test_composed_evaluation import NativeDomain


class LessonDomain(NativeDomain):
    def __init__(self, fail_first=False):
        super().__init__()
        self.fail_first = fail_first

    async def evaluate(self, proposal, request):
        result = await super().evaluate(proposal, request)
        failed = self.fail_first and proposal.candidate.created_cycle == 0
        return replace(result, status=EvalStatus.FAILED_TO_RUN if failed else EvalStatus.OK,
                       metrics={} if failed else result.metrics,
                       text_feedback='ADD_HINT_7' if proposal.candidate.created_cycle == 0 else 'learned')


def profile(*, research=False, memory=None, knowledge=None):
    value = composed_profile(mode='research' if research else 'benchmark')
    value['domain'] = {'name': 'native'}
    value['memory'] = {'name': 'scoped', 'options': memory or {}}
    if knowledge is not None:
        value['knowledge'] = {'name': 'local_files', 'options': knowledge}
    return value


def local_sources(path, ground_text='ADD_HINT_7', audit_text='AUDIT_PRIVATE_CANARY'):
    path.mkdir(parents=True, exist_ok=True)
    ground, audit = path / 'ground.txt', path / 'audit.txt'
    ground.write_text(ground_text)
    audit.write_text(audit_text)
    return {'ground_files': [{'path': str(ground)}], 'audit_files': [{'path': str(audit)}]}


def run(path, *, assembly=None, domain=None, llm=None, cfg=None, registry=None):
    return framework(path, profile=assembly or profile(), evaluator=domain or LessonDomain(),
                     llm=llm, cfg=cfg or config(max_generations=1), registry=registry)


def test_failed_nonparent_memory_changes_next_draft_input_and_artifact(tmp_path):
    assembly = profile(memory={'context_scope': 'run', 'trust_floor': 'ungated', 'max_chars': 3000})
    assembly['operators'] = [{'name': 'draft'}]
    llm = CountingLLM()
    fw = run(tmp_path, assembly=assembly, domain=LessonDomain(fail_first=True), llm=llm)
    result = fw.evolve(TASK)
    evidence = records(fw, 'composed_evidence')
    assert evidence[0]['evidence']['eval_result']['status'] == 'failed_to_run'
    assert evidence[1]['proposal']['candidate']['parents'] == []
    assert 'ADD_HINT_7' not in llm.prompts[0] and 'ADD_HINT_7' in llm.prompts[1]
    assert 'hint_7' in result['best_prompt']
    packs = records(fw, 'composed_context')
    assert packs[0]['context']['memory'] == []
    assert packs[1]['context']['memory'][0]['body'] == 'ADD_HINT_7'
    assert all(row['used_chars'] <= row['limit_chars'] for row in records(fw, 'context_pack'))
    assert evidence[1]['proposal']['candidate']['context_pack_ref'] == packs[1]['context_ref']
    assert fw.replay()['replay_certificate']['passed']


def test_ground_sources_change_actual_candidate_but_audit_text_never_reaches_search(tmp_path):
    sources = local_sources(tmp_path / 'sources')
    llm = CountingLLM()
    fw = run(tmp_path / 'run', assembly=profile(research=True, knowledge=sources),
             llm=llm, cfg=config(max_generations=1))
    result = fw.evolve(TASK)
    assert 'hint_7' in result['best_prompt']
    assert all('ADD_HINT_7' in prompt for prompt in llm.prompts)
    assert 'AUDIT_PRIVATE_CANARY' not in repr(llm.prompts)
    events = records(fw, 'fetch_ledger')
    assert {event['lane'] for event in events} == {'ground', 'audit'}
    assert len(records(fw, 'composed_knowledge_audit')) == 2
    assert 'AUDIT_PRIVATE_CANARY' not in json.dumps(fw._composed.memory.checkpoint_state())
    assert sum(result['ledger']['spent'].values()) == 2014
    assert fw.replay()['replay_certificate']['passed']


def test_benchmark_rejects_knowledge_before_any_factory_or_file_read(tmp_path):
    llm, domain, calls = CountingLLM(), LessonDomain(), []
    registry = default_registry()
    registry.register('provider', 'spy', lambda ctx, opts: calls.append('provider') or llm)
    assembly = profile(knowledge={'ground_files': [{'path': '/missing/ground'}], 'audit_files': []})
    assembly['provider'] = {'name': 'spy'}
    with pytest.raises(ValueError, match='benchmark'):
        run(tmp_path, assembly=assembly, llm=llm, domain=domain, registry=registry)
    assert calls == [] and llm.calls == domain.calls == 0
    assert not (tmp_path / 'x1.jsonl').exists()


def test_independent_runs_have_distinct_scopes_and_do_not_inherit_memory(tmp_path):
    first = run(tmp_path / 'one', cfg=config(max_generations=0))
    second = run(tmp_path / 'two', cfg=config(max_generations=0))
    first.evolve(TASK)
    second.evolve(TASK)
    assert first._composed.memory.context.run_id != second._composed.memory.context.run_id
    assert first._composed.memory.context.domain_id == second._composed.memory.context.domain_id
    assert records(second, 'composed_context')[0]['context']['memory'] == []


def exported_source(path):
    source = run(path, assembly=profile(memory={'export_on_finish': True}), cfg=config(max_generations=0))
    result = source.evolve(TASK)
    exported = result['memory_export']
    return source, {'path': str(path / exported['relative_path']), 'sha256': exported['sha256']}


def test_explicit_memory_export_import_changes_next_run_and_completed_resume_is_idempotent(tmp_path):
    source, snapshot = exported_source(tmp_path / 'source')
    before = Path(snapshot['path']).read_bytes()
    llm = CountingLLM()
    target = run(tmp_path / 'target', assembly=profile(memory={'imports': [snapshot], 'include_imported': True}),
                 llm=llm, cfg=config(max_generations=0))
    target.evolve(TASK)
    assert 'ADD_HINT_7' in llm.prompts[0]
    assert records(target, 'composed_context')[0]['context']['memory'][0]['id'].startswith('import:')
    resumed = run(tmp_path / 'source', assembly=profile(memory={'export_on_finish': True}),
                  cfg=config(max_generations=0, resume_from_checkpoint=True))
    assert resumed.evolve(TASK)['memory_export'] == source.inspect()['memory_export']
    assert Path(snapshot['path']).read_bytes() == before
    assert resumed.replay()['replay_certificate']['passed']
    assert target.replay()['replay_certificate']['passed']


def test_export_to_knowledge_ingest_then_scoped_retrieval_is_a_separate_store(tmp_path):
    knowledge = local_sources(tmp_path / 'sources', ground_text='neutral source')
    knowledge['ingest_on_finish'] = True
    source = run(tmp_path / 'source', assembly=profile(research=True, knowledge=knowledge),
                 cfg=config(max_generations=0))
    result = source.evolve(TASK)
    assert len(records(source, 'knowledge_ingest')) == 1
    assert len(source._composed.parts['knowledge'].records) == 1
    snapshot = {'path': str(tmp_path / 'source' / result['memory_export']['relative_path']),
                'sha256': result['memory_export']['sha256']}
    target_knowledge = {**knowledge, 'ingest_on_finish': False, 'memory_imports': [snapshot]}
    llm = CountingLLM()
    target = run(tmp_path / 'target', assembly=profile(research=True, knowledge=target_knowledge),
                 llm=llm, cfg=config(max_generations=0))
    target.evolve(TASK)
    pack = records(target, 'composed_context')[0]['context']
    assert pack['memory'] == []
    assert any(item['digest_id'].startswith('knowledge:') for item in pack['grounding'])
    assert 'ADD_HINT_7' in llm.prompts[0]
    assert target.replay()['replay_certificate']['passed']
    assert source.replay()['replay_certificate']['passed']


@pytest.mark.parametrize('defect', ['hash', 'task', 'dataset'])
def test_unauthorized_import_fails_before_paid_calls_and_journal(tmp_path, defect):
    _, snapshot = exported_source(tmp_path / 'source')
    domain, llm = LessonDomain(), CountingLLM()
    if defect == 'hash':
        snapshot['sha256'] = 'sha256:' + 'f' * 64
    if defect == 'dataset':
        domain.evaluation_context = 'sha256:' + 'e' * 64
    fw = run(tmp_path / 'target', assembly=profile(memory={'imports': [snapshot], 'include_imported': True}),
             domain=domain, llm=llm)
    with pytest.raises(ValueError):
        fw.evolve('different task' if defect == 'task' else TASK)
    assert domain.calls == llm.calls == 0
    assert not fw.store.path.exists()


def test_changed_ground_file_rejects_resume_without_paid_calls_or_journal(tmp_path):
    sources = local_sources(tmp_path / 'sources')
    assembly = profile(research=True, knowledge=sources)
    fw = run(tmp_path / 'run', assembly=assembly, cfg=config(stop_after_generation=0))
    fw.evolve(TASK)
    Path(sources['ground_files'][0]['path']).write_text('different opened content')
    llm, domain = CountingLLM(), LessonDomain()
    resumed = run(tmp_path / 'run', assembly=assembly, llm=llm, domain=domain,
                  cfg=config(resume_from_checkpoint=True))
    before = resumed.store.path.read_bytes()
    with pytest.raises(ValueError, match='manifest'):
        resumed.evolve(TASK)
    assert llm.calls == domain.calls == 0
    assert resumed.store.path.read_bytes() == before


def test_policy_cannot_forge_cross_scope_memory_or_receipt(tmp_path):
    class ForgingPolicy(GreedyPolicy):
        async def absorb(self, evidence):
            mutations = await super().absorb(evidence)
            for mutation in mutations:
                if mutation.op is MutationOp.WRITE_MEMORY:
                    mutation.fields['entry'].provenance.evidence_refs = ['sha256:' + 'f' * 64]
                    mutation.fields['entry'].scope = 'global'
            return mutations
    assembly, registry = profile(), default_registry()
    assembly['policy'] = {'name': 'forge'}
    registry.register('policy', 'forge', lambda ctx, opts: ForgingPolicy(ctx.scope_context))
    fw = run(tmp_path, assembly=assembly, registry=registry, cfg=config(max_generations=0))
    with pytest.raises(ValueError, match='memory source or scope'):
        fw.evolve(TASK)
    assert fw._composed.memory.entries == {}
    assert not records(fw, 'composed_decision')
    assert records(fw, 'composed_cycle_failed')[0]['known_tokens'] == 1007


@pytest.mark.parametrize('kind', ['skill', 'operator'])
def test_component_cannot_mutate_authoritative_context_in_place(tmp_path, kind):
    from core.composition.defaults import PromptOperator
    class MutatingSkill:
        def apply(self, request):
            request.context['retrieval']['query'] = 'forged context'
            return request
    class MutatingOperator(PromptOperator):
        async def propose(self, request):
            proposal = await super().propose(request)
            request.context['retrieval']['query'] = 'forged context'
            return proposal
    assembly, registry, llm = profile(), default_registry(), CountingLLM()
    if kind == 'skill':
        registry.register('skill', 'mutating', lambda ctx, opts: MutatingSkill())
        assembly['skills'] = [{'name': 'mutating'}]
    else:
        registry.register('operator', 'mutating', lambda ctx, opts: MutatingOperator(ctx.llm, 'draft'))
        assembly['operators'] = [{'name': 'mutating'}]
    fw = run(tmp_path, assembly=assembly, llm=llm, registry=registry, cfg=config(max_generations=0))
    with pytest.raises(ValueError, match='authoritative retrieval context'):
        fw.evolve(TASK)
    assert llm.calls == (0 if kind == 'skill' else 1)
    assert not records(fw, 'composed_evidence')
    assert records(fw, 'composed_context')[0]['context']['query'] == TASK
    assert not fw._composed.budget.reserves


def test_changed_export_artifact_rejects_resume_before_paid_work(tmp_path):
    _, snapshot = exported_source(tmp_path)
    Path(snapshot['path']).write_text('{}')
    llm, domain = CountingLLM(), LessonDomain()
    resumed = run(tmp_path, assembly=profile(memory={'export_on_finish': True}), llm=llm, domain=domain,
                  cfg=config(max_generations=0, resume_from_checkpoint=True))
    before = resumed.store.path.read_bytes()
    with pytest.raises(ValueError, match='export artifact'):
        resumed.evolve(TASK)
    assert llm.calls == domain.calls == 0 and resumed.store.path.read_bytes() == before


def test_identical_evaluation_in_another_run_cannot_rebind_imported_receipt(tmp_path):
    class ConstantLLM:
        def __call__(self, prompt):
            self.last_usage = {'total_tokens': 2}
            return 'unchanged artifact'
    source = run(tmp_path / 'one', assembly=profile(memory={'export_on_finish': True}),
                 llm=ConstantLLM(), cfg=config(max_generations=0))
    exported = source.evolve(TASK)['memory_export']
    snapshot = {'path': str(tmp_path / 'one' / exported['relative_path']), 'sha256': exported['sha256']}
    target = run(tmp_path / 'two', assembly=profile(memory={'imports': [snapshot], 'include_imported': True}),
                 llm=ConstantLLM(), cfg=config(max_generations=0))
    target.evolve(TASK)
    old, new = records(source, 'composed_evidence')[0], records(target, 'composed_evidence')[0]
    assert old['evidence'] == new['evidence']
    assert old['evidence_ref'] != new['evidence_ref']
    assert len(target._composed.memory.bindings) == 2
