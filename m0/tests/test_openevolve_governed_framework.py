"""Real Framework currency/role plumbing over loopback, never a paid run."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from core.loop import Framework, LoopConfig
from core.llm import UsageError
from test_governed_cny_framework import campaign_fixture
from test_governed_cny_provider import local_endpoint, reply
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.mle_bench_lite.composed_domain import SandboxRunner


@pytest.mark.linux
def test_timed_zero_candidate_normal_completion_finishes_but_replay_is_refused(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan

    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    ref = 'sha256:' + plan['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(campaign),
                               cell_id='mori-0', plan_ref=ref, seconds=2700)
    options = dict(ledger=campaign, api_key='fixture-only-secret', seed=0, iterations=1,
                   base_url=local_endpoint.url, max_completion_tokens=4,
                   cell_deadline=clock, draft_plan=plan, expected_plan_ref=ref)
    profile, registry, provider = governed_setup(tmp_path / 'run', **options)
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
                                cfg, str(tmp_path / 'run' / 'framework'), component_registry=registry)

    async def empty_cycle(task, cycle):
        # Exercise normal loop completion without fabricating any proposal or evaluation.
        fw._composed.next_cycle = cycle + 1
        fw._composed._save()
        return True

    monkeypatch.setattr(fw._composed, '_cycle', empty_cycle)
    result = fw.evolve('fixture task')
    assert result['reporting']['final_audit']['reason'] == 'no successful candidate'
    assert not local_endpoint.requests
    bridge = fw._composed.governed.external
    assert campaign.empty_terminal(bridge._ready.authority_binding['currency_run_id']) is None
    with pytest.raises(UsageError, match='empty run lacks'):
        bridge.replay_bundle()


@pytest.mark.linux
def test_timed_zero_candidate_run_replays_without_external_work(tmp_path, local_endpoint, monkeypatch):
    from core.composition.budget import ConvergenceSignal, HierarchicalBudget
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider

    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    ref = 'sha256:' + plan['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(campaign),
                               cell_id='mori-0', plan_ref=ref, seconds=2700)
    options = dict(ledger=campaign, api_key='fixture-only-secret', seed=0, iterations=1,
                   base_url=local_endpoint.url, max_completion_tokens=4,
                   cell_deadline=clock, draft_plan=plan, expected_plan_ref=ref)
    profile, registry, provider = governed_setup(tmp_path / 'run', **options)
    monkeypatch.setattr(HierarchicalBudget, 'converged',
                        lambda self, frontier=None: ConvergenceSignal('global_budget_exhausted', 'fixture'))
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    result = fw.evolve('fixture task')
    assert not fw._composed.proposals
    assert result['reporting']['final_audit']['reason'] == 'no successful candidate'
    assert not local_endpoint.requests

    def adapters(path, store):
        _, _, replay_provider = governed_setup(tmp_path / 'run', **options)
        return replay_provider, CirclePackingDomain(tmp_path / 'replay-domain', runner=SandboxRunner())

    def forbidden(*args, **kwargs):
        raise AssertionError('recorded replay performed external work')

    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
    assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert not local_endpoint.requests
    bridge = fw._composed.governed.external
    run_id = bridge._ready.authority_binding['currency_run_id']
    claim = campaign.cell_deadline_claim('mori-0')
    with pytest.raises(ValueError, match='original run and clock'):
        campaign.anchor_cycle_eligibility(run_id, 'a' * 64, 'mori-0', claim['observation_sequence'],
                                          claim['observation_sha256'], 'b' * 64)
    rows = bridge._root_rows()
    import copy
    # A missing ordinary stop is damaged evidence, not another valid stop.
    with monkeypatch.context() as patch:
        patch.setattr(bridge, '_root_rows', lambda: [row for row in rows if row['kind'] != 'governed_main_stopped'])
        with pytest.raises(UsageError, match='stopped, controlled final transcript'):
            bridge.record_empty_terminal()
    for kind in ('governed_main_stopped', 'metric_final_frozen', 'metric_final_completed'):
        altered = copy.deepcopy(rows)
        altered = [row for row in altered if row['kind'] != kind]
        with monkeypatch.context() as patch:
            patch.setattr(bridge, '_root_rows', lambda: altered)
            with pytest.raises((RuntimeError, ValueError)):
                fw.replay(adapter_factory=adapters)
    with monkeypatch.context() as patch:
        patch.setattr(campaign, 'empty_terminal', lambda run_id: None)
        with pytest.raises(RuntimeError, match='replay execution failed'):
            fw.replay(adapter_factory=adapters)


@pytest.mark.linux
def test_mori_control_and_main_use_same_locked_runtime(tmp_path, local_endpoint, monkeypatch):
    from test_openevolve_source_preflight import draft
    from zoo.circle_packing.frozen_source import freeze_source_plan
    from zoo.circle_packing.frozen_runtime import prepare_frozen_runtime
    from zoo.circle_packing.governed import governed_setup
    campaign = campaign_fixture(tmp_path)
    runner = SandboxRunner()
    clock_options = {}
    cache = os.environ.get('MORI_TEST_OFFLINE_CACHE')
    if cache:
        repository = Path(__file__).resolve().parents[2]
        commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
        checkout = tmp_path / 'checkout'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repository), str(checkout)], check=True)
        subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', commit], check=True)
        plan, ref = draft(campaign, checkout, commit)
        campaign_id = campaign.manifest_binding()['campaign_id']
        source = tmp_path / 'source'
        exported = freeze_source_plan(campaign, plan, checkout=checkout, destination=source,
                                      expected_plan_ref=ref, expected_campaign_id=campaign_id, require_runtime=True)
        runtime = tmp_path / 'runtime'
        frozen = prepare_frozen_runtime(campaign, plan, snapshot=source, source_manifest=exported['manifest'],
            expected_plan_ref=ref, expected_campaign_id=campaign_id, destination=runtime,
            base_python='/usr/bin/python3.12', uv_cache=cache)
        runner = SandboxRunner.for_campaign_runtime(campaign, runtime=runtime, manifest=frozen['manifest'],
                                                    base_python='/usr/bin/python3.12')
        from core.composition.recovery import ContinuationStore
        from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
        clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(campaign),
                                   cell_id='mori-0', plan_ref=ref, seconds=plan['limits']['wallclock_seconds'])
        clock_options = {'cell_deadline': clock, 'draft_plan': plan, 'expected_plan_ref': ref}
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content':
        '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # fixture\n>>>>>>> REPLACE\n'}}]))
    options = dict(ledger=campaign, api_key='fixture-only-secret', seed=0, iterations=1,
                   base_url=local_endpoint.url, max_completion_tokens=4, runner=runner, **clock_options)
    profile, registry, provider = governed_setup(tmp_path / 'run', **options)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=runner)
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    fw.evolve('Improve the arrangement of 26 circles in a square')
    assert fw.inspect()['governance']['completed'] == 1
    assert len(local_endpoint.requests) == 1 and not campaign.snapshot()['pending_calls']
    if cache:
        assert runner.manifest_binding['runtime_ref'] == campaign.circle_runtime_binding()['runtime_ref']
    def adapters(path, store):
        _, _, replay_provider = governed_setup(tmp_path / 'run', **options)
        return replay_provider, CirclePackingDomain(tmp_path / 'replay-domain', runner=runner.independent_runner())
    if cache:
        from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
        def forbidden(*args, **kwargs):
            raise AssertionError('recorded replay performed live work')
        monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
        monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
        assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
        import copy
        bridge = fw._composed.governed.external
        original_bundle = bridge.replay_bundle()
        changed = copy.deepcopy(original_bundle)
        changed['timing']['clock']['observations'][0]['observed_ns'] += 1
        monkeypatch.setattr(bridge, 'replay_bundle', lambda: changed)
        with pytest.raises(RuntimeError, match='replay execution failed'):
            fw.replay(adapter_factory=adapters)
        changed = copy.deepcopy(original_bundle)
        changed['timing']['responses'][0]['observation']['eligible'] = False
        monkeypatch.setattr(bridge, 'replay_bundle', lambda: changed)
        with pytest.raises(RuntimeError, match='replay execution failed'):
            fw.replay(adapter_factory=adapters)
    else:
        assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 1


def test_governed_circle_run_binds_roles_control_cost_and_replay(tmp_path, local_endpoint, monkeypatch):
    from zoo.circle_packing.governed import governed_setup
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content':
        '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # governed fixture\n>>>>>>> REPLACE\n'}}]))
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4))
    assert profile['budget']['options']['limits']['global']['token'] == 4 * (1048576 + 4)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    result = fw.evolve('Improve the arrangement of 26 circles in a square')
    assert 'governed-external' in result['runtime']
    wire = json.loads(local_endpoint.requests[0])
    assert [message['role'] for message in wire['messages']] == ['system', 'user']
    audit = fw._composed.governed.external.audit()
    assert audit['protection_valid'] and not audit['unknown_cost_calls']
    assert campaign.snapshot()['pending_calls'] == []
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 38
    controls = fw.inspect()['governance']
    assert controls['completed'] == 1 and controls['unresolved'] == 0
    def adapters(path, store):
        _, _, fresh_provider = governed_setup(tmp_path / 'run', ledger=campaign,
            api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
            max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4))
        return fresh_provider, CirclePackingDomain(tmp_path / 'replay-domain', runner=SandboxRunner())
    def forbidden(*args, **kwargs):
        raise AssertionError('recorded replay made an HTTP request')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 1
    for path in (tmp_path / 'run').rglob('*'):
        if path.is_file():
            assert b'fixture-only-secret' not in path.read_bytes()


def test_evaluation_anchor_failure_keeps_measured_control_and_blocks_use(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40, dependency_lock_sha256='b' * 64)
    ref = 'sha256:' + plan['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(campaign),
                               cell_id='mori-0', plan_ref=ref, seconds=2700)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, cell_deadline=clock, draft_plan=plan, expected_plan_ref=ref)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    def crash(*args, **kwargs):
        raise RuntimeError('fixture evaluation anchor failure')
    monkeypatch.setattr(campaign, 'anchor_evaluation_eligibility', crash)
    with pytest.raises(RuntimeError, match='anchor failure'):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    assert not local_endpoint.requests and not campaign.snapshot()['pending_calls']
    assert fw._composed.budget.audit_governance()['physical_totals']['eval_count'] >= 1
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()


def test_governed_circle_unknown_usage_keeps_reservation(tmp_path, local_endpoint):
    from zoo.circle_packing.governed import governed_setup
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.append(reply(usage=None))
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(UsageError):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    assert len(local_endpoint.requests) == 1
    assert len(campaign.snapshot()['pending_calls']) == 1


def test_common_ceiling_must_fit_protected_control_and_main_attempts(tmp_path, local_endpoint):
    from zoo.circle_packing.governed import governed_setup
    campaign = campaign_fixture(tmp_path)
    with pytest.raises(ValueError, match='ceiling'):
        governed_setup(tmp_path / 'run', ledger=campaign, api_key='fixture-only-secret',
            seed=0, iterations=1, base_url=local_endpoint.url, max_completion_tokens=4,
            total_token_ceiling=4 * (1048576 + 4) - 1)
    assert not campaign.snapshot()['pending_calls']


def test_common_ceiling_includes_repair_attempts_and_control(tmp_path, local_endpoint):
    from zoo.circle_packing.governed import governed_setup
    campaign = campaign_fixture(tmp_path)
    local_endpoint.responses.extend([
        reply(choices=[{'finish_reason': 'stop', 'message': {'content': 'invalid diff'}}]),
        reply(choices=[{'finish_reason': 'stop', 'message': {'content':
            '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # repaired\n>>>>>>> REPLACE\n'}}])])
    ceiling = 4 * (1048576 + 4)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=ceiling)
    cfg = LoopConfig(max_generations=1, total_budget=ceiling, reeval_floor=0, baseline_every=100)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    fw.evolve('Improve the arrangement of 26 circles in a square')
    assert len(local_endpoint.requests) == 2
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 76
    assert fw.inspect()['governance']['completed'] == 1
    second = json.loads(local_endpoint.requests[1])['messages'][1]['content']
    assert 'Repair feedback:' in second


def test_mori_late_provider_is_billed_and_stops_before_candidate(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content':
        '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # too late\n>>>>>>> REPLACE\n'}}]))
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    original = GovernedCNYProvider.perform_request
    def late(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self is provider:
            now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', late)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    result = fw.evolve('Improve the arrangement of 26 circles in a square')
    assert result['reporting']['final_audit']['state'] == 'skipped'
    assert len(local_endpoint.requests) == 1 and not campaign.snapshot()['pending_calls']
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 38
    audit = fw._composed.budget.audit_governance()
    assert audit['physical_totals']['token'] == 7 and not audit['open_intents']
    assert len(fw._composed.proposals) == 1
    assert fw._composed.governed.external.audit()['protection_valid']
    assert len(list(fw._composed.store.read('composed_provider_deadline_expired'))) == 1
    timing = list(fw._composed.store.read('governed_work_eligibility'))
    control = [row['payload'] for row in timing if row['payload']['phase'] == 'evaluation'
               and row['payload']['lane'] == 'control']
    assert len(control) == 1 and control[0]['observation']['eligible'] is True
    selections = [row['payload'] for row in timing if row['payload']['phase'] == 'cycle_commit']
    assert len(selections) == 1 and selections[0]['observation']['eligible'] is True
    def adapters(path, store):
        _, _, replay_provider = governed_setup(tmp_path / 'run', ledger=campaign,
            api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
            max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
            cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
        return replay_provider, CirclePackingDomain(tmp_path / 'replay-domain', runner=SandboxRunner())
    def forbidden(*args, **kwargs):
        raise AssertionError('recorded replay performed live work')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
    assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 1
    import copy
    original_read = fw._composed.store.read
    def changed_cycle(kind=None):
        rows = copy.deepcopy(list(original_read(kind)))
        for row in rows:
            if row['kind'] == 'governed_work_eligibility' and row['payload']['phase'] == 'cycle_commit':
                row['payload']['decision_sha256'] = '0' * 64
        return iter(rows)
    monkeypatch.setattr(fw._composed.store, 'read', changed_cycle)
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()
    def missing_cycle(kind=None):
        return iter(row for row in original_read(kind) if not (row['kind'] == 'governed_work_eligibility'
                    and row['payload']['phase'] == 'cycle_commit'))
    monkeypatch.setattr(fw._composed.store, 'read', missing_cycle)
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()
    def duplicated_decision(kind=None):
        rows = list(original_read(kind))
        if kind is None:
            index = next(i for i, row in enumerate(rows) if row['kind'] == 'composed_decision')
            rows.insert(index + 1, copy.deepcopy(rows[index]))
        return iter(rows)
    monkeypatch.setattr(fw._composed.store, 'read', duplicated_decision)
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()
    def missing_decision(kind=None):
        return iter(row for row in original_read(kind) if row['kind'] != 'composed_decision')
    monkeypatch.setattr(fw._composed.store, 'read', missing_decision)
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()
    def altered(kind=None):
        rows = copy.deepcopy(list(original_read(kind)))
        for row in rows:
            if row['kind'] == 'governed_work_eligibility':
                row['payload']['observation']['eligible'] = False
        return iter(rows)
    monkeypatch.setattr(fw._composed.store, 'read', altered)
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()
    def missing(kind=None):
        return iter(row for row in original_read(kind) if row['kind'] != 'governed_work_eligibility')
    monkeypatch.setattr(fw._composed.store, 'read', missing)
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()
    def missing_both(kind=None):
        return iter(row for row in original_read(kind) if row['kind'] not in {
            'governed_work_eligibility', 'governed_evaluation_completed'})
    monkeypatch.setattr(fw._composed.store, 'read', missing_both)
    with pytest.raises(ValueError, match='eligibility'):
        fw._composed.governed.external.audit()


def test_mori_deadline_before_provider_is_proven_free_and_stops(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    original = CNYInvocationBridge.invoke
    def expire(self, context, args, kwargs):
        if context.lane == 'main':
            now['ns'] += 2700 * 1_000_000_000
        return original(self, context, args, kwargs)
    monkeypatch.setattr(CNYInvocationBridge, 'invoke', expire)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    fw.evolve('Improve the arrangement of 26 circles in a square')
    assert not local_endpoint.requests and not campaign.snapshot()['pending_calls']
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 0
    audit = fw._composed.budget.audit_governance()
    assert audit['physical_totals']['token'] == 0 and not audit['open_intents']
    assert len(fw._composed.proposals) == 1
    assert fw._composed.governed.external.audit()['protection_valid']


def test_mori_deadline_after_currency_admission_stays_unresolved(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    admit = campaign.admit_call
    def expire(*args, **kwargs):
        result = admit(*args, **kwargs)
        now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(campaign, 'admit_call', expire)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(UsageError):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    assert not local_endpoint.requests and len(campaign.snapshot()['pending_calls']) == 1
    assert fw._composed.budget.state()['open_intents']
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 0


def test_mori_expired_after_binding_starts_no_control_or_evaluation(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle, DeadlineExpired
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    original = CNYInvocationBridge.bind_cell_deadline
    def expire(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(CNYInvocationBridge, 'bind_cell_deadline', expire)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(DeadlineExpired):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    audit = fw._composed.budget.audit_governance()
    assert audit['physical_totals'] == {'token': 0, 'node': 0, 'eval_count': 0}
    assert not audit['open_intents'] and not local_endpoint.requests
    assert not list(fw._composed.store.read('governed_control_started'))


def test_mori_late_control_evaluation_is_charged_but_not_accepted(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from core.llm import ProviderDeadlineSignal
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    original = CirclePackingDomain.evaluate
    async def late(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        if self is not domain:
            now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', late)
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(ProviderDeadlineSignal):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    audit = fw._composed.budget.audit_governance()
    assert audit['physical_totals']['eval_count'] == 1 and not audit['open_intents']
    assert not list(fw._composed.store.read('governed_control_terminal'))
    assert not local_endpoint.requests


@pytest.mark.parametrize('crash_kind', ['composed_provider_completed', 'composed_provider_deadline_expired',
                                       'construction_outcome', 'operator_settlement'])
def test_mori_recovers_late_billed_response_without_repeating_after_crash(tmp_path, local_endpoint, monkeypatch, crash_kind):
    from dataclasses import replace
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    clock_path = tmp_path / 'cell-clock.jsonl'
    lifecycle = CellLifecycle(campaign)
    plan_ref = 'sha256:' + plan['draft_sha256']
    deadline = CellDeadline.start(ContinuationStore(clock_path), lifecycle=lifecycle,
                                  cell_id='mori-0', plan_ref=plan_ref, seconds=2700)
    def setup(clock):
        return governed_setup(tmp_path / 'run', ledger=campaign,
            api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
            max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
            cell_deadline=clock, draft_plan=plan, expected_plan_ref=plan_ref)
    profile, registry, provider = setup(deadline)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content':
        '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # late\n>>>>>>> REPLACE\n'}}]))
    original_perform = GovernedCNYProvider.perform_request
    def late(self, *args, **kwargs):
        result = original_perform(self, *args, **kwargs)
        now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', late)
    original_append = ContinuationStore.append
    def crash(self, kind, payload):
        if now['ns'] >= 2700 * 1_000_000_000 and (kind == crash_kind or
                crash_kind == 'operator_settlement' and kind == 'hierarchical_budget' and payload.get('event') == 'settle'):
            raise SystemExit('fixture crash after original currency settlement')
        return original_append(self, kind, payload)
    monkeypatch.setattr(ContinuationStore, 'append', crash)
    domain_path = tmp_path / 'run' / 'domain'
    domain = CirclePackingDomain(domain_path, runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(SystemExit):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    assert len(local_endpoint.requests) == 1 and campaign.snapshot()['settled_upper_bound_micro_cny'] == 38
    monkeypatch.setattr(ContinuationStore, 'append', original_append)
    def forbidden(*args, **kwargs):
        raise AssertionError('settled provider must not be dispatched twice')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    restored_clock = CellDeadline.restore(ContinuationStore(clock_path), lifecycle=lifecycle,
                                          cell_id='mori-0', plan_ref=plan_ref, seconds=2700)
    profile2, registry2, provider2 = setup(restored_clock)
    restored = Framework.from_profile(profile2, provider2, CirclePackingDomain(domain_path, runner=SandboxRunner()),
        replace(cfg, resume_from_checkpoint=True), str(tmp_path / 'run' / 'framework'), component_registry=registry2)
    result = restored.evolve('Improve the arrangement of 26 circles in a square')
    assert result['reporting']['final_audit']['state'] == 'skipped'
    assert len(local_endpoint.requests) == 1 and not campaign.snapshot()['pending_calls']
    audit = restored._composed.budget.audit_governance()
    assert audit['physical_totals']['token'] == 7 and not audit['open_intents']
    assert len(restored._composed.proposals) == 1
    assert restored._composed.governed.external.audit()['protection_valid']
    assert len(list(restored._composed.store.read('composed_provider_deadline_expired'))) == 1


def test_mori_control_expiry_between_stages_preserves_first_stage_cost(tmp_path, local_endpoint, monkeypatch):
    from core.composition.evaluation import MeasuredEvaluationError
    from core.composition.recovery import ContinuationStore
    from test_openevolve_host_stage_budget import fake_result
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    stages = []
    def first_then_expire(program, *, stage, **kwargs):
        stages.append(stage)
        result = fake_result(program, stage, score=.6)
        now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr('zoo.circle_packing.stage.run_stage', first_then_expire)
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(MeasuredEvaluationError):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    assert stages == [1] and not local_endpoint.requests
    audit = fw._composed.budget.audit_governance()
    assert audit['physical_totals']['eval_count'] == 1 and not audit['open_intents']
    assert not list(fw._composed.store.read('governed_control_terminal'))


@pytest.mark.parametrize('late', [False, True])
def test_mori_final_audit_preserves_timing_and_score(tmp_path, local_endpoint, monkeypatch, late):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content':
        '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # fixture\n>>>>>>> REPLACE\n'}}]))
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    original = CirclePackingDomain.evaluate
    async def late_final(self, proposal, request):
        result = await original(self, proposal, request)
        if late and request.split_id == 'final_audit':
            now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', late_final)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    result = fw.evolve('Improve the arrangement of 26 circles in a square')
    final = result['reporting']['final_audit']
    if not late:
        assert final['state'] == 'completed' and 'evidence' in final
        assert fw._composed.governed.external.audit()['protection_valid']
        return
    assert final['state'] == 'skipped' and 'deadline' in final['reason'] and 'evidence' not in final
    assert not fw._composed.budget.state()['open_intents']
    assert campaign.snapshot()['settled_upper_bound_micro_cny'] == 38
    import copy
    original_read = fw._composed.store.read
    def forged(kind=None):
        rows = copy.deepcopy(list(original_read(kind)))
        if kind is None:
            dev = next(row['payload']['evidence'] for row in rows if row['kind'] == 'composed_physical_evidence'
                       and row['payload']['request']['split_id'] == 'dev')
            for row in rows:
                if row['kind'] == 'metric_final_completed':
                    row['payload'] = {'candidate_id': final['candidate_id'], 'state': 'completed', 'evidence': dev}
        return iter(rows)
    monkeypatch.setattr(fw._composed.store, 'read', forged)
    with pytest.raises(ValueError, match='final.*eligibility'):
        fw._composed.governed.external.audit()
    def score_on_skipped(kind=None):
        rows = copy.deepcopy(list(original_read(kind)))
        for row in rows:
            if row['kind'] == 'metric_final_completed':
                row['payload']['score'] = 99.0
        return iter(rows)
    monkeypatch.setattr(fw._composed.store, 'read', score_on_skipped)
    with pytest.raises(ValueError, match='final.*eligibility'):
        fw._composed.governed.external.audit()


def test_mori_candidate_cannot_be_committed_after_deadline(tmp_path, local_endpoint, monkeypatch):
    from core.composition.defaults import MetricAdmission
    from core.composition.recovery import ContinuationStore
    from core.llm import ProviderDeadlineSignal
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    now = {'ns': 100}
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._boot_identity', lambda: 'boot-a')
    monkeypatch.setattr('zoo.circle_packing.cell_deadline._clock_ns', lambda: now['ns'])
    deadline = CellDeadline.start(ContinuationStore(tmp_path / 'cell-clock.jsonl'),
        lifecycle=CellLifecycle(campaign), cell_id='mori-0', plan_ref='sha256:' + plan['draft_sha256'], seconds=2700)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'stop', 'message': {'content':
        '<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # candidate\n>>>>>>> REPLACE\n'}}]))
    profile, registry, provider = governed_setup(tmp_path / 'run', ledger=campaign,
        api_key='fixture-only-secret', seed=0, iterations=1, base_url=local_endpoint.url,
        max_completion_tokens=4, total_token_ceiling=4 * (1048576 + 4),
        cell_deadline=deadline, draft_plan=plan, expected_plan_ref='sha256:' + plan['draft_sha256'])
    calls = {'count': 0}
    original = MetricAdmission.judge
    def expire_after_decision(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        calls['count'] += 1
        if calls['count'] == 2:
            now['ns'] += 2700 * 1_000_000_000
        return result
    monkeypatch.setattr(MetricAdmission, 'judge', expire_after_decision)
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    with pytest.raises(ProviderDeadlineSignal):
        fw.evolve('Improve the arrangement of 26 circles in a square')
    assert calls['count'] == 2 and len(fw._composed.proposals) == 1
    assert len(list(fw._composed.store.read('composed_decision'))) == 1
    assert not fw._composed.budget.state()['open_intents']


@pytest.mark.linux
def test_timed_known_provider_failure_is_settled_and_replays(tmp_path, local_endpoint, monkeypatch):
    from core.composition.recovery import ContinuationStore
    from zoo.circle_packing.cell_deadline import CellDeadline, CellLifecycle
    from zoo.circle_packing.governed import governed_setup
    from zoo.circle_packing.pilot_plan import build_draft_plan
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider

    campaign = campaign_fixture(tmp_path)
    plan = build_draft_plan(campaign.manifest_binding(), source_commit='a' * 40,
                            dependency_lock_sha256='b' * 64)
    ref = 'sha256:' + plan['draft_sha256']
    clock = CellDeadline.start(ContinuationStore(tmp_path / 'clock.jsonl'), lifecycle=CellLifecycle(campaign),
                               cell_id='mori-0', plan_ref=ref, seconds=2700)
    options = dict(ledger=campaign, api_key='fixture-only-secret', seed=0, iterations=1,
                   base_url=local_endpoint.url, max_completion_tokens=4,
                   cell_deadline=clock, draft_plan=plan, expected_plan_ref=ref)
    profile, registry, provider = governed_setup(tmp_path / 'run', **options)
    local_endpoint.responses.append(reply(choices=[{'finish_reason': 'length', 'message': {'content': 'partial'}}]))
    cfg = LoopConfig(max_generations=1, total_budget=profile['budget']['options']['limits']['global']['token'],
                     reeval_floor=0, baseline_every=100)
    domain = CirclePackingDomain(tmp_path / 'run' / 'domain', runner=SandboxRunner())
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run' / 'framework'),
                                component_registry=registry)
    fw.evolve('Improve the arrangement of 26 circles in a square')
    outcomes = [row['payload'] for row in fw._composed.store.read('construction_outcome')]
    assert any(row['outcome']['kind'] == 'failed' for row in outcomes)
    assert len(local_endpoint.requests) == 1 and not campaign.snapshot()['pending_calls']
    assert fw._composed.governed.external.audit()['protection_valid']
    assert fw._composed.budget.audit_governance()['physical_totals']['token'] == 7
    def adapters(path, store):
        _, _, replay_provider = governed_setup(tmp_path / 'run', **options)
        return replay_provider, CirclePackingDomain(tmp_path / 'replay-domain', runner=SandboxRunner())
    def forbidden(*args, **kwargs):
        raise AssertionError('recorded replay performed external work')
    monkeypatch.setattr(GovernedCNYProvider, 'perform_request', forbidden)
    monkeypatch.setattr(CirclePackingDomain, 'evaluate', forbidden)
    assert fw.replay(adapter_factory=adapters)['replay_certificate']['passed']
    assert len(local_endpoint.requests) == 1
