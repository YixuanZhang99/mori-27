"""Driver-authorized, immutable run-local summaries of development evidence."""
from dataclasses import asdict

from core.composition.contracts import json_copy
from core.x1.checkpoint import payload_digest
from core.memory.types import MemoryEntry, Payload, Provenance, TimeMeta
from core.policy.types import MutationOp, StateMutation


def _hash(value):
    return 'sha256:' + payload_digest(json_copy(value))

def _events(memory, kind):
    if memory._research_events is None:
        raise ValueError('Arbor memory requires driver-bound original events')
    return memory._research_events(kind)

def validate(memory, ref, binding):
    fields = {'role', 'context', 'evaluation_context', 'candidate_id', 'cycle',
              'target_id', 'source_refs', 'previous_ref', 'body', 'synthesis_ref', 'trust'}
    if (set(binding) != fields or binding['role'] != 'tree_insight' or _hash(binding) != ref
            or binding['context'] != asdict(memory.context)
            or binding['evaluation_context'] != memory.evaluation_context):
        raise ValueError('Arbor insight binding differs from its run context')
    sources = binding['source_refs']
    if not sources or sources != sorted(set(sources)):
        raise ValueError('Arbor insight requires canonical development sources')
    for source in sources:
        original = memory.bindings.get(source, {})
        if (original.get('role') != 'dev' or original['context'] != binding['context']
                or original['evaluation_context'] != memory.evaluation_context
                or original['cycle'] > binding['cycle']):
            raise ValueError('Arbor insight contains foreign or non-development evidence')
    current = [memory.bindings[source] for source in sources
               if memory.bindings[source]['cycle'] == binding['cycle']]
    if not current or any(item['candidate_id'] != binding['candidate_id'] for item in current):
        raise ValueError('Arbor insight lacks current development evidence')
    trust = 'ungated' if any(memory.bindings[s]['status'] != 'ok' for s in sources) else 'gated'
    if binding['trust'] != trust:
        raise ValueError('Arbor insight trust exceeds its weakest source')
    previous = binding['previous_ref']
    if previous is not None:
        old = memory.bindings.get(previous, {})
        if (old.get('role') != 'tree_insight' or old['target_id'] != binding['target_id']
                or old['cycle'] >= binding['cycle'] or not set(old['source_refs']).issubset(sources)):
            raise ValueError('Arbor insight loses prior sources or creates a cycle')
    body = binding['body']
    if (type(body) is not dict or set(body) != {'target_id', 'source_refs', 'summary'}
            or body['target_id'] != binding['target_id'] or body['source_refs'] != sources
            or type(body['summary']) is not str or not body['summary'].strip()
            or len(body['summary']) > 4096):
        raise ValueError('Arbor insight summary has invalid identity or size')
    originals = [row['payload'] for row in _events(memory, 'arbor_synthesis')
                 if row['payload']['synthesis_ref'] == binding['synthesis_ref']]
    if len(originals) != 1:
        raise ValueError('Arbor insight lacks its original synthesis')
    event = originals[0]
    if (event['synthesis_ref'] != _hash({'request': event['request'], 'response': event['response']})
            or event['response'] != {'summary': body['summary']}
            or event['request']['source_refs'] != sources
            or event['request']['target_id'] != binding['target_id']
            or event['request']['candidate_id'] != binding['candidate_id']
            or event['request']['cycle'] != binding['cycle']
            or event['request']['previous_ref'] != previous):
        raise ValueError('Arbor insight differs from original synthesis')


