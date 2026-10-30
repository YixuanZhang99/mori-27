"""Population policy and an explicitly two-parent text crossover operator.

Text crossover does not claim a code-signature proof. The domain evaluates the
result through the usual canonical executor; M9 alone decides promotion.
"""
from __future__ import annotations

import json

from core.composition.contracts import OperatorFailure, Proposal
from core.composition.evaluation import validate_evidence
from core.composition.strategies import GreedyPolicy, policy_options
from core.executor.types import Candidate, CostVec, EvalStatus
from core.frontier.population import PopulationFrontier
from core.llm import UsageError, reset_usage, take_usage


def population_policy_options(options):
    policy_options(options)


class PopulationPolicy(GreedyPolicy):
    """Bootstrap two roots, then use the frontier's configured two-parent draw."""
    async def observe(self, state, budget):
        operators = state.get("operators") if isinstance(state, dict) else None
        if operators != ["draft", "crossover"]:
            raise ValueError("population policy requires operators ordered as draft, crossover")
        return await super().observe(state, budget)

    async def select(self, frontier, budget):
        if not isinstance(frontier, PopulationFrontier) or frontier.capacity < 2:
            raise ValueError("population policy requires a population frontier with capacity >= 2")
        if len(frontier.eligible_parent_ids()) < 2:
            return []
        return frontier.sample(2)

    async def ideate(self, context, parent, k):
        if type(k) is not int or k < 1:
            raise ValueError("population ideation requires a positive integer count")
        return [{"operator": "crossover" if parent is not None else "draft",
                 "hypothesis": "Combine complementary behavior from two valid population members"
                    if parent is not None else "Establish an independent population member"} for _ in range(k)]


def crossover_options(options):
    if type(options) is not dict or set(options) - {"prompt_version", "metric"}:
        raise ValueError("unknown text crossover options")
    for name, default in (("prompt_version", "1"), ("metric", "dev/score")):
        if type(options.get(name, default)) is not str or not options.get(name, default).strip():
            raise ValueError("text crossover version and metric must be nonempty text")


class CrossoverOperator:
    measured_cost_units = ("token", "node", "eval_count")

    def __init__(self, llm, *, prompt_version="1", metric="dev/score"):
        crossover_options({"prompt_version": prompt_version, "metric": metric})
        if not callable(llm):
            raise ValueError("text crossover requires a callable provider")
        self.llm, self.prompt_version, self.metric = llm, prompt_version, metric

    async def propose(self, request):
        if len(request.parents) != 2 or len(request.evidence) != 2:
            raise ValueError("crossover requires exactly two parents and their development evidence")
        ids = [parent.candidate.id for parent in request.parents]
        if len(set(ids)) != 2 or request.candidate_id in ids:
            raise ValueError("crossover requires distinct parent and child identities")
        parent_records = []
        for parent, evidence in zip(request.parents, request.evidence):
            validate_evidence(evidence, require_full=False)
            if evidence.candidate_id != parent.candidate.id or evidence.eval_result.status is not EvalStatus.OK \
                    or evidence.eval_result.contract.binding.split_id != "dev" \
                    or self.metric not in evidence.eval_result.metrics:
                raise ValueError("crossover parent lacks matching successful public development evidence")
            if not isinstance(parent.artifact, str) or not parent.artifact.strip():
                raise ValueError("crossover parent artifact must be nonempty text")
            import hashlib
            # Bind the supplied parent code independently of its displayed ID.
            if evidence.eval_result.contract.binding.artifact_sha256 != hashlib.sha256(parent.artifact.encode()).hexdigest():
                raise ValueError("crossover parent artifact differs from its evaluation receipt")
            parent_records.append({"candidate_id": parent.candidate.id, "artifact": parent.artifact,
                                   "metric": self.metric, "score": evidence.eval_result.metrics[self.metric],
                                   "feedback": evidence.eval_result.text_feedback})
        prompt = (f"[composed-crossover v{self.prompt_version}]\n"
                  "Combine useful behavior from BOTH identified parents into one complete candidate.\n"
                  "PARENTS:\n" + json.dumps(parent_records, ensure_ascii=False, sort_keys=True)
                  + "\nCONTEXT:\n" + json.dumps(request.context, ensure_ascii=False, sort_keys=True)
                  + "\nTASK:\n" + request.task_desc)
        reset_usage(self.llm)
        try:
            artifact = self.llm(prompt)
        except UsageError:
            raise
        except Exception as error:
            used = take_usage(self.llm)
            raise OperatorFailure(CostVec(tokens_in=used, node_count=1),
                f"{type(error).__name__}: {error}", measured_cost_units=self.measured_cost_units) from error
        used = take_usage(self.llm)
        if type(artifact) is not str or not artifact.strip():
            raise OperatorFailure(CostVec(tokens_in=used, node_count=1), "crossover returned an empty candidate",
                                  measured_cost_units=self.measured_cost_units)
        candidate = Candidate(request.candidate_id, ids, operator="crossover", created_cycle=request.cycle,
                              context_pack_ref=request.context.get("context_pack_ref"))
        candidate.validate()
        return Proposal(candidate, artifact, CostVec(tokens_in=used, node_count=1), self.measured_cost_units)
