"""Actual public Framework: frozen seed, host mutation, and recorded replay."""
import json

from core.loop import Framework, LoopConfig
from zoo.circle_packing.domain import CirclePackingDomain
from zoo.mle_bench_lite.composed_domain import SandboxRunner


class FixtureProvider:
    model, supplier = 'circle-fixture', 'offline'
    def __init__(self):
        self.calls = 0
        self.last_usage = None
        self.requests = []
    def __call__(self, prompt):
        self.calls += 1
        self.last_usage = {'total_tokens': 7}
        value = json.loads(prompt)
        self.requests.append(value)
        return ('<<<<<<< SEARCH\n    n = 26\n=======\n'
                f'    n = 26\n    # fixture mutation {self.calls}\n>>>>>>> REPLACE\n')


def test_domain_binding_rejects_incompatible_adapters(tmp_path):
    from core.composition.openevolve_runtime import is_openevolve_domain
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    assert is_openevolve_domain(domain)
    class IncompatibleDomain(CirclePackingDomain):
        @property
        def openevolve_binding(self):
            return {'schema_version': 1, 'kind': 'other-evaluator'}
    assert not is_openevolve_domain(IncompatibleDomain(tmp_path / 'other', runner=SandboxRunner()))
    assert not is_openevolve_domain(object())


def test_public_framework_runs_seed_and_host_bound_mutations(tmp_path):
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=2, call_token_bound=128, migration_interval=2)
    provider = FixtureProvider()
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=2, total_budget=2000, reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run'))
    result = fw.evolve('Improve the arrangement of 26 circles in a square')
    assert result['runtime'] == 'composed-v9-m7'
    assert provider.calls == 2
    rows = [r['payload'] for r in fw.store.read('composed_evidence')]
    assert len(rows) == 3
    assert all(row['evidence']['eval_result']['status'] == 'ok' for row in rows)
    assert len(list(fw.store.read('openevolve_host_event'))) >= 5
    assert len(list(fw.store.read('openevolve_prompt'))) == 2
    assert all('SEARCH/REPLACE' in req['response_instruction'] for req in provider.requests)
    inspection = fw.inspect()
    assert inspection['assembly']['policy']['name'] == 'openevolve'
    assert len(inspection['execution']['main']['artifacts']) == 3
    assert all(set(req['vendor_messages']) == {'system', 'user'} for req in provider.requests)


def test_partial_diff_match_counts_are_recorded_and_audited(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    class PartialProvider(FixtureProvider):
        def __call__(self, prompt):
            self.calls += 1
            self.last_usage = {'total_tokens': 7}
            return ('<<<<<<< SEARCH\n    n = 26\n=======\n    n = 26\n    # matched\n>>>>>>> REPLACE\n'
                    '<<<<<<< SEARCH\n    never_present = 4\n=======\n    never_present = 5\n>>>>>>> REPLACE\n')
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    fw = Framework.from_profile(profile, PartialProvider(),
        CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=1000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Improve circle packing')
    rows = [row['payload'] for row in fw.store.read('openevolve_diff_attempts')]
    assert len(rows) == 1 and rows[0]['attempts'][0]['block_count'] == 2
    assert rows[0]['attempts'][0]['matched_block_count'] == 1
    coord, original = fw._composed.openevolve, fw._composed.openevolve._rows
    def forged(kind):
        result = copy.deepcopy(original(kind))
        if kind == 'openevolve_diff_attempts':
            result[0]['attempts'][0]['matched_block_count'] = 2
        return result
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError):
        coord._audit()


def test_public_framework_recorded_replay_uses_no_provider_or_evaluator_calls(tmp_path):
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=2, call_token_bound=128, migration_interval=2)
    provider = FixtureProvider()
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=2, total_budget=2000, reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run'))
    task = 'Improve the arrangement of 26 circles in a square'
    fw.evolve(task)
    class ForbiddenProvider(FixtureProvider):
        def __call__(self, prompt):
            raise AssertionError('recorded replay called the provider')
    class ForbiddenDomain(CirclePackingDomain):
        async def evaluate(self, proposal, request):
            raise AssertionError('recorded replay called the evaluator')
    def adapters(path, store):
        return ForbiddenProvider(), ForbiddenDomain(tmp_path / 'replay-domain', runner=SandboxRunner())
    certificate = fw.replay(task, adapter_factory=adapters)['replay_certificate']
    assert certificate['passed'] and certificate['external_calls'] == 0
    assert provider.calls == 2


