"""Six-cell recovery inventory from one independently pinned campaign head.

This is a claim inventory, not a score reducer or authorization to launch.
An absent claim applies only to the inspected head; a claimed cell may have
completed, failed, or remain in progress, and needs its own terminal evidence.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess

from core.x1.checkpoint import payload_digest
from zoo.circle_packing.pilot_plan import build_draft_plan
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def _validate_replay_output(output, *, mori, vendor, mori_directory, vendor_directory, ledger_path):
    """Keep replay files outside both original cells and frozen authorities."""
    target = Path(output)
    try:
        if not target.is_absolute() or target.name in ('', '.', '..') or target.exists() or target.is_symlink() or \
                target.parent.resolve(strict=True) != target.parent:
            raise ValueError('pair replay requires a fresh absolute workspace')
        # The source tree is <bundle>/source/m0; its parent bundle also holds
        # the original plan and manifest and must remain free of replay files.
        protected = [Path(mori['source']).resolve(strict=True).parent.parent,
                     Path(mori['runtime']).resolve(strict=True), Path(ledger_path).resolve(strict=True).parent,
                     Path(mori['clock']).resolve(strict=False).parent,
                     Path(vendor['clock']).resolve(strict=False).parent,
                     Path(mori['output']).resolve(strict=False), Path(vendor['output']).resolve(strict=False),
                     Path(vendor['workspace']).resolve(strict=False),
                     Path(vendor['worker_directory']).resolve(strict=False),
                     Path(mori_directory).resolve(strict=True), Path(vendor_directory).resolve(strict=True)]
        if any(target == path or target in path.parents or path in target.parents for path in protected):
            raise ValueError('pair replay workspace overlaps original evidence or frozen authorities')
    except (KeyError, TypeError, OSError, RuntimeError) as error:
        raise ValueError('pair replay workspace cannot be verified') from error
    return target


def snapshot_matrix(ledger, plan, *, expected_plan_ref, expected_head):
    """Read one atomic ledger snapshot without creating or modifying any cell."""
    if type(ledger) is not CampaignBudget or type(plan) is not dict:
        raise ValueError('matrix requires the original campaign and frozen plan')
    inventory = ledger.circle_claim_inventory(expected_head=expected_head)
    try:
        expected = build_draft_plan(inventory['campaign'], source_commit=plan['source_commit'],
                                    dependency_lock_sha256=plan['dependency_lock_sha256'])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('matrix plan differs from the original campaign') from error
    ref = 'sha256:' + expected['draft_sha256']
    if expected_plan_ref != ref or payload_digest(plan) != payload_digest(expected):
        raise ValueError('matrix plan differs from its original campaign')
    pilot, claims = inventory['pilot'], inventory['claims']
    if pilot is None or pilot['plan_ref'] != ref or pilot['wallclock_seconds'] != expected['limits']['wallclock_seconds']:
        raise ValueError('matrix requires the frozen original pilot')
    cells = []
    for cell in expected['cells']:
        identifier = f"{cell['arm']}-{cell['seed']}"
        claim = claims.get(identifier)
        if claim is not None and claim['plan_ref'] != ref:
            raise ValueError('cell claim differs from frozen matrix plan')
        cells.append({'cell_id': identifier, 'seed': cell['seed'], 'arm': cell['arm'],
                      'state': 'not_claimed' if claim is None else 'claimed_outcome_unverified', 'score': None})
    from zoo.circle_packing.cell_identity import parse_cell_identity
    for name in set(claims) - {cell['cell_id'] for cell in cells}:
        experiment_id, _arm, seed = parse_cell_identity(name)
        continuation = inventory['continuations'].get(experiment_id)
        if experiment_id is None or seed != 0 or continuation is None or name not in continuation['cell_ids'] or \
                claims[name]['plan_ref'] != 'sha256:' + continuation['draft_sha256']:
            raise ValueError('campaign has an unrecognized cell outside the frozen matrix')
    return {'schema_version': 1, 'scope': 'campaign_claim_inventory_at_pinned_head',
            'performance_claim': False, 'plan_ref': ref, 'journal_head': inventory['journal_head'], 'cells': cells}


def snapshot_continuation_matrix(ledger, plan, *, expected_plan_ref, expected_head):
    """Read one version's claims at a pinned head; scores remain unverified."""
    if type(ledger) is not CampaignBudget or type(plan) is not dict:
        raise ValueError('continuation matrix requires the campaign and bound plan')
    inventory = ledger.circle_claim_inventory(expected_head=expected_head)
    try:
        experiment_id = plan['experiment_id']
        binding = inventory['continuations'][experiment_id]
        ref = 'sha256:' + binding['draft_sha256']
        if expected_plan_ref != ref or payload_digest(plan) != payload_digest(binding['draft']):
            raise ValueError('continuation matrix differs from its bound plan')
        cells = []
        for item in binding['draft']['cells']:
            name = item['cell_id']
            claim = inventory['claims'].get(name)
            if claim is not None and claim['plan_ref'] != ref:
                raise ValueError('continuation claim differs from its plan')
            cells.append({'cell_id': name, 'seed': item['seed'], 'arm': item['arm'],
                          'state': 'not_claimed' if claim is None else 'claimed_outcome_unverified',
                          'score': None})
    except (KeyError, TypeError) as error:
        raise ValueError('continuation matrix has no matching bound plan') from error
    return {'schema_version': 1, 'scope': 'continuation_claim_inventory_at_pinned_head',
            'performance_claim': False, 'experiment_id': experiment_id, 'plan_ref': ref,
            'tree_ref': binding['tree_ref'], 'runtime_ref': binding['runtime_ref'],
            'source_commit': binding['draft']['source_commit'], 'method_changes': binding['draft']['method_changes'],
            'artifact_verification_recorded': binding['artifact_verification_recorded'],
            'journal_head': inventory['journal_head'], 'cells': cells}


