"""Build pinned OpenEvolve prompts exclusively from original dev evidence."""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

from core.composition.contracts import Proposal
from core.composition.evaluation import binding_for, decode_evidence, encode_evidence
from core.executor.types import Candidate, EvalRequest, EvalStatus
from core.x1.checkpoint import payload_digest
# Initializes the repository-pinned host package path.
from core.openevolve_interop import ProgramDatabase as _ProgramDatabase  # noqa: F401
from openevolve.config import PromptConfig
import yaml
from openevolve.prompt.sampler import PromptSampler

_VENDOR = Path(__file__).resolve().parents[2] / 'vendor/openevolve'
_CONFIG = _VENDOR / 'examples/circle_packing/config_phase_1.yaml'
_SAMPLER = _VENDOR / 'openevolve/prompt/sampler.py'
_TEMPLATES = _VENDOR / 'openevolve/prompt/templates.py'
_DEFAULTS = _VENDOR / 'openevolve/prompts/defaults'


def _verify_sources():
    expected = {str(_CONFIG): '9b8de628dba5938e4885b5bac969eef9a500d42b9b4f28745f455f9dc7a920e8',
                str(_SAMPLER): '9e71234def141426fdf6372d9793301308dc55cdafe5f4d2a067ae9e1ee59eb3',
                str(_TEMPLATES): '2a6f2ae941f5eeabf02c5de0c49bd3eac7c5eb9e215c221c965c1cc2d430d212'}
    for name, digest in expected.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError('pinned OpenEvolve prompt source changed')
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in _DEFAULTS.iterdir()
             if p.is_file() and (p.suffix == '.txt' or p.name == 'fragments.json')}
    if len(files) != 14 or payload_digest(files) != 'a2b7705c05fddcb90c3711302dff44dfa0dc5fa83a3507abf8da0cf4800403a7':
        raise ValueError('pinned OpenEvolve prompt template source changed')



def _ref(value):
    return 'sha256:' + payload_digest(value)


def build_bound_prompt(selection, host_events, evidence_rows, *, logical_run_id,
                       evaluator_version, evaluation_context, evolution_round=0):
    """Resolve real selected artifacts; callers supply authenticated run journals."""
    _verify_sources()
    if type(evolution_round) is not int or evolution_round < 0:
        raise ValueError('evolution round must be nonnegative')
    if any(type(v) is not str or not v for v in (logical_run_id, evaluator_version, evaluation_context)):
        raise ValueError('frozen run and evaluator identity required')
    if type(selection) is not dict or type(host_events) is not list or not host_events \
            or host_events[-1].get('kind') != 'select' or host_events[-1].get('result') != selection:
        raise ValueError('selection differs from its original host event')
    required = {'candidate_id', 'host_parent_id', 'source_candidate_id', 'evidence_ref', 'island',
                'inspiration_host_ids', 'inspirations', 'before_ref', 'after_ref'}
    if set(selection) != required or type(selection['inspirations']) is not list \
            or type(selection['inspiration_host_ids']) is not list \
            or [row.get('host_id') for row in selection['inspirations']] != selection['inspiration_host_ids']:
        raise ValueError('invalid host selection receipt')
    references = [(selection['host_parent_id'], selection['source_candidate_id'], selection['evidence_ref'])]
    for item in selection['inspirations']:
        if type(item) is not dict or set(item) != {'host_id', 'source_candidate_id', 'evidence_ref'}:
            raise ValueError('invalid inspiration binding')
        references.append((item['host_id'], item['source_candidate_id'], item['evidence_ref']))
    if any(type(value) is not str or not value for row in references for value in row):
        raise ValueError('invalid selected host or source identity')
    wanted = {row[1] for row in references}
    found = {}
    for row in evidence_rows:
        if type(row) is not dict or set(row) != {'cycle', 'proposal', 'evidence_ref', 'evidence'}:
            raise ValueError('invalid composed evidence journal row')
        proposal = row['proposal']
        candidate = proposal['candidate']['id']
        if candidate not in wanted:
            continue
        if candidate in found:
            raise ValueError('duplicate original evidence for selected source')
        evidence = decode_evidence({'schema_version': 1, 'evidence': row['evidence']})
        result = evidence.eval_result
        binding = result.contract.binding
        artifact = proposal['artifact']
        expected_binding = binding_for(Proposal(Candidate(**proposal['candidate']), artifact),
            EvalRequest(fidelity='dev', split_id='dev'), evaluator_version=evaluator_version,
            evaluation_context=evaluation_context)
        if type(artifact) is not str or not artifact or evidence.candidate_id != candidate \
                or binding != expected_binding or result.status is not EvalStatus.OK:
            raise ValueError('selected source is not the bound successful dev evidence')
        score = result.metrics.get('dev/score')
        if type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError('selected source lacks finite development score')
        expected_ref = _ref({'logical_run_id': logical_run_id, 'evidence': encode_evidence(evidence)})
        if row['evidence_ref'] != expected_ref:
            raise ValueError('selected source evidence reference differs')
        found[candidate] = {'candidate_id': candidate, 'artifact': artifact,
                            'program_ref': 'sha256:' + binding.artifact_sha256,
                            'evidence_ref': expected_ref, 'score': score}
    if set(found) != wanted:
        raise ValueError('selected source lacks original evidence')
    for _, candidate, evidence_ref in references:
        if found[candidate]['evidence_ref'] != evidence_ref:
            raise ValueError('selection reference differs from original evidence')
    primary = found[selection['source_candidate_id']]
    inspirations = [{**found[source], 'host_id': host_id} for host_id, source, _ in references[1:]]
    # Read only the prompt section; never resolve provider credentials here.
    config = PromptConfig(**yaml.safe_load(_CONFIG.read_text())['prompt'])
    if config.template_dir is not None or config.template_variations:
        raise ValueError('pinned prompt configuration requires deterministic default templates')
    # Input sets are already host-selected; no extra random top/diverse sampling.
    # The pinned configuration remains otherwise unchanged.
    prompt = PromptSampler(config).build_prompt(
        current_program=primary['artifact'], parent_program='',
        program_metrics={'combined_score': primary['score']}, previous_programs=[], top_programs=[],
        inspirations=[{'id': item['host_id'], 'code': item['artifact'],
                       'metrics': {'combined_score': item['score']}} for item in inspirations],
        language='python', evolution_round=evolution_round,
        diff_based_evolution=True, feature_dimensions=['complexity', 'diversity'],
        island_id=selection['island'])
    if type(prompt) is not dict or set(prompt) != {'system', 'user'} \
            or any(type(value) is not str or not value for value in prompt.values()):
        raise ValueError('vendor prompt sampler returned invalid messages')
    binding = {'selection': copy.deepcopy(selection), 'primary': copy.deepcopy(primary),
               'inspirations': copy.deepcopy(inspirations), 'evolution_round': evolution_round, 'sampler_config_ref': 'sha256:' + hashlib.sha256(_CONFIG.read_bytes()).hexdigest()}
    return {**prompt, **binding, 'input_ref': _ref(binding), 'prompt_ref': _ref(prompt)}
