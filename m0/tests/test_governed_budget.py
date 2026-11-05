"""Physical control capacity and account attribution share one durable authority."""
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest

from core.budget.ledger import BudgetError
from core.budget.types import AccountingStamp
from core.composition.budget import HierarchicalBudget, JOURNAL_KIND, _hash
from core.executor.types import Candidate, EvalRequest
from core.x1.store import AppendOnlyStore

STAMP = AccountingStamp('offline', 'fixture-v1', 'tokens-v1', 'price-v1', 'today')
ACCOUNTS = {'explore', 'exploit', 'reeval', 'control', 'repair', 'handoff', 'overhead'}


def config():
    return {'limits': {level: {'token': 100, 'node': 10, 'eval_count': 10}
                       for level in ('global', 'direction', 'candidate')},
            'reservation': {'token': 10, 'node': 1, 'eval_count': 1},
            'reservation_modes': {'operator': {'token': 'remaining'}},
            'fidelity_rungs': [{'fidelity': 'cheap'}, {'fidelity': 'full'}]}


def governance():
    return {'schema_version': 1, 'controls': {
        'after_main_cycles': [0, 2], 'seed': 1,
        'provider': {'name': 'fresh', 'options': {}},
        'domain': {'name': 'fresh', 'options': {}},
        'operator': {'name': 'draft', 'options': {}},
        'request': {'fidelity': 'control', 'split_id': 'dev', 'seed_set': [1]},
        'reservations': {'operator': {'token': 20, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 5, 'node': 0, 'eval_count': 1}}}}


def plan():
    controls = governance()['controls']
    return {'plan_ref': 'frozen-plan', 'slots': [
        {'slot_id': f'slot{i}', 'after_main_cycles': after,
         'request': controls['request'], 'reservations': controls['reservations']}
        for i, after in enumerate(controls['after_main_cycles'])]}


def budget(tmp_path, *, options=None, protect=True):
    result = HierarchicalBudget(options or config(), STAMP,
        AppendOnlyStore(tmp_path / 'budget.jsonl'), governance=governance())
    if protect:
        result.protect_controls(plan())
    return result


def settle(controller, receipt, costs=None):
    controller.settle_operation(receipt.intent_id, costs or receipt.amounts,
        measured_units=controller.units, fingerprint=receipt.fingerprint)


def test_remaining_main_quote_cannot_consume_future_control_capacity(tmp_path):
    controller = budget(tmp_path)
    receipt = controller.reserve_operation('main', Candidate('main'), 'main', 'operator')
    assert receipt.amounts == {'token': 50, 'node': 1, 'eval_count': 1}
    assert controller.state()['global']['reserved']['token'] == 50
    audit = controller.audit_governance()
    assert audit['protected'] == {'token': 50, 'node': 2, 'eval_count': 2}
    assert audit['physical_totals'] == {'token': 0, 'node': 0, 'eval_count': 0}


def test_control_conversion_is_atomic_and_uses_frozen_request_not_main_rung(tmp_path):
    controller = budget(tmp_path)
    candidate = Candidate('control0')
    op = controller.reserve_control_operation('slot0', 'operator', candidate)
    assert op.amounts == {'token': 20, 'node': 1, 'eval_count': 0}
    assert controller.audit_governance()['protected']['token'] == 30
    settle(controller, op, {'token': 15, 'node': 1, 'eval_count': 0})
    ev = controller.reserve_control_operation('slot0', 'evaluation', candidate)
    assert ev.granted
    settle(controller, ev)
    assert controller.allocate(Candidate('next'), direction_id='control:slot0').fidelity == 'cheap'
    audit = controller.audit_governance()
    assert audit['accounts']['control'] == {'token': 20, 'node': 1, 'eval_count': 1}
    assert audit['protected']['token'] == 25
    assert audit['slots']['slot0']['status'] == 'evaluated'
    with pytest.raises(BudgetError):
        controller.reserve_control_operation('slot1', 'operator', Candidate('bad', parents=['main']))


