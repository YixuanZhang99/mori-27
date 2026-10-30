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
from zoo.mle_bench_lite.public_train import PROTOCOL, PublicTrainBundle, digest


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
        "and the supplied CSV features. Set random seeds explicitly. Do not use internet, images or geometry files. "
        "Do not read other directories or launch persistent processes.\nPROTOCOL:\n" + json.dumps(bundle.protocol, sort_keys=True))


def run_agent(*, workspace, task_id, model, api_base, token_budget=60000, seed=1,
              iterations=3, solution_timeout=120, variant="full", max_completion_tokens=4096,
              provider=None, runner=None, resume=False, protected_roots=()):
    profile = build_profile(variant=variant, token_budget=token_budget, seed=seed, iterations=iterations)
    workspace = Path(workspace).resolve()
    if runner is None or isinstance(runner, SandboxRunner):
        SandboxRunner.validate_paths(workspace, *protected_roots)
    artifacts = workspace.parent / "agent_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    bundle = PublicTrainBundle(workspace / "data", artifacts / "public_inputs", task_id, seed)
    domain = PublicTrainDomain(bundle, artifacts / "composed_candidates", solution_timeout=solution_timeout, runner=runner)
    if not model or type(model) is not str:
        raise ValueError("explicit model is required")
    if provider is None:
        from zoo.mle_bench_lite.provider import BenchmarkProvider
        provider = BenchmarkProvider(model=model, base_url=api_base, usage_dir=artifacts / "token_usage",
            token_budget=token_budget, max_completion_tokens=max_completion_tokens,
            temperature=0.0, timeout=max(30.0, solution_timeout))
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
    usage_audit = audit_usage(artifacts / "token_usage")
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
            "training_invocations": domain.training_invocations, "evaluation_calls": len(domain.calls),
            "physical_ledger": framework._composed.budget.state(), "result": result}}
    # This full public tree identity is an independent cross-check of the pilot
    # runner's copied inputs (auxiliary files are bound even though unused).
    from zoo.mle_bench_lite.pilot import public_snapshot
    summary["public_data_sha256"] = public_snapshot(workspace / "data")["sha256"]
    _atomic_json(artifacts / "agent_run.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--variant", choices=("baseline", "full"), required=True)
    parser.add_argument("--max-completion-tokens", type=int, default=4096)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if not args.model:
        parser.error("--model is required for a frozen same-backbone comparison")
    summary = run_agent(workspace=args.workspace, task_id=args.task or os.environ.get("MLE_TASK_ID"),
        model=args.model, api_base=args.api_base, token_budget=args.token_budget, seed=args.seed,
        iterations=args.iterations, solution_timeout=args.solution_timeout, variant=args.variant,
        max_completion_tokens=args.max_completion_tokens, resume=args.resume,
        protected_roots=(args.official_root or os.environ.get("MLE_OFFICIAL_ROOT"),
                         args.data_root or os.environ.get("MLE_DATA_ROOT")))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
