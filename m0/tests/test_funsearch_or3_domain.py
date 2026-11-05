"""OR3 development scoring through Framework with an isolated priority process."""
import hashlib
import json
import shutil

import pytest

from test_configured_construction import build
from test_funsearch_framework import CodeProvider, TASK, assembly
from zoo.funsearch_binpacking.domain import OR3DevDomain


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
def test_or3_development_run_scores_and_replays_without_processes(tmp_path, monkeypatch):
    ids = [f'case-{i:02}' for i in range(10)]
    data = {key: {'capacity': 10, 'num_items': 2, 'items': [6, 4]} for key in ids}
    path = tmp_path / 'dev.json'; path.write_text(json.dumps(data))
    template = 'def priority(item, bins):\n    return -(bins - item)\n'
    config = assembly()
    config['policy']['options'].update(case_ids=ids, template=template,
        template_ref='sha256:' + hashlib.sha256(template.encode()).hexdigest())
    config['execution']['constructor']['options']['template'] = template

    class Provider(CodeProvider):
        def __call__(self, prompt):
            value = json.loads(super().__call__(prompt))
            value['artifact'] = template
            return json.dumps(value)

    provider = Provider()
    domain = OR3DevDomain(path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          template=template, timeout=10)
    fw = build(tmp_path / 'run', assembly=config, provider=provider, domain=domain, generations=1)
    fw.evolve(TASK)
    events = [row['payload'] for row in fw.store.read('funsearch_public_candidate')]
    assert len(events) == 2 and all(list(row['scores'].values()) == [-1] * 10 for row in events)
    from core.tasks.funsearch_priority_sandbox import SandboxedPriority
    monkeypatch.setattr(SandboxedPriority, '__enter__', lambda _self: pytest.fail('replay ran candidate'))
    assert fw.replay(TASK)['replay_certificate']['passed']
    assert provider.calls == 2


def test_or3_domain_refuses_changed_dataset(tmp_path):
    data = {f'{i:02}': {'capacity': 10, 'num_items': 1, 'items': [1]} for i in range(10)}
    path = tmp_path / 'dev.json'; path.write_text(json.dumps(data))
    domain = OR3DevDomain(path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          template='def priority(item, bins):\n    return bins\n', timeout=10)
    changed_timeout = OR3DevDomain(path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   template='def priority(item, bins):\n    return bins\n', timeout=20)
    assert domain.evaluator_version != changed_timeout.evaluator_version
    path.write_text('{}')
    with pytest.raises(ValueError, match='dataset'):
        domain.validate_context()


def test_or3_policy_case_set_mismatch_fails_before_provider(tmp_path):
    data = {f'{i:02}': {'capacity': 10, 'num_items': 1, 'items': [1]} for i in range(10)}
    path = tmp_path / 'dev.json'; path.write_text(json.dumps(data))
    template = 'def priority(x):\n    return x\n'
    domain = OR3DevDomain(path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          template=template, timeout=10)
    provider = CodeProvider()
    fw = build(tmp_path / 'run', assembly=assembly(), provider=provider, domain=domain, generations=0)
    with pytest.raises(ValueError, match='frozen FunSearch task'):
        fw.evolve(TASK)
    assert provider.calls == 0


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
def test_timeout_returns_billed_failure_without_candidate_output(tmp_path):
    import asyncio
    from core.composition.contracts import Proposal
    from core.executor.types import Candidate, EvalRequest, EvalStatus
    data = {f'{i:02}': {'capacity': 10, 'num_items': 1, 'items': [1]} for i in range(10)}
    path = tmp_path / 'dev.json'; path.write_text(json.dumps(data))
    template = 'def priority(item, bins):\n    return bins\n'
    domain = OR3DevDomain(path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          template=template, timeout=1)
    proposal = Proposal(Candidate('candidate'), 'def priority(item, bins):\n    while True:\n        pass\n')
    result = asyncio.run(domain.evaluate(proposal, EvalRequest('dev')))
    assert result.status is EvalStatus.FAILED_TO_RUN and result.cost.eval_count == 1
    assert result.metrics == {} and result.text_feedback == 'Sandboxed OR3 candidate failed: TimeoutError'


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
def test_dataset_bytes_are_checked_at_the_actual_read(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
    from core.composition.contracts import Proposal
    from core.executor.types import Candidate, EvalRequest
    data = {f'{i:02}': {'capacity': 10, 'num_items': 1, 'items': [1]} for i in range(10)}
    path = tmp_path / 'dev.json'; path.write_text(json.dumps(data))
    original = path.read_bytes()
    domain = OR3DevDomain(path, expected_sha256=hashlib.sha256(original).hexdigest(),
                          template='def priority(item, bins):\n    return bins\n', timeout=10)
    altered = original.replace(b'"items": [1]', b'"items": [2]', 1)
    real_read = Path.read_bytes
    reads = iter([original, altered, original])
    def changing_read(file):
        return next(reads, original) if file == path else real_read(file)
    monkeypatch.setattr(Path, 'read_bytes', changing_read)
    with pytest.raises(ValueError, match='dataset'):
        asyncio.run(domain.evaluate(Proposal(Candidate('candidate'),
            'def priority(item, bins):\n    return bins\n'), EvalRequest('dev')))
