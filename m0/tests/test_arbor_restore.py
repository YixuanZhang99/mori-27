import pytest
from core.x1.checkpoint import RunCheckpoint
from test_arbor_memory import run_feedback, FeedbackProvider, FeedbackDomain
from test_arbor_recipe import assembly, TASK
from test_configured_construction import build
from test_aide_recipe import rebind_checkpoint


@pytest.mark.parametrize('defect', ['negative', 'hit', 'created'])
def test_restored_insight_metadata_matches_original_events(tmp_path, defect):
    run_feedback(tmp_path)
    payload = RunCheckpoint.load(tmp_path / 'checkpoint.json').payload
    target = next(e for e in payload['memory']['entries']
                  if e['payload']['schema_id'] == 'tree_insight/v1'
                  and e['utility']['harmful_count'] == 1)
    if defect == 'negative':
        target['utility']['helpful_count'] = 100
        target['utility']['harmful_count'] = 0
    elif defect == 'hit':
        target['utility']['hit_count'] = 10000
    else:
        target['time']['created_at'] = 10000
    rebind_checkpoint(tmp_path, payload)
    provider, domain = FeedbackProvider(), FeedbackDomain()
    with pytest.raises(ValueError, match='Arbor'):
        build(tmp_path, assembly=assembly(), provider=provider, domain=domain,
              generations=3, resume=True).evolve(TASK)
    assert provider.calls == 0 and domain.calls == []
