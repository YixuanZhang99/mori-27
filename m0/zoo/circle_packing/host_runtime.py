"""Compose reference-cell authorities from a frozen pilot and original campaign.

This factory does not start the controller or authorize a live pilot. It uses
the existing physical and currency journals and does not persist provider keys.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import os
from pathlib import Path
import re
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
    def operation(self):
        with self._mutex:
            self.check()
            self._active += 1
        try:
            if self._on_start is None:
                raise RuntimeError('reference owner lacks its work-start authority')
            self._on_start()
            yield
        finally:
            with self._mutex:
                self._active -= 1

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