def test_accounts_are_settlement_projections_and_original_failure_attribution(tmp_path):
    controller = budget(tmp_path)
    cases = [('planning', Candidate('planner'), None, 'overhead'),
             ('dev', Candidate('fresh'), EvalRequest('cheap'), 'explore'),
             ('dev', Candidate('child', parents=['fresh']), EvalRequest('cheap'), 'exploit'),
             ('dev_baseline', Candidate('baseline'), EvalRequest('dev'), 'reeval')]
    for index, (phase, candidate, request, account) in enumerate(cases):
        receipt = controller.reserve_operation(str(index), candidate, candidate.id, phase, request=request)
        assert receipt.granted
        settle(controller, receipt, {'token': index + 1, 'node': 0, 'eval_count': 0})
    audit = controller.audit_governance()
    assert set(audit['accounts']) == ACCOUNTS
    assert {name: values['token'] for name, values in audit['accounts'].items()} == {
        'explore': 2, 'exploit': 3, 'reeval': 4, 'overhead': 1,
        'control': 0, 'repair': 0, 'handoff': 0}
    assert audit['physical_totals']['token'] == 10
    assert audit['reconciled'] and audit['coverage_complete']


def test_known_failed_slot_cancels_only_unused_capacity_and_recovers(tmp_path):
    controller = budget(tmp_path)
    op = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    settle(controller, op, {'token': 7, 'node': 1, 'eval_count': 0})
    controller.cancel_control_slot('slot0', 'known proposal failure')
    audit = controller.audit_governance()
    assert audit['protected']['token'] == 25
    assert audit['slots']['slot0']['status'] == 'failed'
    assert audit['accounts']['control']['token'] == 7
    restored = HierarchicalBudget(config(), STAMP, controller.store, governance=governance())
    restored.restore_state(controller.checkpoint_state())
    before = controller.store.path.read_bytes()
    restored.protect_controls(plan())
    assert restored.audit_governance() == audit
    assert controller.store.path.read_bytes() == before
    other = plan()
    other['plan_ref'] = 'changed'
    with pytest.raises(BudgetError):
        restored.protect_controls(other)


@pytest.mark.parametrize('mode', ['unknown', 'overrun'])
def test_unresolved_or_overrun_stops_both_lanes_and_invalidates_guarantee(tmp_path, mode):
    controller = budget(tmp_path)
    op = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    if mode == 'unknown':
        controller.mark_unresolved(op.intent_id, fingerprint=op.fingerprint, reason='unknown')
    else:
        settle(controller, op, {'token': 21, 'node': 1, 'eval_count': 0})
    assert not controller.reserve_operation('main', Candidate('main'), 'main', 'operator').granted
    assert not controller.reserve_control_operation('slot1', 'operator', Candidate('c1')).granted
    assert not controller.audit_governance()['protection_valid']
    with pytest.raises(BudgetError):
        controller.cancel_control_slot('slot0', 'hide unresolved')


def test_impossible_protection_is_rejected_before_journal_write(tmp_path):
    options = config()
    options['limits']['global']['token'] = 49
    controller = budget(tmp_path, options=options, protect=False)
    with pytest.raises(BudgetError):
        controller.protect_controls(plan())
    assert not controller.store.path.exists()


def test_control_and_main_competing_reservations_cannot_steal_holdback(tmp_path):
    controller = budget(tmp_path)
    barrier = threading.Barrier(2)
    def reserve(lane):
        barrier.wait()
        if lane == 'main':
            return controller.reserve_operation('main', Candidate('main'), 'main', 'operator')
        return controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(reserve, ['main', 'control']))
    assert all(receipt.granted for receipt in receipts)
    assert receipts[0].amounts['token'] == 50
    assert controller.state()['global']['reserved']['token'] == 70
    assert controller.audit_governance()['protected']['token'] == 30


