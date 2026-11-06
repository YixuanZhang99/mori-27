"""Offline host fixture stage adapter; never an authority for paid runs."""
import os
from pathlib import Path

from core.x1.store import AppendOnlyStore
from zoo.circle_packing.stage import run_stage
from zoo.mle_bench_lite.composed_domain import SandboxRunner

_stage_one_ids = {}


def _stage(program_path, number):
    try:
        root = Path(os.environ['MORI_CIRCLE_REFERENCE_ROOT']).resolve()
        program = Path(program_path).read_text(encoding='utf-8')
        if os.environ.get('MORI_CIRCLE_STAGE_BROKER') == '1':
            from types import SimpleNamespace
            from zoo.circle_packing.host_transport import HostEvaluationClient
            prior = _stage_one_ids.get(program_path) if number == 2 else None
            request_id, result = HostEvaluationClient(SimpleNamespace(name='fixture')).evaluate(
                program, stage=number, prior_id=prior)
            if number == 1:
                _stage_one_ids[program_path] = request_id
        else:
            result = run_stage(program, stage=number, runner=SandboxRunner(),
                               workspace=root / 'stage-work', timeout=60)
        AppendOnlyStore(root / 'fixture-stages.jsonl').append('stage', result)
        if result['status'] != 'ok':
            return {'combined_score': 0.0, 'fixture_stage_failed': 1.0}
        return result['metrics']
    except Exception:
        # The pinned upstream evaluator otherwise retains the first-stage
        # score after a second-stage exception. Never promote that score when
        # the stage outcome or its receipt is unresolved.
        try:
            root = Path(os.environ['MORI_CIRCLE_REFERENCE_ROOT']).resolve()
            AppendOnlyStore(root / 'fixture-unresolved.jsonl').append('unresolved', {'stage': number})
        except Exception:
            from zoo.circle_packing.host_transport import StageEvidenceFailure
            raise StageEvidenceFailure('cannot record unresolved stage') from None
        return {'combined_score': 0.0, 'fixture_unresolved': 1.0}


def evaluate_stage1(program_path):
    return _stage(program_path, 1)


def evaluate_stage2(program_path):
    return _stage(program_path, 2)


def evaluate(program_path):
    return evaluate_stage1(program_path)
