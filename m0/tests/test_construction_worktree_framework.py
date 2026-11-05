"""Public configured construction binds Git publication to the scored artifact."""
import hashlib
import json

from core.composition.defaults import execution_profile
from core.loop import Framework, LoopConfig
from test_configured_construction import ConstructorProvider, ForbiddenDomain, build, profile, records
from test_composed_budget import Domain, TASK
from test_construction_worktree import git


def test_public_native_evaluation_uses_one_git_published_artifact_for_every_split(tmp_path):
    assembly = profile(role='coder')
    assembly['executor'] = {'name': 'git_artifact'}
    assembly['admission'] = {'name': 'layered'}
    raw, domain = ConstructorProvider(), Domain()
    fw = build(tmp_path, assembly=assembly, provider=raw, domain=domain, generations=0)
    result = fw.evolve(TASK)
    materialized = records(fw, 'materialization_completed')
    assert raw.calls == len(materialized) == 1
    descriptor = materialized[0]['artifact']
    repo = materialized[0]['identity']['artifact_backend']['base_repo']
    assert descriptor['kind'] == 'git_text_v1'
    artifact = git(repo, 'show', descriptor['commit'] + ':' + descriptor['artifact_path'])
    assert {c['artifact'] for c in domain.calls} == {artifact}
    assert {c['request']['split_id'] for c in domain.calls} == {'dev', 'admission', 'final_audit'}
    assert result['execution']['main']['artifacts']
    assert fw.replay(adapter_factory=lambda path, store: (
        ConstructorProvider(forbidden=True), ForbiddenDomain()))['replay_certificate']['passed']


def test_recommended_profile_defaults_to_managed_git_and_resumes(tmp_path):
    assembly = execution_profile()
    assert assembly['schema_version'] == 2
    assert assembly['executor']['name'] == 'git_artifact'
    assert assembly['budget']['name'] == 'hierarchical'
    first = build(tmp_path, assembly=assembly, generations=1, stop=0)
    first.evolve(TASK)
    original = records(first, 'materialization_completed')[0]
    raw = ConstructorProvider()
    resumed = build(tmp_path, assembly=assembly, provider=raw, generations=1, resume=True)
    resumed.evolve(TASK)
    assert raw.calls == 1
    assert records(resumed, 'materialization_completed')[0] == original
    assert resumed.replay()['replay_certificate']['passed']


def test_command_evaluations_start_from_original_artifact_commit_and_replay_without_workers(tmp_path):
    from pathlib import Path
    from test_composed_worktree_framework import prepare, profile as command_profile
    prepare(tmp_path)
    assembly = command_profile(tmp_path)
    assembly.update(schema_version=2, execution=profile()['execution'])
    opts = assembly['executor']['options']
    opts.pop('run_root')
    assembly['executor']['name'] = 'git_artifact'

    class CodeProvider(ConstructorProvider):
        def __call__(self, prompt):
            value = json.loads(super().__call__(prompt))
            value['artifact'] = 'VALUE = 0.7\n'
            return json.dumps(value)

    raw = CodeProvider()
    fw = build(tmp_path / 'run', assembly=assembly, provider=raw, generations=0)
    fw.evolve(TASK)
    materialized = records(fw, 'materialization_completed')[0]
    descriptor = materialized['artifact']
    assert raw.calls == 1
    operations = records(fw, 'worktree_operation_prepared')
    assert len(operations) == 3
    for operation in operations:
        assert operation['binding']['executor']['base_commit'] == descriptor['commit']
        assert operation['binding']['request']['resume_from'] is None
    count_before = [p.read_bytes() for p in (tmp_path / 'run').rglob('invocations.txt')]
    assert len(count_before) == 3 and count_before == [b'called\n'] * 3
    assert fw.replay()['replay_certificate']['passed']
    assert [p.read_bytes() for p in (tmp_path / 'run').rglob('invocations.txt')] == count_before


