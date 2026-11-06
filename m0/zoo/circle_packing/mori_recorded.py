"""Export and independently replay a Mori run without provider credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

from core.x1.checkpoint import RunCheckpoint, payload_digest


def export_replay_input(framework, destination):
    """Persist the original recorded inputs before the host's own replay."""
    runtime = framework._composed
    if runtime is None or runtime.result is None or runtime.governed is None or runtime.governed.external is None:
        raise ValueError('recorded replay requires a completed governed Mori run')
    checkpoint = RunCheckpoint.load(runtime.workdir / 'checkpoint.json')
    evidence = {'schema_version': 1, 'checkpoint': json.loads(checkpoint.to_bytes()),
                'rows': list(runtime.store.read()), 'currency_bundle': runtime.governed.external.replay_bundle()}
    raw = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return payload_digest(evidence)


def replay_mori_snapshot(config, evidence, *, expected_evidence_sha256, expected_campaign_head,
                         ledger, runner, output):
    """Replay recorded inputs in a fresh workspace; never bind a live bridge."""
    from core.loop import Framework, LoopConfig
    from zoo.circle_packing.domain import CirclePackingDomain
    from zoo.circle_packing.frozen_source import verify_frozen_source
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.mori_controller import CONFIG_FIELDS
    from zoo.circle_packing.runner import TASK
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    from zoo.mle_bench_lite.composed_domain import SandboxRunner
    from zoo.mle_bench_lite.governed_currency_audit import RecordedCurrencyView

    if type(config) is not dict or set(config) != CONFIG_FIELDS or type(ledger) is not CampaignBudget or \
            type(runner) is not SandboxRunner or type(evidence) is not dict or \
            set(evidence) != {'schema_version', 'checkpoint', 'rows', 'currency_bundle'} or \
            type(evidence['schema_version']) is not int or evidence['schema_version'] != 1 or \
            type(evidence['rows']) is not list or payload_digest(evidence) != expected_evidence_sha256:
        raise ValueError('recorded Mori replay input differs from its pinned identity')
    if Path(config['ledger']).resolve(strict=True) != ledger.path.resolve(strict=True) or \
            config['campaign_id'] != ledger.manifest_binding()['campaign_id']:
        raise ValueError('recorded Mori replay differs from its campaign')
    source, original = Path(config['source']).resolve(strict=True), Path(config['output']).resolve(strict=True)
    if source != Path(__file__).resolve().parents[2] or \
            str(Path(config['runtime']) / 'bin' / 'python') != sys.executable:
        raise ValueError('recorded Mori replay must use its frozen source and runtime')
    verify_frozen_source(ledger, config['plan'], snapshot=source.parent, manifest=config['source_manifest'],
                         expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'])
    checkpoint = RunCheckpoint.from_bytes(json.dumps(evidence['checkpoint']).encode())
    bundle = evidence['currency_bundle']
    try:
        authority = bundle['ready']['authority_binding']
        view = RecordedCurrencyView(bundle['currency_evidence'], expected_run_id=authority['currency_run_id'],
                                    expected_head=expected_campaign_head)
        if not view._pinned_head:
            raise ValueError('recorded Mori replay requires a pinned campaign head')
        binding = view.run_deadline_binding(authority['currency_run_id'])
        if binding['cell_id'] != f"mori-{config['seed']}" or binding['plan_ref'] != config['ref'] or \
                checkpoint.payload['task_desc'] != TASK:
            raise ValueError('recorded Mori replay differs from its original cell')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('recorded Mori replay lacks its original currency binding') from error
    target = Path(output)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise ValueError('recorded Mori replay requires a fresh absolute workspace')
    parent = target.parent.resolve(strict=True)
    info = parent.stat()
    if parent != target.parent or target.name in ('', '.', '..') or info.st_uid != os.getuid() or \
            stat.S_IMODE(info.st_mode) & 0o077 or \
            any(target == protected or target in protected.parents or protected in target.parents
                for protected in (source, Path(config['runtime']).resolve(strict=True), original,
                                  ledger.path.resolve(strict=True), Path(config['clock']).resolve(strict=True))):
        raise ValueError('recorded Mori replay workspace overlaps protected evidence')
    profile, registry, provider = governed_setup(original, ledger=ledger, api_key=None, seed=config['seed'],
        iterations=config['plan']['iterations'], base_url=config['base_url'],
        max_completion_tokens=config['plan']['max_completion_tokens'], total_token_ceiling=config['plan']['limits']['token'],
        runner=runner, recorded_only=True)
    cfg = LoopConfig(**checkpoint.payload['config'])
    if cfg.max_generations != config['plan']['iterations'] or cfg.total_budget != config['plan']['limits']['token']:
        raise ValueError('recorded Mori replay differs from the frozen budget')
    domain = CirclePackingDomain(original / 'replay-domain', runner=runner.independent_runner())
    framework = Framework.from_profile(profile, provider, domain, cfg, str(target), component_registry=registry)
    runtime = framework._composed
    runtime._logical_run_id = checkpoint.payload['logical_run_id']
    runtime._recorded_rows = evidence['rows']
    runtime._recorded_external_bundle = bundle
    runtime._recorded_artifacts_root = original / 'framework'
    result = framework.evolve(TASK)
    replayed = RunCheckpoint.load(target / 'checkpoint.json')
    if replayed.payload != checkpoint.payload or runtime.store.peek() is not None:
        raise ValueError('recorded Mori replay differs from its original checkpoint or transcript')
    return {'schema_version': 1, 'scope': 'independent_recorded_mori_replay', 'performance_claim': False,
            'passed': True, 'external_calls': 0, 'candidate': result['best_candidate_id']}
