"""Shared currency evidence through provider, public Framework and pilot."""
import hashlib
import json
import shlex
import sys
from pathlib import Path

import pytest

from tests.test_mle_provider import endpoint, deepseek_provider, deepseek_response
from tests.test_mle_composed import fixture_public, TrustedFixtureRunner, TASK
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_agent import run_agent
from zoo.mle_bench_lite.usage_audit import audit_usage
from tests.test_mle_pilot import setup, grader
from zoo.mle_bench_lite import pilot


def test_currency_audit_requires_shared_ledger_and_reconciles_exact_receipt(tmp_path, endpoint):
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(deepseek_response())
    p = deepseek_provider(tmp_path / 'run', endpoint, ledger)
    p('one')
    without = audit_usage(p.usage_dir)
    assert not without['complete'], 'DeepSeek currency evidence cannot be certified from token sidecars alone'
    report = audit_usage(p.usage_dir, spending_ledger=ledger)
    assert report['complete'] and report['costs_complete']
    assert report['currency_audit']['settled_upper_bound_micro_cny'] == 360
    assert report['currency_audit']['reserved_micro_cny'] == 0
    assert report['currency_audit']['complete']
    assert report['currency_audit']['invoice_verified'] is False


def test_currency_audit_detects_deleted_complete_call_and_preserves_its_bill(tmp_path, endpoint):
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.extend([deepseek_response(), deepseek_response()])
    p = deepseek_provider(tmp_path / 'run', endpoint, ledger)
    p('one'); p('two')
    lost = ledger.snapshot()['operations'][0]['call_id']
    (p.usage_dir / (lost + '.json')).unlink()
    (p.calls_dir / (lost + '.started.json')).unlink()
    (p.calls_dir / (lost + '.completed.json')).unlink()
    report = audit_usage(p.usage_dir, spending_ledger=ledger)
    assert not report['complete']
    assert report['known_tokens'] == 240
    assert report['currency_audit']['settled_upper_bound_micro_cny'] == 720
    with pytest.raises(ValueError):
        deepseek_provider(tmp_path / 'run', endpoint, ledger)
    assert len(endpoint.requests) == 2


def test_reservation_without_local_start_is_attributed_to_its_run(tmp_path, endpoint, monkeypatch):
    from zoo.mle_bench_lite import provider as provider_module
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    p = deepseek_provider(tmp_path / 'run', endpoint, ledger)
    def fail_write(*_args):
        raise OSError('simulated local intent write failure')
    monkeypatch.setattr(provider_module, '_exclusive_json', fail_write)
    with pytest.raises(OSError):
        p('one')
    assert not endpoint.requests
    report = audit_usage(p.usage_dir, spending_ledger=ledger)
    assert not report['complete'] and not report['costs_complete']
    assert report['currency_audit']['reserved_micro_cny'] == 2228224
    assert report['unresolved_calls'] == ledger.snapshot()['pending_calls']


