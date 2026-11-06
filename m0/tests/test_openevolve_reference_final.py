"""A reference result must be recomputed from its frozen geometry."""
import copy

import pytest

from test_openevolve_host_stage_budget import fake_result


def test_final_geometry_recomputed_from_original_stage():
    from zoo.circle_packing.reference_final import recalculate_geometry
    result = fake_result('fixture program', 2)
    report = recalculate_geometry(result, expected_program_ref=result['program_ref'],
                                  expected_geometry_ref=result['geometry_ref'], expected_metrics=result['metrics'])
    assert report['geometry'] == result['geometry']
    assert report['metrics'] == result['metrics']
    report['geometry']['radii'][0] = 0
    assert result['geometry']['radii'][0] > 0


@pytest.mark.parametrize('mutation', ['geometry', 'program', 'reference', 'metrics', 'status', 'boolean'])
def test_final_geometry_rejects_changed_or_invalid_stage(mutation):
    from zoo.circle_packing.reference_final import recalculate_geometry
    original = fake_result('fixture program', 2)
    result = copy.deepcopy(original)
    expected_program, expected_geometry = original['program_ref'], original['geometry_ref']
    expected_metrics = copy.deepcopy(original['metrics'])
    if mutation == 'geometry': result['geometry']['radii'][0] = .5
    elif mutation == 'program': expected_program = 'sha256:' + 'f' * 64
    elif mutation == 'reference': expected_geometry = 'sha256:' + 'f' * 64
    elif mutation == 'metrics': expected_metrics['combined_score'] += 1
    elif mutation == 'boolean': expected_metrics['validity'] = True
    else: result['status'] = 'timeout'
    with pytest.raises(ValueError):
        recalculate_geometry(result, expected_program_ref=expected_program,
                             expected_geometry_ref=expected_geometry, expected_metrics=expected_metrics)


def test_result_refuses_changed_predeclared_threshold_before_audit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_governed_cny_framework import campaign_fixture
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.circle_packing import reference_final
    ledger = campaign_fixture(tmp_path)
    plan = build_draft_plan(ledger.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    ref = 'sha256:' + plan['draft_sha256']
    changed = {**plan, 'public_range_sum_radii': 0}
    def forbidden(*args, **kwargs):
        raise AssertionError('modified plan must be rejected before audit')
    monkeypatch.setattr(reference_final, 'audit_anchored_reference_cell', forbidden)
    with pytest.raises(ValueError, match='plan'):
        reference_final.recalculate_reference_snapshot(ledger, SimpleNamespace(_record={'plan_ref': ref}),
            'run', plan=changed, expected_plan_ref=ref, worker_proof={}, stdout='', stderr='', selected={},
            options={}, stamp={}, governance={}, rows=[], request_ids=[])
