"""Measured adapted circle-packing evaluation with frozen geometry evidence."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
from pathlib import Path
import threading
import time

from core.composition.contracts import Proposal, json_copy
from core.composition.evaluation import binding_for, decode_evidence, validate_evidence
from core.executor.evaluation_contract import EvaluationContract, PrivateEvaluationData, PublicEvaluationData
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus
from zoo.circle_packing.geometry import TARGET, validate_geometry
from zoo.circle_packing.stage import EVALUATOR_SHA256, _EVALUATOR, run_cascade
from zoo.mle_bench_lite.composed_domain import SandboxRunner


def _ref(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return 'sha256:' + hashlib.sha256(encoded.encode('utf-8')).hexdigest()


class CirclePackingDomain:
    """Scores development programs once; final audit rechecks frozen geometry."""
    evaluator_version = 'openevolve-circle-packing-adapted-v1'
    measured_cost_units = ('token', 'node', 'eval_count', 'wallclock')

    def __init__(self, workspace, *, runner=None, stage_timeout=60):
        if type(stage_timeout) not in (int, float) or not 0 < stage_timeout <= 60:
            raise ValueError('circle stage timeout must be positive and at most 60 seconds')
        self.workspace = Path(workspace)
        self.runner = runner if runner is not None else SandboxRunner()
        self.stage_timeout = stage_timeout
        self._lock = threading.RLock()
        self._entries = {}
        self._audited = True
        self._cell_deadline = None
        self._implementation = self._implementation_refs()
        self._runner_binding = json_copy(self.runner.manifest_binding)
        self._base_identity = _ref({'evaluator': EVALUATOR_SHA256, 'target': TARGET,
                                    'threshold': .5, 'stage_timeout': stage_timeout,
                                    'implementation': self._implementation,
                                    'runner': self._runner_binding})
        self.evaluation_contexts = {key: _ref({'identity': self._base_identity, 'split': key})
                                    for key in ('dev', 'final_audit')}
        self.validate_context()

    def _implementation_refs(self):
        root = Path(__file__).resolve().parent
        return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ('domain.py', 'stage.py', 'geometry.py', 'reference_final.py', 'host_physical.py')}

    @property
    def evaluation_context(self):
        return self.evaluation_contexts['dev']

    @property
    def openevolve_binding(self):
        return {'schema_version': 1, 'kind': self.evaluator_version}

    @property
    def manifest_binding(self):
        return {'kind': self.evaluator_version, 'identity': self._base_identity,
                'evaluator_sha256': EVALUATOR_SHA256, 'stage_timeout': self.stage_timeout,
                'runner': copy.deepcopy(self._runner_binding), 'implementation': dict(self._implementation),
                'final_validation': 'frozen_geometry_not_statistical_holdout'}

    def validate_context(self):
        if hashlib.sha256(_EVALUATOR.read_bytes()).hexdigest() != EVALUATOR_SHA256 \
                or self._implementation_refs() != self._implementation \
                or json_copy(self.runner.manifest_binding) != self._runner_binding:
            raise ValueError('circle evaluator or runner identity changed')

    def validate_request(self, request):
        request.validate()
        if request.split_id not in ('dev', 'final_audit') or request.fidelity != request.split_id \
                or request.resume_from is not None or request.seed_set is not None \
                or request.time_limit is not None or request.budget_token is not None:
            raise ValueError('circle evaluator supports only unseeded dev and frozen final audit')
        self.validate_context()

    def evaluation_context_for(self, request):
        self.validate_request(request)
        return self.evaluation_contexts[request.split_id]

    def _identity(self, proposal):
        if not isinstance(proposal, Proposal) or not isinstance(proposal.candidate, Candidate) \
                or type(proposal.candidate.id) is not str or not proposal.candidate.id.strip() \
                or type(proposal.artifact) is not str or not proposal.artifact.strip():
            raise ValueError('circle evaluation requires a candidate and program')
        proposal.candidate.validate()
        return {'candidate_id': proposal.candidate.id,
                'program_ref': 'sha256:' + hashlib.sha256(proposal.artifact.encode('utf-8')).hexdigest(),
                'context': self._base_identity}

    def checkpoint_state(self):
        with self._lock:
            self.validate_context()
            return {'schema_version': 1, 'identity': self._base_identity, 'entries': copy.deepcopy(self._entries)}

    def restore_state(self, state):
        with self._lock:
            self.validate_context()
            state = json_copy(state, label='circle domain checkpoint')
            if type(state) is not dict or set(state) != {'schema_version', 'identity', 'entries'} \
                    or type(state['schema_version']) is not int or state['schema_version'] != 1 or state['identity'] != self._base_identity \
                    or type(state['entries']) is not dict:
                raise ValueError('invalid circle domain checkpoint')
            for candidate, record in state['entries'].items():
                self._validate_record(candidate, record)
            self._entries = copy.deepcopy(state['entries'])
            self._audited = not bool(self._entries)

    def _validate_record(self, candidate, record):
        if type(candidate) is not str or not candidate or type(record) is not dict \
                or set(record) != {'identity', 'status', 'stages', 'eval_count', 'wall_seconds', 'geometry', 'geometry_ref', 'metrics'}:
            raise ValueError('invalid original circle execution record')
        identity, stages = record['identity'], record['stages']
        if type(identity) is not dict or set(identity) != {'candidate_id', 'program_ref', 'context'} \
                or identity['candidate_id'] != candidate or identity['context'] != self._base_identity \
                or type(identity['program_ref']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', identity['program_ref']):
            raise ValueError('circle execution identity differs')
        if type(stages) is not list or len(stages) not in (1, 2) \
                or type(record['eval_count']) is not int or record['eval_count'] != len(stages) or record['status'] not in ('ok', 'failed_to_run', 'timeout'):
            raise ValueError('circle stage record differs')
        total = 0.
        for index, stage in enumerate(stages, 1):
            if type(stage) is not dict or stage.get('stage') != index \
                    or stage.get('status') not in ('ok', 'timeout', 'failed_to_run') \
                    or stage.get('evaluator_ref') != 'sha256:' + EVALUATOR_SHA256 \
                    or stage.get('program_ref') != identity['program_ref']:
                raise ValueError('circle stage source identity differs')
            elapsed = stage.get('wall_seconds')
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError('circle stage duration invalid')
            total += elapsed
            if stage['status'] == 'ok':
                metrics = validate_geometry(stage.get('geometry'))
                if stage.get('metrics') != metrics or stage.get('geometry_ref') != _ref(stage['geometry']):
                    raise ValueError('circle stage geometry or score differs')
        if type(record['wall_seconds']) not in (int, float) or not math.isfinite(record['wall_seconds']) \
                or total != record['wall_seconds'] or stages[-1]['status'] != record['status']:
            raise ValueError('circle execution costs or terminal status differ')
        if len(stages) == 2 and (stages[0]['status'] != 'ok' or stages[0]['metrics']['combined_score'] < .5):
            raise ValueError('circle cascade ran an unauthorized second stage')
        if len(stages) == 1 and stages[0]['status'] == 'ok' and stages[0]['metrics']['combined_score'] >= .5:
            raise ValueError('circle cascade skipped the required second stage')
        if record['status'] == 'ok':
            if record['geometry'] != stages[-1]['geometry'] or record['geometry_ref'] != _ref(record['geometry']) \
                    or record['metrics'] != validate_geometry(record['geometry']):
                raise ValueError('frozen circle geometry differs from original stage')
        elif record['geometry'] is not None or record['geometry_ref'] is not None or record['metrics'] is not None:
            raise ValueError('failed circle run cannot expose valid geometry')

    def restore_evidence(self, records):
        """Check checkpoint content against original Framework evaluation evidence."""
        with self._lock:
            self.validate_context()
            recovered = {}
            for row in records:
                payload = row['payload']
                proposal_data = payload['proposal']
                evidence = decode_evidence({'schema_version': 1, 'evidence': payload['evidence']})
                validate_evidence(evidence)
                proposal = Proposal(Candidate(**proposal_data['candidate']), proposal_data['artifact'])
                result = evidence.eval_result
                if result.contract.binding_source == 'invocation':
                    if proposal.artifact or result.status is not EvalStatus.FAILED_TO_RUN \
                            or result.metrics or result.cost != CostVec() or result.contract.private.data:
                        raise ValueError('invalid pre-evaluation invocation evidence')
                    continue
                if result.contract.binding.split_id != 'dev':
                    continue
                identity = self._identity(proposal)
                expected = binding_for(proposal, EvalRequest(fidelity='dev', split_id='dev'), evaluator_version=self.evaluator_version,
                    evaluation_context=self.evaluation_contexts['dev'])
                if result.contract.binding != expected or evidence.candidate_id != proposal.candidate.id:
                    raise ValueError('original circle evidence identity differs')
                data = result.contract.private.data
                record = data.get('record')
                self._validate_record(proposal.candidate.id, record)
                if record['identity'] != identity or data.get('geometry_ref') != record['geometry_ref'] \
                        or result.status.value != record['status'] \
                        or result.cost.eval_count != record['eval_count'] \
                        or result.cost.wall_seconds != record['wall_seconds']:
                    raise ValueError('original circle evidence differs from execution record')
                expected_metrics = {'dev/score': record['metrics']['combined_score']} if record['status'] == 'ok' else {}
                if result.metrics != expected_metrics or proposal.candidate.id in recovered:
                    raise ValueError('original circle metrics or duplicate evidence differ')
                recovered[proposal.candidate.id] = record
            if recovered != self._entries:
                raise ValueError('circle checkpoint lacks matching original evidence')
            self._audited = True

    def bind_cell_deadline(self, deadline):
        from zoo.circle_packing.cell_deadline import CellDeadline
        if type(deadline) is not CellDeadline or self._cell_deadline is not None or self._entries:
            raise ValueError('circle deadline requires one fresh domain and clock')
        self._cell_deadline = deadline

    def _evaluate_dev(self, proposal):
        with self._lock:
            if not self._audited:
                raise ValueError('original circle evidence must be audited before evaluation')
            identity = self._identity(proposal)
            if identity['candidate_id'] in self._entries:
                raise ValueError('candidate identity already has an original execution')
            clock = {} if self._cell_deadline is None else {'deadline': self._cell_deadline}
            outcome = run_cascade(proposal.artifact, runner=self.runner, workspace=self.workspace,
                                  timeout=self.stage_timeout, **clock)
            record = {'identity': identity, 'status': outcome['status'], 'stages': outcome['stages'],
                      'eval_count': outcome['eval_count'], 'wall_seconds': outcome['wall_seconds'],
                      'geometry': outcome.get('geometry'), 'geometry_ref': outcome.get('geometry_ref'),
                      'metrics': outcome.get('metrics')}
            self.validate_context()
            self._validate_record(identity['candidate_id'], record)
            self._entries[identity['candidate_id']] = copy.deepcopy(record)
            return record

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        bound = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                            evaluation_context=self.evaluation_contexts[request.split_id])
        if request.split_id == 'dev':
            record = await asyncio.to_thread(self._evaluate_dev, proposal)
            status = EvalStatus(record['status'])
            metrics = {'dev/score': record['metrics']['combined_score']} if status is EvalStatus.OK else {}
            cost = CostVec(wall_seconds=record['wall_seconds'], eval_count=record['eval_count'])
            private = {'geometry_ref': record['geometry_ref'], 'record': copy.deepcopy(record)}
            public = {'stage_count': record['eval_count']}
        else:
            started = time.monotonic()
            with self._lock:
                if not self._audited:
                    raise ValueError('original circle evidence must be audited before final validation')
                identity = self._identity(proposal)
                record = self._entries.get(identity['candidate_id'])
                if record is None or record['identity'] != identity:
                    raise ValueError('final candidate identity lacks original circle evidence')
                self._validate_record(identity['candidate_id'], record)
                if record['status'] != 'ok':
                    raise ValueError('failed candidate has no frozen geometry')
                from zoo.circle_packing.reference_final import recalculate_geometry
                verified = recalculate_geometry(record['stages'][-1],
                    expected_program_ref=identity['program_ref'], expected_geometry_ref=record['geometry_ref'],
                    expected_metrics=record['metrics'])
                geometry_metrics = verified['metrics']
                status = EvalStatus.OK
                metrics = {'test/score': geometry_metrics['combined_score']}
                cost = CostVec(wall_seconds=time.monotonic() - started, eval_count=1)
                private = {'geometry_ref': record['geometry_ref']}
                public = {}
        return EvalResult(status, metrics, cost, fidelity=request.fidelity,
                          contract=EvaluationContract(bound, self.measured_cost_units,
                              public=PublicEvaluationData(data=public),
                              private=PrivateEvaluationData(data=private)))
