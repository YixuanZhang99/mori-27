"""Independent physical-authority links for external provider receipts."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.composition.provider_evidence import audit_provider_receipts, invocation_records
from core.x1.checkpoint import payload_digest
from test_governed_external_runtime import external_framework, TASK


@pytest.mark.parametrize('change', [
    {'candidate_id': 'foreign-candidate'},
    {'account': 'exploit'},
    {'operation': 'dev', 'phase': 'evaluation'},
])
def test_rehashed_external_context_cannot_relabel_physical_intent(tmp_path, change):
    framework, *_ = external_framework(tmp_path)
    framework.evolve(TASK)
    runtime = framework._composed
    rows = deepcopy(list(runtime.store.read()))
    operation_state = deepcopy(runtime.budget._rebuild()[0])
    start = next(row['payload'] for row in rows if row['kind'] == 'composed_provider_started'
                 and row['payload']['invocation']['lane'] == 'main')
    old_binding = start['binding']
    start['invocation']['external_context'].update(change)
    start['binding'] = payload_digest({'request_sha256': start['request_sha256'],
                                      'invocation': start['invocation']})
    completion = next(row['payload'] for row in rows if row['kind'] == 'composed_provider_completed'
                      and row['payload']['binding'] == old_binding)
    completion['binding'] = start['binding']
    store = SimpleNamespace(read=lambda kind=None: (row for row in rows if kind is None or row['kind'] == kind))
    for identifier, receipts in invocation_records(store).items():
        operation_state['operations'][identifier]['provider_evidence_ref'] = 'sha256:' + payload_digest(receipts)
    audit_runtime = SimpleNamespace(store=store, governed=runtime.governed, _logical_run_id=runtime._logical_run_id,
        budget=SimpleNamespace(_rebuild=lambda: (operation_state, None)))
    with pytest.raises(ValueError, match='physical'):
        audit_provider_receipts(audit_runtime, runtime.governed.sessions, runtime.governed.main_binding)
