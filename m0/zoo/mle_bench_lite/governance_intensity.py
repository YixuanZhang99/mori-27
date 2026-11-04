"""Report planned and observed resident-control timing from audited events."""
from core.x1.checkpoint import payload_digest


def control_timing(plan, planned_cycles, rows, *, logical_run_id):
    """Project timing only; callers must independently authenticate the journal."""
    try:
        if type(plan) is not dict or type(plan['slots']) is not list or \
                type(planned_cycles) is not list or not planned_cycles or \
                any(type(value) is not int or value < 0 for value in planned_cycles) or \
                planned_cycles != sorted(set(planned_cycles)) or planned_cycles[0] != 0 or \
                type(rows) is not list or type(logical_run_id) is not str or not logical_run_id or \
                len(plan['slots']) != len(planned_cycles):
            raise ValueError('control timing evidence is incomplete')
        starts, committed, stopped = [], 0, None
        cycle_starts, evidence, decisions = set(), {}, {}
        for row in rows:
            kind, data = row['kind'], row['payload']
            if kind == 'composed_cycle_started':
                cycle = data['cycle']
                if type(cycle) is not int or cycle != committed:
                    raise ValueError('control timing cycle start differs')
                cycle_starts.add(cycle)
            elif kind == 'composed_evidence':
                cycle = data['cycle']
                if type(cycle) is not int or cycle != committed or cycle in evidence or cycle not in cycle_starts:
                    raise ValueError('control timing cycle evidence differs')
                candidate = data['proposal']['candidate']['id']
                expected_ref = 'sha256:' + payload_digest({'logical_run_id': logical_run_id,
                    'evidence': {'schema_version': 1, 'evidence': data['evidence']}})
                if data['evidence']['candidate_id'] != candidate or data['evidence_ref'] != expected_ref:
                    raise ValueError('control timing cycle evidence identity differs')
                evidence[cycle] = (candidate, data['evidence'])
            elif kind == 'composed_decision':
                candidate = data['candidate_id']
                original = {key: data[key] for key in ('candidate_id', 'incumbent', 'evidence', 'decision')}
                if committed not in evidence or evidence[committed] != (candidate, data['evidence']) or \
                        candidate in decisions or data['event_id'] != 'sha256:' + payload_digest(original):
                    raise ValueError('control timing decision identity differs')
                decisions[candidate] = data['evidence']
            elif kind == 'composed_checkpoint':
                count = data['next_cycle']
                if type(count) is not int or not committed <= count <= committed + 1:
                    raise ValueError('control timing checkpoint order differs')
                if count != committed:
                    if committed not in evidence:
                        raise ValueError('control timing checkpoint lacks cycle evidence')
                    candidate, measured = evidence[committed]
                    if decisions.get(candidate) != measured:
                        raise ValueError('control timing checkpoint lacks matching decision')
                    stopped = None
                committed = count
            elif kind == 'governed_main_stopped':
                if type(data.get('main_cycles')) is not int or data['main_cycles'] != committed or \
                        data.get('disposition') not in {'ordinary', 'integrity'}:
                    raise ValueError('control timing stop differs from committed cycles')
                stopped = data['disposition']
            elif kind == 'governed_control_started':
                if data.get('main_cycles') != committed:
                    raise ValueError('control timing differs from committed cycles')
                starts.append((data, stopped))
        if len(starts) != len(planned_cycles):
            raise ValueError('control timing evidence is incomplete')
        result, previous = [], -1
        for index, (cycle, slot, observed) in enumerate(zip(planned_cycles, plan['slots'], starts)):
            start, stop_disposition = observed
            slot_id = f'control-{index:04d}'
            if type(cycle) is not int or cycle < 0 or type(slot) is not dict or type(start) is not dict or \
                    slot.get('slot_id') != slot_id or slot.get('after_main_cycles') != cycle or \
                    start.get('slot_id') != slot_id or start.get('plan_ref') != plan['plan_ref'] or \
                    type(start.get('main_cycles')) is not int or not previous <= start['main_cycles'] <= cycle or \
                    (start['main_cycles'] < cycle and stop_disposition != 'ordinary') or \
                    stop_disposition == 'integrity':
                raise ValueError('control timing differs from the frozen plan')
            actual = start['main_cycles']
            result.append({'slot_id': slot_id, 'planned_after_main_cycles': cycle,
                           'actual_after_main_cycles': actual, 'drained_early': actual < cycle})
            previous = actual
        return {'slots': result, 'all_on_schedule': not any(row['drained_early'] for row in result)}
    except (KeyError, TypeError) as error:
        raise ValueError('invalid control timing evidence') from error
