"""Public Framework configuration for C01; model calls require explicit live mode."""
from core.composition.defaults import composed_profile, default_registry
from zoo.gepa_gsm8k.domain import GSM8KDomain


def build_profile(data, *, seed, minibatch_size, max_proposals):
    if type(max_proposals) is not int or max_proposals < 0:
        raise ValueError('max_proposals must be a nonnegative integer')
    from core.composition.gepa_recipe import epoch_batch
    epoch_batch(data.ids('train'), seed=seed, size=minibatch_size, iteration=0)
    profile = composed_profile(name='gepa-gsm8k-v1')
    parameters = dict(seed=seed, minibatch_size=minibatch_size, max_proposals=max_proposals, dataset_identity=data.identity)
    profile.update(schema_version=2, domain={'name': 'gepa_gsm8k', 'options': parameters},
        policy={'name': 'gepa_instance', 'options': {'items': data.ids('validation'), 'seed': seed}},
        operators=[{'name': 'draft'}, {'name': 'gepa_reflective', 'options': {
            'train_ids': data.ids('train'), 'seed': seed, 'minibatch_size': minibatch_size}}],
        frontier={'name': 'population', 'options': {'capacity': max(2, max_proposals + 1)}},
        skills=[{'name': 'instruction', 'options': {'text':
            'Produce reusable instructions for solving mathematical word problems. Return a prompt, not executable code.'}}],
        execution={'schema_version': 1, 'spec': {'role': 'general', 'hypothesis_frozen': True,
            'context_projection': []}, 'constructor': {'name': 'prompt'}})
    profile['admission'] = {'name': 'metric_final', 'options': {'final_request': {
        'fidelity': 'final_audit', 'split_id': 'final_audit', 'seed_set': [seed]}}}
    # Token reservations bound complete solver batches, not merely one call.
    per_call = 1_100_000
    batch_tokens = max(len(data.ids('validation')), minibatch_size, len(data.ids('test'))) * per_call
    limit = (max_proposals + 1) * (3 * batch_tokens + per_call)
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {k: {'token': limit, 'node': max_proposals + 1, 'eval_count': 4 * (max_proposals + 1)}
                   for k in ('global', 'direction', 'candidate')},
        'reservation': {'token': batch_tokens, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'planning': {'token': 0, 'node': 0, 'eval_count': 0},
                                   'operator': {'token': per_call, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [seed]}]}}
    return profile


def registry_for(data):
    registry = default_registry()
    def validate(options):
        if type(options) is not dict or set(options) != {'seed', 'minibatch_size', 'max_proposals', 'dataset_identity'} or options['dataset_identity'] != data.identity:
            raise ValueError('GSM8K domain requires its frozen batch schedule')
        from core.composition.gepa_recipe import epoch_batch
        epoch_batch(data.ids('train'), seed=options['seed'], size=options['minibatch_size'], iteration=0)
        if type(options['max_proposals']) is not int or options['max_proposals'] < 0:
            raise ValueError('max_proposals must be nonnegative')
    registry.register('domain', 'gepa_gsm8k', lambda ctx, opts: GSM8KDomain(data, ctx.llm, **{k: v for k, v in opts.items() if k != 'dataset_identity'}),
                      validate_options=validate)
    return registry