def crash_scenario(root, cut, command, resume):
    import os
    import signal
    from pathlib import Path
    from core.composition.recovery import ContinuationStore
    from test_composed_worktree_framework import profile as command_profile

    root = Path(root)
    if command:
        assembly = command_profile(root, layered=False)
        assembly.update(schema_version=2, execution=profile()['execution'])
        assembly['executor']['options'].pop('run_root')
        assembly['executor']['name'] = 'git_artifact'
    else:
        assembly = profile()
        assembly['executor'] = {'name': 'git_artifact'}

    class LoggedProvider(ConstructorProvider):
        def __call__(self, prompt):
            assert not resume, 'resume attempted a replacement provider call'
            with (root / 'provider-count.txt').open('a') as f:
                f.write('called\n'); f.flush(); os.fsync(f.fileno())
            value = json.loads(super().__call__(prompt))
            value['artifact'] = 'VALUE = 0.7\n'
            return json.dumps(value)

    original = ContinuationStore._write
    def interrupted(self, row):
        original(self, row)
        if not resume and row['kind'] == cut:
            os.kill(os.getpid(), signal.SIGKILL)
    ContinuationStore._write = interrupted
    fw = build(root / 'run', assembly=assembly, provider=LoggedProvider(), generations=0, resume=resume)
    fw.evolve(TASK)
    assert fw.replay()['replay_certificate']['passed']


import pytest


@pytest.mark.parametrize('command,cut', [
    (False, 'composed_provider_completed'), (False, 'worktree_artifact_plan'),
    (False, 'worktree_artifact_commit'), (True, 'worktree_process_started'),
    (True, 'worktree_process_completed'), (True, 'worktree_evidence')])
