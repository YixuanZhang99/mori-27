"""Audit recorded reference provider receipts without a key or live calls."""
import json

from core.budget.types import AccountingStamp
from core.composition.budget import HierarchicalBudget
from core.composition.external_provider import ExternalRunContext
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.host_runtime import reference_budget_config
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView


def audit_reference_currency(bundle, *, rows, expected_head, expected_plan_ref, plan, seed):
    """Rebuild a pinned reference currency transcript and compare all receipts."""
    if type(bundle) is not dict or type(rows) is not list or expected_head is None:
        raise ValueError('reference currency audit requires pinned recorded evidence')
    try:
        bundle = json.loads(json.dumps(bundle, ensure_ascii=False, allow_nan=False))
        rows = json.loads(json.dumps(rows, ensure_ascii=False, allow_nan=False))
        prepared, ready = bundle['preparation'], bundle['ready']
        run_id, physical_ref = ready['authority_binding']['currency_run_id'], ready['physical_plan_ref']
        view = RecordedCurrencyView(bundle['currency_evidence'], expected_run_id=run_id,
                                    expected_plan_ref=physical_ref, expected_head=expected_head)
        if not view._pinned_head or expected_plan_ref != 'sha256:' + plan['draft_sha256'] or \
                payload_digest({key: value for key, value in plan.items() if key != 'draft_sha256'}) != plan['draft_sha256'] or \
                view.run_deadline_binding(run_id)['plan_ref'] != expected_plan_ref or \
                view.run_deadline_binding(run_id)['cell_id'] != f'vendor-{seed}':
            raise ValueError('reference currency audit differs from its original cell')
        options, stamp, governance = reference_budget_config(plan, view.manifest_binding(), seed=seed)
        class ReadOnlyRows:
            def read(self, kind=None):
                return (row for row in rows if kind is None or row.get('kind') == kind)
        store = ReadOnlyRows()
        budget = HierarchicalBudget(options, AccountingStamp(**stamp), store, governance=governance)
        def forbidden(*args, **kwargs):
            raise AssertionError('reference recorded audit attempted live work')
        context = ExternalRunContext(**prepared['run'], mode='recorded', recorded_bundle=bundle, store=store,
            physical_identity_lookup=budget.invocation_identity,
            provider_sessions={'main': forbidden, **{key: forbidden for key in prepared['run']['control_provider_bindings']}})
        bridge = CNYInvocationBridge(None, recorded_only=True, recorded_reference=True)
        bridge.bind_run(context)
        audit = bridge.audit()
        currency = view.audit_run(run_id, physical_ref)
        if audit['unknown_cost_calls'] or not audit['protection_valid'] or audit['integrity_violations'] or \
                currency['pending_calls'] or currency['outstanding_micro_cny'] or currency['reserved_micro_cny']:
            raise ValueError('reference currency audit found unresolved or invalid calls')
        return {'schema_version': 1, 'scope': 'anchored_reference_currency_receipts', 'performance_claim': False,
                'run_id': run_id, 'invocations': audit['invocations'],
                'settled_upper_bound_micro_cny': currency['settled_upper_bound_micro_cny'], 'invoice_verified': False}
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('invalid reference currency audit evidence') from error
