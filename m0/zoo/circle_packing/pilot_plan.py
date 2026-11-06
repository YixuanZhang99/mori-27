"""Construct a non-executable draft of the paired circle pilot matrix."""
from __future__ import annotations

import re

from core.composition.openevolve_registration import _DATABASE_SHA, _SEED_SHA
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.stage import EVALUATOR_SHA256
from zoo.mle_bench_lite.cny_budget import POLICY, _hash


def build_draft_plan(campaign, *, source_commit, dependency_lock_sha256):
    if type(source_commit) is not str or not re.fullmatch(r'[0-9a-f]{40}', source_commit) or \
            type(dependency_lock_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', dependency_lock_sha256):
        raise ValueError('source and dependency identities must be pinned hashes')
    fields = set(POLICY) | {'campaign_id', 'limit_micro_cny', 'policy_sha256'}
    if type(campaign) is not dict or set(campaign) != fields or \
            any(campaign[key] != value for key, value in POLICY.items()) or \
            campaign['policy_sha256'] != _hash({key: value for key, value in campaign.items()
                                                 if key != 'policy_sha256'}):
        raise ValueError('campaign must match its original frozen policy')
    output_tokens = 16384
    call_bound = campaign['context_tokens'] + output_tokens
    iterations = 6
    # Includes seed + six candidates, one independent control and final audit.
    evaluations = 2 * (iterations + 1) + 2 + 1
    payload = {'schema_version': 1, 'status': 'draft_not_executable',
        'source_commit': source_commit, 'dependency_lock_sha256': dependency_lock_sha256,
        'upstream_commit': '5153a7d74ee615b7090ec52903629870ecdacdf1',
        'seed_sha256': _SEED_SHA, 'database_sha256': _DATABASE_SHA,
        'evaluator_sha256': EVALUATOR_SHA256, 'campaign_id': campaign['campaign_id'],
        'campaign_policy_sha256': campaign['policy_sha256'], 'model': campaign['model'],
        'reasoning_effort': 'low', 'max_completion_tokens': output_tokens,
        'iterations': iterations, 'migration_interval': 2, 'stage_timeout_seconds': 60,
        'limits': {'token': 4 * call_bound, 'eval_count': evaluations, 'node': iterations + 2,
                   'wallclock_seconds': 2700},
        'public_range_sum_radii': 2.372379655271936,
        'cells': [{'seed': seed, 'arm': arm, 'status': 'unrun'}
                  for seed in (0, 1, 2) for arm in ('vendor', 'mori')]}
    payload['draft_sha256'] = payload_digest(payload)
    return payload
