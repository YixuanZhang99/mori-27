"""Continuation inventory reads one original campaign head without new authority."""
import copy

import pytest

from zoo.mle_bench_lite.cny_budget import CampaignBudget
from test_governed_cny_bridge import setup


def governed(tmp_path):
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    return ledger


def test_inventory_reads_legacy_campaign_without_changing_its_meaning(tmp_path):
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    before = ledger.snapshot()
    inventory = ledger.circle_continuation_inventory(expected_head=before['journal_head'])
    assert inventory['journal_head'] == before['journal_head']
    assert inventory['campaign']['campaign_id'] == before['campaign_id']
    assert inventory['pilot'] is None and inventory['runtime'] is None and inventory['first_pair_audit'] is None
    assert inventory['claims'] == {}
    assert inventory['currency']['remaining_micro_cny'] == 200000000
    assert inventory['currency']['pending_calls'] == [] and inventory['currency']['protected_micro_cny'] == 0
    assert ledger.snapshot() == before


def test_inventory_freezes_one_head_and_returns_detached_values(tmp_path):
    ledger = governed(tmp_path)
    plan, tree, runtime = ('sha256:' + char * 64 for char in 'abc')
    ledger.freeze_circle_pilot(plan, tree, 60, require_runtime=True, require_single_run=True)
    ledger.freeze_circle_runtime(plan, tree, runtime, 'd' * 64)
    head = ledger.snapshot()['journal_head']
    original = ledger.circle_continuation_inventory(expected_head=head)
    assert original['pilot']['plan_ref'] == plan and original['runtime']['runtime_ref'] == runtime
    altered = copy.deepcopy(original)
    altered['pilot']['plan_ref'] = 'changed'
    altered['campaign']['campaign_id'] = 'changed'
    assert ledger.circle_continuation_inventory(expected_head=head) == original
    ledger.reserve('pending-call', 'e' * 64, 64)
    with pytest.raises(ValueError, match='head'):
        ledger.circle_continuation_inventory(expected_head=head)
    latest = ledger.snapshot()
    inventory = ledger.circle_continuation_inventory(expected_head=latest['journal_head'])
    assert inventory['currency']['pending_calls'] == ['pending-call']
    assert inventory['currency']['reserved_micro_cny'] == latest['reserved_micro_cny']
    assert inventory['currency']['remaining_micro_cny'] == latest['remaining_micro_cny']
    assert inventory['pilot'] == original['pilot'] and inventory['runtime'] == original['runtime']
    assert ledger.snapshot() == latest


def test_inventory_includes_existing_protected_capacity(setup):
    ledger = setup[0]
    snapshot = ledger.snapshot()
    inventory = ledger.circle_continuation_inventory(expected_head=snapshot['journal_head'])
    assert inventory['currency']['protected_micro_cny'] == snapshot['protected_micro_cny'] > 0
    assert inventory['currency']['remaining_micro_cny'] == snapshot['remaining_micro_cny']
    assert inventory['currency']['protection_breaches'] == snapshot['protection_breaches']
    assert ledger.snapshot() == snapshot


def test_inventory_rejects_malformed_head(tmp_path):
    ledger = governed(tmp_path)
    with pytest.raises(ValueError):
        ledger.circle_continuation_inventory(expected_head={'seq': True, 'sha256': '0' * 64})


def test_audit_identity_excludes_private_result_content():
    from zoo.mle_bench_lite.cny_budget import _circle_audit_identity, _hash
    proof = {'schema_version': 1, 'plan_ref': 'sha256:' + 'a' * 64,
             'mori_run_id': 'b' * 64, 'reference_run_id': 'c' * 64,
             'mori_rows_sha256': 'd' * 64, 'reference_rows_sha256': 'e' * 64,
             'reference_bundle_sha256': 'f' * 64, 'replay_input_sha256': '1' * 64,
             'result': {'private_program': 'PRIVATE-CANDIDATE-CONTENT'}}
    result = _circle_audit_identity(proof)
    assert result['proof_sha256'] == _hash(proof)
    assert result['plan_ref'] == proof['plan_ref']
    assert 'PRIVATE-CANDIDATE-CONTENT' not in str(result) and 'result' not in result
