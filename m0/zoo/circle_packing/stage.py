"""Execute one pinned evaluator stage in the existing isolated process runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from zoo.circle_packing.geometry import read_geometry_payload, validate_geometry

_EVALUATOR = Path(__file__).resolve().parents[2] / 'vendor/openevolve/examples/circle_packing/evaluator.py'
EVALUATOR_SHA256 = '7fed1c036325e78c45c5390cffa56f4da82a39527721bbdc7c13d55430e7afa4'

# This wrapper and evaluator are mounted read-only. All pickle exchange remains
# within the sandbox. The host reads bounded JSON and recomputes every metric.
_WRAPPER = '''import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("circle_evaluator", "data/evaluator.py")
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)
original = evaluator.run_with_timeout
captured = []
def record(*args, **kwargs):
    centers, radii, total = original(*args, **kwargs)
    captured.append({"centers": centers.tolist() if hasattr(centers, "tolist") else centers,
                     "radii": radii.tolist() if hasattr(radii, "tolist") else radii})
    return centers, radii, total
evaluator.run_with_timeout = record
result = getattr(evaluator, "evaluate_stage" + sys.argv[1])("data/candidate.py")
if len(captured) != 1 or result.get("validity") != 1.0:
    raise RuntimeError("upstream evaluator rejected or did not produce geometry")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
fd = os.open("geometry.json", flags, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as out:
    json.dump(captured[0], out, allow_nan=False, separators=(",", ":"))
'''


def run_stage(program, *, stage, runner, workspace, timeout=60):
    """Execute one physical stage, retaining measured cost even on failure."""
    if type(program) is not str or not program.strip() or len(program.encode('utf-8')) > 1024 * 1024:
        raise ValueError('candidate program must be bounded nonempty UTF-8 text')
    if type(stage) is not int or stage not in (1, 2):
        raise ValueError('circle evaluator stage must be 1 or 2')
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ValueError('stage timeout must be positive and at most 60 seconds')
    evaluator = _EVALUATOR.read_bytes()
    if hashlib.sha256(evaluator).hexdigest() != EVALUATOR_SHA256:
        raise ValueError('pinned circle evaluator source changed')
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    if hasattr(runner, 'validate_paths'):
        runner.validate_paths(root)
    with tempfile.TemporaryDirectory(prefix='circle-stage-', dir=root) as directory:
        path = Path(directory)
        data = path / 'data'
        data.mkdir()
        (data / 'evaluator.py').write_bytes(evaluator)
        (data / 'candidate.py').write_text(program, encoding='utf-8')
        # SandboxRunner invokes program.py with no arguments: freeze stage here.
        (path / 'program.py').write_text('import sys\nsys.argv = [sys.argv[0], ' + repr(str(stage)) + ']\n' + _WRAPPER)
        execution = runner.execute(path, timeout=timeout)
        result = {'status': 'timeout' if execution['timed_out'] else 'failed_to_run',
                  'wall_seconds': execution['wall_seconds'], 'stage': stage,
                  'evaluator_ref': 'sha256:' + EVALUATOR_SHA256,
                  'program_ref': 'sha256:' + hashlib.sha256(program.encode('utf-8')).hexdigest()}
        if execution['timed_out'] or execution['returncode'] != 0:
            return result
        try:
            geometry = read_geometry_payload(path / 'geometry.json')
            metrics = validate_geometry(geometry)
        except (ValueError, OSError):
            return result
        encoded = json.dumps(geometry, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        result.update(status='ok', geometry=geometry, metrics=metrics,
                      geometry_ref='sha256:' + hashlib.sha256(encoded.encode('utf-8')).hexdigest())
        return result


def run_cascade(program, *, runner, workspace, timeout=60):
    """Run the pinned absolute .5 threshold, measuring each physical stage."""
    first = run_stage(program, stage=1, runner=runner, workspace=workspace, timeout=timeout)
    stages = [first]
    if first['status'] == 'ok' and first['metrics']['combined_score'] >= .5:
        stages.append(run_stage(program, stage=2, runner=runner, workspace=workspace, timeout=timeout))
    last = stages[-1]
    result = {'status': last['status'], 'stages': stages, 'eval_count': len(stages),
              'wall_seconds': sum(row['wall_seconds'] for row in stages)}
    if last['status'] == 'ok':
        result.update(metrics=last['metrics'], geometry=last['geometry'],
                      geometry_ref=last.get('geometry_ref'))
    return result
