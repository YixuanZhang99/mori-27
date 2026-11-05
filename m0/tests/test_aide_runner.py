"""Named AIDE protocol and public Framework delivery boundaries."""
import math

import pytest

from test_mle_composed import fixture_public, TEST_ANONYMIZATION_KEY
from zoo.mle_bench_lite.public_train import PublicTrainBundle


@pytest.mark.parametrize('task', ['spooky-author-identification', 'nomad2018-predict-transparent-conductors'])
def test_task_metric_is_opt_in_frozen_and_not_the_legacy_dev_proxy(tmp_path, task):
    public = fixture_public(tmp_path / 'public', task=task)
    legacy = PublicTrainBundle(public, tmp_path / 'legacy', task, 7,
                              anonymization_key=TEST_ANONYMIZATION_KEY)
    task_metric = PublicTrainBundle(public, tmp_path / 'task', task, 7,
                                   anonymization_key=TEST_ANONYMIZATION_KEY, dev_scoring='task_metric')
    assert legacy.indices == task_metric.indices
    assert legacy.local_ids == task_metric.local_ids
    assert legacy.identity != task_metric.identity
    assert legacy.contexts['dev'] != task_metric.contexts['dev']
    assert task_metric.manifest['dev_scoring'] == 'task_metric'
    assert task_metric.protocol['selection_metric'] == (
        'negative_log_loss' if 'spooky' in task else 'negative_mean_target_RMSLE')
    if 'spooky' in task:
        predictions = {row_id: [1 / 3] * 3 for row_id in task_metric.expected_ids}
        expected = -math.log(3)
    else:
        predictions = {row_id: [0, 0] for row_id in task_metric.expected_ids}
        rows = task_metric.indices['dev']
        expected = -sum(math.sqrt(sum(math.log1p(task_metric.labels[i][j]) ** 2
            for i in rows) / len(rows)) for j in range(2)) / 2
    assert task_metric.score(predictions, 'dev') == pytest.approx(expected)
    assert legacy.score(predictions, 'dev') != pytest.approx(expected)


