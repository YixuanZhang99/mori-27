"""Compose reference-cell authorities from a frozen pilot and original campaign.

This factory does not start the controller or authorize a live pilot. It uses
the existing physical and currency journals and does not persist provider keys.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import asyncio
import fcntl
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
from core.executor.process import ProcessJournal
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
        self._mutex, self._active, self._on_start = threading.Lock(), 0, None

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


def build_reference_authorities(output, *, ledger, plan, expected_plan_ref, expected_campaign_id,
                                deadline, snapshot, source_manifest, runner, api_key, base_url=None):
    """Prepare one bounded reference cell; callers still own process supervision."""
    if type(ledger) is not CampaignBudget or type(deadline) is not CellDeadline or \
            deadline._lifecycle.ledger is not ledger:
        raise ValueError('reference requires its original campaign and cell deadline')
    cell = deadline._record['cell_id']
    if not re.fullmatch(r'vendor-[012]', cell):
        raise ValueError('reference requires a declared vendor cell')
    binding = validate_draft_cell(ledger, plan, cell, expected_plan_ref=expected_plan_ref)
    if ledger.manifest_binding()['campaign_id'] != expected_campaign_id or \
            binding['campaign_id'] != expected_campaign_id or \
            deadline._record['plan_ref'] != expected_plan_ref or \
            deadline._record['seconds'] != binding['wallclock_seconds']:
        raise ValueError('reference cell differs from the frozen campaign or plan')
    pilot, runtime = ledger.circle_pilot_binding(), ledger.circle_runtime_binding()
    if pilot is None or not pilot.get('require_runtime') or runtime is None or \
            type(runner) is not SandboxRunner or runner._campaign_runtime is None or \
            runner._campaign_runtime[0] is not ledger or \
            runner.manifest_binding.get('runtime_ref') != runtime['runtime_ref']:
        raise ValueError('reference requires the original frozen campaign runtime')
    verify_frozen_source(ledger, plan, snapshot=snapshot, manifest=source_manifest,
                         expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id)
    if type(api_key) is not str or not api_key.strip():
        raise ValueError('reference provider requires an in-memory key')
    if type(base_url) is not str:
        raise ValueError('reference fixture requires an explicit loopback provider')
    url = urllib.parse.urlsplit(base_url)
    if url.scheme != 'http' or url.hostname not in {'127.0.0.1', '::1'} or \
            url.username or url.password or url.query or url.fragment:
        raise ValueError('reference fixture requires an explicit loopback provider')
    deadline.check()
    requested = Path(output)
    if requested.is_symlink():
        raise ValueError('reference output cannot be a symlink')
    root = requested.resolve()
    if root == ledger.path.resolve().parent or root in ledger.path.resolve().parents:
        raise ValueError('reference output must be separate from the campaign')
    authority_ref = payload_digest({'schema_version': 1, 'cell_id': cell,
        'deadline_ref': deadline._record['record_sha256'], 'plan_ref': expected_plan_ref,
        'campaign_id': expected_campaign_id, 'source_tree_ref': pilot['tree_ref'],
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
                                  currency_run_id=currency_run_id, lease=lease)
    except BaseException:
        lease.close()
        raise


def _build_authorities(root, *, ledger, plan, deadline, cell, expected_plan_ref, runner, api_key,
                       base_url, authority_ref, existing_claim, currency_run_id, lease):
    policy = ledger.manifest_binding()

    def provider(operator_cap):
        return GovernedCNYProvider(policy['model'], base_url,
            campaign_binding=policy, max_completion_tokens=plan['max_completion_tokens'],
            api_key=api_key, message_mode='openevolve_host_v1', reasoning_effort=plan['reasoning_effort'],
            phase_call_limits={'operator': operator_cap, 'evaluation': 0})

    main, control_provider = provider(1), provider(2)
    bound = main.governance_binding()['call_bound']['units']['token']
    if plan['limits']['token'] != 4 * bound:
        raise ValueError('reference token limit differs from the frozen provider capacity')
    limits = {unit: plan['limits'][unit] for unit in ('token', 'node', 'eval_count')}
    controls = {'after_main_cycles': [0], 'seed': int(cell.split('-')[1]),
        'provider': {'name': 'control'}, 'domain': {'name': 'control'}, 'operator': {'name': 'draft'},
        'request': {'fidelity': 'dev', 'split_id': 'dev'},
        'reservations': {'operator': {'token': 2 * bound, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 0, 'node': 0, 'eval_count': 2}}}
    governance = GovernanceConfig.from_dict({'schema_version': 1, 'controls': controls}).to_dict()
    options = {'limits': {level: dict(limits) for level in ('global', 'direction', 'candidate')},
        'require_initial_control': True, 'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'operator': {'token': bound, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}
    journal_path = root / 'events.jsonl'
    if journal_path.is_symlink():
        raise ValueError('reference physical journal cannot be a symlink')
    if journal_path.exists():
        info = journal_path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError('reference physical journal must be a private regular file')
    store = ContinuationStore(journal_path)
    stamp = AccountingStamp('deepseek', policy['model'], 'service-capacity-v1', policy['policy_sha256'], 'campaign')
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
    lease.bind_start(lambda: ledger.start_reference_authority_work(cell, authority_ref))
    run = ExternalRunContext(logical_run_id=authority_ref[:32], runtime_id=EXTERNAL_RUNTIME,
        workdir=str(root), physical_plan=physical_plan, main_provider_binding=main.governance_binding(),
        control_provider_bindings={'control-0000': control_provider.governance_binding()},
        mode='live', recorded_bundle=None, store=store, physical_identity_lookup=budget.invocation_identity,
        provider_sessions={'main': main, 'control-0000': control_provider})
    bridge = CNYInvocationBridge(ledger)
    ready = bridge.bind_run(run)
    bridge.bind_cell_deadline(deadline, plan=plan, expected_plan_ref=expected_plan_ref, cell_id=cell)
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
    if type(authority) is not ReferenceAuthorities:
        raise ValueError('reference fixture requires its original bounded cell authority')
    with authority._lease.session():
        return _run_reference_cell_fixture(authority, deadline, worker_directory, workspace,
            snapshot=snapshot, source_manifest=source_manifest, frozen_plan=frozen_plan,
            expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id,
            runtime=runtime, runtime_manifest=runtime_manifest, base_python=base_python, iterations=iterations)


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
    verify_frozen_source(ledger, frozen_plan, snapshot=snapshot, manifest=source_manifest,
                         expected_plan_ref=expected_plan_ref, expected_campaign_id=expected_campaign_id)
    runner = authority.control.domain.runner
    frozen_runtime = runner._campaign_runtime
    if frozen_runtime is None or frozen_runtime[0] is not ledger or \
            Path(runtime).resolve(strict=True) != runner.runtime_root or runtime_manifest != frozen_runtime[1] or \
            str(base_python) != frozen_runtime[2]:
        raise ValueError('reference fixture requires its original campaign runtime')
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
        if len(starts) != 1:
            raise ValueError('reference fixture lacks its original worker process')
        process = ProcessJournal(store).completed_result(starts[0]['payload'])
        if process['returncode'] != 0 or process['timeout'] or process['wrapper_error']:
            raise ValueError('reference fixture worker did not complete')
        report = json.loads(process['stdout'])
        selected = report.get('selected_program') if type(report) is dict else None
        if type(report) is not dict or report.get('mode') != 'fixture' or report.get('performance_claim') is not False or \
                report.get('controller') != 'pinned_openevolve' or type(selected) is not dict or \
                set(selected) != {'id', 'program_ref', 'metrics'} or type(selected['id']) is not str or \
                not selected['id'] or type(selected['metrics']) is not dict:
            raise ValueError('reference fixture has no valid selected program report')
        rows = list(authority.budget.store.read())
        stage_starts = {r['payload']['request_id']: r['payload'] for r in rows if r['kind'] == 'host_stage_started'}
        stage_ends = {r['payload']['request_id']: r['payload'] for r in rows if r['kind'] == 'host_stage_completed'}
        eligibility = {r['payload']['request_id']: r['payload'] for r in rows if r['kind'] == 'host_stage_eligibility'}
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
            if final['result']['status'] == 'ok' and final['result']['metrics'] == selected['metrics'] and \
                    authority.stages._verify_stage_eligibility(eligibility[final_id], stage_starts[final_id],
                                                              final, deadline):
                matches.append((final_id, final['evidence_ref']))
        if len(matches) != 1:
            raise ValueError('reference fixture selection lacks a unique eligible stage result')
        deadline.check()
        return {'state': 'completed', 'mode': 'fixture', 'performance_claim': False,
                'selected_program': selected, 'stage_request_id': matches[0][0],
                'stage_evidence_ref': matches[0][1]}
    finally:
        token_path.unlink(missing_ok=True)
