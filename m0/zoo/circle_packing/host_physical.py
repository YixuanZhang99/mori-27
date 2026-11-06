"""One-at-a-time host admission using the existing durable physical budget.

This primitive does not bind a currency bridge or enable live reference runs.
"""
from __future__ import annotations

import re

from core.composition.budget import HierarchicalBudget
from core.composition.provider_evidence import evidence_reference, invocation_records
from core.executor.types import Candidate


class HostPhysicalAdmission:
    def __init__(self, budget):
        if not isinstance(budget, HierarchicalBudget) or budget._governed is None or \
                set(budget.units) != {'token', 'node', 'eval_count'}:
            raise ValueError('host requires governed token/node/evaluation physical budget')
        if not budget.audit_governance().get('plan_ref'):
            raise ValueError('host requires protected controls before admission')
        self.budget = budget
        self._lock = budget._lock

    def begin(self, request_id):
        with self._lock:
            return self._begin(request_id)

    def _begin(self, request_id):
        if type(request_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            raise ValueError('host request requires a canonical identity')
        if self.budget.state()['open_intents']:
            raise ValueError('unresolved physical operation blocks host dispatch')
        self.budget.pre_call_check()
        candidate = Candidate('host-' + request_id)
        receipt = self.budget.reserve_operation('host:' + request_id, candidate, 'host', 'operator')
        if not receipt.granted:
            raise ValueError('host physical budget refused admission')
        self.budget.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
        return receipt

    def settle(self, receipt, *, tokens):
        with self._lock:
            self._settle(receipt, tokens=tokens)

    def _settle(self, receipt, *, tokens):
        if type(tokens) is not int or tokens < 0:
            raise ValueError('settlement requires measured nonnegative tokens')
        identity = self.budget.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
        rows = invocation_records(self.budget.store).get(receipt.intent_id, [])
        if len(rows) != 2 or [row['kind'] for row in rows] != [
                'composed_provider_started', 'composed_provider_completed']:
            raise ValueError('settlement requires the original completed provider receipt')
        start, done = (row['payload'] for row in rows)
        invocation = start['invocation']
        context = invocation.get('external_context')
        if invocation.get('schema_version') != 2 or type(context) is not dict or \
                invocation['fingerprint'] != receipt.fingerprint or invocation['lane'] != 'main' or \
                invocation['ordinal'] != 0 or context['candidate_id'] != identity['candidate_id'] or \
                context['account'] != identity['account'] or context['operation'] != 'operator' or \
                done['tokens'] != tokens or done['observed_binding_sha256'] != invocation['adapter_binding_sha256']:
            raise ValueError('provider receipt differs from the physical reservation')
        self.budget.settle_operation(receipt.intent_id, {'token': tokens, 'node': 1, 'eval_count': 0},
            measured_units=self.budget.units, fingerprint=receipt.fingerprint,
            provider_evidence_ref=evidence_reference(self.budget.store, receipt.intent_id))
