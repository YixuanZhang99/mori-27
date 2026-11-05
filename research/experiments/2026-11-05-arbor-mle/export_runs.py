"""Export Arbor records and independently recompute selection, counts and billed usage.

Does not train programs, call providers, read credentials, or recalculate hidden
label losses. Task losses come from original trusted evaluations; official scores
come from the separate post-selection audit. Only named evidence files are copied.
"""
import argparse
from collections import Counter, defaultdict
import fcntl
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3


def require(condition,message):
    if not condition: raise ValueError(message)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def dump(path,value):
    raw=(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    path.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)


def journal_bytes(path):
    with path.open('rb') as stream:
        fcntl.flock(stream,fcntl.LOCK_SH)
        return stream.read()


def currency(receipts,run_ids):
    seen,tokens,lanes=set(),defaultdict(int),defaultdict(int)
    pending=reserved=0
    for receipt in receipts:
        r,s=receipt['reservation'],receipt['settlement']
        require(r['call_id'] not in seen and r['run_id'] in run_ids,'duplicate or unrelated currency receipt')
        seen.add(r['call_id'])
        if s is None:
            pending+=1;reserved+=r['reserved_micro_cny'];continue
        require(s['call_id']==r['call_id'] and not s['bound_violation'],'invalid settlement')
        usage=s['usage']
        for key in ('prompt_tokens','completion_tokens','total_tokens'):
            require(type(usage[key]) is int and usage[key]>=0,'invalid usage')
            tokens[key]+=usage[key]
        require(usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens'],'invalid token total')
        # Recompute the original campaign's frozen upper prices; not a new budget.
        cost=2*usage['prompt_tokens']+8*usage['completion_tokens']
        require(cost==s['upper_bound_micro_cny'],'currency differs from frozen upper prices')
        lanes[r['lane']]+=cost
    total=sum(lanes.values())
    return {'cost_upper_micro_cny':None if pending else total,'settled_upper_micro_cny':total,
        'pending_calls':pending,'pending_reserved_micro_cny':reserved,'settled_calls':len(receipts)-pending,
        'tokens':dict(tokens),'cost_by_lane_micro_cny':dict(lanes),'invoice_verified':False}


def reconcile_currency(starts, ends, receipts, cost):
    """Bind each charged call or proven pre-dispatch refusal to its invocation."""
    completed = {e['binding']: e for e in ends}
    unmatched = {r['reservation']['call_id']: r for r in receipts}
    known_zero, unresolved = 0, False
    for start in starts:
        invocation = start['invocation']; context = invocation['external_context']
        require(start['binding'] == digest({'request_sha256': start['request_sha256'], 'invocation': invocation})[7:],
                'provider invocation binding differs')
        matches = [call for call, receipt in unmatched.items() if call == digest({'schema_version': 1,
            'context': context, 'wire_request_sha256': receipt['reservation']['request_sha256']})[7:]]
        require(len(matches) <= 1, 'multiple currency receipts for one invocation')
        end = completed.get(start['binding'])
        if matches:
            receipt = unmatched.pop(matches[0]); r, settlement = receipt['reservation'], receipt['settlement']
            require(r['run_id'] == context['currency_run_id'] and r['lane'] == context['lane']
                and r['slot_id'] == context['slot_id'] and r['phase'] == context['phase'], 'currency lane or phase differs')
            if end is not None and settlement is not None:
                require(end['tokens'] == settlement['usage']['total_tokens'], 'provider tokens differ from currency receipt')
            if end is None or settlement is None: unresolved = True
        elif end is None:
            unresolved = True
        else:
            require(end.get('outcome') == 'budget_exhausted' and type(end.get('tokens')) is int
                and end['tokens'] == 0 and type(end.get('result')) is str, 'provider completion lacks currency or a known zero refusal')
            known_zero += 1
    require(not unmatched, 'currency receipt lacks matching provider invocation')
    cost['known_zero_refusals'] = known_zero
    if unresolved: cost['cost_upper_micro_cny'] = None


def score(result,manifest,split):
    binding=result['contract']['binding']
    require(binding['split_id']==split and binding['seed_set']==[manifest['split_seed']] and
        binding['evaluation_context']==manifest['dataset_manifest']['split_contexts'][split],
        'evaluation split, context or seed differs')
    if result['status']!='ok':return None
    value=result['metrics']['dev/score' if split=='dev' else 'gate/score']
    require(type(value) in (int,float) and math.isfinite(value) and value<=0,'invalid signed task loss')
    return -value


STAGES = {'observe': 'arbor_observed', 'ideate': 'arbor_ideas_proposed', 'select': 'arbor_selected',
    'dispatch': 'arbor_dispatched', 'backpropagate': 'arbor_backpropagated', 'admission': 'arbor_admission_verdict'}


def digest(value):
    return 'sha256:' + sha(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode())


def controller_rows(rows):
    """Only the main admission component owns controller state in governed runs."""
    result = []
    for row in rows:
        if row['kind'] == 'governed_component':
            p = row['payload']
            if (p.get('lane'), p.get('slot_id'), p.get('component')) == ('main', None, 'admission'):
                result.append({'kind': p['kind'], 'payload': p['payload']})
        elif row['kind'] in ('layered_admission_state', 'layered_admission_receipt'):
            result.append(row)
    return result


def frozen_selection(rows):
    return [r['payload'] for r in controller_rows(rows)
        if r['kind'] == 'layered_admission_state' and r['payload']['event'] == 'selection_frozen']


def layered_selection(manifest, rows, dev, programs):
    """Recompute the fixed CSV protocol, without importing the runtime controller.

    Original losses remain evaluator evidence. Compare receipt projections to that
    evidence before applying strict development and held-out admission rules.
    """
    options = manifest['profile']['admission']['options']
    margin = options.get('margin', 0)
    minimum = options.get('trigger', {}).get('min_dev_gain', 0)
    rules = {'metric': 'gate/score', 'direction': 'maximize', 'dev_metric': 'dev/score',
        'dev_direction': 'maximize', 'margin': margin, 'min_dev_gain': minimum, 'monotonicity': True}
    control = controller_rows(rows)
    states = [r['payload'] for r in control if r['kind'] == 'layered_admission_state']
    calls = states[-1]['state']['calls'] if states else {}
    gate_calls = {k:v for k,v in calls.items() if v['phase'] == 'admission'}
    require(len(gate_calls) <= options['call_budget'], 'admission budget exceeded')
    gates, finals = {}, []
    for row in rows:
        if row['kind'] != 'layered_evidence': continue
        p = row['payload']; r = p['evidence']['evidence']['eval_result']
        b = r['contract']['binding']; identifier = b['candidate_id']
        require(identifier in dev and b['artifact_sha256'] == sha(programs[identifier].encode()),
                'held-out evaluation differs from original artifact')
        score(r, manifest, p['phase'])
        if r['status'] == 'ok':
            require(r['contract']['private']['data']['prediction_sha256'] ==
                dev[identifier]['contract']['private']['data']['prediction_sha256'], 'held-out evaluation replaced predictions')
        if p['phase'] == 'admission':
            require(identifier not in gates and p['key'] in gate_calls and
                gate_calls[p['key']]['binding'] == b, 'gate evidence lacks unique original call')
            gates[identifier] = r
        elif p['phase'] == 'final_audit': finals.append(p)
        else: raise ValueError('unexpected held-out phase')

    def same_view(view, result, identifier):
        if result is None:
            require(view is None, 'unexpected incumbent evidence'); return
        require(view is not None and view['candidate_id'] == identifier, 'receipt candidate differs')
        actual = view['eval_result']
        require(actual['binding'] == result['contract']['binding'] and actual['status'] == result['status']
            and actual['metrics'] == result['metrics'], 'receipt differs from original evaluation')

    selected = None
    decisions = []
    receipts = [r['payload'] for r in control if r['kind'] == 'layered_admission_receipt']
    seen = set()
    for receipt in receipts:
        c = receipt['decision_context']; identifier = c['candidate_id']
        require(identifier in dev and identifier not in seen and c['incumbent_id'] == selected,
                'receipt uses unknown, duplicate or stale candidate')
        seen.add(identifier)
        require(receipt['receipt_id'] == digest(c) and c['rules'] == rules
            and c['decision'] == {'admit': receipt['admit'], 'reason': receipt['reason']}, 'invalid decision receipt')
        same_view(c['development']['candidate'], dev[identifier], identifier)
        same_view(c['development']['incumbent'], dev.get(selected), selected)
        for role, ident in [('candidate', identifier), ('incumbent', selected)]:
            view = c['admission'][role]
            if view is not None: same_view(view, gates.get(ident), ident)
        gain = (dev[identifier]['metrics'].get('dev/score', 0) - dev[selected]['metrics']['dev/score']) if selected else None
        eligible = dev[identifier]['status'] == 'ok' and (selected is None or gain > 0 and gain >= minimum)
        accepted = False
        if c['admission_rule_evaluated']:
            require(eligible and c['development_trigger_passed'], 'gate bypassed development trigger')
            same_view(c['admission']['candidate'], gates.get(identifier), identifier)
            require(identifier in gates, 'evaluated decision lacks actual gate evidence')
            if selected:
                same_view(c['admission']['incumbent'], gates.get(selected), selected)
                require(selected in gates, 'incumbent lacks actual gate evidence')
            candidate = gates[identifier]
            accepted = candidate['status'] == 'ok' and (selected is None or gates[selected]['status'] == 'ok' and
                candidate['metrics']['gate/score'] - gates[selected]['metrics']['gate/score'] > margin)
        require(type(receipt['admit']) is bool and receipt['admit'] == accepted, 'admission differs from original held-out scores')
        if accepted: selected = identifier
        decisions.append({'candidate_id': identifier, 'admit': accepted, 'receipt_id': receipt['receipt_id']})
    verdicts = [r['payload'] for r in rows if r['kind'] == 'arbor_admission_verdict']
    require(verdicts == decisions[:len(verdicts)], 'planner verdicts differ from original receipts')
    require(len(verdicts) <= len(decisions), 'extra planner verdict')
    frozen = frozen_selection(rows)
    require(len(frozen) <= 1 and len(finals) <= 1, 'multiple final freezes or evaluations')
    final_loss, final_state = None, 'not_frozen'
    if frozen:
        f = frozen[0]['state']['final']
        require(f['selected_id'] == selected, 'frozen selection differs from admitted trunk')
        terminal = states[-1]['state']['final']
        require(terminal['selected_id'] == selected and terminal['key'] == f['key'], 'final identity changed after freeze')
        final_state = terminal['status']
        require((selected is None) == (f['key'] is None), 'null selection with final call')
        if finals:
            final = finals[0]; result = final['evidence']['evidence']['eval_result']
            require(final['key'] == f['key'] and result['contract']['binding']['candidate_id'] == selected,
                    'final evaluated another candidate')
            freeze_pos = next(i for i,r in enumerate(rows) if r['payload'] == frozen[0] or
                r['kind'] == 'governed_component' and r['payload'].get('payload') == frozen[0])
            final_pos = next(i for i,r in enumerate(rows) if r['kind'] == 'layered_evidence' and r['payload'] == final)
            require(freeze_pos < final_pos and final_state == 'complete', 'final missing prior freeze or completion')
            final_loss = score(result, manifest, 'final_audit')
        elif final_state == 'complete': raise ValueError('completed final lacks original evidence')
    else: require(not finals, 'final without frozen selection')
    return {'gate_selected_id': selected, 'gate_calls': len(gate_calls),
        'gate_pending_calls': sum(v['status'] == 'pending' for v in gate_calls.values()),
        'admission_decisions': decisions, 'final_state': final_state, 'final_loss': final_loss}


def verify_insights(rows, dev, evaluations):
    """Audit source closure against original dev records, including failed batches."""
    bindings, syntheses = {}, {}
    cycles = {e['candidate_id']: e['cycle'] for e in evaluations}
    cycles.update({r['payload']['candidate_id']: r['payload']['cycle'] for r in rows if r['kind'] == 'arbor_selected'})
    original_refs = {r['payload'].get('evidence_ref'): r['payload']['evidence']['candidate_id']
        for r in rows if r['kind'] == 'composed_evidence' and r['payload'].get('evidence_ref')}
    physical = {r['payload']['evidence']['evidence']['candidate_id']: r['payload']['evidence'] for r in rows
        if r['kind'] == 'composed_physical_evidence' and r['payload']['request']['split_id'] == 'dev'}
    original_refs.update({r['payload']['evidence_ref']: r['payload']['proposal']['candidate']['id']
        for r in rows if r['kind'] == 'arbor_construction_failed'})
    def same_development(item, identifier):
        original = dev[identifier]; actual = item['eval_result']
        require(item['candidate_id'] == identifier and actual['status'] == original['status'] and
            actual['metrics'] == original['metrics'] and actual['contract']['binding'] == original['contract']['binding'],
            'synthesis replaced original public development evidence')
    for row in rows:
        if row['kind'] == 'governed_component':
            p = row['payload']
            if (p.get('lane'), p.get('slot_id'), p.get('component')) != ('main', None, 'memory'): continue
            row = p
        kind, p = row['kind'], row['payload']
        if kind in ('memory_receipt_binding', 'memory_tree_receipt_binding'):
            b = {k:v for k,v in p.items() if k != 'receipt_ref'}; ref = p['receipt_ref']
            require(ref not in bindings, 'repeated memory source binding')
            identifier = b['candidate_id']
            require(identifier in dev and b['cycle'] == cycles[identifier] and
                b['evaluation_context'] == dev[identifier]['contract']['binding']['evaluation_context'], 'memory lacks original dev context')
            if kind == 'memory_receipt_binding':
                require((original_refs.get(ref) == identifier or identifier in physical and ref == digest({
                    'logical_run_id': b['context']['run_id'], 'evidence': physical[identifier]})) and
                    b['role'] == 'dev' and b['status'] == dev[identifier]['status'], 'non-development source in research memory')
            else:
                require(ref == digest(b) and b['synthesis_ref'] in syntheses, 'aggregate lacks original synthesis')
                event = syntheses[b['synthesis_ref']]; request = event['request']
                require(all(b[k] == request[k] for k in ('candidate_id', 'cycle', 'target_id', 'source_refs', 'previous_ref'))
                    and b['body'] == {'target_id': b['target_id'], 'source_refs': b['source_refs'], 'summary': event['response']['summary']},
                    'aggregate differs from original synthesis')
                require(all(bindings[s]['context'] == b['context'] for s in b['source_refs']), 'aggregate crosses runs')
                trust = 'ungated' if any(bindings[s]['status'] != 'ok' for s in b['source_refs']) else 'gated'
                require(b['role'] == 'tree_insight' and b['trust'] == trust, 'aggregate trust exceeds sources')
            bindings[ref] = b
        elif kind == 'arbor_synthesis':
            request = p['request']; identifier = request['candidate_id']; sources = request['source_refs']
            require(p['synthesis_ref'] == digest({'request': request, 'response': p['response']}) and
                p['synthesis_ref'] not in syntheses, 'synthesis hash differs or repeats')
            require(identifier in dev and request['cycle'] == cycles[identifier] and sources and sources == sorted(set(sources))
                and all(s in bindings and bindings[s]['role'] == 'dev' and bindings[s]['cycle'] <= request['cycle'] for s in sources),
                'synthesis contains foreign or non-development sources')
            require(any(bindings[s]['candidate_id'] == identifier for s in sources), 'synthesis omits current evidence')
            same_development(request['new_evidence'], identifier)
            previous = request['previous_ref']
            if previous is not None:
                old = bindings.get(previous, {})
                require(old.get('role') == 'tree_insight' and old['target_id'] == request['target_id'] and
                    old['cycle'] < request['cycle'] and set(old['source_refs']) <= set(sources) and
                    request['previous_summary'] == old['body']['summary'], 'synthesis loses or replaces earlier sources')
            syntheses[p['synthesis_ref']] = p
    return [dict(receipt_ref=ref, **binding) for ref,binding in bindings.items() if binding['role'] == 'tree_insight']


def summarize(manifest,rows,receipts,report,official):
    def events(kind):return [r['payload'] for r in rows if r['kind']==kind]
    programs,evaluations={},[]
    dev_results={}
    for payload in events('composed_evidence'):
        proposal=payload['proposal'];candidate=proposal['candidate'];identifier=candidate['id']
        evidence=payload['evidence'];result=evidence['eval_result'];binding=result['contract']['binding']
        require(identifier not in programs and identifier==evidence['candidate_id']==binding['candidate_id'],
                'duplicate or mismatched candidate')
        require(sha(proposal['artifact'].encode())==binding['artifact_sha256'],'artifact differs from original evaluation')
        loss=score(result,manifest,'dev')
        programs[identifier]=proposal['artifact'];dev_results[identifier]=result
        evaluations.append({'candidate_id':identifier,'cycle':payload['cycle'],'operator':candidate['operator'],
            'parents':candidate['parents'],'status':result['status'],'validation_loss':loss})
    cycles=[e['cycle'] for e in evaluations]
    require(cycles==sorted(set(cycles)),'duplicate or unordered main cycles')
    valid=[e for e in evaluations if e['status']=='ok']
    best=min(valid,key=lambda e:e['validation_loss']) if valid else None
    attempted=len(events('composed_cycle_started'));incomplete=attempted-len(evaluations)
    require(incomplete>=0,'too many terminal evaluations')
    counts={'attempted':attempted,'successful':len(valid),'failed':len(evaluations)-len(valid),
        'incomplete':incomplete,'failure_rate':(attempted-len(valid))/attempted if attempted else None}
    # A failed synthesis can follow real training but precede the atomic cycle
    # commit. Retain that evidence without converting an incomplete attempt into
    # a successful search node. Main cycle and artifact identities are original.
    committed_ids = set(dev_results)
    selected_cycles = {r['payload']['cycle']: r['payload']['candidate_id'] for r in rows if r['kind'] == 'arbor_selected'}
    materialized = {}
    for p in events('materialization_completed'):
        op = p['identity']['operation']
        if op['lane'] == 'main' and op['cycle'] in selected_cycles:
            materialized[selected_cycles[op['cycle']]] = p['construction_result']['artifact']
    for p in events('composed_physical_evidence'):
        if p['request']['split_id'] != 'dev': continue
        result = p['evidence']['evidence']['eval_result']; identifier = result['contract']['binding']['candidate_id']
        if identifier in committed_ids or identifier not in selected_cycles.values(): continue
        require(identifier in materialized and sha(materialized[identifier].encode()) == result['contract']['binding']['artifact_sha256'],
                'uncommitted training lacks original materialized artifact')
        score(result, manifest, 'dev')
        require(identifier not in dev_results or dev_results[identifier] == result, 'conflicting uncommitted evaluation')
        dev_results[identifier] = result; programs[identifier] = materialized[identifier]
    construction_failures = set()
    outcomes = {digest(p): p for p in events('construction_outcome')}
    for p in events('arbor_construction_failed'):
        identifier = p['proposal']['candidate']['id']; result = p['evidence']['evidence']['eval_result']
        original = outcomes.get(p['construction_outcome_ref'])
        require(original is not None, 'construction failure lacks original outcome')
        op, outcome = original['identity']['operation'], original['outcome']
        require(op['lane'] == 'main' and op['cycle'] == p['cycle'] and op['run_id'] == p['logical_run_id']
            and selected_cycles.get(p['cycle']) == identifier and outcome['kind'] == 'failed'
            and outcome['failure_type'] == 'OperatorFailure', 'construction failure identity differs')
        require(p['evidence_ref'] == digest({'logical_run_id': p['logical_run_id'], 'evidence': p['evidence']})
            and p['evidence']['evidence']['candidate_id'] == identifier
            and p['proposal']['artifact'] == '' and result['status'] == 'failed_to_run' and result['metrics'] == {}
            and result['text_feedback'] == outcome['detail'] and result['contract']['binding']['candidate_id'] == identifier
            and result['contract']['binding']['artifact_sha256'] == sha(b''), 'construction failure evidence changed')
        score(result, manifest, 'dev')
        require(identifier not in construction_failures and (identifier not in dev_results or dev_results[identifier] == result),
                'duplicate or conflicting construction failure')
        construction_failures.add(identifier)
        dev_results[identifier] = result; programs[identifier] = ''
    aggregate_sources = verify_insights(rows, dev_results, evaluations)
    layered = layered_selection(manifest, rows, dev_results, programs)
    winner = layered['gate_selected_id']
    final_loss, final_state = layered['final_loss'], layered['final_state']
    controls=[]
    for c in events('governed_control_terminal'):
        value={'state':c['status'],'validation_loss':None}
        if c.get('evidence'):
            result=c['evidence']['evidence']['eval_result']
            value.update(evaluation_status=result['status'],validation_loss=score(result,manifest,'dev'))
        controls.append(value)
    starts,ends=events('composed_provider_started'),events('composed_provider_completed')
    started={r['binding'] for r in starts};ended={r['binding'] for r in ends}
    require(len(started)==len(starts) and len(ended)==len(ends) and ended<=started,'invalid provider event coverage')
    run_ids={(r.get('invocation',{}).get('external_context') or {}).get('currency_run_id') for r in starts}-{None}
    cost=currency(receipts,run_ids)
    if manifest['mode']=='live':
        require(manifest['source']['commit'] and manifest['source']['dirty'] is False,'live source not clean')
        reconcile_currency(starts, ends, receipts, cost)
    submission=None
    if report is not None:
        for key in ('source','task_id','search_seed','split_seed','dataset_identity','dataset_manifest','mode'):
            require(report[key]==manifest[key],'report manifest mismatch: '+key)
        require(report['search']==counts,'reported failure denominator differs')
        if report.get('result'):
            require(report['result']['best_candidate_id']==winner,'reported winner differs')
        require(report['final_score']==(-final_loss if final_loss is not None else None),'reported final score differs')
        if report.get('independent_currency_receipts'):
            require(report['independent_currency_receipts']['total_tokens']==cost['tokens'].get('total_tokens',0) and
                report['independent_currency_receipts']['settled_micro_cny']==cost['settled_upper_micro_cny'],
                'report currency differs from original receipts')
        require(report['stage_trace']=={stage:events(event) for stage,event in STAGES.items()}, 'reported stages differ')
        submission=report.get('submission')
        if submission:
            require(winner is not None and submission['candidate_id']==winner and submission['artifact_sha256']==
                sha(programs[winner].encode()),'submission selects another artifact')
            require(submission['prediction_sha256']==dev_results[winner]['contract']['private']['data']['prediction_sha256'],
                    'submission prediction binding differs')
    official_score=None;official_state='not_graded'
    if official:
        require(submission is not None and official['binding']['selection']==submission,'official score selects another submission')
        require(official['binding']['task_id']==manifest['task_id'],'official task differs')
        official_state=official['state'];official_score=official['official_score']
        if official_score is not None:
            require(type(official_score) in (int,float) and math.isfinite(official_score),'invalid official score')
    summary={'task_id':manifest['task_id'],'search_seed':manifest['search_seed'],'split_seed':manifest['split_seed'],
        'mode':manifest['mode'],'source':manifest['source'],'dataset_identity':manifest['dataset_identity'],
        'scoring':manifest['dataset_manifest']['scoring'],'run_state':report['run_state'] if report else 'report_missing',
        'uncommitted_development_ids':sorted(set(dev_results)-committed_ids-construction_failures),
        'uncommitted_construction_failures':sorted(construction_failures-committed_ids),
        'search':counts,'best_development':best,'final_state':final_state,'final_loss':final_loss,
        'official_state':official_state,'official_score':official_score,'submission':submission,
        'independent_initial_controls':controls,'evaluations':evaluations,
        'tree_choices':events('arbor_selected'), **layered,
        'stage_trace':{stage:events(event) for stage,event in STAGES.items()},
        'aggregate_sources':aggregate_sources, 'hypothesis_proposals':events('arbor_ideas_proposed'), 'insight_syntheses':events('arbor_synthesis'),'currency':cost,'provider_attempts':len(starts),
        'provider_completed':len(ends),'unresolved_provider_bindings':sorted(started-ended),
        'replay_passed':report.get('replay_certificate',{}).get('passed') if report and report.get('replay_certificate') else None,
        'wall_seconds_this_process':report.get('wall_seconds_this_process') if report else None,
        'deviations':report.get('deviations') if report else None,'event_counts':dict(Counter(r['kind'] for r in rows))}
    return summary,programs


def matrix_summary(plan,summaries):
    cells=plan['cells'];expected={c['output'] for c in cells}
    require(len(expected)==len(cells) and set(summaries)<=expected,'unexpected or duplicate matrix cell')
    runs=[{**cell,**summaries[cell['output']]} if cell['output'] in summaries else
        dict(cell,run_state='not_run',official_score=None,final_loss=None) for cell in cells]
    return {'scope':'Adapted Arbor CSV pilot; not paper-budget reproduction or a medal-rate estimate',
        'declared_cells':len(cells),'runs':runs,
        'audit_scope':'Selection, denominators and currency recalculated from original records; losses originate in trusted evaluations. No hidden labels redistributed.'}


def validate_cell(manifest,plan,cell):
    require(all(manifest[k]==cell[k] for k in ('task_id','search_seed','split_seed')),
            'run task or seeds differ from declared cell')
    require(manifest['source']==plan['source'] and manifest['profile']==plan['profiles'][cell['output']] and
            manifest['dataset_identity']==plan['datasets'][cell['task_id']]['identity'],
            'run differs from predeclared protocol')
    relative=Path(cell['output'])
    require(not relative.is_absolute() and '..' not in relative.parts,'invalid cell path')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--matrix',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args(argv)
    plan=read(args.matrix/'matrix-manifest.json')
    with sqlite3.connect(args.ledger.resolve().as_uri()+'?mode=ro',uri=True) as db:
        currency_rows=[json.loads(r[0]) for r in db.execute('select payload from events order by seq')]
    settlements={r['call_id']:r for r in currency_rows if r['kind']=='governed_settle'}
    args.output.mkdir(parents=True,exist_ok=False)
    summaries={};seen_calls=set()
    for cell in plan['cells']:
        root=args.matrix/cell['output']
        if not (root/'run-manifest.json').is_file():continue
        manifest=read(root/'run-manifest.json')
        validate_cell(manifest,plan,cell)
        raw=journal_bytes(root/'composed/x1.jsonl');rows=[json.loads(l) for l in raw.splitlines()]
        ids={(r['payload'].get('invocation',{}).get('external_context') or {}).get('currency_run_id') for r in rows
             if r['kind']=='composed_provider_started'}-{None}
        receipts=[{'reservation':r,'settlement':settlements.get(r['call_id'])} for r in currency_rows
                  if r['kind']=='governed_reserve' and r['run_id'] in ids]
        call_ids={r['reservation']['call_id'] for r in receipts}
        require(not seen_calls & call_ids,'currency calls attributed to multiple cells');seen_calls|=call_ids
        report=read(root/'method-report.json') if (root/'method-report.json').is_file() else None
        official=read(root/'official/result.json') if (root/'official/result.json').is_file() else None
        summary,programs=summarize(manifest,rows,receipts,report,official)
        dest=args.output/cell['output'];dest.mkdir(parents=True)
        (dest/'run-manifest.json').write_bytes((root/'run-manifest.json').read_bytes())
        dump(dest/'currency-receipts.json.gz',receipts)
        if report is not None:
            report_raw=(root/'method-report.json').read_bytes()
            (dest/'method-report.json.gz').write_bytes(gzip.compress(report_raw,mtime=0))
            summary['source_report_sha256']=sha(report_raw)
        else:
            dump(dest/'method-report.json.gz',None)
            summary['source_report_sha256']=None
        summary['source_journal_sha256']=sha(raw)
        dump(dest/'official-result.json',official)
        dump(dest/'summary.json',summary);dump(dest/'programs.json.gz',programs)
        (dest/'x1.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
        if summary['submission']:
            submission=(root/'submission.csv').read_bytes()
            require('sha256:'+sha(submission)==summary['submission']['submission_sha256'],'submission bytes differ')
            (dest/'submission.csv').write_bytes(submission)
            (dest/'selected-program.py').write_text(programs[summary['submission']['candidate_id']])
        if (root/'official/audit.jsonl').is_file():
            (dest/'official-audit.jsonl.gz').write_bytes(gzip.compress(journal_bytes(root/'official/audit.jsonl'),mtime=0))
        summaries[cell['output']]=summary
    (args.output/'matrix-manifest.json').write_bytes((args.matrix/'matrix-manifest.json').read_bytes())
    (args.output/'official-prepared-identity.json').write_bytes((args.matrix/'official-prepared-identity.json').read_bytes())
    dump(args.output/'summary.json',matrix_summary(plan,summaries))
    print(json.dumps({'declared_cells':len(plan['cells']),'exported_cells':len(summaries)}))


if __name__=='__main__':main()
