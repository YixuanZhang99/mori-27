"""Construct a non-executable draft of the paired circle pilot matrix."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess

from core.composition.openevolve_registration import _DATABASE_SHA, _SEED_SHA
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.stage import EVALUATOR_SHA256
from zoo.mle_bench_lite.cny_budget import POLICY, _hash


def require_first_pair_audit(seed):
    """Fail closed for later seeds until the paired audit can be durably bound."""
    if type(seed) is not int or seed not in (0, 1, 2):
        raise ValueError('cell seed is outside the frozen pilot')
    if seed != 0:
        raise ValueError('later seeds require the first pair independent audit')


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
    payload = {'schema_version': 2, 'status': 'draft_not_executable',
        'source_commit': source_commit, 'dependency_lock_sha256': dependency_lock_sha256,
        'upstream_commit': '5153a7d74ee615b7090ec52903629870ecdacdf1',
        'seed_sha256': _SEED_SHA, 'database_sha256': _DATABASE_SHA,
        'evaluator_sha256': EVALUATOR_SHA256, 'campaign_id': campaign['campaign_id'],
        'campaign_policy_sha256': campaign['policy_sha256'], 'model': campaign['model'],
        'reasoning_effort': 'low', 'max_completion_tokens': output_tokens,
        'iterations': iterations, 'migration_interval': 2, 'stage_timeout_seconds': 60,
        'limits': {'token': 2 * (iterations + 1) * call_bound, 'eval_count': evaluations, 'node': iterations + 2,
                   'wallclock_seconds': 2700},
        'public_range_sum_radii': 2.372379655271936,
        'cells': [{'seed': seed, 'arm': arm, 'status': 'unrun'}
                  for seed in (0, 1, 2) for arm in ('vendor', 'mori')]}
    payload['draft_sha256'] = payload_digest(payload)
    return payload


def validate_draft_cell(ledger, plan, cell_id, *, expected_plan_ref):
    """Compare a declared cell with an independently supplied draft identity.

    This preflight does not authorize dispatch or make the draft executable.
    """
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    if type(ledger) is not CampaignBudget or type(plan) is not dict:
        raise ValueError('cell requires the original campaign and a frozen draft plan')
    try:
        expected = build_draft_plan(ledger.manifest_binding(), source_commit=plan['source_commit'],
                                    dependency_lock_sha256=plan['dependency_lock_sha256'])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('cell plan differs from the original campaign') from error
    if type(expected_plan_ref) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', expected_plan_ref) or \
            expected_plan_ref != 'sha256:' + expected['draft_sha256'] or \
            plan != expected or payload_digest(plan) != payload_digest(expected):
        raise ValueError('cell plan differs from the frozen draft and campaign')
    if type(cell_id) is not str or not re.fullmatch(r'(?:vendor|mori)-(?:0|[1-9][0-9]*)', cell_id):
        raise ValueError('cell identity is invalid')
    arm, seed = cell_id.split('-')
    if not any(cell == {'seed': int(seed), 'arm': arm, 'status': 'unrun'} for cell in plan['cells']):
        raise ValueError('cell is not in the frozen draft')
    return {'campaign_id': plan['campaign_id'], 'plan_ref': 'sha256:' + plan['draft_sha256'],
            'cell_id': cell_id, 'wallclock_seconds': plan['limits']['wallclock_seconds']}


def validate_source_preflight(ledger, plan, cell_id, *, checkout, expected_plan_ref):
    """Check current checkout identity; this snapshot cannot authorize a launch.

    Git-ignored files are not checked. The future supervisor must isolate them,
    prevent changes after this check, and verify the actual worker environment
    and original campaign authority.
    """
    binding = validate_draft_cell(ledger, plan, cell_id, expected_plan_ref=expected_plan_ref)
    try:
        root = Path(checkout).resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as error:
        raise ValueError('checkout must be an existing directory') from error
    if not root.is_dir():
        raise ValueError('checkout must be a directory')
    env = {'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_NO_REPLACE_OBJECTS': '1',
           'GIT_OPTIONAL_LOCKS': '0'}
    def git(*args):
        try:
            return subprocess.check_output(['git', '-C', str(root), '-c', 'core.fsmonitor=false',
                '-c', 'core.untrackedCache=false', '-c', 'core.filemode=true', *args], stderr=subprocess.DEVNULL,
                env=env, timeout=30).decode('utf-8').strip()
        except (OSError, subprocess.SubprocessError, UnicodeError) as error:
            raise ValueError('cannot verify source checkout') from error
    if Path(git('rev-parse', '--show-toplevel')).resolve() != root or \
            git('rev-parse', 'HEAD') != plan['source_commit'] or \
            git('ls-files', '--others', '--exclude-standard', '-z'):
        raise ValueError('source checkout differs from the frozen draft')
    git('diff-index', '--cached', '--quiet', '--no-ext-diff', 'HEAD', '--')
    flags = git('ls-files', '-v', '-z').split('\0')
    if any(entry and not entry.startswith('H ') for entry in flags):
        raise ValueError('source checkout has hidden index changes')
    # Git status can apply configured clean filters, making changed execution
    # bytes look clean. Compare actual bytes to each tracked Git blob instead.
    try:
        for entry in git('ls-files', '--stage', '-z').split('\0'):
            if not entry:
                continue
            header, name = entry.split('\t', 1)
            mode, oid, stage = header.split(' ')
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or stage != '0' or \
                    mode not in {'100644', '100755', '120000'}:
                raise ValueError('unsupported source index entry')
            path = root / relative
            info = path.lstat()
            if mode == '120000':
                if not stat.S_ISLNK(info.st_mode):
                    raise ValueError('source file type differs from index')
                data = os.fsencode(os.readlink(path))
            else:
                if not stat.S_ISREG(info.st_mode) or bool(info.st_mode & stat.S_IXUSR) != (mode == '100755'):
                    raise ValueError('source file mode differs from index')
                data = path.read_bytes()
            digest = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data,
                                  usedforsecurity=False).hexdigest()
            if digest != oid:
                raise ValueError('source bytes differ from the frozen index')
    except (OSError, UnicodeError) as error:
        raise ValueError('cannot inspect tracked source bytes') from error
    lock = root / 'm0' / 'uv.lock'
    if lock.is_symlink() or not lock.is_file() or \
            not git('ls-files', '--error-unmatch', '--', 'm0/uv.lock'):
        raise ValueError('dependency lock must be a tracked regular file')
    if hashlib.sha256(lock.read_bytes()).hexdigest() != plan['dependency_lock_sha256']:
        raise ValueError('dependency lock differs from the frozen draft')
    return {**binding, 'source_commit': plan['source_commit'],
            'dependency_lock_sha256': plan['dependency_lock_sha256']}
