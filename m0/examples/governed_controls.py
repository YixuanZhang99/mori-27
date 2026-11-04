"""Offline resident-control example using only the installed public Framework API.

    python governed_controls.py --workdir /tmp/mori-controls
    python governed_controls.py --workdir /tmp/mori-controls --resume
    python governed_controls.py --workdir /tmp/mori-controls --replay

The provider is a declared deterministic fixture. Synthetic token counts exercise
accounting; they are neither model usage nor evidence of IID sampling/superiority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

from core.composition.defaults import composed_profile, default_registry
from core.composition.evaluation import EvaluationContract, binding_for
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.loop import Framework, LoopConfig
from core.x1.checkpoint import RunCheckpoint


TASK = "Return candidate_value=N, where N is an integer from 0 through 100. Aim for 73."
MAX_GENERATIONS = 3
MEASURED_UNITS = ("token", "node", "eval_count")
CAPABILITY = {
    "schema_version": 1,
    "fresh_session": True,
    "state_independent": True,
    "sampling": {"method": "deterministic_fixture", "parameters": {}, "applied": True},
    "call_bound": {"kind": "hard", "units": {"token": 5}},
    "external_currency": False,
}


class FixtureProvider:
    """Each fresh session owns its seed and counter; no network or shared RNG."""

    model = "governed-integer-fixture-v1"
    supplier = "offline-simulation"

    def __init__(self, seed=0):
        self.seed = seed
        self.generation_index = 0
        self.last_usage = {"total_tokens": 0}

    def __call__(self, prompt):
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("fixture provider requires a nonempty prompt")
        self.generation_index += 1
        value = (self.seed * 17 + self.generation_index * 29) % 101
        # Deliberate fixture accounting, with a true bound for this local adapter.
        self.last_usage = {"total_tokens": 5}
        return f"candidate_value={value}"

    def governance_binding(self):
        return copy.deepcopy(CAPABILITY)

    def checkpoint_state(self):
        return {"seed": self.seed, "generation_index": self.generation_index}

    def restore_state(self, state):
        if set(state) != {"seed", "generation_index"} or state["seed"] != self.seed \
                or type(state["generation_index"]) is not int or state["generation_index"] < 0:
            raise ValueError("fixture checkpoint differs from its frozen session")
        self.generation_index = state["generation_index"]


class IntegerDomain:
    """Canonical development evaluation with an explicit content identity."""

    evaluator_version = "integer-distance-v1"
    evaluation_context = "sha256:" + hashlib.sha256(b"integer-distance-v1;target=73;range=0..100").hexdigest()
    measured_cost_units = MEASURED_UNITS

    def validate_request(self, request):
        request.validate()
        if request.fidelity != "dev" or request.split_id != "dev" or request.resume_from is not None:
            raise ValueError("integer fixture supports only development evaluation")

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        match = re.fullmatch(r"candidate_value=(\d{1,3})", proposal.artifact.strip())
        value = int(match.group(1)) if match else None
        valid = value is not None and 0 <= value <= 100
        metrics = {"dev/score": 1.0 - abs(value - 73) / 100.0} if valid else {}
        return EvalResult(
            EvalStatus.OK if valid else EvalStatus.INVALID,
            metrics=metrics, cost=CostVec(eval_count=1), fidelity=request.fidelity,
            text_feedback=f"Development target is 73; candidate value is {value}.",
            contract=EvaluationContract(binding_for(proposal, request,
                evaluator_version=self.evaluator_version,
                evaluation_context=self.evaluation_context), MEASURED_UNITS))


def build_framework(workdir, *, resume=False, pause_after=None):
    registry = default_registry()
    registry.register("provider", "seeded_fixture", lambda ctx, opts:
        FixtureProvider(ctx.invocation_scope["seed"]), governance=CAPABILITY)
    registry.register("domain", "integer_fixture", lambda ctx, opts: IntegerDomain(),
        governance={"schema_version": 1, "fresh_session": True, "state_independent": True})
    profile = composed_profile(name="governed-integer-example")
    profile["domain"] = {"name": "native"}
    profile["budget"] = {"name": "hierarchical", "options": {
        "limits": {
            "global": {"token": 100, "node": 20, "eval_count": 20},
            "direction": {"token": 100, "node": 20, "eval_count": 20},
            "candidate": {"token": 20, "node": 4, "eval_count": 4}},
        "reservation": {"token": 0, "node": 0, "eval_count": 1},
        "operation_reservations": {
            "planning": {"token": 5, "node": 0, "eval_count": 0},
            "operator": {"token": 5, "node": 1, "eval_count": 0}},
        "fidelity_rungs": [{"fidelity": "dev", "split_id": "dev", "seed_set": [1]}]}}
    profile["governance"] = {"schema_version": 1, "controls": {
        "after_main_cycles": [0, 2, 4], "seed": 7,
        "provider": {"name": "seeded_fixture", "options": {}},
        "domain": {"name": "integer_fixture", "options": {}},
        "operator": {"name": "draft", "options": {}},
        "request": {"fidelity": "dev", "split_id": "dev", "seed_set": [1]},
        "reservations": {
            "operator": {"token": 5, "node": 1, "eval_count": 0},
            "evaluation": {"token": 0, "node": 0, "eval_count": 1}}}}
    config = LoopConfig(max_generations=MAX_GENERATIONS, total_budget=100,
        reeval_floor=0, resume_from_checkpoint=resume, stop_after_generation=pause_after)
    return Framework.from_profile(profile, FixtureProvider(), IntegerDomain(), config,
                                  str(workdir), component_registry=registry)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True, help="durable run directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true", help="continue the existing checkpoint")
    mode.add_argument("--replay", action="store_true", help="verify a completed run using recorded outcomes")
    parser.add_argument("--pause-after", type=int, choices=range(MAX_GENERATIONS + 1),
                        help="optional checkpoint pause after generation 0, 1, 2 or 3")
    args = parser.parse_args(argv)
    checkpoint = args.workdir / "checkpoint.json"
    if (args.resume or args.replay) and not checkpoint.is_file():
        parser.error("resume/replay requires an existing checkpoint in --workdir")
    if args.replay:
        if args.pause_after is not None:
            parser.error("--pause-after cannot be combined with --replay")
        payload = RunCheckpoint.load(checkpoint).payload
        if payload["next_cycle"] < MAX_GENERATIONS + 1:
            parser.error("this example requires --resume to finish a paused run before --replay")
    framework = build_framework(args.workdir, resume=args.resume or args.replay,
                                pause_after=args.pause_after)
    result = framework.evolve(TASK)
    certificate = framework.replay(TASK)["replay_certificate"] if args.replay else None
    report = framework.inspect()
    summary = {"runtime": result["runtime"], "workdir": str(args.workdir.resolve()),
        "best_candidate_id": result["best_candidate_id"],
        "best_score": result.get("best_score"), "governance": report["governance"],
        "replay_certificate": certificate,
        "fixture_notice": "Deterministic offline fixture; no IID, superiority or paid-run certification."}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
