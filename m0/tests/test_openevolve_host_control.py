"""Reference control reuses existing protected-control lifecycle and evidence."""
import asyncio

import pytest

from core.budget.types import AccountingStamp
from core.composition.budget import HierarchicalBudget
from core.composition.contracts import GovernanceConfig
from core.composition.external_provider import ExternalRunContext
from core.composition.governance import ControlPlan
from core.composition.recovery import ContinuationStore
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.mle_bench_lite.composed_domain import SandboxRunner
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider


@pytest.fixture
def control_authority(tmp_path, local_endpoint, request):
    ledger = campaign_fixture(tmp_path)
    campaign = ledger.manifest_binding()
    def fresh(operator_cap):
        return GovernedCNYProvider('deepseek-flash', local_endpoint.url, campaign_binding=campaign,
            max_completion_tokens=4, api_key='fixture-only-secret', message_mode='openevolve_host_v1',
            phase_call_limits={'operator': operator_cap, 'evaluation': 0})
    main, control = fresh(1), fresh(1 if getattr(request, "param", None) == "one_control_call" else 2)
    bound = main.governance_binding()['call_bound']['units']['token']
    controls = {'after_main_cycles': [0], 'seed': 0,
        'provider': {'name': 'control'}, 'domain': {'name': 'control'}, 'operator': {'name': 'draft'},
        'request': {'fidelity': 'dev', 'split_id': 'dev'},
        'reservations': {'operator': {'token': 2 * bound, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 0, 'node': 0, 'eval_count': 2}}}
    config = GovernanceConfig.from_dict({'schema_version': 1, 'controls': controls}).to_dict()
    limits = {'token': bound * 4, 'node': 8, 'eval_count': 8}
    options = {'limits': {level: dict(limits) for level in ('global', 'direction', 'candidate')},
        'require_initial_control': True,
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {'operator': {'token': bound, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev'}]}
    store = ContinuationStore(tmp_path / 'events.jsonl')
    budget = HierarchicalBudget(options, AccountingStamp('offline', 'fixture-v1', 'tokens-v1', 'price-v1', 'today'),
                                store, governance=config)
    main_domain = CirclePackingDomain(tmp_path / 'main-domain', runner=SandboxRunner())
    plan = ControlPlan.freeze(config, task_desc='Improve circle packing',
                              initial_context={'circle_domain_binding': main_domain.manifest_binding},
                              max_generations=6, units=budget.units).to_dict()
    budget.protect_controls(plan)
    context = ExternalRunContext(logical_run_id='a' * 32, runtime_id='composed-v8-governed-external',
        workdir=str(tmp_path), physical_plan=plan, main_provider_binding=main.governance_binding(),
        control_provider_bindings={'control-0000': control.governance_binding()}, mode='live', recorded_bundle=None,
        store=store, physical_identity_lookup=budget.invocation_identity,
        provider_sessions={'main': main, 'control-0000': control})
    bridge = CNYInvocationBridge(ledger)
    ready = bridge.bind_run(context)
    return ledger, budget, bridge, context, ready, main_domain


def test_seed_control_uses_existing_lifecycle_and_replays_without_calls(control_authority, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    assert control.domain is not domain and control.domain.runner is not domain.runner
    assert control.domain.workspace.resolve() != domain.workspace.resolve()
    terminal = asyncio.run(control.execute('control-0000'))
    assert terminal['status'] == 'evaluated'
    assert budget.audit_governance()['slots']['control-0000']['status'] == 'evaluated'
    assert budget.audit_governance()['physical_totals']['eval_count'] == 1
    assert budget.main_state()['limits']['global']['token'] == 2 * (1048576 + 4)
    assert not local_endpoint.requests and not ledger.snapshot()['pending_calls']
    assert ledger.snapshot()['protected_micro_cny'] == 0
    before = ledger.snapshot()
    def forbidden(*args, **kwargs):
        raise AssertionError('terminal control repeated evaluation')
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
    assert asyncio.run(control.execute('control-0000')) == terminal
    assert ledger.snapshot() == before and not local_endpoint.requests


def test_control_rejects_nonfresh_domain_before_any_work(control_authority, local_endpoint):
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    domain._entries['nonempty'] = {}
    with pytest.raises(ValueError):
        HostSeedControl(budget, bridge, run, ready, domain)
    assert not local_endpoint.requests


def test_control_rejects_unpinned_sandbox_before_any_work(control_authority, local_endpoint):
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    domain.stage_timeout = 1
    with pytest.raises(ValueError):
        HostSeedControl(budget, bridge, run, ready, domain)
    assert not local_endpoint.requests


def test_unknown_control_evaluation_keeps_reservation_and_cannot_repeat(control_authority, local_endpoint, monkeypatch):
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    async def interrupted(*args, **kwargs):
        raise RuntimeError('fixture evaluation interrupted')
    monkeypatch.setattr(control.domain, 'evaluate', interrupted)
    with pytest.raises(RuntimeError):
        asyncio.run(control.execute('control-0000'))
    assert budget.state()['open_intents'] and ledger.snapshot()['protected_micro_cny'] > 0
    assert not list(budget.store.read('governed_control_terminal'))
    with pytest.raises(ValueError):
        asyncio.run(control.execute('control-0000'))


def test_control_rejects_main_work_that_precedes_slot_zero(control_authority, local_endpoint):
    from core.budget.ledger import BudgetError
    from core.executor.types import Candidate
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    candidate = Candidate('previous-main')
    with pytest.raises(BudgetError):
        budget.reserve_operation('previous-main', candidate, 'main', 'operator')
    assert not list(budget.store.read('governed_control_started')) and not local_endpoint.requests


def test_main_dispatch_requires_audited_independent_control(control_authority, local_endpoint):
    import json
    from test_governed_cny_provider import reply
    from test_openevolve_governed_transport import host_prompt
    from zoo.circle_packing.host_control import HostSeedControl
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    ledger, budget, bridge, run, ready, domain = control_authority
    dispatch = HostDispatchCoordinator(budget, bridge, run, ready)
    with pytest.raises(ValueError, match='control'):
        dispatch('a' * 32, json.loads(host_prompt()))
    assert not local_endpoint.requests and not ledger.snapshot()['pending_calls']
    assert asyncio.run(HostSeedControl(budget, bridge, run, ready, domain).execute('control-0000'))['status'] == 'evaluated'
    local_endpoint.responses.append(reply())
    assert dispatch('a' * 32, json.loads(host_prompt()))['state'] == 'ok'
    assert len(local_endpoint.requests) == 1


def test_main_stage_requires_audited_control_before_execution(control_authority, tmp_path):
    import hashlib
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator, HostDispatchRouter
    from zoo.circle_packing.host_physical import HostStageAdmission
    ledger, budget, bridge, run, ready, domain = control_authority
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    stage = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'main-stage', control_authority=provider)
    program = 'print(1)'
    argument = {'stage': 1, 'program': program,
                'program_ref': 'sha256:' + hashlib.sha256(program.encode()).hexdigest(), 'prior_id': None}
    with pytest.raises(ValueError, match='control'):
        HostDispatchRouter(provider, stage)('a' * 32, argument)
    assert not list(budget.store.read('host_stage_started'))


def test_main_reservation_cannot_interleave_with_control_execution(control_authority, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from core.executor.types import Candidate
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    original = control.domain.evaluate
    async def delayed(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        return await original(*args, **kwargs)
    monkeypatch.setattr(control.domain, 'evaluate', delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        control_future = pool.submit(lambda: asyncio.run(control.execute('control-0000')))
        assert entered.wait(5)
        def reserve_main():
            attempted.set()
            return budget.reserve_operation('next', Candidate('next'), 'main', 'operator')
        main_future = pool.submit(reserve_main)
        assert attempted.wait(5)
        assert not threading.Event().wait(.05)
        assert not main_future.done()
        release.set()
        assert control_future.result(timeout=15)['status'] == 'evaluated'
        assert main_future.result(timeout=5).granted


def test_same_event_loop_cannot_reserve_main_while_control_is_running(control_authority, monkeypatch):
    from core.budget.ledger import BudgetError
    from core.executor.types import Candidate
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = control.domain.evaluate
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        monkeypatch.setattr(control.domain, 'evaluate', delayed)
        task = asyncio.create_task(control.execute('control-0000'))
        await entered.wait()
        with pytest.raises(BudgetError):
            budget.reserve_operation('main-during-control', Candidate('main-during-control'), 'main', 'operator')
        release.set()
        assert (await task)['status'] == 'evaluated'
    asyncio.run(scenario())


def test_control_rejects_different_interpreter_binding(control_authority, tmp_path):
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    runner = SandboxRunner()
    runner.interpreter = '/usr/bin/python3'
    other = CirclePackingDomain(tmp_path / 'other-main', runner=runner)
    with pytest.raises(ValueError):
        HostSeedControl(budget, bridge, run, ready, other)


def test_measured_control_failure_invalidates_protection(control_authority, local_endpoint, monkeypatch):
    from core.composition.evaluation import MeasuredEvaluationError
    from core.executor.types import CostVec
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    async def failed(*args, **kwargs):
        raise MeasuredEvaluationError('failed', CostVec(eval_count=1), ('token', 'node', 'eval_count'), 'split', 0)
    monkeypatch.setattr(control.domain, 'evaluate', failed)
    with pytest.raises(MeasuredEvaluationError):
        asyncio.run(control.execute('control-0000'))
    audit = budget.audit_governance()
    assert audit['slots']['control-0000']['status'] == 'failed'
    assert not audit['protection_valid'] and ledger.snapshot()['protected_micro_cny'] > 0
    assert not local_endpoint.requests


def test_control_terminal_tampering_is_rejected(control_authority, monkeypatch):
    import copy
    from core.budget.ledger import BudgetError
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    asyncio.run(control.execute('control-0000'))
    original = budget.store.read
    def forged(kind=None):
        rows = copy.deepcopy(list(original(kind)))
        for row in rows:
            if row['kind'] == 'governed_control_terminal':
                row['payload']['proposal']['artifact'] += '\n# forged'
        return iter(rows)
    monkeypatch.setattr(budget.store, 'read', forged)
    with pytest.raises((ValueError, BudgetError)):
        asyncio.run(control.execute('control-0000'))


def test_control_recovers_settled_operator_without_repeating_it(control_authority, tmp_path, monkeypatch, local_endpoint):
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, main_domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, main_domain)
    reserve = budget.reserve_control_operation
    def crash(slot, phase, candidate, request=None):
        if phase == 'evaluation':
            raise SystemExit('fixture crash after operator settlement')
        return reserve(slot, phase, candidate, request=request)
    monkeypatch.setattr(budget, 'reserve_control_operation', crash)
    with pytest.raises(SystemExit):
        asyncio.run(control.execute('control-0000'))
    assert budget.audit_governance()['slots']['control-0000']['status'] == 'proposed'
    restored_store = ContinuationStore(budget.store.path)
    restored_budget = HierarchicalBudget(budget.options, budget.stamp, restored_store,
                                         governance=budget._governed.config)
    restored_budget.restore_from_journal()
    restored_run = ExternalRunContext(**run.to_dict(), store=restored_store,
        physical_identity_lookup=restored_budget.invocation_identity, provider_sessions=dict(run.provider_sessions))
    restored_bridge = CNYInvocationBridge(ledger)
    restored_ready = restored_bridge.bind_run(restored_run)
    fresh_main = CirclePackingDomain(main_domain.workspace, runner=SandboxRunner())
    terminal = asyncio.run(HostSeedControl(restored_budget, restored_bridge, restored_run,
                                          restored_ready, fresh_main).execute('control-0000'))
    assert terminal['status'] == 'evaluated' and not local_endpoint.requests
    assert restored_budget.audit_governance()['physical_totals']['node'] == 1


def test_control_recovery_rejects_changed_original_operator_proposal(control_authority, monkeypatch):
    import copy
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, main_domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, main_domain)
    reserve = budget.reserve_control_operation
    def crash(slot, phase, candidate, request=None):
        if phase == 'evaluation':
            raise SystemExit('fixture crash after operator settlement')
        return reserve(slot, phase, candidate, request=request)
    monkeypatch.setattr(budget, 'reserve_control_operation', crash)
    with pytest.raises(SystemExit):
        asyncio.run(control.execute('control-0000'))
    monkeypatch.setattr(budget, 'reserve_control_operation', reserve)
    original = budget.store.read
    def forged(kind=None):
        rows = copy.deepcopy(list(original(kind)))
        for row in rows:
            if row['kind'] == 'governed_operator_outcome':
                row['payload']['proposal']['artifact'] += '\n# forged'
        return iter(rows)
    monkeypatch.setattr(budget.store, 'read', forged)
    async def forbidden(*args, **kwargs):
        raise AssertionError('changed source reached evaluation')
    monkeypatch.setattr(control.domain, 'evaluate', forbidden)
    with pytest.raises(ValueError):
        asyncio.run(control.execute('control-0000'))


@pytest.mark.parametrize('control_authority', ['one_control_call'], indirect=True)
def test_control_rejects_underprotected_currency(control_authority):
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    with pytest.raises(ValueError, match='currency'):
        HostSeedControl(budget, bridge, run, ready, domain)
    assert not list(budget.store.read('governed_control_started'))


def test_stage_cannot_bypass_or_switch_control_budget(control_authority, tmp_path):
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator, HostDispatchRouter
    from zoo.circle_packing.host_physical import HostStageAdmission
    ledger, budget, bridge, run, ready, domain = control_authority
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    with pytest.raises(ValueError, match='authority'):
        HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'main')
    stages = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'main', control_authority=provider)
    with pytest.raises(ValueError, match='authority'):
        HostDispatchRouter(None, stages)
    other = HierarchicalBudget(budget.options, budget.stamp, ContinuationStore(tmp_path / 'other.jsonl'),
                               governance=budget._governed.config)
    other.protect_controls(run.physical_plan)
    with pytest.raises(ValueError, match='authority'):
        HostStageAdmission(other, runner=SandboxRunner(), workspace=tmp_path / 'other', control_authority=provider)


def test_stage_rechecks_sandbox_before_each_execution(control_authority, tmp_path):
    from zoo.circle_packing.host_control import HostSeedControl
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    ledger, budget, bridge, run, ready, domain = control_authority
    asyncio.run(HostSeedControl(budget, bridge, run, ready, domain).execute('control-0000'))
    provider = HostDispatchCoordinator(budget, bridge, run, ready)
    runner = SandboxRunner()
    stage = HostStageAdmission(budget, runner=runner, workspace=tmp_path / 'main-stage', control_authority=provider)
    runner.interpreter = '/usr/bin/python3'
    with pytest.raises(ValueError):
        stage.execute('a' * 32, 'print(1)', stage=1)
    assert not list(budget.store.read('host_stage_started'))


def test_replay_rejects_missing_original_control_terminal(control_authority, monkeypatch):
    from core.budget.ledger import BudgetError
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    asyncio.run(HostSeedControl(budget, bridge, run, ready, domain).execute('control-0000'))
    original = budget.store.read
    def without_terminal(kind=None):
        return iter(row for row in original(kind) if row['kind'] != 'governed_control_terminal')
    monkeypatch.setattr(budget.store, 'read', without_terminal)
    restored = HierarchicalBudget(budget.options, budget.stamp, budget.store, governance=budget._governed.config)
    with pytest.raises(BudgetError, match='terminal'):
        restored.restore_from_journal()


def test_physical_host_requires_control_authority(control_authority):
    from zoo.circle_packing.host_physical import HostPhysicalAdmission
    ledger, budget, bridge, run, ready, domain = control_authority
    with pytest.raises(ValueError, match='authority'):
        HostPhysicalAdmission(budget)


def test_mutating_frozen_budget_cannot_disable_control(control_authority, tmp_path):
    from core.budget.ledger import BudgetError
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    ledger, budget, bridge, run, ready, domain = control_authority
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stage = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'main', control_authority=authority)
    budget.options['require_initial_control'] = False
    with pytest.raises((BudgetError, ValueError)):
        stage.execute('a' * 32, 'print(1)', stage=1)
    assert not list(budget.store.read('host_stage_started'))


def test_mutating_internal_gate_flag_cannot_disable_control(control_authority, tmp_path):
    from core.budget.ledger import BudgetError
    from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
    from zoo.circle_packing.host_physical import HostStageAdmission
    ledger, budget, bridge, run, ready, domain = control_authority
    authority = HostDispatchCoordinator(budget, bridge, run, ready)
    stage = HostStageAdmission(budget, runner=SandboxRunner(), workspace=tmp_path / 'main', control_authority=authority)
    budget._require_initial_control = False
    with pytest.raises(BudgetError, match='configuration'):
        stage.execute('a' * 32, 'print(1)', stage=1)
    assert not list(budget.store.read('host_stage_started'))


def test_fake_control_terminal_cannot_authorize_main(control_authority):
    from core.executor.types import Candidate
    from core.x1.checkpoint import payload_digest
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    candidate = Candidate('fake-control')
    for phase, costs in [('operator', {'token': 0, 'node': 1, 'eval_count': 0}),
                         ('evaluation', {'token': 0, 'node': 0, 'eval_count': 1})]:
        receipt = budget.reserve_control_operation('control-0000', phase, candidate)
        budget.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
        budget.settle_operation(receipt.intent_id, costs, measured_units=budget.units, fingerprint=receipt.fingerprint)
    fake = {'slot_id': 'control-0000', 'plan_ref': run.physical_plan['plan_ref'], 'status': 'evaluated'}
    budget.store.append('governed_control_terminal', fake)
    with pytest.raises(ValueError):
        budget.authorize_initial_control('control-0000', 'sha256:' + payload_digest(fake),
                                         bridge=bridge, run=run, domain=control.domain)
    assert budget.state()['initial_control_ready'] is None


def test_mismatched_evaluation_binding_invalidates_settled_control(control_authority, monkeypatch):
    from dataclasses import replace
    from zoo.circle_packing.host_control import HostSeedControl
    ledger, budget, bridge, run, ready, domain = control_authority
    control = HostSeedControl(budget, bridge, run, ready, domain)
    original = control.domain.evaluate
    async def wrong_binding(*args, **kwargs):
        result = await original(*args, **kwargs)
        binding = replace(result.contract.binding, artifact_sha256='0' * 64)
        return replace(result, contract=replace(result.contract, binding=binding))
    monkeypatch.setattr(control.domain, 'evaluate', wrong_binding)
    with pytest.raises(ValueError):
        asyncio.run(control.execute('control-0000'))
    audit = budget.audit_governance()
    assert audit['slots']['control-0000']['status'] == 'failed'
    assert not audit['protection_valid'] and audit['physical_totals']['eval_count'] == 1
    assert not list(budget.store.read('governed_control_terminal'))
    assert budget.state()['initial_control_ready'] is None
