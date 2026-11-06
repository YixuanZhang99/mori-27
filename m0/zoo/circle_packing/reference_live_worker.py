"""Trusted reference host; the paired live pilot gate is still closed."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from zoo.circle_packing.mori_controller import CONFIG_FIELDS

REFERENCE_CONFIG_FIELDS = CONFIG_FIELDS | {'worker_directory', 'workspace'}


def _take_credential():
    key = os.environ.pop('DEEPSEEK_API_KEY', None)
    if type(key) is not str or not key.strip():
        raise ValueError('reference host requires an in-memory provider credential')
    return key


def _prepare(config, *, api_key, host_ref):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.frozen_source import verify_frozen_source
    from zoo.circle_packing.host_runtime import build_reference_authorities
    from zoo.circle_packing.reproducibility import require_hash_seed_zero
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    from zoo.mle_bench_lite.composed_domain import SandboxRunner

    if type(config) is not dict or set(config) != REFERENCE_CONFIG_FIELDS or \
            type(config['seed']) is not int or config['seed'] not in (0, 1, 2) or \
            any(type(config[name]) is not str or not Path(config[name]).is_absolute()
                for name in ('source', 'runtime', 'ledger', 'clock', 'output', 'worker_directory', 'workspace')):
        raise ValueError('reference host requires its exact cell configuration')
    if type(api_key) is not str or not api_key.strip():
        raise ValueError('reference host requires an in-memory credential')
    ledger = CampaignBudget(config['ledger'])
    if ledger.is_fixture_campaign() or config['base_url'] != ledger.manifest_binding()['provider_base_url']:
        raise ValueError('reference host requires its original non-fixture provider')
    source, runtime, clock_path = Path(config['source']), Path(config['runtime']), Path(config['clock'])
    if source.resolve(strict=True) != Path(__file__).resolve().parents[2] or \
            str(runtime / 'bin' / 'python') != sys.executable:
        raise ValueError('reference host must use its frozen source and runtime')
    if clock_path.is_symlink() or not clock_path.is_file():
        raise ValueError('reference host requires its original cell clock')
    plan, ref = config['plan'], config['ref']
    verify_frozen_source(ledger, plan, snapshot=source.parent, manifest=config['source_manifest'],
                         expected_plan_ref=ref, expected_campaign_id=config['campaign_id'])
    require_hash_seed_zero()
    clock = CellDeadline.restore(ContinuationStore(clock_path), lifecycle=CellLifecycle(ledger),
        cell_id=f"vendor-{config['seed']}", plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
    if ledger.reference_host_claim(clock._record['cell_id']) != {
            'deadline_ref': clock._record['record_sha256'], 'host_ref': host_ref}:
        raise ValueError('reference host lacks its original supervisor claim')
    runner = SandboxRunner.for_campaign_runtime(ledger, runtime=runtime, manifest=config['runtime_manifest'],
                                                base_python='/usr/bin/python3.12')
    authority = build_reference_authorities(config['output'], ledger=ledger, plan=plan, expected_plan_ref=ref,
        expected_campaign_id=config['campaign_id'], deadline=clock, snapshot=source.parent,
        source_manifest=config['source_manifest'], runner=runner, api_key=api_key,
        base_url=config['base_url'], mode='live_preparation')
    return authority, clock


def run(config):
    key = _take_credential()
    from zoo.circle_packing.host_runtime import _require_reference_live_gate, run_reference_cell_live
    _require_reference_live_gate()
    host_ref = os.environ.pop('MORI_REFERENCE_HOST_REF', None)
    authority, clock = _prepare(config, api_key=key, host_ref=host_ref)
    with authority:
        result = run_reference_cell_live(authority, clock, config['worker_directory'], config['workspace'],
            snapshot=Path(config['source']).parent, source_manifest=config['source_manifest'],
            frozen_plan=config['plan'], expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'],
            runtime=config['runtime'], runtime_manifest=config['runtime_manifest'], base_python='/usr/bin/python3.12')
        if result['state'] == 'completed':
            from core.x1.checkpoint import payload_digest
            bundle = authority.bridge.reference_audit_bundle()
            data = json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
            path = Path(config['output']) / 'reference-currency.json'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            result['currency_bundle_sha256'] = payload_digest(bundle)
        return result


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: python -m zoo.circle_packing.reference_live_worker CONFIG')
    print(json.dumps(run(json.loads(Path(sys.argv[1]).read_text())), sort_keys=True))


if __name__ == '__main__':
    main()
