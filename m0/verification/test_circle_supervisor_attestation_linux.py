"""Exercise real supervisor identity with a delegated cgroup and no network."""
import json
import os
from pathlib import Path
import sys
import time

import pytest

from core.composition.recovery import ContinuationStore
from core.executor.process import ProcessJournal
from core.executor.process_identity import start_ticks
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.cell_containment import contained_command, delegated_cell_group, finish_cell_group
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.supervisor_attestation import require_supervised_process
from zoo.mle_bench_lite.cny_budget import CampaignBudget

pytestmark = pytest.mark.linux


def test_original_contained_target_is_accepted_but_copied_claim_is_not(tmp_path, monkeypatch):
    ledger = CampaignBudget.create_fixture(tmp_path / 'campaign.db')
    ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],
                             expected_head=ledger.snapshot()['journal_head'])
    ref = 'sha256:' + 'a' * 64
    clock_path = tmp_path / 'clock.jsonl'
    clock = CellDeadline.start(ContinuationStore(clock_path), lifecycle=CellLifecycle(ledger),
                               cell_id='mori-0', plan_ref=ref, seconds=120)
    root = tmp_path / 'worker'
    root.mkdir(mode=0o700)
    config = {'ledger': str(ledger.path), 'ref': ref, 'clock': str(clock_path), 'seed': 0}
    (root / 'config.json').write_text(json.dumps(config))
    code = '''import sys,time
from pathlib import Path
from core.composition.recovery import ContinuationStore
from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
from zoo.circle_packing.supervisor_attestation import require_supervised_process
from zoo.mle_bench_lite.cny_budget import CampaignBudget
ledger=CampaignBudget(sys.argv[1])
clock=CellDeadline.restore(ContinuationStore(sys.argv[2]), lifecycle=CellLifecycle(ledger),
                           cell_id='mori-0', plan_ref=sys.argv[3], seconds=120)
require_supervised_process(ledger, clock)
Path(sys.argv[4]).write_text('ready')
while not Path(sys.argv[5]).exists(): time.sleep(.01)
'''
    with delegated_cell_group() as group:
        info = group.stat()
        binding = {'schema_version': 1, 'cell_id': 'mori-0', 'deadline_ref': clock._record['record_sha256'],
                   'config_sha256': payload_digest(config), 'directory': str(root),
                   'entry': 'zoo.circle_packing.mori_live_worker', 'containment_group': str(group),
                   'containment_identity': {'device': info.st_dev, 'inode': info.st_ino},
                   'supervisor_pid': os.getpid(), 'supervisor_start_ticks': start_ticks(os.getpid()),
                   'boot_id': clock._record['boot_id']}
        worker_ref = payload_digest(binding)
        ledger.claim_cell_worker('mori-0', clock._record['record_sha256'], worker_ref)
        ready, release = root / 'ready', root / 'release'
        command = contained_command(group, [sys.executable, '-c', code, str(ledger.path), str(clock_path),
                                             ref, str(ready), str(release)])
        journal = ProcessJournal(ContinuationStore(root / 'controller.jsonl'))
        process, record = journal.launch(command, root, {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
            30, {'candidate_id': 'test', 'attempt': 1, 'worker_ref': worker_ref,
                 'containment_required': True, 'containment_binding': binding},
            die_with_parent=True, absolute_deadline={'boot_id': clock._record['boot_id'],
                'deadline_ns': clock._record['start_ns'] + 120_000_000_000})
        try:
            until = time.monotonic() + 20
            while not ready.exists() and process.poll() is None and time.monotonic() < until:
                time.sleep(.02)
            assert ready.exists(), Path(record['stderr_path']).read_text()
            monkeypatch.setenv('MORI_SUPERVISOR_TARGET', record['target_path'])
            with pytest.raises(ValueError, match='target identity'):
                require_supervised_process(ledger, clock)
            release.write_text('go')
            result = journal.wait(process, record, before_record=lambda: finish_cell_group(
                group, expected_identity=binding['containment_identity']))
            assert result['returncode'] == 0
        finally:
            if process.poll() is None:
                journal.terminate_target(record)
                process.kill()
                process.wait()
