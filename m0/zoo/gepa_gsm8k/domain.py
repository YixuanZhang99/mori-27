"""Frozen train/validation/test data and metered numeric-answer evaluation."""
import hashlib
import json
import math
from pathlib import Path

from core.composition.evaluation import EvaluationContract, ItemOutcome, binding_for
from core.composition.gepa_recipe import training_plan
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.llm import UsageError
from core.tasks.gsm8k import extract_number


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def digest(value):
    return 'sha256:' + hashlib.sha256(encoded(value).encode()).hexdigest()


class FrozenDataset:
    def __init__(self, rows, *, files=None):
        if type(rows) is not dict or set(rows) != {'train', 'validation', 'test'}:
            raise ValueError('dataset requires separate train, validation and test splits')
        seen = set()
        for split, values in rows.items():
            if type(values) is not list or not values:
                raise ValueError('dataset splits must be nonempty')
            for row in values:
                if type(row) is not dict or set(row) != {'id', 'question', 'answer'} or any(
                        type(row[k]) is not str or not row[k].strip() for k in row) or row['id'] in seen:
                    raise ValueError('dataset requires unique original IDs, questions and answers')
                answer = extract_number(row['answer'])
                if answer is None or not math.isfinite(answer):
                    raise ValueError('dataset answer must be a finite number')
                seen.add(row['id'])
            rows[split] = sorted(values, key=lambda r: r['id'])
        self._encoded = encoded(rows)
        self._files = dict(files or {})
        self.identity = digest(rows)
        self.split_hashes = {split: digest(values) for split, values in rows.items()}

    @classmethod
    def from_rows(cls, rows):
        return cls(json.loads(encoded(rows)))

    @classmethod
    def from_manifest(cls, path):
        path = Path(path).resolve()
        raw = path.read_bytes()
        manifest = json.loads(raw)
        files = {str(path): hashlib.sha256(raw).hexdigest()}
        rows = {}
        for split in ('train', 'validation', 'test'):
            file = path.parent / (split + '.jsonl')
            content = file.read_bytes()
            expected = manifest['splits'][split]
            actual = hashlib.sha256(content).hexdigest()
            if actual != expected['sha256']:
                raise ValueError('frozen dataset hash differs: ' + split)
            values = [json.loads(line) for line in content.splitlines() if line.strip()]
            if len(values) != expected['count'] or values[0]['id'] != expected['first_id'] \
                    or values[-1]['id'] != expected['last_id']:
                raise ValueError('frozen dataset identity differs: ' + split)
            rows[split] = values
            files[str(file)] = actual
        return cls(rows, files=files)

    def validate(self):
        for filename, expected in self._files.items():
            if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != expected:
                raise ValueError('frozen dataset changed: ' + Path(filename).name)

    def rows(self, split):
        self.validate()
        return json.loads(self._encoded)[split]

    def ids(self, split):
        return [r['id'] for r in self.rows(split)]


class GSM8KDomain:
    evaluator_version = 'gepa-gsm8k-numeric-v1'
    measured_cost_units = ('token', 'node', 'eval_count')

    def __init__(self, data, provider, *, seed, minibatch_size, max_proposals):
        self.data, self.provider = data, provider
        self.evaluation_context = data.split_hashes['validation']
        self.evaluation_contexts = {'train': data.split_hashes['train'], 'dev': data.split_hashes['validation'],
                         'final_audit': data.split_hashes['test']}
        self.batches = {}
        for i in range(max_proposals):
            plan = training_plan(data.ids('train'), seed=seed, size=minibatch_size, iteration=i)
            self.batches[plan.request.fidelity] = plan
        self.seed = seed

    def validate_context(self):
        self.data.validate()

    def validate_request(self, request):
        request.validate()
        self.validate_context()
        if request.split_id == 'train':
            plan = self.batches.get(request.fidelity)
            if plan is None or plan.request != request:
                raise ValueError('training request is outside the frozen batch schedule')
        elif request.split_id not in {'dev', 'final_audit'} or request.fidelity != request.split_id \
                or request.seed_set != [self.seed] or request.resume_from is not None:
            raise ValueError('unsupported GSM8K evaluation request')

    def evaluation_context_for(self, request):
        self.validate_request(request)
        return self.evaluation_contexts[request.split_id]

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        split = {'dev': 'validation', 'final_audit': 'test'}.get(request.split_id, request.split_id)
        values = self.data.rows(split)
        if split == 'train':
            indexed = {r['id']: r for r in values}
            values = [indexed[i] for i in self.batches[request.fidelity].item_ids]
        before = self.provider.usage_total
        outcomes, rollouts = [], []
        failure = None
        try:
            for row in values:
                # Only a question and the instruction are model inputs. Gold is local.
                answer = self.provider(encoded({'kind': 'gsm8k_solver', 'instruction': proposal.artifact,
                    'item_id': row['id'], 'question': row['question'],
                    'output_contract': 'Solve the problem and finish with #### followed by the numeric answer.'}))
                prediction, gold = extract_number(answer), extract_number(row['answer'])
                correct = int(prediction is not None and math.isfinite(prediction) and abs(prediction - gold) <= 1e-6)
                outcomes.append(ItemOutcome(row['id'], correct, visibility='public'))
                if split == 'train':
                    rollouts.append({'item_id': row['id'], 'question': row['question'],
                        'rollout': answer, 'gold_answer': row['answer'], 'correct': correct})
        except UsageError:
            raise
        except Exception as error:
            failure = type(error).__name__
        cost = CostVec(tokens_in=self.provider.usage_total - before, eval_count=1)
        prefix = {'train': 'train', 'validation': 'dev', 'test': 'test'}[split]
        return EvalResult(EvalStatus.FAILED_TO_RUN if failure else EvalStatus.OK,
            {} if failure else {prefix + '/score': sum(i.verdict for i in outcomes) / len(values)}, cost,
            fidelity=request.fidelity, text_feedback=('solver failed: ' + failure) if failure else (
                encoded({'training_rollouts': rollouts}) if split == 'train' else 'Numeric-answer evaluation completed.'),
            contract=EvaluationContract(binding_for(proposal, request, evaluator_version=self.evaluator_version,
                evaluation_context=self.evaluation_context_for(request)), self.measured_cost_units,
                items=tuple(outcomes), token_accounting='total_only'))
