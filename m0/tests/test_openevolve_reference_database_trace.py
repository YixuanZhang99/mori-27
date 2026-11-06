"""Reference database capture must preserve real admission inputs and outputs."""
import hashlib
import json
import pytest

from core.openevolve_interop import Program, ProgramDatabase
from openevolve.config import DatabaseConfig
from zoo.circle_packing.reference_database_trace import capture_database_additions, replay_database_additions


def test_database_addition_capture_restores_method_and_retains_input(tmp_path):
    database = ProgramDatabase(DatabaseConfig(num_islands=4, random_seed=0))
    program = Program(id='candidate', code='x = 1\n', language='python', metrics={'combined_score': 1.0})
    original = ProgramDatabase.add
    with capture_database_additions(ProgramDatabase, tmp_path) as capture:
        assert database.add(program, iteration=1, target_island=0) == 'candidate'
        result = capture.finish()
    assert ProgramDatabase.add is original
    raw = (tmp_path / 'database-additions.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result['sha256'] and result['count'] == 1
    event = json.loads(raw)['events'][0]
    assert event['program']['id'] == 'candidate' and event['returned'] == 'candidate'
    assert event['before']['state']['best_program_id'] is None
    assert event['after']['state']['best_program_id'] == 'candidate'
    audit = replay_database_additions(tmp_path / 'database-additions.json', expected_sha256=result['sha256'], expected_count=1)
    assert audit['verified_additions'] == 1 and audit['continuity_verified'] is False
    assert audit['final_winner_certified'] is False
    changed = json.loads(raw)
    changed['events'][0]['returned'] = 'different'
    tampered = json.dumps(changed, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    (tmp_path / 'database-additions.json').write_bytes(tampered)
    with pytest.raises(ValueError, match='replay mismatch'):
        replay_database_additions(tmp_path / 'database-additions.json',
                                  expected_sha256=hashlib.sha256(tampered).hexdigest(), expected_count=1)
