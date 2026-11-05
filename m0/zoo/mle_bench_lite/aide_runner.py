"""AIDE CSV search through the public Framework; offline fixture by default."""
from core.composition.defaults import composed_profile

RECIPE = 'aide-mle-v1'
REFERENCE_REVISION = 'ad73d227af481bea3de06f884f41b2993dd6453a'


def build_profile(*, split_seed=7, search_seed=0, call_token_bound, max_nodes=10):
    for name, value, minimum in (('split_seed', split_seed, 0), ('search_seed', search_seed, 0),
                                 ('max_nodes', max_nodes, 1), ('call_token_bound', call_token_bound, 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    if max_nodes > 10:
        raise ValueError('AIDE v1 supports at most 10 nodes within its frozen journal capacity')
    p = composed_profile(name=RECIPE)
    p.update(schema_version=2, domain={'name': 'native'}, executor={'name': 'git_artifact'},
        policy={'name': 'aide', 'options': {'num_drafts': 3, 'debug_probability': .5,
            'max_debug_depth': 2, 'seed': search_seed}},
        operators=[{'name': 'draft'}, {'name': 'debug'}, {'name': 'improve'}],
        frontier={'name': 'tree', 'options': {'retain_rejected': True}},
        memory={'name': 'scoped', 'options': {'context_scope': 'run', 'levels': ['L1'],
            'trust_floor': 'ungated', 'include_negative': True, 'include_imported': False,
            'top_k': 10, 'max_chars': 160000}},
        execution={'schema_version': 1, 'spec': {'role': 'general', 'hypothesis_frozen': False,
            'context_projection': ['memory']}, 'constructor': {'name': 'prompt', 'options': {'max_attempts': 1}}},
        admission={'name': 'metric_final', 'options': {'final_request': {
            'fidelity': 'final_audit', 'split_id': 'final_audit', 'seed_set': [split_seed]}}})
    limits = {'token': max_nodes * call_token_bound, 'node': max_nodes, 'eval_count': max_nodes + 1}
    p['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {level: dict(limits) for level in ('global', 'direction', 'candidate')},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
            'operator': {'token': call_token_bound, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [split_seed]}]}}
    return p


# This constant program learns priors from the visible training table only.
# It is a plumbing fixture, not an AIDE result or a competitive baseline.
FIXTURE_PROGRAM = '''import csv, json
from collections import Counter
with open('data/protocol.json') as f: protocol = json.load(f)
with open('data/train.csv') as f: train = list(csv.DictReader(f))
with open('data/predict.csv') as f: predict = list(csv.DictReader(f))
columns = protocol['output_columns']
if protocol['kind'] == 'classification':
    counts = Counter(row['target'] for row in train)
    values = [counts[name] / len(train) for name in columns[1:]]
else:
    values = [sum(float(row[name]) for row in train) / len(train) for name in columns[1:]]
with open('predictions.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(columns)
    writer.writerows([row['row_id'], *values] for row in predict)
'''


class FixtureProvider:
    model, supplier = 'public-training-prior-fixture', 'offline'

    def __call__(self, prompt):
        import json
        self.last_usage = {'total_tokens': 1}
        return json.dumps({'artifact': FIXTURE_PROGRAM, 'hypothesis': 'Fit a prior from public training rows.'})


def governed_setup(bundle, output, *, ledger, api_key, split_seed, search_seed,
                   max_nodes, runner, solution_timeout):
    from core.composition.defaults import default_registry
    from zoo.mle_bench_lite.composed_domain import PublicTrainDomain
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    binding = ledger.manifest_binding()
    snapshot = ledger.snapshot()
    if snapshot.get('pending_calls') or snapshot.get('protection_breaches') or snapshot.get('journal_schema_version') != 2:
        raise ValueError('existing campaign must be quiescent and governance enabled')

    def fresh():
        return GovernedCNYProvider(binding['model'], binding['provider_base_url'],
            campaign_binding=binding, api_key=api_key, max_completion_tokens=16384,
            phase_call_limits={'operator': 1, 'evaluation': 0}, reasoning_effort='low')

    provider = fresh()
    declaration = provider.governance_binding()
    bound = declaration['call_bound']['units']['token']
    p = build_profile(split_seed=split_seed, search_seed=search_seed,
                      max_nodes=max_nodes, call_token_bound=bound)
    registry = default_registry()
    registry.install_external_bridge('cny_invocation_v1', lambda: CNYInvocationBridge(ledger))
    registry.register('provider', 'aide-control', lambda _ctx, _opts: fresh(), governance=declaration)
    registry.register('domain', 'aide-control', lambda ctx, _opts: PublicTrainDomain(
        bundle, output / 'control_candidates' / ctx.invocation_scope['slot_id'],
        solution_timeout=solution_timeout, runner=runner),
        governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    reservations = {'operator': {'token': bound, 'node': 1, 'eval_count': 0},
                    'evaluation': {'token': 0, 'node': 0, 'eval_count': 1}}
    limits = p['budget']['options']['limits']['global']
    for unit in limits:
        limits[unit] += sum(part[unit] for part in reservations.values())
    p['governance'] = {'schema_version': 1, 'controls': {'after_main_cycles': [0], 'seed': search_seed,
        'provider': {'name': 'aide-control'}, 'domain': {'name': 'aide-control'},
        'operator': {'name': 'draft'}, 'request': {
            'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [split_seed]}, 'reservations': reservations}}
    return p, registry, provider


def source_identity():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    try:
        return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                    text=True, stderr=subprocess.DEVNULL).strip(),
                'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root,
                    text=True, stderr=subprocess.DEVNULL))}
    except (OSError, subprocess.CalledProcessError):
        return {'commit': None, 'dirty': None}


