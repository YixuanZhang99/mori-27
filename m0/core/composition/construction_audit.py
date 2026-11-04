"""Read-only join of frozen construction, provider receipts and published artifacts.

Currency prices remain in the external authority. This reducer verifies which
candidate-production operation each provider call and artifact belongs to.
"""
from dataclasses import asdict
import json

from core.composition.construction import ConstructionResult, decode_construction_outcome
from core.composition.contracts import ExecutionConfig
from core.composition.execution import Materialization, _operation
from core.composition.external_provider import CONSTRUCTION_EXTERNAL_RUNTIME
from core.x1.checkpoint import payload_digest


def _prompt_request(arguments, context, identity, frozen, spec):
    key = payload_digest(context)
    if key not in arguments:
        raise ValueError('construction prompt has no original currency preparation')
    prompt = arguments[key]
    if prompt is None:
        return None  # Proven pre-dispatch refusal; no wire request exists.
    if payload_digest({'args': (prompt,), 'kwargs': {}}) != context['argument_sha256']:
        raise ValueError('construction prompt differs from original invocation')
    if identity['materializer']['kind'] != 'prompt_materializer_v1':
        return None  # Custom constructor bytes retain their own versioned contract.
    try:
        request = json.loads(prompt)
        session = 'main' if context['lane'] == 'main' else context['slot_id']
        projection = request['context']
        if request['plan_ref'] != identity['plan_ref'] or \
                request['role'] != frozen['roles'][session].get(spec['role']) or \
                request['hypothesis_frozen'] is not spec['hypothesis_frozen'] or \
                type(request['attempt']) is not int or request['attempt'] != context['ordinal'] + 1 or \
                projection['fields'] != spec['context_projection'] or \
                set(projection['content']) != set(spec['context_projection']):
            raise ValueError('construction prompt differs from frozen plan/projection')
    except (TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError('invalid original construction prompt') from error
    return request


def _validate_prompt_result(result, receipts, spec):
    prompts = [r['prompt'] for r in receipts if r['prompt'] is not None]
    if not prompts:
        return
    first = prompts[0]
    projection_ref = 'sha256:' + payload_digest(first['context'])
    candidate = {**result['candidate'], 'hypothesis': result['initial_hypothesis']}
    original = {'schema_version': 1, 'candidate': candidate, 'recipe': first['recipe'],
                'spec': spec, 'role': first['role'], 'projection': first['context'],
                'projection_ref': projection_ref}
    if result['initial_hypothesis'] != first['hypothesis'] or result['projection_ref'] != projection_ref or \
            result['plan_ref'] != 'sha256:' + payload_digest(original) or \
            any(p['context'] != first['context'] or p['recipe'] != first['recipe'] for p in prompts):
        raise ValueError('construction result differs from its original paid prompt plan')
    try:
        original_output = json.loads(receipts[-1]['result'])
        if original_output['artifact'] != result['artifact'] or \
                original_output['hypothesis'] != result['effective_hypothesis']:
            raise ValueError('construction artifact differs from original paid prompt response')
    except (TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError('construction lacks a valid original paid prompt response') from error


def audit_construction(rows, frozen, *, logical_run_id, provider_arguments):
    starts, terminals, artifacts, calls = {}, {}, {}, {}
    run_starts = [r['payload'] for r in rows if r['kind'] == 'run_start']
    if len(run_starts) > 1:
        raise ValueError('duplicate construction run identity')
    if not run_starts:
        if any(r['kind'] in {'construction_started', 'materialization_completed',
                             'composed_provider_started'} for r in rows):
            raise ValueError('construction proof lacks its original run manifest')
        return {'schema_version': 1, 'materializations': 0, 'provider_calls': 0, 'artifact_links': []}
    run = run_starts[0]
    manifest = run['manifest']
    if run['runtime'] != CONSTRUCTION_EXTERNAL_RUNTIME or \
            payload_digest({k: v for k, v in manifest.items() if k != 'external_governance'}) != frozen['manifest_sha256'] or \
            manifest['assembly'].get('execution') != frozen['execution'] or \
            manifest.get('construction') != frozen['main']:
        raise ValueError('currency construction binding differs from original manifest')
    spec = asdict(ExecutionConfig.from_dict(frozen['execution']).spec)
    manifest_ref = 'sha256:' + payload_digest(manifest)
    pending_call = None
    links = []
    for row in rows:
        kind, data = row['kind'], row['payload']
        if kind == 'construction_started':
            identity = data['identity']
            op = _operation(identity['operation'])
            key = op['intent_id']
            binding = frozen['main'] if op['lane'] == 'main' else frozen['controls'].get(op['slot_id'])
            if key in starts or op['phase'] != 'operator' or op['run_id'] != logical_run_id or \
                    op['manifest_sha256'] != manifest_ref or binding is None or \
                    identity['materializer'] != binding['constructor'] or \
                    identity['artifact_backend'] != binding['artifact_backend']:
                raise ValueError('construction operation differs from frozen external binding')
            starts[key] = identity
        elif kind == 'composed_provider_started':
            context = data['invocation'].get('external_context')
            if context is None:
                raise ValueError('v9 currency construction has an unbound provider call')
            if context['phase'] != 'operator':
                continue  # Planning/evaluation retain their separately audited physical contracts.
            key = context['intent_id']
            identity = starts.get(key)
            if identity is None or key in terminals:
                raise ValueError('provider call is outside its construction operation')
            op = identity['operation']
            if context['runtime_id'] != CONSTRUCTION_EXTERNAL_RUNTIME or \
                    context['logical_run_id'] != op['run_id'] or context['lane'] != op['lane'] or \
                    context['slot_id'] != op['slot_id'] or context['physical_fingerprint'] != op['fingerprint']:
                raise ValueError('provider call differs from construction provenance')
            item = {'context': context, 'tokens': None, 'result': None,
                    'prompt': _prompt_request(provider_arguments, context, identity, frozen, spec)}
            calls.setdefault(key, []).append(item)
            if pending_call is not None:
                raise ValueError('overlapping construction provider receipts')
            pending_call = (data['binding'], item)
        elif kind == 'composed_provider_completed' and pending_call is not None:
            if data['binding'] != pending_call[0]:
                raise ValueError('construction provider terminal differs from its original call')
            pending_call[1]['tokens'] = data['tokens']
            pending_call[1]['result'] = data['result']
            pending_call = None
        elif kind == 'construction_outcome':
            key = data['identity']['operation']['intent_id']
            if key not in starts or key in terminals or pending_call is not None:
                raise ValueError('construction terminal has no unique completed operation')
            result = decode_construction_outcome(data, starts[key])
            receipts = calls.get(key, [])
            if any(v['tokens'] is None for v in receipts) or \
                    result.cost.tokens_in != sum(v['tokens'] for v in receipts):
                raise ValueError('construction terminal lost original provider costs')
            if isinstance(result, ConstructionResult):
                value = result.to_dict()
                _validate_prompt_result(value, receipts, spec)
                op = starts[key]['operation']
                session = 'main' if op['lane'] == 'main' else op['slot_id']
                if value['role'] != frozen['roles'][session].get(spec['role']):
                    raise ValueError('construction role differs from its frozen definition')
                if value['spec_ref'] != 'sha256:' + payload_digest(spec) or value['role']['name'] != spec['role'] or \
                        any(v['context']['candidate_id'] != value['candidate']['id'] for v in receipts) or \
                        spec['hypothesis_frozen'] and value['effective_hypothesis'] != value['initial_hypothesis']:
                    raise ValueError('construction result differs from its frozen execution contract')
            terminals[key] = data
        elif kind == 'materialization_completed':
            materialization = Materialization.from_dict(data)
            key = data['identity']['operation']['intent_id']
            expected = {'identity': data['identity'],
                        'outcome': {'kind': 'returned', 'result': data['construction_result']}}
            if key in artifacts or terminals.get(key) != expected:
                raise ValueError('currency artifact lost its original construction terminal')
            artifacts[key] = materialization
            op = data['identity']['operation']
            links.append({'intent_id': key, 'lane': op['lane'], 'slot_id': op['slot_id'],
                'candidate_id': materialization.proposal.candidate.id,
                'materialization_ref': materialization.ref, 'artifact_ref': data['artifact']['reference'],
                'provider_context_refs': ['sha256:' + payload_digest(v['context']) for v in calls.get(key, [])]})
        elif kind == 'governed_evaluation_started':
            identity = data['identity']
            matches = [v for v in artifacts.values() if v.ref == identity.get('materialization_ref')]
            if len(matches) != 1:
                raise ValueError('currency evaluation requires an original published construction')
            op = matches[0].to_dict()['identity']['operation']
            if identity['lane'] != op['lane'] or identity['control_slot'] != op['slot_id']:
                raise ValueError('currency evaluation crosses construction scope')
    return {'schema_version': 1, 'materializations': len(artifacts),
            'provider_calls': sum(len(v) for v in calls.values()), 'artifact_links': links}
