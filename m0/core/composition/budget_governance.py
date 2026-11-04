"""Governed projections and future capacity in the physical budget journal.

This helper owns no journal or lock. Its owner commits every transition through
HierarchicalBudget, including the single-step obligation-to-reservation change.
"""
from dataclasses import asdict
from decimal import Decimal

from core.budget.ledger import BudgetError
from core.composition.contracts import json_copy
from core.executor.types import EvalRequest

ACCOUNTS = ('explore', 'exploit', 'reeval', 'control', 'repair', 'handoff', 'overhead')


class ControlProtection:
    def __init__(self, owner, governance):
        self.owner = owner
        self.config = json_copy(governance, label='governance')
        if type(self.config) is not dict or set(self.config) != {'schema_version', 'controls'} \
                or self.config['schema_version'] != 1 or type(self.config['controls']) is not dict:
            raise BudgetError('invalid governance configuration')

    def validate_plan(self, plan):
        from core.composition.budget_contracts import _basket, _text, _request, _hash
        plan = json_copy(plan, label='control plan')
        required = {'plan_ref', 'slots'}
        allowed = required | {'schema_version', 'initial_task_sha256', 'initial_context_sha256',
                              'initial_context', 'task_desc'}
        if type(plan) is not dict or not required.issubset(plan) or set(plan) - allowed:
            raise BudgetError('invalid frozen control plan')
        _text(plan['plan_ref'], 'control plan reference')
        full = 'schema_version' in plan
        if full:
            if set(plan) != allowed or type(plan['schema_version']) is not int or plan['schema_version'] != 1 \
                    or plan['initial_task_sha256'] != _hash(plan['task_desc']) \
                    or plan['initial_context_sha256'] != _hash(plan['initial_context']) \
                    or plan['plan_ref'] != _hash({key: value for key, value in plan.items() if key != 'plan_ref'}):
                raise BudgetError('frozen control plan identity or context mismatch')
        elif set(plan) != required:
            raise BudgetError('control plan metadata requires its versioned full binding')
        controls = self.config['controls']
        if type(plan['slots']) is not list or len(plan['slots']) != len(controls['after_main_cycles']):
            raise BudgetError('control plan schedule differs from governance')
        ids = set()
        for index, (slot, after) in enumerate(zip(plan['slots'], controls['after_main_cycles'])):
            required_slot = {'slot_id', 'after_main_cycles', 'request', 'reservations'}
            if type(slot) is not dict or not required_slot.issubset(slot) \
                    or set(slot) - (required_slot | {'seed', 'provider', 'domain', 'operator'}):
                raise BudgetError('invalid frozen control slot')
            _text(slot['slot_id'], 'control slot identity')
            if slot['slot_id'] in ids or type(slot['after_main_cycles']) is not int \
                    or slot['after_main_cycles'] != after:
                raise BudgetError('control slot identities or schedule differ')
            ids.add(slot['slot_id'])
            if full and (set(slot) != required_slot | {'seed', 'provider', 'domain', 'operator'}
                         or slot['slot_id'] != f'control-{index:04d}'
                         or type(slot['seed']) is not int or slot['seed'] != controls['seed'] + index):
                raise BudgetError('frozen control slot identity or seed differs from schedule')
            request = _request(slot['request'])
            if request.resume_from is not None or asdict(request) != asdict(_request(controls['request'])):
                raise BudgetError('control request differs from frozen governance')
            if type(slot['reservations']) is not dict or set(slot['reservations']) != {'operator', 'evaluation'}:
                raise BudgetError('control slot requires both phase reservations')
            for phase in ('operator', 'evaluation'):
                basket = _basket(slot['reservations'][phase], 'control reservation', units=self.owner.units)
                if basket != controls['reservations'][phase]:
                    raise BudgetError('control reservation differs from frozen governance')
                for level in ('direction', 'candidate'):
                    if any(self.owner._decimal(basket[unit]) > self.owner._decimal(limit)
                           for unit, limit in self.owner.options['limits'][level].items()):
                        raise BudgetError('control phase cannot fit scoped budget')
            # Both phases use one candidate and one control direction.
            for level in ('direction', 'candidate'):
                if any(sum(self.owner._decimal(slot['reservations'][phase][unit])
                           for phase in ('operator', 'evaluation')) > self.owner._decimal(limit)
                       for unit, limit in self.owner.options['limits'][level].items()):
                    raise BudgetError('control slot cannot fit scoped budget')
            for field in ('provider', 'domain', 'operator'):
                if field in slot and slot[field] != controls[field]:
                    raise BudgetError('control component differs from frozen governance')
        return plan

    def protect(self, state, plan):
        plan = self.validate_plan(plan)
        if 'control_plan' in state or state['operations'] or state['observations']:
            raise BudgetError('control protection must be frozen before operations')
        state['control_plan'] = plan
        state['control_slots'] = {slot['slot_id']: {
            'phases': {'operator': 'protected', 'evaluation': 'protected'},
            'candidate_id': None, 'reason': None} for slot in plan['slots']}
        protected = self.protected(state)
        if any(protected[unit] > self.owner._decimal(limit)
               for unit, limit in self.owner.options['limits']['global'].items()):
            raise BudgetError('insufficient global capacity for protected controls')

    def protected(self, state):
        values = {unit: Decimal(0) for unit in self.owner.units}
        for slot in state.get('control_plan', {}).get('slots', []):
            live = state['control_slots'][slot['slot_id']]
            for phase, status in live['phases'].items():
                if status == 'protected':
                    for unit, amount in slot['reservations'][phase].items():
                        values[unit] += self.owner._decimal(amount)
        return values

    def slot(self, state, identifier):
        if type(identifier) is not str:
            raise BudgetError('control slot must be a frozen identity')
        for slot in state.get('control_plan', {}).get('slots', []):
            if slot['slot_id'] == identifier:
                return slot, state['control_slots'][identifier]
        raise BudgetError('unknown or unprotected control slot')

    def bind(self, state, intent, lane, control_slot):
        if 'control_plan' not in state:
            raise BudgetError('controls must be protected before any operation')
        if lane == 'main':
            if control_slot is not None:
                raise BudgetError('main operation cannot name a control slot')
            if intent['intent_id'].startswith('control:') or intent['direction_id'].startswith('control:'):
                raise BudgetError('main operation cannot use the control identity namespace')
            if intent['operation'] == 'planning':
                account = 'overhead'
            elif intent['operation'] in {'operator', 'dev'}:
                repeated = intent['operation'] == 'dev' and any(
                    op['intent'].get('lane') == 'main' and op['intent']['operation'] == 'dev'
                    and op['intent']['candidate']['id'] == intent['candidate']['id']
                    and op['status'] != 'released' for op in state['operations'].values())
                account = 'reeval' if repeated else ('exploit' if intent['candidate']['parents'] else 'explore')
            else:
                account = 'reeval'
        elif lane == 'control':
            slot, live = self.slot(state, control_slot)
            if intent['operation'] not in {'operator', 'dev'} or intent['candidate']['parents']:
                raise BudgetError('controls require parentless proposal and frozen dev evaluation')
            phase = 'operator' if intent['operation'] == 'operator' else 'evaluation'
            if intent['intent_id'] != f'control:{control_slot}:{phase}' \
                    or intent['direction_id'] != f'control:{control_slot}':
                raise BudgetError('control operation identity differs from frozen slot')
            if live['phases'][phase] != 'protected' or live['reason'] is not None:
                raise BudgetError('control phase is already consumed or cancelled')
            if phase == 'evaluation':
                op = state['operations'].get(live['phases']['operator'])
                if op is None or op['status'] != 'settled':
                    raise BudgetError('control evaluation requires settled proposal')
                if intent['request'] != asdict(EvalRequest(**slot['request'])):
                    raise BudgetError('control evaluation request differs from frozen request')
            if live['candidate_id'] is not None and live['candidate_id'] != intent['candidate']['id']:
                raise BudgetError('control candidate differs from original slot')
            intent['amounts'] = json_copy(slot['reservations'][phase])
            account = 'control'
        else:
            raise BudgetError('unknown governance lane')
        intent.update(lane=lane, control_slot=control_slot, account=account)
        return intent

    def convert(self, state, intent):
        if intent['lane'] != 'control':
            return
        _, live = self.slot(state, intent['control_slot'])
        phase = 'operator' if intent['operation'] == 'operator' else 'evaluation'
        live['phases'][phase] = intent['intent_id']
        live['candidate_id'] = intent['candidate']['id']

    def cancel(self, state, slot_id, reason):
        from core.composition.budget_contracts import _text
        _text(reason, 'control cancellation reason')
        _, live = self.slot(state, slot_id)
        if state['halt_reasons'] or any(op['status'] == 'unresolved' for op in state['operations'].values()):
            raise BudgetError('cannot cancel obligations during unresolved usage or overrun')
        if live['reason'] is not None:
            raise BudgetError('control slot already cancelled')
        for value in live['phases'].values():
            if value in state['operations'] and state['operations'][value]['status'] not in {'settled', 'released'}:
                raise BudgetError('cannot cancel a control slot with an open operation')
        live['reason'] = reason
        for phase, value in live['phases'].items():
            if value == 'protected':
                live['phases'][phase] = 'cancelled'

    def audit(self, state):
        accounts = {name: {unit: Decimal(0) for unit in self.owner.units} for name in ACCOUNTS}
        unresolved, open_intents = [], []
        for identifier, operation in state['operations'].items():
            if operation['status'] == 'settled':
                for unit, cost in operation['actual_costs'].items():
                    accounts[operation['intent']['account']][unit] += self.owner._decimal(cost)
            elif operation['status'] in {'reserved', 'started', 'unresolved'}:
                open_intents.append(identifier)
                if operation['status'] in {'started', 'unresolved'}:
                    unresolved.append(identifier)
        used, _ = self.owner._totals(state)
        slots = {}
        for identifier, live in state.get('control_slots', {}).items():
            phases = {phase: (state['operations'][value]['status'] if value in state['operations'] else value)
                      for phase, value in live['phases'].items()}
            status = ('failed' if live['reason'] is not None else
                      'evaluated' if phases['evaluation'] == 'settled' else
                      'proposed' if phases['operator'] == 'settled' else 'pending')
            if any(value in {'started', 'unresolved'} for value in phases.values()):
                status = 'unresolved'
            slots[identifier] = {'status': status, 'phases': phases,
                                 'intent_ids': json_copy(live['phases']),
                                 'candidate_id': live['candidate_id'], 'reason': live['reason']}
        numeric = lambda basket: {unit: self.owner._numeric(unit, value) for unit, value in basket.items()}
        return {'schema_version': 1, 'plan_ref': state.get('control_plan', {}).get('plan_ref'),
                'accounts': {name: numeric(basket) for name, basket in accounts.items()},
                'physical_totals': numeric(used), 'protected': numeric(self.protected(state)),
                'provider_evidence_refs': {identifier: operation['provider_evidence_ref']
                    for identifier, operation in state['operations'].items() if operation['status'] == 'settled'},
                'slots': slots, 'unresolved_intents': sorted(unresolved), 'open_intents': sorted(open_intents),
                'halt_reasons': list(state['halt_reasons']), 'coverage_complete': not open_intents,
                'protection_breaches': json_copy(state.get('protection_breaches', {})),
                'reconciled': all(sum(basket[unit] for basket in accounts.values()) == used[unit]
                                  for unit in self.owner.units),
                'protection_valid': 'control_plan' in state and not unresolved and not state['halt_reasons']}
