"""Launch the named Mori controller for a frozen loopback fixture.

This is not a live pilot or proof of whole-cell descendant termination.
The controller is trusted; generated candidate programs use the sandbox.
"""
from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import re
import stat

from core.composition.recovery import ContinuationStore
from core.executor.process import ProcessJournal
from core.executor.sandbox import sandbox_child_path
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.cell_deadline import CellDeadline
from zoo.circle_packing.mori_fixture_worker import validate_config
from zoo.mle_bench_lite.cny_budget import CampaignBudget


def launch_fixture_controller(config, *, deadline, directory):
    """Run one fresh fixture controller under its existing cell deadline."""
    config = validate_config(config)
    ledger = CampaignBudget(config['ledger'])
    if not ledger.is_fixture_campaign():
        raise ValueError('fixture campaign is required')
    return _launch_controller(config, ledger=ledger, deadline=deadline, directory=directory,
                              entry='zoo.circle_packing.mori_fixture_worker', api_key=None)


def launch_live_controller(config, *, deadline, directory, api_key):
    """Supervise a live controller only after the still-closed pilot gate."""
    from zoo.circle_packing.mori_live_worker import _require_live_gate
    _require_live_gate(config)
    from zoo.circle_packing.mori_controller import CONFIG_FIELDS
    if type(config) is not dict or set(config) != CONFIG_FIELDS or \
            type(config['seed']) is not int or config['seed'] not in (0, 1, 2) or \
            any(type(config[name]) is not str or not Path(config[name]).is_absolute()
                for name in ('source', 'runtime', 'ledger', 'clock', 'output')):
        raise ValueError('live controller requires its exact configuration')
    if type(api_key) is not str or not api_key.strip():
        raise ValueError('live controller requires an in-memory credential')
    ledger = CampaignBudget(config['ledger'])
    if ledger.is_fixture_campaign() or config['base_url'] != ledger.manifest_binding()['provider_base_url']:
        raise ValueError('live controller requires its original non-fixture provider')
    from zoo.circle_packing.cell_containment import delegated_cell_group
    with delegated_cell_group() as group:
        return _launch_controller(config, ledger=ledger, deadline=deadline, directory=directory,
                                  entry='zoo.circle_packing.mori_live_worker', api_key=api_key,
                                  containment_group=group)


