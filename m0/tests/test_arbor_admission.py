"""The Arbor trunk follows held-out admission, with only verdicts reaching planning."""
import json
from dataclasses import replace

import pytest

from core.executor.types import EvalStatus
from test_arbor_recipe import ArborProvider, TASK, assembly
from test_composed_budget import Domain
from test_configured_construction import build, records


class GateDomain(Domain):
    def __init__(self, *, child=.2, failed=False, final=.01):
        super().__init__()
        self.child, self.failed, self.final = child, failed, final

    async def evaluate(self, proposal, request):
        result = await super().evaluate(proposal, request)
        if request.split_id == 'admission':
            if self.failed and proposal.candidate.created_cycle == 1:
                return replace(result, status=EvalStatus.FAILED_TO_RUN, metrics={},
                               text_feedback='PRIVATE_GATE_FAILURE')
            return replace(result, metrics={'dev/score': .8 if proposal.candidate.created_cycle == 0 else self.child},
                           text_feedback='PRIVATE_GATE_REASON')
        if request.split_id == 'final_audit':
            return replace(result, metrics={'dev/score': self.final}, text_feedback='PRIVATE_FINAL')
        return result


def run_gate(path, **kwargs):
    configured = assembly()
    configured['admission']['options'].update(kwargs.pop('options', {}))
    provider, domain = ArborProvider(), GateDomain(**kwargs)
    fw = build(path, assembly=configured, provider=provider, domain=domain, generations=2)
    result = fw.evolve(TASK)
    return fw, provider, domain, result


def test_high_dev_low_admission_keeps_trunk_and_only_exports_verdict(tmp_path):
    fw, provider, _, result = run_gate(tmp_path)
    evidence = records(fw, 'composed_evidence')
    root = evidence[0]['proposal']['candidate']['id']
    assert result['best_candidate_id'] == root
    assert records(fw, 'arbor_selected')[2]['execution_base']['candidate_id'] == root
    decisions = records(fw, 'arbor_admission_verdict')
    assert [row['admit'] for row in decisions] == [True, False, False]
    assert all(set(row) == {'candidate_id', 'admit', 'receipt_id'} for row in decisions)
    planning = [json.loads(p) for p in provider.prompts if json.loads(p).get('kind') == 'arbor_ideation']
    assert decisions[1] in [item['body'] for item in planning[2]['context']['retrieval']['content']['memory']
                            if 'admit' in item['body']]
    assert all('PRIVATE_GATE' not in p and 'PRIVATE_FINAL' not in p for p in provider.prompts)


@pytest.mark.parametrize('child,margin', [(.8, 0), (.85, .1)])
def test_tie_and_margin_reject(tmp_path, child, margin):
    fw, _, _, result = run_gate(tmp_path, child=child, options={'margin': margin})
    assert result['best_candidate_id'] == records(fw, 'composed_evidence')[0]['proposal']['candidate']['id']


def test_gate_call_cap_counts_baseline_and_failures(tmp_path):
    fw, _, domain, result = run_gate(tmp_path, failed=True, options={'call_budget': 2})
    assert len([c for c in domain.calls if c['request']['split_id'] == 'admission']) == 2
    assert [row['admit'] for row in records(fw, 'arbor_admission_verdict')] == [True, False, False]
    assert result['best_candidate_id'] == records(fw, 'composed_evidence')[0]['proposal']['candidate']['id']


def test_final_changes_do_not_change_search_or_memory(tmp_path):
    first, provider, _, _ = run_gate(tmp_path / 'one', final=.123)
    other, changed_provider, _, _ = run_gate(tmp_path / 'two', final=12345)
    # Receipt hashes include original measured timings. Normalize only receipt
    # identities and timing; preserve all model-visible scores/text and decisions.
    import re
    def semantic(value):
        if isinstance(value, str):
            return re.sub(r'[0-9a-f]{64}', '<digest>', value)
        if isinstance(value, dict):
            return {key: semantic(item) for key, item in value.items()
                    if key not in {'wall_seconds', 'used_chars', 'run_id', 'source_run_id'}}
        if isinstance(value, list):
            result = [semantic(item) for item in value]
            return sorted(result, key=lambda item: json.dumps(item, sort_keys=True))
        return value
    assert [semantic(json.loads(p)) for p in provider.prompts] == [
        semantic(json.loads(p)) for p in changed_provider.prompts]
    assert semantic(records(first, 'arbor_selected')) == semantic(records(other, 'arbor_selected'))
    assert semantic(first._composed.memory.checkpoint_state()['entries']) == semantic(
        other._composed.memory.checkpoint_state()['entries'])
