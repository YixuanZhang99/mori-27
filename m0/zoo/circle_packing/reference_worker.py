"""Named offline upstream-controller worker; never a live model entrypoint."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys

from zoo.circle_packing.cell_deadline import CellDeadline
from zoo.circle_packing.cell_worker import run_cell_worker

_BOOTSTRAP = ("import runpy,sys; source=sys.argv.pop(1); sys.path.insert(0,source); "
              "sys.argv[0]='zoo.circle_packing.reference_worker'; "
              "runpy.run_module('zoo.circle_packing.reference_worker',run_name='__main__')")


def _token(path):
    """Read a disposable local broker capability, never a provider key."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or \
                stat.S_IMODE(info.st_mode) & 0o077 or info.st_size != 64:
            raise ValueError('broker capability must be a private regular file')
        value = os.read(fd, 65).decode('ascii')
    finally:
        os.close(fd)
    if re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('invalid broker capability')
    return value


def run_reference_fixture(deadline, directory, workspace, *, snapshot, source_manifest,
                          frozen_plan, expected_plan_ref, expected_campaign_id,
                          broker, broker_token_file, iterations=1, runtime=None,
                          runtime_manifest=None, base_python=None):
    """Run the pinned offline host; caller supplies the broker's authority."""
    if type(deadline) is not CellDeadline or type(iterations) is not int or not 1 <= iterations <= 6:
        raise ValueError('reference fixture requires a bounded cell and iterations')
    cell_id = deadline._record['cell_id']
    from zoo.circle_packing.cell_identity import parse_cell_identity
    experiment_id, arm, seed = parse_cell_identity(cell_id)
    if arm != 'vendor' or seed not in (0, 1, 2) or \
            (experiment_id is not None and not deadline._lifecycle.ledger.is_fixture_campaign()):
        raise ValueError('reference fixture requires a vendor cell')
    from zoo.circle_packing.host_transport import HostBroker, probe_broker
    if type(broker) is not HostBroker or broker._socket.fileno() < 0:
        raise ValueError('reference fixture requires its trusted broker')
    workspace = Path(workspace).resolve(strict=True)
    socket = broker.path
    token = Path(broker_token_file)
    if not workspace.is_dir() or not socket.is_absolute() or not token.is_absolute() or \
            socket.parent.resolve() != workspace or token.parent.resolve() != workspace or \
            socket.is_symlink() or not socket.is_socket() or token.is_symlink() or not token.is_file():
        raise ValueError('reference fixture requires workspace-local broker files')
    capability = _token(token)  # Disposable local capability, not a provider key.
    if socket.lstat().st_ino != broker._identity or not hmac.compare_digest(capability, broker._token):
        raise ValueError('broker capability or socket identity differs')
    source = Path(snapshot).resolve(strict=True) / 'm0'
    entry = source / 'zoo' / 'circle_packing' / 'reference_worker.py'
    if entry.is_symlink() or not entry.is_file():
        raise ValueError('frozen source is missing the reference worker entry')
    output = workspace / 'host-run'
    if output.is_symlink() or output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('reference fixture output must be empty')
    binding = deadline._lifecycle.ledger.circle_runtime_binding()
    if binding is not None:
        if runtime is None or runtime_manifest is None or base_python is None:
            raise ValueError('reference fixture requires the frozen runtime')
        runtime_root = Path(runtime).resolve(strict=True)
        python = runtime_root / 'bin' / 'python'
    else:
        if runtime is not None or runtime_manifest is not None or base_python is not None:
            raise ValueError('reference fixture has no frozen runtime binding')
        runtime_root = Path(sys.prefix)
        python = Path(sys.executable)
    probe_broker(socket, capability)
    from zoo.circle_packing.pilot_plan import validate_draft_cell
    validate_draft_cell(deadline._lifecycle.ledger, frozen_plan, cell_id, expected_plan_ref=expected_plan_ref)
    if iterations > frozen_plan['iterations']:
        raise ValueError('reference iterations exceed frozen plan')
    command = ['/usr/bin/env', 'PYTHONHASHSEED=0', str(python), '-c', _BOOTSTRAP, str(source),
               '--socket', str(socket), '--token-file', str(token), '--output', str(output),
               '--seed', str(seed), '--iterations', str(iterations),
               '--model', frozen_plan['model'], '--max-completion-tokens', str(frozen_plan['max_completion_tokens'])]
    return run_cell_worker(deadline, directory, workspace, command, readonly_source=source,
        readonly_runtime=runtime_root, frozen_plan=frozen_plan, snapshot=snapshot,
        source_manifest=source_manifest, expected_plan_ref=expected_plan_ref,
        expected_campaign_id=expected_campaign_id, runtime_manifest=runtime_manifest, base_python=base_python)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', required=True, type=int, choices=(0, 1, 2))
    parser.add_argument('--iterations', required=True, type=int, choices=range(1, 7))
    parser.add_argument('--model', required=True)
    parser.add_argument('--max-completion-tokens', required=True, type=int)
    args = parser.parse_args()
    from zoo.circle_packing.host_reference import run_fixture, _ALLOWED_ENV, _BROKER_ENV
    os.environ['MORI_CIRCLE_BROKER_SOCKET'] = args.socket
    os.environ['MORI_CIRCLE_BROKER_TOKEN'] = _token(args.token_file)
    os.environ['MORI_CIRCLE_STAGE_BROKER'] = '1'
    allowed = set(_ALLOWED_ENV) | set(_BROKER_ENV) | {'MORI_CIRCLE_STAGE_BROKER'}
    for name in set(os.environ) - allowed:
        del os.environ[name]
    result = run_fixture(args.output, seed=args.seed, iterations=args.iterations,
                         fixture_broker=True, fixture_stage_broker=True, model_name=args.model,
                         max_completion_tokens=args.max_completion_tokens)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
