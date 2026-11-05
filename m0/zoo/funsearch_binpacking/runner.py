"""Public Framework configuration for frozen OR3 program search."""
import hashlib
import json
import math
from pathlib import Path

from core.composition.defaults import composed_profile, default_registry
from zoo.funsearch_binpacking.domain import OR3Domain

TEMPLATE = 'def priority(item, bins):\n    return -(bins - item)\n'
TEMPLATE_REF = 'sha256:' + hashlib.sha256(TEMPLATE.encode()).hexdigest()


def build_profile(data, *, seed, max_proposals, call_token_bound, timeout=30):
    if (type(max_proposals) is not int or max_proposals < 0 or
            type(call_token_bound) is not int or call_token_bound <= 0 or
            type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('finite timeout and explicit nonnegative proposals/positive token bound required')
    profile = composed_profile(name='funsearch-or3-v1')
    profile.update(schema_version=2,
        domain={'name': 'funsearch_or3', 'options': {'dataset_identity': data.identity, 'timeout': float(timeout)}},
        policy={'name': 'funsearch', 'options': {'case_ids': data.ids('dev'), 'islands': 2, 'seed': seed,
            'prompt_size': 2, 'temperature': 1.0, 'temperature_period': 10, 'metric': 'score',
            'template': TEMPLATE, 'template_ref': TEMPLATE_REF, 'function_name': 'priority', 'reset_interval': 5}},
        operators=[{'name': 'draft'}, {'name': 'funsearch'}],
        frontier={'name': 'population', 'options': {'capacity': max(2, max_proposals + 1)}},
        execution={'schema_version': 1, 'spec': {'role': 'coder', 'hypothesis_frozen': True,
            'context_projection': []}, 'constructor': {'name': 'funsearch_prompt',
            'options': {'template': TEMPLATE, 'function_name': 'priority'}}},
        skills=[{'name': 'instruction', 'options': {'text':
            'Optimize online bin packing. priority(item, bins) returns one finite numeric priority per '
            'eligible bin; the largest priority chooses the bin. bins is a NumPy vector of remaining '
            'capacities, including empty bins, and np is available. Fewer used bins is better. '
            'Change only the target function. No files, network, external data, or random state.'}}],
        admission={'name': 'metric_final', 'options': {'final_request': {
            'fidelity': 'final_audit', 'split_id': 'final_audit'}}})
    limits = {'token': (max_proposals + 1) * call_token_bound, 'node': max_proposals + 1,
              'eval_count': max_proposals + 2}
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {key: dict(limits) for key in ('global', 'direction', 'candidate')},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
            'operator': {'token': call_token_bound, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}}
    return profile


def registry_for(data):
    registry = default_registry()
    def validate(options):
        if (type(options) is not dict or set(options) != {'dataset_identity', 'timeout'} or
                options['dataset_identity'] != data.identity or
                type(options['timeout']) not in (int, float) or
                not math.isfinite(options['timeout']) or options['timeout'] <= 0):
            raise ValueError('OR3 requires frozen data and a finite positive timeout')
        data.validate()
    registry.register('domain', 'funsearch_or3', lambda _ctx, options: OR3Domain(
        data, template=TEMPLATE, timeout=options['timeout']), validate_options=validate)
    return registry


