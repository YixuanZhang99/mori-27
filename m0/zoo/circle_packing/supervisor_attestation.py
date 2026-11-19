"""Verify that pilot work belongs to the claimed supervised cell process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time

from core.executor.process_identity import _stat_fields, process_alive, start_ticks
from core.x1.checkpoint import payload_digest
from core.x1.store import AppendOnlyStore
from zoo.circle_packing.cell_deadline import _boot_identity


def _private_json(path, *, max_bytes=1048576):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > max_bytes:
            raise ValueError('supervisor identity file is not a private regular file')
        return json.load(stream)


def require_supervised_process(ledger, deadline):
    """Reject a copied claim unless this is its original contained target."""
    raw = os.environ.get('MORI_SUPERVISOR_TARGET')
    if type(raw) is not str or not raw:
        raise ValueError('pilot requires its original supervisor target')
    target = Path(raw)
    if not target.is_absolute() or target.name != 'target.json' or \
            target.parent.parent.name != 'executor-processes' or \
            re.fullmatch('[0-9a-f]{32}', target.parent.name) is None:
        raise ValueError('supervisor target path is invalid')
    root = target.parent.parent.parent
    try:
        info = root.stat()
        if root.is_symlink() or root.resolve(strict=True) != root or target.parent.resolve(strict=True) != target.parent or \
                not stat.S_ISDIR(info.st_mode) or \
                info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('supervisor directory is not private')
        identity = _private_json(target)
        if identity != {'pid': os.getpid(), 'start_ticks': start_ticks(os.getpid())} or \
                identity['start_ticks'] is None:
            raise ValueError('supervisor target identity differs from this process')
        journal = root / 'controller.jsonl'
        until = time.monotonic() + 5
        rows = []
        while time.monotonic() < until:
            if journal.exists():
                jinfo = journal.lstat()
                if not stat.S_ISREG(jinfo.st_mode) or jinfo.st_uid != os.getuid() or jinfo.st_nlink != 1:
                    raise ValueError('supervisor journal is not a private regular file')
                rows = list(AppendOnlyStore(journal).read('executor_process_started'))
                if rows:
                    break
            time.sleep(.01)
        if len(rows) != 1:
            raise ValueError('supervisor process record is missing or ambiguous')
        record = rows[0]['payload']
        binding = record['containment_binding']
        fields = {'schema_version', 'cell_id', 'deadline_ref', 'config_sha256', 'directory', 'entry',
                  'containment_group', 'containment_identity', 'supervisor_pid', 'supervisor_start_ticks', 'boot_id'}
        clock = deadline._record
        cell = clock['cell_id']
        reference = cell.startswith('vendor-')
        entry = 'zoo.circle_packing.reference_live_worker' if reference else 'zoo.circle_packing.mori_live_worker'
        if type(binding) is not dict or set(binding) != fields or binding['schema_version'] != 1 or \
                record.get('containment_required') is not True or record.get('target_path') != str(target) or \
                record.get('execution_id') != target.parent.name or binding['directory'] != str(root) or \
                binding['cell_id'] != cell or binding['deadline_ref'] != clock['record_sha256'] or \
                binding['boot_id'] != clock['boot_id'] or binding['boot_id'] != _boot_identity() or \
                binding['entry'] != entry:
            raise ValueError('supervisor binding differs from the original cell')
        worker_ref = payload_digest(binding)
        claim = ledger.reference_host_claim(cell) if reference else ledger.cell_worker_claim(cell)
        if record.get('worker_ref') != worker_ref or claim != {
                'deadline_ref': clock['record_sha256'], 'host_ref' if reference else 'worker_ref': worker_ref}:
            raise ValueError('supervisor binding differs from the original claim')
        config = _private_json(root / 'config.json', max_bytes=64 * 1024 * 1024)
        if payload_digest(config) != binding['config_sha256'] or config['ref'] != clock['plan_ref'] or \
                type(config['seed']) is not int or cell != f"{'vendor' if reference else 'mori'}-{config['seed']}" or \
                Path(config['ledger']).resolve(strict=True) != ledger.path.resolve(strict=True) or \
                Path(config['clock']).resolve(strict=True) != deadline._store.path.resolve(strict=True):
            raise ValueError('supervisor configuration differs from the original cell')
        command = Path('/proc/self/cmdline').read_bytes().split(b'\0')
        expected_command = [os.fsencode(str(Path(config['runtime']) / 'bin' / 'python')),
                            b'-m', os.fsencode(entry), os.fsencode(str(root / 'config.json')), b'']
        if command != expected_command:
            raise ValueError('supervisor target command differs from its frozen entry')
        wrapper = record['wrapper_pid']
        if wrapper != os.getppid() or not process_alive(wrapper, record['wrapper_start_ticks']) or \
                not process_alive(binding['supervisor_pid'], binding['supervisor_start_ticks']) or \
                int(_stat_fields(wrapper)[1]) != binding['supervisor_pid']:
            raise ValueError('supervisor process chain is no longer alive')
        group = Path(binding['containment_group'])
        cgroup_root = Path('/sys/fs/cgroup').resolve(strict=True)
        resolved = group.resolve(strict=True)
        membership = [line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines()
                      if line.startswith('0::/')]
        group_info = group.stat()
        if group.is_symlink() or resolved != group or cgroup_root not in group.parents or \
                re.fullmatch('mori-cell-[0-9a-f]{32}', group.name) is None or len(membership) != 1 or \
                (cgroup_root / membership[0].lstrip('/')).resolve(strict=True) != group or \
                binding['containment_identity'] != {'device': group_info.st_dev, 'inode': group_info.st_ino}:
            raise ValueError('supervisor containment group differs')
    except (OSError, KeyError, TypeError, json.JSONDecodeError, UnicodeError, IndexError) as error:
        raise ValueError('supervisor identity cannot be verified') from error