def test_named_profile_separates_search_rng_from_every_evaluation_seed():
    from zoo.mle_bench_lite.aide_runner import build_profile
    p = build_profile(split_seed=7, search_seed=2, call_token_bound=100)
    assert p['policy'] == {'name': 'aide', 'options': {
        'num_drafts': 3, 'debug_probability': .5, 'max_debug_depth': 2, 'seed': 2}}
    assert p['budget']['options']['fidelity_rungs'] == [
        {'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [7]}]
    assert p['admission']['name'] == 'metric_final'
    assert p['admission']['options']['final_request'] == {
        'fidelity': 'final_audit', 'split_id': 'final_audit', 'seed_set': [7]}
    assert 'proxy_validity' not in p['budget']['options']
    assert p['budget']['options']['limits']['global']['node'] == 10
    assert p['memory']['options']['top_k'] == 10


@pytest.mark.parametrize('broken', [False, True])
def test_named_runner_real_framework_frozen_final_all_fail_and_resume(tmp_path, broken):
    import json
    from test_mle_composed import TrustedFixtureRunner
    from test_aide_recipe import PlanProvider
    from zoo.mle_bench_lite.aide_runner import run, FIXTURE_PROGRAM

    class Codes(PlanProvider):
        model, supplier = 'test-aide-fixture', 'offline'
        def __call__(self, prompt):
            super().__call__(prompt)
            return json.dumps({'artifact': "raise RuntimeError('ALL_FAILED_MARKER')" if broken else FIXTURE_PROGRAM,
                               'hypothesis': 'Fit a public training prior only.'})

    public = fixture_public(tmp_path / 'public')
    key = tmp_path / 'key'; key.write_bytes(TEST_ANONYMIZATION_KEY); key.chmod(0o600)
    provider = Codes()
    kwargs = dict(output=tmp_path / 'run', public_root=public, task_id='spooky-author-identification',
                  anonymization_key_path=key, runner=TrustedFixtureRunner(), provider=provider, max_nodes=4)
    report = run(**kwargs)
    assert report['run_state'] == ('no_valid_submission' if broken else 'completed')
    assert report['search'] == {'attempted': 4, 'successful': 0 if broken else 4,
                               'failed': 4 if broken else 0, 'incomplete': 0, 'failure_rate': 1. if broken else 0.}
    assert report['replay_certificate']['passed']
    assert report['replay_certificate']['external_calls'] == 0
    assert report['training_invocations_this_process'] == 4
    if broken:
        assert report['final_score'] is None and report['submission'] is None
        assert report['final_audit']['state'] == 'skipped'
    else:
        assert report['final_score'] == pytest.approx(-math.log(3))
        assert report['submission']['candidate_id'] == report['result']['best_candidate_id']
        assert (tmp_path / 'run/submission.csv').is_file()
    calls = provider.calls
    fresh = Codes()
    kwargs["provider"] = fresh
    resumed = run(**kwargs, resume=True)
    assert resumed["run_state"] == report["run_state"]
    assert resumed["replay_certificate"]["passed"]
    assert provider.calls == calls and fresh.calls == 0
    assert resumed['training_invocations_this_process'] == 0
    assert resumed['submission'] == report['submission']
    assert resumed['search'] == report['search']
    assert resumed['final_score'] == report['final_score']
    with pytest.raises(ValueError, match='manifest'):
        run(**kwargs, resume=True, search_seed=2)
    assert provider.calls == calls


def test_runner_retains_unknown_usage_attempt_and_never_submits(tmp_path):
    import json
    from test_mle_composed import TrustedFixtureRunner
    from test_aide_recipe import PlanProvider
    from zoo.mle_bench_lite.aide_runner import run
    provider = PlanProvider(unknown=True)
    report = run(output=tmp_path / 'run', public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', runner=TrustedFixtureRunner(), provider=provider)
    assert report['run_state'] == 'execution_failed'
    assert report['error_type'] is not None and report['submission'] is None
    assert report['final_score'] is None
    assert report['search']['attempted'] == 1 and report['search']['incomplete'] == 1
    assert provider.calls == 1
    assert report['unresolved_provider_bindings']
    assert json.loads((tmp_path / 'run/reports/0000.json').read_text()) == report


def test_governed_profile_control_uses_fixed_split_and_independent_search_seed(tmp_path):
    from test_governed_currency import migrated
    from test_mle_composed import TrustedFixtureRunner
    from zoo.mle_bench_lite.aide_runner import governed_setup
    ledger = migrated(tmp_path)
    bundle = PublicTrainBundle(fixture_public(tmp_path / 'public'), tmp_path / 'inputs',
        'spooky-author-identification', 7, anonymization_key=TEST_ANONYMIZATION_KEY, dev_scoring='task_metric')
    p, _, provider = governed_setup(bundle, tmp_path / 'run', ledger=ledger, api_key='fixture-key',
        split_seed=7, search_seed=2, max_nodes=10, runner=TrustedFixtureRunner(), solution_timeout=120)
    assert p['governance']['controls']['request'] == {
        'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [7]}
    assert p['governance']['controls']['seed'] == 2
    assert p['budget']['options']['limits']['global']['node'] == 11
    assert p['budget']['options']['limits']['candidate']['node'] == 10
    assert provider.manifest_binding()['reasoning_effort'] == 'low'
    assert provider.manifest_binding()['max_completion_tokens'] == 16384
    assert not ledger.snapshot()['pending_calls']


def test_runner_resumes_construction_failure_without_inventing_training_output(tmp_path):
    import json
    from test_mle_composed import TrustedFixtureRunner
    from test_aide_recipe import PlanProvider
    from zoo.mle_bench_lite.aide_runner import run
    class Empty(PlanProvider):
        model, supplier = 'empty-fixture', 'offline'
        def __call__(self, prompt):
            super().__call__(prompt)
            return json.dumps({'artifact': '', 'hypothesis': 'No materialization.'})
    kwargs = dict(output=tmp_path / 'run', public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_nodes=1, runner=TrustedFixtureRunner())
    original = run(**kwargs, provider=Empty())
    assert original['run_state'] == 'no_valid_submission'
    fresh = Empty()
    resumed = run(**kwargs, provider=fresh, resume=True)
    assert resumed['run_state'] == original['run_state']
    assert resumed['search'] == original['search']
    assert resumed['training_invocations_this_process'] == fresh.calls == 0


def test_final_labels_do_not_enter_search_and_data_is_fixed_across_search_seeds(tmp_path):
    import csv
    import json
    from test_mle_composed import TrustedFixtureRunner
    from test_aide_recipe import PlanProvider
    from zoo.mle_bench_lite.aide_runner import run, FIXTURE_PROGRAM
    from zoo.mle_bench_lite.public_train import write_csv
    task = 'nomad2018-predict-transparent-conductors'
    public = fixture_public(tmp_path / 'original', task=task)
    key = tmp_path / 'key'; key.write_bytes(TEST_ANONYMIZATION_KEY); key.chmod(0o600)
    original_bundle = PublicTrainBundle(public, tmp_path / 'preview', task, 7,
        anonymization_key=TEST_ANONYMIZATION_KEY, dev_scoring='task_metric')
    modified = tmp_path / 'modified'; modified.mkdir()
    for name in ('test.csv', 'sample_submission.csv'):
        (modified / name).write_bytes((public / name).read_bytes())
    with (public / 'train.csv').open() as stream:
        reader = csv.DictReader(stream); columns = reader.fieldnames; rows = list(reader)
    for index in original_bundle.indices['final_audit']:
        for target in original_bundle.output_columns:
            rows[index][target] = '1234567'
    write_csv(modified / 'train.csv', columns, rows)
    class Prior(PlanProvider):
        model, supplier = 'prior-fixture', 'offline'
        def __call__(self, prompt):
            super().__call__(prompt)
            return json.dumps({'artifact': FIXTURE_PROGRAM, 'hypothesis': 'Use public priors.'})
    reports, providers = [], []
    for n, (root, search_seed) in enumerate(((public, 0), (modified, 0), (public, 2))):
        provider = Prior(); providers.append(provider)
        reports.append(run(output=tmp_path / f'run{n}', public_root=root, task_id=task, max_nodes=4,
            split_seed=7, search_seed=search_seed, anonymization_key_path=key,
            runner=TrustedFixtureRunner(), provider=provider))
    assert all(r['run_state'] == 'completed' for r in reports)
    assert reports[0]['final_score'] != reports[1]['final_score']
    assert reports[0]['result']['best_score'] == reports[1]['result']['best_score']
    assert reports[0]['result']['best_candidate_id'] == reports[1]['result']['best_candidate_id']
    assert reports[0]['dataset_identity'] == reports[2]['dataset_identity']
    for n in (1, 2):
        for name in ('train.csv', 'predict.csv', 'protocol.json'):
            assert (tmp_path / f'run{n}/public_inputs' / name).read_bytes() == (tmp_path / 'run0/public_inputs' / name).read_bytes()
    # Provenance references are run-specific. The visible task, generated plans,
    # public metrics, program inputs and choices must be identical across final labels.
    for i in range(4):
        first, changed = (json.loads(p.prompts[i]) for p in providers[:2])
        assert first['hypothesis'] == changed['hypothesis']
        assert first['recipe'] == changed['recipe']
        for prompt in (first, changed):
            assert '1234567' not in json.dumps(prompt)
    assert [x['operator'] for x in reports[0]['tree_choices']] == [x['operator'] for x in reports[1]['tree_choices']]


def test_named_profile_refuses_more_nodes_than_its_frozen_journal_capacity():
    from zoo.mle_bench_lite.aide_runner import build_profile
    with pytest.raises(ValueError, match='10'):
        build_profile(call_token_bound=100, max_nodes=11)


def test_packaged_named_profile_is_the_default_main_assembly():
    import json
    from pathlib import Path
    from zoo.mle_bench_lite.aide_runner import build_profile
    from zoo.mle_bench_lite.cny_budget import POLICY
    configured = json.loads((Path(__file__).parents[1] / 'config/profiles/aide_mle.json').read_text())
    assert configured == build_profile(call_token_bound=POLICY['context_tokens'] + 16384)
