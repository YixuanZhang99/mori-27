"""Named Arbor recipe runs through Framework with isolated evaluation and metering."""
import json
from pathlib import Path

import pytest

from test_mle_composed import TEST_ANONYMIZATION_KEY, TrustedFixtureRunner, fixture_public
from zoo.mle_bench_lite.public_train import PublicTrainBundle


def test_named_profile_has_full_defaults_and_bounded_pilot():
    from zoo.mle_bench_lite.arbor_runner import build_profile
    from zoo.mle_bench_lite.cny_budget import POLICY
    full = build_profile(call_token_bound=POLICY['context_tokens'] + 16384)
    configured = json.loads((Path(__file__).parents[1] / 'config/profiles/arbor_mle.json').read_text())
    assert full == configured
    assert full['policy']['options']['max_cycles'] == 20
    pilot = build_profile(split_seed=7, search_seed=2, call_token_bound=100, max_cycles=5)
    assert pilot['policy']['options'] == {'max_cycles': 5, 'max_tree_depth': 2, 'seed': 2, 'max_new_ideas': 3}
    assert pilot['execution']['spec']['hypothesis_frozen'] is True
    assert pilot['admission']['options']['admission_seeds'] == pilot['admission']['options']['final_seeds'] == [7]
    assert pilot['budget']['options']['limits']['global'] == {'token': 3500, 'node': 5, 'eval_count': 9}
    assert pilot['budget']['options']['operation_reservations']['planning']['token'] == 400
    with pytest.raises(ValueError, match='20'):
        build_profile(call_token_bound=100, max_cycles=21)


@pytest.mark.parametrize('broken', [False, True])
def test_runner_frozen_artifact_all_failed_resume_and_recorded_replay(tmp_path, broken):
    from zoo.mle_bench_lite.arbor_runner import run, FixtureProvider
    class Programs(FixtureProvider):
        def __call__(self, prompt):
            response = super().__call__(prompt)
            request = json.loads(prompt)
            if broken and 'recipe' in request:
                value = json.loads(response)
                value['artifact'] = "raise RuntimeError('synthetic failure')"
                return json.dumps(value)
            return response
    public = fixture_public(tmp_path / 'public')
    key = tmp_path / 'key'; key.write_bytes(TEST_ANONYMIZATION_KEY); key.chmod(0o600)
    kwargs = dict(output=tmp_path / 'run', public_root=public, task_id='spooky-author-identification',
                  max_cycles=3, anonymization_key_path=key, runner=TrustedFixtureRunner())
    provider = Programs()
    report = run(**kwargs, provider=provider)
    assert report['run_state'] == ('no_valid_submission' if broken else 'completed')
    assert report['method_id'] == 'Arbor'
    assert report['search']['attempted'] == 3
    assert report['search']['successful'] == (0 if broken else 3)
    assert report['search']['incomplete'] == 0
    assert report['replay_certificate']['passed'] and report['replay_certificate']['external_calls'] == 0
    assert report['training_invocations_this_process'] == 3
    assert len(report['stage_trace']['backpropagate']) == len(report['stage_trace']['admission']) == 3
    if broken:
        assert report['submission'] is None and report['final_score'] is None
    else:
        assert report['final_score'] is not None and (tmp_path / 'run/submission.csv').is_file()
    fresh = Programs()
    resumed = run(**kwargs, provider=fresh, resume=True)
    assert resumed['run_state'] == report['run_state']
    assert resumed['submission'] == report['submission']
    assert resumed['replay_certificate']['passed']
    assert fresh.calls == resumed['training_invocations_this_process'] == 0
    with pytest.raises(ValueError, match='manifest'):
        run(**kwargs, provider=fresh, resume=True, search_seed=2)