@pytest.mark.parametrize('field,value', [('account', 'repair'), ('control_slot', 'slot1'), ('lane', 'main')])
def test_rehashed_attribution_tamper_is_rejected_by_live_audit(tmp_path, field, value):
    controller = budget(tmp_path)
    controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    rows = list(controller.store.read())
    event = rows[-1]['payload']
    event['data']['intent'][field] = value
    event['data']['fingerprint'] = _hash(event['data']['intent'])
    event['event_ref'] = _hash({key: value for key, value in event.items() if key != 'event_ref'})
    controller.store.path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(BudgetError):
        controller.audit_governance()


def test_governance_cannot_adopt_legacy_journal(tmp_path):
    store = AppendOnlyStore(tmp_path / 'budget.jsonl')
    legacy = HierarchicalBudget(config(), STAMP, store)
    legacy.reserve_operation('main', Candidate('main'), 'main', 'planning')
    controller = HierarchicalBudget(config(), STAMP, store, governance=governance())
    with pytest.raises(BudgetError):
        controller.restore_from_journal()


def full_plan():
    value = plan()
    value.update(schema_version=1, task_desc='initial task', initial_context={'summary': 'initial'})
    value['initial_task_sha256'] = _hash(value['task_desc'])
    value['initial_context_sha256'] = _hash(value['initial_context'])
    for index, slot in enumerate(value['slots']):
        slot['slot_id'] = f'control-{index:04d}'
        slot['seed'] = 1 + index
        for field in ('provider', 'domain', 'operator'):
            slot[field] = governance()['controls'][field]
    value['plan_ref'] = _hash({key: item for key, item in value.items() if key != 'plan_ref'})
    return value


@pytest.mark.parametrize('mutation', ['context', 'seed', 'slot_id', 'request', 'reservation'])
def test_full_plan_rejects_rehashed_inconsistent_frozen_inputs(tmp_path, mutation):
    controller = budget(tmp_path, protect=False)
    value = full_plan()
    if mutation == 'context':
        value['initial_context']['summary'] = 'poison'
    elif mutation == 'seed':
        value['slots'][0]['seed'] = 4
    elif mutation == 'slot_id':
        value['slots'][0]['slot_id'] = 'replacement'
    elif mutation == 'request':
        value['slots'][0]['request']['seed_set'] = [3]
    else:
        value['slots'][0]['reservations']['operator']['token'] = 19
    value['plan_ref'] = _hash({key: item for key, item in value.items() if key != 'plan_ref'})
    with pytest.raises(BudgetError):
        controller.protect_controls(value)
    assert not controller.store.path.exists()


def test_full_plan_round_trip_and_live_truncation_detection(tmp_path):
    controller = budget(tmp_path, protect=False)
    controller.protect_controls(full_plan())
    controller.reserve_control_operation('control-0000', 'operator', Candidate('c0'))
    restored = HierarchicalBudget(config(), STAMP, controller.store, governance=governance())
    restored.restore_state(controller.checkpoint_state())
    assert restored.audit_governance() == controller.audit_governance()
    rows = list(controller.store.read())
    controller.store.path.write_text(json.dumps(rows[0]) + '\n')
    with pytest.raises(BudgetError):
        controller.audit_governance()


def test_repeated_main_dev_evaluation_is_reevaluation_account(tmp_path):
    controller = budget(tmp_path)
    candidate = Candidate('main')
    for identifier, expected_fidelity in [('first', 'cheap'), ('second', 'full')]:
        request = controller.allocate(candidate, direction_id='main')
        assert request.fidelity == expected_fidelity
        receipt = controller.reserve_operation(identifier, candidate, 'main', 'dev', request=request)
        settle(controller, receipt, {'token': 3, 'node': 0, 'eval_count': 1})
    audit = controller.audit_governance()
    assert audit['accounts']['explore']['token'] == 3
    assert audit['accounts']['reeval']['token'] == 3


