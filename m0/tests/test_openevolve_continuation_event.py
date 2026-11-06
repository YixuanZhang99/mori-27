"""Version events cannot authorize real campaigns or reinterpret old history."""
import copy

import pytest

from test_openevolve_continuation_draft import inventory
from zoo.circle_packing.continuation_draft import build_continuation_draft
from zoo.mle_bench_lite.cny_budget import _circle_audit_identity, _reduce_governance


def setup_state(tmp_path):
    ledger, before, inv = inventory(tmp_path)
    proof = {key: value for key, value in inv['first_pair_audit'].items() if key != 'proof_sha256'}
    proof['result'] = {'fixture': True}
    inv['first_pair_audit'] = _circle_audit_identity(proof)
    draft = build_continuation_draft(inv, experiment_id='circle-v2', source_commit='6' * 40,
        dependency_lock_sha256='7' * 64, method_changes=['disable thinking in both arms'])
    with ledger._transaction() as (_db, policy, state):
        pass
    governance = state['governance']
    governance['first_pair_audit'] = proof
    governance['cell_claims'] = copy.deepcopy(inv['claims'])
    event = {'kind': 'bind_circle_continuation', 'schema_version': 2,
             'previous_head': before['journal_head'], 'draft': draft,
             'tree_ref': 'sha256:' + '8' * 64, 'runtime_ref': 'sha256:' + '9' * 64,
             'python_sha256': 'a' * 64, 'runtime_manifest_sha256': 'b' * 64}
    return policy, state, event


def reduce(policy, state, event):
    return _reduce_governance(event, policy, state['governance'], state['operations'], state['pending'],
                              state['spent'], seq=state['seq'], previous=state['hash'])


def test_fixture_event_keeps_original_identity_and_creates_no_cell(tmp_path):
    policy, state, event = setup_state(tmp_path)
    old = copy.deepcopy(state['governance'])
    assert reduce(policy, state, event) == (None, 0)
    bound = state['governance']['circle_continuations']['circle-v2']
    assert bound['draft'] == event['draft'] and bound['tree_ref'] == event['tree_ref']
    for key in ('circle_pilot', 'circle_runtime', 'first_pair_audit', 'cell_claims', 'runs'):
        assert state['governance'][key] == old[key]
    with pytest.raises(ValueError): reduce(policy, state, event)


@pytest.mark.parametrize('damage', ['stale', 'draft', 'source', 'runtime', 'python', 'manifest',
                                     'pending', 'protected', 'breach', 'nonfixture', 'proof', 'receipt'])
def test_fixture_event_rejects_stale_tampered_or_unsafe_state(tmp_path, damage):
    policy, state, event = setup_state(tmp_path)
    if damage == 'stale': event['previous_head']['sha256'] = '0' * 64
    elif damage == 'draft': event['draft']['reasoning_effort'] = 'low'
    elif damage == 'source': event['tree_ref'] = 'bad'
    elif damage == 'runtime': event['runtime_ref'] = 'bad'
    elif damage == 'python': event['python_sha256'] = 'bad'
    elif damage == 'manifest': event['runtime_manifest_sha256'] = 'bad'
    elif damage == 'receipt': event['artifact_verification_sha256'] = '0' * 64
    elif damage == 'pending': state['pending'] = 'unresolved'
    elif damage == 'protected': state['governance']['runs']['fake'] = {'obligations': [
        {'status': 'pending', 'bound': {'reserved_micro_cny': 1}}]}
    elif damage == 'breach': state['governance']['breaches'] = ['bad']
    elif damage == 'nonfixture': state['governance']['fixture_campaign'] = False
    else: state['governance']['first_pair_audit']['result'] = {'fixture': 'changed'}
    before = copy.deepcopy(state['governance'])
    with pytest.raises(ValueError): reduce(policy, state, event)
    assert state['governance'] == before


