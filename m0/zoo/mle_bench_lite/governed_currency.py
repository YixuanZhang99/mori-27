"""Private coordinator for physical/CNY admission and recorded outcome adoption.

The runtime owns serialization and physical settlement. This adapter never
retries an admitted request and never treats missing outcomes as free calls.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import uuid

from core.composition.external_provider import (
    ExternalCallOutcome, ExternalPlanBinding, GovernedCallContext,
    external_call_id, external_session_id, validate_external_ordinal,
)
from core.llm import ProviderBudgetExhausted, UsageError
from core.x1.checkpoint import payload_digest
from .cny_budget import usage_run_id, validate_detailed_usage, _reduce_history, _outstanding
from .governed_currency_audit import RecordedCurrencyView, verify_governance_evidence


def _copy(value):
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False))


def _ref(value):
    return 'sha256:' + payload_digest(value)


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class CNYInvocationBridge:
    """Fresh per-runtime adapter; the campaign itself remains independently shared."""

    def __init__(self, ledger, *, usage_dir=None, spool_dir=None, cell_deadline_binding=None):
        self.ledger = ledger
        self._usage_dir = usage_dir
        self._spool_dir = spool_dir
        self._run = None
        self._cell_deadline = None
        self._deadline_bind_lock = threading.RLock()
        self._initial_deadline_binding = cell_deadline_binding

    def bind_cell_deadline(self, deadline, *, plan, expected_plan_ref, cell_id):
        """Bind the draft's shared clock under the physical admission lock."""
        owner = getattr(getattr(self._run, 'physical_identity_lookup', None), '__self__', None)
        lock = getattr(owner, '_lock', self._deadline_bind_lock)
        with lock:
            return self._bind_cell_deadline(deadline, plan=plan, expected_plan_ref=expected_plan_ref, cell_id=cell_id)

    def _bind_cell_deadline(self, deadline, *, plan, expected_plan_ref, cell_id):
        from zoo.circle_packing.cell_deadline import CellDeadline
        from zoo.circle_packing.pilot_plan import validate_draft_cell
        if self._run is None or self._run.mode != 'live' or self._cell_deadline is not None or \
                type(deadline) is not CellDeadline or deadline._lifecycle.ledger is not self.ledger:
            raise ValueError('cell deadline must share the original live currency authority')
        binding = validate_draft_cell(self.ledger, plan, cell_id, expected_plan_ref=expected_plan_ref)
        record = deadline._record
        if record['cell_id'] != binding['cell_id'] or record['plan_ref'] != binding['plan_ref'] or \
                record['seconds'] != binding['wallclock_seconds']:
            raise ValueError('cell deadline differs from the frozen draft')
        fixed = {'schema_version': 1, 'logical_run_id': self._run.logical_run_id,
                 'campaign_id': binding['campaign_id'], 'cell_id': cell_id,
                 'plan_ref': binding['plan_ref'], 'deadline_ref': record['record_sha256']}
        existing = self._load('cell-deadline-binding')
        run_id = self._ready.authority_binding['currency_run_id']
        anchored = self.ledger.run_deadline_binding(run_id)
        proof = {'cell_id': cell_id, 'plan_ref': binding['plan_ref'], 'deadline_ref': record['record_sha256']}
        if existing is None:
            if anchored is not None:
                if anchored != proof:
                    raise ValueError('cell deadline differs from the campaign binding')
                deadline.remaining()  # Reconstruct only from the original anchored clock.
            else:
                rows = list(self._run.store.read())
                if self._records() or any(row['kind'] in {'host_stage_started', 'governed_control_started',
                        'composed_provider_started'} or row['kind'] == 'hierarchical_budget' and
                        row['payload'].get('event') == 'reserve' for row in rows):
                    raise ValueError('cell deadline cannot be first bound after work')
                deadline.check()
                self.ledger.bind_run_deadline(run_id, **proof)
            self._save('cell-deadline-binding', fixed)
        elif existing != fixed or anchored != proof:
            raise ValueError('cell deadline differs from its durable binding')
        else:
            deadline.remaining()  # Validate original identity even after expiry.
        self._cell_deadline = deadline

    def cell_deadline(self):
        """Fail closed when a previously bound live clock is absent or changed."""
        if self._run is None or self._run.mode != 'live':
            return None
        fixed = self._load('cell-deadline-binding')
        deadline = self._cell_deadline
        anchored = self.ledger.run_deadline_binding(self._ready.authority_binding['currency_run_id'])
        if fixed is None and deadline is None and anchored is None:
            return None
        if fixed is None or deadline is None or anchored is None or deadline._lifecycle.ledger is not self.ledger or \
                anchored != {'cell_id': deadline._record['cell_id'], 'plan_ref': deadline._record['plan_ref'],
                             'deadline_ref': deadline._record['record_sha256']} or fixed != {'schema_version': 1, 'logical_run_id': self._run.logical_run_id,
                          'campaign_id': deadline._lifecycle.campaign_id,
                          'cell_id': deadline._record['cell_id'], 'plan_ref': deadline._record['plan_ref'],
                          'deadline_ref': deadline._record['record_sha256']}:
            raise UsageError('durable cell deadline binding is missing or changed')
        return deadline

    def _load(self, name):
        path = self._spool / (name + '.json')
        if not path.exists():
            if path.is_symlink():
                raise ValueError('currency spool symlink is forbidden')
            return None
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ValueError('currency spool requires private regular records')
        try:
            envelope = json.loads(path.read_text())
            if type(envelope) is not dict or set(envelope) != {'payload', 'sha256'} or \
                    envelope['sha256'] != payload_digest(envelope['payload']):
                raise ValueError('currency spool record hash differs')
            return envelope['payload']
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError('currency spool record is unreadable') from error

    def _save(self, name, value):
        old = self._load(name)
        if old is not None:
            if old != value:
                raise ValueError('immutable currency spool record changed')
            return
        target = self._spool / (name + '.json')
        temporary = self._spool / ('.tmp-' + uuid.uuid4().hex)
        data = json.dumps({'payload': value, 'sha256': payload_digest(value)},
                          sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if self._load(name) != value:
                    raise ValueError('immutable currency spool record changed') from None
            _sync_dir(self._spool)
        finally:
            temporary.unlink(missing_ok=True)

    def _root_rows(self):
        # RecordedOutcomeStore intentionally exposes only its adoption cursor
        # through read(); independent proof audit requires the frozen transcript.
        if self._run.mode == 'recorded' and hasattr(self._run.store, 'rows'):
            return _copy(self._run.store.rows)
        return list(self._run.store.read())

    def _session_key(self, context):
        return 'main' if context.lane == 'main' else context.slot_id

    def bind_run(self, context):
        if self._run is not None:
            raise ValueError('external bridge is already bound to a runtime')
        self._run = context
        self._bindings = {'main': context.main_provider_binding, **context.control_provider_bindings}
        identity = {key: value for key, value in context.to_dict().items()
                    if key not in {'mode', 'recorded_bundle'}}
        if context.mode == 'recorded':
            bundle = context.recorded_bundle
            if type(bundle) is not dict or set(bundle) != {'schema_version', 'preparation', 'ready',
                    'calls', 'terminals', 'currency_evidence'} or bundle['schema_version'] != 1:
                raise ValueError('unsupported recorded currency bundle')
            self._bundle = _copy(bundle)
            self._preparation = bundle['preparation']
            if ({key: value for key, value in self._preparation['run'].items() if key != 'workdir'} !=
                    {key: value for key, value in identity.items() if key != 'workdir'}):
                raise ValueError('recorded currency run identity changed')
            self._ready = self._validate_ready(bundle['ready'])
            authority = self._ready.authority_binding
            self._authority = RecordedCurrencyView(bundle['currency_evidence'],
                expected_run_id=authority['currency_run_id'], expected_plan_ref=self._ready.physical_plan_ref,
                expected_policy_sha256=authority['policy_sha256'])
            for row in bundle['currency_evidence']['events']:
                event = json.loads(row['payload'])
                if event.get('kind') == 'bind_run_deadline' and event.get('run_id') == authority['currency_run_id']:
                    raise UsageError('deadline-bound replay requires recorded eligibility evidence')
            if self.audit()['unknown_cost_calls']:
                raise UsageError('recorded currency proof contains unresolved provider usage')
            return self._ready
        if self.ledger is None:
            raise ValueError('live currency bridge requires an existing authority')
        self._authority = self.ledger
        if len({id(raw) for raw in context.provider_sessions.values()}) != len(context.provider_sessions):
            raise ValueError('currency provider sessions must be distinct fresh objects')
        self._spool = Path(self._spool_dir or Path(context.workdir) / '.governed-cny').absolute()
        if self._spool.is_symlink():
            raise ValueError('currency spool symlink is forbidden')
        self._spool.mkdir(mode=0o700, parents=True, exist_ok=True)
        if stat.S_IMODE(self._spool.stat().st_mode) != 0o700:
            raise ValueError('currency spool requires private 0700 directory')
        _sync_dir(self._spool.parent)
        policy = self.ledger.manifest_binding()
        manifests = {}
        obligations = []
        for key, raw in context.provider_sessions.items():
            if raw.governance_binding() != self._bindings[key]:
                raise ValueError('provider differs from frozen governance declaration')
            manifest = raw.manifest_binding()
            if manifest['campaign'] != policy:
                raise ValueError('provider belongs to a different currency authority')
            manifests[key] = manifest
            caps = self._bindings[key]['phase_call_limits']
            if key == 'main':
                continue
            slots = [slot for slot in context.physical_plan['slots'] if slot['slot_id'] == key]
            if len(slots) != 1:
                raise ValueError('provider slot differs from physical plan')
            bound = self.ledger.quote_call(manifest['max_completion_tokens'])
            for phase in ('operator', 'evaluation'):
                if caps[phase] * self._bindings[key]['call_bound']['units']['token'] > \
                        slots[0]['reservations'][phase].get('token', 0):
                    raise ValueError('currency phase call bounds exceed physical protection')
                obligations.extend({'slot_id': key, 'phase': phase, 'ordinal': ordinal, 'bound': bound}
                                   for ordinal in range(caps[phase]))
        usage_dir = str(Path(self._usage_dir or Path(context.workdir) / 'provider_usage').resolve())
        fixed = {'schema_version': 1, 'run': identity, 'usage_dir': usage_dir,
                 'currency_run_id': usage_run_id(usage_dir), 'manifests': manifests,
                 'obligations': sorted(obligations, key=lambda v: (v['slot_id'], v['phase'], v['ordinal']))}
        existing = self._load('plan-prepared')
        if existing is None:
            try:
                self.ledger.audit_run(fixed['currency_run_id'], context.physical_plan['plan_ref'])
            except ValueError:
                pass
            else:
                raise UsageError('protected currency run lost its immutable preparation')
            snapshot = self.ledger.snapshot()
            if snapshot['pending_calls'] or snapshot.get('protection_breaches'):
                raise UsageError('currency authority has unresolved or invalid protection')
            held = sum(value['bound']['reserved_micro_cny'] for value in obligations)
            main_cap = snapshot['remaining_micro_cny'] - held
            if main_cap < 0:
                raise ProviderBudgetExhausted('currency capacity cannot protect the control plan')
            existing = {**fixed, 'main_currency_cap_micro_cny': main_cap,
                        'initial_currency_head': snapshot['journal_head']}
            # Must precede protection: adopting an existing protected plan must
            # never recompute the fixed main ceiling after control savings.
            self._save('plan-prepared', existing)
        elif any(existing.get(key) != value for key, value in fixed.items()):
            raise ValueError('prepared currency run, provider, or relocation changed')
        self._preparation = existing
        self.ledger.protect_run(existing['currency_run_id'], context.physical_plan['plan_ref'], obligations)
        authority = {'currency_run_id': existing['currency_run_id'], 'campaign_id': policy['campaign_id'],
            'policy_sha256': policy['policy_sha256'],
            'phase_call_limits': {key: value['phase_call_limits'] for key, value in self._bindings.items()},
            'session_ids': {key: external_session_id(context.logical_run_id,
                'main' if key == 'main' else 'control', None if key == 'main' else key, payload_digest(value))
                for key, value in self._bindings.items()},
            'obligations_sha256': payload_digest(existing['obligations']),
            'main_currency_cap_micro_cny': existing['main_currency_cap_micro_cny'],
            'initial_currency_head': existing['initial_currency_head']}
        ready = ExternalPlanBinding(schema_version=1, runtime_id=context.runtime_id,
            logical_run_id=context.logical_run_id, physical_plan_ref=context.physical_plan['plan_ref'],
            bridge_plan_ref=_ref(existing), authority_binding=authority)
        self._ready = self._validate_ready(ready.to_dict())
        self._save('ready', ready.to_dict())
        if self._initial_deadline_binding is not None:
            deadline, plan, expected_plan_ref, cell_id = self._initial_deadline_binding
            self.bind_cell_deadline(deadline, plan=plan, expected_plan_ref=expected_plan_ref, cell_id=cell_id)
        return ready

    def _validate_ready(self, value):
        ready = ExternalPlanBinding.from_dict(value)
        prep = self._preparation
        policy = prep['manifests']['main']['campaign']
        expected = {'currency_run_id': prep['currency_run_id'], 'campaign_id': policy['campaign_id'],
            'policy_sha256': policy['policy_sha256'],
            'phase_call_limits': {key: binding['phase_call_limits'] for key, binding in self._bindings.items()},
            'session_ids': {key: external_session_id(self._run.logical_run_id,
                'main' if key == 'main' else 'control', None if key == 'main' else key, payload_digest(binding))
                for key, binding in self._bindings.items()},
            'obligations_sha256': payload_digest(prep['obligations']),
            'main_currency_cap_micro_cny': prep['main_currency_cap_micro_cny'],
            'initial_currency_head': prep['initial_currency_head']}
        if (ready.bridge_plan_ref != _ref(prep) or ready.authority_binding != expected or
                ready.physical_plan_ref != self._run.physical_plan['plan_ref'] or
                ready.logical_run_id != self._run.logical_run_id or ready.runtime_id != self._run.runtime_id or
                type(prep['main_currency_cap_micro_cny']) is not int or prep['main_currency_cap_micro_cny'] < 0):
            raise ValueError('currency bridge ready identity differs from preparation')
        return ready

    def _validate_context(self, context, *, physical=True, admission=True):
        if not isinstance(context, GovernedCallContext):
            raise ValueError('currency invocation requires trusted context')
        ready, authority = self._ready, self._ready.authority_binding
        key = self._session_key(context)
        expected = {'runtime_id': ready.runtime_id, 'logical_run_id': ready.logical_run_id,
            'physical_plan_ref': ready.physical_plan_ref, 'bridge_plan_ref': ready.bridge_plan_ref,
            'currency_run_id': authority['currency_run_id'], 'campaign_id': authority['campaign_id'],
            'policy_sha256': authority['policy_sha256'], 'session_id': authority['session_ids'].get(key),
            'adapter_binding_sha256': payload_digest(self._bindings.get(key))}
        if any(getattr(context, name) != value for name, value in expected.items()):
            raise ValueError('currency invocation differs from frozen bridge identity')
        if admission and (context.phase != 'planning' or 'planning' in self._bindings[key]['phase_call_limits']):
            validate_external_ordinal(self._bindings[key], context.phase, context.ordinal)
        if physical:
            identity = self._run.physical_identity_lookup(context.intent_id,
                                                         fingerprint=context.physical_fingerprint)
            if identity.get('status') != 'started' or any(identity.get(name) != getattr(context, name)
                    for name in ('intent_id', 'physical_fingerprint', 'candidate_id', 'lane', 'slot_id',
                                 'account', 'operation', 'phase')):
                raise ValueError('currency call identity differs from physical authority')
            bound = self._bindings[key]['call_bound']['units']['token']
            if admission and (bound <= 0 or context.ordinal >= identity['amounts'].get('token', 0) // bound):
                raise ValueError('physical reservation cannot admit bounded provider ordinal')
        return key

    def _records(self):
        if self._run.mode == 'recorded':
            return _copy(self._bundle['calls'])
        result = []
        for path in sorted(self._spool.glob('call-*.prepared.json')):
            name = path.name[:-len('.prepared.json')]
            result.append({'prepared': self._load(name + '.prepared'),
                'response': self._load(name + '.response'), 'outcome': self._load(name + '.outcome')})
        return result

    def _name(self, context):
        return 'call-' + payload_digest(context.to_dict())

    def _validate_prepared(self, prepared, context):
        fields = {'schema_version', 'context', 'call_id', 'wire_request_sha256', 'wire_body',
                  'bound', 'physical_bound', 'provider_binding_sha256'}
        if type(prepared) is not dict or type(prepared.get('schema_version')) is not int or \
                prepared.get('schema_version') not in (1, 2) or \
                set(prepared) != fields | ({'argument'} if prepared.get('schema_version') == 2 else set()):
            raise ValueError('invalid prepared currency call')
        key = self._validate_context(context, physical=False, admission=prepared['wire_body'] is not None)
        body = prepared['wire_body'].encode() if prepared['wire_body'] is not None else None
        manifest = self._preparation['manifests'][key]
        if (prepared['context'] != context.to_dict() or
                prepared['wire_request_sha256'] != (hashlib.sha256(body).hexdigest() if body is not None else '0' * 64) or
                prepared['call_id'] != external_call_id(context, prepared['wire_request_sha256']) or
                prepared['bound'] != self._authority.quote_call(manifest['max_completion_tokens']) or
                prepared['physical_bound'] != self._bindings[key]['call_bound'] or
                prepared['provider_binding_sha256'] != payload_digest(manifest)):
            raise ValueError('prepared currency call identity or bounds differ')
        from .provider_protocol import build_request
        if body is None:
            if prepared['schema_version'] != 1:
                raise ValueError('undispatched preparation cannot contain provider arguments')
            return key
        try:
            mode = manifest.get('message_mode', 'single_user_v1')
            if (mode in {'openevolve_v1', 'openevolve_host_v1'}) != (prepared['schema_version'] == 2):
                raise ValueError('prepared message mode differs from frozen provider')
            prompt = (prepared['argument'] if prepared['schema_version'] == 2
                      else json.loads(body)['messages'][0]['content'])
            args_hash = payload_digest({'args': (prompt,), 'kwargs': {}})
            if args_hash != context.argument_sha256 or body != build_request(prompt, {
                    'requested_model': manifest['requested_model'], 'request_format': 'deepseek',
                    'max_completion_tokens': manifest['max_completion_tokens'],
                    'reasoning_effort': manifest.get('reasoning_effort', 'high'), 'message_mode': mode}):
                raise ValueError('prepared wire differs from canonical invocation arguments')
        except (KeyError, TypeError, IndexError, UnicodeError) as error:
            raise ValueError('prepared wire request is damaged') from error
        return key

    def _currency_audit(self):
        return self._authority.audit_run(self._ready.authority_binding['currency_run_id'],
                                         self._ready.physical_plan_ref)

    def _outcome(self, prepared, response, state, reason=None):
        context = prepared['context']
        if state == 'not_admitted':
            outcome, usage, result, response_hash = 'known_refused', {'total_tokens': 0}, None, None
            provider_state = None
        else:
            usage, result, response_hash = response['usage'], response['result'], response['response_sha256']
            provider_state = response['provider_state']
            reason = response['integrity_reason']
            if response['observed_binding_sha256'] != context['adapter_binding_sha256']:
                reason = 'provider_binding_changed'
            if not response['provider_state_valid']:
                reason = 'provider_state_invalid'
            outcome = 'unknown' if state == 'pending' else 'known_failed' if reason else 'returned'
        value = {'call_id': prepared['call_id'], 'context_sha256': payload_digest(context),
            'wire_request_sha256': prepared['wire_request_sha256'], 'response_sha256': response_hash,
            'usage': usage, 'result': result, 'provider_state': provider_state,
            'outcome': outcome, 'currency_state': state,
            'integrity_reason': reason}
        return ExternalCallOutcome(**value, outcome_ref=_ref(value))

    def _validate_response(self, response, prepared):
        if type(response) is not dict or set(response) != {'response_sha256', 'returned_model', 'usage',
                'result', 'finish_reason', 'integrity_reason', 'observed_binding_sha256',
                'provider_state', 'provider_state_valid'}:
            raise ValueError('durable provider response shape differs')
        if type(response['provider_state_valid']) is not bool or (
                not response['provider_state_valid'] and response['provider_state'] is not None):
            raise ValueError('durable provider state validity differs')
        _copy(response['provider_state'])
        key = self._session_key(GovernedCallContext.from_dict(prepared['context']))
        manifest = self._preparation['manifests'][key]
        reason = response['integrity_reason']
        if reason in {'invalid_json', 'invalid_response', 'invalid_usage'} and response['usage'] is None:
            return False
        if response['returned_model'] != manifest['requested_model']:
            if reason != 'model_mismatch':
                raise ValueError('durable response falsely claims model agreement')
            return False
        try:
            usage = validate_detailed_usage(response['usage'])
        except ValueError:
            if reason not in {'invalid_usage_details', 'invalid_usage', 'invalid_json', 'invalid_response'}:
                raise ValueError('durable response falsely claims priced usage') from None
            return False
        bound_reason = ('input_bound_exceeded' if usage['prompt_tokens'] > manifest['campaign']['context_tokens']
            else 'output_bound_exceeded' if usage['completion_tokens'] > manifest['max_completion_tokens'] else None)
        if bound_reason is not None and reason != bound_reason:
            raise ValueError('durable response falsely claims bounded usage')
        if reason is None and (response['finish_reason'] != 'stop' or type(response['result']) is not str
                               or not response['result'].strip()):
            raise ValueError('durable response falsely claims successful output')
        return reason not in {'model_mismatch', 'invalid_usage_details', 'invalid_usage', 'invalid_json', 'invalid_response'}

    def _settle_response(self, prepared, response):
        priced = self._validate_response(response, prepared)
        if priced:
            self.ledger.settle(prepared['call_id'], response['usage'], response['response_sha256'])
        outcome = self._outcome(prepared, response, 'settled' if priced else 'pending')
        if self._run.mode == 'live':
            self._save(self._name(GovernedCallContext.from_dict(prepared['context'])) + '.outcome', outcome.to_dict())
        return outcome

    def invoke(self, context, args, kwargs):
        if self._run.mode != 'live':
            raise UsageError('recorded currency bridge never dispatches')
        key = self._validate_context(context)
        raw = self._run.provider_sessions[key]
        raw.last_usage = {'total_tokens': 0}
        deadline = self.cell_deadline()
        if deadline is not None:
            deadline.check()
        if context.argument_sha256 != payload_digest({'args': args, 'kwargs': kwargs}):
            raise ValueError('currency invocation argument identity changed')
        if type(args) is not tuple or len(args) != 1 or kwargs or type(args[0]) is not str:
            self._recover(context, context.argument_sha256, refusal_reason='invocation_refused')
            raise ProviderBudgetExhausted('provider invocation refused before dispatch')
        if raw.governance_binding() != self._bindings[key] or raw.manifest_binding() != self._preparation['manifests'][key]:
            raise UsageError('currency provider contract changed before dispatch')
        name = self._name(context)
        earlier = [record['prepared']['context'] for record in self._records()
                   if record['prepared']['context']['intent_id'] == context.intent_id]
        if sorted(value['ordinal'] for value in earlier) != list(range(context.ordinal)):
            raise ValueError('currency invocation ordinal differs from prior prepared calls')
        if self._load(name + '.prepared') is not None:
            raise UsageError('currency invocation already prepared; recovery cannot dispatch again')
        try:
            body = raw.prepare_request(args[0])
        except ValueError:
            self._recover(context, context.argument_sha256, refusal_reason='invocation_refused')
            raise ProviderBudgetExhausted('provider invocation refused before dispatch') from None
        prepared = {'schema_version': 1, 'context': context.to_dict(),
            'call_id': external_call_id(context, hashlib.sha256(body).hexdigest()),
            'wire_request_sha256': hashlib.sha256(body).hexdigest(), 'wire_body': body.decode(),
            'bound': self.ledger.quote_call(self._preparation['manifests'][key]['max_completion_tokens']),
            'physical_bound': self._bindings[key]['call_bound'],
            'provider_binding_sha256': payload_digest(self._preparation['manifests'][key])}
        if self._preparation['manifests'][key].get('message_mode') in {'openevolve_v1', 'openevolve_host_v1'}:
            prepared['schema_version'] = 2
            prepared['argument'] = args[0]
        self._validate_prepared(prepared, context)
        self._save(name + '.prepared', prepared)
        try:
            if prepared['schema_version'] == 2:
                raw.validate_dispatch(body, prompt=prepared['argument'])
            else:
                raw.validate_dispatch(body)
        except ValueError:
            # Preparation is durable and validate_dispatch is a pure local
            # check. Confirm no independently committed call before proving zero.
            if any(op['call_id'] == prepared['call_id'] for op in self._currency_audit()['operations']):
                raise UsageError('dispatch refusal conflicts with currency admission') from None
            refusal = self._outcome(prepared, None, 'not_admitted', 'dispatch_refused')
            self._save(name + '.outcome', refusal.to_dict())
            raise ProviderBudgetExhausted('provider readiness refused before dispatch') from None
        audit = self._currency_audit()
        if audit['campaign_pending_calls'] or not audit['protection_valid']:
            raise UsageError('currency campaign is unresolved or protection is invalid')
        main_spent = sum(op.get('upper_bound_micro_cny', op['reserved_micro_cny'])
                         for op in audit['operations'] if op.get('lane') == 'main')
        refused = context.lane == 'main' and main_spent + prepared['bound']['reserved_micro_cny'] > \
            self._ready.authority_binding['main_currency_cap_micro_cny']
        if not refused:
            try:
                self.ledger.admit_call(context.currency_run_id, context.lane, context.slot_id,
                    {'call_id': prepared['call_id'], 'request_sha256': prepared['wire_request_sha256'],
                     'phase': context.phase, 'ordinal': context.ordinal}, prepared['bound'])
            except ValueError:
                snapshot = self.ledger.snapshot()
                if snapshot['pending_calls'] or snapshot.get('protection_breaches'):
                    raise UsageError('currency admission has unresolved authority state') from None
                if snapshot['remaining_micro_cny'] < prepared['bound']['reserved_micro_cny'] and context.lane == 'main':
                    refused = True
                else:
                    raise
        if refused:
            outcome = self._outcome(prepared, None, 'not_admitted', 'capacity_refused')
            self._save(name + '.outcome', outcome.to_dict())
            raise ProviderBudgetExhausted('currency capacity refused before dispatch')
        deadline = self.cell_deadline()
        if deadline is not None:
            deadline.check()
        self._save(name + '.dispatch', {'call_id': prepared['call_id']})
        deadline = self.cell_deadline()
        if deadline is not None:
            deadline.check()
        raw.last_usage = None
        response = (raw.perform_request(body, prompt=prepared['argument']) if prepared['schema_version'] == 2
                    else raw.perform_request(body)).to_dict()
        try:
            response['observed_binding_sha256'] = payload_digest(raw.governance_binding())
        except Exception:
            response['observed_binding_sha256'] = None
        raw.last_usage = response['usage']
        save_state = getattr(raw, 'checkpoint_state', None)
        try:
            response['provider_state'] = _copy(save_state()) if callable(save_state) else None
            response['provider_state_valid'] = True
        except Exception:
            response['provider_state'] = None
            response['provider_state_valid'] = False
        self._save(name + '.response', response)
        outcome = self._settle_response(prepared, response)
        deadline = self.cell_deadline()
        if deadline is not None:
            deadline.check()
        if outcome.outcome == 'unknown':
            raise UsageError('provider outcome cannot establish priced currency usage')
        if outcome.outcome == 'known_failed':
            raise RuntimeError('provider invocation failed (' + outcome.integrity_reason + ')')
        return outcome.result

    def _recover_for_accounting(self, context, argument_sha256):
        """Trusted runtime-only access to original usage, never candidate admission."""
        return self._recover(context, argument_sha256, refusal_reason='deadline_refused')

    def _check_cell_deadline(self):
        deadline = self.cell_deadline()
        if deadline is not None:
            deadline.check()

    def recover(self, context, argument_sha256):
        outcome = self._recover(context, argument_sha256, refusal_reason='capacity_refused')
        deadline = self.cell_deadline()
        if deadline is not None:
            deadline.check()
        return outcome

    def _recover(self, context, argument_sha256, *, refusal_reason):
        self._validate_context(context, physical=self._run.mode == 'live', admission=False)
        if argument_sha256 != context.argument_sha256:
            raise ValueError('recovery invocation argument identity changed')
        records = [record for record in self._records() if record['prepared']['context'] == context.to_dict()]
        audit = self._currency_audit()
        if len(records) > 1:
            raise ValueError('duplicate prepared currency invocation')
        if not records:
            if self._unexplained_matching_currency(context, audit['operations'], self._records()):
                raise UsageError('currency admission exists without its local preparation')
            if self._run.mode != 'live':
                raise UsageError('recorded invocation lacks durable refusal proof')
            name = self._name(context)
            if any(self._load(name + suffix) is not None for suffix in ('.dispatch', '.response', '.outcome')):
                raise UsageError('partial currency spool cannot prove no dispatch')
            starts = [row['payload'] for row in self._run.store.read('composed_provider_started')
                      if row['payload'].get('invocation', {}).get('external_context') == context.to_dict()]
            if len(starts) != 1 or starts[0].get('request_sha256') != argument_sha256 or \
                    starts[0].get('binding') != payload_digest({'request_sha256': argument_sha256,
                                                              'invocation': starts[0]['invocation']}):
                raise UsageError('missing preparation requires authoritative no-dispatch proof')
            key = self._session_key(context)
            prepared = {'schema_version': 1, 'context': context.to_dict(),
                'call_id': external_call_id(context, '0' * 64), 'wire_request_sha256': '0' * 64,
                'wire_body': None, 'bound': self._authority.quote_call(
                    self._preparation['manifests'][key]['max_completion_tokens']),
                'physical_bound': self._bindings[key]['call_bound'],
                'provider_binding_sha256': payload_digest(self._preparation['manifests'][key])}
            self._save(name + '.prepared', prepared)
            records = [{'prepared': prepared, 'response': None, 'outcome': None}]
        record = records[0]
        prepared = record['prepared']
        self._validate_prepared(prepared, context)
        operation = next((op for op in audit['operations'] if op['call_id'] == prepared['call_id']), None)
        if operation is None:
            if record['response'] is not None:
                raise ValueError('provider response has no currency reservation')
            reason = record['outcome'].get('integrity_reason') if record['outcome'] else refusal_reason
            if reason not in {'capacity_refused', 'dispatch_refused', 'invocation_refused', 'deadline_refused'}:
                raise ValueError('unknown pre-admission refusal proof category')
            outcome = self._outcome(prepared, None, 'not_admitted', reason)
            if record['outcome'] is not None and record['outcome'] != outcome.to_dict():
                raise ValueError('unadmitted outcome differs from refusal')
            if self._run.mode == 'live':
                self._save(self._name(context) + '.outcome', outcome.to_dict())
            return outcome
        self._match_operation(prepared, operation)
        if record['response'] is None:
            raise UsageError('admitted currency operation has no durable provider outcome')
        if self._run.mode == 'live':
            return self._settle_response(prepared, record['response'])
        expected = self._outcome(prepared, record['response'], 'settled' if 'usage' in operation else 'pending')
        if record['outcome'] != expected.to_dict():
            raise ValueError('recorded currency outcome differs from authority')
        return expected

    def _unexplained_matching_currency(self, context, operations, records):
        """Exclude a prior call only when all its independent links are intact."""
        root = self._root_rows()
        for operation in operations:
            if any(operation.get(key) != getattr(context, key) for key in ('lane', 'slot_id', 'phase', 'ordinal')):
                continue
            matching = [record for record in records if record['prepared']['call_id'] == operation['call_id']]
            if len(matching) != 1 or 'usage' not in operation:
                return True
            record = matching[0]
            prepared, response, stored = record['prepared'], record['response'], record['outcome']
            other = GovernedCallContext.from_dict(prepared['context'])
            if other.to_dict() == context.to_dict() or response is None or stored is None:
                return True
            self._validate_prepared(prepared, other)
            self._match_operation(prepared, operation)
            if not self._validate_response(response, prepared) or operation['usage'] != response['usage'] or \
                    operation['response_sha256'] != response['response_sha256']:
                return True
            outcome = self._outcome(prepared, response, 'settled')
            if stored != outcome.to_dict():
                return True
            starts = [row['payload'] for row in root if row['kind'] == 'composed_provider_started' and
                      row['payload'].get('invocation', {}).get('external_context') == other.to_dict()]
            if len(starts) != 1:
                return True
            start = starts[0]
            if start.get('request_sha256') != other.argument_sha256 or start.get('binding') != payload_digest({
                    'request_sha256': other.argument_sha256, 'invocation': start['invocation']}):
                return True
            completions = [row['payload'] for row in root if row['kind'] == 'composed_provider_completed' and
                           row['payload'].get('binding') == start['binding']]
            if len(completions) != 1:
                return True
            completion = completions[0]
            if completion.get('tokens') != outcome.usage['total_tokens'] or completion.get('state') != outcome.provider_state or \
                    completion.get('outcome', 'returned') != ('returned' if outcome.outcome == 'returned' else 'failed') or \
                    (outcome.outcome == 'returned' and completion.get('result') != outcome.result):
                return True
            observed = completion.get('observed_binding_sha256')
            if observed != response['observed_binding_sha256'] and not (
                    outcome.integrity_reason == 'provider_binding_changed' and observed is None):
                return True
        return False

    def _match_operation(self, prepared, operation):
        context = prepared['context']
        expected = {'kind': 'governed_reserve', 'schema_version': 2, 'call_id': prepared['call_id'],
            'run_id': context['currency_run_id'], 'plan_ref': context['physical_plan_ref'],
            'lane': context['lane'], 'slot_id': context['slot_id'], 'phase': context['phase'],
            'ordinal': context['ordinal'], 'request_sha256': prepared['wire_request_sha256'],
            'output_allowance': prepared['bound']['output_allowance'],
            'reserved_micro_cny': prepared['bound']['reserved_micro_cny']}
        if any(operation.get(key) != value for key, value in expected.items()):
            raise ValueError('currency reservation differs from prepared physical invocation')

    def finish_control(self, slot_id, terminal_ref):
        rows = [row['payload'] for row in self._run.store.read('governed_control_terminal')
                if row['payload'].get('slot_id') == slot_id]
        if len(rows) != 1 or _ref(rows[0]) != terminal_ref or rows[0].get('plan_ref') != self._ready.physical_plan_ref:
            raise ValueError('currency cancellation requires exact authoritative control terminal')
        value = {'slot_id': slot_id, 'terminal_ref': terminal_ref, 'terminal': rows[0]}
        audit = self._currency_audit()
        slot = audit['slots'].get(slot_id)
        if slot is None:
            raise ValueError('currency cancellation refers to unknown control slot')
        if self._run.mode == 'recorded':
            if value not in self._bundle['terminals']:
                raise ValueError('recorded currency cancellation lacks terminal evidence')
            return
        if slot['pending']:
            self.ledger.cancel_control(self._ready.authority_binding['currency_run_id'], slot_id,
                                       reason='terminal_' + terminal_ref[7:])
        self._save('terminal-' + slot_id, value)

    def _audit_replay_prefix(self):
        return self.audit(_allow_replay_prefix=True)

    def audit(self, *, _allow_replay_prefix=False):
        replay_pending = callable(getattr(self._run.store, 'peek', None)) and self._run.store.peek() is not None
        incomplete = self._run.mode != 'recorded' and (
            getattr(self._run.store, 'restoring', False) or replay_pending)
        if incomplete and not _allow_replay_prefix:
            raise UsageError('currency audit cannot certify an unconsumed replay suffix')
        authority = self._ready.authority_binding
        evidence = self._authority.export_governance_evidence(authority['currency_run_id'],
                                                              self._ready.physical_plan_ref)
        audit = verify_governance_evidence(evidence, expected_run_id=authority['currency_run_id'],
            expected_plan_ref=self._ready.physical_plan_ref, expected_policy_sha256=authority['policy_sha256'])
        if audit['frozen_obligations'] != self._preparation['obligations']:
            raise ValueError('currency obligation set differs from protected bridge plan')
        operations = {op['call_id']: op for op in audit['operations'] if op['kind'] == 'governed_reserve'}
        records = self._records()
        seen = set()
        outcomes = {}
        observed_bindings = {}
        integrity_violations = []
        for record in records:
            prepared = record['prepared']
            context = GovernedCallContext.from_dict(prepared['context'])
            self._validate_prepared(prepared, context)
            identifier = prepared['call_id']
            if identifier in seen:
                raise ValueError('duplicate currency call evidence')
            seen.add(identifier)
            op = operations.pop(identifier, None)
            response, stored = record['response'], record['outcome']
            if op is None:
                if prepared['wire_body'] is None and self._unexplained_matching_currency(
                        context, audit['operations'], records):
                    raise ValueError('absent preparation conflicts with currency admission')
                if response is not None or stored is None:
                    raise ValueError('unadmitted currency call lacks known refusal proof')
                reason = stored.get('integrity_reason')
                if reason not in {'capacity_refused', 'dispatch_refused', 'invocation_refused', 'deadline_refused'}:
                    raise ValueError('unknown pre-admission refusal proof category')
                expected = self._outcome(prepared, None, 'not_admitted', reason)
            else:
                self._match_operation(prepared, op)
                if response is None:
                    if 'usage' in op or stored is not None:
                        raise ValueError('currency settled or completed call lost durable response evidence')
                    value = {'call_id': identifier, 'context_sha256': payload_digest(context.to_dict()),
                        'wire_request_sha256': prepared['wire_request_sha256'], 'response_sha256': None,
                        'usage': None, 'result': None, 'provider_state': None, 'outcome': 'unknown',
                        'currency_state': 'pending', 'integrity_reason': 'outcome_missing'}
                    expected = ExternalCallOutcome(**value, outcome_ref=_ref(value))
                else:
                    if stored is None:
                        raise UsageError('currency call lacks durable outcome publication')
                    priced = self._validate_response(response, prepared)
                    if ('usage' in op) != priced:
                        raise ValueError('currency settlement differs from priced response validity')
                    if priced and (op['usage'] != response['usage'] or op['response_sha256'] != response['response_sha256']):
                        raise ValueError('currency charge differs from durable response')
                    expected = self._outcome(prepared, response, 'settled' if priced else 'pending')
            if stored is not None and stored != expected.to_dict():
                raise ValueError('currency outcome differs from independently reduced authority')
            identity = payload_digest(context.to_dict())
            outcomes[identity] = expected
            observed_bindings[identity] = response['observed_binding_sha256'] if response else context.adapter_binding_sha256
            if expected.integrity_reason in {'provider_binding_changed', 'provider_state_invalid', 'model_mismatch', 'invalid_usage_details',
                    'invalid_usage', 'invalid_json', 'invalid_response', 'input_bound_exceeded', 'output_bound_exceeded'}:
                integrity_violations.append({'call_id': identifier, 'reason': expected.integrity_reason})
        if operations:
            raise ValueError('currency authority has extra calls without physical preparation')
        # Full visibility is required for cross-authority coverage. Continuation
        # prefixes are audited again once the runtime finishes reconstruction.
        replay_pending = callable(getattr(self._run.store, 'peek', None)) and self._run.store.peek() is not None
        if self._run.mode == 'recorded' or (not getattr(self._run.store, 'restoring', False) and not replay_pending):
            starts = {}
            pending = None
            for row in self._root_rows():
                data = row['payload']
                if row['kind'] == 'composed_provider_started':
                    inv = data.get('invocation', {})
                    context_value = inv.get('external_context')
                    if context_value is None:
                        continue
                    context = GovernedCallContext.from_dict(context_value)
                    self._validate_context(context, physical=False, admission=False)
                    identity = payload_digest(context_value)
                    if identity in starts or pending is not None or data['request_sha256'] != context.argument_sha256 or \
                            data['binding'] != payload_digest({'request_sha256': data['request_sha256'], 'invocation': inv}):
                        raise ValueError('physical provider start identity is duplicated or changed')
                    starts[identity] = data
                    pending = (identity, data['binding'])
                elif row['kind'] == 'composed_provider_completed' and pending is not None:
                    identity, binding = pending
                    outcome = outcomes.get(identity)
                    expected_kind = ({'returned': 'returned', 'known_failed': 'failed',
                                      'known_refused': 'budget_exhausted'}.get(outcome.outcome) if outcome else None)
                    if outcome is None or expected_kind is None or data.get('outcome', 'returned') != expected_kind or \
                            data.get('binding') != binding or outcome.usage is None or \
                            data.get('tokens') != outcome.usage['total_tokens'] or \
                            (outcome.outcome == 'returned' and data.get('result') != outcome.result):
                        raise ValueError('physical completion differs from currency outcome')
                    if outcome.currency_state != 'not_admitted' and data.get('state') != outcome.provider_state:
                        raise ValueError('physical completion lost durable provider state')
                    observed = data.get('observed_binding_sha256')
                    if observed != observed_bindings[identity] and not (
                            outcome.integrity_reason == 'provider_binding_changed' and observed is None):
                        raise ValueError('physical completion lost observed provider binding')
                    pending = None
            if set(starts) != set(outcomes):
                raise ValueError('physical and currency invocation coverage differs')
            if pending is not None and outcomes[pending[0]].outcome != 'unknown':
                raise UsageError('physical provider call has no completion')
        main_spent = sum(op.get('upper_bound_micro_cny', op['reserved_micro_cny'])
                         for op in audit['operations'] if op.get('lane') == 'main')
        if main_spent > self._ready.authority_binding['main_currency_cap_micro_cny']:
            if audit['protection_valid']:
                raise ValueError('main currency spend exceeds its frozen independent cap')
            # A correctly priced bound breach may legitimately exceed the cap;
            # preserve that full bill and report invalid protection to core.
            integrity_violations.append({'call_id': None, 'reason': 'main_currency_cap_exceeded'})
        self._validate_adapter_contracts()
        self._validate_initial_capacity(evidence)
        self._validate_terminals(evidence)
        self._last_audit_evidence = _copy(evidence)
        # Public run diagnostics exclude mutable shared campaign balances/head;
        # the private proof retains the exact recorded full campaign snapshot.
        run_audit = {key: value for key, value in audit.items() if key not in {
            'journal_head', 'campaign_settled_upper_bound_micro_cny', 'campaign_outstanding_micro_cny',
            'campaign_pending_calls', 'admission_open'}}
        construction = {}
        if 'construction' in self._run.FIELDS:
            from core.composition.construction_audit import audit_construction
            construction['construction'] = audit_construction(self._root_rows(),
                self._run.construction, logical_run_id=self._run.logical_run_id,
                provider_arguments={payload_digest(record['prepared']['context']):
                    (record['prepared']['argument'] if record['prepared']['schema_version'] == 2 else
                     json.loads(record['prepared']['wire_body'])['messages'][0]['content']
                     if record['prepared']['wire_body'] is not None else None) for record in records})
        return {**construction, **({'coverage_complete': False} if incomplete else {}),
            'schema_version': 1, 'bridge_plan_ref': self._ready.bridge_plan_ref,
            'authority': run_audit, 'invocations': len(records), 'main_currency_cap_micro_cny':
            self._ready.authority_binding['main_currency_cap_micro_cny'], 'invoice_verified': False,
            'protection_valid': audit['protection_valid'] and not integrity_violations,
            'integrity_violations': integrity_violations,
            'unknown_cost_calls': sorted(value.call_id for value in outcomes.values() if value.outcome == 'unknown'),
            'known_provider_tokens': sum(value.usage['total_tokens'] for value in outcomes.values() if value.usage is not None),
            'admission_open': audit['admission_open'] and not integrity_violations}

    def _validate_adapter_contracts(self):
        from .provider_protocol import build_request
        policy = self._authority.manifest_binding()
        obligations = []
        for key, manifest in self._preparation['manifests'].items():
            if manifest['campaign'] != policy:
                raise ValueError('recorded provider differs from frozen currency policy')
            wire = json.loads(build_request('binding', {'requested_model': manifest['requested_model'],
                'request_format': 'deepseek', 'max_completion_tokens': manifest['max_completion_tokens'],
                'reasoning_effort': manifest.get('reasoning_effort', 'high')}))
            wire.pop('messages')
            if 'message_mode' in manifest:
                wire['message_mode'] = manifest['message_mode']
            wire.update(base_url=manifest['base_url'], timeout=manifest['timeout'], policy_sha256=policy['policy_sha256'])
            expected = {'schema_version': 2, 'fresh_session': True, 'state_independent': True,
                'sampling': {'method': 'supplier_unverified', 'parameters': wire, 'applied': True},
                'call_bound': {'kind': 'hard', 'units': {'token': policy['context_tokens'] + manifest['max_completion_tokens']}},
                'external_currency': {'schema_version': 1, 'bridge': 'cny_invocation_v1'},
                'phase_call_limits': manifest['phase_call_limits']}
            if expected != self._bindings.get(key) or manifest['requested_model'] != policy['model']:
                raise ValueError('recorded provider contract differs from frozen adapter declaration')
            if key != 'main':
                bound = self._authority.quote_call(manifest['max_completion_tokens'])
                for phase in ('operator', 'evaluation'):
                    obligations.extend({'slot_id': key, 'phase': phase, 'ordinal': ordinal, 'bound': bound}
                                       for ordinal in range(manifest['phase_call_limits'][phase]))
        obligations.sort(key=lambda value: (value['slot_id'], value['phase'], value['ordinal']))
        if obligations != self._preparation['obligations'] or set(self._preparation['manifests']) != set(self._bindings):
            raise ValueError('recorded phase call coverage differs from protected obligations')

    def _validate_initial_capacity(self, evidence):
        head = self._preparation['initial_currency_head']
        rows = [(row['seq'], row['payload'], row['sha256']) for row in evidence['events']
                if row['seq'] <= head['seq']]
        policy, state = _reduce_history([(evidence['policy_json'],)], rows, [(head['seq'], head['sha256'])])
        if self._preparation['currency_run_id'] in state['governance']['runs'] or state['pending'] is not None:
            raise ValueError('initial currency preparation follows protection or unresolved call')
        cap = policy['limit_micro_cny'] - state['spent'] - state['reserved'] - _outstanding(state['governance'])
        cap -= sum(item['bound']['reserved_micro_cny'] for item in self._preparation['obligations'])
        if cap != self._preparation['main_currency_cap_micro_cny']:
            raise ValueError('fixed main currency cap differs from original campaign capacity')

    def _validate_terminals(self, evidence):
        terminals = (self._bundle['terminals'] if self._run.mode == 'recorded' else
                     [self._load(path.stem) for path in sorted(self._spool.glob('terminal-*.json'))])
        indexed = {}
        for terminal in terminals:
            if type(terminal) is not dict or set(terminal) != {'slot_id', 'terminal_ref', 'terminal'} or \
                    terminal['terminal_ref'] != _ref(terminal['terminal']) or \
                    terminal['terminal'].get('slot_id') != terminal['slot_id'] or \
                    terminal['terminal'].get('plan_ref') != self._ready.physical_plan_ref or \
                    terminal['slot_id'] in indexed:
                raise ValueError('currency terminal proof identity differs')
            indexed[terminal['slot_id']] = terminal
        for row in evidence['events']:
            event = json.loads(row['payload'])
            if event['kind'] != 'cancel_control' or event['run_id'] != self._ready.authority_binding['currency_run_id']:
                continue
            terminal = indexed.get(event['slot_id'])
            if terminal is None or event['reason'] != 'terminal_' + terminal['terminal_ref'][7:]:
                raise ValueError('currency cancellation lacks exact terminal authority proof')
        if self._run.mode == 'recorded' or not getattr(self._run.store, 'restoring', False):
            root = {}
            for row in self._root_rows():
                if row['kind'] != 'governed_control_terminal':
                    continue
                payload = row['payload']
                if payload['slot_id'] in root:
                    raise ValueError('duplicate physical control terminal')
                root[payload['slot_id']] = payload
            if any(root.get(slot) != proof['terminal'] for slot, proof in indexed.items()):
                raise ValueError('currency terminal differs from authoritative root journal')

    def replay_bundle(self):
        if self._run.mode == 'live' and self.ledger.run_deadline_binding(
                self._ready.authority_binding['currency_run_id']) is not None:
            raise UsageError('deadline-bound replay requires recorded eligibility evidence')
        if self._run.mode == 'recorded':
            self.audit()
            return _copy(self._bundle)
        if self.audit()['unknown_cost_calls']:
            raise UsageError('unresolved currency usage cannot produce recorded replay proof')
        authority = self._ready.authority_binding
        terminals = [self._load(path.stem) for path in sorted(self._spool.glob('terminal-*.json'))]
        return {'schema_version': 1, 'preparation': _copy(self._preparation), 'ready': self._ready.to_dict(),
            'calls': self._records(), 'terminals': terminals,
            'currency_evidence': _copy(self._last_audit_evidence)}