@pytest.mark.parametrize('unit', ['token', 'node', 'eval_count', 'wallclock', 'gpu_hours', 'usd'])
def test_every_physical_unit_is_protected_at_global_level(tmp_path, unit):
    quantity = 1 if unit in {'token', 'node', 'eval_count'} else 0.1
    options = {'limits': {level: {unit: quantity * 4} for level in ('global', 'direction', 'candidate')},
               'reservation': {unit: quantity}, 'fidelity_rungs': [{'fidelity': 'dev'}]}
    gov = governance()
    gov['controls']['reservations'] = {phase: {unit: quantity} for phase in ('operator', 'evaluation')}
    value = plan()
    for slot in value['slots']:
        slot['reservations'] = gov['controls']['reservations']
    controller = HierarchicalBudget(options, STAMP, AppendOnlyStore(tmp_path / 'budget.jsonl'), governance=gov)
    controller.protect_controls(value)
    assert not controller.reserve_operation('main', Candidate('main'), 'main', 'planning').granted
    assert controller.reserve_control_operation('slot0', 'operator', Candidate('c0')).granted
    assert not controller.should_continue('main')
    assert controller.converged().rule == 'global_budget_exhausted'


def test_soft_main_view_hides_controls_and_keeps_initial_capacity_deduction(tmp_path):
    controller = budget(tmp_path)
    before = controller.main_state()
    assert before['limits']['global'] == {'token': 50, 'node': 8, 'eval_count': 8}
    assert before['global']['remaining'] == {'token': 50, 'node': 8, 'eval_count': 8}
    assert before['directions'] == before['candidates'] == {}
    assert 'governance' not in before
    op = controller.reserve_control_operation('slot0', 'operator', Candidate('control-secret'))
    settle(controller, op, {'token': 1, 'node': 1, 'eval_count': 0})
    controller.cancel_control_slot('slot0', 'failed private sample')
    assert controller.main_state() == before
    receipt = controller.reserve_operation('main', Candidate('visible'), 'visible-direction', 'planning')
    settle(controller, receipt, {'token': 3, 'node': 0, 'eval_count': 0})
    view = controller.main_account_summary()
    assert view['global']['used']['token'] == 3
    assert view['global']['remaining']['token'] == 47
    assert set(view['directions']) == {'visible-direction'}
    assert set(view['candidates']) == {'visible'}
    assert 'control-secret' not in json.dumps(view)
    assert 'failed private sample' not in json.dumps(view)
    view['limits']['global']['token'] = 999
    assert controller.main_state()['limits']['global']['token'] == 50


def test_fresh_budget_protect_cannot_append_duplicate_plan_to_existing_journal(tmp_path):
    controller = budget(tmp_path)
    before = controller.store.path.read_bytes()
    fresh = HierarchicalBudget(config(), STAMP, controller.store, governance=governance())
    with pytest.raises(BudgetError):
        fresh.protect_controls(plan())
    assert controller.store.path.read_bytes() == before


def test_legacy_main_views_preserve_original_summary(tmp_path):
    controller = HierarchicalBudget(config(), STAMP, AppendOnlyStore(tmp_path / 'legacy.jsonl'))
    receipt = controller.reserve_operation('main', Candidate('main'), 'main', 'planning')
    settle(controller, receipt)
    assert controller.main_state() == controller.state()
    assert controller.main_account_summary() == controller.account_summary()


def test_unused_control_capacity_never_changes_main_remaining_quote_or_admission(tmp_path):
    quotes = []
    for index, cost in enumerate((1, 20)):
        controller = budget(tmp_path / str(index))
        op = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
        settle(controller, op, {'token': cost, 'node': 1, 'eval_count': 0})
        controller.cancel_control_slot('slot0', 'known failure')
        receipt = controller.reserve_operation('main', Candidate('main'), 'main', 'operator')
        quotes.append(receipt.amounts['token'])
        settle(controller, receipt, {'token': 50, 'node': 1, 'eval_count': 0})
        assert not controller.reserve_operation('after', Candidate('after'), 'after', 'planning').granted
        assert not controller.should_continue('after')
        assert controller.converged().rule == 'global_budget_exhausted'
        assert controller.reserve_control_operation('slot1', 'operator', Candidate('c1')).granted
    assert quotes == [50, 50]