def fixture_pair_ledger(tmp_path):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    from zoo.circle_packing.pilot_plan import build_draft_plan
    original_plan = build_draft_plan(ledger.manifest_binding(), source_commit='6' * 40, dependency_lock_sha256='7' * 64)
    ref = 'sha256:' + original_plan['draft_sha256']
    tree = 'sha256:' + 'b' * 64
    ledger.freeze_circle_pilot(ref, tree, 2700, require_runtime=True, require_single_run=True)
    ledger.freeze_circle_runtime(ref, tree, 'sha256:' + 'c' * 64, 'd' * 64)
    mori, vendor = '1' * 64, '2' * 64
    mc, vc = '3' * 64, '4' * 64
    ledger.claim_cell_deadline('mori-0', ref, mc, seconds=2700)
    ledger.claim_cell_deadline('vendor-0', ref, vc, seconds=2700)
    ledger.claim_cell_worker('mori-0', mc, '5' * 64)
    ledger.claim_reference_host('vendor-0', vc, '6' * 64)
    ledger.claim_reference_authority('vendor-0', vc, '7' * 64, vendor, 'sha256:' + '8' * 64)
    ledger.claim_cell_worker('vendor-0', vc, '9' * 64)
    obligation = [{'slot_id': 'control-0000', 'phase': 'operator', 'ordinal': 0,
                   'bound': ledger.quote_call(64)}]
    for run, cell, clock in ((mori, 'mori-0', mc), (vendor, 'vendor-0', vc)):
        ledger.protect_run(run, ref, obligation)
        ledger.bind_run_deadline(run, cell, ref, clock)
        ledger.cancel_control(run, 'control-0000', reason='fixture has no paid calls')
    ledger.start_reference_authority_work('vendor-0', '7' * 64)
    ledger.anchor_cell_deadline_observation('mori-0', 1, mc, 'a' * 64)
    ledger.anchor_evaluation_eligibility(mori, 'b' * 64, 'mori-0', 1, 'a' * 64, 'c' * 64)
    ledger.anchor_cell_deadline_observation('vendor-0', 1, vc, 'd' * 64)
    ledger.anchor_stage_eligibility(vendor, 'e' * 32, 'vendor-0', 1, 'd' * 64, 'f' * 64)
    ledger.anchor_reference_physical_snapshot(vendor, 'vendor-0', '1' * 64, '9' * 64,
                                               ['e' * 32], 1, 'd' * 64, worker_proof_sha256='2' * 64)
    ledger.anchor_cell_deadline_observation('vendor-0', 2, 'd' * 64, '3' * 64)
    ledger.freeze_reference_selection(vendor, 'vendor-0', '4' * 64, 2, '3' * 64)
    head = ledger.snapshot()['journal_head']
    proof = {'schema_version': 1, 'plan_ref': ref, 'mori_run_id': mori, 'reference_run_id': vendor,
             'mori_rows_sha256': '5' * 64, 'reference_rows_sha256': '6' * 64,
             'reference_bundle_sha256': '7' * 64, 'replay_input_sha256': '8' * 64,
             'result': {'scope': 'paired_supervised_snapshots_with_independent_replay', 'performance_claim': False,
                        'seed': 0, 'plan_ref': ref, 'journal_head': head,
                        'replay': {'passed': True, 'external_calls': 0, 'candidate': 'fixture'},
                        'mori': {'candidate': 'fixture', 'settled_upper_bound_micro_cny': 0},
                        'reference': {'settled_upper_bound_micro_cny': 0}}}
    ledger._record_first_pair_audit(proof, expected_head=head)
    return ledger, proof


def test_fixture_event_is_atomically_replayed_by_real_sqlite_journal(tmp_path):
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger, proof = fixture_pair_ledger(tmp_path)
    before = ledger.snapshot()
    original = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    draft = build_continuation_draft(original, experiment_id='circle-v2', source_commit='6' * 40,
        dependency_lock_sha256='7' * 64, method_changes=['disable thinking in both arms'])
    event = {'kind': 'bind_circle_continuation', 'schema_version': 2,
             'previous_head': before['journal_head'], 'draft': draft,
             'tree_ref': 'sha256:' + '8' * 64, 'runtime_ref': 'sha256:' + '9' * 64,
             'python_sha256': 'a' * 64, 'runtime_manifest_sha256': 'b' * 64}
    with ledger._transaction() as (db, _policy, state):
        ledger._append(db, state, event)
    reopened = CampaignBudget(ledger.path)
    with reopened._transaction() as (_db, _policy, state):
        assert state['governance']['circle_continuations']['circle-v2']['draft'] == draft
        assert state['governance']['first_pair_audit'] == proof
        assert set(state['governance']['cell_claims']) == {'mori-0', 'vendor-0'}
    after = reopened.snapshot()
    with pytest.raises(ValueError):
        reopened.claim_cell_deadline('circle-v2--mori-0', 'sha256:' + draft['draft_sha256'], 'c' * 64, seconds=2700)
    assert reopened.snapshot() == after
    assert after['journal_head']['seq'] == before['journal_head']['seq'] + 1
    for key in ('campaign_id', 'limit_micro_cny', 'settled_upper_bound_micro_cny',
                'remaining_micro_cny', 'pending_calls', 'protected_micro_cny'):
        assert after[key] == before[key]
    with pytest.raises(ValueError):
        with reopened._transaction() as (db, _policy, state):
            reopened._append(db, state, event)
    assert reopened.snapshot() == after


def test_concurrent_bindings_from_one_head_commit_only_one_event(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    ledger, _proof = fixture_pair_ledger(tmp_path)
    before = ledger.snapshot()
    inv = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    def attempt(index):
        draft = build_continuation_draft(inv, experiment_id=f'circle-v{index}', source_commit='6' * 40,
            dependency_lock_sha256='7' * 64, method_changes=['fixture continuation'])
        event = {'kind': 'bind_circle_continuation', 'schema_version': 2,
                 'previous_head': before['journal_head'], 'draft': draft,
                 'tree_ref': 'sha256:' + '8' * 64, 'runtime_ref': 'sha256:' + '9' * 64,
                 'python_sha256': 'a' * 64, 'runtime_manifest_sha256': 'b' * 64}
        other = CampaignBudget(ledger.path)
        try:
            with other._transaction() as (db, _policy, state):
                other._append(db, state, event)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(attempt, (2, 3))) == 1
    after = ledger.snapshot()
    assert after['journal_head']['seq'] == before['journal_head']['seq'] + 1
    assert after['remaining_micro_cny'] == before['remaining_micro_cny']
    with ledger._transaction() as (_db, _policy, state):
        assert len(state['governance']['circle_continuations']) == 1
