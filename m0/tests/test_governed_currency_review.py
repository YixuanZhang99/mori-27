"""Independent adversarial review of the additive currency journal."""
from __future__ import annotations

import pytest

from zoo.mle_bench_lite.cny_budget import CampaignBudget
from test_governed_currency import RUN, PLAN, binding, migrated, obligations, rehash_events, usage


def test_rehashed_legacy_settlement_cannot_complete_a_governed_reservation(tmp_path):
    ledger = migrated(tmp_path)
    ledger.protect_run(RUN, PLAN, obligations(ledger))
    ledger.admit_call(RUN, 'control', 'control-0000', binding(), ledger.quote_call(4096))
    ledger.settle('call', usage(), 'e' * 64)

    def downgrade(events):
        settlement = events[-1]
        assert settlement['kind'] == 'governed_settle'
        settlement['kind'] = 'settle'
        del settlement['schema_version']
        del settlement['bound_violation']

    rehash_events(ledger.path, downgrade)
    with pytest.raises(ValueError):
        CampaignBudget(ledger.path)
    with pytest.raises(ValueError):
        ledger.audit_run(RUN, PLAN)