def test_coherently_rehashed_control_as_main_cannot_reconstruct(tmp_path):
    controller = budget(tmp_path)
    controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    rows = list(controller.store.read())
    event = rows[-1]['payload']
    intent = event['data']['intent']
    intent.update(lane='main', control_slot=None, account='explore',
                  amounts={'token': 50, 'node': 1, 'eval_count': 1})
    event['data']['fingerprint'] = _hash(intent)
    event['event_ref'] = _hash({key: value for key, value in event.items() if key != 'event_ref'})
    controller.store.path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    restored = HierarchicalBudget(config(), STAMP, controller.store, governance=governance())
    with pytest.raises(BudgetError):
        restored.restore_from_journal()


def test_governed_settlement_seals_provider_evidence_in_journal_and_checkpoint(tmp_path):
    controller = budget(tmp_path)
    receipt = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    reference = _hash([{'kind': 'provider_completed', 'tokens': 5}])
    controller.settle_operation(receipt.intent_id, {'token': 5, 'node': 1, 'eval_count': 0},
        measured_units=controller.units, fingerprint=receipt.fingerprint, provider_evidence_ref=reference)
    event = list(controller.store.read(JOURNAL_KIND))[-1]['payload']
    assert event['data']['provider_evidence_ref'] == reference
    assert controller.audit_governance()['provider_evidence_refs'] == {receipt.intent_id: reference}
    checkpoint = controller.checkpoint_state()
    assert checkpoint['state']['governance']['provider_evidence_refs'] == {receipt.intent_id: reference}
    restored = HierarchicalBudget(config(), STAMP, controller.store, governance=governance())
    restored.restore_state(checkpoint)
    assert restored.audit_governance()['provider_evidence_refs'] == {receipt.intent_id: reference}


def test_default_empty_provider_proof_is_governed_only(tmp_path):
    controller = budget(tmp_path / 'governed')
    receipt = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    settle(controller, receipt)
    event = list(controller.store.read(JOURNAL_KIND))[-1]['payload']
    assert event['data']['provider_evidence_ref'] == 'sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945'
    legacy = HierarchicalBudget(config(), STAMP, AppendOnlyStore(tmp_path / 'legacy.jsonl'))
    receipt = legacy.reserve_operation('main', Candidate('main'), 'main', 'planning')
    settle(legacy, receipt)
    assert set(list(legacy.store.read(JOURNAL_KIND))[-1]['payload']['data']) == {
        'intent_id', 'fingerprint', 'actual_costs', 'measured_units'}


@pytest.mark.parametrize('reference', ['', 'a' * 64, 'sha256:' + 'A' * 64, 'sha256:' + 'a' * 63, 42, {}])
def test_invalid_provider_evidence_ref_keeps_reservation_open(tmp_path, reference):
    controller = budget(tmp_path)
    receipt = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    before = controller.store.path.read_bytes()
    with pytest.raises(BudgetError):
        controller.settle_operation(receipt.intent_id, receipt.amounts,
            measured_units=controller.units, fingerprint=receipt.fingerprint, provider_evidence_ref=reference)
    assert controller.store.path.read_bytes() == before
    assert controller.state()['open_intents'] == [receipt.intent_id]


def test_rehashed_provider_proof_cannot_adopt_original_checkpoint_state(tmp_path):
    controller = budget(tmp_path)
    receipt = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    controller.settle_operation(receipt.intent_id, receipt.amounts,
        measured_units=controller.units, fingerprint=receipt.fingerprint,
        provider_evidence_ref=_hash([{'tokens': 20}]))
    checkpoint = controller.checkpoint_state()
    rows = list(controller.store.read())
    event = rows[-1]['payload']
    event['data']['provider_evidence_ref'] = _hash([])
    event['event_ref'] = _hash({key: value for key, value in event.items() if key != 'event_ref'})
    controller.store.path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    # Even a rewritten head cannot make the original state omit its receipt proof.
    checkpoint['head'] = event['event_ref']
    restored = HierarchicalBudget(config(), STAMP, controller.store, governance=governance())
    with pytest.raises(BudgetError, match='checkpoint'):
        restored.restore_state(checkpoint)


