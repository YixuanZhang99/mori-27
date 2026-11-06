"""Only the first matched pair may enter the real pilot before its audit."""
import pytest

from zoo.circle_packing.host_runtime import _require_reference_live_gate
from zoo.circle_packing.mori_live_worker import _require_live_gate


@pytest.mark.parametrize('seed', [1, 2, -1, 3, True, None, '0'])
def test_first_pair_gate_rejects_later_or_invalid_seeds(seed):
    with pytest.raises(ValueError, match='gate'):
        _require_live_gate({'seed': seed})
    with pytest.raises(ValueError, match='gate'):
        _require_reference_live_gate(seed)


def test_first_pair_gate_accepts_seed_zero():
    _require_live_gate({'seed': 0})
    _require_reference_live_gate(0)
