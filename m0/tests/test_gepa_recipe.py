"""GEPA C01 acceptance through the public Framework, never a replacement loop."""
import json

import pytest

from core.loop import Framework, LoopConfig
from zoo.gepa_gsm8k.domain import FrozenDataset
from zoo.gepa_gsm8k.runner import build_profile, registry_for

TASK = 'Optimize a GSM8K instruction prompt using training feedback.'


def dataset(test_answer='#### 7'):
    return FrozenDataset.from_rows({split: [
        {'id': f'{split}:{i:06d}', 'question': f'{split} question {i}',
         'answer': test_answer if split == 'test' else '#### 7'} for i in range(2)]
        for split in ('train', 'validation', 'test')})


class Fixture:
    model, supplier = 'gepa-fixture', 'offline'
    def __init__(self, child_correct=2):
        self.prompts, self.constructed = [], 0
        self.child_correct = child_correct
        self.forbidden = False
    def __call__(self, prompt):
        assert not self.forbidden, 'replay called the provider'
        self.prompts.append(prompt)
        self.last_usage = {'total_tokens': 1}
        value = json.loads(prompt)
        if 'recipe' in value:
            artifact = f'prompt-{self.constructed}'
            self.constructed += 1
            return json.dumps({'artifact': artifact, 'hypothesis': value['hypothesis']})
        index = int(value['item_id'].split(':')[-1])
        baseline = value['instruction'] == 'prompt-0'
        if value['item_id'].startswith('train:'):
            correct = index < (1 if baseline else self.child_correct)
        elif value['item_id'].startswith('validation:'):
            correct = index == (0 if baseline else 1)
        else:
            correct = True
        return '#### 7' if correct else '#### 9'


def run(path, *, data=None, provider=None, generations=1, resume=False):
    data, provider = data or dataset(), provider or Fixture()
    profile = build_profile(data, seed=0, minibatch_size=2, max_proposals=generations)
    fw = Framework.from_profile(profile, provider, data,
        LoopConfig(max_generations=generations, total_budget=100000, intent_cost=1000,
                   reeval_floor=0, resume_from_checkpoint=resume), str(path),
        component_registry=registry_for(data))
    result = fw.evolve(TASK)
    return fw, result, provider


def rows(fw, kind):
    return [r['payload'] for r in fw.store.read(kind)]


def test_g1_complementary_validation_winners_remain_parents(tmp_path):
    fw, _, _ = run(tmp_path)
    policy = fw._composed.parts['policy']
    candidates = policy.instance_frontier.checkpoint_state()['candidates']
    assert len(candidates) == 2
    assert len(fw._composed.frontier.member_ids) == 2
    assert set(policy.instance_frontier.frequencies()) == {row['id'] for row in candidates}


@pytest.mark.parametrize('correct,accepted', [(0, False), (1, False), (2, True)])
def test_g2_g3_same_training_batch_strict_improvement_and_validation_gate(tmp_path, correct, accepted):
    fw, _, provider = run(tmp_path, provider=Fixture(correct))
    pairs = rows(fw, 'paired_evaluation_decision')
    assert len(pairs) == 1 and pairs[0]['accepted'] is accepted
    calls = [json.loads(p) for p in provider.prompts if '"item_id"' in p and '"recipe"' not in p]
    train = [c for c in calls if c['item_id'].startswith('train:')]
    assert [c['item_id'] for c in train[:2]] == [c['item_id'] for c in train[2:]]
    dev = [c for c in calls if c['item_id'].startswith('validation:')]
    assert len(dev) == (4 if accepted else 2)
    assert len(rows(fw, 'materialization_completed')) == 2
    assert fw._composed.budget.state()['global']['used']['token'] == len(provider.prompts)
    assert not fw._composed.budget.state()['open_intents']
    if not accepted:
        rejected = list(fw._composed.proposals)[-1]
        assert fw._composed.evidence[rejected].eval_result.contract.binding.split_id == 'train'
        assert fw._composed.frontier.nodes[rejected].score is None
    provider.forbidden = True
    assert fw.replay(TASK)['replay_certificate']['passed']


def test_g5_reflection_contains_actual_train_rollout_and_replays_without_calls(tmp_path):
    fw, _, provider = run(tmp_path)
    reflection = [json.loads(p) for p in provider.prompts if '"recipe"' in p][1]
    instructions = '\n'.join(reflection['recipe']['instructions'])
    assert 'train:000000' in instructions and 'train:000001' in instructions
    assert '#### 9' in instructions and '#### 7' in instructions
    assert 'validation question' not in instructions and 'test question' not in instructions
    count = len(provider.prompts)
    provider.forbidden = True
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert len(provider.prompts) == count


def test_g4_frozen_test_labels_cannot_change_search(tmp_path):
    left, _, lp = run(tmp_path / 'left', data=dataset('#### 7'))
    right, _, rp = run(tmp_path / 'right', data=dataset('#### 8'))
    # Run/context references differ; compare all meaningful model inputs.
    def search(prompts):
        output = []
        for p in prompts:
            v = json.loads(p)
            if 'recipe' in v:
                output.append((v['recipe']['parent_artifacts'], v['recipe']['instructions']))
            else:
                output.append(v)
        return output
    assert search(lp.prompts) == search(rp.prompts)
    assert left._composed.manifest['assembly']['domain']['options']['dataset_identity'] != right._composed.manifest['assembly']['domain']['options']['dataset_identity']


def test_epoch_batches_have_original_ids_and_are_reproducible():
    from core.composition.gepa_recipe import epoch_batch
    ids = [f'original:{i:06d}' for i in range(8)]
    batches = [epoch_batch(ids, seed=3, size=2, iteration=i) for i in range(8)]
    assert sorted(sum(batches[:4], [])) == ids
    assert sorted(sum(batches[4:], [])) == ids
    assert batches == [epoch_batch(list(reversed(ids)), seed=3, size=2, iteration=i) for i in range(8)]


