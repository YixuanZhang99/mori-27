"""Continuation drafts do not grant authority or modify first-pair evidence."""
import copy

import pytest

from zoo.mle_bench_lite.cny_budget import CampaignBudget


def inventory(tmp_path):
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    ref = 'sha256:' + 'a' * 64
    ledger.freeze_circle_pilot(ref, 'sha256:' + 'b' * 64, 2700,
                               require_runtime=True, require_single_run=True)
    ledger.freeze_circle_runtime(ref, 'sha256:' + 'b' * 64, 'sha256:' + 'c' * 64, 'd' * 64)
    before = ledger.snapshot()
    value = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    # Synthetic audit identity; the builder is pure and never writes the ledger.
    value['claims'] = {'mori-0': {}, 'vendor-0': {}}
    value['first_pair_audit'] = {'schema_version': 1, 'plan_ref': ref,
        'mori_run_id': 'e' * 64, 'reference_run_id': 'f' * 64,
        'mori_rows_sha256': '1' * 64, 'reference_rows_sha256': '2' * 64,
        'reference_bundle_sha256': '3' * 64, 'replay_input_sha256': '4' * 64,
        'proof_sha256': '5' * 64}
    return ledger, before, value


def build(value, **changes):
    from zoo.circle_packing.continuation_draft import build_continuation_draft
    args = {'experiment_id': 'circle-v2', 'source_commit': '6' * 40,
            'dependency_lock_sha256': '7' * 64, 'method_changes': ['disable thinking in both arms']}
    args.update(changes)
    return build_continuation_draft(value, **args)


def test_draft_is_versioned_namespaced_and_does_not_authorize_work(tmp_path):
    ledger, before, value = inventory(tmp_path)
    original = copy.deepcopy(value)
    draft = build(value)
    assert draft['schema_version'] == 3 and draft['status'] == 'draft_not_executable'
    assert draft['reasoning_effort'] == 'none' and draft['predecessor_head'] == before['journal_head']
    assert draft['predecessor_audit']['proof_sha256'] == '5' * 64
    assert [c['cell_id'] for c in draft['cells']] == [f'circle-v2--{arm}-{seed}' for seed in range(3) for arm in ('vendor', 'mori')]
    assert all(c['status'] == 'unrun' for c in draft['cells'])
    assert len(draft['draft_sha256']) == 64 and draft == build(value)
    draft['predecessor_audit']['plan_ref'] = 'changed'
    assert value == original and ledger.snapshot() == before
    assert build(value, experiment_id='circle-v3')['draft_sha256'] != build(value)['draft_sha256']


@pytest.mark.parametrize('change', ['no_audit', 'audit_plan', 'audit_digest', 'no_runtime', 'no_pilot',
                                    'pending', 'reserved', 'protected', 'breach', 'disabled', 'audit_private', 'runtime_mismatch'])
def test_incomplete_or_nonquiescent_original_is_rejected(tmp_path, change):
    ledger, before, value = inventory(tmp_path)
    if change == 'no_audit': value['first_pair_audit'] = None
    elif change == 'audit_plan': value['first_pair_audit']['plan_ref'] = 'sha256:' + '0' * 64
    elif change == 'audit_digest': value['first_pair_audit']['proof_sha256'] = 'bad'
    elif change == 'audit_private': value['first_pair_audit']['result'] = 'private content'
    elif change == 'runtime_mismatch': value['runtime']['tree_ref'] = 'sha256:' + '0' * 64
    elif change == 'no_runtime': value['runtime'] = None
    elif change == 'no_pilot': value['pilot'] = None
    elif change == 'pending': value['currency']['pending_calls'] = ['unknown']
    elif change == 'reserved': value['currency']['reserved_micro_cny'] = 1
    elif change == 'protected': value['currency']['protected_micro_cny'] = 1
    elif change == 'breach': value['currency']['protection_breaches'] = ['bad']
    else: value['governance_enabled'] = False
    with pytest.raises(ValueError): build(value)
    assert ledger.snapshot() == before


@pytest.mark.parametrize('changes', [
    {'experiment_id': ''}, {'experiment_id': 'bad/name'}, {'experiment_id': 'x' * 110},
    {'source_commit': 'bad'}, {'dependency_lock_sha256': 'bad'},
    {'method_changes': []}, {'method_changes': ['']}, {'method_changes': [42]},
])
def test_invalid_new_experiment_fields_are_rejected(tmp_path, changes):
    ledger, before, value = inventory(tmp_path)
    with pytest.raises(ValueError): build(value, **changes)
    assert ledger.snapshot() == before
