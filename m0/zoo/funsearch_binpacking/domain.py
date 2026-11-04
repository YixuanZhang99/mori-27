"""Experimental, data-bound OR3 development domain; no held-out evaluation."""
import asyncio
import hashlib
import json
import math
import re
from pathlib import Path

from core.composition.evaluation import EvaluationContract, ItemOutcome, binding_for
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.executor.seccomp import build_seccomp_policy
from core.tasks.funsearch_binpacking import score_partition
from core.tasks.funsearch_priority_sandbox import SandboxedPriority


class OR3DevDomain:
    metric = 'dev/score'
    measured_cost_units = ('token', 'node', 'eval_count')

    def __init__(self, path, *, expected_sha256, template, timeout):
        if (type(expected_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256) or
                type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or
                type(template) is not str):
            raise ValueError('frozen dataset, template and finite timeout are required')
        self.path, self.expected_sha256 = Path(path).absolute(), expected_sha256
        self.template, self.timeout = template, float(timeout)
        configuration = {'protocol': 'or3-sandbox-priority-dev-v1', 'timeout': self.timeout,
            'template_sha256': hashlib.sha256(template.encode()).hexdigest(),
            'seccomp_sha256': build_seccomp_policy()['filter_sha256']}
        self.evaluator_version = 'or3-dev-v1:' + hashlib.sha256(
            json.dumps(configuration, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.evaluation_context = 'sha256:' + expected_sha256
        data = json.loads(self._read_dataset())
        if type(data) is not dict or len(data) != 10 or any(type(key) is not str or not key.strip() for key in data):
            raise ValueError('OR3 dataset requires ten named development cases')
        self.funsearch_binding = {'case_ids': sorted(data), 'metric': 'score',
                                  'template_ref': 'sha256:' + hashlib.sha256(template.encode()).hexdigest()}

    def validate_context(self):
        self._read_dataset()

    def _read_dataset(self):
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError('OR3 dataset differs from its frozen digest')
        raw = self.path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.expected_sha256:
            raise ValueError('OR3 dataset differs from its frozen digest')
        return raw

    def validate_request(self, request):
        request.validate()
        if request.split_id != 'dev' or request.fidelity != 'dev' or request.seed_set is not None or request.resume_from is not None:
            raise ValueError('only unseeded development evaluation is supported')
        self.validate_context()

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        data = json.loads(self._read_dataset())
        bound = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                            evaluation_context=self.evaluation_context)
        timeout = min(self.timeout, request.time_limit) if request.time_limit else self.timeout

        def run():
            with SandboxedPriority(self.template, proposal.artifact, timeout=timeout) as priority:
                return score_partition(data, priority)

        try:
            result = await asyncio.to_thread(run)
        except (ValueError, OSError, TimeoutError) as error:
            return EvalResult(EvalStatus.FAILED_TO_RUN, cost=CostVec(eval_count=1), fidelity='dev',
                text_feedback='Sandboxed OR3 candidate failed: ' + type(error).__name__,
                contract=EvaluationContract(bound, self.measured_cost_units))
        self.validate_context()
        items = tuple(ItemOutcome(key, metrics={'score': score}, visibility='public')
                      for key, score in result['case_scores'].items())
        return EvalResult(EvalStatus.OK, {'dev/score': result['mean_score']}, CostVec(eval_count=1),
            fidelity='dev', contract=EvaluationContract(bound, self.measured_cost_units, items=items))