def test_final_score_changes_with_test_labels_only_after_freeze(tmp_path):
    left, lresult, lp = run(tmp_path / 'left', data=dataset('#### 7'))
    right, rresult, rp = run(tmp_path / 'right', data=dataset('#### 8'))
    assert lresult['reporting']['final_audit']['evidence']['evidence']['eval_result']['metrics']['test/score'] == 1
    assert rresult['reporting']['final_audit']['evidence']['evidence']['eval_result']['metrics']['test/score'] == 0
    for fw, provider in ((left, lp), (right, rp)):
        kinds = [r['kind'] for r in fw.store.read()]
        assert kinds.index('metric_final_frozen') > max(i for i, k in enumerate(kinds) if k == 'composed_decision')
        assert len(rows(fw, 'metric_final_completed')) == 1
        provider.forbidden = True
        assert fw.replay(TASK)['replay_certificate']['passed']


def test_resume_never_repeats_search_or_final_provider_calls(tmp_path):
    first, result, _ = run(tmp_path)
    forbidden = Fixture(); forbidden.forbidden = True
    resumed, restored, _ = run(tmp_path, provider=forbidden, resume=True)
    assert restored['best_candidate_id'] == result['best_candidate_id']
    assert restored['reporting'] == result['reporting']
    assert resumed._composed.budget.state()['global'] == first._composed.budget.state()['global']


def test_frozen_files_are_checked_during_search(tmp_path):
    import hashlib
    root = tmp_path / 'data'; root.mkdir()
    source = dataset()
    manifest = {'splits': {}}
    for split in ('train', 'validation', 'test'):
        values = source.rows(split)
        raw = ''.join(json.dumps(r) + '\n' for r in values).encode()
        (root / (split + '.jsonl')).write_bytes(raw)
        manifest['splits'][split] = {'sha256': hashlib.sha256(raw).hexdigest(),
            'count': len(values), 'first_id': values[0]['id'], 'last_id': values[-1]['id']}
    path = root / 'manifest.json'; path.write_text(json.dumps(manifest))
    data = FrozenDataset.from_manifest(path)
    class Tampering(Fixture):
        def __call__(self, prompt):
            answer = super().__call__(prompt)
            if '"item_id"' in prompt and '"recipe"' not in prompt:
                (root / 'test.jsonl').write_text('changed after freeze')
            return answer
    provider = Tampering()
    with pytest.raises(ValueError, match='frozen dataset changed'):
        run(tmp_path / 'run', data=data, provider=provider)
    assert provider.constructed == 1


def test_governed_solver_reflection_and_control_share_currency_authority(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from zoo.gepa_gsm8k.runner import governed_setup
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    fixture = Fixture()
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            content = fixture(request['messages'][0]['content'])
            body = json.dumps({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 3,
                'completion_tokens': 4, 'total_tokens': 7}, 'choices': [{'finish_reason': 'stop',
                'message': {'content': content}}]}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    ledger = CampaignBudget.create(tmp_path / 'fixture-campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    try:
        data = dataset()
        profile, registry, provider = governed_setup(data, seed=0, minibatch_size=2, max_proposals=1,
            ledger=ledger, api_key='fixture-only', base_url=f'http://127.0.0.1:{server.server_port}/v1')
        fw = Framework.from_profile(profile, provider, data, LoopConfig(max_generations=1,
            total_budget=10000000, reeval_floor=0), str(tmp_path / 'run'), component_registry=registry)
        result = fw.evolve(TASK)
        assert result['reporting']['final_audit']['state'] == 'completed'
        assert fw._composed.budget.state()['global']['used']['token'] == 7 * len(requests)
        assert not ledger.snapshot()['pending_calls']
        assert fw.replay(TASK)['replay_certificate']['passed']
        assert len(fixture.prompts) == len(requests)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_paired_plan_refuses_wrong_items_before_reflection(tmp_path, monkeypatch):
    from dataclasses import replace
    from zoo.gepa_gsm8k.domain import GSM8KDomain
    original = GSM8KDomain.evaluate
    async def changed(self, proposal, request):
        result = await original(self, proposal, request)
        if request.split_id == 'train':
            items = result.contract.items
            return replace(result, contract=replace(result.contract,
                items=(replace(items[0], item_id='replacement'), *items[1:])))
        return result
    monkeypatch.setattr(GSM8KDomain, 'evaluate', changed)
    provider = Fixture()
    with pytest.raises(ValueError, match='exact public binary training items'):
        run(tmp_path, provider=provider)
    assert provider.constructed == 1


def test_budget_stopped_finalized_run_resumes_for_reporting_only(tmp_path):
    data = dataset()
    profile = build_profile(data, seed=0, minibatch_size=2, max_proposals=1)
    for level in profile['budget']['options']['limits'].values():
        level['node'] = 1
    def build(provider, resume=False):
        return Framework.from_profile(profile, provider, data, LoopConfig(max_generations=1,
            total_budget=100000, reeval_floor=0, resume_from_checkpoint=resume), str(tmp_path),
            component_registry=registry_for(data))
    first = build(Fixture())
    result = first.evolve(TASK)
    assert result['cycles'] == 1 and result['stop_reason'] == 'insufficient global node budget'
    assert result['reporting']['final_audit']['state'] == 'completed'
    forbidden = Fixture(); forbidden.forbidden = True
    resumed = build(forbidden, resume=True)
    restored = resumed.evolve(TASK)
    assert restored['reporting'] == result['reporting']
    assert restored['ledger'] == result['ledger']
    assert not forbidden.prompts
