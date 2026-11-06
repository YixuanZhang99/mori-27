"""Reference iteration capture observes original futures without changing them."""
from concurrent.futures import Future
from types import SimpleNamespace

from zoo.circle_packing.reference_iteration_trace import capture_reference_iterations


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
            llm_response='sensitive response', error=None, target_island=0))
        controller.futures[1].set_result(SimpleNamespace(iteration=1, parent_id='parent',
            child_program_dict=None, llm_response=None, error='sensitive error', target_island=1))
        trace = capture.snapshot()
    assert Controller._submit_iteration is original
    assert [row['state'] for row in trace['iterations']] == ['candidate', 'worker_error', 'unresolved']
    assert trace['iterations'][0]['parent_id'] == 'parent' and trace['iterations'][0]['child_id'] == 'child'
    assert 'sensitive response' not in repr(trace) and 'sensitive error' not in repr(trace)
    assert 'candidate code' not in repr(trace)
