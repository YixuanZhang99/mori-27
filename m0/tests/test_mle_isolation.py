"""Regressions for real-pilot isolation, independent of benchmark scores."""
import csv
import json
import random
from collections import Counter

from zoo.mle_bench_lite.public_train import PublicTrainBundle, SPLITS
from test_mle_composed import fixture_public


def public_metadata_attack(inputs):
    """Attacker reads only the three files visible to generated code."""
    protocol = json.loads((inputs / 'protocol.json').read_text())
    with (inputs / 'train.csv').open() as stream:
        counts = Counter(row['target'] for row in csv.DictReader(stream))
    with (inputs / 'predict.csv').open() as stream:
        prediction_count = sum(1 for _ in csv.DictReader(stream))
    rng = random.Random(protocol['seed'])
    for _, count in sorted(counts.items()):
        original_indices = list(range(count + 4))
        rng.shuffle(original_indices)
    mixed = [(split, label) for split in ('dev', 'calibration', 'admission', 'final_audit')
             for label in sorted(counts)]
    mixed += [(None, None)] * (prediction_count - len(mixed))
    rng.shuffle(mixed)
    return {f'r{index:08d}': (split, label) for index, (split, label) in enumerate(mixed)
            if label is not None}


def test_public_metadata_cannot_reconstruct_all_held_out_labels_and_splits(tmp_path):
    source = fixture_public(tmp_path / 'public', task='leaf-classification', rows_per_class=8)
    bundle = PublicTrainBundle(source, tmp_path / 'inputs', 'leaf-classification', 7, anonymization_key=b'k' * 32)
    guessed = public_metadata_attack(bundle.output_root)
    actual = {bundle.local_ids[index]: (split, bundle.labels[index])
              for split in SPLITS for index in bundle.indices[split]}
    assert guessed != actual, 'public seed and counts reconstruct every held-out label and split'


def test_private_permutation_is_shared_only_by_explicit_key(tmp_path):
    source = fixture_public(tmp_path / 'public', task='leaf-classification', rows_per_class=8)
    key = b'k' * 32
    left = PublicTrainBundle(source, tmp_path / 'left', 'leaf-classification', 7, anonymization_key=key)
    right = PublicTrainBundle(source, tmp_path / 'right', 'leaf-classification', 7, anonymization_key=key)
    other = PublicTrainBundle(source, tmp_path / 'other', 'leaf-classification', 7, anonymization_key=b'z' * 32)
    assert left.manifest == right.manifest
    assert left.local_ids != other.local_ids
    assert left.identity != other.identity
    assert all(key not in path.read_bytes() for path in left.output_root.iterdir())
    assert key.decode() not in json.dumps(left.manifest)


def test_anonymization_key_survives_resume_and_missing_or_malformed_key_refuses(tmp_path):
    import pytest
    from zoo.mle_bench_lite import public_train
    key_path = tmp_path / 'private.key'
    key = public_train.load_anonymization_key(key_path, create=True)
    assert len(key) == 32
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert public_train.load_anonymization_key(key_path) == key
    key_path.unlink()
    with pytest.raises(ValueError, match='anonymization key'):
        public_train.load_anonymization_key(key_path)
    key_path.write_bytes(b'short')
    with pytest.raises(ValueError, match='anonymization key'):
        public_train.load_anonymization_key(key_path)


def test_changed_private_key_cannot_rewrite_existing_inputs(tmp_path):
    import pytest
    source = fixture_public(tmp_path / 'public', rows_per_class=8)
    PublicTrainBundle(source, tmp_path / 'inputs', 'spooky-author-identification', 7,
                      anonymization_key=b'k' * 32)
    before = {path.name: path.read_bytes() for path in (tmp_path / 'inputs').iterdir()}
    with pytest.raises(ValueError, match='changed'):
        PublicTrainBundle(source, tmp_path / 'inputs', 'spooky-author-identification', 7,
                          anonymization_key=b'z' * 32)
    assert before == {path.name: path.read_bytes() for path in (tmp_path / 'inputs').iterdir()}


def test_direct_agent_refuses_unusable_sandbox_before_generation(tmp_path):
    import pytest
    from zoo.mle_bench_lite.composed_agent import run_agent
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    calls = []
    class UnusableSandbox(SandboxRunner):
        def __init__(self):
            pass
        @property
        def manifest_binding(self):
            return {'kind': 'unusable-test-sandbox'}
        def preflight(self, **kwargs):
            raise RuntimeError('sandbox readiness failed')
        def execute(self, workspace, timeout):
            raise RuntimeError('sandbox unavailable')
    class ForbiddenProvider:
        last_usage = {'total_tokens': 0}
        def manifest_binding(self):
            return {'kind': 'no-paid-calls-allowed'}
        def __call__(self, prompt):
            calls.append(prompt)
            raise AssertionError('generation began before sandbox readiness')
    workspace = tmp_path / 'workspace'
    fixture_public(workspace / 'data')
    with pytest.raises(RuntimeError, match='sandbox readiness'):
        run_agent(workspace=workspace, task_id='spooky-author-identification', model='fixture',
                  api_base='https://example.invalid', provider=ForbiddenProvider(), runner=UnusableSandbox())
    assert calls == []
    assert not (tmp_path / 'agent_artifacts').exists()


def test_readiness_probe_executes_imports_instead_of_only_checking_paths(tmp_path):
    import sys
    import pytest
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from test_mle_composed import TrustedFixtureRunner
    class LocalProbe(SandboxRunner):
        def __init__(self):
            self.interpreter = sys.executable
        execute = TrustedFixtureRunner.execute
    probe = LocalProbe()
    with pytest.raises(RuntimeError, match='sandbox readiness'):
        probe.preflight(required_modules=('mori27_nonexistent_dependency',))
    result = probe.preflight(required_modules=('csv', 'json'))
    assert result['ready']
    assert result['modules'] == ['csv', 'json']