def report_matrix(ledger, plan, *, expected_plan_ref, expected_head, cell_evidence=None, pair_evidence=None):
    """Reduce original cell evidence, replaying supplied pairs in frozen source.

    A successful process alone is not verified final geometry. Pair evidence
    requires a fresh replay workspace and never supplies its own scores.
    """
    from zoo.circle_packing.cell_deadline import RecordedCellClock
    from zoo.circle_packing.supervisor_audit import audit_contained_terminal
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView

    inventory = snapshot_matrix(ledger, plan, expected_plan_ref=expected_plan_ref, expected_head=expected_head)
    if cell_evidence is None:
        cell_evidence = {}
    names = {cell['cell_id'] for cell in inventory['cells']}
    if type(cell_evidence) is not dict or set(cell_evidence) - names:
        raise ValueError('matrix evidence requires declared cell identities')
    if pair_evidence is None:
        pair_evidence = {}
    if type(pair_evidence) is not dict or any(type(seed) is not int or seed not in (0, 1, 2)
            or type(item) is not dict or set(item) != {'replay_output'} for seed, item in pair_evidence.items()):
        raise ValueError('matrix pairs require only declared seeds and fresh replay workspaces')
    pilot = ledger.circle_pilot_binding()
    if cell_evidence and (pilot is None or pilot.get('require_single_run') is not True):
        raise ValueError('cell currency requires a frozen single-run pilot')
    campaign = ledger.manifest_binding()
    cells = []
    for original in inventory['cells']:
        cell = {**original, 'currency': None}
        name = cell['cell_id']
        claimed = cell['state'] != 'not_claimed'
        cell['state'] = 'claimed_unresolved' if claimed else 'not_claimed_at_head'
        if name in cell_evidence and cell_evidence[name] is None:
            raise ValueError('matrix evidence cannot replace a claim with null')
        item = cell_evidence.get(name)
        if item is not None:
            if not claimed or type(item) is not dict or set(item) != {'config', 'directory', 'view', 'clock'}:
                raise ValueError('matrix cell evidence differs from the claimed cell')
            view, clock = item['view'], item['clock']
            if type(view) is not RecordedCurrencyView or not view._pinned_head or \
                    type(clock) is not RecordedCellClock or view.manifest_binding() != campaign:
                raise ValueError('matrix cell requires original pinned currency and clock')
            envelope = json.loads(view._evidence)
            if envelope['journal_head'] != expected_head or clock._record['cell_id'] != name or \
                    clock._record['plan_ref'] != expected_plan_ref:
                raise ValueError('matrix cell evidence differs from the original head or plan')
            run_id, physical_ref = envelope['run_id'], envelope['plan_ref']
            if view.run_deadline_binding(run_id) != {'cell_id': name, 'plan_ref': expected_plan_ref,
                                                     'deadline_ref': clock._record['record_sha256']}:
                raise ValueError('matrix currency run differs from the original cell')
            RecordedCellClock(clock._evidence, view.cell_deadline_claim(name))
            audit = view.audit_run(run_id, physical_ref)
            cell['currency'] = {key: audit[key] for key in ('settled_upper_bound_micro_cny',
                'outstanding_micro_cny', 'reserved_micro_cny', 'pending_calls', 'breaches', 'invoice_verified')}
            cell['currency']['breaches_scope'] = 'campaign'
            if item['directory'] is not None:
                terminal = audit_contained_terminal(item['config'], directory=item['directory'], view=view, clock=clock)
                cell['state'] = ('contained_completed_unverified' if terminal['state'] == 'contained_completed'
                                 else terminal['state'])
        cells.append(cell)
    by_name = {cell['cell_id']: cell for cell in cells}
    pairs = [{'seed': seed, 'difference': None,
              'state': 'not_claimed_at_head' if all(by_name[f'{arm}-{seed}']['state'] == 'not_claimed_at_head'
                                                    for arm in ('mori', 'vendor')) else 'incomplete'}
             for seed in (0, 1, 2)]
    for seed, pair in pair_evidence.items():
        mori_name, vendor_name = f'mori-{seed}', f'vendor-{seed}'
        if any(name not in cell_evidence or by_name[name]['state'] != 'contained_completed_unverified'
               for name in (mori_name, vendor_name)):
            raise ValueError('pair audit requires both original completed supervisors')
        mori, vendor = cell_evidence[mori_name], cell_evidence[vendor_name]
        config, other = mori['config'], vendor['config']
        if type(config) is not dict or type(other) is not dict or config.get('plan') != plan or \
                other.get('plan') != plan or config.get('ref') != expected_plan_ref or \
                other.get('ref') != expected_plan_ref or config.get('seed') != seed or other.get('seed') != seed or \
                config.get('source') != other.get('source') or config.get('runtime') != other.get('runtime'):
            raise ValueError('pair configurations differ from the original plan')
        replay_output = _validate_replay_output(pair['replay_output'], mori=config, vendor=other,
            mori_directory=mori['directory'], vendor_directory=vendor['directory'], ledger_path=ledger.path)
        source, runtime = Path(config['source']), Path(config['runtime'])
        from zoo.circle_packing.frozen_source import verify_frozen_source
        from zoo.circle_packing.frozen_runtime import verify_frozen_runtime
        verify_frozen_source(ledger, plan, snapshot=source.parent, manifest=config['source_manifest'],
                             expected_plan_ref=expected_plan_ref, expected_campaign_id=campaign['campaign_id'])
        verify_frozen_runtime(ledger, runtime=runtime, manifest=config['runtime_manifest'],
                              base_python='/usr/bin/python3.12')
        probe = Path(__file__).with_name('frozen_pair_probe.py').resolve(strict=True)
        command = [str(runtime / 'bin' / 'python'), str(probe), str(mori['directory']), str(vendor['directory']),
                   json.dumps(expected_head, sort_keys=True), expected_plan_ref, str(seed),
                   str(replay_output), str(ledger.path)]
        env = {'PATH': os.defpath, 'HOME': str(Path.home()), 'PYTHONPATH': str(source),
               'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
        try:
            process = subprocess.run(command, cwd=source, env=env, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('independent frozen pair audit could not complete') from error
        if process.returncode != 0:
            raise ValueError('independent frozen pair audit failed')
        try:
            def unique(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError('duplicate pair audit field')
                    result[key] = value
                return result
            audited = json.loads(process.stdout, object_pairs_hook=unique,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            if audited['scope'] != 'paired_supervised_snapshots_with_independent_replay' or \
                    audited['performance_claim'] is not False or audited['seed'] != seed or \
                    audited['plan_ref'] != expected_plan_ref or audited['journal_head'] != expected_head or \
                    audited['replay']['passed'] is not True or audited['replay']['external_calls'] != 0:
                raise ValueError('independent pair audit differs from the requested evidence')
            values = []
            for name, arm in ((mori_name, 'mori'), (vendor_name, 'reference')):
                summary = audited[arm]
                score, validity = summary['sum_radii'], summary['validity']
                if type(score) not in (int, float) or not math.isfinite(score) or \
                        type(validity) not in (int, float) or not math.isfinite(validity) or \
                        summary['settled_upper_bound_micro_cny'] != by_name[name]['currency']['settled_upper_bound_micro_cny']:
                    raise ValueError('independent pair result differs from cell currency')
                by_name[name].update(state='audited_final_snapshot', score=score if validity == 1 else None,
                                     validity=validity)
                values.append(score if validity == 1 else None)
            if all(value is not None for value in values):
                difference = values[0] - values[1]
                if audited['sum_radii_difference'] != difference:
                    raise ValueError('independent pair difference differs from its snapshots')
                pairs[seed]['difference'] = difference
                pairs[seed]['state'] = 'audited_final_snapshots'
            else:
                pairs[seed]['state'] = 'audited_invalid_geometry'
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError('independent pair audit result is invalid') from error
    if ledger.snapshot()['journal_head'] != expected_head:
        raise ValueError('campaign head changed during matrix report')
    return {'schema_version': 1, 'scope': 'recorded_cell_matrix_with_pair_audits' if pair_evidence else
            'recorded_cell_terminal_matrix', 'performance_claim': False,
            'plan_ref': expected_plan_ref, 'journal_head': inventory['journal_head'], 'cells': cells,
            'pairs': pairs}
