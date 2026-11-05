"""Adversarial regressions from the independent governed-runtime review."""
import json
from dataclasses import replace

import pytest

from core.composition.recovery import ContinuationStore
from core.executor.types import EvalStatus
from test_composed_budget import Domain, TASK
from test_governed_runtime import FreshProvider, governed


class KnownFailureProvider(FreshProvider):
    def __call__(self, prompt):
        super().__call__(prompt)
        raise RuntimeError('known measured failure')


def test_known_failure_terminal_crash_adopts_once_without_another_provider_call(tmp_path, monkeypatch):
    class Crash(BaseException):
        pass

    write = ContinuationStore._write
    crashed = False
    def fail_after_terminal(self, record):
        nonlocal crashed
        write(self, record)
        if not crashed and record['kind'] == 'governed_operator_outcome' \
                and record['payload']['failure_type'] is not None:
            crashed = True
            raise Crash()
    monkeypatch.setattr(ContinuationStore, '_write', fail_after_terminal)
    fw, original, _, _, _ = governed(tmp_path, provider_factory=KnownFailureProvider)
    with pytest.raises(Crash):
        fw.evolve(TASK)
    assert original[0].calls == 1
    resumed, fresh, _, _, _ = governed(tmp_path, resume=True, provider_factory=KnownFailureProvider)
    resumed.evolve(TASK)
    assert [provider.calls for provider in fresh] == [0, 1, 1]
    report = resumed.inspect()['governance']
    assert report['failed'] == 3 and report['unresolved'] == 0
    assert report['budget']['accounts']['control']['token'] == 15


def test_terminal_status_cannot_upgrade_a_failed_control_on_resume(tmp_path):
    class FailedDomain(Domain):
        async def evaluate(self, proposal, request):
            result = await super().evaluate(proposal, request)
            return replace(result, status=EvalStatus.FAILED_TO_RUN, metrics={})

    fw, _, _, _, _ = governed(tmp_path, domain_factory=FailedDomain)
    fw.evolve(TASK)
    assert fw.inspect()['governance']['failed'] == 3
    path = tmp_path / 'x1.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        if row['kind'] == 'governed_control_terminal':
            row['payload']['status'] = 'evaluated'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    resumed, _, _, _, _ = governed(tmp_path, resume=True, domain_factory=FailedDomain)
    with pytest.raises(ValueError, match='control|governed|terminal|status'):
        resumed.evolve(TASK)


@pytest.mark.parametrize('mutation', [
    'missing_evidence', 'proposal', 'parents', 'candidate_cycle', 'start_cycle',
    'duplicate_start', 'physical_evidence', 'missing_operator_outcome',
    'failure_type', 'extra_field'])
def test_terminal_audit_rejects_cross_record_semantic_forgeries(tmp_path, mutation):
    from core.composition.governance_audit import audit_terminals
    fw, _, _, _, _ = governed(tmp_path)
    fw.evolve(TASK)
    runtime = fw._composed
    rows = runtime.store.rows
    terminal = next(row['payload'] for row in rows if row['kind'] == 'governed_control_terminal')
    slot = terminal['slot_id']
    if mutation == 'missing_evidence':
        terminal['evidence'] = None
    elif mutation == 'proposal':
        terminal['proposal']['artifact'] = 'forged artifact'
    elif mutation == 'parents':
        terminal['proposal']['candidate']['parents'] = ['main-leak']
    elif mutation == 'candidate_cycle':
        terminal['proposal']['candidate']['created_cycle'] = 9
    elif mutation == 'start_cycle':
        next(row['payload'] for row in rows if row['kind'] == 'governed_control_started')['main_cycles'] = 9
    elif mutation == 'duplicate_start':
        rows.append(next(row for row in rows if row['kind'] == 'governed_control_started'))
    elif mutation == 'physical_evidence':
        for row in rows:
            if row['kind'] == 'composed_physical_evidence' and row['payload']['intent_id'] == f'control:{slot}:evaluation':
                row['payload']['request']['seed_set'] = [99]
    elif mutation == 'missing_operator_outcome':
        rows[:] = [row for row in rows if not (row['kind'] == 'governed_operator_outcome'
            and row['payload']['intent_id'] == f'control:{slot}:operator')]
    elif mutation == 'failure_type':
        terminal['failure_type'] = 'OperatorFailure'
    else:
        terminal['unvalidated'] = True
    runtime.store.cursor = len(rows)
    with pytest.raises(ValueError, match='control|governed|terminal|evidence|proposal|schedule|settlement'):
        audit_terminals(runtime, runtime.governed.plan, runtime.governed.sessions)


def test_terminal_audit_matches_real_completed_and_drained_slots(tmp_path):
    from core.composition.governance_audit import audit_terminals
    for name, tokens in [('normal', 10000), ('drained', 38)]:
        fw, _, _, _, _ = governed(tmp_path / name, main_tokens=tokens)
        fw.evolve(TASK)
        runtime = fw._composed
        result = audit_terminals(runtime, runtime.governed.plan, runtime.governed.sessions)
        assert len(result) == 3
        assert {item['status'] for item in result.values()} == {'evaluated'}
