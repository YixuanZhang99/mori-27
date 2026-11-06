"""Reference iteration capture observes original futures without changing them."""
from concurrent.futures import Future
from types import SimpleNamespace

from zoo.circle_packing.reference_iteration_trace import (capture_reference_iterations, install_prompt_observer,
                                                            record_iteration_request, record_iteration_stage)


def test_capture_preserves_futures_and_reports_failed_and_unresolved_iterations():
    class Controller:
        def __init__(self):
            self.futures = [Future(), Future(), Future()]
        def _submit_iteration(self, iteration, island=None):
            return self.futures[iteration]
    original = Controller._submit_iteration
    controller = Controller()
    with capture_reference_iterations(Controller) as capture:
        assert controller._submit_iteration(0, 0) is controller.futures[0]
        assert controller._submit_iteration(1, 1) is controller.futures[1]
        assert controller._submit_iteration(2, 0) is controller.futures[2]
        controller.futures[0].set_result(SimpleNamespace(iteration=0, parent_id='parent',
            child_program_dict={'id': 'child', 'code': 'candidate code', 'artifacts_json': '{}'},
            artifacts={'mori_stage_request_id': 'a' * 32}, llm_response='sensitive response', error=None, target_island=0))
        controller.futures[1].set_result(SimpleNamespace(iteration=1, parent_id='parent',
            child_program_dict=None, llm_response=None, error='sensitive error', target_island=1))
        trace = capture.snapshot()
    assert Controller._submit_iteration is original
    assert [row['state'] for row in trace['iterations']] == ['candidate', 'worker_error', 'unresolved']
    assert trace['iterations'][0]['parent_id'] == 'parent' and trace['iterations'][0]['child_id'] == 'child'
    assert trace['iterations'][0]['stage_request_id'] == 'a' * 32
    assert 'sensitive response' not in repr(trace) and 'sensitive error' not in repr(trace)
    assert 'candidate code' not in repr(trace)


def test_prompt_observer_preserves_messages_and_records_only_request_digest(tmp_path, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing import reference_iteration_trace
    import json
    monkeypatch.setattr(reference_iteration_trace, '_active_prompt', None)
    class Sampler:
        def build_prompt(self, *, evolution_round):
            return {'system': 'private system', 'user': 'private user'}
    install_prompt_observer(Sampler, tmp_path)
    result = Sampler().build_prompt(evolution_round=3)
    assert result == {'system': 'private system', 'user': 'private user'}
    rows = list(ContinuationStore(tmp_path / 'iteration-prompts.jsonl').read())
    argument = {'host_messages': result, 'host_prompt_ref': 'sha256:' + payload_digest(result)}
    prompt = json.dumps(argument, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    assert rows == [{'kind': 'reference_iteration_prompt', 'payload': {'iteration': 3,
                      'request_sha256': payload_digest({'args': (prompt,), 'kwargs': {}})}}]
    record_iteration_request(result, 'a' * 32)
    request_rows = list(ContinuationStore(tmp_path / 'iteration-requests.jsonl').read())
    assert request_rows == [{'kind': 'reference_iteration_request', 'payload': {'iteration': 3,
                            'request_sha256': rows[0]['payload']['request_sha256'], 'request_id': 'a' * 32}}]
    record_iteration_stage('b' * 32, 'sha256:' + 'c' * 64, stage=1, prior_id=None)
    stage_rows = list(ContinuationStore(tmp_path / 'iteration-stages.jsonl').read())
    assert stage_rows == [{'kind': 'reference_iteration_stage', 'payload': {'iteration': 3,
                          'request_id': 'b' * 32, 'program_ref': 'sha256:' + 'c' * 64, 'stage': 1, 'prior_id': None}}]
    assert 'private system' not in (tmp_path / 'iteration-prompts.jsonl').read_text()
