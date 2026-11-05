"""Real process-crash windows for governed native invocation adoption."""
from __future__ import annotations
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.composition.recovery import ContinuationStore
from core.llm import UsageError
from test_composed_budget import Domain, TASK
from test_governed_runtime import FreshProvider, governed

pytestmark = pytest.mark.linux


def record_call(root, lane, kind):
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'actual-calls.jsonl').open('a') as stream:
        stream.write(json.dumps({'lane': lane, 'kind': kind}) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def calls(root):
    path = root / 'actual-calls.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class CountingProvider(FreshProvider):
    def __init__(self, root, lane, crash=None):
        super().__init__()
        self.root, self.lane, self.crash = root, lane, crash

    def __call__(self, prompt):
        record_call(self.root, self.lane, 'provider')
        if self.lane == 'control' and self.crash == 'unknown_provider':
            os.kill(os.getpid(), signal.SIGKILL)
        return super().__call__(prompt)


class CountingDomain(Domain):
    def __init__(self, root, lane, crash=None):
        super().__init__()
        self.root, self.lane, self.crash = root, lane, crash

    async def evaluate(self, proposal, request):
        record_call(self.root, self.lane, 'evaluation')
        if self.lane == 'control' and self.crash == 'unknown_evaluation':
            os.kill(os.getpid(), signal.SIGKILL)
        return await super().evaluate(proposal, request)


def build(root, *, resume=False, crash=None):
    fw, _, _, _, _ = governed(root, resume=resume,
        provider_factory=lambda: CountingProvider(root, 'control', crash),
        domain_factory=lambda: CountingDomain(root, 'control', crash))
    fw.llm = fw._composed.llm = CountingProvider(root, 'main')
    fw.evaluator = fw._composed.evaluator = CountingDomain(root, 'main')
    return fw


def owner(root, point):
    original_write = ContinuationStore._write
    def write_and_crash(self, record):
        original_write(self, record)
        kind, data = record['kind'], record['payload']
        kill = (point == 'provider_completed' and kind == 'composed_provider_completed') \
            or (point == 'operator_outcome' and kind == 'governed_operator_outcome') \
            or (point == 'evaluation_completed' and kind == 'governed_evaluation_completed')
        if point in {'operator_settle', 'evaluation_settle'}:
            phase = 'operator' if point == 'operator_settle' else 'evaluation'
            kill = kind == 'hierarchical_budget' and data['event'] == 'settle' \
                and data['data']['intent_id'] == f'control:control-0000:{phase}'
        if kill:
            os.kill(os.getpid(), signal.SIGKILL)
    ContinuationStore._write = write_and_crash
    build(root, crash=point).evolve(TASK)


def crash_owner(root, point):
    env = dict(os.environ, PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE='1')
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
        '--owner', str(root), point], cwd=PROJECT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = process.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        pytest.fail(f'governed owner failed to reach {point}: {stdout}\n{stderr}')
    assert process.returncode == -signal.SIGKILL, (point, stdout, stderr)


@pytest.mark.parametrize('point', ['provider_completed', 'operator_outcome', 'operator_settle',
                                  'evaluation_completed', 'evaluation_settle'])
def test_native_sigkill_adopts_durable_outcome_and_settles_exactly_once(tmp_path, point):
    crash_owner(tmp_path, point)
    assert sum(row['kind'] == 'provider' for row in calls(tmp_path)) == 1
    resumed = build(tmp_path, resume=True)
    result = resumed.evolve(TASK)
    actual = calls(tmp_path)
    for lane in ('main', 'control'):
        for kind in ('provider', 'evaluation'):
            assert actual.count({'lane': lane, 'kind': kind}) == 3, (point, actual)
    audit = result['governance']
    assert audit['completed'] == 3 and audit['failed'] == audit['unresolved'] == 0
    assert audit['budget']['physical_totals'] == {'token': 72, 'node': 6, 'eval_count': 6}
    events = [row['payload'] for row in resumed.store.read('hierarchical_budget')]
    settled = [event['data']['intent_id'] for event in events if event['event'] == 'settle']
    assert len(settled) == len(set(settled))
    assert audit['budget']['open_intents'] == []


@pytest.mark.parametrize('point', ['unknown_provider', 'unknown_evaluation'])
def test_native_sigkill_without_authoritative_completion_never_retries(tmp_path, point):
    crash_owner(tmp_path, point)
    before = calls(tmp_path)
    assert before.count({'lane': 'control', 'kind': 'provider'}) == 1
    assert before.count({'lane': 'control', 'kind': 'evaluation'}) == (point == 'unknown_evaluation')
    resumed = build(tmp_path, resume=True)
    with pytest.raises((ValueError, UsageError), match='completion|retry|continuation|unresolved'):
        resumed.evolve(TASK)
    assert calls(tmp_path) == before


if __name__ == '__main__':
    assert len(sys.argv) == 4 and sys.argv[1] == '--owner'
    owner(Path(sys.argv[2]), sys.argv[3])