def test_public_framework_resume_continues_without_repeating_prior_calls(tmp_path):
    from dataclasses import replace
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=2, call_token_bound=128, migration_interval=2)
    task = 'Improve the arrangement of 26 circles in a square'
    cfg = LoopConfig(max_generations=2, total_budget=2000, reeval_floor=0, baseline_every=100,
                     stop_after_generation=1)
    original_provider = FixtureProvider()
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    first = Framework.from_profile(profile, original_provider, domain, cfg, str(tmp_path / 'run'))
    first.evolve(task)
    assert original_provider.calls == 1
    resumed_provider = FixtureProvider()
    resumed_domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    resumed = Framework.from_profile(profile, resumed_provider, resumed_domain,
        replace(cfg, stop_after_generation=None, resume_from_checkpoint=True), str(tmp_path / 'run'))
    resumed.evolve(task)
    assert resumed_provider.calls == 1
    rows = list(resumed.store.read('composed_evidence'))
    assert len(rows) == 3 and all(row['payload']['evidence']['eval_result']['status'] == 'ok' for row in rows)
    assert len(list(resumed.store.read('openevolve_prompt'))) == 2


def test_public_framework_reserves_and_settles_both_real_cascade_stages(tmp_path):
    from zoo.circle_packing.profile import build_profile
    class GridProvider(FixtureProvider):
        def __call__(self, prompt):
            self.calls += 1
            self.last_usage = {'total_tokens': 7}
            self.requests.append(json.loads(prompt))
            return ('<<<<<<< SEARCH\n    # Initialize arrays for 26 circles\n    n = 26\n=======\n'
                    '    c = np.array([[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)])\n'
                    '    r = np.full(26, .07)\n    return c, r, float(np.sum(r))\n>>>>>>> REPLACE\n')
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    provider = GridProvider()
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run'))
    fw.evolve('Improve circle packing')
    rows = [r['payload'] for r in fw.store.read('composed_evidence')]
    assert [row['evidence']['eval_result']['cost']['eval_count'] for row in rows] == [1, 2]
    final = list(fw.store.read('metric_final_completed'))[-1]['payload']
    assert final['state'] == 'completed'
    assert final['evidence']['evidence']['eval_result']['cost']['eval_count'] == 1
    assert provider.calls == 1


def test_named_profile_matches_frozen_builder():
    from core.profiles import load_profile
    from core.composition.contracts import AssemblyConfig
    from zoo.circle_packing.profile import build_profile
    expected = AssemblyConfig.from_dict(build_profile(seed=0, iterations=6,
        call_token_bound=1064960, migration_interval=50)).to_dict()
    assert load_profile('openevolve_program') == expected