def test_live_profile_accounts_for_planning_repair_and_fresh_control(tmp_path):
    from test_governed_currency import migrated
    from zoo.mle_bench_lite.arbor_runner import governed_setup
    ledger = migrated(tmp_path)
    bundle = PublicTrainBundle(fixture_public(tmp_path / 'public'), tmp_path / 'inputs',
        'spooky-author-identification', 7, anonymization_key=TEST_ANONYMIZATION_KEY, dev_scoring='task_metric')
    profile, _, provider = governed_setup(bundle, tmp_path / 'run', ledger=ledger, api_key='fixture-key',
        split_seed=7, search_seed=2, max_cycles=5, runner=TrustedFixtureRunner(), solution_timeout=120)
    controls = profile['governance']['controls']
    assert controls['request'] == {'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [7]}
    assert controls['after_main_cycles'] == [0] and controls['seed'] == 2
    assert controls['provider']['name'] == 'arbor-control'
    bound = provider.governance_binding()['call_bound']['units']['token']
    assert profile['budget']['options']['limits']['global']['token'] == 37 * bound
    assert controls['reservations']['operator']['token'] == 2 * bound
    assert provider.manifest_binding()['phase_call_limits'] == {'planning': 4, 'operator': 2, 'evaluation': 0}
    assert not ledger.snapshot()['pending_calls']


def test_unknown_usage_keeps_incomplete_attempt_and_no_submission(tmp_path):
    from zoo.mle_bench_lite.arbor_runner import run, FixtureProvider
    class Unknown(FixtureProvider):
        def __call__(self, prompt):
            answer = super().__call__(prompt)
            self.last_usage = None
            return answer
    provider = Unknown()
    report = run(output=tmp_path / 'run', public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_cycles=2, provider=provider, runner=TrustedFixtureRunner())
    assert report['run_state'] == 'execution_failed' and report['error_type'] is not None
    assert report['submission'] is None and report['final_score'] is None
    assert report['search']['attempted'] == report['search']['incomplete'] == 1
    assert report['unresolved_provider_bindings'] and provider.calls == 1


@pytest.mark.linux
def test_linux_frozen_predictions_reject_development_winner_at_admission(tmp_path):
    # Deliberately controlled outputs on synthetic data exercise a false positive;
    # this is an isolation fixture, never evidence of model/benchmark performance.
    import math
    from test_mle_composed import program
    from zoo.mle_bench_lite.arbor_runner import run, FixtureProvider
    public = fixture_public(tmp_path / 'public')
    key = tmp_path / 'key'; key.write_bytes(TEST_ANONYMIZATION_KEY); key.chmod(0o600)
    preview = PublicTrainBundle(public, tmp_path / 'preview', 'spooky-author-identification', 7,
                               anonymization_key=TEST_ANONYMIZATION_KEY, dev_scoring='task_metric')
    codes = [program(preview, cycle=0), program(preview, cycle=2)]
    class Controlled(FixtureProvider):
        def __call__(self, prompt):
            response = super().__call__(prompt)
            request = json.loads(prompt)
            if 'recipe' in request:
                result = json.loads(response)
                result['artifact'] = codes[request['recipe']['hypothesis_binding']['cycle']]
                return json.dumps(result)
            return response
    report = run(output=tmp_path / 'run', public_root=public, task_id='spooky-author-identification',
        max_cycles=2, anonymization_key_path=key, provider=Controlled())
    assert report['run_state'] == 'completed'
    assert report['training_invocations_this_process'] == 2
    assert report['replay_certificate']['passed'] and report['replay_certificate']['external_calls'] == 0
    verdicts = report['stage_trace']['admission']
    assert [v['admit'] for v in verdicts] == [True, False]
    assert report['result']['reporting']['dev_best']['candidate_id'] == verdicts[1]['candidate_id']
    assert report['result']['best_candidate_id'] == report['submission']['candidate_id'] == verdicts[0]['candidate_id']
    assert report['final_score'] == pytest.approx(math.log(.6))
    from core.x1.store import AppendOnlyStore
    evaluations = [r['payload']['evidence']['evidence']['eval_result'] for r in
                   AppendOnlyStore(tmp_path / 'run/composed/x1.jsonl').read('composed_physical_evidence')]
    first = [v for v in evaluations if v['contract']['binding']['candidate_id'] == verdicts[0]['candidate_id']]
    assert {v['contract']['binding']['split_id'] for v in first} == {'dev', 'admission', 'final_audit'}
    assert len({v['contract']['private']['data']['prediction_sha256'] for v in first}) == 1


def test_search_repetition_keeps_data_split_and_program_inputs_fixed(tmp_path):
    from zoo.mle_bench_lite.arbor_runner import run
    public = fixture_public(tmp_path / 'public')
    key = tmp_path / 'key'; key.write_bytes(TEST_ANONYMIZATION_KEY); key.chmod(0o600)
    reports = [run(output=tmp_path / f'run{seed}', public_root=public,
        task_id='spooky-author-identification', split_seed=7, search_seed=seed, max_cycles=1,
        anonymization_key_path=key, runner=TrustedFixtureRunner()) for seed in (0, 2)]
    assert all(report['run_state'] == 'completed' for report in reports)
    assert reports[0]['dataset_identity'] == reports[1]['dataset_identity']
    assert reports[0]['dataset_manifest'] == reports[1]['dataset_manifest']
    for name in ('train.csv', 'predict.csv', 'protocol.json'):
        assert (tmp_path / 'run0/public_inputs' / name).read_bytes() == (
            tmp_path / 'run2/public_inputs' / name).read_bytes()


def test_phase_schemas_do_not_conflict_with_shared_task_text(tmp_path):
    from zoo.mle_bench_lite.arbor_runner import run, FixtureProvider
    class SchemaAware(FixtureProvider):
        def __call__(self, prompt):
            request = json.loads(prompt)
            if request.get('kind') == 'arbor_ideation':
                task = request['observation']['task']
                assert 'Return code only' not in task
                assert 'in artifact' not in task
                assert 'required JSON response' not in task
                assert 'new_ideas and selection' in request['instruction']
            return super().__call__(prompt)
    report = run(output=tmp_path / 'run', public_root=fixture_public(tmp_path / 'public'),
        task_id='spooky-author-identification', max_cycles=1, provider=SchemaAware(), runner=TrustedFixtureRunner())
    assert report['run_state'] == 'completed'
