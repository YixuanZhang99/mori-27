"""Untrusted priorities run outside the trusted scorer process."""
import shutil

import numpy as np
import pytest

from core.tasks.funsearch_binpacking import score_instance
from core.tasks.funsearch_priority_sandbox import SandboxedPriority

TEMPLATE = 'def priority(item, bins):\n    return -(bins - item)\n'


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
def test_priority_isolated_from_host_environment_and_files(tmp_path, monkeypatch):
    secret = tmp_path / 'host-secret'
    secret.write_text('fixture-canary')
    monkeypatch.setenv('MORI_FIXTURE_SECRET', 'fixture-canary')
    code = f'''def priority(item, bins):
    import os
    assert os.getenv('MORI_FIXTURE_SECRET') is None
    try:
        open({str(secret)!r}).read()
    except OSError:
        pass
    else:
        raise RuntimeError('host file was visible')
    return -(bins - item)
'''
    with SandboxedPriority(TEMPLATE, code, timeout=10) as priority:
        assert score_instance({'capacity': 10, 'num_items': 4, 'items': [6, 4, 6, 4]}, priority) == -2
    assert secret.read_text() == 'fixture-canary'


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
def test_priority_timeout_stops_unresponsive_child():
    code = 'def priority(item, bins):\n    while True:\n        pass\n'
    with SandboxedPriority(TEMPLATE, code, timeout=1) as priority:
        with pytest.raises(TimeoutError):
            priority(1, np.array([5]))


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='requires bubblewrap')
def test_invalid_output_and_candidate_source_are_rejected():
    with pytest.raises(ValueError, match='contract'):
        SandboxedPriority(TEMPLATE, 'import os\ndef priority(item, bins):\n    return bins\n', timeout=3)
    with SandboxedPriority(TEMPLATE, 'def priority(item, bins):\n    return [float("nan")]\n', timeout=3) as priority:
        with pytest.raises(ValueError):
            priority(1, np.array([5]))
