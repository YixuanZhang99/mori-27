"""Draft comparison plan fixes common ceilings before any live admission."""
import pytest

from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint


def test_draft_six_cell_plan_has_shared_numeric_ceilings_and_no_calls(tmp_path, local_endpoint):
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.circle_packing.governed import governed_setup
    campaign = campaign_fixture(tmp_path)
    before = campaign.snapshot()
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    assert plan['status'] == 'draft_not_executable'
    assert [(cell['seed'], cell['arm']) for cell in plan['cells']] == [
        (seed, arm) for seed in (0, 1, 2) for arm in ('vendor', 'mori')]
    assert plan['limits']['token'] == 4 * (1048576 + 16384) == 4259840
    assert plan['limits']['eval_count'] == 17
    assert plan['limits']['wallclock_seconds'] == 2700
    profile, _, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=6, base_url=local_endpoint.url,
        total_token_ceiling=plan['limits']['token'])
    assert profile['budget']['options']['limits']['global']['token'] == plan['limits']['token']
    assert profile['budget']['options']['limits']['global']['eval_count'] == plan['limits']['eval_count']
    assert provider.governance_binding()['call_bound']['units']['token'] * 4 == plan['limits']['token']
    assert campaign.snapshot() == before and not local_endpoint.requests


@pytest.mark.parametrize('commit,lock', [('dirty', 'b' * 64), ('a' * 40, 'bad')])
def test_draft_rejects_unpinned_source(commit, lock, tmp_path):
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path)
    with pytest.raises(ValueError):
        build_draft_plan(campaign.manifest_binding(), source_commit=commit, dependency_lock_sha256=lock)


def test_draft_rejects_tampered_campaign_policy(tmp_path):
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path).manifest_binding()
    campaign['context_tokens'] -= 1
    with pytest.raises(ValueError, match='campaign'):
        build_draft_plan(campaign, source_commit='a' * 40, dependency_lock_sha256='b' * 64)
