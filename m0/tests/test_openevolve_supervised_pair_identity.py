"""The supervised pair must retain the independently recovered winner identity."""
import copy

import pytest


def test_reference_supervisor_must_match_the_complete_selected_program(monkeypatch):
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing import pair_audit, supervisor_audit
    selected = {'id': 'winner', 'program_ref': 'sha256:' + '1' * 64,
                'metrics': {'sum_radii': 1.8, 'validity': 1.0}}
    summary = {'mori': {'candidate': 'candidate', 'sum_radii': 1.7, 'validity': 1.0},
               'reference': {'selected_program': selected, 'sum_radii': 1.8, 'validity': 1.0}}
    bundle = {'fixture': 'reference receipts'}
    reports = {
        'mori': {'mode': 'live', 'final_state': 'completed', 'candidate': 'candidate',
                 'final_measurement': {'sum_radii': 1.7, 'validity': 1.0}},
        'reference': {'mode': 'live', 'state': 'completed', 'selected_program': copy.deepcopy(selected),
                      'currency_bundle_sha256': payload_digest(bundle)}}
    monkeypatch.setattr(pair_audit, 'audit_pair_snapshot', lambda **_: copy.deepcopy(summary))
    monkeypatch.setattr(supervisor_audit, 'audit_supervisor_result',
                        lambda config, **_: copy.deepcopy(reports[config['arm']]))
    configs = {'plan': {'fixture': True}, 'ref': 'plan', 'seed': 0}
    arguments = dict(mori_config={**configs, 'arm': 'mori'}, reference_config={**configs, 'arm': 'reference'},
        mori_supervisor_directory='mori', reference_supervisor_directory='reference',
        seed=0, plan=configs['plan'], expected_plan_ref='plan', mori_view=None, mori_clock=None,
        reference_view=None, reference_clock=None, reference_bundle=bundle)
    pair_audit.audit_supervised_pair_snapshot(**arguments)
    reports['reference']['selected_program']['id'] = 'different-winner'
    with pytest.raises(ValueError, match='supervisor reports'):
        pair_audit.audit_supervised_pair_snapshot(**arguments)