def test_framework_coordinator_rejects_tampered_original_materialization(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    fw = Framework.from_profile(profile, FixtureProvider(),
        CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Improve circle packing')
    coord = fw._composed.openevolve
    original = coord._rows
    def forged(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'materialization_completed': rows[0]['construction_result']['artifact'] += '\n# tampered'
        return rows
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError): coord._audit()


def test_framework_accounts_failed_patch_and_replays_without_external_calls(tmp_path):
    from zoo.circle_packing.profile import build_profile
    class RepairProvider(FixtureProvider):
        def __call__(self, prompt):
            if self.calls == 0:
                self.calls += 1
                self.requests.append(json.loads(prompt))
                self.last_usage = {'total_tokens': 11}
                return 'invalid diff'
            return super().__call__(prompt)
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    provider = RepairProvider()
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run'))
    task = 'Improve circle packing with a bounded repair'
    fw.evolve(task)
    assert provider.calls == 2
    records = [row['payload'] for row in fw.store.read('materialization_completed')]
    child = records[-1]['construction_result']
    assert child['cost']['tokens_in'] == 18
    assert [item['status'] for item in child['attempts']] == ['invalid_output', 'complete']
    diff = list(fw.store.read('openevolve_diff_attempts'))[0]['payload']['attempts']
    assert [item['block_count'] for item in diff] == [0, 1]
    assert [item['matched_block_count'] for item in diff] == [0, 1]
    assert provider.requests[1]['repair_feedback']
    class ForbiddenProvider(FixtureProvider):
        def __call__(self, prompt):
            raise AssertionError('replay repeated a provider call')
    class ForbiddenDomain(CirclePackingDomain):
        async def evaluate(self, proposal, request):
            raise AssertionError('replay repeated an evaluator call')
    def adapters(path, store):
        return ForbiddenProvider(), ForbiddenDomain(tmp_path / 'replay-domain', runner=SandboxRunner())
    replay = fw.replay(task, adapter_factory=adapters)['replay_certificate']
    assert replay['passed'] and replay['external_calls'] == 0


def test_public_framework_exhibits_actual_host_migration(tmp_path):
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=6, call_token_bound=128, migration_interval=2)
    provider = FixtureProvider()
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    cfg = LoopConfig(max_generations=6, total_budget=5000, reeval_floor=0, baseline_every=100)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(tmp_path / 'run'))
    fw.evolve('Improve circle packing with migration')
    adapter = fw._composed.parts['policy'].adapter
    migrants = [program for program in adapter.database.programs.values() if program.metadata.get('migrant')]
    assert provider.calls == 6
    assert adapter.database.last_migration_generation >= 2
    assert migrants
    evaluated = {row['payload']['proposal']['candidate']['id'] for row in fw.store.read('composed_evidence')}
    assert all(adapter._sources[program.id]['candidate_id'] in evaluated for program in migrants)
    assert all(program.id not in evaluated for program in migrants)
    class ForbiddenProvider(FixtureProvider):
        def __call__(self, prompt):
            raise AssertionError('migration replay called provider')
    class ForbiddenDomain(CirclePackingDomain):
        async def evaluate(self, proposal, request):
            raise AssertionError('migration replay called evaluator')
    replay = fw.replay('Improve circle packing with migration', adapter_factory=lambda path, store:
        (ForbiddenProvider(), ForbiddenDomain(tmp_path / 'replay-domain', runner=SandboxRunner())))
    assert replay['replay_certificate']['passed'] and replay['replay_certificate']['external_calls'] == 0