@pytest.mark.parametrize('tamper', ['tokens', 'response', 'policy'])
def test_currency_audit_rejects_rehashed_local_receipt_fork(tmp_path, endpoint, tamper):
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    endpoint.replies.append(deepseek_response())
    p = deepseek_provider(tmp_path / 'run', endpoint, ledger); p('one')
    path = next(p.usage_dir.glob('*.json'))
    value = json.loads(path.read_text())
    if tamper == 'tokens':
        value.update(prompt_tokens=101, total_tokens=121, prompt_cache_miss_tokens=21)
    elif tamper == 'response':
        value['response_sha256'] = '0' * 64
    else:
        value['currency_policy_sha256'] = '0' * 64
    path.write_text(json.dumps(value))
    completion = next(p.calls_dir.glob('*.completed.json'))
    record = json.loads(completion.read_text())
    record['usage_receipt_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    completion.write_text(json.dumps(record))
    report = audit_usage(p.usage_dir, spending_ledger=ledger)
    assert not report['complete'] and not report['currency_audit']['complete']
    with pytest.raises(ValueError):
        deepseek_provider(tmp_path / 'run', endpoint, ledger)


def test_public_framework_agent_binds_currency_and_submits_with_real_http(tmp_path, endpoint):
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    workspace = tmp_path / 'run/workspace'
    fixture_public(workspace / 'data')
    code = '''import csv, json, os
assert 'OPENAI_API_KEY' not in os.environ
assert 'MLE_CNY_LEDGER_PATH' not in os.environ
with open('data/protocol.json') as f: protocol=json.load(f)
with open('data/predict.csv') as f: rows=list(csv.DictReader(f))
with open('predictions.csv','w',newline='') as f:
    writer=csv.writer(f); writer.writerow(['row_id','A','B','C'])
    for row in rows: writer.writerow([row['row_id'],1/3,1/3,1/3])
'''
    endpoint.replies.extend(deepseek_response(content=code) for _ in range(8))
    provider = deepseek_provider(tmp_path / 'run/agent_artifacts', endpoint, ledger)
    result = run_agent(workspace=workspace, task_id=TASK, model='deepseek-flash',
        api_base=endpoint.url, token_budget=60000, iterations=0, variant='baseline',
        max_completion_tokens=16384, provider=provider, runner=TrustedFixtureRunner(),
        spending_ledger_path=ledger.path)
    assert result['submission_materialized']
    assert result['currency_campaign'] == ledger.manifest_binding()
    assert result['currency_audit']['complete']
    assert result['currency_audit']['settled_upper_bound_micro_cny'] == 360
    assert result['details']['provider_request_format'] == 'deepseek'
    assert len(endpoint.requests) == 1
    other = CampaignBudget.create(tmp_path / 'other.db')
    with pytest.raises(ValueError, match='campaign'):
        run_agent(workspace=workspace, task_id=TASK, model='deepseek-flash',
            api_base=endpoint.url, token_budget=60000, iterations=0, variant='baseline',
            max_completion_tokens=16384, provider=provider, runner=TrustedFixtureRunner(),
            spending_ledger_path=other.path, resume=True)
    assert len(endpoint.requests) == 1


@pytest.mark.parametrize('variant', ['baseline', 'full'])
def test_variable_reasoning_usage_does_not_abort_an_affordable_first_candidate(tmp_path, endpoint, variant):
    # Actual first-pilot usage exceeded an artificial 12000-token cycle share,
    # despite fitting the real 60000-token run budget and provider output cap.
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    workspace = tmp_path / 'run/workspace'
    fixture_public(workspace / 'data')
    code = '''import csv
with open('data/predict.csv') as f: rows=list(csv.DictReader(f))
with open('predictions.csv','w',newline='') as f:
    writer=csv.writer(f); writer.writerow(['row_id','A','B','C'])
    for row in rows: writer.writerow([row['row_id'],1/3,1/3,1/3])
'''
    first = deepseek_response(content=code)
    first['usage'] = {'prompt_tokens': 3190, 'completion_tokens': 10204, 'total_tokens': 13394,
                      'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 3190,
                      'completion_tokens_details': {'reasoning_tokens': 9000}}
    endpoint.replies.append(first)
    endpoint.replies.extend(deepseek_response(content=code) for _ in range(4))
    provider = deepseek_provider(tmp_path / 'run/agent_artifacts', endpoint, ledger)
    result = run_agent(workspace=workspace, task_id=TASK, model='deepseek-flash',
        api_base=endpoint.url, token_budget=60000, iterations=4, variant=variant,
        max_completion_tokens=16384, provider=provider, runner=TrustedFixtureRunner(),
        spending_ledger_path=ledger.path)
    assert result['submission_materialized'] and (workspace / 'submission.csv').is_file()
    assert result['token_usage']['total_tokens'] == 13874
    assert len(endpoint.requests) == 5
    assert result['currency_audit']['complete']
    assert result['currency_audit']['settled_upper_bound_micro_cny'] == 89452
    assert result['details']['physical_ledger']['global']['used']['token'] == 13874
    assert result['details']['physical_ledger']['halt_reasons'] == []


def test_agent_rejects_candidate_visible_currency_ledger_before_generation(tmp_path):
    workspace = tmp_path / 'run/workspace'
    fixture_public(workspace / 'data')
    ledger = CampaignBudget.create(workspace / 'campaign.db')
    with pytest.raises(ValueError, match='outside'):
        run_agent(workspace=workspace, task_id=TASK, model='deepseek-flash',
            api_base='https://api.deepseek.com', runner=TrustedFixtureRunner(),
            spending_ledger_path=ledger.path)
    assert ledger.snapshot()['operations'] == []


def currency_command(root):
    script = root / 'currency_fixture_agent.py'
    script.write_text('''import json, os, pathlib, sys
sys.path.insert(0, REPO)
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.provider import BenchmarkProvider
from zoo.mle_bench_lite.usage_audit import audit_usage
from zoo.mle_bench_lite.pilot import digest
workspace=pathlib.Path(sys.argv[1]); task,seed,arm=sys.argv[2],int(sys.argv[3]),sys.argv[4]
spec=json.loads((workspace.parents[3]/'pilot_spec.json').read_text())['spec']
ledger=CampaignBudget(os.environ['MLE_CNY_LEDGER_PATH'])
assert ledger.manifest_binding()==spec['currency_campaign']
artifacts=workspace.parent/'agent_artifacts'
p=BenchmarkProvider(spec['model'],spec['provider_base_url'],artifacts/'token_usage',
    spec['budget']['token'],max_completion_tokens=spec['provider_sampling']['max_completion_tokens'],
    timeout=spec['provider_timeout'],request_format='deepseek',spending_ledger=ledger,
    api_key='provider-test-secret')
p('labelled protocol fixture')
audit=audit_usage(p.usage_dir,spending_ledger=ledger)
dataset=spec['datasets'][task+':'+str(seed)]; profile=spec['profiles'][str(seed)+':'+arm]
summary={'task_id':task,'seed':seed,'variant':arm,'protocol':spec['protocol'],
    'actual_model':spec['model'],'requested_model':spec['model'],'token_budget':spec['budget']['token'],
    'token_usage':audit['usage'],'profile':profile,'profile_sha256':digest(profile),
    'dataset_manifest':dataset,'dataset_identity':digest(dataset),
    'public_data_sha256':os.environ['MLE_PILOT_PUBLIC_DATA_SHA256'],
    'currency_campaign':ledger.manifest_binding(),'currency_audit':audit['currency_audit'],
    'details':{'iterations':spec['iterations'],'solution_timeout':spec['solution_timeout'],
        'temperature':0.0,'max_completion_tokens':spec['provider_sampling']['max_completion_tokens'],
        'provider_request_format':'deepseek'}}
(artifacts/'agent_run.json').write_text(json.dumps(summary))
(workspace/'submission.csv').write_text('id,prediction\\n1,0.4\\n')
'''.replace('REPO', repr(str(Path(__file__).resolve().parents[1]))))
    return shlex.join([sys.executable, str(script), '{workspace}', '{task}', '{seed}', '{arm}'])


def run_currency_pilot(tmp_path, setup, ledger, suffix='first', grader_factory=grader):
    official, data, manifest = setup
    return pilot.run_pilot(official, data, tmp_path / suffix, model='deepseek-flash',
        token_budget=60000, time_limit=10, solution_timeout=1, iterations=4, seeds=(1,),
        task_ids=pilot.DEFAULT_TASKS, manifest_path=manifest,
        grader_factory=grader_factory, _fixture_agent_command=currency_command(tmp_path),
        spending_ledger_path=ledger.path)


def test_six_pilot_runs_share_one_budget_and_report_upper_bound(tmp_path, setup, endpoint, monkeypatch):
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    monkeypatch.setenv('OPENAI_API_BASE', endpoint.url)
    endpoint.replies.extend(deepseek_response() for _ in range(6))
    def after_all_calls(task):
        assert len(endpoint.requests) == 6
        return grader(task)
    report = run_currency_pilot(tmp_path, setup, ledger, grader_factory=after_all_calls)
    assert report['pilot_complete'] and report['expected_runs'] == 6
    assert report['spec']['provider_sampling']['max_completion_tokens'] == 16384
    assert report['currency_campaign']['settled_upper_bound_micro_cny'] == 2160
    assert report['currency_campaign']['reserved_micro_cny'] == 0
    assert report['currency_campaign']['invoice_verified'] is False
    assert report['immutable_snapshot_verified'] is False
    assert report['response_identifier_evidence_complete'] is True
    assert all(row['usage_audit']['currency_audit']['complete'] for row in report['runs'])
    assert all(row['currency_call_ids'] for row in report['runs'])
    assert all(request['max_tokens'] == 16384 for request in endpoint.requests)
    assert ledger.snapshot()['settled_upper_bound_micro_cny'] == 2160


def test_unresolved_currency_blocks_remaining_five_runs_and_new_output(tmp_path, setup, endpoint, monkeypatch):
    ledger = CampaignBudget.create(tmp_path / 'campaign.db')
    monkeypatch.setenv('OPENAI_API_BASE', endpoint.url)
    value = deepseek_response(); value['usage'] = {'total_tokens': 120}
    endpoint.replies.append(value)
    report = run_currency_pilot(tmp_path, setup, ledger)
    assert not report['pilot_complete'] and report['failure_count'] == 6
    assert sum(row.get('blocked_before_execution', False) for row in report['runs']) == 5
    assert len(endpoint.requests) == 1
    assert report['currency_campaign']['reserved_micro_cny'] == 2228224
    assert report['runs'][0]['usage_audit']['known_tokens'] == 120
    with pytest.raises(ValueError, match='unresolved'):
        run_currency_pilot(tmp_path, setup, ledger, suffix='new-output')
    assert len(endpoint.requests) == 1


def test_pilot_requires_ledger_outside_replaceable_output_root(tmp_path, setup, endpoint, monkeypatch):
    monkeypatch.setenv('OPENAI_API_BASE', endpoint.url)
    output = tmp_path / 'first'; output.mkdir()
    ledger = CampaignBudget.create(output / 'campaign.db')
    with pytest.raises(ValueError, match='outside'):
        run_currency_pilot(tmp_path, setup, ledger)
    assert endpoint.requests == [] and ledger.snapshot()['operations'] == []


def test_preflight_reports_missing_currency_ledger_without_creating_one(tmp_path, setup, monkeypatch):
    official, data, manifest = setup
    monkeypatch.setenv('OPENAI_API_BASE', 'https://api.deepseek.com')
    report = pilot.preflight_pilot(official, data, model='deepseek-flash', token_budget=60000,
        time_limit=10, solution_timeout=1, iterations=4, seeds=(1,), manifest_path=manifest)
    assert not report['ready']
    assert 'campaign_currency_budget' in {item['requirement'] for item in report['missing']}
    assert not list(tmp_path.rglob('*.db'))


def test_currency_command_preserves_explicit_shared_path_and_output_cap(tmp_path):
    from zoo.mle_bench_lite.runner import _command
    path = tmp_path / 'budget {campaign}.db'
    template = pilot._command('deepseek-flash', 60000, 120, 4,
        max_completion_tokens=16384, spending_ledger_path=path)
    command = _command(template, tmp_path / 'workspace', TASK, 1, 'baseline', 600)
    assert command[command.index('--spending-ledger') + 1] == str(path)
    assert command[command.index('--max-completion-tokens') + 1] == '16384'
