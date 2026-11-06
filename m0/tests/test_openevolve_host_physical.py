"""Host calls reuse the durable hierarchical physical budget."""
import pytest

from core.composition.budget import HierarchicalBudget
from core.composition.provider_evidence import evidence_reference
from core.x1.checkpoint import payload_digest
from test_governed_budget import STAMP, budget, config, governance


def append_receipts(store, receipt, physical, tokens=7):
    from core.composition.external_provider import GovernedCallContext, external_session_id
    identity = physical.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
    context = GovernedCallContext(schema_version=1, runtime_id='composed-v8-governed-external',
        logical_run_id='a' * 32, currency_run_id='1' * 64, campaign_id='2' * 32, policy_sha256='3' * 64,
        physical_plan_ref='sha256:' + '4' * 64, bridge_plan_ref='sha256:' + '5' * 64,
        candidate_id=identity['candidate_id'], intent_id=receipt.intent_id, physical_fingerprint=receipt.fingerprint,
        lane='main', slot_id=None, account=identity['account'], operation='operator', phase='operator', ordinal=0,
        adapter_binding_sha256='b' * 64, session_id=external_session_id('a' * 32, 'main', None, 'b' * 64),
        argument_sha256='c' * 64)
    invocation = {'schema_version': 2, 'external_context': context.to_dict(),
        'intent_id': receipt.intent_id, 'fingerprint': receipt.fingerprint,
        'lane': 'main', 'slot_id': None, 'run_id': 'a' * 32,
        'adapter_binding_sha256': 'b' * 64, 'ordinal': 0}
    request_sha = 'c' * 64
    binding = payload_digest({'request_sha256': request_sha, 'invocation': invocation})
    store.append('composed_provider_started', {'binding': binding, 'request_sha256': request_sha,
                                                'invocation': invocation})
    store.append('composed_provider_completed', {'binding': binding, 'result': 'diff', 'tokens': tokens,
        'state': None, 'observed_binding_sha256': 'b' * 64})


def test_physical_admission_and_settlement_use_original_provider_receipts(tmp_path):
    from zoo.circle_packing.host_physical import HostPhysicalAdmission
    physical = budget(tmp_path)
    host = HostPhysicalAdmission(physical)
    receipt = host.begin('a' * 32)
    assert physical.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)['status'] == 'started'
    append_receipts(physical.store, receipt, physical)
    host.settle(receipt, tokens=7)
    state = physical.audit_governance()
    assert state['physical_totals']['token'] == 7
    assert state['provider_evidence_refs'][receipt.intent_id] == evidence_reference(physical.store, receipt.intent_id)


def test_open_or_unresolved_call_blocks_new_physical_admission_after_restore(tmp_path):
    from zoo.circle_packing.host_physical import HostPhysicalAdmission
    original = budget(tmp_path)
    receipt = HostPhysicalAdmission(original).begin('a' * 32)
    restored = HierarchicalBudget(config(), STAMP, original.store, governance=governance())
    restored.restore_from_journal()
    with pytest.raises(ValueError, match='unresolved'):
        HostPhysicalAdmission(restored).begin('b' * 32)
    restored.mark_unresolved(receipt.intent_id, fingerprint=receipt.fingerprint, reason='unknown_usage')
    with pytest.raises(ValueError, match='unresolved'):
        HostPhysicalAdmission(restored).begin('c' * 32)


def test_unproven_or_changed_receipt_cannot_settle(tmp_path):
    from zoo.circle_packing.host_physical import HostPhysicalAdmission
    physical = budget(tmp_path)
    host = HostPhysicalAdmission(physical)
    receipt = host.begin('a' * 32)
    with pytest.raises(ValueError):
        host.settle(receipt, tokens=7)
    append_receipts(physical.store, receipt, physical, tokens=6)
    with pytest.raises(ValueError):
        host.settle(receipt, tokens=7)
    assert receipt.intent_id in physical.state()['open_intents']


def test_concurrent_host_admissions_leave_only_one_started(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from zoo.circle_packing.host_physical import HostPhysicalAdmission
    physical = budget(tmp_path)
    host = HostPhysicalAdmission(physical)
    def attempt(identifier):
        try:
            return host.begin(identifier)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(attempt, ('a' * 32, 'b' * 32)))
    assert sum(value is not None for value in receipts) == 1
    assert len(physical.state()['open_intents']) == 1


def test_measurement_reference_is_rejected_for_operator_settlement(tmp_path):
    from core.budget.ledger import BudgetError
    from zoo.circle_packing.host_physical import HostPhysicalAdmission
    physical = budget(tmp_path)
    receipt = HostPhysicalAdmission(physical).begin('a' * 32)
    with pytest.raises(BudgetError):
        physical.settle_operation(receipt.intent_id, {'token': 0, 'node': 1, 'eval_count': 0},
            measured_units=physical.units, fingerprint=receipt.fingerprint,
            measurement_evidence_ref='sha256:' + 'f' * 64)
    assert receipt.intent_id in physical.state()['open_intents']
