"""Frozen OR3 selection and terminal scoring through the public Framework."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from core.loop import Framework, LoopConfig

TEMPLATE = 'def priority(item, bins):\n    return -(bins - item)\n'
TASK = 'Improve the online bin packing priority using only development scores.'


def prepared(root, *, held_items=(6, 4)):
    root.mkdir(parents=True)
    manifest = {'schema_version': 1, 'notebook_sha256': '0' * 64,
        'split_rule': 'sorted instance id: first 10 dev, last 10 held_out', 'splits': {}}
    for label, items in (('dev', (6, 4)), ('held_out', held_items)):
        data = {f'{label}:{i:02}': {'capacity': 10, 'num_items': len(items), 'items': list(items)}
                for i in range(10)}
        folder = root / label; folder.mkdir()
        raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
        (folder / 'data.json').write_bytes(raw)
        manifest['splits'][label] = {'sha256': hashlib.sha256(raw).hexdigest(), 'count': 10}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return root / 'manifest.json'


class Provider:
    model, supplier = 'bestfit-fixture', 'offline'
    def __init__(self):
        self.prompts = []
        self.forbidden = False
    def __call__(self, prompt):
        assert not self.forbidden, 'recorded execution requested a model'
        self.prompts.append(json.loads(prompt))
        self.last_usage = {'total_tokens': 1}
        return json.dumps({'artifact': TEMPLATE, 'hypothesis': self.prompts[-1]['hypothesis']})


def run(path, manifest, *, provider=None, resume=False):
    from zoo.funsearch_binpacking.data import FrozenOR3
    from zoo.funsearch_binpacking.runner import build_profile, registry_for
    data = FrozenOR3.from_manifest(manifest)
    provider = provider or Provider()
    profile = build_profile(data, seed=0, max_proposals=2, call_token_bound=100)
    fw = Framework.from_profile(profile, provider, data,
        LoopConfig(max_generations=2, total_budget=1000, reeval_floor=0, resume_from_checkpoint=resume),
        str(path), component_registry=registry_for(data))
    return fw, fw.evolve(TASK), provider


def test_heldout_changes_terminal_score_without_changing_search(tmp_path, monkeypatch):
    # Fix only nondeterministic run identity so complete model inputs can be compared.
    monkeypatch.setattr('core.composition.runtime.uuid.uuid4', lambda: SimpleNamespace(hex='fixture-run'))
    left, lr, lp = run(tmp_path / 'left', prepared(tmp_path / 'data-left'))
    right, rr, rp = run(tmp_path / 'right', prepared(tmp_path / 'data-right', held_items=(7, 7)))
    def final(result):
        return result['reporting']['final_audit']['evidence']['evidence']['eval_result']
    assert final(lr)['metrics']['test/score'] == -1
    assert final(rr)['metrics']['test/score'] == -2
    assert lp.prompts == rp.prompts
    assert left._composed.incumbent == right._composed.incumbent
    for fw in (left, right):
        nodes = list(fw._composed.frontier.nodes.values())
        assert len(fw._composed.frontier.member_ids) == 3
        assert sum(n.status == 'merged' for n in nodes) == 1
        public = [r['payload'] for r in fw.store.read('funsearch_public_candidate')]
        assert all(set(row['scores']) == {f'dev:{i:02}' for i in range(10)} for row in public)
        kinds = [r['kind'] for r in fw.store.read()]
        assert kinds.index('metric_final_frozen') > max(i for i, k in enumerate(kinds) if k == 'composed_decision')


def test_resume_and_replay_do_not_repeat_completed_terminal_worker(tmp_path, monkeypatch):
    manifest = prepared(tmp_path / 'data')
    fw, result, provider = run(tmp_path / 'run', manifest)
    assert result['reporting']['final_audit']['state'] == 'completed'
    from core.tasks.funsearch_priority_sandbox import SandboxedPriority
    monkeypatch.setattr(SandboxedPriority, '__enter__', lambda _self: pytest.fail('repeated sandbox execution'))
    provider.forbidden = True
    restored, repeated, _ = run(tmp_path / 'run', manifest, provider=provider, resume=True)
    assert repeated['reporting'] == result['reporting']
    assert restored.replay(TASK)['replay_certificate']['passed']
    assert len(provider.prompts) == 3


def test_changed_frozen_file_rejected_before_provider(tmp_path):
    from zoo.funsearch_binpacking.data import FrozenOR3
    from zoo.funsearch_binpacking.runner import build_profile, registry_for
    manifest = prepared(tmp_path / 'data')
    data = FrozenOR3.from_manifest(manifest)
    profile = build_profile(data, seed=0, max_proposals=1, call_token_bound=100)
    provider = Provider()
    (manifest.parent / 'held_out' / 'data.json').write_text('{}')
    with pytest.raises(ValueError, match='frozen'):
        fw = Framework.from_profile(profile, provider, data, LoopConfig(max_generations=1),
            str(tmp_path / 'run'), component_registry=registry_for(data))
        fw.evolve(TASK)
    assert not provider.prompts


@pytest.mark.parametrize('fault', ['overlap', 'count', 'invalid_item'])
def test_manifest_rejects_invalid_partition_even_with_matching_hash(tmp_path, fault):
    from zoo.funsearch_binpacking.data import FrozenOR3
    manifest_path = prepared(tmp_path / 'data')
    manifest = json.loads(manifest_path.read_text())
    path = manifest_path.parent / 'held_out' / 'data.json'
    values = json.loads(path.read_text())
    if fault == 'overlap':
        values['dev:00'] = values.pop('held_out:00')
    elif fault == 'count':
        manifest['splits']['held_out']['count'] = 9
    else:
        values['held_out:00']['items'][0] = 11
    raw = json.dumps(values).encode(); path.write_bytes(raw)
    manifest['splits']['held_out']['sha256'] = hashlib.sha256(raw).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        FrozenOR3.from_manifest(manifest_path)


def test_final_timeout_keeps_failed_cost_without_a_score(tmp_path):
    import asyncio
    from core.composition.contracts import Proposal
    from core.executor.types import Candidate, EvalRequest, EvalStatus
    from zoo.funsearch_binpacking.data import FrozenOR3
    from zoo.funsearch_binpacking.domain import OR3Domain
    data = FrozenOR3.from_manifest(prepared(tmp_path / 'data'))
    domain = OR3Domain(data, template=TEMPLATE, timeout=1)
    proposal = Proposal(Candidate('frozen'), 'def priority(item, bins):\n    while True:\n        pass\n')
    result = asyncio.run(domain.evaluate(proposal, EvalRequest('final_audit', split_id='final_audit')))
    assert result.status is EvalStatus.FAILED_TO_RUN
    assert result.cost.eval_count == 1 and result.metrics == {}
    assert result.fidelity == result.contract.binding.split_id == 'final_audit'