def _launch_controller(config, *, ledger, deadline, directory, entry, api_key, containment_group=None):
    if type(deadline) is not CellDeadline or deadline._lifecycle.ledger.path.resolve() != ledger.path.resolve():
        raise ValueError('controller requires the original campaign cell deadline')
    record = deadline._record
    if record['cell_id'] != f"mori-{config['seed']}" or record['plan_ref'] != config['ref'] or \
            Path(config['clock']).resolve(strict=True) != deadline._store.path.resolve(strict=True):
        raise ValueError('fixture controller clock differs from the original cell')
    from zoo.circle_packing.pilot_plan import validate_draft_cell
    cell = validate_draft_cell(ledger, config['plan'], record['cell_id'], expected_plan_ref=config['ref'])
    if cell['campaign_id'] != config['campaign_id'] or record['seconds'] != cell['wallclock_seconds']:
        raise ValueError('fixture controller differs from the frozen plan')
    source, runtime = Path(config['source']).resolve(strict=True), Path(config['runtime']).resolve(strict=True)
    from zoo.circle_packing.frozen_source import verify_frozen_source
    from zoo.circle_packing.frozen_runtime import verify_frozen_runtime
    verify_frozen_source(ledger, config['plan'], snapshot=source.parent, manifest=config['source_manifest'],
                         expected_plan_ref=config['ref'], expected_campaign_id=config['campaign_id'])
    verify_frozen_runtime(ledger, runtime=runtime, manifest=config['runtime_manifest'], base_python='/usr/bin/python3.12')
    requested = Path(directory)
    parent = requested.parent.resolve(strict=True)
    info = parent.stat()
    if not requested.is_absolute() or requested.name in ('', '.', '..') or info.st_uid != os.getuid() or \
            stat.S_IMODE(info.st_mode) & 0o077 or requested.exists() or requested.is_symlink():
        raise ValueError('fixture supervisor requires a fresh private directory')
    root = parent / requested.name
    protected = (source, runtime, ledger.path.resolve(), deadline._store.path.resolve(), Path(config['output']).resolve())
    if any(root == path or root in path.parents or path in root.parents for path in protected):
        raise ValueError('fixture supervisor directory overlaps protected paths')
    child_path = sandbox_child_path()
    remaining = deadline.remaining()
    if remaining <= 0:
        raise ValueError('fixture controller deadline has expired')
    root.mkdir(mode=0o700)
    setup = root / 'config.json'
    fd = os.open(setup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(config, stream, sort_keys=True, allow_nan=False)
    worker_binding = {'schema_version': 1, 'cell_id': record['cell_id'],
        'deadline_ref': record['record_sha256'], 'config_sha256': payload_digest(config),
        'directory': str(root), 'entry': entry}
    if containment_group is not None:
        from core.executor.process_identity import start_ticks
        info, pid = containment_group.stat(), os.getpid()
        ticks = start_ticks(pid)
        if ticks is None:
            raise RuntimeError('containment requires a stable supervisor identity')
        worker_binding['containment_group'] = str(containment_group)
        worker_binding['containment_identity'] = {'device': info.st_dev, 'inode': info.st_ino}
        worker_binding['supervisor_pid'] = pid
        worker_binding['supervisor_start_ticks'] = ticks
        worker_binding['boot_id'] = record['boot_id']
    worker_ref = payload_digest(worker_binding)
    ledger.claim_cell_worker(record['cell_id'], record['record_sha256'], worker_ref)
    remaining = deadline.remaining()
    if remaining <= 0:
        raise ValueError('fixture controller deadline expired after claim')
    journal = ProcessJournal(ContinuationStore(root / 'controller.jsonl'))
    env = {'PATH': child_path, 'PYTHONPATH': str(source), 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    if api_key is not None:
        env['DEEPSEEK_API_KEY'] = api_key
    command = [str(runtime / 'bin' / 'python'), '-m', entry, str(setup)]
    if containment_group is not None:
        from zoo.circle_packing.cell_containment import contained_command
        command = contained_command(containment_group, command)
    metadata = {'candidate_id': 'fixture-coordinator', 'attempt': 1, 'worker_ref': worker_ref}
    if containment_group is not None:
        metadata['containment_required'] = True
        metadata['containment_binding'] = worker_binding
    process, execution = journal.launch(
        command, root, env,
        remaining, metadata, die_with_parent=True,
        absolute_deadline={'boot_id': record['boot_id'],
            'deadline_ns': record['start_ns'] + record['seconds'] * 1_000_000_000})
    try:
        if containment_group is None:
            return journal.wait(process, execution)
        from zoo.circle_packing.cell_containment import finish_cell_group
        return journal.wait(process, execution, before_record=lambda: finish_cell_group(
            containment_group, expected_identity=worker_binding['containment_identity']))
    except BaseException:
        journal.terminate_target(execution)
        if process.poll() is None:
            process.kill()
            process.wait()
        journal.terminate_target(execution)
        raise


def reconcile_live_containment(config, *, deadline, directory):
    """Clean the original group after owner death; the cell remains unresolved."""
    from core.executor.process_identity import process_alive, start_ticks
    from zoo.circle_packing.cell_containment import finish_cell_group
    from zoo.circle_packing.cell_deadline import _boot_identity
    if type(config) is not dict or type(deadline) is not CellDeadline or \
            type(config.get('seed')) is not int or config['seed'] not in (0, 1, 2):
        raise ValueError('reconciliation requires the original cell configuration')
    ledger = deadline._lifecycle.ledger
    if ledger.is_fixture_campaign() or config.get('ledger') != str(ledger.path) or \
            config.get('clock') != str(deadline._store.path) or config.get('ref') != deadline._record['plan_ref'] or \
            deadline._record['cell_id'] != f"mori-{config['seed']}":
        raise ValueError('reconciliation differs from the original campaign or cell')
    deadline.export_evidence()  # Check original anchored clock and boot without extending it.
    root = Path(directory)
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root:
        raise ValueError('reconciliation requires the original private directory')
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('reconciliation requires the original private directory')
    journal_path = root / 'controller.jsonl'
    info = journal_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise ValueError('reconciliation requires the original private journal')
    lock_fd = os.open(root / 'reconcile.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        lock_info = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1 or \
                lock_info.st_uid != os.getuid() or stat.S_IMODE(lock_info.st_mode) != 0o600:
            raise ValueError('reconciliation requires a private lock')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        store = ContinuationStore(journal_path)
        rows = list(store.read())
        started = [row['payload'] for row in rows if row['kind'] == 'executor_process_started']
        if len(started) != 1 or any(row['kind'] in ('executor_process_finished', 'executor_containment_verified',
                'circle_containment_reconciled') for row in rows):
            raise ValueError('reconciliation requires one unfinished original process')
        process = started[0]
        binding = process.get('containment_binding')
        fields = {'schema_version', 'cell_id', 'deadline_ref', 'config_sha256', 'directory', 'entry',
                  'containment_group', 'containment_identity', 'supervisor_pid', 'supervisor_start_ticks', 'boot_id'}
        if type(binding) is not dict or set(binding) != fields or type(binding['schema_version']) is not int or \
                binding['schema_version'] != 1 or \
                process.get('containment_required') is not True or process.get('candidate_id') != 'fixture-coordinator' or \
                type(process.get('attempt')) is not int or process['attempt'] != 1 or \
                type(process.get('execution_id')) is not str or re.fullmatch(r'[0-9a-f]{32}', process['execution_id']) is None or \
                binding['cell_id'] != deadline._record['cell_id'] or binding['deadline_ref'] != deadline._record['record_sha256'] or \
                binding['config_sha256'] != payload_digest(config) or binding['directory'] != str(root) or \
                binding['entry'] != 'zoo.circle_packing.mori_live_worker' or binding['boot_id'] != _boot_identity() or \
                binding['boot_id'] != deadline._record['boot_id']:
            raise ValueError('reconciliation process identity differs')
        worker_ref = payload_digest(binding)
        if process.get('worker_ref') != worker_ref or ledger.cell_worker_claim(binding['cell_id']) != {
                'deadline_ref': binding['deadline_ref'], 'worker_ref': worker_ref}:
            raise ValueError('reconciliation differs from the original worker claim')
        for pid, ticks in ((binding['supervisor_pid'], binding['supervisor_start_ticks']),
                           (process.get('wrapper_pid'), process.get('wrapper_start_ticks'))):
            if type(pid) is not int or pid <= 0 or type(ticks) is not int or ticks < 0:
                raise ValueError('reconciliation requires stable process identities')
            if Path(f'/proc/{pid}').exists():
                current = start_ticks(pid)
                if current is None:
                    raise ValueError('reconciliation cannot verify process identity')
                if current == ticks and process_alive(pid, ticks):
                    raise RuntimeError('reconciliation refuses a running original process')
        group = Path(binding['containment_group'])
        cg_root = Path('/sys/fs/cgroup').resolve(strict=True)
        if not group.is_absolute() or group.is_symlink() or group.resolve(strict=True) != group or \
                cg_root not in group.parents or re.fullmatch(r'mori-cell-[0-9a-f]{32}', group.name) is None:
            raise ValueError('reconciliation requires the original containment group')
        identity = binding['containment_identity']
        if type(identity) is not dict or set(identity) != {'device', 'inode'} or \
                any(type(identity[key]) is not int or identity[key] < 0 for key in identity):
            raise ValueError('reconciliation requires the original containment identity')
        finish_cell_group(group, expected_identity=identity)
        store.append('circle_containment_reconciled', {'execution_id': process['execution_id'],
                                                       'worker_ref': worker_ref})
        return {'state': 'group_cleaned_cell_unresolved', 'execution_id': process['execution_id']}
    finally:
        os.close(lock_fd)
