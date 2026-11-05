"""Pure built-in construction recipes and versioned role registration."""
from dataclasses import asdict
import hashlib

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

    def __init__(self, kind, *, prompt_version="1", metric="dev/score", max_debug_depth=2):
        self.kind, self.prompt_version, self.metric = kind, prompt_version, metric
        self.max_debug_depth = max_debug_depth

    def recipe(self, request):
        if len(request.parents) != {"draft": 0, "reflective": 1, "crossover": 2, 'debug': 1, 'improve': 1}[self.kind] \
                or len(request.evidence) != len(request.parents):
            raise ValueError("construction recipe has invalid selected parent inputs")
        comparisons = {}
        for parent, evidence in zip(request.parents, request.evidence):
            if evidence.candidate_id != parent.candidate.id:
                raise ValueError("recipe parent differs from its comparison evidence")
            if self.kind != 'debug':
                comparisons[parent.candidate.id] = evidence.eval_result.metrics[self.metric]
            else:
                entries = request.context.get('retrieval', {}).get('content', {}).get('memory', [])
                matched = [item for item in entries if type(item.get('body')) is dict and item['body'].get('kind') == 'aide_journal_v1'
                    and item['body'].get('candidate_id') == parent.candidate.id
                    and item.get('level') == 'L1'
                    and item.get('provenance', {}).get('source_candidate_id') == parent.candidate.id
                    and item['body'].get('artifact_sha256') == 'sha256:' + hashlib.sha256(parent.artifact.encode()).hexdigest()
                    and item['body'].get('status') in {'failed_to_run', 'timeout', 'invalid'}
                    and type(item['body'].get('public_feedback')) is str
                    and item['body']['public_feedback'].strip()]
                if len(matched) != 1:
                    raise ValueError('selected failed parent requires its source-bound public feedback')
        instruction = request.context.get("instruction", "")
        if type(instruction) is not str:
            raise ValueError("recipe instruction must be configured text")
        return {"kind": self.kind, "task_desc": request.task_desc,
            "parent_artifacts": [{"candidate_id": p.candidate.id, "artifact": p.artifact} for p in request.parents],
            "instructions": [instruction] if instruction else [], "comparison": comparisons}


class HypothesisRecipeOperator:
    """Use a driver-authorized trunk while retaining the hypothesis skeleton."""
    measured_cost_units = ('token', 'node', 'eval_count')

    def recipe(self, request):
        from core.composition.construction import validate_hypothesis_binding
        data = request.strategy['arbor']
        binding = data['binding']
        base = binding['execution_base']
        parents = [] if base is None else [{'candidate_id': base['candidate_id'], 'artifact': data['artifact']}]
        candidate = {'id': request.candidate_id, 'parents': [p.candidate.id for p in request.parents],
            'hypothesis': request.strategy['hypotheses'][0]['hypothesis'],
            'created_cycle': request.cycle, 'context_pack_ref': request.context['context_pack_ref']}
        validate_hypothesis_binding(binding, parents, candidate)
        return {'kind': 'hypothesis_refine', 'task_desc': request.task_desc,
            'parent_artifacts': parents, 'instructions': [
                'Implement this fixed hypothesis against the supplied current trunk. '
                'The hypothesis skeleton records research ancestry, not a different executable base.'],
            'comparison': {}, 'hypothesis_binding': binding}


class FunSearchRecipeOperator:
    """Bridge a driver-verified ordered program selection into a construction plan.

    The runtime must obtain this payload from its durable coordinator, not an
    untrusted policy. ConstructionPlan validates its shape and digests; the
    invocation audit must independently bind it to original journal events.
    """
    measured_cost_units = ("token", "node", "eval_count")

    def __init__(self, *, metric='dev/score'):
        if type(metric) is not str or not metric:
            raise ValueError('FunSearch comparison metric is required')
        self.metric = metric

    def recipe(self, request):
        try:
            data = request.strategy['funsearch']
            if type(data) is not dict or set(data) != {'selection', 'materialization'}:
                raise ValueError('FunSearch requires driver-bound selection and materialization')
            selection, materialized = data['selection'], data['materialization']
            if (type(selection) is not dict or type(materialized) is not dict or
                    materialized['samples'] != selection['samples'] or
                    selection['ancestry'] != [parent.candidate.id for parent in request.parents] or
                    len(request.parents) != len(request.evidence) or not request.parents):
                raise ValueError('FunSearch selected samples differ from parent inputs')
            comparisons = {}
            for parent, evidence in zip(request.parents, request.evidence):
                if evidence.candidate_id != parent.candidate.id:
                    raise ValueError('FunSearch parent differs from comparison evidence')
                comparisons[parent.candidate.id] = evidence.eval_result.metrics[self.metric]
            binding = {'selection': selection, **{key: materialized[key] for key in
                ('selection_ref', 'input_ref', 'prompt_ref', 'evidence_refs', 'binding_ref')}}
            return {'kind': 'funsearch', 'task_desc': request.task_desc,
                'parent_artifacts': [{'candidate_id': parent.candidate.id, 'artifact': parent.artifact}
                                     for parent in request.parents],
                'instructions': [materialized['prompt']], 'comparison': comparisons, 'funsearch_binding': binding}
        except (KeyError, TypeError) as exc:
            raise ValueError('invalid FunSearch recipe inputs') from exc


def register_construction(registry):
    registry.register("constructor", "prompt", lambda ctx, opts: PromptMaterializer(DEFAULT_ROLES, **opts),
        validate_options=constructor_options,
        execution={"schema_version": 1, "roles": {key: asdict(role) for key, role in DEFAULT_ROLES.items()}})


def funsearch_constructor_options(options):
    if type(options) is not dict or set(options) != {'template', 'function_name'}:
        raise ValueError('FunSearch constructor requires a frozen template and target')
    from core.composition.funsearch_validator import program_validator
    program_validator(options['template'], options['function_name'])


def register_funsearch_construction(registry):
    from core.composition.funsearch_validator import program_validator
    # Function-only restrictions describe the artifact, not the wire response.
    # Keep the M7 JSON envelope explicit, including for independent controls.
    output_instruction = (' Return exactly one JSON object with string fields "artifact" and "hypothesis". '
        'Put the complete Python function in the artifact string, using JSON escaping for newlines. '
        'Copy the input hypothesis unchanged. Do not return bare code or Markdown fences.')
    roles = {name: RoleDefinition(name, '2', role.instructions + output_instruction)
             for name, role in DEFAULT_ROLES.items()}
    registry.register('constructor', 'funsearch_prompt', lambda ctx, opts: PromptMaterializer(
        roles, validator=program_validator(opts['template'], opts['function_name']),
        validator_version='funsearch-program-v1', validator_deterministic=True),
        validate_options=funsearch_constructor_options,
        execution={'schema_version': 1, 'roles': {key: asdict(role) for key, role in roles.items()}})
