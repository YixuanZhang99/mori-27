"""A claimed pilot cannot authorize work in an unsupervised process."""
import pytest
import os
from pathlib import Path
import sys

from core.composition.recovery import ContinuationStore
from core.executor.process import ProcessJournal


def test_missing_supervisor_identity_fails_before_any_claim_is_used(monkeypatch):
    from zoo.circle_packing.supervisor_attestation import require_supervised_process
    monkeypatch.delenv('MORI_SUPERVISOR_TARGET', raising=False)
    with pytest.raises(ValueError, match='supervisor'):
        require_supervised_process(None, None)


def test_contained_process_receives_its_own_published_target_path(tmp_path):
    journal = ProcessJournal(ContinuationStore(tmp_path / 'controller.jsonl'))
    process, record = journal.launch(
        [sys.executable, '-c', 'import os; print(os.environ.get("MORI_SUPERVISOR_TARGET", ""))'],
        tmp_path, dict(os.environ), 10, {'containment_required': True, 'candidate_id': 'test', 'attempt': 1})
    result = journal.wait(process, record, before_record=lambda: None)
    assert result['returncode'] == 0
    assert Path(record['stdout_path']).read_text().strip() == record['target_path']
