"""Pure built-in construction recipes and versioned role registration."""
from dataclasses import asdict

from core.composition.construction import PromptMaterializer, RoleDefinition


DEFAULT_ROLES = {name: RoleDefinition(name, "1", text) for name, text in (
    ("general", "Construct a complete artifact that implements the stated hypothesis."),
    ("coder", "Construct executable code implementing the hypothesis; preserve the required interfaces."),
    ("analyst", "Construct an evidence-based analysis implementing the stated hypothesis; distinguish observations from assumptions."))}


def constructor_options(options):
    if type(options) is not dict or set(options) - {"max_attempts"} \
            or type(options.get("max_attempts", 1)) is not int or options.get("max_attempts", 1) < 1:
        raise ValueError("prompt constructor requires a positive max_attempts")


class RecipeOperator:
    measured_cost_units = ("token", "node", "eval_count")

    def __init__(self, kind, *, prompt_version="1", metric="dev/score"):
        self.kind, self.prompt_version, self.metric = kind, prompt_version, metric

    def recipe(self, request):
        if len(request.parents) != {"draft": 0, "reflective": 1, "crossover": 2}[self.kind] \
                or len(request.evidence) != len(request.parents):
            raise ValueError("construction recipe has invalid selected parent inputs")
        comparisons = {}
        for parent, evidence in zip(request.parents, request.evidence):
            if evidence.candidate_id != parent.candidate.id:
                raise ValueError("recipe parent differs from its comparison evidence")
            comparisons[parent.candidate.id] = evidence.eval_result.metrics[self.metric]
        instruction = request.context.get("instruction", "")
        if type(instruction) is not str:
            raise ValueError("recipe instruction must be configured text")
        return {"kind": self.kind, "task_desc": request.task_desc,
            "parent_artifacts": [{"candidate_id": p.candidate.id, "artifact": p.artifact} for p in request.parents],
            "instructions": [instruction] if instruction else [], "comparison": comparisons}


def register_construction(registry):
    registry.register("constructor", "prompt", lambda ctx, opts: PromptMaterializer(DEFAULT_ROLES, **opts),
        validate_options=constructor_options,
        execution={"schema_version": 1, "roles": {key: asdict(role) for key, role in DEFAULT_ROLES.items()}})