def test_framework_retains_charged_exhausted_patch_failure(tmp_path):
    from zoo.circle_packing.profile import build_profile
    class BadProvider(FixtureProvider):
        def __call__(self, prompt):
            self.calls += 1
            self.requests.append(json.loads(prompt))
            self.last_usage = {'total_tokens': 7}
            return 'no SEARCH/REPLACE block'
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    provider = BadProvider()
    domain = CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner())
    fw = Framework.from_profile(profile, provider, domain,
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Improve circle packing, keep failure evidence')
    rows = [row['payload'] for row in fw.store.read('composed_evidence')]
    assert provider.calls == 2 and len(rows) == 2
    assert rows[-1]['evidence']['eval_result']['status'] == 'failed_to_run'
    assert rows[-1]['proposal']['cost']['tokens_in'] == 14
    events = [row['payload'] for row in fw.store.read('openevolve_host_event')]
    assert events[-1]['kind'] == 'abandon'
    assert events[-1]['candidate_id'] == rows[-1]['proposal']['candidate']['id']
    diff = list(fw.store.read('openevolve_diff_attempts'))[0]['payload']['attempts']
    assert [item['block_count'] for item in diff] == [0, 0]
    assert [item['matched_block_count'] for item in diff] == [0, 0]


def test_framework_resumes_after_failed_patch_without_repeating_failed_calls(tmp_path):
    from dataclasses import replace
    from zoo.circle_packing.profile import build_profile
    class BadProvider(FixtureProvider):
        def __call__(self, prompt):
            self.calls += 1
            self.last_usage = {'total_tokens': 7}
            return 'no diff'
    task = 'Improve circle packing with durable failures'
    profile = build_profile(seed=0, iterations=2, call_token_bound=128, migration_interval=2)
    cfg = LoopConfig(max_generations=2, total_budget=2000, reeval_floor=0,
                     baseline_every=100, stop_after_generation=1)
    bad = BadProvider()
    first = Framework.from_profile(profile, bad, CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
                                   cfg, str(tmp_path / 'run'))
    first.evolve(task)
    assert bad.calls == 2
    good = FixtureProvider()
    resumed = Framework.from_profile(profile, good, CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
                                     replace(cfg, stop_after_generation=None, resume_from_checkpoint=True),
                                     str(tmp_path / 'run'))
    resumed.evolve(task)
    assert good.calls == 1
    evidence = [r['payload']['evidence']['eval_result']['status'] for r in resumed.store.read('composed_evidence')]
    assert evidence == ['ok', 'failed_to_run', 'ok']


def test_framework_audit_rejects_changed_original_diff_response(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    fw = Framework.from_profile(profile, FixtureProvider(),
        CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Improve circle packing and audit original responses')
    coord = fw._composed.openevolve
    original = coord._rows
    def forged(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'composed_provider_completed': rows[0]['result'] = 'not the original diff'
        return rows
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError): coord._audit()


def test_framework_audit_rejects_forged_failed_construction_cost(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    class BadProvider(FixtureProvider):
        def __call__(self, prompt):
            self.calls += 1
            self.last_usage = {'total_tokens': 7}
            return 'not a patch'
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    fw = Framework.from_profile(profile, BadProvider(),
        CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Improve circle packing and audit failures')
    coord = fw._composed.openevolve
    original = coord._rows
    def forged(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'composed_evidence': rows[-1]['proposal']['cost']['tokens_in'] = 0
        return rows
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError): coord._audit()


def test_framework_audit_rejects_changed_original_provider_request(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    fw = Framework.from_profile(profile, FixtureProvider(),
        CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Improve circle packing and audit original requests')
    coord = fw._composed.openevolve
    original = coord._rows
    def forged(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'composed_provider_started': rows[0]['request_sha256'] = '0' * 64
        return rows
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError): coord._audit()


def test_framework_audit_rejects_changed_failed_attempt_request(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    class BadProvider(FixtureProvider):
        def __call__(self, prompt):
            self.calls += 1
            self.last_usage = {'total_tokens': 7}
            return 'not a patch'
    fw = Framework.from_profile(build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2),
        BadProvider(), CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Audit the failed construction request')
    coord = fw._composed.openevolve
    original = coord._rows
    def forged(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'composed_provider_started': rows[-1]['request_sha256'] = '0' * 64
        return rows
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError): coord._audit()


def test_framework_audit_rejects_tampered_seed_plan(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=0, call_token_bound=128, migration_interval=2)
    fw = Framework.from_profile(profile, FixtureProvider(),
        CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=0, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Audit the pinned seed plan')
    coord = fw._composed.openevolve
    original = coord._rows
    def forged(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'openevolve_construction_plan': rows[0]['plan']['candidate']['hypothesis'] = 'tampered'
        return rows
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError): coord._audit()


def test_framework_audit_rejects_changed_original_selection_scope(tmp_path, monkeypatch):
    import copy
    import pytest
    from zoo.circle_packing.profile import build_profile
    profile = build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2)
    fw = Framework.from_profile(profile, FixtureProvider(),
        CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Audit eligible source scope')
    coord = fw._composed.openevolve
    original = coord._rows
    def forged(kind):
        rows = copy.deepcopy(original(kind))
        if kind == 'openevolve_selection_scope': rows[0]['eligible_ids'] = ['forged']
        return rows
    monkeypatch.setattr(coord, '_rows', forged)
    with pytest.raises(ValueError): coord._audit()


def test_framework_audit_rebuilds_budget_at_each_selection_scope(tmp_path):
    import pytest
    from zoo.circle_packing.profile import build_profile
    fw = Framework.from_profile(build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2),
        FixtureProvider(), CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Audit the original budget at parent selection')
    coord = fw._composed.openevolve
    scope = next(row for row in coord.store.rows if row['kind'] == 'openevolve_selection_scope')
    scope['payload']['budget_ref'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError): coord._audit()


def test_framework_audit_rebuilds_frontier_at_each_selection_scope(tmp_path):
    import pytest
    from zoo.circle_packing.profile import build_profile
    fw = Framework.from_profile(build_profile(seed=0, iterations=1, call_token_bound=128, migration_interval=2),
        FixtureProvider(), CirclePackingDomain(tmp_path / 'domain', runner=SandboxRunner()),
        LoopConfig(max_generations=1, total_budget=2000, reeval_floor=0, baseline_every=100), str(tmp_path / 'run'))
    fw.evolve('Audit the original frontier at parent selection')
    coord = fw._composed.openevolve
    scope = next(row for row in coord.store.rows if row['kind'] == 'openevolve_selection_scope')
    scope['payload']['frontier_ref'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError): coord._audit()