def run(*, output, public_root, task_id, split_seed=7, search_seed=0, max_nodes=10,
        solution_timeout=120, anonymization_key_path=None, provider=None, runner=None,
        ledger=None, api_key=None, resume=False, protected_roots=()):
    """Freeze one run; never start a campaign or retry an unresolved provider call.

    Provider/runner injection is for trusted offline tests. Live mode always uses
    the governed provider and the real sandbox and requires clean source.
    """
    import json
    import time
    from pathlib import Path
    from core.composition.contracts import Proposal
    from core.composition.defaults import default_registry
    from core.executor.types import Candidate
    from core.loop import Framework, LoopConfig
    from zoo.mle_bench_lite.agent_common import _atomic_json
    from zoo.mle_bench_lite.composed_agent import task_description
    from zoo.mle_bench_lite.composed_domain import PublicTrainDomain, SandboxRunner
    from zoo.mle_bench_lite.public_train import PublicTrainBundle, digest, file_digest, load_anonymization_key
    started_at = time.monotonic()
    output = Path(output).resolve()
    source = source_identity()
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError('output is nonempty; choose a new directory or resume')
    if ledger is not None:
        if provider is not None or runner is not None:
            raise ValueError('live mode does not accept injected provider or runner')
        if not source['commit'] or source['dirty']:
            raise ValueError('live evidence requires committed clean sources')
        if not api_key:
            raise ValueError('live provider key is not configured')
        if ledger.path.resolve() == output or output in ledger.path.resolve().parents:
            raise ValueError('existing campaign ledger must be outside run output')
    runner = runner or SandboxRunner()
    key_path = Path(anonymization_key_path).resolve() if anonymization_key_path else output / 'anonymization.key'
    if isinstance(runner, SandboxRunner):
        runner.validate_paths(output, public_root, key_path, ledger.path if ledger else None, *protected_roots)
        runner.preflight(required_modules=('numpy', 'pandas', 'sklearn') if ledger else ('numpy',))
    key = load_anonymization_key(key_path, create=anonymization_key_path is None and not resume)
    bundle = PublicTrainBundle(public_root, output / 'public_inputs', task_id, split_seed,
                              anonymization_key=key, dev_scoring='task_metric')
    domain = PublicTrainDomain(bundle, output / 'candidates', solution_timeout=solution_timeout, runner=runner)
    if ledger is not None:
        profile, registry, provider = governed_setup(bundle, output, ledger=ledger, api_key=api_key,
            split_seed=split_seed, search_seed=search_seed, max_nodes=max_nodes,
            runner=runner, solution_timeout=solution_timeout)
    else:
        provider = provider or FixtureProvider()
        registry = default_registry()
        profile = build_profile(split_seed=split_seed, search_seed=search_seed,
                                max_nodes=max_nodes, call_token_bound=100)
    task = task_description(bundle).replace('Return code only.',
        'Return the complete executable code in artifact and your plan in hypothesis in the required JSON response.')
    task += '\nSelect by maximum ' + bundle.protocol['selection_metric'] + '; this is the negated task loss.'
    binding = getattr(provider, 'manifest_binding', None)
    manifest = {'schema_version': 1, 'recipe_revision': RECIPE, 'mode': 'live' if ledger else 'fixture',
        'source': source, 'task_id': task_id, 'split_seed': split_seed, 'search_seed': search_seed,
        'max_nodes': max_nodes, 'solution_timeout': solution_timeout, 'profile': profile,
        'dataset_identity': bundle.identity, 'dataset_manifest': bundle.manifest,
        'domain': domain.manifest_binding, 'task_description_sha256': digest(task),
        'provider': binding() if callable(binding) else {'model': provider.model, 'supplier': provider.supplier}}
    manifest_path = output / 'run-manifest.json'
    if resume:
        if not manifest_path.is_file() or manifest_path.is_symlink() or json.loads(manifest_path.read_text()) != manifest:
            raise ValueError('frozen run manifest differs; source, data and configuration cannot change on resume')
    else:
        with manifest_path.open('x') as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
    fw = Framework.from_profile(profile, provider, domain,
        LoopConfig(max_generations=max_nodes - 1, total_budget=profile['budget']['options']['limits']['global']['token'],
                   reeval_floor=0, resume_from_checkpoint=resume), str(output / 'composed'), component_registry=registry)
    # Restoring evidence validates original training outputs; it never trains.
    domain.restore_evidence(fw.store.read('composed_evidence'))
    import copy
    replay_provider = copy.deepcopy(provider)
    def replay_adapters(_workdir, _store):
        return replay_provider, PublicTrainDomain(bundle, output / "candidates",
            solution_timeout=solution_timeout, runner=copy.deepcopy(runner))

    result = certificate = submission = currency = receipts = physical = None
    state, error_type = 'execution_failed', None
    try:
        result = fw.evolve(task)
        state = 'replay_failed'
        certificate = fw.replay(task, adapter_factory=replay_adapters)['replay_certificate']
        if not certificate['passed'] or certificate['external_calls'] != 0:
            raise ValueError('recorded replay failed')
        if ledger is not None:
            state = 'currency_audit_failed'
            currency = fw.inspect()['governance']['external_currency']
            if currency['unknown_cost_calls'] or currency['integrity_violations'] or not currency['protection_valid']:
                raise ValueError('currency audit is incomplete')
            from zoo.mle_bench_lite.m7_pilot_audit import audit_currency_receipts
            receipts = audit_currency_receipts(output / 'composed', ledger, expected_model=manifest['provider']['requested_model'])
            if receipts['total_tokens'] != currency['known_provider_tokens'] or \
                    receipts['settled_micro_cny'] != currency['authority']['settled_upper_bound_micro_cny']:
                raise ValueError('independent currency receipts differ')
        if result.get('best_candidate_id') is None:
            state = 'no_valid_submission'
        else:
            state = 'materialization_failed'
            selected = [r['payload'] for r in fw.store.read('composed_evidence')
                        if r['payload']['proposal']['candidate']['id'] == result['best_candidate_id']]
            if len(selected) != 1:
                raise ValueError('selected candidate must have unique original evidence')
            item = selected[0]
            proposal = Proposal(Candidate(**item['proposal']['candidate']), item['proposal']['artifact'])
            record = domain.materialize(proposal, output / 'submission.csv', expected_prediction_sha256=
                item['evidence']['eval_result']['contract']['private']['data']['prediction_sha256'])
            submission = {'candidate_id': result['best_candidate_id'],
                'artifact_sha256': record['identity']['artifact_sha256'],
                'prediction_sha256': record['prediction_sha256'],
                'submission_sha256': file_digest(output / 'submission.csv')}
            if ledger is not None:
                from zoo.mle_bench_lite.m7_pilot_audit import audit_physical_and_submission
                physical = audit_physical_and_submission(output / 'composed', bundle, output / 'submission.csv',
                    expected_tokens=receipts['total_tokens'], candidates_root=output / 'candidates')
            state = 'completed'
    except Exception as error:
        # Deliberately retain unknown reservations. No retry or invented usage.
        error_type = type(error).__name__
    rows = list(fw.store.read())
    evidence = [r['payload'] for r in rows if r['kind'] == 'composed_evidence']
    attempted = sum(r['kind'] == 'composed_cycle_started' for r in rows)
    failed = sum(r['evidence']['eval_result']['status'] != 'ok' for r in evidence)
    incomplete = attempted - len(evidence)
    finals = [r['payload'] for r in rows if r['kind'] == 'metric_final_completed']
    final = finals[0] if len(finals) == 1 else {'state': 'not_completed'}
    final_score = final.get('evidence', {}).get('evidence', {}).get('eval_result', {}).get('metrics', {}).get('gate/score')
    provider_started = {r['payload']['binding'] for r in rows if r['kind'] == 'composed_provider_started'}
    provider_completed = {r['payload']['binding'] for r in rows if r['kind'] == 'composed_provider_completed'}
    report = {'method_id': 'AIDE', 'reference_revision': REFERENCE_REVISION, 'recipe_revision': RECIPE,
        'fidelity': 'adapted', 'mode': manifest['mode'], 'source': source, 'task_id': task_id,
        'split_seed': split_seed, 'search_seed': search_seed, 'max_nodes': max_nodes,
        'dataset_identity': bundle.identity, 'dataset_manifest': bundle.manifest,
        'run_state': state, 'error_type': error_type, 'result': result,
        'search': {'attempted': attempted, 'successful': len(evidence) - failed, 'failed': failed,
            'incomplete': incomplete, 'failure_rate': (failed + incomplete) / attempted if attempted else None},
        'completed_evidence': evidence, 'replay_certificate': certificate,
        'tree_choices': [r['payload'] for r in rows if r['kind'] == 'aide_selection'],
        'final_audit': final, 'final_score': final_score, 'submission': submission,
        'official_score': None, 'external_benchmark_score_produced': False,
        'unresolved_provider_bindings': sorted(provider_started - provider_completed),
        'training_invocations_this_process': domain.training_invocations,
        'wall_seconds_this_process': time.monotonic() - started_at,
        'currency_audit': currency, 'independent_currency_receipts': receipts,
        'independent_physical_submission': physical}
    if ledger is not None:
        try:
            report['campaign_after'] = ledger.snapshot()
        except Exception as error:
            report['campaign_snapshot_error'] = type(error).__name__
            report['run_state'] = 'reporting_failed'
    # Preserve every attempt, including a failed resume, as well as the latest view.
    attempts = output / 'reports'; attempts.mkdir(exist_ok=True)
    with (attempts / f'{len(list(attempts.glob("*.json"))):04d}.json').open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    _atomic_json(output / 'method-report.json', report)
    return report


