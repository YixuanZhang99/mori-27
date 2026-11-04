"""Recovery of public-train predictions at a durable native terminal."""
import asyncio
import copy

import pytest

from core.composition.contracts import Proposal
from core.executor.types import Candidate, EvalRequest
from test_mle_composed import fixture_public, program, TrustedFixtureRunner, TASK, TEST_ANONYMIZATION_KEY
from zoo.mle_bench_lite.composed_domain import PublicTrainDomain
from zoo.mle_bench_lite.public_train import PublicTrainBundle


def setup_domain(tmp_path):
    bundle = PublicTrainBundle(fixture_public(tmp_path / 'public'), tmp_path / 'inputs', TASK, 1,
                               anonymization_key=TEST_ANONYMIZATION_KEY)
    root = tmp_path / 'candidates'
    first = PublicTrainDomain(bundle, root, runner=TrustedFixtureRunner())
    proposal = Proposal(Candidate('candidate-1'), program(bundle))
    result = asyncio.run(first.evaluate(proposal, EvalRequest('dev')))
    return bundle, root, first, proposal, result


def test_terminal_state_restores_original_predictions_without_retraining(tmp_path):
    bundle, root, first, proposal, result = setup_domain(tmp_path)
    terminal_state = first.checkpoint_state()
    recovered = PublicTrainDomain(bundle, root, runner=TrustedFixtureRunner())
    recovered.restore_state(terminal_state)
    recovered.materialize(proposal, tmp_path / 'submission.csv', expected_prediction_sha256=
                          result.contract.private.data['prediction_sha256'])
    asyncio.run(recovered.evaluate(proposal, EvalRequest('admission', split_id='admission')))
    assert recovered.training_invocations == 0


@pytest.mark.parametrize('change', ['predictions', 'record', 'state'])
def test_terminal_restore_rejects_changed_candidate_data(tmp_path, change):
    bundle, root, first, proposal, _ = setup_domain(tmp_path)
    terminal_state = copy.deepcopy(first.checkpoint_state())
    path = first.candidate_path(proposal)
    if change == 'predictions':
        with (path / 'predictions.csv').open('a') as stream:
            stream.write('\n')
    elif change == 'record':
        with (path / 'outcome.json').open('a') as stream:
            stream.write(' ')
    else:
        terminal_state['dataset_identity'] = 'different'
    recovered = PublicTrainDomain(bundle, root, runner=TrustedFixtureRunner())
    with pytest.raises(ValueError):
        recovered.restore_state(terminal_state)
    assert recovered.training_invocations == 0


def test_durable_terminal_adopts_state_without_invoking_evaluator(tmp_path):
    from core.executor.types import EvidenceRecord
    from test_composed_recovery import base, resumed

    bundle, root, first, proposal, result = setup_domain(tmp_path)
    store, checkpoint = base(tmp_path)
    identity = {'candidate_id': proposal.candidate.id, 'split': 'dev'}
    async def completed():
        return EvidenceRecord(proposal.candidate.id, result)
    original, elapsed = asyncio.run(store.evaluation_call(identity, completed, domain=first))
    before = store.path.read_bytes()
    recovered = PublicTrainDomain(bundle, root, runner=TrustedFixtureRunner())
    async def forbidden():
        raise AssertionError('durable evaluation was executed twice')
    replayed, replay_elapsed = asyncio.run(resumed(store, checkpoint).evaluation_call(
        identity, forbidden, domain=recovered))
    assert replayed == original and replay_elapsed == elapsed
    assert store.path.read_bytes() == before
    recovered.materialize(proposal, tmp_path / 'submission.csv', expected_prediction_sha256=
                          result.contract.private.data['prediction_sha256'])
    assert recovered.training_invocations == 0


@pytest.mark.parametrize("tamper", [False, True])
def test_public_framework_resumes_after_evaluation_terminal(tmp_path, monkeypatch, tamper):
    import json
    from core.composition.recovery import ContinuationStore
    from test_configured_construction import build, profile, ConstructorProvider, records
    from test_materialization_recovery import Crash

    bundle = PublicTrainBundle(fixture_public(tmp_path / 'public'), tmp_path / 'inputs', TASK, 1,
                               anonymization_key=TEST_ANONYMIZATION_KEY)
    root = tmp_path / 'candidates'
    class CodeProvider(ConstructorProvider):
        def __call__(self, prompt):
            value = json.loads(super().__call__(prompt))
            value['artifact'] = program(bundle)
            return json.dumps(value)
    first_domain = PublicTrainDomain(bundle, root, runner=TrustedFixtureRunner())
    provider = CodeProvider()
    original = ContinuationStore._write
    def cut(self, row):
        original(self, row)
        if row['kind'] == 'governed_evaluation_completed':
            raise Crash('evaluation terminal')
    monkeypatch.setattr(ContinuationStore, '_write', cut)
    first = build(tmp_path / 'run', assembly=profile(), provider=provider, domain=first_domain, generations=0)
    with pytest.raises(Crash):
        first.evolve('Generate a CSV prediction program')
    assert first_domain.training_invocations == 1
    monkeypatch.setattr(ContinuationStore, '_write', original)
    if tamper:
        prediction_file = next(root.glob('*/predictions.csv'))
        with prediction_file.open('a') as stream:
            stream.write('\n')
    recovered_domain = PublicTrainDomain(bundle, root, runner=TrustedFixtureRunner())
    recovered = build(tmp_path / 'run', assembly=profile(), provider=ConstructorProvider(forbidden=True),
                      domain=recovered_domain, generations=0, resume=True)
    if tamper:
        with pytest.raises(ValueError, match='predictions changed') as caught:
            recovered.evolve('Generate a CSV prediction program')
        assert 'durable continuation diverged' in str(caught.value.__cause__)
        assert recovered_domain.training_invocations == 0 and provider.calls == 1
        return
    result = recovered.evolve('Generate a CSV prediction program')
    chosen = result['best_candidate_id']
    evidence = next(r for r in records(recovered, 'composed_evidence') if r['proposal']['candidate']['id'] == chosen)
    from core.executor.types import Candidate
    proposal = Proposal(Candidate(**evidence['proposal']['candidate']), evidence['proposal']['artifact'])
    recovered_domain.materialize(proposal, tmp_path / 'submission.csv', expected_prediction_sha256=
        evidence['evidence']['eval_result']['contract']['private']['data']['prediction_sha256'])
    assert recovered_domain.training_invocations == 0
    assert provider.calls == 1
    assert len(records(recovered, 'governed_evaluation_completed')) == 1