def test_legacy_settlement_cannot_silently_drop_provider_proof(tmp_path):
    legacy = HierarchicalBudget(config(), STAMP, AppendOnlyStore(tmp_path / 'legacy.jsonl'))
    receipt = legacy.reserve_operation('main', Candidate('main'), 'main', 'planning')
    with pytest.raises(BudgetError, match='governance'):
        legacy.settle_operation(receipt.intent_id, receipt.amounts,
            measured_units=legacy.units, fingerprint=receipt.fingerprint, provider_evidence_ref=_hash([]))


def test_known_bound_breach_halts_both_lanes_without_losing_actual_bill(tmp_path):
    controller = budget(tmp_path)
    receipt = controller.reserve_operation('main', Candidate('main'), 'main', 'planning')
    assert receipt.amounts['token'] == 10
    settle(controller, receipt, {'token': 6, 'node': 0, 'eval_count': 0})
    assert controller.audit_governance()['protection_valid']
    controller.invalidate_protection(receipt.intent_id, 'provider_call_bound_exceeded')
    before = controller.store.path.read_bytes()
    controller.invalidate_protection(receipt.intent_id, 'provider_call_bound_exceeded')
    assert controller.store.path.read_bytes() == before
    assert not controller.reserve_operation('next', Candidate('next'), 'next', 'planning').granted
    assert not controller.reserve_control_operation('slot0', 'operator', Candidate('c0')).granted
    with pytest.raises(BudgetError):
        controller.pre_call_check()
    audit = controller.audit_governance()
    assert not audit['protection_valid']
    assert audit['physical_totals']['token'] == 6
    assert audit['protected']['token'] == 50
    assert audit['accounts']['overhead']['token'] == 6
    assert audit['protection_breaches'] == {'main': ['provider_call_bound_exceeded']}
    restored = HierarchicalBudget(config(), STAMP, controller.store, governance=governance())
    restored.restore_state(controller.checkpoint_state())
    assert restored.audit_governance() == audit
    assert not restored.reserve_control_operation('slot1', 'operator', Candidate('c1')).granted


def test_protection_invalidation_requires_a_settled_governed_intent(tmp_path):
    controller = budget(tmp_path)
    receipt = controller.reserve_control_operation('slot0', 'operator', Candidate('c0'))
    before = controller.store.path.read_bytes()
    with pytest.raises(BudgetError, match='settled'):
        controller.invalidate_protection(receipt.intent_id, 'provider_binding_drift')
    with pytest.raises(BudgetError, match='settled'):
        controller.invalidate_protection('unknown', 'provider_binding_drift')
    assert controller.store.path.read_bytes() == before
    legacy = HierarchicalBudget(config(), STAMP, AppendOnlyStore(tmp_path / 'legacy.jsonl'))
    receipt = legacy.reserve_operation('main', Candidate('main'), 'main', 'planning')
    settle(legacy, receipt)
    with pytest.raises(BudgetError, match='governance'):
        legacy.invalidate_protection(receipt.intent_id, 'provider_binding_drift')


@pytest.mark.parametrize('reason', ['', ' ', ' padded', 'padded ', False, {}])
def test_protection_breach_reason_is_canonical_nonempty_text(tmp_path, reason):
    controller = budget(tmp_path)
    receipt = controller.reserve_operation('main', Candidate('main'), 'main', 'planning')
    settle(controller, receipt)
    before = controller.store.path.read_bytes()
    with pytest.raises(BudgetError):
        controller.invalidate_protection(receipt.intent_id, reason)
    assert controller.store.path.read_bytes() == before