def fixture_data(root, task_id):
    """Small synthetic CSVs; no Kaggle access and no hidden labels in programs."""
    from zoo.mle_bench_lite.public_train import TASK_SPECS, write_csv
    if root.exists():
        return root
    root.mkdir(parents=True)
    spec = TASK_SPECS[task_id]
    if spec['kind'] == 'classification':
        classes = ['A', 'B', 'C']
        targets = [spec['target']]
        train = [{'id': str(i), 'x': i, targets[0]: classes[i % 3]} for i in range(60)]
        sample = [{'id': str(i), **{name: 1 / 3 for name in classes}} for i in range(4)]
        outputs = classes
    else:
        targets = outputs = spec['targets']
        train = [{'id': str(i), 'x': i, **{name: i / 10 + 1 for name in targets}} for i in range(60)]
        sample = [{'id': str(i), **{name: 0 for name in outputs}} for i in range(4)]
    write_csv(root / 'train.csv', ['id', 'x', *targets], train)
    write_csv(root / 'test.csv', ['id', 'x'], [{'id': str(i), 'x': i + 1000} for i in range(4)])
    write_csv(root / 'sample_submission.csv', ['id', *outputs], sample)
    return root


def main(argv=None):
    import argparse
    import json
    import os
    from pathlib import Path
    from zoo.mle_bench_lite.public_train import TASK_SPECS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('fixture', 'live'), default='fixture')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', choices=tuple(TASK_SPECS), default='spooky-author-identification')
    parser.add_argument('--public-root', type=Path)
    parser.add_argument('--anonymization-key', type=Path)
    parser.add_argument('--spending-ledger', type=Path)
    parser.add_argument('--split-seed', type=int, default=7)
    parser.add_argument('--search-seed', type=int, default=0)
    parser.add_argument('--max-nodes', type=int, default=10)
    parser.add_argument('--solution-timeout', type=float, default=120)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    ledger = secret = None
    public = args.public_root
    if args.mode == 'live':
        if public is None or args.spending_ledger is None or not args.spending_ledger.is_file() or args.anonymization_key is None:
            parser.error('live requires public-root, existing spending-ledger and shared private anonymization-key')
        secret = os.environ.get('OPENAI_API_KEY')
        if not secret:
            parser.error('OPENAI_API_KEY is not configured')
        from zoo.mle_bench_lite.cny_budget import CampaignBudget
        ledger = CampaignBudget(args.spending_ledger)
    elif public is None:
        public = args.output.with_name(args.output.name + '-fixture-data')
        if args.resume and not public.is_dir():
            parser.error('resume requires original fixture data')
        public = fixture_data(public, args.task)
    report = run(output=args.output, public_root=public, task_id=args.task,
        split_seed=args.split_seed, search_seed=args.search_seed, max_nodes=args.max_nodes,
        solution_timeout=args.solution_timeout, anonymization_key_path=args.anonymization_key,
        ledger=ledger, api_key=secret, resume=args.resume)
    print(json.dumps({key: report[key] for key in (
        'mode', 'run_state', 'error_type', 'task_id', 'split_seed', 'search_seed', 'search', 'final_score')}))
    return 0 if report['run_state'] in ('completed', 'no_valid_submission') else 1


if __name__ == '__main__':
    raise SystemExit(main())
