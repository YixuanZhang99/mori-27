"""Reference recovery reads only bounded worker journals and never starts work."""
import os

import pytest


def test_missing_worker_journal_is_rejected_without_creating_files(tmp_path):
    from zoo.circle_packing.reference_recovery import read_worker_journal
    before = list(tmp_path.iterdir())
    with pytest.raises(ValueError, match='journal'):
        read_worker_journal(tmp_path)
    assert list(tmp_path.iterdir()) == before


def test_worker_journal_rejects_symlinks_hardlinks_and_oversize(tmp_path):
    from zoo.circle_packing.reference_recovery import read_worker_journal
    journal = tmp_path / 'worker.jsonl'
    target = tmp_path / 'other'
    target.write_text('{}\n')
    journal.symlink_to(target)
    with pytest.raises(ValueError, match='journal'):
        read_worker_journal(tmp_path)
    journal.unlink()
    os.link(target, journal)
    with pytest.raises(ValueError, match='journal'):
        read_worker_journal(tmp_path)
    journal.unlink()
    journal.write_bytes(b'0' * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match='journal'):
        read_worker_journal(tmp_path)


def test_worker_journal_requires_one_start_and_one_terminal_in_order(tmp_path):
    from zoo.circle_packing.reference_recovery import read_worker_journal
    journal = tmp_path / 'worker.jsonl'
    for contents in ('{}\n', '{"kind":"executor_process_finished","payload":{}}\n',
                     '{"kind":"executor_process_finished","payload":{}}\n'
                     '{"kind":"executor_process_started","payload":{}}\n',
                     '{"kind":"executor_process_started","payload":{}}\n'
                     '{"kind":"executor_process_started","payload":{}}\n'
                     '{"kind":"executor_process_finished","payload":{}}\n'):
        journal.write_text(contents)
        with pytest.raises(ValueError, match='journal'):
            read_worker_journal(tmp_path)