def test_public_sigkill_recovers_original_generation_commit_and_worker(tmp_path, command, cut):
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path
    from core.executor.process_identity import process_alive
    from test_composed_worktree_framework import prepare
    if command:
        prepare(tmp_path)
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([
        str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)])}
    script = 'import sys; from test_construction_worktree_framework import crash_scenario; crash_scenario(sys.argv[1],sys.argv[2],sys.argv[3]=="yes",sys.argv[4]=="resume")'
    args = [sys.executable, '-c', script, str(tmp_path), cut, 'yes' if command else 'no']
    try:
        first = subprocess.run([*args, 'first'], env=env, capture_output=True, text=True, timeout=20)
        assert first.returncode == -signal.SIGKILL, first.stderr
        plans = list((tmp_path / 'run' / 'construction-artifacts').rglob('plan.json'))
        previous_commit = json.loads(plans[0].read_text())['descriptor']['commit'] if plans else None
        restored = subprocess.run([*args, 'resume'], env=env, capture_output=True, text=True, timeout=20)
        assert restored.returncode == 0, restored.stderr
        assert (tmp_path / 'provider-count.txt').read_text() == 'called\n'
        original = [json.loads(s)['payload'] for s in (tmp_path / 'run' / 'x1.jsonl').read_text().splitlines()
                    if json.loads(s)['kind'] == 'materialization_completed']
        assert len(original) == 1
        if previous_commit:
            assert original[0]['artifact']['commit'] == previous_commit
        if command:
            invocations = list((tmp_path / 'run').rglob('invocations.txt'))
            assert len(invocations) == 1 and invocations[0].read_text() == 'called\n'
    finally:
        for path in (tmp_path / 'run').rglob('supervisor.json'):
            value = json.loads(path.read_text())
            if process_alive(value['pid'], value['start_ticks']):
                try:
                    os.killpg(value['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_git_control_materializations_have_distinct_managed_repositories(tmp_path):
    from test_construction_controls import build as governed_build
    template, providers, domains, main = governed_build(tmp_path)
    assembly = template._composed.assembly.to_dict()
    assembly['executor'] = {'name': 'git_artifact'}
    fw = Framework.from_profile(assembly, main, Domain(), template._composed.cfg, str(tmp_path),
                                component_registry=template._composed.registry)
    fw.evolve(TASK)
    materializations = records(fw, 'materialization_completed')
    repositories = {m['identity']['artifact_backend']['base_repo'] for m in materializations}
    assert len(repositories) == 4
    assert main.calls == 3 and [p.calls for p in providers] == [1, 1, 1]
    assert fw.replay()['replay_certificate']['passed']


def test_command_wallclock_cannot_be_underreported_by_producer(tmp_path):
    from test_composed_budget import physical_operations
    from test_composed_worktree_framework import prepare, profile as command_profile
    prepare(tmp_path)
    script = tmp_path / 'repo' / 'evaluate.py'
    script.write_text(script.read_text().replace("['token','node','eval_count']", "['token','node','eval_count','wallclock']"))
    git(tmp_path / 'repo', 'add', 'evaluate.py')
    git(tmp_path / 'repo', 'commit', '--quiet', '-m', 'producer claims zero wall time')
    assembly = command_profile(tmp_path, layered=False, physical_wall=True, delay=0.05)
    assembly.update(schema_version=2, execution=profile()['execution'])
    assembly['executor']['options'].pop('run_root')
    assembly['executor']['name'] = 'git_artifact'
    assembly['domain']['options']['measured_cost_units'].append('wallclock')
    class CodeProvider(ConstructorProvider):
        def __call__(self, prompt):
            value = json.loads(super().__call__(prompt))
            value['artifact'] = 'VALUE = 0.7\n'
            return json.dumps(value)
    fw = build(tmp_path / 'run', assembly=assembly, provider=CodeProvider(), generations=0)
    fw.evolve(TASK)
    actual = next(o['actual']['wallclock'] for o in physical_operations(fw) if o['intent']['operation'] == 'dev')
    original = records(fw, 'worktree_process_completed')[0]['wall_seconds']
    assert actual >= original > 0.05


def test_governed_git_command_reconciles_supervisor_wallclock(tmp_path, monkeypatch):
    from test_composed_budget import options
    from test_composed_worktree_framework import prepare
    from test_governed_worktree import BoundLocalProvider, governed_worktree
    prepare(tmp_path)
    script = tmp_path / 'repo' / 'evaluate.py'
    script.write_text(script.read_text().replace("['token','node','eval_count']", "['token','node','eval_count','wallclock']"))
    git(tmp_path / 'repo', 'add', 'evaluate.py')
    git(tmp_path / 'repo', 'commit', '--quiet', '-m', 'explicit producer wall meter')
    original = BoundLocalProvider.__call__
    def generate(self, prompt):
        artifact = original(self, prompt)
        return json.dumps({'artifact': artifact, 'hypothesis': json.loads(prompt)['hypothesis']})
    monkeypatch.setattr(BoundLocalProvider, '__call__', generate)
    template, main, controls = governed_worktree(tmp_path)
    assembly = template._composed.assembly.to_dict()
    assembly.update(schema_version=2, execution=profile()['execution'])
    assembly['executor']['name'] = 'git_artifact'
    assembly['executor']['options'].pop('run_root')
    assembly['budget']['options'] = options(units={'token': 10, 'node': 0, 'eval_count': 1, 'wallclock': 10.0})
    assembly['domain']['options']['measured_cost_units'].append('wallclock')
    control = assembly['governance']['controls']
    control['domain']['options']['measured_cost_units'].append('wallclock')
    for phase in control['reservations'].values():
        phase['wallclock'] = 10.0
    fw = Framework.from_profile(assembly, main, None, template._composed.cfg, str(tmp_path / 'run'),
                                component_registry=template._composed.registry)
    result = fw.evolve('Verify independent command controls and original process measurements')
    assert result['governance']['completed'] == 3
    assert result['governance']['budget']['reconciled']
    assert fw.replay()['replay_certificate']['passed']
