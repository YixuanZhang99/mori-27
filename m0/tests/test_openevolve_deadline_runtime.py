"""Deadline stop must not change unrelated provider timeout semantics."""
from types import SimpleNamespace

import pytest

from core.composition.recovery import ContinuationStore


def test_unrelated_transport_timeout_uses_existing_failure_path(tmp_path):
    store = ContinuationStore(tmp_path / 'events.jsonl')
    provider = SimpleNamespace(usage_total=0, raw_provider=object(),
        current_invocation_binding={'intent_id': 'fixture'},
        external_deadline_check=lambda: None,
        external_accounting_recover=lambda *_: pytest.fail('must not recover an unrelated timeout'),
        governance_binding=lambda: {'fixture': True})
    def timeout():
        raise TimeoutError('transport')
    with pytest.raises(RuntimeError, match='provider invocation failed'):
        store.provider_call(provider, timeout, (), {})
    rows = list(store.read('composed_provider_completed'))
    assert len(rows) == 1 and rows[0]['payload']['outcome'] == 'failed'


def test_expiry_after_reservation_releases_never_started_operation(tmp_path):
    from core.executor.types import Candidate
    from core.llm import ProviderDeadlineSignal
    from test_governed_budget import budget
    controller = budget(tmp_path)
    expired = {'value': False}
    def guard():
        if expired['value']:
            raise ProviderDeadlineSignal('deadline')
    controller.install_admission_guard(guard)
    receipt = controller.reserve_operation('attempt', Candidate('attempt'), 'main', 'operator')
    assert receipt.granted
    expired['value'] = True
    with pytest.raises(ProviderDeadlineSignal):
        controller.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    assert not controller.state()['open_intents']
    assert controller._rebuild()[0]['operations'][receipt.intent_id]['status'] == 'released'
    with pytest.raises(ProviderDeadlineSignal):
        controller.reserve_operation('new', Candidate('new'), 'main', 'operator')


def test_expired_guard_replays_only_exact_durable_budget_transitions(tmp_path):
    from core.budget.types import AccountingStamp
    from core.composition.budget import HierarchicalBudget
    from core.executor.types import Candidate
    from core.llm import ProviderDeadlineSignal
    from test_governed_budget import config, governance, plan
    path = tmp_path / 'events.jsonl'
    stamp = AccountingStamp('offline', 'fixture-v1', 'tokens-v1', 'price-v1', 'today')
    original = HierarchicalBudget(config(), stamp, ContinuationStore(path), governance=governance())
    original.protect_controls(plan())
    receipt = original.reserve_operation('one', Candidate('one'), 'main', 'operator')
    original.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
    store = ContinuationStore(path)
    store.cursor = 1  # Only the original control protection is visible at restore.
    restored = HierarchicalBudget(config(), stamp, store, governance=governance())
    restored.restore_from_journal()
    def expired():
        raise ProviderDeadlineSignal('deadline')
    restored.install_admission_guard(expired)
    replayed = restored.reserve_operation('one', Candidate('one'), 'main', 'operator')
    restored.start_operation(replayed.intent_id, fingerprint=replayed.fingerprint)
    assert restored.state()['open_intents'] == ['one']
    with pytest.raises(ProviderDeadlineSignal):
        restored.reserve_operation('new', Candidate('new'), 'main', 'operator')


def test_mori_cascade_does_not_start_second_stage_after_expiry(monkeypatch, tmp_path):
    from core.composition.evaluation import MeasuredEvaluationError
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.stage import run_cascade
    from unittest.mock import Mock
    deadline = Mock()
    deadline.remaining.side_effect = [1.0, 0.0]
    stages = []
    def run(program, *, stage, timeout, **kwargs):
        stages.append((stage, timeout))
        return fake_result(program, stage, score=.6)
    monkeypatch.setattr('zoo.circle_packing.stage.run_stage', run)
    with pytest.raises(MeasuredEvaluationError) as rejected:
        run_cascade('program', runner=object(), workspace=tmp_path, timeout=60, deadline=deadline)
    assert stages == [(1, 1.0)]
    assert rejected.value.cost.eval_count == 1


def test_mori_cascade_caps_stage_to_remaining_time(monkeypatch, tmp_path):
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.stage import run_cascade
    from unittest.mock import Mock
    deadline = Mock()
    deadline.remaining.return_value = 1.5
    timeouts = []
    def run(program, *, stage, timeout, **kwargs):
        timeouts.append(timeout)
        return fake_result(program, stage, score=.4)
    monkeypatch.setattr('zoo.circle_packing.stage.run_stage', run)
    result = run_cascade('program', runner=object(), workspace=tmp_path, timeout=60, deadline=deadline)
    assert result['eval_count'] == 1 and timeouts == [1.5]


def test_recorded_provider_completion_is_not_returned_after_deadline(tmp_path):
    from core.llm import ProviderDeadlineExpired, ProviderDeadlineSignal
    path = tmp_path / 'events.jsonl'
    initial = ContinuationStore(path)
    provider = SimpleNamespace(usage_total=0, raw_provider=object(),
        current_invocation_binding={'intent_id': 'fixture'}, governance_binding=lambda: {'fixture': True})
    assert initial.provider_call(provider, lambda: 'original response', (), {}) == 'original response'
    replay = ContinuationStore(path)
    replay.cursor = 0
    def expired():
        raise ProviderDeadlineSignal('deadline')
    restored = SimpleNamespace(usage_total=0, _usage_total=0, raw_provider=object(),
        current_invocation_binding={'intent_id': 'fixture'}, governance_binding=lambda: {'fixture': True},
        external_deadline_check=expired)
    with pytest.raises(ProviderDeadlineExpired):
        replay.provider_call(restored, lambda: pytest.fail('must not invoke'), (), {})
    assert restored.usage_total == 0
