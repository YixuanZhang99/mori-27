"""One-at-a-time host admission using the existing durable physical budget.

This primitive does not bind a currency bridge or enable live reference runs.
"""
from __future__ import annotations

import re
import hashlib
import json
import math

from core.composition.budget import HierarchicalBudget
from core.composition.provider_evidence import evidence_reference, invocation_records
from core.executor.types import Candidate
from core.x1.checkpoint import payload_digest
from zoo.circle_packing.stage import EVALUATOR_SHA256, run_stage
from zoo.circle_packing.geometry import validate_geometry


def _validate_stage_result(result, *, stage, program_ref):
    if type(result) is not dict or result.get('stage') != stage or result.get('program_ref') != program_ref or \
            result.get('evaluator_ref') != 'sha256:' + EVALUATOR_SHA256 or \
            result.get('status') not in {'ok', 'timeout', 'failed_to_run'} or \
            type(result.get('wall_seconds')) not in (int, float) or \
            not math.isfinite(result['wall_seconds']) or result['wall_seconds'] < 0:
        raise ValueError('stage outcome lacks measured physical identity')
    if result['status'] == 'ok':
        try:
            geometry = result['geometry']
            encoded = json.dumps(geometry, sort_keys=True, ensure_ascii=False,
                                 separators=(',', ':'), allow_nan=False).encode()
            if result['metrics'] != validate_geometry(geometry) or \
                    result['geometry_ref'] != 'sha256:' + hashlib.sha256(encoded).hexdigest():
                raise ValueError('stage geometry differs from measured metrics')
        except (KeyError, TypeError) as error:
            raise ValueError('stage outcome lacks verified geometry') from error


