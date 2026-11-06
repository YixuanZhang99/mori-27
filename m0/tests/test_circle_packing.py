"""Host-side geometry is independent of candidate-reported scores."""
import json
import math

import pytest


def grid():
    centers = [[(i % 6 + .5) / 6, (i // 6 + .5) / 6] for i in range(26)]
    return {'centers': centers, 'radii': [0.07] * 26}


def test_geometry_recomputes_valid_sum_and_stage_score():
    from zoo.circle_packing.geometry import validate_geometry
    result = validate_geometry(grid())
    assert result['validity'] == 1
    assert result['sum_radii'] == pytest.approx(1.82)
    assert result['combined_score'] == pytest.approx(1.82 / 2.635)
    assert result['combined_score'] > .5


@pytest.mark.parametrize('problem', ['shape', 'nonfinite', 'negative', 'overlap', 'outside', 'boolean', 'forged', 'huge'])
def test_geometry_rejects_invalid_or_forged_candidate_data(problem):
    from zoo.circle_packing.geometry import validate_geometry
    geometry = grid()
    if problem == 'shape': geometry['centers'].pop()
    if problem == 'nonfinite': geometry['centers'][0][0] = math.nan
    if problem == 'negative': geometry['radii'][0] = -.01
    if problem == 'overlap': geometry['centers'][1] = geometry['centers'][0][:]
    if problem == 'outside': geometry['centers'][0][0] = 0
    if problem == 'boolean': geometry['radii'][0] = True
    if problem == 'forged': geometry['combined_score'] = 1e20
    if problem == 'huge': geometry['centers'][0][0] = 10**1000
    with pytest.raises(ValueError):
        validate_geometry(geometry)


def test_geometry_artifact_rejects_symlinks_oversize_and_duplicate_json_keys(tmp_path):
    from zoo.circle_packing.geometry import read_geometry
    target = tmp_path / 'outside.json'
    target.write_text(json.dumps(grid()))
    link = tmp_path / 'geometry.json'
    link.symlink_to(target)
    with pytest.raises(ValueError): read_geometry(link)
    link.unlink()
    link.write_bytes(b' ' * 65537)
    with pytest.raises(ValueError): read_geometry(link)
    link.write_text('{"centers": [], "centers": [], "radii": []}')
    with pytest.raises(ValueError): read_geometry(link)
    link.write_text(json.dumps(grid(), allow_nan=False))
    assert read_geometry(link)['sum_radii'] == pytest.approx(1.82)


def test_geometry_matches_pinned_evaluator_on_valid_and_overlapping_grid():
    import importlib.util
    from pathlib import Path
    import numpy as np
    from zoo.circle_packing.geometry import validate_geometry
    source = Path(__file__).resolve().parents[1] / 'vendor/openevolve/examples/circle_packing/evaluator.py'
    spec = importlib.util.spec_from_file_location('pinned_circle_evaluator_fixture', source)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    geometry = grid()
    assert evaluator.validate_packing(np.asarray(geometry['centers']), np.asarray(geometry['radii']))
    assert validate_geometry(geometry)['combined_score'] == pytest.approx(sum(geometry['radii']) / evaluator.TARGET_VALUE)
    geometry['centers'][1] = geometry['centers'][0][:]
    assert not evaluator.validate_packing(np.asarray(geometry['centers']), np.asarray(geometry['radii']))
    with pytest.raises(ValueError):
        validate_geometry(geometry)
