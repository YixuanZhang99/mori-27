"""Stage requests share the authenticated broker and physical budget."""
import threading
from types import SimpleNamespace

import pytest

from test_openevolve_host_stage_budget import fake_result, stage_budget


def test_broker_routes_qualified_stages_to_physical_budget(tmp_path, monkeypatch, short_socket_dir):
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.host_transport import HostBroker, HostEvaluationClient
    from zoo.circle_packing.host_dispatch import HostDispatchRouter
    import zoo.circle_packing.host_physical as module
    budget = stage_budget(tmp_path)
    monkeypatch.setattr(module, 'run_stage', lambda program, *, stage, **kwargs: fake_result(program, stage))
    stages = HostStageAdmission(budget, runner=object(), workspace=tmp_path / 'sandbox')
    router = HostDispatchRouter(None, stages)
    path = short_socket_dir / 'stages.sock'
    with HostBroker(path, 'a' * 64, router) as broker:
        thread = threading.Thread(target=lambda: [broker.serve_one() for _ in range(2)], daemon=True)
        thread.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        client = HostEvaluationClient(SimpleNamespace(name='fixture'))
        first_id, first = client.evaluate('program', stage=1)
        _, second = client.evaluate('program', stage=2, prior_id=first_id)
        thread.join(timeout=5)
    assert first['status'] == second['status'] == 'ok'
    assert budget.audit_governance()['physical_totals']['eval_count'] == 2


def test_bad_predecessor_is_refused_before_stage_execution(tmp_path, monkeypatch, short_socket_dir):
    from zoo.circle_packing.host_physical import HostStageAdmission
    from zoo.circle_packing.host_transport import HostBroker, HostEvaluationClient
    from zoo.circle_packing.host_dispatch import HostDispatchRouter
    from core.llm import UsageError
    budget = stage_budget(tmp_path)
    stages = HostStageAdmission(budget, runner=object(), workspace=tmp_path / 'sandbox')
    path = short_socket_dir / 'stages.sock'
    with HostBroker(path, 'a' * 64, HostDispatchRouter(None, stages)) as broker:
        thread = threading.Thread(target=broker.serve_one, daemon=True)
        thread.start()
        monkeypatch.setenv('MORI_CIRCLE_BROKER_SOCKET', str(path))
        monkeypatch.setenv('MORI_CIRCLE_BROKER_TOKEN', 'a' * 64)
        client = HostEvaluationClient(SimpleNamespace(name='fixture'))
        with pytest.raises(UsageError):
            client.evaluate('program', stage=2, prior_id='b' * 32)
        thread.join(timeout=5)
    assert budget.audit_governance()['physical_totals']['eval_count'] == 0
