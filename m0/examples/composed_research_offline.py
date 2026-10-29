"""Run all five configured stages locally, without credentials or network.

This is a deterministic contract demonstration, not a research benchmark. The
proposer reports synthetic fixture token usage; local evaluations report their
actual call count. No GPU, currency, or wall-clock measurements are claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.defaults import composed_profile
from core.composition.evaluation import (EvaluationContract, PrivateEvaluationData,
                                        PublicEvaluationData, binding_for)
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.loop import Framework, LoopConfig


class LocalProposer:
    model = "offline-checklist-proposer-v1"
    supplier = "offline-simulation"
    measured_cost_units = ("token",)

    def __init__(self):
        self.prompts = []
        self.last_usage = {"total_tokens": 0}

    def __call__(self, prompt):
        self.prompts.append(prompt)
        self.last_usage = {"total_tokens": 20}
        if prompt.startswith("[draft"):
            artifact = "STATE_ASSUMPTIONS\nSHOW_ARITHMETIC"
        else:
            artifact = prompt.split("CURRENT PROMPT:\n", 1)[1].split("\n\nSCORE:", 1)[0]
            for missing in re.findall(r"NEXT_CHECK=([A-Z_]+)", prompt):
                if missing not in artifact:
                    artifact += "\n" + missing
                    break
        # An actual opened ground source changes the generated artifact.
        if "CHECK_UNITS" in prompt and "CHECK_UNITS" not in artifact:
            artifact += "\nCHECK_UNITS"
        return artifact


class ChecklistDomain:
    evaluator_version = "offline-checklist-domain-v1"
    measured_cost_units = ("token", "eval_count")
    metric = "dev/score"

    def __init__(self):
        self.cases = {
            "dev": (("addition", ("SHOW_ARITHMETIC",)),
                    ("distance", ("CHECK_UNITS",)),
                    ("division", ("STATE_ASSUMPTIONS", "VERIFY_RESULT"))),
            "admission": (("discount", ("SHOW_ARITHMETIC", "VERIFY_RESULT")),
                          ("volume", ("CHECK_UNITS", "VERIFY_RESULT"))),
            "final_audit": (("conversion", ("CHECK_UNITS", "VERIFY_RESULT")),),
        }
        self.contexts = {split: self._context(split) for split in self.cases}
        self.evaluation_context = self.contexts["dev"]
        self.calls = []

    def _context(self, split):
        data = {"evaluator": self.evaluator_version, "split": split, "cases": self.cases[split]}
        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def validate_context(self):
        if any(self._context(split) != context for split, context in self.contexts.items()):
            raise ValueError("offline dataset content or evaluator configuration changed")

    def validate_request(self, request):
        request.validate()
        self.validate_context()
        if request.split_id not in self.cases or request.fidelity != request.split_id:
            raise ValueError("unsupported offline split/fidelity")
        if any(value is not None for value in (request.time_limit, request.budget_token, request.resume_from)):
            raise ValueError("this deterministic domain does not support execution resource hints")

    def evaluation_context_for(self, request):
        self.validate_request(request)
        return self.contexts[request.split_id]

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        self.calls.append((proposal.candidate.id, request.split_id))
        outcomes = {identifier: all(check in proposal.artifact for check in checks)
                    for identifier, checks in self.cases[request.split_id]}
        score = sum(outcomes.values()) / len(outcomes)
        missing = sorted({check for _, checks in self.cases[request.split_id] for check in checks
                          if check not in proposal.artifact})
        feedback = (" ".join("NEXT_CHECK=" + check for check in missing) or "All development checks pass.") \
            if request.split_id == "dev" else "HELD_OUT_FEEDBACK_MUST_NOT_ENTER_SEARCH"
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context_for(request))
        return EvalResult(EvalStatus.OK, {self.metric: score},
            CostVec(tokens_in=0, eval_count=1), fidelity=request.fidelity, text_feedback=feedback,
            contract=EvaluationContract(binding, ("token", "eval_count"), token_accounting="total_only",
                public=PublicEvaluationData({"case_count": len(outcomes)}) if request.split_id == "dev" else PublicEvaluationData(),
                private=PrivateEvaluationData(data={"case_outcomes": outcomes})))


def example_profile(root):
    sources = root / "sources"
    sources.mkdir()
    ground, audit = sources / "ground.txt", sources / "audit.txt"
    ground.write_text("Arithmetic checklist guidance: include CHECK_UNITS to make dimensions explicit.\n", encoding="utf-8")
    audit.write_text("AUDIT_ONLY_SOURCE: historical checklist formatting and independent related work.\n", encoding="utf-8")
    profile = composed_profile("offline-research", mode="research")
    profile["domain"] = {"name": "native"}
    profile["memory"] = {"name": "scoped", "options": {"context_scope": "ancestors", "export_on_finish": True}}
    profile["knowledge"] = {"name": "local_files", "options": {
        "ground_files": [{"path": str(ground)}], "audit_files": [{"path": str(audit)}],
        "ingest_on_finish": True}}
    profile["admission"] = {"name": "layered", "options": {
        "admission_seeds": [11], "final_seeds": [37], "call_budget": 8}}
    local_eval = {"token": 0, "eval_count": 1, "node": 0}
    profile["budget"] = {"name": "hierarchical", "options": {
        "limits": {"global": {"token": 1000, "eval_count": 100, "node": 20},
                   "direction": {"token": 500, "eval_count": 50, "node": 10},
                   "candidate": {"token": 200, "eval_count": 10, "node": 1}},
        "reservation": {"token": 100, "eval_count": 0, "node": 0},
        "operation_reservations": {"operator": {"token": 100, "eval_count": 0, "node": 1},
            "dev": local_eval, "dev_baseline": local_eval, "admission": local_eval, "final": local_eval},
        "fidelity_rungs": [{"fidelity": "dev", "split_id": "dev", "seed_set": [1]}],
        "convergence": {"patience": 2, "min_samples": 3, "min_improvement": 0.0}}}
    return profile


def run(workdir=None):
    if workdir is None:
        root = Path(tempfile.mkdtemp(prefix="composed-research-offline-"))
    else:
        root = Path(workdir).resolve()
        root.mkdir(parents=True, exist_ok=False)
    provider, domain = LocalProposer(), ChecklistDomain()
    framework = Framework.from_profile(example_profile(root), provider, domain,
        LoopConfig(max_generations=2, total_budget=10_000, intent_cost=100,
                   reeval_floor=0, baseline_every=2), str(root / "run"))
    result = framework.evolve("Improve the offline arithmetic checklist from observed development failures.")
    report = result["reporting"]
    assert report["dev_best"] and report["gate_selected"]
    assert report["final_audit"]["calls"] == 1
    assert "CHECK_UNITS" in result["best_prompt"]
    assert "AUDIT_ONLY_SOURCE" not in repr(provider.prompts)
    assert "HELD_OUT_FEEDBACK_MUST_NOT_ENTER_SEARCH" not in repr(provider.prompts)
    assert result["ledger"]["global"]["used"]["token"] == len(provider.prompts) * 20
    assert result["ledger"]["global"]["used"]["eval_count"] == len(domain.calls)
    assert result["ledger"]["global"]["used"]["node"] == len(provider.prompts)
    export = result["memory_export"]
    assert export["status"] == "exported" and (root / "run" / export["relative_path"]).is_file()
    replay = framework.replay()["replay_certificate"]
    assert replay["passed"]
    return {"workdir": str(root), "reporting": report, "budget": result["ledger"],
            "memory_export": export, "replay_passed": replay["passed"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", help="New output directory; omitted uses a fresh temporary directory")
    args = parser.parse_args()
    output = run(args.workdir)
    report = output["reporting"]
    final = report["final_audit"]
    print("workdir:", output["workdir"])
    print("dev_best:", report["dev_best"])
    print("gate_selected:", report["gate_selected"])
    print("final_audit:", {"state": final["state"], "selected_id": final.get("selected_id"),
                           "calls": final["calls"], "metrics": final.get("evidence", {}).get("eval_result", {}).get("metrics")})
    print("global_budget:", output["budget"]["global"])
    print("direction_budgets:", output["budget"]["directions"])
    print("candidate_budgets:", output["budget"]["candidates"])
    print("memory_export:", output["memory_export"])
    print("replay_passed:", output["replay_passed"])
