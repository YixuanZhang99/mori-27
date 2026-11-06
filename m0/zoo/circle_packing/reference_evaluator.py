"""Offline host fixture stage adapter; never an authority for paid runs."""
import os
from pathlib import Path

from core.x1.store import AppendOnlyStore
from zoo.circle_packing.stage import run_stage
from zoo.mle_bench_lite.composed_domain import SandboxRunner


def _stage(program_path, number):
    root = Path(os.environ['MORI_CIRCLE_REFERENCE_ROOT']).resolve()
    result = run_stage(Path(program_path).read_text(encoding='utf-8'), stage=number,
                       runner=SandboxRunner(), workspace=root / 'stage-work', timeout=60)
    AppendOnlyStore(root / 'fixture-stages.jsonl').append('stage', result)
    if result['status'] != 'ok':
        return {'combined_score': 0.0, 'fixture_stage_failed': 1.0}
    return result['metrics']


def evaluate_stage1(program_path):
    return _stage(program_path, 1)


def evaluate_stage2(program_path):
    return _stage(program_path, 2)


def evaluate(program_path):
    return evaluate_stage1(program_path)