def governed_setup(data, *, seed, max_proposals, ledger, api_key,
                   max_completion_tokens=16384, timeout=30, base_url=None):
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    snapshot = ledger.snapshot()
    if snapshot.get('protection_breaches') or snapshot.get('journal_schema_version') != 2:
        raise ValueError('existing campaign must have valid protection and governance enabled')
    binding = ledger.manifest_binding()
    def fresh():
        return GovernedCNYProvider(binding['model'], base_url or binding['provider_base_url'],
            campaign_binding=binding, api_key=api_key, max_completion_tokens=max_completion_tokens,
            phase_call_limits={'operator': 1, 'evaluation': 0})
    provider = fresh()
    declaration = provider.governance_binding()
    bound = declaration['call_bound']['units']['token']
    profile = build_profile(data, seed=seed, max_proposals=max_proposals, call_token_bound=bound, timeout=timeout)
    registry = registry_for(data)
    registry.install_external_bridge('cny_invocation_v1', lambda: CNYInvocationBridge(ledger))
    registry.register('provider', 'funsearch-cny-control', lambda _ctx, _opts: fresh(), governance=declaration)
    registry.register('domain', 'funsearch-dev-control', lambda _ctx, _opts: OR3Domain(
        data, template=TEMPLATE, timeout=timeout),
        governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    reservations = {'operator': {'token': bound, 'node': 1, 'eval_count': 0},
                    'evaluation': {'token': 0, 'node': 0, 'eval_count': 1}}
    limits = profile['budget']['options']['limits']['global']
    for unit in limits:
        limits[unit] += sum(part[unit] for part in reservations.values())
    profile['governance'] = {'schema_version': 1, 'controls': {'after_main_cycles': [0], 'seed': seed,
        'provider': {'name': 'funsearch-cny-control'}, 'domain': {'name': 'funsearch-dev-control'},
        'operator': {'name': 'draft'}, 'request': {'fidelity': 'dev', 'split_id': 'dev'},
        'reservations': reservations}}
    return profile, registry, provider


class FixtureProvider:
    model, supplier = 'fixed-best-fit-fixture', 'offline'
    def __call__(self, prompt):
        self.last_usage = {'total_tokens': 1}
        return json.dumps({'artifact': TEMPLATE, 'hypothesis': json.loads(prompt)['hypothesis']})


def fixture_data(root):
    from zoo.funsearch_binpacking.data import FrozenOR3, SPLIT_RULE
    path = root / 'manifest.json'
    if path.exists():
        return FrozenOR3.from_manifest(path)
    root.mkdir(parents=True, exist_ok=False)
    manifest = {'schema_version': 1, 'notebook_sha256': '0' * 64, 'split_rule': SPLIT_RULE, 'splits': {}}
    for split in ('dev', 'held_out'):
        values = {f'{split}:{i:02}': {'capacity': 10, 'num_items': 2, 'items': [6, 4]} for i in range(10)}
        raw = json.dumps(values, sort_keys=True, separators=(',', ':')).encode()
        folder = root / split; folder.mkdir()
        (folder / 'data.json').write_bytes(raw)
        manifest['splits'][split] = {'sha256': hashlib.sha256(raw).hexdigest(), 'count': 10}
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return FrozenOR3.from_manifest(path)


def reference_baseline(data, timeout):
    from core.tasks.funsearch_binpacking import score_partition
    from core.tasks.funsearch_priority_sandbox import SandboxedPriority
    report = {'method': 'fixed-best-fit-reference', 'model_calls': 0, 'search_result': False,
              'dataset_identity': data.identity, 'template_ref': TEMPLATE_REF, 'timeout': timeout, 'splits': {}}
    for split in ('dev', 'held_out'):
        values = data.rows(split)
        with SandboxedPriority(TEMPLATE, TEMPLATE, timeout=timeout) as priority:
            report['splits'][split] = score_partition(values, priority)
        data.validate()
    return report


def main(argv=None):
    import argparse
    import os
    import subprocess
    from core.loop import Framework, LoopConfig
    from core.x1.store import AppendOnlyStore
    from zoo.funsearch_binpacking.data import FrozenOR3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('fixture', 'live'), default='fixture')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--spending-ledger', type=Path)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--max-proposals', type=int, default=10)
    parser.add_argument('--max-completion-tokens', type=int, default=16384)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--final-only', action='store_true')
    args = parser.parse_args(argv)
    if args.final_only:
        journal = args.output / 'x1.jsonl'
        if not args.resume or not journal.is_file() or len(list(AppendOnlyStore(journal).read('metric_final_frozen'))) != 1:
            raise ValueError('final-only requires an existing frozen selection and --resume')
    if args.output.exists() and any(args.output.iterdir()) and not args.resume:
        parser.error('output is nonempty; use a new directory or --resume')
    try:
        root = Path(__file__).resolve().parents[3]
        source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
            text=True, stderr=subprocess.DEVNULL).strip()
        source_dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root,
            text=True, stderr=subprocess.DEVNULL))
    except (OSError, subprocess.CalledProcessError):
        if args.mode == 'live':
            parser.error('live evidence requires a Git checkout with a verifiable source commit')
        source_commit, source_dirty = None, None
    if args.mode == 'live' and source_dirty:
        parser.error('live evidence requires committed clean sources')
    ledger = None
    if args.mode == 'live':
        if args.manifest is None or args.spending_ledger is None or not args.spending_ledger.is_file():
            parser.error('live mode requires a frozen manifest and the existing campaign ledger')
        secret = os.environ.get('OPENAI_API_KEY')
        if not secret:
            parser.error('OPENAI_API_KEY is not configured')
        data = FrozenOR3.from_manifest(args.manifest)
        if data.notebook_sha256 != 'eec45846a8661722addbb856179327cf2ede0bc502e32be4ad58a6ac54e0aca6' or data.hashes != {
                'dev': 'a99be58e4e5cf25986edcffd55f03928f47e82f2db00397eab72b9c1d73c19c3',
                'held_out': '4c18523528ff1c9c5bf235f105478a731c312a92d2924c27c2253ac729918045'}:
            parser.error('live pilot requires the pinned official OR3 partitions')
        from zoo.mle_bench_lite.cny_budget import CampaignBudget
        ledger = CampaignBudget(args.spending_ledger)
        profile, registry, provider = governed_setup(data, seed=args.seed, max_proposals=args.max_proposals,
            ledger=ledger, api_key=secret, max_completion_tokens=args.max_completion_tokens, timeout=args.timeout)
    else:
        if args.resume and not (args.output / 'fixture-data' / 'manifest.json').is_file():
            raise ValueError('resume requires the original frozen fixture data')
        data, provider = fixture_data(args.output / 'fixture-data'), FixtureProvider()
        profile = build_profile(data, seed=args.seed, max_proposals=args.max_proposals,
                                call_token_bound=100, timeout=args.timeout)
        registry = registry_for(data)
    # The fixed external reference also verifies the real sandbox before any
    # paid request. Neither its dev nor held-out scores are sent to the model.
    baseline_path = args.output / 'baseline-reference.json'
    if args.resume:
        if not baseline_path.is_file():
            raise ValueError('resume requires its frozen baseline reference')
        baseline_raw = baseline_path.read_bytes()
    else:
        baseline_raw = (json.dumps(reference_baseline(data, args.timeout), indent=2) + '\n').encode()
        args.output.mkdir(parents=True, exist_ok=True)
        with baseline_path.open('xb') as handle:
            handle.write(baseline_raw)
    baseline = json.loads(baseline_raw)
    binding = getattr(provider, 'manifest_binding', None)
    manifest = {'schema_version': 1, 'mode': args.mode, 'source_commit': source_commit,
        'source_dirty': source_dirty, 'dataset_identity': data.identity, 'split_hashes': data.split_hashes,
        'profile': profile, 'baseline_sha256': hashlib.sha256(baseline_raw).hexdigest(),
        'provider': binding() if callable(binding) else {'model': provider.model, 'supplier': provider.supplier}}
    manifest_path = args.output / 'run-manifest.json'
    if args.resume:
        if not manifest_path.is_file() or json.loads(manifest_path.read_text()) != manifest:
            raise ValueError('frozen run manifest differs; resume cannot change source, data or configuration')
    else:
        with manifest_path.open('x') as handle:
            handle.write(json.dumps(manifest, indent=2) + '\n')
    fw = Framework.from_profile(profile, provider, data,
        LoopConfig(max_generations=args.max_proposals,
            total_budget=profile['budget']['options']['limits']['global']['token'], reeval_floor=0,
            resume_from_checkpoint=args.resume), str(args.output), component_registry=registry)
    result, replay_passed, error_type = None, None, None
    run_state = 'execution_failed'
    try:
        result = fw.evolve('Improve the online bin packing priority using only development scores.')
        run_state = 'replay_failed'
        replay_passed = fw.replay()['replay_certificate']['passed']
        if replay_passed:
            run_state = 'completed'
        else:
            error_type = 'ReplayCertificateFailed'
    except Exception as error:
        # Unknown usage must stop execution. Preserve the attempt without
        # replaying, retrying, settling, or releasing any pending reservation.
        error_type = type(error).__name__
    rows = list(AppendOnlyStore(args.output / 'x1.jsonl').read())
    completed_evidence = [row['payload'] for row in rows if row['kind'] == 'composed_evidence']
    evaluations = [row['evidence']['eval_result'] for row in completed_evidence]
    attempted = sum(row['kind'] == 'composed_cycle_started' for row in rows)
    failed = sum(value['status'] != 'ok' for value in evaluations)
    incomplete = attempted - len(evaluations)
    final_rows = [row['payload'] for row in rows if row['kind'] == 'metric_final_completed']
    final = final_rows[0] if len(final_rows) == 1 else {'state': 'invalid_multiple_reports'} if final_rows else {
        'state': 'frozen_pending' if any(row['kind'] == 'metric_final_frozen' for row in rows) else 'not_frozen'}
    started = {row['payload']['binding'] for row in rows if row['kind'] == 'composed_provider_started'}
    completed = {row['payload']['binding'] for row in rows if row['kind'] == 'composed_provider_completed'}
    campaign_after, campaign_snapshot_error = None, None
    if ledger is not None:
        try:
            campaign_after = ledger.snapshot()
        except Exception as error:
            campaign_snapshot_error = type(error).__name__
            if run_state == 'completed':
                run_state, error_type = 'reporting_failed', campaign_snapshot_error
    report = {'method_id': 'FunSearch', 'reference_revision': 'cc53f274237d7ab05c19df939edbc1f9616a7c19',
        'recipe_revision': 'funsearch-or3-v1', 'fidelity': 'adapted', 'mode': args.mode, 'seed': args.seed,
        'source_commit': source_commit, 'source_dirty': source_dirty, 'dataset_identity': data.identity,
        'split_hashes': data.split_hashes, 'max_proposals': args.max_proposals, 'timeout': args.timeout,
        'deviations': ['two islands; bounded 10-proposal standard pilot; independent Python RNG',
            'reset every five successful registrations including initialization, instead of wall-clock resets',
            'cluster objective is last sorted case; global final selection uses development mean',
            'initial program generated by M7; only the priority function may change',
            'independent initial live control uses dev only; not a budget-matched comparison',
            'fixed best-fit reference evaluated before search; reference scores never enter generation'],
        'run_state': run_state, 'error_type': error_type,
        'search': {'attempted': attempted, 'successful': len(evaluations) - failed, 'failed': failed,
                   'incomplete': incomplete, 'failure_rate': (failed + incomplete) / attempted if attempted else None},
        'baseline': baseline, 'result': result, 'replay_passed': replay_passed,
        'final_audit': final, 'completed_evidence': completed_evidence,
        'unresolved_provider_bindings': sorted(started - completed),
        'campaign_after': campaign_after, 'campaign_snapshot_error': campaign_snapshot_error}
    (args.output / 'method-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.output / 'profile.json').write_text(json.dumps(profile, indent=2) + '\n')
    print(json.dumps({'mode': args.mode, 'seed': args.seed, 'run_state': run_state, 'error_type': error_type,
        'cycles': result['cycles'] if result else None,
        'dev_score': result['best_score'] if result else None, 'final_audit': final['state'],
        'search': report['search'], 'replay_passed': report['replay_passed'],
        'report': str((args.output / 'method-report.json').resolve())}))
    return 0 if run_state == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
