"""Prepare credential-free cell configurations from frozen pilot authorities.

This does not claim a cell, authorize a model call, or open the live gate.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat


def prepare_cell_configs(ledger, *, plan, expected_plan_ref, source_root, source_manifest,
                         runtime, runtime_manifest, directory):
    """Write six private, non-overwriting configurations without touching the ledger."""
    from zoo.circle_packing.frozen_source import verify_frozen_source
    from zoo.circle_packing.frozen_runtime import verify_frozen_runtime
    from zoo.circle_packing.pilot_plan import validate_draft_cell
    from zoo.mle_bench_lite.cny_budget import CampaignBudget

    if type(ledger) is not CampaignBudget or type(plan) is not dict:
        raise ValueError('configuration preparation requires the original campaign and plan')
    source, runtime, directory = Path(source_root), Path(runtime), Path(directory)
    if not all(path.is_absolute() for path in (source, runtime, directory)):
        raise ValueError('pilot preparation paths must be absolute')
    policy = ledger.manifest_binding()
    campaign_id = policy['campaign_id']
    validate_draft_cell(ledger, plan, 'mori-0', expected_plan_ref=expected_plan_ref)
    verify_frozen_source(ledger, plan, snapshot=source, manifest=source_manifest,
                         expected_plan_ref=expected_plan_ref, expected_campaign_id=campaign_id)
    verify_frozen_runtime(ledger, runtime=runtime, manifest=runtime_manifest, base_python='/usr/bin/python3.12')
    source = source.resolve(strict=True)
    runtime = runtime.resolve(strict=True)
    root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(root_fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('pilot configuration directory must be private')
        directory = directory.resolve(strict=True)
        protected = (source, runtime, ledger.path.resolve(strict=True))
        if any(directory == path or directory in path.parents or path in directory.parents for path in protected):
            raise ValueError('pilot configuration directory overlaps frozen authorities')
        names = [f'{arm}-{seed}' for seed in range(3) for arm in ('mori', 'vendor')]
        if any(len(os.fsencode(directory / name / 'workspace' / 'broker.sock')) >= 104
               for name in names if name.startswith('vendor-')):
            raise ValueError('reference broker socket path is too long')
        for name in names:
            try:
                os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ValueError('pilot cell configuration already exists')
        results = []
        for name in names:
            arm, seed_text = name.split('-')
            seed = int(seed_text)
            os.mkdir(name, 0o700, dir_fd=root_fd)
            cell_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            try:
                cell = directory / name
                config = {'plan': plan, 'ref': expected_plan_ref, 'runtime_manifest': runtime_manifest,
                          'source_manifest': source_manifest, 'source': str(source / 'm0'),
                          'runtime': str(runtime), 'ledger': str(ledger.path.resolve(strict=True)),
                          'clock': str(cell / 'clock.jsonl'), 'output': str(cell / 'output'),
                          'base_url': policy['provider_base_url'], 'campaign_id': campaign_id, 'seed': seed}
                if arm == 'vendor':
                    os.mkdir('workspace', 0o700, dir_fd=cell_fd)
                    config.update(worker_directory=str(cell / 'worker'), workspace=str(cell / 'workspace'))
                encoded = json.dumps(config, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()
                fd = os.open('config.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=cell_fd)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(cell_fd)
                results.append({'cell_id': name, 'config_path': str(cell / 'config.json'),
                                'supervisor_directory': str(cell / 'supervisor')})
            finally:
                os.close(cell_fd)
        os.fsync(root_fd)
        return results
    finally:
        os.close(root_fd)


def main():
    import argparse
    from zoo.mle_bench_lite.cny_budget import CampaignBudget

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ledger', 'plan', 'expected-plan-ref', 'source-root', 'source-manifest',
                 'runtime', 'runtime-manifest', 'directory'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    def read_json(path):
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)
    results = prepare_cell_configs(CampaignBudget(args.ledger), plan=read_json(args.plan),
        expected_plan_ref=args.expected_plan_ref, source_root=args.source_root,
        source_manifest=read_json(args.source_manifest), runtime=args.runtime,
        runtime_manifest=read_json(args.runtime_manifest), directory=args.directory)
    print(json.dumps({'scope': 'prepared_cell_configurations', 'cells': results}, sort_keys=True))


if __name__ == '__main__':
    main()