def governed_setup(data, *, seed, minibatch_size, max_proposals, ledger, api_key,
                   max_completion_tokens=4096, base_url=None):
    from zoo.mle_bench_lite.cny_budget import POLICY
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    profile = build_profile(data, seed=seed, minibatch_size=minibatch_size, max_proposals=max_proposals)
    registry = registry_for(data)
    snapshot = ledger.snapshot()
    if snapshot.get('pending_calls') or snapshot.get('protection_breaches') or snapshot.get('journal_schema_version') != 2:
        raise ValueError('existing campaign must be quiescent and governance enabled')
    binding = ledger.manifest_binding()
    def fresh_provider(evaluations):
        return GovernedCNYProvider(binding['model'], base_url or binding['provider_base_url'],
            campaign_binding=binding, api_key=api_key, max_completion_tokens=max_completion_tokens,
            phase_call_limits={'operator': 1, 'evaluation': evaluations})
    main = fresh_provider(max(minibatch_size, len(data.ids('validation')), len(data.ids('test'))))
    control_calls = len(data.ids('validation'))
    declaration = fresh_provider(control_calls).governance_binding()
    registry.install_external_bridge('cny_invocation_v1', lambda: CNYInvocationBridge(ledger))
    registry.register('provider', 'gepa-cny-control', lambda ctx, opts: fresh_provider(control_calls),
                      governance=declaration)
    registry.register('domain', 'gepa-validation-control', lambda ctx, opts: GSM8KDomain(
        data, ctx.llm, seed=seed, minibatch_size=minibatch_size, max_proposals=max_proposals),
        governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    bound = POLICY['context_tokens'] + max_completion_tokens
    reservations = {'operator': {'token': bound, 'node': 1, 'eval_count': 0},
                    'evaluation': {'token': bound * control_calls, 'node': 0, 'eval_count': 1}}
    limits = profile['budget']['options']['limits']['global']
    for unit in limits:
        limits[unit] += sum(v[unit] for v in reservations.values())
    profile['governance'] = {'schema_version': 1, 'controls': {'after_main_cycles': [0], 'seed': seed,
        'provider': {'name': 'gepa-cny-control'}, 'domain': {'name': 'gepa-validation-control'},
        'operator': {'name': 'draft'}, 'request': {'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [seed]},
        'reservations': reservations}}
    return profile, registry, main


def fixture_dataset():
    from zoo.gepa_gsm8k.domain import FrozenDataset
    return FrozenDataset.from_rows({split: [{'id': f'{split}:{i:06d}',
        'question': f'What is {i} + 7?', 'answer': f'#### {i + 7}'}
        for i in range(8 if split == 'train' else 2)] for split in ('train', 'validation', 'test')})


class FixtureProvider:
    model, supplier = 'gepa-offline-fixture', 'offline'
    def __call__(self, prompt):
        import json
        self.last_usage = {'total_tokens': 1}
        value = json.loads(prompt)
        if 'recipe' in value:
            return json.dumps({'hypothesis': value['hypothesis'], 'artifact':
                'Solve carefully and give the final number.' if value['recipe']['parent_artifacts']
                else 'Give a quick answer.'})
        index = int(value['item_id'].split(':')[-1])
        correct = value['instruction'].startswith('Solve carefully') or index % 2 == 0
        return '#### ' + str(index + (7 if correct else 8))


def main(argv=None):
    import argparse
    import json
    import os
    from pathlib import Path
    from core.loop import Framework, LoopConfig
    from zoo.gepa_gsm8k.domain import FrozenDataset
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('fixture', 'live'), default='fixture')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--spending-ledger', type=Path)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--minibatch-size', type=int, default=8)
    parser.add_argument('--max-proposals', type=int, default=10)
    parser.add_argument('--max-completion-tokens', type=int, default=4096)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()) and not args.resume:
        parser.error('output is nonempty; use a new directory or --resume')
    import subprocess
    repository = Path(__file__).resolve().parents[3]
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repository, text=True).strip()
    source_dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repository, text=True))
    if args.mode == 'live' and source_dirty:
        parser.error('live evidence requires committed clean sources')
    if args.mode == 'live':
        if args.manifest is None or args.spending_ledger is None or not args.spending_ledger.is_file():
            parser.error('live mode requires a frozen manifest and the existing campaign ledger')
        secret = os.environ.get('OPENAI_API_KEY')
        if not secret:
            parser.error('OPENAI_API_KEY is not configured')
        from zoo.mle_bench_lite.cny_budget import CampaignBudget
        data = FrozenDataset.from_manifest(args.manifest)
        profile, registry, provider = governed_setup(data, seed=args.seed,
            minibatch_size=args.minibatch_size, max_proposals=args.max_proposals,
            ledger=CampaignBudget(args.spending_ledger), api_key=secret,
            max_completion_tokens=args.max_completion_tokens)
    else:
        data, provider = fixture_dataset(), FixtureProvider()
        profile = build_profile(data, seed=args.seed, minibatch_size=args.minibatch_size,
                                max_proposals=args.max_proposals)
        registry = registry_for(data)
    args.output.mkdir(parents=True, exist_ok=True)
    binding = getattr(provider, 'manifest_binding', None)
    run_manifest = {'schema_version': 1, 'mode': args.mode, 'source_commit': source_commit,
        'source_dirty': source_dirty, 'dataset_identity': data.identity,
        'split_hashes': data.split_hashes, 'profile': profile,
        'provider': binding() if callable(binding) else {'model': provider.model, 'supplier': provider.supplier}}
    manifest_path = args.output / 'run-manifest.json'
    if args.resume:
        if not manifest_path.is_file() or json.loads(manifest_path.read_text()) != run_manifest:
            raise ValueError('frozen run manifest differs; resume cannot change source, data or configuration')
    else:
        with manifest_path.open('x') as handle:
            handle.write(json.dumps(run_manifest, indent=2, ensure_ascii=False) + '\n')
    fw = Framework.from_profile(profile, provider, data,
        LoopConfig(max_generations=args.max_proposals, total_budget=profile['budget']['options']['limits']['global']['token'],
                   intent_cost=1, reeval_floor=0, resume_from_checkpoint=args.resume), str(args.output),
        component_registry=registry)
    result = fw.evolve('Optimize a reusable GSM8K solver instruction using only training rollouts.')
    replay = fw.replay()
    report = {'method_id': 'GEPA', 'reference_revision': '3d34469165f0d604df3b48f1d5c776e9080f3da0',
        'recipe_revision': 'gepa-gsm8k-v1', 'fidelity': 'adapted', 'mode': args.mode, 'seed': args.seed,
        'source_commit': source_commit, 'source_dirty': source_dirty,
        'dataset_identity': data.identity, 'split_hashes': data.split_hashes,
        'minibatch_size': args.minibatch_size, 'max_proposals': args.max_proposals,
        'deviations': ['single component; merge off; perfect-parent skipping off',
            'separate seeded batch and frontier random streams; stable insertion-order ties',
            'initial prompt generated by M7; one initial independent IID-RS sample in live mode',
            'IID-RS control uses validation only; it is not a budget-matched benchmark comparison'],
        'result': result, 'replay_passed': replay['replay_certificate']['passed']}
    (args.output / 'method-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    (args.output / 'profile.json').write_text(json.dumps(profile, indent=2) + '\n')
    print(json.dumps({'mode': args.mode, 'seed': args.seed, 'cycles': result['cycles'],
        'validation_accuracy': result['best_score'], 'final_audit': result['reporting']['final_audit']['state'],
        'replay_passed': report['replay_passed'], 'report': str((args.output / 'method-report.json').resolve())}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
