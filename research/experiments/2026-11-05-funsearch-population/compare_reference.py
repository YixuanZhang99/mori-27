"""Compare bounded selection calculations against a hash-checked upstream file."""
import ast
import hashlib
import json
from pathlib import Path
import random
import sys
import numpy as np
import scipy.special

from core.funsearch_population import FunSearchPopulation

source = Path(sys.argv[1]).read_bytes()
expected_hash = 'b2bef312d04861f467f304f65788efe959f0493818976b052c46b4703151affc'
if hashlib.sha256(source).hexdigest() != expected_hash:
    raise ValueError('reference source hash differs')
tree = ast.parse(source)
names = {'_softmax', '_reduce_score', '_get_signature'}
functions = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in names]
module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *functions], type_ignores=[])
namespace = {'np': np, 'scipy': scipy}
exec(compile(ast.fix_missing_locations(module), '<pinned-reference>', 'exec'), namespace)
rng = random.Random(3751)
maximum_error = 0.0
for trial in range(200):
    period = 20
    initial = rng.uniform(.2, 3)
    p = FunSearchPopulation(case_ids=['a', 'b'], islands=2, seed=trial,
                            prompt_size=2, temperature=initial, temperature_period=period)
    rows = []
    for j in range(rng.randint(2, 8)):
        scores = {'a': rng.randint(-5, 5) / 3, 'b': rng.randint(-5, 5) / 3}
        rows.append(scores)
        p.register(str(j), 'x' * rng.randint(1, 120), scores, island=0, epoch=0)
    clusters = p.inspect_island(0)['clusters']
    unique = []
    for scores in rows:
        sig = namespace['_get_signature'](scores)
        if sig not in unique:
            unique.append(sig)
        assert namespace['_reduce_score'](scores) == scores['b']
    assert [tuple(c['signature']) for c in clusters] == unique
    temp = initial * (1 - len(rows) % period / period)
    reference = namespace['_softmax'](np.array([s[-1] for s in unique]), temp)
    actual = p.cluster_probabilities(0)
    maximum_error = max(maximum_error, max(abs(float(x) - y) for x, y in zip(reference, actual)))
    for cluster in clusters:
        lengths = np.array([p.candidate(c)['program_length'] for c in cluster['candidates']])
        normalized = (lengths - min(lengths)) / (max(lengths) + 1e-6)
        reference = namespace['_softmax'](-normalized, 1.0)
        actual = p.program_probabilities(0, cluster['signature'])
        maximum_error = max(maximum_error, max(abs(float(x) - y) for x, y in zip(reference, actual)))
if maximum_error > 1e-12:
    raise ValueError('probability differs from reference')
print(json.dumps({'reference_commit':'cc53f274237d7ab05c19df939edbc1f9616a7c19',
                  'reference_sha256':expected_hash,'random_fixtures':200,
                  'maximum_absolute_probability_error':maximum_error,
                  'scope':'signature, reduction and probability calculations only; not RNG parity or benchmark'}, indent=2))