class HostPhysicalAdmission:
    def __init__(self, budget, *, control_authority=None):
        if not isinstance(budget, HierarchicalBudget) or budget._governed is None or \
                set(budget.units) != {'token', 'node', 'eval_count'}:
            raise ValueError('host requires governed token/node/evaluation physical budget')
        if not budget.audit_governance().get('plan_ref'):
            raise ValueError('host requires protected controls before admission')
        if budget._require_initial_control:
            from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
            if type(control_authority) is not HostDispatchCoordinator or control_authority.budget is not budget:
                raise ValueError('host physical admission requires its control authority')
        self.budget, self.control_authority = budget, control_authority
        self._lock = budget._lock

    def begin(self, request_id):
        with self._lock:
            return self._begin(request_id)

    def _begin(self, request_id):
        self.budget._check_config()
        if self.budget._require_initial_control:
            self.control_authority._require_control()
        if type(request_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            raise ValueError('host request requires a canonical identity')
        if self.budget.state()['open_intents']:
            raise ValueError('unresolved physical operation blocks host dispatch')
        self.budget.pre_call_check()
        candidate = Candidate('host-' + request_id)
        receipt = self.budget.reserve_operation('host:' + request_id, candidate, 'host', 'operator')
        if not receipt.granted:
            raise ValueError('host physical budget refused admission')
        self.budget.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
        return receipt

    def settle(self, receipt, *, tokens):
        with self._lock:
            self._settle(receipt, tokens=tokens)

    def _settle(self, receipt, *, tokens):
        if type(tokens) is not int or tokens < 0:
            raise ValueError('settlement requires measured nonnegative tokens')
        identity = self.budget.invocation_identity(receipt.intent_id, fingerprint=receipt.fingerprint)
        rows = invocation_records(self.budget.store).get(receipt.intent_id, [])
        if len(rows) != 2 or [row['kind'] for row in rows] != [
                'composed_provider_started', 'composed_provider_completed']:
            raise ValueError('settlement requires the original completed provider receipt')
        start, done = (row['payload'] for row in rows)
        invocation = start['invocation']
        context = invocation.get('external_context')
        if invocation.get('schema_version') != 2 or type(context) is not dict or \
                invocation['fingerprint'] != receipt.fingerprint or invocation['lane'] != 'main' or \
                invocation['ordinal'] != 0 or context['candidate_id'] != identity['candidate_id'] or \
                context['account'] != identity['account'] or context['operation'] != 'operator' or \
                done['tokens'] != tokens or done['observed_binding_sha256'] != invocation['adapter_binding_sha256']:
            raise ValueError('provider receipt differs from the physical reservation')
        self.budget.settle_operation(receipt.intent_id, {'token': tokens, 'node': 1, 'eval_count': 0},
            measured_units=self.budget.units, fingerprint=receipt.fingerprint,
            provider_evidence_ref=evidence_reference(self.budget.store, receipt.intent_id))


class HostStageAdmission:
    """Charge real reference evaluator stages to the existing physical journal.

    The authoritative dispatcher owns this component. It is not a complete
    host runner, stage-result exporter or wall-clock controller.
    """
    def __init__(self, budget, *, runner, workspace, control_authority=None):
        from pathlib import Path
        if not isinstance(budget, HierarchicalBudget) or budget._governed is None or \
                set(budget.units) != {'token', 'node', 'eval_count'} or \
                not budget.audit_governance().get('plan_ref'):
            raise ValueError('stage evaluation requires governed protected physical budget')
        if budget._require_initial_control:
            from zoo.circle_packing.host_dispatch import HostDispatchCoordinator
            if type(control_authority) is not HostDispatchCoordinator or control_authority.budget is not budget:
                raise ValueError('stage requires its original control authority and budget')
        self.budget, self.runner, self.workspace = budget, runner, Path(workspace)
        self.control_authority = control_authority
        self._lock = budget._lock

    def _require_control(self):
        self.budget._check_config()
        if self.budget._require_initial_control:
            from zoo.mle_bench_lite.composed_domain import SandboxRunner
            control = self.control_authority.control_domain
            main_path, control_path = self.workspace.resolve(), control.workspace.resolve()
            if type(self.runner) is not SandboxRunner or self.runner is control.runner or \
                    self.runner.manifest_binding != control.runner.manifest_binding or \
                    main_path == control_path or main_path in control_path.parents or control_path in main_path.parents:
                raise ValueError('main stage sandbox differs from frozen independent control')
            self.control_authority._require_control()

    def audit(self):
        """Join original stage records to the physical journal and geometry."""
        from core.composition.budget import JOURNAL_KIND
        with self._lock:
            self._require_control()
            operations = self.budget._rebuild()[0]['operations']
            provider_records = invocation_records(self.budget.store)
            rows = list(self.budget.store.read())
            starts, completed, positions = {}, {}, {}
            for index, row in enumerate(rows):
                payload = row['payload']
                if row['kind'] == JOURNAL_KIND and payload.get('event') in {'start', 'settle'}:
                    key = (payload['event'], payload['data']['intent_id'])
                    if key in positions:
                        raise ValueError('duplicate physical stage transition')
                    positions[key] = index
                elif row['kind'] == 'host_stage_started':
                    request_id = payload.get('request_id')
                    if request_id in starts or set(payload) != {'request_id', 'stage', 'prior_id', 'program_ref',
                                                                  'intent_id', 'fingerprint'}:
                        raise ValueError('duplicate or invalid stage start')
                    starts[request_id] = (index, payload)
                elif row['kind'] == 'host_stage_completed':
                    request_id = payload.get('request_id')
                    if request_id in completed or set(payload) != {'request_id', 'fingerprint', 'result', 'result_ref', 'evidence_ref'}:
                        raise ValueError('duplicate or invalid stage terminal')
                    completed[request_id] = (index, payload)
            if set(starts) != set(completed):
                raise ValueError('stage evidence has an unresolved operation')
            physical_ids = {key for key in operations if key.startswith('host-stage:')}
            if physical_ids != {'host-stage:' + key for key in starts}:
                raise ValueError('physical stage and evidence coverage differ')
            used = set()
            for key, (start_index, start) in starts.items():
                terminal_index, terminal = completed[key]
                result, intent_id = terminal['result'], start['intent_id']
                operation = operations.get(intent_id)
                if type(key) is not str or not re.fullmatch(r'[0-9a-f]{32}', key) or \
                        type(start['stage']) is not int or start['stage'] not in (1, 2) or \
                        type(start['program_ref']) is not str or \
                        not re.fullmatch(r'sha256:[0-9a-f]{64}', start['program_ref']) or \
                        intent_id != 'host-stage:' + key or operation is None or operation['status'] != 'settled' or \
                        operation['fingerprint'] != start['fingerprint'] or terminal['fingerprint'] != start['fingerprint'] or \
                        operation['intent']['candidate']['id'] != 'host-stage-' + key or \
                        operation['intent']['operation'] != 'dev' or operation['intent']['lane'] != 'main' or \
                        operation['intent']['amounts'] != {'token': 0, 'node': 0, 'eval_count': 1} or \
                        operation['actual_costs'] != {'token': 0, 'node': 0, 'eval_count': 1} or \
                        operation['provider_evidence_ref'] != 'sha256:' + payload_digest([]) or \
                        provider_records.get(intent_id) or \
                        terminal['result_ref'] != 'sha256:' + payload_digest(result) or \
                        terminal['evidence_ref'] != 'sha256:' + payload_digest({'start': start, 'result': result}) or \
                        operation.get('measurement_evidence_ref') != terminal['evidence_ref'] or \
                        not positions.get(('start', intent_id), len(rows)) < start_index < terminal_index < \
                            positions.get(('settle', intent_id), -1):
                    raise ValueError('stage evidence differs from its physical operation')
                _validate_stage_result(result, stage=start['stage'], program_ref=start['program_ref'])
                prior = start['prior_id']
                if start['stage'] == 1:
                    if prior is not None:
                        raise ValueError('first stage has a predecessor')
                elif start['stage'] == 2:
                    if prior not in completed or prior in used or completed[prior][0] >= start_index:
                        raise ValueError('second stage lacks a unique earlier first stage')
                    previous = completed[prior][1]['result']
                    previous_start = starts[prior][1]
                    if previous_start['stage'] != 1 or previous_start['program_ref'] != start['program_ref'] or \
                            previous['status'] != 'ok' or previous['metrics']['combined_score'] < .5:
                        raise ValueError('second stage differs from qualifying first stage')
                    used.add(prior)
                else:
                    raise ValueError('unsupported recorded stage')
            return {'schema_version': 1, 'stage_calls': len(starts),
                    'stage_one_calls': sum(value[1]['stage'] == 1 for value in starts.values()),
                    'stage_two_calls': sum(value[1]['stage'] == 2 for value in starts.values())}

    def _prior(self, prior_id, program_ref):
        starts = [row['payload'] for row in self.budget.store.read('host_stage_started')]
        if any(row['stage'] == 2 and row['prior_id'] == prior_id for row in starts):
            raise ValueError('stage one has already been used for stage two')
        matches = [row['payload'] for row in self.budget.store.read('host_stage_completed')
                   if row['payload'].get('request_id') == prior_id]
        original = [row for row in starts if row['request_id'] == prior_id]
        if len(matches) != 1 or len(original) != 1:
            raise ValueError('stage two requires an original completed first stage')
        first, start = matches[0], original[0]
        result = first['result']
        _validate_stage_result(result, stage=1, program_ref=program_ref)
        operations = self.budget._rebuild()[0]['operations']
        op = operations.get(start['intent_id'])
        if first['result_ref'] != 'sha256:' + payload_digest(result) or first['fingerprint'] != start['fingerprint'] \
                or first.get('evidence_ref') != 'sha256:' + payload_digest({'start': start, 'result': result}) \
                or start['stage'] != 1 or start['program_ref'] != program_ref or result.get('program_ref') != program_ref \
                or result.get('stage') != 1 or result.get('status') != 'ok' or \
                type(result.get('metrics', {}).get('combined_score')) not in (int, float) or \
                not math.isfinite(result['metrics']['combined_score']) or result['metrics']['combined_score'] < .5 or \
                op is None or op['status'] != 'settled' or op['fingerprint'] != start['fingerprint'] or \
                op.get('measurement_evidence_ref') != first['evidence_ref'] or \
                op['actual_costs']['eval_count'] != 1:
            raise ValueError('stage one is not qualifying original measured evidence')

    def execute(self, request_id, program, *, stage, prior_id=None, timeout=60):
        with self._lock:
            self._require_control()
            deadline = self.control_authority.bridge.cell_deadline() if self.control_authority is not None else None
            if deadline is not None:
                deadline.check()
            if type(request_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', request_id) or \
                    type(program) is not str or not program.strip() or len(program.encode()) > 1024 * 1024 or \
                    type(stage) is not int or stage not in (1, 2) or \
                    type(timeout) not in (int, float) or not 0 < timeout <= 60:
                raise ValueError('stage request requires bounded program, stage and timeout')
            if self.budget.state()['open_intents']:
                raise ValueError('unresolved physical operation blocks stage execution')
            self.budget.pre_call_check()
            program_ref = 'sha256:' + hashlib.sha256(program.encode()).hexdigest()
            if stage == 1 and prior_id is not None or stage == 2 and (
                    type(prior_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', prior_id)):
                raise ValueError('stage predecessor identity differs')
            if stage == 2:
                self._prior(prior_id, program_ref)
            candidate = Candidate('host-stage-' + request_id)
            request = self.budget.allocate(candidate, direction_id='host')
            receipt = self.budget.reserve_operation('host-stage:' + request_id, candidate, 'host', 'dev',
                request=request)
            if not receipt.granted:
                raise ValueError('physical budget refused the stage')
            if receipt.amounts != {'token': 0, 'node': 0, 'eval_count': 1}:
                self.budget.release_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
                raise ValueError('physical stage reservation must cover exactly one evaluation')
            self.budget.start_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
            try:
                started = {'request_id': request_id, 'stage': stage,
                    'prior_id': prior_id, 'program_ref': program_ref, 'intent_id': receipt.intent_id,
                    'fingerprint': receipt.fingerprint}
                self.budget.store.append('host_stage_started', started)
                if deadline is not None:
                    remaining = deadline.remaining()
                    if remaining <= 0:
                        from zoo.circle_packing.cell_deadline import DeadlineExpired
                        raise DeadlineExpired('cell deadline expired before stage execution')
                    timeout = min(timeout, remaining)
                result = run_stage(program, stage=stage, runner=self.runner, workspace=self.workspace, timeout=timeout)
                _validate_stage_result(result, stage=stage, program_ref=program_ref)
                measured_ref = 'sha256:' + payload_digest({'start': started, 'result': result})
                self.budget.store.append('host_stage_completed', {'request_id': request_id,
                    'fingerprint': receipt.fingerprint, 'result': result,
                    'result_ref': 'sha256:' + payload_digest(result), 'evidence_ref': measured_ref})
                self.budget.settle_operation(receipt.intent_id, {'token': 0, 'node': 0, 'eval_count': 1},
                    measured_units=self.budget.units, fingerprint=receipt.fingerprint,
                    provider_evidence_ref=evidence_reference(self.budget.store, receipt.intent_id),
                    measurement_evidence_ref=measured_ref)
                if deadline is not None:
                    deadline.check()
                return result
            except Exception:
                try:
                    if receipt.intent_id in self.budget.state()['open_intents']:
                        self.budget.mark_unresolved(receipt.intent_id, fingerprint=receipt.fingerprint,
                                                    reason='host_stage_unresolved')
                except Exception:
                    pass
                raise