def prepare(memory, *, target_id, source_refs, previous_ref, body, cycle, synthesis_ref):
    sources = sorted(set(source_refs))
    current = [memory.bindings.get(ref, {}) for ref in sources
               if memory.bindings.get(ref, {}).get('cycle') == cycle]
    if not current:
        raise ValueError('Arbor insight requires current evidence')
    binding = {'role': 'tree_insight', 'context': asdict(memory.context),
        'evaluation_context': memory.evaluation_context, 'candidate_id': current[0]['candidate_id'],
        'cycle': cycle, 'target_id': target_id, 'source_refs': sources,
        'previous_ref': previous_ref, 'body': body, 'synthesis_ref': synthesis_ref,
        'trust': 'ungated' if any(memory.bindings[r]['status'] != 'ok' for r in sources) else 'gated'}
    ref = _hash(binding)
    validate(memory, ref, binding)
    memory.bindings[ref] = binding
    memory.store.append('memory_tree_receipt_binding', {'receipt_ref': ref, **binding})
    identifier = 'arbor-insight:' + ref[7:]
    entry = MemoryEntry(identifier, Payload('structured', body, 'tree_insight/v1'),
        Provenance(memory.context.run_id, evidence_refs=[ref], trust_tier=binding['trust'],
                   source_candidate_id=binding['candidate_id']),
        TimeMeta(float(cycle)), memory.context, scope='run', level='L2')
    if binding['trust'] == 'ungated':
        entry.utility.harmful_count = 1
    return [StateMutation(MutationOp.WRITE_MEMORY, identifier, {'entry': entry, 'at': float(cycle)},
                          'retain source-bound incremental research insight')]


def validate_entry(memory, entry, ref, binding, *, imported):
    validate(memory, ref, binding)
    if (imported or entry.scope != 'run' or entry.context != memory.context
            or entry.id != 'arbor-insight:' + ref[7:] or entry.level != 'L2'
            or entry.provenance.evidence_refs != [ref]
            or entry.provenance.source_run_id != memory.context.run_id
            or entry.provenance.source_candidate_id != binding['candidate_id']
            or entry.provenance.trust_tier != binding['trust']
            or entry.payload.schema_id != 'tree_insight/v1' or entry.payload.body != binding['body']):
        raise ValueError('Arbor memory differs from its driver-authorized insight')


def verdict_binding(memory, verdict):
    if (type(verdict) is not dict or set(verdict) != {'candidate_id', 'admit', 'receipt_id'}
            or type(verdict['admit']) is not bool):
        raise ValueError('Arbor admission exports only candidate, verdict and receipt')
    records = [row['payload'] for row in _events(memory, 'layered_admission_receipt')
               if row['payload']['receipt_id'] == verdict['receipt_id']]
    if (len(records) != 1 or records[0]['admit'] != verdict['admit']
            or records[0]['decision_context']['candidate_id'] != verdict['candidate_id']):
        raise ValueError('Arbor admission verdict lacks its original controller receipt')
    return {'role': 'admission_verdict', 'context': asdict(memory.context),
            'evaluation_context': memory.evaluation_context, 'verdict': verdict}


def prepare_verdict(memory, verdict, *, cycle):
    binding = verdict_binding(memory, verdict)
    ref = _hash(binding)
    memory.bindings[ref] = binding
    memory.store.append('memory_admission_receipt_binding', {'receipt_ref': ref, **binding})
    identifier = 'arbor-verdict:' + ref[7:]
    entry = MemoryEntry(identifier, Payload('structured', verdict, 'admission_verdict/v1'),
        Provenance(memory.context.run_id, evidence_refs=[ref], trust_tier='gated',
                   source_candidate_id=verdict['candidate_id']),
        TimeMeta(float(cycle)), memory.context, scope='run', level='L1')
    return [StateMutation(MutationOp.WRITE_MEMORY, identifier, {'entry': entry, 'at': float(cycle)},
                          'record only the original admission verdict')]


def validate_verdict_entry(memory, entry, ref, binding, *, imported):
    if (binding != verdict_binding(memory, binding['verdict']) or _hash(binding) != ref
            or imported or entry.scope != 'run' or entry.context != memory.context
            or entry.id != 'arbor-verdict:' + ref[7:] or entry.level != 'L1'
            or entry.provenance.evidence_refs != [ref]
            or entry.provenance.source_candidate_id != binding['verdict']['candidate_id']
            or entry.provenance.source_run_id != memory.context.run_id
            or entry.provenance.trust_tier != 'gated'
            or entry.payload.schema_id != 'admission_verdict/v1' or entry.payload.body != binding['verdict']):
        raise ValueError('Arbor admission memory differs from its limited verdict')
