"""Compose reference-cell authorities from a frozen pilot and original campaign.

This factory does not start the controller or authorize a live pilot. It uses
the existing physical and currency journals and does not persist provider keys.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import threading
import urllib.parse

from core.budget.types import AccountingStamp
from core.composition.budget import HierarchicalBudget, JOURNAL_KIND
from core.composition.contracts import GovernanceConfig
from core.composition.external_provider import ExternalRunContext, EXTERNAL_RUNTIME
from core.composition.governance import ControlPlan
from core.composition.recovery import ContinuationStore
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.cell_deadline import CellDeadline
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.circle_packing.frozen_source import verify_frozen_source
from zoo.circle_packing.host_control import HostSeedControl
from zoo.circle_packing.host_dispatch import HostDispatchCoordinator, HostDispatchRouter
from zoo.circle_packing.host_physical import HostStageAdmission
from zoo.circle_packing.host_transport import HostBroker
from zoo.circle_packing.pilot_plan import validate_draft_cell
from zoo.circle_packing.runner import TASK
from zoo.mle_bench_lite.cny_budget import CampaignBudget, usage_run_id
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _require_reference_live_gate(seed):
    if type(seed) is int and seed == 0:
        return
    raise ValueError('live pilot gate is not complete')


def _read_verified_worker_result(worker_directory, started):
    """Read bounded worker outputs from their opened, execution-bound files."""
    execution_id = started.get('execution_id')
    if type(execution_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', execution_id):
        raise ValueError('reference worker process path has invalid execution identity')
    root = Path(worker_directory) / 'executor-processes' / execution_id
    files = {'result_path': ('result.json', 65536), 'stdout_path': ('stdout.txt', 8 * 1024 * 1024),
             'stderr_path': ('stderr.txt', 32 * 1024 * 1024)}
    if any(type(started.get(key)) is not str or started[key] != str(root / name)
           for key, (name, _limit) in files.items()):
        raise ValueError('reference worker process path differs from its execution identity')
    fds = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(worker_directory, flags)
        fds.append(fd)
        for component in ('executor-processes', execution_id):
            fd = os.open(component, flags, dir_fd=fd)
            fds.append(fd)
        contents, identities = {}, {}
        for key, (name, limit) in files.items():
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=fd)
            try:
                info = os.fstat(child)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or \
                        info.st_size > limit:
                    raise ValueError('reference worker process path is not a bounded private artifact')
                chunks, remaining = [], limit + 1
                while remaining:
                    part = os.read(child, remaining)
                    if not part:
                        break
                    chunks.append(part)
                    remaining -= len(part)
                data, after = b''.join(chunks), os.fstat(child)
                if len(data) > limit or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != \
                        (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError('reference worker process artifact changed while reading')
                contents[key] = data.decode('utf-8')
                identities[name] = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            finally:
                os.close(child)
        for name, identity in identities.items():
            current = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != identity:
                raise ValueError('reference worker process path changed while reading')
        for parent, name, original in ((None, worker_directory, fds[0]),
                                       (fds[0], 'executor-processes', fds[1]),
                                       (fds[1], execution_id, fds[2])):
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            opened = os.fstat(original)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError('reference worker process directory changed while reading')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate worker result field')
                result[key] = value
            return result
        result = json.loads(contents['result_path'], object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if type(result) is not dict or set(result) not in ({'returncode', 'timeout'},
                {'returncode', 'timeout', 'wrapper_error'}) or type(result['returncode']) is not int or \
                type(result['timeout']) is not bool or \
                ('wrapper_error' in result and type(result['wrapper_error']) is not str):
            raise ValueError('reference worker process terminal is invalid')
        return {'returncode': result['returncode'], 'timeout': result['timeout'],
                'stdout': contents['stdout_path'], 'stderr': contents['stderr_path'],
                'wrapper_error': result.get('wrapper_error')}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('reference worker process path cannot be safely inspected') from error
    finally:
        for fd in reversed(fds):
            os.close(fd)


class _AuthorityLease:
    def __init__(self, root):
        fd = os.open(root / 'authority.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or \
                    stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError('reference authority lock must be a private regular file')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('another reference authority owner is active') from error
        except BaseException:
            os.close(fd)
            raise
        self._fd, self._pid = fd, os.getpid()
        self._mutex, self._active, self._on_start, self._sealed = threading.Lock(), 0, None, False

    def bind_start(self, callback):
        if self._on_start is not None or not callable(callback):
            raise ValueError('reference owner requires one work-start authority')
        self._on_start = callback

    def check(self):
        if self._fd is None or self._pid != os.getpid():
            raise RuntimeError('reference authority owner is closed or belongs to another process')

    @contextmanager
    def session(self):
        with self._mutex:
            self.check()
            if self._sealed:
                raise RuntimeError('reference authority is sealed')
            self._active += 1
        try:
            yield
        finally:
            with self._mutex:
                self._active -= 1

    @contextmanager
    def operation(self):
        with self.session():
            if self._on_start is None:
                raise RuntimeError('reference owner lacks its work-start authority')
            self._on_start()
            yield

    def seal(self, callback):
        """Stop new work before recording a selection; failure stays sealed."""
        if not callable(callback):
            raise ValueError('reference seal requires an anchor callback')
        with self._mutex:
            self.check()
            if self._sealed or self._active != 1:
                raise RuntimeError('reference authority has active or sealed work')
            self._sealed = True
        return callback()

    def close(self):
        with self._mutex:
            if self._active:
                raise RuntimeError('reference authority has active work')
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    def __del__(self):
        if getattr(self, '_fd', None) is not None:
            self.close()


@dataclass(frozen=True)
class ReferenceAuthorities:
    budget: HierarchicalBudget
    bridge: CNYInvocationBridge
    run: ExternalRunContext
    control: HostSeedControl
    dispatch: HostDispatchCoordinator
    stages: HostStageAdmission
    router: HostDispatchRouter
    _lease: _AuthorityLease = field(repr=False, compare=False)

    def close(self):
        self._lease.close()

    def __enter__(self):
        self._lease.check()
        return self

    def __exit__(self, *_args):
        self.close()


def build_reference_provider(ledger, plan, *, api_key, base_url, operator_cap, fixture=False):
    """Construct a reference transport without admitting or starting a call."""
    from zoo.circle_packing.pilot_plan import build_draft_plan
    if type(ledger) is not CampaignBudget or type(plan) is not dict or type(fixture) is not bool or \
            type(operator_cap) is not int or operator_cap not in (1, 2) or \
            type(api_key) is not str or not api_key.strip():
        raise ValueError('reference provider requires a campaign, plan and bounded call limit')
    policy = ledger.manifest_binding()
    try:
        if type(plan.get('schema_version')) is int and plan['schema_version'] == 3:
            if not fixture:
                raise ValueError('continuation provider requires a fixture campaign')
            cell = f"{plan['experiment_id']}--vendor-0"
            validate_draft_cell(ledger, plan, cell, expected_plan_ref='sha256:' + plan['draft_sha256'])
        else:
            expected = build_draft_plan(policy, source_commit=plan['source_commit'],
                                        dependency_lock_sha256=plan['dependency_lock_sha256'])
            if plan != expected or payload_digest(plan) != payload_digest(expected):
                raise ValueError('reference provider plan differs from its campaign')
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('reference provider plan differs from its campaign') from error
    if fixture:
        try:
            url = urllib.parse.urlsplit(base_url)
            if not ledger.is_fixture_campaign() or api_key != 'fixture-only-secret' or url.scheme != 'http' or \
                    url.hostname not in {'127.0.0.1', '::1'} or not url.port or \
                    url.username or url.password or url.query or url.fragment:
                raise ValueError('fixture reference requires its fake key and loopback provider')
        except (TypeError, ValueError) as error:
            raise ValueError('fixture reference requires its fake key and loopback provider') from error
    elif ledger.is_fixture_campaign() or base_url != policy['provider_base_url']:
        raise ValueError('reference requires the original campaign provider')
    return GovernedCNYProvider(policy['model'], base_url, campaign_binding=policy,
        max_completion_tokens=plan['max_completion_tokens'], api_key=api_key,
        message_mode='openevolve_host_v1', reasoning_effort=plan['reasoning_effort'],
        phase_call_limits={'operator': operator_cap, 'evaluation': 0})


def build_reference_authorities(output, *, ledger, plan, expected_plan_ref, expected_campaign_id,
                                deadline, snapshot, source_manifest, runner, api_key, base_url=None,
                                mode='fixture'):
    """Prepare one bounded reference cell; callers still own process supervision."""
    if type(ledger) is not CampaignBudget or type(deadline) is not CellDeadline or \
            deadline._lifecycle.ledger is not ledger:
        raise ValueError('reference requires its original campaign and cell deadline')
    if mode not in ('fixture', 'live_preparation'):
        raise ValueError('unsupported reference authority mode')
    if mode == 'fixture' and not ledger.is_fixture_campaign():
        raise ValueError('reference fixture requires a marked fixture campaign')
    if mode == 'live_preparation' and ledger.is_fixture_campaign():
        raise ValueError('live preparation requires a non-fixture campaign')
    cell = deadline._record['cell_id']
    from zoo.circle_packing.cell_identity import parse_cell_identity
    experiment_id, arm, seed = parse_cell_identity(cell)
    if arm != 'vendor' or seed not in (0, 1, 2) or (experiment_id is not None and mode != 'fixture'):
        raise ValueError('reference requires a declared vendor cell')
    if mode == 'live_preparation' and cell != 'vendor-0':
        raise ValueError('live pilot gate allows only the first paired cells')
    binding = validate_draft_cell(ledger, plan, cell, expected_plan_ref=expected_plan_ref)
    if ledger.manifest_binding()['campaign_id'] != expected_campaign_id or \
            binding['campaign_id'] != expected_campaign_id or \
            deadline._record['plan_ref'] != expected_plan_ref or \
            deadline._record['seconds'] != binding['wallclock_seconds']:
        raise ValueError('reference cell differs from the frozen campaign or plan')
    pilot, runtime = ledger.circle_pilot_binding(), ledger.circle_runtime_binding()
    if mode == 'live_preparation' and (pilot is None or not pilot.get('require_single_run')):
        raise ValueError('live reference requires a single-run pilot')
    if mode == 'live_preparation':
        from zoo.circle_packing.supervisor_attestation import require_supervised_process
        require_supervised_process(ledger, deadline)
    if experiment_id is not None:
        continuation = ledger.circle_continuation_binding(experiment_id)
        if type(runner) is not SandboxRunner or runner._campaign_runtime is None or \
                runner._campaign_runtime[0] is not ledger or runner._continuation_runtime is None or \
                payload_digest(runner._continuation_runtime[0]) != payload_digest(plan) or \
                Path(snapshot).resolve(strict=True) != (Path(runner._continuation_runtime[1]) / 'source').resolve(strict=True) or \
                continuation is None or 'sha256:' + payload_digest(source_manifest) != continuation['tree_ref'] or \
                runner.manifest_binding.get('runtime_ref') != continuation['runtime_ref']:
            raise ValueError('reference requires its bound continuation source and runtime')
        tree_ref, runtime = continuation['tree_ref'], continuation
    else:
        if pilot is None or not pilot.get('require_runtime') or runtime is None or \
                type(runner) is not SandboxRunner or runner._campaign_runtime is None or \
                runner._campaign_runtime[0] is not ledger or runner._continuation_runtime is not None or \
                runner.manifest_binding.get('runtime_ref') != runtime['runtime_ref']:
            raise ValueError('reference requires the original frozen campaign runtime')
        verify_frozen_source(ledger, plan, snapshot=snapshot, manifest=source_manifest,
                             expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id)
        tree_ref = pilot['tree_ref']
    build_reference_provider(ledger, plan, api_key=api_key, base_url=base_url,
                             operator_cap=1, fixture=mode == 'fixture')
    deadline.check()
    requested = Path(output)
    if requested.is_symlink():
        raise ValueError('reference output cannot be a symlink')
    root = requested.resolve()
    if root == ledger.path.resolve().parent or root in ledger.path.resolve().parents:
        raise ValueError('reference output must be separate from the campaign')
    authority_ref = payload_digest({'schema_version': 1, 'cell_id': cell,
        'deadline_ref': deadline._record['record_sha256'], 'plan_ref': expected_plan_ref,
        'campaign_id': expected_campaign_id, 'source_tree_ref': tree_ref,
        'runtime_ref': runtime['runtime_ref'], 'output': str(root), 'base_url': base_url.rstrip('/')})
    currency_run_id = usage_run_id(root / 'provider_usage')
    expected_claim = {'deadline_ref': deadline._record['record_sha256'], 'authority_ref': authority_ref,
                      'currency_run_id': currency_run_id}
    existing_claim = ledger.reference_authority_claim(cell)
    if existing_claim is not None and any(existing_claim.get(key) != value for key, value in expected_claim.items()):
        raise ValueError('reference cell already has a different authority')
    if existing_claim is not None and existing_claim['work_started']:
        raise ValueError('reference work already started; recovery is not yet available')
    state = ledger.snapshot()
    if state['pending_calls'] or state['protection_breaches'] or \
            existing_claim is None and state['protected_micro_cny']:
        raise ValueError('reference requires a quiescent original campaign')
    if existing_claim is None:
        if not root.exists():
            root.mkdir(mode=0o700, parents=False)
        elif not root.is_dir() or any(path.name not in {'authority.lock', 'events.jsonl'} for path in root.iterdir()):
            raise ValueError('reference output contains unclaimed work')
    elif not root.is_dir():
        raise ValueError('reference authority lost its original directory')
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('reference authority directory must remain private')
    _sync_directory(root.parent)
    lease = _AuthorityLease(root)
    try:
        fresh_claim = ledger.reference_authority_claim(cell)
        if fresh_claim is not None and any(fresh_claim.get(key) != value for key, value in expected_claim.items()):
            raise ValueError('reference cell already has a different authority')
        if existing_claim is not None and fresh_claim is None:
            raise ValueError('reference authority claim disappeared')
        if fresh_claim is not None and fresh_claim['work_started']:
            raise ValueError('reference work already started; recovery is not yet available')
        state = ledger.snapshot()
        if state['pending_calls'] or state['protection_breaches'] or \
                fresh_claim is None and state['protected_micro_cny']:
            raise ValueError('reference requires a quiescent original campaign')
        return _build_authorities(root, ledger=ledger, plan=plan, deadline=deadline, cell=cell,
                                  expected_plan_ref=expected_plan_ref, runner=runner, api_key=api_key,
                                  base_url=base_url, authority_ref=authority_ref, existing_claim=fresh_claim,
                                  currency_run_id=currency_run_id, lease=lease, mode=mode)
    except BaseException:
        lease.close()
        raise


def reference_budget_config(plan, campaign, *, seed, ledger=None):
    """Derive the reference physical budget without credentials or a live authority."""
    from zoo.circle_packing.pilot_plan import build_draft_plan
    if type(plan) is not dict or type(seed) is not int or seed not in (0, 1, 2):
        raise ValueError('reference budget requires its frozen plan and seed')
    try:
        if type(plan.get('schema_version')) is int and plan['schema_version'] == 3:
            if type(ledger) is not CampaignBudget or ledger.manifest_binding() != campaign:
                raise ValueError('continuation budget requires its original fixture campaign')
            validate_draft_cell(ledger, plan, f"{plan['experiment_id']}--vendor-{seed}",
                                expected_plan_ref='sha256:' + plan['draft_sha256'])
            expected = plan
        else:
            expected = build_draft_plan(campaign, source_commit=plan['source_commit'],
                                        dependency_lock_sha256=plan['dependency_lock_sha256'])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('reference budget differs from its frozen campaign') from error
    if payload_digest(plan) != payload_digest(expected):
        raise ValueError('reference budget differs from its frozen campaign')
    bound = campaign['context_tokens'] + plan['max_completion_tokens']
    if plan['limits']['token'] != 2 * (plan['iterations'] + 1) * bound:
        raise ValueError('reference token limit differs from the frozen provider capacity')
    limits = {unit: plan['limits'][unit] for unit in ('token', 'node', 'eval_count')}
    controls = {'after_main_cycles': [0], 'seed': seed,
        'provider': {'name': 'control'}, 'domain': {'name': 'control'}, 'operator': {'name': 'draft'},
        'request': {'fidelity': 'dev', 'split_id': 'dev'},
        'reservations': {'operator': {'token': 2 * bound, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 0, 'node': 0, 'eval_count': 2}}}
    governance = GovernanceConfig.from_dict({'schema_version': 1, 'controls': controls}).to_dict()
    options = {'limits': {level: dict(limits) for level in ('global', 'direction', 'candidate')},
        'require_initial_control': True, 'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'operator': {'token': bound, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}
    stamp = AccountingStamp('deepseek', campaign['model'], 'service-capacity-v1', campaign['policy_sha256'], 'campaign')
    return options, asdict(stamp), governance


def _build_authorities(root, *, ledger, plan, deadline, cell, expected_plan_ref, runner, api_key,
                       base_url, authority_ref, existing_claim, currency_run_id, lease, mode):
    policy = ledger.manifest_binding()

    def provider(operator_cap):
        return build_reference_provider(ledger, plan, api_key=api_key, base_url=base_url,
                                        operator_cap=operator_cap, fixture=mode == 'fixture')

    main, control_provider = provider(1), provider(2)
    from zoo.circle_packing.cell_identity import parse_cell_identity
    _experiment_id, _arm, seed = parse_cell_identity(cell)
    options, stamp_values, governance = reference_budget_config(plan, policy, seed=seed, ledger=ledger)
    if main.governance_binding()['call_bound']['units']['token'] != policy['context_tokens'] + plan['max_completion_tokens']:
        raise ValueError('reference provider capacity differs from its frozen plan')
    journal_path = root / 'events.jsonl'
    if journal_path.is_symlink():
        raise ValueError('reference physical journal cannot be a symlink')
    if journal_path.exists():
        info = journal_path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError('reference physical journal must be a private regular file')
    store = ContinuationStore(journal_path)
    stamp = AccountingStamp(**stamp_values)
    budget = HierarchicalBudget(options, stamp, store, governance=governance)
    prior_events = list(store.read(JOURNAL_KIND))
    if existing_claim is not None and not prior_events:
        raise ValueError('reference authority lost its original physical journal')
    if existing_claim is None and (len(prior_events) > 1 or any(
            row['kind'] != JOURNAL_KIND for row in store.read())):
        raise ValueError('unclaimed reference output contains prior work')
    if prior_events:
        budget.restore_from_journal()
    domain = CirclePackingDomain(root / 'domain', runner=runner)
    physical_plan = ControlPlan.freeze(governance, task_desc=TASK,
        initial_context={'circle_domain_binding': domain.manifest_binding},
        max_generations=plan['iterations'], units=budget.units).to_dict()
    budget.protect_controls(physical_plan)
    _sync_directory(root)
    initial = list(store.read(JOURNAL_KIND))
    if not initial or initial[0]['payload'].get('event') != 'protect_controls':
        raise ValueError('reference authority lacks initial physical protection')
    initial_ref = initial[0]['payload']['event_ref']
    if existing_claim is not None and existing_claim.get('initial_budget_ref') != initial_ref:
        raise ValueError('reference physical journal differs from original authority claim')
    ledger.claim_reference_authority(cell, deadline._record['record_sha256'], authority_ref,
                                     currency_run_id, initial_ref)
    def start_work():
        if mode != 'fixture':
            _require_reference_live_gate(int(cell.rsplit('-', 1)[1]))
            from zoo.circle_packing.supervisor_attestation import require_supervised_process
            require_supervised_process(ledger, deadline)
        ledger.start_reference_authority_work(cell, authority_ref)
    lease.bind_start(start_work)
    run = ExternalRunContext(logical_run_id=authority_ref[:32], runtime_id=EXTERNAL_RUNTIME,
        workdir=str(root), physical_plan=physical_plan, main_provider_binding=main.governance_binding(),
        control_provider_bindings={'control-0000': control_provider.governance_binding()},
        mode='live', recorded_bundle=None, store=store, physical_identity_lookup=budget.invocation_identity,
        provider_sessions={'main': main, 'control-0000': control_provider})
    bridge = CNYInvocationBridge(ledger, cell_deadline_binding=(deadline, plan, expected_plan_ref, cell))
    ready = bridge.bind_run(run)
    protected = HostSeedControl(budget, bridge, run, ready, domain, owner_check=lease.check,
                                owner_operation=lease.operation)
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready, runner=runner, owner_check=lease.check,
                                       owner_operation=lease.operation)
    stages = HostStageAdmission(budget, runner=runner.independent_runner(), workspace=root / 'stages',
                                control_authority=dispatch)
    return ReferenceAuthorities(budget, bridge, run, protected, dispatch, stages,
                                HostDispatchRouter(dispatch, stages), lease)


def run_reference_cell_fixture(authority, deadline, worker_directory, workspace, *, snapshot, source_manifest,
                               frozen_plan, expected_plan_ref, expected_campaign_id, runtime,
                               runtime_manifest, base_python, iterations=1):
    """Run one loopback reference fixture; no live or benchmark claim is made.

    The selection is matched to original stage evidence for this invocation,
    but is not yet anchored as a final result or independently revalidated.
    """
    if type(authority) is not ReferenceAuthorities or not authority.bridge.ledger.is_fixture_campaign():
        raise ValueError('reference fixture requires its original bounded cell authority')
    with authority._lease.session():
        return _run_reference_cell_fixture(authority, deadline, worker_directory, workspace,
            snapshot=snapshot, source_manifest=source_manifest, frozen_plan=frozen_plan,
            expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id,
            runtime=runtime, runtime_manifest=runtime_manifest, base_python=base_python, iterations=iterations)


def run_reference_cell_live(authority, deadline, worker_directory, workspace, *, snapshot, source_manifest,
                            frozen_plan, expected_plan_ref, expected_campaign_id, runtime,
                            runtime_manifest, base_python):
    """Run the full frozen reference cell only after the live pilot gate opens."""
    _require_reference_live_gate(int(deadline._record['cell_id'].rsplit('-', 1)[1]))
    if type(authority) is not ReferenceAuthorities or authority.bridge.ledger.is_fixture_campaign() or \
            type(frozen_plan) is not dict or type(frozen_plan.get('iterations')) is not int:
        raise ValueError('live reference requires its original non-fixture authority and plan')
    with authority._lease.session():
        result = _run_reference_cell_fixture(authority, deadline, worker_directory, workspace,
            snapshot=snapshot, source_manifest=source_manifest, frozen_plan=frozen_plan,
            expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id,
            runtime=runtime, runtime_manifest=runtime_manifest, base_python=base_python,
            iterations=frozen_plan['iterations'])
    return {**result, 'mode': 'live', 'performance_claim': False}


def _run_reference_cell_fixture(authority, deadline, worker_directory, workspace, *, snapshot, source_manifest,
                                frozen_plan, expected_plan_ref, expected_campaign_id, runtime,
                                runtime_manifest, base_python, iterations):
    if type(deadline) is not CellDeadline or \
            authority.bridge.cell_deadline() is not deadline or type(iterations) is not int or \
            not 1 <= iterations <= frozen_plan['iterations']:
        raise ValueError('reference fixture requires its original bounded cell authority')
    authority._lease.check()
    ledger = deadline._lifecycle.ledger
    if ledger is not authority.bridge.ledger or ledger.manifest_binding()['campaign_id'] != expected_campaign_id:
        raise ValueError('reference fixture differs from its original campaign')
    validate_draft_cell(ledger, frozen_plan, deadline._record['cell_id'], expected_plan_ref=expected_plan_ref)
    runner = authority.control.domain.runner
    frozen_runtime = runner._campaign_runtime
    if frozen_runtime is None or frozen_runtime[0] is not ledger or \
            Path(runtime).resolve(strict=True) != runner.runtime_root or str(base_python) != frozen_runtime[2]:
        raise ValueError('reference fixture requires its original campaign runtime')
    if runner._continuation_runtime is not None:
        draft, source_directory, _runtime_directory = runner._continuation_runtime
        continuation = ledger.circle_continuation_binding(draft['experiment_id'])
        if payload_digest(draft) != payload_digest(frozen_plan) or \
                Path(snapshot).resolve(strict=True) != (Path(source_directory) / 'source').resolve(strict=True) or \
                continuation is None or 'sha256:' + payload_digest(source_manifest) != continuation['tree_ref'] or \
                payload_digest(runtime_manifest) != continuation['runtime_manifest_sha256']:
            raise ValueError('reference fixture differs from its continuation binding')
    else:
        if runtime_manifest != frozen_runtime[1]:
            raise ValueError('reference fixture requires its original campaign runtime')
        verify_frozen_source(ledger, frozen_plan, snapshot=snapshot, manifest=source_manifest,
                             expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id)
    runner._verify_campaign_runtime()
    if Path(workspace).is_symlink() or Path(worker_directory).is_symlink():
        raise ValueError('reference fixture requires fresh isolated worker locations')
    workspace = Path(workspace).resolve(strict=True)
    worker_directory = Path(worker_directory).resolve()
    authority_root = Path(authority.run.workdir).resolve(strict=True)
    source_root = Path(snapshot).resolve(strict=True)
    runtime_root = Path(runtime).resolve(strict=True)
    protected = (authority_root, source_root, runtime_root, ledger.path.resolve(), deadline._store.path.resolve())
    def overlaps(left, right):
        return left == right or left in right.parents or right in left.parents
    info = workspace.stat()
    if not workspace.is_dir() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700 or \
            any(workspace.iterdir()) or worker_directory.exists() or not worker_directory.parent.is_dir() or \
            not os.access(worker_directory.parent, os.W_OK | os.X_OK) or \
            overlaps(workspace, worker_directory) or any(overlaps(path, protected_path)
                for path in (workspace, worker_directory) for protected_path in protected):
        raise ValueError('reference fixture requires fresh isolated worker locations')
    entry = source_root / 'm0' / 'zoo' / 'circle_packing' / 'reference_worker.py'
    if entry.is_symlink() or not entry.is_file():
        raise ValueError('reference fixture requires its named frozen worker')
    token_path, socket_path = workspace / 'broker-token', workspace / 'broker.sock'
    if len(os.fsencode(socket_path)) >= 104:
        raise ValueError('reference fixture socket path is too long')
    deadline.check()
    token = secrets.token_hex(32)
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(token)
        stop, errors = threading.Event(), []
        with HostBroker(socket_path, token, authority.router) as broker:
            control = asyncio.run(authority.control.execute('control-0000'))
            if control['status'] != 'evaluated':
                raise ValueError('reference fixture requires its independent completed control')
            broker._socket.settimeout(.25)
            def serve():
                with authority._lease.session():
                    while not stop.is_set():
                        try:
                            broker.serve_one()
                        except socket.timeout:
                            continue
                        except Exception as error:
                            if not stop.is_set():
                                errors.append(error)
                            return
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            worker_error = None
            try:
                from zoo.circle_packing.reference_worker import run_reference_fixture
                result = run_reference_fixture(deadline, worker_directory, workspace, snapshot=snapshot,
                    source_manifest=source_manifest, frozen_plan=frozen_plan, expected_plan_ref=expected_plan_ref,
                    expected_campaign_id=expected_campaign_id, broker=broker, broker_token_file=token_path,
                    iterations=iterations, runtime=runtime, runtime_manifest=runtime_manifest, base_python=base_python)
            except BaseException as error:
                worker_error = error
            finally:
                stop.set()
                broker.cancel_active()
                thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError('reference fixture broker has unresolved in-flight work') from worker_error
            if worker_error is not None:
                raise worker_error
            if errors:
                raise RuntimeError('reference fixture broker failed') from errors[0]
        if result['state'] != 'completed':
            return {'state': result['state'], 'mode': 'fixture', 'performance_claim': False}
        deadline.check()
        authority.dispatch.audit()
        authority.stages.audit()
        store = ContinuationStore(worker_directory / 'worker.jsonl')
        starts = list(store.read('executor_process_started'))
        claim = ledger.cell_worker_claim(deadline._record['cell_id'])
        if len(starts) != 1 or claim is None:
            raise ValueError('reference worker process lacks its original claim')
        started = starts[0]['payload']
        if type(started) is not dict or started.get('cell_id') != deadline._record['cell_id'] or \
                started.get('worker_ref') != claim['worker_ref'] or \
                claim['deadline_ref'] != deadline._record['record_sha256'] or \
                started.get('candidate_id') != 'cell-worker' or type(started.get('attempt')) is not int or \
                started['attempt'] != 1:
            raise ValueError('reference worker process differs from its original claim')
        finished = list(store.read('executor_process_finished'))
        terminal = finished[0]['payload'] if len(finished) == 1 else None
        if type(terminal) is not dict or type(terminal.get('attempt')) is not int or \
                type(terminal.get('returncode')) is not int or type(terminal.get('timeout')) is not bool or \
                type(terminal.get('recovered')) is not bool or terminal != {
                'execution_id': started.get('execution_id'), 'candidate_id': 'cell-worker', 'attempt': 1,
                'returncode': 0, 'timeout': False, 'recovered': False}:
            raise ValueError('reference worker process lacks its matching successful terminal')
        process = _read_verified_worker_result(worker_directory, started)
        if process['returncode'] != 0 or process['timeout'] or process['wrapper_error']:
            raise ValueError('reference fixture worker did not complete')
        worker_proof = {'schema_version': 1, 'started': started, 'terminal': terminal,
            'result': {'returncode': process['returncode'], 'timeout': process['timeout'],
                'stdout_sha256': hashlib.sha256(process['stdout'].encode('utf-8')).hexdigest(),
                'stderr_sha256': hashlib.sha256(process['stderr'].encode('utf-8')).hexdigest(),
                'wrapper_error': process['wrapper_error']}}
        report = json.loads(process['stdout'])
        selected = report.get('selected_program') if type(report) is dict else None
        if type(report) is not dict or report.get('mode') != 'fixture' or report.get('performance_claim') is not False or \
                report.get('controller') != 'pinned_openevolve' or type(selected) is not dict or \
                set(selected) != {'id', 'program_ref', 'metrics'} or type(selected['id']) is not str or \
                not selected['id'] or type(selected['metrics']) is not dict:
            raise ValueError('reference fixture has no valid selected program report')
        def finalize_selection():
            rows = list(authority.budget.store.read())
            stage_starts = {r['payload']['request_id']: r['payload'] for r in rows if r['kind'] == 'host_stage_started'}
            stage_ends = {r['payload']['request_id']: r['payload'] for r in rows if r['kind'] == 'host_stage_completed'}
            eligibility = {r['payload']['request_id']: r['payload'] for r in rows if r['kind'] == 'host_stage_eligibility'}
            receipt = report.get('selection_stage_request_id')
            if type(receipt) is not str or not re.fullmatch(r'[0-9a-f]{32}', receipt):
                raise ValueError('reference fixture selection lacks its stage receipt')
            matches = []
            for request_id, start in stage_starts.items():
                if start['stage'] != 1 or start['program_ref'] != selected['program_ref']:
                    continue
                first = stage_ends[request_id]
                if first['result']['status'] != 'ok' or not authority.stages._verify_stage_eligibility(
                        eligibility[request_id], start, first, deadline):
                    continue
                final_id = request_id
                if first['result']['metrics']['combined_score'] >= .5:
                    second = [key for key, value in stage_starts.items()
                              if value['stage'] == 2 and value['prior_id'] == request_id]
                    if len(second) != 1:
                        continue
                    final_id = second[0]
                final = stage_ends[final_id]
                if final_id == receipt and final['result']['status'] == 'ok' and \
                        json.dumps(final['result']['metrics'], sort_keys=True, allow_nan=False) == \
                        json.dumps(selected['metrics'], sort_keys=True, allow_nan=False) and \
                        authority.stages._verify_stage_eligibility(eligibility[final_id], stage_starts[final_id],
                                                                  final, deadline):
                    matches.append((final_id, final['evidence_ref']))
            if len(matches) != 1:
                raise ValueError('reference fixture selection lacks a unique eligible stage result')
            from zoo.circle_packing.reference_selection import read_reference_selection
            saved = read_reference_selection(workspace, selected)
            final_start = stage_starts[matches[0][0]]
            request_ids = ([final_start['prior_id'], final_start['request_id']] if final_start['stage'] == 2
                           else [final_start['request_id']])
            with authority.budget._lock:
                physical_rows = list(authority.budget.store.read())
                rows_sha256 = payload_digest(physical_rows)
                worker = ledger.cell_worker_claim(deadline._record['cell_id'])
                if worker != claim:
                    raise ValueError('reference snapshot lacks its original worker claim')
                run_id = authority.dispatch.ready.authority_binding['currency_run_id']
                def anchor(observation):
                    if not observation['eligible']:
                        from zoo.circle_packing.cell_deadline import DeadlineExpired
                        raise DeadlineExpired('reference physical snapshot is late')
                    value = observation['observation']
                    ledger.anchor_reference_physical_snapshot(run_id, deadline._record['cell_id'], rows_sha256,
                        worker['worker_ref'], request_ids, value['sequence'], value['sha256'],
                        worker_proof_sha256=payload_digest(worker_proof))
                deadline.observe_and_anchor(anchor)
            def freeze_selection():
                def anchor_selection(observation):
                    if not observation['eligible']:
                        from zoo.circle_packing.cell_deadline import DeadlineExpired
                        raise DeadlineExpired('reference selection freeze is late')
                    value = observation['observation']
                    ledger.freeze_reference_selection(run_id, deadline._record['cell_id'], payload_digest(selected),
                                                       value['sequence'], value['sha256'])
                deadline.observe_and_anchor(anchor_selection)
            freeze_selection()
            return {'state': 'completed', 'mode': 'fixture', 'performance_claim': False,
                    'selected_program': selected, 'stage_request_id': matches[0][0],
                    'stage_evidence_ref': matches[0][1], 'saved_program_ref': saved['saved_program_ref'],
                    'physical_snapshot_ref': 'sha256:' + rows_sha256, 'worker_proof': worker_proof}
        return authority._lease.seal(finalize_selection)
    finally:
        token_path.unlink(missing_ok=True)
