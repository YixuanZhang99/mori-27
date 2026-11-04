"""Run MLE public-data development through the latest configured Framework.

The official benchmark score is produced later by the external campaign runner.
This process neither imports an official grader nor reads private benchmark data.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from core.composition.contracts import Proposal
from core.executor.types import Candidate
from core.loop import Framework, LoopConfig
from zoo.mle_bench_lite.agent_common import _atomic_json, add_common_arguments
from zoo.mle_bench_lite.composed_domain import PublicTrainDomain, SandboxRunner
from zoo.mle_bench_lite.public_train import PROTOCOL, PublicTrainBundle, digest, load_anonymization_key


def build_profile(*, variant, token_budget, seed, iterations, anchor_every=1, capacity=4):
    if variant not in ("baseline", "full"):
        raise ValueError("variant must be baseline or full")
    for name, value, minimum in (("token_budget", token_budget, 1), ("seed", seed, 0),
                                 ("iterations", iterations, 0), ("anchor_every", anchor_every, 1),
                                 ("capacity", capacity, 2)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    limits = {"token": token_budget, "eval_count": max(16, (iterations + 1) * 8), "node": iterations + 1}
    budget = {"limits": {level: dict(limits) for level in ("global", "direction", "candidate")},
        "reservation": {"token": 0, "eval_count": 1, "node": 0},
        "operation_reservations": {"planning": {"token": 0, "eval_count": 0, "node": 0},
                                   "operator": {"token": max(1, token_budget // (iterations + 1)), "eval_count": 0, "node": 1}},
        "reservation_modes": {"operator": {"token": "remaining"}},
        "fidelity_rungs": [{"fidelity": "dev", "split_id": "dev", "seed_set": [seed]}]}
    if variant == "full":
        budget["proxy_validity"] = {"every_n_cycles": anchor_every,
            "anchor_request": {"fidelity": "true", "split_id": "calibration", "seed_set": [seed]},
            "proxy_metric": "dev/score", "true_metric": "true/score",
            "proxy_direction": "maximize", "true_direction": "maximize",
            "min_pairs": 3, "window": 8, "min_rank_correlation": 0.5}
    return {"schema_version": 1, "name": f"mle_csv_{variant}", "mode": "benchmark",
        "provider": {"name": "provided"}, "domain": {"name": "native"},
        "policy": {"name": "population" if variant == "full" else "greedy"},
        "operators": [{"name": "draft"}, {"name": "crossover" if variant == "full" else "reflective"}],
        "frontier": {"name": "population", "options": {"capacity": capacity,
            "selection": "tournament", "sample_seed": seed}} if variant == "full" else {"name": "tree"},
        "memory": {"name": "scoped", "options": {"include_negative": variant == "full", "max_chars": 16000}},
        "executor": {"name": "inprocess"},
        "admission": {"name": "layered", "options": {"metric": "gate/score", "dev_metric": "dev/score",
            "direction": "maximize", "dev_direction": "maximize", "call_budget": 2 * (iterations + 1),
            "admission_seeds": [seed], "final_seeds": [seed]}},
        "budget": {"name": "hierarchical", "options": budget}, "skills": []}


def task_description(bundle):
    return ("Write a COMPLETE executable Python program for a frozen CSV machine-learning task. "
        "Return code only. It will run once in an isolated workspace with no network. "
        "Read data/protocol.json, data/train.csv and data/predict.csv. Train using only train.csv. "
        "Write predictions.csv with EXACT row_id coverage and the output columns declared below. "
        "The prediction table mixes anonymous validation and final submission rows; do not infer or select subsets. "
        "Classification output must be finite probabilities in [0,1] summing to 1 on each row; regression output "
        "must be finite and nonnegative. You may use installed numpy/pandas/scikit-learn, standard library, "
        "For multiclass logistic regression, use a compatible solver such as lbfgs, or explicitly wrap a "
        "binary estimator in OneVsRestClassifier. "
        "and the supplied CSV features. Set random seeds explicitly. Do not use internet, images or geometry files. "
        "Do not read other directories or launch persistent processes.\nPROTOCOL:\n" + json.dumps(bundle.protocol, sort_keys=True))


def run_agent(*, workspace, task_id, model, api_base, token_budget=60000, seed=1,
              iterations=3, solution_timeout=120, variant="full", max_completion_tokens=4096,
              provider=None, runner=None, resume=False, protected_roots=(), anonymization_key_path=None,
              spending_ledger_path=None):
    profile = build_profile(variant=variant, token_budget=token_budget, seed=seed, iterations=iterations)
    workspace = Path(workspace).resolve()
    if runner is None:
        runner = SandboxRunner()
    if isinstance(runner, SandboxRunner):
        SandboxRunner.validate_paths(workspace, *protected_roots)
        runner.preflight()
    artifacts = workspace.parent / "agent_artifacts"
    spending_ledger = getattr(provider, "spending_ledger", None)
    if spending_ledger_path is None and spending_ledger is not None:
        spending_ledger_path = spending_ledger.path
    if spending_ledger_path is not None:
        from zoo.mle_bench_lite.cny_budget import CampaignBudget
        ledger_path = Path(spending_ledger_path).absolute()
        SandboxRunner.validate_paths(ledger_path)
        if any(ledger_path.resolve() == root or root in ledger_path.resolve().parents
               for root in (workspace, artifacts)):
            raise ValueError("campaign ledger must stay outside candidate workspace and run artifacts")
        loaded = CampaignBudget(ledger_path)
        if provider is not None and (spending_ledger is None
                or spending_ledger.manifest_binding() != loaded.manifest_binding()):
            raise ValueError("provided provider uses a different campaign ledger")
        spending_ledger = loaded
    artifacts.mkdir(parents=True, exist_ok=True)
    key_path = (Path(anonymization_key_path).absolute() if anonymization_key_path is not None
                else artifacts / "anonymization.key")
    if key_path == workspace or workspace in key_path.resolve().parents:
        raise ValueError("anonymization key must stay outside the candidate workspace")
    SandboxRunner.validate_paths(key_path)
    key = load_anonymization_key(key_path,
        create=anonymization_key_path is None and not resume and not (artifacts / "public_inputs").exists())
    bundle = PublicTrainBundle(workspace / "data", artifacts / "public_inputs", task_id, seed,
                              anonymization_key=key)
    domain = PublicTrainDomain(bundle, artifacts / "composed_candidates", solution_timeout=solution_timeout, runner=runner)
    if not model or type(model) is not str:
        raise ValueError("explicit model is required")
    if provider is None:
        from zoo.mle_bench_lite.provider import BenchmarkProvider
        provider = BenchmarkProvider(model=model, base_url=api_base, usage_dir=artifacts / "token_usage",
            token_budget=token_budget, max_completion_tokens=max_completion_tokens,
            temperature=0.0, timeout=max(30.0, solution_timeout),
            request_format="deepseek" if spending_ledger is not None else None,
            spending_ledger=spending_ledger)
    contract = {"protocol": PROTOCOL, "profile": profile, "dataset_identity": bundle.identity,
                "domain": domain.manifest_binding, "provider": provider.manifest_binding(),
                "task_description_sha256": digest(task_description(bundle))}
    contract_path = artifacts / "agent_contract.json"
    if contract_path.exists():
        if not resume or contract_path.is_symlink() or json.loads(contract_path.read_text()) != contract:
            raise ValueError("agent contract differs from the original run; use a fresh output directory")
    else:
        if resume or (artifacts / "composed/x1.jsonl").exists():
            raise ValueError("existing run lacks its original frozen agent contract")
        with contract_path.open("x") as stream:
            json.dump(contract, stream, sort_keys=True, allow_nan=False)
    config = LoopConfig(total_budget=token_budget, intent_cost=1, reeval_floor=0,
                        max_generations=iterations, checkpoint_enabled=True, resume_from_checkpoint=resume)
    framework = Framework.from_profile(profile, provider, domain, config, str(artifacts / "composed"))
    domain.restore_evidence(framework.store.read("composed_evidence"))
    result = framework.evolve(task_description(bundle))
    from zoo.mle_bench_lite.usage_audit import audit_usage
    usage_audit = audit_usage(artifacts / "token_usage", spending_ledger=spending_ledger)
    if not usage_audit["complete"] or not usage_audit["receipt_count"]:
        raise ValueError("provider operations lack complete independent cost and identity evidence")
    chosen = result.get("best_candidate_id")
    records = [row["payload"] for row in framework.store.read("composed_evidence")]
    selected_record = next((row for row in records if row["proposal"]["candidate"]["id"] == chosen), None)
    if selected_record is None:
        raise ValueError("run has no admitted successful candidate to submit")
    selected = selected_record["proposal"]
    proposal = Proposal(Candidate(**selected["candidate"]), selected["artifact"])
    record = domain.materialize(proposal, workspace / "submission.csv", expected_prediction_sha256=
        selected_record["evidence"]["eval_result"]["contract"]["private"]["data"]["prediction_sha256"])
    usage = usage_audit["usage"]
    if len(usage["models"]) != 1 or usage["total_tokens"] > token_budget:
        raise ValueError("provider receipts do not establish an in-budget single-backbone run")
    spent = framework._composed.budget.state()["global"]["used"]["token"]
    if spent != usage["total_tokens"]:
        raise ValueError("physical framework ledger differs from independent provider receipts")
    summary = {"arm": variant, "variant": variant, "protocol": PROTOCOL, "task_id": task_id, "seed": seed,
        "profile": profile, "profile_sha256": digest(profile), "dataset_identity": bundle.identity,
        "agent_contract_sha256": digest(contract),
        "dataset_manifest": bundle.manifest, "actual_model": usage["models"][0], "requested_model": model,
        "token_budget": token_budget, "token_usage": usage, "token_budget_exceeded": False,
        "submission_materialized": True, "external_benchmark_score_produced": False,
        "selected_candidate_id": chosen, "selected_artifact_sha256": record["identity"]["artifact_sha256"],
        "prediction_sha256": record["prediction_sha256"], "submission_sha256":
            "sha256:" + __import__("hashlib").sha256((workspace / "submission.csv").read_bytes()).hexdigest(),
        "details": {"iterations": iterations, "solution_timeout": solution_timeout,
            "temperature": 0.0, "max_completion_tokens": max_completion_tokens,
            "provider_request_format": getattr(provider, "request_format", "fixture"),
            "training_invocations": domain.training_invocations, "evaluation_calls": len(domain.calls),
            "physical_ledger": framework._composed.budget.state(), "result": result}}
    if spending_ledger is not None:
        summary.update(currency_campaign=spending_ledger.manifest_binding(),
                       currency_audit=usage_audit["currency_audit"], immutable_snapshot_verified=False)
    # This full public tree identity is an independent cross-check of the pilot
    # runner's copied inputs (auxiliary files are bound even though unused).
    from zoo.mle_bench_lite.pilot import public_snapshot
    summary["public_data_sha256"] = public_snapshot(workspace / "data")["sha256"]
    _atomic_json(artifacts / "agent_run.json", summary)
    return summary




def build_governed_profile(*, variant, token_budget, seed, iterations, max_completion_tokens=4096,
                           control_cycles=None):
    """Freeze M7 search, resident control and hard per-call reservations."""
    from zoo.mle_bench_lite.cny_budget import POLICY
    if type(token_budget) is not int or type(max_completion_tokens) is not int or max_completion_tokens <= 0:
        raise ValueError("hard provider capacity requires positive integer budgets")
    if max_completion_tokens > POLICY["max_output_tokens"]:
        raise ValueError("hard provider capacity exceeds maximum output")
    cycles = [0] if control_cycles is None else control_cycles
    if type(iterations) is not int or iterations < 0 or type(cycles) not in (list, tuple) or not cycles or \
            any(type(cycle) is not int or cycle < 0 or cycle > iterations + 1 for cycle in cycles) or \
            list(cycles) != sorted(set(cycles)) or cycles[0] != 0:
        raise ValueError("control schedule must start at zero and contain unique ordered valid cycles")
    cycles = list(cycles)
    bound = POLICY["context_tokens"] + max_completion_tokens
    required_main = max(1, cycles[-1])
    if len(cycles) + required_main > iterations + 2:
        raise ValueError("control schedule cannot reach its last planned cycle within node capacity")
    if token_budget < (len(cycles) + required_main) * bound:
        raise ValueError("hard provider capacity cannot protect controls and reach their planned cycle")
    profile = build_profile(variant=variant, token_budget=token_budget, seed=seed, iterations=iterations)
    profile.update(schema_version=2, executor={'name': 'git_artifact', 'options': {}},
        execution={'schema_version': 1, 'spec': {'role': 'general', 'hypothesis_frozen': True,
                   'context_projection': ['memory', 'grounding']},
                   'constructor': {'name': 'prompt', 'options': {'max_attempts': 1}}})
    limits = profile['budget']['options']['limits']
    for level in limits.values():
        level['node'] = iterations + 2
        level['token'] = token_budget
    budget = profile['budget']['options']
    budget.pop('reservation_modes', None)
    budget['operation_reservations']['operator'] = {'token': bound, 'eval_count': 0, 'node': 1}
    profile['governance'] = {'schema_version': 1, 'controls': {'after_main_cycles': cycles, 'seed': seed,
        'provider': {'name': 'mle-cny'}, 'domain': {'name': 'mle-public-control'},
        'operator': {'name': 'draft'}, 'request': {'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [seed]},
        'reservations': {'operator': {'token': bound, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 0, 'node': 0, 'eval_count': 1}}}}
    return profile


def run_governed_agent(*, workspace, task_id, model, api_base, token_budget, seed=1,
                       iterations=3, solution_timeout=120, variant="full", max_completion_tokens=4096,
                       runner=None, anonymization_key_path=None, spending_ledger_path=None, api_key=None,
                       resume=False, protected_roots=(), control_cycles=None):
    """Experimental M7 public-train entry; caller must supply the existing CNY ledger."""
    from zoo.mle_bench_lite.cny_budget import CampaignBudget
    from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
    from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider
    from core.composition.defaults import default_registry

    profile = build_governed_profile(variant=variant, token_budget=token_budget, seed=seed,
                                     iterations=iterations, max_completion_tokens=max_completion_tokens,
                                     control_cycles=control_cycles)
    if spending_ledger_path is None:
        raise ValueError("existing shared campaign ledger required")
    workspace = Path(workspace).resolve()
    artifacts = workspace.parent / "agent_artifacts"
    ledger_path = Path(spending_ledger_path).absolute()
    if any(ledger_path.resolve() == root or root in ledger_path.resolve().parents for root in (workspace, artifacts)):
        raise ValueError("ledger must stay outside candidate workspace and artifacts")
    if runner is None:
        runner = SandboxRunner()
    if isinstance(runner, SandboxRunner):
        runner.validate_paths(workspace, ledger_path, *protected_roots)
        runner.preflight()
    ledger = CampaignBudget(ledger_path)
    snapshot = ledger.snapshot()
    if snapshot.get("pending_calls") or snapshot.get("protection_breaches") or snapshot.get("journal_schema_version") != 2:
        raise ValueError("campaign must be quiescent and governance enabled")
    key_path = Path(anonymization_key_path).absolute() if anonymization_key_path else artifacts / "anonymization.key"
    if key_path == workspace or workspace in key_path.resolve().parents:
        raise ValueError("anonymization key must stay outside candidate workspace")
    artifacts.mkdir(parents=True, exist_ok=True)
    if isinstance(runner, SandboxRunner):
        runner.validate_paths(key_path)
    key = load_anonymization_key(key_path, create=anonymization_key_path is None and not resume
                                 and not (artifacts / "public_inputs").exists())
    bundle = PublicTrainBundle(workspace / "data", artifacts / "public_inputs", task_id, seed,
                              anonymization_key=key)
    domain = PublicTrainDomain(bundle, artifacts / "composed_candidates", solution_timeout=solution_timeout, runner=runner)
    registry = default_registry()
    registry.install_external_bridge('cny_invocation_v1', lambda: CNYInvocationBridge(ledger))
    binding = ledger.manifest_binding()
    secret = api_key if api_key is not None else os.environ.get('OPENAI_API_KEY')
    def fresh_provider():
        return GovernedCNYProvider(model, api_base, campaign_binding=binding,
            max_completion_tokens=max_completion_tokens, timeout=max(30., solution_timeout), api_key=secret,
            phase_call_limits={'operator': 1, 'evaluation': 0})
    provider = fresh_provider()
    registry.register('provider', 'mle-cny', lambda ctx, opts: fresh_provider(),
                      governance=provider.governance_binding())
    def fresh_domain(ctx, opts):
        return PublicTrainDomain(bundle, artifacts / 'control_candidates' / ctx.invocation_scope['slot_id'],
                                 solution_timeout=solution_timeout, runner=runner)
    registry.register('domain', 'mle-public-control', fresh_domain,
                      governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    task = task_description(bundle).replace('Return code only.',
        'Put the complete executable code in the artifact field of the required JSON response.')
    contract = {'protocol': PROTOCOL, 'profile': profile, 'dataset_identity': bundle.identity,
                'domain': domain.manifest_binding, 'provider': provider.manifest_binding(),
                'task_description_sha256': digest(task), 'runtime': 'm7-governed-cny'}
    contract_path = artifacts / 'agent_contract.json'
    if contract_path.exists():
        if not resume or contract_path.is_symlink() or json.loads(contract_path.read_text()) != contract:
            raise ValueError("agent contract differs from original run; use a fresh output directory")
    else:
        if resume or (artifacts / "composed/x1.jsonl").exists():
            raise ValueError("existing run lacks its original frozen agent contract")
        with contract_path.open('x') as stream:
            json.dump(contract, stream, sort_keys=True, allow_nan=False)
    cfg = LoopConfig(total_budget=token_budget, intent_cost=1, reeval_floor=0, max_generations=iterations,
                     checkpoint_enabled=True, resume_from_checkpoint=resume)
    fw = Framework.from_profile(profile, provider, domain, cfg, str(artifacts / 'composed'),
                                component_registry=registry)
    domain.restore_evidence(fw.store.read('composed_evidence'))
    result = fw.evolve(task)
    selected = next((row['payload'] for row in fw.store.read('composed_evidence')
                     if row['payload']['proposal']['candidate']['id'] == result.get('best_candidate_id')), None)
    if selected is None:
        raise ValueError('run has no admitted successful candidate to submit')
    inspection = fw.inspect()['governance']['external_currency']
    if inspection['unknown_cost_calls'] or inspection['integrity_violations'] or not inspection['protection_valid'] \
            or inspection['invocations'] < 1:
        raise ValueError("governed provider audit is incomplete or has an integrity violation")
    def replay_adapters(_workdir, _store):
        return fresh_provider(), PublicTrainDomain(bundle, artifacts / 'composed_candidates',
                                                   solution_timeout=solution_timeout, runner=runner)
    certificate = fw.replay(task, adapter_factory=replay_adapters)['replay_certificate']
    if not certificate.get('passed') or certificate.get('external_calls') != 0:
        raise ValueError('recorded replay did not certify the original run')
    from zoo.mle_bench_lite.m7_pilot_audit import audit_currency_receipts
    receipt_audit = audit_currency_receipts(artifacts / 'composed', ledger, expected_model=model)
    if receipt_audit['total_tokens'] != inspection['known_provider_tokens'] or \
            receipt_audit['settled_micro_cny'] != inspection['authority']['settled_upper_bound_micro_cny']:
        raise ValueError('independent currency receipts differ from framework inspection')
    selected_links = [link for link in receipt_audit['construction']['artifact_links']
                      if link['lane'] == 'main' and link['candidate_id'] == result['best_candidate_id']]
    if len(selected_links) != 1:
        raise ValueError('selected candidate lacks a unique main construction provenance')
    proposal_data = selected['proposal']
    proposal = Proposal(Candidate(**proposal_data['candidate']), proposal_data['artifact'])
    record = domain.materialize(proposal, workspace / 'submission.csv', expected_prediction_sha256=
        selected['evidence']['eval_result']['contract']['private']['data']['prediction_sha256'])
    from zoo.mle_bench_lite.m7_pilot_audit import audit_physical_and_submission
    physical_audit = audit_physical_and_submission(artifacts / 'composed', bundle, workspace / 'submission.csv',
                                                   expected_tokens=receipt_audit['total_tokens'])
    if physical_audit['selected_candidate_id'] != result['best_candidate_id']:
        raise ValueError('independent physical audit chose a different candidate')
    summary = {'runtime': result['runtime'], 'submission_materialized': True,
               'independent_physical_submission': physical_audit,
               'recorded_replay': certificate, 'independent_currency_receipts': receipt_audit, 'arm': variant, 'variant': variant, 'task_id': task_id,
               'seed': seed, 'protocol': PROTOCOL, 'requested_model': model, 'token_budget': token_budget,
               'actual_model': model, 'immutable_snapshot_verified': False,
               'profile': profile, 'profile_sha256': digest(profile),
               'dataset_identity': bundle.identity, 'dataset_manifest': bundle.manifest,
               'agent_contract_sha256': digest(contract), 'external_benchmark_score_produced': False,
               'selected_candidate_id': result['best_candidate_id'],
               'selected_artifact_sha256': record['identity']['artifact_sha256'],
               'prediction_sha256': record['prediction_sha256'], 'submission_sha256':
                   'sha256:' + __import__('hashlib').sha256((workspace / 'submission.csv').read_bytes()).hexdigest(),
               'token_usage': {'total_tokens': inspection['known_provider_tokens']},
               'details': {'training_invocations': domain.training_invocations, 'iterations': iterations,
                           'solution_timeout': solution_timeout, 'max_completion_tokens': max_completion_tokens,
                           'temperature': 0.0, 'temperature_applied': False, 'provider_request_format': 'deepseek',
                           'controls_completed': result['governance']['completed']}, 'currency_audit': inspection}
    from zoo.mle_bench_lite.pilot import public_snapshot
    summary['public_data_sha256'] = public_snapshot(workspace / 'data')['sha256']
    _atomic_json(artifacts / 'agent_run.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--variant", choices=("baseline", "full"), required=True)
    parser.add_argument("--runtime", choices=("legacy", "m7"), default="legacy")
    parser.add_argument("--max-completion-tokens", type=int, default=4096)
    parser.add_argument("--spending-ledger", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--control-cycles", type=int, nargs='+')
    args = parser.parse_args(argv)
    if not args.model:
        parser.error("--model is required for a frozen same-backbone comparison")
    if args.control_cycles is not None and args.runtime != 'm7':
        parser.error("--control-cycles requires the m7 runtime")
    expected_source = os.environ.get('MLE_COMPARISON_SOURCE_COMMIT')
    if expected_source:
        if args.runtime != 'm7' or args.control_cycles is None:
            parser.error('comparison source requires a governed control schedule')
        from zoo.mle_bench_lite.pilot import _comparison_runtime_source
        if _comparison_runtime_source()['commit'] != expected_source:
            raise ValueError('comparison child source differs from the frozen commit')
    entry = run_governed_agent if args.runtime == "m7" else run_agent
    schedule_options = {'control_cycles': args.control_cycles} if args.control_cycles is not None else {}
    summary = entry(workspace=args.workspace, task_id=args.task or os.environ.get("MLE_TASK_ID"),
        model=args.model, api_base=args.api_base, token_budget=args.token_budget, seed=args.seed,
        iterations=args.iterations, solution_timeout=args.solution_timeout, variant=args.variant,
        max_completion_tokens=args.max_completion_tokens, resume=args.resume,
        anonymization_key_path=os.environ.get("MLE_ANONYMIZATION_KEY_PATH"),
        spending_ledger_path=args.spending_ledger or os.environ.get("MLE_CNY_LEDGER_PATH") or None,
        protected_roots=(args.official_root or os.environ.get("MLE_OFFICIAL_ROOT"),
                         args.data_root or os.environ.get("MLE_DATA_ROOT")), **schedule_options)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
