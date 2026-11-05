"""Durable serial campaign admission; no external provider requests."""
import importlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest


def budget_type():
    name = 'zoo.mle_bench_lite.cny_budget'
    assert importlib.util.find_spec(name) is not None, 'persistent CNY admission is missing'
    return importlib.import_module(name).CampaignBudget


def usage(prompt=100, completion=20):
    return {'prompt_tokens': prompt, 'completion_tokens': completion,
            'total_tokens': prompt + completion}


def test_reopen_settlement_releases_only_unused_reservation(tmp_path):
    cls = budget_type()
    ledger = cls.create(tmp_path / 'campaign.db')
    binding = ledger.manifest_binding()
    ledger.reserve('call-1', 'a' * 64, 16384)
    assert ledger.snapshot()['reserved_micro_cny'] == 2228224
    reopened = cls(ledger.path)
    assert reopened.manifest_binding() == binding
    reopened.settle('call-1', usage(), 'b' * 64)
    snapshot = cls(ledger.path).snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] == 360
    assert snapshot['reserved_micro_cny'] == 0
    assert snapshot['remaining_micro_cny'] == 199999640
    assert snapshot['invoice_verified'] is False
    reopened.settle('call-1', usage(), 'b' * 64)  # crash-safe identical replay
    assert reopened.snapshot() == snapshot
    with pytest.raises(ValueError):
        reopened.settle('call-1', usage(completion=21), 'b' * 64)


def test_unknown_operation_blocks_another_instance_and_new_run(tmp_path):
    cls = budget_type()
    ledger = cls.create(tmp_path / 'campaign.db')
    ledger.reserve('lost-response', 'a' * 64, 4096)
    other = cls(ledger.path)
    with pytest.raises(ValueError, match='unresolved'):
        other.reserve('other-run', 'b' * 64, 4096)
    assert other.snapshot()['reserved_micro_cny'] == 2129920
    assert other.snapshot()['pending_calls'] == ['lost-response']


def test_exhaustion_refuses_reservation_without_mutating_history(tmp_path):
    cls = budget_type()
    ledger = cls.create(tmp_path / 'campaign.db', limit_micro_cny=2129920)
    ledger.reserve('first', 'a' * 64, 4096)
    ledger.settle('first', usage(), 'b' * 64)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match='exhausted'):
        ledger.reserve('second', 'c' * 64, 4096)
    assert ledger.snapshot() == before


def test_concurrent_admission_commits_only_one_unresolved_operation(tmp_path):
    cls = budget_type()
    ledger = cls.create(tmp_path / 'campaign.db')
    def attempt(index):
        try:
            cls(ledger.path).reserve(str(index), 'a' * 64, 4096)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as workers:
        assert sum(workers.map(attempt, range(8))) == 1
    assert ledger.snapshot()['reserved_micro_cny'] == 2129920


@pytest.mark.parametrize('invalid', [
    {'total_tokens': 120},
    {'prompt_tokens': True, 'completion_tokens': 20, 'total_tokens': 21},
    {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 121},
    {**usage(), 'completion_tokens_details': {'reasoning_tokens': 21}},
    {**usage(), 'prompt_cache_hit_tokens': 80, 'prompt_cache_miss_tokens': 30},
    {**usage(), 'prompt_tokens_details': {'cached_tokens': 101}},
    usage(prompt=1048577), usage(completion=4097),
])
def test_invalid_or_out_of_policy_usage_retains_full_reservation(tmp_path, invalid):
    ledger = budget_type().create(tmp_path / 'campaign.db')
    ledger.reserve('call', 'a' * 64, 4096)
    with pytest.raises(ValueError):
        ledger.settle('call', invalid, 'b' * 64)
    assert ledger.snapshot()['reserved_micro_cny'] == 2129920


def test_cache_and_reasoning_are_preserved_without_double_charging(tmp_path):
    ledger = budget_type().create(tmp_path / 'campaign.db')
    ledger.reserve('call', 'a' * 64, 4096)
    detailed = {**usage(), 'prompt_cache_hit_tokens': 80, 'prompt_cache_miss_tokens': 20,
                'prompt_tokens_details': {'cached_tokens': 80},
                'completion_tokens_details': {'reasoning_tokens': 15}}
    ledger.settle('call', detailed, 'b' * 64)
    snapshot = ledger.snapshot()
    assert snapshot['settled_upper_bound_micro_cny'] == 360
    assert snapshot['operations'][0]['usage'] == detailed


@pytest.mark.parametrize('damage', ['missing', 'truncate', 'delete_event', 'change_event', 'replace'])
def test_missing_corrupt_or_replaced_ledger_never_becomes_new_budget(tmp_path, damage):
    cls = budget_type()
    path = tmp_path / 'campaign.db'
    ledger = cls.create(path)
    ledger.reserve('call', 'a' * 64, 4096)
    if damage == 'missing':
        path.unlink()
    elif damage == 'truncate':
        path.write_bytes(path.read_bytes()[:100])
    elif damage == 'replace':
        path.unlink(); cls.create(path)
    else:
        with sqlite3.connect(path) as db:
            if damage == 'delete_event':
                db.execute('DELETE FROM events')
            else:
                db.execute("UPDATE events SET payload='{}'")
    with pytest.raises((ValueError, OSError)):
        ledger.snapshot()
    if damage != 'replace':
        with pytest.raises((ValueError, OSError)):
            cls(path)


def test_creation_cannot_overwrite_existing_or_follow_symlink(tmp_path):
    cls = budget_type()
    path = tmp_path / 'campaign.db'
    ledger = cls.create(path)
    with pytest.raises((ValueError, OSError)):
        cls.create(path)
    link = tmp_path / 'link.db'; link.symlink_to(path)
    with pytest.raises((ValueError, OSError)):
        cls(link)
    assert path.stat().st_mode & 0o777 == 0o600
    assert ledger.snapshot()['remaining_micro_cny'] == 200000000
