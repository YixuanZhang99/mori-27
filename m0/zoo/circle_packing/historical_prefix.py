"""Private temporary campaign prefixes for independent offline auditing only."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import platform
import sqlite3
import stat
import tempfile

from zoo.mle_bench_lite.cny_budget import CampaignBudget, _head_anchor, _reduce_history


@contextmanager
def _historical_network_filter():
    """Deny outbound connection and addressed sends in this process tree."""
    from core.executor.seccomp import (_filter_bytes, _instruction, _BPF_JMP_JEQ_K, _BPF_LD_W_ABS,
                                       _BPF_RET_K, _SECCOMP_RET_ERRNO_EPERM, _SECCOMP_RET_ALLOW)
    if platform.machine() != 'x86_64' or not hasattr(os, 'memfd_create'):
        raise ValueError('historical replay requires Linux x86_64 seccomp support')
    program = _filter_bytes()[:-8]
    # connect, sendmsg, sendmmsg and io_uring can reach external sockets.
    for number in (42, 46, 307, 425, 426, 427):
        program += _instruction(_BPF_JMP_JEQ_K, 0, 1, number)
        program += _instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO_EPERM)
    # sendto with a destination is denied, while send on a local socketpair
    # (used by Python's asyncio event loop) remains available.
    program += _instruction(_BPF_JMP_JEQ_K, 0, 5, 44)
    program += _instruction(_BPF_LD_W_ABS, 0, 0, 48)
    program += _instruction(_BPF_JMP_JEQ_K, 0, 2, 0)
    program += _instruction(_BPF_LD_W_ABS, 0, 0, 52)
    program += _instruction(_BPF_JMP_JEQ_K, 1, 0, 0)
    program += _instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO_EPERM)
    program += _instruction(_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW)
    fd = os.memfd_create('mori-historical-seccomp', os.MFD_CLOEXEC)
    try:
        if os.write(fd, program) != len(program):
            raise OSError('cannot write historical seccomp filter')
        os.lseek(fd, 0, os.SEEK_SET)
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _temporary_verified_prefix(ledger, *, expected_head):
    """Yield a private, verified prefix; never use this copy for paid execution."""
    if type(ledger) is not CampaignBudget:
        raise ValueError('historical replay requires the original campaign')
    _head_anchor(expected_head)
    with tempfile.TemporaryDirectory(prefix='mori-historical-campaign-') as temporary:
        path = Path(temporary) / 'prefix.db'
        with ledger._transaction() as (original, _policy, state):
            if expected_head['seq'] > state['seq']:
                raise ValueError('historical head is beyond the current campaign')
            policies = original.execute('SELECT payload FROM policy').fetchall()
            events = original.execute('SELECT seq, payload, hash FROM events WHERE seq <= ? ORDER BY seq',
                                      (expected_head['seq'],)).fetchall()
            # The transaction has already checked the full current journal;
            # this separately proves the caller-pinned historical prefix.
            _reduce_history(policies, events, [(expected_head['seq'], expected_head['sha256'])])
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with sqlite3.connect(path) as copy:
                copy.execute('PRAGMA synchronous=FULL')
                copy.execute('CREATE TABLE policy (payload TEXT NOT NULL)')
                copy.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL)')
                copy.execute('CREATE TABLE head (seq INTEGER NOT NULL, hash TEXT NOT NULL)')
                copy.executemany('INSERT INTO policy VALUES (?)', policies)
                copy.executemany('INSERT INTO events VALUES (?, ?, ?)', events)
                copy.execute('INSERT INTO head VALUES (?, ?)', (expected_head['seq'], expected_head['sha256']))
        # Reopen and validate the materialized bytes, not only the in-memory rows.
        if CampaignBudget(path).snapshot()['journal_head'] != expected_head:
            raise ValueError('materialized historical prefix differs from its requested head')
        yield path


def replay_historical_pair(ledger, *, expected_head, expected_plan_ref, seed, mori_directory,
                           vendor_directory, replay_output):
    """Replay original frozen evidence in an isolated, credential-free namespace."""
    import json
    import math
    import shutil
    import subprocess

    from zoo.circle_packing.frozen_runtime import verify_frozen_runtime
    from zoo.circle_packing.frozen_source import verify_frozen_source
    from zoo.circle_packing.pilot_matrix import _validate_replay_output

    if type(ledger) is not CampaignBudget or type(seed) is not int or seed not in (0, 1, 2):
        raise ValueError('historical replay requires the original campaign and seed')
    _head_anchor(expected_head)
    mori_root, vendor_root = Path(mori_directory).resolve(strict=True), Path(vendor_directory).resolve(strict=True)
    try:
        mori = json.loads((mori_root / 'config.json').read_text())
        vendor = json.loads((vendor_root / 'config.json').read_text())
        if type(mori) is not dict or type(vendor) is not dict or any(
                c['seed'] != seed or type(c['seed']) is not int or c['ref'] != expected_plan_ref or
                Path(c['ledger']).resolve(strict=True) != ledger.path.resolve(strict=True) for c in (mori, vendor)) or \
                any(mori[key] != vendor[key] for key in ('plan', 'source', 'runtime')):
            raise ValueError('historical replay configurations differ')
        source, runtime = Path(mori['source']).resolve(strict=True), Path(mori['runtime']).resolve(strict=True)
        output = _validate_replay_output(replay_output, mori=mori, vendor=vendor,
            mori_directory=mori_root, vendor_directory=vendor_root, ledger_path=ledger.path)
        campaign = ledger.manifest_binding()
        verify_frozen_source(ledger, mori['plan'], snapshot=source.parent, manifest=mori['source_manifest'],
                             expected_plan_ref=expected_plan_ref, expected_campaign_id=campaign['campaign_id'])
        verify_frozen_runtime(ledger, runtime=runtime, manifest=mori['runtime_manifest'],
                              base_python='/usr/bin/python3.12')
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise ValueError('historical replay evidence is invalid') from error
    bwrap = shutil.which('bwrap')
    if bwrap is None:
        raise ValueError('historical replay requires bubblewrap network isolation')
    ledger_path = ledger.path.resolve(strict=True)
    probe = Path(__file__).with_name('frozen_pair_probe.py').resolve(strict=True)
    output_parent = Path(output).parent
    parent_info = output_parent.stat()
    protected = (source, runtime, mori_root, vendor_root, ledger_path.parent, probe)
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid() or \
            stat.S_IMODE(parent_info.st_mode) & 0o077 or any(
                output_parent == path or output_parent in path.parents or path in output_parent.parents
                for path in protected):
        raise ValueError('historical replay output parent must be private and separate')
    before = ledger.snapshot()['journal_head']
    with _temporary_verified_prefix(ledger, expected_head=expected_head) as prefix, \
            tempfile.TemporaryDirectory(prefix='.mori-historical-output-', dir=output_parent) as output_staging:
        temporary = prefix.parent
        masked = ledger_path.parent
        if any(masked == path or masked in path.parents for path in
               (source, runtime, mori_root, vendor_root, probe, Path(output), temporary)):
            raise ValueError('historical replay paths overlap the masked campaign directory')
        try:
            evidence_paths = {source.parent, runtime, mori_root, vendor_root, probe,
                Path(mori['clock']).resolve(strict=True), Path(vendor['clock']).resolve(strict=True),
                Path(mori['output']).resolve(strict=True), Path(vendor['output']).resolve(strict=True),
                Path(vendor['workspace']).resolve(strict=True), Path(vendor['worker_directory']).resolve(strict=True)}
            forbidden = {Path('/'), Path('/home'), Path.home(), Path('/tmp'), Path('/run'), Path('/etc'), Path('/root')}
            if any(path in forbidden or path == masked or masked in path.parents or path in masked.parents
                   for path in evidence_paths):
                raise ValueError('historical evidence requires narrow paths outside the campaign directory')
            if any(not (path.is_dir() or path.is_file()) for path in evidence_paths):
                raise ValueError('historical evidence includes an unsupported file type')
        except (KeyError, TypeError, OSError) as error:
            raise ValueError('historical replay mount paths are invalid') from error
        command = [bwrap, '--die-with-parent', '--unshare-net', '--unshare-pid', '--tmpfs', '/',
                   '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
                   '--dev', '/dev', '--proc', '/proc']
        for path in sorted(evidence_paths, key=lambda value: (len(value.parts), str(value))):
            command.extend(['--ro-bind', str(path), str(path)])
        command.extend(['--bind', str(prefix), str(ledger_path), '--bind', str(temporary), str(temporary),
                        '--bind', str(output_staging), str(output_parent), '--chdir', str(source)])
        env = {'PATH': os.defpath, 'HOME': str(temporary), 'PYTHONPATH': str(source),
               'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
        try:
            with _historical_network_filter() as fd:
                command.extend(['--seccomp', str(fd), '--', str(runtime / 'bin/python'), str(probe),
                    str(mori_root), str(vendor_root), json.dumps(expected_head, sort_keys=True),
                    expected_plan_ref, str(seed), str(output), str(ledger_path)])
                process = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                         text=True, timeout=600, pass_fds=(fd,))
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('isolated historical replay could not complete') from error
        if process.returncode != 0:
            raise ValueError('isolated historical replay failed')
        try:
            def unique(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError('duplicate historical replay field')
                    result[key] = value
                return result
            result = json.loads(process.stdout, object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite historical replay')))
            if type(result) is not dict or set(result) != {'scope', 'seed', 'plan_ref', 'journal_head',
                    'performance_claim', 'mori', 'reference', 'sum_radii_difference', 'replay'} or \
                    result['scope'] != 'paired_supervised_snapshots_with_independent_replay' or \
                    type(result['seed']) is not int or result['seed'] != seed or result['plan_ref'] != expected_plan_ref or \
                    result['journal_head'] != expected_head or result['performance_claim'] is not False or \
                    type(result['replay']) is not dict or result['replay'].get('passed') is not True or \
                    type(result['replay'].get('external_calls')) is not int or result['replay']['external_calls'] != 0:
                raise ValueError('historical replay result differs from its original evidence')
            mori_result, reference_result = result['mori'], result['reference']
            if type(mori_result) is not dict or type(reference_result) is not dict or \
                    type(mori_result.get('candidate')) is not str or not mori_result['candidate'] or \
                    result['replay'].get('candidate') != mori_result['candidate']:
                raise ValueError('historical replay candidate differs from its original evidence')
            for summary in (mori_result, reference_result):
                if any(type(summary.get(key)) not in (int, float) or not math.isfinite(summary[key])
                       for key in ('sum_radii', 'validity')) or summary['validity'] not in (0, 1) or \
                        type(summary.get('settled_upper_bound_micro_cny')) is not int or \
                        summary['settled_upper_bound_micro_cny'] < 0:
                    raise ValueError('historical replay summary is invalid')
            difference = result['sum_radii_difference']
            if type(difference) not in (int, float) or not math.isfinite(difference) or \
                    difference != mori_result['sum_radii'] - reference_result['sum_radii']:
                raise ValueError('historical replay difference is invalid')
            safe_summary = {key: result[key] for key in ('scope', 'seed', 'plan_ref', 'journal_head',
                                                         'performance_claim', 'sum_radii_difference')}
            for arm in ('mori', 'reference'):
                safe_summary[arm] = {key: result[arm][key] for key in
                    ('sum_radii', 'validity', 'settled_upper_bound_micro_cny')}
            safe_summary['mori']['candidate'] = mori_result['candidate']
            safe_summary['replay'] = {key: result['replay'][key] for key in ('passed', 'external_calls', 'candidate')}
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError('historical replay result is invalid') from error
        if ledger.snapshot()['journal_head'] != before:
            raise ValueError('campaign head changed during historical replay')
        staged_output = Path(output_staging) / Path(output).name
        if staged_output.is_symlink() or not staged_output.is_dir():
            raise ValueError('historical replay did not produce its isolated output')
        from zoo.circle_packing.continuation_source import _publish_source
        _publish_source(staged_output, output)
        parent_fd = os.open(output_parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    if ledger.snapshot()['journal_head'] != before:
        raise ValueError('campaign head changed during historical replay')
    return safe_summary
